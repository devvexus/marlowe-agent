"""Forensics on the stage-5 population: the held-out cases where gold survives narrowing yet
lands outside the fused top-3. For each: why did the pair miss it, did the reader see it, how
long is the turn, where does the answer sit?

DIAGNOSTIC -- fits nothing, selects nothing. Its output decides which next mechanism is aimed
at reality rather than intuition.

    python tools/pick_forensics.py --run runs/session-m0c-n/cascade-heldout-cuda-v2/heldout
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import readers  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    args = ap.parse_args()

    pools, _ = load_pools(args.run)
    texts = turn_texts()
    reader = readers.load("mobilebert-uncased-squad-v2", provider="CUDAExecutionProvider")

    print(f"{'query':10} {'fused':>5} {'best':>5} {'L2r':>4} {'L6r':>6} {'rdScore':>8} "
          f"{'words':>5} {'ans@':>5}")
    n = 0
    for q, p in pools.items():
        cur = sorted((i for i, c in enumerate(p.candidates) if c.fusion_rank is not None),
                     key=lambda i: p.candidates[i].fusion_rank)
        g = [bool(c.is_gold) for c in p.candidates]
        golds = [i for i in cur if g[i]]
        if not golds:
            continue
        fused_rank = min(cur.index(i) + 1 for i in golds)
        if fused_rank <= 3:
            continue
        n += 1
        # best (lowest) L-2/L-6 rank among the gold candidates within the slate
        l2 = sorted((i for i, c in enumerate(p.candidates) if c.rerank_score is not None),
                    key=lambda i: (-p.candidates[i].rerank_score, i))
        gi = golds[0]
        d = texts.get(q, {}).get(p.candidates[gi].turn_id) or ""
        rd = reader.score(p.question, d)["score"]
        words = len(d.split())
        # where in the turn does the corpus's answer string sit?
        ans = ""
        try:
            import json, io
            if not main._corpus:
                split = (REPO / "tools" / "split.json").read_text(encoding="utf-8")
                raw = json.loads(io.open(REPO / json.loads(split)["corpus_path"],
                                         encoding="utf-8").read())
                main._corpus = {inst["query_id"]: inst for inst in raw}
            inst = main._corpus.get(q)
            if inst:
                ans = str(inst.get("answer", ""))
        except Exception:
            pass
        pos = (d.lower().find(ans.lower()) / max(len(d), 1)) if ans else -1.0
        print(f"{q:10} {fused_rank:>5} {min(l2.index(i)+1 for i in golds):>5} "
              f"{l2.index(gi)+1:>4} {p.candidates[gi].fusion_rank+1 if p.candidates[gi].fusion_rank is not None else -1:>6} "
              f"{rd:>8.2f} {words:>5} {pos:>5.2f}")
    print(f"\nstage-5 population: {n} queries")
    return 0


main._corpus = None

if __name__ == "__main__":
    raise SystemExit(main())
