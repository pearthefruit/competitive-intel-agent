"""Prompt templates for patent/IP analysis reports."""


def build_patent_prompt(company, patents_text, total_count):
    """Build prompt for LLM-generated patent analysis."""
    return f"""You are an intellectual property analyst specializing in competitive intelligence. Analyze the following US patent data for "{company}" and write a strategic IP assessment.

PATENT DATA (from USPTO Open Data Portal):
{patents_text}

Write a concise patent/IP analysis report (500-700 words) with these sections:

## Patent Portfolio Overview
Total patents, filing frequency, recent vs older filings. Is the company actively innovating?

## Innovation Focus Areas
What technology areas are they investing in most? Group by CPC categories. Identify their core R&D themes.

## Recent Filing Trends
What has the company been patenting recently? Are there shifts in focus compared to older patents?

## Most Notable Patents
Highlight 2-3 patents with the highest citation counts or most strategically interesting claims.

## Strategic IP Assessment
What does the patent portfolio reveal about the company's competitive strategy? Are they building defensive patents, pioneering new technology, or protecting market position? What should competitors be aware of?

Rules:
- Use actual patent numbers and data from the input. Do not fabricate.
- If the patent count is low (<5), note this and what it might mean.
- Be direct and analytical — this is competitive intelligence.
- Focus on strategic implications, not just listing patents.

## Sources
At the end of the report, include a **Sources** section listing the patent URLs from the data (Google Patents links). Format as markdown links: `[US<patent_number> - Title](url)`.
"""


def build_patent_prompt_fallback(company, search_results):
    """Build prompt for patent analysis using web search (when PatentsView has no results)."""
    return f"""You are an intellectual property analyst. No USPTO patent data was found for "{company}" in PatentsView. Based on the following search results, summarize what is publicly known about their IP and innovation activity.

SEARCH RESULTS:
{search_results}

Write a brief IP assessment (300-400 words) covering:
## Innovation & IP Summary
What is known about this company's patent activity, R&D focus, or technology innovation from public sources?

## Strategic Implications
What does the available information suggest about their IP strategy?

Rules:
- Only state what the search results support. Note when information is limited.
- The company may hold patents under a different legal entity name, or may be a private company with limited patent visibility.

## Sources
At the end of the report, include a **Sources** section listing the URLs from the search results. Format as markdown links: `[Title](url)`.
"""
