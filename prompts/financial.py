"""Prompt templates for financial analysis reports."""


def build_financial_prompt(company, ticker, financials_text, is_public=True):
    """Build prompt for LLM-generated financial analysis of a public company."""
    return f"""You are a financial analyst specializing in competitive intelligence for consulting firms. Analyze the following SEC EDGAR financial data, live market data, analyst estimates, and news for {company} (ticker: {ticker}) and write a strategic financial intelligence report.

FINANCIAL DATA (SEC EDGAR XBRL filings + Yahoo Finance live market data):
{financials_text}

Write a concise financial intelligence report (700-900 words) with these sections:

## Executive Summary
2-3 sentence overview of the company's financial health, market position, and trajectory. Include market cap if available.

## Market Valuation
Current stock price, market cap, enterprise value, and key valuation multiples (P/E, EV/EBITDA, Price/Book). How does the market value this company relative to its fundamentals? Is it trading at a premium or discount? Include 52-week range context.

## Revenue & Growth
Revenue trends across quarters/years. Calculate and highlight YoY growth rates. Note acceleration or deceleration.

## Profitability
Operating income, net income, gross profit margins. Are margins expanding or compressing?

## R&D Investment
R&D spending levels and as % of revenue (if calculable). What does this signal about innovation priorities?

## Balance Sheet Strength
Cash position, total assets vs liabilities. Is the company well-capitalized?

## Market Sentiment & Analyst Outlook
If analyst estimates, price targets, upgrades/downgrades, or news are provided, summarize what the market expects. What do forward revenue estimates and analyst actions signal about the company's trajectory?

## Strategic Implications & Consulting Opportunities
What do these financials tell us about the company's strategy? Connect financial trends to business decisions. Identify potential consulting engagement opportunities — e.g., margin compression → operational efficiency, flat R&D → innovation strategy, revenue decline → restructuring/transformation, rapid growth → scaling challenges, high capex → digital transformation.

## Key Risks
2-3 financial risks or red flags visible in the data.

Rules:
- Use actual numbers from the data. Do not fabricate figures.
- Express large numbers in billions/millions for readability.
- Calculate growth rates where consecutive periods are available.
- Be direct and analytical — this is for competitive intelligence, not investor relations.
- If data for a section is missing, note it briefly and move on.

CITATION FORMAT (like Perplexity — clickable numbered links):
- Assign each unique source a number (1, 2, 3...).
- Every time you reference a specific number or claim, add a clickable superscript citation right after it using this exact markdown format: `[¹](url)`, `[²](url)`, etc.
- Use Unicode superscript characters: ¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹
- Multiple citations on the same claim: `$394.3B [¹](url1)[²](url2)`
- NEVER present a number without a clickable citation link.

Example of correct output:
"Revenue reached $394.3B [¹](https://www.sec.gov/Archives/...) with 4% YoY growth. The stock trades at $247.99 with a market cap of $3.6T [²](https://finance.yahoo.com/quote/{ticker}/). R&D spending hit $29.9B [¹](https://www.sec.gov/Archives/...), representing 7.6% of revenue."

Source numbering:
- Each unique SEC filing URL = one source number
- Yahoo Finance = one source number (https://finance.yahoo.com/quote/{ticker}/)
- SEC EDGAR company page = one source number (https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}&type=&dateb=&owner=include&count=40)
- Reuse the same number when citing the same source again.

## Sources
At the end, list all numbered sources:
1. [SEC 10-K - Date](url)
2. [Yahoo Finance - {ticker}](https://finance.yahoo.com/quote/{ticker}/)
3. [SEC EDGAR - {ticker}](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}&type=&dateb=&owner=include&count=40)
...and so on for each unique source used.
"""


def build_financial_prompt_private(company, search_results, has_statements=False):
    """Build prompt for financial analysis when company is not in SEC EDGAR (private or foreign-listed)."""

    if has_statements:
        # Foreign-listed company with full financial data from Yahoo Finance
        return f"""You are a financial analyst specializing in competitive intelligence for consulting firms. The company "{company}" is publicly traded on a non-US exchange. Full financial statements from Yahoo Finance are provided below alongside web search results.

DATA (Yahoo Finance financial statements + market data + analyst estimates + news + web search):
{search_results}

Write a strategic financial intelligence report (700-900 words) with these sections:

## Executive Summary
2-3 sentence overview: financial health, market position, trajectory. Note the stock exchange and market cap.

## Revenue & Growth Trajectory
Multi-year revenue trends from the financial statements. Calculate YoY growth rates. Is growth accelerating or decelerating? What do analyst consensus estimates project for the next 1-2 years?

## Profitability & Operational Efficiency
Gross margin, operating margin, and net margin trends over time. Is the company getting more or less efficient? Where is margin pressure coming from (COGS, operating expenses, R&D)?

## Balance Sheet & Capital Allocation
Cash position vs debt levels. How is the company deploying capital — R&D, capex, acquisitions, buybacks? Is free cash flow healthy?

## Market Sentiment & Forward Outlook
Analyst price targets, revenue estimates, recent upgrades/downgrades. What is the market pricing in? Use recent news to contextualize — restructuring announcements, M&A, leadership changes, strategic pivots.

## Consulting Engagement Opportunities
Based on the financial signals, identify 2-3 specific consulting opportunities a firm like McKinsey, EY, or Deloitte might pursue. Be specific — connect each opportunity to a financial trend:
- Margin compression → operational transformation / cost optimization
- Flat/declining revenue → growth strategy / market entry / digital channels
- Rising R&D with no revenue lift → innovation strategy / R&D effectiveness
- High debt or cash burn → financial restructuring / working capital optimization
- Rapid growth → scaling operations / org design / tech modernization
- Strategic pivot visible in news → change management / integration (M&A)

Rules:
- Use actual numbers from the financial statements. Do not fabricate figures.
- Calculate margins and growth rates from the data provided.
- Be direct and analytical — this is for competitive intelligence, not investor relations.
- If data for a section is missing, note it briefly and move on.

CITATION FORMAT (like Perplexity — clickable numbered links):
- Assign each unique source URL a number (1, 2, 3...).
- Every time you reference a specific number or claim, add a clickable superscript citation right after it using this exact markdown format: `[¹](url)`, `[²](url)`, etc.
- Use Unicode superscript characters: ¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹
- NEVER present a number or factual claim without a clickable citation link.
- Yahoo Finance data should cite: https://finance.yahoo.com/quote/TICKER/

## Sources
At the end, list all numbered sources:
1. [Source Title](url)
2. [Yahoo Finance - TICKER](url)
...and so on for each unique source used.
"""
    else:
        # Truly private company or no financial data available
        return f"""You are a financial analyst specializing in competitive intelligence. The company "{company}" was not found in SEC EDGAR and no structured financial data is available from Yahoo Finance. It is likely a private company. Based on the following search results, write what is publicly known about their financial position.

SEARCH RESULTS:
{search_results}

Write a concise financial intelligence report (400-600 words) with these sections:

## Executive Summary
What is publicly known about this company's financial position.

## Revenue & Growth
Reported or estimated revenue figures, growth rates, recent earnings.

## Profitability & Financial Health
Margins, profits, cash position, debt — whatever is available from public reporting or estimates.

## Funding & Valuation
Known funding rounds, investors, and valuation estimates.

## Business Model
How the company makes money, based on available information.

## Strategic Implications
What the financial signals suggest about the company's strategy and trajectory.

Rules:
- Only state what the search results support. Clearly note when information is estimated or unconfirmed.
- Be direct and analytical.
- If very little is known, say so — do not speculate extensively.

CITATION FORMAT (like Perplexity — clickable numbered links):
- Assign each unique source URL a number (1, 2, 3...).
- Every time you reference a specific number or claim, add a clickable superscript citation right after it using this exact markdown format: `[¹](url)`, `[²](url)`, etc.
- Use Unicode superscript characters: ¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹
- NEVER present a number or factual claim without a clickable citation link.

## Sources
At the end, list all numbered sources:
1. [Source Title](url)
...and so on for each unique source used.
"""
