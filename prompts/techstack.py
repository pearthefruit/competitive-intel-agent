"""Prompt templates for tech stack analysis reports."""


def build_techstack_prompt(url, tech_summary, page_count):
    """Build prompt for LLM-generated tech stack analysis."""
    return f"""You are a technology analyst specializing in competitive intelligence. Analyze the following detected technologies for {url} (crawled {page_count} pages) and write a strategic technology assessment.

DETECTED TECHNOLOGIES:
{tech_summary}

Write a concise tech stack analysis report (500-700 words) with these sections:

## Tech Stack Overview
Summary table of all detected technologies by category. Note which are the core technologies vs supporting tools.

## Frontend Architecture
What frontend framework and approach are they using? What does this tell us about their engineering team and priorities?

## Analytics & Marketing Stack
What analytics, marketing automation, and customer engagement tools do they use? What does this reveal about their go-to-market strategy?

## Infrastructure
CDN, hosting, performance monitoring choices. What does this suggest about their scale, reliability requirements, and cloud strategy?

## Strategic Assessment
What does this technology stack tell us about the company's engineering maturity, hiring needs, and technical direction? Any notable technology choices that differentiate them?

Rules:
- Only discuss technologies that were actually detected. Do not speculate about undetected tools.
- Note when a technology was detected on all pages vs only some pages (indicates site-wide vs page-specific).
- Be direct and analytical — this is competitive intelligence, not a product review.
- If the detected tech is minimal, note this and suggest what it might mean (e.g., custom-built stack, server-rendered, minimal client-side).

## Sources
At the end of the report, include a **Sources** section listing the page URLs that were crawled for technology detection.
"""
