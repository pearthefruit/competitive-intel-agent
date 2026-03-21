"""Agent 3: Strategic Report — generate competitive intelligence report."""

import os
import json
from datetime import datetime
from collections import Counter
from pathlib import Path

import httpx
import google.generativeai as genai

from db import init_db, get_connection, get_company_id, get_all_classified_jobs, get_company_info
from prompts.analyze import build_analyze_prompt
from scraper.web_search import search_news, format_news_for_prompt

# Providers to try in order for report generation (single call, needs good reasoning)
PROVIDERS = [
    {"name": "groq", "env_key": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions", "model": "llama-3.3-70b-versatile"},
    {"name": "mistral", "env_key": "MISTRAL_API_KEY", "url": "https://api.mistral.ai/v1/chat/completions", "model": "mistral-small-latest"},
    {"name": "gemini", "env_key": "GEMINI_API_KEYS", "url": None, "model": "gemini-2.5-flash-lite"},
]


def _generate_text(prompt):
    """Try providers in order until one works. Returns (text, model_name)."""
    http = httpx.Client(timeout=60, follow_redirects=True)
    for p in PROVIDERS:
        key = os.environ.get(p["env_key"], "").strip()
        if not key:
            continue
        # Handle comma-separated keys (Gemini)
        if "," in key:
            key = key.split(",")[0].strip()

        try:
            if p["name"] == "gemini":
                genai.configure(api_key=key)
                model = genai.GenerativeModel(p["model"])
                response = model.generate_content(prompt)
                http.close()
                return response.text, f"gemini/{p['model']}"
            else:
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                body = {"model": p["model"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
                resp = http.post(p["url"], json=body, headers=headers)
                if resp.status_code == 200:
                    text = resp.json()["choices"][0]["message"]["content"]
                    http.close()
                    return text, f"{p['name']}/{p['model']}"
        except Exception:
            continue
    http.close()
    raise RuntimeError("All providers failed for report generation")


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
    seniority_counts = Counter()
    location_counts = Counter()
    skill_counts = Counter()
    growth_counts = Counter()

    for job in jobs:
        dept_counts[job["department_category"] or "Other"] += 1
        seniority_counts[job["seniority_level"] or "Unknown"] += 1

        loc = job["location"] or "Unknown"
        location_counts[loc] += 1

        skills = _safe_json_loads(job["key_skills"])
        for skill in skills:
            skill_counts[skill] += 1

        growth_counts[job["growth_signal"] or "unclear"] += 1

    return dept_counts, seniority_counts, location_counts, skill_counts, growth_counts


def _format_counter(counter, label, top_n=None):
    """Format a Counter as a readable stats block."""
    items = counter.most_common(top_n)
    total = sum(counter.values())
    lines = [f"  {name}: {count} ({count*100//total}%)" for name, count in items]
    return f"- {label}:\n" + "\n".join(lines)


def _build_classifications_json(jobs, max_jobs=50):
    """Build a compact JSON summary for the LLM prompt, sampling if too many jobs."""
    # For large job sets, send a representative sample to stay under context limits
    sample = jobs if len(jobs) <= max_jobs else jobs[::len(jobs)//max_jobs][:max_jobs]
    summaries = []
    for job in sample:
        summaries.append({
            "title": job["title"],
            "dept": job["department_category"],
            "level": job["seniority_level"],
            "loc": job["location"],
            "skills": _safe_json_loads(job["key_skills"])[:5],
            "signals": _safe_json_loads(job["strategic_signals"])[:2],
        })
    return json.dumps(summaries, indent=1)


def analyze(company_name, db_path="intel.db"):
    """Generate strategic report for the given company.

    Returns path to the generated markdown file.
    """
    init_db(db_path)
    conn = get_connection(db_path)

    company_id = get_company_id(conn, company_name)
    if not company_id:
        print(f"[error] Company '{company_name}' not found. Run collect first.")
        conn.close()
        return None

    company = get_company_info(conn, company_id)
    jobs = get_all_classified_jobs(conn, company_id)
    conn.close()

    if not jobs:
        print(f"[error] No classified jobs for {company_name}. Run classify first.")
        return None

    print(f"[analyze] Generating report for {company_name} ({len(jobs)} jobs)...")

    # Compute stats
    dept_counts, seniority_counts, location_counts, skill_counts, growth_counts = _compute_stats(jobs)

    stats_summary = "\n".join([
        _format_counter(dept_counts, "By department"),
        _format_counter(seniority_counts, "By seniority"),
        _format_counter(location_counts, "By location", top_n=10),
        _format_counter(skill_counts, "Top skills", top_n=15),
        _format_counter(growth_counts, "Growth signals"),
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
        print(f"[analyze] Found {len(unique_news)} recent news articles")
    else:
        print(f"[analyze] No recent news found (report will use hiring data only)")

    # Generate narrative via LLM
    prompt = build_analyze_prompt(company_name, len(jobs), stats_summary, classifications_json, news_context)

    try:
        narrative, model_used = _generate_text(prompt)
        print(f"[analyze] Narrative generated via {model_used}")
    except Exception as e:
        print(f"[error] LLM report generation failed: {e}")
        narrative = "*Report generation failed. See stats below.*"
        model_used = "none"

    # Assemble report
    today = datetime.now().strftime("%Y-%m-%d")
    report = f"""# Competitive Intelligence: {company_name}

**Generated:** {today}
**Jobs analyzed:** {len(jobs)}
**Data source:** {company['url'] or 'N/A'}
**ATS:** {company['ats_type'] or 'N/A'}
**Model:** {model_used}

---

## Hiring Snapshot

### By Department
| Department | Count | % |
|-----------|-------|---|
"""
    total = sum(dept_counts.values())
    for dept, count in dept_counts.most_common():
        report += f"| {dept} | {count} | {count*100//total}% |\n"

    report += f"""
### By Seniority
| Level | Count | % |
|-------|-------|---|
"""
    for level, count in seniority_counts.most_common():
        report += f"| {level} | {count} | {count*100//total}% |\n"

    report += f"""
### Top Skills
| Skill | Mentions |
|-------|----------|
"""
    for skill, count in skill_counts.most_common(20):
        report += f"| {skill} | {count} |\n"

    report += f"""
### Top Locations
| Location | Count |
|----------|-------|
"""
    for loc, count in location_counts.most_common(10):
        report += f"| {loc} | {count} |\n"

    report += f"""
---

{narrative}
"""

    # Save to file
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    safe_name = company_name.lower().replace(" ", "_").replace("/", "_")
    filename = reports_dir / f"{safe_name}_{today}.md"
    filename.write_text(report, encoding="utf-8")

    print(f"[analyze] Report saved to {filename}")
    return str(filename)
