# SignalVault — Competitive Intelligence Agent

## What This Is

A competitive intelligence platform that scrapes, classifies, and analyzes company data to produce consulting-ready intelligence briefings. Built as a **portfolio piece** to demonstrate value to digital transformation and AI consulting firms (EY Studio+, McKinsey Digital, Deloitte Digital, etc.).

**Value prop:** Help consulting partners identify and qualify digital transformation targets — find companies that need AI, cloud, data, or modernization consulting, score their digital maturity, and map engagement opportunities with estimated scope.

## Stack

- **Backend:** Python, Flask, SQLite (WAL mode)
- **Frontend:** Single-page app in vanilla JS (no framework), Jinja2 template (`web/templates/base.html`)
- **AI:** Multi-provider rotation — 5 providers with 17+ model fallbacks. Report providers: Gemini (primary, multi-key rotation), Groq, Cerebras, Mistral, OpenRouter (free models). Chat providers: Gemini (primary, native function calling), Groq, Cerebras, Mistral, OpenRouter. Separate provider lists for reports (`REPORT_PROVIDERS`) and chat (`CHAT_PROVIDERS`).
- **Scraping:** httpx + BeautifulSoup, SEC EDGAR, USPTO patents, Reddit RSS, HackerNews, YouTube transcripts
- **CLI:** Click-based (`main.py`), also serves web UI via `python main.py web --port 5001`
- **DB:** `intel.db` — 7 tables: companies, jobs, classifications, dossiers, dossier_analyses, dossier_events, hiring_snapshots

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
│   ├── scoring.py           # Algorithmic DMS base scores (deterministic, runs before LLM)
│   ├── collect.py           # Job scraping from ATS boards
│   ├── classify.py          # Job classification (department, seniority, strategic tags)
│   ├── analyze.py           # Strategic hiring analysis report
│   ├── financial.py         # SEC EDGAR / web search financial analysis
│   ├── competitors.py       # Competitive landscape mapping
│   ├── sentiment.py         # Employee sentiment (Glassdoor, Reddit+comments, HN+comments, Blind, Fishbowl, 1P3A)
│   ├── patents.py           # USPTO patent portfolio analysis
│   ├── techstack.py         # Website technology detection + analysis
│   ├── seo.py               # SEO & AEO audit
│   ├── pricing.py           # Product & pricing strategy analysis
│   ├── compare.py           # Head-to-head comparison + landscape analysis
│   └── profile.py           # Full company profile (runs financial + competitors + sentiment + patents)
├── prompts/
│   ├── chat.py              # System prompt, condensed prompt, tool schemas + tiered selection for chat agent
│   ├── briefing.py          # Briefing prompt with hybrid DMS scoring rubric + algo score injection
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
│   ├── web_search.py        # Multi-source web search (news, reddit, youtube via DuckDuckGo)
│   ├── sec_edgar.py         # SEC EDGAR XBRL API for public company financials
│   ├── stock_data.py        # Stock price data via yfinance
│   ├── patents.py           # USPTO PatentsView + Google Patents search
│   ├── ats_api.py           # ATS board scrapers (Greenhouse, Lever, Ashby, Workday, etc.)
│   ├── custom_api.py        # Custom company-specific careers API scrapers (Amazon, Jane Street) + registry
│   ├── linkedin.py          # LinkedIn guest API job listing scraper
│   ├── detect.py            # ATS type auto-detection (custom APIs → ATS probes → Workday → LinkedIn)
│   ├── reddit_rss.py        # Reddit RSS feed scraper with comment fetching (direct, bypasses DDG)
│   ├── hackernews.py        # HackerNews Algolia API search + comment fetching
│   ├── onepoint3acres.py    # 1Point3Acres (一亩三分地) interview experience scraper (Chinese tech community)
│   └── youtube.py           # YouTube search + transcript extraction
├── web/
│   ├── app.py               # Flask app factory, API routes, SSE chat endpoint, tool result summarization
│   └── templates/
│       └── base.html         # Entire SPA — HTML + CSS + JS in one file (~3000 lines)
├── reports/                  # Generated markdown reports (gitignored)
└── .env                      # API keys (gitignored)
```

## Architecture

### Data Flow

1. **Collect:** Scrape job listings from ATS boards (or custom company APIs for Amazon, Jane Street, etc.) → `companies` + `jobs` tables
2. **Classify:** LLM classifies each job (department, seniority, strategic tags) → `classifications` table
3. **Analyze:** Generate strategic hiring analysis report → saved to `reports/` + `dossier_analyses`
4. **Other analyses:** Financial, competitors, sentiment, patents, techstack, SEO, pricing — each produces a report + key facts stored on the dossier
5. **Dossier system:** All analyses accumulate on a company dossier. Key facts are extracted from each report and stored as JSON. Changes between runs are detected and saved as timeline events.
6. **Briefing:** Computes algorithmic DMS base scores from structured data, then synthesizes all dossier data into a consulting-ready intelligence briefing with hybrid Digital Maturity Score and engagement opportunities.

### Dossier System

- `dossiers` table: one row per company (company_name is unique, case-insensitive)
- `dossier_analyses` table: one row per analysis run (links to dossier, stores report_file + key_facts_json)
- `dossier_events` table: timeline events (change_detected, manual notes)
- `save_to_dossier()` in `agents/llm.py`: called at end of every analysis — extracts key facts, detects changes, stores everything
- `compute_dms_scores()` in `agents/scoring.py`: computes deterministic base scores from hiring stats + key facts
- `generate_briefing()` in `agents/briefing.py`: calls scoring module, then synthesizes all data into structured JSON briefing, merges algo scores, recomputes overall

### Key Facts Extraction

Type-specific extraction prompts in `agents/llm.py` (9 type-specific + 1 generic fallback):
- **techstack:** frontend_framework, css_framework, analytics_tools, marketing_tools, cdn_hosting, cms, monitoring_tools, ab_testing_tools, auth_provider, search_provider, payment_provider, infrastructure_provider, total_technologies_detected, tech_modernity_signals
- **seo:** seo_title_optimization_pct, seo_meta_desc_pct, seo_heading_hierarchy_pct, seo_schema_types, seo_has_faq_schema, seo_has_article_schema, aeo_readiness_signals, seo_overall_assessment, pages_analyzed
- **pricing:** pricing_model, pricing_tiers, price_range, has_public_pricing, has_free_tier, target_segment
- **hiring:** total_open_roles, engineering_ratio, ai_ml_ratio, top_departments, top_subcategories, seniority_skew, growth_signal, top_strategic_tags, hiring_trend, notable_shifts, top_skills, primary_locations
- **sentiment:** overall_sentiment, glassdoor_rating, recommend_to_friend_pct, approve_of_ceo_pct, top_pros, top_cons, culture_themes, notable_concerns, sentiment_trend (sources: Glassdoor snippets, Blind snippets, Fishbowl snippets, Reddit posts+comments, HN stories+comments, 1Point3Acres interview posts, news)
- **financial:** revenue, revenue_growth, market_cap, valuation, headcount, profitability, cash_position, recent_funding, key_financial_risks, financial_health
- **competitors:** key_competitors, market_position, competitive_advantages, competitive_weaknesses, market_share, competitive_moat, threat_level
- **patents:** total_patents, recent_patents, top_patent_areas, ai_ml_patents, patent_trend, notable_patents, rd_intensity
- **profile:** hq_location, ceo, founded, sector, headcount, revenue, market_cap, key_products, key_competitors, business_model, key_risks
- **generic fallback:** revenue, market_cap, headcount, founded, hq_location, ceo, sector, key_products, key_competitors, key_risks, patent_count, sentiment_score, hiring_trend, notable_events

Also includes `reextract_all_key_facts()` function to re-extract from existing reports using type-specific prompts without re-running analyses.

### Digital Maturity Score — Hybrid Algorithmic + LLM

Two-pass scoring system: deterministic algorithm computes base scores, then LLM adjusts within ±10 with justification.

**Pass 1 — Algorithmic (`agents/scoring.py`):**
`compute_dms_scores(hiring_stats, all_key_facts)` computes base scores from structured data:
- **Tech Modernity (30%):** Engineering ratio from `hiring_stats.dept_counts`, modern/legacy stack matching from `top_skills`, sector floor (AI→90, software→80), techstack infra + monitoring signals
- **Data & Analytics (25%):** Data role subcategories from `hiring_stats.subcategory_counts`, "Data Infrastructure" strategic tag, advanced analytics + A/B testing tools from techstack key facts
- **AI Readiness (25%):** `ai_ml_role_count` as % of engineering, "AI/ML Investment" strategic tag, `ai_ml_patents` from patents key facts, patent trend bonus
- **Organizational Readiness (20%):** `hiring_trend` enum, growth signal ratio, count of investment-related strategic tags, sentiment enum + Glassdoor rating

Each dimension returns: `algorithmic_score` (0-100), `confidence` (0.0-1.0), `signals_used` (human-readable list), `missing_analyses`.

**Pass 2 — LLM adjustment:**
Algorithmic scores + signals are injected into the briefing prompt. The LLM can adjust each sub-score by ±10. Deviations >5 require an "Algorithmic deviation:" justification in the rationale. High-confidence dimensions (≥0.75) discourage adjustments beyond ±5.

**Pass 3 — Post-processing (`agents/briefing.py`):**
After LLM returns, `briefing.py` merges algo fields (`algorithmic_score`, `algorithmic_confidence`, `signals_used`) onto each sub-score, adds `algorithmic_weighted_score` to the top level, and **recomputes** `overall_score` + `overall_label` from LLM sub-scores (never trusts LLM arithmetic).

Score tiers: Digital Vanguard (80-100), Digital Contender (60-79), Digitally Exposed (40-59), Digital Laggard (20-39), Digital Liability (0-19)

### LLM Provider Rotation

**Report providers** (`REPORT_PROVIDERS` in `agents/llm.py`): Used for all report-generating analyses.
- Gemini: gemini-2.5-flash-lite, gemini-2.5-flash, gemini-3-flash-preview (multi-key rotation via comma-separated `GEMINI_API_KEYS`)
- Groq: llama-3.3-70b-versatile, llama-4-scout-17b-16e-instruct, qwen3-32b
- Cerebras: llama-3.3-70b
- Mistral: mistral-small-latest
- OpenRouter: hermes-3-llama-3.1-405b:free, llama-3.3-70b-instruct:free, qwen3-next-80b-a3b-instruct:free, mistral-small-3.1-24b-instruct:free

**Chat providers** (`CHAT_PROVIDERS` in `agents/chat.py`): Used for the agentic chat interface with function calling.
- Gemini: gemini-2.5-flash, gemini-3-flash-preview (primary, native function calling)
- Groq: llama-3.3-70b-versatile, llama-4-scout-17b-16e-instruct, qwen3-32b, compound-beta
- Cerebras: llama-3.3-70b
- Mistral: mistral-small-latest
- OpenRouter: hermes-3-llama-3.1-405b:free, llama-3.3-70b-instruct:free, qwen3-next-80b-a3b-instruct:free, mistral-small-3.1-24b-instruct:free, step-3.5-flash:free, gemma-3-27b-it:free, nemotron-3-nano-30b-a3b:free

Rate limit fallback: tries next model within same provider, then next provider. Gemini keys are expanded so each key is tried per model before moving on. HTTP 429 triggers fallback; context overflow errors are propagated.

### Chat Tools (full list)

Defined in `prompts/chat.py`, executed in `agents/chat.py`:

- **Reasoning:** think
- **Raw Data:** search_sec_edgar, search_patents_raw, search_financial_news
- **Job Intelligence:** hiring_pipeline, collect, classify, reclassify, analyze
- **Analysis Reports:** financial_analysis, patent_analysis, competitor_analysis, sentiment_analysis, seo_audit, techstack_analysis, pricing_analysis
- **Multi-Company:** full_analysis, compare_companies, landscape_analysis
- **Search:** web_search, reddit_search, reddit_deep_search, hn_search, youtube_search, youtube_transcript
- **Database:** query_db
- **Dossiers:** get_dossier, save_dossier_event, refresh_key_facts, generate_briefing
- **Utility:** get_current_datetime

### Context-Aware Chat

- Web UI sends `context.company` with chat requests when the user is viewing a company's report/dossier
- `_build_context_injection()` in `web/app.py` injects key facts from the dossier into the system prompt
- Current date/time injected into system prompt so search queries use the correct year
- Company-scoped chats with context pill shown above the chat input in the UI

### Chat Context Management (Multi-Step LLM)

The chat system uses a three-pronged approach to prevent context overflow errors, especially on smaller models where the fixed overhead (system prompt ~9K chars + 31 tool schemas ~17K chars = ~26K chars) would leave barely any room for conversation.

**1. Tool Result Summarization** — After each tool executes, the raw result is compressed via a secondary LLM call (`generate_text()` from `agents/llm.py`) before being added to conversation history. The user still sees the full result in the UI; only the LLM's context gets the summary. Results under 600 chars are kept as-is; longer results are summarized to ~200-300 chars. Falls back to simple truncation if the summarization call fails. Implementation: `_summarize_tool_result()` in `web/app.py`.

**2. Dynamic Tool Schema Selection** — Round 1 of each user message sends all 31 tools (~17K chars). Rounds 2+ send only 11 "follow-up" tools (~6K chars). Tool tiers defined in `prompts/chat.py`:
- `CORE_TOOL_NAMES` (6 tools): think, web_search, query_db, get_dossier, get_current_datetime, save_dossier_event
- `FOLLOW_UP_TOOL_NAMES` (11 tools): core + search_financial_news, reddit_search, hn_search, generate_briefing, hiring_pipeline
- `get_tool_schemas(tier)` function: accepts "full" (all tools), "follow_up" (core + key), "minimal" (think + web_search + datetime)

**3. Condensed System Prompt** — Full system prompt (~9K chars) used only on round 1. Rounds 2+ swap to `CONDENSED_SYSTEM_PROMPT` (~400 chars) that keeps essential behavioral rules only. The nuclear trim fallback (context overflow recovery) also uses condensed prompt + no tools.

**Net effect on context overhead:**
- Round 1: ~26K chars (unchanged — LLM needs full context for initial decision)
- Rounds 2+: ~4K chars (saves ~22K chars)
- Each tool result: ~200-300 chars in history instead of 2000-4000 chars

This is the same multi-step LLM pattern used in Crucible (JobDiscovery) — spending small, fast LLM calls to manage context for the main chat LLM.

### PDF Export

- Server-side PDF generation using `xhtml2pdf` + `markdown` libraries
- Route: `GET /api/reports/<filename>/pdf`
- Light-theme styled output with SignalVault header/footer
- Replaces the old broken html2pdf.js client-side approach

### Hiring Snapshots

- `hiring_snapshots` table: periodic captures of hiring stats (dept counts, seniority, AI/ML roles, skills, locations)
- Unique constraint on (company_id, snapshot_date)
- Used by briefing generator for temporal trend analysis (hiring trajectory)
- `get_hiring_snapshots()` and `save_hiring_snapshot()` in `db.py`

## Web UI

Three-pane SPA layout:
- **Left pane (260px):** Navigation tabs (Reports, Dossiers, Chat) + list view with company badges on chat items
- **Middle pane:** Chat interface with SSE streaming, tool call display, thinking indicators, context pill above input showing what company/report is being viewed
- **Right pane (540px):** Report viewer / Dossier detail / Intelligence briefing with source popovers showing priority-ordered key facts

### CSS Design System

- Dark theme: `--bg-primary: #0a0a0a`, `--bg-secondary: #111`, `--bg-tertiary: #1a1a1a`
- Accent: blue `#3b82f6`, purple `#a855f7`, green `#22c55e`, yellow `#eab308`, red `#ef4444`
- Links: `#60a5fa` for contrast on dark theme
- Card pattern: `background: var(--bg-tertiary); border: 1px solid var(--border); border-radius: 8px;`
- All text is small: 11-13px body, 10px labels
- Scrollable panes with hidden scrollbars

### API Routes

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/api/reports` | List all reports |
| GET | `/api/reports/<filename>/content` | Get report content |
| GET | `/api/reports/<filename>/pdf` | Export report as styled PDF (server-side, xhtml2pdf) |
| DELETE | `/api/reports/<filename>` | Delete report |
| GET | `/api/dossiers` | List all dossiers |
| GET | `/api/dossiers/<name>` | Get dossier detail (includes analyses, events, briefing_json) |
| POST | `/api/dossiers/<name>/events` | Add timeline event |
| GET | `/api/dossiers/<name>/hiring-snapshots` | Get hiring snapshot history for temporal trends |
| POST | `/api/dossiers/<name>/briefing` | Generate intelligence briefing |
| GET | `/api/dossiers/<name>/pdf` | Export intelligence briefing as styled PDF |
| POST | `/api/chat` | SSE chat endpoint (with context injection + company scoping + dynamic tool selection) |

## Code Conventions

- **NEVER hardcode API keys** — always `os.environ.get()`
- LLM calls go through `agents/llm.py` (`generate_text`, `generate_json`)
- Every analysis agent calls `save_to_dossier()` at the end to persist results
- Reports saved as markdown to `reports/` directory
- All prompts live in `prompts/` — one file per analysis type
- Chat tool schemas defined in `prompts/chat.py` (with tiered selection via `get_tool_schemas()`), tool execution in `agents/chat.py`
- Citation format: Perplexity-style clickable superscript links `[¹](url)` across all report prompts
- `company_name` parameter on techstack/seo/pricing agents links site analyses to company dossiers (instead of using domain name)
- Flask server runs with `use_reloader=False` — must restart to pick up code changes

## Environment Variables

```
GEMINI_API_KEYS     # Comma-separated Gemini API keys (supports multi-key rotation per model)
GROQ_API_KEY        # Groq API key
CEREBRAS_API_KEY    # Cerebras API key
MISTRAL_API_KEY     # Mistral API key
OPENROUTER_API_KEY  # OpenRouter API key (free-tier models)
USPTO_API_KEY       # USPTO PatentsView API key (falls back to PATENTSVIEW_API_KEY)
```

## Database Schema Details

### Core Tables (Job Intelligence)
- **companies:** id, name, url, ats_type, seniority_framework, last_scraped, created_at
- **jobs:** id, company_id, title, department, location, url (UNIQUE), description, description_hash, salary, date_posted, scrape_status, scraped_at
- **classifications:** id, job_id (UNIQUE), department_category, department_subcategory, seniority_level, key_skills, strategic_signals, strategic_tags, growth_signal, classified_at, model_used

### Dossier Tables
- **dossiers:** id, company_name (UNIQUE NOCASE), sector, description, briefing_json, briefing_generated_at, briefing_model, created_at, updated_at
- **dossier_analyses:** id, dossier_id (FK), analysis_type, report_file, key_facts_json, model_used, created_at
- **dossier_events:** id, dossier_id (FK), event_date, event_type, title, description, source_url, data_json, created_at

### Temporal Analysis
- **hiring_snapshots:** id, company_id (FK), snapshot_date, total_roles, dept_counts, subcategory_counts, seniority_counts, strategic_tag_counts, ai_ml_role_count, growth_signal_ratio, top_skills, top_locations, created_at — UNIQUE(company_id, snapshot_date)

## Current State (March 2026)

Fully functional with 12 analysis types, agentic chat with 5 LLM providers and 17+ model fallbacks, dossier system with change detection, hiring temporal analysis via snapshots, context-aware company-scoped chat with multi-step context management (tool result summarization, dynamic tool schema selection, condensed system prompts), server-side PDF export (reports + briefings), and intelligence briefing with hybrid algorithmic+LLM Digital Maturity Score. The briefing is the flagship feature — it transforms raw intelligence into a consulting partner-ready document that identifies digital transformation opportunities with section-to-source citation mapping and engagement opportunity prioritization. The DMS now uses a two-pass hybrid approach: deterministic algorithmic base scores computed from structured data, then LLM fine-tuning within ±10 bounds with required justification for deviations.

## Planned Improvements

- **Temporal analysis smarts**: Currently `get_previous_key_facts()` compares against the immediately prior run regardless of date. Same-day re-runs produce noise (spurious "changes" from LLM extraction variance, or no-op comparisons). Improvements: skip temporal injection if previous analysis is from the same day; compare against the oldest/first analysis to show long-term trends; add a minimum time gap (e.g. 24h) before flagging changes as significant.
- **Multi-source job collection**: Primary ATS + LinkedIn supplement is implemented, but could expand to scrape multiple ATS boards if a company uses more than one (e.g. Greenhouse for engineering + Workday for corporate).
- **Briefing diff view**: Side-by-side comparison of two briefings for the same company to visually highlight what changed between analysis runs.
