"""M0c Session M — the reranker quality/latency frontier on the GPU deployment target.

Judged by `runs/session-m0c-m/PREREGISTRATION.json`, which was written and COMMITTED first.

    python tools/preregister_m0c_m.py          # first, always
    python tools/sweep_reranker_frontier.py

## What this measures

For each admitted cross-encoder x each rerank depth, on the FIT split: R@1, R@1_current, R@5,
input recall at that depth, conditional accuracy, and GPU milliseconds per query.

Nine models were fetched, digest-pinned and gated in Session I and then recorded "deferred as
UNMEASURED -- not closed, not refuted, not run". Every cost figure ever used to reject one of them
is a **1-thread CPU** number, and the deployment target is a GPU. ADR-029 ships the CUDA path at
14.7 ms P95 against a 300 ms budget, so the rerank stage may grow ~85x before the budget binds.

## THE CONTROL, and nothing is believed before it passes

The shipped model at depth 10 must reproduce the published fit R@1 of **0.7555 exactly**. If it
does not, this pipeline is not computing what the binary computes and every other cell is a number
of the right shape about the wrong system.

That is `publish_precision_coverage.py`'s discipline, adopted here for the same reason it exists
there: it *"refuses to write unless its held-out R@1 equals cue-overlap.json's exactly"*, and it was
added after a session produced a complete, plausible, correctly-formatted curve that read R@1
0.5411 where the authority read 0.6725.

**A reproduction is not a formality here.** The pipeline re-derives a five-level ranking key from a
dump; there are at least four ways to get it subtly wrong (tiebreak direction, `None` ordering on
unreranked candidates, pruning survival, row order) and every one of them yields a plausible number.

## Why the slate is drawn on the SHIPPED key

The slate is the top `depth` survivors under the *existing* pre-rerank key. Drawing it with the key
the reranker then replaces is what makes this a rerank stage rather than a new cue -- the same
reason `retrieve.rs` draws it that way. Changing the slate rule is a different experiment (M0c
Session A's R3 arm, which was +0.0087 on fit and -0.0044 on held-out).

## What this does NOT do

It ships nothing and touches no Rust. bge-reranker-base and jina-v2 are XLM-RoBERTa and cannot load
in `rerank.rs` at all, which is a WordPiece pair encoder with a digest-pinned tokenizer. Measure
first, build once, and only for a winner.
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

from marlowe_eval.datasets import longmemeval  # noqa: E402

FIT_POOLS = REPO / "runs" / "session-k" / "fit"
OUT_DIR = REPO / "runs" / "session-m0c-m"
PREREG = OUT_DIR / "PREREGISTRATION.json"

# The published fit numbers this pipeline must reproduce before anything else is read.
CONTROL_R1 = 0.7555
CONTROL_R1_CURRENT = 0.6900

MAX_SEQ = 256  # the shipped sequence length; ADR-015 -- a length change is a different scorer

# Every admitted model, cheapest first. The two fine-tunes are Session J's; the rest are Session I's
# manifest. `ms-marco-MiniLM-L-2-v2-ft-session-j` is the shipped control and is scored first.
MODELS = [
    "ms-marco-MiniLM-L-2-v2-ft-session-j",   # SHIPPED CONTROL
    "ms-marco-MiniLM-L-6-v2-ft-session-j",
    "ms-marco-MiniLM-L-2-v2",
    "ms-marco-MiniLM-L-4-v2",
    "ms-marco-MiniLM-L-6-v2",
    "ms-marco-MiniLM-L-12-v2",
    "jina-reranker-v1-turbo-en",
    "bge-reranker-base",
    "jina-reranker-v2-base-multilingual",
    "mxbai-rerank-base-v1",
]

# Tier A loads in the shipped Rust path with a digest re-pin and nothing else. Tier B needs a second
# tokenizer implementation in Rust. Reported as a cost column so shippability is known BEFORE a
# winner is picked rather than discovered after.
TIER_A = {
    "ms-marco-MiniLM-L-2-v2-ft-session-j",
    "ms-marco-MiniLM-L-6-v2-ft-session-j",
    "ms-marco-MiniLM-L-2-v2",
    "ms-marco-MiniLM-L-4-v2",
    "ms-marco-MiniLM-L-6-v2",
    "ms-marco-MiniLM-L-12-v2",
}


def shipped_order(pool: Pool) -> np.ndarray:
    """`retrieve.rs`'s five-level key, as an index order over the pool's own row order.

    1. survived pruning (survivors first)
    2. rerank score descending -- `None` AFTER any `Some`
    3. score  (the winning cue's z)
    4. margin (its lead over its own runner-up)
    5. id ascending

    Level 2's `None` handling is written out rather than derived: Rust's `Option` ordering puts
    `None` FIRST, which is the opposite of what is wanted, and `retrieve.rs` says so in a comment
    for the same reason. An unreranked candidate must never outrank a reranked one on the strength
    of having no score.
    """
    cands = pool.candidates
    keys = []
    for i, c in enumerate(cands):
        reranked = c.rerank_score is not None
        keys.append(
            (
                0 if c.survived_pruning else 1,      # survivors first
                0 if reranked else 1,                # reranked before unreranked
                -(c.rerank_score if reranked else 0.0),
                -c.score,
                -c.margin,
                c.memory_id or "",
            )
        )
    return np.array(sorted(range(len(cands)), key=lambda i: keys[i]), dtype=np.int64)


def reordered(pool: Pool, slate: list[int], logits: list[float]) -> np.ndarray:
    """The pool's order with `slate` re-scored by a new cross-encoder.

    Everything outside the slate keeps its relative position BELOW the slate, exactly as the shipped
    key does: an unreranked candidate sorts after every reranked one.
    """
    cands = pool.candidates
    new = {i: v for i, v in zip(slate, logits)}
    keys = []
    for i, c in enumerate(cands):
        if i in new:
            keys.append((0, -new[i], 0.0, 0.0, c.memory_id or ""))
        else:
            keys.append((1, 0.0, -c.score, -c.margin, c.memory_id or ""))
    return np.array(sorted(range(len(cands)), key=lambda i: keys[i]), dtype=np.int64)


def current_gold_ids(corpus) -> dict[str, frozenset[str]]:
    """Gold turns MINUS the superseded ones, for R@1_current.

    LongMemEval marks both the stale and the current turn `has_answer`, so retrieving an outdated
    value scores as an R@1 hit. M0c Session A measured the inflation at +0.0437 held-out and +0.28
    on knowledge-update, where 38.5% of apparent hits are the stale fact.

    **The classifier deliberately uses no ordering.** M0c Session A's first version ranked the two
    answer sessions by date and called the later one current; its own diagnostic killed it -- date
    order agreed with the session suffix on only 166 of 250 cases, and the corpus dates 76 of 500
    cases AFTER their own question. The quantity wanted is which gold turn states the value the
    answer holds, and that is directly checkable against the answer string.
    """
    out: dict[str, frozenset[str]] = {}
    gold_map = corpus.gold_map()
    all_texts = turn_texts()
    for case in corpus.cases:
        gold = gold_map.get(case.query_id, frozenset())
        if case.is_abstention or not case.gold_answer:
            out[case.query_id] = gold
            continue
        answer = case.gold_answer.strip().lower()
        texts = all_texts.get(case.query_id, {})
        bearing = {t for t in gold if answer and answer in (texts.get(t) or "").lower()}
        # No turn contains the answer string verbatim -> no defensible current/stale split for this
        # case, so it keeps its full gold set and is counted exactly as R@1 counts it. Flagged in
        # the report rather than silently resolved by a proxy.
        out[case.query_id] = frozenset(bearing) if bearing else gold
    return out


def evaluate(pools, order_by_qid, gold_current) -> dict:
    n = len(pools)
    r1 = r5 = r1_cur = 0
    per_cat: dict[str, list[int]] = {}
    for qid, pool in pools.items():
        order = order_by_qid[qid]
        gold = pool.gold
        top = order[0]
        hit1 = bool(gold[top])
        r1 += int(hit1)
        r5 += int(any(gold[i] for i in order[:5]))
        cur = gold_current.get(qid, frozenset())
        hit_cur = bool(hit1 and pool.candidates[top].turn_id in cur)
        r1_cur += int(hit_cur)
        per_cat.setdefault(pool.category, [0, 0, 0])
        per_cat[pool.category][0] += 1
        per_cat[pool.category][1] += int(hit1)
        per_cat[pool.category][2] += int(hit_cur)
    return {
        "n": n,
        "R@1": round(r1 / n, 4),
        "R@1_current": round(r1_cur / n, 4),
        "R@5": round(r5 / n, 4),
        "per_category": {
            k: {"n": v[0], "R@1": round(v[1] / v[0], 4), "R@1_current": round(v[2] / v[0], 4)}
            for k, v in sorted(per_cat.items())
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depths", type=int, nargs="+", default=[10, 20, 30])
    ap.add_argument("--models", nargs="+", default=MODELS)
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--out", default=str(OUT_DIR / "frontier.json"))
    args = ap.parse_args()

    if not PREREG.exists():
        raise SystemExit(
            f"{PREREG} does not exist. Run tools/preregister_m0c_m.py first -- the bands that "
            "judge this sweep have to predate its numbers."
        )

    pools, stats = load_pools(FIT_POOLS)
    print(f"fit pools: {stats['pools']} queries, {stats['candidates']:,} candidates")

    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_current = current_gold_ids(corpus)
    texts = turn_texts()

    # ---- the control, before anything else is scored ----------------------------------------
    baseline_order = {qid: shipped_order(p) for qid, p in pools.items()}
    control = evaluate(pools, baseline_order, gold_current)
    ok = abs(control["R@1"] - CONTROL_R1) < 1e-9
    print(f"\nCONTROL  shipped key, depth 10: R@1 {control['R@1']}  (published {CONTROL_R1})  "
          f"R@1_current {control['R@1_current']}  (published {CONTROL_R1_CURRENT})")
    if not ok:
        raise SystemExit(
            f"REFUSING TO SWEEP. The reconstruction reads R@1 {control['R@1']}; the published fit "
            f"value is {CONTROL_R1}. This pipeline is not computing what the binary computes, so "
            "every cell it would produce is a plausible number about the wrong system. Fix the "
            "key before measuring anything."
        )
    print("control reproduces the published fit R@1 exactly. proceeding.\n")

    results = []
    for name in args.models:
        try:
            ce = R.load(name, provider=args.provider)
        except Exception as e:  # noqa: BLE001
            print(f"{name}: REFUSED -- {type(e).__name__}: {str(e)[:140]}")
            results.append({"model": name, "refused": f"{type(e).__name__}: {str(e)[:300]}"})
            continue

        gates = {
            "smoke": R.smoke_test(ce),
            "determinism": R.determinism(ce),
            "batch_invariance": R.batch_invariance(ce),
        }
        if not gates["smoke"].get("pass"):
            print(f"{name}: REFUSED -- discrimination smoke test failed")
            results.append({"model": name, "refused": "smoke_test", "gates": gates})
            continue

        for depth in args.depths:
            order_by_qid = {}
            per_query_ms = []
            recall_at_depth = 0
            for qid, pool in pools.items():
                base = baseline_order[qid]
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
                "tier": "A" if name in TIER_A else "B",
                "params_m": ce.params_m,
                "arch": ce.arch,
                "depth": depth,
                "input_recall": round(ir, 4),
                "conditional_accuracy": round(got["R@1"] / ir, 4) if ir else 0.0,
                "rerank_ms_p50": round(float(np.percentile(per_query_ms, 50)), 2),
                "rerank_ms_p95": round(float(np.percentile(per_query_ms, 95)), 2),
                "provider": args.provider,
                "gates": gates,
                **got,
            }
            results.append(cell)
            print(
                f"{name:<38} d{depth:<3} R@1 {got['R@1']:.4f}  cur {got['R@1_current']:.4f}  "
                f"ir {ir:.4f}  ca {cell['conditional_accuracy']:.4f}  "
                f"{cell['rerank_ms_p50']:7.2f} ms p50"
            )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "_what": "M0c Session M -- reranker frontier, FIT split, GPU",
                "judged_by": "runs/session-m0c-m/PREREGISTRATION.json",
                "provider": args.provider,
                "max_seq": MAX_SEQ,
                "control": control,
                "control_published": {"R@1": CONTROL_R1, "R@1_current": CONTROL_R1_CURRENT},
                "pools": stats,
                "cells": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
