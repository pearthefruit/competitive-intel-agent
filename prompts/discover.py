"""Prompt for discovering prospective companies in a niche/vertical."""


def build_discovery_prompt(niche, search_results_text, context=None, top_n=15):
    """Build a prompt to extract company names from search results.

    Args:
        niche: The vertical/niche being prospected (e.g. "DTC skincare brands")
        search_results_text: Formatted search results from web/Reddit/news
        context: Optional structured fields from Niche Builder:
            {vertical, company_size, geography, business_model, qualifiers}
        top_n: Target number of companies to extract

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

Extract **at least {top_n} companies** from the search results below that match this niche:

**Target niche:** {niche}
{context_block}
## How many companies to return

You MUST return at least {top_n} companies. It is better to include a borderline company than to return fewer than {top_n}. If you can only find fewer than {top_n} strong matches, include companies that are partial matches or adjacent to the niche — flag them with a lower confidence in `why_included`. The user will filter later; your job is to surface candidates, not gatekeep.

## Size Constraints

If a size constraint is specified above (or in the niche string), prefer companies in that range but do NOT exclude companies solely for being slightly outside the range. Include them and note the size mismatch in `why_included`.
- **Startup**: Early-stage, typically under $20M revenue, under 100 employees
- **SMB / small business**: Under $50M revenue, under 200 employees
- **Midmarket**: $50M\u2013$500M revenue range
- **Enterprise**: $500M+ revenue
If no size constraint is specified, include companies of any size.

## Geography

If a geography is specified, prefer companies in that region but include notable companies outside it if they operate there. "Global" means no geographic restriction.

## Search Results

{search_results_text}

## Instructions

1. Extract company names, websites, and brief descriptions from the search results.
2. **Only include real, identifiable companies** \u2014 not industry categories, news outlets, or generic mentions.
3. **Include well-known market leaders** in this space \u2014 they provide useful reference points even if they seem obvious.
4. If the search results mention fewer than {top_n} companies, use your knowledge to add relevant companies in this niche that the search may have missed. Clearly note these as "Added from domain knowledge" in `why_included`.
5. Aim for variety \u2014 don't just list the top 3 most-mentioned names.
6. If a company's website URL isn't in the results, infer it from the company name. If unknown, use null.
7. For **description**, write a concise sentence about what the company does and what makes them notable.
8. For **why_included**, explain which specific search signals or criteria make this company a fit.
9. For **evidence**, include 1-3 search result entries that support this company's inclusion. Each entry must use the exact source URL from the search results above, the source title, and a direct quote or specific data point. Do NOT fabricate URLs — only use URLs that appear in the search results. For companies added from domain knowledge, evidence may be empty.

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


def build_query_generation_prompt(niche, context=None):
    """Build a prompt for LLM-powered search query generation.

    Instead of template-based queries, the LLM decomposes a complex niche
    description into targeted, concise search queries that work well with
    DuckDuckGo and Google News RSS.
    """
    context = context or {}

    ctx_lines = []
    if context.get("vertical"):
        ctx_lines.append(f"- Vertical: {context['vertical']}")
    if context.get("company_size"):
        ctx_lines.append(f"- Target company size: {context['company_size']}")
    if context.get("business_model"):
        ctx_lines.append(f"- Business model: {context['business_model']}")
    if context.get("geography"):
        ctx_lines.append(f"- Geography: {context['geography']}")
    if context.get("qualifiers"):
        ctx_lines.append(f"- Additional filters: {context['qualifiers']}")

    context_block = "\n".join(ctx_lines) if ctx_lines else "No additional context provided."

    return f"""You are a search query strategist. Your job is to generate targeted search queries that will surface real companies matching a niche description.

## Niche Description

"{niche}"

## Structured Context

{context_block}

## Instructions

Generate 12-14 search queries optimized for DuckDuckGo and Google News RSS. Each query must be SHORT (3-8 words ideal — DuckDuckGo performs poorly with long queries).

**Query design principles:**
1. **Decompose the niche** into industry terms, product categories, and synonyms. Do NOT use the raw niche string as a query — break it down.
2. **Use industry jargon** — if the niche implies a specific sector (e.g., proptech, fintech, martech, edtech), use those terms.
3. **Anchor on example companies** — if the niche implies well-known players, generate "competitors to X" or "alternatives to X" queries.
4. **Vary query angles** across these categories:
   - Company listicles: "top [industry] companies", "best [product] platforms"
   - Competitive landscape: "[known player] competitors alternatives"
   - Funding/growth signals: "[industry] startups funding 2025 2026"
   - Industry directories: "list of [industry] vendors", "[industry] market map"
   - News coverage: "[industry] companies expansion growth"
   - Community: "[product type] recommendations reddit"
5. **Apply size/geo filters** where relevant (e.g., "enterprise proptech" or "UK fintech startups")
6. **Never generate a query longer than 10 words** — shorter is better for search engines.

## Output Format

Return a JSON array. Each element:
```json
{{{{"source": "web", "query": "proptech backend platform companies"}}}}
```

**Source types and recommended counts:**
- `"web"` — 6-8 queries (main discovery channel)
- `"news"` — 2 queries (recent coverage = active companies)
- `"gnews"` — 2 queries (broader news coverage via Google News RSS)
- `"reddit"` — 1-2 queries (community signals, use "reddit" in the query if needed)

Return ONLY the JSON array. No explanation or markdown fences."""


def build_similar_discovery_prompt(seed_company, search_results_text, profile=None, top_n=10):
    """Build a prompt to find companies similar to *seed_company*.

    Uses the profile context (industry, services, scale, client_type) from
    ``_profile_lookup`` to anchor the similarity search accurately.  Output
    schema matches ``build_discovery_prompt`` so the rest of the pipeline is
    unchanged.
    """
    profile_block = ""
    if profile:
        parts = []
        if profile.get("industry"):
            parts.append(f"- **Industry:** {profile['industry']}")
        if profile.get("services"):
            svc = profile["services"]
            if isinstance(svc, list):
                svc = ", ".join(svc)
            parts.append(f"- **Services:** {svc}")
        if profile.get("scale"):
            parts.append(f"- **Scale:** {profile['scale']}")
        if profile.get("client_type"):
            parts.append(f"- **Client Type:** {profile['client_type']}")
        if parts:
            profile_block = f"""
## Seed Company Profile

{chr(10).join(parts)}

Use this profile to identify companies with similar business models, industry focus,
client base, and scale.  Do NOT include companies that are merely in the same broad
sector but operate at a fundamentally different scale or serve different markets.
"""

    return f"""You are a GTM research analyst identifying companies similar to a known company.

## Task

Find **at least {top_n} companies** that are direct competitors, close alternatives, or players in the
same niche as **{seed_company}**.

{profile_block}

## How many companies to return

You MUST return at least {top_n} companies. It is better to include a borderline company than to return fewer than {top_n}. If the search results mention fewer than {top_n} similar companies, use your domain knowledge to add relevant ones and note "Added from domain knowledge" in `why_included`.

## Search Results

{search_results_text}

## Instructions

1. Include companies that are **genuinely similar** to {seed_company} — same type of
   business, overlapping customer base or product category. Companies at different scales are OK.
2. **Exclude {seed_company} itself** from results.
3. For **why_included**, explain specifically HOW this company is similar to {seed_company} —
   what they share in terms of market, product, or customer profile.
4. Include evidence from the search results to support each inclusion.
5. Aim for variety — don't just list the 3 most obvious competitors.
6. If a company's website URL isn't in the results, infer it from the company name. If
   unknown, use null.
7. For **evidence**, include 1-3 search result entries that support this company's inclusion.
   Each entry must use the exact source URL from the search results above.  Do NOT
   fabricate URLs — only use URLs that appear in the search results. Evidence may be empty for companies added from domain knowledge.

## Output Format

Return a JSON array. Each element:
```json
{{{{
  "name": "Company Name",
  "website": "https://example.com",
  "description": "One-sentence description of what they do",
  "estimated_size": "startup | smb | midmarket | enterprise",
  "why_included": "How this company is similar to {seed_company}",
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
