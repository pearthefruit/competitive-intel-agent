"""Agent: Employee Sentiment — analyze workplace culture and employer reputation via web search."""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context, unique_report_path
from scraper.web_search import search_web, search_news, search_reddit, search_tiktok, format_search_results, dedup_results
from scraper.google_news import search_google_news
from scraper.hackernews import search_hackernews
from scraper.reddit_rss import search_reddit_rss
from scraper.onepoint3acres import search_1point3acres
from scraper.blind import search_blind
from scraper.tiktok import fetch_tiktok_from_search_results, format_tiktok_for_prompt
from prompts.sentiment import build_sentiment_prompt


def _result_detail(results, max_items=10):
    """Format search results as detail lines for progress events."""
    lines = []
    for r in results[:max_items]:
        title = r.get('title', '')[:80]
        url = r.get('href', r.get('url', ''))
        if title:
            lines.append(f'• {title}' + (f'  ({url})' if url else ''))
    return '\n'.join(lines) if lines else ''


def sentiment_analysis(company, progress_cb=None):
    """Analyze employee sentiment for a company. Returns report path or None.

    Args:
        company: Company name
        progress_cb: Optional callback(event_type, event_data) for structured progress.
            Events emitted: source_start, source_done, generating, report_saved
    """
    _cb = progress_cb or (lambda *a: None)
    print(f"\n[sentiment] Analyzing employee sentiment for {company}...")

    # Multiple targeted searches
    _cb("source_start", {"source": "glassdoor_web", "label": "Glassdoor / Web", "detail": "Searching employee review sites"})
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
        _cb("source_done", {"source": "glassdoor_web", "status": "skipped", "summary": "No results"})
    else:
        _cb("source_done", {"source": "glassdoor_web", "status": "done", "summary": f"{web_count} results", "detail": _result_detail(all_results)})

    # Blind / TeamBlind (anonymous, verified-employee reviews — strong for tech)
    _cb("source_start", {"source": "blind", "label": "Blind", "detail": "Scraping employee reviews"})
    print("[sentiment] Scraping Blind for employee reviews and discussions...")
    blind = search_blind(company, max_results=15)
    if not blind:
        # Fallback to DDG snippets if direct scrape fails
        print("[sentiment] Direct Blind scrape returned nothing, falling back to DDG...")
        blind = search_web(f"site:teamblind.com {company} reviews", max_results=3)
    all_results.extend(blind)
    if blind:
        print(f"[sentiment] Blind returned {len(blind)} results")
        _cb("source_done", {"source": "blind", "status": "done", "summary": f"{len(blind)} results", "detail": _result_detail(blind)})
    else:
        _cb("source_done", {"source": "blind", "status": "skipped", "summary": "No results"})

    # Fishbowl (anonymous professional community — strong for finance/consulting)
    _cb("source_start", {"source": "fishbowl", "label": "Fishbowl", "detail": "Searching professional community posts"})
    print("[sentiment] Searching Fishbowl for professional community posts...")
    fishbowl = search_web(f"site:fishbowlapp.com {company}", max_results=3)
    if not fishbowl:
        fishbowl = search_web(f"fishbowlapp.com {company} reviews culture", max_results=2)
    all_results.extend(fishbowl)
    if fishbowl:
        print(f"[sentiment] Fishbowl returned {len(fishbowl)} results")
        _cb("source_done", {"source": "fishbowl", "status": "done", "summary": f"{len(fishbowl)} results", "detail": _result_detail(fishbowl)})
    else:
        _cb("source_done", {"source": "fishbowl", "status": "skipped", "summary": "No results"})

    # News about workplace/culture (DDG + Google News)
    _cb("source_start", {"source": "news", "label": "News", "detail": "DDG news + Google News for workplace coverage"})
    news = search_news(f"{company} employees workplace culture", max_results=3)
    all_results.extend(news)
    print("[sentiment] Searching Google News for workplace/culture coverage...")
    gnews = search_google_news(f"{company} employees workplace culture", max_results=5, days_back=30)
    all_results.extend(gnews)
    news_count = len(news) + len(gnews)
    if news_count:
        news_all = list(news) + list(gnews)
        _cb("source_done", {"source": "news", "status": "done", "summary": f"{news_count} results", "detail": _result_detail(news_all)})
    else:
        _cb("source_done", {"source": "news", "status": "skipped", "summary": "No results"})

    # Reddit — general search + targeted career subreddits
    _cb("source_start", {"source": "reddit", "label": "Reddit", "detail": "Searching for candid employee perspectives"})
    print("[sentiment] Searching Reddit for candid employee perspectives...")
    reddit = search_reddit(f"{company} working at employee experience", max_results=5)
    all_results.extend(reddit)
    if web_count == 0 and reddit:
        print(f"[sentiment] Reddit returned {len(reddit)} results — these tend to be more candid than formal review sites")
    if reddit:
        _cb("source_done", {"source": "reddit", "status": "done", "summary": f"{len(reddit)} results", "detail": _result_detail(reddit)})
    else:
        _cb("source_done", {"source": "reddit", "status": "skipped", "summary": "No results"})

    # Reddit — career-specific subreddits (finance, consulting, accounting, tech, CS)
    _cb("source_start", {"source": "reddit_rss", "label": "Reddit RSS", "detail": "Searching career subreddits"})
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
        _cb("source_done", {"source": "reddit_rss", "status": "done", "summary": f"{len(career_reddit)} results", "detail": _result_detail(career_reddit)})
    else:
        _cb("source_done", {"source": "reddit_rss", "status": "skipped", "summary": "No results"})

    # Hacker News (tech community — candid takes on companies)
    _cb("source_start", {"source": "hackernews", "label": "Hacker News", "detail": "Searching tech community perspectives"})
    print("[sentiment] Searching Hacker News for tech community perspectives...")
    hn = search_hackernews(f"{company} working culture employees", max_results=5, fetch_comments_top_n=3)
    all_results.extend(hn)
    if web_count == 0 and hn:
        print(f"[sentiment] Hacker News returned {len(hn)} results — useful for tech industry sentiment")
    if hn:
        _cb("source_done", {"source": "hackernews", "status": "done", "summary": f"{len(hn)} results", "detail": _result_detail(hn)})
    else:
        _cb("source_done", {"source": "hackernews", "status": "skipped", "summary": "No results"})

    # 1Point3Acres (Chinese tech community — interview experiences, hiring signals)
    _cb("source_start", {"source": "1point3acres", "label": "1Point3Acres", "detail": "Searching interview experiences"})
    print("[sentiment] Searching 1Point3Acres for interview experiences...")
    onepoint3 = search_1point3acres(company, max_results=15)
    all_results.extend(onepoint3)
    if onepoint3:
        print(f"[sentiment] 1Point3Acres returned {len(onepoint3)} interview posts")
        _cb("source_done", {"source": "1point3acres", "status": "done", "summary": f"{len(onepoint3)} results", "detail": _result_detail(onepoint3)})
    else:
        _cb("source_done", {"source": "1point3acres", "status": "skipped", "summary": "No results"})

    # TikTok (employee culture content, day-in-the-life, company reviews)
    _cb("source_start", {"source": "tiktok", "label": "TikTok", "detail": "Searching employee/culture content"})
    tiktok_text = ""
    try:
        print("[sentiment] Searching TikTok for employee/culture content...")
        tiktok_search = search_tiktok(f"{company} employee review culture", max_results=5)
        if tiktok_search:
            tiktok_items = fetch_tiktok_from_search_results(tiktok_search, max_videos=3)
            if tiktok_items:
                tiktok_text = format_tiktok_for_prompt(tiktok_items)
                print(f"[sentiment] TikTok returned {len(tiktok_items)} videos with content")
                tiktok_detail = '\n'.join(f"• {t.get('title', 'Video')[:80]}  ({t.get('url', '')})" for t in tiktok_items[:5])
                _cb("source_done", {"source": "tiktok", "status": "done", "summary": f"{len(tiktok_items)} videos", "detail": tiktok_detail})
                # Also add as search results for dedup/formatting
                for t in tiktok_items:
                    all_results.append({
                        "title": t.get("title", "TikTok video"),
                        "href": t.get("url", ""),
                        "body": t.get("description", "") or t.get("transcript", "")[:500],
                        "date": t.get("date", ""),
                        "source": "tiktok",
                    })
            else:
                _cb("source_done", {"source": "tiktok", "status": "skipped", "summary": "No video content"})
        else:
            _cb("source_done", {"source": "tiktok", "status": "skipped", "summary": "No results"})
    except Exception as e:
        print(f"[sentiment] TikTok search failed (yt-dlp may not be installed): {e}")
        _cb("source_done", {"source": "tiktok", "status": "error", "summary": str(e)[:80]})

    if not all_results:
        print("[sentiment] No results from any source (web, news, Reddit, Blind, Fishbowl, HN, 1P3A, TikTok)")
        return None

    # Deduplicate (normalized title matching, keeps highest-quality source)
    unique = dedup_results(all_results)

    search_text = format_search_results(unique)

    # Append TikTok transcript/caption data (richer than the snippet in search results)
    if tiktok_text:
        search_text += "\n\n## TikTok Video Content\n\n" + tiktok_text

    # Generate report
    prompt = build_sentiment_prompt(company, search_text)
    prompt += get_temporal_context(company, "sentiment")

    _cb("generating", {"detail": "LLM synthesizing sentiment report"})
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
    filename = unique_report_path(reports_dir, f"{safe_name}_sentiment_{today}.md")
    filename.write_text(report, encoding="utf-8")

    print(f"[sentiment] Report saved to {filename}")
    save_to_dossier(company, "sentiment", report_file=str(filename), report_text=report, model_used=model, progress_cb=_cb)
    _cb("report_saved", {"path": str(filename), "model": model})
    return str(filename)
