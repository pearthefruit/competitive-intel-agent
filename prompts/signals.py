"""Prompts for signal thread synthesis and entity extraction."""


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

    return f"""You are a signal analyst grouping news signals into thematic threads.

A thread is a persistent pattern or developing story — signals about the same topic, trend, or event get grouped together.
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
      "title": "Short descriptive title for the pattern",
      "summary": "2-3 sentence summary of what this pattern is about and why it matters. Factual, no speculation.",
      "domain": "economics",
      "signal_ids": [125, 130, 131]
    }}
  ]
}}

Rules:
- Assign a signal to an existing thread if it's clearly about the same topic/event/trend
- Group unassigned signals into new threads if 2+ signals share a common theme
- Signals that don't fit any thread and can't form a new group should have thread_id: null
- Thread titles should be specific patterns, not generic categories (e.g., "Semiconductor Tariff Escalation" not "Trade News")
- Summaries should be factual — describe what's happening, not what it means for consulting
- domain must be one of: economics, finance, geopolitics, tech_ai, labor, regulatory
- A new thread needs at least 2 signals
- Return ONLY the JSON object"""


def build_entity_extraction_prompt(signals_text):
    """Prompt for FAST_CHAIN to extract named entities from signal text.

    Extracts companies, sectors, geographies, and key figures mentioned.
    """
    return f"""Extract named entities from these news signals.

SIGNALS:
{signals_text}

Return JSON only:
{{
  "entities": [
    {{
      "signal_id": 123,
      "entities": [
        {{"type": "company", "value": "TSMC", "normalized": "Taiwan Semiconductor Manufacturing"}},
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
- For companies, include a normalized full name when the signal uses an abbreviation or nickname
- Only extract entities that are specifically named — not generic mentions like "the economy" or "companies"
- If a signal has no extractable entities, omit it from the list
- Return ONLY the JSON object"""


def build_thread_update_prompt(thread_title, thread_summary, new_signals_text):
    """Prompt to update a thread's summary after new signals are added."""
    return f"""Update this thread summary to incorporate the new signals.

THREAD: {thread_title}
CURRENT SUMMARY: {thread_summary}

NEW SIGNALS ADDED:
{new_signals_text}

Write an updated 2-3 sentence summary that incorporates the new information.
Be factual — describe the pattern and what's developing. No speculation about opportunities or impact.
Return ONLY the updated summary text, nothing else."""
