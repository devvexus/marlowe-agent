"""Raise cond@3 at depth 20 -- the one deficient stage left under the rank-3 model.

    PYTHONIOENCODING=utf-8 python tools/cond3_attack.py

## The target, from the stage model

Held-out, 234 answerable, with the last stage read at rank 3 instead of rank 1:

    ingest + exclusions + scope   0.9786  OK
    session pruning               0.9825  OK
    slate draw (top-10)           0.9200  deficient
    cross-encoder gold in top-3   0.9420  deficient
    -> 0.8332 = 195/234

`tools/rk_by_depth.py` showed **depth 20 already fixes the slate stage**: fit input recall 0.9738
against a pruning ceiling of 0.9825 is a slate-draw retention of **0.9911**. That leaves exactly one
deficient stage -- `cond@3` at depth 20, measured at **0.9507**, target **0.975**.

Mathematical limit at depth 20: R@3 = input_recall x cond@3 <= 0.9738 x 1.0 = **0.9738**, and the
pipeline ceiling with perfect ordering at any depth is the pruning survival rate, **0.9825**.

## The arms, all measured at depth 20, all non-LLM

  * `L-2-ft @20`            the shipped graph -- CONTROL
  * `L-6-ft @20`            Session J's other fine-tune, 23M. Its cond@3 has never been measured.
  * `RRF(L-2, cue)`         rank fusion of the cross-encoder's order with the cue key's order
  * `RRF(L-2, L-6)`         rank fusion of the two fine-tuned graphs
  * `RRF(L-2, L-6, cue)`    all three

**Why rank fusion is not the dead arm.** "dense-cosine fusion at rank 2" was SCORE fusion evaluated
on R@1 and read 0 flips at every weight; the 5-model ensemble was a vote evaluated on R@1 above the
0.084 band. This is RANK fusion evaluated on **top-3 membership**, which is a different quantity with
a different failure mode: a candidate needs only to avoid being pushed below rank 3 by BOTH rankers,
so complementary errors cancel instead of competing. That reasoning is stated before the run and is
falsifiable by the table below.

**k = 60 is Cormack et al.'s published default and is FIXED before any number exists.** No other
value is tried. A k chosen after seeing the result is the knob this project has four collapses from.

## The gates

1. `L-2-ft` at depth 10 must reproduce fit R@1 = **0.7555** exactly.
2. The depth-10 cue slate must equal the set the binary actually reranked, read from the dump.
3. Every graph passes its discrimination smoke test and its digest is pinned by `session_i_rerankers`.
4. R@k monotone non-decreasing in k, and R@d == input recall at depth d.

## Reuse, not re-implementation

`cue_only_order` from `correct_case_control`; `reordered`, `shipped_order`, the gate constant from
`sweep_reranker_frontier`; pools and texts from `reach_pools`; the ONE loader from
`session_i_rerankers`.

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
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "cond3-attack.json"
L2 = "ms-marco-MiniLM-L-2-v2-ft-session-j"
L6 = "ms-marco-MiniLM-L-6-v2-ft-session-j"
MAX_SEQ = 256
RRF_K = 60
KS = (1, 2, 3, 5, 10, 20)
TARGET_COND3 = 0.975


def best_rank(pool, order):
    for r, v in enumerate(order, 1):
        if pool.gold[int(v)]:
            return r
    return 10 ** 6


def rrf(*rank_lists):
    """Fuse orders (lists of candidate indices, best first) by reciprocal rank. Lower score = better."""
    ranks = [{i: r for r, i in enumerate(o)} for o in rank_lists]
    items = list(rank_lists[0])
    sc = {i: sum(1.0 / (RRF_K + rk.get(i, len(items))) for rk in ranks) for i in items}
    return sorted(items, key=lambda i: (-sc[i], i))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--depth", type=int, default=20)
    ap.add_argument("--provider", default="CPUExecutionProvider")
    args = ap.parse_args()
    D = args.depth
    # The depth itself must be a reported rank: gate 4 asserts R@D == input recall, which is the
    # check that the arm really is ranking the slate it was handed and nothing else.
    global KS
    KS = tuple(sorted(set(KS) | {D}))

    pools, stats = load_pools(FIT_POOLS)
    texts = turn_texts()
    n = len(pools)
    print(f"fit pools: {stats['pools']} queries, {stats['candidates']:,} candidates  depth {D}")

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
    print(f"GATE 2  depth-10 cue slate == the set the binary reranked: {exact}/{n} exact")

    slate = {q: cue[q][:D] for q in pools}
    ir = round(sum(any(p.gold[i] for i in slate[q]) for q, p in pools.items()) / n, 4)
    print(f"        input recall at depth {D}: {ir}   (mathematical limit of R@{3} here)")

    ce_orders = {}
    for name, mdl in (("L-2", L2), ("L-6", L6)):
        ce = R.load(mdl, provider=args.provider)
        sm = R.smoke_test(ce)
        if not sm.get("pass"):
            raise SystemExit(f"REFUSING (GATE 3). {mdl} failed its smoke test.")
        print(f"GATE 3  {mdl} ({ce.params_m}M, {ce.arch}) smoke PASS "
              f"(rel {sm['relevant']:.3f} vs irr {sm['irrelevant']:.3f})")
        o = {}
        for q, p in pools.items():
            docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in slate[q]]
            sc = ce.score_batch(p.question, docs, MAX_SEQ)
            o[q] = [i for _, i in sorted(zip(sc, slate[q]), key=lambda t: (-t[0], t[1]))]
        ce_orders[name] = o

    arms = {
        f"L-2-ft @{D} (CONTROL)": ce_orders["L-2"],
        f"L-6-ft @{D}": ce_orders["L-6"],
        f"RRF(L-2, cue) @{D}": {q: rrf(ce_orders["L-2"][q], slate[q]) for q in pools},
        f"RRF(L-2, L-6) @{D}": {q: rrf(ce_orders["L-2"][q], ce_orders["L-6"][q]) for q in pools},
        f"RRF(L-2, L-6, cue) @{D}": {q: rrf(ce_orders["L-2"][q], ce_orders["L-6"][q], slate[q])
                                     for q in pools},
    }

    print("\n" + "=" * 112)
    print(f"cond@3 AT DEPTH {D} -- input recall {ir} is common to every arm, so only cond@3 moves")
    print("=" * 112)
    hdr = " ".join(f"{'R@' + str(k):>7}" for k in KS)
    print(f"  {'arm':26s} {hdr}   {'cond@1':>7} {'cond@3':>7}   {'vs .975':>8}")
    cells = {}
    for name, o in arms.items():
        ranks = {q: best_rank(p, o[q]) for q, p in pools.items()}
        vals = {k: sum(1 for r in ranks.values() if r <= k) / n for k in KS}
        prev = 0.0
        for k in KS:
            if vals[k] + 1e-12 < prev:
                raise SystemExit(f"REFUSING (GATE 4). R@k not monotone at k={k} in {name}.")
            prev = vals[k]
        if abs(round(vals[D], 4) - ir) > 1e-9:
            raise SystemExit(f"REFUSING (GATE 4). R@{D} {round(vals[D], 4)} != input recall {ir} "
                             f"in {name}.")
        c1, c3 = vals[1] / ir, vals[3] / ir
        cells[name] = {"depth": D, "input_recall": ir,
                       **{f"R@{k}": round(v, 4) for k, v in vals.items()},
                       "conditional_top1": round(c1, 4), "conditional_top3": round(c3, 4),
                       "gap_to_target_cond3": round(TARGET_COND3 - c3, 4)}
        print(f"  {name:26s} " + " ".join(f"{vals[k]:>7.4f}" for k in KS) +
              f"   {c1:>7.4f} {c3:>7.4f}   {c3 - TARGET_COND3:>+8.4f}")

    ctrl = cells[f"L-2-ft @{D} (CONTROL)"]
    print("\n" + "=" * 112)
    print("VERDICT")
    print("=" * 112)
    print(f"  mathematical limit at depth {D} (cond@3 = 1.0): R@3 = {ir:.4f}")
    print(f"  pipeline ceiling at any depth (pruning survival): R@3 = 0.9825")
    for name, c in cells.items():
        if name == f"L-2-ft @{D} (CONTROL)":
            continue
        print(f"  {name:26s} dR@3 {c['R@3'] - ctrl['R@3']:+.4f}   "
              f"dcond@3 {c['conditional_top3'] - ctrl['conditional_top3']:+.4f}   "
              f"dR@1 {c['R@1'] - ctrl['R@1']:+.4f}")
    best = max(cells, key=lambda k: cells[k]["R@3"])
    print(f"\n  best arm: {best}  R@3 {cells[best]['R@3']:.4f}  cond@3 "
          f"{cells[best]['conditional_top3']:.4f}  "
          f"({'CLEARS' if cells[best]['conditional_top3'] >= TARGET_COND3 else 'short of'} "
          f"the {TARGET_COND3} stage-retention target)")

    # -- CONDITIONAL STAGE RETENTION ---------------------------------------------------------------
    # Each stage scored ONLY on the queries where gold survived every prior stage, so a stage is
    # never blamed for gold that a previous stage had already lost. This is the quantity the stage
    # model calls "stage retention" and it is what a 0.975-per-stage target is stated against.
    corpus_n = None
    try:
        from marlowe_eval.datasets import longmemeval  # noqa: E402
        sp = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
        corpus = longmemeval.load(REPO / sp["corpus_path"])
        fit_ids = set(sp.get("fit") or sp.get("fit_query_ids") or [])
        if fit_ids:
            corpus_n = sum(1 for c in corpus.cases
                           if c.query_id in fit_ids and getattr(c, "gold_answer", None) is not None)
    except Exception as exc:  # noqa: BLE001
        print(f"\n  (stage 1 not derivable here: {exc})")

    surv_ok = [q for q, p in pools.items()
               if any(p.gold[i] and p.candidates[i].survived_pruning
                      for i in range(len(p.candidates)))]
    slate_ok = [q for q in surv_ok if any(pools[q].gold[i] for i in slate[q])]

    print("\n" + "=" * 112)
    print(f"CONDITIONAL STAGE RETENTION -- each stage judged ONLY where gold reached it "
          f"(fit, depth {D})")
    print("=" * 112)
    print(f"  {'stage':38s} {'in':>6} {'out':>6} {'retention':>10}   {'vs 0.975':>9}")
    rows = []
    if corpus_n:
        rows.append(("ingest + exclusions + scope", corpus_n, n))
    else:
        print(f"  {'ingest + exclusions + scope':38s} {'—':>6} {n:>6} "
              f"{'(0.9786)':>10}   {'quoted':>9}  <- held-out figure from the record, not measured here")
    rows.append(("session pruning", n, len(surv_ok)))
    rows.append((f"slate draw (top-{D} by cue key)", len(surv_ok), len(slate_ok)))
    stage_tbl = {}
    for label, a, b in rows:
        ret = b / a
        stage_tbl[label] = {"in": a, "out": b, "retention": round(ret, 4)}
        print(f"  {label:38s} {a:>6} {b:>6} {ret:>10.4f}   {ret - TARGET_COND3:>+9.4f}")
    for name, c in cells.items():
        b = round(c["conditional_top3"] * len(slate_ok))
        stage_tbl[f"cross-encoder top-3 :: {name}"] = {
            "in": len(slate_ok), "out": int(b), "retention": c["conditional_top3"]}
        print(f"  {'cross-encoder top-3 :: ' + name:38s} {len(slate_ok):>6} {int(b):>6} "
              f"{c['conditional_top3']:>10.4f}   {c['conditional_top3'] - TARGET_COND3:>+9.4f}")

    # The chain from the n-query base EXCLUDES the ingest stage, because R@3 is measured on n.
    post = [stage_tbl[label]["retention"] for label, _, _ in rows
            if not label.startswith("ingest")] + [cells[best]["conditional_top3"]]
    prod = 1.0
    for v in post:
        prod *= v
    print(f"\n  product of post-ingest retentions: {prod:.4f}  vs measured R@3 "
          f"{cells[best]['R@3']:.4f}  reconstructs: {abs(prod - cells[best]['R@3']) < 1e-3}")
    proj = 1.0
    for v in post[:-1]:
        proj *= v
    print(f"  if cond@3 reached {TARGET_COND3}: R@3 = {proj * TARGET_COND3:.4f} "
          f"(on the {n}-query published basis)")

    # -- IS cond@3 SATURATED? the union oracle over the arms -----------------------------------------
    # If structurally different rankers miss the SAME cases, the residue is intrinsic and cond@3 is
    # at its limit for this model family. If they miss DIFFERENT cases, a combination has headroom.
    # The union uses gold labels and is an UPPER BOUND, not a shippable configuration.
    print("\n" + "=" * 112)
    print("IS cond@3 SATURATED? union oracle over the arms (uses labels -- a CEILING, not a system)")
    print("=" * 112)
    hitset = {}
    for name, o in arms.items():
        hitset[name] = {q for q in slate_ok if best_rank(pools[q], o[q]) <= 3}
    ce_only = [k for k in arms if "cue" not in k]
    union_ce = set().union(*(hitset[k] for k in ce_only))
    inter_ce = set.intersection(*(hitset[k] for k in ce_only))
    union_all = set().union(*hitset.values())
    m = len(slate_ok)
    for label, s in (("L-2 alone", hitset[f"L-2-ft @{D} (CONTROL)"]),
                     ("intersection of the 3 CE arms", inter_ce),
                     ("UNION of the 3 CE arms", union_ce),
                     ("UNION of all 5 arms", union_all)):
        print(f"  {label:34s} {len(s):>4}/{m}   cond@3 {len(s) / m:.4f}   "
              f"R@3 {len(s) / n * (m / m):.4f}" if False else
              f"  {label:34s} {len(s):>4}/{m}   cond@3 {len(s) / m:.4f}")
    print(f"\n  headroom from combining the CE arms: {len(union_ce) - len(hitset[ce_only[0]])} cases "
          f"({(len(union_ce) - len(hitset[ce_only[0]])) / m:+.4f} cond@3)")
    missed = sorted(set(slate_ok) - union_all)
    print(f"  cases NO arm places in the top 3: {len(missed)}")
    from collections import Counter
    print(f"  their categories: {dict(Counter(pools[q].category for q in missed))}")
    print(f"  ids: {missed}")
    stage_tbl["_union_oracle"] = {
        "n_in_slate": m, "L2_alone": len(hitset[f"L-2-ft @{D} (CONTROL)"]),
        "intersection_ce": len(inter_ce), "union_ce": len(union_ce), "union_all": len(union_all),
        "cond3_union_ce": round(len(union_ce) / m, 4),
        "missed_by_every_arm": missed,
    }

    art = {"_what": f"attack on cond@3 at depth {D}, the one deficient stage under the rank-3 model",
           "_split": "fit", "_rrf_k": RRF_K, "_rrf_k_fixed_before_measurement": True,
           "_target_cond3": TARGET_COND3, "_input_recall": ir,
           "_mathematical_limit_R@3_at_this_depth": ir,
           "_pipeline_ceiling_R@3_pruning_bound": 0.9825,
           "_gates": {"fit_R@1": r1, "published": CONTROL_R1, "slate_exact": exact},
           "cells": cells}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(art, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
