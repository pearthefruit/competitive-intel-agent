"""Site crawler — fetch a homepage and key internal pages for SEO/AEO analysis."""

import json
import time
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SKIP_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
                   ".mp4", ".mp3", ".zip", ".css", ".js", ".ico", ".woff", ".woff2", ".ttf"}


def crawl_site(url, max_pages=10):
    """Crawl a website starting from url, following internal links.

    Prioritizes navigation links over body links.
    Returns list of page dicts with extracted metadata.
    """
    parsed_base = urlparse(url)
    base_domain = parsed_base.netloc
    if not base_domain:
        print(f"[crawl] Invalid URL: {url}")
        return []

    client = httpx.Client(headers=REQUEST_HEADERS, timeout=15, follow_redirects=True)
    visited = set()
    pages = []

    # Queue: (url, priority) — lower priority number = crawl first
    # Priority 0 = homepage, 1 = nav links, 2 = body links
    queue = [(url, 0)]

    print(f"[crawl] Starting crawl of {base_domain} (max {max_pages} pages)...")

    while queue and len(pages) < max_pages:
        # Sort by priority so nav links come first
        queue.sort(key=lambda x: x[1])
        current_url, priority = queue.pop(0)

        # Normalize URL
        current_url = current_url.split("#")[0].rstrip("/")
        if current_url in visited:
            continue

        # Skip non-HTML resources
        path_lower = urlparse(current_url).path.lower()
        if any(path_lower.endswith(ext) for ext in SKIP_EXTENSIONS):
            continue

        visited.add(current_url)

        try:
            resp = client.get(current_url)
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type:
                continue

            # Accept pages with HTML content (some SPAs return 404 but serve full HTML)
            if resp.status_code >= 400 and len(resp.text) < 5000:
                print(f"  [{len(pages)+1}] {resp.status_code} — {current_url[:70]}")
                continue

            page_data = _extract_page_data(resp.text, current_url)
            page_data["html"] = resp.text
            page_data["response_headers"] = dict(resp.headers)
            pages.append(page_data)
            print(f"  [{len(pages)}/{max_pages}] {page_data['title'][:50] or current_url[:50]}")

            # Discover new links to crawl
            if len(pages) < max_pages:
                new_links = _discover_links(resp.text, current_url, base_domain, visited)
                for link_url, link_priority in new_links:
                    normalized = link_url.split("#")[0].rstrip("/")
                    if normalized not in visited:
                        queue.append((normalized, link_priority))

            # Polite delay
            if len(pages) < max_pages:
                time.sleep(1)

        except Exception as e:
            print(f"  [error] {current_url[:60]}: {e}")

    client.close()
    print(f"[crawl] Done — crawled {len(pages)} pages")
    return pages


def _extract_page_data(html, url):
    """Extract SEO/AEO-relevant metadata from a page's HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Meta description
    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    meta_description = meta_desc_tag.get("content", "") if meta_desc_tag else ""

    # Meta keywords
    meta_kw_tag = soup.find("meta", attrs={"name": "keywords"})
    meta_keywords = meta_kw_tag.get("content", "") if meta_kw_tag else ""

    # Headings
    headings = []
    for level in range(1, 7):
        for h in soup.find_all(f"h{level}"):
            text = h.get_text(strip=True)
            if text:
                headings.append({"level": level, "text": text})

    # Images
    images = []
    for img in soup.find_all("img"):
        images.append({
            "src": img.get("src", ""),
            "alt": img.get("alt", ""),
            "has_alt": bool(img.get("alt", "").strip()),
        })

    # Links
    internal_links = []
    external_links = []
    parsed_url = urlparse(url)
    base_domain = parsed_url.netloc

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        anchor = a.get_text(strip=True)
        abs_url = urljoin(url, href)
        parsed_href = urlparse(abs_url)

        if parsed_href.netloc == base_domain:
            internal_links.append({"url": abs_url, "anchor": anchor})
        elif parsed_href.scheme in ("http", "https"):
            external_links.append({"url": abs_url, "anchor": anchor})

    # Schema.org / JSON-LD
    schema_data = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                schema_data.extend(data)
            else:
                schema_data.append(data)
        except (json.JSONDecodeError, TypeError):
            pass

    # Open Graph tags
    og_tags = {}
    for meta in soup.find_all("meta", property=re.compile(r"^og:")):
        og_tags[meta.get("property", "")] = meta.get("content", "")

    # Twitter card tags
    twitter_tags = {}
    for meta in soup.find_all("meta", attrs={"name": re.compile(r"^twitter:")}):
        twitter_tags[meta.get("name", "")] = meta.get("content", "")

    # Canonical
    canonical_tag = soup.find("link", rel="canonical")
    canonical = canonical_tag.get("href", "") if canonical_tag else ""

    # Word count (visible text only)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    visible_text = soup.get_text(separator=" ", strip=True)
    word_count = len(visible_text.split())

    # FAQ detection (HTML patterns)
    faq_items = []
    # Check for FAQ-like patterns: elements with "question"/"answer" classes or Q&A headings
    for el in soup.find_all(class_=re.compile(r"faq|question|accordion", re.I)):
        text = el.get_text(strip=True)[:200]
        if text:
            faq_items.append(text)
    # Check for headings that are questions
    for h in headings:
        if h["text"].endswith("?"):
            faq_items.append(h["text"])

    # Lists and tables (AEO signals — structured content)
    list_count = len(soup.find_all(["ul", "ol"]))
    table_count = len(soup.find_all("table"))

    return {
        "url": url,
        "title": title,
        "meta_description": meta_description,
        "meta_keywords": meta_keywords,
        "headings": headings,
        "images": images,
        "internal_links": internal_links,
        "external_links": external_links,
        "schema_data": schema_data,
        "og_tags": og_tags,
        "twitter_tags": twitter_tags,
        "canonical": canonical,
        "word_count": word_count,
        "faq_items": faq_items,
        "list_count": list_count,
        "table_count": table_count,
    }


def _discover_links(html, current_url, base_domain, visited):
    """Find internal links to crawl next, prioritizing nav/header links."""
    soup = BeautifulSoup(html, "html.parser")
    nav_links = []
    body_links = []

    # Priority 1: links inside <nav>, <header>, or elements with nav-like classes
    nav_containers = soup.find_all(["nav", "header"])
    nav_containers += soup.find_all(class_=re.compile(r"nav|menu|header", re.I))

    nav_hrefs = set()
    for container in nav_containers:
        for a in container.find_all("a", href=True):
            abs_url = urljoin(current_url, a["href"])
            parsed = urlparse(abs_url)
            normalized = abs_url.split("#")[0].rstrip("/")

            if (parsed.netloc == base_domain
                    and normalized not in visited
                    and not any(parsed.path.lower().endswith(ext) for ext in SKIP_EXTENSIONS)):
                nav_hrefs.add(normalized)
                nav_links.append((normalized, 1))

    # Priority 2: all other internal links (body content)
    for a in soup.find_all("a", href=True):
        abs_url = urljoin(current_url, a["href"])
        parsed = urlparse(abs_url)
        normalized = abs_url.split("#")[0].rstrip("/")

        if (parsed.netloc == base_domain
                and normalized not in visited
                and normalized not in nav_hrefs
                and not any(parsed.path.lower().endswith(ext) for ext in SKIP_EXTENSIONS)):
            body_links.append((normalized, 2))

    return nav_links + body_links
