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

    return f"""You are a macro-level signal analyst grouping news signals into DIRECTIONAL OBSERVATIONS — not neutral topics, but specific claims about what is happening.

A thread is NOT a topic. It is a DIRECTIONAL CLAIM backed by signals.
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
      "title": "Directional claim about what is happening",
      "summary": "2-3 sentences: What specific thing is happening? What evidence supports this direction? Who is affected?",
      "domain": "economics",
      "signal_ids": [125, 130, 131]
    }}
  ]
}}

THREAD TITLE RULES — THIS IS CRITICAL:
- Every title MUST take a DIRECTION. Something is going UP, DOWN, ACCELERATING, DECLINING, BREAKING, SHIFTING.
- BAD: "Labor Market Trends" (no direction — trends which way?)
- GOOD: "US Labor Market Weakening Despite Strong Headline Numbers"
- BAD: "Stock Market Rotation" (rotation is neutral)
- GOOD: "Tech Stocks Surging While Industrials Decline"
- BAD: "Chipmaker Revenue Divergence" (divergence is vague)
- GOOD: "NVIDIA and AMD Revenue Soaring on AI Demand"
- BAD: "Remote Work Trends" (what about them?)
- GOOD: "Remote Work Adoption Accelerating as Companies Cut Office Space"
- BAD: "Geopolitical Tensions" (too vague, no specifics)
- GOOD: "Iran Conflict Escalation Disrupting Oil Supply Routes"
- BAD: "Supply Chain Disruptions" (which supply chain? disrupted how?)
- GOOD: "Semiconductor Supply Chain Fracturing Along US-China Fault Lines"

If signals point in OPPOSITE directions, create TWO threads — one for each direction. Don't merge bullish and bearish signals into one "mixed" thread.

OTHER RULES:
- Group by PATTERN across companies, not by individual company
- A new thread needs at least 2 signals
- Signals that are truly isolated should have thread_id: null
- NEVER create a thread covering the same topic as an existing thread. Assign to the existing one instead.
- Prefer assigning to existing threads over creating new ones
- domain can be pipe-separated: economics|geopolitics for cross-domain threads
- Return ONLY the JSON object"""


def build_hypothesis_merge_prompt(hypotheses):
    """Prompt to merge 2-3 related hypotheses into one stronger hypothesis."""
    hyp_text = "\n\n".join(
        f"Hypothesis {i+1}: {h['title']}\nReasoning: {h.get('reasoning', '')}"
        for i, h in enumerate(hypotheses)
    )
    return f"""These hypotheses from a macro signal analysis overlap significantly. Merge them into ONE stronger, more comprehensive hypothesis.

{hyp_text}

Return JSON:
{{
  "title": "A clear, concise title for the merged hypothesis (keep [[concept]] markers if present)",
  "reasoning": "Combined reasoning that synthesizes all inputs — preserve specific details, data points, and [[concept]] markers from the originals. 2-4 sentences.",
  "confidence": "high" | "medium" | "low"
}}

Rules:
- The merged hypothesis should be STRONGER than any individual one — combine their evidence
- Preserve [[concept]] markers from the originals
- Don't just concatenate — synthesize into a cohesive narrative
- Return ONLY the JSON object"""


def build_causal_validation_prompt(cause_thread, effect_thread):
    """Prompt to validate whether one thread plausibly causes another."""
    cause_signals = "\n".join(
        f"- {s.get('title', '')}" for s in (cause_thread.get("signals") or [])[:5]
    )
    effect_signals = "\n".join(
        f"- {s.get('title', '')}" for s in (effect_thread.get("signals") or [])[:5]
    )
    return f"""Assess whether Thread A plausibly CAUSES or LEADS TO Thread B.

Thread A: {cause_thread.get('title', '')}
Domain: {cause_thread.get('domain', '')}
Summary: {cause_thread.get('synthesis', '')[:300]}
Recent signals:
{cause_signals}

Thread B: {effect_thread.get('title', '')}
Domain: {effect_thread.get('domain', '')}
Summary: {effect_thread.get('synthesis', '')[:300]}
Recent signals:
{effect_signals}

Return JSON:
{{
  "plausible": true | false,
  "mechanism": "1-2 sentences explaining HOW A causes B (the causal mechanism)",
  "confidence": "high" | "medium" | "low",
  "temporal": "Does A temporally precede B? yes/no/unclear"
}}

Be honest. If the connection is weak or speculative, say so. Not everything that correlates is causal."""


def build_entity_extraction_prompt(signals_text):
    """Prompt to extract entities including concepts and events from signals."""
    return f"""Extract entities from these news signals. Extract BOTH named entities AND thematic concepts.

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
        {{"type": "regulation", "value": "CHIPS Act"}},
        {{"type": "concept", "value": "supply chain reshoring"}},
        {{"type": "event", "value": "US-China trade war 2026"}}
      ]
    }}
  ]
}}

Entity types:
- company: specific companies. ALWAYS normalize (e.g. "NVDA" → "NVIDIA Corporation")
- sector: broad industry categories ("semiconductors", "fintech", "pharmaceuticals")
- geography: countries or major regions
- person: named individuals with influence on the story
- regulation: specific laws, policies, executive orders
- concept: thematic ideas that connect across domains ("tariffs", "remote work", "AI automation", "supply chain reshoring", "workforce displacement", "inflation pressure"). These are the MOST VALUABLE — they link stories that share no companies or sectors but are driven by the same forces
- event: specific time-anchored happenings ("Iran-Israel conflict 2026", "FOMC March 2026 meeting", "Trump tariff executive order")

Rules:
- Extract 2-4 concepts per signal — these are the ideas BEHIND the news, not the news itself
- Concepts should be 2-4 words, lowercase, reusable across signals ("AI automation" not "AI is automating jobs at Block")
- Events should be specific enough to be unique but general enough to connect signals
- For companies: resolve tickers to full names in "normalized"
- Omit signals with no extractable entities
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
- IMPORTANT: In connection_summary, hypothesis titles, hypothesis reasoning, and effect descriptions, wrap key concepts, companies, sectors, and policies in [[double brackets]]. Example: "[[Federal Reserve]] rate decisions amplify [[inflation]] risk in [[emerging markets]]". This makes them interactive in the UI.
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
- Every sub-thread MUST have at least 2 signals — never create a sub-thread with only 1 signal
- The remaining group catches signals that are genuinely miscellaneous — rename it to something specific if possible
- Return ONLY the JSON object"""
