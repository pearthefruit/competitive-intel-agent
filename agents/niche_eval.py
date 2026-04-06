"""Niche evaluation — lightweight financial scanning and market aggregation.

Scans discovered companies for financial data (revenue, market cap, employees,
growth) using Yahoo Finance + SEC EDGAR. No LLM calls for public companies.
Aggregates into niche-level metrics and charts data.
"""

import json
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from agents.metrics import _format_currency
from scraper.stock_data import lookup_ticker, get_stock_data
from scraper.sec_edgar import lookup_cik, get_company_facts, extract_financials
from agents.metrics import compute_financial_metrics


# ---------------------------------------------------------------------------
# Per-company lightweight scan
# ---------------------------------------------------------------------------

def lightweight_financial_scan(company_name, description=None, progress_cb=None):
    """Collect lightweight financial data for a single company. No report generation.

    Tries Yahoo Finance + SEC EDGAR for public companies. Falls back to a single
    FAST_CHAIN LLM call for private companies where nothing is found.

    Returns dict with company snapshot data.
    """
    result = {
        "company_name": company_name,
        "ticker": None,
        "is_public": False,
        "sector": None,
        "industry": None,
        "revenue": None,
        "revenue_formatted": None,
        "revenue_yoy_growth": None,
        "market_cap": None,
        "market_cap_formatted": None,
        "employee_count": None,
        "operating_margin": None,
        "hq_country": None,
        "data_quality": "low",
        "sources": [],
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }

    # --- Tier 1: Yahoo Finance (ticker lookup + market data) ---
    ticker = None
    try:
        ticker = lookup_ticker(company_name)
    except Exception as e:
        print(f"[niche_eval] Ticker lookup failed for {company_name}: {e}")

    if ticker:
        result["ticker"] = ticker
        result["is_public"] = True
        result["sources"].append("yahoo_finance")

        try:
            stock_data = get_stock_data(ticker)
            if stock_data:
                result["market_cap"] = stock_data.get("market_cap")
                if result["market_cap"]:
                    result["market_cap_formatted"] = _format_currency(result["market_cap"])
                result["sector"] = stock_data.get("sector")
                result["industry"] = stock_data.get("industry")
                result["hq_country"] = stock_data.get("country")
                result["employee_count"] = stock_data.get("employee_count")
                result["data_quality"] = "medium"
        except Exception as e:
            print(f"[niche_eval] Stock data failed for {ticker}: {e}")

    # --- Tier 2: SEC EDGAR (revenue, financials — US public companies) ---
    if ticker:
        try:
            cik_result = lookup_cik(company_name)
            cik = None
            if isinstance(cik_result, dict):
                cik = cik_result.get("cik")
            elif isinstance(cik_result, list) and cik_result:
                cik = cik_result[0].get("cik")

            if cik:
                facts = get_company_facts(cik)
                if facts:
                    financials = extract_financials(facts)
                    if financials:
                        metrics = compute_financial_metrics(financials)
                        if metrics.get("revenue_latest"):
                            result["revenue"] = metrics["revenue_latest"]
                            result["revenue_formatted"] = metrics.get("revenue_formatted")
                            result["revenue_yoy_growth"] = metrics.get("revenue_yoy_growth")
                            result["operating_margin"] = metrics.get("operating_margin")
                            result["data_quality"] = "high"
                            result["sources"].append("sec_edgar")
                        # Employee count from EDGAR if Yahoo didn't have it
                        if not result["employee_count"] and metrics.get("employee_count"):
                            result["employee_count"] = metrics["employee_count"]
        except Exception as e:
            print(f"[niche_eval] SEC EDGAR failed for {company_name}: {e}")

    # --- Tier 3: LLM fallback for private companies ---
    if not ticker and result["data_quality"] == "low":
        try:
            estimated = _estimate_private_company(company_name, description)
            if estimated:
                result["revenue"] = estimated.get("estimated_revenue")
                if result["revenue"]:
                    result["revenue_formatted"] = _format_currency(result["revenue"])
                result["employee_count"] = estimated.get("estimated_employees")
                result["hq_country"] = estimated.get("hq_country")
                result["sector"] = estimated.get("sector")
                result["industry"] = estimated.get("industry")
                result["sources"].append("llm_estimate")
        except Exception as e:
            print(f"[niche_eval] LLM estimate failed for {company_name}: {e}")

    return result


def _estimate_private_company(company_name, description=None):
    """Use a single FAST_CHAIN LLM call to estimate private company financials."""
    from agents.llm import generate_json, FAST_CHAIN
    from prompts.niche_eval import build_private_company_prompt

    prompt = build_private_company_prompt(company_name, description)
    return generate_json(prompt, timeout=15, chain=FAST_CHAIN)


# ---------------------------------------------------------------------------
# Batch scan
# ---------------------------------------------------------------------------

def scan_niche_financials(companies, progress_cb=None):
    """Scan all discovered companies in parallel for financial data.

    Args:
        companies: list of dicts with at least {name, description} from discovery
        progress_cb: callback(event_type, event_data) for SSE streaming

    Returns list of snapshot dicts from lightweight_financial_scan().
    """
    total = len(companies)
    if progress_cb:
        progress_cb("niche_scan_start", {"total": total})

    results = []

    def _scan_one(idx, company):
        name = company.get("name", "Unknown")
        desc = company.get("description", "")
        if progress_cb:
            progress_cb("niche_scan_progress", {
                "company": name, "index": idx + 1, "total": total,
                "status": "scanning",
            })
        try:
            snapshot = lightweight_financial_scan(name, description=desc)
            if progress_cb:
                progress_cb("niche_scan_progress", {
                    "company": name, "index": idx + 1, "total": total,
                    "status": "done",
                    "snapshot": {
                        "revenue_formatted": snapshot.get("revenue_formatted"),
                        "market_cap_formatted": snapshot.get("market_cap_formatted"),
                        "is_public": snapshot.get("is_public"),
                        "data_quality": snapshot.get("data_quality"),
                    },
                })
            return snapshot
        except Exception as e:
            print(f"[niche_eval] Scan failed for {name}: {e}")
            traceback.print_exc()
            if progress_cb:
                progress_cb("niche_scan_progress", {
                    "company": name, "index": idx + 1, "total": total,
                    "status": "error", "error": str(e),
                })
            return {
                "company_name": name,
                "data_quality": "none",
                "sources": [],
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            }

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_scan_one, i, c): i
            for i, c in enumerate(companies)
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                print(f"[niche_eval] Future error: {e}")

    return results


# ---------------------------------------------------------------------------
# Niche-level aggregation
# ---------------------------------------------------------------------------

def compute_niche_aggregates(scan_results):
    """Compute niche-level metrics from per-company scan data.

    Handles missing data: each metric only includes companies with actual values.
    Reports coverage counts so the frontend knows data completeness.
    """
    with_revenue = [s for s in scan_results if s.get("revenue")]
    with_market_cap = [s for s in scan_results if s.get("market_cap")]
    with_employees = [s for s in scan_results if s.get("employee_count")]
    with_growth = [s for s in scan_results if s.get("revenue_yoy_growth") is not None]

    # --- Revenue buckets ---
    REVENUE_BUCKETS = [
        ("<$5M", 0, 5_000_000),
        ("$5M-$25M", 5_000_000, 25_000_000),
        ("$25M-$50M", 25_000_000, 50_000_000),
        ("$50M-$100M", 50_000_000, 100_000_000),
        ("$100M-$500M", 100_000_000, 500_000_000),
        ("$500M-$1B", 500_000_000, 1_000_000_000),
        ("$1B+", 1_000_000_000, float("inf")),
    ]
    revenue_buckets = []
    for label, lo, hi in REVENUE_BUCKETS:
        companies_in = [s["company_name"] for s in with_revenue if lo <= s["revenue"] < hi]
        revenue_buckets.append({"label": label, "count": len(companies_in), "companies": companies_in})

    # --- Employee buckets ---
    EMPLOYEE_BUCKETS = [
        ("<50", 0, 50),
        ("50-500", 50, 500),
        ("500-5K", 500, 5_000),
        ("5K+", 5_000, float("inf")),
    ]
    employee_buckets = []
    for label, lo, hi in EMPLOYEE_BUCKETS:
        companies_in = [s["company_name"] for s in with_employees if lo <= s["employee_count"] < hi]
        employee_buckets.append({"label": label, "count": len(companies_in), "companies": companies_in})

    # --- Growth buckets ---
    GROWTH_BUCKETS = [
        ("Declining (<0%)", -float("inf"), 0),
        ("Stable (0-10%)", 0, 10),
        ("Growing (10-25%)", 10, 25),
        ("Rapid (25%+)", 25, float("inf")),
    ]
    growth_buckets = []
    for label, lo, hi in GROWTH_BUCKETS:
        companies_in = [s["company_name"] for s in with_growth if lo <= s["revenue_yoy_growth"] < hi]
        growth_buckets.append({"label": label, "count": len(companies_in), "companies": companies_in})

    # --- Market share (among companies with known revenue) ---
    total_rev = sum(s["revenue"] for s in with_revenue) if with_revenue else 0
    market_share = sorted(
        [{
            "company": s["company_name"],
            "revenue": s["revenue"],
            "revenue_formatted": s.get("revenue_formatted") or _format_currency(s["revenue"]),
            "share_pct": round(s["revenue"] / total_rev * 100, 1) if total_rev else 0,
        } for s in with_revenue],
        key=lambda x: x["revenue"],
        reverse=True,
    ) if with_revenue else []

    # --- Geography ---
    geography = {}
    for s in scan_results:
        country = s.get("hq_country") or "Unknown"
        geography[country] = geography.get(country, 0) + 1

    # --- Sectors ---
    sectors = {}
    for s in scan_results:
        sector = s.get("sector") or "Unknown"
        sectors[sector] = sectors.get(sector, 0) + 1

    # --- Aggregate stats ---
    revenues = sorted([s["revenue"] for s in with_revenue])
    median_rev = revenues[len(revenues) // 2] if revenues else None
    growth_vals = [s["revenue_yoy_growth"] for s in with_growth]
    avg_growth = round(sum(growth_vals) / len(growth_vals), 1) if growth_vals else None
    median_growth = sorted(growth_vals)[len(growth_vals) // 2] if growth_vals else None

    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "company_count": len(scan_results),
        "data_coverage": {
            "revenue_known": len(with_revenue),
            "market_cap_known": len(with_market_cap),
            "employees_known": len(with_employees),
            "growth_known": len(with_growth),
        },
        "aggregate": {
            "total_revenue": total_rev if with_revenue else None,
            "total_revenue_formatted": _format_currency(total_rev) if with_revenue else None,
            "median_revenue": median_rev,
            "median_revenue_formatted": _format_currency(median_rev) if median_rev else None,
            "total_market_cap": sum(s["market_cap"] for s in with_market_cap) if with_market_cap else None,
            "total_market_cap_formatted": _format_currency(sum(s["market_cap"] for s in with_market_cap)) if with_market_cap else None,
            "total_employees": sum(s["employee_count"] for s in with_employees) if with_employees else None,
            "avg_revenue_growth": avg_growth,
            "median_revenue_growth": median_growth,
        },
        "distributions": {
            "revenue_buckets": revenue_buckets,
            "employee_buckets": employee_buckets,
            "growth_buckets": growth_buckets,
        },
        "market_share": market_share,
        "geography": geography,
        "sectors": sectors,
        "public_vs_private": {
            "public": sum(1 for s in scan_results if s.get("is_public")),
            "private": sum(1 for s in scan_results if not s.get("is_public")),
        },
        "per_company": [
            {
                "name": s.get("company_name", "Unknown"),
                "revenue": s.get("revenue"),
                "revenue_formatted": s.get("revenue_formatted"),
                "market_cap": s.get("market_cap"),
                "market_cap_formatted": s.get("market_cap_formatted"),
                "employees": s.get("employee_count"),
                "growth": s.get("revenue_yoy_growth"),
                "is_public": s.get("is_public", False),
                "data_quality": s.get("data_quality", "low"),
                "sector": s.get("sector"),
                "hq_country": s.get("hq_country"),
            }
            for s in scan_results
        ],
    }
