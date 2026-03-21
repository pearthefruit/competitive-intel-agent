"""CLI entry point for the Competitive Intelligence Agent."""

from dotenv import load_dotenv
load_dotenv()

import click

from agents.collect import collect
from agents.classify import classify
from agents.analyze import analyze
from agents.chat import chat_repl


@click.group()
def cli():
    """Competitive Intelligence Agent — scrape, classify, and analyze job postings."""
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
def classify_cmd(company, db):
    """Classify all unclassified jobs for a company."""
    classify(company, db)


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


@cli.command("chat")
@click.option("--db", default="intel.db", help="SQLite database path")
def chat_cmd(db):
    """Interactive chat — ask questions in plain English."""
    chat_repl(db)


if __name__ == "__main__":
    cli()
