"""Diff the wired binary's fused top-3 against the offline half-weight arm, per query.

Identifies WHICH queries disagree and how close the fused scores were -- distinguishing
sub-resolution logit noise from an algebra error.

    python tools/reader_wiring_diff.py --run runs/session-m0c-n/cascade-reader-heldout/heldout
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from reach_pools import load_pools, turn_texts  # noqa: E402

import argparse

RRF_K = 60.0
W = 0.5

ap = argparse.ArgumentParser()
ap.add_argument("--run", type=Path, required=True)
args = ap.parse_args()
run = args.run
pools, _ = load_pools(run)
TEXTS = turn_texts()

# Offline arm recomputed here from the SAME dump's primary logits (pure L-2 since the fix)
# plus freshly scored L-6/reader logits via the loaders -- identical to pick_probe w=0.5.
import readers  # noqa: E402
import session_i_rerankers as R  # noqa: E402

enc6 = R.load("ms-marco-MiniLM-L-6-v2-ft-session-j", provider="CUDAExecutionProvider")
reader = readers.load("mobilebert-uncased-squad-v2", provider="CUDAExecutionProvider")

discordant = 0
for q, p in sorted(pools.items()):
    cur = [i for i, c in enumerate(p.candidates) if c.fusion_rank is not None]
    # primary ranks from the dump (pure L-2 logits)
    l2 = {i: p.candidates[i].rerank_score for i in cur}
    docs = [TEXTS.get(q, {}).get(p.candidates[i].turn_id) or "" for i in cur]
    s6 = dict(zip(cur, enc6.score_batch(p.question, docs, 256)))
    ra = {i: reader.score(p.question, d)["score"] for i, d in zip(cur, docs)}

    def fuse(s2map):
        r2 = {i: sorted(cur, key=lambda j: (-s2map[j], j)).index(i) for i in cur}
        r6 = {i: sorted(cur, key=lambda j: (-s6[j], j)).index(i) for i in cur}
        rr = {i: sorted(cur, key=lambda j: (-ra[j], j)).index(i) for i in cur}
        return sorted(cur, key=lambda i: (
            -(1/(RRF_K+r2[i]) + 1/(RRF_K+r6[i]) + W/(RRF_K+rr[i]+1)), i))

    mine_top3 = set(fuse(l2)[:3])
    binary_order = sorted(cur, key=lambda i: p.candidates[i].fusion_rank)
    bin_top3 = set(binary_order[:3])
    if mine_top3 != bin_top3:
        discordant += 1
        g = [bool(c.is_gold) for c in p.candidates]
        print(f"{q}: offline top3 {sorted(mine_top3)} vs binary {sorted(bin_top3)}  "
              f"gold_in_offline={any(g[i] for i in mine_top3)} "
              f"gold_in_binary={any(g[i] for i in bin_top3)}")
print(f"\ndiscordant top-3 sets: {discordant}/{len(pools)}")
