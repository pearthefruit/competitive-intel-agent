"""Agent 2: LLM Classification — multi-provider rotation with batch support."""

import os
import json
import time

import httpx
import google.generativeai as genai

from db import init_db, get_connection, get_company_id, get_unclassified_jobs, insert_classification
from prompts.classify import build_batch_classify_prompt

BATCH_SIZE = 5

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


def classify(company_name, db_path="intel.db"):
    """Classify all unclassified jobs in batches of 5, rotating across providers.

    Returns number of jobs classified.
    """
    init_db(db_path)
    conn = get_connection(db_path)

    company_id = get_company_id(conn, company_name)
    if not company_id:
        print(f"[error] Company '{company_name}' not found. Run collect first.")
        conn.close()
        return 0

    jobs = get_unclassified_jobs(conn, company_id)
    if not jobs:
        print(f"[classify] No unclassified jobs for {company_name}")
        conn.close()
        return 0

    llm = MultiProviderLLM()

    valid_jobs = [j for j in jobs if j["description"]]
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

        prompt = build_batch_classify_prompt(batch_data)

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
    conn.close()
    print(f"[classify] Done: {classified} classified, {errors} errors")
    return classified
