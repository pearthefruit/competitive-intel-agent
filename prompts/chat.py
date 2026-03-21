"""System prompt and tool schemas for the chat interface."""

SYSTEM_PROMPT = """You are a Competitive Intelligence Assistant. You help users analyze companies by scraping their job boards, classifying roles, generating strategic reports, and performing deep competitive research.

You have access to these tools:

**Job Intelligence:**
- collect: Scrape open job postings from a company's job board. Auto-detects Greenhouse, Lever, or Ashby boards, and falls back to LinkedIn search if no dedicated ATS board is found.
- classify: Classify all unclassified jobs for a company using LLM (department, seniority, skills, signals).
- analyze: Generate a strategic intelligence report from classified jobs.
- full_pipeline: Run the complete pipeline (collect → classify → analyze) for a company in one go.

**Research & Analysis:**
- financial_analysis: Analyze a company's financials. Uses SEC EDGAR for public companies (revenue, profit, R&D, cash), web search for private companies.
- techstack_analysis: Detect what technologies a website uses (frameworks, analytics, CDN, CMS, etc.) by crawling the site.
- patent_analysis: Analyze a company's patent portfolio from USPTO data (innovation areas, IP strategy).
- pricing_analysis: Analyze a website's pricing strategy, tiers, and positioning by crawling the site.
- competitor_analysis: Map the competitive landscape — identify competitors, differentiators, market position.
- sentiment_analysis: Analyze employee sentiment and workplace culture from reviews and news.
- seo_audit: Run an SEO & AEO (Answer Engine Optimization) audit on a website.

**Utilities:**
- query_db: Run a read-only SQL query against the intel database to answer questions about collected data.
- web_search: Search the web for company news, market context, earnings, or anything not in the database.

The database has three tables:
- companies (id, name, url, ats_type, last_scraped, created_at)
- jobs (id, company_id, title, department, location, url, description, salary, date_posted, scrape_status, scraped_at)
- classifications (id, job_id, department_category, seniority_level, key_skills, strategic_signals, growth_signal, classified_at, model_used)

When users ask to analyze a company, use full_pipeline unless they specifically want a single step.
When users ask data questions (counts, breakdowns, comparisons), use query_db with appropriate SQL.
When users ask about company news, market context, earnings, or anything not in the database, use web_search.
When users ask about financials, revenue, funding, or SEC filings, use financial_analysis.
When users ask about tech stack, technologies, or what a site is built with, use techstack_analysis.
When users ask about patents, IP, or innovation, use patent_analysis.
When users ask about pricing, plans, or product tiers, use pricing_analysis.
When users ask about competitors or competitive landscape, use competitor_analysis.
When users ask about employee reviews, workplace culture, or employer reputation, use sentiment_analysis.
When users ask for SEO analysis, website audit, or AEO analysis, use seo_audit.
Always be concise and actionable in your responses."""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "collect",
            "description": "Scrape all open job postings from a company's ATS board. Auto-detects the board URL if not provided.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "Company name (e.g. 'Stripe', 'Datadog')"
                    },
                    "url": {
                        "type": "string",
                        "description": "ATS board URL. Optional — auto-detected if omitted."
                    }
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "classify",
            "description": "Classify all unclassified jobs for a company (department, seniority, skills, strategic signals).",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "Company name"
                    }
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
                    "company": {
                        "type": "string",
                        "description": "Company name"
                    }
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "full_pipeline",
            "description": "Run the complete pipeline: collect jobs → classify → generate report. Use this when the user wants a full analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "Company name"
                    },
                    "url": {
                        "type": "string",
                        "description": "ATS board URL. Optional — auto-detected if omitted."
                    }
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_db",
            "description": "Run a read-only SQL SELECT query against the intelligence database. Use for questions about job counts, department breakdowns, skill trends, company comparisons, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "A SELECT SQL query to run against the database."
                    }
                },
                "required": ["sql"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information. Use for company news, earnings reports, funding rounds, product launches, market analysis, or anything not in the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query (e.g. 'Stripe quarterly earnings 2026', 'Datadog acquisition news')"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "seo_audit",
            "description": "Run an SEO & AEO (Answer Engine Optimization) audit on a website. Crawls key pages and analyzes on-page signals, structured data, keyword targeting, and AI-readiness.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Website URL to audit (e.g. 'https://stripe.com', 'ramp.com')"
                    },
                    "max_pages": {
                        "type": "integer",
                        "description": "Max pages to crawl (default: 10)"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "financial_analysis",
            "description": "Analyze a company's financial health. Uses SEC EDGAR data for public companies (revenue, net income, R&D, cash position) or web search for private companies (funding, valuation estimates).",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "Company name (e.g. 'Apple', 'Stripe')"
                    }
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "techstack_analysis",
            "description": "Detect and analyze a website's technology stack by crawling it. Identifies frontend frameworks, analytics, CDNs, CMS, marketing tools, and more.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Website URL to analyze (e.g. 'https://stripe.com')"
                    },
                    "max_pages": {
                        "type": "integer",
                        "description": "Max pages to crawl (default: 5)"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "patent_analysis",
            "description": "Analyze a company's patent portfolio using USPTO PatentsView data. Identifies innovation focus areas, filing trends, and IP strategy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "Company name (as it appears on patents, e.g. 'Apple Inc.', 'Google LLC')"
                    }
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pricing_analysis",
            "description": "Analyze a website's pricing strategy, product tiers, and competitive positioning by crawling the site and extracting pricing page data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Website URL to analyze (e.g. 'https://stripe.com')"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "competitor_analysis",
            "description": "Map the competitive landscape for a company. Identifies competitors, differentiators, market position, and strategic threats.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "Company name (e.g. 'Stripe', 'Datadog')"
                    }
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sentiment_analysis",
            "description": "Analyze employee sentiment, workplace culture, and employer reputation using web search results from Glassdoor, news, and other sources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "Company name (e.g. 'Stripe', 'Google')"
                    }
                },
                "required": ["company"]
            }
        }
    },
]
