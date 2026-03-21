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
"""


def build_financial_prompt_private(company, search_results):
    """Build prompt for financial analysis of a private company using search results."""
    return f"""You are a financial analyst specializing in competitive intelligence. The company "{company}" is private and does not file with the SEC. Based on the following search results, write what is publicly known about their financial position.

SEARCH RESULTS:
{search_results}

Write a concise financial intelligence report (400-600 words) with these sections:

## Executive Summary
What is publicly known about this company's financial position.

## Funding & Valuation
Known funding rounds, investors, and valuation estimates.

## Revenue Estimates
Any publicly reported or estimated revenue figures, growth rates.

## Business Model
How the company makes money, based on available information.

## Strategic Implications
What the financial signals suggest about the company's strategy and trajectory.

Rules:
- Only state what the search results support. Clearly note when information is estimated or unconfirmed.
- Be direct and analytical.
- If very little is known, say so — do not speculate extensively.
"""
