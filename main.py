"""CLI entry point for SignalVault."""

from dotenv import load_dotenv
load_dotenv()

import click

from agents.collect import collect
from agents.classify import classify
from agents.analyze import analyze
from agents.chat import chat_repl
from agents.seo import seo_audit
from agents.financial import financial_analysis
from agents.techstack import techstack_analysis
from agents.patents import patent_analysis
from agents.pricing import pricing_analysis
from agents.competitors import competitor_analysis
from agents.sentiment import sentiment_analysis
from agents.executive_signals import executive_signals_analysis
from agents.profile import company_profile
from agents.compare import compare_companies, landscape_analysis


@click.group()
def cli():
    """SignalVault — research, analyze, and assess digital transformation readiness."""
    pass


@cli.command("collect")
@click.option("--company", required=True, help="Company name")
@click.option("--url", default=None, help="ATS job board URL (auto-detected if omitted)")
@click.option("--db", default="intel.db", help="SQLite database path")
def collect_cmd(company, url, db):
    """Scrape all open roles from an ATS board."""
    collect(company, url, db)


@cli.command("classify")
@click.option("--company", required=True, help="Company name")
@click.option("--db", default="intel.db", help="SQLite database path")
@click.option("--mode", default="comprehensive", type=click.Choice(["fast", "comprehensive"]),
              help="fast=heuristic only (no API calls), comprehensive=heuristic+LLM (default)")
def classify_cmd(company, db, mode):
    """Classify all unclassified jobs for a company."""
    classify(company, db, mode=mode)


@cli.command("analyze")
@click.option("--company", required=True, help="Company name")
@click.option("--db", default="intel.db", help="SQLite database path")
def analyze_cmd(company, db):
    """Generate a strategic intelligence report."""
    analyze(company, db)


@cli.command()
@click.option("--company", required=True, help="Company name")
@click.option("--url", default=None, help="ATS job board URL (auto-detected if omitted)")
@click.option("--db", default="intel.db", help="SQLite database path")
def full(company, url, db):
    """Run the full pipeline: collect → classify → analyze."""
    print(f"\n{'='*60}")
    print(f"  Competitive Intelligence: {company}")
    print(f"{'='*60}\n")

    new, skipped = collect(company, url, db)
    if new == 0 and skipped == 0:
        print("\n[abort] No jobs collected. Check the URL and try again.")
        return

    print()
    classified = classify(company, db)

    print()
    report_path = analyze(company, db)

    if report_path:
        print(f"\n{'='*60}")
        print(f"  Done! Report: {report_path}")
        print(f"{'='*60}")


@cli.command("seo")
@click.option("--url", required=True, help="Website URL to audit")
@click.option("--max-pages", default=10, help="Max pages to crawl (default: 10)")
def seo_cmd(url, max_pages):
    """Run an SEO & AEO audit on a website."""
    seo_audit(url, max_pages)


@cli.command("financial")
@click.option("--company", required=True, help="Company name")
def financial_cmd(company):
    """Run a financial analysis (SEC EDGAR for public, web search for private)."""
    financial_analysis(company)


@cli.command("techstack")
@click.option("--url", required=True, help="Website URL to analyze")
@click.option("--max-pages", default=5, help="Max pages to crawl (default: 5)")
@click.option("--company", default=None, help="Company name (enables hiring data enrichment)")
@click.option("--db", default="intel.db", help="SQLite database path")
def techstack_cmd(url, max_pages, company, db):
    """Detect and analyze a website's technology stack."""
    techstack_analysis(url, max_pages, company_name=company, db_path=db)


@cli.command("patents")
@click.option("--company", required=True, help="Company name")
def patents_cmd(company):
    """Analyze a company's patent portfolio (USPTO data)."""
    patent_analysis(company)


@cli.command("pricing")
@click.option("--url", required=True, help="Website URL to analyze")
def pricing_cmd(url):
    """Analyze a website's pricing strategy and product tiers."""
    pricing_analysis(url)


@cli.command("competitors")
@click.option("--company", required=True, help="Company name")
def competitors_cmd(company):
    """Map the competitive landscape for a company."""
    competitor_analysis(company)


@cli.command("sentiment")
@click.option("--company", required=True, help="Company name")
def sentiment_cmd(company):
    """Analyze employee sentiment and workplace culture."""
    sentiment_analysis(company)


@cli.command("executive-signals")
@click.option("--company", required=True, help="Company name")
@click.option("--db", default="intel.db", help="SQLite database path")
def executive_signals_cmd(company, db):
    """Analyze executive hiring signals — leadership changes and organizational commitment."""
    executive_signals_analysis(company, db_path=db)


@cli.command("profile")
@click.option("--company", required=True, help="Company name")
@click.option("--url", default=None, help="ATS job board URL (optional, enables hiring analysis)")
@click.option("--db", default="intel.db", help="SQLite database path")
def profile_cmd(company, url, db):
    """Run a complete company profile (financial + competitors + sentiment + patents)."""
    company_profile(company, url, db)


@cli.command("compare")
@click.option("--company-a", required=True, help="First company")
@click.option("--company-b", required=True, help="Second company")
def compare_cmd(company_a, company_b):
    """Compare two companies side by side."""
    compare_companies(company_a, company_b)


@cli.command("landscape")
@click.option("--company", required=True, help="Company name")
@click.option("--top-n", default=3, help="Number of competitors to analyze (default: 3)")
def landscape_cmd(company, top_n):
    """Auto-discover competitors and generate landscape analysis."""
    landscape_analysis(company, top_n)


@cli.command("ua-discover")
@click.option("--niche", required=True, help="Target niche/vertical (e.g. 'DTC skincare brands')")
@click.option("--top-n", default=15, help="Max companies to discover (default: 15)")
@click.option("--db", default="intel.db", help="SQLite database path")
def ua_discover_cmd(niche, top_n, db):
    """Discover prospective companies in a niche/vertical."""
    from agents.discover import discover_prospects
    companies = discover_prospects(niche, top_n, db)
    if companies:
        print(f"\n  Discovered {len(companies)} companies in '{niche}'")
    else:
        print(f"\n  No companies found for '{niche}'")


@cli.command("ua-fit")
@click.option("--company", required=True, help="Company name")
@click.option("--url", default=None, help="Company website URL (optional, enables tech detection)")
@click.option("--db", default="intel.db", help="SQLite database path")
def ua_fit_cmd(company, url, db):
    """Score a company's prospect fit using research analyses (techstack, financial, sentiment)."""
    from agents.ua_fit import score_ua_fit
    fit = score_ua_fit(company, website_url=url, db_path=db)
    if fit:
        print(f"\n  {company}: {fit['overall_score']}/100 — {fit['overall_label']}")
        print(f"  Angle: {fit.get('recommended_angle', 'N/A')}")
    else:
        print(f"\n  Failed to score {company}")


@cli.command("ua-pipeline")
@click.option("--niche", required=True, help="Target niche/vertical (e.g. 'DTC skincare brands')")
@click.option("--top-n", default=15, help="Max companies to discover and score (default: 15)")
@click.option("--db", default="intel.db", help="SQLite database path")
def ua_pipeline_cmd(niche, top_n, db):
    """Full pipeline: discover companies, validate websites, run analyses, score prospects."""
    from agents.ua_fit import run_pipeline
    companies, results, report_path = run_pipeline(niche, top_n, db)
    if report_path:
        scored = [(n, f) for n, f in results if f]
        scored.sort(key=lambda x: x[1].get("overall_score", 0), reverse=True)
        print(f"\n{'='*60}")
        print(f"  Pipeline complete: {len(scored)} companies scored")
        print(f"  Report: {report_path}")
        print(f"{'='*60}")
        if scored:
            print(f"\n  Top prospects:")
            for i, (name, fit) in enumerate(scored[:5], 1):
                print(f"    {i}. {name} — {fit['overall_score']}/100 ({fit['overall_label']})")


@cli.command("chat")
@click.option("--db", default="intel.db", help="SQLite database path")
def chat_cmd(db):
    """Interactive chat — ask questions in plain English."""
    chat_repl(db)


@cli.command("forecast")
@click.option("--signal-id", type=int, default=None,
              help="Generate binary forecasts from one signal")
@click.option("--resolve", is_flag=True, help="Resolve forecasts whose data has landed")
@click.option("--score", is_flag=True, help="Show the calibration record")
@click.option("--db", default="intel.db", help="SQLite database path")
def forecast_cmd(signal_id, resolve, score, db):
    """Binary series-bound forecasts — the Brier-scoreable prediction path."""
    from db import get_connection, init_db
    from agents.forecasts import (generate_forecasts_for_signal,
                                  resolve_due_forecasts, brier_summary,
                                  BRIER_COINFLIP, ForecastUnavailable)
    init_db(db)  # idempotent; applies the forecast column migration on older DBs
    conn = get_connection(db)
    try:
        if signal_id:
            row = conn.execute(
                "SELECT id, title, body, domain FROM signals WHERE id = ?",
                (signal_id,)).fetchone()
            if not row:
                print(f"No signal {signal_id}")
                return
            try:
                ids = generate_forecasts_for_signal(
                    row["id"], row["title"], row["body"], row["domain"], conn)
            except ForecastUnavailable as e:
                # Loud on purpose: an outage reported as "0 forecasts" reads as the
                # model declining, and that misreading compounds silently.
                print(f"LLM unavailable — NOT a decline. Nothing judged.\n  {e}")
                return
            if not ids:
                print("Model declined — no forecast for this signal.")
            print(f"Generated {len(ids)} forecast(s): {ids or '—'}")
            for pid in ids:
                p = conn.execute(
                    "SELECT claim, probability, expected_by FROM predictions WHERE id = ?",
                    (pid,)).fetchone()
                print(f"  [{p['probability']:.0%}] {p['claim']}  (resolves ~{p['expected_by']})")

        if resolve:
            print(resolve_due_forecasts(conn))

        if score:
            s = brier_summary(conn)
            if not s["n"]:
                print("No resolved forecasts yet — nothing to score.")
                return
            verdict = "better than chance" if s["vs_coinflip"] > 0 else "worse than chance"
            print(f"\n  Resolved forecasts : {s['n']}")
            print(f"  Brier score        : {s['brier']}  ({verdict}; "
                  f"{BRIER_COINFLIP} = always saying 50%)")
            print(f"  Base rate          : {s['base_rate']:.0%} of forecasts came true")
            print("\n  Reliability (does 70% actually mean 70%?)")
            for b in s["buckets"]:
                print(f"    {b['range']:>9}  n={b['n']:<4} said {b['predicted']:.0%}  "
                      f"happened {b['actual']:.0%}")
            print("\n  By series")
            for r in s["by_series"]:
                print(f"    {r['series_id']:<14} n={r['n']:<4} brier {r['brier']}")
            print()
    finally:
        conn.close()


@cli.command("web")
@click.option("--port", default=5001, help="Port to run on (default: 5001)")
@click.option("--db", default="intel.db", help="SQLite database path")
def web_cmd(port, db):
    """Launch the web dashboard."""
    from web.app import create_app
    app = create_app(db)
    print(f"\n  SignalVault: http://localhost:{port}")
    print(f"  Press Ctrl+C to quit\n")
    # use_reloader=False prevents the reloader from killing background analysis threads
    app.run(debug=True, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    cli()
