"""RSS feed scraper — general news and official data sources.

Fetches press releases, statements, and news from:
- Al Jazeera (English news)
- Federal Reserve (FOMC, speeches, policy)
- FDA (drug approvals, safety alerts, enforcement)
- CDC (health alerts, disease tracking, guidance)
- SEC (enforcement, press releases)
- NASA (missions, discoveries, contracts)
- DOE (energy policy, grid, climate)
- WHO (global health, outbreaks, policy)
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import httpx

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# Feed registry: name → (url, domain, source_name, source_type)
RSS_FEEDS = {
    "aljazeera": {
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "domain": "geopolitics",
        "source_name": "Al Jazeera",
        "source_type": "news",
    },
    "fed": {
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "domain": "economics",
        "source_name": "Federal Reserve",
        "source_type": "government",
    },
    "fda": {
        "url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
        "domain": "regulatory",
        "source_name": "FDA",
        "source_type": "government",
    },
    "cdc": {
        "url": "https://tools.cdc.gov/api/v2/resources/media/132608.rss",
        "domain": "regulatory",
        "source_name": "CDC",
        "source_type": "government",
    },
    "sec": {
        "url": "https://www.sec.gov/news/pressreleases.rss",
        "domain": "finance",
        "source_name": "SEC",
        "source_type": "government",
    },
    "nasa": {
        "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss",
        "domain": "tech_ai",
        "source_name": "NASA",
        "source_type": "government",
    },
    "doe": {
        "url": "https://www.energy.gov/rss.xml",
        "domain": "economics",
        "source_name": "Dept. of Energy",
        "source_type": "government",
    },
    "who": {
        "url": "https://www.who.int/rss-feeds/news-english.xml",
        "domain": "regulatory",
        "source_name": "WHO",
        "source_type": "government",
    },
    "whitehouse_exec": {
        "url": "https://www.whitehouse.gov/presidential-actions/feed/",
        "domain": "geopolitics",
        "source_name": "White House",
        "source_type": "government",
    },
    "whitehouse_news": {
        "url": "https://www.whitehouse.gov/news/feed/",
        "domain": "geopolitics",
        "source_name": "White House",
        "source_type": "government",
    },
    "whitehouse_statements": {
        "url": "https://www.whitehouse.gov/briefings-statements/feed/",
        "domain": "geopolitics",
        "source_name": "White House",
        "source_type": "government",
    },
}


def _parse_date(date_str):
    """Parse various RSS date formats to ISO date string."""
    if not date_str:
        return ""
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ]:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str[:10] if len(date_str) >= 10 else ""


def _strip_html(text):
    """Remove HTML tags from text."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", text).strip()


def fetch_rss_feed(feed_key, max_results=15, days_back=7):
    """Fetch items from an RSS feed.

    Returns list of dicts: {title, href, body, date, source, source_type}
    """
    feed = RSS_FEEDS.get(feed_key)
    if not feed:
        return []

    try:
        resp = httpx.get(feed["url"], headers=_HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            print(f"[rss_feed] {feed_key} HTTP {resp.status_code}")
            return []
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"[rss_feed] {feed_key} fetch/parse error: {e}")
        return []

    # Handle both RSS 2.0 (<channel><item>) and Atom (<entry>)
    items = root.findall(".//item")
    if not items:
        # Try Atom format
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//atom:entry", ns) or root.findall(".//{http://www.w3.org/2005/Atom}entry")

    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d") if days_back else None
    results = []

    for item in items[:max_results * 2]:
        # RSS 2.0
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        date_el = item.find("pubDate")

        # Atom fallback
        if title_el is None:
            title_el = item.find("{http://www.w3.org/2005/Atom}title")
        if link_el is None:
            link_el = item.find("{http://www.w3.org/2005/Atom}link")
        if desc_el is None:
            desc_el = item.find("{http://www.w3.org/2005/Atom}summary") or item.find("{http://www.w3.org/2005/Atom}content")
        if date_el is None:
            date_el = item.find("{http://www.w3.org/2005/Atom}updated") or item.find("{http://www.w3.org/2005/Atom}published")

        title = (title_el.text or "").strip() if title_el is not None else ""
        if not title:
            continue

        # Get link — RSS uses text content, Atom uses href attribute
        href = ""
        if link_el is not None:
            href = link_el.get("href") or (link_el.text or "").strip()

        body = _strip_html((desc_el.text or "") if desc_el is not None else "")
        date_str = _parse_date((date_el.text or "") if date_el is not None else "")

        # Filter stale
        if cutoff and date_str and date_str < cutoff:
            continue

        results.append({
            "title": title,
            "href": href,
            "body": body[:2000],
            "date": date_str,
            "source": feed["source_name"],
            "source_type": feed["source_type"],
        })

        if len(results) >= max_results:
            break

    print(f"[rss_feed] {feed_key}: {len(results)} items")
    return results


def fetch_all_rss_feeds(max_per_feed=10, days_back=7):
    """Fetch from all RSS feeds. Returns dict of feed_key → items."""
    all_results = {}
    for key in RSS_FEEDS:
        all_results[key] = fetch_rss_feed(key, max_results=max_per_feed, days_back=days_back)
    return all_results
