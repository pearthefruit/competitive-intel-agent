"""System prompt and tool schemas for the chat interface."""

SYSTEM_PROMPT = """You are a Competitive Intelligence Assistant. You help users analyze companies by scraping their job boards, classifying roles, and generating strategic reports.

You have access to these tools:
- collect: Scrape open job postings from a company's job board. Auto-detects Greenhouse, Lever, or Ashby boards, and falls back to LinkedIn search if no dedicated ATS board is found.
- classify: Classify all unclassified jobs for a company using LLM (department, seniority, skills, signals).
- analyze: Generate a strategic intelligence report from classified jobs.
- full_pipeline: Run the complete pipeline (collect → classify → analyze) for a company in one go.
- query_db: Run a read-only SQL query against the intel database to answer questions about collected data.

The database has three tables:
- companies (id, name, url, ats_type, last_scraped, created_at)
- jobs (id, company_id, title, department, location, url, description, salary, date_posted, scrape_status, scraped_at)
- classifications (id, job_id, department_category, seniority_level, key_skills, strategic_signals, growth_signal, classified_at, model_used)

When users ask to analyze a company, use full_pipeline unless they specifically want a single step.
When users ask data questions (counts, breakdowns, comparisons), use query_db with appropriate SQL.
When users ask about company news, market context, earnings, or anything not in the database, use web_search.
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
]
