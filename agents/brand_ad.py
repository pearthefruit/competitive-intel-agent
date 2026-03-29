"""Agent: Brand & Ad Intelligence — analyze advertising activity, brand campaigns, and marketing signals."""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context, unique_report_path
from scraper.web_search import search_web, search_news, search_reddit, search_youtube, format_search_results
from scraper.reddit_rss import search_reddit_rss
from prompts.brand_ad import build_brand_ad_prompt


def brand_ad_intelligence(company):
    """Analyze brand & advertising intelligence for a company. Returns report path or None."""
    print(f"\n[brand_ad] Analyzing brand & advertising intelligence for {company}...")

    all_results = []

    # --- Web searches: advertising activity, brand strategy, marketing hires ---
    web_queries = [
        (f'"{company}" advertising campaigns', 3),
        (f'"{company}" brand marketing strategy', 3),
        (f'"{company}" CMO VP marketing hire', 3),
        (f'"{company}" media buyer demand gen programmatic', 3),
        (f'"{company}" influencer partnership social media campaign', 3),
    ]

    for query, max_r in web_queries:
        results = search_web(query, max_results=max_r)
        all_results.extend(results)

    web_count = len(all_results)
    if web_count == 0:
        print(f"[brand_ad] No web results — company may have limited advertising footprint")

    # --- Ad trade publications (AdAge, AdWeek, The Drum, Marketing Dive) ---
    print("[brand_ad] Searching ad trade publications...")
    trade_pubs = search_web(
        f'site:adage.com OR site:adweek.com OR site:thedrum.com OR site:marketingdive.com "{company}"',
        max_results=5,
    )
    all_results.extend(trade_pubs)
    if trade_pubs:
        print(f"[brand_ad] Trade publications returned {len(trade_pubs)} results")

    # --- News searches: campaign launches, brand refresh, ad spend ---
    print("[brand_ad] Searching news for advertising activity...")
    news_queries = [
        (f'"{company}" advertising campaign launch', 5),
        (f'"{company}" marketing brand refresh rebrand', 5),
        (f'"{company}" ad spend digital marketing budget', 3),
    ]

    for query, max_r in news_queries:
        results = search_news(query, max_results=max_r)
        all_results.extend(results)

    # --- Reddit: marketing-focused subreddits ---
    print("[brand_ad] Searching marketing subreddits...")
    marketing_subs = ["marketing", "PPC", "advertising", "socialmedia"]
    reddit_rss = search_reddit_rss(
        f'"{company}" advertising marketing',
        max_results=5,
        subreddits=marketing_subs,
        fetch_comments_top_n=2,
    )
    all_results.extend(reddit_rss)
    if reddit_rss:
        print(f"[brand_ad] Marketing subreddits returned {len(reddit_rss)} results")

    # --- Reddit general ---
    reddit_general = search_reddit(f"{company} ads marketing campaign", max_results=3)
    all_results.extend(reddit_general)

    # --- YouTube: ad/commercial content ---
    print("[brand_ad] Searching YouTube for ad/commercial content...")
    yt = search_youtube(f"{company} ad commercial", max_results=5)
    all_results.extend(yt)
    if yt:
        print(f"[brand_ad] YouTube returned {len(yt)} results")

    if not all_results:
        print("[brand_ad] No results from any source (web, news, Reddit, YouTube)")
        return None

    # Deduplicate by title
    seen = set()
    unique = []
    for r in all_results:
        title = r.get("title", "")
        if title not in seen:
            seen.add(title)
            unique.append(r)

    search_text = format_search_results(unique)

    # Generate report
    prompt = build_brand_ad_prompt(company, search_text)
    prompt += get_temporal_context(company, "brand_ad")

    print("[brand_ad] Generating report...")
    text, model = generate_text(prompt)

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company.lower().replace(" ", "_").replace(".", "_")

    header = f"""# Brand & Ad Intelligence: {company}

**Date:** {today}
**Source:** Web Search | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = unique_report_path(reports_dir, f"{safe_name}_brand_ad_{today}.md")
    filename.write_text(report, encoding="utf-8")

    print(f"[brand_ad] Report saved to {filename}")
    save_to_dossier(company, "brand_ad", report_file=str(filename), report_text=report, model_used=model)
    return str(filename)
