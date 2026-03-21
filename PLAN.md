# Competitive Intelligence Agent (CLI)

## What It Does
Takes a company name + ATS job board URL, scrapes all open roles, classifies each role with an LLM, and generates a strategic competitive intelligence report. Three agents chained in a pipeline.

## Stack
- Python CLI (click)
- SQLite (single file, auto-created)
- Gemini API (`os.environ.get("GEMINI_API_KEY")`)
- Output: Markdown report files

## Reusing JobDiscovery Scrapers

The existing JobDiscovery project lives at:
```
c:\Users\peary\OneDrive - The City University of New York\Web Scraping\JobDiscovery\
```

### What to import/adapt from JobDiscovery

| File | What we need |
|------|-------------|
| `scraper/ats_api.py` | `GreenhouseScraper`, `LeverScraper`, `AshbyScraper` — all have `.scrape(source, keywords, exclude_keywords)` returning `(matched, filtered_out)` tuples |
| `scraper/career_page.py` | `CareerPageScraper` — generic career page scraping with tiered extraction (JSON-LD → CSS → LLM) |
| `scraper/linkedin.py` | `LinkedInScraper` — guest API, no auth required |
| `scraper/dedup.py` | `DeduplicationManager` — URL normalization + dedup logic |
| `scraper/selectors.py` | `SelectorRegistry` — CSS selector defaults per ATS platform |
| `scraper/llm_extract.py` | `LLMExtractor` — multi-model fallback for HTML → structured data |

**Approach:** Copy the scraper files we need into this project's `scraper/` directory. Adapt them to work standalone (strip Flask/DB dependencies, simplify to return plain dicts). Don't try to import across projects — keep this self-contained.

### Job data structure (what scrapers return)
```python
{
    'url': 'https://...',
    'title': 'Senior PM',
    'company': 'Google',
    'location': 'Mountain View, CA',
    'salary': '$150k - $200k/year',
    'description': '...',
    '_extraction_method': 'json-ld|css|ats-api|serp-card',
    '_source_scraper': 'greenhouse|lever|ashby|linkedin|career_page',
}
```

## Database Schema (SQLite)

```sql
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT,
    ats_type TEXT,  -- greenhouse/lever/ashby/career_page/linkedin
    last_scraped TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    title TEXT,
    department TEXT,
    location TEXT,
    url TEXT UNIQUE,
    description TEXT,
    description_hash TEXT,      -- SHA256 of description, detect changes on re-scrape
    date_posted TEXT,
    scrape_status TEXT DEFAULT 'scraped',  -- scraped/failed/partial
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE,
    department_category TEXT,     -- Engineering, Marketing, Sales, Operations, Finance, Legal, HR, Data, Design, Product, Executive, Other
    seniority_level TEXT,         -- Entry, Mid, Senior, Staff, Director, VP, C-Suite
    key_skills TEXT,              -- JSON array of top 5-8 skills/tools
    strategic_signals TEXT,       -- JSON array: e.g. ["AI/ML investment", "international expansion"]
    growth_signal TEXT,           -- "likely new role" / "unclear" / "possible backfill"
    classified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    model_used TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
```

### Changes from original plan
- `is_likely_backfill BOOLEAN` → `growth_signal TEXT` — JDs rarely reveal backfill status; a softer three-value field is more honest
- Added `description_hash` on jobs — detect whether a JD changed on re-scrape without comparing full text
- Added `scrape_status` on jobs — track partial scrapes
- Added `UNIQUE` on `classifications.job_id` — one classification per job
- All tables use `CREATE TABLE IF NOT EXISTS` — idempotent setup

### Re-scrape strategy
- `INSERT OR IGNORE` for jobs by URL — skip duplicates by default
- Future: add `--refresh` flag that updates description + description_hash where hash changed

## Project Structure

```
competitive-intel-agent/
├── main.py                 # CLI entry point (click)
├── db.py                   # SQLite setup + helpers
├── agents/
│   ├── __init__.py
│   ├── collect.py          # Agent 1: scrape jobs
│   ├── classify.py         # Agent 2: LLM classification
│   └── analyze.py          # Agent 3: strategic report
├── scraper/                # Adapted from JobDiscovery
│   ├── __init__.py
│   ├── ats_api.py          # Greenhouse, Lever, Ashby
│   ├── career_page.py      # Generic career pages (phase 2)
│   ├── linkedin.py         # LinkedIn guest API (phase 2)
│   └── dedup.py            # URL normalization
├── prompts/
│   ├── classify.py         # Classification prompt template
│   └── analyze.py          # Report generation prompt template
├── reports/                # Generated reports (gitignored)
├── requirements.txt
└── .env.example
```

### Why modules instead of standalone scripts
- `main.py` owns all CLI logic — single entry point, cleaner UX
- Agent modules expose clean functions (`collect(company, url)`, `classify(company)`, `analyze(company)`) — easy to test and chain
- Avoids duplicating DB setup and arg parsing across three files

## Agent 1: collect.py (Data Collection)

```python
def collect(company_name: str, url: str, db_path: str = "intel.db") -> int:
    """Scrape all open roles from the given URL.
    Returns number of new jobs saved.
    """
```

### Behavior
- URL is **required** in v1 — no auto-detection of ATS type
- Detect ATS type from URL pattern (reuse JobDiscovery's `detect_scraper_type()` logic):
  - `boards.greenhouse.io` or `job-boards.greenhouse.io` → Greenhouse
  - `jobs.lever.co` → Lever
  - `jobs.ashbyhq.com` → Ashby
  - Everything else → generic career page (phase 2)
- Instantiate appropriate scraper, call `.scrape()`
- For each job returned:
  - Compute `description_hash = hashlib.sha256(description.encode()).hexdigest()`
  - `INSERT OR IGNORE` into jobs table
- **Rate limiting:** `time.sleep(0.5)` between individual job detail fetches (Greenhouse/Lever APIs return all jobs in one call so this mainly matters for career page scraping)
- Print progress: `"Scraped 47 new jobs from Stripe (23 skipped as duplicates)"`

### Phase 1 scrapers (v1)
- Greenhouse (JSON API — single call gets all jobs with descriptions)
- Lever (JSON API — single call gets all jobs)
- Ashby (JSON API — single call gets all jobs)

### Phase 2 scrapers (later)
- Generic career pages (requires adapting career_page.py — more complex, needs httpx)
- LinkedIn (useful but rate-limited, needs careful throttling)

## Agent 2: classify.py (LLM Classification)

```python
def classify(company_name: str, db_path: str = "intel.db") -> int:
    """Classify all unclassified jobs for the given company.
    Returns number of jobs classified.
    """
```

### Behavior
- Query: `SELECT * FROM jobs WHERE company_id = ? AND id NOT IN (SELECT job_id FROM classifications)`
- **One job per LLM call** — not batched. JDs are 2-5K tokens each; batching degrades quality and risks hitting context limits. Gemini 2.5 Pro is cheap enough that accuracy > cost savings.
- For each job, send description to Gemini with classification prompt
- Parse structured response → insert into classifications table
- **Error handling:** If Gemini call fails (rate limit, timeout), log the error and continue to next job. Don't crash.
- Print progress: `"Classified 47/47 jobs for Stripe"`

### Classification prompt (in prompts/classify.py)
Send the job title + description, ask Gemini to return JSON:
```json
{
    "department_category": "Engineering",
    "seniority_level": "Senior",
    "key_skills": ["Python", "Kubernetes", "AWS", "GraphQL", "PostgreSQL"],
    "strategic_signals": ["AI/ML investment", "Platform rebuild"],
    "growth_signal": "likely new role"
}
```

**Department categories** (fixed list): Engineering, Marketing, Sales, Operations, Finance, Legal, HR, Data, Design, Product, Executive, Other

**Seniority levels** (fixed list): Entry, Mid, Senior, Staff, Director, VP, C-Suite

**Growth signal values:** "likely new role" / "unclear" / "possible backfill"

## Agent 3: analyze.py (Strategic Report)

```python
def analyze(company_name: str, db_path: str = "intel.db") -> str:
    """Generate strategic report for the given company.
    Returns path to the generated markdown file.
    """
```

### Behavior
1. Query all classified jobs for the company
2. Compute aggregate stats in Python (not LLM):
   - Jobs by department (count + %)
   - Jobs by seniority level
   - Jobs by location (top 10)
   - Top skills/tools across all roles (frequency count)
   - Growth signal breakdown
3. Send aggregates + raw classification data to Gemini with analysis prompt
4. Gemini generates the strategic narrative sections
5. Assemble final report: metadata header + stats tables + narrative
6. Save to `reports/{company}_{date}.md`
7. Print report to terminal

### Report format
```markdown
# Competitive Intelligence: {Company}

**Generated:** {date}
**Jobs analyzed:** {count}
**Data source:** {url}
**Model:** {model_name}

---

## Hiring Snapshot
{auto-generated stats tables}

## Executive Summary
{2-3 sentence AI summary}

## Department Breakdown
{what each department's hiring tells us}

## Technical Stack & Skills
{what tools/languages they're investing in}

## Geographic Signals
{where they're expanding}

## Strategic Interpretation
{what this company is building toward, written like a human analyst}
```

**Prompt guidance:** The report should read like a human analyst wrote it. No bullet point soup, no "in conclusion" filler, no hedging with "it appears that." State observations directly.

## CLI Interface (main.py)

```bash
# Individual agents
python main.py collect --company "Stripe" --url "https://boards.greenhouse.io/stripe"
python main.py classify --company "Stripe"
python main.py analyze --company "Stripe"

# Full pipeline
python main.py full --company "Stripe" --url "https://boards.greenhouse.io/stripe"
```

`full` runs all three in sequence: collect → classify → analyze.

### Optional flags (future)
- `--refresh` — re-scrape and update changed JDs
- `--model` — override default Gemini model
- `--output` — custom output path for report

## Error Handling
- Scrape failure → log warning, continue to next job/source
- LLM call failure → log error, skip that job, continue
- DB write failure → log error, continue
- **Never crash the pipeline.** Each agent handles its own errors and reports a summary at the end.

## Dependencies (requirements.txt)
```
click
google-generativeai
httpx
beautifulsoup4
lxml
```

No Selenium, no Puppeteer, no heavy browsers. The ATS APIs (Greenhouse, Lever, Ashby) are pure HTTP JSON — `httpx` is all we need for v1.

## Build Order

1. `db.py` — SQLite setup, auto-create tables, helper functions
2. `scraper/ats_api.py` — Adapt Greenhouse + Lever + Ashby from JobDiscovery (strip Flask deps, return plain dicts)
3. `agents/collect.py` — Wire up scrapers, save to DB
4. `prompts/classify.py` — Classification prompt template
5. `agents/classify.py` — Gemini integration, one-per-call classification
6. `prompts/analyze.py` — Report generation prompt template
7. `agents/analyze.py` — Aggregate stats + Gemini narrative + markdown output
8. `main.py` — Click CLI with collect/classify/analyze/full commands
9. Test end-to-end with a real Greenhouse board (e.g., Stripe)
