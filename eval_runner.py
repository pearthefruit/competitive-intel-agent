"""eval_runner.py — measure lens scoring variance across N runs with frozen inputs.

Usage:
    python eval_runner.py                        # run default companies + lens
    python eval_runner.py --n 3                  # fewer runs (faster, cheaper)
    python eval_runner.py --company "HPE"        # single company (DB name lookup)
    python eval_runner.py --lens ctv-ad-sales    # different lens
    python eval_runner.py --run-analyses         # fetch missing analyses first
    python eval_runner.py --list-runs            # show past eval sessions
    python eval_runner.py --show-run <run_id>    # reprint stats for a session
"""

from dotenv import load_dotenv
load_dotenv()

import argparse
import json
import statistics
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = "intel.db"
DEFAULT_LENS = "digital-transformation"
DEFAULT_N = 5

# Names must match dossiers table exactly — use --company <partial> for fuzzy lookup
DEFAULT_COMPANIES = [
    {"name": "Hewlett Packard Enterprise", "website": "https://www.hpe.com"},
    {"name": "Honeywell",                  "website": "https://www.honeywell.com"},
    {"name": "Caterpillar",                "website": "https://www.caterpillar.com"},
    {"name": "Kroger",                     "website": "https://www.kroger.com"},
    {"name": "UnitedHealth",               "website": "https://www.unitedhealthgroup.com"},
]


# ── report loading ────────────────────────────────────────────────────────────

def _get_all_report_paths(company_name, max_age_days=90):
    """Return all available analysis reports for a company, not just lens-required ones."""
    from db import get_connection
    conn = get_connection(DB_PATH)
    rows = conn.execute(
        """SELECT da.analysis_type, da.report_file
           FROM dossier_analyses da
           JOIN dossiers d ON da.dossier_id = d.id
           WHERE d.company_name = ? COLLATE NOCASE
             AND da.report_file IS NOT NULL
           ORDER BY da.created_at DESC""",
        (company_name,),
    ).fetchall()
    conn.close()

    seen, paths = set(), {}
    for row in rows:
        atype = row["analysis_type"]
        if atype in seen:
            continue  # keep most recent per type
        fpath = Path(row["report_file"])
        if fpath.exists():
            paths[atype] = str(fpath)
            seen.add(atype)
    return paths


def _run_fresh_analyses(company_name, required_analyses, website_url):
    from agents.lens import _find_recent_report, _run_analysis
    paths = {}
    for atype in required_analyses:
        existing = _find_recent_report(company_name, atype, db_path=DB_PATH)
        if existing:
            paths[atype] = existing
            continue
        print(f"  [analyses] Running {atype} for {company_name}...")
        try:
            path = _run_analysis(atype, company_name, website_url, DB_PATH)
            if path:
                paths[atype] = path
                print(f"  [analyses] {atype} → {path}")
            else:
                print(f"  [analyses] {atype} returned no report")
        except Exception as e:
            print(f"  [analyses] {atype} failed: {e}")
    return paths


# ── model tracking ────────────────────────────────────────────────────────────

def _get_last_model_used():
    """Query llm_usage for the model used in the most recent LLM call."""
    try:
        from db import get_connection
        conn = get_connection(DB_PATH)
        row = conn.execute(
            "SELECT model FROM llm_usage ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return row["model"] if row else "unknown"
    except Exception:
        return "unknown"


# ── scoring ───────────────────────────────────────────────────────────────────

def _score_once(prompt, dimensions, labels):
    """Single LLM scoring call. Returns (score_data, model_used) or (None, None)."""
    from agents.llm import generate_json, BRIEFING_CHAIN
    from agents.lens import _get_label

    score_data = generate_json(prompt, timeout=90, chain=BRIEFING_CHAIN)
    model_used = _get_last_model_used()

    if not isinstance(score_data, dict) or "sub_scores" not in score_data:
        return None, model_used

    sub_scores = score_data.get("sub_scores", {})
    overall = 0.0
    for dim in dimensions:
        raw = sub_scores.get(dim["key"], {})
        s = raw.get("score", 50) if isinstance(raw, dict) else 50
        try:
            s = int(s)
        except (ValueError, TypeError):
            s = 50
        s = max(0, min(100, s))
        overall += s * dim["weight"]

    score_data["overall_score"] = round(overall)
    score_data["overall_label"] = _get_label(round(overall), labels)
    return score_data, model_used


# ── stats & reporting ─────────────────────────────────────────────────────────

def _build_stats(company_name, run_records, dimensions):
    """Compute per-dimension stats. Returns a dict for both printing and export."""
    run_scores = [r["score_data"] for r in run_records]
    models_used = [r.get("model", "unknown") for r in run_records]
    unique_models = list(dict.fromkeys(models_used))  # preserve order, deduplicate

    overalls = [s["overall_score"] for s in run_scores]
    tier_labels = [s.get("overall_label", "?") for s in run_scores]
    unique_tiers = list(dict.fromkeys(tier_labels))

    overall_stats = {
        "min": min(overalls), "max": max(overalls),
        "mean": statistics.mean(overalls),
        "std": statistics.stdev(overalls) if len(overalls) > 1 else 0,
    }
    overall_stats["cov"] = (overall_stats["std"] / overall_stats["mean"] * 100) if overall_stats["mean"] else 0

    dim_stats = {}
    for dim in dimensions:
        key = dim["key"]
        scores = []
        for s in run_scores:
            raw = s.get("sub_scores", {}).get(key, {})
            val = raw.get("score", 50) if isinstance(raw, dict) else 50
            try:
                scores.append(int(val))
            except (ValueError, TypeError):
                scores.append(50)
        mean_d = statistics.mean(scores)
        std_d = statistics.stdev(scores) if len(scores) > 1 else 0
        dim_stats[key] = {
            "label": dim["label"],
            "min": min(scores), "max": max(scores),
            "mean": mean_d, "std": std_d,
            "cov": (std_d / mean_d * 100) if mean_d else 0,
        }

    return {
        "company": company_name,
        "n_runs": len(run_records),
        "overall": overall_stats,
        "dims": dim_stats,
        "tier_labels": tier_labels,
        "unique_tiers": unique_tiers,
        "models": models_used,
        "unique_models": unique_models,
        "run_scores": run_scores,
    }


def _print_stats(stats):
    company = stats["company"]
    n = stats["n_runs"]
    if n < 2:
        print(f"  {company}: only {n} run(s) — need ≥2 for stats\n")
        return

    o = stats["overall"]
    tier_stable = "✓ stable" if len(stats["unique_tiers"]) == 1 else f"✗ FLIPS: {' / '.join(stats['unique_tiers'])}"
    model_note = stats["unique_models"][0] if len(stats["unique_models"]) == 1 else f"⚠ MIXED: {', '.join(stats['unique_models'])}"

    print(f"\n  ┌── {company} ({n} runs) ──")
    flag_o = "  ← HIGH VARIANCE" if o["cov"] > 10 else ""
    print(f"  │ Overall      {o['min']:3d}–{o['max']:3d}  mean={o['mean']:5.1f}  std={o['std']:4.1f}  CoV={o['cov']:4.1f}%  tier={tier_stable}{flag_o}")
    for key, d in stats["dims"].items():
        flag = "  ← HIGH VARIANCE" if d["cov"] > 10 else ""
        print(f"  │ {d['label']:<22s} {d['min']:3d}–{d['max']:3d}  mean={d['mean']:5.1f}  std={d['std']:4.1f}  CoV={d['cov']:4.1f}%{flag}")
    print(f"  │ Model: {model_note}")
    print(f"  └{'─' * 60}")


def _export_markdown(all_stats, lens_name, run_id, n_runs, reports_dir="reports"):
    """Save a clean markdown report to reports/eval_<run_id>_<date>.md."""
    Path(reports_dir).mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = Path(reports_dir) / f"eval_{run_id}_{date_str}.md"

    lines = [
        f"# SignalVault Eval Report — {lens_name}",
        f"",
        f"**Session:** `{run_id}` | **Date:** {date_str} | **Runs per company:** {n_runs}",
        f"",
        f"## What This Measures",
        f"",
        f"Each company is scored {n_runs} times using identical frozen input reports. "
        f"The same evidence is passed to the LLM every run — only sampling randomness varies. "
        f"Coefficient of Variation (CoV) measures score stability: <5% is excellent, <10% is acceptable, >10% flags a volatile dimension.",
        f"",
        f"---",
        f"",
    ]

    for stats in all_stats:
        company = stats["company"]
        n = stats["n_runs"]
        o = stats["overall"]
        tier_stable = "✓ Stable" if len(stats["unique_tiers"]) == 1 else f"⚠ Flips: {' / '.join(stats['unique_tiers'])}"
        model_note = stats["unique_models"][0] if len(stats["unique_models"]) == 1 else f"⚠ Mixed: {', '.join(stats['unique_models'])}"

        lines += [
            f"## {company}",
            f"",
            f"**Model:** {model_note} | **Tier stability:** {tier_stable} | **Runs completed:** {n}/{n_runs}",
            f"",
            f"| Run | Overall | " + " | ".join(d["label"] for d in stats["dims"].values()) + " | Tier |",
            f"|-----|---------|" + "---------|" * len(stats["dims"]) + "------|",
        ]

        for i, s in enumerate(stats["run_scores"], 1):
            sub = s.get("sub_scores", {})
            dim_scores = []
            for key in stats["dims"]:
                raw = sub.get(key, {})
                val = raw.get("score", "?") if isinstance(raw, dict) else "?"
                dim_scores.append(str(val))
            lines.append(
                f"| {i} | {s['overall_score']} | " + " | ".join(dim_scores) + f" | {s.get('overall_label', '?')} |"
            )

        lines += [
            f"",
            f"**Variance summary:**",
            f"",
            f"| Dimension | Min | Max | Mean | Std | CoV | Status |",
            f"|-----------|-----|-----|------|-----|-----|--------|",
        ]

        flag_o = "⚠ HIGH" if o["cov"] > 10 else "✓"
        lines.append(f"| Overall | {o['min']} | {o['max']} | {o['mean']:.1f} | {o['std']:.1f} | {o['cov']:.1f}% | {flag_o} |")
        for key, d in stats["dims"].items():
            flag = "⚠ HIGH" if d["cov"] > 10 else "✓"
            lines.append(f"| {d['label']} | {d['min']} | {d['max']} | {d['mean']:.1f} | {d['std']:.1f} | {d['cov']:.1f}% | {flag} |")

        lines += ["", "---", ""]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return str(out_path)


# ── main eval loop ────────────────────────────────────────────────────────────

def run_eval(companies, lens_slug, n_runs, run_analyses=False):
    from db import get_connection, get_lens_by_slug, save_eval_run
    from agents.lens import _get_required_analyses, _read_and_truncate_reports
    from prompts.lens import build_lens_scoring_prompt

    conn = get_connection(DB_PATH)
    lens = get_lens_by_slug(conn, lens_slug)
    conn.close()

    if not lens:
        print(f"[eval] Lens '{lens_slug}' not found in DB")
        return

    config = lens["config"]
    dimensions = config.get("dimensions", [])
    labels = config.get("labels", [])
    run_id = uuid.uuid4().hex[:8]
    started = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"\n{'='*65}")
    print(f"  Eval session {run_id}  |  {lens['name']}  |  N={n_runs}  |  {started}")
    print(f"  Companies: {', '.join(c['name'] for c in companies)}")
    print(f"{'='*65}\n")

    all_stats = []

    for company_info in companies:
        company = company_info["name"]
        website = company_info.get("website")

        # Use all available reports, not just lens-required ones
        if run_analyses:
            required = _get_required_analyses(dimensions, website)
            report_paths = _run_fresh_analyses(company, required, website)
        else:
            report_paths = _get_all_report_paths(company)

        if not report_paths:
            print(f"  {company}: no reports found. Run with --run-analyses to fetch them.\n")
            continue

        reports = _read_and_truncate_reports(report_paths)
        input_snapshot = {"report_paths": report_paths, "reports_used": list(report_paths.keys())}
        prompt = build_lens_scoring_prompt(company, config, reports, website)

        print(f"  {company} — {len(report_paths)} report(s): {', '.join(report_paths.keys())}")

        run_records = []
        for i in range(1, n_runs + 1):
            print(f"    run {i}/{n_runs}...", end=" ", flush=True)
            score_data, model_used = _score_once(prompt, dimensions, labels)

            if score_data is None:
                print(f"FAILED  [{model_used}]")
                continue

            overall = score_data["overall_score"]
            tier = score_data["overall_label"]
            print(f"{overall:3d}  {tier:<25s}  [{model_used}]")

            run_records.append({"score_data": score_data, "model": model_used, "run_number": i})

            # Commit per run to avoid DB lock during LLM calls
            conn = get_connection(DB_PATH)
            save_eval_run(conn, run_id, company, lens["id"], i, input_snapshot, score_data, model=model_used)
            conn.commit()
            conn.close()

        if run_records:
            stats = _build_stats(company, run_records, dimensions)
            all_stats.append(stats)
            _print_stats(stats)

    if all_stats:
        report_path = _export_markdown(all_stats, lens["name"], run_id, n_runs)
        print(f"\nReport saved → {report_path}")

    print(f"Run ID: {run_id}  (use --show-run {run_id} to revisit)\n")


# ── list / show past runs ─────────────────────────────────────────────────────

def list_runs():
    from db import get_connection
    conn = get_connection(DB_PATH)
    rows = conn.execute(
        """SELECT run_id, COUNT(*) as n_calls,
                  COUNT(DISTINCT company_name) as n_companies,
                  GROUP_CONCAT(DISTINCT model) as models,
                  MIN(ran_at) as started
           FROM eval_runs
           GROUP BY run_id ORDER BY started DESC"""
    ).fetchall()
    conn.close()
    if not rows:
        print("No eval runs saved yet.")
        return
    print(f"\n{'Run ID':<12} {'Calls':>6} {'Co.':>4}  {'Model(s)':<30}  Started")
    print("-" * 70)
    for r in rows:
        print(f"{r['run_id']:<12} {r['n_calls']:>6} {r['n_companies']:>4}  {str(r['models'] or ''):<30}  {r['started'][:16]}")
    print()


def show_run(run_id):
    from db import get_connection, get_eval_runs

    conn = get_connection(DB_PATH)
    runs = get_eval_runs(conn, run_id=run_id)
    lens_id = runs[0]["lens_id"] if runs else None
    lens_row = conn.execute("SELECT * FROM lenses WHERE id=?", (lens_id,)).fetchone() if lens_id else None
    conn.close()

    if not runs:
        print(f"No runs found for session {run_id}")
        return

    config = json.loads(lens_row["config_json"]) if lens_row else {}
    dimensions = config.get("dimensions", [])

    by_company = {}
    for r in runs:
        by_company.setdefault(r["company_name"], []).append(r)

    print(f"\nEval session: {run_id}\n")
    for company, company_runs in by_company.items():
        stats = _build_stats(company, company_runs, dimensions)
        _print_stats(stats)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SignalVault lens scoring eval runner")
    parser.add_argument("--n", type=int, default=DEFAULT_N, help=f"Runs per company (default {DEFAULT_N})")
    parser.add_argument("--lens", default=DEFAULT_LENS, help=f"Lens slug (default: {DEFAULT_LENS})")
    parser.add_argument("--company", help="Score a single company (partial name ok, looks up DB)")
    parser.add_argument("--run-analyses", action="store_true", help="Fetch missing analyses before scoring")
    parser.add_argument("--list-runs", action="store_true", help="List past eval sessions")
    parser.add_argument("--show-run", metavar="RUN_ID", help="Show stats for a past session")
    args = parser.parse_args()

    if args.list_runs:
        list_runs()
        return

    if args.show_run:
        show_run(args.show_run)
        return

    companies = DEFAULT_COMPANIES
    if args.company:
        needle = args.company.lower()
        match = next((c for c in DEFAULT_COMPANIES if needle in c["name"].lower()), None)
        if not match:
            from db import get_connection
            conn = get_connection(DB_PATH)
            row = conn.execute(
                "SELECT DISTINCT company_name FROM dossiers WHERE LOWER(company_name) LIKE ? LIMIT 1",
                (f"%{needle}%",),
            ).fetchone()
            conn.close()
            if row:
                db_name = row["company_name"]
                match = next((c for c in DEFAULT_COMPANIES if c["name"] == db_name), {"name": db_name})
        companies = [match] if match else [{"name": args.company}]

    run_eval(companies, args.lens, args.n, run_analyses=args.run_analyses)


if __name__ == "__main__":
    main()
