"""Prompts for generating falsifiable predictions from signals."""


def build_evidence_judge_prompt(signal_title: str, signal_body: str, prediction_claim: str, prediction_mechanism: str) -> str:
    return f"""You are evaluating whether a new signal supports, refutes, or is unrelated to a prediction.

PREDICTION: {prediction_claim}
MECHANISM: {prediction_mechanism}

NEW SIGNAL:
Title: {signal_title}
Content: {signal_body[:1500]}

Evaluate the relationship. Rules:
- Only score ≥ 0.3 if there is a DIRECT, specific connection — not just thematic overlap
- 'supports': signal provides evidence that the prediction is coming true
- 'refutes': signal provides evidence against the prediction
- 'partial': signal is weakly related or provides mixed evidence
- weight 0.0-0.29 = unrelated (don't write this to evidence)

Return JSON:
{{
  "stance": "supports|refutes|partial|unrelated",
  "weight": float 0.0-1.0,
  "note": "1-2 sentences explaining the connection (or null if unrelated)"
}}"""


def build_thread_predictions_prompt(thread_title: str, thread_body: str) -> str:
    return f"""You are a competitive intelligence analyst generating falsifiable forward-looking predictions.

Given this intelligence thread (a synthesized cluster of related signals):
TITLE: {thread_title}
SYNTHESIS: {thread_body[:2000]}

Generate 2-3 falsifiable, time-bounded second-order predictions. Each prediction is a specific consequence that should become observable within a defined timeframe IF this thread's pattern continues.

Rules:
- Be SPECIFIC and FALSIFIABLE — vague predictions are useless
- Time horizon: 30-180 days realistically; use 365 only for structural shifts
- Each prediction must have a clear falsifier (what would prove it wrong)
- Prefer leading indicators over lagging ones
- Do NOT restate the thread — predict the NEXT effect

Return JSON:
{{
  "predictions": [
    {{
      "claim": "string — complete falsifiable statement: 'If X, then Y will be observable via Z by [date]'",
      "mechanism": "string — 1-2 sentences explaining why this effect follows",
      "horizon_days": integer,
      "falsifier": "string — specific observable condition that would refute this",
      "confidence": integer 1-5,
      "indicator_type": "leading|concurrent|lagging"
    }}
  ]
}}"""


def build_predictions_prompt(signal_title: str, signal_body: str, domain: str) -> str:
    return f"""You are a competitive intelligence analyst generating falsifiable forward-looking predictions.

Given this signal:
DOMAIN: {domain}
TITLE: {signal_title}
BODY: {signal_body[:2000]}

Generate 2-3 falsifiable, time-bounded second-order predictions. Each prediction is a specific consequence that should become observable within a defined timeframe IF this signal's trend continues.

Rules:
- Be SPECIFIC and FALSIFIABLE — vague predictions are useless
- Time horizon: 30-180 days realistically; use 365 only for structural shifts
- Each prediction must have a clear falsifier (what would prove it wrong)
- Prefer leading indicators over lagging ones
- Do NOT restate the signal — predict the NEXT effect

Return JSON:
{{
  "predictions": [
    {{
      "claim": "string — complete falsifiable statement: 'If X, then Y will be observable via Z by [date]'",
      "mechanism": "string — 1-2 sentences explaining why this effect follows",
      "horizon_days": integer,
      "falsifier": "string — specific observable condition that would refute this",
      "confidence": integer 1-5,
      "indicator_type": "leading|concurrent|lagging"
    }}
  ]
}}"""
