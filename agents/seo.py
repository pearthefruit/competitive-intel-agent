"""Agent 5: SEO & AEO Audit — crawl a site and analyze on-page signals."""

from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context
from scraper.site_crawler import crawl_site
from prompts.seo import build_seo_prompt


def _extract_seo_signals(page):
    """Extract SEO metrics from a single page."""
    title = page["title"]
    meta_desc = page["meta_description"]
    headings = page["headings"]
    images = page["images"]

    h1s = [h for h in headings if h["level"] == 1]
    h2s = [h for h in headings if h["level"] == 2]
    h3s = [h for h in headings if h["level"] == 3]

    images_with_alt = sum(1 for img in images if img["has_alt"])
    images_total = len(images)

    # Schema types present
    schema_types = []
    for s in page["schema_data"]:
        if isinstance(s, dict):
            t = s.get("@type", "")
            if isinstance(t, list):
                schema_types.extend(t)
            elif t:
                schema_types.append(t)

    return {
        "url": page["url"],
        "title": title,
        "title_length": len(title),
        "title_ok": 10 <= len(title) <= 70,
        "meta_description": meta_desc,
        "meta_desc_length": len(meta_desc),
        "meta_desc_ok": 50 <= len(meta_desc) <= 160,
        "h1_count": len(h1s),
        "h1_texts": [h["text"] for h in h1s],
        "h2_count": len(h2s),
        "h3_count": len(h3s),
        "heading_hierarchy_ok": len(h1s) == 1 and len(h2s) >= 1,
        "images_total": images_total,
        "images_with_alt": images_with_alt,
        "alt_coverage": f"{images_with_alt}/{images_total}" if images_total else "n/a",
        "internal_link_count": len(page["internal_links"]),
        "external_link_count": len(page["external_links"]),
        "has_canonical": bool(page["canonical"]),
        "has_og_tags": bool(page["og_tags"]),
        "has_twitter_tags": bool(page["twitter_tags"]),
        "schema_types": schema_types,
        "word_count": page["word_count"],
    }


def _extract_aeo_signals(page):
    """Extract AEO (Answer Engine Optimization) metrics from a single page."""
    schema_types = []
    for s in page["schema_data"]:
        if isinstance(s, dict):
            t = s.get("@type", "")
            if isinstance(t, list):
                schema_types.extend(t)
            elif t:
                schema_types.append(t)

    aeo_schema_types = {"FAQPage", "HowTo", "QAPage", "Article", "BlogPosting",
                        "Product", "Review", "Recipe", "Event"}
    matched_aeo_types = [t for t in schema_types if t in aeo_schema_types]

    return {
        "url": page["url"],
        "has_faq_schema": "FAQPage" in schema_types,
        "has_howto_schema": "HowTo" in schema_types,
        "has_article_schema": any(t in schema_types for t in ["Article", "BlogPosting", "NewsArticle"]),
        "aeo_schema_types": matched_aeo_types,
        "faq_items_count": len(page["faq_items"]),
        "faq_items": page["faq_items"][:5],  # Sample
        "question_headings": [h["text"] for h in page["headings"] if h["text"].endswith("?")],
        "list_count": page["list_count"],
        "table_count": page["table_count"],
        "word_count": page["word_count"],
        "has_structured_content": page["list_count"] > 0 or page["table_count"] > 0,
    }


def _build_seo_summary(seo_signals):
    """Build aggregate SEO summary string."""
    total = len(seo_signals)
    titles_ok = sum(1 for s in seo_signals if s["title_ok"])
    meta_ok = sum(1 for s in seo_signals if s["meta_desc_ok"])
    headings_ok = sum(1 for s in seo_signals if s["heading_hierarchy_ok"])
    has_canonical = sum(1 for s in seo_signals if s["has_canonical"])
    has_og = sum(1 for s in seo_signals if s["has_og_tags"])

    total_images = sum(s["images_total"] for s in seo_signals)
    images_with_alt = sum(s["images_with_alt"] for s in seo_signals)

    all_schema = set()
    for s in seo_signals:
        all_schema.update(s["schema_types"])

    avg_word_count = sum(s["word_count"] for s in seo_signals) // max(total, 1)

    lines = [
        f"- Pages analyzed: {total}",
        f"- Titles optimized (10-70 chars): {titles_ok}/{total}",
        f"- Meta descriptions optimized (50-160 chars): {meta_ok}/{total}",
        f"- Proper heading hierarchy (1 H1 + H2s): {headings_ok}/{total}",
        f"- Canonical tags present: {has_canonical}/{total}",
        f"- Open Graph tags present: {has_og}/{total}",
        f"- Image alt text coverage: {images_with_alt}/{total_images}" if total_images else "- No images found",
        f"- Schema.org types found: {', '.join(sorted(all_schema)) or 'none'}",
        f"- Average word count: {avg_word_count}",
    ]
    return "\n".join(lines)


def _build_aeo_summary(aeo_signals):
    """Build aggregate AEO summary string."""
    total = len(aeo_signals)
    has_faq = sum(1 for s in aeo_signals if s["has_faq_schema"])
    has_howto = sum(1 for s in aeo_signals if s["has_howto_schema"])
    has_article = sum(1 for s in aeo_signals if s["has_article_schema"])
    has_structured = sum(1 for s in aeo_signals if s["has_structured_content"])
    total_questions = sum(len(s["question_headings"]) for s in aeo_signals)
    total_faq_items = sum(s["faq_items_count"] for s in aeo_signals)
    total_lists = sum(s["list_count"] for s in aeo_signals)
    total_tables = sum(s["table_count"] for s in aeo_signals)

    lines = [
        f"- FAQ schema: {has_faq}/{total} pages",
        f"- HowTo schema: {has_howto}/{total} pages",
        f"- Article/Blog schema: {has_article}/{total} pages",
        f"- Pages with structured content (lists/tables): {has_structured}/{total}",
        f"- Question-format headings found: {total_questions}",
        f"- FAQ/accordion items detected: {total_faq_items}",
        f"- Total lists across site: {total_lists}",
        f"- Total tables across site: {total_tables}",
    ]
    return "\n".join(lines)


def _build_page_details(seo_signals, aeo_signals):
    """Build compact per-page details for the LLM prompt."""
    details = []
    for seo, aeo in zip(seo_signals, aeo_signals):
        issues = []
        if not seo["title_ok"]:
            title_issue = "missing" if not seo["title"] else f"length {seo['title_length']}ch"
            issues.append(f"title {title_issue}")
        if not seo["meta_desc_ok"]:
            meta_issue = "missing" if not seo["meta_description"] else f"length {seo['meta_desc_length']}ch"
            issues.append(f"meta desc {meta_issue}")
        if not seo["heading_hierarchy_ok"]:
            issues.append(f"{seo['h1_count']} H1s")
        if seo["images_total"] > 0 and seo["images_with_alt"] < seo["images_total"]:
            issues.append(f"alt text: {seo['alt_coverage']}")
        if not seo["has_canonical"]:
            issues.append("no canonical")

        aeo_features = []
        if aeo["has_faq_schema"]:
            aeo_features.append("FAQ schema")
        if aeo["question_headings"]:
            aeo_features.append(f"{len(aeo['question_headings'])} Q headings")
        if aeo["has_structured_content"]:
            aeo_features.append(f"{aeo['list_count']}L/{aeo['table_count']}T")

        detail = f"- {seo['url']}\n"
        detail += f"  Title: \"{seo['title'][:60]}\"\n"
        detail += f"  H1: {', '.join(seo['h1_texts'][:2]) or 'none'} | Words: {seo['word_count']} | Schema: {', '.join(seo['schema_types'][:3]) or 'none'}\n"
        if issues:
            detail += f"  SEO issues: {'; '.join(issues)}\n"
        if aeo_features:
            detail += f"  AEO signals: {'; '.join(aeo_features)}\n"

        details.append(detail)

    return "\n".join(details)


def seo_audit(url, max_pages=10, company_name=None):
    """Run a full SEO & AEO audit on a website.

    Returns path to the generated report markdown file.
    """
    # Ensure URL has scheme
    if not url.startswith("http"):
        url = "https://" + url

    print(f"[seo] Starting SEO & AEO audit for {url}")

    # Crawl the site
    pages = crawl_site(url, max_pages=max_pages)
    if not pages:
        print("[seo] Crawl returned zero pages — possible causes:")
        print("[seo]   - Site may block automated crawlers (check robots.txt or Cloudflare/bot protection)")
        print("[seo]   - Site may be fully JS-rendered (SPA) and requires a headless browser to access content")
        print("[seo]   - URL may be invalid, behind authentication, or returning non-200 status codes")
        print("[seo]   - Try using the site's root domain if you used a deep link")
        return None

    if len(pages) < max_pages:
        print(f"[seo] Only crawled {len(pages)}/{max_pages} pages — site may have few internal links, aggressive rate-limiting, or a flat structure")

    # Extract signals
    print(f"[seo] Analyzing {len(pages)} pages...")
    seo_signals = [_extract_seo_signals(p) for p in pages]
    aeo_signals = [_extract_aeo_signals(p) for p in pages]

    # Build summaries
    seo_summary = _build_seo_summary(seo_signals)
    aeo_summary = _build_aeo_summary(aeo_signals)
    page_details = _build_page_details(seo_signals, aeo_signals)

    # Generate LLM narrative
    prompt = build_seo_prompt(url, len(pages), seo_summary, aeo_summary, page_details)
    prompt += get_temporal_context(company_name or domain, "seo")

    try:
        narrative, model_used = generate_text(prompt)
        print(f"[seo] Report generated via {model_used}")
    except Exception as e:
        print(f"[error] LLM report generation failed: {e}")
        narrative = "*Report generation failed. See data below.*"
        model_used = "none"

    # Assemble report
    domain = urlparse(url).netloc
    today = datetime.now().strftime("%Y-%m-%d")

    report = f"""# SEO & AEO Audit: {domain}

**URL:** {url}
**Crawled:** {len(pages)} pages | **Date:** {today}
**Model:** {model_used}

---

## SEO Overview

{seo_summary}

## AEO Overview

{aeo_summary}

---

## SEO Scorecard

| Page | Title | Meta Desc | H1 | Alt Text | Schema | Words |
|------|-------|-----------|-----|----------|--------|-------|
"""

    for seo in seo_signals:
        short_url = urlparse(seo["url"]).path or "/"
        title_status = "ok" if seo["title_ok"] else f"{seo['title_length']}ch"
        meta_status = "ok" if seo["meta_desc_ok"] else ("missing" if not seo["meta_description"] else f"{seo['meta_desc_length']}ch")
        h1_status = "ok" if seo["h1_count"] == 1 else f"{seo['h1_count']}"
        alt_status = seo["alt_coverage"]
        schema_status = ", ".join(seo["schema_types"][:2]) or "none"
        report += f"| {short_url[:30]} | {title_status} | {meta_status} | {h1_status} | {alt_status} | {schema_status} | {seo['word_count']} |\n"

    report += f"""
---

{narrative}
"""

    # Save to file
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    safe_domain = domain.replace(".", "_").replace("/", "_")
    filename = reports_dir / f"{safe_domain}_seo_{today}.md"
    filename.write_text(report, encoding="utf-8")

    print(f"[seo] Report saved to {filename}")
    dossier_name = company_name or domain
    save_to_dossier(dossier_name, "seo", report_file=str(filename), report_text=report, model_used=model_used)
    return str(filename)
