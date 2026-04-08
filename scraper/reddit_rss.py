"""Direct Reddit search via RSS feeds — no API key, no DDG dependency.

Parses Atom XML from Reddit's .rss endpoints. Use as a fallback when
DuckDuckGo is rate-limited, or as a primary Reddit-specific source.
"""

import re
import time
from html import unescape
from xml.etree import ElementTree as ET

import httpx

# Subreddits useful for competitive intelligence, by category
SUBREDDITS = {
    "general": ["technology", "business", "startups", "Entrepreneur", "news"],
    "finance": ["investing", "stocks", "wallstreetbets", "SecurityAnalysis", "economics"],
    "tech": ["programming", "cscareerquestions", "SaaS", "devops"],
    "industry": ["consulting", "MBA", "ProductManagement"],
    "retail_cpg": ["retail", "CPG", "FMCG", "ecommerce", "supplychain"],
}

_NS = {"atom": "http://www.w3.org/2005/Atom"}
_HEADERS = {"User-Agent": "SignalVault/1.0 (competitive intelligence research tool)"}


def _fetch_rss(url, timeout=15):
    """Fetch and parse an Atom RSS feed. Returns list of entry elements."""
    try:
        resp = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=timeout)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        return root.findall("atom:entry", _NS)
    except Exception as e:
        print(f"[reddit_rss] Fetch failed for {url}: {e}")
        return []


def _parse_entry(entry):
    """Extract fields from an Atom entry element."""
    title_el = entry.find("atom:title", _NS)
    link_el = entry.find("atom:link", _NS)
    updated_el = entry.find("atom:updated", _NS)
    content_el = entry.find("atom:content", _NS)
    author_el = entry.find("atom:author/atom:name", _NS)
    entry_id = entry.find("atom:id", _NS)

    # Strip HTML from content
    body = ""
    if content_el is not None and content_el.text:
        raw = unescape(content_el.text)
        body = re.sub(r"<[^>]+>", " ", raw)
        body = re.sub(r"\s+", " ", body).strip()
        # Remove the generic "submitted by /u/... [link] [comments]" boilerplate
        body = re.sub(r"submitted by\s+/u/\S+\s*\[link\]\s*\[comments\]", "", body).strip()

    return {
        "title": title_el.text if title_el is not None else "",
        "href": link_el.get("href") if link_el is not None else "",
        "body": body,
        "date": updated_el.text if updated_el is not None else "",
        "author": author_el.text if author_el is not None else "",
        "source": "reddit",
        "id": entry_id.text if entry_id is not None else "",
    }


def search_subreddit(subreddit, query, sort="relevance", limit=5):
    """Search within a specific subreddit via RSS.

    Args:
        subreddit: Subreddit name (without r/)
        query: Search query
        sort: 'relevance', 'new', 'hot', 'top'
        limit: Max results (Reddit caps at 25 per request)

    Returns list of dicts with: title, href, body, date, author, source.
    """
    url = (
        f"https://www.reddit.com/r/{subreddit}/search.rss"
        f"?q={query}&restrict_sr=on&sort={sort}&limit={limit}"
    )
    entries = _fetch_rss(url)
    results = []
    for e in entries:
        parsed = _parse_entry(e)
        if parsed["title"]:
            parsed["subreddit"] = subreddit
            results.append(parsed)
    return results


def search_all_reddit(query, sort="relevance", limit=10):
    """Search across all of Reddit via RSS.

    Returns list of dicts with: title, href, body, date, author, source.
    """
    url = (
        f"https://www.reddit.com/search.rss"
        f"?q={query}&sort={sort}&limit={limit}"
    )
    entries = _fetch_rss(url)
    results = []
    for e in entries:
        parsed = _parse_entry(e)
        # Skip subreddit entries (id starts with t5_)
        if parsed["id"].startswith("t5_"):
            continue
        if parsed["title"]:
            results.append(parsed)
    return results


def fetch_post_comments(post_url, limit=10):
    """Fetch top comments from a Reddit post via RSS.

    Args:
        post_url: Full Reddit post URL
        limit: Max comments to fetch

    Returns list of dicts with: title, body, author, date.
    """
    # Ensure URL ends properly for RSS
    rss_url = post_url.rstrip("/") + "/.rss?limit=" + str(limit)
    entries = _fetch_rss(rss_url)

    comments = []
    for e in entries:
        parsed = _parse_entry(e)
        # Skip the post itself (first entry is usually the OP)
        if not parsed["body"] or parsed["body"] == "":
            continue
        comments.append(parsed)

    return comments


def search_reddit_rss(query, max_results=10, subreddits=None, fetch_comments_top_n=0):
    """High-level Reddit search: searches targeted subreddits + global.

    This is the main function to use as a DDG fallback.

    Args:
        query: Search query (e.g. "Stripe competitors")
        max_results: Total results to return
        subreddits: List of subreddit names to search. If None, uses smart defaults.
        fetch_comments_top_n: Fetch comments from top N posts (0 = skip).

    Returns list of dicts with: title, href, body, date, author, source.
    """
    print(f"[reddit_rss] Searching Reddit for: {query}")

    all_results = []
    seen_ids = set()

    # Pick subreddits to search dynamically
    if subreddits is None:
        try:
            # Use an ultra-fast LLM call to guess the company's sector from the query and pick tailored subreddits
            from agents.llm import generate_text, CHEAP_CHAIN
            prompt = (
                f"You are a routing agent for a competitive intelligence system. "
                f"What are the 4 best Reddit subreddits to search for data on: '{query}'?\n"
                f"Deduce the industry (e.g., 'SaaS', 'FMCG', 'consulting', 'banking', 'retail', 'tech').\n"
                f"Reply ONLY with a comma separated list of 4 relevant subreddit names without the 'r/' prefix (e.g. 'business, SaaS, startups, investing'). Do not include any other text."
            )
            sub_text, _ = generate_text(prompt, timeout=4, chain=CHEAP_CHAIN)
            picked = [s.strip().replace("r/", "") for s in sub_text.split(",") if s.strip()]
            if picked and len(picked) <= 8:
                subreddits = picked[:4]
                print(f"[reddit_rss] AI Dynamically selected subreddits for context: {subreddits}")
            else:
                raise ValueError("LLM returned malformed list")
        except Exception as e:
            print(f"[reddit_rss] Dynamic subreddit selection skipped ({e}), using defaults.")
            subreddits = ["business", "technology", "investing", "news"]

    # Search each subreddit (limit per sub to avoid hammering)
    per_sub = max(2, max_results // len(subreddits))
    for sub in subreddits:
        results = search_subreddit(sub, query, sort="relevance", limit=per_sub)
        for r in results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                all_results.append(r)
        # Small delay between requests to be polite
        time.sleep(0.5)

    # Also search globally for broader coverage
    global_results = search_all_reddit(query, sort="relevance", limit=max_results)
    for r in global_results:
        if r["id"] not in seen_ids:
            seen_ids.add(r["id"])
            all_results.append(r)

    # Optionally fetch comments from top posts
    if fetch_comments_top_n > 0:
        for r in all_results[:fetch_comments_top_n]:
            if r.get("href"):
                time.sleep(0.5)
                comments = fetch_post_comments(r["href"], limit=5)
                if comments:
                    # Append comment text to the post body
                    comment_text = " | ".join(
                        c["body"][:200] for c in comments[:3] if c["body"]
                    )
                    if comment_text:
                        r["body"] = (r["body"] + " — Top comments: " + comment_text)[:500]

    # Trim to requested count
    all_results = all_results[:max_results]

    print(f"[reddit_rss] Found {len(all_results)} results")
    return all_results
