"""Prompt for Prospect Fit Scoring — scores a company for Universal Ads (premium video) suitability.

Uses actual research analysis reports (financial, techstack, brand_ad) as evidence
rather than raw web search snippets. Fixed 5-dimension rubric — no ICP config needed.
"""

import json


_FIT_SCHEMA = {
    "overall_score": "0-100 integer (compute as weighted sum, do NOT just estimate)",
    "overall_label": "Prime Prospect | Strong Candidate | Possible Fit | Weak Fit | Not a Fit",
    "sub_scores": {
        "financial_capacity": {
            "score": "0-100",
            "rationale": "2-3 sentences citing specific evidence from the financial report",
            "signals": ["list of specific signals: revenue figures, funding rounds, growth rates"],
        },
        "advertising_maturity": {
            "score": "0-100",
            "rationale": "2-3 sentences citing specific ad pixels, marketing tools, or channels detected",
            "signals": ["list of specific ad pixels or marketing tools found"],
        },
        "growth_trajectory": {
            "score": "0-100",
            "rationale": "2-3 sentences citing revenue growth, expansion news, or hiring trends",
            "signals": ["list of specific growth signals: YoY %, expansion announcements, headcount"],
        },
        "creative_readiness": {
            "score": "0-100",
            "rationale": "2-3 sentences citing brand presence, social media activity, or video content",
            "signals": ["list of specific creative signals: social platforms, video content, brand campaigns"],
        },
        "channel_expansion_intent": {
            "score": "0-100",
            "rationale": "2-3 sentences citing signals of intent to explore new ad channels",
            "signals": ["list of specific intent signals: new channel mentions, marketing hires, campaign launches"],
        },
    },
    "recommended_angle": "1-2 sentence sales approach grounded in the specific evidence above",
    "key_risks": ["list of 2-3 specific objections or risks based on the evidence"],
    "company_snapshot": {
        "website": "string or null",
        "estimated_revenue": "string or null — from financial report",
        "estimated_employees": "string or null — from financial report",
        "ecom_platform": "string or null — from techstack report",
        "recent_funding": "string or null — from financial report",
        "primary_ad_channels": ["list of social/digital channels they use — from brand_ad/techstack"],
        "ad_pixels_detected": ["list of ad tracking pixels found on website — from techstack report"],
    },
}


def build_ua_fit_prompt(company_name, reports, website_url=None):
    """Build the prospect fit scoring prompt from analysis reports.

    Args:
        company_name: Name of the company being scored
        reports: dict of {analysis_type: truncated_report_text}
                 Keys: 'techstack', 'financial', 'brand_ad' (any subset)
        website_url: Optional website URL

    Returns:
        Prompt string expecting JSON output.
    """
    website_note = f"\n**Website:** {website_url}" if website_url else ""

    # Build report sections
    report_sections = []
    if "techstack" in reports:
        report_sections.append(f"## Tech Stack & Ad Infrastructure Analysis\n\n{reports['techstack']}")
    if "financial" in reports:
        report_sections.append(f"## Financial Analysis\n\n{reports['financial']}")
    if "brand_ad" in reports:
        report_sections.append(f"## Brand & Ad Intelligence\n\n{reports['brand_ad']}")

    if not report_sections:
        reports_text = "No analysis reports available — score all dimensions 50 (neutral) and note 'no data'."
    else:
        reports_text = "\n\n---\n\n".join(report_sections)

    analyses_available = len(report_sections)
    schema_json = json.dumps(_FIT_SCHEMA, indent=2)

    return f"""You are a GTM intelligence analyst scoring a company's suitability as a prospect for a premium video / streaming TV advertising platform (similar to Comcast Universal Ads).

## Company Being Scored

**Company:** {company_name}{website_note}
**Analysis reports available:** {analyses_available}/3

## Research Reports

The following are excerpts from detailed research analyses run on this company. These are your PRIMARY evidence source — cite specific data points from these reports in your rationale.

{reports_text}

## Scoring Task

Score each of the 5 dimensions below from 0 to 100. Be precise — use the full range. A score of 75 means something different from 80.

### Dimension 1: Financial Capacity (Weight: 25%)
**Question:** Can this company afford TV/streaming ad campaigns ($10K–$100K/month)?
**Evidence source:** Financial report (revenue, funding, growth, profitability).

| Score | Meaning |
|-------|---------|
| 80–100 | Clear evidence of $10M+ revenue or recent Series B+ funding. Has budget headroom for new channels. |
| 60–79 | Revenue/funding suggests moderate capacity. Could allocate $10K–50K/month without strain. |
| 40–59 | Financial signals ambiguous or limited. Early-stage, unclear revenue, or tight margins. |
| 20–39 | Resource-constrained. Minimal funding, small team, or financial difficulty evident. |
| 0–19 | Clearly cannot afford new ad channels. Pre-revenue or in distress. |

### Dimension 2: Paid Media Footprint (Weight: 20%)
**Question:** Do they already run paid digital ads? Companies already buying social/search ads are primed for the next channel.
**Evidence source:** Tech stack report — look specifically for "Advertising Pixels" category. FB Pixel = they advertise. Google Analytics alone does NOT count.

| Score | Meaning |
|-------|---------|
| 80–100 | 2+ ad pixels detected (Facebook, TikTok, Google Ads, etc). Marketing automation present. Heavy digital buyer but NOT yet on TV/CTV. |
| 60–79 | 1 ad pixel detected OR strong social presence indicating paid activity. Some marketing infrastructure. |
| 40–59 | Basic analytics (GA4) only — tracking but not necessarily buying ads. Ambiguous. |
| 20–39 | Almost no ad infrastructure. Likely organic/word-of-mouth only. No pixels detected. |
| 0–19 | No advertising tools detected, OR already a major TV advertiser at scale (wrong direction). |

### Dimension 3: Growth Trajectory (Weight: 20%)
**Question:** Are they on a growth trajectory that demands reaching new audiences?
**Evidence source:** Financial report (revenue growth rate, recent funding) + Brand & Ad Intelligence report (expansion news, marketing hires).

| Score | Meaning |
|-------|---------|
| 80–100 | Strong growth (>20% YoY revenue, or recent funding round), expansion announcements, active hiring. |
| 60–79 | Moderate growth signals. Stable and expanding, not explosive. Positive news coverage. |
| 40–59 | Flat or unclear trajectory. No meaningful growth or decline signals. |
| 20–39 | Concerning signals — layoffs, revenue decline, market contraction, negative press. |
| 0–19 | Company clearly shrinking, in distress, or going through strategic wind-down. |

### Dimension 4: Video Asset Readiness (Weight: 20%)
**Question:** Do they produce video/visual content that could translate into TV spots?
**Evidence source:** Brand & Ad Intelligence report (brand campaigns, social media presence, video content, YouTube activity) + tech stack (social embeds, video players).

| Score | Meaning |
|-------|---------|
| 80–100 | Strong social/video presence (YouTube, TikTok, Reels). Existing brand campaigns. Product visually demonstrable on screen (fashion, food, beauty, fitness, CPG). |
| 60–79 | Good brand presence, photo-heavy or text-heavy. Could transition to video. Clear brand voice. |
| 40–59 | Basic digital presence, limited content output. Possible but would need creative investment. |
| 20–39 | Minimal brand presence. Highly technical B2B product or invisible online. |
| 0–19 | No creative presence, or product fundamentally unsuited for video (raw materials, industrial). |

### Dimension 5: Channel Expansion Intent (Weight: 15%)
**Question:** Are there signals they're actively exploring new marketing channels beyond current spend?
**Evidence source:** Brand & Ad Intelligence report (CTV/streaming mentions, new channel launches, channel diversification signals) + financial (marketing budget trends).

| Score | Meaning |
|-------|---------|
| 80–100 | Explicit mentions of CTV, streaming, or "beyond social" in news/press. Hiring brand/media roles. Recent campaign outside usual channels. |
| 60–79 | Implicit intent — entering new markets, increasing budgets, industry peers are diversifying. |
| 40–59 | No specific intent signals. Profile suggests receptivity but no evidence. |
| 20–39 | Content with existing channels. No diversification signals. |
| 0–19 | Actively cutting marketing spend or explicitly focused away from broadcast channels. |

## Output Format

Return a JSON object matching this exact schema:

```json
{schema_json}
```

## Critical Rules

1. **Compute `overall_score` yourself:** (financial_capacity × 0.25) + (advertising_maturity × 0.20) + (growth_trajectory × 0.20) + (creative_readiness × 0.20) + (channel_expansion_intent × 0.15). I will verify your arithmetic.
2. **Every `rationale` MUST cite specific evidence** from the reports above — company names, dollar amounts, pixel names, news headlines. No generic statements.
3. If a report is missing for a dimension, score it **50** (neutral) and write "Analysis not available" in the rationale.
4. `ad_pixels_detected` in `company_snapshot` must list the specific pixels found in the tech stack report's "Advertising Pixels" section. If none found, use empty array.
5. `recommended_angle` must reference the company's actual situation — not generic boilerplate.

Return ONLY the JSON object. No explanation, no markdown fences."""


# ---- Vertical Insight Prompt ----

_VERTICAL_INSIGHT_SCHEMA = {
    "vertical_summary": "2-3 sentence overview of the niche as an advertising opportunity",
    "insight_paragraphs": [
        "Each paragraph is 2-4 sentences. 3-5 paragraphs covering: market dynamics, common ad maturity patterns, financial capacity range, creative readiness, and recommended approach."
    ],
    "top_3_priorities": [
        {"title": "short title", "description": "1-2 sentence action item for the sales team"}
    ],
    "common_objections": [
        {"objection": "what the prospect might say", "counter": "how to respond, citing evidence from the data"}
    ],
}


def build_vertical_insight_prompt(niche, prospect_summaries):
    """Build a prompt for generating campaign-level vertical insights.

    Args:
        niche: The niche/vertical searched (e.g. "DTC beauty brands")
        prospect_summaries: List of dicts with keys:
            company_name, overall_score, overall_label, sub_scores (dict),
            recommended_angle, key_risks, company_snapshot
    """
    schema_json = json.dumps(_VERTICAL_INSIGHT_SCHEMA, indent=2)

    # Build per-company summaries
    company_lines = []
    for p in prospect_summaries:
        sub = p.get("sub_scores", {})
        dims = []
        for key in ["financial_capacity", "advertising_maturity", "growth_trajectory",
                     "creative_readiness", "channel_expansion_intent"]:
            s = sub.get(key, {})
            dims.append(f"  {key}: {s.get('score', '?')}/100")
        snap = p.get("company_snapshot", {})
        revenue = snap.get("estimated_revenue", "unknown")
        pixels = ", ".join(snap.get("ad_pixels_detected", [])) or "none"
        risks = "; ".join(p.get("key_risks", []))

        company_lines.append(f"""### {p.get('company_name', '?')} — Score: {p.get('overall_score', '?')}/100 ({p.get('overall_label', '?')})
{chr(10).join(dims)}
  Revenue: {revenue} | Ad pixels: {pixels}
  Angle: {p.get('recommended_angle', 'N/A')}
  Risks: {risks}""")

    companies_text = "\n\n".join(company_lines) if company_lines else "No prospect data available."

    return f"""You are a GTM strategy analyst preparing a vertical insight brief for a sales team selling premium video / streaming TV advertising (similar to Comcast Universal Ads).

## Niche / Vertical

**"{niche}"**

## Scored Prospects in This Vertical

The following companies were discovered, analyzed (financial + techstack + brand & ad intel), and scored. Use their data to synthesize vertical-level patterns.

{companies_text}

## Task

Analyze the data above and produce a vertical insight that helps the sales team understand:
1. What makes this vertical attractive (or not) for premium video advertising
2. Common patterns across the prospects — are they mostly digital-heavy? Under-indexed on TV? Well-funded?
3. What the typical objections will be and how to counter them with evidence
4. Top 3 priorities for approaching this vertical

**Critical rules:**
- Every claim must be grounded in the prospect data above — cite specific companies, scores, and signals
- Do not hallucinate data not present in the summaries
- Be direct and actionable — this is for sales professionals, not academics

## Output Format

Return a JSON object matching this schema:

```json
{schema_json}
```

Return ONLY the JSON object. No explanation, no markdown fences."""


# ---- Outreach Brief Prompt ----

_OUTREACH_BRIEF_SCHEMA = {
    "why_fit": "2-3 sentences explaining why this company is a fit, citing specific evidence (revenue, pixels, growth)",
    "media_mix_gap": "1-2 sentences identifying what's missing in their current media mix that premium video/CTV would fill",
    "competitive_context": "1-2 sentences on what competitors in this space are doing with TV/video advertising",
    "potential_objections": [
        {"objection": "what they might say", "counter": "specific response grounded in their data"}
    ],
    "talking_points": [
        "Each is 1-2 sentences. 3-5 talking points that reference specific data from the reports."
    ],
    "suggested_subject_line": "email subject line for cold outreach",
    "opening_hook": "2-3 sentence opening for an outreach email, referencing something specific about the company",
}


def build_outreach_brief_prompt(company_name, fit_data, reports, vertical_insight=None):
    """Build a prompt for generating a per-prospect outreach brief.

    Args:
        company_name: Company being briefed
        fit_data: The ua_fit JSON (scores, sub_scores, snapshot, etc.)
        reports: dict of {analysis_type: report_text} (truncated excerpts)
        vertical_insight: Optional vertical insight JSON from the campaign
    """
    schema_json = json.dumps(_OUTREACH_BRIEF_SCHEMA, indent=2)

    # Fit summary
    score = fit_data.get("overall_score", "?")
    label = fit_data.get("overall_label", "?")
    angle = fit_data.get("recommended_angle", "N/A")
    snap = fit_data.get("company_snapshot", {})
    sub = fit_data.get("sub_scores", {})
    risks = fit_data.get("key_risks", [])

    dim_lines = []
    for key, lbl in [("financial_capacity", "Financial Capacity"),
                      ("advertising_maturity", "Paid Media Footprint"),
                      ("growth_trajectory", "Growth Trajectory"),
                      ("creative_readiness", "Video Asset Readiness"),
                      ("channel_expansion_intent", "Channel Expansion Intent")]:
        s = sub.get(key, {})
        dim_lines.append(f"- {lbl}: {s.get('score', '?')}/100 — {s.get('rationale', 'N/A')}")

    snap_lines = []
    for field, label_txt in [("website", "Website"), ("estimated_revenue", "Revenue"),
                              ("estimated_employees", "Employees"), ("ecom_platform", "E-com Platform"),
                              ("recent_funding", "Recent Funding")]:
        if snap.get(field):
            snap_lines.append(f"- {label_txt}: {snap[field]}")
    pixels = snap.get("ad_pixels_detected", [])
    if pixels:
        snap_lines.append(f"- Ad Pixels: {', '.join(pixels)}")
    channels = snap.get("primary_ad_channels", [])
    if channels:
        snap_lines.append(f"- Ad Channels: {', '.join(channels)}")

    # Build report sections
    report_sections = []
    if "techstack" in reports:
        report_sections.append(f"### Tech Stack Report\n{reports['techstack']}")
    if "financial" in reports:
        report_sections.append(f"### Financial Report\n{reports['financial']}")
    if "brand_ad" in reports:
        report_sections.append(f"### Brand & Ad Intelligence Report\n{reports['brand_ad']}")

    reports_text = "\n\n".join(report_sections) if report_sections else "No detailed reports available."

    vertical_section = ""
    if vertical_insight:
        vi_summary = vertical_insight.get("vertical_summary", "")
        vi_objections = vertical_insight.get("common_objections", [])
        obj_text = "\n".join(f"- {o.get('objection', '')}: {o.get('counter', '')}" for o in vi_objections)
        vertical_section = f"""
## Vertical Context

{vi_summary}

**Common objections in this vertical:**
{obj_text}
"""

    return f"""You are a demand gen specialist preparing an outreach brief for a sales rep selling premium video / streaming TV advertising (similar to Comcast Universal Ads).

## Target Company

**{company_name}** — Score: {score}/100 ({label})
Recommended angle: {angle}

### Dimension Scores
{chr(10).join(dim_lines)}

### Company Snapshot
{chr(10).join(snap_lines) if snap_lines else "No snapshot data."}

### Key Risks
{chr(10).join('- ' + r for r in risks) if risks else "None identified."}
{vertical_section}
## Detailed Research Reports

{reports_text}

## Task

Create an outreach brief that a sales rep can use to prepare for a cold call or email to this company. The brief must:

1. **Why they're a fit** — cite specific data (revenue, pixels, growth signals)
2. **Media mix gap** — what's missing in their current ad strategy
3. **Competitive context** — what peers/competitors are doing with TV/video
4. **Objections + counters** — 2-3 likely pushbacks with evidence-based responses
5. **Talking points** — 3-5 specific, data-backed points for the conversation
6. **Subject line + opening hook** — for a cold outreach email

**Critical rules:**
- Every claim must reference specific data from the reports or scores. No generic claims.
- Talking points should be concise and punchy — not corporate boilerplate.
- The opening hook should reference something specific and recent about the company.
- Do not fabricate data that isn't in the reports.

## Output Format

Return a JSON object matching this schema:

```json
{schema_json}
```

Return ONLY the JSON object. No explanation, no markdown fences."""
