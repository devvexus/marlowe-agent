"""R@k as a function of rerank depth -- the arithmetic behind a 94% R@3 bar.

    PYTHONIOENCODING=utf-8 python tools/rk_by_depth.py

## Why

The session's target moved from R@1 to **R@3 >= 0.94**. Two published numbers already constrain
that hard, and they need to be laid beside each other:

    held-out R@3  0.8515        held-out R@10 0.9039

At depth 10, R@10 IS the input recall -- gold is not in the slate at all for 22 of 229 held-out
queries. So **0.94 R@3 is unreachable at depth 10 by any admission or reordering change**; the
ceiling is 0.9039. It becomes arithmetically possible only if the slate deepens, and the spent
depth-30 held-out read recorded input recall **0.9782**.

This measures, on FIT, what R@1/2/3/5/10 actually are at depths 10, 20 and 30, so the required
conditional accuracy is a measured quantity rather than an inference from two aggregates.

**The slate is drawn on the PRE-RERANK CUE KEY, not on `shipped_order`.** `sweep_reranker_frontier`
slices `shipped_order(pool)[:depth]`, whose second sort level is the cross-encoder's own score.
That is harmless at depth >= 10 (the top-10 SET is the same either way) but it is circular below
it, and `tools/sweep_rerank_depth_down.py` had to correct exactly this. The same correction is used
here so every depth is drawn the way `retrieve.rs` draws it.

## The gates

1. The shipped key must reconstruct fit R@1 = **0.7555** exactly, or this refuses.
2. The depth-10 cue slate must equal the candidate set the binary actually reranked -- read from
   the dump (`rerank_score is not None`), not reconstructed -- on all 229 queries.
3. R@k must be monotone non-decreasing in k, and input recall at depth d must equal R@d.

## Reuse, not re-implementation

Ranking key, reorder, gate constant from `sweep_reranker_frontier`; cue-only order from
`correct_case_control`; pools and texts from `reach_pools`; the ONE cross-encoder loader from
`session_i_rerankers`.

**Fit split only. Held-out is not opened; its figures are quoted from the record.**
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import session_i_rerankers as R  # noqa: E402
from correct_case_control import cue_only_order  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, reordered, shipped_order  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "rk-by-depth.json"
MODEL = "ms-marco-MiniLM-L-2-v2-ft-session-j"
MAX_SEQ = 256
KS = (1, 2, 3, 5, 10, 20, 30, 40, 50)
HELDOUT_QUOTED = {"R@1": 0.6725, "R@3": 0.8515, "R@5": 0.8865, "R@10": 0.9039,
                  "_source": "STATE.md / runs/session-m0c-m/heldout-read*.json -- QUOTED, not read"}


def best_gold_rank(pool, order):
    for r, v in enumerate(order, 1):
        if pool.gold[int(v)]:
            return r
    return 10 ** 6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--depths", type=int, nargs="+", default=[10, 20, 30])
    ap.add_argument("--provider", default="CPUExecutionProvider")
    args = ap.parse_args()

    pools, stats = load_pools(FIT_POOLS)
    texts = turn_texts()
    print(f"fit pools: {stats['pools']} queries, {stats['candidates']:,} candidates")

    ship = {q: shipped_order(p) for q, p in pools.items()}
    r1 = round(sum(int(p.gold[int(ship[q][0])]) for q, p in pools.items()) / len(pools), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING (GATE 1). fit R@1 {r1}; published {CONTROL_R1}.")
    print(f"GATE 1  shipped key fit R@1 {r1} == published {CONTROL_R1}   PASSED")

    cue = {q: cue_only_order(p) for q, p in pools.items()}
    exact = 0
    for q, p in pools.items():
        drew = {i for i, c in enumerate(p.candidates) if c.rerank_score is not None}
        exact += {int(v) for v in cue[q][:10]} == drew
    print(f"GATE 2  cue slate at depth 10 == the set the binary reranked: {exact}/{len(pools)} exact")
    if exact != len(pools):
        raise SystemExit("REFUSING (GATE 2). The cue slate is not the product's slate.")

    ce = R.load(MODEL, provider=args.provider)
    smoke = R.smoke_test(ce)
    if not smoke.get("pass"):
        raise SystemExit("REFUSING. smoke test failed.")
    print(f"loaded {MODEL} ({ce.params_m}M, {ce.arch}, {args.provider})  smoke PASS\n")

    # -- how deep can the slate actually go? -------------------------------------------------------
    # Session pruning keeps ~10% of the pool. Past that depth the slate stops being "the top d
    # survivors" and starts including turns pruning REMOVED, which is a different experiment wearing
    # the same label. Measured here rather than assumed, and reported per depth.
    surv = {q: sum(1 for c in p.candidates if c.survived_pruning) for q, p in pools.items()}
    ns = sorted(surv.values())
    print(f"survivors per pool: min {ns[0]}  median {ns[len(ns) // 2]}  max {ns[-1]}  "
          f"mean {sum(ns) / len(ns):.1f}")

    cells = {}
    print("=" * 118)
    print("R@k BY RERANK DEPTH -- shipped graph, fit split, slate drawn on the pre-rerank cue key")
    print("=" * 118)
    hdr = " ".join(f"{'R@' + str(k):>7}" for k in KS)
    print(f"  {'depth':>5} {'in.rec':>7} {hdr}   {'cond@3':>7}  {'need@3':>7}  {'q<depth':>8}")
    for d in args.depths:
        order = {}
        for q, p in pools.items():
            slate = [int(i) for i in cue[q][:d]]
            docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in slate]
            order[q] = reordered(p, slate, ce.score_batch(p.question, docs, MAX_SEQ))
        ranks = {q: best_gold_rank(p, order[q]) for q, p in pools.items()}
        n = len(pools)
        vals = {k: sum(1 for r in ranks.values() if r <= k) / n for k in KS}
        ir = sum(1 for q, p in pools.items()
                 if any(p.gold[i] for i in [int(v) for v in cue[q][:d]])) / n
        if abs(ir - vals[max(k for k in KS if k <= d)]) > 1e-9 and d in KS:
            raise SystemExit(f"REFUSING (GATE 3). input recall {ir} != R@{d} {vals.get(d)}.")
        cond3 = vals[3] / ir if ir else float("nan")
        need = 0.94 / ir if ir else float("nan")
        exhausted = sum(1 for q in pools if surv[q] < d)
        cells[d] = {"input_recall": round(ir, 4), **{f"R@{k}": round(v, 4) for k, v in vals.items()},
                    "conditional_top3": round(cond3, 4),
                    "required_conditional_top3_for_0.94": round(need, 4),
                    "reachable": bool(ir >= 0.94),
                    "queries_with_fewer_survivors_than_depth": exhausted}
        flag = "   <- CEILING BELOW 0.94" if ir < 0.94 else ""
        print(f"  {d:>5} {ir:>7.4f} " + " ".join(f"{vals[k]:>7.4f}" for k in KS) +
              f"   {cond3:>7.4f}  {need:>7.4f}  {exhausted:>8d}{flag}")

    if abs(cells[10]["R@1"] - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING. depth-10 R@1 {cells[10]['R@1']} != {CONTROL_R1}.")
    print(f"\n  depth-10 cell reproduces the published fit R@1 {CONTROL_R1}: True")

    print("\n" + "=" * 104)
    print("THE 0.94 R@3 BAR")
    print("=" * 104)
    print(f"  held-out today (QUOTED, not read): R@3 {HELDOUT_QUOTED['R@3']}  "
          f"R@10 {HELDOUT_QUOTED['R@10']}  -- R@10 at depth 10 IS the input recall")
    for d in args.depths:
        c = cells[d]
        verdict = ("REACHABLE in principle" if c["reachable"]
                   else "UNREACHABLE -- the slate ceiling is below the bar")
        print(f"  depth {d:>2}: fit input recall {c['input_recall']:.4f}, fit R@3 {c['R@3']:.4f}, "
              f"conditional top-3 {c['conditional_top3']:.4f} -> would need "
              f"{c['required_conditional_top3_for_0.94']:.4f}   {verdict}")

    art = {"_what": "R@k by rerank depth on fit, and what a 0.94 R@3 bar requires.",
           "_split": "fit", "_heldout_quoted_not_read": HELDOUT_QUOTED,
           "model": MODEL, "gates": {"fit_R@1": r1, "published": CONTROL_R1,
                                     "cue_slate_exact": exact},
           "cells": cells}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(art, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
