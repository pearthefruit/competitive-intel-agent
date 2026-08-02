"""Prompt template for business process / operations maturity reports."""


def build_ops_maturity_prompt(url, company_name, ops_summary, tech_summary=None):
    """Build prompt for an LLM-generated operations maturity assessment.

    Args:
        url: company website
        company_name: display name for the company
        ops_summary: output of scraper.ops_detect.format_ops_for_prompt()
        tech_summary: optional output of scraper.tech_detect.format_tech_for_prompt()
    """
    data_block = f"""DETECTED OPERATIONAL SIGNALS (from targeted page probing of {url}):
{ops_summary}"""

    if tech_summary:
        data_block += f"""

DETECTED SOFTWARE STACK:
{tech_summary}"""

    return f"""You are an operating partner at a lower-middle-market private equity firm conducting \
pre-LOI screening on {company_name} ({url}). You are assessing how much of this business runs on \
repeatable systems versus how much runs out of the owner's head.

This matters because it is the single best predictor of two things: whether the business can survive \
a change of ownership, and how much post-close operating leverage there is to capture.

{data_block}

Write an operations maturity assessment (600-900 words) with these sections:

## Maturity Snapshot
A short table: Demand Generation | Sales Process | Content & Marketing | Self-Serve Capability | \
Hiring Infrastructure | Back-Office Systems. Rate each Absent / Basic / Systematized / Advanced, \
with the specific evidence that justifies the rating in one clause.

## Demand Generation
How do leads reach this business? Is there any mechanism to capture an interested visitor who is \
not ready to buy today (email list, newsletter, gated content), or does every lead require a phone \
call? Name the tooling if it was detected. Absence of an email service provider on a business of \
this size means the customer list is not an asset that transfers cleanly.

## Sales Process
Is there a defined path from interest to purchase — booking/demo/quote page, scheduling tool, \
public pricing, case studies — or does everything route through a contact form? Distinguish a \
scheduling tool (systematized) from a contact form (owner-dependent).

## Content & Marketing Operations
Assess the content engine on RECENCY, not existence. A blog whose last post is two years old is a \
worse signal than no blog at all — it means someone started a program and it died, which usually \
means it died with the person who ran it. State plainly whether content is active, stale, or abandoned.

## Systems & Back Office
What software does the business actually run on? Vertical operating software (field service \
management, restaurant POS, practice management, salon booking) is strong evidence of \
systematization — those tools force process. A business with no operating software beyond a website \
is likely running on spreadsheets, paper, and memory.

## Owner Dependency Indicators
Flag anything suggesting the business IS one person: no team page, single contact route, owner's name \
in the company name, no hiring infrastructure, personal rather than institutional branding. Also flag \
counter-evidence: named management, ATS, multiple locations.

## Post-Close Operating Levers
3-5 specific, concrete gaps an acquirer could close in the first 12-24 months, ordered by \
effort-to-impact. Be specific and cheap: "no email capture on a site with proven foot traffic — a \
Klaviyo list plus a win-back flow is a two-week project" beats "improve digital marketing." Where the \
business is already strong, say there is no lever there rather than inventing one.

Rules:
- Ground every claim in the detected signals above. Do not speculate about tools that were not detected.
- Absence of evidence IS evidence here — a probe that found no pricing page is a real finding, not a \
data gap. But distinguish "we checked and it isn't there" from "we couldn't check."
- If the site blocked probing or almost nothing was detected, say so plainly and rate confidence LOW \
rather than inferring a low-maturity business from a failed crawl. A modern SPA can hide funnel \
machinery behind JavaScript that this probe cannot see — call that out as a limitation where the \
detected stack suggests it.
- Be direct. This is a screening memo, not a marketing audit. No hedging, no soft-skill filler.

CITATION FORMAT (like Perplexity — clickable numbered links):
- Assign each probed page URL a number (1, 2, 3...).
- When a finding comes from a specific page, add a clickable superscript: `[¹](url)`.
- Use Unicode superscripts: ¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹
- Reuse the same number when citing the same page again.

## Sources
At the end, list all numbered sources with FULL 'https://' URLs:
1. [Page Title](url)
2. [Page Title](url)
"""
