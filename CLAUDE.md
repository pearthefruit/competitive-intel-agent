# SignalVault — Competitive Intelligence Agent

## What This Is

A competitive intelligence platform that scrapes, classifies, and analyzes company data to produce consulting-ready intelligence briefings. Built as a **portfolio piece** for digital transformation and AI consulting firms (EY Studio+, McKinsey Digital, Deloitte Digital, etc.).

**Value prop:** Help consulting partners identify and qualify digital transformation targets — find companies that need AI, cloud, data, or modernization consulting, score their digital maturity, and map engagement opportunities with estimated scope.

## Stack

- **Backend:** Python, Flask, SQLite (WAL mode)
- **Frontend:** Single-page app in vanilla JS (no framework), Jinja2 template (`web/templates/base.html`)
- **AI:** Multi-provider rotation (Groq, Cerebras, Mistral, Gemini, OpenRouter) with automatic fallback. Three chains: `REPORT_CHAIN` (capable models), `BRIEFING_CHAIN` (Gemini-first for structured JSON), `FAST_CHAIN` (8B-14B models for classification/extraction/query generation).
- **Scraping:** httpx + BeautifulSoup + trafilatura, SEC EDGAR, USPTO patents, Reddit RSS, HackerNews, YouTube transcripts, Google News RSS, Blind, TikTok (yt-dlp), 1Point3Acres
- **ML:** scikit-learn TF-IDF for signal classification (no external API)
- **CLI:** Click-based (`main.py`), also serves web UI via `python main.py web --port 5001`

## Commands

```bash
python main.py web --port 5001          # Web UI (must restart for code changes — use_reloader=False)
python main.py profile --company "X"    # Full company profile (financial + competitors + sentiment + patents)
python main.py chat                     # Interactive chat REPL
python main.py ua-discover --niche "DTC skincare" --top-n 15  # Prospect discovery
```

All analysis commands: `collect`, `classify`, `analyze`, `financial`, `competitors`, `sentiment`, `patents`, `techstack`, `seo`, `pricing`, `compare`, `landscape`, `profile`

## Architecture

### Data Flow

1. **Collect** → scrape ATS job boards → `companies` + `jobs` tables
2. **Classify** → LLM classifies jobs (department, seniority, strategic tags) → `classifications`
3. **Analyze** → 8 analysis agents (financial, competitors, sentiment, patents, techstack, SEO, pricing, hiring) → reports + key facts on dossier. All agents emit structured `progress_cb` events for real-time UI.
4. **Dossier system** → analyses accumulate per company. Key facts extracted as JSON. Changes between runs detected as timeline events. Fuzzy matching (0.85 threshold) prevents duplicate dossiers.
5. **Niche Evaluation** → after discovery + validation, lightweight financial scan of all companies (Yahoo Finance, SEC EDGAR, LLM fallback). Aggregates into market sizing charts (revenue distribution, company size, growth, geography, sectors). Runs as Phase 2.5 in the pipeline with SSE streaming.
6. **Briefing** → hybrid algorithmic + LLM Digital Maturity Score. Algorithm computes base scores from structured data, LLM adjusts ±10 with justification, post-processing recomputes overall. Anomaly detection identifies consulting opportunities.

### Key Architectural Decisions

- **Hybrid DMS scoring:** Deterministic algorithm first (`agents/scoring.py`), then LLM adjustment within bounds (`agents/briefing.py`). Never trusts LLM arithmetic — always recomputes.
- **Chat context management:** Three-pronged approach to prevent context overflow on small models: (1) tool result summarization via secondary LLM, (2) dynamic tool schema selection (31 tools round 1, 11 tools round 2+), (3) condensed system prompt on rounds 2+. Saves ~22K chars per round.
- **LLM-powered discovery queries:** `_build_queries_llm()` in `agents/discover.py` uses `FAST_CHAIN` to decompose complex niche descriptions into targeted search queries. Falls back to template-based generation if LLM fails.
- **Execution log auditability:** Discovery events include per-result metadata (title, URL, source, date) and full company details. Frontend renders as clickable links in pipeline tree mini-cards via `_richDetail` flag.
- **Lens system** (`agents/lens.py`): Configurable evaluation frameworks with custom dimensions, weights, rubrics. Replaces hardcoded CTV scoring. Default "CTV Ad Sales" lens preserved. Prospecting module uses lens scores when available (via `_getScore()` accessor), falls back to UA fit for legacy campaigns. `scoring_lens_id` on campaigns tracks which lens was used; auto-set when companies are scored via lens endpoint.
- **Niche evaluation** (`agents/niche_eval.py`): Bottom-up market sizing from discovered companies. Lightweight financial scan (Yahoo Finance + SEC EDGAR + LLM fallback for private companies) runs in parallel via ThreadPoolExecutor(5). Aggregates into revenue distribution, company size breakdown, growth signals, geography, and sector charts. Stored as `niche_eval_json` on campaigns. Per-company snapshots cached as `financial_snapshot_json` on dossiers for reuse in full research.
- **Three-tier signal assignment**: (1) TF-IDF keyword classifier (`agents/signals_classify.py`) — scikit-learn bigrams, thread titles weighted 3x, auto-assigns high-confidence matches, learns organically from user assignments. (2) LLM batches of 10 for remaining unassigned. (3) Review queue with suggestions, undo, searchable thread dropdown, "+ New thread".
- **Signal pruning** (`POST /api/signals/prune`): SequenceMatcher >=85% title similarity deduplication. Keeps earliest signal, marks dupes as noise (recoverable), transfers thread links to survivor.
- **Unified targeted search** (`POST /api/signals/search`): Hits 6 sources — Google News, DuckDuckGo News, HackerNews, Reddit, Gov RSS keyword-filtered, FRED keyword search.
- **Stacked board highlights**: Multiple entity/keyword highlights layer additively via `_boardHighlights` array with pill tray. "Link N" and "Brainstorm N" action buttons on multi-select.
- **Interactive brainstorm**: `[[double bracket]]` clickable concepts in brainstorm output — inline search feedback, cross-reference board highlights.
- **Timeline strip** (Level 1): `GET /api/signals/timeline` — horizontal SVG below board, thread bars with signal density dots, domain-colored. Levels 2-3 planned.
- **Multi-domain rendering**: `_parseDomains()` + `_renderDomainBadges()` handles pipe-separated domains, split-color board nodes, alias mapping (SOFTWARE_DEVELOPMENT->tech_ai). `sanitize_domain()` in db.py normalizes LLM-produced domains.
- **Native UI helpers**: `_showToast()`, `_showConfirm()`, `_showInlineInput()` — zero browser dialogs remaining (R8).
- **Resizable detail pane**: Drag handle, width persisted to localStorage, default 380px. Dynamic titles per context (Signal/Thread/Narrative/Review Queue).

### Two Modules

- **Research** — three-pane layout: navigation (Reports/Dossiers/Chat) | chat with SSE streaming + tool execution | report/dossier/briefing viewer
- **Prospecting** — four-pane layout: niche input + campaign sidebar | execution engine (pipeline tree flowchart) | market summary (company selection) | company detail. Three-phase: Discover (LLM-powered search) → Niche Evaluation (bottom-up market sizing) → Research (lens-based scoring). Supports recursive "Find Similar" discovery trees (max depth 3) with bidirectional navigation (breadcrumb up, Related Explorations down).

### Pipeline Tree Component

Shared `renderPipelineTree()` renders flowchart cards with horizontal fan-out for data sources. Used by `_discoverLogToTree()` (discovery execution logs), `_structuredStepsToTree()` (chat tool progress), and `_buildToolStepsTree()` (bridge fallback). Fullscreen overlay via `.exec-overlay`.

## Code Conventions

- **NEVER hardcode API keys** — always `os.environ.get()`
- LLM calls go through `agents/llm.py` (`generate_text`, `generate_json`)
- Every analysis agent calls `save_to_dossier()` to persist results + extract key facts
- All prompts live in `prompts/` — one file per analysis type
- Chat tools defined in `prompts/chat.py`, executed in `agents/chat.py`
- Citation format: Perplexity-style clickable superscript links `[¹](url)`
- Flask server runs with `use_reloader=False` — must restart to pick up code changes
- Dark theme always — `#0a0a0a` backgrounds, blue/purple accents, 11-13px body text

## Environment Variables

```
GEMINI_API_KEYS     # Comma-separated (multi-key rotation per model)
GROQ_API_KEY
CEREBRAS_API_KEY
MISTRAL_API_KEY
OPENROUTER_API_KEY  # Free-tier models
USPTO_API_KEY       # Falls back to PATENTSVIEW_API_KEY
```

## Legacy Notes

- `agents/ua_fit.py` / `prompts/ua_fit.py` — legacy CTV-specific ICP scoring, superseded by lens system. `validate_websites()` and `generate_vertical_insight()` still used as fallbacks. DB columns `ua_fit_json`, `ua_fit_generated_at` preserved for backward compat. Prospecting module prefers `lens_score` over `ua_fit` via `_getScore()` helper in frontend.
- Chat tools renamed from `ua_*` prefix: `discover_prospects`, `score_prospect`, `get_scored_prospects`
- CLI commands still use `ua-discover`, `ua-fit`, `ua-pipeline` names
- ICP Wizard system (`icp_profiles` table, 5-step survey modal) dormant but preserved

## Signals Module

Five-tab intelligence monitoring workspace: Signals -> Threads -> Narratives -> Board -> Execution.

### Key API Routes (Signals)
- `GET /api/signals/search` — filter existing signals by keyword
- `POST /api/signals/search` — unified targeted search (6 sources: Google News, DuckDuckGo News, HackerNews, Reddit, Gov RSS, FRED)
- `GET /api/signals/timeline?days=60` — signal density data for timeline strip
- `POST /api/signals/prune` — deduplicate signals (>=85% title similarity)
- `GET/POST /api/signals/review-queue/*` — three-tier assignment review queue

### Thread Splitting
- Minimum 6 signals required (raised from 3)
- Post-LLM validation drops sub-threads with <2 signals

### Board Interactions
- Double-click zoom from board view
- Physics freeze saves node positions
- Click empty space dismisses detail pane (including narratives)
- Entity toggle: click entity chip again to unhighlight board nodes
- Global keyword search bar with pills in board view

### SQLite Threading
- DB connections created inside worker threads for resynthesize (avoids cross-thread errors)

## Planned Improvements

- **Temporal analysis smarts**: Skip same-day comparisons, compare against oldest analysis for long-term trends, minimum 24h gap before flagging changes
- **Multi-source job collection**: Multiple ATS boards per company
- **Briefing diff view**: Side-by-side comparison between analysis runs
- **Timeline Levels 2-3**: Thread lifecycle bars with range selector (L2), causal timeline with predictions (L3) — see `knowledge/signals-module/timeline-plan.md`
