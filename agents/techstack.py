"""Agent: Tech Stack Detection — crawl a site and identify technologies.

Combines two data sources:
1. Website crawl — fingerprints frontend frameworks, analytics, CDNs, CMS, etc.
2. Hiring data (when available) — backend languages, databases, cloud platforms,
   DevOps tools, AI/ML frameworks extracted from classified job listings.
"""

import json
import re
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

from agents.llm import generate_text, save_to_dossier, get_temporal_context, unique_report_path
from scraper.site_crawler import crawl_site
from scraper.tech_detect import detect_technologies, format_tech_for_prompt
from prompts.techstack import build_techstack_prompt


# Regex for extracting technology mentions from raw job descriptions.
# Used as fallback when jobs are FAST-classified (empty key_skills).
_TECH_REGEX = re.compile(
    r'\b('
    # Languages
    r'Python|Java(?:Script)?|TypeScript|Go(?:lang)?|Rust|C\+\+|C#|\.NET|Ruby|PHP|Scala|Kotlin|Swift|Elixir|Clojure|R\b|'
    # Frontend
    r'React|Angular|Vue\.?js|Next\.?js|Svelte|Remix|Gatsby|Nuxt|Ember|'
    # Backend / runtime
    r'Node\.?js|Django|Flask|FastAPI|Spring(?:\s?Boot)?|Rails|Express|NestJS|Laravel|'
    # Cloud
    r'AWS|Amazon Web Services|Azure|GCP|Google Cloud|'
    # Containers / orchestration
    r'Kubernetes|Docker|Terraform|Ansible|Pulumi|Helm|ArgoCD|'
    # Databases
    r'PostgreSQL|Postgres|MySQL|MongoDB|Redis|Elasticsearch|DynamoDB|Cassandra|CockroachDB|'
    r'Snowflake|BigQuery|Redshift|ClickHouse|Neo4j|Pinecone|'
    # Data / ML
    r'Kafka|RabbitMQ|Spark|Airflow|dbt|Flink|Databricks|'
    r'TensorFlow|PyTorch|Scikit-learn|Hugging\s?Face|LangChain|OpenAI|'
    r'Pandas|NumPy|Jupyter|MLflow|SageMaker|Vertex AI|'
    # CI/CD
    r'Jenkins|GitHub Actions|CircleCI|GitLab CI|'
    # Monitoring / observability
    r'Datadog|Splunk|Grafana|Prometheus|New Relic|PagerDuty|Sentry|'
    # APIs / protocols
    r'GraphQL|gRPC|REST API|OpenAPI|'
    # Design / frontend tooling
    r'Figma|Storybook|Chromatic|Tailwind|'
    # Other
    r'Salesforce|Tableau|Power BI|Looker|Segment|Amplitude|Mixpanel'
    r')\b',
    re.IGNORECASE
)


def _extract_skills_from_descriptions(jobs, limit=50):
    """Regex-extract technology mentions from job descriptions.

    Used as fallback for FAST-classified jobs that have empty key_skills.
    Returns a Counter of {skill: count}.
    """
    skill_counts = Counter()
    for job in jobs[:limit]:
        desc = job.get("description") or ""
        if not desc:
            continue
        for match in _TECH_REGEX.findall(desc):
            skill_counts[match.strip()] += 1
    return skill_counts


def _build_hiring_tech_section(company_name, db_path):
    """Query hiring data and build a formatted text section for the LLM prompt.

    Returns (hiring_text, hiring_stats_dict) or (None, None) if no data.
    """
    try:
        from db import get_connection, get_company_id, compute_hiring_stats, get_all_classified_jobs

        conn = get_connection(db_path)
        company_id = get_company_id(conn, company_name)
        if not company_id:
            conn.close()
            return None, None

        hiring_stats = compute_hiring_stats(conn, company_id)
        if not hiring_stats:
            conn.close()
            return None, None

        classified_jobs = get_all_classified_jobs(conn, company_id)
        conn.close()

        if not classified_jobs or len(classified_jobs) < 10:
            if classified_jobs:
                print(f"[techstack] Only {len(classified_jobs)} classified jobs — too few for reliable hiring-derived tech signals, skipping")
            return None, None

        # --- Aggregate skills ---
        comprehensive_skills = hiring_stats.get("top_skills", [])

        # Check for FAST-classified jobs with empty key_skills
        fast_jobs = [j for j in classified_jobs
                     if not j.get("key_skills") or j.get("key_skills") == "[]"]

        regex_skills = None
        if fast_jobs and len(fast_jobs) > len(classified_jobs) * 0.5:
            regex_counts = _extract_skills_from_descriptions(fast_jobs)
            if regex_counts:
                regex_skills = [s for s, _ in regex_counts.most_common(25)]

        # --- Build formatted section ---
        lines = []
        lines.append(f"### Hiring Data Summary ({hiring_stats['total_roles']} open roles)")

        if comprehensive_skills:
            lines.append(f"\n**Top Technical Skills (from classified job listings):**")
            lines.append(", ".join(comprehensive_skills[:20]))

        if regex_skills:
            lines.append(f"\n**Additional Technologies (extracted from {len(fast_jobs)} job descriptions):**")
            lines.append(", ".join(regex_skills[:20]))

        # Strategic tags — tech-related only
        stags = hiring_stats.get("strategic_tag_counts", {})
        if stags:
            tech_keywords = ("tech", "ai", "ml", "data", "cloud", "infra",
                             "platform", "modernization", "engineering", "automation")
            tech_tags = {k: v for k, v in stags.items()
                         if any(t in k.lower() for t in tech_keywords)}
            if tech_tags:
                lines.append(f"\n**Technology-Related Strategic Tags:**")
                for tag, count in sorted(tech_tags.items(), key=lambda x: -x[1]):
                    lines.append(f"  - {tag} ({count} roles)")

        # Department breakdown — tech depts only
        dept = hiring_stats.get("dept_counts", {})
        tech_dept_keywords = ("engineering", "data", "it", "infrastructure",
                              "security", "devops", "platform", "research")
        tech_depts = {k: v for k, v in dept.items()
                      if any(t in k.lower() for t in tech_dept_keywords)}
        if tech_depts:
            lines.append(f"\n**Technical Department Distribution:**")
            for d, count in sorted(tech_depts.items(), key=lambda x: -x[1]):
                pct = round(count * 100 / hiring_stats["total_roles"])
                lines.append(f"  - {d}: {count} roles ({pct}%)")

        # Sample engineering JD snippets (3 jobs, 300 chars each)
        eng_dept_keywords = ("engineering", "data", "it", "infrastructure",
                             "security", "devops", "platform", "research")
        eng_jobs = [j for j in classified_jobs
                    if any(t in (j.get("department_category") or "").lower()
                           for t in eng_dept_keywords)]
        if eng_jobs:
            lines.append(f"\n**Sample Engineering Job Descriptions (technology context):**")
            for j in eng_jobs[:3]:
                title = j.get("title", "Unknown")
                desc = (j.get("description") or "")[:300].replace("\n", " ").strip()
                if desc:
                    lines.append(f"  - **{title}:** {desc}...")

        return "\n".join(lines), hiring_stats

    except Exception as e:
        print(f"[techstack] Warning: Could not load hiring data: {e}")
        return None, None


def techstack_analysis(url, max_pages=5, company_name=None, db_path=None):
    """Crawl a website and analyze its technology stack. Returns report path or None.

    When db_path and company_name are provided, the report is enriched with
    technology signals extracted from the company's classified job listings.
    """
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

    # Query hiring data if DB is available
    hiring_section = None
    hiring_stats = None
    if db_path and company_name:
        hiring_section, hiring_stats = _build_hiring_tech_section(company_name, db_path)
        if hiring_section:
            print(f"[techstack] Hiring data found: {hiring_stats['total_roles']} roles, "
                  f"{len(hiring_stats.get('top_skills', []))} skills identified")
        else:
            print(f"[techstack] No hiring data found for '{company_name}' — report will cover website stack only")

    # Generate report
    prompt = build_techstack_prompt(url, tech_summary, len(pages), hiring_section=hiring_section)
    prompt += get_temporal_context(company_name or domain, "techstack")

    print("[techstack] Generating report...")
    text, model = generate_text(prompt)

    # Save report
    today = datetime.now().strftime("%Y-%m-%d")

    if company_name:
        safe_prefix = company_name.lower().replace(" ", "_").replace(".", "_")
    else:
        base_domain = re.sub(r'^www\.', '', domain)
        base_domain = base_domain.split('.')[0]
        safe_prefix = base_domain.replace("-", "_").replace(".", "_")

    hiring_tag = f" | **Hiring Data:** {hiring_stats['total_roles']} roles" if hiring_stats else ""
    header = f"""# Tech Stack Analysis: {domain}

**URL:** {url}
**Crawled:** {len(pages)} pages | **Date:** {today}
**Technologies Detected:** {total_techs}{hiring_tag} | **Model:** {model}

---

"""
    report = header + text

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = unique_report_path(reports_dir, f"{safe_prefix}_techstack_{today}.md")
    filename.write_text(report, encoding="utf-8")

    print(f"[techstack] Report saved to {filename}")
    dossier_name = company_name or domain
    save_to_dossier(dossier_name, "techstack", report_file=str(filename), report_text=report, model_used=model)
    return str(filename)
