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


REPORT_PROVIDERS = [
    {"name": "gemini", "env_key": "GEMINI_API_KEYS", "url": None, "model": "gemini-2.5-flash-lite"},
    {"name": "groq", "env_key": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions", "model": "llama-3.3-70b-versatile"},
    {"name": "mistral", "env_key": "MISTRAL_API_KEY", "url": "https://api.mistral.ai/v1/chat/completions", "model": "mistral-small-latest"},
]


def generate_text(prompt, timeout=60, providers=None):
    """Try providers in order until one works. Returns (text, model_name)."""
    provider_list = providers or REPORT_PROVIDERS
    http = httpx.Client(timeout=timeout, follow_redirects=True)

    for p in provider_list:
        key = os.environ.get(p["env_key"], "").strip()
        if not key:
            continue
        if "," in key:
            key = key.split(",")[0].strip()

        try:
            if p["name"] == "gemini":
                with gemini_lock:
                    genai.configure(api_key=key)
                    model = genai.GenerativeModel(p["model"])
                    response = model.generate_content(prompt)
                http.close()
                return response.text, f"gemini/{p['model']}"
            else:
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                body = {"model": p["model"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
                resp = http.post(p["url"], json=body, headers=headers)
                if resp.status_code == 200:
                    text = resp.json()["choices"][0]["message"]["content"]
                    http.close()
                    return text, f"{p['name']}/{p['model']}"
        except Exception:
            continue

    http.close()
    raise RuntimeError("All LLM providers failed for text generation")


def generate_json(prompt, timeout=60):
    """Generate text and parse as JSON. Returns parsed dict/list or None."""
    try:
        text, _ = generate_text(prompt, timeout=timeout)
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

_TYPE_KEY_FACTS_PROMPTS = {
    "techstack": _TECHSTACK_FACTS_PROMPT,
    "seo": _SEO_FACTS_PROMPT,
    "pricing": _PRICING_FACTS_PROMPT,
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
