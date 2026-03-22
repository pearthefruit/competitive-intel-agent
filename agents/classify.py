"""Agent 2: LLM Classification — hybrid heuristic + LLM with multi-provider rotation."""

import os
import json
import re
import time
import random

import httpx
import google.generativeai as genai

from agents.llm import gemini_lock
from db import (init_db, get_connection, get_company_id, get_unclassified_jobs,
                insert_classification, get_company_seniority_framework, set_company_seniority_framework,
                compute_hiring_stats, save_hiring_snapshot)
from prompts.classify import build_batch_classify_prompt, SENIORITY_FRAMEWORKS

BATCH_SIZE = 10
MAX_CLASSIFY_JOBS = 200  # Statistical sample cap — 200 jobs is representative for dept/seniority distributions


# ---------------------------------------------------------------------------
# Heuristic pre-classification (no LLM needed)
# ---------------------------------------------------------------------------

# Department detection: (regex pattern on title, category)
_DEPT_RULES = [
    # Executive first (before other matches)
    (r'\b(CEO|CTO|CFO|COO|CRO|CMO|CIO|CISO|CPO|Chief\s)', "Executive"),
    # Engineering
    (r'\b(Engineer|Developer|Architect|SRE|DevOps|Programmer|SWE)\b', "Engineering"),
    (r'\b(Software|Backend|Frontend|Full[\s-]?Stack|Platform|Infrastructure|iOS|Android|Mobile|QA|SDET|Embedded)\b', "Engineering"),
    # Data
    (r'\b(Data\s+(Engineer|Scientist|Analyst)|Machine Learning|ML\s|Deep Learning|NLP|Computer Vision|Analytics Engineer|BI\s|Business Intelligence)\b', "Data"),
    # Product
    (r'\b(Product\s+(Manager|Owner|Lead)|Program Manager|TPM|Technical Program)\b', "Product"),
    # Design
    (r'\b(Design(er)?|UX|UI|User Experience|User Interface|Creative Director)\b', "Design"),
    # Marketing
    (r'\b(Marketing|Growth|Brand|Content|SEO|SEM|Demand Gen|Communications|PR\b|Public Relations)\b', "Marketing"),
    # Sales
    (r'\b(Sales|Account Executive|AE\b|SDR|BDR|Business Development|Solutions Engineer|Pre[\s-]?Sales|Customer Success)\b', "Sales"),
    # HR
    (r'\b(Recruiter|Recruiting|Talent|Human Resources|HR\b|People\s+(Operations|Partner)|HRBP)\b', "HR"),
    # Finance
    (r'\b(Finance|Financial|Accountant|Accounting|Controller|Treasury|FP&A|Tax\b|Audit)\b', "Finance"),
    # Legal
    (r'\b(Legal|Counsel|Attorney|Lawyer|Compliance|Regulatory|Privacy)\b', "Legal"),
    # Operations
    (r'\b(Operations|Ops\b|Supply Chain|Logistics|Procurement|Facilities)\b', "Operations"),
]

# Seniority detection per framework: list of (pattern, level) checked in order
_SENIORITY_RULES = {
    "tech": [
        (r'\b(Intern|Co[\s-]?op)\b', "Entry"),
        (r'\b(Junior|Jr\.?|New Grad|Associate(?!\s+Director))\b', "Entry"),
        (r'\bI\b(?!\s*-)', "Entry"),  # "Engineer I" but not "AI"
        (r'\b(Chief|CTO|CFO|CEO|COO|CRO|CMO|CIO|CISO|CPO)\b', "C-Suite"),
        (r'\b(VP|Vice President|Head of)\b', "VP"),
        (r'\bDirector\b', "Director"),
        (r'\b(Staff|Principal)\b', "Staff"),
        (r'\b(Senior|Sr\.?|Lead)\b', "Senior"),
        (r'\b(II|III)\b', "Senior"),
    ],
    "banking": [
        (r'\bAnalyst\b(?!.*Senior)', "Entry"),
        (r'\bSenior Analyst\b', "Mid"),
        (r'\bAssociate\b(?!.*Senior|.*Director)', "Mid"),
        (r'\bSenior Associate\b', "Senior"),
        (r'\b(Chief|CEO|CFO|CRO|CIO|Partner)\b', "C-Suite"),
        (r'\b(Managing Director|MD)\b', "VP"),
        (r'\b(Group Head|Division Head|Global Head)\b', "VP"),
        (r'\b(SVP|Senior Vice President|Executive Director)\b', "Staff"),
        (r'\bDirector\b(?!.*Managing)', "Director"),
        (r'\b(VP|Vice President)\b', "Senior"),  # Banking VP = tech Senior
    ],
    "consulting": [
        (r'\b(Analyst|Junior)\b', "Entry"),
        (r'\b(Associate|Consultant)\b(?!.*Senior|.*Director)', "Entry"),
        (r'\b(Senior Associate|Senior Consultant)\b', "Mid"),
        (r'\b(Chief|CEO|Global Lead|Chairman)\b', "C-Suite"),
        (r'\b(Partner|Managing Partner|Equity Partner|Managing Director)\b', "VP"),
        (r'\b(Director|Principal|Of Counsel)\b', "Director"),
        (r'\b(Senior Manager|Associate Director|Counsel)\b', "Staff"),
        (r'\b(Manager|Engagement Manager)\b', "Senior"),
    ],
    "corporate": [
        (r'\b(Intern|Co[\s-]?op)\b', "Entry"),
        (r'\b(Associate|Coordinator|Specialist|Clerk)\b(?!.*Senior|.*Director)', "Entry"),
        (r'\b(Chief|CEO|CFO|COO|CTO|President)\b', "C-Suite"),
        (r'\b(VP|Vice President|SVP|EVP|Head of)\b', "VP"),
        (r'\b(Director|Senior Director|Group Director)\b', "Director"),
        (r'\b(Senior Manager|Associate Director)\b', "Staff"),
        (r'\b(Manager|Team Lead)\b', "Senior"),
        (r'\bSenior (Specialist|Analyst)\b', "Mid"),
    ],
}

# Growth signal keywords (searched in description)
_NEW_ROLE_KW = re.compile(
    r'\b(build(?:ing)?|launch(?:ing)?|greenfield|founding team|0[\s-]to[\s-]1|'
    r'new team|new product|new market|ground[\s-]?up|first hire|brand new|'
    r'establish(?:ing)?|stand[\s-]?up|create from scratch|net[\s-]?new)\b',
    re.IGNORECASE,
)
_BACKFILL_KW = re.compile(
    r'\b(established team|maintain(?:ing)?|scaling existing|existing (team|product|platform)|'
    r'mature (team|product|codebase)|ongoing|BAU|steady[\s-]?state)\b',
    re.IGNORECASE,
)


def _heuristic_seniority(title, framework="tech"):
    """Determine seniority from title using rule-based matching. Returns level or None."""
    rules = _SENIORITY_RULES.get(framework, _SENIORITY_RULES["tech"])
    for pattern, level in rules:
        if re.search(pattern, title, re.IGNORECASE):
            return level
    return None


def _heuristic_department(title, ats_department=""):
    """Determine department category from title and ATS department field."""
    # Check title first (more specific)
    for pattern, dept in _DEPT_RULES:
        if re.search(pattern, title, re.IGNORECASE):
            return dept
    # Fall back to ATS department field if available
    if ats_department:
        for pattern, dept in _DEPT_RULES:
            if re.search(pattern, ats_department, re.IGNORECASE):
                return dept
    return None


def _heuristic_growth_signal(description):
    """Determine growth signal from job description keywords."""
    if not description:
        return "unclear"
    desc_lower = description[:2000]  # Only check first 2K chars
    new_matches = len(_NEW_ROLE_KW.findall(desc_lower))
    backfill_matches = len(_BACKFILL_KW.findall(desc_lower))
    if new_matches > backfill_matches and new_matches >= 2:
        return "likely new role"
    elif backfill_matches > new_matches and backfill_matches >= 2:
        return "possible backfill"
    elif new_matches > 0 and backfill_matches == 0:
        return "likely new role"
    elif backfill_matches > 0 and new_matches == 0:
        return "possible backfill"
    return "unclear"


def heuristic_preclassify(job, framework="tech"):
    """Pre-classify seniority, department, and growth_signal without LLM.

    Returns dict with keys that were confidently classified.
    Missing keys mean the heuristic was uncertain — LLM should decide.
    """
    title = job["title"] or ""
    dept_hint = job["department"] or ""
    desc = job["description"] or ""

    result = {}

    seniority = _heuristic_seniority(title, framework)
    if seniority:
        result["seniority_level"] = seniority

    department = _heuristic_department(title, dept_hint)
    if department:
        result["department_category"] = department

    result["growth_signal"] = _heuristic_growth_signal(desc)

    return result

# Provider configs: (env_key, api_url, models, needs_auth_header)
PROVIDERS = [
    {
        "name": "gemini",
        "type": "gemini",
        "env_key": "GEMINI_API_KEYS",
        "models": ["gemini-2.5-flash-lite", "gemini-2.5-flash"],
    },
    {
        "name": "groq",
        "type": "openai",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "models": ["llama-3.3-70b-versatile", "compound-beta"],
    },
    {
        "name": "mistral",
        "type": "openai",
        "env_key": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "models": ["mistral-small-latest"],
    },
]


def _parse_json_response(text):
    """Extract JSON array from LLM response, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


def _normalize_classification(result):
    """Ensure new fields have valid defaults if the LLM omits them."""
    if not result.get("department_subcategory"):
        result["department_subcategory"] = "General"
    tags = result.get("strategic_tags")
    if not isinstance(tags, list):
        result["strategic_tags"] = []
    # Ensure strategic_signals is a string (new prompt returns a sentence, not a list)
    signals = result.get("strategic_signals")
    if isinstance(signals, list):
        result["strategic_signals"] = "; ".join(str(s) for s in signals)
    elif not isinstance(signals, str):
        result["strategic_signals"] = ""
    return result


class MultiProviderLLM:
    """Rotates across multiple LLM providers, falling through on rate limits."""

    def __init__(self):
        self.providers = []
        self.http = httpx.Client(timeout=30, follow_redirects=True)
        self._load_providers()
        self.current = 0

    def _load_providers(self):
        for p in PROVIDERS:
            if p["type"] == "gemini":
                keys_str = os.environ.get(p["env_key"], "")
                keys = [k.strip() for k in keys_str.split(",") if k.strip()]
                if keys:
                    for key in keys:
                        for model in p["models"]:
                            self.providers.append({
                                "name": f"gemini/{model}",
                                "type": "gemini",
                                "key": key,
                                "model": model,
                            })
            else:
                key = os.environ.get(p["env_key"], "").strip()
                if key:
                    for model in p["models"]:
                        self.providers.append({
                            "name": f"{p['name']}/{model}",
                            "type": "openai",
                            "key": key,
                            "url": p["url"],
                            "model": model,
                        })

        if not self.providers:
            raise RuntimeError("No LLM API keys found. Set at least one in .env")
        print(f"[classify] Loaded {len(self.providers)} provider slots across {len(set(p['name'].split('/')[0] for p in self.providers))} providers")

    def generate(self, prompt):
        """Try current provider, rotate on failure. Returns (text, model_name)."""
        start = self.current
        tried = 0

        while tried < len(self.providers):
            p = self.providers[self.current]
            self.current = (self.current + 1) % len(self.providers)
            tried += 1

            try:
                if p["type"] == "gemini":
                    text = self._call_gemini(p, prompt)
                else:
                    text = self._call_openai_compat(p, prompt)
                return text, p["name"]
            except Exception as e:
                err = str(e)
                if "429" in err or "rate" in err.lower() or "quota" in err.lower():
                    continue  # Try next provider
                raise  # Non-rate-limit error, propagate

        raise RuntimeError("All providers rate limited")

    def _call_gemini(self, p, prompt):
        with gemini_lock:
            genai.configure(api_key=p["key"])
            model = genai.GenerativeModel(p["model"])
            response = model.generate_content(prompt)
        return response.text

    def _call_openai_compat(self, p, prompt):
        headers = {
            "Authorization": f"Bearer {p['key']}",
            "Content-Type": "application/json",
        }
        body = {
            "model": p["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        resp = self.http.post(p["url"], json=body, headers=headers)
        if resp.status_code == 429:
            raise RuntimeError("429 rate limited")
        if resp.status_code != 200:
            raise RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def close(self):
        self.http.close()


def classify(company_name, db_path="intel.db", seniority_framework=None, custom_seniority_rules=None,
             max_jobs=None):
    """Classify unclassified jobs in batches, rotating across providers.

    Samples up to MAX_CLASSIFY_JOBS (200) by default to save API calls while
    maintaining statistically representative department/seniority distributions.

    seniority_framework: "tech", "banking", "consulting", "corporate" (auto-detected if None)
    custom_seniority_rules: user-defined rules string (overrides framework)
    max_jobs: override the sample cap (None = use MAX_CLASSIFY_JOBS default)
    Returns number of jobs classified.
    """
    init_db(db_path)
    conn = get_connection(db_path)

    company_id = get_company_id(conn, company_name)
    if not company_id:
        print(f"[error] Company '{company_name}' not found. Run collect first.")
        conn.close()
        return 0

    # Resolve seniority framework: explicit param > stored on company > default "tech"
    if seniority_framework and seniority_framework in SENIORITY_FRAMEWORKS:
        set_company_seniority_framework(conn, company_id, seniority_framework)
        print(f"[classify] Using {SENIORITY_FRAMEWORKS[seniority_framework]['name']} seniority framework")
    elif not seniority_framework:
        stored = get_company_seniority_framework(conn, company_id)
        if stored and stored in SENIORITY_FRAMEWORKS:
            seniority_framework = stored
            print(f"[classify] Using stored {SENIORITY_FRAMEWORKS[stored]['name']} seniority framework")
        else:
            seniority_framework = "tech"
            print(f"[classify] Using default Tech seniority framework")

    if custom_seniority_rules:
        print(f"[classify] Using custom seniority rules provided by user")

    jobs = get_unclassified_jobs(conn, company_id)
    if not jobs:
        print(f"[classify] No unclassified jobs for {company_name}")
        conn.close()
        return 0

    valid_jobs = [j for j in jobs if j["description"]]

    # Sample cap: avoid burning through rate limits on companies with 500+ jobs
    cap = max_jobs if max_jobs is not None else MAX_CLASSIFY_JOBS
    if len(valid_jobs) > cap:
        print(f"[classify] {len(valid_jobs)} unclassified jobs found — sampling {cap} for representative coverage")
        valid_jobs = random.sample(valid_jobs, cap)

    # --- Phase 1: Heuristic pre-classification (instant, no API calls) ---
    fw = seniority_framework or "tech"
    heuristic_cache = {}  # job_id -> {seniority_level, department_category, growth_signal}
    h_seniority_hits = 0
    h_dept_hits = 0

    for j in valid_jobs:
        h = heuristic_preclassify(j, framework=fw)
        heuristic_cache[j["id"]] = h
        if "seniority_level" in h:
            h_seniority_hits += 1
        if "department_category" in h:
            h_dept_hits += 1

    print(f"[classify] Heuristic pre-classification: seniority {h_seniority_hits}/{len(valid_jobs)}, "
          f"department {h_dept_hits}/{len(valid_jobs)}")

    # --- Phase 2: LLM classification for strategic fields ---
    llm = MultiProviderLLM()

    total_batches = (len(valid_jobs) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"[classify] Classifying {len(valid_jobs)} jobs in {total_batches} batches for {company_name}...")

    classified = 0
    errors = 0

    for batch_idx in range(0, len(valid_jobs), BATCH_SIZE):
        batch = valid_jobs[batch_idx:batch_idx + BATCH_SIZE]
        batch_num = batch_idx // BATCH_SIZE + 1

        batch_data = [{
            "id": j["id"],
            "title": j["title"] or "Untitled",
            "description": j["description"],
            "department": j["department"] or "",
        } for j in batch]

        prompt = build_batch_classify_prompt(batch_data, seniority_framework=seniority_framework,
                                                    custom_seniority_rules=custom_seniority_rules)

        try:
            text, model_name = llm.generate(prompt)
            results = _parse_json_response(text)

            if not isinstance(results, list):
                results = [results]

            results_by_id = {r.get("job_id"): r for r in results if r.get("job_id")}

            batch_classified = 0
            for job_data in batch_data:
                result = results_by_id.get(job_data["id"])
                if result:
                    result = _normalize_classification(result)

                    # Merge: heuristic values override LLM for structural fields
                    h = heuristic_cache.get(job_data["id"], {})
                    if h.get("seniority_level"):
                        result["seniority_level"] = h["seniority_level"]
                    if h.get("department_category"):
                        result["department_category"] = h["department_category"]
                    if h.get("growth_signal"):
                        result["growth_signal"] = h["growth_signal"]

                    insert_classification(conn, job_data["id"], result, model_name)
                    batch_classified += 1
                else:
                    errors += 1

            classified += batch_classified
            titles = [j["title"][:25] for j in batch_data]
            print(f"  [batch {batch_num}/{total_batches}] {batch_classified}/{len(batch_data)} via {model_name}: {', '.join(titles)}")

        except json.JSONDecodeError as e:
            print(f"  [batch {batch_num}/{total_batches}] JSON parse error: {e}")
            errors += len(batch_data)

        except RuntimeError as e:
            if "All providers rate limited" in str(e):
                print(f"  [batch {batch_num}/{total_batches}] All providers rate limited, waiting 60s...")
                time.sleep(60)
                # Retry this batch
                try:
                    text, model_name = llm.generate(prompt)
                    results = _parse_json_response(text)
                    if not isinstance(results, list):
                        results = [results]
                    results_by_id = {r.get("job_id"): r for r in results if r.get("job_id")}
                    for job_data in batch_data:
                        result = results_by_id.get(job_data["id"])
                        if result:
                            result = _normalize_classification(result)
                            insert_classification(conn, job_data["id"], result, model_name)
                            classified += 1
                        else:
                            errors += 1
                    print(f"  [batch {batch_num}/{total_batches}] Retry succeeded via {model_name}")
                except Exception as retry_e:
                    print(f"  [batch {batch_num}/{total_batches}] Retry failed: {retry_e}")
                    errors += len(batch_data)
            else:
                print(f"  [batch {batch_num}/{total_batches}] Error: {e}")
                errors += len(batch_data)

        except Exception as e:
            print(f"  [batch {batch_num}/{total_batches}] Error: {e}")
            errors += len(batch_data)

        # Brief delay between batches
        if batch_idx + BATCH_SIZE < len(valid_jobs):
            time.sleep(1)

    llm.close()

    # Save hiring snapshot after classification
    if classified > 0:
        stats = compute_hiring_stats(conn, company_id)
        if stats:
            save_hiring_snapshot(conn, company_id, stats)
            print(f"[classify] Saved hiring snapshot: {stats['total_roles']} total roles, "
                  f"{stats['ai_ml_role_count']} AI/ML")

    conn.close()
    print(f"[classify] Done: {classified} classified, {errors} errors")
    return classified
