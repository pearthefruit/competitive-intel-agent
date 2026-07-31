"""Agent 3: Strategic Report — generate competitive intelligence report."""

import json
from datetime import datetime
from collections import Counter
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context, unique_report_path
from db import init_db, get_connection, get_company_id, get_all_classified_jobs, get_company_info
from prompts.analyze import build_analyze_prompt
from scraper.web_search import search_news, format_news_for_prompt


def _safe_json_loads(text):
    """Try to parse JSON, return empty list on failure."""
    if not text:
        return []
    try:
        result = json.loads(text.replace("'", '"'))
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _compute_stats(jobs):
    """Compute aggregate statistics from classified jobs."""
    dept_counts = Counter()
    subcat_counts = Counter()  # (subcategory, department) pairs
    seniority_counts = Counter()
    location_counts = Counter()
    skill_counts = Counter()
    growth_counts = Counter()
    strategic_tag_counts = Counter()

    for job in jobs:
        dept = job["department_category"] or "Other"
        dept_counts[dept] += 1

        subcat = job.get("department_subcategory") or "General"
        subcat_counts[(subcat, dept)] += 1

        seniority_counts[job["seniority_level"] or "Unknown"] += 1

        loc = job["location"] or "Unknown"
        location_counts[loc] += 1

        skills = _safe_json_loads(job["key_skills"])
        for skill in skills:
            skill_counts[skill] += 1

        growth_counts[job["growth_signal"] or "unclear"] += 1

        tags = _safe_json_loads(job.get("strategic_tags"))
        for tag in tags:
            strategic_tag_counts[tag] += 1

    return (dept_counts, subcat_counts, seniority_counts, location_counts,
            skill_counts, growth_counts, strategic_tag_counts)


def _format_counter(counter, label, top_n=None):
    """Format a Counter as a readable stats block."""
    items = counter.most_common(top_n)
    total = sum(counter.values())
    lines = [f"  {name}: {count} ({count*100//total}%)" for name, count in items]
    return f"- {label}:\n" + "\n".join(lines)


def _format_subcat_counter(subcat_counts, label):
    """Format subcategory counter (keyed by (subcat, dept) tuples)."""
    items = subcat_counts.most_common()
    total = sum(subcat_counts.values())
    lines = [f"  {subcat} ({dept}): {count} ({count*100//total}%)" for (subcat, dept), count in items]
    return f"- {label}:\n" + "\n".join(lines)


def _build_classifications_json(jobs, max_jobs=50):
    """Build a compact JSON summary for the LLM prompt, sampling if too many jobs."""
    sample = jobs if len(jobs) <= max_jobs else jobs[::len(jobs)//max_jobs][:max_jobs]
    summaries = []
    for job in sample:
        entry = {
            "title": job["title"],
            "dept": job["department_category"],
            "subcat": job.get("department_subcategory") or "General",
            "level": job["seniority_level"],
            "loc": job["location"],
            "skills": _safe_json_loads(job["key_skills"])[:5],
            "growth": job.get("growth_signal") or "unclear",
        }
        tags = _safe_json_loads(job.get("strategic_tags"))
        if tags:
            entry["tags"] = tags
        signal = job.get("strategic_signals") or ""
        if signal and signal != "[]":
            entry["signal"] = signal[:100]
        summaries.append(entry)
    return json.dumps(summaries, indent=1)


def _pct(count, total):
    """Calculate percentage, avoiding division by zero."""
    return count * 100 // total if total else 0


def _generate_insufficient_data_report(company_name, company, jobs, db_path):
    """Generate a minimal report when the sample size is too small for analysis."""
    today = datetime.now().strftime("%Y-%m-%d")
    job_list = "\n".join(f"- {j.get('title', 'Unknown')} ({j.get('location', 'N/A')})" for j in jobs)
    report = f"""# Hiring Analysis: {company_name}

**Generated:** {today} | **Jobs found:** {len(jobs)} | **Source:** {company['url'] or 'N/A'}

---

Not enough data for hiring analysis — only {len(jobs)} role(s) found (minimum 10 required).

**Roles found:** {', '.join(j.get('title', 'Unknown') for j in jobs) or 'None'}
"""
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    safe_name = company_name.lower().replace(" ", "_").replace("/", "_")
    filename = unique_report_path(reports_dir, f"{safe_name}_hiring_{today}.md")
    filename.write_text(report, encoding="utf-8")
    print(f"[analyze] Insufficient data report saved to {filename}")
    save_to_dossier(company_name, "hiring", report_file=str(filename), report_text=report, model_used="none", db_path=db_path)
    return str(filename)


def _capture_hiring_sources(company_name, company, jobs, db_path):
    """Register scraped job postings into the source RAG store.

    Until now the hiring agent read jobs from the DB, wrote a report, and
    stopped — the postings themselves (and their ATS provenance) never entered
    ``source_documents`` / ``source_chunks``, so "Chat with Sources" could not
    see them (the ``hiring_data`` source_type was reserved but never written).
    This indexes each posting plus a provenance summary so the hiring evidence
    is semantically searchable and available to the value-creation lens.

    Non-fatal: any failure is logged and swallowed so it never breaks the run.
    """
    try:
        from agents.source_capture import capture_and_embed
        from db import get_or_create_dossier
    except Exception as e:
        print(f"[analyze] Source capture unavailable — skipping hiring source indexing: {e}")
        return

    board_url = company.get("url") or ""
    ats = company.get("ats_type") or "unknown"
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection(db_path)
    try:
        dossier_id = get_or_create_dossier(conn, company_name)
        captured = 0

        for job in jobs:
            title = job.get("title") or "Untitled role"
            job_url = job.get("url") or f"job://{company.get('id')}/{job.get('id')}"
            skills = _safe_json_loads(job.get("key_skills"))
            tags = _safe_json_loads(job.get("strategic_tags"))

            dept = job.get("department_category") or job.get("department") or "Unknown"
            if job.get("department_subcategory"):
                dept = f"{dept} / {job['department_subcategory']}"

            parts = [
                f"Job title: {title}",
                f"Company: {company_name}",
                f"Department: {dept}",
                f"Seniority: {job.get('seniority_level') or 'Unknown'}",
                f"Location: {job.get('location') or 'Unknown'}",
            ]
            if job.get("salary"):
                parts.append(f"Salary: {job['salary']}")
            if skills:
                parts.append(f"Key skills: {', '.join(skills)}")
            if tags:
                parts.append(f"Strategic tags: {', '.join(tags)}")
            parts.append(f"Sourced from: {ats} ATS ({board_url})")
            if job.get("description"):
                parts.append("\nJob description:\n" + str(job["description"]))
            content = "\n".join(parts)

            try:
                _, is_new = capture_and_embed(
                    conn,
                    dossier_id=dossier_id,
                    source_type="hiring_data",
                    title=f"Job posting: {title} — {company_name}",
                    url=job_url,
                    content=content,
                    metadata={
                        "department": job.get("department_category") or job.get("department"),
                        "seniority": job.get("seniority_level"),
                        "location": job.get("location"),
                        "salary": job.get("salary"),
                        "ats": ats,
                        "source_board": job.get("source_board") or board_url,
                    },
                    source_date=job.get("date_posted"),
                )
                if is_new:
                    captured += 1
            except Exception as e:
                print(f"[analyze] Failed to capture job '{title}' (non-fatal): {e}")

        # Provenance summary — directly answers "what job board / ATS?" and
        # gives the retriever an aggregate hiring view. Keyed per company+day so
        # re-runs refresh the counts instead of returning early on dedup.
        dept_counts = Counter((j.get("department_category") or "Other") for j in jobs)
        loc_counts = Counter((j.get("location") or "Unknown") for j in jobs)
        dept_line = ", ".join(f"{d} ({n})" for d, n in dept_counts.most_common())
        loc_line = ", ".join(f"{l} ({n})" for l, n in loc_counts.most_common(8))
        provenance = (
            f"Hiring data provenance for {company_name}.\n"
            f"All {len(jobs)} job postings analyzed were sourced from the {ats} ATS "
            f"at {board_url}.\n"
            f"Scraped and analyzed on {today}.\n"
            f"Department breakdown: {dept_line}.\n"
            f"Top locations: {loc_line}."
        )
        try:
            capture_and_embed(
                conn,
                dossier_id=dossier_id,
                source_type="hiring_data",
                title=f"Hiring provenance — {company_name}",
                url=board_url or f"hiring-provenance://{company_name}",
                content=provenance,
                metadata={"ats": ats, "job_board_url": board_url, "jobs_analyzed": len(jobs)},
                source_date=today,
                dedup_kwargs={"url": f"hiring-provenance://{company_name.lower()}/{today}"},
            )
        except Exception as e:
            print(f"[analyze] Failed to capture hiring provenance (non-fatal): {e}")

        conn.commit()
        print(f"[analyze] Indexed {captured} new hiring source(s) + provenance for {company_name}")
    except Exception as e:
        print(f"[analyze] Hiring source capture failed (non-fatal): {e}")
    finally:
        conn.close()


def analyze(company_name, db_path="intel.db"):
    """Generate strategic report for the given company.

    Returns path to the generated markdown file.
    """
    init_db(db_path)
    conn = get_connection(db_path)

    company_id = get_company_id(conn, company_name)
    if not company_id:
        print(f"[analyze] Company '{company_name}' not found in database — the collect step may not have run, or the company name may not match exactly")
        print(f"[analyze] Try running 'collect' first, or check the exact company name in the database")
        conn.close()
        return None

    company = get_company_info(conn, company_id)
    jobs = get_all_classified_jobs(conn, company_id)
    conn.close()

    if not jobs:
        print(f"[analyze] No classified jobs for {company_name} — the classify step may not have run yet, or all jobs were filtered out")
        print(f"[analyze] Run 'classify' first to categorize collected job postings")
        return None

    if len(jobs) < 10:
        print(f"[analyze] Only {len(jobs)} jobs for {company_name} — insufficient for meaningful hiring analysis (minimum 10)")
        print(f"[analyze] Generating minimal report noting insufficient data")
        return _generate_insufficient_data_report(company_name, company, jobs, db_path)

    print(f"[analyze] Generating report for {company_name} ({len(jobs)} jobs)...")

    # Compute stats
    (dept_counts, subcat_counts, seniority_counts, location_counts,
     skill_counts, growth_counts, strategic_tag_counts) = _compute_stats(jobs)

    total = len(jobs)

    stats_summary = "\n".join([
        _format_counter(dept_counts, "By department"),
        _format_subcat_counter(subcat_counts, "By sub-category"),
        _format_counter(seniority_counts, "By seniority"),
        _format_counter(location_counts, "By location", top_n=10),
        _format_counter(skill_counts, "Top skills", top_n=15),
        _format_counter(growth_counts, "Growth signals"),
        _format_counter(strategic_tag_counts, "Strategic tags") if strategic_tag_counts else "",
    ])

    classifications_json = _build_classifications_json(jobs)

    # Search for recent news to enrich the report
    print(f"[analyze] Searching for recent news about {company_name}...")
    news_articles = search_news(f"{company_name} news", max_results=10)
    news_articles += search_news(f"{company_name} earnings OR funding OR acquisition", max_results=5)

    # Deduplicate by title
    seen_titles = set()
    unique_news = []
    for a in news_articles:
        t = a.get("title", "")
        if t and t not in seen_titles:
            seen_titles.add(t)
            unique_news.append(a)

    news_context = format_news_for_prompt(unique_news) if unique_news else None
    if news_context:
        print(f"[analyze] Found {len(unique_news)} recent news articles to enrich the hiring analysis")
    else:
        print(f"[analyze] No recent news found — report will rely on hiring data alone, which limits strategic context")
        print(f"[analyze] For richer analysis, consider running financial or competitor agents alongside this one")

    # Generate narrative via LLM
    prompt = build_analyze_prompt(company_name, total, stats_summary, classifications_json, news_context)
    prompt += get_temporal_context(company_name, "hiring", db_path=db_path)

    try:
        narrative, model_used = generate_text(prompt)
        print(f"[analyze] Narrative generated via {model_used}")
    except Exception as e:
        print(f"[error] LLM report generation failed: {e}")
        narrative = "*Report generation failed. See stats below.*"
        model_used = "none"

    # Assemble report
    today = datetime.now().strftime("%Y-%m-%d")
    report = f"""# Competitive Intelligence: {company_name}

**Generated:** {today}
**Jobs analyzed:** {total}
**Data source:** {company['url'] or 'N/A'}
**ATS:** {company['ats_type'] or 'N/A'}
**Model:** {model_used}

---

## Hiring Snapshot

### By Department
| Department | Count | % |
|-----------|-------|---|
"""
    for dept, count in dept_counts.most_common():
        report += f"| {dept} | {count} | {_pct(count, total)}% |\n"

    # Sub-category breakdown (the strategic signal)
    report += """
### By Sub-Category
| Sub-Category | Department | Count | % |
|-------------|-----------|-------|---|
"""
    for (subcat, dept), count in subcat_counts.most_common():
        report += f"| {subcat} | {dept} | {count} | {_pct(count, total)}% |\n"

    report += """
### By Seniority
| Level | Count | % |
|-------|-------|---|
"""
    for level, count in seniority_counts.most_common():
        report += f"| {level} | {count} | {_pct(count, total)}% |\n"

    report += """
### Growth Signals
| Signal | Count | % |
|--------|-------|---|
"""
    for signal, count in growth_counts.most_common():
        report += f"| {signal} | {count} | {_pct(count, total)}% |\n"

    if strategic_tag_counts:
        report += """
### Strategic Tags
| Tag | Roles | % |
|-----|-------|---|
"""
        for tag, count in strategic_tag_counts.most_common():
            report += f"| {tag} | {count} | {_pct(count, total)}% |\n"

    report += """
### Top Skills
| Skill | Mentions |
|-------|----------|
"""
    for skill, count in skill_counts.most_common(20):
        report += f"| {skill} | {count} |\n"

    report += """
### Top Locations
| Location | Count | % |
|----------|-------|---|
"""
    for loc, count in location_counts.most_common(15):
        report += f"| {loc} | {count} | {_pct(count, total)}% |\n"

    report += f"""
---

{narrative}
"""

    # Save to file
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    safe_name = company_name.lower().replace(" ", "_").replace("/", "_")
    filename = unique_report_path(reports_dir, f"{safe_name}_hiring_{today}.md")
    filename.write_text(report, encoding="utf-8")

    print(f"[analyze] Report saved to {filename}")
    save_to_dossier(company_name, "hiring", report_file=str(filename), report_text=report, model_used=model_used, db_path=db_path)

    # Register the scraped postings into the source RAG store so the hiring
    # evidence (JDs, roles, ATS provenance) is interrogable via Chat with
    # Sources and available to the value-creation lens.
    _capture_hiring_sources(company_name, company, jobs, db_path)

    return str(filename)
