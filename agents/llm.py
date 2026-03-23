"""Shared LLM provider rotation for report generation agents."""

import os
import json
import threading
from pathlib import Path

import httpx
import google.generativeai as genai

import re
from datetime import datetime, timezone

# Lock for genai.configure() which sets global state — prevents races between threads
gemini_lock = threading.Lock()

from db import (get_connection, get_or_create_dossier, add_dossier_analysis,
                add_dossier_event, get_previous_key_facts)


# Default chain for regular analyses — saves Gemini quota for briefings
REPORT_PROVIDERS = [
    # --- Groq (fast, generous limits) ---
    {"name": "groq", "env_key": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions", "model": "llama-3.3-70b-versatile"},
    {"name": "groq", "env_key": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions", "model": "meta-llama/llama-4-scout-17b-16e-instruct"},
    {"name": "groq", "env_key": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions", "model": "qwen/qwen3-32b"},
    # --- Cerebras (1M tokens/day) ---
    {"name": "cerebras", "env_key": "CEREBRAS_API_KEY", "url": "https://api.cerebras.ai/v1/chat/completions", "model": "llama-3.3-70b"},
    # --- Mistral (unlimited daily, slow 2 RPM) ---
    {"name": "mistral", "env_key": "MISTRAL_API_KEY", "url": "https://api.mistral.ai/v1/chat/completions", "model": "mistral-small-latest"},
    # --- Gemini (fallback — prefer saving quota for briefings) ---
    {"name": "gemini", "env_key": "GEMINI_API_KEYS", "url": None, "model": "gemini-2.5-flash-lite"},
    # --- OpenRouter (low daily quota, last resort) ---
    {"name": "openrouter", "env_key": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions", "model": "nousresearch/hermes-3-llama-3.1-405b:free"},
    {"name": "openrouter", "env_key": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions", "model": "meta-llama/llama-3.3-70b-instruct:free"},
    {"name": "openrouter", "env_key": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions", "model": "qwen/qwen3-next-80b-a3b-instruct:free"},
    {"name": "openrouter", "env_key": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/chat/completions", "model": "mistralai/mistral-small-3.1-24b-instruct:free"},
]

# Gemini-first chain reserved for intelligence briefings
BRIEFING_PROVIDERS = [
    {"name": "gemini", "env_key": "GEMINI_API_KEYS", "url": None, "model": "gemini-2.5-flash-lite"},
    {"name": "gemini", "env_key": "GEMINI_API_KEYS", "url": None, "model": "gemini-2.5-flash"},
    {"name": "gemini", "env_key": "GEMINI_API_KEYS", "url": None, "model": "gemini-3-flash-preview"},
    # Fallbacks if Gemini is exhausted
    {"name": "groq", "env_key": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions", "model": "llama-3.3-70b-versatile"},
    {"name": "cerebras", "env_key": "CEREBRAS_API_KEY", "url": "https://api.cerebras.ai/v1/chat/completions", "model": "llama-3.3-70b"},
    {"name": "mistral", "env_key": "MISTRAL_API_KEY", "url": "https://api.mistral.ai/v1/chat/completions", "model": "mistral-small-latest"},
]


def generate_text(prompt, timeout=60, providers=None):
    """Try providers in order until one works. Returns (text, model_name).

    Gemini entries with comma-separated keys in GEMINI_API_KEYS are expanded
    so each key is tried before moving to the next provider/model.
    """
    provider_list = providers or REPORT_PROVIDERS
    http = httpx.Client(timeout=timeout, follow_redirects=True)

    # Expand comma-separated keys (works for all providers)
    expanded = []
    for p in provider_list:
        raw_key = os.environ.get(p["env_key"], "").strip()
        if not raw_key:
            continue
        if "," in raw_key:
            for k in raw_key.split(","):
                k = k.strip()
                if k:
                    expanded.append({**p, "_key": k})
        else:
            expanded.append({**p, "_key": raw_key})

    for p in expanded:
        key = p["_key"]
        model_id = f"{p['name']}/{p['model']}"
        # Show truncated key suffix so you can tell which account was used
        key_hint = key[-4:] if len(key) >= 4 else '****'

        try:
            if p["name"] == "gemini":
                with gemini_lock:
                    genai.configure(api_key=key)
                    model = genai.GenerativeModel(p["model"])
                    response = model.generate_content(prompt)
                http.close()
                print(f"[llm] ✓ {model_id} (key …{key_hint})")
                return response.text, model_id
            else:
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                body = {"model": p["model"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
                resp = http.post(p["url"], json=body, headers=headers)
                if resp.status_code == 200:
                    text = resp.json()["choices"][0]["message"]["content"]
                    http.close()
                    print(f"[llm] ✓ {model_id} (key …{key_hint})")
                    return text, model_id
                elif resp.status_code == 429:
                    print(f"[llm] {model_id} (key …{key_hint}) rate limited — trying next key")
                    continue
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                print(f"[llm] {model_id} (key …{key_hint}) rate limited — trying next key")
            else:
                print(f"[llm] {model_id} (key …{key_hint}) failed: {e}")
            continue

    http.close()
    raise RuntimeError("All LLM providers failed for text generation")


def generate_json(prompt, timeout=60, providers=None):
    """Generate text and parse as JSON. Returns parsed dict/list or None."""
    try:
        text, _ = generate_text(prompt, timeout=timeout, providers=providers)
        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
        return json.loads(text)
    except Exception as e:
        print(f"[llm] JSON generation failed: {e}")
        return None


# --- Dossier integration ---

_KEY_FACTS_PROMPT = """Extract structured key facts from this competitive intelligence report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Do not guess or infer. Use null for missing values.

Fields to extract:
- "revenue": latest annual revenue as string (e.g. "$50B")
- "market_cap": market cap as string (e.g. "$2.8T")
- "headcount": approximate employee count as integer
- "founded": founding year as integer
- "hq_location": headquarters city/state/country
- "ceo": current CEO name
- "sector": industry sector
- "key_products": array of top 3-5 products/services
- "key_competitors": array of top 3-5 competitors
- "key_risks": array of top 3 business risks
- "patent_count": total patents as integer
- "top_patent_areas": array of top 3-5 patent technology areas
- "sentiment_score": employee sentiment (positive/mixed/negative)
- "hiring_trend": hiring trend (growing/stable/shrinking)
- "notable_events": array of max 3 recent strategic events (each: {{"title": "...", "date": "...", "type": "..."}})

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

# Type-specific key facts prompts for richer structured data
_TECHSTACK_FACTS_PROMPT = """Extract structured tech stack facts from this report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "frontend_framework": primary frontend framework name (e.g. "React", "Next.js", "Vue.js") or null
- "css_framework": CSS framework name (e.g. "Tailwind", "Bootstrap") or null
- "analytics_tools": array of analytics/tracking tools detected (e.g. ["Google Analytics", "Segment", "Mixpanel"])
- "marketing_tools": array of marketing/CRM tools detected (e.g. ["HubSpot", "Marketo", "Intercom"])
- "cdn_hosting": array of CDN/hosting providers detected (e.g. ["Cloudflare", "AWS CloudFront", "Vercel"])
- "cms": CMS platform if any (e.g. "WordPress", "Contentful") or null
- "monitoring_tools": array of performance/error monitoring tools (e.g. ["Sentry", "Datadog", "New Relic"])
- "ab_testing_tools": array of A/B testing / experimentation tools (e.g. ["Optimizely", "LaunchDarkly"])
- "auth_provider": authentication provider if any (e.g. "Auth0", "Okta") or null
- "search_provider": search infrastructure if any (e.g. "Algolia") or null
- "payment_provider": payment processor if any (e.g. "Stripe", "PayPal") or null
- "infrastructure_provider": primary cloud/hosting (e.g. "AWS", "Google Cloud", "Vercel") or null
- "total_technologies_detected": integer count of all technologies found
- "tech_modernity_signals": array of 2-3 short observations about whether the stack is modern, legacy, or mixed

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_SEO_FACTS_PROMPT = """Extract structured SEO/AEO facts from this audit report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "seo_title_optimization_pct": integer 0-100 (percentage of pages with properly optimized title tags)
- "seo_meta_desc_pct": integer 0-100 (percentage of pages with optimized meta descriptions)
- "seo_heading_hierarchy_pct": integer 0-100 (percentage of pages with proper heading hierarchy)
- "seo_schema_types": array of schema.org types found (e.g. ["Organization", "Product", "FAQPage"])
- "seo_has_faq_schema": boolean — true if FAQ schema markup was found
- "seo_has_article_schema": boolean — true if Article schema was found
- "aeo_readiness_signals": array of 2-3 short observations about AI answer engine readiness
- "seo_overall_assessment": "strong" or "moderate" or "weak"
- "pages_analyzed": integer count of pages audited

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_PRICING_FACTS_PROMPT = """Extract structured pricing facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "pricing_model": one of "freemium", "subscription", "usage_based", "enterprise_only", "contact_sales", "hybrid", "unknown"
- "pricing_tiers": array of tier/plan names (e.g. ["Free", "Pro", "Enterprise"])
- "price_range": string describing visible price range (e.g. "$0-$500/mo", "Contact Sales", "$99-$999/mo")
- "has_public_pricing": boolean — true if specific prices are publicly listed
- "has_free_tier": boolean — true if a free plan or trial is offered
- "target_segment": one of "SMB", "Mid-Market", "Enterprise", "All Segments"

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_HIRING_FACTS_PROMPT = """Extract structured hiring intelligence from this competitive hiring analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "total_open_roles": integer count of open positions analyzed
- "engineering_ratio": string percentage of roles in Engineering (e.g. "67%")
- "ai_ml_ratio": string percentage of engineering roles in AI/ML specifically (e.g. "12% of engineering")
- "top_departments": array of top 3-5 departments with counts (e.g. ["Engineering (67%)", "Data (19%)", "Product (10%)"])
- "top_subcategories": array of top 5-8 subcategories with counts (e.g. ["AI/ML (15)", "Platform/Infrastructure (8)"])
- "seniority_skew": string describing the distribution (e.g. "senior-heavy (43% Senior+)" or "mid-heavy (55% Mid-level)")
- "growth_signal": string percentage of likely new roles (e.g. "67% likely new roles")
- "top_strategic_tags": array of most common strategic tags (e.g. ["AI/ML Investment", "Platform Migration"])
- "hiring_trend": one of "growing", "stable", "shrinking"
- "notable_shifts": string describing any noteworthy patterns (e.g. "Heavy PhD-required AI roles suggest research expansion")
- "top_skills": array of top 10 most demanded skills/technologies
- "primary_locations": array of top 3-5 hiring locations

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_SENTIMENT_FACTS_PROMPT = """Extract structured employee sentiment facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "overall_sentiment": one of "positive", "mixed", "negative"
- "glassdoor_rating": number (e.g. 4.2) or null
- "recommend_to_friend_pct": string percentage (e.g. "78%") or null
- "approve_of_ceo_pct": string percentage (e.g. "92%") or null
- "top_pros": array of top 3-5 employee pros/positives (short phrases)
- "top_cons": array of top 3-5 employee cons/negatives (short phrases)
- "culture_themes": array of 3-5 recurring culture themes (e.g. "mission-driven", "fast-paced", "work-life balance concerns")
- "notable_concerns": array of 2-3 notable employee concerns or red flags
- "sentiment_trend": one of "improving", "stable", "declining" or null

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_FINANCIAL_FACTS_PROMPT = """Extract structured financial facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "revenue": latest annual revenue as string (e.g. "$50B")
- "revenue_growth": year-over-year revenue growth as string (e.g. "+23%") or null
- "market_cap": market cap as string (e.g. "$2.8T") or null
- "valuation": private valuation as string (e.g. "$380B") or null if public
- "headcount": approximate employee count as integer
- "profitability": one of "profitable", "near-breakeven", "unprofitable", "unknown"
- "cash_position": string describing cash/liquidity (e.g. "$12B cash on hand") or null
- "recent_funding": string describing latest funding round (e.g. "Series E, $4B at $380B valuation") or null
- "key_financial_risks": array of top 3 financial risks
- "financial_health": one of "strong", "moderate", "weak", "unknown"

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_COMPETITORS_FACTS_PROMPT = """Extract structured competitive landscape facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "key_competitors": array of top 3-5 direct competitors
- "market_position": one of "leader", "challenger", "niche", "emerging"
- "competitive_advantages": array of 3-5 key competitive strengths
- "competitive_weaknesses": array of 2-3 key competitive vulnerabilities
- "market_share": string estimate if available (e.g. "~15% of enterprise AI market") or null
- "competitive_moat": string describing primary defensibility (e.g. "distribution + enterprise relationships") or null
- "threat_level": one of "high", "medium", "low" — how threatened is this company by competitors

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_PATENTS_FACTS_PROMPT = """Extract structured patent/IP facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "total_patents": integer count of patents found
- "recent_patents": integer count of patents filed in last 2 years or null
- "top_patent_areas": array of top 3-5 technology areas with patent counts (e.g. ["Machine Learning (12)", "NLP (8)", "Computer Vision (5)"])
- "ai_ml_patents": integer count of AI/ML related patents or null
- "patent_trend": one of "accelerating", "steady", "declining" or null
- "notable_patents": array of 2-3 notable or strategically significant patents (short descriptions)
- "rd_intensity": one of "very high", "high", "moderate", "low" — overall R&D/innovation intensity

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_PROFILE_FACTS_PROMPT = """Extract structured company profile facts from this analysis report about {company}.

Return a JSON object with ONLY the fields you can find evidence for. Use null for missing values.

Fields to extract:
- "hq_location": headquarters city/state/country
- "ceo": current CEO name
- "founded": founding year as integer
- "sector": industry sector
- "headcount": approximate employee count as integer
- "revenue": latest annual revenue as string (e.g. "$50B")
- "market_cap": market cap as string (e.g. "$2.8T") or null
- "key_products": array of top 3-5 products/services
- "key_competitors": array of top 3-5 competitors
- "business_model": string describing how they make money (1 sentence)
- "key_risks": array of top 3 business risks

Report:
{report_text}

Return ONLY valid JSON, no explanation."""

_TYPE_KEY_FACTS_PROMPTS = {
    "techstack": _TECHSTACK_FACTS_PROMPT,
    "seo": _SEO_FACTS_PROMPT,
    "pricing": _PRICING_FACTS_PROMPT,
    "hiring": _HIRING_FACTS_PROMPT,
    "sentiment": _SENTIMENT_FACTS_PROMPT,
    "financial": _FINANCIAL_FACTS_PROMPT,
    "competitors": _COMPETITORS_FACTS_PROMPT,
    "patents": _PATENTS_FACTS_PROMPT,
    "profile": _PROFILE_FACTS_PROMPT,
}


def extract_key_facts(company, report_text, analysis_type=None):
    """Extract structured key facts from a report. Returns dict or None."""
    # Truncate very long reports to save tokens
    if len(report_text) > 8000:
        report_text = report_text[:8000] + "\n\n... (truncated)"

    prompt_template = _TYPE_KEY_FACTS_PROMPTS.get(analysis_type, _KEY_FACTS_PROMPT)
    prompt = prompt_template.format(company=company, report_text=report_text)
    facts = generate_json(prompt, timeout=30)

    if isinstance(facts, dict):
        # Clean out null values
        return {k: v for k, v in facts.items() if v is not None}
    return None


def reextract_all_key_facts(company, db_path="intel.db"):
    """Re-extract key facts for all analyses of a company using type-specific prompts.

    Reads existing report files, re-runs extraction with the correct prompt,
    and updates the DB records in-place. Returns summary of what was updated.
    """
    from db import get_connection, get_dossier_by_company

    conn = get_connection(db_path)
    dossier = get_dossier_by_company(conn, company)
    if not dossier:
        conn.close()
        return f"No dossier found for '{company}'."

    updated = []
    skipped = []

    for analysis in dossier.get("analyses", []):
        atype = analysis["analysis_type"]
        report_file = analysis.get("report_file")
        analysis_id = analysis["id"]

        if not report_file:
            skipped.append(f"{atype}: no report file")
            continue

        report_path = Path(report_file)
        if not report_path.exists():
            skipped.append(f"{atype}: report file missing ({report_file})")
            continue

        try:
            report_text = report_path.read_text(encoding="utf-8")
            new_facts = extract_key_facts(company, report_text, analysis_type=atype)
            if new_facts:
                facts_json = json.dumps(new_facts)
                conn.execute(
                    "UPDATE dossier_analyses SET key_facts_json = ? WHERE id = ?",
                    (facts_json, analysis_id),
                )
                conn.commit()
                updated.append(f"{atype}: {len(new_facts)} facts extracted")
            else:
                skipped.append(f"{atype}: extraction returned nothing")
        except Exception as e:
            skipped.append(f"{atype}: error — {e}")

    conn.close()

    lines = [f"Re-extracted key facts for {company}:"]
    if updated:
        lines.append(f"\nUpdated ({len(updated)}):")
        for u in updated:
            lines.append(f"  ✓ {u}")
    if skipped:
        lines.append(f"\nSkipped ({len(skipped)}):")
        for s in skipped:
            lines.append(f"  - {s}")
    return "\n".join(lines)


def _parse_numeric(value):
    """Parse a numeric value from various formats. Returns float or None.

    Handles: 22547, "22547", "$50B", "$2.8T", "221,000", "12.5%", "$198.3M"
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    text = value.strip().replace(",", "").replace("%", "")

    multipliers = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}
    match = re.match(r"^\$?\s*([\d.]+)\s*([TBMK])?", text, re.IGNORECASE)
    if match:
        num = float(match.group(1))
        suffix = (match.group(2) or "").upper()
        return num * multipliers.get(suffix, 1.0)

    try:
        return float(text.lstrip("$"))
    except (ValueError, TypeError):
        return None


# Fields that should be compared numerically
_NUMERIC_FIELDS = {"revenue", "market_cap", "headcount", "patent_count", "founded"}
# Fields where any change is significant
_IMPORTANT_FIELDS = {"ceo", "sentiment_score", "hiring_trend", "sector"}
# List fields where we track additions/removals
_LIST_FIELDS = {"key_products", "key_competitors", "key_risks", "top_patent_areas"}
# Minimum % change to consider significant for numeric fields
_CHANGE_THRESHOLD_PCT = 5.0


def _detect_changes(old_facts, new_facts):
    """Compare old and new key facts, return list of change dicts.

    Each change: {field, old_value, new_value, change_type, pct_change?}
    change_type: increased | decreased | changed | added | removed
    """
    changes = []
    all_fields = set(old_facts.keys()) | set(new_facts.keys())

    for field in all_fields:
        old_val = old_facts.get(field)
        new_val = new_facts.get(field)

        # Skip notable_events — these are ephemeral, not tracked for changes
        if field == "notable_events":
            continue

        # Both missing or identical
        if old_val == new_val:
            continue

        # Field added (didn't exist before)
        if old_val is None and new_val is not None:
            changes.append({"field": field, "old_value": None, "new_value": new_val, "change_type": "added"})
            continue

        # Field removed
        if old_val is not None and new_val is None:
            continue  # Don't flag removals — LLM may just not extract it this time

        # Numeric comparison
        if field in _NUMERIC_FIELDS:
            old_num = _parse_numeric(old_val)
            new_num = _parse_numeric(new_val)
            if old_num is not None and new_num is not None and old_num != 0:
                pct = ((new_num - old_num) / abs(old_num)) * 100
                if abs(pct) >= _CHANGE_THRESHOLD_PCT:
                    change_type = "increased" if pct > 0 else "decreased"
                    changes.append({
                        "field": field, "old_value": old_val, "new_value": new_val,
                        "change_type": change_type, "pct_change": round(pct, 1),
                    })
            continue

        # List comparison
        if field in _LIST_FIELDS:
            if isinstance(old_val, list) and isinstance(new_val, list):
                old_set = set(str(x).lower() for x in old_val)
                new_set = set(str(x).lower() for x in new_val)
                added = new_set - old_set
                removed = old_set - new_set
                if added:
                    changes.append({
                        "field": field, "old_value": list(old_set), "new_value": list(new_set),
                        "change_type": "added", "items_added": list(added), "items_removed": list(removed),
                    })
                elif removed:
                    changes.append({
                        "field": field, "old_value": list(old_set), "new_value": list(new_set),
                        "change_type": "removed", "items_added": list(added), "items_removed": list(removed),
                    })
            continue

        # String/important field comparison
        if field in _IMPORTANT_FIELDS:
            if str(old_val).lower().strip() != str(new_val).lower().strip():
                changes.append({
                    "field": field, "old_value": old_val, "new_value": new_val,
                    "change_type": "changed",
                })

    return changes


def get_temporal_context(company, analysis_type, db_path="intel.db"):
    """Return a prompt section with previous key facts for temporal comparison.
    Returns empty string if no prior analysis exists."""
    from db import get_connection, get_dossier_by_company, get_previous_key_facts
    try:
        conn = get_connection(db_path)
        dossier = get_dossier_by_company(conn, company)
        if not dossier:
            conn.close()
            return ""
        prev = get_previous_key_facts(conn, dossier["id"], analysis_type)
        if not prev:
            conn.close()
            return ""
        row = conn.execute(
            """SELECT created_at FROM dossier_analyses
               WHERE dossier_id = ? AND analysis_type = ?
               ORDER BY created_at DESC LIMIT 1""",
            (dossier["id"], analysis_type)
        ).fetchone()
        conn.close()
        prev_date = (row["created_at"] or "")[:10] if row else "unknown"
        facts_json = json.dumps(prev, indent=2)
        return (
            f"\n\n## Previous Analysis ({prev_date})\n"
            f"We previously analyzed this company's {analysis_type} data. "
            f"Key findings from that analysis:\n{facts_json}\n\n"
            f"IMPORTANT: Compare your current findings against these previous values. "
            f"When you find a significant change, explicitly call it out "
            f"(e.g., 'Revenue increased from $48B to $52B, representing 8.3% growth "
            f"since {prev_date}'). Highlight what changed, what stayed the same, "
            f"and what the trend implies."
        )
    except Exception:
        return ""


def save_to_dossier(company, analysis_type, report_file=None, report_text=None,
                    model_used=None, db_path="intel.db"):
    """Save an analysis to the company dossier with extracted key facts.

    Called at the end of every analysis agent. Extracts structured facts from
    the report, detects changes vs. previous run, and stores everything.
    """
    try:
        conn = get_connection(db_path)

        # Get or create dossier
        dossier_id = get_or_create_dossier(conn, company)

        # Extract key facts from report text
        key_facts_json = None
        new_facts = None
        if report_text:
            print(f"[dossier] Extracting key facts for {company}/{analysis_type}...")
            new_facts = extract_key_facts(company, report_text, analysis_type=analysis_type)
            if new_facts:
                key_facts_json = json.dumps(new_facts)
                print(f"[dossier] Extracted {len(new_facts)} facts: {list(new_facts.keys())}")
            else:
                print("[dossier] No key facts extracted")

        # Detect changes vs. previous analysis
        if new_facts:
            old_facts = get_previous_key_facts(conn, dossier_id, analysis_type)
            if old_facts:
                changes = _detect_changes(old_facts, new_facts)
                if changes:
                    print(f"[dossier] Detected {len(changes)} changes since last {analysis_type} scan:")
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    for c in changes:
                        # Log to console
                        if c.get("pct_change") is not None:
                            print(f"[dossier]   {c['field']}: {c['old_value']} -> {c['new_value']} ({c['pct_change']:+.1f}%)")
                        elif c["change_type"] == "added" and c.get("items_added"):
                            print(f"[dossier]   {c['field']}: +{c['items_added']}")
                        else:
                            print(f"[dossier]   {c['field']}: {c['old_value']} -> {c['new_value']}")

                        # Save as timeline event
                        if c.get("pct_change") is not None:
                            title = f"{c['field']}: {c['old_value']} -> {c['new_value']} ({c['pct_change']:+.1f}%)"
                        elif c["change_type"] == "added" and c.get("items_added"):
                            title = f"{c['field']}: added {', '.join(c['items_added'][:3])}"
                        else:
                            title = f"{c['field']}: {c['old_value']} -> {c['new_value']}"

                        add_dossier_event(
                            conn, dossier_id,
                            event_type="change_detected",
                            title=title,
                            description=f"Detected during {analysis_type} analysis",
                            event_date=today,
                            data_json=json.dumps(c),
                        )
                else:
                    print(f"[dossier] No significant changes since last {analysis_type} scan")
            else:
                print(f"[dossier] First {analysis_type} scan — no prior data to compare")

        # Store the analysis
        add_dossier_analysis(
            conn, dossier_id, analysis_type,
            report_file=report_file,
            key_facts_json=key_facts_json,
            model_used=model_used,
        )

        conn.close()
        print(f"[dossier] Saved {analysis_type} analysis to {company} dossier")
        return dossier_id
    except Exception as e:
        print(f"[dossier] Error saving to dossier: {e}")
        return None
