"""Where does gold die in the cascade? A per-stage census over one run's dump.

DIAGNOSTIC, not an arm evaluation: it reads dumps that already exist, fits nothing, selects
nothing, and has no authority over design. Its job is to say WHICH stage loses each case so the
next pre-registration aims at a measured weakness instead of an intuited one.

    python tools/narrow_census.py --run runs/session-m0c-n/cascade-fit-cuda/fit
    python tools/narrow_census.py --run runs/session-m0c-n/cascade-heldout-cuda/heldout
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from reach_pools import load_pools  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    args = ap.parse_args()

    pools, _ = load_pools(args.run)
    n = len(pools)
    slate = after_narrow = r3 = r1 = 0
    lost_at_narrow = []
    for q, p in pools.items():
        gold = [bool(c.is_gold) for c in p.candidates]
        idx_slate = [i for i, c in enumerate(p.candidates) if c.rerank_score is not None]
        g_slate = [i for i in idx_slate if gold[i]]
        if not g_slate:
            continue
        slate += 1
        idx_narrow = [i for i, c in enumerate(p.candidates) if c.fusion_rank is not None]
        if not any(gold[i] for i in idx_narrow):
            by_l2 = sorted(idx_slate, key=lambda i: (-p.candidates[i].rerank_score, i))
            best_gold_rank_in_slate = min(by_l2.index(i) for i in g_slate) + 1
            best_gold_logit = max(p.candidates[i].rerank_score for i in g_slate)
            cut_logit = p.candidates[by_l2[9]].rerank_score
            lost_at_narrow.append((q, best_gold_rank_in_slate, best_gold_logit, cut_logit))
            continue
        after_narrow += 1
        order = sorted(idx_narrow, key=lambda i: p.candidates[i].fusion_rank)
        grank = next((r for r, i in enumerate(order, 1) if gold[i]), None)
        if grank is not None and grank <= 3:
            r3 += 1
            if grank == 1:
                r1 += 1

    print(f"{args.run.name}: n={n}")
    print(f"  gold reaches the 30-slate : {slate}/{n} = {slate/n:.4f}")
    print(f"  survives narrowing (10)   : {after_narrow}/{slate} = {after_narrow/slate:.4f}"
          f"   ({slate - after_narrow} cases lost HERE)")
    print(f"  fused into top-3          : {r3}/{after_narrow} = {r3/after_narrow:.4f}"
          f"   ({after_narrow - r3} cases lost here)")
    print(f"  fused rank-1              : {r1}/{after_narrow} = {r1/after_narrow:.4f}")
    if lost_at_narrow:
        print(f"\n  cases lost AT the narrowing (gold's slate-rank by L-2 logit | logits):")
        for q, rk_, gl, cut in lost_at_narrow:
            print(f"    {q}: gold at slate-rank {rk_}, logit {gl:.3f} vs cut {cut:.3f} "
                  f"(gap {-cut + gl:+.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
