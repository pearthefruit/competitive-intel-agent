"""Agent: Operations Maturity — assess whether a business runs on systems or on its owner.

Sibling to techstack.py, aimed at a different question. techstack asks what the
site is built with; this asks whether the company has a funnel, a content
engine, self-serve capability, and hiring infrastructure — the things that
determine whether a sub-$25M business survives a change of ownership.

Uses targeted path probing rather than the nav-priority BFS crawl: for this
analysis the absence of a pricing page has to mean "there isn't one", not
"the crawler didn't happen to reach it".
"""

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from agents.llm import generate_text, save_to_dossier, get_temporal_context, unique_report_path
from db import get_connection, save_source_document, link_sources_to_analysis
from scraper.ops_detect import (
    probe_paths, detect_ops_signals, format_ops_for_prompt, is_blocked, REQUEST_HEADERS,
)
from scraper.tech_detect import detect_technologies, format_tech_for_prompt
from prompts.ops_maturity import build_ops_maturity_prompt


def _fetch_homepage(url, timeout=15):
    """Fetch the homepage. Returns (html, final_url, status).

    status is one of "ok" | "unreachable" | "blocked". The blocked case must stay
    distinct: a Cloudflare challenge is served as a real HTML body, so accepting
    it silently turns "we couldn't look" into "this business has no funnel".
    """
    try:
        with httpx.Client(headers=REQUEST_HEADERS, timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url)
            if is_blocked(resp.text, resp.status_code):
                return None, str(resp.url), "blocked"
            if "text/html" not in resp.headers.get("content-type", ""):
                return None, url, "unreachable"
            if resp.status_code >= 400 and len(resp.text) < 5000:
                return None, url, "unreachable"
            return resp.text, str(resp.url), "ok"
    except Exception as e:
        print(f"[ops] Homepage fetch failed for {url}: {e}")
        return None, url, "unreachable"


def ops_maturity_analysis(url, company_name=None, db_path=None, progress_cb=None):
    """Probe a company website and assess operational maturity. Returns report path or None.

    Args:
        url: Website URL to analyze
        company_name: Optional company name for dossier linking
        db_path: Unused today — kept for signature parity with the other site agents
        progress_cb: Optional callback(event_type, event_data) for structured progress.
            Events emitted: source_start, source_done, generating, report_saved
    """
    _cb = progress_cb or (lambda *a: None)
    _pending_sources = []

    if not url.startswith("http"):
        url = f"https://{url}"

    domain = urlparse(url).netloc
    print(f"\n[ops] Assessing operations maturity for {domain}...")

    # --- Homepage ---
    _cb("source_start", {"source": "homepage", "label": "Homepage", "detail": f"Fetching {domain}"})
    homepage_html, final_url, status = _fetch_homepage(url)
    if status == "blocked":
        print(f"[ops] {domain} is WAF/bot-protected — aborting rather than reporting a false negative")
        _cb("source_done", {"source": "homepage", "status": "error",
                            "summary": "Blocked by bot protection — no assessment possible"})
        return None
    if not homepage_html:
        print("[ops] Could not fetch homepage — site may be unreachable or require JS rendering")
        _cb("source_done", {"source": "homepage", "status": "error", "summary": "Homepage unreachable"})
        return None
    _cb("source_done", {"source": "homepage", "status": "done",
                        "summary": f"{len(homepage_html):,} bytes", "detail": final_url})

    # --- Targeted path probing ---
    _cb("source_start", {"source": "path_probe", "label": "Page Probe",
                         "detail": "Checking for pricing, blog, booking, careers, portal pages"})
    probed, probe_meta = probe_paths(final_url)
    if probe_meta["blocked"]:
        print(f"[ops] {domain} blocked path probing — aborting rather than reporting a false negative")
        _cb("source_done", {"source": "path_probe", "status": "error",
                            "summary": "Blocked by bot protection — no assessment possible"})
        return None
    probe_detail = "\n".join(f"• {cap}: {d['url']}" for cap, d in sorted(probed.items()))
    quality_note = " [CATCH-ALL SITE — page existence unreliable]" if probe_meta["catchall"] else ""
    print(f"[ops] Probed {domain} — found {len(probed)} known page types{quality_note}")
    _cb("source_done", {"source": "path_probe", "status": "done",
                        "summary": f"{len(probed)} page types found{quality_note}",
                        "detail": probe_detail or "No known page types found"})

    # --- Signal extraction ---
    _cb("source_start", {"source": "ops_signals", "label": "Ops Signals",
                         "detail": "Extracting funnel, content, and systems signals"})
    signals = detect_ops_signals(homepage_html, final_url, probed, probe_meta)
    ops_summary = format_ops_for_prompt(signals)
    lc = signals["lead_capture"]
    sf = signals["sales_funnel"]
    summary_bits = [
        f"ESP: {lc['esp'] or 'none'}",
        f"booking: {sf['booking_tool'] or 'none'}",
        f"pricing page: {'yes' if sf['pricing_page'] else 'no'}",
    ]
    _cb("source_done", {"source": "ops_signals", "status": "done",
                        "summary": ", ".join(summary_bits), "detail": ops_summary})

    # --- Software stack over the same pages (free — we already have the HTML) ---
    _cb("source_start", {"source": "tech_detect", "label": "Software Stack",
                         "detail": "Fingerprinting operating software across probed pages"})
    pseudo_pages = [{"url": final_url, "html": homepage_html, "response_headers": {}}]
    pseudo_pages += [{"url": d["url"], "html": d["html"], "response_headers": {}}
                     for d in probed.values()]
    tech = detect_technologies(pseudo_pages)
    tech_summary = format_tech_for_prompt(tech, len(pseudo_pages))
    total_techs = sum(len(v) for v in tech.values())
    _cb("source_done", {"source": "tech_detect", "status": "done",
                        "summary": f"{total_techs} technologies across {len(pseudo_pages)} pages",
                        "detail": tech_summary})

    # Capture probed pages as sources
    for cap, d in probed.items():
        _pending_sources.append({
            "source_type": "web_crawl",
            "url": d["url"],
            "title": (d.get("title") or f"{cap} page")[:500],
            "content": re.sub(r"<[^>]+>", " ", d["html"])[:50000],
            "raw_data": None,
        })
    _pending_sources.append({
        "source_type": "ops_maturity",
        "url": final_url,
        "title": f"Operations maturity signals: {company_name or domain}"[:500],
        "content": ops_summary,
        "raw_data": None,
    })

    # --- Report ---
    prompt = build_ops_maturity_prompt(final_url, company_name or domain, ops_summary, tech_summary)
    prompt += get_temporal_context(company_name or domain, "ops_maturity")

    _cb("generating", {"detail": "LLM synthesizing operations maturity report"})
    print("[ops] Generating report...")
    text, model = generate_text(prompt)

    today = datetime.now().strftime("%Y-%m-%d")
    if company_name:
        safe_prefix = company_name.lower().replace(" ", "_").replace(".", "_")
    else:
        base_domain = re.sub(r"^www\.", "", domain).split(".")[0]
        safe_prefix = base_domain.replace("-", "_")

    header = f"""# Operations Maturity Assessment: {company_name or domain}

**URL:** {final_url}
**Pages probed:** {len(probed)} of {len(signals['pages_found']) + len(signals['pages_missing'])} known types | **Date:** {today}
**Software detected:** {total_techs} | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = unique_report_path(reports_dir, f"{safe_prefix}_ops_maturity_{today}.md")
    filename.write_text(report, encoding="utf-8")

    print(f"[ops] Report saved to {filename}")
    dossier_name = company_name or domain
    dossier_result = save_to_dossier(dossier_name, "ops_maturity", report_file=str(filename),
                                     report_text=report, model_used=model, progress_cb=_cb)
    _flush_sources(dossier_name, dossier_result, _pending_sources)
    _cb("report_saved", {"path": str(filename), "model": model})
    return str(filename)


def _flush_sources(company, dossier_result, pending_sources):
    """Persist collected sources. Mirrors the techstack agent's non-fatal pattern."""
    if not dossier_result or not pending_sources:
        return
    try:
        from agents.source_capture import capture_and_embed
        _use_rag = True
    except Exception:
        _use_rag = False

    try:
        conn = get_connection()
        dossier_id = dossier_result["dossier_id"]
        analysis_id = dossier_result["analysis_id"]
        source_ids = []
        seen_urls = set()
        for s in pending_sources:
            url = s.get("url")
            if url and (url, s["source_type"]) in seen_urls:
                continue
            if url:
                seen_urls.add((url, s["source_type"]))
            try:
                if _use_rag:
                    sid, _ = capture_and_embed(
                        conn, dossier_id=dossier_id, source_type=s["source_type"],
                        title=s.get("title"), url=s.get("url"), content=s.get("content"),
                        metadata=None, source_date=None, sections=None,
                        dedup_kwargs={"url": s.get("url") or ""},
                    )
                else:
                    sid = save_source_document(
                        conn, dossier_id, s["source_type"], s.get("url"),
                        s.get("title"), s.get("content"), s.get("raw_data"),
                    )
                source_ids.append(sid)
            except Exception as e:
                print(f"[sources] Failed to save source '{s.get('title', '')}': {e}")
        if analysis_id and source_ids:
            link_sources_to_analysis(conn, analysis_id, source_ids)
        conn.close()
        print(f"[sources] Saved {len(source_ids)} source documents for {company}")
    except Exception as e:
        print(f"[sources] Error saving source documents: {e}")
