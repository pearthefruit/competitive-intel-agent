"""Prompt template for the company profile executive summary."""


def build_profile_prompt(company, report_contents):
    """Build the executive summary prompt from individual report contents.

    report_contents: dict of {analysis_type: report_text}
    e.g. {"financial": "...", "competitors": "...", "sentiment": "...", "patents": "..."}
    """
    sections = []
    for analysis_type, content in report_contents.items():
        # Truncate each report to keep prompt manageable
        truncated = content[:3000] if len(content) > 3000 else content
        sections.append(f"## {analysis_type.upper()} ANALYSIS\n{truncated}")

    all_reports = "\n\n---\n\n".join(sections)

    return f"""You are a senior competitive intelligence analyst. You have just completed a comprehensive analysis of **{company}** across multiple dimensions. Below are the individual analysis reports.

Your task: synthesize these into a **single executive summary** that a C-level executive could read in 5 minutes.

---

{all_reports}

---

Write the executive summary with these sections:

## Executive Summary
2-3 paragraph overview of {company}'s current position, key strengths, and primary risks.

## Key Findings
Bullet points — the 5-8 most important findings across all analyses.

## Strategic Position
Where {company} stands in the market: competitive advantages, financial health, innovation posture, talent strategy.

## Risks & Opportunities
Top 3 risks and top 3 opportunities, with supporting evidence from the analyses.

## Recommendations
3-5 actionable recommendations for someone competing with or investing in {company}.

Be concise, data-driven, and specific. Reference actual numbers and findings from the reports. No filler.

## Sources
At the end, include a **Sources** section consolidating all source URLs from the individual reports (SEC filings, patents, web sources). Format as markdown links."""
