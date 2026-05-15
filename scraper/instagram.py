"""Instagram profile scraper via instaloader — fetches recent post captions for sentiment analysis.

Requires: pip install instaloader

No authentication required for public profiles, but Instagram rate-limits anonymous
requests aggressively. Designed to fetch ~10-15 recent posts per run with graceful
failure if the account is private or rate-limited.

Discovery: web search for "{company} site:instagram.com" to find the handle.
Extraction: instaloader Profile.from_username + get_posts() iterator.
"""

import re
from itertools import islice

from scraper.web_search import search_web


def find_instagram_handle(company):
    """Search the web to find a company's Instagram handle.

    Returns the handle string (no @) or None.
    """
    results = search_web(f"{company} site:instagram.com", max_results=5)
    for r in results:
        url = r.get("href") or r.get("url") or ""
        handle = _extract_handle_from_url(url)
        if handle and handle not in ("p", "explore", "reel", "stories", "tv"):
            return handle

    # Fallback: DDG title/body snippet often contains "@handle"
    for r in results:
        text = (r.get("title") or "") + " " + (r.get("body") or "")
        m = re.search(r"instagram\.com/([A-Za-z0-9_.]{2,30})", text)
        if m:
            handle = m.group(1)
            if handle not in ("p", "explore", "reel", "stories", "tv"):
                return handle

    return None


def _extract_handle_from_url(url):
    """Extract Instagram handle from a URL like instagram.com/handle or instagram.com/handle/."""
    m = re.search(r"instagram\.com/([A-Za-z0-9_.]{2,30})/?(?:\?|$)", url)
    return m.group(1) if m else None


def fetch_instagram_posts(handle, max_posts=15, timeout_posts=20):
    """Fetch recent posts from a public Instagram profile.

    Args:
        handle: Instagram username (no @)
        max_posts: Maximum posts to return
        timeout_posts: Stop iterating after this many posts attempted (guards against slow feeds)

    Returns list of dicts: {url, title, caption, date, likes, post_type, hashtags}
    """
    try:
        import instaloader
    except ImportError:
        print("[instagram] instaloader not installed — run: pip install instaloader")
        return []

    try:
        L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            quiet=True,
        )

        profile = instaloader.Profile.from_username(L.context, handle)

        if profile.is_private:
            print(f"[instagram] Profile @{handle} is private — skipping")
            return []

        posts = []
        for post in islice(profile.get_posts(), timeout_posts):
            caption = post.caption or ""
            if not caption and post.typename == "GraphVideo":
                caption = post.title or ""

            hashtags = list(post.caption_hashtags) if caption else []

            posts.append({
                "url": f"https://www.instagram.com/p/{post.shortcode}/",
                "title": f"@{handle} — {post.date_utc.strftime('%Y-%m-%d')} ({post.typename})",
                "caption": caption,
                "date": post.date_utc.isoformat(),
                "likes": post.likes,
                "post_type": post.typename,
                "hashtags": hashtags[:20],
                "source": "instagram",
            })

            if len(posts) >= max_posts:
                break

        print(f"[instagram] Fetched {len(posts)} posts from @{handle}")
        return posts

    except Exception as e:
        err = str(e)
        if "404" in err or "not found" in err.lower():
            print(f"[instagram] Profile @{handle} not found")
        elif "login" in err.lower() or "checkpoint" in err.lower():
            print(f"[instagram] Login required for @{handle} — profile may be restricted")
        elif "too many" in err.lower() or "rate" in err.lower():
            print(f"[instagram] Rate limited by Instagram for @{handle}")
        else:
            print(f"[instagram] Error fetching @{handle}: {e}")
        return []


def format_instagram_for_prompt(posts):
    """Format Instagram posts as text for an LLM prompt.

    Returns a markdown string.
    """
    if not posts:
        return ""

    lines = ["### Instagram Posts\n"]
    for p in posts:
        date = p.get("date", "")[:10]
        likes = p.get("likes")
        likes_str = f"  ({likes:,} likes)" if likes else ""
        caption = (p.get("caption") or "").strip()
        hashtags = p.get("hashtags", [])

        lines.append(f"**{date}**{likes_str}")
        if caption:
            lines.append(caption[:800])
        if hashtags:
            lines.append("Tags: " + " ".join(f"#{h}" for h in hashtags[:10]))
        lines.append("")

    return "\n".join(lines)
