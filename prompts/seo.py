"""Prompt template for SEO & AEO audit reports."""


def build_seo_prompt(url, page_count, seo_summary, aeo_summary, page_details):
    return f"""You are an SEO and AEO (Answer Engine Optimization) analyst writing a comprehensive audit report for {url}.

DATA:
- Pages crawled: {page_count}
{seo_summary}

AEO SIGNALS:
{aeo_summary}

PER-PAGE DETAILS:
{page_details}

Write a strategic SEO & AEO audit report. Be specific — reference actual page URLs, exact titles, and concrete issues. No generic advice. Every recommendation should reference something you found in the data.

## Executive Summary
2-3 sentences. Overall SEO health and AEO readiness. What's the biggest opportunity?

## Keyword Analysis
Based on title tags, headings, meta descriptions, and content themes across all crawled pages:
- What keywords is this site clearly targeting?
- What keyword gaps exist (themes in content but missing from titles/meta)?
- Which pages are the most keyword-optimized vs. least?

## SEO Scorecard
For each major SEO factor (titles, meta descriptions, headings, alt text, schema, internal linking), rate the site and call out specific pages with issues.

## AEO Readiness
How well is this site prepared for AI answer engines (ChatGPT, Perplexity, Google AI Overview)?
- Structured data coverage and types
- FAQ and Q&A content presence
- Featured snippet candidates (lists, tables, direct answers)
- Content format suitability for AI extraction

## Most Optimized Pages
Which 2-3 pages are best optimized and why?

## Biggest Opportunities
Top 5 specific, actionable recommendations ranked by impact. Each should reference a specific page or pattern found in the data.

Keep it under 1000 words. Dense with specifics, no filler."""
