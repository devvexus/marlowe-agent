"""The slate is the target -- and its ORDERING is, not its size. Which draw rule maximises recall?

    PYTHONIOENCODING=utf-8 python tools/slate_draw_rules.py

## Why, in one table

`tools/rk_by_depth.py` measured R@3 = input_recall(depth) x conditional_top3(depth) on fit:

    depth  in.rec   R@3   cond@3
       10  0.9214 0.8996  0.9763
       20  0.9738 0.9258  0.9507
       30  0.9825 0.9258  0.9422
       40  0.9825 0.9170  0.9333
       50  0.9825 0.9127  0.9289

**Depth is exhausted.** R@3 peaks at 0.9258 and declines; input recall saturates at 0.9825 (the
4 turns session pruning removed are below rank 50 in the cue order and no depth reaches them);
`cond@3` decays monotonically because every extra slot is another distractor.

But **input recall at a given depth is a property of the CUE ORDERING ALONE** -- the cross-encoder
has no vote in what it is handed. So re-ordering buys recall at NO cost in `cond@3`, where
deepening buys it at a worsening one. If a draw rule delivered depth-20's recall inside a depth-10
slate, R@3 would be 0.9738 x 0.9763 = **0.9507**, against 0.9258 for the best depth.

## What is measured

Input recall at depths 10 and 20 for every draw rule -- this needs no cross-encoder at all and is
the quantity that binds R@3:

  * `shipped`      the product's fused cue key (`cue_only_order`) -- THE CONTROL
  * `bm25`         lexical cue alone
  * `dense`        dense cosine alone
  * `rrf`          reciprocal rank fusion of the two, k = 60
  * `either_oracle`  gold in bm25's top-d OR dense's top-d -- AN UPPER BOUND, uses labels, NOT
                     shippable, reported as a ceiling and labelled as one everywhere

Each is run with the product's pruning level ON (survivors first, as `retrieve.rs` orders) and
OFF, because pruning's 4-case cost is now the binding ceiling and its value under R@3 has never
been read.

**RRF's k = 60 is the published default from Cormack et al. and is fixed here BEFORE any number is
produced.** It is not tuned, and no other value is tried; a k chosen after seeing the result would
be exactly the knob this project has four collapses from.

## The gate

`cue_only_order`'s depth-10 slate must equal the candidate set the binary actually reranked -- read
from the dump (`rerank_score is not None`), not reconstructed -- on all 229 queries, and the shipped
key must reproduce fit R@1 0.7555. Without both, a "better" rule is being compared against a
control that is not the product.

## Reuse, not re-implementation

`cue_only_order` from `correct_case_control`; ranking key and gate constant from
`sweep_reranker_frontier`; pools from `reach_pools`. Cue scores are READ FROM THE DUMP the binary
produced. No cue is recomputed here, so no second implementation can disagree with the first.

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

from correct_case_control import cue_only_order  # noqa: E402
from reach_pools import load_pools  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "slate-draw-rules.json"
RRF_K = 60  # Cormack et al.'s published default. FIXED BEFORE ANY NUMBER. Not tuned.
DEPTHS = (10, 20)


def rank_map(pool, key, prune_first):
    """Indices ordered by `key` descending, optionally survivors first, id ascending as the tiebreak.

    The id tiebreak matches `shipped_order`'s level 5 so two rules never differ by tie order alone.
    """
    idx = list(range(len(pool.candidates)))
    idx.sort(key=lambda i: (
        (not pool.candidates[i].survived_pruning) if prune_first else 0,
        -(key(pool.candidates[i]) if key(pool.candidates[i]) is not None else -1e9),
        i,
    ))
    return idx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    pools, stats = load_pools(FIT_POOLS)
    print(f"fit pools: {stats['pools']} queries, {stats['candidates']:,} candidates")

    ship = {q: shipped_order(p) for q, p in pools.items()}
    r1 = round(sum(int(p.gold[int(ship[q][0])]) for q, p in pools.items()) / len(pools), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING (GATE 1). fit R@1 {r1}; published {CONTROL_R1}.")
    print(f"GATE 1  shipped key fit R@1 {r1} == published {CONTROL_R1}   PASSED")

    cue = {q: [int(v) for v in cue_only_order(p)] for q, p in pools.items()}
    exact = sum(set(cue[q][:10]) == {i for i, c in enumerate(p.candidates)
                                     if c.rerank_score is not None}
                for q, p in pools.items())
    print(f"GATE 2  cue slate at depth 10 == the set the binary reranked: {exact}/{len(pools)} exact")
    if exact != len(pools):
        raise SystemExit("REFUSING (GATE 2). The control is not the product's slate.")

    def bm25(c):
        return c.lexical_bm25

    def dense(c):
        return c.dense_cosine

    rules = {}
    for prune in (True, False):
        tag = "" if prune else " (no pruning level)"
        b = {q: rank_map(p, bm25, prune) for q, p in pools.items()}
        d = {q: rank_map(p, dense, prune) for q, p in pools.items()}
        rules[f"bm25{tag}"] = b
        rules[f"dense{tag}"] = d
        rrf = {}
        for q, p in pools.items():
            rb = {i: r for r, i in enumerate(b[q])}
            rd = {i: r for r, i in enumerate(d[q])}
            sc = {i: 1.0 / (RRF_K + rb[i]) + 1.0 / (RRF_K + rd[i]) for i in range(len(p.candidates))}
            idx = sorted(range(len(p.candidates)), key=lambda i: (
                (not p.candidates[i].survived_pruning) if prune else 0, -sc[i], i))
            rrf[q] = idx
        rules[f"rrf k={RRF_K}{tag}"] = rrf
    rules["shipped (CONTROL)"] = cue

    print("\n" + "=" * 100)
    print("INPUT RECALL BY SLATE DRAW RULE -- the quantity that binds R@3. No cross-encoder involved.")
    print("=" * 100)
    print(f"  {'draw rule':34s} " + " ".join(f"{'ir@' + str(d):>9}" for d in DEPTHS) +
          f"   {'proj R@3 @10':>13}")
    results = {}
    order_names = ["shipped (CONTROL)"] + [k for k in rules if k != "shipped (CONTROL)"]
    for name in order_names:
        o = rules[name]
        row = {}
        for d in DEPTHS:
            hit = sum(any(p.gold[i] for i in o[q][:d]) for q, p in pools.items())
            row[f"ir@{d}"] = round(hit / len(pools), 4)
        # cond@3 is a property of the reranker over a depth-10 slate, measured at 0.9763.
        row["projected_R@3_at_depth10"] = round(row["ir@10"] * 0.9763, 4)
        results[name] = row
        print(f"  {name:34s} " + " ".join(f"{row['ir@' + str(d)]:>9.4f}" for d in DEPTHS) +
              f"   {row['projected_R@3_at_depth10']:>13.4f}")

    # -- the ceiling ------------------------------------------------------------------------------
    print("\n  UPPER BOUND (uses gold labels; NOT shippable, quoted only as a ceiling):")
    for d in DEPTHS:
        b = rules["bm25"]
        dn = rules["dense"]
        hit = sum(any(p.gold[i] for i in b[q][:d]) or any(p.gold[i] for i in dn[q][:d])
                  for q, p in pools.items())
        ir = round(hit / len(pools), 4)
        results[f"either_cue_oracle@{d}"] = ir
        print(f"    either-cue oracle  ir@{d} {ir:.4f}   -> projected R@3 at depth 10 "
              f"{ir * 0.9763:.4f}" if d == 10 else
              f"    either-cue oracle  ir@{d} {ir:.4f}")

    best = max((k for k in results if isinstance(results[k], dict)),
               key=lambda k: results[k]["ir@10"])
    ctrl = results["shipped (CONTROL)"]["ir@10"]
    print(f"\n  best shippable rule at depth 10: {best}  ir@10 {results[best]['ir@10']:.4f}  "
          f"vs control {ctrl:.4f}  delta {results[best]['ir@10'] - ctrl:+.4f}")
    print("  NOTE: projected R@3 assumes cond@3 = 0.9763 measured on the SHIPPED slate. A different "
          "slate is a different candidate set, so the projection is a HYPOTHESIS to be confirmed by "
          "reranking, never a result.")

    art = {"_what": "input recall by slate draw rule at fixed depth -- can re-ordering buy the "
                    "recall that deepening buys, without deepening's cond@3 cost?",
           "_split": "fit", "_rrf_k": RRF_K, "_rrf_k_fixed_before_measurement": True,
           "_gate": {"fit_R@1": r1, "published": CONTROL_R1, "cue_slate_exact": exact},
           "_cond3_used_for_projection": 0.9763,
           "results": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(art, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
