"""Agent: Employee Sentiment — analyze workplace culture and employer reputation via web search."""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context
from scraper.web_search import search_web, search_news, search_reddit, format_search_results
from scraper.hackernews import search_hackernews
from scraper.reddit_rss import search_reddit_rss
from scraper.onepoint3acres import search_1point3acres
from prompts.sentiment import build_sentiment_prompt


def sentiment_analysis(company):
    """Analyze employee sentiment for a company. Returns report path or None."""
    print(f"\n[sentiment] Analyzing employee sentiment for {company}...")

    # Multiple targeted searches
    queries = [
        f"{company} glassdoor reviews",
        f"{company} employee reviews workplace",
        f"{company} workplace culture",
        f"{company} best place to work",
    ]

    all_results = []
    for query in queries:
        results = search_web(query, max_results=3)
        all_results.extend(results)

    web_count = len(all_results)
    if web_count == 0:
        print(f"[sentiment] No Glassdoor/web results — company may be too small, too new, or using an unusual name that search engines don't associate with employer reviews")

    # Blind / TeamBlind (anonymous, verified-employee reviews — strong for tech)
    print("[sentiment] Searching Blind for anonymous employee reviews...")
    blind = search_web(f"site:teamblind.com {company} reviews", max_results=3)
    if not blind:
        blind = search_web(f"teamblind.com {company} employee reviews", max_results=2)
    all_results.extend(blind)
    if blind:
        print(f"[sentiment] Blind returned {len(blind)} results")

    # Fishbowl (anonymous professional community — strong for finance/consulting)
    print("[sentiment] Searching Fishbowl for professional community posts...")
    fishbowl = search_web(f"site:fishbowlapp.com {company}", max_results=3)
    if not fishbowl:
        fishbowl = search_web(f"fishbowlapp.com {company} reviews culture", max_results=2)
    all_results.extend(fishbowl)
    if fishbowl:
        print(f"[sentiment] Fishbowl returned {len(fishbowl)} results")

    # News about workplace/culture
    news = search_news(f"{company} employees workplace culture", max_results=3)
    all_results.extend(news)

    # Reddit — general search + targeted career subreddits
    print("[sentiment] Searching Reddit for candid employee perspectives...")
    reddit = search_reddit(f"{company} working at employee experience", max_results=5)
    all_results.extend(reddit)
    if web_count == 0 and reddit:
        print(f"[sentiment] Reddit returned {len(reddit)} results — these tend to be more candid than formal review sites")

    # Reddit — career-specific subreddits (finance, consulting, accounting, tech, CS)
    career_subs = [
        "FinancialCareers", "consulting", "Big4",
        "cscareerquestions", "ExperiencedDevs",
        "Accounting", "MBA",
    ]
    print(f"[sentiment] Searching {len(career_subs)} career subreddits...")
    career_reddit = search_reddit_rss(
        f"{company} working culture",
        max_results=5,
        subreddits=career_subs,
        fetch_comments_top_n=3,
    )
    all_results.extend(career_reddit)
    if career_reddit:
        print(f"[sentiment] Career subreddits returned {len(career_reddit)} results")

    # Hacker News (tech community — candid takes on companies)
    print("[sentiment] Searching Hacker News for tech community perspectives...")
    hn = search_hackernews(f"{company} working culture employees", max_results=5, fetch_comments_top_n=3)
    all_results.extend(hn)
    if web_count == 0 and hn:
        print(f"[sentiment] Hacker News returned {len(hn)} results — useful for tech industry sentiment")

    # 1Point3Acres (Chinese tech community — interview experiences, hiring signals)
    print("[sentiment] Searching 1Point3Acres for interview experiences...")
    onepoint3 = search_1point3acres(company, max_results=15)
    all_results.extend(onepoint3)
    if onepoint3:
        print(f"[sentiment] 1Point3Acres returned {len(onepoint3)} interview posts")

    if not all_results:
        print("[sentiment] No results from any source (web, news, Reddit, Blind, Fishbowl, HN, 1P3A)")
        return None

    # Deduplicate
    seen = set()
    unique = []
    for r in all_results:
        title = r.get("title", "")
        if title not in seen:
            seen.add(title)
            unique.append(r)

    search_text = format_search_results(unique)

    # Generate report
    prompt = build_sentiment_prompt(company, search_text)
    prompt += get_temporal_context(company, "sentiment")

    print("[sentiment] Generating report...")
    text, model = generate_text(prompt)

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company.lower().replace(" ", "_").replace(".", "_")

    header = f"""# Employee Sentiment Analysis: {company}

**Date:** {today}
**Source:** Web Search | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = reports_dir / f"{safe_name}_sentiment_{today}.md"
    filename.write_text(report, encoding="utf-8")

    print(f"[sentiment] Report saved to {filename}")
    save_to_dossier(company, "sentiment", report_file=str(filename), report_text=report, model_used=model)
    return str(filename)
