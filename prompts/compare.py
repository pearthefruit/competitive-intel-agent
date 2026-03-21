"""Prompt templates for company comparison and landscape analysis."""


def build_comparison_prompt(company_a, company_b, reports_a, reports_b):
    """Build comparison prompt from individual reports for both companies.

    reports_a / reports_b: dict of {analysis_type: report_text}
    """
    sections_a = []
    for atype, content in reports_a.items():
        truncated = content[:2500] if len(content) > 2500 else content
        sections_a.append(f"### {atype.upper()}\n{truncated}")

    sections_b = []
    for atype, content in reports_b.items():
        truncated = content[:2500] if len(content) > 2500 else content
        sections_b.append(f"### {atype.upper()}\n{truncated}")

    text_a = "\n\n".join(sections_a)
    text_b = "\n\n".join(sections_b)

    return f"""You are a senior competitive intelligence analyst. Compare these two companies based on the analysis reports below.

# {company_a.upper()} — ANALYSIS REPORTS
{text_a}

---

# {company_b.upper()} — ANALYSIS REPORTS
{text_b}

---

Write a comparison report with these sections:

## Side-by-Side Overview
A table comparing key metrics across dimensions (financial, market position, talent, innovation). Use actual numbers from the reports.

## Financial Comparison
Who's in a stronger financial position and why? Revenue, growth, profitability, funding.

## Market & Competitive Position
How do they compete? Overlapping markets, differentiation, relative strengths.

## Talent & Culture
Hiring patterns, employee sentiment, team composition differences.

## Innovation & IP
Patent activity, R&D focus, technology bets.

## Strategic Assessment
Who has the stronger position overall? What are each company's key advantages and vulnerabilities relative to the other?

## Key Takeaways
5-7 bullet points — the most important things a decision-maker should know about how these companies compare.

Be specific and data-driven. Use numbers from the reports. Don't hedge — make clear assessments.

CITATION FORMAT (like Perplexity — clickable numbered links):
- The source reports contain URLs (SEC filings, Yahoo Finance, patent links, web articles). Extract them.
- Assign each unique source URL a number (1, 2, 3...).
- When referencing a specific number or claim, add a clickable superscript citation: `[¹](url)`, `[²](url)`, etc.
- Use Unicode superscript characters: ¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹
- Example: "{company_a}'s revenue of $50B [¹](https://sec.gov/...) dwarfs {company_b}'s $12B [²](https://sec.gov/...)."
- Reuse the same number when citing the same source again.

## Sources
At the end, list all numbered sources:
1. [Source Title](url)
2. [Source Title](url)
...and so on for each unique source used."""


def build_landscape_prompt(company, competitors, all_reports):
    """Build landscape overview from reports on company + competitors.

    all_reports: dict of {company_name: {analysis_type: report_text}}
    """
    sections = []
    for comp_name, reports in all_reports.items():
        parts = []
        for atype, content in reports.items():
            truncated = content[:2000] if len(content) > 2000 else content
            parts.append(f"### {atype.upper()}\n{truncated}")
        sections.append(f"# {comp_name.upper()}\n\n" + "\n\n".join(parts))

    all_text = "\n\n---\n\n".join(sections)
    comp_list = ", ".join(competitors)

    return f"""You are a senior competitive intelligence analyst. You've analyzed **{company}** and its top competitors ({comp_list}). Below are the analysis reports for each company.

{all_text}

---

Write a competitive landscape report with these sections:

## Market Map
Overview of the market these companies compete in. Who are the leaders, challengers, and niche players?

## Company Profiles
A comparison table covering: company, estimated revenue/funding, employee count/sentiment, key products, competitive advantage.

## Strengths & Weaknesses Matrix
For each company, list 3 key strengths and 3 key weaknesses based on the data.

## Head-to-Head: {company} vs. Each Competitor
Short paragraph for each competitor explaining how {company} competes with them specifically.

## Competitive Threats
What are the biggest threats to {company} from these competitors?

## Opportunities
Where can {company} gain advantage? Gaps in the market, competitor weaknesses to exploit.

## Strategic Recommendations
5 specific, actionable recommendations for {company} based on this landscape analysis.

Be specific and use data from the reports. Make clear assessments, not hedged statements.

CITATION FORMAT (like Perplexity — clickable numbered links):
- The source reports contain URLs (SEC filings, Yahoo Finance, patent links, web articles). Extract them.
- Assign each unique source URL a number (1, 2, 3...).
- When referencing a specific number or claim, add a clickable superscript citation: `[¹](url)`, `[²](url)`, etc.
- Use Unicode superscript characters: ¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹
- Reuse the same number when citing the same source again.

## Sources
At the end, list all numbered sources:
1. [Source Title](url)
2. [Source Title](url)
...and so on for each unique source used."""


def build_extract_competitors_prompt(company, search_results):
    """Build a short prompt to extract competitor names from search results."""
    return f"""From the search results below, identify the top direct competitors of {company}.

{search_results}

Return ONLY a JSON array of company names, nothing else. Example: ["Company A", "Company B", "Company C"]

Rules:
- Only include direct competitors (companies in the same market/industry)
- Do not include {company} itself
- Maximum 5 companies
- Use the most common/official company name (e.g. "Stripe" not "Stripe Inc.")"""
