"""Pre-computed metrics layer — deterministic math on structured data. Zero LLM calls.

Computes financial ratios, hiring metrics, patent velocity, and cross-analysis
derived signals from data that already exists in the pipeline.
"""

import json
import math


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_div(a, b):
    """Safe division returning None if b is zero/None."""
    if not b or b == 0:
        return None
    return a / b


def _pct(a, b):
    """Percentage of a/b, returning None if invalid."""
    r = _safe_div(a, b)
    return round(r * 100, 1) if r is not None else None


def _format_currency(value):
    """Format a number into human-readable currency (e.g. $8.4B)."""
    if value is None:
        return None
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}${abs_val / 1e12:.1f}T"
    if abs_val >= 1e9:
        return f"{sign}${abs_val / 1e9:.1f}B"
    if abs_val >= 1e6:
        return f"{sign}${abs_val / 1e6:.0f}M"
    if abs_val >= 1e3:
        return f"{sign}${abs_val / 1e3:.0f}K"
    return f"{sign}${abs_val:.0f}"


def _cagr(start_val, end_val, years):
    """Compound annual growth rate."""
    if not start_val or start_val <= 0 or not end_val or end_val <= 0 or years <= 0:
        return None
    return round(((end_val / start_val) ** (1 / years) - 1) * 100, 1)


def _get_fy_values(entries):
    """Extract full-year (FY) values from XBRL entries, sorted newest first.

    Returns list of (fiscal_year, value) tuples.
    """
    fy_entries = [e for e in entries if e.get("fiscal_period") == "FY"]
    fy_entries.sort(key=lambda x: x.get("fiscal_year", 0), reverse=True)
    return [(e["fiscal_year"], e["value"]) for e in fy_entries if e.get("value") is not None]


def _yoy_growth_from_fy(fy_values):
    """Compute YoY growth from [(year, value), ...] sorted newest first."""
    if len(fy_values) < 2:
        return None
    curr = fy_values[0][1]
    prev = fy_values[1][1]
    if not prev or prev == 0:
        return None
    return round((curr - prev) / abs(prev) * 100, 1)


def _trend_from_series(values):
    """Determine trend direction from a list of values (newest first).

    Returns 'increasing', 'stable', or 'decreasing'.
    """
    if len(values) < 2:
        return None
    recent = values[0]
    oldest = values[-1]
    if not oldest or oldest == 0:
        return None
    change_pct = (recent - oldest) / abs(oldest) * 100
    if change_pct > 5:
        return "increasing"
    elif change_pct < -5:
        return "decreasing"
    return "stable"


# ---------------------------------------------------------------------------
# Financial Metrics
# ---------------------------------------------------------------------------

def compute_financial_metrics(financials_dict, stock_data=None, extended=None):
    """Compute financial ratios from SEC EDGAR XBRL data + Yahoo Finance.

    Args:
        financials_dict: from extract_financials() — {metric: [{period, value, ...}, ...]}
        stock_data: from get_stock_data() — {price, market_cap, ...} or None
        extended: from get_extended_financials() — {income_stmt, cash_flow, ...} or None

    Returns dict of computed metrics with both raw values and formatted strings.
    """
    m = {}

    # --- Revenue ---
    rev_fy = _get_fy_values(financials_dict.get("revenue", []))
    if rev_fy:
        m["revenue_latest"] = rev_fy[0][1]
        m["revenue_latest_year"] = rev_fy[0][0]
        m["revenue_formatted"] = _format_currency(rev_fy[0][1])
        m["revenue_yoy_growth"] = _yoy_growth_from_fy(rev_fy)
        if len(rev_fy) >= 4:
            m["revenue_cagr_3yr"] = _cagr(rev_fy[3][1], rev_fy[0][1], 3)
        if len(rev_fy) >= 6:
            m["revenue_cagr_5yr"] = _cagr(rev_fy[5][1], rev_fy[0][1], 5)
        m["revenue_trend"] = _trend_from_series([v for _, v in rev_fy[:5]])

    # --- R&D Expense ---
    rd_fy = _get_fy_values(financials_dict.get("rd_expense", []))
    if rd_fy:
        m["rd_expense_latest"] = rd_fy[0][1]
        m["rd_expense_formatted"] = _format_currency(rd_fy[0][1])
        if rev_fy:
            m["rd_intensity"] = _pct(rd_fy[0][1], rev_fy[0][1])
        # R&D trend
        rd_intensities = []
        for rd_yr, rd_val in rd_fy[:5]:
            matching_rev = next((v for y, v in rev_fy if y == rd_yr), None)
            if matching_rev:
                rd_intensities.append(_pct(rd_val, matching_rev))
        if len(rd_intensities) >= 2:
            m["rd_intensity_trend"] = _trend_from_series([x for x in rd_intensities if x is not None])

    # --- Profitability ---
    oi_fy = _get_fy_values(financials_dict.get("operating_income", []))
    if oi_fy and rev_fy:
        m["operating_margin"] = _pct(oi_fy[0][1], rev_fy[0][1])

    ni_fy = _get_fy_values(financials_dict.get("net_income", []))
    if ni_fy and rev_fy:
        m["net_margin"] = _pct(ni_fy[0][1], rev_fy[0][1])

    gp_fy = _get_fy_values(financials_dict.get("gross_profit", []))
    if gp_fy and rev_fy:
        m["gross_margin"] = _pct(gp_fy[0][1], rev_fy[0][1])

    # --- Balance Sheet ---
    cash_fy = _get_fy_values(financials_dict.get("cash", []))
    if cash_fy:
        m["cash_position"] = cash_fy[0][1]
        m["cash_formatted"] = _format_currency(cash_fy[0][1])

    assets_fy = _get_fy_values(financials_dict.get("total_assets", []))
    liab_fy = _get_fy_values(financials_dict.get("total_liabilities", []))
    equity_fy = _get_fy_values(financials_dict.get("stockholders_equity", []))
    if liab_fy and equity_fy and equity_fy[0][1]:
        m["debt_to_equity"] = round(liab_fy[0][1] / equity_fy[0][1], 2)

    # --- Employees + Productivity ---
    emp_fy = _get_fy_values(financials_dict.get("employees", []))
    if emp_fy:
        m["employee_count"] = emp_fy[0][1]
        if rev_fy:
            rev_per_emp = _safe_div(rev_fy[0][1], emp_fy[0][1])
            if rev_per_emp:
                m["revenue_per_employee"] = round(rev_per_emp)
                m["revenue_per_employee_formatted"] = _format_currency(rev_per_emp)

    # --- FCF from Yahoo Finance extended data ---
    if extended:
        try:
            import pandas as pd
            cf = extended.get("cash_flow")
            if cf is not None and not cf.empty:
                # Find operating cash flow and capex rows
                for label in ["Operating Cash Flow", "Total Cash From Operating Activities",
                              "Cash Flow From Continuing Operating Activities"]:
                    if label in cf.index:
                        ocf_row = cf.loc[label]
                        latest_ocf = ocf_row.iloc[0]
                        if pd.notna(latest_ocf):
                            m["operating_cash_flow"] = int(latest_ocf)
                            m["operating_cash_flow_formatted"] = _format_currency(int(latest_ocf))
                        break

                for label in ["Capital Expenditure", "Capital Expenditures"]:
                    if label in cf.index:
                        capex_row = cf.loc[label]
                        latest_capex = capex_row.iloc[0]
                        if pd.notna(latest_capex) and m.get("operating_cash_flow"):
                            fcf = m["operating_cash_flow"] + int(latest_capex)  # capex is negative
                            m["fcf_latest"] = fcf
                            m["fcf_formatted"] = _format_currency(fcf)
                            if rev_fy:
                                m["fcf_margin"] = _pct(fcf, rev_fy[0][1])
                        break

            # --- Analyst consensus ---
            targets = extended.get("price_targets")
            if isinstance(targets, dict) and targets.get("mean"):
                m["analyst_target_mean"] = targets["mean"]
                m["analyst_target_high"] = targets.get("high")
                m["analyst_target_low"] = targets.get("low")
                m["analyst_count"] = targets.get("numberOfAnalysts")
                if stock_data and stock_data.get("price"):
                    upside = _pct(targets["mean"] - stock_data["price"], stock_data["price"])
                    m["analyst_upside_pct"] = upside

        except Exception as e:
            print(f"[metrics] Warning: extended data processing failed: {e}")

    # --- Market data from stock_data ---
    if stock_data:
        m["market_cap"] = stock_data.get("market_cap")
        m["market_cap_formatted"] = _format_currency(stock_data.get("market_cap"))
        m["pe_ratio"] = stock_data.get("pe_ratio")
        m["forward_pe"] = stock_data.get("forward_pe")
        m["ev_to_ebitda"] = stock_data.get("ev_to_ebitda")
        m["enterprise_value"] = stock_data.get("enterprise_value")

    # Strip None values
    return {k: v for k, v in m.items() if v is not None}


# ---------------------------------------------------------------------------
# Hiring Metrics
# ---------------------------------------------------------------------------

def compute_hiring_metrics(hiring_stats, snapshots=None):
    """Compute hiring-derived metrics from classified job data.

    Args:
        hiring_stats: from compute_hiring_stats() or None
        snapshots: from get_hiring_snapshots() — list of historical snapshots

    Returns dict of computed metrics.
    """
    if not hiring_stats:
        return {}

    m = {}
    total = hiring_stats.get("total_roles", 0)
    if total == 0:
        return {}

    m["total_roles"] = total
    dept_counts = hiring_stats.get("dept_counts", {})
    seniority_counts = hiring_stats.get("seniority_counts", {})

    # --- Engineering concentration ---
    eng_count = dept_counts.get("Engineering", 0)
    m["engineering_ratio"] = _pct(eng_count, total)

    # --- AI/ML intensity ---
    ai_count = hiring_stats.get("ai_ml_role_count", 0)
    m["ai_ml_role_count"] = ai_count
    m["ai_ml_intensity"] = _pct(ai_count, eng_count) if eng_count else _pct(ai_count, total)

    # --- Seniority balance ---
    senior_levels = {"Senior", "Director", "VP", "C-Suite", "Sr. Manager"}
    entry_levels = {"Entry", "Mid"}
    senior_count = sum(seniority_counts.get(s, 0) for s in senior_levels)
    entry_count = sum(seniority_counts.get(s, 0) for s in entry_levels)
    m["senior_ratio"] = _pct(senior_count, total)
    m["entry_ratio"] = _pct(entry_count, total)
    if entry_count > 0:
        m["senior_to_entry_ratio"] = round(senior_count / entry_count, 2)

    # --- Department concentration (Herfindahl-Hirschman Index) ---
    if dept_counts and total > 0:
        shares = [(c / total) for c in dept_counts.values()]
        hhi = sum(s ** 2 for s in shares)
        m["dept_concentration_hhi"] = round(hhi, 3)
        # Normalized: 1/N = perfectly distributed, 1.0 = single department
        n_depts = len(dept_counts)
        if n_depts > 1:
            m["dept_diversity"] = round(1 - (hhi - 1/n_depts) / (1 - 1/n_depts), 2)

    # --- Growth signals ---
    growth_str = hiring_stats.get("growth_signal_ratio", "")
    if growth_str:
        try:
            pct_val = float(growth_str.replace("%", "").replace(" new roles", "").strip())
            m["new_role_ratio"] = pct_val
        except (ValueError, AttributeError):
            pass

    # --- Hiring velocity from snapshots ---
    if snapshots and len(snapshots) >= 2:
        # Parse snapshots (they come as dicts with JSON-encoded fields)
        parsed = []
        for s in snapshots:
            snap_total = s.get("total_roles", 0)
            snap_date = s.get("snapshot_date", "")
            if snap_total and snap_date:
                parsed.append((snap_date, snap_total))
        parsed.sort(key=lambda x: x[0], reverse=True)

        if len(parsed) >= 2:
            newest_total = parsed[0][1]
            oldest_total = parsed[-1][1]
            delta_pct = _pct(newest_total - oldest_total, oldest_total)
            m["hiring_velocity_pct"] = delta_pct
            m["snapshot_count"] = len(parsed)
            m["snapshot_range"] = f"{parsed[-1][0]} to {parsed[0][0]}"

            # Trend: compare first half vs second half velocity
            if len(parsed) >= 4:
                mid = len(parsed) // 2
                recent_delta = parsed[0][1] - parsed[mid][1]
                older_delta = parsed[mid][1] - parsed[-1][1]
                if older_delta > 0 and recent_delta > older_delta * 1.2:
                    m["hiring_velocity_trend"] = "accelerating"
                elif older_delta > 0 and recent_delta < older_delta * 0.8:
                    m["hiring_velocity_trend"] = "decelerating"
                else:
                    m["hiring_velocity_trend"] = "stable"

    return {k: v for k, v in m.items() if v is not None}


# ---------------------------------------------------------------------------
# Patent / Innovation Metrics
# ---------------------------------------------------------------------------

def compute_patent_metrics(patents_kf):
    """Compute innovation metrics from patent key facts.

    Args:
        patents_kf: key facts dict from patents analysis

    Returns dict of computed metrics.
    """
    if not patents_kf:
        return {}

    m = {}
    total = patents_kf.get("total_patents")
    recent = patents_kf.get("recent_patents")

    if total is not None:
        m["total_patents"] = total
    if recent is not None:
        m["recent_patents"] = recent
        if total and total > 0:
            m["recent_patent_share"] = _pct(recent, total)

    ai_patents = patents_kf.get("ai_ml_patents")
    if ai_patents is not None and total:
        m["ai_ml_patent_share"] = _pct(ai_patents, total)

    trend = patents_kf.get("patent_trend")
    if trend:
        m["patent_trend"] = trend

    rd_intensity = patents_kf.get("rd_intensity")
    if rd_intensity:
        m["rd_intensity_qualitative"] = rd_intensity

    return {k: v for k, v in m.items() if v is not None}


# ---------------------------------------------------------------------------
# Cross-Analysis Derived Metrics
# ---------------------------------------------------------------------------

def _compute_cross_metrics(financial_m, hiring_m, patent_m, all_key_facts):
    """Compute metrics that span multiple analysis types."""
    m = {}

    # R&D spend per patent — are they efficient innovators?
    rd = financial_m.get("rd_expense_latest")
    total_patents = patent_m.get("total_patents")
    if rd and total_patents and total_patents > 0:
        rd_per_patent = rd / total_patents
        m["rd_per_patent"] = round(rd_per_patent)
        m["rd_per_patent_formatted"] = _format_currency(rd_per_patent)

    # Hiring velocity vs revenue growth — scaling efficiently or bloating?
    rev_growth = financial_m.get("revenue_yoy_growth")
    hire_velocity = hiring_m.get("hiring_velocity_pct")
    if rev_growth is not None and hire_velocity is not None:
        if rev_growth > 0:
            ratio = hire_velocity / rev_growth
            m["hiring_to_revenue_growth_ratio"] = round(ratio, 2)
            if ratio > 1.5:
                m["scaling_efficiency"] = "hiring outpacing revenue (potential bloat)"
            elif ratio < 0.5:
                m["scaling_efficiency"] = "revenue outpacing hiring (high productivity)"
            else:
                m["scaling_efficiency"] = "balanced"

    # AI rhetoric vs reality
    hiring_kf = all_key_facts.get("hiring", {})
    ai_tags = 0
    stag_counts = hiring_kf.get("top_strategic_tags", [])
    for tag in stag_counts:
        if isinstance(tag, str) and "ai" in tag.lower():
            ai_tags += 1
    ai_roles = hiring_m.get("ai_ml_role_count", 0)
    ai_patents = patent_m.get("ai_ml_patent_share", 0) or 0
    ai_signals = (1 if ai_roles > 5 else 0) + (1 if ai_patents > 10 else 0) + (1 if ai_tags > 0 else 0)
    if ai_signals > 0:
        m["ai_investment_signals"] = ai_signals
        m["ai_investment_level"] = "strong" if ai_signals >= 3 else "moderate" if ai_signals >= 2 else "emerging"

    return {k: v for k, v in m.items() if v is not None}


# ---------------------------------------------------------------------------
# Master Function
# ---------------------------------------------------------------------------

def compute_company_metrics(financials=None, stock_data=None, extended=None,
                            hiring_stats=None, snapshots=None, all_key_facts=None):
    """Compute all metrics for a company. Returns unified dict.

    All args are optional — computes whatever is available.
    """
    all_key_facts = all_key_facts or {}

    financial_m = compute_financial_metrics(financials or {}, stock_data, extended)
    hiring_m = compute_hiring_metrics(hiring_stats, snapshots)
    patent_m = compute_patent_metrics(all_key_facts.get("patents", {}))
    cross_m = _compute_cross_metrics(financial_m, hiring_m, patent_m, all_key_facts)

    return {
        "financial": financial_m,
        "hiring": hiring_m,
        "patents": patent_m,
        "cross_analysis": cross_m,
    }


def format_metrics_for_prompt(metrics):
    """Format computed metrics as a text block for LLM prompt injection.

    Returns a string to be inserted into the briefing prompt.
    """
    lines = ["## Pre-Computed Metrics (deterministic — use these exact numbers, do NOT recalculate)"]

    fin = metrics.get("financial", {})
    if fin:
        lines.append("\n### Financial")
        parts = []
        if fin.get("revenue_formatted"):
            s = f"Revenue: {fin['revenue_formatted']}"
            if fin.get("revenue_latest_year"):
                s += f" (FY{fin['revenue_latest_year']})"
            parts.append(s)
        if fin.get("revenue_yoy_growth") is not None:
            parts.append(f"YoY Growth: {fin['revenue_yoy_growth']:+.1f}%")
        if fin.get("revenue_cagr_3yr") is not None:
            parts.append(f"3yr CAGR: {fin['revenue_cagr_3yr']:.1f}%")
        if parts:
            lines.append("- " + " | ".join(parts))

        parts = []
        if fin.get("rd_intensity") is not None:
            s = f"R&D Intensity: {fin['rd_intensity']:.1f}% of revenue"
            if fin.get("rd_expense_formatted"):
                s += f" ({fin['rd_expense_formatted']})"
            parts.append(s)
        if fin.get("rd_intensity_trend"):
            parts.append(f"Trend: {fin['rd_intensity_trend']}")
        if parts:
            lines.append("- " + " | ".join(parts))

        parts = []
        if fin.get("operating_margin") is not None:
            parts.append(f"Operating Margin: {fin['operating_margin']:.1f}%")
        if fin.get("net_margin") is not None:
            parts.append(f"Net Margin: {fin['net_margin']:.1f}%")
        if fin.get("gross_margin") is not None:
            parts.append(f"Gross Margin: {fin['gross_margin']:.1f}%")
        if parts:
            lines.append("- " + " | ".join(parts))

        parts = []
        if fin.get("fcf_formatted"):
            parts.append(f"FCF: {fin['fcf_formatted']}")
        if fin.get("fcf_margin") is not None:
            parts.append(f"FCF Margin: {fin['fcf_margin']:.1f}%")
        if fin.get("cash_formatted"):
            parts.append(f"Cash: {fin['cash_formatted']}")
        if parts:
            lines.append("- " + " | ".join(parts))

        if fin.get("revenue_per_employee_formatted"):
            lines.append(f"- Revenue per Employee: {fin['revenue_per_employee_formatted']}" +
                        (f" ({fin['employee_count']:,} employees)" if fin.get("employee_count") else ""))

        if fin.get("market_cap_formatted"):
            parts = [f"Market Cap: {fin['market_cap_formatted']}"]
            if fin.get("pe_ratio"):
                parts.append(f"P/E: {fin['pe_ratio']:.1f}")
            if fin.get("ev_to_ebitda"):
                parts.append(f"EV/EBITDA: {fin['ev_to_ebitda']:.1f}")
            lines.append("- " + " | ".join(parts))

        if fin.get("analyst_target_mean"):
            parts = [f"Analyst Target: ${fin['analyst_target_mean']:.0f}"]
            if fin.get("analyst_upside_pct") is not None:
                parts.append(f"Upside: {fin['analyst_upside_pct']:+.1f}%")
            if fin.get("analyst_count"):
                parts.append(f"({fin['analyst_count']} analysts)")
            lines.append("- " + " | ".join(parts))

    hire = metrics.get("hiring", {})
    if hire:
        lines.append("\n### Hiring")
        parts = []
        if hire.get("total_roles"):
            parts.append(f"Open Roles: {hire['total_roles']}")
        if hire.get("engineering_ratio") is not None:
            parts.append(f"Engineering: {hire['engineering_ratio']:.0f}%")
        if hire.get("ai_ml_intensity") is not None:
            parts.append(f"AI/ML: {hire['ai_ml_intensity']:.1f}% of engineering")
        if parts:
            lines.append("- " + " | ".join(parts))

        parts = []
        if hire.get("senior_ratio") is not None:
            parts.append(f"Senior+: {hire['senior_ratio']:.0f}%")
        if hire.get("new_role_ratio") is not None:
            parts.append(f"New Roles: {hire['new_role_ratio']:.0f}%")
        if hire.get("dept_diversity") is not None:
            parts.append(f"Dept Diversity: {hire['dept_diversity']:.2f}")
        if parts:
            lines.append("- " + " | ".join(parts))

        if hire.get("hiring_velocity_pct") is not None:
            s = f"Hiring Velocity: {hire['hiring_velocity_pct']:+.1f}% vs prior snapshot"
            if hire.get("hiring_velocity_trend"):
                s += f" ({hire['hiring_velocity_trend']})"
            lines.append(f"- {s}")

    pat = metrics.get("patents", {})
    if pat:
        lines.append("\n### Innovation")
        parts = []
        if pat.get("total_patents"):
            parts.append(f"Patents: {pat['total_patents']}")
        if pat.get("recent_patents"):
            parts.append(f"{pat['recent_patents']} recent (2yr)")
        if pat.get("ai_ml_patent_share") is not None:
            parts.append(f"AI/ML share: {pat['ai_ml_patent_share']:.0f}%")
        if pat.get("patent_trend"):
            parts.append(f"Trend: {pat['patent_trend']}")
        if parts:
            lines.append("- " + " | ".join(parts))

    cross = metrics.get("cross_analysis", {})
    if cross:
        lines.append("\n### Cross-Analysis Signals")
        if cross.get("rd_per_patent_formatted"):
            lines.append(f"- R&D per Patent: {cross['rd_per_patent_formatted']}")
        if cross.get("scaling_efficiency"):
            lines.append(f"- Scaling: {cross['scaling_efficiency']}")
        if cross.get("ai_investment_level"):
            lines.append(f"- AI Investment: {cross['ai_investment_level']} ({cross.get('ai_investment_signals', 0)}/3 signals)")

    return "\n".join(lines) if len(lines) > 1 else ""


def format_peer_table_for_prompt(target_metrics, peers):
    """Format peer benchmarks as a markdown table for LLM prompt injection.

    Args:
        target_metrics: dict from compute_financial_metrics() for target company
        peers: list of {name, metrics: dict} from compute_peer_benchmarks()
    """
    if not peers:
        return ""

    # Columns to compare
    columns = [
        ("Rev Growth", "revenue_yoy_growth", ".1f", "%"),
        ("R&D Intensity", "rd_intensity", ".1f", "%"),
        ("Op Margin", "operating_margin", ".1f", "%"),
        ("Net Margin", "net_margin", ".1f", "%"),
        ("FCF Margin", "fcf_margin", ".1f", "%"),
        ("P/E", "pe_ratio", ".1f", ""),
    ]

    # Filter to columns where at least target or one peer has data
    active_cols = []
    for label, key, fmt, suffix in columns:
        has_data = target_metrics.get(key) is not None
        if not has_data:
            has_data = any(p.get("metrics", {}).get(key) is not None for p in peers)
        if has_data:
            active_cols.append((label, key, fmt, suffix))

    if not active_cols:
        return ""

    lines = ["\n### Peer Benchmarks"]
    header = "| Metric | Target |" + " | ".join(p["name"] for p in peers) + " |"
    sep = "|--------|--------|" + "|".join("--------" for _ in peers) + "|"
    lines.append(header)
    lines.append(sep)

    for label, key, fmt, suffix in active_cols:
        row = f"| {label} | "
        tv = target_metrics.get(key)
        row += f"{tv:{fmt}}{suffix}" if tv is not None else "—"
        row += " | "
        cells = []
        for p in peers:
            pv = p.get("metrics", {}).get(key)
            cells.append(f"{pv:{fmt}}{suffix}" if pv is not None else "—")
        row += " | ".join(cells) + " |"
        lines.append(row)

    return "\n".join(lines)
