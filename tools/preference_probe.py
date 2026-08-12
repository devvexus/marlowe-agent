"""single-session-preference, characterised as its own problem for the first time.

    PYTHONIOENCODING=utf-8 python tools/preference_probe.py

## Why

Every number in this project pools six question categories. `single-session-preference` reads
**0.3333 on fit** -- 5 correct of 15 -- with **4.07x failure enrichment**, is immune to rerank
depth (W2: saturates at 0.3333 by depth 5 and never moves again), and has survived all 27 measured
mechanisms untouched. It has never been analysed alone.

There is a structural reason to suspect it is a DIFFERENT TASK rather than a harder instance of the
same one. `a89d7624` asks *"I'm planning a trip to Denver soon. Any suggestions on what to do
there?"*; the gold turn is *"During my previous visit to Denver, where I had a great time meeting
Brandon Flowers after The Killers' concert..."*. The question is a REQUEST, not a question, and the
retrieval target is a turn that REVEALS A PREFERENCE, not a turn that contains an answer. A
cross-encoder trained on MS MARCO relevance plus answer-bearing LongMemEval turns has never been
trained for that.

## What this measures -- diagnosis only, no mechanism, nothing tuned

1. **Per-category R@1 for three rankings**: cue-only (no cross-encoder at all), shipped (cue key +
   cross-encoder at depth 10), and the oracle-in-slate ceiling (was gold even reachable?). The
   decisive question is whether the cross-encoder HELPS or HURTS this category -- if cue-only beats
   shipped on preference, the rerank stage is actively destroying it, which no pooled number could
   ever show.
2. **Where the loss is**, per category: pruning survival, in-slate rate (input recall), and
   conditional accuracy given in-slate. A category that fails at the slate is a different problem
   from one that fails at the head.
3. **The per-query dump** for all 15 preference queries -- question, gold answer, every gold turn's
   pre-rerank and final rank, and the top-3 text -- so the failures can be READ, which is how the
   only useful findings in this session were produced.

## The gate

The shipped key must reconstruct fit R@1 = **0.7555** exactly over the full 229, or this refuses
before printing anything. The per-category R@1 values must recombine to it at the category weights.

## Reuse, not re-implementation

Ranking key, reorder and gate constant from `sweep_reranker_frontier`; cue-only order from
`correct_case_control`; pools and texts from `reach_pools`; roles from `failure_forensics`. No
scoring rule is restated here.

**Fit split only. Held-out is not opened.**
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from correct_case_control import cue_only_order  # noqa: E402
from failure_forensics import SLATE_DEPTH, turn_roles  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

from marlowe_eval.datasets import longmemeval  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "preference-probe.json"
TARGET = "single-session-preference"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dump", default=TARGET, help="category to dump per-query")
    args = ap.parse_args()

    pools, stats = load_pools(FIT_POOLS)
    texts, roles = turn_texts(), turn_roles()
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    questions = {c.query_id: c.question for c in corpus.cases}
    answers = {c.query_id: c.gold_answer for c in corpus.cases}
    print(f"fit pools: {stats['pools']} queries, {stats['candidates']:,} candidates")

    rows = {}
    for qid, pool in pools.items():
        ship, cue = shipped_order(pool), cue_only_order(pool)
        slate = [int(v) for v in cue[:SLATE_DEPTH]]
        gold_idx = [i for i, g in enumerate(pool.gold) if g]
        rank_ship = {int(v): r + 1 for r, v in enumerate(ship)}
        rank_cue = {int(v): r + 1 for r, v in enumerate(cue)}
        rows[qid] = {
            "category": pool.category,
            "ship_hit": bool(pool.gold[int(ship[0])]),
            "cue_hit": bool(pool.gold[int(cue[0])]),
            "in_slate": any(i in slate for i in gold_idx),
            "survived": any(pool.candidates[i].survived_pruning for i in gold_idx),
            "n_gold": len(gold_idx),
            "n_cand": len(pool.candidates),
            "gold_ranks_ship": sorted(rank_ship[i] for i in gold_idx),
            "gold_ranks_cue": sorted(rank_cue[i] for i in gold_idx),
            "_ship": ship, "_cue": cue, "_slate": slate, "_gold": gold_idx,
        }

    r1 = round(sum(r["ship_hit"] for r in rows.values()) / len(rows), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING. Reconstructed fit R@1 {r1}; published {CONTROL_R1}.")
    print(f"\nGATE  shipped key fit R@1 {r1} == published {CONTROL_R1}   PASSED")

    cats = sorted({r["category"] for r in rows.values()})
    per_cat = {}
    print("\n" + "=" * 104)
    print("PER-CATEGORY -- does the cross-encoder HELP or HURT?  (fit, depth 10)")
    print("=" * 104)
    print(f"  {'category':28s} {'n':>4} {'cue-only':>9} {'shipped':>8} {'rerank d':>9} "
          f"{'in-slate':>9} {'cond.acc':>9} {'pruned-ok':>10}")
    for c in cats:
        rs = [r for r in rows.values() if r["category"] == c]
        n = len(rs)
        cue_r1 = sum(r["cue_hit"] for r in rs) / n
        ship_r1 = sum(r["ship_hit"] for r in rs) / n
        ins = sum(r["in_slate"] for r in rs) / n
        surv = sum(r["survived"] for r in rs) / n
        ins_n = sum(r["in_slate"] for r in rs)
        ca = (sum(r["ship_hit"] for r in rs if r["in_slate"]) / ins_n) if ins_n else float("nan")
        per_cat[c] = {"n": n, "cue_only_R@1": round(cue_r1, 4), "shipped_R@1": round(ship_r1, 4),
                      "rerank_delta": round(ship_r1 - cue_r1, 4), "in_slate": round(ins, 4),
                      "conditional_accuracy": round(ca, 4), "survived_pruning": round(surv, 4)}
        print(f"  {c:28s} {n:>4} {cue_r1:>9.4f} {ship_r1:>8.4f} {ship_r1 - cue_r1:>+9.4f} "
              f"{ins:>9.4f} {ca:>9.4f} {surv:>10.4f}")
    tot = sum(v["n"] for v in per_cat.values())
    recomb = round(sum(v["n"] * v["shipped_R@1"] for v in per_cat.values()) / tot, 4)
    print(f"  {'RECOMBINATION':28s} {tot:>4} "
          f"{sum(v['n'] * v['cue_only_R@1'] for v in per_cat.values()) / tot:>9.4f} "
          f"{recomb:>8.4f}   reconstructs {r1}: {abs(recomb - r1) < 5e-4}")

    # -- the per-query dump ------------------------------------------------------------------------
    sel = [(q, r) for q, r in rows.items() if r["category"] == args.dump]
    print("\n" + "=" * 104)
    print(f"{args.dump.upper()} -- all {len(sel)} fit queries")
    print("=" * 104)
    dump = []
    for qid, r in sorted(sel, key=lambda t: (not t[1]["ship_hit"], t[0])):
        pool = pools[qid]
        mark = "HIT " if r["ship_hit"] else "MISS"
        print(f"\n[{mark}] {qid}  gold turns {r['n_gold']}  cand {r['n_cand']}  "
              f"in_slate {r['in_slate']}  gold ranks: cue {r['gold_ranks_cue'][:4]} "
              f"-> shipped {r['gold_ranks_ship'][:4]}")
        print(f"   Q: {questions.get(qid, '')[:300]}")
        print(f"   A: {str(answers.get(qid, ''))[:300]}")
        top = []
        for rank, v in enumerate(r["_ship"][:3], 1):
            i = int(v)
            t = (texts.get(qid, {}).get(pool.candidates[i].turn_id) or "").replace("\n", " ")
            g = " <<GOLD" if pool.gold[i] else ""
            role = roles.get(qid, {}).get(pool.candidates[i].turn_id, "?")
            print(f"   {rank}. [{role}]{g} {t[:260]}")
            top.append({"rank": rank, "role": role, "gold": bool(pool.gold[i]), "text": t})
        dump.append({"query_id": qid, "hit": r["ship_hit"], "question": questions.get(qid),
                     "gold_answer": answers.get(qid), "n_gold": r["n_gold"],
                     "in_slate": r["in_slate"], "gold_ranks_cue": r["gold_ranks_cue"],
                     "gold_ranks_ship": r["gold_ranks_ship"], "top3": top})

    art = {"_what": "single-session-preference characterised alone: per-category rerank effect plus "
                    "the full per-query dump for the target category.",
           "_split": "fit", "_gate": {"fit_R@1": r1, "published": CONTROL_R1},
           "per_category": per_cat, "dumped_category": args.dump, "queries": dump}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(art, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
