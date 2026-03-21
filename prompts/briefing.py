"""Prompt template for the consulting target intelligence briefing."""

import json


_BRIEFING_SCHEMA = {
    "subject_identity": {
        "name": "string",
        "sector": "string",
        "hq_location": "string",
        "ceo": "string",
        "founded": "integer",
        "headcount": "integer or string",
        "revenue": "string (e.g. '$50B')",
        "market_cap": "string (e.g. '$2.8T') or 'N/A (private)'",
        "website": "string",
    },
    "digital_maturity": {
        "overall_score": "integer 0-100",
        "overall_label": "Digitally Advanced | Digitally Maturing | Digital Laggard | Pre-Digital",
        "sub_scores": {
            "tech_modernity": {"score": "integer 0-100", "rationale": "string", "signals": ["string"]},
            "data_analytics": {"score": "integer 0-100", "rationale": "string", "signals": ["string"]},
            "ai_readiness": {"score": "integer 0-100", "rationale": "string", "signals": ["string"]},
            "organizational_readiness": {"score": "integer 0-100", "rationale": "string", "signals": ["string"]},
        },
    },
    "engagement_opportunities": [
        {
            "service": "string (consulting service name)",
            "priority": "high | medium | low",
            "evidence": "string (specific data points justifying this)",
            "estimated_scope": "string (e.g. '$1-3M, 6-12 months')",
            "entry_point": "string (decision-maker title)",
        }
    ],
    "budget_signals": {
        "can_afford": "boolean",
        "evidence": "string",
        "revenue_trend": "string",
        "hiring_trend": "string",
        "investment_areas": ["string"],
        "confidence": "high | medium | low",
    },
    "competitive_pressure": {
        "urgency": "high | medium | low",
        "competitors": [
            {"name": "string", "digital_maturity_estimate": "string", "threat": "string"}
        ],
        "urgency_drivers": ["string"],
    },
    "financial_position": {
        "summary": "string (2-3 sentences)",
        "metrics": [{"label": "string", "value": "string"}],
    },
    "innovation_ip": {
        "patent_count": "integer",
        "top_areas": ["string"],
        "rd_intensity": "string",
        "assessment": "string (2-3 sentences)",
    },
    "talent_culture": {
        "sentiment": "string (positive/mixed/negative)",
        "hiring_momentum": "string (2-3 sentences)",
        "department_focus": {"department_name": "percentage as integer"},
        "top_skills": ["string (top 5-8 skills)"],
        "assessment": "string (2-3 sentences)",
    },
    "risk_profile": [
        {"category": "string", "description": "string", "severity": "high | medium | low"}
    ],
    "strategic_assessment": "string (2-3 paragraphs — executive summary of the overall opportunity)",
}


def build_briefing_prompt(company_name, all_key_facts, report_summaries, hiring_stats=None):
    """Build the intelligence briefing prompt.

    Args:
        company_name: Target company name
        all_key_facts: dict of {analysis_type: {fact_key: value}} — merged from all analyses
        report_summaries: dict of {analysis_type: truncated_report_text}
        hiring_stats: dict with dept_counts, seniority_counts, strategic_tag_counts, etc. or None
    """
    # Format key facts
    facts_lines = []
    for atype, facts in all_key_facts.items():
        facts_lines.append(f"### {atype.upper()} ANALYSIS KEY FACTS")
        for k, v in facts.items():
            facts_lines.append(f"- {k}: {v}")
        facts_lines.append("")
    formatted_facts = "\n".join(facts_lines) if facts_lines else "No structured key facts available."

    # Format report summaries
    summary_lines = []
    for atype, text in report_summaries.items():
        summary_lines.append(f"### {atype.upper()} REPORT (excerpt)")
        summary_lines.append(text)
        summary_lines.append("\n---\n")
    formatted_summaries = "\n".join(summary_lines) if summary_lines else "No report summaries available."

    # Format hiring stats
    if hiring_stats:
        hiring_lines = []
        hiring_lines.append(f"Total open roles: {hiring_stats.get('total_roles', 'unknown')}")

        dept_counts = hiring_stats.get("dept_counts", {})
        if dept_counts:
            hiring_lines.append("\nDepartment distribution:")
            total = sum(dept_counts.values())
            for dept, count in sorted(dept_counts.items(), key=lambda x: -x[1]):
                pct = round(count * 100 / total) if total else 0
                hiring_lines.append(f"  - {dept}: {count} roles ({pct}%)")

        seniority_counts = hiring_stats.get("seniority_counts", {})
        if seniority_counts:
            hiring_lines.append("\nSeniority distribution:")
            for level, count in sorted(seniority_counts.items(), key=lambda x: -x[1]):
                hiring_lines.append(f"  - {level}: {count}")

        tag_counts = hiring_stats.get("strategic_tag_counts", {})
        if tag_counts:
            hiring_lines.append("\nStrategic hiring tags:")
            for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])[:10]:
                hiring_lines.append(f"  - {tag}: {count} roles")

        hiring_lines.append(f"\nAI/ML roles: {hiring_stats.get('ai_ml_role_count', 0)}")
        hiring_lines.append(f"Growth signal ratio: {hiring_stats.get('growth_signal_ratio', 'unknown')}")

        formatted_hiring = "\n".join(hiring_lines)
    else:
        formatted_hiring = "No hiring data available."

    schema_str = json.dumps(_BRIEFING_SCHEMA, indent=2)

    return f"""You are a senior management consultant at a top-tier firm (McKinsey, Deloitte, EY Studio+). You are preparing a **target qualification intelligence briefing** on **{company_name}** to help a consulting partner assess whether to pursue this company for digital transformation and AI consulting engagements.

Your audience is a consulting partner who needs to quickly assess:
1. Can this company afford consulting? (Budget signals)
2. Do they need digital transformation? (Digital maturity gaps)
3. What specific services can we sell? (Engagement opportunities)
4. Is there urgency? (Competitive pressure + recent changes)
5. What's their org structure like? (Decision maker signals)
6. What are the risks of engaging? (Due diligence)

AVAILABLE INTELLIGENCE:

{formatted_facts}

{formatted_summaries}

HIRING DATA:
{formatted_hiring}

---

DIGITAL MATURITY SCORING RUBRIC:

Score each dimension 0-100 based on ALL available evidence. Use the rubric below.

### Tech Modernity (weight: 30%)
- 80-100: Modern stack (React/Vue/Next.js/Svelte + modern analytics + modern hosting like Vercel/Cloudflare + monitoring + experimentation tools). No legacy dependencies.
- 60-79: Mixed stack. Some modern tools but legacy components present (jQuery alongside React, WordPress as main CMS, old CDN).
- 40-59: Predominantly legacy. Old frameworks, minimal analytics beyond Google Analytics, traditional hosting, no experimentation or monitoring tools.
- 20-39: Very legacy or minimal detectable stack (raw HTML, no framework, no analytics, Wix/Squarespace for a company that should have custom tech).
- 0-19: No tech data available or fully pre-digital.
- If no tech stack data: score 50 and note "insufficient data — tech stack analysis recommended".

### Data & Analytics Maturity (weight: 25%)
- 80-100: Advanced analytics (Segment/Amplitude/Mixpanel/PostHog + A/B testing tools like Optimizely/LaunchDarkly + CDP/data warehouse signals from hiring). Marketing automation in place.
- 60-79: Standard analytics (Google Analytics/GA4) + 1-2 advanced tools (tag management, basic marketing automation).
- 40-59: Basic analytics only (Google Analytics alone). No experimentation, no advanced marketing tools.
- 20-39: No analytics detected or minimal tracking.
- Hiring data bonus: +5-10 if company is actively hiring Data Engineers, Data Scientists, Analytics Engineers, or ML Ops roles.

### AI Readiness (weight: 25%)
- 80-100: Active AI hiring (AI/ML roles > 10% of engineering), AI-related patents, AI tools/platforms detected or referenced in strategic signals. "AI/ML Investment" strategic tag present.
- 60-79: Some AI hiring (5-10% of engineering) or AI patents exist, but no visible AI tooling or unified AI platform.
- 40-59: Minimal AI signals (1-3 AI roles, or "AI" mentioned in strategic signals but not a primary focus).
- 20-39: No AI signals at all — no AI hiring, no AI patents, no AI tools.
- Patent bonus: +5-10 if AI/ML patent areas exist in the IP portfolio.

### Organizational Readiness (weight: 20%)
- 80-100: Growing hiring trend, high engineering ratio (>50% of roles), strong strategic tags (Cloud/Infrastructure, AI/ML Investment, Platform Migration, Automation). Positive employee sentiment.
- 60-79: Stable hiring, moderate engineering ratio (30-50%), some strategic investment tags.
- 40-59: Mixed signals. Flat or slightly declining hiring. Low engineering ratio (<30%). Few strategic tags.
- 20-39: Shrinking hiring, negative sentiment, no strategic investment signals. Indicates organizational resistance to change.

**Overall score = weighted average (Tech×0.30 + Data×0.25 + AI×0.25 + Org×0.20). Round to integer.**

Labels:
- 80-100: "Digitally Advanced" — harder to sell broad transformation, focus on specialized AI/optimization engagements
- 60-79: "Digitally Maturing" — prime target for acceleration and optimization engagements
- 40-59: "Digital Laggard" — major transformation opportunity, biggest potential engagement value
- 20-39: "Pre-Digital" — massive opportunity but verify budget/appetite before investing pursuit effort
- 0-19: "Not Assessed" — insufficient data

ENGAGEMENT OPPORTUNITY MAPPING:

Based on gaps between the company's current state and best-in-class digital maturity, generate 3-5 prioritized consulting engagement opportunities. Use real consulting service names:
- Cloud Migration & Architecture
- AI/ML Strategy & Implementation
- Data & Analytics Modernization
- Digital Customer Experience
- IT Operating Model Transformation
- Cybersecurity & Compliance
- Legacy Application Modernization
- Change Management & Org Design
- Intelligent Automation / RPA
- Supply Chain Digitization

For each opportunity, provide:
- Specific evidence from the intelligence data (not generic observations)
- Estimated scope using consulting conventions: "$500K-1M" (small), "$1-3M" (medium), "$2-5M" (large), "$5M+" (transformation)
- The decision-maker title who would champion this engagement

---

Return ONLY valid JSON matching this exact schema. No commentary outside the JSON.

{schema_str}

IMPORTANT:
- Base everything on actual data provided above. Do not fabricate numbers or claims.
- If a dimension has no data, score it 50 and note "insufficient data" in the rationale.
- The strategic_assessment should be the most opinionated section — give a clear recommendation on whether to pursue this company and why.
- For engagement_opportunities, be specific about what the evidence shows, not generic consulting advice.
- For risk_profile, include both business risks to the target company AND engagement risks for the consulting firm (e.g., "long procurement cycles", "recent leadership change may delay decisions")."""
