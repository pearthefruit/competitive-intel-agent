# SignalVault

A competitive intelligence platform. It captures company evidence from public sources, keeps that evidence as the system of record, and turns it into scored assessments you can interrogate — from the terminal or a web dashboard.

Built with Python, Flask, and SQLite, on free LLM APIs (Gemini, Groq, Cerebras, Mistral, OpenRouter) and public data (SEC EDGAR, USPTO, ProPublica, FRED, Reddit, HackerNews, Blind, Google News).

> Working notes and architecture detail live in `CLAUDE.md`. This file is the orientation doc.

## The idea

Most competitive research tools produce a document and stop. SignalVault keeps the **sources** — every filing section, article, job posting, and prior report is chunked and embedded — so any claim can be traced back, re-queried, and contradicted later. Analyses, scores, and briefings are layers on top of that store, not replacements for it.

Three surfaces:

| Module | What it's for |
|---|---|
| **Research** | Analyze one company in depth. Reports, dossiers, chat over captured sources, lens scoring, briefings. |
| **Prospecting** | Find companies. Niche or "find similar" discovery → market sizing → lens scoring on the survivors. |
| **Signals** | Monitor over time. Signals → threads → narratives → causal board, with falsifiable predictions and FRED-bound forecasts. |

## Analyses

Each runs standalone, saves a markdown report, extracts key facts onto the company's dossier, and captures its sources into the RAG store.

| Analysis | Sources | Produces |
|---|---|---|
| `financial` | SEC EDGAR XBRL, 8-K, ProPublica 990, Yahoo Finance, revenue estimators, web | Revenue, margins, cash, growth; estimates for private companies |
| `competitors` | Web, news, Reddit, HN, YouTube | Landscape, differentiators, threat level |
| `sentiment` | Blind, Glassdoor, Fishbowl, Reddit, HN, 1Point3Acres, TikTok, news | Employee sentiment, culture, interview experience |
| `patents` | USPTO / PatentsView, Google Patents | Innovation areas, IP posture, filing trends |
| `techstack` | Site crawl + fingerprinting | Frameworks, analytics, ad pixels, vertical software |
| `ops_maturity` | Targeted path probing | Whether a business runs on systems or on its owner |
| `seo` | Site crawl | On-page SEO, structured data, AI-answer readiness |
| `pricing` | Site crawl | Tiers, feature matrix, positioning |
| `hiring` | ATS boards (Greenhouse, Lever, Ashby, Workday, LinkedIn, custom APIs) | Hiring patterns, org structure, growth signals |
| `executive_signals` | 8-K, filings, web | Leadership changes, investment domains |
| `brand_ad` | Web, ad libraries | Brand and paid-media posture |

Plus `profile` (several at once), `compare` (head-to-head), and `landscape` (auto-discovered competitor set).

## Lenses

A **lens** is an evaluation framework: named dimensions, weights, and rubrics. The same company scores differently through different lenses, and you can build your own in the UI.

Presets: `ctv-ad-sales`, `digital-transformation`, `workforce-management`, `software-investment`, `stock-investment`, `procurement`, `smb-ma`.

Scoring runs the dimensions' required analyses (reusing anything under 7 days old), feeds the reports to the model against the rubric, then **recomputes the weighted overall in Python** — LLM arithmetic is never trusted.

`smb-ma` exists because $1M–$25M private targets break every assumption the rest of the system makes: no filings, no analyst coverage, no ATS board. It leans on ops maturity probing and revenue estimation instead, and carries its own scope guidance so it doesn't quote a Big-4 fee larger than the target's annual profit.

## Source memory (RAG)

Every analysis captures what it read. Sources are deduplicated by identity, chunked, and embedded with MiniLM into SQLite.

- **10-K sections** (Item 1, 1A, 7, 7A, 8) are indexed separately; short sources stay single-chunk.
- **Retrieval spreads across documents** — a 10-K is ~160 chunks and a news article is 1, so flat top-k ranking used to hand every slot to one filing. Per-document and per-type caps fix that.
- **Analysis reports are captured too**, as a clearly-marked *synthesis* tier that can never be mistaken for primary evidence.
- **Chat is retrieval-first**: for a previously-analyzed company the model searches captured sources before touching the web, and the Sources pane pins exactly what each answer used.
- **Sources are rejected, never deleted.** A deleted source gets re-inserted by the next run; a rejected one stays as its own blocklist.

## Signals, predictions, forecasts

The Signals module tracks developing stories: captured signals are assigned to threads (TF-IDF classifier → LLM batch → human review queue), threads compose into narratives, and narratives render on a causal board.

**Predictions** are falsifiable second-order effects — "if X, then Y observable via Z by date D" — generated from signals and threads. Incoming signals are matched against open predictions semantically (MiniLM cosine, not keyword overlap, which measurably fails at this corpus size) and judged as supporting, refuting, or mixed.

**Forecasts** are the scoreable path: yes/no statements bound to a FRED series, with a real probability and a Brier score. The resolution date comes from the release calendar, not the model. Needs `FRED_API_KEY`.

## Setup

```bash
cd competitive-intel-agent
pip install -r requirements.txt
cp .env.example .env      # then fill in keys
```

| Key | Needed for | Free |
|---|---|---|
| `GEMINI_API_KEYS` | Primary provider (comma-separated for rotation) | Yes |
| `GROQ_API_KEY` | Fallback + fast classification | Yes |
| `CEREBRAS_API_KEY` / `MISTRAL_API_KEY` / `OPENROUTER_API_KEY` | Further fallbacks | Yes |
| `USPTO_API_KEY` | Patents (falls back to `PATENTSVIEW_API_KEY`) | Yes |
| `FRED_API_KEY` | Binary forecasts | Yes |
| `WHISPER_ENABLED` / `WHISPER_MODEL` | Transcribing video signals | Local |

At least one LLM provider is required. Calls fan out across every (model × key) combination for a provider before falling through to the next, so one rate limit doesn't stop a run.

## Usage

```bash
python main.py web --port 5001            # dashboard (restart to pick up code changes)
python main.py chat                       # terminal chat with tool calling

python main.py financial --company "Apple"
python main.py sentiment --company "Google"
python main.py techstack --url "https://stripe.com"
python main.py ops-maturity --url "https://example.com" --company "Example"
python main.py profile --company "Stripe"           # several analyses at once
python main.py compare --company-a "Stripe" --company-b "Ramp"
python main.py landscape --company "Stripe" --top-n 3

python main.py full --company "Datadog"             # collect → classify → analyze
python main.py ua-discover --niche "DTC skincare" --top-n 15
python main.py forecast --signal-id 42              # FRED-bound binary forecast
```

Full list: `collect`, `classify`, `analyze`, `full`, `financial`, `competitors`, `sentiment`, `patents`, `techstack`, `ops-maturity`, `seo`, `pricing`, `executive-signals`, `profile`, `compare`, `landscape`, `forecast`, `chat`, `web`.

## Layout

```
competitive-intel-agent/
├── main.py             # Click CLI
├── db.py               # schema, migrations, all DB helpers
├── agents/             # one module per analysis, plus llm.py, chat.py,
│                       #   lens.py, briefing.py, discover.py, niche_eval.py,
│                       #   predictions.py, forecasts.py, source_capture.py,
│                       #   embeddings.py, ops_maturity.py
├── prompts/            # one prompt module per analysis type
├── scraper/            # data collection: ats_api, sec_edgar, patents,
│                       #   site_crawler, tech_detect, ops_detect, blind,
│                       #   fred_api, revenue_estimators, google_news, …
├── web/
│   ├── app.py          # Flask app, API routes, SSE streaming
│   ├── templates/base.html
│   └── static/js/      # 17 SPA modules — no build step
├── extension/          # browser extension for signal + document capture
├── reports/            # generated markdown (gitignored)
└── intel.db            # SQLite (gitignored)
```

The frontend is deliberately buildless vanilla JS. Modules share globals, so **cross-module variables must use `var`, not `let`**.

## Conventions

- Never hardcode API keys — `os.environ.get()` only.
- All LLM calls go through `agents/llm.py`; all prompts live in `prompts/`.
- Every analysis agent ends by calling `save_to_dossier()`, which extracts key facts and captures the report as a source.
- Reports are `reports/{company}_{type}_{YYYY-MM-DD}.md`, and work well pointed at an Obsidian vault.
- No native browser dialogs in the UI — use `_showToast()` / `_showConfirm()` / `_showInlineInput()`.
- Flask runs with `use_reloader=False`; restart for Python changes.

## License

MIT
