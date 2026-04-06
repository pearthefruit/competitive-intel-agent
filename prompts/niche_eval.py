"""Prompts for niche evaluation — private company financial extraction from search results."""


def build_private_company_prompt(company_name, description=None, search_context=None):
    """Prompt for FAST_CHAIN to extract financials from web search results.

    search_context is required — we never call the LLM without real data to extract from.
    """
    desc_block = f"\nDescription: {description}" if description else ""

    return f"""You are a business analyst. Extract financial data for this company from the search results below.
Use ONLY facts from the search results. If a data point isn't mentioned, return null — do NOT guess.

Company: {company_name}{desc_block}

Search results:
{search_context}

Return JSON only:
{{
  "revenue_latest": 400000000,      // most recent annual revenue in USD, or null
  "revenue_latest_year": 2025,      // year of the most recent revenue figure, or null
  "revenue_prior": 280000000,       // prior year annual revenue in USD, or null
  "revenue_prior_year": 2024,       // year of the prior revenue figure, or null
  "estimated_employees": 200,       // from results, or null
  "hq_country": "United States",    // or null
  "sector": "Consumer Staples",     // broad sector, or null
  "industry": "Beverages",          // specific industry, or null
  "confidence": "medium"
}}

Rules:
- Extract revenue figures WITH their years. Look for "2024 revenue", "FY2025 sales", "$400M in 2024", etc.
- Revenue = annual sales/revenue in USD. Convert if needed (e.g., "$2B in sales" → 2000000000)
- Funding raised is NOT revenue — do not confuse the two
- If only one revenue figure is mentioned, put it in revenue_latest and leave revenue_prior null
- If revenue figures span multiple years (e.g., "$18M in 2020" and "$400M in 2024"), use the two most recent
- If the search results don't mention a field at all, return null
- Return ONLY the JSON object, no explanation"""
