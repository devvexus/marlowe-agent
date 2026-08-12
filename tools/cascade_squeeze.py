"""Squeeze cond@3: fuse EVERY Session-J-recipe fine-tune in the cascade's second stage.

    PYTHONIOENCODING=utf-8 python tools/cascade_squeeze.py

## Where the remaining loss is

Held-out, 229 basis, current cascade: **R@3 0.8865 = 0.9825 (pruning) x 0.9956 (slate@30) x 0.9062
(cond@3)**. Pruning loses 4 cases and removing it is measured HARMFUL (-0.0175 at depth 10, -0.0218
at depth 20). The slate loses 1. **`cond@3` loses 21 and is the entire wall.**

A 5-arm label oracle reached cond@3 **0.9686** on fit against any single arm's **0.9507** -- 3 cases
of headroom that two-way RRF captured none of. W1 trained four more graphs before it was stopped and
they were never scored: `ms-marco-MiniLM-L-{2,4,6,12}-v2-ft-w1`, all on Session J's exact recipe
(same pairs file, same MarginMSE, same delta rule, same seed, same conversation fold), all Tier A.

This scores them, and it answers the capacity question as a by-product: L-2 (15M) -> L-4 (19M) ->
L-6 (22M) -> L-12 (33M) **at fixed fine-tuning**, which is the comparison `frontier.json` never
made -- every model there above 23M is a stock pretrained checkpoint.

## THE RULE, FIXED BEFORE ANY NUMBER EXISTS

**PRIMARY = RRF over ALL SIX Session-J-recipe fine-tunes**, k = 60. Not a subset. Choosing which
graphs to fuse by looking at fit is exactly the selection this project has four collapses from, so
the rule is "everything trained the same way" and there is nothing to tune.

The `ft-m-*` family (Session M Phase 2) is DELIBERATELY EXCLUDED and the reason is stated up front:
those were trained on `deployed_top_k` negatives, a different mining procedure, and arm B is on the
record as fit 0.8253 -> held-out 0.6812. Mixing a known fit-overfitter into a fusion measured on fit
would flatter the fit number and not the held-out one.

Stage 1 is unchanged and unchosen: the SHIPPED graph narrows 30 -> 10, exactly as pre-registered in
`PREREGISTRATION-CASCADE-HELDOUT.json`.

## REGISTERED PREDICTION

  * The 6-way fusion beats the 2-way's fit cond@3 of 0.9467 by **+0.005 to +0.020**, i.e. R@3 0.9301
    -> 0.9310-0.9480. It cannot exceed the union oracle, so ~0.9550 is a hard cap.
  * **L-12-ft is NOT the best single picker.** Session J's two-point fine-tuned curve is
    flat-to-inverted (L-2-ft 0.7555 vs L-6-ft 0.7467 at depth 10) and 5,612 training pairs is thin
    for 33M parameters. If L-12-ft wins, capacity was genuinely confounded and that is a result.
  * Fusing 6 near-identical rankers may add **nothing** -- they share a base, a recipe and a training
    set, so their errors are correlated. A null here says the 3-case oracle headroom is unreachable
    by fusion and only a differently-trained model can take it.

## Gates

1. Shipped graph, depth 10, must reproduce fit R@1 **0.7555** exactly.
2. Depth-10 cue slate == the candidate set the binary actually reranked, read from the dump.
3. Every graph digest-checked against `capacity-manifest.json` / `session_i_rerankers.FINETUNES`,
   and every graph passes its discrimination smoke test.
4. The control arm (shipped graph picking from the narrowed 10) must reproduce the depth-30 R@3 of
   **0.9258** already measured by `tools/rk_by_depth.py`.

Registration is done at RUNTIME into `session_i_rerankers.FINETUNES`; that file is a record of other
sessions' work and is not written to.

**Fit split only. Held-out is not opened.**
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import session_i_rerankers as R  # noqa: E402
from correct_case_control import cue_only_order  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "cascade-squeeze.json"
MANIFEST = REPO / "runs" / "session-m0c-m" / "capacity-manifest.json"
SHIPPED = "ms-marco-MiniLM-L-2-v2-ft-session-j"
L6J = "ms-marco-MiniLM-L-6-v2-ft-session-j"
W1 = ["ms-marco-MiniLM-L-2-v2-ft-w1", "ms-marco-MiniLM-L-4-v2-ft-w1",
      "ms-marco-MiniLM-L-6-v2-ft-w1", "ms-marco-MiniLM-L-12-v2-ft-w1"]
MAX_SEQ, RRF_K, SLATE, NARROW = 256, 60, 30, 10
D30_R3 = 0.9258


def register_w1():
    """Add W1's graphs to the loader's pinned table at runtime. Digests come from its manifest."""
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    added = {}
    for m in man["models"]:
        if m["name"] in W1:
            R.FINETUNES[m["name"]] = {
                "digest": m["digests"]["model.onnx"],
                "params_m": m["params_m"], "arch": "BERT", "max_seq": m["max_seq"],
            }
            added[m["name"]] = m["digests"]["model.onnx"][:16]
    return added


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--provider", default="CPUExecutionProvider")
    args = ap.parse_args()

    pools, stats = load_pools(FIT_POOLS)
    texts = turn_texts()
    n = len(pools)
    print(f"fit pools: {n} queries  slate {SLATE} -> narrow {NARROW} -> top 3")

    ship = {q: shipped_order(p) for q, p in pools.items()}
    r1 = round(sum(int(p.gold[int(ship[q][0])]) for q, p in pools.items()) / n, 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING (GATE 1). fit R@1 {r1}; published {CONTROL_R1}.")
    cue = {q: [int(v) for v in cue_only_order(p)] for q, p in pools.items()}
    exact = sum(set(cue[q][:10]) == {i for i, c in enumerate(p.candidates)
                                     if c.rerank_score is not None} for q, p in pools.items())
    if exact != n:
        raise SystemExit(f"REFUSING (GATE 2). slate mismatch on {n - exact}.")
    print(f"GATE 1  fit R@1 {r1} == {CONTROL_R1}    GATE 2  slate {exact}/{n} exact")
    print(f"GATE 3  registered at runtime: {register_w1()}")

    slate = {q: cue[q][:SLATE] for q in pools}
    ir = sum(any(pools[q].gold[i] for i in slate[q]) for q in pools) / n
    in_slate = [q for q in pools if any(pools[q].gold[i] for i in slate[q])]

    ce = R.load(SHIPPED, provider=args.provider)
    if not R.smoke_test(ce).get("pass"):
        raise SystemExit("REFUSING. shipped graph smoke test failed.")
    narrow = {}
    for q, p in pools.items():
        docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in slate[q]]
        sc = ce.score_batch(p.question, docs, MAX_SEQ)
        narrow[q] = [i for _, i in sorted(zip(sc, slate[q]), key=lambda t: (-t[0], t[1]))][:NARROW]
    nret = sum(any(pools[q].gold[i] for i in narrow[q]) for q in pools) / n
    print(f"\n  ir@{SLATE} {ir:.4f} -> after narrowing {nret:.4f} "
          f"(retention {nret / ir:.4f}), {len(in_slate)} queries with gold in slate")

    models = [SHIPPED, L6J] + W1
    orders = {}
    for name in models:
        c = R.load(name, provider=args.provider)
        sm = R.smoke_test(c)
        if not sm.get("pass"):
            raise SystemExit(f"REFUSING (GATE 3). {name} failed its smoke test.")
        o = {}
        for q, p in pools.items():
            docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in narrow[q]]
            s = c.score_batch(p.question, docs, MAX_SEQ)
            o[q] = [i for _, i in sorted(zip(s, narrow[q]), key=lambda t: (-t[0], t[1]))]
        orders[name] = o
        print(f"  scored {name:38s} {c.params_m:>3}M  smoke margin {sm['margin']:.3f}")

    def cond3(o):
        return sum(1 for q in in_slate
                   if any(pools[q].gold[int(v)] for v in o[q][:3])) / len(in_slate)

    def r3(o):
        return sum(1 for q in pools if any(pools[q].gold[int(v)] for v in o[q][:3])) / n

    def r1_(o):
        return sum(1 for q in pools if pools[q].gold[int(o[q][0])]) / n

    def rrf(names):
        out = {}
        for q in pools:
            rk = [{i: r for r, i in enumerate(orders[nm][q])} for nm in names]
            sc = {i: sum(1.0 / (RRF_K + m[i]) for m in rk) for i in narrow[q]}
            out[q] = sorted(narrow[q], key=lambda i: (-sc[i], i))
        return out

    print("\n" + "=" * 100)
    print("EACH GRAPH ALONE as the final picker over the narrowed 10 (capacity at fixed fine-tuning)")
    print("=" * 100)
    print(f"  {'graph':40s} {'params':>7} {'R@1':>8} {'R@3':>8} {'cond@3':>8}")
    cells = {}
    for name in models:
        o = orders[name]
        cells[name] = {"R@1": round(r1_(o), 4), "R@3": round(r3(o), 4),
                       "conditional_top3": round(cond3(o), 4)}
        pm = R.FINETUNES.get(name, {}).get("params_m", "?")
        print(f"  {name:40s} {pm:>7} {cells[name]['R@1']:>8.4f} {cells[name]['R@3']:>8.4f} "
              f"{cells[name]['conditional_top3']:>8.4f}")

    ctl = cells[SHIPPED]["R@3"]
    if abs(ctl - D30_R3) > 1e-4:
        raise SystemExit(f"REFUSING (GATE 4). control R@3 {ctl} != rk-by-depth's {D30_R3}.")
    print(f"\n  GATE 4  control reproduces depth-30 R@3 {D30_R3}: True")

    print("\n" + "=" * 100)
    print("FUSIONS -- PRIMARY is all six (pre-registered). Others shown for shape, NOT for picking.")
    print("=" * 100)
    fusions = {"PRIMARY all 6": models, "session-j pair (shipped cascade)": [SHIPPED, L6J]}
    for k in (3, 4, 5):
        fusions[f"first {k} of the declared order"] = models[:k]
    print(f"  {'fusion':40s} {'R@1':>8} {'R@3':>8} {'cond@3':>8}")
    for label, names in fusions.items():
        o = rrf(names)
        cells[label] = {"R@1": round(r1_(o), 4), "R@3": round(r3(o), 4),
                        "conditional_top3": round(cond3(o), 4), "members": names}
        print(f"  {label:40s} {cells[label]['R@1']:>8.4f} {cells[label]['R@3']:>8.4f} "
              f"{cells[label]['conditional_top3']:>8.4f}")

    # The union ceiling over every graph -- uses labels, a CEILING and not a system.
    union = {q for q in in_slate
             for nm in models if any(pools[q].gold[int(v)] for v in orders[nm][q][:3])}
    print(f"\n  union oracle over all {len(models)} graphs: cond@3 "
          f"{len(union) / len(in_slate):.4f}  (CEILING, uses labels)")
    missed = sorted(set(in_slate) - union)
    from collections import Counter
    print(f"  missed by every graph: {len(missed)}  {dict(Counter(pools[q].category for q in missed))}")

    prim = cells["PRIMARY all 6"]
    base = cells["session-j pair (shipped cascade)"]
    print(f"\n  PRIMARY vs the shipped cascade: dR@3 {prim['R@3'] - base['R@3']:+.4f}  "
          f"dcond@3 {prim['conditional_top3'] - base['conditional_top3']:+.4f}  "
          f"dR@1 {prim['R@1'] - base['R@1']:+.4f}")

    art = {"_what": "cond@3 squeeze: fuse every Session-J-recipe fine-tune in the cascade's stage 2",
           "_split": "fit", "_rule_fixed_before_measurement":
               "PRIMARY = RRF over all six Session-J-recipe fine-tunes, k=60. ft-m-* excluded "
               "(different negatives; arm B is a known fit-overfitter).",
           "_rrf_k": RRF_K, "_slate": SLATE, "_narrow": NARROW,
           "input_recall": round(ir, 4), "after_narrowing": round(nret, 4),
           "union_oracle_cond3": round(len(union) / len(in_slate), 4),
           "missed_by_every_graph": missed, "cells": cells}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(art, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
