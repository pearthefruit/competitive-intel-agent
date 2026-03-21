"""Prompt templates for employee sentiment analysis reports."""


def build_sentiment_prompt(company, search_results):
    """Build prompt for LLM-generated employee sentiment analysis."""
    return f"""You are an HR intelligence analyst specializing in employer brand and workplace culture. Based on the following search results about "{company}", analyze employee sentiment and workplace culture.

SEARCH RESULTS:
{search_results}

Write a concise employee sentiment report (500-700 words) with these sections:

## Overall Sentiment
General employee sentiment — positive, mixed, or negative? What's the overall reputation as an employer?

## Strengths
What do employees consistently praise? (culture, compensation, growth opportunities, leadership, work-life balance, etc.)

## Concerns
What are common complaints or criticisms? (management, burnout, compensation, career growth, layoffs, etc.)

## Culture & Leadership
What is the company culture like? How is leadership perceived? Any notable cultural shifts?

## Hiring Signal Implications
What does employee sentiment suggest about the company's ability to attract and retain talent?
How might sentiment affect their competitive position in the talent market?

Rules:
- Base analysis on what the search results actually say. Do not fabricate ratings or statistics.
- Note the source of information when possible (Glassdoor, LinkedIn, news articles, etc.).
- If information is limited, say so — do not speculate extensively.
- Be balanced — note both positives and negatives.
- Be direct and analytical — this is competitive intelligence, not a career advice column.

## Sources
At the end of the report, include a **Sources** section listing the URLs from the search results that informed your analysis. Format as markdown links: `[Title](url)`.
"""
