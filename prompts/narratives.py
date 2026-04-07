"""Prompts for the Narratives system — hypothesis decomposition and evidence classification."""


def build_narrative_decomposition_prompt(thesis, reasoning=""):
    """Decompose a user's hypothesis into sub-claims and generate search queries."""
    reasoning_block = f"\nUser's reasoning:\n{reasoning}\n" if reasoning else ""

    return f"""You are a research analyst. The user has a hypothesis they want to validate.

Hypothesis: {thesis}
{reasoning_block}
Your job:
1. Decompose this into 3-5 testable sub-claims. Each should be independently verifiable.
2. For each sub-claim, generate 2-3 targeted search queries — mix of:
   - Direct evidence queries (searching for supporting data)
   - Contrarian queries (searching for evidence AGAINST the claim)
   - Adjacent/analogue queries (related markets, historical parallels)
3. Give the narrative a concise title (under 60 chars).

Return JSON:
{{
  "title": "short narrative title",
  "sub_claims": [
    {{
      "claim": "the testable sub-claim",
      "queries": ["search query 1", "search query 2", "contrarian query"]
    }}
  ]
}}

Rules:
- Sub-claims must be specific and measurable, not vague
- Include at least one contrarian query per sub-claim
- Queries should be what you'd type into Google News, not academic
- Avoid generic queries like "is X true" — be specific about what data to look for
- Think cross-domain: tech, labor, finance, regulatory angles"""


def build_evidence_classification_prompt(thesis, signal_title, signal_body):
    """Classify a signal as supporting, contradicting, or neutral to a narrative."""
    body_preview = (signal_body or "")[:1500]
    return f"""Given this hypothesis:
"{thesis}"

Classify this signal:
Title: {signal_title}
Content: {body_preview}

Return JSON:
{{
  "stance": "supporting" | "contradicting" | "neutral",
  "relevance": 1-5,
  "reason": "one sentence explaining why"
}}

Be honest — if the signal contradicts the hypothesis, say so. Neutral means it's related but doesn't clearly support or contradict."""
