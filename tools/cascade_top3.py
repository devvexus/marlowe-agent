"""Cascade: deep slate for recall, cross-encoder narrows it, a SECOND model picks the top 3.

    PYTHONIOENCODING=utf-8 python tools/cascade_top3.py

## The idea, and why it is not the arms already measured

R@3 = input_recall x cond@3, and the two fight: depth 10 gives ir 0.9214 with cond@3 0.9763;
depth 20 gives ir 0.9738 with cond@3 0.9507; depth 30 gives ir 0.9825 with cond@3 0.9422. Every
extra slot is another distractor, so `cond@3` decays as the slate grows.

But `cond@10` does NOT decay the same way. At depth 30, gold is in L-2's **top 10 of 30** for
0.9782 of queries -- a retention of 0.9956 over the slate's 0.9825. **So the cross-encoder is
excellent at narrowing and only mediocre at the final pick.**

That yields a ten-candidate set with recall **0.9782**, against the cue slate's **0.9214**, at the
same final width. If a second ranker picks the top 3 out of that narrowed ten as well as any ranker
picks 3 out of a ten-wide cue slate (cond@3 0.9763), R@3 would be 0.9782 x 0.9763 = **0.9549**.

**Cascading with the SAME model is a no-op** -- top 3 of L-2's top 10 of 30 is exactly top 3 of 30,
which is the already-measured 0.9258. So stage 2 must be a different ranker. That is what is tested.

**The reason it may fail, stated before the run.** The narrowed ten are the ten the first model
scored HIGHEST, so they are the hardest possible distractors -- selected for looking relevant. That
is exactly why the RRF slate's `cond@3` fell (0.9763 -> 0.9539) when it admitted candidates two cues
agreed on. If `cond@3` over the narrowed ten drops below 0.9464, the cascade loses to depth 20.

## Arms, all at slate depth 30, narrowed to 10 by L-2

    control      L-2 top-3 of 30                      (already measured: R@3 0.9258)
    cascade-L6   L-6 ranks the narrowed 10, top 3
    cascade-rrf  RRF(L-2, L-6) over the narrowed 10
    cascade-sum  z-normalised score sum over the narrowed 10

`cascade-sum` is included because RRF discards score magnitude, and at a three-wide cut the margin
between candidates 3 and 4 is exactly the information RRF throws away. z-normalisation is per query
over the ten, which is a within-query monotone transform of each model's own scores and therefore
does not violate ADR-010/ADR-011 -- it changes the FUSION, not either ranker's own order.

RRF k = 60 (Cormack's published default), fixed before any number exists. Nothing else is tuned.

## Gates

1. L-2 at depth 10 reproduces fit R@1 = 0.7555 exactly.
2. The depth-10 cue slate equals the set the binary actually reranked, read from the dump.
3. Both graphs pass their smoke tests; digests pinned by `session_i_rerankers`.
4. `control` reproduces the depth-30 R@3 of 0.9258 already measured by `tools/rk_by_depth.py`.
5. Narrowing retention (gold in L-2's top 10 of 30) is reported, not assumed.

**Fit split only. Held-out is not opened.**
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import session_i_rerankers as R  # noqa: E402
from correct_case_control import cue_only_order  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "cascade-top3.json"
L2 = "ms-marco-MiniLM-L-2-v2-ft-session-j"
L6 = "ms-marco-MiniLM-L-6-v2-ft-session-j"
MAX_SEQ, RRF_K, SLATE, NARROW = 256, 60, 30, 10
D30_R3_PUBLISHED = 0.9258  # runs/session-m0c-m/rk-by-depth.json, depth 30


def z(xs):
    if len(xs) < 2:
        return [0.0] * len(xs)
    m, s = st.mean(xs), st.pstdev(xs)
    return [(x - m) / s if s else 0.0 for x in xs]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--provider", default="CPUExecutionProvider")
    args = ap.parse_args()

    pools, stats = load_pools(FIT_POOLS)
    texts = turn_texts()
    n = len(pools)
    print(f"fit pools: {stats['pools']} queries  slate {SLATE} -> narrow {NARROW} -> top 3")

    ship = {q: shipped_order(p) for q, p in pools.items()}
    r1 = round(sum(int(p.gold[int(ship[q][0])]) for q, p in pools.items()) / n, 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING (GATE 1). fit R@1 {r1}; published {CONTROL_R1}.")
    cue = {q: [int(v) for v in cue_only_order(p)] for q, p in pools.items()}
    exact = sum(set(cue[q][:10]) == {i for i, c in enumerate(p.candidates)
                                     if c.rerank_score is not None} for q, p in pools.items())
    if exact != n:
        raise SystemExit(f"REFUSING (GATE 2). cue slate != reranked set on {n - exact}.")
    print(f"GATE 1  fit R@1 {r1} == {CONTROL_R1}   GATE 2  slate {exact}/{n} exact")

    ce2 = R.load(L2, provider=args.provider)
    ce6 = R.load(L6, provider=args.provider)
    for m, ce in ((L2, ce2), (L6, ce6)):
        if not R.smoke_test(ce).get("pass"):
            raise SystemExit(f"REFUSING (GATE 3). {m} failed its smoke test.")
    print(f"GATE 3  both graphs smoke PASS ({ce2.params_m}M, {ce6.params_m}M)")

    slate = {q: cue[q][:SLATE] for q in pools}
    ir = sum(any(p.gold[i] for i in slate[q]) for q, p in pools.items()) / n

    s2, narrowed = {}, {}
    for q, p in pools.items():
        docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in slate[q]]
        sc = ce2.score_batch(p.question, docs, MAX_SEQ)
        s2[q] = dict(zip(slate[q], sc))
        narrowed[q] = [i for _, i in sorted(zip(sc, slate[q]), key=lambda t: (-t[0], t[1]))][:NARROW]

    narrow_ret = sum(any(p.gold[i] for i in narrowed[q]) for q, p in pools.items()) / n
    in_slate = [q for q, p in pools.items() if any(p.gold[i] for i in slate[q])]
    print(f"\n  slate ir@{SLATE} {ir:.4f}   after L-2 narrows to {NARROW}: {narrow_ret:.4f}   "
          f"narrowing retention {narrow_ret / ir:.4f}")

    s6 = {}
    for q, p in pools.items():
        docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in narrowed[q]]
        s6[q] = dict(zip(narrowed[q], ce6.score_batch(p.question, docs, MAX_SEQ)))

    def order_from(q, key):
        return sorted(narrowed[q], key=lambda i: (-key(q, i), i))

    r2 = {q: {i: r for r, i in enumerate(narrowed[q])} for q in pools}
    r6 = {q: {i: r for r, i in enumerate(sorted(narrowed[q], key=lambda i: (-s6[q][i], i)))}
          for q in pools}
    zz = {}
    for q in pools:
        a = dict(zip(narrowed[q], z([s2[q][i] for i in narrowed[q]])))
        b = dict(zip(narrowed[q], z([s6[q][i] for i in narrowed[q]])))
        zz[q] = {i: a[i] + b[i] for i in narrowed[q]}

    arms = {
        "control  L-2 top-3 of 30": {q: sorted(slate[q], key=lambda i: (-s2[q][i], i)) for q in pools},
        "cascade-L6": {q: order_from(q, lambda q, i: s6[q][i]) for q in pools},
        "cascade-rrf": {q: sorted(narrowed[q], key=lambda i: (
            -(1.0 / (RRF_K + r2[q][i]) + 1.0 / (RRF_K + r6[q][i])), i)) for q in pools},
        "cascade-sum": {q: order_from(q, lambda q, i: zz[q][i]) for q in pools},
    }

    print("\n" + "=" * 96)
    print("CASCADE -- R@3 and cond@3, cond@3 measured over the queries whose gold reached the slate")
    print("=" * 96)
    print(f"  {'arm':28s} {'R@1':>8} {'R@2':>8} {'R@3':>8}   {'cond@3':>8}   {'vs d20':>8}")
    cells, base = {}, 0.9258
    for name, o in arms.items():
        rk = {}
        for q, p in pools.items():
            rk[q] = next((r for r, v in enumerate(o[q], 1) if p.gold[int(v)]), 10 ** 6)
        v = {k: sum(1 for r in rk.values() if r <= k) / n for k in (1, 2, 3)}
        c3 = sum(1 for q in in_slate if rk[q] <= 3) / len(in_slate)
        cells[name] = {**{f"R@{k}": round(x, 4) for k, x in v.items()},
                       "conditional_top3": round(c3, 4)}
        print(f"  {name:28s} {v[1]:>8.4f} {v[2]:>8.4f} {v[3]:>8.4f}   {c3:>8.4f}   "
              f"{v[3] - base:>+8.4f}")

    ctl = cells["control  L-2 top-3 of 30"]["R@3"]
    if abs(ctl - D30_R3_PUBLISHED) > 1e-4:
        raise SystemExit(f"REFUSING (GATE 4). control R@3 {ctl} != rk-by-depth's {D30_R3_PUBLISHED}.")
    print(f"\n  GATE 4  control reproduces rk-by-depth.json's depth-30 R@3 {D30_R3_PUBLISHED}: True")
    best = max(cells, key=lambda k: cells[k]["R@3"])
    print(f"  best: {best}  R@3 {cells[best]['R@3']:.4f}  "
          f"(depth-20 baseline 0.9258, depth-10 shipped 0.8996)")

    art = {"_what": "cascade: depth-30 slate, L-2 narrows to 10, a second ranker picks the top 3",
           "_split": "fit", "_rrf_k": RRF_K, "_slate": SLATE, "_narrow": NARROW,
           "input_recall": round(ir, 4), "after_narrowing": round(narrow_ret, 4),
           "narrowing_retention": round(narrow_ret / ir, 4),
           "_gates": {"fit_R@1": r1, "slate_exact": exact, "control_R@3": ctl},
           "cells": cells}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(art, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
