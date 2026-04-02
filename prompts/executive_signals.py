"""Prompt templates for executive hiring signals analysis."""


def build_executive_signals_prompt(company, sec_8k_text, news_text, executive_openings_text):
    """Build prompt for LLM-generated executive hiring signals report."""
    sections = []

    if sec_8k_text:
        sections.append(f"SEC 8-K FILINGS (Official disclosures of officer/director changes):\n{sec_8k_text}")
    if executive_openings_text:
        sections.append(f"OPEN EXECUTIVE POSITIONS (from company job boards — shows hiring intent):\n{executive_openings_text}")
    if news_text:
        sections.append(f"NEWS & COMMUNITY SOURCES (press releases, articles, employee discussions):\n{news_text}")

    combined = "\n\n---\n\n".join(sections) if sections else "No data sources returned results."

    return f"""You are a leadership intelligence analyst specializing in executive hiring as an indicator of organizational commitment. Based on the following data about "{company}", analyze executive-level hiring signals.

DATA SOURCES:
{combined}

Write a concise executive signals report (500-800 words) with these sections:

## Executive Summary
2-3 sentences: What does leadership hiring tell us about this company's strategic direction? Are they putting executive weight behind their stated priorities, or is it all middle-management?

## Recent Executive Changes
For each identifiable executive appointment or departure, provide:
- **Name** | **Title** | **Date** (if known) | **Previous Company/Role** (if known)
- One-sentence interpretation: what does this hire signal about the company's direction?

If no specific appointments are found, state that clearly — do not fabricate names or dates.

## Open Executive Searches
List any VP, SVP, C-suite, or senior director positions the company is actively recruiting for. These are leading indicators — they show where leadership intends to invest before the hire is made.

## Strategic Pattern Analysis
What strategic domains is leadership investing in? Map executive hires and searches to domains:
- **AI / Machine Learning** — CTO, VP AI, Chief Data Officer, VP ML
- **Digital Transformation** — Chief Digital Officer, VP Digital, CTO hires from tech companies
- **Product & Growth** — CPO, VP Product, Chief Growth Officer
- **Operations & Efficiency** — COO, VP Operations, Chief Transformation Officer
- **Go-to-Market** — CRO, CMO, VP Sales, Chief Customer Officer
- **Risk & Compliance** — Chief Risk Officer, General Counsel, CISO
- **Finance & M&A** — CFO, VP Corp Dev, VP Strategy

Are they hiring externally (bringing new thinking) or promoting internally (continuity)?

## Leadership Investment Thesis
This is the core insight. Connect the dots:
- Does executive hiring align with the company's public strategy?
- Is there top-down commitment, or are strategic initiatives orphaned below the VP level?
- What does the pattern suggest about organizational readiness for transformation?
- Red flags: executive churn, empty C-suite seats, leadership gaps in critical areas

## Organizational Commitment Assessment
Rate as one of: **Strong** | **Moderate** | **Weak** | **Unclear**
- **Strong**: Multiple recent executive hires in strategic areas, stable leadership team, clear alignment between hires and strategy
- **Moderate**: Some executive activity, mixed signals, or gaps in key areas
- **Weak**: Leadership vacuums, high C-suite turnover, no executive investment in stated priorities
- **Unclear**: Insufficient data to assess

Rules:
- Only report what the data actually shows. Do not fabricate executive names, dates, or appointments.
- If data is limited, say so — a "no signal" finding is still valuable intelligence.
- Focus on the strategic implications, not just listing names and titles.
- Distinguish between confirmed appointments (from SEC filings, press releases) and speculative signals (from job postings, community chatter).

CITATION FORMAT (like Perplexity — clickable numbered links):
- Assign each unique source URL a number (1, 2, 3...).
- When referencing a claim, add a clickable superscript citation: `[¹](url)`, `[²](url)`, etc.
- Use Unicode superscript characters: ¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹
- Reuse the same number when citing the same source again.

## Sources
At the end, list all numbered sources with FULL 'https://' URLs:
1. [Source Title](https://...)
2. [Source Title](https://...)
"""
