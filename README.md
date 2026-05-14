# Signal Vault

A competitive intelligence platform that scrapes job boards, analyzes financials, maps competitors, and generates consulting-ready intelligence briefings — from the terminal or a three-pane web dashboard.

Built with Python, Flask, and free LLM APIs (Gemini, Groq, Cerebras, Mistral, OpenRouter) with public data sources (SEC EDGAR, PatentsView, DuckDuckGo, Reddit, HackerNews, YouTube, 1Point3Acres).

## Features

### Job Intelligence
- **Auto-detect ATS boards** — Custom APIs (Amazon, Jane Street) → Greenhouse, Lever, Ashby → Workday → LinkedIn fallback
- **LLM classification** — department, seniority, skills, strategic signals
- **Strategic reports** — hiring patterns, growth signals, org structure insights

### Research & Analysis
| Tool | Source | What it does |
|------|--------|-------------|
| `financial` | SEC EDGAR / web search | Revenue, profitability, R&D, cash position (public); funding & valuation (private) |
| `competitors` | Web search + LLM | Competitive landscape, differentiators, market positioning |
| `sentiment` | Web + Reddit + HN + Blind + 1P3A | Employee reviews, workplace culture, interview experiences |
| `patents` | USPTO PatentsView | Innovation areas, IP strategy, filing trends |
| `pricing` | Site crawl + LLM | Pricing tiers, feature matrix, positioning strategy |
| `seo` | Site crawl + LLM | On-page SEO signals, structured data, AI-readiness |
| `techstack` | Site crawl + fingerprinting | Frontend frameworks, analytics, CDN, CMS, marketing tools |

### Company Dossiers
- **Accumulating intelligence** -- all analyses are saved to a per-company dossier with extracted key facts
- **Change detection** -- automatically detects changes between analysis runs (revenue shifts, new competitors, sentiment changes)
- **Timeline events** -- track acquisitions, product launches, leadership changes, funding rounds
- **Intelligence briefings** -- consulting-ready documents with Digital Maturity Score (0-100), engagement opportunity map, budget signals, and competitive pressure assessment

### Web Dashboard
- **Three-pane SPA** -- reports list, chat interface, and report/dossier viewer
- **Context-aware chat** -- automatically scopes conversations to the company you're viewing
- **PDF export** -- server-side styled PDF generation for any report
- **Source popovers** -- priority-ordered key facts displayed on briefing cards

### Utilities
- **Interactive chat** -- natural language interface with tool-calling and 31 tools (ask anything)
- **SQL queries** -- query the job database directly
- **Web search** -- search the web, Reddit, Hacker News, and YouTube for company context

## Architecture

```
competitive-intel-agent/
├── main.py                 # CLI entry point (Click)
├── db.py                   # SQLite schema, migrations, all DB helpers
├── agents/                 # Agent modules (one per tool)
│   ├── llm.py              # LLM provider rotation, generate_text/generate_json, key facts extraction, change detection, save_to_dossier
│   ├── chat.py             # Agentic chat with multi-provider function calling (ChatLLM class)
│   ├── briefing.py         # Intelligence briefing generator (Digital Maturity Score)
│   ├── collect.py          # Job scraping from ATS boards
│   ├── classify.py         # Job classification (department, seniority, strategic tags)
│   ├── analyze.py          # Strategic hiring analysis report
│   ├── financial.py        # SEC EDGAR / web search financial analysis
│   ├── competitors.py      # Competitive landscape mapping
│   ├── sentiment.py        # Employee sentiment analysis
│   ├── patents.py          # Patent portfolio analysis
│   ├── pricing.py          # Pricing strategy analysis
│   ├── seo.py              # SEO & AEO audit
│   ├── techstack.py        # Technology stack detection
│   ├── profile.py          # Full company profile (runs financial + competitors + sentiment + patents)
│   └── compare.py          # Head-to-head comparison + landscape analysis
├── scraper/                # Data collection modules
│   ├── ats_api.py          # Greenhouse, Lever, Ashby APIs
│   ├── custom_api.py       # Custom company APIs (Amazon, Jane Street) with extensible registry
│   ├── detect.py           # ATS auto-detection: custom APIs → Greenhouse/Lever/Ashby → Workday → LinkedIn
│   ├── linkedin.py         # LinkedIn guest API scraper
│   ├── workday.py          # Workday ATS API scraper
│   ├── sec_edgar.py        # SEC EDGAR XBRL API client
│   ├── stock_data.py       # Stock price data via yfinance
│   ├── patents.py          # USPTO PatentsView + Google Patents
│   ├── site_crawler.py     # Generic website crawler (httpx + BS4)
│   ├── tech_detect.py      # Technology fingerprinting
│   ├── web_search.py       # DuckDuckGo search wrapper (news, web, reddit, youtube)
│   ├── reddit_rss.py       # Reddit RSS feed scraper with comment fetching
│   ├── hackernews.py       # HackerNews Algolia API search + comment fetching
│   ├── onepoint3acres.py   # 1Point3Acres interview experience scraper (Chinese tech community)
│   └── youtube.py          # YouTube search + transcript extraction
├── prompts/                # LLM prompt templates
│   ├── chat.py             # System prompt, condensed prompt, tool schemas + tiered selection for chat agent
│   ├── briefing.py         # Briefing prompt with Digital Maturity scoring rubric
│   ├── classify.py         # Job classification prompt
│   ├── analyze.py          # Strategic report prompt
│   ├── financial.py        # Financial analysis prompts
│   ├── competitors.py      # Competitor mapping prompt
│   ├── sentiment.py        # Sentiment analysis prompt
│   ├── patents.py          # Patent analysis prompt
│   ├── pricing.py          # Pricing analysis prompt
│   ├── seo.py              # SEO audit prompt
│   ├── techstack.py        # Tech stack prompt
│   ├── compare.py          # Comparison prompt
│   └── profile.py          # Executive profile prompt
├── web/
│   ├── app.py              # Flask app factory, API routes, SSE chat endpoint, tool result summarization
│   └── templates/
│       └── base.html       # Entire SPA — HTML + CSS + JS in one file (~3000 lines)
├── reports/                # Generated markdown reports (gitignored)
└── intel.db                # SQLite database (gitignored)
```

**LLM Provider Rotation:** 5 providers with 17+ model fallbacks. Report generation uses Gemini (primary, multi-key rotation) -> Groq -> Cerebras -> Mistral -> OpenRouter (free models). The chat interface uses Gemini (primary, native function calling) -> Groq -> Cerebras -> Mistral -> OpenRouter, with automatic rate-limit fallback through the chain.

**Chat Context Management:** The chat system uses a multi-step LLM approach to prevent context overflow on smaller models. Tool results are compressed via secondary LLM calls before entering conversation history (user still sees full results). Dynamic tool schema selection drops from 31 tools (~17K chars) on round 1 to 11 follow-up tools (~6K chars) on subsequent rounds. The system prompt swaps from the full version (~9K chars) to a condensed version (~400 chars) after round 1. Net effect: rounds 2+ use ~4K chars of fixed overhead instead of ~26K.

## Setup

### 1. Install dependencies

```bash
cd competitive-intel-agent
pip install -r requirements.txt
```

### 2. Configure API keys

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

| Key | Required | Free? | Get it at |
|-----|----------|-------|-----------|
| `GEMINI_API_KEYS` | Recommended (primary) | Yes | [aistudio.google.com](https://aistudio.google.com) |
| `GROQ_API_KEY` | Recommended | Yes | [console.groq.com](https://console.groq.com) |
| `CEREBRAS_API_KEY` | Optional | Yes | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| `MISTRAL_API_KEY` | Optional | Yes | [console.mistral.ai](https://console.mistral.ai) |
| `OPENROUTER_API_KEY` | Optional | Free tier | [openrouter.ai](https://openrouter.ai) |
| `USPTO_API_KEY` | For patents | Yes | [patentsview.org/apis/keyrequest](https://patentsview.org/apis/keyrequest) |

`GEMINI_API_KEYS` supports comma-separated values for multi-key rotation. You need **at least one** of Gemini, Groq, Cerebras, Mistral, or OpenRouter. Gemini is recommended as the primary provider (best quality for reports, native function calling for chat).

## Usage

### Job Intelligence Pipeline

```bash
# Scrape jobs from a company's ATS board
python main.py collect --company "Stripe"

# Classify all scraped jobs (department, seniority, skills)
python main.py classify --company "Stripe"

# Generate a strategic intelligence report
python main.py analyze --company "Stripe"

# Or run the full pipeline in one shot
python main.py full --company "Stripe"

# Provide a direct ATS URL if auto-detection fails
python main.py collect --company "Datadog" --url "https://careers.datadoghq.com/jobs"
```

### Research & Analysis

```bash
# Financial analysis (SEC EDGAR for public companies, web search for private)
python main.py financial --company "Apple"
python main.py financial --company "Stripe"   # private → web search fallback

# Map the competitive landscape
python main.py competitors --company "Ramp"

# Employee sentiment & workplace culture
python main.py sentiment --company "Google"

# Patent portfolio analysis
python main.py patents --company "Apple Inc."

# Pricing strategy analysis
python main.py pricing --url "https://stripe.com"

# SEO & AEO audit
python main.py seo --url "https://ramp.com" --max-pages 10

# Technology stack detection
python main.py techstack --url "https://stripe.com"
```

### Multi-Company Analysis

```bash
# Full company profile (financial + competitors + sentiment + patents in parallel)
python main.py profile --company "Stripe"

# Compare two companies side by side
python main.py compare --company-a "Stripe" --company-b "Ramp"

# Auto-discover competitors and generate landscape report
python main.py landscape --company "Stripe" --top-n 3
```

### Web Dashboard

```bash
# Launch the web UI at http://localhost:5001
python main.py web
```

### Interactive Chat

```bash
python main.py chat
```

The chat interface understands natural language and can call any tool:

```
You: What's Stripe's competitive landscape look like?
[calling competitor_analysis(company='Stripe')]
Assistant: I've completed a competitive analysis for Stripe. The report has been
saved to reports/stripe_competitors_2026-03-21.md. Here are the key findings...

You: How many engineering jobs does Datadog have?
[calling query_db(sql='SELECT COUNT(*) ...')]
Assistant: Datadog currently has 47 engineering positions listed...

You: Search for recent Ramp funding news
[calling web_search(query='Ramp funding news 2026')]
Assistant: Here's what I found about Ramp's recent funding...
```

### All Commands

```
Usage: main.py [COMMAND]

Commands:
  collect      Scrape all open roles from an ATS board
  classify     Classify all unclassified jobs for a company
  analyze      Generate a strategic intelligence report
  full         Run the full pipeline: collect → classify → analyze
  financial    Run a financial analysis (SEC EDGAR / web search)
  competitors  Map the competitive landscape for a company
  sentiment    Analyze employee sentiment and workplace culture
  patents      Analyze a company's patent portfolio (USPTO data)
  pricing      Analyze a website's pricing strategy and product tiers
  seo          Run an SEO & AEO audit on a website
  techstack    Detect and analyze a website's technology stack
  profile      Run a complete company profile (all analyses at once)
  compare      Compare two companies side by side
  landscape    Auto-discover competitors and generate landscape analysis
  chat         Interactive chat — ask questions in plain English
  web          Launch the web dashboard
```

## Reports

All reports are saved as markdown files in the `reports/` directory, named:
```
reports/{company}_{analysis_type}_{YYYY-MM-DD}.md
```

Reports work great with [Obsidian](https://obsidian.md) — just point a vault at the `reports/` folder.

## Database

All data is stored in SQLite (`intel.db`) with 7 tables:

**Job Intelligence:**
- **companies** -- company metadata, ATS info, seniority framework
- **jobs** -- scraped job postings (title, department, location, description, salary)
- **classifications** -- LLM-generated labels (department category/subcategory, seniority, skills, strategic signals/tags)

**Company Dossiers:**
- **dossiers** -- one row per company (company_name UNIQUE NOCASE), accumulates intelligence, stores briefing JSON
- **dossier_analyses** -- one row per analysis run (links to dossier, stores report_file + key_facts_json + model_used)
- **dossier_events** -- timeline events (change_detected, manual notes, acquisitions, etc.)
- **hiring_snapshots** -- periodic captures of hiring stats for temporal trend analysis

Query the database directly:
```bash
python main.py chat
You: how many companies have we analyzed?
[calling query_db(sql='SELECT COUNT(*) FROM companies')]
```

## License

MIT
