"""Hacker News search via Algolia API — no API key required.

Official HN search API: https://hn.algolia.com/api
Great for tech company news, product launches, and developer sentiment.
"""

import re
from html import unescape

import httpx

_BASE = "https://hn.algolia.com/api/v1"
_HEADERS = {"User-Agent": "SignalForge/1.0 (competitive intelligence research tool)"}


def _clean_html(text):
    """Strip HTML tags and decode entities from HN comment text."""
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def search_stories(query, max_results=10, sort="relevance"):
    """Search HN stories (submissions).

    Args:
        query: Search query (e.g. "Stripe payments")
        max_results: Number of results (max 50)
        sort: 'relevance' (most popular) or 'date' (most recent)

    Returns list of dicts with: title, href, body, date, points, comments, source, hn_id.
    """
    endpoint = f"{_BASE}/search" if sort == "relevance" else f"{_BASE}/search_by_date"
    params = {
        "query": query,
        "tags": "story",
        "hitsPerPage": min(max_results, 50),
    }

    try:
        resp = httpx.get(endpoint, params=params, headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"[hackernews] Search failed: {resp.status_code}")
            return []

        data = resp.json()
        results = []
        for hit in data.get("hits", []):
            title = hit.get("title", "")
            # HN stories can link externally or be self-posts (Ask HN, Show HN)
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
            points = hit.get("points", 0)
            num_comments = hit.get("num_comments", 0)

            results.append({
                "title": title,
                "href": url,
                "body": f"{points} points, {num_comments} comments on Hacker News",
                "date": hit.get("created_at", ""),
                "points": points,
                "num_comments": num_comments,
                "source": "hackernews",
                "hn_id": hit.get("objectID", ""),
                "hn_url": f"https://news.ycombinator.com/item?id={hit['objectID']}",
            })

        return results

    except Exception as e:
        print(f"[hackernews] Search error: {e}")
        return []


def fetch_comments(story_id, max_comments=10):
    """Fetch top comments for an HN story.

    Args:
        story_id: HN story objectID (e.g. '29387264')
        max_comments: Max comments to return

    Returns list of dicts with: body, author, date, points.
    """
    params = {
        "tags": f"comment,story_{story_id}",
        "hitsPerPage": min(max_comments, 50),
    }

    try:
        resp = httpx.get(f"{_BASE}/search", params=params, headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            return []

        data = resp.json()
        comments = []
        for hit in data.get("hits", []):
            text = _clean_html(hit.get("comment_text", ""))
            if text:
                comments.append({
                    "body": text,
                    "author": hit.get("author", ""),
                    "date": hit.get("created_at", ""),
                    "points": hit.get("points", 0),
                })

        return comments

    except Exception as e:
        print(f"[hackernews] Comment fetch error: {e}")
        return []


def search_hackernews(query, max_results=10, sort="relevance", fetch_comments_top_n=0):
    """High-level HN search with optional comment fetching.

    Args:
        query: Search query
        max_results: Number of stories to return
        sort: 'relevance' or 'date'
        fetch_comments_top_n: Fetch comments from top N stories (0 = skip)

    Returns list of dicts with: title, href, body, date, points, source.
    """
    print(f"[hackernews] Searching HN for: {query}")
    stories = search_stories(query, max_results=max_results, sort=sort)

    if fetch_comments_top_n > 0:
        for story in stories[:fetch_comments_top_n]:
            hn_id = story.get("hn_id")
            if hn_id:
                comments = fetch_comments(hn_id, max_comments=5)
                if comments:
                    comment_text = " | ".join(
                        c["body"][:200] for c in comments[:3] if c["body"]
                    )
                    if comment_text:
                        story["body"] = (
                            story["body"] + " — Top comments: " + comment_text
                        )[:600]

    print(f"[hackernews] Found {len(stories)} stories")
    return stories
