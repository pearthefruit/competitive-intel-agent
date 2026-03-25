"""Prompt templates for tech stack analysis reports."""


def build_techstack_prompt(url, tech_summary, page_count, hiring_section=None):
    """Build prompt for LLM-generated tech stack analysis.

    When hiring_section is provided, the prompt requests a dual-source report
    covering both website-detected and hiring-derived technology signals.
    """

    # --- Data sources ---
    data_block = f"""DETECTED TECHNOLOGIES (from website crawl of {page_count} pages):
{tech_summary}"""

    if hiring_section:
        data_block += f"""

HIRING-DERIVED TECHNOLOGY SIGNALS:
{hiring_section}"""

    # --- Report sections ---
    if hiring_section:
        sections = """Write a strategic tech stack analysis report (700-1000 words) with these sections:

## Tech Stack Overview
Summary table of all detected technologies by category AND source (website crawl vs hiring data). Note which are customer-facing technologies vs internal engineering tools.

## Customer-Facing Stack (Website Crawl)
Frontend framework, analytics, marketing tools, and infrastructure detected from the public website. What does this reveal about their engineering team and go-to-market priorities?

## Internal Engineering Stack (Hiring Signals)
Backend languages, databases, cloud infrastructure, DevOps tools, and AI/ML frameworks inferred from job listings. What does this reveal about their core product architecture and engineering investments?

## Stack Convergence & Gaps
Where do website signals and hiring signals align? Where do they diverge? For example, the website may use React (visible in HTML) while job listings reveal the backend is Python/Go — these are complementary. Flag any contradictions or surprising gaps.

## Analytics & Marketing Stack
What analytics, marketing automation, and customer engagement tools do they use? Combine signals from both website detection and hiring (e.g., hiring for Segment/Amplitude engineers vs detecting GA on the website).

## Infrastructure & Cloud Strategy
CDN, hosting, cloud providers, and DevOps/SRE tooling. Combine website detection (CDN headers) with hiring signals (AWS/GCP/Azure skills, Kubernetes, Terraform mentions).

## Strategic Assessment
What does the combined technology picture tell us about engineering maturity, technical direction, and competitive positioning? Include hiring-derived insights (e.g., heavy Kubernetes hiring suggests microservices migration, AI/ML hiring suggests product intelligence investment)."""
    else:
        sections = """Write a concise tech stack analysis report (500-700 words) with these sections:

## Tech Stack Overview
Summary table of all detected technologies by category. Note which are the core technologies vs supporting tools.

## Frontend Architecture
What frontend framework and approach are they using? What does this tell us about their engineering team and priorities?

## Analytics & Marketing Stack
What analytics, marketing automation, and customer engagement tools do they use? What does this reveal about their go-to-market strategy?

## Infrastructure
CDN, hosting, performance monitoring choices. What does this suggest about their scale, reliability requirements, and cloud strategy?

## Strategic Assessment
What does this technology stack tell us about the company's engineering maturity, hiring needs, and technical direction? Any notable technology choices that differentiate them?"""

    # --- Rules ---
    rules = """
Rules:
- Only discuss technologies that were actually detected or mentioned in the data. Do not speculate about undetected tools.
- Note when a technology was detected on all pages vs only some pages (indicates site-wide vs page-specific).
- Be direct and analytical — this is competitive intelligence, not a product review."""

    if hiring_section:
        rules += """
- Clearly attribute each technology to its source: [Website] for crawl-detected, [Hiring] for job-listing-derived.
- When the same technology appears in both sources, note this as a strong confirmation signal.
- Treat job description mentions as indicative of internal stack, not certainties — companies sometimes list aspirational skills."""
    else:
        rules += """
- If the detected tech is minimal, note this and suggest what it might mean (e.g., custom-built stack, server-rendered, minimal client-side)."""

    # --- Citations ---
    citation = """
CITATION FORMAT (like Perplexity — clickable numbered links):
- Assign each crawled page URL a number (1, 2, 3...).
- When referencing a technology detection from a specific page, add a clickable superscript citation: `[¹](url)`, `[²](url)`, etc.
- Use Unicode superscript characters: ¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹
- Reuse the same number when citing the same page again.

## Sources
At the end, list all numbered sources. YOU MUST INCLUDE THE FULL 'https://' URL for every source:
1. [Page Title](url)
2. [Page Title](url)
...and so on."""

    return f"""You are a technology analyst specializing in competitive intelligence. Analyze the following technology signals for {url} and write a strategic technology assessment.

{data_block}

{sections}

{rules}

{citation}
"""
