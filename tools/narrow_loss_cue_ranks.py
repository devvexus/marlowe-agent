"""For each narrowing loss: where does the buried gold rank under the CUE key within its slate?

Decides the shape of the narrowing probe without committing to an arm: if the lost golds are
cue-strong, a fusion narrow (L-2 x cue RRF, width fixed at 10) can carry them in; if they are
cue-weak too, no re-cut of the same 30 recovers them and the honest answer is a wider fuse set
(a knob) or nothing.

    python tools/narrow_loss_cue_ranks.py --run runs/session-m0c-n/cascade-heldout-cuda-v2/heldout
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
    print(f"{'query':10} {'L2-rank':>7} {'cue-rank':>8} {'slate':>5}   fused-in-by-union?")
    for q, p in pools.items():
        gold = [bool(c.is_gold) for c in p.candidates]
        idx_slate = [i for i, c in enumerate(p.candidates) if c.rerank_score is not None]
        g_slate = [i for i in idx_slate if gold[i]]
        idx_narrow = [i for i, c in enumerate(p.candidates) if c.fusion_rank is not None]
        if not g_slate or any(gold[i] for i in idx_narrow):
            continue
        by_l2 = sorted(idx_slate, key=lambda i: (-p.candidates[i].rerank_score, i))
        # The cue key INSIDE the slate: survivors-first, z desc, margin desc, id asc -- the draw
        # order itself, which is how the binary built the slate before truncating to 30.
        by_cue = sorted(idx_slate,
                        key=lambda i: ((not p.candidates[i].survived_pruning),
                                       -p.candidates[i].score, -p.candidates[i].margin, i))
        l2_rank = min(by_l2.index(i) for i in g_slate) + 1
        cue_rank = min(by_cue.index(i) for i in g_slate) + 1
        # Would a plain UNION of both top-10s have carried the gold?
        union_in = l2_rank <= 10 or cue_rank <= 10
        print(f"{q:10} {l2_rank:>7} {cue_rank:>8} {len(idx_slate):>5}   "
              f"{'YES' if union_in else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
