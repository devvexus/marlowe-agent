"""THE HELD-OUT READ. One configuration, one number, spent deliberately.

    python tools/heldout_read.py

## Why this file exists and why it is separate

The held-out split is a consumable. Every read of it teaches you something about the test set, and a
loop of read-adjust-read turns it into a second training set. So it gets its own tool, one
configuration per invocation, and the invocation is recorded.

## THE FLOOR WAS NOT CLEARED, AND THIS READ WAS SPENT ANYWAY

`runs/session-m0c-m/PREREGISTRATION.json` registers a promotion floor of **+0.02 over fit R@1
0.7555**, reused verbatim from M0c Session A so it could not be chosen to fit. The configuration
below measures **0.7729 on fit, +0.0174**. **It does not clear.**

By the registration, nothing is promoted and held-out is not touched. The read is being taken
regardless, **at the human's explicit direction**, with the argument recorded here rather than by
lowering the number:

  FOR. +0.0174 is the largest quality movement measured since ADR-018. Its two arms are the same
  model family so the fine-tune's fit contamination cancels. It is Tier A -- a digest re-pin in
  `rerank.rs` and a depth constant, no new tokenizer. It costs 37 ms of a 263 ms surplus. All six
  per-graph gates pass. And the fit/held-out relationship is not a fixed offset, so the held-out
  delta could be larger OR smaller than the fit delta -- which is the human's stated reason and is
  a correct one.

  AGAINST. The floor was set a session in advance for exactly this decision, and the one directly
  comparable fit gain in this project's history went from **+0.0087 fit to -0.0044 held-out** (M0c
  Session A's slate arm). A fit gain of this size has already changed sign once on this corpus.

**CLAUDE.md's rule is "if the bar looks wrong when the result arrives, argue it explicitly and
record the argument -- do not move it."** The bar is not moved. It stands at +0.02, this
configuration is recorded as having missed it on fit, and the held-out read is recorded as
discretionary.

## The test

McNemar exact, two-sided, on the discordant pairs. The comparison is PAIRED -- the same held-out
cases, one thing changed -- so an unpaired proportion test would be the wrong instrument and would
also be far less powerful. Wilson half-width at n=229, p=0.67 is +/-0.061; McNemar resolves a
change an order of magnitude smaller because it reads only the cases that moved.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from math import comb
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import session_i_rerankers as R  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import current_gold_ids, shipped_order  # noqa: E402

from marlowe_eval.datasets import longmemeval  # noqa: E402

HELDOUT_POOLS = REPO / "runs" / "session-k" / "heldout"
OUT = REPO / "runs" / "session-m0c-m" / "heldout-read.json"

# The published held-out numbers this reconstruction must reproduce before anything is believed.
PUBLISHED_R1 = 0.6725
PUBLISHED_R5 = 0.8865
MAX_SEQ = 256


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact binomial on the discordant pairs. b+c==0 -> p=1.0."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(0, k + 1)) / (2.0**n)
    return min(1.0, 2.0 * tail)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reranker", default="ms-marco-MiniLM-L-6-v2-ft-session-j")
    ap.add_argument("--depth", type=int, default=30)
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    pools, stats = load_pools(HELDOUT_POOLS)
    texts_all = turn_texts()
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_current = current_gold_ids(corpus)

    # ---- the instrument gate, on held-out ----------------------------------------------------
    base_correct, base_current, base_r5 = {}, {}, 0
    cue_orders = {}
    for qid, pool in pools.items():
        o = shipped_order(pool)
        top = int(o[0])
        base_correct[qid] = bool(pool.gold[top])
        base_current[qid] = bool(
            base_correct[qid] and pool.candidates[top].turn_id in gold_current.get(qid, frozenset())
        )
        base_r5 += int(any(pool.gold[int(i)] for i in o[:5]))
        keys = [
            (0 if c.survived_pruning else 1, -c.score, -c.margin, c.memory_id or "")
            for c in pool.candidates
        ]
        cue_orders[qid] = sorted(range(len(pool.candidates)), key=lambda i: keys[i])

    n = len(pools)
    r1 = round(sum(base_correct.values()) / n, 4)
    r5 = round(base_r5 / n, 4)
    if abs(r1 - PUBLISHED_R1) > 1e-9:
        raise SystemExit(
            f"REFUSING. Reconstructed held-out R@1 is {r1}; published is {PUBLISHED_R1}. The read "
            "would be describing a system the product does not produce -- and it would have burned "
            "the split to say nothing."
        )
    print(f"control: held-out R@1 {r1} == published {PUBLISHED_R1}   R@5 {r5} (published {PUBLISHED_R5})")
    print(f"         {n} queries, {stats['candidates']:,} candidates")
    print(f"reading: {args.reranker} @ depth {args.depth}\n")

    ce = R.load(args.reranker, provider=args.provider)

    new_correct, new_current, new_r5, ir_hits, lat = {}, {}, 0, 0, []
    for i, qid in enumerate(sorted(pools), 1):
        pool = pools[qid]
        texts = texts_all.get(qid, {})
        slate = [int(j) for j in cue_orders[qid][: args.depth]]
        docs = [texts.get(pool.candidates[j].turn_id) or "" for j in slate]
        t0 = time.perf_counter()
        logits = ce.score_batch(pool.question, docs, MAX_SEQ)
        lat.append((time.perf_counter() - t0) * 1000.0)
        order = sorted(
            range(len(slate)),
            key=lambda j: (-logits[j], pool.candidates[slate[j]].memory_id or ""),
        )
        ranked = [slate[j] for j in order]
        top = ranked[0]
        new_correct[qid] = bool(pool.gold[top])
        new_current[qid] = bool(
            new_correct[qid] and pool.candidates[top].turn_id in gold_current.get(qid, frozenset())
        )
        new_r5 += int(any(pool.gold[j] for j in ranked[:5]))
        ir_hits += int(any(pool.gold[j] for j in slate))
        if i % 50 == 0:
            print(f"  {i}/{n}  {np.median(lat):.1f} ms/query")

    # ---- the paired test ----------------------------------------------------------------------
    b = sum(1 for q in pools if base_correct[q] and not new_correct[q])  # lost
    c = sum(1 for q in pools if new_correct[q] and not base_correct[q])  # gained
    p = mcnemar_exact(b, c)

    bc = sum(1 for q in pools if base_current[q] and not new_current[q])
    cc = sum(1 for q in pools if new_current[q] and not base_current[q])
    p_cur = mcnemar_exact(bc, cc)

    new_r1 = round(sum(new_correct.values()) / n, 4)
    ir = round(ir_hits / n, 4)
    result = {
        "_what": "HELD-OUT READ -- one configuration, spent deliberately",
        "_split": "heldout",
        "_floor_status": {
            "registered_floor": 0.02,
            "fit_delta_of_this_config": 0.0174,
            "cleared": False,
            "_note": (
                "The floor was NOT cleared on fit. This read was taken at the human's explicit "
                "direction. The bar is not moved; the argument is recorded in the module docstring."
            ),
        },
        "reranker": args.reranker,
        "depth": args.depth,
        "provider": args.provider,
        "digest": ce.digest,
        "n": n,
        "baseline": {
            "R@1": r1, "R@1_current": round(sum(base_current.values()) / n, 4), "R@5": r5,
        },
        "new": {
            "R@1": new_r1, "R@1_current": round(sum(new_current.values()) / n, 4),
            "R@5": round(new_r5 / n, 4), "input_recall": ir,
            "conditional_accuracy": round(new_r1 / ir, 4) if ir else 0.0,
        },
        "delta": {
            "R@1": round(new_r1 - r1, 4),
            "R@1_current": round(sum(new_current.values()) / n - sum(base_current.values()) / n, 4),
        },
        "mcnemar_R@1": {"gained": c, "lost": b, "discordant": b + c, "p_two_sided": round(p, 6),
                        "significant_at_0.05": bool(p < 0.05)},
        "mcnemar_R@1_current": {"gained": cc, "lost": bc, "discordant": bc + cc,
                                "p_two_sided": round(p_cur, 6),
                                "significant_at_0.05": bool(p_cur < 0.05)},
        "latency_ms_per_query": {"p50": round(float(np.percentile(lat, 50)), 2),
                                 "p95": round(float(np.percentile(lat, 95)), 2)},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"\n{'':22}{'baseline':>12}{'new':>12}{'delta':>10}")
    print(f"{'R@1':22}{r1:>12.4f}{new_r1:>12.4f}{new_r1 - r1:>+10.4f}")
    print(f"{'R@1_current':22}{sum(base_current.values())/n:>12.4f}"
          f"{sum(new_current.values())/n:>12.4f}"
          f"{sum(new_current.values())/n - sum(base_current.values())/n:>+10.4f}")
    print(f"{'R@5':22}{r5:>12.4f}{new_r5/n:>12.4f}{new_r5/n - r5:>+10.4f}")
    print(f"{'input recall':22}{'0.9039':>12}{ir:>12.4f}")
    print(f"\nMcNemar R@1: gained {c}, lost {b}, discordant {b+c}, p = {p:.6f}"
          f"  {'SIGNIFICANT' if p < 0.05 else 'not significant'} at 0.05")
    print(f"latency {np.percentile(lat,50):.1f} ms p50 / {np.percentile(lat,95):.1f} ms p95")
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
