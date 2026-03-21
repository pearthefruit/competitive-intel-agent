"""Agent: Employee Sentiment — analyze workplace culture and employer reputation via web search."""

import os
from datetime import datetime
from pathlib import Path

import httpx
import google.generativeai as genai

from scraper.web_search import search_web, search_news, format_search_results
from prompts.sentiment import build_sentiment_prompt

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
    raise RuntimeError("All providers failed for sentiment report generation")


def sentiment_analysis(company):
    """Analyze employee sentiment for a company. Returns report path or None."""
    print(f"\n[sentiment] Analyzing employee sentiment for {company}...")

    # Multiple targeted searches
    queries = [
        f"{company} glassdoor reviews",
        f"{company} employee reviews workplace",
        f"{company} workplace culture",
        f"{company} best place to work",
    ]

    all_results = []
    for query in queries:
        results = search_web(query, max_results=3)
        all_results.extend(results)

    # News about workplace/culture
    news = search_news(f"{company} employees workplace culture", max_results=3)
    all_results.extend(news)

    if not all_results:
        print("[sentiment] No search results found")
        return None

    # Deduplicate
    seen = set()
    unique = []
    for r in all_results:
        title = r.get("title", "")
        if title not in seen:
            seen.add(title)
            unique.append(r)

    search_text = format_search_results(unique)

    # Generate report
    prompt = build_sentiment_prompt(company, search_text)

    print("[sentiment] Generating report...")
    text, model = _generate_text(prompt)

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_name = company.lower().replace(" ", "_").replace(".", "_")

    header = f"""# Employee Sentiment Analysis: {company}

**Date:** {today}
**Source:** Web Search | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = reports_dir / f"{safe_name}_sentiment_{today}.md"
    filename.write_text(report, encoding="utf-8")

    print(f"[sentiment] Report saved to {filename}")
    return str(filename)
