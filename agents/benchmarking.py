"""Competitor financial benchmarking — deterministic peer comparison. Zero LLM calls.

Pulls SEC EDGAR + Yahoo Finance data for competitors and computes comparative metrics.
"""

from agents.metrics import compute_financial_metrics


def compute_peer_benchmarks(company, company_metrics, competitor_names, progress_cb=None):
    """Pull financials for competitors and compute comparative metrics.

    Args:
        company: target company name
        company_metrics: pre-computed financial metrics dict for the target
        competitor_names: list of competitor names (from key_facts["competitors"]["key_competitors"])
        progress_cb: optional callback for streaming progress

    Returns dict:
        peers: [{name, ticker, metrics: {...}}, ...]
        target: {name, ticker, metrics: company_metrics}
        percentile_ranks: {metric: percentile} — where target sits vs peers
    """
    _cb = progress_cb or (lambda *a: None)

    if not competitor_names:
        return None

    from scraper.sec_edgar import lookup_cik, get_company_facts, extract_financials
    from scraper.stock_data import get_stock_data, get_extended_financials

    peers = []
    for comp_name in competitor_names[:4]:
        _cb("source_start", {"source": f"peer_{comp_name}", "label": f"Peer: {comp_name}", "detail": f"Fetching financials for {comp_name}"})
        print(f"[benchmarking] Fetching data for peer: {comp_name}")

        peer_metrics = {}
        ticker = None

        try:
            cik_result = lookup_cik(comp_name)
            if cik_result and not isinstance(cik_result, list):
                ticker = cik_result["ticker"]
                facts = get_company_facts(cik_result["cik"])
                if facts:
                    financials = extract_financials(facts)
                    stock_data = get_stock_data(ticker)
                    extended = get_extended_financials(ticker) if ticker else None
                    peer_metrics = compute_financial_metrics(financials, stock_data, extended)
            elif isinstance(cik_result, list) and cik_result:
                # Multiple matches — take first
                ticker = cik_result[0]["ticker"]
                facts = get_company_facts(cik_result[0]["cik"])
                if facts:
                    financials = extract_financials(facts)
                    stock_data = get_stock_data(ticker)
                    extended = get_extended_financials(ticker) if ticker else None
                    peer_metrics = compute_financial_metrics(financials, stock_data, extended)
            else:
                # Not public — try Yahoo Finance directly
                stock_data = get_stock_data(comp_name)
                if stock_data:
                    ticker = comp_name
                    extended = get_extended_financials(comp_name)
                    peer_metrics = compute_financial_metrics({}, stock_data, extended)

        except Exception as e:
            print(f"[benchmarking] Failed to fetch data for {comp_name}: {e}")

        if peer_metrics:
            peers.append({"name": comp_name, "ticker": ticker, "metrics": peer_metrics})
            summary = f"rev={peer_metrics.get('revenue_formatted', '?')}, growth={peer_metrics.get('revenue_yoy_growth', '?')}%"
            _cb("source_done", {"source": f"peer_{comp_name}", "status": "done", "summary": summary})
            print(f"[benchmarking] {comp_name}: {summary}")
        else:
            _cb("source_done", {"source": f"peer_{comp_name}", "status": "skipped", "summary": "No financial data"})
            print(f"[benchmarking] {comp_name}: no data found")

    if not peers:
        return None

    # Compute percentile ranks for target vs peers
    percentiles = _compute_percentiles(company_metrics, peers)

    return {
        "peers": peers,
        "target": {"name": company, "metrics": company_metrics},
        "percentile_ranks": percentiles,
    }


def _compute_percentiles(target_metrics, peers):
    """Compute where the target sits vs peers for each metric.

    Returns dict of {metric_key: percentile (0-100)}.
    Higher percentile = target ranks better.
    """
    compare_keys = [
        ("revenue_yoy_growth", True),    # higher is better
        ("rd_intensity", True),           # higher = more investment
        ("operating_margin", True),       # higher is better
        ("net_margin", True),             # higher is better
        ("fcf_margin", True),             # higher is better
        ("revenue_per_employee", True),   # higher is better
        ("pe_ratio", False),              # lower is better (cheaper)
    ]

    percentiles = {}
    for key, higher_is_better in compare_keys:
        target_val = target_metrics.get(key)
        if target_val is None:
            continue

        peer_vals = [p["metrics"].get(key) for p in peers if p["metrics"].get(key) is not None]
        if not peer_vals:
            continue

        all_vals = peer_vals + [target_val]
        all_vals.sort(reverse=higher_is_better)
        rank = all_vals.index(target_val)
        percentile = round((1 - rank / (len(all_vals) - 1)) * 100) if len(all_vals) > 1 else 50
        percentiles[key] = percentile

    return percentiles
