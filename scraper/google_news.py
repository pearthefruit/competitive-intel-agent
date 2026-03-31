"""Google News RSS scraper — no API key, no DDG dependency.

Parses RSS 2.0 XML from Google News search. Supplements DDG for broader,
more recent news coverage with proper date and source metadata.
"""

import re
import time
import threading
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from xml.etree import ElementTree as ET

import httpx

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# Rate limiting (same pattern as DDG in web_search.py)
_GNEWS_MIN_INTERVAL = 0.5
_gnews_last_call = 0.0
_gnews_lock = threading.Lock()


def _gnews_throttle():
    """Wait if needed to respect Google News rate limits."""
    global _gnews_last_call
    with _gnews_lock:
        now = time.monotonic()
        elapsed = now - _gnews_last_call
        if elapsed < _GNEWS_MIN_INTERVAL:
            time.sleep(_GNEWS_MIN_INTERVAL - elapsed)
        _gnews_last_call = time.monotonic()


def _resolve_google_news_url(google_url):
    """Resolve a Google News redirect URL to the actual article URL.

    Google News wraps article links in redirect URLs like:
    https://news.google.com/rss/articles/CBMi...
    Follow the redirect to get the real URL.
    """
    if not google_url or "news.google.com" not in google_url:
        return google_url
    try:
        resp = httpx.head(
            google_url,
            headers=_HEADERS,
            follow_redirects=True,
            timeout=8,
        )
        final_url = str(resp.url)
        if "news.google.com" not in final_url:
            return final_url
    except Exception:
        pass
    return google_url


def _parse_pub_date(date_str):
    """Parse RSS pubDate (RFC 2822) to ISO format date string."""
    if not date_str:
        return ""
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return date_str


def search_google_news(query, max_results=10, days_back=None):
    """Search Google News via RSS feed.

    Args:
        query: Search query (e.g. "Apple earnings 2026")
        max_results: Maximum results to return
        days_back: Optional — restrict to articles from the last N days.
                   Uses Google News 'when:Nd' parameter.

    Returns list of dicts: {title, href, body, date, source}
    """
    _gnews_throttle()

    encoded_query = quote(query)
    if days_back:
        encoded_query += f"+when:{days_back}d"

    url = (
        f"https://news.google.com/rss/search?"
        f"q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    )

    try:
        resp = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=15)
        if resp.status_code != 200:
            print(f"[google_news] HTTP {resp.status_code} for query: {query[:60]}")
            return []

        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"[google_news] Fetch/parse failed for '{query[:60]}': {e}")
        return []

    # RSS 2.0: <rss><channel><item>...</item></channel></rss>
    channel = root.find("channel")
    if channel is None:
        print(f"[google_news] No <channel> in RSS for: {query[:60]}")
        return []

    items = channel.findall("item")
    if not items:
        print(f"[google_news] No items for: {query[:60]}")
        return []

    results = []
    seen_urls = set()

    for item in items[:max_results * 2]:  # extra to account for dedup
        title_el = item.find("title")
        link_el = item.find("link")
        pub_date_el = item.find("pubDate")
        source_el = item.find("source")
        desc_el = item.find("description")

        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        raw_link = link_el.text.strip() if link_el is not None and link_el.text else ""
        pub_date = pub_date_el.text.strip() if pub_date_el is not None and pub_date_el.text else ""
        source_name = source_el.text.strip() if source_el is not None and source_el.text else ""
        description = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

        if not title:
            continue

        # Resolve actual article URL (Google wraps in redirects)
        href = _resolve_google_news_url(raw_link)

        if href in seen_urls:
            continue
        seen_urls.add(href)

        # Strip HTML from description (Google News descriptions have <a> tags)
        if description:
            description = re.sub(r"<[^>]+>", " ", description)
            description = re.sub(r"\s+", " ", description).strip()

        results.append({
            "title": title,
            "href": href,
            "body": description,
            "date": _parse_pub_date(pub_date),
            "source": source_name or "Google News",
        })

        if len(results) >= max_results:
            break

    print(f"[google_news] Found {len(results)} results for: {query[:60]}")
    return results
