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

### Agent Source Memory (RAG)

**Status:** BUILT (2026-05-19); source-of-record overhaul 2026-07-12 — 10-K section capture fixed (was silently broken: 5MB cap + dead anchor parsing meant zero 10-Ks ever indexed), `source_type` canonicalized (`CANONICAL_SOURCE_TYPES` in source_capture.py; publisher names → `metadata.publisher`; migration `migrate_source_types.py`), chat is retrieval-first over captured sources with `[¹](source:ID)` citations, and captured 10-Ks auto-bridge into the Documents module (`ensure_filing_document` in db.py, `file_type='sec_filing'`).

A source capture + embedding layer scoped to the Research module. Agents save raw source content at run time; users interrogate it via "Source Mode" chat in the right pane.

- **Files:** `agents/source_capture.py` (dedup + insert + embed), hook in `agents/financial.py` via `source_cb` param
- **Schema:** `source_documents`, `source_sections` (Item 1/1A/7/7A/8 for 10-Ks stored separately), `source_chunks` (embeddings)
- **Embeddings:** MiniLM, SQLite BLOBs, numpy flat search. Short sources (<600 words) stored as single chunk; 10-Ks section-indexed.
- **Dedup:** by source identity (10-K: company+fiscal_year; 8-K: accession_number; other: URL hash)
- **Chat:** `search_sources` tool, scoped to one company. Source Mode suppresses all other agent tools.
- **UI:** Sources tab in Research right pane → "Chat with these sources" → Source Mode header banner
- **Capture coverage:** all seven analysis agents call `capture_and_embed` — financial, sentiment, competitors, patents, techstack, seo, pricing — plus hiring via `_capture_hiring_sources()` in `analyze.py`. (The old "Phase 2 sentiment / Phase 3 competitors TODO" note was stale; both have been wired for some time.)
- **Retrieval diversity** (`_select_diverse` in `source_capture.py`): chunk counts are wildly uneven by source type — a 10-K averages ~160 chunks, a news article or patent exactly 1. Flat top-k ranking therefore returned **2.3 documents / 1.9 source types on average, with 6.5 of 8 slots from a single document** (measured over 10 real queries across HPE/Oracle/Mastercard/DocuSign/Dave/StubHub); in 5 of 10 cases all 8 slots came from one document. `MAX_CHUNKS_PER_DOC = 3` / `MAX_CHUNKS_PER_SECTION = 2` raise that to **4.5 docs / 3.3 types** for 0.023 of mean cosine (0.493 → 0.470). Thresholding happens *before* selection, and unfilled slots backfill from capped-out chunks, so the caps reshape ranking without ever shrinking the result. Where a company's corpus is genuinely one document the caps correctly change nothing — that is a coverage problem, not a ranking one.
- **Coverage gap (2026-07-30):** 232 of 508 dossiers have been analyzed; only **35 have sources**. The other 197 were analyzed before RAG shipped (~2026-05-14), so retrieval-first chat silently finds nothing and falls back to web search for them. Recoverable without network: 851 report `.md` files on disk, and 46 sourceless dossiers whose job postings are still in the local `jobs` table. 146 sourceless dossiers had a financial analysis and are SEC-reachable. Note `backfill_10k_sources.py` gates on "has `sec_xbrl`, no `sec_10k`", which structurally cannot reach those 146.
- Storage estimate: ~1MB per company per full financial run

### Documents Module

**Status:** BUILT (2026-05-24, buggy). Full spec at `memory/signalvault-documents-spec.md`.

A reading and capture surface for long-form research documents. User reads → highlights passages → annotations become threads. The module stays thin — synthesis happens through existing threads/narratives/chains.

- **Supported types:** PDF (PyMuPDF), Markdown, plain text, DOCX (python-docx), EPUB (ebooklib), email (extension-extracted HTML), sec_filing (auto-bridged from captured 10-Ks — green "10-K" badge, "View on EDGAR" link, no file affordances)
- **Storage modes:** Reference (opens from original path) or Stored (vault copy at `documents/{id}_{slug}.{ext}`). Emails always stored.
- **Schema:** `documents` (title, source, year, file_type, file_path, stored_path, extracted_text_json), `document_annotations` (selected_text, note, section_index, thread_id)
- **Extraction:** all formats produce `extracted_text_json` — array of `{index, label, text}` sections
- **Annotation → Thread flow:** select text → popover → LLM generates thread title (non-blocking) → thread created with `[document]` source tag
- **Email ingestion:** extension detects Gmail (Phase 1), Substack/Outlook (Phase 2). Mode switcher in popup: Signal | Document. Extracts subject/sender/body HTML → sectioned by H1-H3 headings → `<hr>` splits → paragraph blocks.
- **API:** `POST /api/documents`, `GET /api/documents`, `GET /api/documents/<id>`, `POST /api/documents/<id>/annotations`, etc.
- **Embeddings:** MiniLM (same stack as Source RAG). `backfill_embeddings.py` for retroactive indexing.
- **Phase 2 (TODO):** "Propose narratives" button — LLM clusters document threads into narrative stubs
- **Phase 3 (TODO):** PDF.js rendering (layout-faithful, bounding-box annotations)

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

- **Predictions System** (WORKING as of 2026-07-19): Falsifiable second-order effects generated from signals/threads/narratives — "if X, then Y observable via Z by date D." Backend `agents/predictions.py`, frontend `web/static/js/predictions.js`, schema `predictions` + `prediction_evidence`. Predictions tab revived 2026-07-19 (`d10bae2`) with detail in the shared right pane — the earlier "rebuild as ribbon, not tab" note is obsolete. Lifecycle engine (`3c05aae`): date-anchored prompts, 14d-grace expiry sweep, overdue state, auto-resolution suggestions. Evidence matching uses `semantic_candidates()` — MiniLM cosine at `MIN_MATCH_SIMILARITY = 0.50` over `predictions.claim_embedding`, top-5 cap. Raised from 0.45 after an A/B showed the judge calls nearly every 0.45–0.50 pair 'unrelated' (cost with no evidence yield). **Do not revert this to keyword/IDF overlap: measured at 120 signals × 136 predictions, lexical ranking is uncorrelated with topic and no threshold fixes it — IDF is meaningless at this corpus size.** Backfill embeddings with `backfill_prediction_embeddings.py`. Scan/feed fan-out is wired (`/api/signals/scan` drains the `signals.predictions_matched_at` queue via `match_pending_signals_async`); retro-matching is built (Phase 2c, `retro_match_prediction`, called from both generators via `_retro_match_new`). Remaining: narrative scorecards, board ghost nodes.

  **The qualitative path is not calibration-scoreable — by construction.** `expected_by` is `today + horizon_days` where the LLM picks `horizon_days` freely (prompt guidance is just "30-180 days realistically"), so deadlines have no external referent — the 14d grace window exists to absorb that. And `confidence` is an ordinal `1-5`, not a probability, so no proper scoring rule applies. The ~174 existing predictions are retroactively unscoreable. This is fine — that path is for linking and narrative evidence, not for a track record. Full spec at `memory/signalvault-predictions-spec.md`.

- **Binary Forecasts** (BUILT 2026-07-19, needs `FRED_API_KEY`): the Brier-scoreable prediction path. `agents/forecasts.py` + `prompts/forecasts.py`, CLI `python main.py forecast [--signal-id N] [--resolve] [--score]`. Shares the `predictions` table, discriminated by `resolution_kind`: `NULL`/`'llm_judge'` = existing qualitative rows, `'series'` = binary forecasts. A forecast is a yes/no statement about a FRED series ("UNRATE above 4.3% in the 2026-10-01 observation") with a real `probability` 0-1; resolution is a number fetch, and `brier_score` is stored per row.
  - **The date comes from the release calendar, not the model** — that is the whole point. `target_period` is the observation date; `expected_by` is only an estimate of when it publishes.
  - **Series are picked from a fixed catalog** (`scraper/fred_api.KEY_INDICATORS`, 15 series) and the prompt is shown each series' *current value*. Both constraints are load-bearing: free-form IDs hallucinate, and a model that cannot see the current level picks thresholds that are already settled — those score perfectly and mean nothing. `build_catalog()` drops any series it cannot get a live value for; no key → empty catalog → generation no-ops rather than forecasting blind.
  - **`basis` — level vs. percent change.** A per-series property in `_BASIS`, never the model's choice. `'level'` for mean-reverting rates/ratios/spreads (UNRATE, FEDFUNDS, DGS10, VIXCLS, ICSA, HOUST, UMCSENT, DEXUSEU, T10YIE, BAMLH0A0HYM2); `'change_pct'` for trending index levels and cumulative counts (CPIAUCSL, PAYEMS, GDP, RSXFS, INDPRO). **Why this exists:** the first CPI forecast the system produced was "CPI below 333.0" against a 332.568 baseline at 75% — two months of ordinary inflation breaks that on drift alone, so it was a near-certain miss dressed as a considered call. On a trending series a level threshold near the current value is decided by drift, not by the signal. Forecasting the period-over-period change is also what real forecasters do; nobody predicts the CPI index level. The prompt renders the catalog in two clearly separated groups and shows change-basis series their recent period-over-period moves (not just the level) so thresholds anchor on the change distribution. Resolution computes the change from the prior observation; `resolved_value` holds the compared quantity, with `resolved_level` and `prior_value` kept for audit.
  - **Rows with `basis` NULL predate this split and resolve as level forecasts.** Do not backfill them to a change basis — reinterpreting a forecast after the fact is how a calibration record stops meaning anything. Same reason a forecast you have come to doubt gets left in place to resolve (#175 is exactly this).
  - `_validate()` rejects bad forecasts (unknown series, probability out of range, past target period) rather than repairing them — a repaired forecast is one nothing actually predicted.
  - **Returning zero forecasts is a normal outcome** — most signals bear on no macro series. But an empty list from the model and an LLM outage must never collapse into the same result: `generate_json` returns `None` when every provider fails, so the naive `(result or {}).get("forecasts", [])` reports a total outage as "the model considered this and declined." That drills holes in the calibration record that look like conservatism rather than downtime. Provider failure now raises `ForecastUnavailable`; only a real `{"forecasts": []}` counts as a decline. This bit during first testing — every signal appeared to decline while the providers were simply down.
  - Two integration points: series rows leave `claim_embedding` NULL so `semantic_candidates()` already excludes them from the evidence judge (no change needed); `sweep_expired_predictions()` was changed to skip `resolution_kind='series'` — expiring a forecast because a release ran late would bias the Brier score toward whatever publishes on time.
  - Not yet wired: no auto-generation on capture (cost + most signals don't qualify), no API route, no UI surface, no resolver cron. Generation is untested end-to-end pending a FRED key; schema/resolution/scoring/sweep-isolation are tested.
- **Thread naming and dedup**: titles too generic (e.g. "Labor Market Trends" duplicated); fuzzy dedup misses same-domain near-dupes
- **Keyboard nav — `e` key**: edit signal body in Global Signals module (all other keys built)
- **Documents module bug fixes**: module is functional but buggy (2026-05-24)
- **Source RAG Phase 2**: sentiment agent (Reddit, Blind, news)
- **Source RAG Phase 3**: competitors agent
- **Temporal analysis smarts**: Skip same-day comparisons, compare against oldest analysis for long-term trends, minimum 24h gap before flagging changes
- **Multi-source job collection**: Multiple ATS boards per company
- **Briefing diff view**: Side-by-side comparison between analysis runs
- **Timeline Levels 2-3**: Thread lifecycle bars with range selector (L2), causal timeline with predictions (L3) — see `knowledge/signals-module/timeline-plan.md`
