"""Prompt builder for extracting market signals from Instagram post captions."""


def build_signal_extraction_prompt(caption, post_date, handle):
    return f"""You are a financial intelligence analyst. Extract factual market signals from this Instagram post caption.

Source: @{handle}
Post date: {post_date}
Caption:
{caption}

Return a JSON array of signals (max 8). Each signal must be explicitly stated in the caption — no inference, no hallucination.

Schema:
[{{
  "title": "concise signal title, max 12 words",
  "body": "1-2 sentence expanded context with specifics from the caption",
  "company_or_ticker": "primary company name or ticker symbol, or null if macro",
  "signal_type": "one of: macro|earnings|regulatory|m_and_a|product_launch|leadership|geopolitical|crypto|market_move",
  "confidence": 0.0
}}]

Rules:
- Only extract facts explicitly stated in the caption. Never infer or guess.
- confidence is your self-assessed certainty that this is a real, actionable signal (0.0-1.0)
- If the caption contains no meaningful signals, return an empty array []
- Do not include vague statements like "markets were mixed"
- Titles must be specific: include company names, percentages, or specific claims
- Return ONLY the JSON array, no other text"""
