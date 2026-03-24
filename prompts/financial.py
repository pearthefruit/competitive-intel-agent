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
Present a summary table, then 1-2 sentences of commentary:

| Metric | Value |
|--------|-------|
| Stock Price | $X.XX |
| Market Cap | $X.XB |
| P/E Ratio | X.X |
| EV/EBITDA | X.X |
| 52-Week Range | $X - $X |

How does the market value this company relative to its fundamentals? Is it trading at a premium or discount?

## Revenue & Growth
Present a table of revenue by period with YoY growth, then commentary:

| Period | Revenue | YoY Growth |
|--------|---------|------------|
| FY 2024 | $X.XB | +X.X% |
| FY 2023 | $X.XB | +X.X% |
| ... | ... | ... |

Note acceleration or deceleration trends.

## Profitability
Present a margins table, then commentary:

| Period | Gross Margin | Operating Margin | Net Margin |
|--------|-------------|-----------------|------------|
| FY 2024 | X.X% | X.X% | X.X% |
| ... | ... | ... | ... |

Are margins expanding or compressing?

## R&D Investment
R&D spending levels and as % of revenue (if calculable). Use a small table if multiple periods are available. What does this signal about innovation priorities?

## Balance Sheet Strength
Present key balance sheet metrics in a table:

| Metric | Value |
|--------|-------|
| Cash & Equivalents | $X.XB |
| Total Assets | $X.XB |
| Total Liabilities | $X.XB |
| Debt-to-Equity | X.X |

Is the company well-capitalized?

## Market Sentiment & Analyst Outlook
If analyst estimates, price targets, upgrades/downgrades, or news are provided, summarize what the market expects. Use a table for analyst price targets if available. What do forward revenue estimates and analyst actions signal about the company's trajectory?

## Financial Services Metrics (ONLY if this is a financial services firm — skip entirely otherwise)
If the company is an asset manager, bank, insurer, private equity firm, hedge fund, or other financial services firm, include a section with relevant sector-specific metrics:
- **Asset Managers / PE / Hedge Funds:** AUM (assets under management), AUM growth, fee structure (management + performance fees), fund strategy, number of funds
- **Banks:** Net interest margin, capital adequacy ratio (CET1/Tier 1), loan-to-deposit ratio, credit quality (NPL ratio)
- **Insurance:** Gross written premiums, combined ratio, investment portfolio size
Present in a table. If the company is NOT a financial services firm, skip this section entirely.

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
- USE MARKDOWN TABLES for all financial data — tables make numbers scannable. Follow each table with 1-2 sentences of analytical commentary. Do not bury numbers in prose paragraphs.

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
Present a multi-year revenue table, then commentary:

| Year | Revenue | YoY Growth |
|------|---------|------------|
| 2024 | $X.XB | +X.X% |
| 2023 | $X.XB | +X.X% |
| ... | ... | ... |

Is growth accelerating or decelerating? What do analyst consensus estimates project for the next 1-2 years?

## Profitability & Operational Efficiency
Present a margins table, then commentary:

| Year | Gross Margin | Operating Margin | Net Margin |
|------|-------------|-----------------|------------|
| 2024 | X.X% | X.X% | X.X% |
| ... | ... | ... | ... |

Is the company getting more or less efficient? Where is margin pressure coming from?

## Balance Sheet & Capital Allocation
Present key balance sheet metrics in a table:

| Metric | Value |
|--------|-------|
| Cash & Equivalents | $X.XB |
| Total Debt | $X.XB |
| Net Debt | $X.XB |
| Free Cash Flow | $X.XB |

How is the company deploying capital — R&D, capex, acquisitions, buybacks?

## Market Sentiment & Forward Outlook
Analyst price targets, revenue estimates, recent upgrades/downgrades. Use a table for analyst consensus if available. What is the market pricing in?

## Financial Services Metrics (ONLY if this is a financial services firm — skip entirely otherwise)
If the company is an asset manager, bank, insurer, PE firm, hedge fund, or other financial services firm, include sector-specific metrics:
- **Asset Managers / PE / Hedge Funds:** AUM, AUM growth, fee structure, fund strategy, number of funds
- **Banks:** Net interest margin, capital adequacy ratio, loan-to-deposit ratio, credit quality
- **Insurance:** Gross written premiums, combined ratio, investment portfolio size
Present in a table. Skip this section entirely for non-financial-services companies.

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
- USE MARKDOWN TABLES for all financial data — tables make numbers scannable. Follow each table with 1-2 sentences of analytical commentary. Do not bury numbers in prose paragraphs.

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
Reported or estimated revenue figures, growth rates, recent earnings. If multiple data points are available, present them in a markdown table.

## Profitability & Financial Health
Margins, profits, cash position, debt — whatever is available from public reporting or estimates. Use a table if enough metrics are available.

## Funding & Valuation
Known funding rounds, investors, and valuation estimates. If multiple rounds are known, present in a table (Round | Date | Amount | Valuation).

## Financial Services Metrics (ONLY if this is a financial services firm — skip entirely otherwise)
If the company is an asset manager, bank, PE firm, hedge fund, or other financial services firm, include sector-specific metrics even if the firm is private:
- **Asset Managers / PE / Hedge Funds:** AUM (assets under management) — this is often publicly reported even for private firms via SEC ADV filings, press releases, or industry databases. Also include fund strategy, fee structure, and number of funds if available.
- **Banks / Insurance:** Capital ratios, premiums, or other sector-specific metrics if available.
Present in a table. Skip this section entirely for non-financial-services companies.

## Business Model
How the company makes money, based on available information.

## Strategic Implications
What the financial signals suggest about the company's strategy and trajectory.

Rules:
- Only state what the search results support. Clearly note when information is estimated or unconfirmed.
- Be direct and analytical.
- If very little is known, say so — do not speculate extensively.
- When enough data points exist, use markdown tables to present financial data — tables make numbers scannable.

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
