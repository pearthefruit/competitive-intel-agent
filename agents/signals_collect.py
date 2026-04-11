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
    """Classify a signal's domain from its title/body using keyword matching.
    Title matches are weighted 2x. Falls back to economics only if nothing matches."""
    title_lower = (title or "").lower()
    body_lower = (body or "").lower()
    scores = {
        "economics": 0, "finance": 0, "geopolitics": 0,
        "tech_ai": 0, "labor": 0, "regulatory": 0,
    }
    kw = {
        "economics": ["gdp", "recession", "inflation", "economic", "economy", "fed ", "interest rate", "monetary", "fiscal", "cpi", "consumer spending", "imf", "central bank", "treasury"],
        "finance": ["earnings", "ipo", "spac", "merger", "acquisition", "investor", "sec filing", "13f", "market cap", "dividend", "valuation", "wall street", "hedge fund", "bond", "yield"],
        "geopolitics": ["tariff", "sanction", "trade war", "export control", "geopolit", "china", "iran", "strait of hormuz", "nato", "diplomacy", "embargo", "military", "conflict", "ceasefire", "war "],
        "tech_ai": ["ai ", "artificial intelligence", "llm", "machine learning", "chip", "semiconductor", "software", "cloud", "startup", "tech", "robot", "autonomous", "data center", "low-code", "no-code", "saas", "iphone", "apple", "google", "microsoft", "meta ", "amazon", "nvidia", "phone", "device", "launch", "hardware", "foldable", "android", "app ", "platform", "cyber", "quantum"],
        "labor": ["layoff", "hiring", "workforce", "employment", "job market", "remote work", "salary", "labor", "worker", "talent", "contractor", "jobs report", "nonfarm", "unemployment"],
        "regulatory": ["regulation", "compliance", "enforcement", "fda", "antitrust", "privacy", "gdpr", "sec enforce", "ban", "oversight", "legislation", "congress", "executive order"],
    }
    for domain, keywords in kw.items():
        for k in keywords:
            if k in title_lower:
                scores[domain] += 2  # title matches weighted 2x
            elif k in body_lower:
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
    # Determine source type
    source_type = item.get("source_type") or ("government" if source == "gov_rss" else "social" if source in ("reddit", "hackernews") else "news")
    return {
        "source": source,
        "domain": domain,
        "title": title,
        "url": url,
        "body": body,
        "published_at": item.get("date") or "",
        "source_name": item.get("source") or source,
        "source_type": source_type,
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


def _collect_gov_for_domain(domain, max_per_source=10, progress_cb=None):
    """Collect government RSS signals relevant to a specific domain."""
    _cb = progress_cb or (lambda *a: None)
    signals = []
    try:
        from scraper.rss_feeds import RSS_FEEDS, fetch_rss_feed
    except ImportError:
        return signals

    domain_feeds = {k: v for k, v in RSS_FEEDS.items() if v["domain"] == domain}
    if not domain_feeds:
        return signals

    feed_names = list(domain_feeds.keys())
    _cb("source_start", {"source": "gov_rss", "domain": domain, "feeds": feed_names})
    for key in feed_names:
        items = fetch_rss_feed(key, max_results=max_per_source, days_back=7)
        for item in items:
            sig = _normalize_signal(item, "rss_feed", domain)
            if sig:
                sig["source_name"] = item.get("source", key)
                signals.append(sig)
    _cb("source_done", {"source": "rss_feed", "count": len(signals), "feeds": feed_names})
    return signals


# ── Domain registry ───────────────────────────────────────────────────

def _wrap_with_gov(collector_fn):
    """Wrap a domain collector to also fetch government RSS feeds."""
    domain = {v: k for k, v in {
        "economics": _collect_economics, "finance": _collect_finance,
        "geopolitics": _collect_geopolitics, "tech_ai": _collect_tech_ai,
        "labor": _collect_labor, "regulatory": _collect_regulatory,
    }.items()}.get(collector_fn)

    def wrapped(max_per_source=10, progress_cb=None):
        signals = collector_fn(max_per_source=max_per_source, progress_cb=progress_cb)
        if domain:
            signals.extend(_collect_gov_for_domain(domain, max_per_source=max_per_source, progress_cb=progress_cb))
        return signals
    return wrapped


DOMAIN_COLLECTORS = {
    "economics": _wrap_with_gov(_collect_economics),
    "finance": _wrap_with_gov(_collect_finance),
    "geopolitics": _wrap_with_gov(_collect_geopolitics),
    "tech_ai": _wrap_with_gov(_collect_tech_ai),
    "labor": _wrap_with_gov(_collect_labor),
    "regulatory": _wrap_with_gov(_collect_regulatory),
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


def targeted_search(query, days_back=30, progress_cb=None):
    """Search for signals across ALL sources for a specific query.

    Unlike domain collectors (which use hardcoded queries), this takes an
    arbitrary user query and fans it out to every available source.

    Returns list of signal dicts + audit breakdown per source.
    """
    from scraper.google_news import search_google_news
    from scraper.hackernews import search_stories
    from scraper.reddit_rss import search_reddit_rss
    from concurrent.futures import ThreadPoolExecutor, as_completed

    _cb = progress_cb or (lambda *a: None)
    results = []
    seen_hashes = set()
    audit = []

    def _add(sig):
        if not sig:
            return False
        h = sig["content_hash"]
        if h in seen_hashes:
            return False
        seen_hashes.add(h)
        results.append(sig)
        return True

    # 1. Google News — primary news source
    _cb("source_start", {"source": "google_news", "query": query})
    try:
        news = search_google_news(query, max_results=12, days_back=days_back)
        count = sum(1 for item in news if _add(_normalize_signal(item, "google_news", "targeted")))
        audit.append({"source": "Google News", "raw": len(news), "new": count})
    except Exception as e:
        print(f"[targeted_search] Google News error: {e}")
        audit.append({"source": "Google News", "raw": 0, "new": 0, "error": str(e)})
    _cb("source_done", {"source": "google_news", "count": count if 'count' in dir() else 0})

    # 2. DuckDuckGo News — different index, catches what Google News misses
    _cb("source_start", {"source": "ddg_news", "query": query})
    try:
        from scraper.web_search import search_news as ddg_search_news
        ddg_news = ddg_search_news(query, max_results=10)
        count = 0
        for item in ddg_news:
            sig = _normalize_signal({
                "title": item.get("title", ""),
                "href": item.get("url") or item.get("href", ""),
                "body": item.get("body", ""),
                "date": item.get("date", ""),
                "source": item.get("source", ""),
            }, "ddg_news", "targeted")
            if _add(sig):
                count += 1
        audit.append({"source": "DuckDuckGo News", "raw": len(ddg_news), "new": count})
    except Exception as e:
        print(f"[targeted_search] DDG News error: {e}")
        audit.append({"source": "DuckDuckGo News", "raw": 0, "new": 0, "error": str(e)})
    _cb("source_done", {"source": "ddg_news", "count": count if 'count' in dir() else 0})

    # 3. HackerNews — tech/startup community
    _cb("source_start", {"source": "hackernews", "query": query})
    try:
        hn = search_stories(query, max_results=8, sort="date")
        count = sum(1 for item in hn if _add(_normalize_signal(item, "hackernews", "targeted")))
        audit.append({"source": "Hacker News", "raw": len(hn), "new": count})
    except Exception as e:
        print(f"[targeted_search] HN error: {e}")
        audit.append({"source": "Hacker News", "raw": 0, "new": 0, "error": str(e)})
    _cb("source_done", {"source": "hackernews", "count": count if 'count' in dir() else 0})

    # 4. Reddit — social sentiment
    _cb("source_start", {"source": "reddit", "query": query})
    try:
        reddit = search_reddit_rss(query, max_results=8, subreddits=None, fetch_comments_top_n=0)
        count = sum(1 for item in reddit if _add(_normalize_signal(item, "reddit", "targeted")))
        audit.append({"source": "Reddit", "raw": len(reddit), "new": count})
    except Exception as e:
        print(f"[targeted_search] Reddit error: {e}")
        audit.append({"source": "Reddit", "raw": 0, "new": 0, "error": str(e)})
    _cb("source_done", {"source": "reddit", "count": count if 'count' in dir() else 0})

    # 5. RSS Feeds — keyword-filter across all feeds
    _cb("source_start", {"source": "rss_feeds", "query": query})
    try:
        from scraper.rss_feeds import RSS_FEEDS, fetch_rss_feed
        query_lower = query.lower()
        rss_count = 0
        for key in RSS_FEEDS:
            items = fetch_rss_feed(key, max_results=15, days_back=days_back)
            for item in items:
                title = (item.get("title") or "").lower()
                body = (item.get("body") or "").lower()
                if query_lower in title or query_lower in body:
                    sig = _normalize_signal(item, "rss_feed", RSS_FEEDS[key]["domain"])
                    if sig:
                        sig["source_type"] = RSS_FEEDS[key].get("source_type", "news")
                        sig["source_name"] = RSS_FEEDS[key]["source_name"]
                        if _add(sig):
                            rss_count += 1
        audit.append({"source": "RSS Feeds", "new": rss_count})
    except Exception as e:
        print(f"[targeted_search] RSS feed error: {e}")
        audit.append({"source": "RSS Feeds", "raw": 0, "new": 0, "error": str(e)})
    _cb("source_done", {"source": "rss_feeds", "count": rss_count if 'rss_count' in dir() else 0})

    # 6. FRED — search for relevant economic indicators
    _cb("source_start", {"source": "fred", "query": query})
    try:
        from scraper.fred_api import search_series, fetch_series
        series_matches = search_series(query, limit=5)
        fred_count = 0
        for s in series_matches:
            obs = fetch_series(s["series_id"], limit=2)
            if not obs:
                continue
            latest = obs[-1]
            prior = obs[-2] if len(obs) > 1 else None
            val = latest.get("value", "N/A")
            title = f"{s['title']}: {val} ({latest.get('date', '')})"
            body = f"{s['title']}. Latest: {val} on {latest.get('date', '')}."
            if prior:
                body += f" Previous: {prior.get('value', 'N/A')} on {prior.get('date', '')}."
            sig = {
                "source": "fred",
                "domain": _classify_domain(s["title"], ""),
                "title": title,
                "url": f"https://fred.stlouisfed.org/series/{s['series_id']}",
                "body": body,
                "published_at": latest.get("date", ""),
                "source_name": "FRED",
                "source_type": "data_point",
                "content_hash": _content_hash("fred", s["series_id"], f"{latest.get('date', '')}:{val}"),
            }
            if _add(sig):
                fred_count += 1
        audit.append({"source": "FRED", "raw": len(series_matches), "new": fred_count})
    except Exception as e:
        print(f"[targeted_search] FRED error: {e}")
        audit.append({"source": "FRED", "raw": 0, "new": 0, "error": str(e)})
    _cb("source_done", {"source": "fred", "count": fred_count if 'fred_count' in dir() else 0})

    _cb("search_complete", {"total": len(results), "sources": len(audit)})
    return results, audit
