"""Prompts for generating falsifiable predictions from signals."""

import datetime


def _today_str() -> str:
    return datetime.date.today().strftime("%B %d, %Y")


def build_evidence_judge_prompt(signal_title: str, signal_body: str, prediction_claim: str, prediction_mechanism: str) -> str:
    return f"""You are evaluating whether a new signal supports, refutes, or is unrelated to a prediction.

PREDICTION: {prediction_claim}
MECHANISM: {prediction_mechanism}

NEW SIGNAL:
Title: {signal_title}
Content: {signal_body[:1500]}

Candidates reach you already filtered for topical relevance, so "these are both
about the economy" is NOT a reason to avoid committing. Pick the stance the
evidence actually points to.

Stances — 'partial' is the narrowest, not the safe default:
- 'supports': the signal is evidence the prediction is coming true. Use this even
  if the signal is only one step toward the claim, as long as it points that way.
- 'refutes': the signal is evidence against the prediction, on the same reasoning.
- 'partial': reserved for genuinely MIXED evidence — the signal cuts both ways,
  supporting one part of the claim while undercutting another. If the signal
  points in ONE direction, choose supports or refutes, not partial.
- 'unrelated': the signal has no bearing on whether this claim comes true.
  Topically adjacent but causally irrelevant still counts as unrelated.

Ask yourself: does this signal move my belief about whether the claim happens?
- Yes, toward it → supports.  Yes, against it → refutes.
- Both at once → partial.     Not at all → unrelated.

Weight = how much it moves your belief:
- 0.7-1.0: direct, specific evidence about this exact claim
- 0.4-0.69: real but indirect evidence (right mechanism, adjacent subject)
- 0.3-0.39: marginal — barely moves the needle
- 0.0-0.29: unrelated (this is not written to the evidence ledger)

Return JSON:
{{
  "stance": "supports|refutes|partial|unrelated",
  "weight": float 0.0-1.0,
  "note": "1-2 sentences: what specifically in the signal bears on the claim (or null if unrelated)"
}}"""


_SHARED_RULES = """Rules:
- TODAY'S DATE IS {today}. Every date you mention in a claim or falsifier MUST be AFTER today.
  Compute deadline dates as today + horizon_days. NEVER use dates from before {today} —
  a prediction with a past deadline is invalid and will be discarded.
- Be SPECIFIC and FALSIFIABLE — vague predictions are useless
- Time horizon: 30-180 days realistically; use 365 only for structural shifts
- Each prediction must have a clear falsifier (what would prove it wrong)
- Prefer leading indicators over lagging ones"""

_SHARED_SCHEMA = """Return JSON:
{{
  "predictions": [
    {{
      "claim": "string — complete falsifiable statement: 'If X, then Y will be observable via Z by [date after {today}]'",
      "mechanism": "string — 1-2 sentences explaining why this effect follows",
      "horizon_days": integer,
      "falsifier": "string — specific observable condition that would refute this",
      "confidence": integer 1-5,
      "indicator_type": "leading|concurrent|lagging"
    }}
  ]
}}"""


def build_thread_predictions_prompt(thread_title: str, thread_body: str) -> str:
    today = _today_str()
    return f"""You are a competitive intelligence analyst generating falsifiable forward-looking predictions.

Given this intelligence thread (a synthesized cluster of related signals):
TITLE: {thread_title}
SYNTHESIS: {thread_body[:2000]}

Generate 2-3 falsifiable, time-bounded second-order predictions. Each prediction is a specific consequence that should become observable within a defined timeframe IF this thread's pattern continues.

{_SHARED_RULES.format(today=today)}
- Do NOT restate the thread — predict the NEXT effect

{_SHARED_SCHEMA.format(today=today)}"""


def build_predictions_prompt(signal_title: str, signal_body: str, domain: str) -> str:
    today = _today_str()
    return f"""You are a competitive intelligence analyst generating falsifiable forward-looking predictions.

Given this signal:
DOMAIN: {domain}
TITLE: {signal_title}
BODY: {signal_body[:2000]}

Generate 2-3 falsifiable, time-bounded second-order predictions. Each prediction is a specific consequence that should become observable within a defined timeframe IF this signal's trend continues.

{_SHARED_RULES.format(today=today)}
- Do NOT restate the signal — predict the NEXT effect

{_SHARED_SCHEMA.format(today=today)}"""
