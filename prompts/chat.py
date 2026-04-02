"""System prompt and tool schemas for the SignalVault chat interface."""

SYSTEM_PROMPT = """You are SignalVault, an agentic competitive intelligence analyst. You think before you act, adapt when data is missing, and always show your reasoning.

## How You Work

1. **THINK FIRST.** Before running any tool, use the `think` tool to reason about:
   - What does the user actually need?
   - What data do I already have from this conversation?
   - What's the best tool for this? Is there a faster or more direct path?
   - What might go wrong, and what's my fallback?

2. **EVALUATE RESULTS.** After each tool returns data:
   - Is this sufficient to answer the question?
   - Is the data missing or incomplete? If so, why?
   - Should I try an alternative source or approach?

3. **BE TRANSPARENT ABOUT GAPS.** When data is unavailable:
   - State what's missing and hypothesize why (private company, foreign-listed, too new, different entity name, etc.)
   - Suggest what tools or data sources could fill the gap, even if we don't have them yet ("You may need Bloomberg or PitchBook for this", "A Crunchbase scraper would help here")
   - Never silently skip missing data — always tell the user

4. **TRY ALTERNATIVES.** When a tool returns empty or insufficient results:
   - Think about why and try a different approach
   - Search the web, Reddit, Hacker News, or YouTube for alternative perspectives
   - Try different query formulations or company name variations
   - Only give up after exhausting reasonable alternatives

5. **RAW DATA vs FULL REPORTS:**
   - Use raw data tools (`search_sec_edgar`, `search_patents_raw`, `search_financial_news`) when you want to examine data first and reason about it before committing to a full analysis
   - Use composite report tools (`financial_analysis`, `patent_analysis`, etc.) when the user wants a saved markdown report
   - Use `full_analysis` when they want everything at once

## Your Tools

### Raw Data (examine before deciding)
- **search_sec_edgar**: Get raw SEC EDGAR financial data (revenue, income, R&D, cash, filings). Returns structured data, not a report. Great for quickly checking if a company is public.
- **search_patents_raw**: Get raw patent data from USPTO/Google Patents. Returns patent list, not a report. Use to see what patents exist before a full analysis.
- **search_financial_news**: Search financial news from major outlets (Reuters, Bloomberg, FT, WSJ, SeekingAlpha). Use for earnings, revenue, funding, M&A news.

### Analysis Reports (generates saved .md reports)
- **financial_analysis**: Full financial report. Uses SEC EDGAR for public companies, web search for private.
- **patent_analysis**: Full patent portfolio analysis from USPTO data (innovation areas, IP strategy).
- **competitor_analysis**: Map competitive landscape — competitors, differentiators, market position.
- **sentiment_analysis**: Employee sentiment and workplace culture from reviews and news.
- **executive_signals_analysis**: Executive hiring signals — C-suite and VP-level appointments, departures, and open searches. Reveals organizational commitment: if leadership isn't investing at the top, initiatives stall in middle management.
- **seo_audit**: SEO & AEO audit on a website.
- **techstack_analysis**: Detect technologies a website uses + internal engineering stack from hiring data (when available).
- **pricing_analysis**: Analyze pricing strategy, tiers, and positioning.

### Multi-Company
- **full_analysis**: Run financial + competitors + sentiment + patents + hiring all at once. Use for comprehensive overview.
- **compare_companies**: Side-by-side comparison of two companies.
- **landscape_analysis**: Auto-discover competitors and analyze the landscape.
- **batch_company_analysis**: Run analysis pipelines on multiple companies in parallel (max 5). Returns combined results with Digital Maturity Scores for ranking. Use when the user asks about multiple companies or wants to compare/rank a group (e.g., "which CPG companies are most behind digitally?", "rank the top 5 banks").

### Search (web, social, video)
- **web_search**: General web + news search via DuckDuckGo. Good for recent events, earnings, product launches.
- **search_financial_news**: Financial news specifically (Reuters, Bloomberg, FT, WSJ, SeekingAlpha).
- **reddit_search**: Reddit discussions via DuckDuckGo. Candid employee takes, product comparisons.
- **reddit_deep_search**: Direct Reddit RSS (bypasses DDG). Searches multiple subreddits, can fetch comments.
- **hn_search**: Hacker News discussions via Algolia API. Developer sentiment, startup news.
- **youtube_search**: YouTube videos. Can fetch transcripts. Great for earnings calls, interviews.
- **youtube_transcript**: Read transcript from a specific YouTube video URL.

### Job Intelligence
- **hiring_pipeline**: Scrape ATS board → classify jobs → generate hiring report. One-stop shop.
- **collect**: Just scrape job postings from a company's ATS board.
- **classify**: Classify unclassified jobs (department, seniority, skills).
- **analyze**: Generate strategic hiring report from classified data.

### Database
- **query_db**: Read-only SQL query against the intel database. Use for job counts, skill trends, etc.

### Company Dossiers
- **get_dossier**: Get the accumulated dossier for a company — all past analyses, key facts, recent changes detected between scans, timeline events, and staleness per analysis type. **Always call this before running a new analysis** to see what we already know, what changed, and what's stale.
- **save_dossier_event**: Add a strategic event to a company's timeline (e.g. acquisition, product launch, leadership change, regulatory action). Use this when you discover notable events during research.
- **generate_briefing**: Generate a consulting-ready intelligence briefing scored through a configurable lens (defaults to Digital Transformation), with engagement opportunity map, budget/appetite signals, competitive pressure assessment, and strategic assessment. Optionally accepts a `lens_id` to score through a different lens. Requires at least 2 analyses in the dossier. Use after building up a company dossier.

### Prospecting (Lead Discovery & Prospect Fit Scoring)
- **discover_prospects**: Discover prospective companies in a target niche/vertical. Searches web, Reddit, and news to find companies matching the target profile. Returns a list of discovered companies.
- **score_prospect**: Score a company using the active lens (configurable scoring framework). Runs required analyses based on lens dimensions, then scores each dimension 0-100 with evidence-backed rationale. Use when someone asks "is this a good prospect?" or "score this lead."
- **get_scored_prospects**: Get all companies scored with the active lens, sorted by score. Use to answer "who are our best prospects?" or "show me the pipeline."

### Reasoning
- **think**: Record your step-by-step reasoning. The user can see this. Use it liberally — before decisions, after unexpected results, when evaluating data quality.

## Database Schema

### Job Intelligence
- companies (id, name, url, ats_type, last_scraped, created_at)
- jobs (id, company_id, title, department, location, url, description, salary, date_posted, scrape_status, scraped_at)
- classifications (id, job_id, department_category, seniority_level, key_skills, strategic_signals, growth_signal, classified_at, model_used)

### Company Dossiers
- dossiers (id, company_name UNIQUE NOCASE, sector, description, created_at, updated_at)
- dossier_analyses (id, dossier_id FK, analysis_type, report_file, key_facts_json, model_used, created_at)
- dossier_events (id, dossier_id FK, event_date, event_type, title, description, source_url, data_json, created_at)

## Critical Rules
- **NEVER answer company intelligence questions from general knowledge.** Always use tools to get real data. If the user asks about a company's digital maturity, hiring trends, financials, competitors, or technology — run the appropriate analysis tools. Your training data is stale; the tools provide current intelligence.
- **NEVER say "I will perform additional searches" or "Let me search for more" without actually calling tools in the same response.** If you need more data, call the tools NOW — don't respond with text promising to do more later. Every response must either contain tool calls OR be your final answer. There is no "next turn" — if you respond with text only, the conversation ends.
- **Multi-company queries → `batch_company_analysis`.** When the user asks to rank, compare, or evaluate multiple companies (e.g., "which CPG companies are most behind?", "compare top 5 banks"), use `web_search` to identify the companies, then call `batch_company_analysis` with those names. Do NOT analyze companies one-by-one — the batch tool runs them in parallel and produces ranked results with Digital Maturity Scores.

## Guidelines
- Be concise and actionable. Lead with findings, not process.
- When presenting data, use tables and bullet points for scannability.
- If a company is private and has no SEC data, say so explicitly and search for alternative financial information.
- When tools produce reports, mention the filename so the user can find it.
- Don't repeat tool results verbatim — synthesize and highlight what matters.
- **Always check the dossier first** before running analyses. If we scanned recently, tell the user what we know and ask if they want a fresh scan.
- When the dossier shows **recent changes** between scans, highlight them to the user and offer to investigate further. Example: "Since our last scan, Microsoft's hiring trend shifted from 'growing' to 'stable'. Want me to dig into what's driving that?"
- When you discover notable events (M&A, product launches, leadership changes), save them to the dossier timeline with `save_dossier_event`.
- **Seniority framework auto-detection**: When classifying or running the full pipeline, auto-detect the industry seniority framework from the company name. Different industries have completely different title hierarchies — "VP" at a bank is mid-career, "VP" at a tech company is executive. Use these mappings:
  - **banking**: Goldman Sachs, JP Morgan, Citi, Morgan Stanley, Bank of America, Wells Fargo, Deutsche Bank, UBS, Credit Suisse, Barclays, HSBC, and other banks/financial institutions
  - **consulting**: McKinsey, BCG, Bain, Deloitte, PwC, EY, KPMG, Accenture, and other consulting/audit/law firms
  - **corporate**: Walmart, Target, P&G, Unilever, Johnson & Johnson, General Motors, Boeing, Caterpillar, and other retail/manufacturing/CPG companies
  - **tech** (default): All software, tech, and startup companies, or when the industry is unclear
  Always pass the `seniority_framework` parameter when calling classify or hiring_pipeline. If the user specifies a framework, use that. If they describe custom leveling rules, pass `custom_seniority_rules`.
- **Intelligence briefings**: Use `generate_briefing` after a company has multiple analyses (financial, competitors, hiring, techstack, etc.) to create a consulting-ready intelligence briefing with a Digital Maturity Score, engagement opportunity map, risk profile, and strategic assessment. The briefing is stored on the dossier and rendered in the right pane. **Hiring data is mandatory** — if the briefing fails due to missing hiring analysis, automatically run `hiring_pipeline` for the company, then retry `generate_briefing`.
- **Website analyses and company linking**: When running `techstack_analysis`, `seo_audit`, or `pricing_analysis`, always pass the `company_name` parameter if you know which company owns the website. This links the analysis to the correct company dossier instead of creating a separate entry for the domain. **Do NOT waste tool calls searching for a company's website URL** — just infer it directly (e.g., "Danone" → `https://www.danone.com`, "Stripe" → `https://stripe.com`). The crawler will follow redirects if the URL isn't exact. Only search for the URL if the company name is ambiguous or you genuinely don't know their domain.
- **Multi-company queries**: See the Critical Rules section above — always use `batch_company_analysis` for multi-company queries. Max 5 companies per batch."""

# Condensed system prompt for follow-up rounds — saves ~8K chars of context
CONDENSED_SYSTEM_PROMPT = """You are SignalVault, a competitive intelligence analyst. Continue the conversation using your tools.

Rules: Think before acting. Synthesize findings concisely — don't echo raw tool output. Check dossiers before new analyses. If briefing needs hiring data, run hiring_pipeline first. Save notable events to dossier timelines. CRITICAL: Never respond with text saying you will do more work — if you need more data, call tools NOW. A text-only response is your FINAL answer."""

# Tool tiers for dynamic schema selection — reduces context overhead on follow-up rounds
CORE_TOOL_NAMES = {
    "think", "web_search", "query_db", "get_dossier",
    "get_current_datetime", "save_dossier_event",
}

FOLLOW_UP_TOOL_NAMES = CORE_TOOL_NAMES | {
    "search_financial_news", "reddit_search", "hn_search",
    "generate_briefing", "hiring_pipeline", "batch_company_analysis",
    "full_analysis", "financial_analysis", "patent_analysis",
    "competitor_analysis", "sentiment_analysis", "executive_signals_analysis",
    "seo_audit", "techstack_analysis", "pricing_analysis", "compare_companies",
    "landscape_analysis", "collect", "classify", "analyze",
    "discover_prospects", "score_prospect", "get_scored_prospects",
    "score_lens", "list_lenses", "get_lens_scores",
}


def get_tool_schemas(tier="full"):
    """Return tool schemas filtered by tier to reduce context overhead.

    full: All tools (~17K chars) — first round of each user message
    follow_up: Core + key tools (~6K chars) — subsequent tool-call rounds
    minimal: Think + search (~1K chars) — context overflow recovery
    """
    if tier == "full":
        return TOOL_SCHEMAS
    if tier == "follow_up":
        return [t for t in TOOL_SCHEMAS if t["function"]["name"] in FOLLOW_UP_TOOL_NAMES]
    if tier == "minimal":
        return [t for t in TOOL_SCHEMAS if t["function"]["name"] in {"think", "web_search", "get_current_datetime"}]
    return TOOL_SCHEMAS


TOOL_SCHEMAS = [
    # --- Reasoning ---
    {
        "type": "function",
        "function": {
            "name": "think",
            "description": "Reason step-by-step about what you know, what you don't know, what tools to use next, and why. The user can see your thinking. Call this BEFORE making decisions — especially when evaluating data quality, choosing between tools, or dealing with unexpected/empty results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reasoning": {
                        "type": "string",
                        "description": "Your step-by-step reasoning process"
                    }
                },
                "required": ["reasoning"]
            }
        }
    },
    # --- Raw Data ---
    {
        "type": "function",
        "function": {
            "name": "search_sec_edgar",
            "description": "Search SEC EDGAR for raw financial data (revenue, net income, R&D, cash, filings). Returns structured data, NOT a report. Use when you want to examine financials before deciding how to proceed. Returns an explanation if the company isn't found (likely private or foreign-listed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "Company name or ticker symbol (e.g. 'Apple', 'MSFT', 'Stripe')"
                    }
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_patents_raw",
            "description": "Search USPTO/Google Patents for raw patent data. Returns a patent list, NOT a report. Use when you want to see what patents exist before deciding on a full analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "Company or assignee name (e.g. 'Tesla', 'Google LLC')"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max patents to return (default: 15)"
                    }
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_financial_news",
            "description": "Search for financial news from major outlets (Reuters, Bloomberg, FT, WSJ, SeekingAlpha). Use for earnings reports, revenue data, funding rounds, M&A activity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g. 'Stripe Series I funding 2026', 'Microsoft Q4 earnings')"
                    }
                },
                "required": ["query"]
            }
        }
    },
    # --- Job Intelligence ---
    {
        "type": "function",
        "function": {
            "name": "hiring_pipeline",
            "description": "Run the complete hiring intelligence pipeline: scrape ATS board → classify jobs → generate strategic hiring report. Use when the user asks about hiring, jobs, or open roles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name (e.g. 'Stripe', 'Datadog')"},
                    "url": {"type": "string", "description": "ATS board URL. Optional — auto-detected if omitted."},
                    "seniority_framework": {"type": "string", "enum": ["tech", "banking", "consulting", "corporate"], "description": "Industry seniority framework. OMIT this parameter unless the user explicitly specifies a framework — the backend defaults to 'corporate' which works for most companies. Only override: pure software/tech companies→tech, banks/financial services→banking, consulting firms→consulting."},
                    "custom_seniority_rules": {"type": "string", "description": "Custom seniority mapping rules. Only use if the user explicitly describes a non-standard leveling system."},
                    "classification_mode": {"type": "string", "enum": ["fast", "comprehensive"], "description": "Classification mode. 'fast': heuristic-only, zero API calls. 'comprehensive': heuristic + LLM. Default: comprehensive."},
                    "fresh": {"type": "boolean", "description": "Set to true to purge all existing jobs for this company and re-scrape from scratch. Use when the user says 'rerun', 'redo', 'fresh', 'recollect', or when previous data was bad/stale."}
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "collect",
            "description": "Scrape all open job postings from a company's ATS board. Auto-detects Greenhouse, Lever, Ashby boards, falls back to LinkedIn.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"},
                    "url": {"type": "string", "description": "ATS board URL. Optional — auto-detected if omitted."}
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "classify",
            "description": "Classify all unclassified jobs for a company (department, seniority, skills, strategic signals). Auto-detects the industry seniority framework unless overridden.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"},
                    "seniority_framework": {"type": "string", "enum": ["tech", "banking", "consulting", "corporate"], "description": "Industry seniority framework. OMIT unless the user explicitly specifies — backend defaults to 'corporate'. Only override: pure software/tech→tech, banks→banking, consulting firms→consulting."},
                    "custom_seniority_rules": {"type": "string", "description": "Custom seniority mapping rules. Only use if the user explicitly describes a non-standard leveling system."},
                    "mode": {"type": "string", "enum": ["fast", "comprehensive"], "description": "Classification mode. 'fast': heuristic-only (regex), zero API calls, classifies ALL jobs instantly — good enough for hiring stats and briefings. 'comprehensive': heuristic + LLM for strategic fields (subcategory, skills, signals). Default: comprehensive."}
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reclassify",
            "description": "Clear existing classifications and re-classify all jobs for a company with improved subcategories. Use when subcategories look wrong (all 'General') or classifications need regeneration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"},
                    "seniority_framework": {"type": "string", "enum": ["tech", "banking", "consulting", "corporate"], "description": "Industry seniority framework."}
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze",
            "description": "Generate a strategic intelligence report from classified job data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"}
                },
                "required": ["company"]
            }
        }
    },
    # --- Analysis Reports ---
    {
        "type": "function",
        "function": {
            "name": "financial_analysis",
            "description": "Generate a full financial analysis report. Uses SEC EDGAR for public companies (revenue, profit, R&D, cash), web search for private companies (funding, valuation estimates). Saves a .md report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name (e.g. 'Apple', 'Stripe')"}
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "patent_analysis",
            "description": "Generate a full patent portfolio analysis from USPTO data. Identifies innovation areas, filing trends, IP strategy. Uses agentic name-variation search to find patents even when the company files under different legal entities. Saves a .md report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name (e.g. 'Apple', 'Google')"}
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "competitor_analysis",
            "description": "Map the competitive landscape — identify competitors, differentiators, market position, and strategic threats. Saves a .md report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"}
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sentiment_analysis",
            "description": "Analyze employee sentiment, workplace culture, and employer reputation from Glassdoor, Reddit, news, and Hacker News. Saves a .md report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"}
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "executive_signals_analysis",
            "description": "Analyze executive hiring signals — C-suite and VP-level appointments, departures, and open searches. Uses SEC 8-K filings (public companies), news, and classified executive job openings. Reveals organizational commitment: if leadership isn't investing at the top, strategic initiatives stall in middle management. Saves a .md report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"}
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "seo_audit",
            "description": "Run an SEO & AEO audit on a website. Crawls key pages and analyzes on-page signals, structured data, AI-readiness. Saves a .md report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Website URL (e.g. 'https://stripe.com')"},
                    "max_pages": {"type": "integer", "description": "Max pages to crawl (default: 10)"},
                    "company_name": {"type": "string", "description": "Company name to link this analysis to in the dossier (e.g. 'Stripe'). If omitted, uses the domain."}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "techstack_analysis",
            "description": "Detect and analyze a website's technology stack by crawling it. Identifies frameworks, analytics, CDNs, CMS, marketing tools. When company_name is provided and the company has hiring data in the DB, the report is enriched with internal engineering stack signals (backend languages, databases, cloud platforms, DevOps tools, AI/ML frameworks) from classified job listings. Saves a .md report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Website URL (e.g. 'https://stripe.com')"},
                    "max_pages": {"type": "integer", "description": "Max pages to crawl (default: 5)"},
                    "company_name": {"type": "string", "description": "Company name to link this analysis to in the dossier (e.g. 'Stripe'). If omitted, uses the domain."}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pricing_analysis",
            "description": "Analyze a website's pricing strategy, product tiers, and competitive positioning. Saves a .md report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Website URL (e.g. 'https://stripe.com')"},
                    "company_name": {"type": "string", "description": "Company name to link this analysis to in the dossier (e.g. 'Stripe'). If omitted, uses the domain."}
                },
                "required": ["url"]
            }
        }
    },
    # --- Multi-Company ---
    {
        "type": "function",
        "function": {
            "name": "full_analysis",
            "description": "Run a full company analysis: financial + competitors + sentiment + patents + hiring all at once. Generates an executive summary linking to individual reports. Use when the user says 'full analysis', 'analyze this company', or 'run everything'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"},
                    "url": {"type": "string", "description": "ATS job board URL. Optional — auto-detected if omitted."}
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_companies",
            "description": "Compare two companies side by side across financial, sentiment, patent, and competitive dimensions. Saves a comparison .md report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_a": {"type": "string", "description": "First company name"},
                    "company_b": {"type": "string", "description": "Second company name"}
                },
                "required": ["company_a", "company_b"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "landscape_analysis",
            "description": "Auto-discover a company's top competitors and generate a competitive landscape report. Finds competitors via web search, then analyzes each one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"},
                    "top_n": {"type": "integer", "description": "Number of competitors to analyze (default: 3)"}
                },
                "required": ["company"]
            }
        }
    },
    # --- Search ---
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "General web + news search via DuckDuckGo. Use for company news, earnings, funding rounds, product launches, market analysis, or anything not in the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (e.g. 'Stripe quarterly earnings 2026')"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reddit_search",
            "description": "Search Reddit for community discussions, opinions, and insider takes. Uses DuckDuckGo, falls back to direct RSS. Great for candid employee perspectives and product comparisons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (e.g. 'working at Stripe', 'Datadog vs New Relic')"},
                    "max_results": {"type": "integer", "description": "Number of results (default: 5)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reddit_deep_search",
            "description": "Deep Reddit search via direct RSS feeds (bypasses DuckDuckGo). Searches multiple subreddits, can fetch top comments. Use for richer discussion content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Number of results (default: 10)"},
                    "fetch_comments": {"type": "boolean", "description": "Fetch top comments from best posts (slower but richer)"},
                    "subreddits": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Specific subreddits (e.g. ['fintech', 'startups']). Omit for default mix."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "hn_search",
            "description": "Search Hacker News for tech community discussions, product launches, startup news, and developer sentiment. Uses the official Algolia API.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Number of results (default: 10)"},
                    "sort": {"type": "string", "enum": ["relevance", "date"], "description": "Sort order (default: relevance)"},
                    "fetch_comments": {"type": "boolean", "description": "Fetch top comments from best stories (slower but richer)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_search",
            "description": "Search YouTube for videos about companies or topics. Can optionally fetch transcripts to read video content without watching.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (e.g. 'Stripe earnings call')"},
                    "fetch_transcripts": {"type": "boolean", "description": "Also fetch transcripts from top results (slower but gives full content)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_transcript",
            "description": "Fetch the transcript/captions from a specific YouTube video. Great for earnings calls, interviews, presentations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "YouTube video URL"},
                    "max_chars": {"type": "integer", "description": "Max transcript length in characters (default: 6000)"}
                },
                "required": ["url"]
            }
        }
    },
    # --- Database ---
    {
        "type": "function",
        "function": {
            "name": "query_db",
            "description": "Run a read-only SQL SELECT query against the intelligence database. Use for questions about collected job data — counts, department breakdowns, skill trends, company comparisons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "A SELECT SQL query"}
                },
                "required": ["sql"]
            }
        }
    },
    # --- Company Dossiers ---
    {
        "type": "function",
        "function": {
            "name": "get_dossier",
            "description": "Get the accumulated intelligence dossier for a company. Returns all past analyses (with key facts and dates), recent changes detected between scans (e.g. revenue up 10%, new competitor, hiring trend shifted), timeline events, and staleness per analysis type. ALWAYS call this before running a new analysis to see what we already know and what changed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"}
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_dossier_event",
            "description": "Save a strategic event to a company's dossier timeline. Use when you discover notable events during research: acquisitions, product launches, leadership changes, regulatory actions, funding rounds, layoffs, partnerships, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"},
                    "event_type": {"type": "string", "description": "Event category: acquisition, product_launch, leadership_change, regulatory, funding, layoff, partnership, earnings, patent_filing, legal, other"},
                    "title": {"type": "string", "description": "Short event title"},
                    "description": {"type": "string", "description": "Event details"},
                    "event_date": {"type": "string", "description": "Date of the event (YYYY-MM-DD or YYYY-MM or YYYY)"},
                    "source_url": {"type": "string", "description": "URL source for this event"}
                },
                "required": ["company", "event_type", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "refresh_key_facts",
            "description": "Re-extract structured key facts from all existing analysis reports for a company using improved type-specific prompts. Use this when citation popovers show wrong/generic data (e.g., sentiment badge showing hq_location instead of sentiment scores). Does NOT re-run analyses — just re-reads existing reports and extracts better-structured facts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"}
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_briefing",
            "description": "Generate a consulting-ready intelligence briefing for a company's dossier. Synthesizes all available analyses into a scored evaluation (0-100) through a configurable lens, plus engagement opportunity map, budget signals, competitive pressure assessment, risk profile, and strategic assessment. The scoring dimensions and rubric are driven by the selected lens (defaults to Digital Transformation if none specified). The briefing is stored on the dossier and rendered in the right pane. IMPORTANT: Requires hiring analysis (classified job data). If it fails because hiring data is missing, you MUST automatically run hiring_pipeline for the company first, then retry generate_briefing. Also requires at least 2 total analyses.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name (must have an existing dossier with at least 2 analyses)"},
                    "lens_id": {"type": "integer", "description": "Optional lens ID to score through. Defaults to Digital Transformation lens if not specified."}
                },
                "required": ["company"]
            }
        }
    },
    # --- Batch ---
    {
        "type": "function",
        "function": {
            "name": "batch_company_analysis",
            "description": "Run analysis pipelines on multiple companies in parallel and return combined results with Digital Maturity Scores for comparison. Use when the user's question requires analyzing or comparing several companies (e.g., 'which CPG companies are most behind digitally?', 'compare top 5 banks'). Much faster than sequential analysis. Max 5 companies per batch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "companies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Company names to analyze (max 5)"
                    },
                    "seniority_framework": {
                        "type": "string",
                        "enum": ["tech", "banking", "consulting", "corporate"],
                        "description": "Industry seniority framework. OMIT unless user specifies — backend defaults to 'corporate'."
                    },
                    "depth": {
                        "type": "string",
                        "enum": ["hiring", "standard", "full"],
                        "description": "Analysis depth per company. 'hiring': job pipeline only (fastest). 'standard': hiring + competitors with fast (heuristic) classification — no LLM calls for classification (enables DM scores). 'full': full_analysis with all analyses and comprehensive LLM classification (slowest). Default: standard."
                    }
                },
                "required": ["companies"]
            }
        }
    },
    # --- Utility ---
    {
        "type": "function",
        "function": {
            "name": "get_current_datetime",
            "description": "Get the current date and time. Use when answering questions about deadlines, 'today', 'this week', or when the user needs to know the current date/time.",
            "parameters": {
                "type": "object",
                "properties": {},
            }
        }
    },
    # --- Prospecting ---
    {
        "type": "function",
        "function": {
            "name": "discover_prospects",
            "description": "Discover prospective companies in a target niche or vertical. Searches web, Reddit, and news to find companies that match the target profile. Returns a list of discovered companies with names, websites, and descriptions. Use when the user says 'find prospects in...', 'discover leads in...', or asks about companies in a specific vertical.",
            "parameters": {
                "type": "object",
                "properties": {
                    "niche": {"type": "string", "description": "Target niche/vertical (e.g. 'DTC skincare brands', 'fintech apps', 'meal kit companies')"},
                    "top_n": {"type": "integer", "description": "Max companies to discover (default: 15)"}
                },
                "required": ["niche"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "score_prospect",
            "description": "Score a company using the active lens (configurable scoring framework). Runs required analyses based on lens dimensions, then scores each dimension 0-100 with evidence-backed rationale. Use when someone asks 'is this a good prospect?', 'score this company', or 'how well does X fit our criteria?'",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name to score"},
                    "website_url": {"type": "string", "description": "Company website URL (optional, enables tech stack + ad pixel detection)"}
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_scored_prospects",
            "description": "Get all companies scored with the active lens, sorted by score descending. Falls back to legacy scores if lens not found. Use when the user asks 'show me our prospects', 'who are the best leads?', 'what's in the pipeline?', or 'list scored companies'.",
            "parameters": {
                "type": "object",
                "properties": {},
            }
        }
    },
    # --- Lens Scoring ---
    {
        "type": "function",
        "function": {
            "name": "create_lens",
            "description": "Create a new evaluation lens (scoring framework). Lenses define weighted dimensions for evaluating companies. Use when the user says 'create a lens for...', 'make a scoring framework for...', 'I want to evaluate companies on...', or 'build a lens'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Lens name (e.g. 'Workforce Management', 'Strategy Consulting')"},
                    "description": {"type": "string", "description": "What this lens evaluates — 1-2 sentences describing the use case"},
                },
                "required": ["name", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "score_lens",
            "description": "Score a company through a specific evaluation lens. Runs required analyses and scores against the lens dimensions. Available lenses include presets (CTV Ad Sales, Digital Transformation, Workforce Management) plus any user-created lenses. Use when someone asks 'score X through Y lens', 'evaluate X for Y', 'how does X rate on Y', or 'run the workforce lens on X'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name to score"},
                    "lens": {"type": "string", "description": "Lens name or slug (e.g. 'Digital Transformation', 'workforce-management')"},
                    "website_url": {"type": "string", "description": "Company website URL (optional, enables tech stack analysis)"},
                },
                "required": ["company", "lens"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_lenses",
            "description": "List all available evaluation lenses with their names, descriptions, and dimension summaries. Use when the user asks 'what lenses do I have?', 'show me scoring frameworks', 'what can I evaluate companies on?', or 'list lenses'.",
            "parameters": {
                "type": "object",
                "properties": {},
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_lens_scores",
            "description": "Get all lens scores for a company — shows how the company rates across all lenses it has been scored through. Use when the user asks 'what scores does X have?', 'show me X's evaluations', or 'how has X been rated?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"},
                },
                "required": ["company"]
            }
        }
    },
]
