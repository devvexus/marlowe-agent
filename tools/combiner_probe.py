"""Probe 2: can a training-free vote across the six pinned graphs capture part of the
union-oracle's cond@3 headroom that RRF leaves on the table?

Pre-registered in runs/session-m0c-n/PREREGISTRATION-COMBINER.json. Scores all six members on
the CURRENT narrowed tens, then evaluates:

    PRIMARY    six_vote_top3 : score = #graphs placing you in their top-3; ties by six-way RRF
    SECONDARY  six_zsum      : per-query z-normalised logit sum across the six

Instrument gate: the freshly-scored PAIR cascade must reproduce the binary's fusion order on
every fit query before any arm is read.

    python tools/combiner_probe.py --run runs/session-m0c-n/cascade-fit-cuda-v2/fit --provider CUDAExecutionProvider
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import session_i_rerankers as R  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402

MAX_SEQ, RRF_K = 256, 60.0
MEMBERS = [
    "ms-marco-MiniLM-L-2-v2-ft-session-j",
    "ms-marco-MiniLM-L-6-v2-ft-session-j",
    "ms-marco-MiniLM-L-2-v2-ft-w1",
    "ms-marco-MiniLM-L-4-v2-ft-w1",
    "ms-marco-MiniLM-L-6-v2-ft-w1",
    "ms-marco-MiniLM-L-12-v2-ft-w1",
]

# The four ft-w1 members postdate session_i_rerankers' pinned table; cascade_squeeze.py
# established the pattern -- register at runtime from the capacity manifest, digests read
# from the record, never guessed.
W1_MANIFEST = REPO / "runs" / "session-m0c-m" / "capacity-manifest.json"


def register_w1() -> None:
    man = json.loads(W1_MANIFEST.read_text(encoding="utf-8"))
    for m in man["models"]:
        if m["name"] in MEMBERS:
            R.FINETUNES[m["name"]] = {
                "digest": m["digests"]["model.onnx"],
                "params_m": m.get("params_m"),
                "arch": m.get("arch", "BERT"),
                "max_seq": 512,
            }


def evaluate(name, orders, gold, base):
    r1 = r3 = g3 = l3 = 0
    for q, order in orders.items():
        g = gold[q]
        rank = next((r for r, i in enumerate(order, 1) if g[i]), None)
        h1, h3 = rank == 1, rank is not None and rank <= 3
        r1 += h1
        r3 += h3
        b1, b3 = base[q]
        g3 += (h3 and not b3)
        l3 += (b3 and not h3)
    n = len(orders)
    print(f"{name:22} R@1 {r1}/{n} = {r1/n:.4f}   R@3 {r3}/{n} = {r3/n:.4f}   "
          f"gained {g3} lost {l3}")
    return {"name": name, "R@1": r1, "R@3": r3, "gained3": g3, "lost3": l3}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--out", type=Path, default=REPO / "runs/session-m0c-n/combiner-probe.json")
    args = ap.parse_args()

    pools, _ = load_pools(args.run)
    texts = turn_texts()
    register_w1()
    encoders = {}
    for m in MEMBERS:
        e = R.load(m, provider=args.provider)
        if not R.smoke_test(e).get("pass"):
            raise SystemExit(f"REFUSING: {m} failed its smoke test.")
        encoders[m] = e

    gold = {q: [bool(c.is_gold) for c in p.candidates] for q, p in pools.items()}
    narrow: dict[str, list[int]] = {}
    scores: dict[str, dict[str, dict[int, float]]] = {m: {} for m in MEMBERS}

    mismatched = 0
    for q, p in pools.items():
        cur = sorted((i for i, c in enumerate(p.candidates) if c.fusion_rank is not None),
                     key=lambda i: p.candidates[i].fusion_rank)
        narrow[q] = cur
        docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in cur]
        for m in MEMBERS:
            scores[m][q] = dict(zip(cur, encoders[m].score_batch(p.question, docs, MAX_SEQ)))
        # gate: pair cascade from fresh logits == binary fusion order
        s2, s6 = scores[MEMBERS[0]][q], scores[MEMBERS[1]][q]
        r2 = {i: sorted(cur, key=lambda j: (-s2[j], j)).index(i) for i in cur}
        r6 = {i: sorted(cur, key=lambda j: (-s6[j], j)).index(i) for i in cur}
        mine = sorted(cur, key=lambda i: (
            -(1.0/(RRF_K + r2[i]) + 1.0/(RRF_K + r6[i])), i))
        if mine != cur:
            mismatched += 1

    print(f"instrument gate: pair-cascade order reproduced on "
          f"{len(pools)-mismatched}/{len(pools)} queries")
    if mismatched:
        raise SystemExit("REFUSING. Offline reconstruction disagrees with the binary.")

    base = {}
    for q, cur in narrow.items():
        rank = next((r for r, i in enumerate(cur, 1) if gold[q][i]), None)
        base[q] = (rank == 1, rank is not None and rank <= 3)

    results = [evaluate("BASELINE pair-RRF", narrow, gold, base)]

    # PRIMARY: top-3 vote across six, ties by six-way RRF
    vote_orders = {}
    for q, cur in narrow.items():
        def six_rrf(i):
            s = 0.0
            for m in MEMBERS:
                sc = scores[m][q]
                s += 1.0 / (RRF_K + sorted(cur, key=lambda j: (-sc[j], j)).index(i) + 1)
            return s
        def votes(i):
            v = 0
            for m in MEMBERS:
                sc = scores[m][q]
                if sorted(cur, key=lambda j: (-sc[j], j)).index(i) < 3:
                    v += 1
            return (-v, -six_rrf(i), i)
        vote_orders[q] = sorted(cur, key=votes)
    results.append(evaluate("PRIMARY six-vote", vote_orders, gold, base))

    # SECONDARY: per-query z-sum over six
    zsum_orders = {}
    for q, cur in narrow.items():
        zs = []
        for m in MEMBERS:
            xs = [scores[m][q][i] for i in cur]
            mu, sd = st.mean(xs), st.pstdev(xs) if len(xs) > 1 else 0.0
            zs.append({i: ((scores[m][q][i] - mu) / sd if sd else 0.0) for i in cur})
        total = {i: sum(z[i] for z in zs) for i in cur}
        zsum_orders[q] = sorted(cur, key=lambda i: (-total[i], i))
    results.append(evaluate("SECONDARY six-zsum", zsum_orders, gold, base))

    args.out.write_text(json.dumps(
        {"_what": "Probe 2 evaluation", "prereg": "PREREGISTRATION-COMBINER.json",
         "instrument_gate_mismatches": mismatched, "arms": results}, indent=2) + "\n",
        encoding="utf-8")
    print(f"wrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
