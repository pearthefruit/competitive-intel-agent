"""Prompts for binary, series-bound forecasts.

Distinct from prompts/predictions.py: those produce qualitative claims resolved by
an LLM judge over incoming signals. These produce yes/no forecasts bound to a
public data series, resolved by fetching a number. The difference that matters is
not the presence of a number in the text — it is that nothing here requires human
judgment to settle.

Two constraints do the heavy lifting:
  1. The model picks a series from a fixed catalog. Free-form series IDs hallucinate.
  2. The model is shown each series' CURRENT value. Without it, thresholds land
     either already-true or absurd, and the forecast is unscoreable in practice.
"""


def format_catalog(entries: list) -> str:
    """Render catalog entries as prompt text, grouped by what a threshold means.

    The two groups are kept visually separate because the single most damaging
    mistake here is setting a level threshold on a trending index — it gets
    settled by drift rather than by anything the signal said.
    """
    level, change = [], []
    for e in entries:
        sid, unit = e["series_id"], e.get("unit", "")
        freq = e.get("frequency", "periodic")
        if e.get("basis") == "change_pct":
            hist = ", ".join(f"{c['change_pct']:+.2f}%" for c in e.get("recent_changes", [])[:6])
            change.append(
                f"- {sid} — {e['label']} ({freq})\n"
                f"    latest period-over-period change: "
                f"{e.get('latest_change_pct', 0):+.2f}%  (as of {e.get('latest_date', '?')})\n"
                f"    recent changes, newest first: {hist}\n"
                f"    [level is currently {e.get('latest_value')}{unit} — context only, "
                f"DO NOT set a threshold on it]"
            )
        else:
            level.append(
                f"- {sid} — {e['label']} ({freq}, currently "
                f"{e.get('latest_value')}{unit} as of {e.get('latest_date', '?')})"
            )

    out = []
    if level:
        out.append("GROUP A — forecast the LEVEL. Your threshold is a value the "
                   "series itself will print.\n" + "\n".join(level))
    if change:
        out.append("GROUP B — forecast the PERCENT CHANGE from the prior period. "
                   "Your threshold is a percentage,\nNOT a level. These series trend "
                   "upward almost every period, so a threshold on the level is\n"
                   "decided by drift alone and tells us nothing.\n" + "\n".join(change))
    return "\n\n".join(out)


def build_binary_forecast_prompt(signal_title: str, signal_body: str, domain: str,
                                 catalog_entries: list, today: str) -> str:
    catalog = format_catalog(catalog_entries)
    valid_ids = ", ".join(e["series_id"] for e in catalog_entries)

    return f"""You are a forecaster. Today is {today}.

Given this intelligence signal, produce 0-2 BINARY forecasts about published
economic data — each one a yes/no question that a public data release will settle
without any human judgment.

SIGNAL DOMAIN: {domain}
TITLE: {signal_title}
BODY: {signal_body[:2000]}

AVAILABLE SERIES (you MUST use one of these exact IDs — no others exist):
{catalog}

Valid series_id values: {valid_ids}

WHEN TO FORECAST, AND WHEN TO DECLINE.

Forecast when the signal is about US macroeconomic conditions or a direct driver
of one of the series above. This includes: a data release for one of these series
(a CPI report, a jobs report, a Fed decision), monetary or fiscal policy news,
energy or commodity price moves, credit and rate conditions, or broad US labor
market news. If the signal is a US data release for one of these series, you
SHOULD produce a forecast about that series' next reading — that is the clearest
case there is, not a marginal one.

Decline — return an empty list — when the signal has no bearing on these US
series: company-specific news, sports, culture, local stories, or macro news about
a country whose data is not in the catalog above (the catalog is US-only, so a
report on Russian or Chinese inflation does not license a forecast about US CPI
unless the signal itself argues a US transmission channel).

Both errors are real. A forced, unrelated forecast pollutes the calibration record
permanently; but declining on a signal that plainly bears on one of these series
throws away the forecasts most worth making. Judge the signal, do not default
either way.

Rules for each forecast:
- Pick the ONE series this signal most directly bears on.
- THE THRESHOLD MEANS DIFFERENT THINGS IN THE TWO GROUPS. Get this right:
    * Group A (level): threshold is a level. "UNRATE above 4.4" means the
      unemployment rate prints above 4.4%.
    * Group B (percent change): threshold is a PERCENT CHANGE from the prior
      period. "CPIAUCSL above 0.3" means CPI rises MORE THAN 0.3% that period —
      it does NOT mean the index is above 0.3. Anchor it on the recent changes
      listed for that series, never on its level.
- Set the threshold near, but not at, the relevant recent value — the current
  level for Group A, the recent change for Group B. The forecast must be
  genuinely uncertain: if it is already settled, it is worthless. Aim for
  something you'd put between 20% and 80% on.
- `probability` is your honest credence that the statement is TRUE, as a decimal
  0.0-1.0. This is scored with a Brier score, so both overconfidence and
  hedging everything to 0.5 are penalized. Say 0.85 when you mean it; say 0.55
  when it is nearly a coin flip.
- `target_period` is the ISO date (YYYY-MM-DD) of the OBSERVATION you are
  forecasting, not the release date. Monthly series are dated the 1st of their
  month (e.g. October data is 2026-10-01). Pick a period 1-4 releases out,
  and it MUST be after {today}.
- `rationale` connects the signal to the series in 1-2 sentences. If you cannot
  state a mechanism, that is a sign this forecast should not exist.

Return JSON:
{{
  "forecasts": [
    {{
      "series_id": "one of the exact IDs above",
      "comparator": "above|below",
      "threshold": float,
      "target_period": "YYYY-MM-DD",
      "probability": float 0.0-1.0,
      "rationale": "string",
      "claim": "string — plain English. Group A: 'Unemployment rate is above 4.3% in the October 2026 reading'. Group B: 'CPI rises more than 0.3% in the October 2026 reading'"
    }}
  ]
}}"""
