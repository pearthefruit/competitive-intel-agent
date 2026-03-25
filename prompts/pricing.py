"""Prompt templates for product & pricing intelligence reports."""


def build_pricing_prompt(url, pricing_pages_text, site_summary):
    """Build prompt for LLM-generated pricing analysis."""
    return f"""You are a product and pricing strategist specializing in competitive intelligence. Analyze the following website data for {url} to extract pricing strategy, product tiers, and competitive positioning.

PRICING-RELATED PAGES:
{pricing_pages_text}

SITE OVERVIEW:
{site_summary}

Write a concise pricing intelligence report (500-700 words) with these sections:

## Pricing Model Overview
What pricing model does the company use? (per-seat, usage-based, tiered, flat-rate, freemium, enterprise-only, etc.)

## Tier Breakdown
If tiers are visible, create a comparison table:
| Tier | Price | Key Features | Target Audience |
Analyze what each tier includes and who it targets.

## Feature Differentiation
What features are gated behind higher tiers? What's the upgrade path? What drives upsells?

## Positioning Strategy
How does the pricing position the company? (premium, value, market leader, challenger, etc.)
What signals does the pricing page send about their target market?

## Competitive Pricing Assessment
Based on the product type and pricing structure, how does this compare to typical market pricing?
Is there a free tier or trial? What's the conversion strategy?

Rules:
- Only report pricing and features that are visible in the page data. Do not guess specific dollar amounts if not shown.
- If the pricing page says "Contact Sales" or "Request a Demo" with no public pricing, note this as enterprise/sales-led pricing.
- Be direct and analytical — this is competitive intelligence.
- Note if pricing information was limited or hidden.

CITATION FORMAT (like Perplexity — clickable numbered links):
- Assign each crawled page URL a number (1, 2, 3...).
- When referencing specific pricing, features, or claims from a page, add a clickable superscript citation: `[¹](url)`, `[²](url)`, etc.
- Use Unicode superscript characters: ¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹
- Reuse the same number when citing the same page again.

## Sources
At the end, list all numbered sources. YOU MUST INCLUDE THE FULL 'https://' URL for every source:
1. [Page Title](url)
2. [Page Title](url)
...and so on.
"""
