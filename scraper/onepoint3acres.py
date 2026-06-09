"""1Point3Acres (一亩三分地) interview experience scraper.

Fetches recent interview posts for a company from the 1Point3Acres interview section.
No authentication required — uses the public Next.js SSR data embedded in the HTML.
Posts include both Chinese titles and English translations provided by the site.

Useful for: tech company sentiment, interview difficulty signals, hiring trends
among Chinese/international tech workers.
"""

import json
import re
import time
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}

# Map numeric job category IDs to labels (observed from the site)
JOB_CATEGORIES = {
    1: "Software Engineer",
    2: "Data Scientist",
    3: "Product Manager",
    4: "Quantitative/Finance",
    5: "Data Engineer",
    6: "Hardware/EE",
    7: "Mechanical Engineer",
    8: "Business Analyst",
    9: "Design/UX",
    10: "Marketing",
    11: "Other",
    12: "Machine Learning",
}

JOB_TYPES = {
    1: "Fulltime",
    2: "Intern",
}

FRESH_STATUS = {
    1: "New Grad",
    2: "Experienced",
}


def _generate_slugs(company_name):
    """Generate candidate URL slugs for 1p3a.

    1p3a slugs are inconsistent — 'Jane Street' could be 'jane-street' or 'janestreet'.
    Returns multiple variants to try.
    """
    name = company_name.strip().lower()
    # Remove common suffixes
    for suffix in [" inc", " inc.", " co", " co.", " corp", " llc", " ltd", " & company", " & co"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()

    slugs = []
    # Hyphenated: "jane-street"
    slugs.append(re.sub(r"[^a-z0-9]+", "-", name).strip("-"))
    # No separator: "janestreet"
    slugs.append(re.sub(r"[^a-z0-9]", "", name))
    # As-is lowercase (single-word companies)
    if " " not in name:
        slugs.append(name)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for s in slugs:
        if s and s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def _fetch_post_content(post_url):
    """Fetch the full interview description from an individual post page.

    1point3acres embeds content in __NEXT_DATA__ just like the listing page.
    Returns the content string, or None if unavailable (login-gated or error).
    """
    try:
        resp = httpx.get(post_url, headers=_HEADERS, follow_redirects=True, timeout=12)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        next_data_tag = soup.find("script", id="__NEXT_DATA__")
        if next_data_tag and next_data_tag.string:
            try:
                page_data = json.loads(next_data_tag.string)
                queries = (
                    page_data.get("props", {})
                    .get("pageProps", {})
                    .get("trpcState", {})
                    .get("json", {})
                    .get("queries", [])
                )
                for q in queries:
                    state_data = q.get("state", {}).get("data", {})
                    if not isinstance(state_data, dict):
                        continue
                    # Direct content fields
                    for field in ("content", "body", "message", "description", "text"):
                        val = state_data.get(field)
                        if isinstance(val, str) and len(val) > 80:
                            return val
                    # Nested under common keys
                    for key in ("thread", "post", "data", "item"):
                        nested = state_data.get(key)
                        if isinstance(nested, dict):
                            for field in ("content", "body", "message", "description"):
                                val = nested.get(field)
                                if isinstance(val, str) and len(val) > 80:
                                    return val
            except Exception:
                pass

        # BeautifulSoup fallback — look for main content container
        for selector in (".message-body", ".post-message", ".postcontent",
                         "[class*='message']", "[class*='content']", "article", "main"):
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    return text[:8000]
        return None
    except Exception:
        return None


def _fetch_posts_for_slug(slug):
    """Try fetching interview posts for a single slug. Returns (posts, total) or ([], 0)."""
    url = f"https://www.1point3acres.com/interview/company/{slug}"
    try:
        resp = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=15)
        if resp.status_code != 200:
            return [], 0

        soup = BeautifulSoup(resp.text, "html.parser")
        next_data_tag = soup.find("script", id="__NEXT_DATA__")
        if not next_data_tag or not next_data_tag.string:
            return [], 0

        page_data = json.loads(next_data_tag.string)
        queries = (
            page_data.get("props", {})
            .get("pageProps", {})
            .get("trpcState", {})
            .get("json", {})
            .get("queries", [])
        )

        for q in queries:
            qkey = q.get("queryKey", [])
            if any("getInterviewThreadList" in str(k) for k in qkey):
                data = q.get("state", {}).get("data", {})
                if isinstance(data, dict):
                    return data.get("data", []), data.get("total", 0)
        return [], 0
    except Exception:
        return [], 0


def search_1point3acres(company_name, max_results=24):
    """Fetch recent interview posts for a company from 1Point3Acres.

    Returns list of dicts with: title, href, body, date, source.
    These match the format used by other scrapers in the sentiment pipeline.
    """
    slugs = _generate_slugs(company_name)

    print(f"[1point3acres] Fetching interview posts for {company_name} (slugs: {', '.join(slugs)})...")

    try:
        # Try each slug variant until one returns results
        posts = []
        total = 0
        used_slug = None
        for slug in slugs:
            posts, total = _fetch_posts_for_slug(slug)
            if posts:
                used_slug = slug
                break

        if not posts:
            print(f"[1point3acres] No interview posts found for '{company_name}'")
            return []

        print(f"[1point3acres] Found {len(posts)} recent posts (total: {total}, slug: {used_slug})")

        results = []
        for post in posts[:max_results]:
            tid = post.get("tid", "")
            subject = post.get("subject", "")
            en_subject = post.get("enSubject", "")
            dateline = post.get("dateline", 0)
            replies = post.get("replies", 0)
            recommend = post.get("recommend_add", 0)
            options = post.get("options", {})

            # Format date
            date_str = ""
            if dateline:
                try:
                    date_str = datetime.fromtimestamp(dateline).strftime("%Y-%m-%d")
                except (ValueError, OSError):
                    pass

            # Build descriptive body from metadata
            category = JOB_CATEGORIES.get(options.get("jobcategory"), "")
            job_type = JOB_TYPES.get(options.get("jobtype"), "")
            fresh = FRESH_STATUS.get(options.get("fresh"), "")

            meta_parts = [p for p in [category, job_type, fresh] if p]
            meta_str = ", ".join(meta_parts)

            post_url = f"https://www.1point3acres.com/interview/post/{tid}"

            # Try to fetch the actual post content; fall back to metadata summary
            full_content = _fetch_post_content(post_url)
            if full_content:
                body = full_content
            else:
                body = en_subject or subject
                if meta_str:
                    body += f" [{meta_str}]"
                if replies:
                    body += f" ({replies} replies)"
                if subject != en_subject and en_subject:
                    body += f" — Original: {subject}"

            results.append({
                "title": en_subject or subject,
                "href": post_url,
                "body": body,
                "date": date_str,
                "source": "1point3acres",
            })

            # Small delay to avoid rate-limiting individual post fetches
            time.sleep(0.4)

        return results

    except httpx.TimeoutException:
        print("[1point3acres] Request timed out")
        return []
    except Exception as e:
        print(f"[1point3acres] Error: {e}")
        return []
