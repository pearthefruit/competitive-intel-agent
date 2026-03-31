"""Prompts for the Lens scoring system — dynamic evaluation frameworks.

Two prompt builders:
  1. build_lens_scoring_prompt() — score a company through a lens config
  2. build_lens_generation_prompt() — LLM-generate a new lens config from a description
"""

import json


def build_lens_scoring_prompt(company_name, lens_config, reports, website_url=None):
    """Build a dynamic scoring prompt from a lens config and analysis reports.

    Args:
        company_name: Company being scored
        lens_config: dict with keys: dimensions, labels, score_label, scoring_context,
                     angle_guidance, risk_focus
        reports: dict of {analysis_type: truncated_report_text}
        website_url: Optional company website URL

    Returns:
        Prompt string expecting JSON output.
    """
    dimensions = lens_config.get("dimensions", [])
    labels = lens_config.get("labels", [])
    scoring_context = lens_config.get("scoring_context", "You are an analyst evaluating a company.")
    angle_guidance = lens_config.get("angle_guidance", "")
    risk_focus = lens_config.get("risk_focus", "")

    website_note = f"\n**Website:** {website_url}" if website_url else ""

    # Build report sections
    report_sections = []
    for atype, text in reports.items():
        label = atype.replace("_", " ").title()
        report_sections.append(f"## {label} Analysis\n\n{text}")

    if not report_sections:
        reports_text = "No analysis reports available — score all dimensions 50 (neutral) and note 'no data'."
    else:
        reports_text = "\n\n---\n\n".join(report_sections)

    # Build dimension sections
    dim_sections = []
    for i, dim in enumerate(dimensions, 1):
        weight_pct = int(dim["weight"] * 100)
        sources = ", ".join(s.replace("_", " ").title() for s in dim.get("sources", []))
        rubric = dim.get("rubric", "Score 0-100 based on available evidence.")
        dim_sections.append(
            f"### Dimension {i}: {dim['label']} (Weight: {weight_pct}%)\n"
            f"**Evidence source:** {sources}\n\n"
            f"| Score | Meaning |\n|-------|---------|"
        )
        for line in rubric.strip().split("\n"):
            line = line.strip()
            if line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    dim_sections.append(f"| {parts[0].strip()} | {parts[1].strip()} |")
                else:
                    dim_sections.append(f"| — | {line} |")

    dim_text = "\n\n".join(dim_sections)

    # Build output schema dynamically
    sub_scores_schema = {}
    for dim in dimensions:
        sub_scores_schema[dim["key"]] = {
            "score": "0-100",
            "rationale": "2-3 sentences citing specific evidence from the reports",
            "signals": [{"text": "short signal description", "url": "source URL or null"}],
        }

    output_schema = {
        "overall_score": "0-100 integer (compute as weighted sum)",
        "overall_label": " | ".join(l["label"] for l in labels),
        "sub_scores": sub_scores_schema,
        "recommended_angle": "1-2 sentence approach grounded in the specific evidence above",
        "key_risks": ["list of 2-3 specific risks based on the evidence"],
        "company_snapshot": {
            "website": "string or null",
            "estimated_revenue": "string or null",
            "estimated_employees": "string or null",
        },
        "engagement_opportunities": [
            {
                "service": "consulting service name",
                "priority": "high | medium | low",
                "evidence": "string with [source] tags — specific data points",
                "detail": "2-3 sentences — why this is a real need",
                "estimated_scope": "e.g. '$1-3M, 6-12 months'",
                "why_now": "1-2 sentences — company-specific timing trigger explaining urgency",
                "source_analyses": ["analysis_type1", "analysis_type2"],
            }
        ],
        "risk_profile": [
            {"category": "string", "description": "string with [source] tags", "severity": "high | medium | low"}
        ],
        "strategic_assessment": "2-3 paragraphs with [source] tags — executive summary through this lens",
    }
    schema_json = json.dumps(output_schema, indent=2)

    # Build weight formula
    weight_formula = " + ".join(
        f"({dim['key']} x {dim['weight']})" for dim in dimensions
    )

    # Build label mapping
    label_text = "\n".join(
        f"- {l['min_score']}-{labels[i-1]['min_score']-1 if i > 0 else 100}: {l['label']}"
        if i > 0 else f"- {l['min_score']}-100: {l['label']}"
        for i, l in enumerate(labels)
    )

    angle_note = f"\n**Angle guidance:** {angle_guidance}" if angle_guidance else ""
    risk_note = f"\n**Risk focus areas:** {risk_focus}" if risk_focus else ""

    return f"""{scoring_context}

## Company Being Scored

**Company:** {company_name}{website_note}
**Analysis reports available:** {len(report_sections)}/{len(set(s for d in dimensions for s in d.get('sources', [])))}

## Research Reports

The following are excerpts from detailed research analyses run on this company. These are your PRIMARY evidence source — cite specific data points from these reports in your rationale.

{reports_text}

## Scoring Task

Score each dimension below from 0 to 100. Be precise — use the full range.

{dim_text}

## Label Mapping

{label_text}

## Output Format

Return a JSON object matching this exact schema:

```json
{schema_json}
```

## Critical Rules

1. **Compute `overall_score` yourself:** {weight_formula}. I will verify your arithmetic.
2. **Every `rationale`, `evidence`, and `description` field MUST include [source] tags** citing which analysis reports the evidence comes from. Format: "...React/Next.js stack [techstack] with $2B revenue [financial]." Valid source tags: {', '.join(reports.keys())}. No generic statements — cite specific data.
3. If a report is missing for a dimension, score it **50** (neutral) and write "Analysis not available" in the rationale.
4. `recommended_angle` must reference the company's actual situation — not generic boilerplate.{angle_note}{risk_note}
5. **Signal sources:** Each signal object must have a `text` (short description) and `url` (source URL or null). Extract URLs from citation links in the reports.

## Engagement Opportunities (3-5 items)

Identify consulting services this company likely needs, evaluated through this scoring lens.
- Focus on gaps OUTSIDE the company's core competency — never sell them what they already do well.
- If a dimension scores 80+, do NOT suggest HIGH priority consulting for that area.
- Each `evidence` field must cite specific data with [source] tags.
- `source_analyses`: list which analysis types support this opportunity.
- Scope estimation (Big 4 blended rate ~$3-5K/consultant/day):
  $500K-1M (3-6mo, small team) | $1-3M (6-12mo, medium) | $2-5M (9-18mo, large) | $5M+ (12-24mo, only $50B+ companies).
  CRITICAL: Scale to company size.

## Risk Profile (3-5 items)

Identify risks for a consulting firm engaging this company through this lens. Include both business risks and engagement risks. Each `description` must include [source] tags. Severity: high/medium/low.

## Strategic Assessment

2-3 paragraphs: executive summary of the overall opportunity through this specific lens. Be opinionated — give a clear recommendation. Reference specific evidence with [source] tags.

Return ONLY the JSON object. No explanation, no markdown fences."""


# ---- Lens Generation Prompt ----

_AVAILABLE_ANALYSES = [
    "techstack", "financial", "brand_ad", "sentiment",
    "competitors", "hiring", "patents", "seo", "pricing",
]

_LENS_CONFIG_SCHEMA = {
    "dimensions": [
        {
            "key": "snake_case_key",
            "label": "Human Readable Label",
            "weight": 0.25,
            "sources": ["analysis_type_1", "analysis_type_2"],
            "rubric": "80-100: ...\n60-79: ...\n40-59: ...\n20-39: ...\n0-19: ...",
        }
    ],
    "labels": [
        {"min_score": 80, "label": "[Domain] Vanguard"},
        {"min_score": 60, "label": "[Domain] Contender"},
        {"min_score": 40, "label": "[Domain] Explorer"},
        {"min_score": 20, "label": "[Domain] Laggard"},
        {"min_score": 0, "label": "[Domain] Dark Spot"},
    ],
    "score_label": "Short Score Name (e.g. 'Workforce Maturity Score')",
    "scoring_context": "You are a ... consultant evaluating ...",
    "angle_guidance": "Focus on ...",
    "risk_focus": "key risk areas to watch for",
}


def build_lens_generation_prompt(name, description):
    """Build a prompt that generates a full lens config from a name and description.

    Args:
        name: Lens name (e.g. "Strategy Consulting")
        description: Natural language description of what this lens evaluates

    Returns:
        Prompt string expecting JSON output.
    """
    schema_json = json.dumps(_LENS_CONFIG_SCHEMA, indent=2)
    analyses_list = ", ".join(_AVAILABLE_ANALYSES)

    return f"""You are an expert at designing evaluation frameworks for business intelligence.

## Task

Create a scoring lens called **"{name}"** based on this description:

> {description}

## What a Lens Is

A lens is a configurable evaluation framework that scores companies across weighted dimensions. Each dimension draws evidence from specific analysis reports that have already been run on the company.

## Available Analysis Types (data sources)

These are the analysis types the system can run. Each dimension's `sources` must reference one or more of these:

{analyses_list}

Brief descriptions:
- **techstack**: Website technology stack — frameworks, analytics, ad pixels, CDN, CMS
- **financial**: Revenue, funding, growth, headcount, profitability (SEC EDGAR + web search)
- **brand_ad**: Brand presence, ad campaigns, social media activity, marketing hires
- **sentiment**: Employee sentiment — Glassdoor, Reddit, Blind, news coverage, culture signals
- **competitors**: Competitive landscape — market position, moat, key rivals
- **hiring**: Job postings analysis — departments, seniority, strategic tags, growth signals
- **patents**: Patent portfolio — innovation areas, R&D intensity, AI/ML patents
- **seo**: Website SEO audit — search visibility, content strategy
- **pricing**: Product pricing strategy — tiers, models, competitive positioning

## Requirements

1. Create 4-6 dimensions that best evaluate the lens description
2. Weights must sum to exactly 1.0
3. Each dimension needs a rubric with 5 score bands (80-100, 60-79, 40-59, 20-39, 0-19)
4. Each dimension must reference 1-3 analysis types as sources
5. Create 5 tier labels (descending from top to bottom) — these MUST be thematic and branded to the domain, following the pattern "[Domain Keyword] [Evocative Tier]". Examples from existing lenses:
   - Digital Transformation: "Digital Vanguard", "Digital Contender", "Digitally Exposed", "Digital Laggard", "Digital Liability"
   - Workforce Management: "Workforce Leader", "Workforce Builder", "Workforce Challenger", "Workforce Laggard", "Workforce Crisis"
   - CTV Ad Sales: "CTV Vanguard", "CTV Contender", "CTV Explorer", "CTV Laggard", "CTV Dark Spot"
   DO NOT use generic labels like "Strong Candidate", "Possible Fit", "Not a Fit". Make them memorable and domain-specific.
6. The `scoring_context` should set the persona for the scoring LLM
7. Keep rubric descriptions concise but specific enough to score against
8. Prefer fewer, more targeted analysis types over running everything

## Output Format

Return a JSON object matching this schema:

```json
{schema_json}
```

Return ONLY the JSON object. No explanation, no markdown fences."""
