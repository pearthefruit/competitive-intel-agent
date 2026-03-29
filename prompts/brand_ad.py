"""Prompt templates for brand & advertising intelligence reports."""


def build_brand_ad_prompt(company, search_results):
    """Build prompt for LLM-generated brand & advertising intelligence analysis."""
    return f"""You are an advertising intelligence analyst specializing in brand marketing and media buying patterns. Based on the following search results about "{company}", analyze their advertising activity, brand presence, and marketing investment signals.

SEARCH RESULTS:
{search_results}

Write a concise brand & advertising intelligence report (400-600 words) with these sections:

## Ad Channel Activity
What advertising channels is this company using? Look for evidence of: paid social (Meta/Instagram, TikTok, Snapchat), paid search (Google Ads, Bing), programmatic display, OOH, audio/podcast, CTV/streaming TV, linear TV. Note which channels have confirmed activity vs. inferred.

## Brand Campaign Activity
Recent or ongoing marketing campaigns, brand launches, rebrands, seasonal promotions, or notable creative work. Include any mentions from ad trade publications (AdAge, AdWeek, The Drum, Marketing Dive).

## Marketing Investment Signals
Evidence of marketing budget growth or contraction: CMO/VP Marketing hires, demand gen or media buyer job postings, agency relationships, marketing technology investments, stated ad spend figures.

## Content & Creative Output
Social media presence, YouTube channel activity, influencer partnerships, video ad content, user-generated content campaigns. Is this a brand that produces visual/video content suitable for TV spots?

## Channel Expansion Indicators
Any signals that this company is exploring new advertising channels: mentions of CTV, streaming, connected TV, OTT, "beyond digital," new market expansion, or diversification of media mix. Also note if industry peers are moving into new channels.

Rules:
- Base analysis on what the search results actually say. Do not fabricate campaigns, ad spend figures, or channel usage.
- If information is limited, say so — do not speculate extensively.
- Be direct and analytical — this is sales intelligence for a CTV advertising platform.
- Prioritize recency — a campaign from 6 months ago is more relevant than one from 3 years ago.
- Focus on ADVERTISING and MARKETING signals only. Do not discuss employee sentiment, workplace culture, or Glassdoor ratings.

CITATION FORMAT (like Perplexity — clickable numbered links):
- Assign each unique source URL a number (1, 2, 3...).
- When referencing a claim, add a clickable superscript citation: `[¹](url)`, `[²](url)`, etc.
- Use Unicode superscript characters: ¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹
- Example: "The company launched a TikTok campaign in Q3 [¹](https://adweek.com/...) and hired a new CMO from Pepsi [²](https://linkedin.com/...)."
- Reuse the same number when citing the same source again.

## Sources
At the end, list all numbered sources. YOU MUST INCLUDE THE FULL 'https://' URL for every source:
1. [Source Title](https://...)
2. [Source Title](https://...)
...and so on.
"""
