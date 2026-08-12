"""ADR-010 reach check: can a SQuAD-v2 span reader separate our head failures?

    python tools/reader_reach.py --model tinyroberta-squad2 --provider CUDAExecutionProvider

**Measurement only. Nothing ships, no Rust, no held-out read, no training.**

The question, precisely: the head probe measured that the rank-1/rank-2 decision has **26 POSITIVE**
pairs (a flip fixes), **110 NEGATIVE** (a flip breaks) and **93 AMBIGUOUS** (a flip is a no-op), so
the ceiling on ANY tie-break is **+26 cases = +0.1135 R@1** and the floor is -0.4803. Every feature
tried against that population scored between -63 and +5 net.

Does the reader do better, and does it do better WITHOUT breaking the 110?

## Three arms, because they have different ceilings and different costs

* **`swap`** — reader decides rank 1 vs rank 2 only. Ceiling +0.1135. Cheapest: 2 pairs/query.
* **`rerank`** — reader re-orders the whole depth-10 slate. Higher ceiling, because it can rescue a
  gold sitting at rank 3-10, which a swap structurally cannot. 10 pairs/query.
* **`gated`** — reader decides ONLY when the cross-encoder's head gap is below a threshold. The head
  probe found the cross-encoder is *anti-correlated* with correctness below a 0.084 gap (6 of 7
  decisive flips wrong, Fisher p = 0.000178), so a hand-off exactly there is the targeted version
  and it costs the reader almost nothing.

## The control that makes this readable

`flips_gained` alone is not a result. A rule that flips everything gains all 26 and loses all 110.
**Both numbers are reported for every arm, always**, plus the net and the R@1 delta.

The reader's own inverted sign is run as a negative control: a signal that "helps" in both
directions is measuring nothing.
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
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "reader-reach.json"
DEPTH = 10
GATE_TAU = 0.084  # the head probe's anti-correlated region


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="tinyroberta-squad2")
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    pools, _ = load_pools(FIT_POOLS)
    texts_all = turn_texts()

    orders, hits = {}, 0
    for qid, pool in pools.items():
        orders[qid] = shipped_order(pool)
        hits += int(pool.gold[orders[qid][0]])
    r1 = round(hits / len(pools), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING: reconstructed fit R@1 {r1} != published {CONTROL_R1}")
    print(f"control: fit R@1 {r1}  ({len(pools)} queries)  model={args.model} {args.provider}")

    reader = readers.load(args.model, provider=args.provider)
    smoke = readers.smoke_test(reader)
    if not smoke["pass"]:
        raise SystemExit(f"REFUSING: {args.model} fails the discrimination smoke test.")

    qids = sorted(pools)
    if args.limit:
        qids = qids[: args.limit]

    per_query, lat = {}, []
    for n, qid in enumerate(qids, 1):
        pool = pools[qid]
        texts = texts_all.get(qid, {})
        slate = [int(i) for i in orders[qid][:DEPTH]]
        t0 = time.perf_counter()
        scored = []
        for i in slate:
            txt = texts.get(pool.candidates[i].turn_id) or ""
            s = reader.score(pool.question, txt) if txt else {"score": -1e9}
            scored.append(s["score"])
        lat.append((time.perf_counter() - t0) * 1000.0)
        per_query[qid] = {
            "slate": slate,
            "reader": scored,
            "gold": [bool(pool.gold[i]) for i in slate],
            "ce": [pool.candidates[i].rerank_score for i in slate],
        }
        if n % 25 == 0:
            print(f"  {n}/{len(qids)}  {np.median(lat):.1f} ms/query median")

    # ---- arms ---------------------------------------------------------------------------------
    def evaluate(pick) -> dict:
        gained = lost = same = 0
        for qid, d in per_query.items():
            base_gold = d["gold"][0]
            j = pick(d)
            new_gold = d["gold"][j]
            if new_gold and not base_gold:
                gained += 1
            elif base_gold and not new_gold:
                lost += 1
            else:
                same += 1
        net = gained - lost
        return {
            "flips_gained": gained,
            "flips_lost": lost,
            "unchanged": same,
            "net_cases": net,
            "net_r1_delta": round(net / len(per_query), 4),
            "new_r1": round((sum(1 for d in per_query.values() if d["gold"][pick(d)])) / len(per_query), 4),
        }

    def swap(d, sign=1):
        return 0 if sign * d["reader"][0] >= sign * d["reader"][1] else 1

    def rerank(d, sign=1):
        return int(np.argmax([sign * s for s in d["reader"]]))

    def gated(d, sign=1):
        ce = d["ce"]
        if ce[0] is None or ce[1] is None or (ce[0] - ce[1]) > GATE_TAU:
            return 0
        return swap(d, sign)

    arms = {
        "swap": evaluate(swap),
        "rerank": evaluate(rerank),
        f"gated_tau_{GATE_TAU}": evaluate(gated),
        "swap_INVERTED_control": evaluate(lambda d: swap(d, -1)),
        "rerank_INVERTED_control": evaluate(lambda d: rerank(d, -1)),
    }

    result = {
        "_what": "ADR-010 reach check for a SQuAD-v2 span reader on the shipped depth-10 slate",
        "_split": "fit",
        "_measurement_only": True,
        "model": args.model,
        "provider": args.provider,
        "digest": reader.digest,
        "smoke": smoke,
        "control_fit_r1": r1,
        "head_probe_ceiling": {
            "positives": 26, "negatives": 110, "ambiguous": 93,
            "max_r1_delta_any_tiebreak": 0.1135,
        },
        "latency_ms_per_query_depth10": {
            "p50": round(float(np.percentile(lat, 50)), 2),
            "p95": round(float(np.percentile(lat, 95)), 2),
        },
        "arms": arms,
        "per_query": per_query,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"\n{'arm':<28}{'gained':>8}{'lost':>7}{'net':>6}{'dR@1':>9}{'R@1':>9}")
    for k, v in arms.items():
        print(f"{k:<28}{v['flips_gained']:>8}{v['flips_lost']:>7}{v['net_cases']:>6}"
              f"{v['net_r1_delta']:>9.4f}{v['new_r1']:>9.4f}")
    print(f"\nbaseline R@1 {r1}   reader {np.percentile(lat,50):.0f} ms/query at depth 10")
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
