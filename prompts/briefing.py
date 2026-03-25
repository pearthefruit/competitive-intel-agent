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
        "overall_score": "integer 0-100 (auto-recomputed from sub-scores — your value will be overwritten)",
        "overall_label": "Digital Vanguard | Digital Contender | Digitally Exposed | Digital Laggard | Digital Liability",
        "algorithmic_weighted_score": "integer 0-100 (auto-populated — do not set)",
        "overall_algorithmic_confidence": "float 0-1 (auto-populated — do not set)",
        "sub_scores": {
            "tech_modernity": {
                "score": "integer 0-100 — your score based on all evidence",
                "rationale": "string with [source] tags — explain what evidence supports the score",
                "signals": ["string with [source] tag"],
                "source_analyses": ["string — which analyses informed this score"],
                "algorithmic_score": "integer 0-100 (auto-populated — do not set)",
                "algorithmic_confidence": "float 0-1 (auto-populated — do not set)",
                "signals_used": ["string (auto-populated — do not set)"],
            },
            "data_analytics": {
                "score": "integer 0-100 — your score based on all evidence",
                "rationale": "string with [source] tags — explain what evidence supports the score",
                "signals": ["string with [source] tag"],
                "source_analyses": ["string"],
                "algorithmic_score": "integer 0-100 (auto-populated — do not set)",
                "algorithmic_confidence": "float 0-1 (auto-populated — do not set)",
                "signals_used": ["string (auto-populated — do not set)"],
            },
            "ai_readiness": {
                "score": "integer 0-100 — your score based on all evidence",
                "rationale": "string with [source] tags — explain what evidence supports the score",
                "signals": ["string with [source] tag"],
                "source_analyses": ["string"],
                "algorithmic_score": "integer 0-100 (auto-populated — do not set)",
                "algorithmic_confidence": "float 0-1 (auto-populated — do not set)",
                "signals_used": ["string (auto-populated — do not set)"],
            },
            "organizational_readiness": {
                "score": "integer 0-100 — your score based on all evidence",
                "rationale": "string with [source] tags — explain what evidence supports the score",
                "signals": ["string with [source] tag"],
                "source_analyses": ["string"],
                "algorithmic_score": "integer 0-100 (auto-populated — do not set)",
                "algorithmic_confidence": "float 0-1 (auto-populated — do not set)",
                "signals_used": ["string (auto-populated — do not set)"],
            },
        },
    },
    "hiring_trajectory": {
        "trend": "accelerating | growing | stable | decelerating | shrinking",
        "velocity": "string (e.g. '+45% in 5 weeks')",
        "interpretation": "string (2-3 sentences analyzing what the hiring shifts reveal about strategy)",
        "department_shifts": [
            {"department": "string", "direction": "up | down | stable", "detail": "string (e.g. '8% → 15%')"}
        ],
    },
    "engagement_opportunities": [
        {
            "service": "string (consulting service name)",
            "priority": "high | medium | low",
            "evidence": "string with [source] tags (specific data points justifying this)",
            "detail": "string (2-3 sentences — deeper explanation of why this is needed, what the engagement looks like, expected outcomes)",
            "estimated_scope": "string (e.g. '$1-3M, 6-12 months')",
            "why_now": "string (1-2 sentences — company-specific timing trigger explaining why THIS company needs this NOW, referencing specific data points like recent funding, hiring velocity, sentiment shifts, competitive moves, or regulatory changes)",
            "source_analyses": ["string — which analyses support this opportunity"],
        }
    ],
    "data_confidence": {
        "jobs_analyzed": "integer",
        "scrape_coverage": "string (e.g. 'full ATS board' or 'LinkedIn sample — 100 of ~500 estimated')",
        "analyses_available": ["string — list of analysis types completed"],
        "analyses_missing": ["string — analysis types NOT yet run"],
        "overall_confidence": "high | medium | low",
        "caveats": ["string — important limitations or data gaps"],
    },
    "budget_signals": {
        "can_afford": "boolean",
        "evidence": "string with [source] tags",
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


def _format_algo_scores_block(algo_scores):
    """Format scoring instructions for the LLM.

    The LLM scores each dimension directly using the rubric and all available
    evidence. Algorithmic signals are NOT shown to the LLM — they are injected
    as metadata after the LLM responds (for the info-icon audit trail).
    """
    lines = [
        "",
        "---",
        "",
        "DIGITAL MATURITY SCORING:",
        "",
        "Score each dimension 0-100 based on ALL available evidence from the reports, key facts, and hiring data above.",
        "Use the scoring rubric below as your guide. Your scores are final — they will be used directly.",
        "",
        "The overall_score will be RECOMPUTED as a weighted average from your sub-scores — do not try to set it yourself.",
        "",
        "SCORING RULES:",
        "- Base your scores on EVIDENCE, not assumptions. Every score must be justified by data from the reports.",
        "- SMALL SAMPLE SIZES: If fewer than 100 roles were analyzed (especially LinkedIn samples), "
        "do NOT treat department percentages as reliable. A 41-role LinkedIn snapshot showing 6% engineering "
        "does NOT mean the company lacks engineering capability — it means the sample is too small to draw structural conclusions. "
        "Focus on sector identity, patents, strategic tags, report content, and the company's known products/capabilities.",
        "- Consider the company's CORE BUSINESS and PRODUCTS when scoring, not just scraped data. Samsung making HBM chips "
        "is strong AI Readiness evidence even if few 'AI Engineer' titles appear in a small LinkedIn sample.",
        "- Do NOT restate the score number in the rationale (e.g. 'The score of 53...'). Scores are displayed separately in the UI.",
        "",
    ]

    return "\n".join(lines)


def _format_anomaly_signals_block(anomaly_signals):
    """Format structural anomaly signals into a prompt section for the LLM."""
    if not anomaly_signals:
        return ""

    lines = [
        "",
        "---",
        "",
        "STRUCTURAL ANOMALY SIGNALS (algorithmically detected — use these to inform engagement opportunities):",
        "",
        "These anomalies were detected from the hiring data INDEPENDENTLY of the Digital Maturity Score.",
        "A company can score 95 on digital maturity and still have structural problems that create",
        "real consulting opportunities. Use these signals when generating engagement_opportunities.",
        "",
    ]

    for a in anomaly_signals:
        severity = a.get("severity", "notable").upper()
        lines.append(f"  [{severity}] {a['signal']}")
        lines.append(f"    → Consulting angle: {a['consulting_angle']}")
        lines.append("")

    lines.append("Use these signals alongside the report evidence when generating engagement_opportunities.")
    lines.append("Anomalies marked [WARNING] should be strongly considered for HIGH priority opportunities.")
    lines.append("")

    return "\n".join(lines)


def build_briefing_prompt(company_name, all_key_facts, report_summaries,
                          hiring_stats=None, hiring_snapshots=None,
                          data_confidence=None, algo_scores=None,
                          anomaly_signals=None):
    """Build the intelligence briefing prompt.

    Args:
        company_name: Target company name
        all_key_facts: dict of {analysis_type: {fact_key: value}} — merged from all analyses
        report_summaries: dict of {analysis_type: truncated_report_text}
        hiring_stats: dict with dept_counts, seniority_counts, etc. or None
        hiring_snapshots: list of historical snapshot dicts (most recent first) or None
        data_confidence: dict with jobs_analyzed, scrape_source, analyses_available, etc. or None
        algo_scores: dict from compute_dms_scores() or None
        anomaly_signals: list of anomaly dicts from compute_anomaly_signals() or None
    """
    # Format key facts with source labels
    facts_lines = []
    for atype, facts in all_key_facts.items():
        facts_lines.append(f"### {atype.upper()} ANALYSIS KEY FACTS  [source: {atype}]")
        for k, v in facts.items():
            facts_lines.append(f"- {k}: {v}")
        facts_lines.append("")
    formatted_facts = "\n".join(facts_lines) if facts_lines else "No structured key facts available."

    # Format report summaries with source labels
    summary_lines = []
    for atype, text in report_summaries.items():
        summary_lines.append(f"### {atype.upper()} REPORT (excerpt)  [source: {atype}]")
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

        subcat_counts = hiring_stats.get("subcategory_counts", {})
        if subcat_counts:
            hiring_lines.append("\nSub-category distribution:")
            for subcat, count in sorted(subcat_counts.items(), key=lambda x: -x[1])[:15]:
                hiring_lines.append(f"  - {subcat}: {count} roles")

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

        top_skills = hiring_stats.get("top_skills", [])
        if top_skills:
            hiring_lines.append(f"\nTop skills: {', '.join(top_skills[:15])}")

        formatted_hiring = "\n".join(hiring_lines)
    else:
        formatted_hiring = "No hiring data available."

    # Format hiring snapshots for temporal analysis
    if hiring_snapshots and len(hiring_snapshots) > 1:
        snap_lines = ["HIRING TREND DATA (historical snapshots):"]
        for i, snap in enumerate(reversed(hiring_snapshots)):  # chronological order
            marker = " ← current" if i == len(hiring_snapshots) - 1 else ""
            dept = snap.get("dept_counts", {})
            total = snap.get("total_roles", 0)
            eng_pct = round(dept.get("Engineering", 0) * 100 / total) if total else 0
            ai_count = snap.get("ai_ml_role_count", 0)
            ai_pct = round(ai_count * 100 / total) if total else 0
            snap_lines.append(
                f"- {snap['snapshot_date']}: {total} roles "
                f"(Eng: {eng_pct}%, AI/ML: {ai_pct}%, "
                f"AI/ML count: {ai_count}){marker}"
            )

        # Compute trend
        oldest = hiring_snapshots[-1]  # list is most-recent-first
        newest = hiring_snapshots[0]
        old_total = oldest.get("total_roles", 0)
        new_total = newest.get("total_roles", 0)
        if old_total and old_total > 0:
            pct_change = round((new_total - old_total) * 100 / old_total)
            snap_lines.append(f"\nOverall trend: {pct_change:+d}% total roles "
                              f"({oldest['snapshot_date']} → {newest['snapshot_date']})")

        formatted_snapshots = "\n".join(snap_lines)
    else:
        formatted_snapshots = "No historical hiring snapshots available (only current data)."

    # Format data confidence
    if data_confidence:
        conf_lines = [
            f"- Jobs analyzed: {data_confidence.get('jobs_analyzed', 'unknown')}",
            f"- Scrape coverage: {data_confidence.get('scrape_coverage', 'unknown')}",
            f"- Analyses completed: {', '.join(data_confidence.get('analyses_available', []))}",
            f"- Analyses NOT run: {', '.join(data_confidence.get('analyses_missing', []))}",
        ]
        formatted_confidence = "\n".join(conf_lines)
    else:
        formatted_confidence = "No confidence metadata available."

    schema_str = json.dumps(_BRIEFING_SCHEMA, indent=2)

    return f"""You are a senior management consultant at a top-tier firm (McKinsey, Deloitte, EY Studio+). You are preparing a **target qualification intelligence briefing** on **{company_name}** to help a consulting partner assess whether to pursue this company for digital transformation and AI consulting engagements.

Your audience is a consulting partner who needs to quickly assess:
1. Can this company afford consulting? (Budget signals)
2. What is their actual digital capability? (Honest digital maturity assessment)
3. What specific services can we sell? (Engagement opportunities — independent of maturity score)
4. Is there urgency? (Competitive pressure + recent changes)
5. How is their hiring strategy shifting? (Hiring trajectory)
6. What are the risks of engaging? (Due diligence)

AVAILABLE INTELLIGENCE:

{formatted_facts}

{formatted_summaries}

HIRING DATA:  [source: hiring]
{formatted_hiring}

{formatted_snapshots}

DATA CONFIDENCE:
{formatted_confidence}

---

CRITICAL CITATION REQUIREMENT:

Every factual claim in rationale, signals, and evidence fields MUST include a source tag in square brackets referencing which analysis produced the data. Valid source tags: {list(all_key_facts.keys()) + (['hiring'] if hiring_stats else [])}

Format: "Company has 142 open roles with 67% in engineering [hiring]. 29 AI-related patents filed [patents]. Revenue reached $20B [financial]."

If you cannot cite a source for a claim, DO NOT make the claim. No unsourced assertions.

SECTION-TO-SOURCE MAPPING — only cite sources that ACTUALLY provide evidence for a section:

| Section | Primary sources | Secondary sources | NEVER cite |
|---------|----------------|-------------------|------------|
| tech_modernity | hiring, techstack | patents | sentiment, financial, seo |
| data_analytics | hiring, techstack | patents | sentiment, financial, seo |
| ai_readiness | hiring, patents | techstack, competitors | sentiment, financial, seo |
| organizational_readiness | hiring, sentiment | financial | patents, techstack, seo |
| hiring_trajectory | hiring ONLY | (none) | sentiment, financial, patents, techstack |
| engagement_opportunities | Depends on service — cite hiring for hiring-related evidence, financial for budget evidence, patents for IP evidence, techstack for tech evidence, sentiment for culture/org evidence | | Do NOT cite sentiment for tech/data/AI opportunities |
| budget_signals | financial, hiring | pricing | sentiment, patents, techstack |
| competitive_pressure | competitors, landscape | hiring | sentiment, financial |
| financial_position | financial | (none) | sentiment, hiring, patents |
| innovation_ip | patents | hiring, techstack | sentiment, financial |
| talent_culture | hiring, sentiment | (none) | patents, financial, techstack |
| risk_profile | Any source relevant to the specific risk | |

IMPORTANT: [sentiment] = employee sentiment data (Glassdoor/Reddit reviews, sentiment scores). It is ONLY relevant for organizational_readiness, talent_culture, and culture-related engagement opportunities (e.g., Change Management). NEVER cite [sentiment] for tech modernity, data/analytics, AI readiness, hiring trajectory, or budget signals — sentiment has NOTHING to do with those dimensions.

Similarly, [hiring] data should NOT be cited for financial_position or innovation_ip unless directly relevant (e.g., "R&D hiring supports patent activity").

The source_analyses array for each section MUST match the inline [source] tags used in that section's text fields.

{_format_algo_scores_block(algo_scores)}---

DIGITAL CAPABILITY SCORING RUBRIC:

IMPORTANT: This score measures the company's ACTUAL digital and technological capability — NOT their attractiveness as a consulting target. Score honestly. A digitally advanced company can still need consulting help (specialized AI work, org design, M&A integration, etc.).

Score each dimension 0-100 based on ALL available evidence.

### Tech Modernity (weight: 30%)
Primary signals: hiring data (what technologies they hire for), sector/product (what they build), engineering ratio.
Secondary signals: website tech stack (what's on their public site — this is a weak signal for internal capability).

CRITICAL DISTINCTION — "uses SaaS tools" vs "is a SaaS company":
A non-tech company (food, retail, manufacturing, etc.) whose public website uses SaaS tools like Algolia, Cloudflare, or Shopify is NOT a SaaS/software company. Using off-the-shelf SaaS products on a marketing website is a PURCHASING decision, not an engineering capability. If anything, heavy reliance on third-party SaaS for a company's public site suggests they LACK internal engineering depth — it is a neutral-to-negative signal for tech modernity, never a positive one. Only score website SaaS usage positively if the company's CORE BUSINESS is technology/software.

- 80-100: Company IS a technology/software/AI company (core product is technology), OR hiring data shows modern stack (React/Go/Rust/K8s/cloud-native/microservices roles dominate), high engineering ratio (>50% of open roles). If a company literally BUILDS software, LLMs, cloud infrastructure, or AI products, floor at 80 — their tech modernity is self-evident regardless of what's on their marketing website.
- 60-79: Tech-adjacent company with significant engineering investment (30-50% engineering roles), modern tools in hiring reqs, some legacy maintenance roles. Mixed website tech stack.
- 40-59: Non-tech company with modest engineering team (<30% roles). Hiring shows legacy technologies (COBOL, mainframe, .NET Framework, on-prem). Website shows dated stack.
- 20-39: Minimal tech hiring. No engineering culture signals. Basic or outsourced IT.
- 0-19: No tech data available or fully pre-digital.
- If no tech stack data AND no hiring data: score 50 and note "insufficient data" in rationale.

### Data & Analytics (weight: 25%)
Primary signals: hiring data (Data Engineers, Data Scientists, ML Ops, Analytics Engineers — these tell you far more than website trackers), data-related strategic tags, company product.
Secondary signals: analytics tools detected on website (Segment, Amplitude, etc. — useful for non-tech companies, but irrelevant for companies whose product IS data/AI).

- 80-100: Company's core product IS data or AI, OR actively hiring multiple data roles (Data Engineers, Data Scientists, Analytics Engineers, ML Ops). "Data Infrastructure" strategic tag present. Evidence of data platform investment.
- 60-79: Some data hiring but not a strategic focus. OR advanced analytics tooling on website (Segment/Amplitude + A/B testing). Marketing automation signals.
- 40-59: No data-specific hiring. Basic website analytics only (GA alone). No experimentation signals.
- 20-39: No data signals at all — no data roles, no analytics tools.

### AI Readiness (weight: 25%)
- 95-100: Company's core product IS AI/ML (e.g., OpenAI, Anthropic, Google DeepMind, Nvidia AI). AI is the business, not a capability being adopted. Score accordingly.
- 80-94: Active AI hiring (AI/ML roles >10% of engineering), AI-related patents, AI tools/platforms, "AI/ML Investment" strategic tag. AI is a major strategic focus but not the core product.
- 60-79: Some AI hiring (5-10% of engineering) or AI patents exist, but no visible unified AI platform strategy.
- 40-59: Minimal AI signals (1-3 AI roles, or "AI" mentioned in strategy but not a focus).
- 20-39: No AI signals — no AI hiring, no AI patents, no AI tools.
- Patent bonus: +5-10 if AI/ML patent areas exist in the IP portfolio.

### Organizational Readiness (weight: 20%)
- 80-100: Growing hiring trend, high engineering ratio (>50%), strong strategic investment tags (Cloud/Infrastructure, AI/ML Investment, Platform Migration, Automation). Positive employee sentiment.
- 60-79: Stable hiring, moderate engineering ratio (30-50%), some strategic investment tags.
- 40-59: Mixed signals. Flat or slightly declining hiring. Low engineering ratio (<30%). Few strategic tags.
- 20-39: Shrinking hiring, negative sentiment, no strategic investment signals.
- NUANCE: Negative sentiment from rapid growth (burnout, equity complaints during hypergrowth) is NOT the same as organizational resistance to change. Distinguish growing pains from structural dysfunction. A company growing from 1000 to 8000 employees will have cultural friction — that's an org design opportunity, not a sign of low readiness.

**Overall score = weighted average (Tech×0.30 + Data×0.25 + AI×0.25 + Org×0.20). NOTE: The overall_score will be RECOMPUTED programmatically from your sub-scores — focus on getting each sub-score right rather than the overall arithmetic.**

Labels (direct, no sugarcoating — these should make a C-suite exec pay attention):
- 80-100: "Digital Vanguard"
- 60-79: "Digital Contender"
- 40-59: "Digitally Exposed"
- 20-39: "Digital Laggard"
- 0-19: "Digital Liability"

{_format_anomaly_signals_block(anomaly_signals)}---

ENGAGEMENT OPPORTUNITY MAPPING:

CRITICAL RULE — DO NOT SUGGEST SERVICES THAT ARE THE COMPANY'S CORE COMPETENCY OR ADJACENT EXPERTISE:
- If the company IS an AI company (OpenAI, Anthropic, Google DeepMind, etc.), do NOT suggest "AI/ML Strategy & Implementation", "Data & Analytics Modernization", OR "AI Governance & Responsible AI" — they are the world experts in ALL of these. Anthropic literally invented Constitutional AI and leads responsible AI research. OpenAI has its own governance frameworks. These companies don't need consulting help with AI anything.
- If the company IS a cloud company (AWS, Azure, GCP), do NOT suggest "Cloud Migration" or "Enterprise Architecture."
- If the company IS a cybersecurity company, do NOT suggest "Cybersecurity & Compliance."
- Apply this principle broadly and AGGRESSIVELY: never sell a company what they already do better than anyone, AND never sell them what's adjacent to their core expertise either. Think about what they would laugh at if a consultant pitched it.

INSTEAD, focus on their ACTUAL pain points from the data:
- Hypergrowth scaling problems (99% new roles = organizational chaos)
- Non-core operational gaps (AI companies still need help with sales ops, supply chain, facilities)
- M&A integration, international expansion, regulatory compliance in NEW jurisdictions
- The messy human/org problems that tech excellence doesn't solve

PRIORITY LEVELS — these reflect how much the company NEEDS external help, not how important the category sounds:
- HIGH = Clear evidence of a gap or pain point in an area OUTSIDE the company's expertise. They can't solve this internally.
- MEDIUM = Some evidence of need, company has partial capability but could benefit from external expertise.
- LOW = Minor gap or the company has significant internal capability. Only worth pursuing if the engagement is large or strategic.

If a company scores 80+ in a digital maturity dimension, do NOT suggest HIGH priority consulting for that dimension. A company that IS an AI leader should NEVER have "AI Governance" rated HIGH.

Engagement opportunities should reflect REAL problems the company faces based on evidence, not textbook consulting services. A company can be digitally advanced AND have genuine consulting needs — those needs just won't be in their core domain.

Generate 3-5 prioritized consulting engagement opportunities. Use real consulting service names:
- Cloud Migration & Architecture
- AI/ML Strategy & Implementation (only for companies ADOPTING AI, not building it)
- Data & Analytics Modernization (only for companies that DON'T have data as their core product)
- Digital Customer Experience
- IT Operating Model Transformation
- Cybersecurity & Compliance
- Legacy Application Modernization
- Change Management & Org Design
- Intelligent Automation / RPA
- Supply Chain Digitization
- AI Governance & Responsible AI (ONLY for companies ADOPTING AI, never for AI-native companies)
- Technology Due Diligence (M&A)
- Engineering Effectiveness & Developer Platform
- Talent Strategy & Organizational Design
- Enterprise Architecture & Technical Debt

For each opportunity, provide:
- Specific evidence from the intelligence data WITH [source] tags (not generic observations)
- A "detail" field: 2-3 sentences expanding on WHY this is a real need, what the engagement would look like, and what outcomes the client should expect. This is the deeper explanation a partner would want when clicking into the opportunity.
- Estimated scope using the METHODOLOGY below (not a guess — show your reasoning via the evidence)
- A "why_now" field: 1-2 sentences explaining the company-specific timing trigger — why THIS company needs this NOW. Reference specific recent events, data points, or inflection points. Examples: "Post-$30B Series G with 99% new roles — the org is scaling faster than its processes can support." or "Revenue grew 29% but sentiment is declining — cultural debt is accumulating during hypergrowth." Make it specific enough that it couldn't apply to a random company.
- source_analyses: list of which analysis types support this opportunity

SCOPE ESTIMATION METHODOLOGY — these must be defensible to a consulting partner:

Estimates are based on typical Big 4 / MBB engagement structures (blended daily rate ~$3-5K/consultant):
- **$500K-1M, 3-6 months**: Small team (2-3 consultants). Assessments, strategy design, POC, governance framework. Example: AI readiness assessment for a company with <$5B revenue.
- **$1-3M, 6-12 months**: Medium team (4-6 consultants). Platform implementation, org redesign, single workstream transformation. Scale to company size — a 5,000-person company's org redesign costs less than a 50,000-person company's.
- **$2-5M, 9-18 months**: Large team (6-10 consultants). Multi-workstream programs, enterprise-wide platform rollout, M&A integration. Appropriate for $10B+ revenue companies with complex operations.
- **$5M+, 12-24 months**: Full transformation team (10+ consultants). Company-wide digital transformation, multi-geography rollout. Only appropriate for $50B+ companies with evidence of large-scale transformation need.

CRITICAL: Scale the estimate to the company's size and complexity. A $2B company does NOT get a $5M engagement. Use revenue, headcount, and hiring velocity as sizing inputs. For financial services firms (asset managers, PE, banks), use AUM as a primary size indicator — a $500B AUM firm has different consulting capacity than a $5B boutique. If in doubt, estimate conservatively — an overstated scope destroys credibility faster than an understated one.

---

HIRING TRAJECTORY:

If historical hiring snapshots are provided, analyze the trajectory:
- Is total headcount growing, stable, or shrinking?
- Which departments are growing vs shrinking as a percentage?
- What strategic shifts does this reveal?
- Generate the hiring_trajectory section with trend, velocity, interpretation, and department_shifts.

If no historical data exists, set hiring_trajectory to null.

---

DATA CONFIDENCE:

Assess the overall confidence of this briefing based on the data available. Consider:
- How many jobs were analyzed (>100 = high confidence, 30-100 = medium, <30 = low for hiring signals)
- Whether the scrape covered the full ATS board or was a limited sample
- How many of the 12 analysis types have been completed
- Any significant data gaps that affect specific scores

---

Return ONLY valid JSON matching this exact schema. No commentary outside the JSON.

{schema_str}

IMPORTANT:
- Base everything on actual data provided above. Do not fabricate numbers or claims.
- EVERY factual claim must have a [source] tag. Unsourced claims destroy credibility.
- If a dimension has no data, score it 50 and note "insufficient data — [analysis type] recommended" in the rationale.
- The strategic_assessment should be the most opinionated section — give a clear recommendation on whether to pursue this company and why.
- For engagement_opportunities, identify REAL needs from the evidence. A company that builds AI doesn't need AI strategy, data modernization, OR AI governance — they are experts in all of those. Focus on their non-core pain points: org design for hypergrowth, sales operations, compliance in new jurisdictions, M&A integration.
- For risk_profile, include both business risks to the target company AND engagement risks for the consulting firm (e.g., "long procurement cycles", "recent leadership change may delay decisions").
- COMPUTE the overall_score as the exact weighted average. Do not round sub-scores to produce a convenient overall number.

MISSING DATA HANDLING — critical for credibility:
- If patent analysis was NOT run (patents not in analyses_available), set innovation_ip.patent_count to -1 and assessment to "Patent analysis not conducted — run patent_analysis to assess IP portfolio." Do NOT report 0 patents for a Fortune 500 company without evidence.
- If financial analysis was NOT run, say "Financial data not analyzed" in financial_position.summary — do not fabricate revenue or market cap.
- If any analysis is missing, note it explicitly rather than inferring or defaulting to zero. A wrong number is worse than admitting incomplete data.
- In the data_confidence section, clearly list which analyses are missing and how that affects specific scores."""
