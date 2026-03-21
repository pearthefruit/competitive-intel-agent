"""Prompt templates for financial analysis reports."""


def build_financial_prompt(company, ticker, financials_text, is_public=True):
    """Build prompt for LLM-generated financial analysis of a public company."""
    return f"""You are a financial analyst specializing in competitive intelligence. Analyze the following SEC EDGAR financial data for {company} (ticker: {ticker}) and write a strategic financial intelligence report.

FINANCIAL DATA (from SEC EDGAR XBRL filings):
{financials_text}

Write a concise financial intelligence report (600-800 words) with these sections:

## Executive Summary
2-3 sentence overview of the company's financial health and trajectory.

## Revenue & Growth
Revenue trends across quarters/years. Calculate and highlight YoY growth rates. Note acceleration or deceleration.

## Profitability
Operating income, net income, gross profit margins. Are margins expanding or compressing?

## R&D Investment
R&D spending levels and as % of revenue (if calculable). What does this signal about innovation priorities?

## Balance Sheet Strength
Cash position, total assets vs liabilities. Is the company well-capitalized?

## Strategic Implications
What do these financials tell us about the company's strategy? Connect financial trends to business decisions (e.g., high R&D = building new products, growing cash = preparing for acquisition).

## Key Risks
2-3 financial risks or red flags visible in the data.

Rules:
- Use actual numbers from the data. Do not fabricate figures.
- Express large numbers in billions/millions for readability.
- Calculate growth rates where consecutive periods are available.
- Be direct and analytical — this is for competitive intelligence, not investor relations.
- If data for a section is missing, note it briefly and move on.

## Sources
At the end of the report, include a **Sources** section listing the SEC filing URLs provided in the data. Format as markdown links: `[Form Type - Date](url)`. If no URLs are available, link to the company's SEC EDGAR page: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}&type=&dateb=&owner=include&count=40`
"""


def build_financial_prompt_private(company, search_results):
    """Build prompt for financial analysis when company is not in SEC EDGAR (private or foreign-listed)."""
    return f"""You are a financial analyst specializing in competitive intelligence. The company "{company}" was not found in SEC EDGAR. It may be a private company, or it may be publicly traded on a non-US exchange (e.g., London Stock Exchange, Euronext, SIX Swiss Exchange, Tokyo Stock Exchange, etc.). Based on the following search results, write what is publicly known about their financial position.

SEARCH RESULTS:
{search_results}

IMPORTANT: First determine whether this company is publicly traded on a non-US exchange, or truly private. This distinction matters for the report framing.

Write a concise financial intelligence report (400-600 words) with these sections:

## Executive Summary
What is publicly known about this company's financial position. Note where the company is listed if it's publicly traded.

## Revenue & Growth
Reported or estimated revenue figures, growth rates, recent earnings.

## Profitability & Financial Health
Margins, profits, cash position, debt — whatever is available from public reporting or estimates.

## Funding & Valuation
For private companies: known funding rounds, investors, and valuation estimates.
For public companies: market cap, recent stock performance, major shareholders.

## Business Model
How the company makes money, based on available information.

## Strategic Implications
What the financial signals suggest about the company's strategy and trajectory.

Rules:
- Only state what the search results support. Clearly note when information is estimated or unconfirmed.
- Do NOT assume the company is private just because it's not in SEC EDGAR — many large companies are listed on non-US exchanges.
- Be direct and analytical.
- If very little is known, say so — do not speculate extensively.

## Sources
At the end of the report, include a **Sources** section listing the URLs from the search results that informed your analysis. Format as markdown links: `[Title](url)`.
"""
