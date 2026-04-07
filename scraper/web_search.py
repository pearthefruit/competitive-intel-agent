"""Web search via DuckDuckGo + Reddit RSS fallback.

Primary: DuckDuckGo (no API key required).
Fallback: Reddit RSS feeds (direct, no DDG dependency).
"""

import re
import time
import threading
import concurrent.futures
from urllib.parse import urlparse
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

def _extract_article_bs4(html, max_chars=3000):
    """Extract article text using semantic selectors, then full-page fallback."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()

    # Try semantic article containers first (ordered by specificity)
    for selector in ["article", "[role='main'] article", "main article",
                      ".entry-content", ".post-content", ".article-body",
                      ".article-content", ".story-body", "#article-body",
                      "main", "[role='main']"]:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator=" ", strip=True)
            if len(text) > 200:
                return text[:max_chars]

    # Full-page fallback
    text = soup.get_text(separator=" ", strip=True)
    return text[:max_chars] if text else ""


def fetch_page_text(url, max_chars=3000):
    """Fetch and extract article text from a URL.

    Extraction chain: trafilatura → BS4 semantic selectors → BS4 full page.
    HTTP chain: httpx → curl_cffi (browser TLS impersonation) on failure.
    """
    if not url.startswith("http"):
        return ""

    html = ""
    # --- HTTP fetch ---
    try:
        with httpx.Client(headers=REQUEST_HEADERS, timeout=12, follow_redirects=True) as client:
            resp = client.get(url)
            ct = resp.headers.get("content-type", "").lower()
            if resp.status_code == 200 and "text/html" in ct:
                html = resp.text
            else:
                print(f"[search] httpx {resp.status_code} for {url[:80]}, trying curl_cffi")
    except Exception as e:
        print(f"[search] httpx failed for {url[:80]}: {e}")

    # Fallback: curl_cffi with browser TLS impersonation
    if not html:
        try:
            from curl_cffi import requests as cffi_requests
            resp = cffi_requests.get(url, impersonate="chrome", timeout=15, allow_redirects=True)
            ct = resp.headers.get("content-type", "").lower()
            if resp.status_code == 200 and "text/html" in ct:
                html = resp.text
                print(f"[search] curl_cffi fetched {url[:80]}")
            else:
                print(f"[search] curl_cffi {resp.status_code} for {url[:80]}")
        except Exception as e:
            print(f"[search] curl_cffi failed for {url[:80]}: {e}")

    if not html:
        return ""

    # --- Content extraction ---
    # Try trafilatura first
    try:
        import trafilatura
        result = trafilatura.extract(html, include_comments=False, include_tables=True)
        # Validate: trafilatura sometimes returns nav/menu garbage
        if result and len(result) > 200:
            # Quick sanity check: if >40% of lines are very short (<15 chars),
            # it's probably nav links, not article text
            lines = result.strip().split("\n")
            short_lines = sum(1 for l in lines if len(l.strip()) < 15)
            if len(lines) < 5 or short_lines / len(lines) < 0.4:
                print(f"[search] Trafilatura extracted {len(result)} chars from {url[:80]}")
                return result[:max_chars]
            else:
                print(f"[search] Trafilatura returned nav-like content for {url[:80]}, using BS4")
    except Exception as e:
        print(f"[search] Trafilatura failed for {url[:80]}: {e}")

    # Fallback: BS4 semantic extraction
    text = _extract_article_bs4(html, max_chars)
    if text:
        print(f"[search] BS4 extracted {len(text)} chars from {url[:80]}")
    return text


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


def search_tiktok(query, max_results=5):
    """Search TikTok via DuckDuckGo site-scoped query.

    Returns list of dicts with: title, href, body.
    """
    return search_web(f"site:tiktok.com {query}", max_results=max_results)


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


# --- Dedup utilities ---

_STRIP_PREFIXES = re.compile(
    r"^(breaking:\s*|exclusive:\s*|update:\s*|just in:\s*|watch:\s*|"
    r"analysis:\s*|opinion:\s*|report:\s*)",
    re.IGNORECASE,
)

# Source quality ranking — higher is better (wire services > outlets > blogs)
_SOURCE_QUALITY = {
    "reuters.com": 10, "bloomberg.com": 10,
    "wsj.com": 9, "ft.com": 9, "apnews.com": 9,
    "nytimes.com": 8, "washingtonpost.com": 8,
    "cnbc.com": 7, "bbc.com": 7, "bbc.co.uk": 7,
    "seekingalpha.com": 6, "techcrunch.com": 6, "theinformation.com": 6,
    "theverge.com": 5, "arstechnica.com": 5, "wired.com": 5,
}


def _normalize_title(title):
    """Normalize a title for dedup: strip prefixes, punctuation, lowercase."""
    t = _STRIP_PREFIXES.sub("", title.strip())
    t = re.sub(r"[^\w\s]", "", t).lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _source_quality(result):
    """Score a result by source domain quality (higher = better)."""
    url = result.get("url") or result.get("href", "")
    if not url:
        return 3
    try:
        host = urlparse(url).netloc.lower()
        host = re.sub(r"^(www\d?\.|m\.|mobile\.)", "", host)
        return _SOURCE_QUALITY.get(host, 3)
    except Exception:
        return 3


def dedup_results(results):
    """Deduplicate search results using normalized title matching.

    For wire stories reprinted across outlets, keeps the highest-quality source.
    Returns deduplicated list preserving original order of kept items.
    """
    if not results:
        return []

    clusters = {}  # normalized_title -> list of (index, result)
    for i, r in enumerate(results):
        title = r.get("title", "")
        if not title:
            continue
        norm = _normalize_title(title)
        if not norm:
            continue
        clusters.setdefault(norm, []).append((i, r))

    keep_indices = set()
    for norm_title, group in clusters.items():
        if len(group) == 1:
            keep_indices.add(group[0][0])
        else:
            # Keep the highest-quality source
            group.sort(key=lambda x: _source_quality(x[1]), reverse=True)
            keep_indices.add(group[0][0])

    # Also keep results with no title (rare)
    for i, r in enumerate(results):
        if not r.get("title"):
            keep_indices.add(i)

    deduped = [results[i] for i in sorted(keep_indices)]
    if len(deduped) < len(results):
        print(f"[search] Dedup: {len(results)} → {len(deduped)} results")
    return deduped
