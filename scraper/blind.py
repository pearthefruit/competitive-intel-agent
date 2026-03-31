"""Blind (teamblind.com) scraper — company reviews and discussion posts.

Fetches employee reviews and discussion threads from Blind's public company pages.
No authentication required — company pages are publicly accessible.

Three extraction layers (best to worst):
1. JSON-LD structured data — individual reviews with ratings, roles, review text
2. RSC stream — pros/cons text embedded in React Server Components payload
3. Post links — discussion thread titles and URLs from the posts page
"""

import json
import re

import httpx
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_TIMEOUT = 15


def _generate_slugs(company_name):
    """Generate candidate URL slugs for Blind company pages."""
    name = company_name.strip()
    for suffix in [" Inc", " Inc.", " Co", " Co.", " Corp", " LLC", " Ltd", " & Company", " & Co"]:
        if name.lower().endswith(suffix.lower()):
            name = name[:-len(suffix)].strip()

    slugs = []
    slugs.append(re.sub(r"\s+", "-", name))            # Title-Case-Hyphens
    if " " not in name:
        slugs.append(name)
    slugs.append(re.sub(r"\s+", "-", name.lower()))     # lowercase-hyphens
    slugs.append(re.sub(r"\s+", "", name))               # CamelCase

    seen = set()
    return [s for s in slugs if s and s not in seen and not seen.add(s)]


def _fetch_page(url):
    """Fetch a page, return BeautifulSoup or None."""
    try:
        resp = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None
        return BeautifulSoup(resp.text, "html.parser")
    except httpx.TimeoutException:
        print(f"[blind] Timeout: {url}")
        return None
    except Exception as e:
        print(f"[blind] Error: {url}: {e}")
        return None


def _extract_jsonld_reviews(soup, page_url):
    """Extract structured reviews from JSON-LD script tags.

    Returns (reviews_list, aggregate_info_dict).
    """
    reviews = []
    aggregate = {}

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            continue

        if data.get("@type") == "Review":
            rating = data.get("reviewRating", {})
            author = data.get("author", {})
            role = author.get("name", "")
            body = data.get("reviewBody", "")
            score = rating.get("ratingValue")

            if body:
                title = f"{body[:60]}{'...' if len(body) > 60 else ''}"
                if role:
                    title = f"[{score}/5] {role}: {body[:50]}"
                reviews.append({
                    "title": title,
                    "href": page_url,
                    "body": f"Rating: {score}/5 | Role: {role}\nReview: {body}",
                    "date": "",
                    "source": "blind",
                })

        elif data.get("@type") == "EmployerAggregateRating":
            aggregate = {
                "rating": data.get("ratingValue"),
                "count": data.get("ratingCount"),
                "company": (data.get("itemReviewed") or {}).get("name", ""),
            }

        elif data.get("@type") == "FAQPage":
            for entity in data.get("mainEntity", []):
                q = entity.get("name", "")
                a = (entity.get("acceptedAnswer") or {}).get("text", "")
                if q and a:
                    reviews.append({
                        "title": q,
                        "href": page_url,
                        "body": f"Q: {q}\nA: {a}",
                        "date": "",
                        "source": "blind",
                    })

    return reviews, aggregate


def _extract_rsc_reviews(soup, company_name):
    """Extract pros/cons review text from React Server Components stream."""
    results = []

    for script in soup.find_all("script"):
        text = script.string or ""
        if len(text) < 500 or "self.__next_f.push" not in text:
            continue

        # Extract substantial review-like strings from the RSC payload
        strings = re.findall(r'"([^"]{60,800})"', text)
        for s in strings:
            s = s.replace("\\n", "\n").replace("\\t", " ").strip()
            # Skip obvious non-review strings
            if s.startswith(("/", "flex ", "grid ", "px-", "className", "function", "http", "self.")):
                continue
            if "<" in s or "{" in s or "=>" in s:
                continue
            if "Alumni Lounge" in s or "/channels/" in s:
                continue
            # Require multiple review-signal words (not just one generic word like "management")
            signals = sum(1 for kw in [
                "wlb", "work life", "work-life", "culture", "toxic", "comp ",
                "compensation", "politics", "political", "leadership", "benefits",
                "balance", "ownership", "stack ranking", "pip", "layoff",
                "interview", "hiring", "burnout", "overwork", "micromanag",
                "promotion", "refresher", "rsu", "stock", "salary",
                "pros", "cons", "recommend", "rating",
            ] if kw in s.lower())
            if signals >= 2 or (signals >= 1 and len(s) > 100):
                results.append(s)

    # Deduplicate and format
    seen = set()
    unique = []
    for s in results:
        key = s[:60]
        if key not in seen:
            seen.add(key)
            unique.append({
                "title": f"Blind review — {company_name}",
                "href": f"https://www.teamblind.com/company/{company_name}/reviews",
                "body": s[:2000],
                "date": "",
                "source": "blind",
            })

    return unique


def _extract_post_links(soup, page_url):
    """Extract discussion post links from the posts page."""
    results = []
    seen_hrefs = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/post/" not in href:
            continue
        if not href.startswith("http"):
            href = f"https://www.teamblind.com{href}"
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        text = a.get_text(separator=" ", strip=True)
        if len(text) < 10:
            continue

        results.append({
            "title": text[:200],
            "href": href,
            "body": text[:2000],
            "date": "",
            "source": "blind",
        })

    return results


def search_blind(company_name, max_results=15):
    """Fetch employee reviews and discussion posts from Blind.

    Extraction priority:
    1. JSON-LD reviews (structured: rating, role, review text)
    2. RSC stream pros/cons (raw review text from React payload)
    3. Discussion post links

    Returns list of dicts: {title, href, body, date, source}.
    """
    slugs = _generate_slugs(company_name)
    print(f"[blind] Searching Blind for {company_name} (slugs: {', '.join(slugs)})...")

    all_results = []
    aggregate = {}
    found_slug = None

    for slug in slugs:
        url = f"https://www.teamblind.com/company/{slug}/reviews"
        soup = _fetch_page(url)
        if not soup:
            continue

        # Layer 1: JSON-LD structured reviews
        jsonld_reviews, agg = _extract_jsonld_reviews(soup, url)
        if jsonld_reviews:
            print(f"[blind] Found {len(jsonld_reviews)} JSON-LD reviews (slug: {slug})")
            all_results.extend(jsonld_reviews)
            aggregate = agg
            found_slug = slug

            # Layer 2: RSC stream for additional pros/cons text
            rsc_reviews = _extract_rsc_reviews(soup, company_name)
            if rsc_reviews:
                print(f"[blind] Found {len(rsc_reviews)} additional review snippets from RSC stream")
                all_results.extend(rsc_reviews)
            break

        # Check if we at least got RSC data (page exists but no JSON-LD)
        rsc_reviews = _extract_rsc_reviews(soup, company_name)
        if rsc_reviews:
            print(f"[blind] Found {len(rsc_reviews)} review snippets from RSC stream (slug: {slug})")
            all_results.extend(rsc_reviews)
            found_slug = slug
            break

    # Layer 3: Discussion posts (use found slug or try all)
    post_slugs = [found_slug] if found_slug else slugs
    for slug in post_slugs:
        url = f"https://www.teamblind.com/company/{slug}/posts"
        soup = _fetch_page(url)
        if soup:
            posts = _extract_post_links(soup, url)
            if posts:
                print(f"[blind] Found {len(posts)} discussion posts")
                all_results.extend(posts)
            break

    if not all_results:
        print(f"[blind] No results found for '{company_name}' on Blind")
        return []

    # Prepend aggregate rating summary if available
    if aggregate.get("rating"):
        summary = f"Blind Aggregate Rating: {aggregate['rating']}/5 based on {aggregate.get('count', '?')} verified employee reviews"
        all_results.insert(0, {
            "title": f"Blind Rating: {aggregate['rating']}/5 ({aggregate.get('count', '?')} reviews)",
            "href": f"https://www.teamblind.com/company/{found_slug or slugs[0]}/reviews",
            "body": summary,
            "date": "",
            "source": "blind",
        })

    # Deduplicate by body content
    seen = set()
    unique = []
    for r in all_results:
        key = r["body"][:80]
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique[:max_results]
