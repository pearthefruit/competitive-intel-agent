"""YouTube transcript extraction — no API key required."""

import re

from youtube_transcript_api import YouTubeTranscriptApi


def extract_video_id(url):
    """Extract YouTube video ID from various URL formats.

    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    """
    patterns = [
        r'(?:v=|youtu\.be/|embed/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def get_transcript(video_id, languages=("en",)):
    """Fetch transcript for a YouTube video.

    Returns list of {'text': str, 'start': float, 'duration': float} or None.
    """
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=list(languages))
        return transcript
    except Exception:
        # Try auto-generated captions if manual not available
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            # Try any auto-generated English transcript
            for t in transcript_list:
                if t.language_code.startswith("en"):
                    return t.fetch()
            # Fall back to first available, translated to English
            for t in transcript_list:
                try:
                    return t.translate("en").fetch()
                except Exception:
                    continue
        except Exception:
            pass
    return None


def format_transcript(transcript, max_chars=4000):
    """Format transcript segments into readable text.

    Combines segments into paragraphs, truncated to max_chars.
    """
    if not transcript:
        return ""

    # Combine all text segments
    full_text = " ".join(seg["text"] for seg in transcript)

    # Clean up common transcript artifacts
    full_text = re.sub(r'\[Music\]', '', full_text)
    full_text = re.sub(r'\[Applause\]', '', full_text)
    full_text = re.sub(r'\s+', ' ', full_text).strip()

    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "..."

    return full_text


def get_video_transcript(url, max_chars=4000):
    """Full pipeline: URL → video ID → transcript → formatted text.

    Returns (formatted_text, video_id) or (None, None) on failure.
    """
    video_id = extract_video_id(url)
    if not video_id:
        return None, None

    transcript = get_transcript(video_id)
    if not transcript:
        return None, video_id

    text = format_transcript(transcript, max_chars=max_chars)
    return text, video_id


def fetch_transcripts_from_search_results(results, max_videos=3, max_chars_per=3000):
    """Given YouTube search results, fetch transcripts for top videos.

    Returns list of dicts: {title, url, video_id, transcript}
    """
    transcripts = []
    for r in results[:max_videos * 2]:  # Try more than we need since some will fail
        url = r.get("href") or r.get("url", "")
        if "youtube.com" not in url and "youtu.be" not in url:
            continue

        title = r.get("title", "")
        text, video_id = get_video_transcript(url, max_chars=max_chars_per)

        if text:
            transcripts.append({
                "title": title,
                "url": url,
                "video_id": video_id,
                "transcript": text,
            })
            if len(transcripts) >= max_videos:
                break

    return transcripts


def format_transcripts_for_prompt(transcripts, max_total_chars=8000):
    """Format fetched transcripts for LLM context."""
    if not transcripts:
        return ""

    lines = []
    total = 0
    for t in transcripts:
        header = f"### {t['title']}\nSource: {t['url']}\n"
        content = t["transcript"]

        chunk = header + content
        if total + len(chunk) > max_total_chars:
            remaining = max_total_chars - total
            if remaining > 200:
                lines.append(header + content[:remaining - len(header)] + "...")
            break

        lines.append(chunk)
        total += len(chunk)

    return "\n\n---\n\n".join(lines)
