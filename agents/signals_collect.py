"""Signal collection agent — gathers macro signals across 6 domains.

Reuses existing scrapers (Google News RSS, Reddit RSS, HackerNews Algolia,
FRED API) to collect signals for the Signals module. Each domain has its
own set of queries and source combinations.

Signals are deduplicated via content_hash before database insertion.
"""

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from scraper.google_news import search_google_news
from scraper.reddit_rss import search_all_reddit
from scraper.hackernews import search_stories


def _content_hash(source, url, title):
    """SHA-256 hash for deduplication."""
    raw = f"{source}|{url or ''}|{title or ''}".lower().strip()
    return hashlib.sha256(raw.encode()).hexdigest()


def _classify_domain(title, body=""):
    """Classify a signal's domain from its title/body using keyword matching."""
    text = (title + " " + (body or "")).lower()
    scores = {
        "economics": 0, "finance": 0, "geopolitics": 0,
        "tech_ai": 0, "labor": 0, "regulatory": 0,
    }
    kw = {
        "economics": ["gdp", "recession", "inflation", "economic", "economy", "fed ", "interest rate", "monetary", "fiscal", "cpi", "consumer spending", "imf"],
        "finance": ["stock", "earnings", "ipo", "spac", "merger", "acquisition", "investor", "sec filing", "13f", "revenue", "market cap", "shares", "dividend", "valuation"],
        "geopolitics": ["tariff", "sanction", "trade war", "export control", "geopolit", "china", "iran", "strait of hormuz", "nato", "diplomacy", "embargo"],
        "tech_ai": ["ai ", "artificial intelligence", "llm", "machine learning", "chip", "semiconductor", "software", "cloud", "startup", "tech", "robot", "autonomous", "data center", "low-code", "no-code", "saas"],
        "labor": ["layoff", "hiring", "workforce", "employment", "job market", "remote work", "salary", "labor", "worker", "talent", "contractor"],
        "regulatory": ["regulation", "compliance", "enforcement", "fda", "antitrust", "privacy", "gdpr", "sec enforce", "ban", "oversight"],
    }
    for domain, keywords in kw.items():
        for k in keywords:
            if k in text:
                scores[domain] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "economics"


def _normalize_signal(item, source, domain):
    """Convert a scraper result dict into a standardized signal dict."""
    title = (item.get("title") or "").strip()
    if not title:
        return None
    url = item.get("href") or item.get("url") or ""
    body = (item.get("body") or "")[:2000]
    # Auto-classify domain for targeted/narrative signals
    if domain in ("targeted", "narrative"):
        domain = _classify_domain(title, body)
    return {
        "source": source,
        "domain": domain,
        "title": title,
        "url": url,
        "body": body,
        "published_at": item.get("date") or "",
        "source_name": item.get("source") or source,
        "content_hash": _content_hash(source, url, title),
    }


# ── Domain-specific collectors ────────────────────────────────────────

def _collect_economics(max_per_source=10, progress_cb=None):
    """Economics domain: FRED indicators + macro news."""
    _cb = progress_cb or (lambda *a: None)
    signals = []

    # FRED key indicators (each becomes its own signal)
    _cb("source_start", {"source": "fred", "domain": "economics"})
    try:
        from scraper.fred_api import get_key_indicators
        indicators = get_key_indicators()
        for ind in indicators:
            direction_emoji = {"up": "↑", "down": "↓", "stable": "→"}.get(ind["direction"], "→")
            title = f"{ind['label']}: {ind['latest_value']}{ind['unit']} {direction_emoji}"
            if ind["change"] is not None:
                title += f" ({ind['change']:+.2f})"
            signals.append({
                "source": "fred",
                "domain": "economics",
                "title": title,
                "url": f"https://fred.stlouisfed.org/series/{ind['series_id']}",
                "body": f"{ind['label']} as of {ind['latest_date']}. "
                        f"Previous: {ind['prior_value']} on {ind['prior_date']}."
                        if ind.get("prior_value") else f"{ind['label']} as of {ind['latest_date']}.",
                "published_at": ind["latest_date"],
                "source_name": "FRED",
                "content_hash": _content_hash("fred", ind["series_id"], f"{ind['latest_date']}:{ind['latest_value']}"),
            })
        _cb("source_done", {"source": "fred", "count": len(indicators)})
    except Exception as e:
        print(f"[signals] FRED error: {e}")
        _cb("source_done", {"source": "fred", "count": 0})

    # Google News for macro economics
    queries = [
        "economy GDP growth recession",
        "inflation CPI consumer prices",
        "unemployment jobs report labor market",
    ]
    _cb("source_start", {"source": "google_news", "domain": "economics", "queries": queries})
    news_count = 0
    for q in queries:
        results = search_google_news(q, max_results=max_per_source, days_back=7)
        for item in results:
            sig = _normalize_signal(item, "google_news", "economics")
            if sig:
                signals.append(sig)
                news_count += 1
        time.sleep(0.3)
    _cb("source_done", {"source": "google_news", "count": news_count, "queries": queries})

    return signals


def _collect_finance(max_per_source=10, progress_cb=None):
    """Finance domain: SEC filings, earnings, markets."""
    _cb = progress_cb or (lambda *a: None)
    signals = []

    queries_news = [
        "SEC 13F filing institutional investor",
        "earnings report quarterly results beat miss",
        "IPO SPAC acquisition merger deal",
        "sector rotation market outlook",
    ]
    _cb("source_start", {"source": "google_news", "domain": "finance", "queries": queries_news})
    news_count = 0
    for q in queries_news:
        results = search_google_news(q, max_results=max_per_source, days_back=7)
        for item in results:
            sig = _normalize_signal(item, "google_news", "finance")
            if sig:
                signals.append(sig)
                news_count += 1
        time.sleep(0.3)
    _cb("source_done", {"source": "google_news", "count": news_count, "queries": queries_news})

    # Reddit finance
    reddit_q = "earnings SEC filing institutional"
    _cb("source_start", {"source": "reddit", "domain": "finance", "queries": [reddit_q]})
    reddit_results = search_all_reddit(reddit_q, limit=max_per_source)
    for item in reddit_results:
        sig = _normalize_signal(item, "reddit", "finance")
        if sig:
            signals.append(sig)
    _cb("source_done", {"source": "reddit", "count": len(reddit_results), "queries": [reddit_q]})

    # HackerNews finance
    hn_q = "acquisition IPO funding"
    _cb("source_start", {"source": "hackernews", "domain": "finance", "queries": [hn_q]})
    hn_results = search_stories(hn_q, max_results=max_per_source, sort="date")
    for item in hn_results:
        sig = _normalize_signal(item, "hackernews", "finance")
        if sig:
            signals.append(sig)
    _cb("source_done", {"source": "hackernews", "count": len(hn_results), "queries": [hn_q]})

    return signals


def _collect_geopolitics(max_per_source=10, progress_cb=None):
    """Geopolitics domain: trade policy, sanctions, supply chain."""
    _cb = progress_cb or (lambda *a: None)
    signals = []

    queries_news = [
        "trade policy tariff sanctions",
        "supply chain disruption geopolitical",
        "export controls technology ban",
    ]
    _cb("source_start", {"source": "google_news", "domain": "geopolitics", "queries": queries_news})
    news_count = 0
    for q in queries_news:
        results = search_google_news(q, max_results=max_per_source, days_back=7)
        for item in results:
            sig = _normalize_signal(item, "google_news", "geopolitics")
            if sig:
                signals.append(sig)
                news_count += 1
        time.sleep(0.3)
    _cb("source_done", {"source": "google_news", "count": news_count, "queries": queries_news})

    reddit_q = "trade war sanctions supply chain"
    _cb("source_start", {"source": "reddit", "domain": "geopolitics", "queries": [reddit_q]})
    reddit_results = search_all_reddit(reddit_q, limit=max_per_source)
    for item in reddit_results:
        sig = _normalize_signal(item, "reddit", "geopolitics")
        if sig:
            signals.append(sig)
    _cb("source_done", {"source": "reddit", "count": len(reddit_results), "queries": [reddit_q]})

    return signals


def _collect_tech_ai(max_per_source=10, progress_cb=None):
    """Tech/AI domain: breakthroughs, regulation, product launches."""
    _cb = progress_cb or (lambda *a: None)
    signals = []

    # HN is the primary source for tech/AI
    hn_queries = ["artificial intelligence AI", "machine learning LLM", "tech regulation antitrust"]
    _cb("source_start", {"source": "hackernews", "domain": "tech_ai", "queries": hn_queries})
    hn_count = 0
    for q in hn_queries:
        results = search_stories(q, max_results=max_per_source, sort="date")
        for item in results:
            sig = _normalize_signal(item, "hackernews", "tech_ai")
            if sig:
                signals.append(sig)
                hn_count += 1
    _cb("source_done", {"source": "hackernews", "count": hn_count, "queries": hn_queries})

    news_q = "AI breakthrough regulation technology"
    _cb("source_start", {"source": "google_news", "domain": "tech_ai", "queries": [news_q]})
    news_results = search_google_news(news_q, max_results=max_per_source, days_back=7)
    for item in news_results:
        sig = _normalize_signal(item, "google_news", "tech_ai")
        if sig:
            signals.append(sig)
    _cb("source_done", {"source": "google_news", "count": len(news_results), "queries": [news_q]})

    reddit_q = "AI artificial intelligence breakthrough regulation"
    _cb("source_start", {"source": "reddit", "domain": "tech_ai", "queries": [reddit_q]})
    reddit_results = search_all_reddit(reddit_q, limit=max_per_source)
    for item in reddit_results:
        sig = _normalize_signal(item, "reddit", "tech_ai")
        if sig:
            signals.append(sig)
    _cb("source_done", {"source": "reddit", "count": len(reddit_results), "queries": [reddit_q]})

    return signals


def _collect_labor(max_per_source=10, progress_cb=None):
    """Labor domain: hiring surges, layoffs, workforce trends."""
    _cb = progress_cb or (lambda *a: None)
    signals = []

    queries = [
        "layoffs hiring freeze workforce reduction",
        "hiring surge talent shortage skills gap",
        "remote work return office workforce trends",
    ]
    _cb("source_start", {"source": "google_news", "domain": "labor", "queries": queries})
    news_count = 0
    for q in queries:
        results = search_google_news(q, max_results=max_per_source, days_back=7)
        for item in results:
            sig = _normalize_signal(item, "google_news", "labor")
            if sig:
                signals.append(sig)
                news_count += 1
        time.sleep(0.3)
    _cb("source_done", {"source": "google_news", "count": news_count, "queries": queries})

    reddit_q = "layoffs hiring workforce"
    _cb("source_start", {"source": "reddit", "domain": "labor", "queries": [reddit_q]})
    reddit_results = search_all_reddit(reddit_q, limit=max_per_source)
    for item in reddit_results:
        sig = _normalize_signal(item, "reddit", "labor")
        if sig:
            signals.append(sig)
    _cb("source_done", {"source": "reddit", "count": len(reddit_results), "queries": [reddit_q]})

    return signals


def _collect_regulatory(max_per_source=10, progress_cb=None):
    """Regulatory domain: new regulations, enforcement, compliance."""
    _cb = progress_cb or (lambda *a: None)
    signals = []

    queries = [
        "SEC enforcement regulation compliance",
        "FDA approval regulation pharmaceutical",
        "antitrust investigation monopoly regulation",
        "data privacy GDPR regulation",
    ]
    _cb("source_start", {"source": "google_news", "domain": "regulatory", "queries": queries})
    news_count = 0
    for q in queries:
        results = search_google_news(q, max_results=max_per_source, days_back=7)
        for item in results:
            sig = _normalize_signal(item, "google_news", "regulatory")
            if sig:
                signals.append(sig)
                news_count += 1
        time.sleep(0.3)
    _cb("source_done", {"source": "google_news", "count": news_count, "queries": queries})

    hn_q = "regulation antitrust enforcement"
    _cb("source_start", {"source": "hackernews", "domain": "regulatory", "queries": [hn_q]})
    hn_results = search_stories(hn_q, max_results=max_per_source, sort="date")
    for item in hn_results:
        sig = _normalize_signal(item, "hackernews", "regulatory")
        if sig:
            signals.append(sig)
    _cb("source_done", {"source": "hackernews", "count": len(hn_results), "queries": [hn_q]})

    return signals


# ── Domain registry ───────────────────────────────────────────────────

DOMAIN_COLLECTORS = {
    "economics": _collect_economics,
    "finance": _collect_finance,
    "geopolitics": _collect_geopolitics,
    "tech_ai": _collect_tech_ai,
    "labor": _collect_labor,
    "regulatory": _collect_regulatory,
}

ALL_DOMAINS = list(DOMAIN_COLLECTORS.keys())


# ── Public API ────────────────────────────────────────────────────────

def collect_domain_signals(domain, max_per_source=10, progress_cb=None):
    """Collect signals for a single domain.

    Args:
        domain: One of ALL_DOMAINS
        max_per_source: Max results per source per query
        progress_cb: Optional callback(event_type, event_data)

    Returns list of signal dicts ready for DB insertion.
    """
    collector = DOMAIN_COLLECTORS.get(domain)
    if not collector:
        print(f"[signals] Unknown domain: {domain}")
        return []
    return collector(max_per_source=max_per_source, progress_cb=progress_cb)


def collect_all_domains(max_per_source=8, progress_cb=None):
    """Collect signals across all 6 domains sequentially.

    Args:
        max_per_source: Max results per source per query
        progress_cb: Optional callback(event_type, event_data)

    Returns list of all signal dicts (deduplicated by content_hash).
    """
    _cb = progress_cb or (lambda *a: None)
    all_signals = []
    seen_hashes = set()

    for domain in ALL_DOMAINS:
        _cb("domain_start", {"domain": domain})
        signals = collect_domain_signals(domain, max_per_source=max_per_source, progress_cb=progress_cb)
        new_count = 0
        for sig in signals:
            if sig["content_hash"] not in seen_hashes:
                seen_hashes.add(sig["content_hash"])
                all_signals.append(sig)
                new_count += 1
        _cb("domain_done", {"domain": domain, "count": new_count, "total": len(all_signals)})

    _cb("scan_complete", {"total": len(all_signals), "domains": len(ALL_DOMAINS)})
    return all_signals
