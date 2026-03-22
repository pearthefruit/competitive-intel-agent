"""Agent: Patent/IP Analysis — agentic USPTO search with name-variation retry."""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_text, generate_json, save_to_dossier, get_temporal_context
from scraper.patents import (
    search_patents, search_patents_with_name,
    format_patents_for_prompt,
)
from scraper.web_search import search_web, format_search_results
from prompts.patents import build_patent_prompt, build_patent_prompt_fallback


def _discover_applicant_names(company):
    """Use LLM to brainstorm legal entity names a company might file patents under.

    Returns a list of USPTO search queries (with wildcards).
    """
    prompt = f"""A user is searching for US patents filed by "{company}". The USPTO search uses the applicant/assignee name field.

Companies often file patents under different legal entity names. For example:
- "Microsoft" files under "Microsoft Corporation" and "Microsoft Technology Licensing, LLC"
- "Google" files under "Google LLC" and "Alphabet Inc."
- "Apple" files under "Apple Inc."
- "Meta" files under "Meta Platforms, Inc." and formerly "Facebook, Inc."

Generate a JSON array of 5-10 applicant name search queries for "{company}" that I should try on the USPTO database. Use wildcards (*) where helpful. Order from most likely to least likely.

Example output for "Microsoft":
["Microsoft*", "Microsoft Corporation", "Microsoft Technology Licensing*"]

Return ONLY a JSON array of strings, nothing else."""

    result = generate_json(prompt)
    if isinstance(result, list) and result:
        return [str(q) for q in result[:10]]

    # Fallback: generate basic variations manually
    name = company.strip()
    variations = [
        f"{name}*",
        f"{name} Corporation",
        f"{name} Inc*",
        f"{name} LLC",
        f"{name} Technology*",
        f"{name} Licensing*",
    ]
    return variations


def _search_with_name_variations(company, max_results=25):
    """Agentic patent search: try multiple name variations until we find results.

    Returns (patents, total_count, source, matched_name) or ([], 0, None, None).
    """
    # Step 1: Try direct search first
    print(f"[patents] Searching USPTO for \"{company}\"...")
    patents, total, source = search_patents(company, max_results)
    if patents:
        return patents, total, source, company

    # Step 2: LLM generates name variations
    print(f"[patents] No results for \"{company}\" — asking LLM for name variations...")
    variations = _discover_applicant_names(company)
    print(f"[patents] Trying {len(variations)} name variations: {variations[:5]}...")

    for name_query in variations:
        # Skip if it's essentially the same as the original search
        if name_query.rstrip("*").lower() == company.lower():
            continue

        print(f"[patents] Trying \"{name_query}\"...")
        patents, total = search_patents_with_name(name_query, max_results)
        if patents:
            print(f"[patents] Found {total} patents under \"{name_query}\"")
            return patents, total, "USPTO ODP", name_query

    # Step 3: Web search to discover the actual filing name
    print(f"[patents] Name variations exhausted — searching web for filing names...")
    web_results = search_web(f'"{company}" patent assignee USPTO filing entity name', max_results=5)

    if web_results:
        # Ask LLM to extract entity names from web results
        web_text = "\n".join(
            f"- {r.get('title', '')}: {r.get('body', '')}" for r in web_results
        )
        extract_prompt = f"""From these search results about "{company}" patents, extract the exact legal entity names used to file patents.

{web_text}

Return ONLY a JSON array of entity names found. Example: ["Company Inc.", "Company Technology LLC"]
If no specific names are found, return an empty array: []"""

        names = generate_json(extract_prompt)
        if isinstance(names, list) and names:
            print(f"[patents] Web search found entity names: {names}")
            for entity_name in names[:5]:
                query = f"{entity_name}*" if not entity_name.endswith("*") else entity_name
                print(f"[patents] Trying web-discovered name \"{query}\"...")
                patents, total = search_patents_with_name(query, max_results)
                if patents:
                    print(f"[patents] Found {total} patents under \"{entity_name}\"")
                    return patents, total, "USPTO ODP", entity_name

    if not web_results:
        print(f"[patents] Web search for filing entity names also returned nothing — company may not have US patents or may file through a parent/holding entity")

    return [], 0, None, None


def patent_analysis(company):
    """Analyze a company's patent portfolio. Returns report path or None."""
    print(f"\n[patents] Analyzing patent portfolio for {company}...")

    # Agentic search with name variations
    patents, total_count, source, matched_name = _search_with_name_variations(company)

    if patents:
        patents_text = format_patents_for_prompt(patents, total_count)
        # Note the matched name if different from input
        extra_context = ""
        if matched_name and matched_name.lower().rstrip("*") != company.lower():
            extra_context = f"\nNote: Patents are filed under the entity name \"{matched_name}\" (not \"{company}\").\n"
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
