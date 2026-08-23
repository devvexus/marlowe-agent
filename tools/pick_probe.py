"""Probe 3: can an ANSWERABILITY opinion improve the cascade's pick as a third fused ranking?

Pre-registered: runs/session-m0c-n/PREREGISTRATION-PICK.json.

    PRIMARY    reader_fusion : mobilebert SQuAD-v2 answerability joins L-2 x L-6 in the RRF
    SECONDARY  delta_fusion  : shipped-graph logit DELTA under a stoplist-sharpened query joins it

    python tools/pick_probe.py --run runs/session-m0c-n/cascade-fit-cuda-v2/fit --provider CUDAExecutionProvider
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import session_i_rerankers as R  # noqa: E402
import readers  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402

MAX_SEQ, RRF_K = 256, 60.0
READER_NAME = "mobilebert-uncased-squad-v2"
STOPLIST = set(
    "i me my we our you your he she it they them the a an and or but if then of to in on at "
    "for with about as is are was were be been being do does did done have has had what which "
    "who whom whose when where why how this that these those there here not no yes so too very "
    "can will just should now".split()
)


def sharpen(question: str) -> str:
    words = [w for w in "".join(c if c.isalnum() else " " for c in question.lower()).split()]
    kept = [w for w in words if w not in STOPLIST]
    return question if not kept else " ".join(kept)


def rrf3(r2: dict[int, int], r6: dict[int, int], r3rd: dict[int, int], weight: float = 1.0) -> list[int]:
    members = list(r2)
    def key(i):
        s = (1.0 / (RRF_K + r2[i] + 1) + 1.0 / (RRF_K + r6[i] + 1)
             + weight / (RRF_K + r3rd[i] + 1))
        return (-s, i)
    return sorted(members, key=key)


def evaluate(name, orders, gold, base):
    r1 = r3 = g3 = l3 = g1 = l1 = 0
    for q, order in orders.items():
        g = gold[q]
        rank = next((r for r, i in enumerate(order, 1) if g[i]), None)
        h1, h3 = rank == 1, rank is not None and rank <= 3
        b1, b3 = base[q]
        r1 += h1
        r3 += h3
        g3 += (h3 and not b3)
        l3 += (b3 and not h3)
        g1 += (h1 and not b1)
        l1 += (b1 and not h1)
    n = len(orders)
    print(f"{name:22} R@1 {r1}/{n} = {r1/n:.4f} ({g1:+d}/{-l1:+d})   "
          f"R@3 {r3}/{n} = {r3/n:.4f} ({g3:+d}/{-l3:+d})")
    return {"name": name, "R@1": r1, "R@3": r3, "gained1": g1, "lost1": -l1,
            "gained3": g3, "lost3": -l3}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--weight", type=float, default=1.0,
                    help="the third opinion's vote share in the fusion. 1.0 = Probe 3 as "
                         "registered; 0.5 = Probe 3b's single declared value. NEVER swept.")
    ap.add_argument("--out", type=Path, default=REPO / "runs/session-m0c-n/pick-probe.json")
    args = ap.parse_args()

    pools, _ = load_pools(args.run)
    texts = turn_texts()
    enc2 = R.load("ms-marco-MiniLM-L-2-v2-ft-session-j", provider=args.provider)
    enc6 = R.load("ms-marco-MiniLM-L-6-v2-ft-session-j", provider=args.provider)
    reader = readers.load(READER_NAME, provider=args.provider)
    if not readers.smoke_test(reader).get("pass"):
        raise SystemExit(f"REFUSING: {READER_NAME} failed its smoke test.")

    gold = {q: [bool(c.is_gold) for c in p.candidates] for q, p in pools.items()}
    S2: dict[str, dict[int, float]] = {}
    S6: dict[str, dict[int, float]] = {}
    narrow, mismatched = {}, 0
    for q, p in pools.items():
        cur = sorted((i for i, c in enumerate(p.candidates) if c.fusion_rank is not None),
                     key=lambda i: p.candidates[i].fusion_rank)
        narrow[q] = cur
        docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in cur]
        s2 = dict(zip(cur, enc2.score_batch(p.question, docs, MAX_SEQ)))
        s6 = dict(zip(cur, enc6.score_batch(p.question, docs, MAX_SEQ)))
        r2 = {i: sorted(cur, key=lambda j: (-s2[j], j)).index(i) for i in cur}
        r6 = {i: sorted(cur, key=lambda j: (-s6[j], j)).index(i) for i in cur}
        if rrf3(r2, r6, {i: k for k, i in enumerate(sorted(cur))}) != cur and False:
            pass  # two-way gate handled below with the exact pair formula
        pair = sorted(cur, key=lambda i: (-(1.0/(RRF_K+r2[i]) + 1.0/(RRF_K+r6[i])), i))
        if pair != cur:
            mismatched += 1
        S2[q], S6[q] = s2, s6

    print(f"instrument gate: pair-cascade order reproduced on "
          f"{len(pools)-mismatched}/{len(pools)} queries")
    if mismatched:
        raise SystemExit("REFUSING. Offline reconstruction disagrees with the binary.")

    base = {}
    for q, cur in narrow.items():
        rank = next((r for r, i in enumerate(cur, 1) if gold[q][i]), None)
        base[q] = (rank == 1, rank is not None and rank <= 3)

    results = [evaluate("BASELINE pair-RRF", narrow, gold, base)]

    # PRIMARY: reader answerability as the third ranking
    ro = {}
    for q, p in pools.items():
        cur = narrow[q]
        ans = {}
        for i in cur:
            d = texts.get(q, {}).get(p.candidates[i].turn_id) or ""
            ans[i] = reader.score(p.question, d)["score"]
        rA = {i: sorted(cur, key=lambda j: (-ans[j], j)).index(i) for i in cur}
        r2 = {i: sorted(cur, key=lambda j: (-S2[q][j], j)).index(i) for i in cur}
        r6 = {i: sorted(cur, key=lambda j: (-S6[q][j], j)).index(i) for i in cur}
        ro[q] = rrf3(r2, r6, rA, weight=args.weight)
    results.append(evaluate(f"PRIMARY reader-fusion w={args.weight:g}", ro, gold, base))

    # SECONDARY: delta under the sharpened query, through the SHIPPED graph
    do = {}
    for q, p in pools.items():
        cur = narrow[q]
        qp = sharpen(p.question)
        docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in cur]
        if qp == p.question:
            deltas = {i: 0.0 for i in cur}
        else:
            s2p = dict(zip(cur, enc2.score_batch(qp, docs, MAX_SEQ)))
            deltas = {i: s2p[i] - S2[q][i] for i in cur}
        rD = {i: sorted(cur, key=lambda j: (-deltas[j], j)).index(i) for i in cur}
        r2 = {i: sorted(cur, key=lambda j: (-S2[q][j], j)).index(i) for i in cur}
        r6 = {i: sorted(cur, key=lambda j: (-S6[q][j], j)).index(i) for i in cur}
        do[q] = rrf3(r2, r6, rD)
    results.append(evaluate("SECONDARY delta-fusion", do, gold, base))

    args.out.write_text(json.dumps(
        {"_what": "Probe 3 evaluation", "prereg": "PREREGISTRATION-PICK.json",
         "instrument_gate_mismatches": mismatched, "arms": results}, indent=2) + "\n",
        encoding="utf-8")
    print(f"wrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
