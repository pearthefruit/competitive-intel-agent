"""TikTok content extraction via yt-dlp — metadata, descriptions, and auto-captions.

Discovery: DuckDuckGo site:tiktok.com search (handled by web_search.search_tiktok).
Extraction: yt-dlp subprocess for metadata + auto-generated subtitles.

No authentication required. yt-dlp must be installed (pip install yt-dlp).
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path


def _is_tiktok_video_url(url):
    """Check if a URL is a direct TikTok video link (not a discover/search page)."""
    if "/discover/" in url or "/search" in url or "/tag/" in url:
        return False
    return bool(re.search(r'tiktok\.com/(@[\w.]+/video/\d+|vm\.tiktok\.com/)', url))


def get_tiktok_metadata(url, timeout=30):
    """Fetch TikTok video metadata via yt-dlp --dump-json.

    Returns dict with: title, description, uploader, view_count, like_count,
    duration, upload_date, tags, has_subtitles, url. Returns None on failure.
    """
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", "--no-warnings", url],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            print(f"[tiktok] yt-dlp failed for {url[:80]}: {result.stderr[:200]}")
            return None

        data = json.loads(result.stdout)

        return {
            "title": data.get("title", ""),
            "description": data.get("description", ""),
            "uploader": data.get("uploader", ""),
            "uploader_id": data.get("uploader_id", ""),
            "view_count": data.get("view_count"),
            "like_count": data.get("like_count"),
            "comment_count": data.get("comment_count"),
            "duration": data.get("duration"),
            "upload_date": data.get("upload_date", ""),
            "tags": data.get("tags", []),
            "url": data.get("webpage_url", url),
            "has_subtitles": bool(data.get("subtitles") or data.get("automatic_captions")),
            "_subtitle_langs": list((data.get("subtitles") or {}).keys()) + list((data.get("automatic_captions") or {}).keys()),
        }

    except subprocess.TimeoutExpired:
        print(f"[tiktok] yt-dlp timeout for {url[:80]}")
        return None
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"[tiktok] yt-dlp error for {url[:80]}: {e}")
        return None
    except Exception as e:
        print(f"[tiktok] Unexpected error for {url[:80]}: {e}")
        return None


def get_tiktok_subtitles(url, lang="en", timeout=30):
    """Download auto-generated subtitles for a TikTok video.

    Returns subtitle text as a string, or None if unavailable.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = str(Path(tmpdir) / "tiktok_sub")
        try:
            result = subprocess.run(
                [
                    "yt-dlp",
                    "--skip-download",
                    "--write-auto-subs",
                    "--sub-lang", lang,
                    "--sub-format", "vtt",
                    "--no-warnings",
                    "-o", out_path,
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            # Find the subtitle file (yt-dlp appends language code)
            sub_files = list(Path(tmpdir).glob("*.vtt")) + list(Path(tmpdir).glob("*.srt"))
            if not sub_files:
                return None

            raw = sub_files[0].read_text(encoding="utf-8", errors="replace")
            return _parse_vtt(raw)

        except subprocess.TimeoutExpired:
            print(f"[tiktok] Subtitle download timeout for {url[:80]}")
            return None
        except Exception as e:
            print(f"[tiktok] Subtitle error for {url[:80]}: {e}")
            return None


def _parse_vtt(vtt_text):
    """Parse VTT/SRT subtitle text into clean prose."""
    lines = []
    for line in vtt_text.splitlines():
        line = line.strip()
        # Skip VTT headers, timestamps, and empty lines
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        if re.match(r"^\d+$", line):  # SRT sequence numbers
            continue
        if re.match(r"\d{2}:\d{2}", line):  # Timestamps
            continue
        # Strip VTT positioning tags
        line = re.sub(r"<[^>]+>", "", line)
        if line:
            lines.append(line)

    # Deduplicate consecutive identical lines (VTT often repeats)
    deduped = []
    for line in lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)

    text = " ".join(deduped)
    # Clean up whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) > 10 else None


def get_tiktok_content(url, max_chars=3000):
    """Full pipeline: URL → metadata + subtitles → formatted content.

    Returns dict: {title, url, uploader, description, transcript, stats, tags}
    or None on failure.
    """
    metadata = get_tiktok_metadata(url)
    if not metadata:
        return None

    # Try subtitles if available
    transcript = None
    if metadata.get("has_subtitles"):
        transcript = get_tiktok_subtitles(url)
        if transcript and len(transcript) > max_chars:
            transcript = transcript[:max_chars] + "..."

    # Format stats string
    stats_parts = []
    if metadata.get("view_count") is not None:
        stats_parts.append(f"{metadata['view_count']:,} views")
    if metadata.get("like_count") is not None:
        stats_parts.append(f"{metadata['like_count']:,} likes")
    if metadata.get("comment_count") is not None:
        stats_parts.append(f"{metadata['comment_count']:,} comments")

    # Format upload date
    date_str = metadata.get("upload_date", "")
    if date_str and len(date_str) == 8:
        date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    return {
        "title": metadata.get("title", ""),
        "url": metadata.get("url", url),
        "uploader": metadata.get("uploader", ""),
        "description": metadata.get("description", "")[:1000],
        "transcript": transcript,
        "stats": " | ".join(stats_parts),
        "tags": metadata.get("tags", []),
        "date": date_str,
    }


def fetch_tiktok_from_search_results(results, max_videos=5, max_chars_per=3000):
    """Given DDG search results, extract TikTok content for video URLs.

    Returns list of dicts: {title, url, uploader, description, transcript, stats, tags, date}
    """
    extracted = []
    for r in results[:max_videos * 2]:  # Try more than needed since some fail
        url = r.get("href") or r.get("url", "")
        if not _is_tiktok_video_url(url):
            continue

        content = get_tiktok_content(url, max_chars=max_chars_per)
        if content:
            # Use DDG title as fallback if yt-dlp title is empty
            if not content["title"]:
                content["title"] = r.get("title", "TikTok video")
            extracted.append(content)
            if len(extracted) >= max_videos:
                break

    return extracted


def format_tiktok_for_prompt(tiktok_items, max_total_chars=6000):
    """Format extracted TikTok content for LLM context."""
    if not tiktok_items:
        return ""

    lines = []
    total = 0
    for t in tiktok_items:
        header = f"### {t['title']}\n"
        header += f"Source: {t['url']}\n"
        if t.get("uploader"):
            header += f"Creator: @{t['uploader']}\n"
        if t.get("stats"):
            header += f"Stats: {t['stats']}\n"
        if t.get("date"):
            header += f"Date: {t['date']}\n"
        if t.get("tags"):
            header += f"Tags: {', '.join(t['tags'][:10])}\n"

        body = ""
        if t.get("transcript"):
            body += f"\nTranscript:\n{t['transcript']}"
        elif t.get("description"):
            body += f"\nDescription:\n{t['description']}"

        chunk = header + body
        if total + len(chunk) > max_total_chars:
            remaining = max_total_chars - total
            if remaining > 200:
                lines.append(chunk[:remaining] + "...")
            break

        lines.append(chunk)
        total += len(chunk)

    return "\n\n---\n\n".join(lines)
