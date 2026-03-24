"""Agent: Patent/IP Analysis — agentic USPTO search with name-variation retry."""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_text, generate_json, save_to_dossier, get_temporal_context
from scraper.patents import (
    search_patents, search_patents_with_name,
    format_patents_for_prompt,
)
from scraper.stock_data import get_company_industry
from scraper.web_search import search_web, format_search_results
from prompts.patents import build_patent_prompt, build_patent_prompt_fallback


def _research_company_entities(company):
    """Web search + LLM to discover all entity names a company might file patents under.

    Searches the web first to gather real info, then asks LLM to synthesize
    name variations from both its training data and the web results.
    Returns a list of USPTO search queries (with wildcards).
    """
    # Step 1: Web search for corporate structure info
    print(f"[patents] Researching corporate structure for \"{company}\"...")
    web_results = search_web(f'"{company}" company subsidiary parent "also known as" OR "formerly" OR "acquired by" OR "operates as"', max_results=4)
    web_results += search_web(f'"{company}" patent assignee USPTO', max_results=2)

    web_context = ""
    if web_results:
        web_context = "\n\nWeb research results about this company:\n" + "\n".join(
            f"- {r.get('title', '')}: {r.get('body', '')}" for r in web_results
        )

    # Step 2: LLM synthesizes name variations from training data + web results
    prompt = f"""A user is searching for US patents filed by "{company}". The USPTO search uses the applicant/assignee name field.
{web_context}

Based on both the web research above and your own knowledge, generate ALL possible entity names this company might file patents under. Consider:
- Legal entity variations (Inc., LLC, Corp., etc.)
- Parent or holding companies
- Subsidiaries and acquired companies
- Former names or DBAs ("also known as", "formerly known as", "operates as")
- Research divisions or technology licensing arms

Generate a JSON array of 5-12 applicant name search queries. Use wildcards (*) where helpful. Order from most likely to least likely.

Example output for "Google":
["Google*", "Google LLC", "Alphabet*", "DeepMind*", "Waymo*"]

Return ONLY a JSON array of strings, nothing else."""

    result = generate_json(prompt)
    if isinstance(result, list) and result:
        return [str(q) for q in result[:12]]

    # Fallback: generate basic variations manually
    name = company.strip()
    variations = [
        f"{name}*",
        f"{name} Corporation",
        f"{name} Inc*",
        f"{name} LLC",
        f"{name} Technology*",
    ]
    return variations


def _search_with_name_variations(company, max_results=25, company_industry=""):
    """Agentic patent search: try multiple name variations until we find results.

    Returns (patents, total_count, source, matched_name) or ([], 0, None, None).
    """
    # Step 1: Try direct search first
    print(f"[patents] Searching USPTO for \"{company}\"...")
    patents, total, source = search_patents(company, max_results, company_industry)
    if patents:
        return patents, total, source, company

    # Step 2: Research company + LLM generates informed name variations
    print(f"[patents] No results for \"{company}\" — researching entity names...")
    variations = _research_company_entities(company)
    print(f"[patents] Trying {len(variations)} name variations: {variations[:5]}...")

    for name_query in variations:
        # Skip if it's essentially the same as the original search
        if name_query.rstrip("*").lower() == company.lower():
            continue

        print(f"[patents] Trying \"{name_query}\"...")
        patents, total = search_patents_with_name(name_query, max_results, company_industry)
        if patents:
            print(f"[patents] Found {total} patents under \"{name_query}\"")
            return patents, total, "USPTO ODP", name_query

    print(f"[patents] No patents found under any name variation")

    return [], 0, None, None


def patent_analysis(company):
    """Analyze a company's patent portfolio. Returns report path or None."""
    print(f"\n[patents] Analyzing patent portfolio for {company}...")

    # Look up company industry for relevance filtering
    print(f"[patents] Looking up industry for {company}...")
    industry_info = get_company_industry(company)
    industry_str = industry_info.get("industry") or industry_info.get("sector") or ""
    if industry_str:
        print(f"[patents] Industry: {industry_str}")
    else:
        # Fallback: quick web search for industry context
        web_results = search_web(f'"{company}" company industry sector what does', max_results=2)
        if web_results:
            industry_str = " ".join(r.get("body", "") for r in web_results)[:300]
            print(f"[patents] Industry context from web: {industry_str[:80]}...")

    # Agentic search with name variations
    patents, total_count, source, matched_name = _search_with_name_variations(
        company, company_industry=industry_str
    )

    if patents:
        patents_text = format_patents_for_prompt(patents, total_count)
        # Note the matched name if different from input
        extra_context = ""
        if matched_name and matched_name.lower().rstrip("*") != company.lower():
            extra_context = f"\nNote: Patents are filed under the entity name \"{matched_name}\" (not \"{company}\").\n"
        if industry_str:
            extra_context += f"\nCompany industry: {industry_str}\n"
        prompt = build_patent_prompt(company, extra_context + patents_text, total_count)
    else:
        # Final fallback: web search for patent information
        print(f"[patents] No patents found in any database — trying web search")
        results = search_web(f"{company} patent filings USPTO portfolio", max_results=5)
        results += search_web(f"{company} patent innovation R&D technology", max_results=3)
        if not results:
            print("[patents] No patent information found via any method — company may not hold US patents, or files under an unrelated entity name")
            return None
        search_text = format_search_results(results)
        prompt = build_patent_prompt_fallback(company, search_text)
        total_count = 0
        source = "Web Search"

    # Generate report
    prompt += get_temporal_context(company, "patents")
    print("[patents] Generating report...")
    text, model = generate_text(prompt)

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company.lower().replace(" ", "_").replace(".", "_")

    header = f"""# Patent/IP Analysis: {company}

**Total Patents:** {total_count} | **Date:** {today}
**Source:** {source or "Web Search"} | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = reports_dir / f"{safe_name}_patents_{today}.md"
    filename.write_text(report, encoding="utf-8")

    print(f"[patents] Report saved to {filename}")
    save_to_dossier(company, "patents", report_file=str(filename), report_text=report, model_used=model)
    return str(filename)
