"""FRED (Federal Reserve Economic Data) API client.

Free API from the St. Louis Fed — 800K+ economic data series.
API key optional for basic access; set FRED_API_KEY for higher rate limits.

Docs: https://fred.stlouisfed.org/docs/api/fred/
"""

import os
from datetime import datetime, timedelta

import httpx

_BASE = "https://api.stlouisfed.org/fred"
_HEADERS = {"User-Agent": "SignalVault/1.0 (competitive intelligence research tool)"}

# Key economic indicators with human-readable labels and context
KEY_INDICATORS = [
    {"series_id": "UNRATE",    "label": "Unemployment Rate",    "unit": "%",    "domain": "labor"},
    {"series_id": "PAYEMS",    "label": "Nonfarm Payrolls",     "unit": "K",    "domain": "labor"},
    {"series_id": "CPIAUCSL",  "label": "CPI (All Urban)",      "unit": "index","domain": "economics"},
    {"series_id": "GDP",       "label": "GDP",                  "unit": "$B",   "domain": "economics"},
    {"series_id": "FEDFUNDS",  "label": "Fed Funds Rate",       "unit": "%",    "domain": "finance"},
    {"series_id": "DGS10",     "label": "10-Year Treasury",     "unit": "%",    "domain": "finance"},
    {"series_id": "DEXUSEU",   "label": "USD/EUR Exchange Rate", "unit": "",    "domain": "finance"},
    {"series_id": "VIXCLS",    "label": "VIX (Volatility)",     "unit": "",     "domain": "finance"},
    {"series_id": "ICSA",      "label": "Initial Jobless Claims","unit": "K",   "domain": "labor"},
    {"series_id": "HOUST",     "label": "Housing Starts",       "unit": "K",    "domain": "economics"},
    {"series_id": "RSXFS",     "label": "Retail Sales",         "unit": "$M",   "domain": "economics"},
    {"series_id": "INDPRO",    "label": "Industrial Production", "unit": "index","domain": "economics"},
    {"series_id": "UMCSENT",   "label": "Consumer Sentiment",   "unit": "index","domain": "economics"},
    {"series_id": "T10YIE",    "label": "10Y Breakeven Inflation","unit": "%",  "domain": "economics"},
    {"series_id": "BAMLH0A0HYM2", "label": "High Yield Spread", "unit": "%",   "domain": "finance"},
]


def _get_api_key():
    return os.environ.get("FRED_API_KEY", "")


def fetch_series(series_id, limit=10, observation_start=None):
    """Fetch recent observations for a FRED series.

    Args:
        series_id: FRED series ID (e.g., 'UNRATE')
        limit: Number of observations to return
        observation_start: ISO date string for start of range

    Returns list of dicts: {date, value}
    """
    api_key = _get_api_key()
    if not api_key:
        print(f"[fred] No FRED_API_KEY set, skipping {series_id}")
        return []

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    if observation_start:
        params["observation_start"] = observation_start

    try:
        resp = httpx.get(
            f"{_BASE}/series/observations",
            params=params,
            headers=_HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[fred] HTTP {resp.status_code} for series {series_id}")
            return []

        data = resp.json()
        observations = []
        for obs in data.get("observations", []):
            val = obs.get("value", ".")
            if val == ".":  # FRED uses "." for missing data
                continue
            observations.append({
                "date": obs.get("date", ""),
                "value": float(val),
            })
        return observations

    except Exception as e:
        print(f"[fred] Error fetching {series_id}: {e}")
        return []


def get_series_info(series_id):
    """Fetch metadata for a FRED series (title, frequency, units, etc.)."""
    api_key = _get_api_key()
    if not api_key:
        return None

    try:
        resp = httpx.get(
            f"{_BASE}/series",
            params={"series_id": series_id, "api_key": api_key, "file_type": "json"},
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        serieses = resp.json().get("seriess", [])
        return serieses[0] if serieses else None
    except Exception:
        return None


def search_series(query, limit=10):
    """Search for FRED series by keyword.

    Returns list of dicts: {series_id, title, frequency, units, popularity}
    """
    api_key = _get_api_key()
    if not api_key:
        print("[fred] No FRED_API_KEY set, skipping search")
        return []

    try:
        resp = httpx.get(
            f"{_BASE}/series/search",
            params={
                "search_text": query,
                "api_key": api_key,
                "file_type": "json",
                "limit": limit,
                "order_by": "popularity",
                "sort_order": "desc",
            },
            headers=_HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            return []

        results = []
        for s in resp.json().get("seriess", []):
            results.append({
                "series_id": s.get("id", ""),
                "title": s.get("title", ""),
                "frequency": s.get("frequency_short", ""),
                "units": s.get("units_short", ""),
                "popularity": s.get("popularity", 0),
            })
        return results

    except Exception as e:
        print(f"[fred] Search error: {e}")
        return []


def get_key_indicators():
    """Fetch latest values + change direction for key economic indicators.

    Returns list of dicts: {series_id, label, unit, domain, latest_value,
    latest_date, prior_value, prior_date, change, change_pct, direction}
    """
    results = []
    for ind in KEY_INDICATORS:
        obs = fetch_series(ind["series_id"], limit=2)
        if not obs:
            continue

        latest = obs[0]
        prior = obs[1] if len(obs) > 1 else None

        entry = {
            "series_id": ind["series_id"],
            "label": ind["label"],
            "unit": ind["unit"],
            "domain": ind["domain"],
            "latest_value": latest["value"],
            "latest_date": latest["date"],
            "prior_value": prior["value"] if prior else None,
            "prior_date": prior["date"] if prior else None,
            "change": None,
            "change_pct": None,
            "direction": "stable",
        }

        if prior and prior["value"] != 0:
            change = latest["value"] - prior["value"]
            change_pct = (change / abs(prior["value"])) * 100
            entry["change"] = round(change, 4)
            entry["change_pct"] = round(change_pct, 2)
            if change > 0:
                entry["direction"] = "up"
            elif change < 0:
                entry["direction"] = "down"

        results.append(entry)

    print(f"[fred] Fetched {len(results)} key indicators")
    return results
