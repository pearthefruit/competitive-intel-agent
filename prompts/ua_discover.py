"""Prompt for discovering prospective companies in a niche/vertical."""


def build_discovery_prompt(niche, search_results_text):
    """Build a prompt to extract company names from search results.

    Args:
        niche: The vertical/niche being prospected (e.g. "DTC skincare brands")
        search_results_text: Formatted search results from web/Reddit/news

    Returns:
        Prompt string expecting JSON array output.
    """
    return f"""You are a GTM research analyst identifying companies that are prospects for premium video / streaming TV advertising.

## Task

Extract a list of **real companies** from the search results below that match this niche:

**Target niche:** {niche}

**CRITICAL:** The niche description above is your primary filter. If the user specifies a size constraint (e.g., "SMBs", "startups", "midmarket", "enterprise"), you MUST strictly enforce it:
- **SMBs / small businesses**: Exclude ANY company with estimated revenue over $50M or 200+ employees. Well-known, heavily-funded brands (e.g., companies that have raised $500M+, or are household names) are NOT SMBs.
- **Startups**: Only include early-stage companies, typically under $20M revenue.
- **Midmarket**: $50M–$500M revenue range.
- **Enterprise**: $500M+ revenue.
If no size constraint is specified, default to SMB-to-midmarket.

## Search Results

{search_results_text}

## Instructions

1. Extract company names, websites, and brief descriptions from the search results.
2. **Only include real, identifiable companies** — not industry categories, news outlets, or generic mentions.
3. **Exclude mega-brands** already advertising on TV at scale (Nike, Coca-Cola, P&G, Unilever) — they're not prospects, they already have TV budgets.
4. **Exclude companies that violate the size constraint** in the niche description. If the user asked for SMBs, a company doing $1B+ in revenue is NOT an SMB — exclude it even if it appears in every search result.
5. **Exclude micro-businesses** with no marketing presence (sole proprietors, local-only shops with no online footprint).
6. **Exclude companies whose primary website is clearly a restaurant, brick-and-mortar shop, or personal brand** unless they have clear e-commerce or national brand presence.
7. **Focus on the sweet spot** defined by the niche: companies with a real digital marketing operation (website, social presence, brand recognition) that haven't yet invested in TV/streaming ads.
8. Aim for variety — don't just list the top 3 most-mentioned names.
9. If a company's website URL isn't explicitly in the results, infer it from the company name (e.g., "Glossier" → "glossier.com"). If unknown, use null.

## Output Format

Return a JSON array. Each element:
```json
{{
  "name": "Company Name",
  "website": "https://example.com",
  "description": "One-sentence description of what they do",
  "estimated_size": "startup | smb | midmarket | enterprise",
  "why_included": "Brief reason this company fits the niche"
}}
```

Return ONLY the JSON array. No explanation or markdown fences."""
