"""Prompt for discovering prospective companies in a niche/vertical."""


def build_discovery_prompt(niche, search_results_text, context=None):
    """Build a prompt to extract company names from search results.

    Args:
        niche: The vertical/niche being prospected (e.g. "DTC skincare brands")
        search_results_text: Formatted search results from web/Reddit/news
        context: Optional structured fields from Niche Builder:
            {vertical, company_size, geography, business_model, qualifiers}

    Returns:
        Prompt string expecting JSON array output.
    """
    context = context or {}

    # Build structured context block if available
    ctx_lines = []
    if context.get("vertical"):
        ctx_lines.append(f"- **Vertical / Industry:** {context['vertical']}")
    if context.get("company_size"):
        ctx_lines.append(f"- **Target Size:** {context['company_size']}")
    if context.get("business_model"):
        ctx_lines.append(f"- **Business Model:** {context['business_model']}")
    if context.get("geography"):
        ctx_lines.append(f"- **Geography:** {context['geography']}")
    if context.get("qualifiers"):
        ctx_lines.append(f"- **Additional Qualifiers:** {context['qualifiers']}")

    context_block = ""
    if ctx_lines:
        context_block = f"""
## Structured Criteria

{chr(10).join(ctx_lines)}

Use these criteria as hard filters. A company must match ALL specified criteria to be included.
"""

    return f"""You are a GTM research analyst identifying prospective companies.

## Task

Extract a list of **real companies** from the search results below that match this niche:

**Target niche:** {niche}
{context_block}
## Size Constraints

If a size constraint is specified above (or in the niche string), enforce it strictly:
- **Startup**: Early-stage, typically under $20M revenue, under 100 employees
- **SMB / small business**: Under $50M revenue, under 200 employees. Exclude well-known mega-funded brands.
- **Midmarket**: $50M\u2013$500M revenue range
- **Enterprise**: $500M+ revenue
If no size constraint is specified, default to SMB-to-midmarket.

## Geography

If a geography is specified, only include companies headquartered in or primarily operating in that region. "US" means US-based companies. "Global" means no geographic restriction.

## Search Results

{search_results_text}

## Instructions

1. Extract company names, websites, and brief descriptions from the search results.
2. **Only include real, identifiable companies** \u2014 not industry categories, news outlets, or generic mentions.
3. **Exclude mega-brands** already advertising on TV at scale (Nike, Coca-Cola, P&G, Unilever) \u2014 they're not prospects.
4. **Strictly enforce all criteria** (size, geography, business model). If the user asked for SMBs in the US, a $1B Indian enterprise is not a match.
5. **Exclude micro-businesses** with no marketing presence (sole proprietors, local-only shops with no online footprint).
6. **Focus on the sweet spot**: companies with a real digital marketing operation that could benefit from deeper evaluation.
7. Aim for variety \u2014 don't just list the top 3 most-mentioned names.
8. If a company's website URL isn't in the results, infer it from the company name. If unknown, use null.
9. For **description**, write a concise sentence about what the company does and what makes them notable.
10. For **why_included**, explain which specific search signals or criteria make this company a fit.
11. For **evidence**, include 1-3 search result entries that support this company's inclusion. Each entry must use the exact source URL from the search results above, the source title, and a direct quote or specific data point (e.g. "raised $40M Series B in Q1 2026", "Glassdoor rating dropped to 2.8"). Do NOT fabricate URLs — only use URLs that appear in the search results.

## Output Format

Return a JSON array. Each element:
```json
{{{{
  "name": "Company Name",
  "website": "https://example.com",
  "description": "One-sentence description of what they do",
  "estimated_size": "startup | smb | midmarket | enterprise",
  "why_included": "Brief reason this company fits the niche and criteria",
  "evidence": [
    {{{{
      "source_title": "Title of the article or page",
      "source_url": "https://exact-url-from-search-results",
      "snippet": "Direct quote or key data point (1-2 sentences)"
    }}}}
  ]
}}}}
```

Return ONLY the JSON array. No explanation or markdown fences."""
