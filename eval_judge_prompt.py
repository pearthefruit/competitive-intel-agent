"""A/B the evidence-judge prompt: current (prompts/predictions.py) vs the previous
version, on real signal->prediction candidate pairs from intel.db.

Written 2026-07-19 because the judge prompt was rewritten to stop 'partial' being
used as a hedge, but all LLM providers were down and the change went untested.
Run this when providers recover to find out whether it actually worked.

    cd competitive-intel-agent
    python eval_judge_prompt.py              # 12 pairs (24 LLM calls)
    python eval_judge_prompt.py --pairs 20   # more pairs, more calls

Costs 2 FAST_CHAIN calls per pair. Writes nothing to the DB — read-only.

What to look for: NEW should convert clear one-directional cases from 'partial'
into 'supports'/'refutes'. The 'actionable' line at the bottom is the headline
number — auto-resolution needs >=3 supports or >=2 refutes per prediction, so
partial-heavy output means the lifecycle engine stays stalled.
"""
import argparse
import sqlite3
import sys
from collections import Counter

# Must precede any agents.* import: agents/llm.py reads keys from the environment
# and does NOT load .env itself — only web/app.py and main.py do. Without this,
# every provider "fails" instantly with no network call and no llm_usage row.
from dotenv import load_dotenv
load_dotenv()

from agents.predictions import semantic_candidates
from agents.llm import generate_json, FAST_CHAIN
from prompts.predictions import build_evidence_judge_prompt

# The pre-2026-07-19 prompt, kept verbatim as the A/B baseline.
OLD_PROMPT = """You are evaluating whether a new signal supports, refutes, or is unrelated to a prediction.

PREDICTION: {claim}
MECHANISM: {mech}

NEW SIGNAL:
Title: {title}
Content: {body}

Evaluate the relationship. Rules:
- Only score >= 0.3 if there is a DIRECT, specific connection - not just thematic overlap
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


def judge(prompt):
    try:
        return generate_json(prompt, chain=FAST_CHAIN, expect="object",
                             required_keys=["stance", "weight"]) or {}
    except Exception as e:
        print(f"    [llm error] {e}")
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="intel.db")
    ap.add_argument("--pairs", type=int, default=12, help="candidate pairs to judge")
    ap.add_argument("--signals", type=int, default=120, help="recent signals to draw from")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    sigs = conn.execute(
        "SELECT id, title, body FROM signals ORDER BY collected_at DESC LIMIT ?",
        (args.signals,),
    ).fetchall()

    pairs = []
    for s in sigs:
        for cand in semantic_candidates(s["title"], s["body"], conn):
            pairs.append((s, cand))
        if len(pairs) >= args.pairs:
            break
    pairs = pairs[: args.pairs]

    if not pairs:
        print("No candidate pairs above the similarity threshold. "
              "Has backfill_prediction_embeddings.py been run?")
        conn.close()
        sys.exit(1)

    print(f"A/B on {len(pairs)} candidate pairs ({len(pairs) * 2} LLM calls)\n")
    old_st, new_st, changed = Counter(), Counter(), 0

    for i, (s, cand) in enumerate(pairs, 1):
        body = (s["body"] or "")[:1500]
        mech = cand.get("mechanism") or ""
        o = judge(OLD_PROMPT.format(claim=cand["claim"], mech=mech,
                                    title=s["title"], body=body))
        n = judge(build_evidence_judge_prompt(s["title"], body, cand["claim"], mech))

        os_, ns_ = o.get("stance", "err"), n.get("stance", "err")
        old_st[os_] += 1
        new_st[ns_] += 1
        if os_ != ns_ and "err" not in (os_, ns_):
            changed += 1
        flag = "  <-- changed" if os_ != ns_ else ""
        print(f"{i:2}. cos={cand['similarity']:.2f}  "
              f"OLD={os_:9}(w={o.get('weight', 0)})  "
              f"NEW={ns_:9}(w={n.get('weight', 0)}){flag}")
        print(f"     SIG:  {s['title'][:70]}")
        print(f"     PRED: {cand['claim'][:70]}")

    if old_st.get("err") or new_st.get("err"):
        print("\n!! Some calls failed ('err'). If all of them did, providers are down "
              "— rerun later; these results mean nothing.")

    print(f"\nOLD stances: {dict(old_st)}")
    print(f"NEW stances: {dict(new_st)}")
    act = lambda d: d.get("supports", 0) + d.get("refutes", 0)
    print(f"actionable (supports+refutes):  OLD {act(old_st)}/{len(pairs)}  "
          f"NEW {act(new_st)}/{len(pairs)}")
    print(f"stance changed on {changed}/{len(pairs)} pairs")
    conn.close()


if __name__ == "__main__":
    main()
