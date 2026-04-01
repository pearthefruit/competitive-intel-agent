"""Agent 5: SEO & AEO Audit — crawl a site and analyze on-page signals."""

from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context, unique_report_path
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


def seo_audit(url, max_pages=10, company_name=None, progress_cb=None):
    """Run a full SEO & AEO audit on a website.

    Returns path to the generated report markdown file.
    """
    _cb = progress_cb or (lambda *a: None)

    # Ensure URL has scheme
    if not url.startswith("http"):
        url = "https://" + url

    print(f"[seo] Starting SEO & AEO audit for {url}")
    domain = urlparse(url).netloc

    # --- Phase 1: Site Crawl ---
    _cb('analysis_start', {'analysis_type': 'crawl', 'label': 'Site Crawl'})
    _cb('source_start', {'source': 'crawler', 'label': 'Web Crawler', 'detail': f'Crawling up to {max_pages} pages from {domain}'})
    pages = crawl_site(url, max_pages=max_pages)
    if not pages:
        print("[seo] Crawl returned zero pages — possible causes:")
        print("[seo]   - Site may block automated crawlers (check robots.txt or Cloudflare/bot protection)")
        print("[seo]   - Site may be fully JS-rendered (SPA) and requires a headless browser to access content")
        print("[seo]   - URL may be invalid, behind authentication, or returning non-200 status codes")
        print("[seo]   - Try using the site's root domain if you used a deep link")
        _cb('source_done', {'source': 'crawler', 'status': 'error', 'summary': 'Zero pages crawled'})
        _cb('analysis_done', {'analysis_type': 'crawl'})
        return None

    if len(pages) < max_pages:
        print(f"[seo] Only crawled {len(pages)}/{max_pages} pages — site may have few internal links, aggressive rate-limiting, or a flat structure")
    crawl_detail = '\n'.join(f"• {p.get('url', '?')}  ({p.get('word_count', 0)} words)" for p in pages[:10])
    _cb('source_done', {'source': 'crawler', 'status': 'done', 'summary': f'{len(pages)} pages crawled', 'detail': crawl_detail})
    _cb('analysis_done', {'analysis_type': 'crawl'})

    # --- Phase 2: Signal Analysis ---
    _cb('analysis_start', {'analysis_type': 'analysis', 'label': 'SEO/AEO Analysis'})
    print(f"[seo] Analyzing {len(pages)} pages...")

    _cb('source_start', {'source': 'seo_signals', 'label': 'SEO Signal Extraction', 'detail': f'Analyzing {len(pages)} pages for on-page SEO'})
    seo_signals = [_extract_seo_signals(p) for p in pages]
    seo_summary = _build_seo_summary(seo_signals)
    titles_ok = sum(1 for s in seo_signals if s.get('title_ok'))
    meta_ok = sum(1 for s in seo_signals if s.get('meta_desc_ok'))
    hierarchy_ok = sum(1 for s in seo_signals if s.get('heading_hierarchy_ok'))
    seo_detail = f"Title optimization: {titles_ok}/{len(seo_signals)} pages\nMeta descriptions: {meta_ok}/{len(seo_signals)} pages\nHeading hierarchy: {hierarchy_ok}/{len(seo_signals)} pages"
    seo_detail += '\n' + '\n'.join(f"• {s.get('url', '?')}: title={s.get('title_length')}ch, H1s={s.get('h1_count')}" for s in seo_signals[:8])
    _cb('source_done', {'source': 'seo_signals', 'status': 'done', 'summary': f'{len(seo_signals)} pages analyzed', 'detail': seo_detail})

    _cb('source_start', {'source': 'aeo_signals', 'label': 'AEO Signal Extraction', 'detail': 'Schema, FAQ, structured content detection'})
    aeo_signals = [_extract_aeo_signals(p) for p in pages]
    aeo_summary = _build_aeo_summary(aeo_signals)
    faq_pages = sum(1 for a in aeo_signals if a.get('has_faq_schema'))
    article_pages = sum(1 for a in aeo_signals if a.get('has_article_schema'))
    all_schema = set()
    for a in aeo_signals:
        all_schema.update(a.get('aeo_schema_types', []))
    aeo_detail = f"FAQ schema: {faq_pages} pages\nArticle schema: {article_pages} pages\nSchema types found: {', '.join(sorted(all_schema)) or 'none'}"
    _cb('source_done', {'source': 'aeo_signals', 'status': 'done', 'summary': f'{len(aeo_signals)} pages analyzed', 'detail': aeo_detail})

    page_details = _build_page_details(seo_signals, aeo_signals)
    _cb('analysis_done', {'analysis_type': 'analysis'})

    # --- Phase 3: Report Generation ---
    _cb('analysis_start', {'analysis_type': 'report', 'label': 'Report Generation'})

    prompt = build_seo_prompt(url, len(pages), seo_summary, aeo_summary, page_details)
    prompt += get_temporal_context(company_name or domain, "seo")

    _cb('source_start', {'source': 'llm', 'label': 'LLM Synthesis', 'detail': f'Generating SEO/AEO audit narrative for {len(pages)} pages'})
    try:
        narrative, model_used = generate_text(prompt)
        print(f"[seo] Report generated via {model_used}")
        _cb('source_done', {'source': 'llm', 'status': 'done', 'summary': f'Generated via {model_used}'})
    except Exception as e:
        print(f"[error] LLM report generation failed: {e}")
        narrative = "*Report generation failed. See data below.*"
        model_used = "none"
        _cb('source_done', {'source': 'llm', 'status': 'error', 'summary': str(e)[:80]})

    # Assemble report
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
    filename = unique_report_path(reports_dir, f"{safe_domain}_seo_{today}.md")
    filename.write_text(report, encoding="utf-8")

    print(f"[seo] Report saved to {filename}")
    _cb('report_saved', {'path': str(filename)})
    _cb('analysis_done', {'analysis_type': 'report'})

    dossier_name = company_name or domain
    save_to_dossier(dossier_name, "seo", report_file=str(filename), report_text=report, model_used=model_used, progress_cb=_cb)
    return str(filename)
