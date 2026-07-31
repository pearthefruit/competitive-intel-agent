"""Binary, series-bound forecasts — the calibration-scoreable half of predictions.

Why this sits beside agents/predictions.py rather than inside it:

A prediction there is a qualitative claim with an LLM-chosen deadline, resolved by
an LLM judge weighing incoming signals. It cannot be scored for accuracy — the
model picks its own horizon (so "by when" has no external referent) and emits an
ordinal 1-5 confidence (so no proper scoring rule applies). Those predictions are
still useful for linking and narrative evidence; they are just not a track record.

A forecast here is a yes/no statement about a published data series: "UNRATE is
above 4.3% in the October 2026 observation." The date comes from the release
calendar, not the model. The probability is a real 0-1 credence. Resolution is a
number fetch, not a judgment. That makes it Brier-scoreable, which is the only way
to ever say how good the forecasts actually are.

Both live in the `predictions` table, discriminated by `resolution_kind`:
    NULL / 'llm_judge'  → existing qualitative path, untouched
    'series'            → this module

Two integration details that fall out for free, and one that did not:
  - `semantic_candidates()` filters on `claim_embedding IS NOT NULL`, and series
    forecasts deliberately leave it NULL, so they never reach the evidence judge.
    No change needed there.
  - `sweep_expired_predictions()` would have expired these on the qualitative
    grace window, which is wrong — their data lands on its own schedule. That
    sweep now skips them; abandonment is handled here instead.
"""

import datetime
import logging

from agents.llm import generate_json, FAST_CHAIN
from scraper.fred_api import KEY_INDICATORS, fetch_series

logger = logging.getLogger(__name__)

VALID_SERIES = {e["series_id"]: e for e in KEY_INDICATORS}

# Typical publication lag by series cadence, used only to decide when a forecast
# is overdue or abandonable. Resolution itself waits for the observation to land,
# so a late release delays scoring rather than corrupting it.
_LAG_DAYS = {"daily": 4, "weekly": 10, "monthly": 45, "quarterly": 95}

# Cadence per series. FRED exposes this via get_series_info(), but that is an
# extra API call per series per run for a value that effectively never changes.
_CADENCE = {
    "UNRATE": "monthly", "PAYEMS": "monthly", "CPIAUCSL": "monthly",
    "GDP": "quarterly", "FEDFUNDS": "monthly", "DGS10": "daily",
    "DEXUSEU": "daily", "VIXCLS": "daily", "ICSA": "weekly",
    "HOUST": "monthly", "RSXFS": "monthly", "INDPRO": "monthly",
    "UMCSENT": "monthly", "T10YIE": "daily", "BAMLH0A0HYM2": "daily",
}

# What quantity a forecast about each series compares against.
#
# 'level' suits series that mean-revert within a bounded range — a rate, ratio or
# spread. A threshold near the current value stays genuinely uncertain.
#
# 'change_pct' is required for trending index levels and cumulative counts. Their
# level rises almost monotonically, so a threshold set near the current value is
# settled by drift alone regardless of what any signal says: the very first CPI
# forecast this system produced was "CPI below 333.0" against a 332.568 baseline,
# which two months of ordinary inflation breaks on its own. Forecasting the
# period-over-period change instead is also what actual forecasters do — nobody
# predicts the CPI index level, they predict the inflation rate.
_BASIS = {
    "CPIAUCSL": "change_pct", "PAYEMS": "change_pct", "GDP": "change_pct",
    "RSXFS": "change_pct", "INDPRO": "change_pct",
    "UNRATE": "level", "FEDFUNDS": "level", "DGS10": "level",
    "DEXUSEU": "level", "VIXCLS": "level", "ICSA": "level",
    "HOUST": "level", "UMCSENT": "level", "T10YIE": "level",
    "BAMLH0A0HYM2": "level",
}

# A daily series is not guaranteed to print on the exact target date (weekends,
# holidays), so resolution accepts the next observation within this window. Wider
# than this and we would be scoring against a materially different period.
_PERIOD_TOLERANCE_DAYS = 10

# How many past observations to fetch when showing the model what a normal
# period-over-period move looks like for a change-basis series.
_CHANGE_HISTORY = 7

# Give up on a forecast whose data never arrives. Generous — a delayed release
# should never be recorded as a miss, since that would bias the Brier score.
_ABANDON_AFTER_DAYS = 120

MAX_FORECASTS_PER_SIGNAL = 2


class ForecastUnavailable(RuntimeError):
    """The LLM could not be reached — NOT a decision to decline.

    These two must never collapse into the same result. `generate_json` returns
    None when every provider fails, and an empty forecast list is also a normal,
    expected outcome, so a naive `(result or {}).get(...)` reports a total outage
    as "the model considered this signal and declined." That silently drills holes
    in the calibration record which look like conservatism rather than downtime.
    """


def cadence(series_id: str) -> str:
    return _CADENCE.get(series_id, "monthly")


def basis(series_id: str) -> str:
    """Which quantity forecasts about this series compare. Not the model's choice.

    Letting the LLM pick the basis would just move the level-vs-change mistake one
    step upstream; the right basis is a fixed property of the series.
    """
    return _BASIS.get(series_id, "level")


def _pct_change(current: float, prior: float):
    """Period-over-period % change, or None if it is not computable."""
    if prior in (None, 0) or current is None:
        return None
    return (current - prior) / abs(prior) * 100.0


def _expected_release(target_period: str, series_id: str) -> str:
    """Approximate date the observation for target_period becomes public."""
    d = datetime.date.fromisoformat(target_period)
    return (d + datetime.timedelta(days=_LAG_DAYS[cadence(series_id)])).isoformat()


def build_catalog(limit_domains=None) -> list:
    """Catalog entries enriched with each series' current value.

    The live value is what keeps thresholds meaningful — a model guessing blind
    picks bounds that are already settled, which produces forecasts that score
    perfectly and mean nothing.
    """
    entries = []
    for ind in KEY_INDICATORS:
        if limit_domains and ind["domain"] not in limit_domains:
            continue
        sid = ind["series_id"]
        want = _CHANGE_HISTORY + 1 if basis(sid) == "change_pct" else 1
        obs = fetch_series(sid, limit=want)
        if not obs:
            # Deliberately dropped rather than offered without a value. A series
            # the model cannot see the current level of produces thresholds that
            # are already settled, and those score perfectly while meaning
            # nothing. No key at all → empty catalog → generation no-ops.
            continue

        entry = dict(ind)
        entry["frequency"] = cadence(sid)
        entry["basis"] = basis(sid)
        entry["latest_value"] = obs[0]["value"]
        entry["latest_date"] = obs[0]["date"]

        if entry["basis"] == "change_pct":
            # Showing the level alone is not enough here — the model needs to see
            # what a normal move looks like, or it anchors its threshold on the
            # level and lands right back in the drift trap.
            changes = []
            for newer, older in zip(obs, obs[1:]):
                ch = _pct_change(newer["value"], older["value"])
                if ch is not None:
                    changes.append({"date": newer["date"], "change_pct": round(ch, 3)})
            if not changes:
                continue
            entry["recent_changes"] = changes
            entry["latest_change_pct"] = changes[0]["change_pct"]

        entries.append(entry)
    return entries


def _validate(f: dict, today: datetime.date) -> tuple:
    """Return (cleaned_forecast, None) or (None, reason). Rejects, never repairs.

    A forecast that needs fixing up is one the model did not really make; silently
    correcting it would put a claim in the ledger that nothing actually predicted.
    """
    sid = (f.get("series_id") or "").strip()
    if sid not in VALID_SERIES:
        return None, f"unknown series_id {sid!r}"

    comparator = (f.get("comparator") or "").strip().lower()
    if comparator not in ("above", "below"):
        return None, f"bad comparator {comparator!r}"

    try:
        threshold = float(f["threshold"])
        probability = float(f["probability"])
    except (KeyError, TypeError, ValueError):
        return None, "threshold/probability not numeric"

    if not 0.0 <= probability <= 1.0:
        return None, f"probability {probability} out of range"

    try:
        target = datetime.date.fromisoformat((f.get("target_period") or "").strip())
    except ValueError:
        return None, f"bad target_period {f.get('target_period')!r}"
    if target <= today:
        return None, f"target_period {target} is not in the future"

    b = basis(sid)
    if b == "change_pct" and cadence(sid) == "daily":
        # Change basis needs a well-defined prior period; daily series are not
        # mapped to it, so this would be a configuration error rather than a
        # model error. Guard anyway.
        return None, f"{sid} is daily and cannot use change basis"

    return {
        "series_id": sid,
        "basis": b,
        "comparator": comparator,
        "threshold": threshold,
        "probability": probability,
        "target_period": target.isoformat(),
        "claim": (f.get("claim") or "").strip() or _default_claim(sid, b, comparator, threshold, target),
        "rationale": (f.get("rationale") or "").strip(),
    }, None


def _default_claim(series_id, basis_kind, comparator, threshold, target) -> str:
    label = VALID_SERIES[series_id]["label"]
    unit = VALID_SERIES[series_id].get("unit", "")
    if basis_kind == "change_pct":
        direction = "rises more than" if comparator == "above" else "rises less than"
        return f"{label} {direction} {threshold}% in the {target.isoformat()} observation"
    return f"{label} is {comparator} {threshold}{unit} in the {target.isoformat()} observation"


def generate_forecasts_for_signal(signal_id: int, signal_title: str, signal_body: str,
                                  domain: str, db, catalog=None) -> list:
    """Generate 0-2 binary forecasts for a signal. Returns new prediction ids.

    Empty is a normal, common result — most signals bear on no macro series, and
    the prompt is written to say so rather than reach for one.
    """
    from prompts.forecasts import build_binary_forecast_prompt

    today = datetime.date.today()
    catalog = catalog if catalog is not None else build_catalog()
    if not catalog:
        logger.warning("Forecast catalog empty (FRED_API_KEY missing?) — skipping")
        return []

    prompt = build_binary_forecast_prompt(
        signal_title, signal_body or "", domain or "general", catalog, today.isoformat()
    )
    try:
        result = generate_json(prompt, chain=FAST_CHAIN, expect="object",
                               required_keys=["forecasts"])
    except Exception as e:
        raise ForecastUnavailable(f"LLM call failed for signal {signal_id}: {e}") from e

    if result is None:
        # Distinct from {"forecasts": []}, which is the model actually declining.
        raise ForecastUnavailable(
            f"All LLM providers failed for signal {signal_id} — no forecast was judged"
        )

    raw = result.get("forecasts") or []

    new_ids = []
    for f in raw[:MAX_FORECASTS_PER_SIGNAL]:
        clean, reason = _validate(f, today)
        if not clean:
            logger.info(f"Rejected forecast for signal {signal_id}: {reason}")
            continue

        entry = next((c for c in catalog if c["series_id"] == clean["series_id"]), {})
        # Baseline is stored on the same footing as the threshold, so "was this
        # forecast near the money when it was made?" stays answerable later.
        baseline = (entry.get("latest_change_pct") if clean["basis"] == "change_pct"
                    else entry.get("latest_value"))
        expected_by = _expected_release(clean["target_period"], clean["series_id"])
        horizon = (datetime.date.fromisoformat(expected_by) - today).days
        unit_txt = "% change" if clean["basis"] == "change_pct" else ""

        cur = db.execute(
            """INSERT INTO predictions
               (parent_kind, parent_id, claim, mechanism, horizon_days, expected_by,
                falsifier, confidence, indicator_type, resolution_kind, probability,
                series_id, comparator, threshold, target_period, baseline_value, basis)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'series', ?, ?, ?, ?, ?, ?, ?)""",
            ('signal', signal_id,
             clean["claim"],
             clean["rationale"],
             horizon,
             expected_by,
             f"The {clean['target_period']} observation of {clean['series_id']} comes in "
             f"{'at or below' if clean['comparator'] == 'above' else 'at or above'} "
             f"{clean['threshold']}{unit_txt}",
             # confidence is the legacy 1-5 ordinal; derive it so existing list/detail
             # UI renders these sanely, but probability is what actually gets scored.
             max(1, min(5, round(abs(clean["probability"] - 0.5) * 8) + 1)),
             'leading',
             clean["probability"],
             clean["series_id"],
             clean["comparator"],
             clean["threshold"],
             clean["target_period"],
             baseline,
             clean["basis"])
        )
        new_ids.append(cur.lastrowid)

    db.commit()
    if new_ids:
        logger.info(f"Generated {len(new_ids)} binary forecasts for signal {signal_id}")
    return new_ids


# ── Resolution ────────────────────────────────────────────────────────────────

def _find_observation(series_id: str, target_period: str):
    """Return (observation, prior_observation) settling target_period.

    Returns (None, None) if the target observation has not printed yet. `prior` is
    the immediately preceding observation, needed for change-basis resolution; it
    is None when the target is the first point in the fetched range.

    FRED dates an observation at the START of its period (October monthly data is
    2026-10-01), so an exact match is the common case. Daily series can skip the
    exact date for weekends and holidays, hence the bounded look-forward.
    """
    target = datetime.date.fromisoformat(target_period)
    # No observation_start: we need points BEFORE the target as well, to compute
    # the period-over-period change. 150 covers a decade of monthly data and
    # ~7 months of daily.
    obs = fetch_series(series_id, limit=150)
    if not obs:
        return None, None

    # fetch_series returns newest-first; scan oldest-first for the first
    # observation at or after the target period.
    candidates = sorted(obs, key=lambda o: o["date"])
    for i, o in enumerate(candidates):
        d = datetime.date.fromisoformat(o["date"])
        prior = candidates[i - 1] if i > 0 else None
        if d == target:
            return o, prior
        if d > target:
            if (d - target).days <= _PERIOD_TOLERANCE_DAYS:
                return o, prior
            return None, None
    return None, None


def resolve_due_forecasts(db, limit: int = 200) -> dict:
    """Resolve series forecasts whose data has landed. Returns counts.

    Cheap and idempotent — safe on a cron or on every predictions list request.
    Only touches rows whose target period has passed; a forecast whose data is
    merely late stays open rather than counting as a miss.
    """
    today = datetime.date.today()
    rows = db.execute(
        """SELECT id, series_id, comparator, threshold, target_period, probability, basis
           FROM predictions
           WHERE resolution_kind = 'series' AND status = 'open'
             AND target_period <= ?
           ORDER BY target_period LIMIT ?""",
        (today.isoformat(), limit),
    ).fetchall()

    resolved = abandoned = pending = 0
    for r in rows:
        try:
            obs, prior = _find_observation(r["series_id"], r["target_period"])
        except Exception as e:
            logger.warning(f"Fetch failed resolving forecast {r['id']}: {e}")
            pending += 1
            continue

        if not obs:
            overdue = (today - datetime.date.fromisoformat(r["target_period"])).days
            if overdue > _ABANDON_AFTER_DAYS:
                db.execute(
                    """UPDATE predictions SET status = 'expired',
                       resolved_at = CURRENT_TIMESTAMP,
                       resolution_note = ?
                       WHERE id = ?""",
                    (f"Abandoned — no observation for {r['target_period']} after "
                     f"{overdue} days. Not scored.", r["id"]),
                )
                abandoned += 1
            else:
                pending += 1
            continue

        level = obs["value"]
        # NULL basis = a row created before the change-basis path existed. Those
        # were made as level forecasts and must resolve as level forecasts —
        # re-interpreting a forecast after the fact is how a record stops meaning
        # anything.
        is_change = (r["basis"] == "change_pct")

        if is_change:
            compared = _pct_change(level, prior["value"] if prior else None)
            if compared is None:
                logger.warning(
                    f"Forecast {r['id']}: no prior observation for change basis — left open")
                pending += 1
                continue
            detail = (f"{r['series_id']} moved {compared:+.2f}% "
                      f"({prior['value']} → {level}) for {obs['date']}")
        else:
            compared = level
            detail = f"{r['series_id']} printed {level} for {obs['date']}"

        outcome = 1 if (compared > r["threshold"] if r["comparator"] == "above"
                        else compared < r["threshold"]) else 0
        brier = (r["probability"] - outcome) ** 2
        thr_unit = "%" if is_change else ""

        db.execute(
            """UPDATE predictions
               SET status = ?, resolved_at = CURRENT_TIMESTAMP,
                   resolved_value = ?, resolved_level = ?, prior_value = ?,
                   outcome = ?, brier_score = ?, resolution_note = ?
               WHERE id = ?""",
            ('confirmed' if outcome else 'refuted',
             compared, level, (prior["value"] if prior else None), outcome, brier,
             f"{detail} (threshold {r['comparator']} {r['threshold']}{thr_unit}). "
             f"Forecast {r['probability']:.0%} → Brier {brier:.3f}",
             r["id"]),
        )
        resolved += 1

    db.commit()
    if resolved or abandoned:
        logger.info(f"Forecasts: {resolved} resolved, {abandoned} abandoned, {pending} pending")
    return {"resolved": resolved, "abandoned": abandoned, "pending": pending}


# ── Calibration ───────────────────────────────────────────────────────────────

# Reference points for reading a Brier score. 0.25 is what you get by saying 50%
# to everything, so it is the line a forecast has to beat to be worth anything.
BRIER_COINFLIP = 0.25


def brier_summary(db) -> dict:
    """Calibration record over resolved binary forecasts.

    Includes a reliability table (predicted vs. actual frequency by probability
    bucket) because an aggregate Brier hides the thing you most want to know:
    whether "70%" actually means 70%.
    """
    rows = db.execute(
        """SELECT probability, outcome, brier_score, series_id
           FROM predictions
           WHERE resolution_kind = 'series' AND brier_score IS NOT NULL"""
    ).fetchall()

    if not rows:
        return {"n": 0, "brier": None, "vs_coinflip": None,
                "base_rate": None, "buckets": [], "by_series": []}

    n = len(rows)
    brier = sum(r["brier_score"] for r in rows) / n
    base_rate = sum(r["outcome"] for r in rows) / n

    buckets = []
    for lo in [0.0, 0.2, 0.4, 0.6, 0.8]:
        hi = lo + 0.2
        # Top bucket is closed so a 1.0 forecast is not dropped.
        sel = [r for r in rows if lo <= r["probability"] < hi or (hi == 1.0 and r["probability"] == 1.0)]
        if sel:
            buckets.append({
                "range": f"{lo:.0%}-{hi:.0%}",
                "n": len(sel),
                "predicted": sum(r["probability"] for r in sel) / len(sel),
                "actual": sum(r["outcome"] for r in sel) / len(sel),
            })

    by_series = {}
    for r in rows:
        by_series.setdefault(r["series_id"], []).append(r["brier_score"])

    return {
        "n": n,
        "brier": round(brier, 4),
        "vs_coinflip": round(BRIER_COINFLIP - brier, 4),  # positive = better than chance
        "base_rate": round(base_rate, 3),
        "buckets": buckets,
        "by_series": sorted(
            ({"series_id": k, "n": len(v), "brier": round(sum(v) / len(v), 4)}
             for k, v in by_series.items()),
            key=lambda d: d["brier"],
        ),
    }
