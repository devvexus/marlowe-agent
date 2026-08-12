"""The combined measurement: L-6-ft @ depth 30, PLUS the gated span reader on top.

    python tools/combined_reach.py

Measured separately on fit, each against the 0.7555 baseline:

    L-6-ft @ depth 30            0.7729   (+0.0174, 4 cases)
    roberta-base gated reader    0.7817   (+0.0262, 6 cases)   [on the L-2-ft depth-10 ranking]

Adding those gives +10 cases and 0.7991. **This script exists because that addition is not a
measurement.** L-6 at depth 30 changes the ranking, which changes which queries have a small
cross-encoder gap, which changes what the reader gate fires on at all. The mechanisms could be
additive, overlapping, or interfering, and only running them together says which.

Session G already produced the cautionary case: two arms worth +5 and +21 combined to +4.

## THE THRESHOLD DOES NOT TRANSFER, AND THAT IS THE POINT OF THE SWEEP

tau = 0.084 was selected on the head probe of the **L-2-ft depth-10** ranking, in **L-2-ft's logit
units**. L-6-ft is a different graph with a different logit scale and a different gap distribution.
Carrying 0.084 across that boundary is precisely the "a measurement is scoped to the system it was
taken on" error this project keeps a ledger of.

So tau is SWEPT here and the whole curve is reported. A single number at one inherited tau would be
a plausible figure about the wrong system.

## Cost

The reader is scored on the top 2 of every query unconditionally (458 pairs) so the sweep can be
done offline. **In deployment it would only fire below the threshold**, so the shipped cost is a
fraction of what this script pays.
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

import readers  # noqa: E402
import session_i_rerankers as R  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "combined-reach.json"
RERANKER = "ms-marco-MiniLM-L-6-v2-ft-session-j"
READER = "roberta-base-squad2"
DEPTH = 30
MAX_SEQ = 256


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reranker", default=RERANKER)
    ap.add_argument("--reader", default=READER)
    ap.add_argument("--depth", type=int, default=DEPTH)
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    pools, _ = load_pools(FIT_POOLS)
    texts_all = turn_texts()

    # Instrument gate: the shipped reconstruction must reproduce the published fit R@1.
    base_orders, hits = {}, 0
    for qid, pool in pools.items():
        base_orders[qid] = shipped_order(pool)
        hits += int(pool.gold[base_orders[qid][0]])
    r1 = round(hits / len(pools), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING: reconstructed fit R@1 {r1} != published {CONTROL_R1}")
    print(f"control: shipped fit R@1 {r1}  ({len(pools)} queries)")

    # The cue-only order: what the slate is drawn on, before any cross-encoder. Same key the
    # shipped path uses at level 1/3/4/5, with the rerank level absent.
    cue_orders = {}
    for qid, pool in pools.items():
        keys = [
            (0 if c.survived_pruning else 1, -c.score, -c.margin, c.memory_id or "")
            for c in pool.candidates
        ]
        cue_orders[qid] = sorted(range(len(pool.candidates)), key=lambda i: keys[i])

    ce = R.load(args.reranker, provider=args.provider)
    rd = readers.load(args.reader, provider=args.provider)
    if not readers.smoke_test(rd)["pass"]:
        raise SystemExit(f"REFUSING: {args.reader} fails the discrimination smoke test.")
    print(f"reranker {args.reranker} @ depth {args.depth}   reader {args.reader}")

    rows, ce_ms, rd_ms = {}, [], []
    for n, qid in enumerate(sorted(pools), 1):
        pool = pools[qid]
        texts = texts_all.get(qid, {})
        slate = [int(i) for i in cue_orders[qid][: args.depth]]
        docs = [texts.get(pool.candidates[i].turn_id) or "" for i in slate]

        t0 = time.perf_counter()
        logits = ce.score_batch(pool.question, docs, MAX_SEQ)
        ce_ms.append((time.perf_counter() - t0) * 1000.0)

        # Tiebreak on memory_id ascending, matching `retrieve.rs`'s final level.
        order = sorted(
            range(len(slate)),
            key=lambda j: (-logits[j], pool.candidates[slate[j]].memory_id or ""),
        )
        top1, top2 = slate[order[0]], slate[order[1]]
        gap = float(logits[order[0]] - logits[order[1]])

        # Reader on the top 2, unconditionally, so tau can be swept offline.
        t0 = time.perf_counter()
        s1 = rd.score(pool.question, texts.get(pool.candidates[top1].turn_id) or "")["score"]
        s2 = rd.score(pool.question, texts.get(pool.candidates[top2].turn_id) or "")["score"]
        rd_ms.append((time.perf_counter() - t0) * 1000.0)

        rows[qid] = {
            "gold_top1": bool(pool.gold[top1]),
            "gold_top2": bool(pool.gold[top2]),
            "ce_gap": gap,
            "reader_top1": s1,
            "reader_top2": s2,
        }
        if n % 40 == 0:
            print(f"  {n}/{len(pools)}  ce {np.median(ce_ms):.1f} ms  reader {np.median(rd_ms):.1f} ms")

    n = len(rows)
    rerank_only = sum(1 for d in rows.values() if d["gold_top1"]) / n
    print(f"\nL-6-ft @ depth {args.depth} alone: R@1 {rerank_only:.4f}")

    # ---- tau sweep ----------------------------------------------------------------------------
    gaps = sorted({round(d["ce_gap"], 4) for d in rows.values()})
    taus = [0.0, 0.02, 0.05, 0.084, 0.12, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 1e9]
    curve = []
    for tau in taus:
        gained = lost = fired = 0
        for d in rows.values():
            if d["ce_gap"] >= tau:
                continue
            fired += 1
            swap = d["reader_top2"] > d["reader_top1"]
            if not swap:
                continue
            if d["gold_top2"] and not d["gold_top1"]:
                gained += 1
            elif d["gold_top1"] and not d["gold_top2"]:
                lost += 1
        net = gained - lost
        curve.append({
            "tau": tau,
            "queries_gate_fired": fired,
            "flips_gained": gained,
            "flips_lost": lost,
            "net_cases": net,
            "r1": round(rerank_only + net / n, 4),
            "delta_vs_shipped": round(rerank_only + net / n - CONTROL_R1, 4),
        })

    best = max(curve, key=lambda c: c["net_cases"])
    result = {
        "_what": "L-6-ft @ depth 30 PLUS a gated span reader, measured together on fit",
        "_split": "fit",
        "_measurement_only": True,
        "reranker": args.reranker,
        "reader": args.reader,
        "depth": args.depth,
        "provider": args.provider,
        "shipped_baseline_r1": CONTROL_R1,
        "reranker_only_r1": round(rerank_only, 4),
        "tau_sweep": curve,
        "best_cell": best,
        "_tau_caveat": (
            "tau 0.084 was selected on the L-2-ft depth-10 head probe, in L-2-ft's logit units. "
            "L-6-ft is a different graph with a different gap distribution, so the whole curve is "
            "reported and no single inherited tau is quoted as the result."
        ),
        "latency_ms_per_query": {
            "reranker_depth30_p50": round(float(np.percentile(ce_ms, 50)), 2),
            "reader_top2_p50": round(float(np.percentile(rd_ms, 50)), 2),
            "_note": "the reader is scored unconditionally here; in deployment it fires only below tau",
        },
        "gap_distribution": {
            "p10": round(float(np.percentile([d["ce_gap"] for d in rows.values()], 10)), 4),
            "p50": round(float(np.percentile([d["ce_gap"] for d in rows.values()], 50)), 4),
            "p90": round(float(np.percentile([d["ce_gap"] for d in rows.values()], 90)), 4),
        },
        "per_query": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"\n{'tau':>8}{'fired':>8}{'gain':>6}{'lost':>6}{'net':>6}{'R@1':>9}{'vs ship':>10}")
    for c in curve:
        t = "inf" if c["tau"] > 1e8 else f"{c['tau']:.3f}"
        print(f"{t:>8}{c['queries_gate_fired']:>8}{c['flips_gained']:>6}{c['flips_lost']:>6}"
              f"{c['net_cases']:>6}{c['r1']:>9.4f}{c['delta_vs_shipped']:>+10.4f}")
    print(f"\nshipped {CONTROL_R1}   reranker-only {rerank_only:.4f}   best combined {best['r1']:.4f}")
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
