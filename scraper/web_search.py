"""Web search via DuckDuckGo — no API key required."""

from ddgs import DDGS


def search_news(query, max_results=10):
    """Search for recent news articles.

    Returns list of dicts with: title, url, body, date, source.
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results))
        return results
    except Exception as e:
        print(f"[search] News search failed: {e}")
        return []


def search_web(query, max_results=5):
    """General web search.

    Returns list of dicts with: title, href, body.
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return results
    except Exception as e:
        print(f"[search] Web search failed: {e}")
        return []


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
