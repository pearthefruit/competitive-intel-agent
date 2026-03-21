"""Prompt templates for competitor mapping reports."""


def build_competitor_prompt(company, search_results):
    """Build prompt for LLM-generated competitor landscape analysis."""
    return f"""You are a competitive intelligence analyst. Based on the following search results, map the competitive landscape for "{company}".

SEARCH RESULTS:
{search_results}

Write a concise competitor mapping report (500-700 words) with these sections:

## Competitive Landscape Overview
Brief summary of the market {company} operates in and the competitive dynamics.

## Key Competitors
Create a table:
| Competitor | Category | Key Differentiator | Threat Level |

Include 5-8 competitors. Category = direct, indirect, or emerging. Threat level = high, medium, or low.

## Competitive Differentiators
What makes {company} different from its main competitors? What are competitors doing that {company} is not?

## Market Position
Where does {company} sit in the market? (leader, challenger, niche player, etc.)

## Strategic Threats & Opportunities
Top 3 competitive threats and top 3 opportunities based on the landscape.

Rules:
- Only mention competitors that appear in the search results or are widely known.
- Be specific about what differentiates each competitor.
- Be direct and actionable — this is for strategic decision-making.

CITATION FORMAT (like Perplexity — clickable numbered links):
- Assign each unique source URL a number (1, 2, 3...).
- When referencing a specific claim or data point, add a clickable superscript citation: `[¹](url)`, `[²](url)`, etc.
- Use Unicode superscript characters: ¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹
- Reuse the same number when citing the same source again.

## Sources
At the end, list all numbered sources:
1. [Source Title](url)
2. [Source Title](url)
...and so on.
"""
