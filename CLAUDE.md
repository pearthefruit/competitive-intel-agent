# SignalForge — Competitive Intelligence Agent

## What This Is

A competitive intelligence platform that scrapes, classifies, and analyzes company data to produce consulting-ready intelligence briefings. Built as a **portfolio piece** to demonstrate value to digital transformation and AI consulting firms (EY Studio+, McKinsey Digital, Deloitte Digital, etc.).

**Value prop:** Help consulting partners identify and qualify digital transformation targets — find companies that need AI, cloud, data, or modernization consulting, score their digital maturity, and map engagement opportunities with estimated scope.

## Stack

- **Backend:** Python, Flask, SQLite (WAL mode)
- **Frontend:** Single-page app in vanilla JS (no framework), Jinja2 template (`web/templates/base.html`)
- **AI:** Multi-provider rotation — Gemini 2.5 Flash Lite (primary), Groq, Mistral. Chat uses Gemini function calling.
- **Scraping:** httpx + BeautifulSoup, SEC EDGAR, USPTO patents, Reddit RSS, HackerNews, YouTube transcripts
- **CLI:** Click-based (`main.py`), also serves web UI via `python main.py web --port 5001`
- **DB:** `intel.db` — 5 tables: companies, jobs, classifications, dossiers, dossier_analyses, dossier_events

## Commands

```bash
# Start web UI (must restart to pick up code changes — use_reloader=False)
python main.py web --port 5001

# Individual analyses
python main.py collect --company "Apple" --url <ats_url>
python main.py classify --company "Apple"
python main.py analyze --company "Apple"
python main.py financial --company "Apple"
python main.py competitors --company "Apple"
python main.py sentiment --company "Apple"
python main.py patents --company "Apple"
python main.py techstack --url "https://apple.com"
python main.py seo --url "https://apple.com" --max-pages 10
python main.py pricing --url "https://apple.com"
python main.py profile --company "Apple"            # runs financial + competitors + sentiment + patents
python main.py compare --company-a "Apple" --company-b "Samsung"
python main.py landscape --company "Apple"           # auto-discovers competitors
python main.py chat                                  # interactive chat REPL
```

## Project Structure

```
competitive-intel-agent/
├── main.py                  # CLI entry point (Click)
├── db.py                    # SQLite schema, migrations, all DB helpers
├── intel.db                 # SQLite database (gitignored)
├── agents/
│   ├── llm.py               # LLM provider rotation, generate_text/generate_json, save_to_dossier, key facts extraction, change detection
│   ├── chat.py              # Agentic chat with Gemini function calling (ChatLLM class)
│   ├── briefing.py          # Intelligence briefing generator (Digital Maturity Score)
│   ├── collect.py           # Job scraping from ATS boards
│   ├── classify.py          # Job classification (department, seniority, strategic tags)
│   ├── analyze.py           # Strategic hiring analysis report
│   ├── financial.py         # SEC EDGAR / web search financial analysis
│   ├── competitors.py       # Competitive landscape mapping
│   ├── sentiment.py         # Employee sentiment (Glassdoor, Reddit, HN)
│   ├── patents.py           # USPTO patent portfolio analysis
│   ├── techstack.py         # Website technology detection + analysis
│   ├── seo.py               # SEO & AEO audit
│   ├── pricing.py           # Product & pricing strategy analysis
│   ├── compare.py           # Head-to-head comparison + landscape analysis
│   └── profile.py           # Full company profile (runs financial + competitors + sentiment + patents)
├── prompts/
│   ├── chat.py              # System prompt + tool schemas for chat agent
│   ├── briefing.py          # Briefing prompt with Digital Maturity scoring rubric
│   ├── analyze.py           # Hiring analysis prompt
│   ├── classify.py          # Job classification prompt
│   ├── financial.py         # Financial analysis prompt
│   ├── competitors.py       # Competitor mapping prompt
│   ├── sentiment.py         # Sentiment analysis prompt
│   ├── patents.py           # Patent analysis prompt
│   ├── techstack.py         # Tech stack analysis prompt
│   ├── seo.py               # SEO audit prompt
│   ├── pricing.py           # Pricing analysis prompt
│   ├── compare.py           # Comparison prompt
│   └── profile.py           # Executive profile prompt
├── scraper/
│   ├── site_crawler.py      # General website crawler (httpx + BS4)
│   ├── tech_detect.py       # Technology fingerprinting from HTML/headers/scripts
│   ├── web_search.py        # Multi-source web search (news, reddit, youtube)
│   ├── sec_edgar.py         # SEC EDGAR API for public company financials
│   ├── stock_data.py        # Stock price data via yfinance
│   ├── patents.py           # USPTO patent search
│   ├── ats_api.py           # ATS board scrapers (Greenhouse, Lever, Workday, etc.)
│   ├── linkedin.py          # LinkedIn job listing scraper
│   ├── detect.py            # ATS type detection
│   ├── reddit_rss.py        # Reddit RSS feed scraper
│   ├── hackernews.py        # HackerNews Algolia API
│   └── youtube.py           # YouTube transcript extraction
├── web/
│   ├── app.py               # Flask app factory, API routes, SSE chat endpoint
│   └── templates/
│       └── base.html         # Entire SPA — HTML + CSS + JS in one file (~2500 lines)
├── reports/                  # Generated markdown reports (gitignored)
└── .env                      # API keys (gitignored)
```

## Architecture

### Data Flow

1. **Collect:** Scrape job listings from ATS boards → `companies` + `jobs` tables
2. **Classify:** LLM classifies each job (department, seniority, strategic tags) → `classifications` table
3. **Analyze:** Generate strategic hiring analysis report → saved to `reports/` + `dossier_analyses`
4. **Other analyses:** Financial, competitors, sentiment, patents, techstack, SEO, pricing — each produces a report + key facts stored on the dossier
5. **Dossier system:** All analyses accumulate on a company dossier. Key facts are extracted from each report and stored as JSON. Changes between runs are detected and saved as timeline events.
6. **Briefing:** Synthesizes all dossier data into a consulting-ready intelligence briefing with Digital Maturity Score and engagement opportunities.

### Dossier System

- `dossiers` table: one row per company (company_name is unique, case-insensitive)
- `dossier_analyses` table: one row per analysis run (links to dossier, stores report_file + key_facts_json)
- `dossier_events` table: timeline events (change_detected, manual notes)
- `save_to_dossier()` in `agents/llm.py`: called at end of every analysis — extracts key facts, detects changes, stores everything
- `generate_briefing()` in `agents/briefing.py`: synthesizes all data into structured JSON briefing

### Key Facts Extraction

Type-specific extraction prompts in `agents/llm.py`:
- **techstack:** frontend_framework, analytics_tools, marketing_tools, cdn_hosting, monitoring_tools, ab_testing_tools, tech_modernity_signals
- **seo:** seo_title_optimization_pct, seo_meta_desc_pct, seo_schema_types, aeo_readiness_signals, seo_overall_assessment
- **pricing:** pricing_model, pricing_tiers, price_range, has_public_pricing, target_segment
- **generic (financial, competitors, sentiment, patents):** revenue, market_cap, headcount, ceo, sector, key_products, key_competitors, patent_count, sentiment_score, hiring_trend

### Digital Maturity Score (Briefing)

LLM-scored 0-100 composite with 4 weighted sub-scores:
- **Tech Modernity (30%):** Modern vs legacy stack signals from techstack analysis
- **Data & Analytics (25%):** Analytics tools sophistication from techstack + SEO data
- **AI Readiness (25%):** AI/ML hiring signals from classifications + patent portfolio
- **Organizational Readiness (20%):** Hiring momentum, engineering ratio, strategic tags

Score tiers: Digitally Advanced (80-100), Digitally Maturing (60-79), Digital Laggard (40-59), Pre-Digital (0-39)

## Web UI

Three-pane SPA layout:
- **Left pane (260px):** Navigation tabs (Reports, Dossiers, Chat) + list view
- **Middle pane:** Chat interface with SSE streaming, tool call display, thinking indicators
- **Right pane (540px):** Report viewer / Dossier detail / Intelligence briefing

### CSS Design System

- Dark theme: `--bg-primary: #0a0a0a`, `--bg-secondary: #111`, `--bg-tertiary: #1a1a1a`
- Accent: blue `#3b82f6`, purple `#a855f7`, green `#22c55e`, yellow `#eab308`, red `#ef4444`
- Card pattern: `background: var(--bg-tertiary); border: 1px solid var(--border); border-radius: 8px;`
- All text is small: 11-13px body, 10px labels
- Scrollable panes with hidden scrollbars

### API Routes

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/api/reports` | List all reports |
| GET | `/api/reports/<filename>/content` | Get report content |
| DELETE | `/api/reports/<filename>` | Delete report |
| GET | `/api/dossiers` | List all dossiers |
| GET | `/api/dossiers/<name>` | Get dossier detail (includes analyses, events, briefing_json) |
| POST | `/api/dossiers/<name>/events` | Add timeline event |
| POST | `/api/dossiers/<name>/briefing` | Generate intelligence briefing |
| POST | `/api/chat` | SSE chat endpoint |

## Code Conventions

- **NEVER hardcode API keys** — always `os.environ.get()`
- LLM calls go through `agents/llm.py` (`generate_text`, `generate_json`)
- Every analysis agent calls `save_to_dossier()` at the end to persist results
- Reports saved as markdown to `reports/` directory
- All prompts live in `prompts/` — one file per analysis type
- Chat tool schemas defined in `prompts/chat.py`, tool execution in `agents/chat.py`
- Citation format: Perplexity-style clickable superscript links `[¹](url)` across all report prompts
- `company_name` parameter on techstack/seo/pricing agents links site analyses to company dossiers (instead of using domain name)
- Flask server runs with `use_reloader=False` — must restart to pick up code changes

## Environment Variables

```
GEMINI_API_KEYS     # Comma-separated Gemini API keys
GROQ_API_KEY        # Groq API key
MISTRAL_API_KEY     # Mistral API key
```

## Current State (March 2026)

Fully functional with 12 analysis types, agentic chat, dossier system with change detection, and intelligence briefing with Digital Maturity Score. The briefing is the flagship feature — it transforms raw intelligence into a consulting partner-ready document that identifies digital transformation opportunities.
