"""M0c Session M / W2 — the rerank depth sweep, DOWNWARD. Fit split only.

    python tools/sweep_rerank_depth_down.py

`tools/sweep_reranker_frontier.py` swept depths {10, 20, 30}. Depth below 10 has never been
measured. R@1 factorises as `input_recall x conditional_accuracy`, and conditional accuracy falls
monotonically as depth RISES (0.8200 -> 0.7893 -> 0.7823 at d10/d20/d30). Nobody has asked what it
does when depth falls.

## WHY THIS IS A NEW DRIVER AND NOT `--depths 1 2 3 ...` ON THE EXISTING SWEEP

The existing sweep draws its slate as `shipped_order(pool)[:depth]`, and `shipped_order`'s SECOND
sort level is **the shipped cross-encoder's own rerank score**. For depth >= 10 that is harmless:
the shipped stage reranks exactly the top 10 of the pre-rerank key, so reordering within that block
leaves the top-10 (and top-20, top-30) SET identical to the pre-rerank key's.

**Below 10 it is not harmless, it is circular.** `shipped_order(pool)[:3]` is the shipped model's
own top 3, so a "depth 3" cell would measure a model re-scoring a slate the incumbent had already
picked, and "depth 1" would reproduce 0.7555 rather than the cue-only 0.5633 — the degenerate
control would read as a pass while measuring nothing. Running `--depths 1 2 3` on the existing tool
produces a complete, plausible, wrong table.

So the slate here is drawn on the **pre-rerank cue key** (`cue_order`), which is `shipped_order`
with level 2 deleted and nothing else changed. That is what `retrieve.rs` draws the slate on.

## THREE INSTRUMENT CHECKS, ALL BEFORE ANY CELL IS READ

1. **The published control.** `shipped_order` must reproduce fit R@1 = 0.7555 exactly. This is the
   existing sweep's gate, imported rather than restated.
2. **`cue_order`'s top 10 is exactly the set the product reranked.** The dump records which
   candidates carry a `rerank_score`, so what slate the binary drew is not reconstructed — it is
   READ. If `cue_order[:10]` disagrees with it on any query, the cue key is wrong and every cell
   below depth 10 is a number about the wrong slate. This is the check that the existing gate
   cannot make, because the existing gate passes on a key that is circular below 10.
3. **Depth 1 is degenerate.** At depth 1 the cross-encoder cannot reorder anything, so R@1 must
   equal the cue-only R@1 for BOTH models and for the un-reranked cue order itself. Three numbers
   that must agree, and they are free.

Nothing is modified in `sweep_reranker_frontier.py`, `reach_pools.py` or `session_i_rerankers.py` —
`shipped_order`, `reordered`, `evaluate` and `current_gold_ids` are all imported from the first, so
there is no second ranking key in this file.

CAVEAT, stated rather than hidden: the imported `reordered` keys non-slate candidates on
`(score, margin)` without the pruning level, so **R@5 at depths below 5 mixes pruning-failed
candidates into ranks 2-5**. R@1, R@1_current, input recall and conditional accuracy are unaffected
(the slate is non-empty at every depth, so rank 1 always comes from the slate). R@5 is reported for
depths >= 5 only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import session_i_rerankers as R  # noqa: E402
from reach_pools import Pool, load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import (  # noqa: E402
    CONTROL_R1,
    CONTROL_R1_CURRENT,
    FIT_POOLS,
    MAX_SEQ,
    OUT_DIR,
    current_gold_ids,
    evaluate,
    reordered,
    shipped_order,
)

from marlowe_eval.datasets import longmemeval  # noqa: E402

# The cue-only fit R@1 the degenerate depth-1 cell must equal. Recomputed here from the pools rather
# than trusted, and the recomputed value is what depth 1 is checked against; this constant is only
# what the recomputation is itself checked against.
CUE_ONLY_R1 = 0.5633

MODELS = [
    "ms-marco-MiniLM-L-2-v2-ft-session-j",   # SHIPPED
    "ms-marco-MiniLM-L-6-v2-ft-session-j",
]


def cue_order(pool: Pool) -> np.ndarray:
    """`retrieve.rs`'s PRE-rerank key — the key the slate is drawn on.

    Identical to `shipped_order` with its level-2 rerank term removed, and nothing else changed:

    1. survived pruning (survivors first)
    2. score  (the winning cue's z)
    3. margin (its lead over its own runner-up)
    4. id ascending

    This is the ordering the rerank stage REPLACES, so it is what a slate of any depth must be
    drawn from. Validated against the dump's own record of which candidates were reranked.
    """
    cands = pool.candidates
    keys = [
        (0 if c.survived_pruning else 1, -c.score, -c.margin, c.memory_id or "")
        for c in cands
    ]
    return np.array(sorted(range(len(cands)), key=lambda i: keys[i]), dtype=np.int64)


def slate_agreement(pools: dict[str, Pool], depth: int = 10) -> dict:
    """Does `cue_order`'s top `depth` equal the set the binary actually reranked?

    Read, not reconstructed: a candidate carries `rerank_score is not None` iff the shipped stage
    scored it. Queries where the shipped stage reranked a different count (an exhausted budget, a
    pool smaller than the depth) are reported separately rather than folded into the disagreement
    count, because they are a property of the run and not of the key.
    """
    exact = mismatched = size_differs = 0
    examples = []
    for qid, pool in pools.items():
        actual = {i for i, c in enumerate(pool.candidates) if c.rerank_score is not None}
        mine = set(int(i) for i in cue_order(pool)[:depth])
        if len(actual) != depth:
            size_differs += 1
            continue
        if actual == mine:
            exact += 1
        else:
            mismatched += 1
            if len(examples) < 5:
                examples.append({"qid": qid, "only_mine": sorted(mine - actual),
                                 "only_actual": sorted(actual - mine)})
    return {"depth": depth, "exact": exact, "mismatched": mismatched,
            "reranked_count_not_depth": size_differs, "examples": examples}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depths", type=int, nargs="+",
                    default=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    ap.add_argument("--models", nargs="+", default=MODELS)
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--out", default=str(OUT_DIR / "depth-down.json"))
    ap.add_argument("--dump-hits", action="store_true",
                    help="also record the per-query rank-1 hit vector for each cell, so two "
                         "depths can be compared by DISCORDANT PAIRS rather than by the "
                         "difference of two rates. A +1-case gap between cells that agree on "
                         "225 queries and a +1-case gap between cells that disagree on 40 are "
                         "the same headline number and are not the same result.")
    args = ap.parse_args()

    pools, stats = load_pools(FIT_POOLS)
    print(f"fit pools: {stats['pools']} queries, {stats['candidates']:,} candidates")

    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_current = current_gold_ids(corpus)
    texts = turn_texts()

    # ---- INSTRUMENT 1: the published control -------------------------------------------------
    shipped = {qid: shipped_order(p) for qid, p in pools.items()}
    control = evaluate(pools, shipped, gold_current)
    print(f"\nGATE 1  shipped key, depth 10: R@1 {control['R@1']}  (published {CONTROL_R1})  "
          f"R@1_current {control['R@1_current']}  (published {CONTROL_R1_CURRENT})")
    if abs(control["R@1"] - CONTROL_R1) >= 1e-9:
        raise SystemExit(
            f"REFUSING TO SWEEP. The reconstruction reads R@1 {control['R@1']}; the published fit "
            f"value is {CONTROL_R1}. Every cell would be a plausible number about the wrong system."
        )
    print("        control reproduces the published fit R@1 exactly.")

    # ---- INSTRUMENT 2: the cue key draws the slate the binary drew ----------------------------
    agree = slate_agreement(pools, 10)
    print(f"\nGATE 2  cue_order[:10] vs the candidates the binary actually reranked: "
          f"exact {agree['exact']}  mismatched {agree['mismatched']}  "
          f"(reranked-count != 10 on {agree['reranked_count_not_depth']} queries, excluded)")
    if agree["mismatched"]:
        for ex in agree["examples"]:
            print(f"          {ex}")
        raise SystemExit(
            "REFUSING TO SWEEP. The pre-rerank cue key does not reproduce the slate the product "
            "drew, so every sub-depth-10 cell would rerank a slate the product never draws."
        )
    print("        the pre-rerank cue key reproduces the product's slate exactly.")

    # ---- INSTRUMENT 3: the cue-only R@1 that depth 1 must equal -------------------------------
    cue = {qid: cue_order(p) for qid, p in pools.items()}
    cue_eval = evaluate(pools, cue, gold_current)
    print(f"\nGATE 3  cue-only order (no rerank at all): R@1 {cue_eval['R@1']}  "
          f"(brief states {CUE_ONLY_R1})  R@1_current {cue_eval['R@1_current']}")
    if abs(cue_eval["R@1"] - CUE_ONLY_R1) >= 1e-4:
        raise SystemExit(
            f"REFUSING TO SWEEP. Cue-only R@1 reads {cue_eval['R@1']}, the brief states "
            f"{CUE_ONLY_R1}. The depth-1 degenerate control would have nothing to check against."
        )
    print("        depth 1 must reproduce this exactly, for BOTH models.\n")

    results = []
    for name in args.models:
        ce = R.load(name, provider=args.provider)
        gates = {
            "smoke": R.smoke_test(ce),
            "determinism": R.determinism(ce),
            "batch_invariance": R.batch_invariance(ce),
        }
        print(f"{name}: params {ce.params_m}M  smoke {gates['smoke']['pass']}  "
              f"determinism {gates['determinism']['pass']}  "
              f"batch_inv max_abs_diff {gates['batch_invariance']['max_abs_diff']:.6f}")
        if not gates["smoke"].get("pass"):
            raise SystemExit(f"{name}: discrimination smoke test failed")

        for depth in args.depths:
            order_by_qid = {}
            per_query_ms = []
            recall_at_depth = 0
            for qid, pool in pools.items():
                base = cue[qid]
                slate = [int(i) for i in base[:depth]]
                docs = [texts.get(qid, {}).get(pool.candidates[i].turn_id) or "" for i in slate]
                t0 = time.perf_counter()
                logits = ce.score_batch(pool.question, docs, MAX_SEQ)
                per_query_ms.append((time.perf_counter() - t0) * 1000.0)
                order_by_qid[qid] = reordered(pool, slate, logits)
                recall_at_depth += int(any(pool.gold[i] for i in slate))

            got = evaluate(pools, order_by_qid, gold_current)
            ir = recall_at_depth / len(pools)
            cell = {
                "model": name,
                "params_m": ce.params_m,
                "depth": depth,
                "input_recall": round(ir, 4),
                "conditional_accuracy": round(got["R@1"] / ir, 4) if ir else 0.0,
                "rerank_ms_p50": round(float(np.percentile(per_query_ms, 50)), 2),
                "rerank_ms_p95": round(float(np.percentile(per_query_ms, 95)), 2),
                "provider": args.provider,
                "gates": gates,
                **got,
            }
            # R@5 is not meaningful below depth 5 with the imported `reordered` (see module
            # docstring). Removed rather than reported wrong.
            if depth < 5:
                cell["R@5"] = None
            if args.dump_hits:
                cell["hits"] = {
                    qid: int(bool(pool.gold[order_by_qid[qid][0]]))
                    for qid, pool in pools.items()
                }
            results.append(cell)
            print(
                f"{name:<38} d{depth:<3} R@1 {got['R@1']:.4f}  cur {got['R@1_current']:.4f}  "
                f"ir {ir:.4f}  ca {cell['conditional_accuracy']:.4f}  "
                f"{cell['rerank_ms_p50']:7.2f} ms p50  {cell['rerank_ms_p95']:7.2f} ms p95"
            )

            if depth == 1 and abs(got["R@1"] - cue_eval["R@1"]) >= 1e-9:
                raise SystemExit(
                    f"DEPTH-1 CONTROL FAILED for {name}: R@1 {got['R@1']} != cue-only "
                    f"{cue_eval['R@1']}. At depth 1 the cross-encoder cannot reorder anything, so "
                    "these must be identical. The harness is not doing what it claims and every "
                    "other cell is wrong."
                )
        print()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "_what": "M0c Session M / W2 -- rerank depth swept DOWNWARD, FIT split, GPU",
                "slate_drawn_on": "pre-rerank cue key (cue_order), validated against the dump",
                "provider": args.provider,
                "max_seq": MAX_SEQ,
                "control": control,
                "control_published": {"R@1": CONTROL_R1, "R@1_current": CONTROL_R1_CURRENT},
                "slate_agreement": agree,
                "cue_only": cue_eval,
                "pools": stats,
                "cells": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
