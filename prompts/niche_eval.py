"""Prompts for niche evaluation — private company financial extraction from search results."""


def build_private_company_prompt(company_name, description=None, search_context=None, niche_context=None):
    """Prompt for FAST_CHAIN to extract financials from web search results.

    search_context is required — we never call the LLM without real data to extract from.
    niche_context (e.g. "local restaurants in Atlanta", "midmarket SaaS companies") is used
    to anchor any estimate when search results contain size signals but no explicit revenue.
    """
    desc_block = f"\nDescription: {description}" if description else ""
    niche_block = f"\nNiche: {niche_context}" if niche_context else ""

    niche_guidance = ""
    if niche_context:
        niche_guidance = f"""
Niche context: "{niche_context}"
Use this ONLY as a sanity check and to anchor estimates when the search results contain
size signals (employee count, funding round, customer count, pricing) but NO explicit revenue.
In that case you may produce a range estimate — put the midpoint in revenue_latest, set
is_estimated=true, and populate estimate_low/estimate_high/estimate_basis.
If there are no size signals at all, return null for all revenue fields regardless of niche.
"""

    return f"""You are a business analyst. Extract financial data for this company from the search results below.
Use ONLY facts stated in the search results. If a data point is not explicitly mentioned, return null.

Company: {company_name}{desc_block}{niche_block}

Search results:
{search_context}
{niche_guidance}
Return JSON only — do NOT use placeholder or example values, do NOT invent data:
{{
  "revenue_latest": null,           // most recent annual revenue in USD, or null if not stated
  "revenue_latest_year": null,      // year of revenue figure, or null
  "revenue_prior": null,            // prior year annual revenue in USD, or null
  "revenue_prior_year": null,       // year of prior figure, or null
  "is_estimated": false,            // true ONLY if revenue_latest is a range midpoint estimate
  "estimate_low": null,             // range low bound in USD (only when is_estimated=true)
  "estimate_high": null,            // range high bound in USD (only when is_estimated=true)
  "estimate_basis": null,           // brief explanation of what signals drove the estimate
  "estimated_employees": null,      // from search results, or null
  "hq_country": null,               // or null
  "sector": null,                   // broad sector, or null
  "industry": null,                 // specific industry, or null
  "confidence": "low"               // "high" (SEC/press release), "medium" (credible report), "low" (estimate)
}}

Rules:
- CRITICAL: return null for any field not found in the search results. Do NOT use numbers from this prompt as defaults.
- Revenue = annual sales/revenue in USD. Convert if needed ("$2B in sales" → 2000000000)
- Funding raised is NOT revenue — never put funding in revenue fields
- If only one revenue figure is found, use revenue_latest; leave revenue_prior null
- If revenue spans multiple years, use the two most recent
- Only set is_estimated=true when you are producing a range estimate from indirect signals + niche context
- Return ONLY the JSON object, no explanation"""
