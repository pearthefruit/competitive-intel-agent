"""Report generation prompt template for Agent 3."""


def build_analyze_prompt(company_name, total_jobs, stats_summary, classifications_json, news_context=None):
    prompt = f"""You are a competitive intelligence analyst writing a strategic brief about {company_name}'s hiring activity.

DATA:
- Total open roles: {total_jobs}
{stats_summary}

RAW CLASSIFICATION DATA:
{classifications_json}"""

    if news_context:
        prompt += f"""

RECENT NEWS & MARKET CONTEXT:
{news_context}"""

    prompt += f"""

Write a strategic intelligence report with these sections. Write in direct, analytical prose — like a human analyst at a consulting firm. No bullet point soup. No "in conclusion" or "it appears that" hedging. State observations directly.

## Executive Summary
2-3 sentences. What is {company_name} doing and why should a competitor care?

## Hiring Velocity & Focus
Where is the hiring concentrated? What does the department mix tell us about priorities?

## Technical Stack & Skills
What technologies and tools are they investing in? What does the skills concentration reveal about their technical direction?

## Geographic Signals
Where are they hiring? What does the location spread suggest about expansion or operational strategy?"""

    if news_context:
        prompt += f"""

## Market Context & News
Connect recent news (product launches, funding, earnings, acquisitions) to the hiring patterns. What do the news signals confirm or contradict about the hiring data?"""

    prompt += f"""

## Strategic Interpretation
Connect the dots. What is {company_name} building toward? What competitive moves might this hiring pattern signal? What would you watch for next?

Keep it under {1000 if news_context else 800} words total. Dense with insight, light on filler."""

    return prompt
