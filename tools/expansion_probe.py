"""Probe 4: neighbour expansion for SHORT candidates at scoring time.

Pre-registered: runs/session-m0c-n/PREREGISTRATION-EXPANSION.json.
Candidates <= 16 words are scored against prev+turn+next from their own session; fusion and
reader arms are otherwise identical to the shipped configuration.

    python tools/expansion_probe.py --run runs/session-m0c-n/cascade-fit-cuda-v2/fit --provider CUDAExecutionProvider
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import readers  # noqa: E402
import session_i_rerankers as R  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402

MAX_SEQ, RRF_K, SHORT = 256, 60.0, 16


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--out", type=Path, default=REPO / "runs/session-m0c-n/expansion-probe.json")
    args = ap.parse_args()

    pools, _ = load_pools(args.run)
    TEXTS = turn_texts()
    enc2 = R.load("ms-marco-MiniLM-L-2-v2-ft-session-j", provider=args.provider)
    enc6 = R.load("ms-marco-MiniLM-L-6-v2-ft-session-j", provider=args.provider)
    reader = readers.load("mobilebert-uncased-squad-v2", provider=args.provider)

    # session-ordered texts for neighbour lookup: (qid, sid) -> {turn_index: text}
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    raw = json.loads(open(REPO / split["corpus_path"], encoding="utf-8").read())
    sess_texts: dict[tuple[str, str], dict[int, str]] = {}
    for x in raw:
        qid = x["question_id"]
        for sid, sess in zip(x["haystack_session_ids"], x["haystack_sessions"]):
            sess_texts[(qid, sid)] = {i: t["content"] for i, t in enumerate(sess)}

    def expanded(q, p, i) -> str:
        c = p.candidates[i]
        d = TEXTS.get(q, {}).get(c.turn_id) or ""
        if len(d.split()) > SHORT or c.sid is None or c.turn_index is None:
            return d
        sess = sess_texts.get((q, c.sid))
        if not sess:
            return d
        parts = [sess[j] for j in (c.turn_index - 1, c.turn_index, c.turn_index + 1)
                 if j in sess]
        return " ".join(parts)

    gold = {q: [bool(c.is_gold) for c in p.candidates] for q, p in pools.items()}
    narrow, mismatched = {}, 0
    S2: dict[str, dict[int, float]] = {}
    S6: dict[str, dict[int, float]] = {}
    for q, p in pools.items():
        cur = sorted((i for i, c in enumerate(p.candidates) if c.fusion_rank is not None),
                     key=lambda i: p.candidates[i].fusion_rank)
        narrow[q] = cur
        docs = [TEXTS.get(q, {}).get(p.candidates[i].turn_id) or "" for i in cur]
        S2[q] = dict(zip(cur, enc2.score_batch(p.question, docs, MAX_SEQ)))
        S6[q] = dict(zip(cur, enc6.score_batch(p.question, docs, MAX_SEQ)))
        r2 = {i: sorted(cur, key=lambda j: (-S2[q][j], j)).index(i) for i in cur}
        r6 = {i: sorted(cur, key=lambda j: (-S6[q][j], j)).index(i) for i in cur}
        pair = sorted(cur, key=lambda i: (-(1.0/(RRF_K+r2[i]) + 1.0/(RRF_K+r6[i])), i))
        if pair != cur:
            mismatched += 1
    print(f"instrument gate: {len(pools)-mismatched}/{len(pools)}")
    if mismatched:
        raise SystemExit("REFUSING")

    base = {}
    for q, cur in narrow.items():
        rank = next((r for r, i in enumerate(cur, 1) if gold[q][i]), None)
        base[q] = (rank == 1, rank is not None and rank <= 3)

    def evaluate(name, orders):
        r1 = r3 = g3 = l3 = g1 = l1 = 0
        recovered_stage5 = []
        for q, order in orders.items():
            g = gold[q]
            rank = next((r for r, i in enumerate(order, 1) if g[i]), None)
            h1, h3 = rank == 1, rank is not None and rank <= 3
            b1, b3 = base[q]
            r1 += h1; r3 += h3
            if h3 and not b3:
                recovered_stage5.append(q)
            g3 += (h3 and not b3); l3 += (b3 and not h3)
            g1 += (h1 and not b1); l1 += (b1 and not h1)
        n = len(orders)
        print(f"{name:28} R@1 {r1}/{n} ({g1:+d}/{-l1:+d})   "
              f"R@3 {r3}/{n} = {r3/n:.4f} ({g3:+d}/{-l3:+d})  {recovered_stage5}")
        return {"name": name, "R@1": r1, "R@3": r3}

    evaluate("BASELINE (no expansion)", narrow)

    E2: dict[str, dict[int, float]] = {}
    E6: dict[str, dict[int, float]] = {}
    n_expanded = 0
    for q, p in pools.items():
        e2, e6 = dict(S2[q]), dict(S6[q])
        for i in narrow[q]:
            d_exp = expanded(q, p, i)
            d = TEXTS.get(q, {}).get(p.candidates[i].turn_id) or ""
            if d_exp != d:
                n_expanded += 1
                e2[i] = enc2.score(p.question, d_exp)
                e6[i] = enc6.score(p.question, d_exp)
        E2[q], E6[q] = e2, e6
    print(f"expanded candidates: {n_expanded}")

    def fuse(s2, s6):
        out = {}
        for q, cur in narrow.items():
            a, b = s2[q], s6[q]
            r2 = {i: sorted(cur, key=lambda j: (-a[j], j)).index(i) for i in cur}
            r6 = {i: sorted(cur, key=lambda j: (-b[j], j)).index(i) for i in cur}
            out[q] = sorted(cur, key=lambda i: (
                -(1.0/(RRF_K+r2[i]) + 1.0/(RRF_K+r6[i])), i))
        return out

    evaluate("EXPANSION pair", fuse(E2, E6))

    RA: dict[str, dict[int, float]] = {}
    for q, p in pools.items():
        RA[q] = {i: reader.score(p.question, expanded(q, p, i))["score"] for i in narrow[q]}
    out = {}
    for q, cur in narrow.items():
        a, b, cc = E2[q], E6[q], RA[q]
        r2 = {i: sorted(cur, key=lambda j: (-a[j], j)).index(i) for i in cur}
        r6 = {i: sorted(cur, key=lambda j: (-b[j], j)).index(i) for i in cur}
        ra = {i: sorted(cur, key=lambda j: (-cc[j], j)).index(i) for i in cur}
        out[q] = sorted(cur, key=lambda i: (
            -(1.0/(RRF_K+r2[i]) + 1.0/(RRF_K+r6[i]) + 0.5/(RRF_K+ra[i]+1)), i))
    evaluate("EXPANSION + reader w=0.5", out)

    args.out.write_text(json.dumps({"_what": "Probe 4 evaluation"}, indent=2) + "\n",
                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
