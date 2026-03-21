"""Web search via DuckDuckGo + Reddit RSS fallback.

Primary: DuckDuckGo (no API key required).
Fallback: Reddit RSS feeds (direct, no DDG dependency).
"""

import time
from ddgs import DDGS

from scraper.reddit_rss import search_reddit_rss


def search_news(query, max_results=10):
    """Search for recent news articles.

    Returns list of dicts with: title, url, body, date, source.
    """
    for attempt in range(3):
        try:
            ddgs = DDGS()
            results = list(ddgs.news(query, max_results=max_results))
            return results
        except Exception as e:
            if "futures" in str(e).lower():
                print(f"[search] News search failed (threading): {e}")
                return []
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            print(f"[search] News search failed after {attempt + 1} attempts: {e}")
            return []
    return []


def search_web(query, max_results=5):
    """General web search.

    Returns list of dicts with: title, href, body.
    """
    for attempt in range(3):
        try:
            ddgs = DDGS()
            results = list(ddgs.text(query, max_results=max_results))
            return results
        except Exception as e:
            if "futures" in str(e).lower():
                print(f"[search] Web search failed (threading): {e}")
                return []
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
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


def format_search_results(results):
    """Format web/news search results for chat display."""
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
            line += f"\n  {body[:200]}"
        lines.append(line)

    return "\n\n".join(lines)
