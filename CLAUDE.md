# SignalVault — Competitive Intelligence Agent

## What This Is

A competitive intelligence platform that scrapes, classifies, and analyzes company data to produce consulting-ready intelligence briefings. Built as a **portfolio piece** for digital transformation and AI consulting firms (EY Studio+, McKinsey Digital, Deloitte Digital, etc.).

**Value prop:** Help consulting partners identify and qualify digital transformation targets — find companies that need AI, cloud, data, or modernization consulting, score their digital maturity, and map engagement opportunities with estimated scope.

## Stack

- **Backend:** Python, Flask, SQLite (WAL mode)
- **Frontend:** Single-page app in vanilla JS (no framework), Jinja2 template (`web/templates/base.html`)
- **AI:** Multi-provider rotation (Groq, Cerebras, Mistral, Gemini, OpenRouter) with automatic fallback. Three chains: `REPORT_CHAIN` (capable models), `BRIEFING_CHAIN` (Gemini-first for structured JSON), `FAST_CHAIN` (8B-14B models for classification/extraction/query generation).
- **Scraping:** httpx + BeautifulSoup + trafilatura, SEC EDGAR, USPTO patents, Reddit RSS, HackerNews, YouTube transcripts, Google News RSS, Blind, TikTok (yt-dlp), 1Point3Acres
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
5. **Briefing** → hybrid algorithmic + LLM Digital Maturity Score. Algorithm computes base scores from structured data, LLM adjusts ±10 with justification, post-processing recomputes overall. Anomaly detection identifies consulting opportunities.

### Key Architectural Decisions

- **Hybrid DMS scoring:** Deterministic algorithm first (`agents/scoring.py`), then LLM adjustment within bounds (`agents/briefing.py`). Never trusts LLM arithmetic — always recomputes.
- **Chat context management:** Three-pronged approach to prevent context overflow on small models: (1) tool result summarization via secondary LLM, (2) dynamic tool schema selection (31 tools round 1, 11 tools round 2+), (3) condensed system prompt on rounds 2+. Saves ~22K chars per round.
- **LLM-powered discovery queries:** `_build_queries_llm()` in `agents/discover.py` uses `FAST_CHAIN` to decompose complex niche descriptions into targeted search queries. Falls back to template-based generation if LLM fails.
- **Execution log auditability:** Discovery events include per-result metadata (title, URL, source, date) and full company details. Frontend renders as clickable links in pipeline tree mini-cards via `_richDetail` flag.
- **Lens system** (`agents/lens.py`): Configurable evaluation frameworks with custom dimensions, weights, rubrics. Replaces hardcoded CTV scoring. Default "CTV Ad Sales" lens preserved.

### Two Modules

- **Research** — three-pane layout: navigation (Reports/Dossiers/Chat) | chat with SSE streaming + tool execution | report/dossier/briefing viewer
- **Prospecting** — four-pane layout: niche input + campaign sidebar | execution engine (pipeline tree flowchart) | market summary (company selection) | company detail. Two-phase: Discover (LLM-powered search) → Research (lens-based scoring). Supports recursive "Find Similar" discovery trees (max depth 3).

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

- `agents/ua_fit.py` / `prompts/ua_fit.py` — legacy ICP scoring, superseded by lens system. `validate_websites()` still used. DB columns `ua_fit_json`, `ua_fit_generated_at` preserved for backward compat.
- Chat tools renamed from `ua_*` prefix: `discover_prospects`, `score_prospect`, `get_scored_prospects`
- CLI commands still use `ua-discover`, `ua-fit`, `ua-pipeline` names
- ICP Wizard system (`icp_profiles` table, 5-step survey modal) dormant but preserved

## Planned Improvements

- **Temporal analysis smarts**: Skip same-day comparisons, compare against oldest analysis for long-term trends, minimum 24h gap before flagging changes
- **Multi-source job collection**: Multiple ATS boards per company
- **Briefing diff view**: Side-by-side comparison between analysis runs
