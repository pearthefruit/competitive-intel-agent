"""Agent: Tech Stack Detection — crawl a site and identify technologies."""

from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

from agents.llm import generate_text, save_to_dossier
from scraper.site_crawler import crawl_site
from scraper.tech_detect import detect_technologies, format_tech_for_prompt
from prompts.techstack import build_techstack_prompt


def techstack_analysis(url, max_pages=5, company_name=None):
    """Crawl a website and analyze its technology stack. Returns report path or None."""
    # Ensure URL has scheme
    if not url.startswith("http"):
        url = f"https://{url}"

    domain = urlparse(url).netloc
    print(f"\n[techstack] Analyzing tech stack for {domain}...")

    # Crawl the site
    pages = crawl_site(url, max_pages=max_pages)
    if not pages:
        print("[techstack] No pages crawled — site may block automated requests, require JS rendering, or be behind authentication")
        return None

    # Detect technologies
    tech = detect_technologies(pages)
    total_techs = sum(len(v) for v in tech.values())
    print(f"[techstack] Detected {total_techs} technologies across {len(tech)} categories")

    if total_techs == 0:
        print("[techstack] No technologies detected — possible reasons:")
        print("[techstack]   - Site may be heavily server-rendered with no client-side framework fingerprints")
        print("[techstack]   - Custom/proprietary stack with no recognizable signatures in HTML, headers, or scripts")
        print("[techstack]   - CDN or reverse proxy may be stripping identifying headers")
        print("[techstack] The LLM will still attempt analysis based on page structure and content clues")
    elif total_techs < 3:
        print(f"[techstack] Only {total_techs} technologies found — site may use an uncommon stack or aggressively minimize client-side code")
        print("[techstack] Check BuiltWith.com or Wappalyzer browser extension for deeper detection")

    # Format for prompt
    tech_summary = format_tech_for_prompt(tech, len(pages))

    # Generate report
    prompt = build_techstack_prompt(url, tech_summary, len(pages))

    print("[techstack] Generating report...")
    text, model = generate_text(prompt)

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
    dossier_name = company_name or domain
    save_to_dossier(dossier_name, "techstack", report_file=str(filename), report_text=report, model_used=model)
    return str(filename)
