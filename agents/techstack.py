"""Agent: Tech Stack Detection — crawl a site and identify technologies."""

import os
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

import httpx
import google.generativeai as genai

from scraper.site_crawler import crawl_site
from scraper.tech_detect import detect_technologies, format_tech_for_prompt
from prompts.techstack import build_techstack_prompt

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
    raise RuntimeError("All providers failed for tech stack report generation")


def techstack_analysis(url, max_pages=5):
    """Crawl a website and analyze its technology stack. Returns report path or None."""
    # Ensure URL has scheme
    if not url.startswith("http"):
        url = f"https://{url}"

    domain = urlparse(url).netloc
    print(f"\n[techstack] Analyzing tech stack for {domain}...")

    # Crawl the site
    pages = crawl_site(url, max_pages=max_pages)
    if not pages:
        print("[techstack] No pages crawled")
        return None

    # Detect technologies
    tech = detect_technologies(pages)
    total_techs = sum(len(v) for v in tech.values())
    print(f"[techstack] Detected {total_techs} technologies across {len(tech)} categories")

    if total_techs == 0:
        print("[techstack] No technologies detected — site may use custom/server-rendered stack")

    # Format for prompt
    tech_summary = format_tech_for_prompt(tech, len(pages))

    # Generate report
    prompt = build_techstack_prompt(url, tech_summary, len(pages))

    print("[techstack] Generating report...")
    text, model = _generate_text(prompt)

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")
    safe_domain = domain.replace(".", "_").replace("/", "_")

    header = f"""# Tech Stack Analysis: {domain}

**URL:** {url}
**Crawled:** {len(pages)} pages | **Date:** {today}
**Technologies Detected:** {total_techs} | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = reports_dir / f"{safe_domain}_techstack_{today}.md"
    filename.write_text(report, encoding="utf-8")

    print(f"[techstack] Report saved to {filename}")
    return str(filename)
