"""Prompt template for the consulting target intelligence briefing.

Lens-parameterized: the scoring rubric, dimensions, tier labels, and engagement
opportunity framing are all driven by the lens config passed to build_briefing_prompt().
"""

import json


# ---------- Static schema sections (lens-agnostic) ----------

_STATIC_SCHEMA_SECTIONS = {
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
            "detail": "string (2-3 sentences — deeper explanation of why this is needed)",
            "estimated_scope": "string (e.g. '$1-3M, 6-12 months')",
            "why_now": "string (1-2 sentences — company-specific timing trigger)",
            "source_analyses": ["string — which analyses support this opportunity"],
        }
    ],
    "data_confidence": {
        "jobs_analyzed": "integer",
        "scrape_coverage": "string",
        "analyses_available": ["string"],
        "analyses_missing": ["string"],
        "overall_confidence": "high | medium | low",
        "caveats": ["string"],
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


def _build_briefing_schema(lens_config, use_algo=False):
    """Build the full briefing JSON schema dynamically from lens config."""
    dimensions = lens_config.get("dimensions", [])
    labels = lens_config.get("labels", [])
    label_options = " | ".join(l["label"] for l in labels)

    # Build dynamic sub_scores from lens dimensions
    sub_scores = {}
    for dim in dimensions:
        entry = {
            "score": "integer 0-100 — your score based on all evidence",
            "rationale": "string with [source] tags — explain what evidence supports the score",
            "signals": ["string with [source] tag"],
            "source_analyses": ["string — which analyses informed this score"],
        }
        if use_algo:
            entry["algorithmic_score"] = "integer 0-100 (auto-populated — do not set)"
            entry["algorithmic_confidence"] = "float 0-1 (auto-populated — do not set)"
            entry["signals_used"] = ["string (auto-populated — do not set)"]
        sub_scores[dim["key"]] = entry

    scoring_section = {
        "overall_score": "integer 0-100 (auto-recomputed from sub-scores — your value will be overwritten)",
        "overall_label": label_options,
        "sub_scores": sub_scores,
    }
    if use_algo:
        scoring_section["algorithmic_weighted_score"] = "integer 0-100 (auto-populated — do not set)"
        scoring_section["overall_algorithmic_confidence"] = "float 0-1 (auto-populated — do not set)"

    schema = {"subject_identity": _STATIC_SCHEMA_SECTIONS["subject_identity"]}
    schema["scoring"] = scoring_section
    for key in ("hiring_trajectory", "engagement_opportunities", "data_confidence",
                "budget_signals", "competitive_pressure", "financial_position",
                "innovation_ip", "talent_culture", "risk_profile", "strategic_assessment"):
        schema[key] = _STATIC_SCHEMA_SECTIONS[key]

    return schema


# ---------- Scoring rubric builder ----------

def _build_scoring_rubric(lens_config):
    """Build the scoring rubric section dynamically from lens dimensions."""
    dimensions = lens_config.get("dimensions", [])
    labels = lens_config.get("labels", [])
    score_label = lens_config.get("score_label", "Score")

    lines = [
        "",
        "---",
        "",
        f"SCORING RUBRIC ({score_label}):",
        "",
        "IMPORTANT: This score measures the company's ACTUAL capability in these dimensions — "
        "NOT their attractiveness as a consulting target. Score honestly.",
        "",
        "Score each dimension 0-100 based on ALL available evidence.",
        "",
    ]

    for dim in dimensions:
        weight_pct = int(dim["weight"] * 100)
        sources = ", ".join(s.replace("_", " ").title() for s in dim.get("sources", []))
        lines.append(f"### {dim['label']} (weight: {weight_pct}%)")
        if sources:
            lines.append(f"Primary evidence: {sources}")
        lines.append("")
        rubric = dim.get("rubric", "Score 0-100 based on available evidence.")
        lines.append(rubric)
        lines.append("")

    # Weight formula
    weight_parts = []
    for d in dimensions:
        weight_parts.append(f"{d['label']}×{d['weight']:.2f}")
    weight_formula = " + ".join(weight_parts)
    lines.append(f"**Overall score = weighted average ({weight_formula}).**")
    lines.append("NOTE: The overall_score will be RECOMPUTED programmatically from your sub-scores — "
                 "focus on getting each sub-score right rather than the overall arithmetic.")
    lines.append("")

    # Tier labels
    lines.append("Labels (direct, no sugarcoating):")
    for label in labels:
        lines.append(f'- {label["min_score"]}+: "{label["label"]}"')
    lines.append("")

    return "\n".join(lines)


def _build_scoring_rules_block(use_algo):
    """Build scoring rules instructions for the LLM."""
    lines = [
        "",
        "---",
        "",
        "SCORING INSTRUCTIONS:",
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
        "does NOT mean the company lacks engineering capability — focus on sector identity, patents, strategic tags, "
        "report content, and the company's known products/capabilities.",
        "- Consider the company's CORE BUSINESS and PRODUCTS when scoring, not just scraped data.",
        "- Do NOT restate the score number in the rationale (e.g. 'The score of 53...'). Scores are displayed separately in the UI.",
        "",
    ]
    return "\n".join(lines)


# ---------- Engagement opportunity builder ----------

def _build_engagement_guidance(lens_config):
    """Build engagement opportunity mapping guidance from lens config."""
    scoring_context = lens_config.get("scoring_context", "")
    angle_guidance = lens_config.get("angle_guidance", "")
    risk_focus = lens_config.get("risk_focus", "")
    service_list = lens_config.get("engagement_service_list", [])

    lines = [
        "",
        "---",
        "",
        "ENGAGEMENT OPPORTUNITY MAPPING:",
        "",
        "CRITICAL RULE — DO NOT SUGGEST SERVICES THAT ARE THE COMPANY'S CORE COMPETENCY OR ADJACENT EXPERTISE.",
        "Apply this principle broadly: never sell a company what they already do better than anyone, "
        "AND never sell them what's adjacent to their core expertise. Think about what they would laugh at if a consultant pitched it.",
        "",
        "INSTEAD, focus on their ACTUAL pain points from the data:",
        "- Hypergrowth scaling problems",
        "- Non-core operational gaps",
        "- M&A integration, international expansion, regulatory compliance",
        "- The messy human/org problems that tech excellence doesn't solve",
        "",
    ]

    if angle_guidance:
        lines.append(f"LENS-SPECIFIC GUIDANCE: {angle_guidance}")
        lines.append("")

    if risk_focus:
        lines.append(f"RISK AREAS TO WATCH: {risk_focus}")
        lines.append("")

    lines.extend([
        "PRIORITY LEVELS — these reflect how much the company NEEDS external help:",
        "- HIGH = Clear evidence of a gap or pain point OUTSIDE the company's expertise.",
        "- MEDIUM = Some evidence of need, company has partial capability.",
        "- LOW = Minor gap or the company has significant internal capability.",
        "",
        "If a company scores 80+ in a scoring dimension, do NOT suggest HIGH priority consulting for that area.",
        "",
        "Generate 3-5 prioritized consulting engagement opportunities.",
    ])

    if service_list:
        lines.append("Use real consulting service names such as:")
        for svc in service_list:
            lines.append(f"- {svc}")
    else:
        lines.extend([
            "Use real consulting service names relevant to the scoring lens context.",
            f"Lens context: {scoring_context}",
        ])

    lines.extend([
        "",
        "For each opportunity, provide:",
        "- Specific evidence from the intelligence data WITH [source] tags",
        "- A 'detail' field: 2-3 sentences expanding on WHY this is a real need",
        "- Estimated scope (see methodology below)",
        "- A 'why_now' field: 1-2 sentences explaining the company-specific timing trigger",
        "- source_analyses: list of which analysis types support this opportunity",
        "",
        "SCOPE ESTIMATION METHODOLOGY (Big 4 / MBB blended rate ~$3-5K/consultant/day):",
        "- $500K-1M, 3-6 months: Small team (2-3 consultants). Assessments, strategy, POC.",
        "- $1-3M, 6-12 months: Medium team (4-6 consultants). Platform implementation, org redesign.",
        "- $2-5M, 9-18 months: Large team (6-10 consultants). Multi-workstream programs.",
        "- $5M+, 12-24 months: Full transformation (10+ consultants). Only for $50B+ companies.",
        "CRITICAL: Scale to company size. A $2B company does NOT get a $5M engagement.",
        "",
    ])

    return "\n".join(lines)


# ---------- Anomaly signals (lens-agnostic) ----------

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
        "These anomalies were detected from the hiring data INDEPENDENTLY of the scoring dimensions.",
        "A company can score 95 and still have structural problems that create",
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


# ---------- Section-to-source mapping builder ----------

def _build_source_mapping(lens_config, all_key_facts, hiring_stats):
    """Build the section-to-source citation mapping dynamically from lens dimensions."""
    dimensions = lens_config.get("dimensions", [])
    valid_sources = list(all_key_facts.keys()) + (["hiring"] if hiring_stats else [])

    lines = [
        f"Valid source tags: {valid_sources}",
        "",
        "Format: \"Company has 142 open roles [hiring]. Revenue reached $20B [financial].\"",
        "",
        "If you cannot cite a source for a claim, DO NOT make the claim.",
        "",
        "SECTION-TO-SOURCE MAPPING — only cite sources that ACTUALLY provide evidence for a section:",
        "",
        "| Section | Primary sources |",
        "|---------|----------------|",
    ]

    # Dynamic: scoring dimensions mapped to their sources
    for dim in dimensions:
        sources = ", ".join(dim.get("sources", []))
        lines.append(f"| {dim['key']} | {sources} |")

    # Static sections (lens-agnostic)
    lines.extend([
        "| hiring_trajectory | hiring |",
        "| engagement_opportunities | Depends on service — cite the relevant source |",
        "| budget_signals | financial, hiring |",
        "| competitive_pressure | competitors |",
        "| financial_position | financial |",
        "| innovation_ip | patents, hiring |",
        "| talent_culture | hiring, sentiment |",
        "| risk_profile | Any relevant source |",
        "",
        "IMPORTANT: [sentiment] = employee sentiment data (Glassdoor/Reddit reviews). "
        "Only cite it for dimensions that list sentiment as a source, and for talent_culture. "
        "NEVER cite [sentiment] for tech/data/AI dimensions unless the lens rubric specifies it.",
        "",
        "The source_analyses array for each section MUST match the inline [source] tags used.",
        "",
    ])

    return "\n".join(lines)


# ---------- Main prompt builder ----------

def build_briefing_prompt(company_name, all_key_facts, report_summaries,
                          hiring_stats=None, hiring_snapshots=None,
                          data_confidence=None, algo_scores=None,
                          anomaly_signals=None, lens_config=None,
                          computed_metrics_text=None):
    """Build the intelligence briefing prompt.

    Args:
        company_name: Target company name
        all_key_facts: dict of {analysis_type: {fact_key: value}}
        report_summaries: dict of {analysis_type: truncated_report_text}
        hiring_stats: dict with dept_counts, seniority_counts, etc. or None
        hiring_snapshots: list of historical snapshot dicts (most recent first) or None
        data_confidence: dict with jobs_analyzed, etc. or None
        algo_scores: dict from compute_dms_scores() or None
        anomaly_signals: list of anomaly dicts from compute_anomaly_signals() or None
        lens_config: dict with dimensions, labels, score_label, scoring_context, etc.
        computed_metrics_text: pre-computed metrics block to inject (from format_metrics_for_prompt)
    """
    # ---- Format intelligence data (unchanged) ----

    # Key facts
    facts_lines = []
    for atype, facts in all_key_facts.items():
        facts_lines.append(f"### {atype.upper()} ANALYSIS KEY FACTS  [source: {atype}]")
        for k, v in facts.items():
            facts_lines.append(f"- {k}: {v}")
        facts_lines.append("")
    formatted_facts = "\n".join(facts_lines) if facts_lines else "No structured key facts available."

    # Report summaries
    summary_lines = []
    for atype, text in report_summaries.items():
        summary_lines.append(f"### {atype.upper()} REPORT (excerpt)  [source: {atype}]")
        summary_lines.append(text)
        summary_lines.append("\n---\n")
    formatted_summaries = "\n".join(summary_lines) if summary_lines else "No report summaries available."

    # Hiring stats
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

    # Hiring snapshots
    if hiring_snapshots and len(hiring_snapshots) > 1:
        snap_lines = ["HIRING TREND DATA (historical snapshots):"]
        for i, snap in enumerate(reversed(hiring_snapshots)):
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

        oldest = hiring_snapshots[-1]
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

    # Data confidence
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

    # ---- Build dynamic sections from lens config ----

    use_algo = algo_scores is not None
    score_label = lens_config.get("score_label", "Score") if lens_config else "Digital Maturity Score"
    scoring_context = lens_config.get("scoring_context", "") if lens_config else ""

    schema = _build_briefing_schema(lens_config, use_algo=use_algo) if lens_config else {}
    schema_str = json.dumps(schema, indent=2)

    scoring_rules = _build_scoring_rules_block(use_algo)
    scoring_rubric = _build_scoring_rubric(lens_config) if lens_config else ""
    engagement_guidance = _build_engagement_guidance(lens_config) if lens_config else ""
    anomaly_block = _format_anomaly_signals_block(anomaly_signals)
    source_mapping = _build_source_mapping(lens_config, all_key_facts, hiring_stats) if lens_config else ""

    # System prompt intro — lens-aware
    if scoring_context:
        system_intro = scoring_context
    else:
        system_intro = (
            "You are a senior management consultant at a top-tier firm (McKinsey, Deloitte, EY Studio+). "
            "You are preparing a target qualification intelligence briefing."
        )

    return f"""{system_intro}

You are preparing a **target qualification intelligence briefing** on **{company_name}**.

Your audience is a consulting partner who needs to quickly assess:
1. Can this company afford consulting? (Budget signals)
2. What is their actual capability? (Honest {score_label.lower()} assessment)
3. What specific services can we sell? (Engagement opportunities — independent of maturity score)
4. Is there urgency? (Competitive pressure + recent changes)
5. How is their hiring strategy shifting? (Hiring trajectory)
6. What are the risks of engaging? (Due diligence)

AVAILABLE INTELLIGENCE:

{formatted_facts}

{formatted_summaries}

{computed_metrics_text or ''}

HIRING DATA:  [source: hiring]
{formatted_hiring}

{formatted_snapshots}

DATA CONFIDENCE:
{formatted_confidence}

---

CRITICAL CITATION REQUIREMENT:

{source_mapping}{scoring_rules}{scoring_rubric}{anomaly_block}{engagement_guidance}---

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
- How many jobs were analyzed (>100 = high confidence, 30-100 = medium, <30 = low)
- Whether the scrape covered the full ATS board or was a limited sample
- How many analysis types have been completed
- Any significant data gaps that affect specific scores

---

Return ONLY valid JSON matching this exact schema. No commentary outside the JSON.

{schema_str}

IMPORTANT:
- Base everything on actual data provided above. Do not fabricate numbers or claims.
- EVERY factual claim must have a [source] tag. Unsourced claims destroy credibility.
- If a dimension has no data, score it 50 and note "insufficient data" in the rationale.
- The strategic_assessment should be the most opinionated section — give a clear recommendation.
- For engagement_opportunities, identify REAL needs from the evidence. Never sell a company what they already do.
- For risk_profile, include both business risks AND engagement risks for the consulting firm.
- COMPUTE the overall_score as the exact weighted average.

MISSING DATA HANDLING:
- If patent analysis was NOT run, set innovation_ip.patent_count to -1. Do NOT report 0 patents without evidence.
- If financial analysis was NOT run, say "Financial data not analyzed" — do not fabricate.
- If any analysis is missing, note it explicitly rather than defaulting to zero."""
