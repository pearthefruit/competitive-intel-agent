"""Agent: Product & Pricing Intel — crawl a site and extract pricing strategy."""

import re
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context, unique_report_path
from db import get_connection, save_source_document, link_sources_to_analysis
from scraper.site_crawler import crawl_site
from prompts.pricing import build_pricing_prompt

PRICING_URL_PATTERNS = re.compile(r"pricing|plans|packages|subscribe|buy|upgrade", re.IGNORECASE)
PRICING_HEADING_PATTERNS = re.compile(r"pricing|plans|packages|price|cost|tier|subscribe|free trial", re.IGNORECASE)


def _is_pricing_page(page):
    """Check if a page is pricing-related based on URL and headings."""
    url = page.get("url", "")
    if PRICING_URL_PATTERNS.search(url):
        return True

    for h in page.get("headings", []):
        if h["level"] <= 3 and PRICING_HEADING_PATTERNS.search(h["text"]):
            return True

    return False


def _extract_pricing_content(page):
    """Extract pricing-relevant content from a page."""
    lines = []
    url = page.get("url", "")
    lines.append(f"URL: {url}")
    lines.append(f"Title: {page.get('title', '')}")

    # Headings
    for h in page.get("headings", []):
        prefix = "#" * h["level"]
        lines.append(f"{prefix} {h['text']}")

    # FAQ items (often contain pricing Q&A)
    for faq in page.get("faq_items", []):
        lines.append(f"FAQ: {faq}")

    # Lists (often contain feature lists)
    lines.append(f"Lists on page: {page.get('list_count', 0)}")
    lines.append(f"Tables on page: {page.get('table_count', 0)}")
    lines.append(f"Word count: {page.get('word_count', 0)}")

    return "\n".join(lines)


def pricing_analysis(url, company_name=None, progress_cb=None):
    """Crawl a website and analyze its pricing strategy. Returns report path or None."""
    _cb = progress_cb or (lambda *a: None)
    _pending_sources = []

    if not url.startswith("http"):
        url = f"https://{url}"

    domain = urlparse(url).netloc
    print(f"\n[pricing] Analyzing pricing for {domain}...")

    # --- Phase 1: Site Crawl ---
    _cb('analysis_start', {'analysis_type': 'crawl', 'label': 'Site Crawl'})
    _cb('source_start', {'source': 'crawler', 'label': 'Web Crawler', 'detail': f'Crawling up to 5 pages from {domain}'})
    pages = crawl_site(url, max_pages=5)
    if not pages:
        print("[pricing] No pages crawled — site may block automated requests or require JS rendering")
        _cb('source_done', {'source': 'crawler', 'status': 'error', 'summary': 'No pages crawled'})
        _cb('analysis_done', {'analysis_type': 'crawl'})
        return None
    crawl_detail = '\n'.join(f"• {p.get('url', '?')}  ({p.get('word_count', 0)} words)" for p in pages[:10])
    _cb('source_done', {'source': 'crawler', 'status': 'done', 'summary': f'{len(pages)} pages crawled', 'detail': crawl_detail})
    _cb('analysis_done', {'analysis_type': 'crawl'})

    # Collect crawled pages as source documents
    for p in pages:
        page_text = p.get("text") or p.get("content") or p.get("body") or ""
        if page_text:
            source_type = "pricing_page" if _is_pricing_page(p) else "web"
            _pending_sources.append({
                "source_type": source_type,
                "url": p.get("url"),
                "title": (p.get("title") or "")[:500],
                "content": page_text[:50000],
                "raw_data": None,
            })

    # --- Phase 2: Pricing Detection ---
    _cb('analysis_start', {'analysis_type': 'pricing_detect', 'label': 'Pricing Detection'})

    _cb('source_start', {'source': 'page_classify', 'label': 'Page Classification', 'detail': f'Identifying pricing pages from {len(pages)} crawled'})
    pricing_pages = [p for p in pages if _is_pricing_page(p)]
    other_pages = [p for p in pages if not _is_pricing_page(p)]
    print(f"[pricing] Found {len(pricing_pages)} pricing-related pages out of {len(pages)} crawled")
    classify_detail = '\n'.join(f"• {p.get('url', '?')} (pricing)" for p in pricing_pages[:5])
    if other_pages:
        classify_detail += '\n' + '\n'.join(f"• {p.get('url', '?')} (other)" for p in other_pages[:3])
    _cb('source_done', {'source': 'page_classify', 'status': 'done', 'summary': f'{len(pricing_pages)} pricing pages found', 'detail': classify_detail})

    _cb('source_start', {'source': 'extract', 'label': 'Content Extraction', 'detail': 'Extracting pricing data from pages'})
    if pricing_pages:
        pricing_text = "\n\n---\n\n".join(_extract_pricing_content(p) for p in pricing_pages)
        _cb('source_done', {'source': 'extract', 'status': 'done', 'summary': f'Extracted from {len(pricing_pages)} pricing pages'})
    else:
        print("[pricing] No dedicated pricing page found — possible reasons:")
        print("[pricing]   - Enterprise/contact-sales model (no public pricing)")
        print("[pricing]   - Pricing may be behind a login or gated by region")
        print("[pricing]   - Pricing page may use a subdomain or external billing portal (e.g., Stripe, Chargebee)")
        print("[pricing] Extracting pricing clues from homepage and other crawled pages instead")
        pricing_text = "No dedicated pricing page found. Extracting from homepage and other pages:\n\n"
        pricing_text += "\n\n---\n\n".join(_extract_pricing_content(p) for p in pages[:3])
        _cb('source_done', {'source': 'extract', 'status': 'done', 'summary': 'No pricing page — extracted from homepage'})

    # Site summary from all pages
    site_lines = []
    for p in pages:
        site_lines.append(f"- {p.get('url', '')}: {p.get('title', '')} ({p.get('word_count', 0)} words)")
    site_summary = "\n".join(site_lines)
    _cb('analysis_done', {'analysis_type': 'pricing_detect'})

    # --- Phase 3: Report Generation ---
    _cb('analysis_start', {'analysis_type': 'report', 'label': 'Report Generation'})

    prompt = build_pricing_prompt(url, pricing_text, site_summary)
    prompt += get_temporal_context(company_name or domain, "pricing")

    print("[pricing] Generating report...")
    _cb('source_start', {'source': 'llm', 'label': 'LLM Synthesis', 'detail': f'Analyzing pricing strategy for {domain}'})
    text, model = generate_text(prompt)
    _cb('source_done', {'source': 'llm', 'status': 'done', 'summary': f'Generated via {model}'})

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_domain = domain.replace(".", "_").replace("/", "_")

    header = f"""# Product & Pricing Analysis: {domain}

**URL:** {url}
**Crawled:** {len(pages)} pages | **Pricing Pages Found:** {len(pricing_pages)}
**Date:** {today} | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = unique_report_path(reports_dir, f"{safe_domain}_pricing_{today}.md")
    filename.write_text(report, encoding="utf-8")

    print(f"[pricing] Report saved to {filename}")
    _cb('report_saved', {'path': str(filename)})
    _cb('analysis_done', {'analysis_type': 'report'})

    dossier_name = company_name or domain
    dossier_result = save_to_dossier(dossier_name, "pricing", report_file=str(filename), report_text=report, model_used=model, progress_cb=_cb)
    _flush_sources(dossier_name, dossier_result, _pending_sources)
    return str(filename)


def _flush_sources(company, dossier_result, pending_sources):
    if not dossier_result or not pending_sources:
        return
    # Deduplicate by URL
    seen_urls = set()
    deduped = []
    for s in pending_sources:
        url = s.get("url")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(s)
    try:
        conn = get_connection()
        dossier_id = dossier_result["dossier_id"]
        analysis_id = dossier_result["analysis_id"]
        source_ids = []
        for s in deduped:
            sid = save_source_document(
                conn, dossier_id, s["source_type"], s.get("url"),
                s.get("title"), s.get("content"), s.get("raw_data"),
            )
            source_ids.append(sid)
        if analysis_id and source_ids:
            link_sources_to_analysis(conn, analysis_id, source_ids)
        conn.close()
        print(f"[sources] Saved {len(source_ids)} source documents for {company}")
    except Exception as e:
        print(f"[sources] Error saving source documents: {e}")
