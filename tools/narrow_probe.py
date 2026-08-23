"""Probe 1: does a better 30->10 cut recover gold without paying more in distractors?

Pre-registered in runs/session-m0c-n/PREREGISTRATION-NARROWING.json. Reads the fit cascade dump
(pure L-2 logits since the write-back fix), reconstructs the pipeline offline, and evaluates the
two registered arms:

    PRIMARY   union narrow : (L-2 top-10 of slate) U (cue top-10 of slate), fuse RRF over union
    SECONDARY rrf narrow   : slate re-cut to exactly 10 by RRF(L2-rank, cue-rank), stage 2 as-is

INSTRUMENT GATE FIRST: re-scoring the CURRENT narrowed tens with L-6 must reproduce the binary's
fusion order on every fit query, or everything below is refused.

    python tools/narrow_probe.py --run runs/session-m0c-n/cascade-fit-cuda-v2/fit --provider cuda
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import session_i_rerankers as R  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402

L6 = "ms-marco-MiniLM-L-6-v2-ft-session-j"
MAX_SEQ, RRF_K = 256, 60.0
NARROW = 10


def cue_order(p) -> list[int]:
    idx = [i for i, c in enumerate(p.candidates) if c.rerank_score is not None]
    return sorted(idx, key=lambda i: ((not p.candidates[i].survived_pruning),
                                      -p.candidates[i].score, -p.candidates[i].margin, i))


def l2_order(p) -> list[int]:
    idx = [i for i, c in enumerate(p.candidates) if c.rerank_score is not None]
    return sorted(idx, key=lambda i: (-p.candidates[i].rerank_score, i))


def fuse(order_pairs: dict[int, list[int]]) -> list[int]:
    """RRF over the ranking lists in `order_pairs`; returns candidates fused-descending."""
    members = set(order_pairs[next(iter(order_pairs))])
    def key(i):
        s = sum(1.0 / (RRF_K + ranks.index(i) + 1) for ranks in order_pairs.values())
        return (-s, i)
    return sorted(members, key=key)


def evaluate(name: str, orders: dict[str, list[int]], gold: dict[str, list[bool]],
             base: dict[str, tuple[int, int]] | None) -> dict:
    r1 = r3 = postnarrow = 0
    gained3 = lost3 = 0
    sizes = []
    for q in orders:
        g = gold[q]
        order = orders[q]
        postnarrow += any(g[i] for i in order)
        rank = next((r for r, i in enumerate(order, 1) if g[i]), None)
        hit1 = rank == 1
        hit3 = rank is not None and rank <= 3
        r1 += hit1
        r3 += hit3
        if base:
            b1, b3 = base[q]
            gained3 += (hit3 and not b3)
            lost3 += (b3 and not hit3)
        sizes.append(len(order))
    n = len(orders)
    line = (f"{name:24} R@1 {r1}/{n} = {r1/n:.4f}   R@3 {r3}/{n} = {r3/n:.4f}   "
            f"post-narrow {postnarrow}/{n} = {postnarrow/n:.4f}   mean-set {sum(sizes)/n:.1f}")
    if base:
        line += f"   R@3 gained {gained3} lost {lost3}"
    print(line)
    return {"name": name, "R@1": r1, "R@3": r3, "post_narrow": postnarrow,
            "gained3": gained3, "lost3": lost3, "mean_set": sum(sizes)/n}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--out", type=Path, default=REPO / "runs/session-m0c-n/narrow-probe.json")
    args = ap.parse_args()

    pools, _ = load_pools(args.run)
    texts = turn_texts()
    ce6 = R.load(L6, provider=args.provider)
    if not R.smoke_test(ce6).get("pass"):
        raise SystemExit("REFUSING: L-6 smoke test failed.")

    gold = {q: [bool(c.is_gold) for c in p.candidates] for q, p in pools.items()}

    # ── instrument gate: reproduce the binary's fusion order on the CURRENT narrowed tens ──
    mismatched = 0
    for q, p in pools.items():
        cur = sorted((i for i, c in enumerate(p.candidates) if c.fusion_rank is not None),
                     key=lambda i: p.candidates[i].fusion_rank)
        docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in cur]
        s6 = ce6.score_batch(p.question, docs, MAX_SEQ)
        s6_by = dict(zip(cur, s6))
        by_l2 = l2_order(p)
        r2_list = [i for i in by_l2 if i in s6_by]      # L-2 LOGIT order, restricted to the ten
        r6_list = sorted(cur, key=lambda i: (-s6_by[i], i))
        mine = fuse({"l2": r2_list, "l6": r6_list})
        if mine != cur:
            mismatched += 1
    print(f"instrument gate: fusion order reproduced on {len(pools) - mismatched}/{len(pools)} "
          f"fit queries")
    if mismatched:
        raise SystemExit("REFUSING. The offline reconstruction is not the binary; fix first.")

    # baseline from the binary's own columns
    base_orders, base_hits = {}, {}
    for q, p in pools.items():
        cur = sorted((i for i, c in enumerate(p.candidates) if c.fusion_rank is not None),
                     key=lambda i: p.candidates[i].fusion_rank)
        base_orders[q] = cur
        rank = next((r for r, i in enumerate(cur, 1) if gold[q][i]), None)
        base_hits[q] = (rank == 1, rank is not None and rank <= 3)
    results = [evaluate("BASELINE (binary)", base_orders, gold, None)]

    # ── PRIMARY: union narrow ──
    union_orders = {}
    cache6: dict[str, dict[int, float]] = {}
    for q, p in pools.items():
        u = sorted(set(l2_order(p)[:NARROW]) | set(cue_order(p)[:NARROW]))
        docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in u]
        s6 = dict(zip(u, ce6.score_batch(p.question, docs, MAX_SEQ)))
        cache6[q] = s6
        r2 = {i: r for r, i in enumerate(l2_order(p)) if i in s6}
        r6 = {i: r for r, i in enumerate(sorted(u, key=lambda i: (-s6[i], i)))}
        union_orders[q] = fuse({"l2": sorted(r2, key=r2.get), "l6": sorted(r6, key=r6.get)})
    results.append(evaluate("PRIMARY union narrow", union_orders, gold, base_hits))

    # ── SECONDARY: rrf narrow (width fixed at 10) ──
    rrf_orders = {}
    for q, p in pools.items():
        by_l2, by_cue = l2_order(p), cue_order(p)
        def rrf_key(i):
            s = (1.0/(RRF_K + by_l2.index(i) + 1) + 1.0/(RRF_K + by_cue.index(i) + 1))
            return (-s, i)
        cut = sorted(by_l2, key=rrf_key)[:NARROW]
        s6 = {i: cache6[q][i] for i in cut if i in cache6[q]}
        missing = [i for i in cut if i not in s6]
        if missing:
            docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in missing]
            for i, v in zip(missing, ce6.score_batch(p.question, docs, MAX_SEQ)):
                s6[i] = v
        r6 = {i: r for r, i in enumerate(sorted(cut, key=lambda i: (-s6[i], i)))}
        rrf_orders[q] = fuse({"l2": [i for i in by_l2 if i in set(cut)],
                              "l6": sorted(r6, key=r6.get)})
    results.append(evaluate("SECONDARY rrf narrow", rrf_orders, gold, base_hits))

    args.out.write_text(json.dumps(
        {"_what": "Probe 1 evaluation", "prereg": "PREREGISTRATION-NARROWING.json",
         "instrument_gate_mismatches": mismatched, "arms": results}, indent=2) + "\n",
        encoding="utf-8")
    print(f"wrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
