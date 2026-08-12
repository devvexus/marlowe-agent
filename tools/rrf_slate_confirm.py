"""Rerank the RRF slate and measure R@3 for real. The projection is a hypothesis; this is the test.

    PYTHONIOENCODING=utf-8 python tools/rrf_slate_confirm.py

## What is being confirmed

`tools/slate_draw_rules.py` measured input recall at fixed depth 10 on fit:

    shipped fused cue key   ir@10 0.9214
    rrf k=60                ir@10 0.9476     (+0.0262, and 99.5% of the either-cue oracle 0.9520)

and PROJECTED R@3 = 0.9476 x 0.9763 = 0.9251 by carrying `cond@3` over from the shipped slate.

**That projection is not a result and must not be quoted as one.** `cond@3 = 0.9763` was measured
on the SHIPPED slate. The RRF slate is a DIFFERENT candidate set -- it swaps roughly one candidate
in six -- so the cross-encoder's top-3 precision over it is an unmeasured quantity. Carrying a
number across that boundary is the exact failure family this project keeps a ledger of: *a
measurement is scoped to the system it was taken on.*

So the slate is drawn by RRF and actually reranked, and `cond@3` is RE-MEASURED on it.

## Cells

    shipped @10   (CONTROL -- must reproduce fit R@1 0.7555 exactly)
    rrf     @10
    rrf     @20

`rrf @20` is included because RRF's ir@20 is 0.9694 -- LOWER than the shipped key's 0.9738 -- so if
RRF wins at depth 10 and loses at depth 20, that is evidence the gain is real and depth-specific
rather than a uniform shift.

## What would falsify the finding

`cond@3` on the RRF slate falling far enough to cancel the recall gain -- i.e. RRF R@3 <= 0.8996.
That is a live possibility: RRF admits candidates the isotonic fusion rejected, and those may be
harder distractors precisely because two different cues both liked them.

## The gates

1. The shipped key must reconstruct fit R@1 = **0.7555** exactly.
2. The shipped depth-10 slate must equal the set the binary actually reranked, read from the dump.
3. Input recall re-derived here must match `slate-draw-rules.json` for both rules.
4. R@k must be monotone non-decreasing in k.

## Reuse, not re-implementation

`cue_only_order` from `correct_case_control`; `reordered`, `shipped_order` and the gate constant
from `sweep_reranker_frontier`; pools and texts from `reach_pools`; the ONE cross-encoder loader
from `session_i_rerankers`. RRF is built from the ranks of cue scores READ FROM THE DUMP.

**Fit split only. Held-out is not opened.**
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

OUT = REPO / "runs" / "session-m0c-m" / "rrf-slate-confirm.json"
DRAW_RULES = REPO / "runs" / "session-m0c-m" / "slate-draw-rules.json"
MODEL = "ms-marco-MiniLM-L-2-v2-ft-session-j"
MAX_SEQ = 256
RRF_K = 60
KS = (1, 2, 3, 5, 10, 20)


def rank_list(pool, key, prune_first=True):
    idx = list(range(len(pool.candidates)))
    idx.sort(key=lambda i: (
        (not pool.candidates[i].survived_pruning) if prune_first else 0,
        -(key(pool.candidates[i]) if key(pool.candidates[i]) is not None else -1e9),
        i,
    ))
    return idx


def rrf_order(pool):
    b = rank_list(pool, lambda c: c.lexical_bm25)
    d = rank_list(pool, lambda c: c.dense_cosine)
    rb = {i: r for r, i in enumerate(b)}
    rd = {i: r for r, i in enumerate(d)}
    sc = {i: 1.0 / (RRF_K + rb[i]) + 1.0 / (RRF_K + rd[i]) for i in range(len(pool.candidates))}
    return sorted(range(len(pool.candidates)),
                  key=lambda i: (not pool.candidates[i].survived_pruning, -sc[i], i))


def best_gold_rank(pool, order):
    for r, v in enumerate(order, 1):
        if pool.gold[int(v)]:
            return r
    return 10 ** 6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--provider", default="CPUExecutionProvider")
    args = ap.parse_args()

    pools, stats = load_pools(FIT_POOLS)
    texts = turn_texts()
    n = len(pools)
    print(f"fit pools: {stats['pools']} queries, {stats['candidates']:,} candidates")

    ship = {q: shipped_order(p) for q, p in pools.items()}
    r1 = round(sum(int(p.gold[int(ship[q][0])]) for q, p in pools.items()) / n, 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING (GATE 1). fit R@1 {r1}; published {CONTROL_R1}.")
    print(f"GATE 1  shipped key fit R@1 {r1} == published {CONTROL_R1}   PASSED")

    cue = {q: [int(v) for v in cue_only_order(p)] for q, p in pools.items()}
    exact = sum(set(cue[q][:10]) == {i for i, c in enumerate(p.candidates)
                                     if c.rerank_score is not None} for q, p in pools.items())
    if exact != n:
        raise SystemExit(f"REFUSING (GATE 2). cue slate != reranked set on {n - exact} queries.")
    print(f"GATE 2  shipped depth-10 slate == the set the binary reranked: {exact}/{n} exact")

    rrf = {q: rrf_order(p) for q, p in pools.items()}

    ir = {}
    for name, o in (("shipped", cue), ("rrf", rrf)):
        for d in (10, 20):
            ir[f"{name}@{d}"] = round(
                sum(any(p.gold[i] for i in o[q][:d]) for q, p in pools.items()) / n, 4)
    if DRAW_RULES.exists():
        prev = json.loads(DRAW_RULES.read_text(encoding="utf-8"))["results"]
        want = {"shipped@10": prev["shipped (CONTROL)"]["ir@10"],
                "shipped@20": prev["shipped (CONTROL)"]["ir@20"],
                "rrf@10": prev["rrf k=60"]["ir@10"], "rrf@20": prev["rrf k=60"]["ir@20"]}
        bad = [k for k, v in want.items() if abs(ir[k] - v) > 1e-9]
        if bad:
            raise SystemExit(f"REFUSING (GATE 3). input recall disagrees with "
                             f"slate-draw-rules.json on {bad}.")
        print(f"GATE 3  input recall reproduces slate-draw-rules.json on all four cells: True")

    ce = R.load(MODEL, provider=args.provider)
    if not R.smoke_test(ce).get("pass"):
        raise SystemExit("REFUSING. smoke test failed.")
    print(f"loaded {MODEL} ({ce.params_m}M, {ce.arch}, {args.provider})  smoke PASS\n")

    print("=" * 108)
    print("RERANKED -- cond@3 RE-MEASURED on each slate, never carried across")
    print("=" * 108)
    hdr = " ".join(f"{'R@' + str(k):>7}" for k in KS)
    print(f"  {'cell':16s} {'in.rec':>7} {hdr}   {'cond@1':>7} {'cond@3':>7}")
    cells = {}
    for name, o, d in (("shipped @10", cue, 10), ("rrf @10", rrf, 10), ("rrf @20", rrf, 20)):
        order = {}
        for q, p in pools.items():
            slate = [int(i) for i in o[q][:d]]
            docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in slate]
            order[q] = reordered(p, slate, ce.score_batch(p.question, docs, MAX_SEQ))
        ranks = {q: best_gold_rank(p, order[q]) for q, p in pools.items()}
        vals = {k: sum(1 for r in ranks.values() if r <= k) / n for k in KS}
        prev_v = 0.0
        for k in KS:
            if vals[k] + 1e-12 < prev_v:
                raise SystemExit(f"REFUSING (GATE 4). R@k not monotone at k={k} in {name}.")
            prev_v = vals[k]
        rec = ir[f"{'shipped' if name.startswith('shipped') else 'rrf'}@{d}"]
        c1, c3 = vals[1] / rec, vals[3] / rec
        cells[name] = {"depth": d, "input_recall": rec,
                       **{f"R@{k}": round(v, 4) for k, v in vals.items()},
                       "conditional_top1": round(c1, 4), "conditional_top3": round(c3, 4)}
        print(f"  {name:16s} {rec:>7.4f} " + " ".join(f"{vals[k]:>7.4f}" for k in KS) +
              f"   {c1:>7.4f} {c3:>7.4f}")

    if abs(cells["shipped @10"]["R@1"] - CONTROL_R1) > 1e-9:
        raise SystemExit("REFUSING. The control cell does not reproduce the published fit R@1.")
    print(f"\n  control cell reproduces published fit R@1 {CONTROL_R1}: True")

    base = cells["shipped @10"]
    print("\n" + "=" * 108)
    print("VERDICT")
    print("=" * 108)
    for name in ("rrf @10", "rrf @20"):
        c = cells[name]
        dr3 = c["R@3"] - base["R@3"]
        dc3 = c["conditional_top3"] - base["conditional_top3"]
        dir_ = c["input_recall"] - base["input_recall"]
        print(f"  {name:10s}  dR@3 {dr3:+.4f}   (input recall {dir_:+.4f}, cond@3 {dc3:+.4f})   "
              f"dR@1 {c['R@1'] - base['R@1']:+.4f}")
    print(f"\n  projection made before this run: rrf @10 R@3 = 0.9251 (0.9476 x 0.9763)")
    print(f"  actually measured:                rrf @10 R@3 = {cells['rrf @10']['R@3']:.4f}")

    art = {"_what": "RRF slate at fixed depth, actually reranked. cond@3 re-measured per slate.",
           "_split": "fit", "_rrf_k": RRF_K, "_projection_being_tested": 0.9251,
           "_gates": {"fit_R@1": r1, "published": CONTROL_R1, "slate_exact": exact},
           "input_recall": ir, "cells": cells}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(art, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
