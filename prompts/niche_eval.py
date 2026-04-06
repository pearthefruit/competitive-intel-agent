"""Prompts for niche evaluation — private company estimation fallback."""


def build_private_company_prompt(company_name, description=None):
    """Prompt for FAST_CHAIN to estimate financials of a private company.

    Only used when Yahoo Finance and SEC EDGAR return nothing.
    """
    desc_block = f"\nDescription: {description}" if description else ""

    return f"""You are a business analyst. Estimate the following for this company based on your knowledge.
If you are unsure, return null for that field. Do NOT fabricate precise numbers — use round estimates.

Company: {company_name}{desc_block}

Return JSON only:
{{
  "estimated_revenue": 50000000,  // annual USD, or null
  "estimated_employees": 200,     // or null
  "hq_country": "United States",  // or null
  "sector": "Technology",         // broad sector, or null
  "industry": "Software",         // specific industry, or null
  "confidence": "low"             // always "low" for estimates
}}

Rules:
- Revenue should be annual in USD (no formatting, just the number)
- If this is clearly a small startup with no public revenue data, estimate based on funding stage and employee count
- If you genuinely don't know, return null — do not guess wildly
- Return ONLY the JSON object, no explanation"""
