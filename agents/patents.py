"""Agent: Patent/IP Analysis — search USPTO patents and analyze innovation strategy."""

import os
from datetime import datetime
from pathlib import Path

import httpx
import google.generativeai as genai

from scraper.patents import search_patents, format_patents_for_prompt
from scraper.web_search import search_web, format_search_results
from prompts.patents import build_patent_prompt, build_patent_prompt_fallback

PROVIDERS = [
    {"name": "groq", "env_key": "GROQ_API_KEY", "url": "https://api.groq.com/openai/v1/chat/completions", "model": "llama-3.3-70b-versatile"},
    {"name": "mistral", "env_key": "MISTRAL_API_KEY", "url": "https://api.mistral.ai/v1/chat/completions", "model": "mistral-small-latest"},
    {"name": "gemini", "env_key": "GEMINI_API_KEYS", "url": None, "model": "gemini-2.5-flash-lite"},
]


def _generate_text(prompt):
    """Try providers in order until one works. Returns (text, model_name)."""
    http = httpx.Client(timeout=60, follow_redirects=True)
    for p in PROVIDERS:
        key = os.environ.get(p["env_key"], "").strip()
        if not key:
            continue
        if "," in key:
            key = key.split(",")[0].strip()

        try:
            if p["name"] == "gemini":
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
    raise RuntimeError("All providers failed for patent report generation")


def patent_analysis(company):
    """Analyze a company's patent portfolio. Returns report path or None."""
    print(f"\n[patents] Analyzing patent portfolio for {company}...")

    # Search PatentsView
    patents, total_count = search_patents(company)

    if patents:
        patents_text = format_patents_for_prompt(patents, total_count)
        prompt = build_patent_prompt(company, patents_text, total_count)
    else:
        # Fallback to web search
        print(f"[patents] No patents found in PatentsView — trying web search")
        results = search_web(f"{company} patents innovation R&D", max_results=5)
        if not results:
            print("[patents] No patent information found")
            return None
        search_text = format_search_results(results)
        prompt = build_patent_prompt_fallback(company, search_text)
        total_count = 0

    # Generate report
    print("[patents] Generating report...")
    text, model = _generate_text(prompt)

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company.lower().replace(" ", "_").replace(".", "_")

    header = f"""# Patent/IP Analysis: {company}

**Total US Patents:** {total_count} | **Date:** {today}
**Source:** {"USPTO PatentsView" if patents else "Web Search"} | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = reports_dir / f"{safe_name}_patents_{today}.md"
    filename.write_text(report, encoding="utf-8")

    print(f"[patents] Report saved to {filename}")
    return str(filename)
