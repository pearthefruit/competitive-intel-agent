"""Agent: Company Profile — run all analyses concurrently and generate executive summary."""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context
from agents.financial import financial_analysis
from agents.competitors import competitor_analysis
from agents.sentiment import sentiment_analysis
from agents.patents import patent_analysis
from agents.collect import collect
from agents.classify import classify
from agents.analyze import analyze
from prompts.profile import build_profile_prompt


def _run_job_pipeline(company, url, db_path):
    """Run collect → classify → analyze. Returns report path or None."""
    try:
        new, skipped = collect(company, url, db_path)
        if new == 0 and skipped == 0:
            return None
        classify(company, db_path)
        return analyze(company, db_path)
    except Exception as e:
        print(f"[profile] Job pipeline error: {e}")
        return None


def company_profile(company, url=None, db_path="intel.db"):
    """Run all analyses for a company concurrently. Returns executive summary path."""
    print(f"\n{'='*60}")
    print(f"  Company Profile: {company}")
    print(f"{'='*60}\n")

    # Define analysis tasks
    tasks = {
        "financial": lambda: financial_analysis(company),
        "competitors": lambda: competitor_analysis(company),
        "sentiment": lambda: sentiment_analysis(company),
        "patents": lambda: patent_analysis(company),
    }

    tasks["hiring"] = lambda: _run_job_pipeline(company, url, db_path)

    task_names = list(tasks.keys())
    print(f"[profile] Planning {len(task_names)} analyses: {', '.join(task_names)}")

    # Run sequentially to avoid nested ThreadPoolExecutor issues
    # (ddgs web search uses threading internally, nesting pools causes crashes)
    report_paths = {}
    for name, fn in tasks.items():
        try:
            print(f"[profile] Running {name}...")
            path = fn()
            if path:
                report_paths[name] = path
                print(f"[profile] {name} complete: {path}")
            else:
                print(f"[profile] {name} returned no results — see above for reasoning")
        except Exception as e:
            print(f"[profile] {name} failed: {e}")

    # Summarize what we got vs what's missing
    completed = set(report_paths.keys())
    missing = set(task_names) - completed
    if missing:
        print(f"[profile] Missing data for: {', '.join(missing)} — executive summary will have gaps in these areas")

    if not report_paths:
        print("[profile] No analyses completed successfully — cannot generate executive summary")
        return None

    # Read all reports for the executive summary
    print(f"\n[profile] {len(report_paths)} analyses complete. Generating executive summary...")

    report_contents = {}
    for analysis_type, path in report_paths.items():
        try:
            text = Path(path).read_text(encoding="utf-8")
            report_contents[analysis_type] = text
        except Exception:
            pass

    if not report_contents:
        print("[profile] Could not read any reports for summary")
        return None

    # Generate executive summary
    prompt = build_profile_prompt(company, report_contents)
    prompt += get_temporal_context(company, "profile", db_path=db_path)
    text, model = generate_text(prompt)

    # Save
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company.lower().replace(" ", "_").replace(".", "_")

    header = f"""# Company Profile: {company}

**Date:** {today} | **Model:** {model}
**Analyses completed:** {', '.join(report_paths.keys())}

---

"""
    report = header + text

    # Append individual report links
    report += "\n\n---\n\n## Individual Reports\n\n"
    for analysis_type, path in sorted(report_paths.items()):
        report += f"- **{analysis_type.title()}**: [{path}]({path})\n"

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = reports_dir / f"{safe_name}_profile_{today}.md"
    filename.write_text(report, encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"  Profile complete! Executive summary: {filename}")
    print(f"  Individual reports:")
    for analysis_type, path in sorted(report_paths.items()):
        print(f"    {analysis_type}: {path}")
    print(f"{'='*60}")

    save_to_dossier(company, "profile", report_file=str(filename), report_text=report, model_used=model)
    return str(filename)
