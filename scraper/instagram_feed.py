"""Instagram private API feed fetcher for @dualassets and similar accounts.

No credentials required — uses public mobile API with standard browser headers.
Rate limit handling: raises RuntimeError on 429 so caller can surface to user.
"""

import re
import time
import requests

_HARDCODED_IDS = {
    "dualassets": "76923923363",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "x-ig-app-id": "936619743392459",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.instagram.com/",
}

_SESSION = None


def _get_session():
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update(_HEADERS)
        # Prime cookies by visiting profile page
        try:
            _SESSION.get("https://www.instagram.com/", timeout=10)
        except Exception:
            pass
    return _SESSION


def resolve_user_id(handle):
    """Resolve Instagram handle to numeric user_id.

    Scrapes profile page for embedded JSON. Falls back to hardcoded table.
    Returns user_id string or None.
    """
    if handle in _HARDCODED_IDS:
        fallback = _HARDCODED_IDS[handle]
    else:
        fallback = None

    try:
        sess = _get_session()
        resp = sess.get(f"https://www.instagram.com/{handle}/", timeout=15)
        if resp.status_code != 200:
            return fallback

        text = resp.text
        # Try structured JSON patterns first
        m = re.search(r'"user_id":"(\d+)"', text)
        if not m:
            m = re.search(r'"pk":"(\d+)"', text)
        if not m:
            m = re.search(r'"pk":(\d+)', text)
        if m:
            return m.group(1)
    except Exception as e:
        print(f"[ig_feed] resolve_user_id error for {handle}: {e}")

    return fallback


def fetch_feed(user_id, count=12, max_id=None):
    """Fetch one page of feed for a user.

    Returns (posts, next_max_id, more_available).
    Each post dict: {shortcode, url, caption, taken_at, media_type}.
    Only includes media_type == 2 (video/Reels).
    Raises RuntimeError on rate limit or HTTP error.
    """
    url = f"https://i.instagram.com/api/v1/feed/user/{user_id}/"
    params = {"count": count}
    if max_id:
        params["max_id"] = max_id

    try:
        sess = _get_session()
        resp = sess.get(url, params=params, timeout=20)
    except Exception as e:
        raise RuntimeError(f"Instagram request failed: {e}")

    if resp.status_code == 429:
        raise RuntimeError("Instagram rate limit hit (429). Please wait and retry.")
    if resp.status_code != 200:
        raise RuntimeError(f"Instagram API returned {resp.status_code}")

    try:
        data = resp.json()
    except Exception:
        raise RuntimeError("Instagram API returned non-JSON response")

    items = data.get("items") or []
    posts = []
    for item in items:
        if item.get("media_type") != 2:  # 1=photo, 2=video, 8=carousel
            continue
        shortcode = item.get("code") or item.get("shortcode") or ""
        caption_obj = item.get("caption")
        caption = caption_obj.get("text", "") if isinstance(caption_obj, dict) else ""
        posts.append({
            "shortcode": shortcode,
            "url": f"https://www.instagram.com/reel/{shortcode}/",
            "caption": caption or "",
            "taken_at": item.get("taken_at", 0),
            "media_type": item.get("media_type", 2),
        })

    next_max_id = data.get("next_max_id")
    more_available = bool(data.get("more_available", False))
    return posts, next_max_id, more_available


def fetch_new_posts(user_id, since_timestamp=None, max_posts=20):
    """Fetch posts newer than since_timestamp (unix int).

    Paginates until since_timestamp boundary or max_posts reached.
    Returns list in chronological order (oldest first).
    """
    collected = []
    max_id = None

    while len(collected) < max_posts:
        posts, next_max_id, more_available = fetch_feed(user_id, count=12, max_id=max_id)

        if not posts:
            break

        for post in posts:
            if since_timestamp and post["taken_at"] <= since_timestamp:
                # Reached the cutoff — stop pagination
                posts_sorted = sorted(collected, key=lambda p: p["taken_at"])
                return posts_sorted[:max_posts]
            collected.append(post)
            if len(collected) >= max_posts:
                break

        if not more_available or not next_max_id:
            break

        max_id = next_max_id
        time.sleep(0.5)  # polite pause between pages

    return sorted(collected, key=lambda p: p["taken_at"])
