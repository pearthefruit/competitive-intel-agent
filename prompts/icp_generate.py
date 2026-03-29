"""Prompt for generating an ICP configuration from wizard survey answers.

Takes structured survey responses and asks the LLM to produce a complete
ICP config JSON that drives the scoring and discovery pipeline.
"""

import json


_ICP_CONFIG_SCHEMA = {
    "icp_definition": "2-4 sentence prose describing the ideal prospect. Be specific.",
    "dimensions": [
        {
            "key": "snake_case_dimension_name",
            "label": "Human Readable Label",
            "weight": 0.20,
            "description": "What this dimension measures",
            "rubric": {
                "80_100": "What signals indicate 80-100",
                "60_79": "What signals indicate 60-79",
                "40_59": "What signals indicate 40-59",
                "20_39": "What signals indicate 20-39",
                "0_19": "What signals indicate 0-19",
            },
            "signal_queries": {
                "primary": "{company} search query for this dimension",
                "secondary": "{company} optional second query (or null)",
                "news": False,
                "reddit": "null or {company} reddit query",
            },
            "signal_category_name": "Human readable signal bucket name",
            "use_tech_detection": False,
        },
    ],
    "labels": [
        {"min_score": 80, "label": "Prime Prospect"},
        {"min_score": 60, "label": "Strong Candidate"},
        {"min_score": 40, "label": "Possible Fit"},
        {"min_score": 20, "label": "Weak Fit"},
        {"min_score": 0, "label": "Not a Fit"},
    ],
    "discovery_filters": {
        "include_description": "What types of companies to include in discovery",
        "exclude_description": "What types of companies to exclude",
        "search_queries_template": [
            "top {niche} 2026",
            "fastest growing {niche}",
            "best {niche} companies brands",
            "{niche} emerging brands to watch",
        ],
    },
    "scoring_output_schema": {
        "recommended_angle_guidance": "What the sales angle should focus on",
        "risk_focus": "Types of risks/objections to highlight",
    },
    "suggested_niches": [
        "example niche query 1",
        "example niche query 2",
        "example niche query 3",
    ],
}


def build_icp_generation_prompt(survey_answers):
    """Build a prompt to generate an ICP config from the guided survey wizard.

    The wizard funnels: B2B/B2C → industry → sub-industry → offer → customers → sales.
    Questions adapt to business type. The LLM infers the full ICP from these answers.

    Args:
        survey_answers: Dict with funnel + adaptive fields (see schema in plan).

    Returns:
        Prompt string expecting JSON output matching the ICP config schema.
    """
    sa = survey_answers

    # Build the business context line
    customer_type = sa.get("customer_type", "B2B")
    industry = sa.get("industry", "")
    sub_industry = sa.get("sub_industry", "")
    niche_detail = sa.get("niche_detail", "")
    biz_context = f"{customer_type}"
    if industry:
        biz_context += f" > {industry}"
    if sub_industry:
        biz_context += f" > {sub_industry}"
    if niche_detail:
        biz_context += f" ({niche_detail})"

    # B2B customer fields
    sizes = ", ".join(sa.get("sizes", [])) or "Not specified"
    commonalities = ", ".join(sa.get("commonalities", [])) or "None selected"
    commonalities_other = sa.get("commonalities_other", "").strip()
    if commonalities_other:
        commonalities += f". Also: {commonalities_other}"

    # B2C customer fields
    consumer_traits = ", ".join(sa.get("consumer_traits", [])) or "None selected"
    where_they_buy = ", ".join(sa.get("where_they_buy", [])) or "Not specified"
    acquisition_channels = ", ".join(sa.get("acquisition_channels", [])) or "Not specified"

    pre_revenue_note = ""
    if sa.get("pre_revenue"):
        pre_revenue_note = "\n**Note:** This user is pre-revenue. Their answers are aspirational. Infer a reasonable ICP from their business context and product description.\n"

    # Build customer section based on B2B vs B2C
    is_b2c = customer_type == "B2C"

    if is_b2c:
        customer_section = f"""**Ideal consumer:**
{sa.get('ideal_consumer', 'Not provided')}

**Price point:**
{sa.get('price_point', 'Not specified')}

**Where they buy:**
{where_they_buy}

**Consumer traits:**
{consumer_traits}"""

        sales_section = f"""**How customers find them:**
{acquisition_channels}

**Purchase frequency:**
{sa.get('purchase_frequency', 'Not specified')}

**Average order value:**
{sa.get('avg_order_value', 'Not specified')}"""
    else:
        customer_section = f"""**Best customers (or dream customers):**
{sa.get('best_customers', 'Not provided')}

**Company sizes they target:**
{sizes}

**What those customers have in common:**
{commonalities}"""

        sales_section = f"""**How customers buy:**
{sa.get('how_they_buy', 'Not specified')}

**Typical deal size:**
{sa.get('deal_size', 'Not specified')}

**Sales cycle length:**
{sa.get('sales_cycle', 'Not specified')}"""

    schema_json = json.dumps(_ICP_CONFIG_SCHEMA, indent=2)

    return f"""You are a GTM strategist helping someone define their Ideal Customer Profile.
They used a guided wizard that narrowed down their business type first, then asked
adaptive questions. Your job is to generate a precise, actionable ICP configuration.

This configuration drives automated company discovery, scoring, and ranking. It must be
specific to their industry and business model — not generic.
{pre_revenue_note}
## Business Context

**Business type:** {biz_context}

## Their Offer

**What they do:**
{sa.get('product', 'Not provided')}

**What problem it solves:**
{sa.get('problem', 'Not provided')}

## Their Customers

{customer_section}

## How They Sell

{sales_section}

## Your Task

From the above, generate a complete ICP config JSON. The config must be tailored to their
specific industry ({industry or 'general'}) and business model ({customer_type}).

{"For B2C businesses: dimensions should focus on consumer-facing signals like social media presence, brand awareness, product reviews, retail distribution, marketing spend, and growth trajectory. The 'companies' being scored are the B2C brands themselves — think of them as potential partners, competitors to study, or acquisition targets." if is_b2c else ""}

Generate a JSON object matching this schema:

```json
{schema_json}
```

## Rules

1. Generate **4-6 dimensions**. Weights MUST sum to exactly 1.0.
2. Each dimension must have **specific, actionable rubric bands** — not generic filler. The rubric should reference concrete signals that a web search could actually find for companies in {industry or 'this space'}.
3. **Signal queries** use `{{company}}` as placeholder. Target findable information.
4. The **ICP definition** should be 2-4 sentences, specific to {sub_industry or industry or 'their business'}.
5. **Labels** must cover full 0-100 range with 5 tiers. Customize to the context.
6. **Discovery filters** should reflect their industry, company sizes, and business type.
7. **search_queries_template** uses `{{niche}}` as placeholder.
8. Set `use_tech_detection: true` on at most one dimension where website crawling helps.
9. Set `news: true` where recent news matters (growth, funding, launches).
10. Set `reddit` query where community discussion adds signal.
11. If any answer is blank or "Not sure", infer from other answers.
12. **suggested_niches**: Generate 3-5 specific niche search queries the user could use to discover prospects. These should be concrete, searchable terms like "DTC skincare brands", "mid-market SaaS companies", "regional restaurant chains" — based on their industry and ideal customer profile.

Return ONLY the JSON object. No explanation or markdown fences."""
