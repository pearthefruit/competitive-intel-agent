"""Web search via DuckDuckGo + Reddit RSS fallback.

Primary: DuckDuckGo (no API key required).
Fallback: Reddit RSS feeds (direct, no DDG dependency).
"""

import time
import threading
import concurrent.futures
import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

from scraper.reddit_rss import search_reddit_rss

# Throttle DDG calls to avoid rate limits (min seconds between calls)
_DDG_MIN_INTERVAL = 0.5
_ddg_last_call = 0.0
_ddg_lock = threading.Lock()


def _ddg_throttle():
    """Wait if needed to respect DDG rate limits."""
    global _ddg_last_call
    with _ddg_lock:
        now = time.monotonic()
        elapsed = now - _ddg_last_call
        if elapsed < _DDG_MIN_INTERVAL:
            time.sleep(_DDG_MIN_INTERVAL - elapsed)
        _ddg_last_call = time.monotonic()

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def fetch_page_text(url, max_chars=3000):
    try:
        if not url.startswith("http"):
            return ""
        with httpx.Client(headers=REQUEST_HEADERS, timeout=12, follow_redirects=True) as client:
            resp = client.get(url)
            ct = resp.headers.get("content-type", "").lower()
            if resp.status_code == 200 and "text/html" in ct:
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                text = soup.get_text(separator=" ", strip=True)[:max_chars]
                if text:
                    print(f"[search] Fetched {len(text)} chars from {url[:80]}")
                return text
            else:
                print(f"[search] Skip {url[:80]} — status={resp.status_code} ct={ct[:40]}")
    except Exception as e:
        print(f"[search] Failed to fetch {url[:80]}: {e}")
    return ""


def search_news(query, max_results=10, fetch_content=False):
    """Search for recent news articles.

    Returns list of dicts with: title, url, body, date, source.
    """
    for attempt in range(3):
        try:
            _ddg_throttle()
            ddgs = DDGS()
            results = list(ddgs.news(query, max_results=max_results))
            if fetch_content and results:
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    future_to_r = {executor.submit(fetch_page_text, r.get("url", "")): r for r in results if r.get("url")}
                    for future in concurrent.futures.as_completed(future_to_r):
                        r = future_to_r[future]
                        try:
                            text = future.result()
                        except Exception:
                            text = ""
                        if text:
                            r["body"] = text
            return results
        except Exception as e:
            if "futures" in str(e).lower():
                print(f"[search] News search failed (threading): {e}")
                return []
            if attempt < 2:
                wait = 2 * (attempt + 1)
                print(f"[search] News search attempt {attempt + 1} failed ({type(e).__name__}), retrying in {wait}s...")
                time.sleep(wait)
                continue
            print(f"[search] News search failed after {attempt + 1} attempts: {e}")
            return []
    return []


def search_web(query, max_results=5, fetch_content=False):
    """General web search.

    Returns list of dicts with: title, href, body.
    """
    for attempt in range(3):
        try:
            _ddg_throttle()
            ddgs = DDGS()
            results = list(ddgs.text(query, max_results=max_results))
            if fetch_content and results:
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    future_to_r = {executor.submit(fetch_page_text, r.get("href", "")): r for r in results if r.get("href")}
                    for future in concurrent.futures.as_completed(future_to_r):
                        r = future_to_r[future]
                        try:
                            text = future.result()
                        except Exception:
                            text = ""
                        if text:
                            r["body"] = text
            return results
        except Exception as e:
            if "futures" in str(e).lower():
                print(f"[search] Web search failed (threading): {e}")
                return []
            if attempt < 2:
                wait = 2 * (attempt + 1)
                print(f"[search] Web search attempt {attempt + 1} failed ({type(e).__name__}), retrying in {wait}s...")
                time.sleep(wait)
                continue
            print(f"[search] Web search failed after {attempt + 1} attempts: {e}")
            return []
    return []


def search_reddit(query, max_results=5):
    """Search Reddit — tries DDG first, falls back to direct RSS feeds.

    Returns list of dicts with: title, href, body.
    """
    # Try DDG site-scoped search first
    results = search_web(f"site:reddit.com {query}", max_results=max_results)
    if results:
        return results

    # Fallback: direct Reddit RSS
    print("[search] DDG Reddit search failed, falling back to Reddit RSS...")
    return search_reddit_rss(query, max_results=max_results)


def search_youtube(query, max_results=5):
    """Search YouTube via DuckDuckGo site-scoped query.

    Returns list of dicts with: title, href, body.
    """
    return search_web(f"site:youtube.com {query}", max_results=max_results)


def format_news_for_prompt(articles, max_chars=2000):
    """Format news articles into a compact string for LLM context."""
    if not articles:
        return ""

    lines = []
    total = 0
    for a in articles:
        title = a.get("title", "")
        body = a.get("body", "")
        date = a.get("date", "")
        source = a.get("source", "")

        line = f"- [{date}] {title}"
        if source:
            line += f" ({source})"
        if body:
            line += f"\n  {body[:200]}"

        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)

    return "\n".join(lines)


def format_search_results(results, max_body_chars=2000):
    """Format web/news search results for LLM context.

    When fetch_content=True was used, each result's body can contain up to 3000
    chars of page text.  Truncating to 200 chars (the old default) threw away
    almost all of that, which is why private-company financial reports were
    missing recent data.  Now we pass through up to max_body_chars per result so
    the LLM actually sees the fetched content.
    """
    if not results:
        return "No results found."

    lines = []
    for r in results:
        title = r.get("title", "")
        url = r.get("url") or r.get("href", "")
        body = r.get("body", "")
        date = r.get("date", "")
        source = r.get("source", "")

        line = f"**{title}**"
        if date:
            line += f" [{date}]"
        if source:
            line += f" — {source}"
        if url:
            line += f"\n  {url}"
        if body:
            line += f"\n  {body[:max_body_chars]}"
        lines.append(line)

    return "\n\n".join(lines)
