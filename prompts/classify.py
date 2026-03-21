"""Classification prompt template for Agent 2."""

DEPARTMENT_CATEGORIES = [
    "Engineering", "Marketing", "Sales", "Operations", "Finance",
    "Legal", "HR", "Data", "Design", "Product", "Executive", "Other",
]

SENIORITY_LEVELS = [
    "Entry", "Mid", "Senior", "Staff", "Director", "VP", "C-Suite",
]

GROWTH_SIGNALS = ["likely new role", "unclear", "possible backfill"]


def build_batch_classify_prompt(jobs):
    """Build a prompt to classify multiple jobs at once.

    jobs: list of dicts with 'id', 'title', 'description', 'department' keys.
    Returns the prompt string.
    """
    job_blocks = []
    for j in jobs:
        desc = (j.get("description") or "")[:3000]  # Shorter per job in batch mode
        dept = j.get("department") or ""
        hint = f" (Department: {dept})" if dept else ""
        job_blocks.append(f"### JOB {j['id']}: {j['title']}{hint}\n{desc}")

    jobs_text = "\n\n---\n\n".join(job_blocks)

    return f"""You are a hiring analyst. Classify each job posting below.

{jobs_text}

Respond with ONLY a valid JSON array (no markdown, no explanation). One object per job, in the same order:
[
  {{
    "job_id": <the JOB id number>,
    "department_category": "<one of: {', '.join(DEPARTMENT_CATEGORIES)}>",
    "seniority_level": "<one of: {', '.join(SENIORITY_LEVELS)}>",
    "key_skills": ["<top 5-8 specific skills, tools, or technologies>"],
    "strategic_signals": ["<1-3 signals about company direction>"],
    "growth_signal": "<one of: {', '.join(GROWTH_SIGNALS)}>"
  }}
]

Rules:
- department_category must be from the provided list exactly
- seniority_level: intern/associate=Entry, no prefix=Mid, senior/lead=Senior, staff/principal=Staff, director=Director, VP/head of=VP, C-suite titles=C-Suite
- key_skills: specific technologies, tools, frameworks — not soft skills
- strategic_signals: what hiring for this role reveals about company direction
- growth_signal: "likely new role" if building/launching something new; "possible backfill" if replacing/maintaining; "unclear" otherwise
- Return exactly {len(jobs)} objects in the array, one per job"""
