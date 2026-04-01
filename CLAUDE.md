# SignalVault — Competitive Intelligence Agent

## What This Is

A competitive intelligence platform that scrapes, classifies, and analyzes company data to produce consulting-ready intelligence briefings. Built as a **portfolio piece** to demonstrate value to digital transformation and AI consulting firms (EY Studio+, McKinsey Digital, Deloitte Digital, etc.).

**Value prop:** Help consulting partners identify and qualify digital transformation targets — find companies that need AI, cloud, data, or modernization consulting, score their digital maturity, and map engagement opportunities with estimated scope.

## Stack

- **Backend:** Python, Flask, SQLite (WAL mode)
- **Frontend:** Single-page app in vanilla JS (no framework), Jinja2 template (`web/templates/base.html`)
- **AI:** Multi-provider rotation — 5 providers with 17+ model fallbacks. Report providers: Gemini (primary, multi-key rotation), Groq, Cerebras, Mistral, OpenRouter (free models). Chat providers: Gemini (primary, native function calling), Groq, Cerebras, Mistral, OpenRouter. Separate provider lists for reports (`REPORT_PROVIDERS`) and chat (`CHAT_PROVIDERS`).
- **Scraping:** httpx + BeautifulSoup + trafilatura, SEC EDGAR (XBRL + 8-K filings), USPTO patents, Reddit RSS, HackerNews, YouTube transcripts, Google News RSS, Blind, TikTok (yt-dlp), 1Point3Acres
- **CLI:** Click-based (`main.py`), also serves web UI via `python main.py web --port 5001`
- **DB:** `intel.db` — 13 tables: companies, jobs, classifications, dossiers, dossier_analyses, dossier_events, hiring_snapshots, llm_usage, icp_profiles, lenses, lens_scores, campaigns (+ parent_campaign_id, seed_company, execution_log_json for recursive discovery trees), campaign_prospects

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

# Prospecting (ICP fit scoring)
python main.py ua-discover --niche "DTC skincare" --top-n 15 [--icp-profile <id>]
python main.py ua-fit --company "Glossier" [--url "https://glossier.com"] [--icp-profile <id>]
python main.py ua-pipeline --niche "DTC skincare" --top-n 15 [--icp-profile <id>]
```

## Project Structure

```
competitive-intel-agent/
├── main.py                  # CLI entry point (Click)
├── db.py                    # SQLite schema, migrations, all DB helpers (incl. recursive campaign tree CTE, fuzzy dossier matching, dossier merge)
├── intel.db                 # SQLite database (gitignored)
├── agents/
│   ├── llm.py               # LLM provider rotation, generate_text/generate_json, save_to_dossier (progress_cb: extract/changes/save events), key facts extraction, change detection
│   ├── chat.py              # Agentic chat with Gemini function calling (ChatLLM class)
│   ├── briefing.py          # Intelligence briefing generator (Digital Maturity Score)
│   ├── scoring.py           # Algorithmic DMS base scores (deterministic, runs before LLM)
│   ├── collect.py           # Job scraping from ATS boards
│   ├── classify.py          # Job classification (department, seniority, strategic tags)
│   ├── analyze.py           # Strategic hiring analysis report
│   ├── financial.py         # SEC EDGAR / web search financial analysis (progress_cb: structured events per source)
│   ├── competitors.py       # Competitive landscape mapping (progress_cb: structured events per source)
│   ├── sentiment.py         # Employee sentiment (Glassdoor, Reddit+comments, HN+comments, Blind, Fishbowl, 1P3A) (progress_cb: structured events per source)
│   ├── patents.py           # USPTO patent portfolio analysis (progress_cb: structured events per source)
│   ├── techstack.py         # Website technology detection + analysis (progress_cb: structured events per source)
│   ├── seo.py               # SEO & AEO audit (progress_cb: structured events per source)
│   ├── pricing.py           # Product & pricing strategy analysis (progress_cb: structured events per source)
│   ├── compare.py           # Head-to-head comparison + landscape analysis
│   ├── profile.py           # Full company profile (runs financial + competitors + sentiment + patents)
│   ├── ua_discover.py       # Prospect discovery via web search (smart query generation + company-anchored "Find Similar" via discover_similar())
│   ├── ua_fit.py            # Legacy ICP fit scoring (validate_websites still used, scoring functions importable)
│   └── lens.py              # Lens scoring engine — score_with_lens(), configurable dimensions/weights/rubrics, threads progress_cb to analysis agents
├── prompts/
│   ├── chat.py              # System prompt, condensed prompt, tool schemas + tiered selection for chat agent
│   ├── briefing.py          # Briefing prompt with hybrid DMS scoring rubric + algo score injection
│   ├── icp_generate.py      # ICP config generation prompt (survey answers → config JSON)
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
│   ├── profile.py           # Executive profile prompt
│   ├── ua_fit.py            # Legacy ICP fit scoring prompt (still used for historical campaigns)
│   ├── ua_discover.py       # Prospect discovery prompt (structured context + similar company discovery prompt)
│   └── lens.py              # Lens scoring prompt — dynamic rubric from lens dimensions/weights
├── scraper/
│   ├── site_crawler.py      # General website crawler (httpx + BS4)
│   ├── tech_detect.py       # Technology fingerprinting from HTML/headers/scripts
│   ├── web_search.py        # Multi-source web search (news, reddit, youtube via DuckDuckGo) + dedup_results()
│   ├── google_news.py       # Google News RSS scraper (date filtering, redirect resolution)
│   ├── sec_edgar.py         # SEC EDGAR XBRL API + 8-K filings for public company financials + COMPANY_ALIASES (26 brand→entity mappings)
│   ├── stock_data.py        # Stock price data via yfinance
│   ├── patents.py           # USPTO PatentsView + Google Patents search
│   ├── ats_api.py           # ATS board scrapers (Greenhouse, Lever, Ashby, Workday, etc.)
│   ├── custom_api.py        # Custom company-specific careers API scrapers (Amazon, Jane Street) + registry
│   ├── linkedin.py          # LinkedIn guest API job listing scraper
│   ├── detect.py            # ATS type auto-detection (custom APIs → ATS probes → Workday → LinkedIn)
│   ├── reddit_rss.py        # Reddit RSS feed scraper with comment fetching (direct, bypasses DDG)
│   ├── hackernews.py        # HackerNews Algolia API search + comment fetching
│   ├── onepoint3acres.py    # 1Point3Acres (一亩三分地) interview experience scraper (Chinese tech community)
│   ├── blind.py             # Blind direct scraper (JSON-LD reviews + RSC stream + post links)
│   ├── tiktok.py            # TikTok video metadata + captions via yt-dlp
│   ├── nonprofit.py         # ProPublica Nonprofit Explorer API (IRS Form 990 data)
│   └── youtube.py           # YouTube search + transcript extraction
├── web/
│   ├── app.py               # Flask app factory, API routes, SSE chat endpoint (_structured_cb wrapper for analysis progress), tool result summarization, discovery tree API
│   └── templates/
│       └── base.html         # Entire SPA — HTML + CSS + JS in one file (~12100+ lines)
├── reports/                  # Generated markdown reports (gitignored)
└── .env                      # API keys (gitignored)
```

## Architecture

### Data Flow

1. **Collect:** Scrape job listings from ATS boards (or custom company APIs for Amazon, Jane Street, etc.) → `companies` + `jobs` tables
2. **Classify:** LLM classifies each job (department, seniority, strategic tags) → `classifications` table
3. **Analyze:** Generate strategic hiring analysis report → saved to `reports/` + `dossier_analyses`
4. **Other analyses:** Financial, competitors, sentiment, patents, techstack, SEO, pricing — each produces a report + key facts stored on the dossier. All 7 agents accept `progress_cb` and emit structured events (`source_start`, `source_done`, `generating`, `report_saved`) with `detail` fields per data source for real-time UI progress tracking. Detail fields contain actual result data (search result titles/URLs, extracted metrics, tech categories, patent titles, SEO signals, etc.) making pipeline tree mini-cards clickable.
5. **Dossier system:** All analyses accumulate on a company dossier. Key facts are extracted from each report and stored as JSON. Changes between runs are detected and saved as timeline events.
6. **Briefing:** Computes algorithmic DMS base scores from structured data, then synthesizes all dossier data into a consulting-ready intelligence briefing with hybrid Digital Maturity Score and engagement opportunities.

### Dossier System

- `dossiers` table: one row per company (company_name is unique, case-insensitive)
- `dossier_analyses` table: one row per analysis run (links to dossier, stores report_file + key_facts_json)
- `dossier_events` table: timeline events (change_detected, manual notes)
- `save_to_dossier()` in `agents/llm.py`: called at end of every analysis — extracts key facts, detects changes, stores everything. Also emits structured progress events (extract, changes, save) when called with a `progress_cb`.
- `get_or_create_dossier()`: exact NOCASE match first, then `_find_similar_dossier()` fuzzy fallback (0.85 threshold via `difflib.SequenceMatcher`) to prevent duplicate dossiers from typos/spelling variants
- `merge_dossiers(conn, keep_name, merge_name)`: moves all analyses, events, lens_scores, campaign_prospects from one dossier to another, deletes the merged one. Exposed via `POST /api/dossiers/merge`.
- `get_all_dossiers(conn, hide_empty=False)`: accepts `hide_empty` param to exclude dossiers with 0 analyses (Discover stubs). Both `/api/dossiers` and `/api/companies` default to `hide_empty=1`.
- `compute_dms_scores()` in `agents/scoring.py`: computes deterministic base scores from hiring stats + key facts
- `generate_briefing()` in `agents/briefing.py`: calls scoring module, then synthesizes all data into structured JSON briefing, merges algo scores, recomputes overall

### Key Facts Extraction

Type-specific extraction prompts in `agents/llm.py` (9 type-specific + 1 generic fallback):
- **techstack:** frontend_framework, css_framework, analytics_tools, marketing_tools, cdn_hosting, cms, monitoring_tools, ab_testing_tools, auth_provider, search_provider, payment_provider, infrastructure_provider, total_technologies_detected, tech_modernity_signals
- **seo:** seo_title_optimization_pct, seo_meta_desc_pct, seo_heading_hierarchy_pct, seo_schema_types, seo_has_faq_schema, seo_has_article_schema, aeo_readiness_signals, seo_overall_assessment, pages_analyzed
- **pricing:** pricing_model, pricing_tiers, price_range, has_public_pricing, has_free_tier, target_segment
- **hiring:** total_open_roles, engineering_ratio, ai_ml_ratio, top_departments, top_subcategories, seniority_skew, growth_signal, top_strategic_tags, hiring_trend, notable_shifts, top_skills, primary_locations
- **sentiment:** overall_sentiment, glassdoor_rating, recommend_to_friend_pct, approve_of_ceo_pct, top_pros, top_cons, culture_themes, notable_concerns, sentiment_trend (sources: Glassdoor snippets, Blind snippets, Fishbowl snippets, Reddit posts+comments, HN stories+comments, 1Point3Acres interview posts, news)
- **financial:** revenue, revenue_growth, market_cap, valuation, headcount, profitability, cash_position, recent_funding, key_financial_risks, financial_health, aum, aum_growth, fee_structure, fund_strategy, is_financial_services
- **competitors:** key_competitors, market_position, competitive_advantages, competitive_weaknesses, market_share, competitive_moat, threat_level
- **patents:** total_patents, recent_patents, top_patent_areas, ai_ml_patents, patent_trend, notable_patents, rd_intensity
- **profile:** hq_location, ceo, founded, sector, headcount, revenue, market_cap, key_products, key_competitors, business_model, key_risks
- **generic fallback:** revenue, market_cap, headcount, founded, hq_location, ceo, sector, key_products, key_competitors, key_risks, patent_count, sentiment_score, hiring_trend, notable_events

Also includes `reextract_all_key_facts()` function to re-extract from existing reports using type-specific prompts without re-running analyses.

### Digital Maturity Score — Hybrid Algorithmic + LLM

Two-pass scoring system: deterministic algorithm computes base scores, then LLM adjusts within ±10 with justification.

**Pass 1 — Algorithmic (`agents/scoring.py`):**
`compute_dms_scores(hiring_stats, all_key_facts)` computes base scores from structured data:
- **Tech Modernity (30%):** Engineering ratio from `hiring_stats.dept_counts`, modern/legacy stack matching from `top_skills`, sector additive bonus (AI→+25, software→+15) on top of base score (so a legacy SaaS company with weak signals can still score poorly), techstack infra + monitoring signals
- **Data & Analytics (25%):** Data role subcategories from `hiring_stats.subcategory_counts`, "Data Infrastructure" strategic tag, advanced analytics + A/B testing tools from techstack key facts
- **AI Readiness (25%):** `ai_ml_role_count` as % of engineering, "AI/ML Investment" strategic tag, `ai_ml_patents` from patents key facts, patent trend bonus
- **Organizational Readiness (20%):** `hiring_trend` enum, growth signal ratio, count of investment-related strategic tags, sentiment enum + Glassdoor rating

Each dimension returns: `algorithmic_score` (0-100), `confidence` (0.0-1.0), `signals_used` (human-readable list), `missing_analyses`.

**Pass 2 — LLM adjustment:**
Algorithmic scores + signals are injected into the briefing prompt. The LLM can adjust each sub-score by ±10. Deviations >5 require an "Algorithmic deviation:" justification in the rationale. High-confidence dimensions (≥0.75) discourage adjustments beyond ±5.

**Pass 3 — Post-processing (`agents/briefing.py`):**
After LLM returns, `briefing.py` merges algo fields (`algorithmic_score`, `algorithmic_confidence`, `signals_used`) onto each sub-score, adds `algorithmic_weighted_score` to the top level, and **recomputes** `overall_score` + `overall_label` from LLM sub-scores (never trusts LLM arithmetic).

Score tiers: Digital Vanguard (80-100), Digital Contender (60-79), Digitally Exposed (40-59), Digital Laggard (20-39), Digital Liability (0-19)

**Anomaly Detection (`compute_anomaly_signals()` in `agents/scoring.py`):**
Runs alongside DMS scoring and detects 8 structural anomaly types that indicate consulting opportunities regardless of DMS score:
1. **Engineering-heavy org** — disproportionate engineering headcount vs. business functions
2. **Top-heavy seniority** — high ratio of senior/staff/principal roles with few mid-level execution layers
3. **Scaling without leaders** — rapid headcount growth with no corresponding management/director hiring
4. **Replacement churn** — re-opening roles at the same level/department (turnover signal)
5. **Department surge** — one department growing dramatically faster than the rest
6. **AI without data foundation** — AI/ML roles hired before data engineering/infrastructure is in place
7. **Growth-sentiment gap** — strong hiring signals paired with negative employee sentiment
8. **Low Glassdoor** — Glassdoor rating below threshold (culture/leadership risk signal)
9. **Strategic sprawl** — too many unrelated strategic tag clusters (unfocused roadmap)

Detected anomalies are injected into the briefing prompt to improve engagement opportunity generation. Each anomaly includes a label, severity, and a plain-English description of why it matters to a consulting buyer.

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
- **Analysis Reports:** financial_analysis, patent_analysis, competitor_analysis, sentiment_analysis, seo_audit, techstack_analysis, pricing_analysis (all 7 pass `progress_callback` through for structured per-source events with `detail` fields)
- **Multi-Company:** full_analysis, compare_companies, landscape_analysis
- **Search:** web_search, reddit_search, reddit_deep_search, hn_search, youtube_search, youtube_transcript (all emit `progress_callback` steps for real-time UI progress)
- **Database:** query_db
- **Dossiers:** get_dossier, save_dossier_event, refresh_key_facts, generate_briefing
- **Prospecting:** ua_discover, ua_fit_score (aliased → CTV Ad Sales lens), get_ua_targets (aliased → lens_scores), score_lens, create_lens, list_lenses
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

**4. Structured Progress Callbacks** — The SSE chat endpoint uses `_structured_cb(*args)` as the progress callback for tool execution. It handles both 1-arg string calls (legacy flat progress) and 2-arg `(event_type, data_dict)` structured calls from analysis agents. Structured events are queued as dicts with `_structured: True` flag. The SSE emitter (`_emit_progress`) detects this flag and includes the structured event fields directly in the SSE payload with `structured: true`. This fixes a bug where `lens.py`'s 2-arg `progress_cb("analysis_start", {...})` calls crashed the old 1-arg lambda.

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

### Prospecting Module (Lens-Based Scoring)

- **Architecture:** Two-phase workflow — **Discover** (pure search) + **Research** (lens-based scoring). Discovery supports both niche-based and company-anchored ("Find Similar") modes.
- **Discover:** `agents/ua_discover.py` + `prompts/ua_discover.py` — smart query generation from structured Niche Builder context (8-12 targeted queries). No scoring in pipeline. Users select up to 3 companies → "Send to Research".
- **Find Similar:** `discover_similar()` in `agents/ua_discover.py` — company-anchored recursive discovery. Uses `_profile_lookup` from `compare.py` for profile-aware search, `_build_similar_queries()` for targeted queries. Creates child campaigns linked via `parent_campaign_id`. Max tree depth: 3. Emits `seed_profile` SSE event with company profile data. Prompt: `build_similar_discovery_prompt()` in `prompts/ua_discover.py`.
- **Discovery Tree:** Campaigns form a tree structure (root → child → grandchild). `get_root_campaigns()` returns top-level campaigns; `get_campaign_tree()` uses recursive CTE to fetch full tree. `get_campaign_depth()` computes depth for max-depth enforcement. `delete_campaign()` cascades to children. Frontend renders tree in Pane 2 with breadcrumb navigation in Pane 3.
- **Lens system:** `agents/lens.py` + `prompts/lens.py` — configurable evaluation frameworks with custom dimensions, weights, rubrics. Default "CTV Ad Sales" lens with 5 dimensions matching legacy CTV scoring.
- **Default dimensions (CTV Ad Sales lens):**
  - Financial Capacity (25%) — `financial_capacity` — SEC EDGAR / web
  - Paid Media Footprint (20%) — `advertising_maturity` — ad pixel detection via techstack
  - Growth Trajectory (20%) — `growth_trajectory` — financial growth + sentiment news
  - Video Asset Readiness (20%) — `creative_readiness` — sentiment + social/video mentions
  - Channel Expansion Intent (15%) — `channel_expansion_intent` — sentiment news + hiring signals
- **Score Tiers:** Prime Prospect (80+), Strong Candidate (60+), Possible Fit (40+), Weak Fit (20+), Not a Fit (0+)
- **UI:** Dynamic lens names (no hardcoded CTV labels). Dimension Cards with bar + rationale + signal tags. Score tooltips from lens rubric_description.
- **CLI commands:** `ua-discover`, `ua-fit`, `ua-pipeline`
- **Chat integration:** `ua_discover`, `ua_fit_score` (aliased to CTV lens), `get_ua_targets` (aliased to lens_scores), `score_lens`, `create_lens`, `list_lenses`
- **DB:** `lenses` table (dimensions_json), `lens_scores` table (score_data JSON). Legacy `dossiers.ua_fit_json` preserved for backward compat.

### ICP Wizard System

The ICP Wizard makes the prospecting module configurable instead of hardcoded. A guided survey generates a complete ICP config via LLM.

**Config generation flow:**
1. User completes 5-step survey in modal wizard
2. Survey answers posted to `POST /api/icp-profiles/generate`
3. LLM prompt (`prompts/icp_generate.py`) generates structured config JSON
4. Config includes: dimensions (key, label, weight, rubric, signal_queries), labels, discovery_filters, icp_definition, suggested_niches
5. User reviews and can edit weights/definition before saving

**Wizard steps (in `base.html`):**
- Step 0: Business type funnel (B2B/B2C -> industry -> sub-industry -> freeform detail) using `_INDUSTRY_TREE` data structure
- Step 1: Your Offer (product + problem)
- Step 2: Your Customers (adapts B2B vs B2C questions)
- Step 3: How You Sell (adapts B2B vs B2C)
- Step 4: Review (LLM generates config, user edits weights/definition)

**UI elements:**
- ICP profile indicator with popover menu (profile switching + wizard launch)
- Niche suggestion chips from `config.suggested_niches` after wizard completion
- Discover button shake animation + feedback when niche input empty
- Methodology transparency section (per-dimension queries, URLs, snippets) replaces old "View Full Dossier" button

## Web UI

Module sidebar (64px) on far left with icon+label buttons (Research, Prospects). Each module has its own workspace toggled via `.active` class.

**Research workspace** — three-pane SPA layout:
- **Left pane (290px):** Navigation tabs (Reports, Dossiers, Chat) + list view with company badges on chat items
- **Middle pane:** Chat interface with SSE streaming, tool call display, thinking indicators, context pill above input showing what company/report is being viewed
- **Right pane (580px):** Report viewer / Dossier detail / Intelligence briefing with source popovers showing priority-ordered key facts

**Prospecting workspace** — 4-pane horizontal pipeline layout:
- **Pane 1 (Sidebar, 250px):** Niche input + Niche Builder modal + flat campaign history list (root campaigns only)
- **Pane 2 (Execution Engine, 420px):** Pipeline steps only (no company cards) — search activity log + step nodes (Discovery → Found N → Validation → Complete), persists after completion. `renderExecutionPane()` uses `renderPipelineTree()` for campaigns with `execution_log` data (flowchart cards). For campaigns with children, renders a **discovery tree** (`renderDiscoveryTree()`) showing parent→child campaign hierarchy. State: `_activeTreeRootId`, `_activeTreeNodeId`.
- **Pane 3 (Market Summary, 350px):** Owns company list exclusively — checkbox-based selection (max 3), validation badges (valid/limited/skipped), Send to Research bar with lens dropdown. Shows breadcrumb navigation (`_buildBreadcrumb()`) when viewing a child campaign in a tree.
- **Pane 4 (Company Detail, flex):** Discovery view: "Why this company?" + source evidence with type badges + **"Find Similar" button** (`runFindSimilar()`) for company-anchored recursive discovery. Scored view: lens score ring, dimension cards, playbook. No Send to Research button (selection in Pane 3 only). Ancestry badges on company cards for tree context.

**Pipeline Tree component** — shared `renderPipelineTree(nodes, container)` renders universal tree nodes with schema `{id, parent_id, label, status, kind, icon, iconBg, summary, detail, children[]}`. CSS restyled as visual flowchart: `.ptree-card` stage cards with colored left borders (green=done, blue=cached, purple=running, red=error), `.ptree-arrow` connectors between cards (gradient line + CSS triangle arrowhead), `.ptree-mini` mini-cards for data sources. **Horizontal fan-out**: sources branch horizontally from parent stage via `.ptree-fanout` layout (vertical line → `.ptree-fanout-rail` horizontal rail → individual `.ptree-mini` cards with tick connectors). Running cards get `ptree-pulse` animation. Collapsible detail on click. Used by:
- `_discoverLogToTree()` — converts Discover `execution_log` → tree nodes grouped by source type (web/news/reddit). Search mini-cards expand to show individual result links (title + URL + source/date metadata) per query. AI Extraction mini-cards show each extracted company with description, size, website, and "why included" rationale. Uses `_richDetail` flag for HTML-safe rendering (clickable links).
- `_buildToolStepsTree()` — parses Research chat `tool_progress` strings by `[agent]` prefix into tree stages (bridge/fallback for agents without structured progress)
- `_structuredStepsToTree()` — converts `structuredSteps[]` (from `progress_cb` events) into proper PipelineTree nodes, grouping by analysis_type with mini-card fan-out per data source. Preferred over bridge parser when `structuredSteps` available.

**Fullscreen execution overlay** — `.exec-overlay` fullscreen dark overlay (z-index 9999, backdrop blur) opens via "View Execution →" link on completed analysis tool bubbles in chat. Shows flowchart at 1200px max-width with scaled-up nodes (18px labels, 38px icons). Non-interactive cards (pointer-events:none, no hover, no chevron). Close via X button, click outside, or Escape key. `openExecOverlay(msgIdx)` prefers `structuredSteps` over bridge parser; `closeExecOverlay()` cleans up.

**Structured progress events** — `tool_progress` SSE handler detects `event.structured === true` (from all 8 agents via `_structured_cb`). Structured events stored in `chat.messages[i].structuredSteps[]` (separate from flat `steps[]`). All events include `detail` fields with actual result data (search titles/URLs, extracted metrics, patent titles, SEO signals, etc.) making pipeline tree mini-cards clickable. Live DOM updates render structured events with status icons (checkmark=done, dash=skipped, x=error, play=running), source labels, and summaries. Completed tree tools show compact bubble + "View Execution →" link (no inline flowchart); running tools keep flat step list during execution; non-tree tools keep flat step list on expand. Scrollbar on `.tool-progress-log` inside bubble (moved from `.tool-group` wrapper), max-height 320px with styled purple scrollbar.

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
| PATCH/DELETE | `/api/reports/<filename>` | Update metadata / Delete report |
| PATCH | `/api/dossiers/<name>` | Update dossier metadata (sector, description) |
| DELETE | `/api/analyses/<id>` | Delete individual analysis |
| GET | `/api/llm-usage` | LLM usage stats (today + all-time) |
| GET | `/api/llm-health` | LLM provider health check |
| GET | `/api/dossiers` | List all dossiers (default `hide_empty=1` filters Discover stubs; pass `?hide_empty=0` for all) |
| GET | `/api/dossiers/<name>` | Get dossier detail (includes analyses, events, briefing_json) |
| POST | `/api/dossiers/merge` | Merge two dossiers (moves all data from `merge` into `keep`, deletes merged) |
| POST | `/api/dossiers/<name>/events` | Add timeline event |
| GET | `/api/dossiers/<name>/hiring-snapshots` | Get hiring snapshot history for temporal trends |
| POST | `/api/dossiers/<name>/briefing` | Generate intelligence briefing |
| GET | `/api/dossiers/<name>/pdf` | Export intelligence briefing as styled PDF |
| GET | `/api/icp-profiles` | List all ICP profiles |
| GET | `/api/icp-profiles/<id>` | Get single ICP profile |
| POST | `/api/icp-profiles` | Create ICP profile |
| PUT | `/api/icp-profiles/<id>` | Update ICP profile |
| DELETE | `/api/icp-profiles/<id>` | Delete non-default ICP profile |
| POST | `/api/icp-profiles/<id>/activate` | Set ICP profile as active |
| POST | `/api/icp-profiles/generate` | LLM-generate config from survey answers |
| GET | `/api/ua-targets` | List scored prospects (legacy, sorted by score desc) |
| POST | `/api/dossiers/<name>/ua-fit` | Score company against active ICP (legacy) |
| POST | `/api/ua-pipeline` | SSE pipeline: discover + validate (streaming progress, accepts context, seed_company, parent_campaign_id; depth max 3) |
| POST | `/api/send-to-research` | Send selected companies (max 3) from Discover to Research |
| GET | `/api/lenses` | List all lenses |
| GET | `/api/lenses/<id>` | Get single lens with full config |
| POST | `/api/lenses` | Create a new lens |
| POST | `/api/lenses/generate` | LLM-generate a lens config from name + description |
| PUT | `/api/lenses/<id>` | Update a lens config |
| DELETE | `/api/lenses/<id>` | Delete a non-preset lens |
| POST | `/api/dossiers/<name>/score-lens` | Score company through a lens |
| GET | `/api/dossiers/<name>/lens-scores` | Get all lens scores for a company |
| GET | `/api/campaigns` | List root campaigns with children tree + prospects (includes `execution_log` from detail) |
| GET | `/api/campaigns/<id>` | Single campaign with prospects + insight |
| GET | `/api/campaigns/<id>/tree` | Full recursive tree of campaigns rooted at id |
| PATCH | `/api/campaigns/<id>` | Rename campaign |
| DELETE | `/api/campaigns/<id>` | Delete campaign (cascades to children) |
| PATCH | `/api/campaign-prospects/<cid>/<did>` | Update prospect status |
| POST | `/api/campaigns/<id>/insight` | Generate vertical insight |
| POST | `/api/campaigns/<cid>/prospects/<name>/brief` | Generate outreach brief |
| GET | `/api/companies` | List all companies (default `hide_empty=1` filters Discover stubs; pass `?hide_empty=0` for all) |
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
- **dossiers:** id, company_name (UNIQUE NOCASE), sector, description, briefing_json, briefing_generated_at, briefing_model, ua_fit_score, ua_fit_label, ua_fit_json, ua_fit_generated_at, icp_profile_id, created_at, updated_at
- **dossier_analyses:** id, dossier_id (FK), analysis_type, report_file, key_facts_json, model_used, created_at
- **dossier_events:** id, dossier_id (FK), event_date, event_type, title, description, source_url, data_json, created_at

### Temporal Analysis
- **hiring_snapshots:** id, company_id (FK), snapshot_date, total_roles, dept_counts, subcategory_counts, seniority_counts, strategic_tag_counts, ai_ml_role_count, growth_signal_ratio, top_skills, top_locations, created_at — UNIQUE(company_id, snapshot_date)

### Lens System
- **lenses:** id, name, slug (UNIQUE), description, dimensions_json (array of {key, label, weight, rubric}), created_at, updated_at
- **lens_scores:** id, lens_id (FK), dossier_id (FK), overall_score, tier_label, score_data (JSON), created_at, updated_at — UNIQUE(lens_id, dossier_id)

### Prospecting Campaigns
- **campaigns:** id, niche, name, top_n, status, insight_json, parent_campaign_id (FK → campaigns, nullable — enables recursive discovery trees), seed_company (TEXT, nullable — company name that spawned a "Find Similar" child), execution_log_json (TEXT — search events with per-result metadata `{title, url, source?, date?}`, AI extraction events with full `company_details` `[{name, website, description, estimated_size, why_included}]`, validation events, seed profile), created_at, updated_at
- **campaign_prospects:** id, campaign_id (FK), dossier_id (FK), validation_status, prospect_status, brief_json, created_at

### ICP Profiles (Dormant)
- **icp_profiles:** id, name, description, is_default, is_active, survey_answers_json, config_json, created_at, updated_at
  - `config_json` is the single source of truth: dimensions (key, label, weight, rubric, signal_queries), labels, discovery_filters, icp_definition, suggested_niches
  - Default "Universal Ads ICP" profile auto-created via `ensure_default_icp_profile()` on first run
  - 8 DB helpers: create/update/delete/set_active/get_active/get/get_all/ensure_default

### LLM Usage Tracking
- **llm_usage:** id, model, provider, prompt_tokens, completion_tokens, total_tokens, latency_ms, analysis_type, company_name, status, error_message, created_at

## Current State (April 2026)

Fully functional with 12 analysis types, agentic chat with 5 LLM providers and 17+ model fallbacks, dossier system with change detection, hiring temporal analysis via snapshots, context-aware company-scoped chat with multi-step context management (tool result summarization, dynamic tool schema selection, condensed system prompts), server-side PDF export (reports + briefings), and intelligence briefing with hybrid algorithmic+LLM Digital Maturity Score. Two modules via vertical sidebar: **Market Research** (three-pane layout for analysis, dossiers, chat) and **Prospecting** (two-phase workflow: Discover + Research with lens-based scoring). The **lens system** (`lenses` + `lens_scores` tables) replaces hardcoded CTV scoring — configurable evaluation frameworks with custom dimensions, weights, and rubrics. Default "CTV Ad Sales" lens preserves the original 5-dimension scoring. Discovery supports both niche-based search (8-12 targeted queries from structured Niche Builder context) and company-anchored "Find Similar" mode (recursive discovery trees up to depth 3, using `_profile_lookup` for profile-aware queries). Users select up to 3 companies and send to Research for lens-based scoring. **Discovery trees** form parent-child campaign hierarchies navigable via tree visualization in Pane 2 with breadcrumb navigation. **Pipeline Tree** is a shared visualization component (`renderPipelineTree()`) restyled as a visual flowchart — stage cards with colored left borders, arrow connectors (gradient line + CSS triangle), and horizontal fan-out for data sources. Used for both discovery execution logs and chat tool progress. Chat tools now emit `progress_callback` steps for search operations (web, Reddit, HN, YouTube). **Structured progress callbacks** on all 8 agents (financial, sentiment, techstack, competitors, patents, seo, pricing + llm/save_to_dossier) emit per-source events (`source_start`, `source_done`, `generating`, `report_saved`) with `detail` fields via `_structured_cb` bridge in `web/app.py`, rendered as live status-icon progress in chat tool bubbles. Detail fields contain actual result data (search titles/URLs, metrics, patent titles, SEO signals, etc.) making pipeline tree mini-cards clickable. `_structuredStepsToTree()` converts structured events into proper tree nodes grouped by analysis type. **Fullscreen execution overlay** (`.exec-overlay`) opens from "View Execution →" on completed chat tool bubbles to show the flowchart at 1200px max-width with scaled-up nodes. Discover module flowchart fixed — `list_campaigns()` now copies `execution_log` from campaign detail to response. **Dossier data quality**: `_find_similar_dossier()` fuzzy matching (0.85 threshold via `difflib.SequenceMatcher`) prevents duplicate dossiers from typos/spelling variants; `merge_dossiers()` function + `POST /api/dossiers/merge` route for manual deduplication; `get_all_dossiers(hide_empty=True)` default filters out Discover stubs with 0 analyses (pass `?hide_empty=0` to see all). **SEC EDGAR company aliases**: `COMPANY_ALIASES` dict in `scraper/sec_edgar.py` maps 26 brand names to SEC filing entities (Google->Alphabet, Meta->Meta Platforms, Amazon->Amazon.com, etc.); known non-SEC companies (Samsung) map to None for early exit. Chat tools `ua_fit_score` and `get_ua_targets` are aliased to the lens system with legacy fallback. CTV-specific labels removed from UI (dynamic lens names). ICP Wizard system dormant but preserved. The briefing remains the flagship feature — it transforms raw intelligence into a consulting partner-ready document that identifies digital transformation opportunities with section-to-source citation mapping and engagement opportunity prioritization. **Execution log auditability**: Discovery `search_done` events now include per-result metadata (`{title, url, source?, date?}`) via `_result_items()` helper; `extracted` events include full `company_details` (name, website, description, estimated_size, why_included). Frontend renders search results as clickable links under each query in mini-card detail panels, and extracted companies as individual mini-cards with expandable descriptions. `_richDetail` flag enables HTML-safe rendering in `_renderCard()`. Report filename sanitization uses `re.sub(r'[^\w\-]', '_', ...)` to prevent crashes from special characters (quotes, colons, etc.) in niche strings.

## Planned Improvements

- **Temporal analysis smarts**: Currently `get_previous_key_facts()` compares against the immediately prior run regardless of date. Same-day re-runs produce noise (spurious "changes" from LLM extraction variance, or no-op comparisons). Improvements: skip temporal injection if previous analysis is from the same day; compare against the oldest/first analysis to show long-term trends; add a minimum time gap (e.g. 24h) before flagging changes as significant.
- **Multi-source job collection**: Primary ATS + LinkedIn supplement is implemented, but could expand to scrape multiple ATS boards if a company uses more than one (e.g. Greenhouse for engineering + Workday for corporate).
- **Briefing diff view**: Side-by-side comparison of two briefings for the same company to visually highlight what changed between analysis runs.
