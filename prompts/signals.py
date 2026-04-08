"""Prompts for signal thread synthesis, entity extraction, and brainstorm hypothesis generation."""


def build_thread_assignment_prompt(new_signals_text, existing_threads_text):
    """Prompt for FAST_CHAIN to assign new signals to existing threads or create new ones.

    The LLM sees the new signals + summaries of existing threads and decides:
    - Which existing thread each signal belongs to (by thread_id)
    - Which signals should form new threads (grouped together)
    - Title + summary for any new threads
    """
    existing_block = ""
    if existing_threads_text:
        existing_block = f"""
EXISTING THREADS (assign signals to these when they match):
{existing_threads_text}
"""

    return f"""You are a macro-level signal analyst identifying PATTERNS and TRENDS across news signals. Your job is to spot developing macro stories that span companies, sectors, and geographies — not to catalog individual company events.

THINK LIKE A SENIOR CONSULTANT: What patterns would a McKinsey partner notice reading across all these signals? What macro forces are at play?
{existing_block}
NEW SIGNALS TO ASSIGN:
{new_signals_text}

Return JSON only:
{{
  "assignments": [
    {{"signal_id": 123, "thread_id": 5}},
    {{"signal_id": 124, "thread_id": 5}},
    {{"signal_id": 125, "thread_id": null}}
  ],
  "new_threads": [
    {{
      "title": "Short title describing the MACRO pattern",
      "summary": "2-3 sentences: What is the pattern? What forces are driving it? Which sectors/companies are affected?",
      "domain": "economics",
      "signal_ids": [125, 130, 131]
    }}
  ]
}}

CRITICAL RULES:
- Think MACRO, not micro. "Enterprise AI Adoption Accelerating" not "Company X Launches AI Product"
- Group by PATTERN, not by company. Multiple companies doing the same thing = one thread about the trend
- Cross-domain threads are the most valuable (e.g., tariffs + layoffs + supply chain = one pattern)
- Thread titles should name the FORCE or TREND, not a single event
- BAD: "Cal-Maine Foods Q3 Earnings" (single company event)
- GOOD: "Food Sector Earnings Volatility Amid Input Cost Pressure" (macro pattern)
- BAD: "NVIDIA Stock Movement" (single company)
- GOOD: "Chipmaker Revenue Divergence: AI Up, Consumer Down" (industry pattern)
- Summaries should identify what's developing and which sectors/companies are affected
- A new thread needs at least 2 signals
- Signals that are truly isolated (no pattern) should have thread_id: null
- domain must be one of: economics, finance, geopolitics, tech_ai, labor, regulatory
- Return ONLY the JSON object"""


def build_entity_extraction_prompt(signals_text):
    """Prompt for FAST_CHAIN to extract named entities from signal text.

    Extracts companies, sectors, geographies, and key figures mentioned.
    """
    return f"""Extract named entities from these news signals. Focus on specific, identifiable entities.

SIGNALS:
{signals_text}

Return JSON only:
{{
  "entities": [
    {{
      "signal_id": 123,
      "entities": [
        {{"type": "company", "value": "TSMC", "normalized": "Taiwan Semiconductor Manufacturing Co."}},
        {{"type": "sector", "value": "semiconductors"}},
        {{"type": "geography", "value": "Taiwan"}},
        {{"type": "person", "value": "Jensen Huang"}},
        {{"type": "regulation", "value": "CHIPS Act"}}
      ]
    }}
  ]
}}

Rules:
- type must be one of: company, sector, geography, person, regulation
- For companies: ALWAYS include the full company name in "normalized" (e.g., "CALM" → "Cal-Maine Foods, Inc.", "NVDA" → "NVIDIA Corporation")
- Do NOT extract stock tickers alone — always resolve to the company name
- sector should be broad industry categories: "semiconductors", "cloud computing", "pharmaceuticals", "retail", "financial services"
- geography should be countries or major regions, not cities
- Only extract entities that are specifically named — not generic mentions
- If a signal has no extractable entities, omit it from the list
- Return ONLY the JSON object"""


def build_thread_update_prompt(thread_title, thread_summary, new_signals_text):
    """Prompt to update a thread's summary after new signals are added."""
    return f"""Update this thread summary to incorporate the new signals.

THREAD: {thread_title}
CURRENT SUMMARY: {thread_summary}

NEW SIGNALS ADDED:
{new_signals_text}

Write an updated 2-3 sentence summary that describes the developing pattern. Name specific companies and sectors affected. Be factual — describe what's happening, not what it means for consulting.
Return ONLY the updated summary text, nothing else."""


def build_brainstorm_prompt(threads_text, shared_entities_text):
    """Prompt for generating hypotheses from connected threads.

    Takes 2-3 connected threads and their shared entities, generates
    hypotheses about what the connection means and second-order effects.
    """
    return f"""You are a senior strategy consultant examining interconnected signals across multiple domains. These threads share entities and may be causally linked.

CONNECTED THREADS:
{threads_text}

SHARED ENTITIES CONNECTING THESE THREADS:
{shared_entities_text}

Generate insight by analyzing what these connections mean together. Return JSON:
{{
  "connection_summary": "1-2 sentences explaining WHY these threads are connected and what the combined pattern suggests",
  "hypotheses": [
    {{
      "title": "Short hypothesis title",
      "reasoning": "2-3 sentences explaining the logic chain. What does Thread A + Thread B imply? What second-order effects might follow?",
      "confidence": "high|medium|low",
      "investigate": "A specific question or search that would validate or invalidate this hypothesis"
    }}
  ],
  "second_order_effects": [
    {{
      "effect": "One sentence describing a downstream effect nobody is talking about yet",
      "affected_sectors": ["sector1", "sector2"],
      "affected_companies": ["Company A", "Company B"]
    }}
  ],
  "questions_to_investigate": [
    "Specific question that would deepen understanding of this pattern"
  ],
  "link_labels": [
    {{"source_thread": "Thread A title", "target_thread": "Thread B title", "label": "concise 2-4 word relationship (e.g. 'amplifies inflation risk', 'supply chain dependency', 'regulatory spillover')"}}
  ]
}}

Rules:
- Generate 2-4 hypotheses, ranging from obvious to non-obvious
- Second-order effects should be things NOT mentioned in any individual signal — emergent from the combination
- "investigate" should be a concrete search query or research question, not vague
- Confidence: high = strong evidence chain, medium = plausible but needs validation, low = speculative but worth exploring
- Be specific — name companies, sectors, dollar amounts when possible
- You are generating HYPOTHESES for investigation, not making assertions
- link_labels: one entry per thread PAIR. Label must be a specific relationship mechanism, NOT generic words like "related to" or "connected" or "drives". Name the actual causal link (e.g. "amplifies inflation risk", "supply chain dependency").
- Return ONLY the JSON object"""


def build_thread_split_prompt(thread_title, signals_text):
    """Prompt for proposing how to split a large thread into specific sub-threads."""
    return f"""You are a senior analyst reviewing a signal thread that has grown too broad. Your job is to propose breaking it into more specific, actionable sub-threads.

CURRENT THREAD: "{thread_title}"

SIGNALS IN THIS THREAD:
{signals_text}

Analyze these signals and propose 2-5 specific sub-threads that would be more meaningful than the current broad grouping. Each sub-thread should represent a distinct, specific trend or pattern.

Return JSON:
{{
  "proposed_splits": [
    {{
      "title": "Specific thread name (e.g. 'AI-Driven Tech Layoffs at FAANG' not 'Tech Layoffs')",
      "rationale": "One sentence: why these signals belong together and why this is a distinct pattern",
      "signal_ids": [1, 2, 3],
      "domain": "economics|finance|geopolitics|tech_ai|labor|regulatory"
    }}
  ],
  "remaining": {{
    "title": "Suggested name for signals that don't fit any sub-thread (or null if all assigned)",
    "signal_ids": [4, 5]
  }}
}}

Rules:
- Sub-thread titles must be SPECIFIC — name companies, technologies, policies, not vague categories
- BAD: "Technology Trends", "Market Changes", "Labor Issues"
- GOOD: "FAANG AI Infrastructure Hiring Freeze", "Semiconductor Supply Chain Reshoring", "Remote Work Adoption in Creative Industries"
- Every signal must appear in exactly one group (either a proposed split or remaining)
- Don't create a sub-thread with only 1 signal unless it's truly distinct
- The remaining group catches signals that are genuinely miscellaneous — rename it to something specific if possible
- Return ONLY the JSON object"""
