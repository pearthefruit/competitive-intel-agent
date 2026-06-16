"""Instagram feed fetcher for @dualassets and similar accounts.

Instagram's private API requires a valid session cookie (sessionid).
Export cookies from your logged-in browser and set:
    INSTAGRAM_COOKIES_FILE=C:\\path\\to\\cookies.txt

Use the "Get cookies.txt LOCALLY" Chrome extension or equivalent to export
in Netscape format. The sessionid cookie must be present.
"""

import http.cookiejar
import os
import re
import subprocess
import tempfile
import time

import requests

# Module-level Whisper model cache — keyed by model_size string.
_whisper_model_cache = {}

_HARDCODED_IDS = {
    "dualassets": "76923923363",
}

_IG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "x-ig-app-id": "936619743392459",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.instagram.com/",
}


def _build_session():
    """Build a requests session with Instagram headers and cookies from file."""
    sess = requests.Session()
    sess.headers.update(_IG_HEADERS)

    cookies_path = os.environ.get("INSTAGRAM_COOKIES_FILE")
    if cookies_path and os.path.exists(cookies_path):
        jar = http.cookiejar.MozillaCookieJar()
        try:
            jar.load(cookies_path, ignore_discard=True, ignore_expires=True)
            for c in jar:
                if "instagram.com" in c.domain:
                    sess.cookies.set(c.name, c.value, domain=c.domain)
        except Exception as e:
            print(f"[ig_feed] Could not load cookies from {cookies_path}: {e}")

    # Prime csrf/rur cookies from homepage
    try:
        sess.get("https://www.instagram.com/", timeout=10)
    except Exception:
        pass

    return sess


def resolve_user_id(handle):
    """Return known numeric user_id for handle, or the handle itself as fallback."""
    if handle in _HARDCODED_IDS:
        return _HARDCODED_IDS[handle]

    try:
        sess = _build_session()
        resp = sess.get(f"https://www.instagram.com/{handle}/", timeout=15)
        if resp.status_code == 200:
            for pattern in (r'"user_id":"(\d+)"', r'"pk":"(\d+)"', r'"pk":(\d+)'):
                m = re.search(pattern, resp.text)
                if m:
                    return m.group(1)
    except Exception as e:
        print(f"[ig_feed] resolve_user_id error for {handle}: {e}")

    return handle


def _check_status(resp):
    if resp.status_code == 401:
        raise RuntimeError(
            "Instagram session expired or invalid (401). Re-export your browser cookies and "
            "update INSTAGRAM_COOKIES_FILE."
        )
    if resp.status_code == 429:
        raise RuntimeError("Instagram rate limit hit (429). Please wait a few minutes and retry.")
    if resp.status_code != 200:
        raise RuntimeError(f"Instagram API returned {resp.status_code}")


def _parse_media_item(item):
    """Extract post dict from a media item object. Returns None if not a video."""
    media_type = item.get("media_type")
    # 2 = video/Reel; 8 = carousel — check if carousel contains video
    if media_type == 8:
        carousel = item.get("carousel_media") or []
        if not any(m.get("media_type") == 2 for m in carousel):
            return None
    elif media_type != 2:
        return None

    shortcode = item.get("code") or item.get("shortcode") or ""
    caption_obj = item.get("caption")
    caption = caption_obj.get("text", "") if isinstance(caption_obj, dict) else ""
    return {
        "shortcode": shortcode,
        "url": f"https://www.instagram.com/reel/{shortcode}/",
        "caption": caption or "",
        "taken_at": item.get("taken_at", 0),
        "media_type": 2,
    }


def _fetch_clips_page(sess, user_id, max_id=None):
    """Fetch one page from the Reels/Clips endpoint (separate from regular feed).

    Returns (posts, next_max_id, more_available).
    """
    url = "https://i.instagram.com/api/v1/clips/user/"
    body = {
        "target_user_id": str(user_id),
        "page_size": "12",
        "include_feed_video": "true",
    }
    if max_id:
        body["max_id"] = str(max_id)

    try:
        resp = sess.post(url, data=body, timeout=20)
    except Exception as e:
        raise RuntimeError(f"Instagram clips request failed: {e}")

    _check_status(resp)

    try:
        data = resp.json()
    except Exception:
        raise RuntimeError("Instagram API returned non-JSON response")

    raw_items = data.get("items") or []
    posts = []
    for entry in raw_items:
        # Clips endpoint wraps each item: {"media": {...}}
        item = entry.get("media") or entry
        post = _parse_media_item(item)
        if post:
            posts.append(post)

    paging = data.get("paging_info") or {}
    next_max_id = paging.get("max_id") or data.get("next_max_id")
    more_available = bool(paging.get("more_available", data.get("more_available", False)))
    print(f"[ig_feed] clips page: {len(raw_items)} items → {len(posts)} reels, more={more_available}")
    return posts, next_max_id, more_available


def fetch_new_posts(handle, since_timestamp=None, max_posts=20):
    """Fetch Reels newer than since_timestamp (unix int) via the Clips endpoint.

    Requires INSTAGRAM_COOKIES_FILE env var pointing to a Netscape cookies.txt
    exported from a logged-in browser session.

    Returns list in chronological order (oldest first).
    """
    sess = _build_session()

    if not sess.cookies.get("sessionid"):
        raise RuntimeError(
            "Instagram requires login. Export your browser cookies:\n"
            "1. Install 'Get cookies.txt LOCALLY' Chrome extension\n"
            "2. Log into Instagram, then click the extension and export\n"
            "3. Set INSTAGRAM_COOKIES_FILE=C:\\path\\to\\cookies.txt in your .env"
        )

    user_id = resolve_user_id(handle)
    collected = []
    max_id = None

    while len(collected) < max_posts:
        posts, next_max_id, more_available = _fetch_clips_page(sess, user_id, max_id=max_id)

        if not posts:
            break

        for post in posts:
            if since_timestamp and post["taken_at"] and post["taken_at"] <= since_timestamp:
                return sorted(collected, key=lambda p: p["taken_at"])[:max_posts]
            collected.append(post)
            if len(collected) >= max_posts:
                break

        if not more_available or not next_max_id:
            break

        max_id = next_max_id
        time.sleep(0.5)

    return sorted(collected, key=lambda p: p["taken_at"])


def whisper_enabled() -> bool:
    """Return True if Whisper transcription is both enabled (via env var) and importable."""
    if os.environ.get("WHISPER_ENABLED", "").lower() not in ("1", "true"):
        return False
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe_reel(url, model_size=None) -> "str | None":
    """Download audio from an Instagram reel and transcribe it via OpenAI Whisper.

    The caller is responsible for checking whisper_enabled() before calling this.
    The Whisper model is cached at module level — first call is slow, subsequent fast.
    """
    if model_size is None:
        model_size = os.environ.get("WHISPER_MODEL", "base")

    tmp_path = tempfile.mktemp(suffix=".mp3")
    try:
        cmd = [
            "yt-dlp", "-x", "--audio-format", "mp3",
            "--no-playlist", "--quiet", "--no-warnings",
            "-o", tmp_path, url,
        ]
        result = subprocess.run(cmd, timeout=120, capture_output=True)
        if result.returncode != 0:
            print(f"[instagram_feed] yt-dlp failed for {url}: {result.stderr.decode(errors='replace')[:300]}")
            return None

        import whisper
        if model_size not in _whisper_model_cache:
            print(f"[instagram_feed] Loading Whisper model '{model_size}' (first use)...")
            _whisper_model_cache[model_size] = whisper.load_model(model_size)
        model = _whisper_model_cache[model_size]

        transcript_text = model.transcribe(tmp_path)["text"]
        return transcript_text.strip() or None

    except Exception as e:
        print(f"[instagram_feed] transcribe_reel error for {url}: {e}")
        return None
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
