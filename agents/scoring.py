"""Algorithmic Digital Maturity Score — deterministic base scores from structured data.

Computes base scores for each DMS dimension using hiring stats, key facts, and
techstack data. Designed to run before the LLM briefing call; scores are injected
into the prompt so the LLM adjusts within ±10 with justification.
"""

import re

# ---------------------------------------------------------------------------
# Reference sets
# ---------------------------------------------------------------------------

AI_NATIVE_KEYWORDS = frozenset({
    "artificial intelligence", "machine learning", "ai", "llm",
    "large language model", "foundation model", "generative ai",
    "deep learning", "computer vision", "natural language processing",
})

SOFTWARE_KEYWORDS = frozenset({
    "software", "cloud", "saas", "platform", "developer tools", "devops",
    "data platform", "analytics platform", "cybersecurity", "fintech",
    "edtech", "healthtech", "martech", "adtech", "infrastructure",
    "enterprise software", "b2b software",
})

DATA_PRODUCT_KEYWORDS = frozenset({
    "data platform", "analytics", "business intelligence", "bi platform",
    "data warehouse", "data lake", "etl", "observability platform",
    "data infrastructure", "data analytics",
})

MODERN_STACK = frozenset({
    "react", "next.js", "nextjs", "vue", "vue.js", "svelte", "typescript",
    "go", "golang", "rust", "kubernetes", "k8s", "terraform", "docker",
    "graphql", "kafka", "microservices", "grpc", "mlops", "pytorch",
    "spark", "airflow", "dbt", "ray", "jax", "triton", "cuda",
    "aws", "gcp", "azure", "vercel", "cloudflare", "tailwind",
    "fastapi", "node.js", "postgresql", "redis", "elasticsearch",
})

LEGACY_STACK = frozenset({
    "cobol", ".net framework", "vb.net", "visual basic", "mainframe",
    "oracle forms", "powerbuilder", "coldfusion", "perl", "cvs", "svn",
    "delphi", "foxpro", "classic asp", "struts",
})

DATA_SUBCATEGORIES = frozenset({
    "Data Engineering", "Data Science", "Analytics", "ML Ops",
    "BI/Reporting", "General Data",
})

ADVANCED_ANALYTICS_TOOLS = frozenset({
    "segment", "amplitude", "mixpanel", "heap", "rudderstack", "snowplow",
    "mparticle", "fullstory", "posthog",
})

AB_TESTING_TOOLS = frozenset({
    "optimizely", "launchdarkly", "statsig", "growthbook", "vwo",
    "split.io", "flagsmith",
})

MODERN_INFRA = frozenset({
    "aws", "google cloud", "gcp", "azure", "vercel", "cloudflare",
    "fly.io", "render", "railway", "netlify",
})

MODERN_MONITORING = frozenset({
    "datadog", "new relic", "sentry", "dynatrace", "grafana",
    "honeycomb", "pagerduty", "splunk",
})

INVESTMENT_TAGS = frozenset({
    "AI/ML Investment", "Cloud/Infrastructure", "Platform Migration",
    "Automation", "Data Infrastructure", "Developer Experience",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_pct(value):
    """Extract a percentage from strings like '67%', '67% new roles', '12% of engineering'.

    Returns float 0-100, or None if unparseable.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = re.search(r"([\d.]+)\s*%", value)
    if match:
        return float(match.group(1))
    return None


def _clamp(val, lo=0, hi=100):
    return max(lo, min(hi, val))


def _sector_text(profile_kf, hiring_kf):
    """Get lowercased sector string from profile or hiring key facts."""
    return (
        (profile_kf.get("sector") or hiring_kf.get("sector") or "")
        .lower()
        .strip()
    )


def _matches_any(text, keywords):
    """Check if text contains any keyword from the set (word-boundary match).

    Uses regex word boundaries to avoid false positives like 'water infrastructure'
    matching 'infrastructure' in SOFTWARE_KEYWORDS, or 'saas-centric' matching 'saas'.
    """
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw)}\b", text):
            return True
    return False


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------

def _score_tech_modernity(hiring_stats, techstack_kf, profile_kf, hiring_kf):
    """Score Tech Modernity (0-100).

    Sector is an additive bonus, not a floor — so a legacy SaaS company can
    still score poorly if their hiring/stack signals are weak.
    """
    signals = []
    missing = []

    sector = _sector_text(profile_kf, hiring_kf)

    # --- Sector bonus (additive, not floor) ---
    sector_pts = 0
    if _matches_any(sector, AI_NATIVE_KEYWORDS):
        sector_pts = 25
        signals.append(f"AI-native sector '{sector}' → +25 pts")
    elif _matches_any(sector, SOFTWARE_KEYWORDS):
        sector_pts = 15
        signals.append(f"Software sector '{sector}' → +15 pts")

    # --- Engineering ratio ---
    eng_pts = 0
    if hiring_stats:
        dept_counts = hiring_stats.get("dept_counts", {})
        total = hiring_stats.get("total_roles", 0)
        eng_count = dept_counts.get("Engineering", 0)
        if total > 0:
            eng_pct = eng_count * 100 / total
            if eng_pct >= 50:
                eng_pts = 30
            elif eng_pct >= 30:
                eng_pts = 20
            elif eng_pct >= 15:
                eng_pts = 10
            signals.append(f"Engineering ratio {eng_pct:.0f}% ({eng_count}/{total}) → +{eng_pts} pts")
        else:
            missing.append("hiring")
    else:
        missing.append("hiring")

    # --- Modern vs legacy stack skills ---
    stack_pts = 0
    if hiring_stats and hiring_stats.get("top_skills"):
        skills_lower = {s.lower() for s in hiring_stats["top_skills"]}
        modern_hits = skills_lower & MODERN_STACK
        legacy_hits = skills_lower & LEGACY_STACK
        if len(modern_hits) >= 5:
            stack_pts = 20
        elif len(modern_hits) >= 3:
            stack_pts = 15
        elif len(modern_hits) >= 1:
            stack_pts = 8

        if legacy_hits:
            legacy_penalty = -15 if len(legacy_hits) >= 2 else -8
            stack_pts += legacy_penalty
            signals.append(f"Legacy stack skills ({', '.join(sorted(legacy_hits))}) → {legacy_penalty} pts")

        if modern_hits:
            top_modern = sorted(modern_hits)[:5]
            signals.append(f"Modern stack skills ({', '.join(top_modern)}) → +{max(stack_pts, 0)} pts")

    # --- Techstack key facts ---
    infra_pts = 0
    monitoring_pts = 0
    if techstack_kf:
        infra = (techstack_kf.get("infrastructure_provider") or "").lower()
        if any(m in infra for m in MODERN_INFRA):
            infra_pts = 5
            signals.append(f"Modern infra ({infra}) → +5 pts")

        monitoring = techstack_kf.get("monitoring_tools", [])
        if monitoring:
            monitoring_lower = {m.lower() for m in monitoring}
            if monitoring_lower & MODERN_MONITORING:
                monitoring_pts = 5
                signals.append(f"Monitoring tools ({', '.join(sorted(monitoring_lower & MODERN_MONITORING))}) → +5 pts")
    else:
        missing.append("techstack")

    # --- Combine (additive from base 30, no floor) ---
    raw = sector_pts + eng_pts + stack_pts + infra_pts + monitoring_pts
    final = _clamp(30 + raw)

    # Confidence: how many signal sources were present
    sources_present = sum([
        hiring_stats is not None,
        bool(techstack_kf),
        hiring_stats is not None and bool(hiring_stats.get("top_skills")),
    ])
    confidence = round(sources_present / 3, 2)

    return {
        "algorithmic_score": final,
        "confidence": confidence,
        "signals_used": signals if signals else ["No signals available — defaulting to 30"],
        "missing_analyses": sorted(set(missing)),
    }


def _score_data_analytics(hiring_stats, techstack_kf, profile_kf, hiring_kf):
    """Score Data & Analytics (0-100).

    Sector bonus for data-product companies; no floor override.
    """
    signals = []
    missing = []

    sector = _sector_text(profile_kf, hiring_kf)
    sector_pts = 0
    if _matches_any(sector, DATA_PRODUCT_KEYWORDS):
        sector_pts = 20
        signals.append(f"Data-product sector '{sector}' → +20 pts")

    # --- Data role hiring ---
    data_hiring_pts = 0
    tag_bonus = 0
    if hiring_stats:
        subcat_counts = hiring_stats.get("subcategory_counts", {})
        total = hiring_stats.get("total_roles", 0)

        data_role_count = sum(subcat_counts.get(s, 0) for s in DATA_SUBCATEGORIES)
        if total > 0 and data_role_count > 0:
            data_pct = data_role_count * 100 / total
            if data_pct >= 15:
                data_hiring_pts = 40
            elif data_pct >= 8:
                data_hiring_pts = 30
            elif data_pct >= 3:
                data_hiring_pts = 20
            else:
                data_hiring_pts = 10
            signals.append(
                f"Data roles: {data_role_count} ({data_pct:.0f}% of total) → +{data_hiring_pts} pts"
            )
        elif total > 0:
            signals.append("No data-specific roles in hiring → +0 pts")

        # Strategic tag
        stag_counts = hiring_stats.get("strategic_tag_counts", {})
        if stag_counts.get("Data Infrastructure", 0) > 0:
            tag_bonus = 15
            signals.append(f"'Data Infrastructure' strategic tag → +15 pts")
    else:
        missing.append("hiring")

    # --- Analytics tooling from techstack ---
    tooling_pts = 0
    if techstack_kf:
        analytics = {t.lower() for t in (techstack_kf.get("analytics_tools") or [])}
        ab_tools = {t.lower() for t in (techstack_kf.get("ab_testing_tools") or [])}

        has_advanced = bool(analytics & ADVANCED_ANALYTICS_TOOLS)
        has_ab = bool(ab_tools & AB_TESTING_TOOLS) or bool(ab_tools)  # any AB tool counts

        if has_advanced and has_ab:
            tooling_pts = 20
            signals.append(f"Advanced analytics + A/B testing tools → +20 pts")
        elif has_advanced:
            tooling_pts = 12
            signals.append(f"Advanced analytics tools ({', '.join(sorted(analytics & ADVANCED_ANALYTICS_TOOLS))}) → +12 pts")
        elif has_ab:
            tooling_pts = 8
            signals.append(f"A/B testing tools → +8 pts")
    else:
        missing.append("techstack")

    # --- Combine (additive from base 15, no floor) ---
    raw = sector_pts + data_hiring_pts + tag_bonus + tooling_pts
    final = _clamp(15 + raw)

    sources_present = sum([
        hiring_stats is not None,
        bool(techstack_kf),
        hiring_stats is not None and bool(hiring_stats.get("subcategory_counts")),
    ])
    confidence = round(sources_present / 3, 2)

    return {
        "algorithmic_score": final,
        "confidence": confidence,
        "signals_used": signals if signals else ["No signals available — defaulting to 15"],
        "missing_analyses": sorted(set(missing)),
    }


def _score_ai_readiness(hiring_stats, patents_kf, profile_kf, hiring_kf):
    """Score AI Readiness (0-100).

    Sector bonus for AI-native companies; no floor override.
    """
    signals = []
    missing = []

    sector = _sector_text(profile_kf, hiring_kf)
    sector_pts = 0
    if _matches_any(sector, AI_NATIVE_KEYWORDS):
        sector_pts = 30
        signals.append(f"AI-native sector '{sector}' → +30 pts")

    # --- AI/ML hiring ---
    ai_hiring_pts = 0
    if hiring_stats:
        ai_ml_count = hiring_stats.get("ai_ml_role_count", 0)
        dept_counts = hiring_stats.get("dept_counts", {})
        eng_count = dept_counts.get("Engineering", 0)
        total = hiring_stats.get("total_roles", 0)

        # Use eng count as denominator if available, else total
        denominator = eng_count if eng_count > 0 else total
        ai_of_eng_pct = (ai_ml_count * 100 / denominator) if denominator > 0 else 0

        if ai_of_eng_pct >= 20 or ai_ml_count >= 50:
            ai_hiring_pts = 55
        elif ai_of_eng_pct >= 10 or ai_ml_count >= 20:
            ai_hiring_pts = 45
        elif ai_of_eng_pct >= 5 or ai_ml_count >= 8:
            ai_hiring_pts = 30
        elif ai_of_eng_pct >= 2 or ai_ml_count >= 3:
            ai_hiring_pts = 15
        elif ai_ml_count >= 1:
            ai_hiring_pts = 8

        if ai_ml_count > 0:
            signals.append(
                f"AI/ML roles: {ai_ml_count} ({ai_of_eng_pct:.0f}% of eng) → +{ai_hiring_pts} pts"
            )
        else:
            signals.append("No AI/ML roles in hiring → +0 pts")

        # Strategic tag bonus
        stag_counts = hiring_stats.get("strategic_tag_counts", {})
        if stag_counts.get("AI/ML Investment", 0) > 0:
            bonus = min(10, 55 - ai_hiring_pts)  # cap total at 55
            if bonus > 0:
                ai_hiring_pts += bonus
                signals.append(f"'AI/ML Investment' strategic tag → +{bonus} pts")
    else:
        missing.append("hiring")

    # --- Patent signal ---
    patent_pts = 0
    if patents_kf:
        ai_ml_patents = patents_kf.get("ai_ml_patents")
        patent_trend = patents_kf.get("patent_trend", "")

        if isinstance(ai_ml_patents, (int, float)) and ai_ml_patents > 0:
            if ai_ml_patents >= 20:
                patent_pts = 20
            elif ai_ml_patents >= 5:
                patent_pts = 15
            elif ai_ml_patents >= 1:
                patent_pts = 10
            signals.append(f"AI/ML patents: {ai_ml_patents} → +{patent_pts} pts")

            if patent_trend == "accelerating" and patent_pts > 0:
                patent_pts = min(patent_pts + 5, 20)
                signals.append(f"Accelerating patent trend → +5 pts (capped at 20)")
        elif ai_ml_patents == 0:
            signals.append("No AI/ML patents → +0 pts")
    else:
        missing.append("patents")

    # --- Combine (additive from base 10, no floor) ---
    raw = sector_pts + ai_hiring_pts + patent_pts
    final = _clamp(10 + raw)

    sources_present = sum([
        hiring_stats is not None,
        bool(patents_kf),
        hiring_stats is not None and hiring_stats.get("ai_ml_role_count", 0) > 0,
    ])
    confidence = round(sources_present / 3, 2)

    return {
        "algorithmic_score": final,
        "confidence": confidence,
        "signals_used": signals if signals else ["No signals available — defaulting to 10"],
        "missing_analyses": sorted(set(missing)),
    }


def _score_org_readiness(hiring_stats, hiring_kf, sentiment_kf, exec_kf=None):
    """Score Organizational Readiness (0-100)."""
    signals = []
    missing = []
    exec_kf = exec_kf or {}

    # --- Hiring trend ---
    trend_map = {"growing": 25, "stable": 15, "shrinking": 0}
    hiring_trend = (hiring_kf.get("hiring_trend") or "").lower()
    trend_pts = trend_map.get(hiring_trend, 10)
    if hiring_trend in trend_map:
        signals.append(f"Hiring trend '{hiring_trend}' → +{trend_pts} pts")
    elif hiring_kf:
        signals.append(f"Hiring trend unknown → +10 pts (default)")
    else:
        missing.append("hiring")

    # --- Growth signal ratio ---
    growth_pts = 0
    if hiring_stats:
        growth_ratio = hiring_stats.get("growth_signal_ratio", "")
        raw_pct = _parse_pct(growth_ratio)
        if raw_pct is not None:
            if raw_pct >= 60:
                growth_pts = 20
            elif raw_pct >= 40:
                growth_pts = 12
            elif raw_pct >= 20:
                growth_pts = 6
            signals.append(f"Growth signal {raw_pct:.0f}% new roles → +{growth_pts} pts")
    else:
        missing.append("hiring")

    # --- Strategic investment tags ---
    tag_pts = 0
    if hiring_stats:
        stag_counts = hiring_stats.get("strategic_tag_counts", {})
        investment_count = sum(1 for tag in INVESTMENT_TAGS if stag_counts.get(tag, 0) > 0)
        if investment_count >= 4:
            tag_pts = 20
        elif investment_count >= 2:
            tag_pts = 12
        elif investment_count >= 1:
            tag_pts = 6
        if investment_count > 0:
            present_tags = [t for t in INVESTMENT_TAGS if stag_counts.get(t, 0) > 0]
            signals.append(
                f"Investment tags ({investment_count}): {', '.join(sorted(present_tags))} → +{tag_pts} pts"
            )

    # --- Sentiment ---
    sentiment_pts = 0
    if sentiment_kf:
        overall = (sentiment_kf.get("overall_sentiment") or "").lower()
        sentiment_pts = {"positive": 20, "mixed": 10, "negative": -5}.get(overall, 0)

        # Glassdoor override
        glassdoor = sentiment_kf.get("glassdoor_rating")
        if isinstance(glassdoor, (int, float)):
            if glassdoor >= 4.3:
                sentiment_pts = max(sentiment_pts, 20)
            elif glassdoor >= 3.8:
                sentiment_pts = max(sentiment_pts, 12)
            elif glassdoor >= 3.0:
                sentiment_pts = max(sentiment_pts, 5)
            else:
                sentiment_pts = min(sentiment_pts, -5)
            signals.append(f"Glassdoor {glassdoor} + sentiment '{overall}' → {'+' if sentiment_pts >= 0 else ''}{sentiment_pts} pts")
        elif overall:
            signals.append(f"Sentiment '{overall}' → {'+' if sentiment_pts >= 0 else ''}{sentiment_pts} pts")
    else:
        missing.append("sentiment")

    # --- Executive signals ---
    exec_pts = 0
    if exec_kf:
        commitment = (exec_kf.get("organizational_commitment") or "").lower()
        commitment_pts = {"strong": 15, "moderate": 8, "weak": -5, "unclear": 0}.get(commitment, 0)
        domains = exec_kf.get("leadership_investment_domains") or []
        domain_pts = min(len(domains) * 3, 10)
        exec_pts = commitment_pts + domain_pts
        signals.append(f"Executive commitment '{commitment}' + {len(domains)} leadership domains → {'+' if exec_pts >= 0 else ''}{exec_pts} pts")
    else:
        missing.append("executive_signals")

    # --- Combine ---
    raw = trend_pts + growth_pts + tag_pts + sentiment_pts + exec_pts
    final = _clamp(15 + raw)

    sources_present = sum([
        hiring_stats is not None,
        bool(hiring_kf),
        bool(sentiment_kf),
        bool(exec_kf),
    ])
    confidence = round(sources_present / 4, 2)

    return {
        "algorithmic_score": final,
        "confidence": confidence,
        "signals_used": signals if signals else ["No signals available — defaulting to 15"],
        "missing_analyses": sorted(set(missing)),
    }


# ---------------------------------------------------------------------------
# Anomaly detection — structural signals that indicate consulting needs
# regardless of Digital Maturity Score
# ---------------------------------------------------------------------------

SENIOR_SENIORITIES = frozenset({"Director", "VP", "C-Suite"})


def compute_anomaly_signals(hiring_stats, all_key_facts):
    """Detect structural anomalies that may indicate consulting opportunities.

    These are independent of the DMS — a company scoring 95 can still have
    anomalies that represent real engagement hooks (org design, change mgmt, etc.).

    Returns list of dicts: {type, severity, signal, consulting_angle}
    """
    anomalies = []
    hiring_kf = all_key_facts.get("hiring", {})
    sentiment_kf = all_key_facts.get("sentiment", {})

    if not hiring_stats:
        return anomalies

    dept_counts = hiring_stats.get("dept_counts", {})
    total = hiring_stats.get("total_roles", 0)
    seniority_counts = hiring_stats.get("seniority_counts", {})
    stag_counts = hiring_stats.get("strategic_tag_counts", {})

    # --- 1. Engineering-heavy org (>60%) ---
    eng_count = dept_counts.get("Engineering", 0)
    if total >= 10:
        eng_pct = eng_count * 100 / total
        if eng_pct >= 60:
            anomalies.append({
                "type": "engineering_heavy",
                "severity": "notable",
                "signal": (
                    f"Engineering is {eng_pct:.0f}% of all open roles ({eng_count}/{total}). "
                    f"Company may be underinvesting in go-to-market, operations, or people functions."
                ),
                "consulting_angle": "Org design, GTM strategy, operational scaling",
            })

    # --- 2. Top-heavy seniority (Director+ >= 15% of hiring) ---
    if total >= 20:
        senior_count = sum(seniority_counts.get(s, 0) for s in SENIOR_SENIORITIES)
        senior_pct = senior_count * 100 / total
        if senior_pct >= 15:
            anomalies.append({
                "type": "top_heavy_seniority",
                "severity": "notable",
                "signal": (
                    f"Director+ roles are {senior_pct:.0f}% of hiring ({senior_count}/{total}). "
                    f"May indicate leadership restructuring, exec churn, or rapid management build-out."
                ),
                "consulting_angle": "Leadership advisory, org restructuring, executive coaching",
            })

    # --- 3. Entry-heavy with few senior (inverse top-heavy — scaling without leaders) ---
    if total >= 30:
        entry_count = seniority_counts.get("Entry", 0)
        senior_plus = sum(seniority_counts.get(s, 0) for s in SENIOR_SENIORITIES)
        entry_pct = entry_count * 100 / total
        senior_plus_pct = senior_plus * 100 / total
        if entry_pct >= 40 and senior_plus_pct < 5:
            anomalies.append({
                "type": "scaling_without_leaders",
                "severity": "notable",
                "signal": (
                    f"Entry-level is {entry_pct:.0f}% of hiring but Director+ is only "
                    f"{senior_plus_pct:.0f}%. Rapid headcount growth without proportional "
                    f"leadership investment."
                ),
                "consulting_angle": "Management training, leadership pipeline, org design for scale",
            })

    # --- 4. Low growth signal ratio → replacement churn ---
    growth_ratio_pct = _parse_pct(hiring_stats.get("growth_signal_ratio", ""))
    if growth_ratio_pct is not None and growth_ratio_pct < 20 and total >= 30:
        anomalies.append({
            "type": "replacement_churn",
            "severity": "warning",
            "signal": (
                f"Only {growth_ratio_pct:.0f}% of {total} open roles are net-new (growth). "
                f"Most hiring appears to be backfill/replacement, suggesting retention issues."
            ),
            "consulting_angle": "Retention strategy, employer brand, compensation benchmarking, exit interview analysis",
        })

    # --- 5. Single department surge (any dept >40% of hiring, excluding engineering) ---
    for dept, count in dept_counts.items():
        if dept == "Engineering":
            continue
        if total >= 15 and count >= 10:
            dept_pct = count * 100 / total
            if dept_pct >= 40:
                anomalies.append({
                    "type": "dept_surge",
                    "severity": "notable",
                    "signal": (
                        f"{dept} is {dept_pct:.0f}% of all hiring ({count}/{total}). "
                        f"Major build-out in a single function."
                    ),
                    "consulting_angle": f"Scaling support for {dept}, process design, talent strategy",
                })

    # --- 6. AI/ML hiring without data foundation ---
    ai_ml_count = hiring_stats.get("ai_ml_role_count", 0)
    if ai_ml_count >= 5:
        subcat_counts = hiring_stats.get("subcategory_counts", {})
        data_roles = sum(subcat_counts.get(s, 0) for s in DATA_SUBCATEGORIES)
        has_data_tag = stag_counts.get("Data Infrastructure", 0) > 0
        if data_roles < 3 and not has_data_tag:
            anomalies.append({
                "type": "ai_without_data_foundation",
                "severity": "warning",
                "signal": (
                    f"Hiring {ai_ml_count} AI/ML roles but only {data_roles} data roles "
                    f"and no 'Data Infrastructure' tag. May be building AI capability "
                    f"without adequate data foundation."
                ),
                "consulting_angle": "Data strategy, data platform modernization, MLOps, data governance",
            })

    # --- 7. Fast growth + negative sentiment → change management ---
    hiring_trend = (hiring_kf.get("hiring_trend") or "").lower()
    if sentiment_kf:
        overall_sentiment = (sentiment_kf.get("overall_sentiment") or "").lower()
        if hiring_trend == "growing" and overall_sentiment == "negative":
            anomalies.append({
                "type": "growth_sentiment_gap",
                "severity": "warning",
                "signal": (
                    "Rapid hiring growth combined with negative employee sentiment. "
                    "Classic signs of scaling pain — culture dilution, process gaps, or burnout."
                ),
                "consulting_angle": "Change management, culture integration, org design for hypergrowth",
            })

        # Low Glassdoor regardless of other signals
        glassdoor = sentiment_kf.get("glassdoor_rating")
        if isinstance(glassdoor, (int, float)) and glassdoor < 3.0:
            anomalies.append({
                "type": "low_glassdoor",
                "severity": "warning",
                "signal": (
                    f"Glassdoor rating {glassdoor}/5 signals significant employee dissatisfaction."
                ),
                "consulting_angle": "Employee experience transformation, leadership coaching, workplace strategy",
            })

    # --- 8. Many strategic tags but no clear focus (>5 different tags active) ---
    active_tags = [t for t, c in stag_counts.items() if c > 0]
    if len(active_tags) >= 6:
        anomalies.append({
            "type": "strategic_sprawl",
            "severity": "notable",
            "signal": (
                f"{len(active_tags)} different strategic investment tags detected: "
                f"{', '.join(sorted(active_tags)[:6])}. Company may be spreading investment "
                f"across too many fronts."
            ),
            "consulting_angle": "Strategic prioritization, portfolio rationalization, program management",
        })

    return anomalies


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_dms_scores(hiring_stats, all_key_facts):
    """Compute algorithmic Digital Maturity base scores from structured data.

    Args:
        hiring_stats: dict from compute_hiring_stats() or None
        all_key_facts: dict of {analysis_type: {field: value}} from dossier

    Returns:
        dict with per-dimension scores, weighted overall, and confidence.
    """
    hiring_kf = all_key_facts.get("hiring", {})
    techstack_kf = all_key_facts.get("techstack", {})
    patents_kf = all_key_facts.get("patents", {})
    sentiment_kf = all_key_facts.get("sentiment", {})
    profile_kf = all_key_facts.get("profile", {})

    tech = _score_tech_modernity(hiring_stats, techstack_kf, profile_kf, hiring_kf)
    data = _score_data_analytics(hiring_stats, techstack_kf, profile_kf, hiring_kf)
    ai = _score_ai_readiness(hiring_stats, patents_kf, profile_kf, hiring_kf)
    exec_kf = all_key_facts.get("executive_signals", {})
    org = _score_org_readiness(hiring_stats, hiring_kf, sentiment_kf, exec_kf)

    # Weighted overall
    weighted = round(
        tech["algorithmic_score"] * 0.30
        + data["algorithmic_score"] * 0.25
        + ai["algorithmic_score"] * 0.25
        + org["algorithmic_score"] * 0.20
    )

    overall_confidence = round(
        (tech["confidence"] + data["confidence"] + ai["confidence"] + org["confidence"]) / 4,
        2,
    )

    return {
        "tech_modernity": tech,
        "data_analytics": data,
        "ai_readiness": ai,
        "org_readiness": org,
        "weighted_algorithmic_score": weighted,
        "overall_confidence": overall_confidence,
    }
