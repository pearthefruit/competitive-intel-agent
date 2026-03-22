"""Classification prompt template for Agent 2."""

DEPARTMENT_CATEGORIES = [
    "Engineering", "Marketing", "Sales", "Operations", "Finance",
    "Legal", "HR", "Data", "Design", "Product", "Executive", "Other",
]

DEPARTMENT_SUBCATEGORIES = {
    "Engineering": [
        "AI/ML", "Platform/Infrastructure", "Security", "Frontend/Web",
        "Backend/API", "Mobile", "DevOps/SRE", "QA/Testing", "General Engineering",
    ],
    "Data": [
        "Data Engineering", "Data Science", "Analytics", "ML Ops",
        "BI/Reporting", "General Data",
    ],
    "Product": [
        "Product Management", "Technical Product Management",
        "Product Operations", "General Product",
    ],
    "Marketing": [
        "Growth/Performance", "Brand/Creative", "Content",
        "Product Marketing", "General Marketing",
    ],
    "Sales": [
        "Account Executive", "Solutions/Pre-Sales", "SDR/BDR",
        "Sales Engineering", "Customer Success", "General Sales",
    ],
    "Design": [
        "UX/Product Design", "Visual/Brand Design", "UX Research", "General Design",
    ],
}

SENIORITY_LEVELS = [
    "Entry", "Mid", "Senior", "Staff", "Director", "VP", "C-Suite",
]

GROWTH_SIGNALS = ["likely new role", "unclear", "possible backfill"]

STRATEGIC_TAGS = [
    "AI/ML Investment", "Cloud/Infrastructure", "International Expansion",
    "New Product Line", "Compliance/Regulatory", "Cost Optimization",
    "Platform Migration", "Security Hardening", "Data Infrastructure",
    "Developer Experience", "Customer Experience", "M&A Integration",
    "Go-to-Market Expansion", "Automation", "Sustainability/ESG",
]

# --- Industry-specific seniority frameworks ---

SENIORITY_FRAMEWORKS = {
    "tech": {
        "name": "Tech / Startup",
        "rules": """seniority_level — check these signals in order:
1. Title contains "Intern", "Co-op" → Entry
2. Title contains "Junior", "Associate", "New Grad", "I" (as in "Engineer I") → Entry
3. Title contains "Staff", "Principal" → Staff
4. Title contains "Director" → Director
5. Title contains "VP", "Vice President", "Head of" → VP
6. Title contains "Chief", "CTO", "CFO", "CEO", "CRO", "CMO" → C-Suite
7. Title contains "Senior", "Sr.", "Lead", "II" or "III" → Senior
8. JD mentions "8+ years", "10+ years", or "lead a team" → Senior
9. JD mentions "5+ years" or "3-5 years" → likely Senior (use judgment)
10. JD mentions "0-2 years" or "1-3 years" → Mid
11. No clear signals → Mid (but this should be rare if you check title and JD carefully)
Do NOT default to Mid just because you're unsure. Check the title and JD thoroughly first.""",
    },
    "banking": {
        "name": "Banking / Finance",
        "rules": """seniority_level — BANKING title hierarchy (very different from tech):
In banking, "VP" is mid-career (NOT executive). "Associate" is mid-level (NOT entry). "Analyst" is entry.
1. Title contains "Analyst" (without "Senior") → Entry
2. Title contains "Senior Analyst" → Mid
3. Title contains "Associate" (without "Senior") → Mid (in banking, Associate ≈ tech Mid)
4. Title contains "Senior Associate" → Senior
5. Title contains "VP", "Vice President" → Senior (in banking, VP ≈ tech Senior, it is mid-career)
6. Title contains "SVP", "Senior Vice President", "Executive Director" → Staff
7. Title contains "Director" (without "Managing"), "First VP" → Director
8. Title contains "Managing Director", "MD" → VP (in banking, MD ≈ tech VP/exec)
9. Title contains "Group Head", "Division Head", "Global Head" → VP
10. Title contains "Chief", "CEO", "CFO", "CRO", "CIO", "Partner" (PE/VC) → C-Suite
11. JD mentions "2-4 years" → Entry/Mid; "5-8 years" → Senior; "10+ years" → Staff+
12. No clear signals → Mid
CRITICAL: Do not treat "VP" as executive-level at a bank. It is equivalent to "Senior" in tech.""",
    },
    "consulting": {
        "name": "Consulting / Professional Services / Law / Audit",
        "rules": """seniority_level — CONSULTING/PROFESSIONAL SERVICES title hierarchy:
In consulting, "Associate" is entry-level (NOT mid). "Manager" is senior. "Partner" is near the top.
1. Title contains "Analyst", "Junior" → Entry
2. Title contains "Associate", "Consultant" (without "Senior" prefix) → Entry (in consulting, Associate IS entry-level)
3. Title contains "Senior Associate", "Senior Consultant" → Mid
4. Title contains "Manager", "Engagement Manager" → Senior
5. Title contains "Senior Manager", "Associate Director", "Counsel" (law) → Staff
6. Title contains "Director", "Principal" (non-equity), "Of Counsel" → Director
7. Title contains "Partner", "Managing Partner", "Equity Partner", "Managing Director" → VP
8. Title contains "Senior Partner", "CEO", "Global Lead", "Chairman" → C-Suite
9. JD mentions "2-4 years" → Entry/Mid; "6-8 years" → Senior; "10+ years" → Staff+
10. No clear signals → Mid
CRITICAL: "Associate" at consulting/law/audit firms is ENTRY level, not mid-level.""",
    },
    "corporate": {
        "name": "Corporate / Retail / Manufacturing",
        "rules": """seniority_level — CORPORATE/RETAIL title hierarchy:
In corporate settings, "Manager" can be an individual contributor. VP is higher than Director.
1. Title contains "Intern", "Co-op" → Entry
2. Title contains "Associate", "Coordinator", "Specialist", "Clerk" (without "Senior") → Entry
3. Title contains "Senior Specialist", "Analyst", no seniority prefix → Mid
4. Title contains "Manager", "Team Lead" → Senior (note: "Manager" can still be IC at some companies)
5. Title contains "Senior Manager", "Associate Director" → Staff
6. Title contains "Director", "Senior Director", "Group Director" → Director
7. Title contains "VP", "Vice President", "SVP", "EVP", "Head of" → VP
8. Title contains "Chief", "CEO", "CFO", "COO", "CTO", "President" → C-Suite
9. JD mentions "3-5 years" → Mid; "7+ years" → Senior; "10+ years" → Staff+
10. No clear signals → Mid
NOTE: At companies like Walmart, "Manager" may be an individual contributor. Use JD context.""",
    },
}

FRAMEWORK_NAMES = {k: v["name"] for k, v in SENIORITY_FRAMEWORKS.items()}


import re

# Patterns that signal the start of EEO / legal boilerplate
_EEO_PATTERNS = re.compile(
    r'(?:'
    r'equal\s+(?:employment\s+)?opportunity|'
    r'EEO\s|'
    r'affirmative\s+action|'
    r'we\s+are\s+(?:an?\s+)?(?:equal|committed\s+to\s+(?:diversity|providing\s+equal))|'
    r'does\s+not\s+discriminate|'
    r'without\s+regard\s+to\s+race|'
    r'reasonable\s+accommodation|'
    r'E-Verify|'
    r'background\s+check\s+(?:is\s+)?required|'
    r'drug[\s-]?free\s+workplace|'
    r'this\s+(?:job\s+)?description\s+is\s+not\s+(?:designed|intended)\s+to'
    r')',
    re.IGNORECASE,
)


def _strip_eeo(text):
    """Strip EEO / legal boilerplate from end of job descriptions."""
    if not text:
        return text
    match = _EEO_PATTERNS.search(text)
    if match and match.start() > len(text) * 0.3:
        # Only strip if the boilerplate starts after the first 30% of the description
        return text[:match.start()].rstrip()
    return text


def _format_subcategories():
    """Build a readable subcategory reference for the prompt."""
    lines = []
    for dept, subcats in DEPARTMENT_SUBCATEGORIES.items():
        lines.append(f"  {dept}: {', '.join(subcats)}")
    lines.append("  All other departments: use \"General\"")
    return "\n".join(lines)


def build_batch_classify_prompt(jobs, seniority_framework="tech", custom_seniority_rules=None):
    """Build a prompt to classify multiple jobs at once.

    jobs: list of dicts with 'id', 'title', 'description', 'department' keys.
    seniority_framework: one of "tech", "banking", "consulting", "corporate"
    custom_seniority_rules: if provided, overrides the framework with user-defined rules
    Returns the prompt string.
    """
    job_blocks = []
    for j in jobs:
        desc = _strip_eeo((j.get("description") or ""))[:3000]
        dept = j.get("department") or ""
        hint = f" (Department: {dept})" if dept else ""
        job_blocks.append(f"### JOB {j['id']}: {j['title']}{hint}\n{desc}")

    jobs_text = "\n\n---\n\n".join(job_blocks)
    subcategory_ref = _format_subcategories()

    # Select seniority rules
    if custom_seniority_rules:
        seniority_rules = f"seniority_level — CUSTOM RULES (provided by user):\n{custom_seniority_rules}"
        framework_note = "Custom seniority framework"
    elif seniority_framework in SENIORITY_FRAMEWORKS:
        seniority_rules = SENIORITY_FRAMEWORKS[seniority_framework]["rules"]
        framework_note = f"Using {SENIORITY_FRAMEWORKS[seniority_framework]['name']} seniority framework"
    else:
        seniority_rules = SENIORITY_FRAMEWORKS["tech"]["rules"]
        framework_note = "Using Tech / Startup seniority framework (default)"

    return f"""You are a hiring analyst performing competitive intelligence classification. Classify each job posting below with precision.

{framework_note}

{jobs_text}

Respond with ONLY a valid JSON array (no markdown, no explanation). One object per job, in the same order:
[
  {{
    "job_id": <the JOB id number>,
    "department_category": "<one of: {', '.join(DEPARTMENT_CATEGORIES)}>",
    "department_subcategory": "<see subcategory list below>",
    "seniority_level": "<one of: {', '.join(SENIORITY_LEVELS)}>",
    "key_skills": ["<top 5-8 specific skills, tools, or technologies>"],
    "strategic_signals": "<1 sentence: what hiring for this role reveals about company direction>",
    "strategic_tags": ["<1-3 tags from the curated list below, only if clearly evidenced>"],
    "growth_signal": "<one of: {', '.join(GROWTH_SIGNALS)}>"
  }}
]

DEPARTMENT SUBCATEGORIES (pick the closest match):
{subcategory_ref}

STRATEGIC TAGS (pick 1-3 ONLY if clearly supported by the job description):
{', '.join(STRATEGIC_TAGS)}

RULES:

department_category: must be from the provided list exactly.
department_subcategory: pick the most specific match from the subcategory list above. This is where the strategic signal lives — "Engineering" alone is not useful; "AI/ML" vs "Security" vs "Platform/Infrastructure" tells a very different story.

{seniority_rules}

key_skills: specific technologies, tools, frameworks, methodologies. NOT soft skills like "communication" or "teamwork".

strategic_signals: one concise sentence about what this hire reveals about company direction.
strategic_tags: pick from the curated list ONLY. Do not invent new tags. Only tag if the JD clearly supports it (mentions AI/ML work, cloud migration, new product, regulatory needs, etc.).

growth_signal:
- "likely new role": JD mentions building, launching, greenfield, founding team, 0-to-1, new team, new product, or new market
- "possible backfill": JD mentions established team, maintaining, scaling existing systems, or is a standard recurring function
- "unclear": genuinely ambiguous — but try to make a call if the JD gives any hints

Return exactly {len(jobs)} objects in the array, one per job."""
