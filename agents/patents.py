"""Agent: Patent/IP Analysis — agentic USPTO search with name-variation retry."""

from datetime import datetime
from pathlib import Path

from agents.llm import generate_text, generate_json, save_to_dossier, get_temporal_context, FAST_CHAIN, unique_report_path
from scraper.patents import (
    search_patents, search_patents_with_name,
    format_patents_for_prompt,
)
from scraper.stock_data import get_company_industry
from scraper.web_search import search_web, format_search_results
from prompts.patents import build_patent_prompt, build_patent_prompt_fallback


def _research_company_entities(company, industry=""):
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

    industry_context = ""
    if industry:
        industry_context = f"\n\nKnown industry/sector: {industry}"

    # Step 2: LLM synthesizes name variations from training data + web results
    prompt = f"""A user is searching for US patents filed by "{company}". The USPTO search uses the applicant/assignee name field.
{web_context}{industry_context}

Based on both the web research above and your own knowledge, generate ALL possible entity names this company might file patents under. Consider:
- Legal entity variations (Inc., LLC, Corp., etc.)
- Parent or holding companies
- Subsidiaries and acquired companies
- Former names or DBAs ("also known as", "formerly known as", "operates as")
- Research divisions or technology licensing arms

CRITICAL — Entity Disambiguation:
- Only include entities that are GENUINELY the same company or its direct subsidiaries/parents.
- Do NOT include similarly-named but DIFFERENT companies. For example:
  - "Abbott Capital" (PE firm) must NOT include "Abbott Laboratories" (healthcare company)
  - "Delta Dental" must NOT include "Delta Air Lines"
- Do NOT generate overly-broad wildcards (e.g. "Abbott*") if they would match unrelated companies with the same root name. Only use broad wildcards when there is ONE dominant company with that name.
- If the company is in finance, private equity, or consulting, it likely holds ZERO patents — return a short list of only the most precise variations.

Generate a JSON array of 3-12 applicant name search queries. Use wildcards (*) where helpful. Order from most likely to least likely.

Example output for "Google":
["Google*", "Google LLC", "Alphabet*", "DeepMind*", "Waymo*"]

Example output for "Abbott Capital" (a PE firm — NOT Abbott Laboratories):
["Abbott Capital*", "Abbott Capital Management*"]

Return ONLY a JSON array of strings, nothing else."""

    result = generate_json(prompt, chain=FAST_CHAIN)
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


def _search_with_name_variations(company, max_results=25, company_industry="", progress_cb=None):
    """Agentic patent search: try multiple name variations until we find results.

    Returns (patents, total_count, source, matched_name) or ([], 0, None, None).
    """
    _cb = progress_cb or (lambda *a: None)

    # Step 1: Try direct search first
    print(f"[patents] Searching USPTO for \"{company}\"...")
    _cb('source_start', {'source': 'uspto_direct', 'label': 'USPTO Direct Search', 'detail': f'Searching for "{company}"'})
    patents, total, source = search_patents(company, max_results, company_industry)
    if patents:
        patent_detail = '\n'.join(f"• {p.get('patent_title', 'N/A')[:80]}  ({p.get('patent_date', '')})" for p in patents[:10])
        _cb('source_done', {'source': 'uspto_direct', 'status': 'done', 'summary': f'Found {total} patents', 'detail': patent_detail})
        return patents, total, source, company

    _cb('source_done', {'source': 'uspto_direct', 'status': 'skipped', 'summary': 'No direct results'})

    # Step 2: Research company + LLM generates informed name variations
    print(f"[patents] No results for \"{company}\" — researching entity names...")
    _cb('source_start', {'source': 'entity_research', 'label': 'Entity Name Research', 'detail': f'Discovering corporate names for "{company}"'})
    variations = _research_company_entities(company, industry=company_industry)
    print(f"[patents] Trying {len(variations)} name variations: {variations[:5]}...")
    entity_detail = '\n'.join(f'• {v}' for v in variations[:10])
    _cb('source_done', {'source': 'entity_research', 'status': 'done', 'summary': f'{len(variations)} name variations', 'detail': entity_detail})

    # For multi-word companies, track the first word to detect overly-broad variations
    company_words = company.lower().split()
    first_word = company_words[0] if len(company_words) >= 2 else None

    _cb('source_start', {'source': 'name_search', 'label': 'Name Variation Search', 'detail': f'Trying {len(variations)} entity name patterns'})
    for name_query in variations:
        clean_query = name_query.rstrip("*").strip().lower()

        # Skip if it's essentially the same as the original search
        if clean_query == company.lower():
            continue

        # Skip overly-broad variations for multi-word companies:
        # e.g. "Abbott*" for "Abbott Capital" would match Abbott Laboratories
        if first_word and clean_query == first_word:
            print(f"[patents] Skipping overly-broad \"{name_query}\" for \"{company}\"")
            continue

        print(f"[patents] Trying \"{name_query}\"...")
        patents, total = search_patents_with_name(name_query, max_results, company_industry)
        if patents:
            print(f"[patents] Found {total} patents under \"{name_query}\"")
            name_patent_detail = '\n'.join(f"• {p.get('patent_title', 'N/A')[:80]}  ({p.get('patent_date', '')})" for p in patents[:10])
            _cb('source_done', {'source': 'name_search', 'status': 'done', 'summary': f'Found {total} patents under "{name_query}"', 'detail': f'Entity: {name_query}\n{name_patent_detail}'})
            return patents, total, "USPTO ODP", name_query

    print(f"[patents] No patents found under any name variation")
    _cb('source_done', {'source': 'name_search', 'status': 'skipped', 'summary': 'No patents under any variation'})

    return [], 0, None, None


def patent_analysis(company, progress_cb=None):
    """Analyze a company's patent portfolio. Returns report path or None."""
    _cb = progress_cb or (lambda *a: None)
    print(f"\n[patents] Analyzing patent portfolio for {company}...")

    # --- Phase 1: Industry Lookup ---
    _cb('analysis_start', {'analysis_type': 'lookup', 'label': 'Industry Lookup'})
    print(f"[patents] Looking up industry for {company}...")
    _cb('source_start', {'source': 'stock_api', 'label': 'Stock Data API', 'detail': f'Looking up industry for {company}'})
    industry_info = get_company_industry(company)
    industry_str = industry_info.get("industry") or industry_info.get("sector") or ""
    if industry_str:
        print(f"[patents] Industry: {industry_str}")
        industry_detail = '\n'.join(f'• {k}: {v}' for k, v in industry_info.items() if v)
        _cb('source_done', {'source': 'stock_api', 'status': 'done', 'summary': industry_str, 'detail': industry_detail})
    else:
        _cb('source_done', {'source': 'stock_api', 'status': 'skipped', 'summary': 'No stock data'})
        # Fallback: quick web search for industry context
        _cb('source_start', {'source': 'web_industry', 'label': 'Web Industry Search', 'detail': f'Searching web for {company} industry'})
        web_results = search_web(f'"{company}" company industry sector what does', max_results=2)
        if web_results:
            industry_str = " ".join(r.get("body", "") for r in web_results)[:300]
            print(f"[patents] Industry context from web: {industry_str[:80]}...")
            _cb('source_done', {'source': 'web_industry', 'status': 'done', 'summary': industry_str[:80]})
        else:
            _cb('source_done', {'source': 'web_industry', 'status': 'skipped', 'summary': 'No industry context found'})
    _cb('analysis_done', {'analysis_type': 'lookup'})

    # --- Phase 2: Patent Search ---
    _cb('analysis_start', {'analysis_type': 'search', 'label': 'Patent Search'})
    patents, total_count, source, matched_name = _search_with_name_variations(
        company, company_industry=industry_str, progress_cb=_cb
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
        _cb('source_start', {'source': 'web_fallback', 'label': 'Web Search Fallback', 'detail': 'Searching web for patent information'})
        results = search_web(f"{company} patent filings USPTO portfolio", max_results=5)
        results += search_web(f"{company} patent innovation R&D technology", max_results=3)
        if not results:
            print("[patents] No patent information found via any method — company may not hold US patents, or files under an unrelated entity name")
            _cb('source_done', {'source': 'web_fallback', 'status': 'error', 'summary': 'No patent info found via any method'})
            _cb('analysis_done', {'analysis_type': 'search'})
            return None
        web_detail = '\n'.join(f"• {r.get('title', '')[:80]}  ({r.get('href', '')})" for r in results[:10])
        _cb('source_done', {'source': 'web_fallback', 'status': 'done', 'summary': f'{len(results)} web results', 'detail': web_detail})
        search_text = format_search_results(results)
        prompt = build_patent_prompt_fallback(company, search_text)
        total_count = 0
        source = "Web Search"
    _cb('analysis_done', {'analysis_type': 'search'})

    # --- Phase 3: Report Generation ---
    _cb('analysis_start', {'analysis_type': 'report', 'label': 'Report Generation'})
    prompt += get_temporal_context(company, "patents")
    print("[patents] Generating report...")
    _cb('source_start', {'source': 'llm', 'label': 'LLM Synthesis', 'detail': 'Generating patent analysis report'})
    text, model = generate_text(prompt)
    _cb('source_done', {'source': 'llm', 'status': 'done', 'summary': f'Generated via {model}'})

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
    filename = unique_report_path(reports_dir, f"{safe_name}_patents_{today}.md")
    filename.write_text(report, encoding="utf-8")

    print(f"[patents] Report saved to {filename}")
    _cb('report_saved', {'path': str(filename)})
    _cb('analysis_done', {'analysis_type': 'report'})

    save_to_dossier(company, "patents", report_file=str(filename), report_text=report, model_used=model, progress_cb=_cb)
    return str(filename)
