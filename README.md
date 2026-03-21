# Competitive Intelligence Agent

A CLI-powered competitive intelligence platform that scrapes job boards, analyzes financials, maps competitors, and generates strategic reports — all from your terminal.

Built with Python, free LLM APIs (Groq, Mistral, Gemini), and public data sources (SEC EDGAR, PatentsView, DuckDuckGo).

## Features

### Job Intelligence
- **Auto-detect ATS boards** — Greenhouse, Lever, Ashby, with LinkedIn fallback
- **LLM classification** — department, seniority, skills, strategic signals
- **Strategic reports** — hiring patterns, growth signals, org structure insights

### Research & Analysis
| Tool | Source | What it does |
|------|--------|-------------|
| `financial` | SEC EDGAR / web search | Revenue, profitability, R&D, cash position (public); funding & valuation (private) |
| `competitors` | Web search + LLM | Competitive landscape, differentiators, market positioning |
| `sentiment` | Web search + LLM | Employee reviews, workplace culture, Glassdoor themes |
| `patents` | USPTO PatentsView | Innovation areas, IP strategy, filing trends |
| `pricing` | Site crawl + LLM | Pricing tiers, feature matrix, positioning strategy |
| `seo` | Site crawl + LLM | On-page SEO signals, structured data, AI-readiness |
| `techstack` | Site crawl + fingerprinting | Frontend frameworks, analytics, CDN, CMS, marketing tools |

### Utilities
- **Interactive chat** — natural language interface with tool-calling (ask anything)
- **SQL queries** — query the job database directly
- **Web search** — search the web for any company context

## Architecture

```
competitive-intel-agent/
├── main.py                 # CLI entry point (Click)
├── db.py                   # SQLite setup + helpers
├── agents/                 # Agent modules (one per tool)
│   ├── collect.py          # Job scraping
│   ├── classify.py         # LLM classification
│   ├── analyze.py          # Strategic report generation
│   ├── chat.py             # Interactive chat with tool-calling
│   ├── financial.py        # SEC EDGAR + private company analysis
│   ├── competitors.py      # Competitive landscape mapping
│   ├── sentiment.py        # Employee sentiment analysis
│   ├── patents.py          # Patent portfolio analysis
│   ├── pricing.py          # Pricing strategy analysis
│   ├── seo.py              # SEO & AEO audit
│   └── techstack.py        # Technology stack detection
├── scraper/                # Data collection modules
│   ├── ats_api.py          # Greenhouse, Lever, Ashby APIs
│   ├── detect.py           # ATS type auto-detection
│   ├── linkedin.py         # LinkedIn guest API scraper
│   ├── sec_edgar.py        # SEC EDGAR XBRL API client
│   ├── patents.py          # PatentsView API client
│   ├── site_crawler.py     # Generic website crawler
│   ├── tech_detect.py      # Technology fingerprinting
│   └── web_search.py       # DuckDuckGo search wrapper
├── prompts/                # LLM prompt templates
│   ├── chat.py             # System prompt + tool schemas
│   ├── classify.py         # Job classification prompt
│   ├── analyze.py          # Strategic report prompt
│   ├── financial.py        # Financial analysis prompts
│   ├── competitors.py      # Competitor mapping prompt
│   ├── sentiment.py        # Sentiment analysis prompt
│   ├── patents.py          # Patent analysis prompt
│   ├── pricing.py          # Pricing analysis prompt
│   ├── seo.py              # SEO audit prompt
│   └── techstack.py        # Tech stack prompt
├── reports/                # Generated markdown reports
└── intel.db                # SQLite database
```

**LLM Provider Rotation:** Each agent tries Groq → Mistral → Gemini in order, falling back automatically if one fails. The chat interface uses Groq and Mistral (which support OpenAI-compatible function calling).

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
| `GROQ_API_KEY` | Yes (for chat) | Yes | [console.groq.com](https://console.groq.com) |
| `GEMINI_API_KEYS` | Recommended | Yes | [aistudio.google.com](https://aistudio.google.com) |
| `MISTRAL_API_KEY` | Optional | Yes | [console.mistral.ai](https://console.mistral.ai) |
| `PATENTSVIEW_API_KEY` | For patents | Yes | [patentsview.org/apis/keyrequest](https://patentsview.org/apis/keyrequest) |
| `CEREBRAS_API_KEY` | Optional | Yes | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| `OPENROUTER_API_KEY` | Optional | Free tier | [openrouter.ai](https://openrouter.ai) |

You need **at least one** of Groq, Mistral, or Gemini for the analysis tools to work. Groq is recommended for the chat interface (best function-calling support).

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

Job data is stored in SQLite (`intel.db`) with three tables:
- **companies** — company metadata and ATS info
- **jobs** — scraped job postings (title, department, location, description, salary)
- **classifications** — LLM-generated labels (department category, seniority, skills, strategic signals)

Query the database directly:
```bash
python main.py chat
You: how many companies have we analyzed?
[calling query_db(sql='SELECT COUNT(*) FROM companies')]
```

## License

MIT
