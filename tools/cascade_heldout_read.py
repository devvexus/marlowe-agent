"""THE HELD-OUT READ of the cascade. One configuration, fixed in writing before this ran.

    PYTHONIOENCODING=utf-8 python tools/cascade_heldout_read.py

## This spends a consumable

`runs/session-m0c-m/PREREGISTRATION-CASCADE-HELDOUT.json` fixes the configuration, the primary and
secondary fusions, the one disclosed knob, the predicted bands and what would falsify the arm. It
was committed to disk BEFORE this file was written. Nothing here was tuned afterwards, no other
depth or width was tried on this split, and there will be no second read.

    slate depth 30 on the PRE-RERANK CUE KEY
      -> ms-marco-MiniLM-L-2-v2-ft-session-j scores all 30, keep its top 10
      -> fuse with ms-marco-MiniLM-L-6-v2-ft-session-j over the narrowed 10
      -> admit top 3

    PRIMARY   RRF, k = 60          SECONDARY (declared)   per-query z-normalised score sum

## Registered prediction, for scoring afterwards

    held-out R@3            0.870 - 0.895   (baseline 0.8515)
    held-out R@1            0.690 - 0.720   (baseline 0.6725)
    held-out input recall   0.965 - 0.980   (baseline 0.9039)
    cond@3                  0.90  - 0.95    (baseline 0.9420)
    FALSIFIED IF            R@3 <= 0.8515, or input recall fails to rise

Input recall is the component to trust most: it is a property of the cue ordering and the depth
constant alone -- no model, no threshold, nothing fitted. If it does not rise, the pipeline was not
reconstructed and every other number here is suspect.

## The gates, and the read is refused if any fails

1. The shipped key at depth 10 must reproduce the published held-out **R@1 0.6725** exactly.
2. It must also reproduce the published **R@1_current 0.5852** and **R@5 0.8865**.
3. The depth-10 cue slate must equal the candidate set the binary actually reranked, read from the
   dump (`rerank_score is not None`), on every query.
4. Both graphs pass their discrimination smoke tests; digests pinned by `session_i_rerankers`.
5. R@k monotone non-decreasing in k.

## Reporting

R@1/2/3/5, R@1_current, input recall, cond@1, cond@3, the conditional stage-retention table, and
**McNemar exact paired counts** -- at n=229 the Wilson half-width near p=0.9 is about 0.039, so an
unpaired delta cannot resolve this effect.

## Reuse, not re-implementation

`cue_only_order` from `correct_case_control`; `shipped_order`, `current_gold_ids` and the pools path
convention from `sweep_reranker_frontier`; pools and texts from `reach_pools`; the ONE cross-encoder
loader from `session_i_rerankers`.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from collections import Counter
from math import comb
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import session_i_rerankers as R  # noqa: E402
from correct_case_control import cue_only_order  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import current_gold_ids, shipped_order  # noqa: E402

from marlowe_eval.datasets import longmemeval  # noqa: E402

HELDOUT = REPO / "runs" / "session-k" / "heldout"
OUT = REPO / "runs" / "session-m0c-m" / "cascade-heldout-read.json"
L2 = "ms-marco-MiniLM-L-2-v2-ft-session-j"
L6 = "ms-marco-MiniLM-L-6-v2-ft-session-j"
MAX_SEQ, RRF_K, SLATE, NARROW = 256, 60, 30, 10

PUBLISHED = {"R@1": 0.6725, "R@1_current": 0.5852, "R@5": 0.8865, "R@3": 0.8515,
             "input_recall": 0.9039}
PREDICTED = {"R@3": (0.870, 0.895), "R@1": (0.690, 0.720),
             "input_recall": (0.965, 0.980), "cond@3": (0.90, 0.95)}
KS = (1, 2, 3, 5, 10, 30)


def z(xs):
    if len(xs) < 2:
        return [0.0] * len(xs)
    m, s = st.mean(xs), st.pstdev(xs)
    return [(x - m) / s if s else 0.0 for x in xs]


def mcnemar(a_hits, b_hits, qids):
    """Exact two-sided McNemar over the discordant pairs. b is the new arm."""
    g = sum(1 for q in qids if b_hits[q] and not a_hits[q])
    l = sum(1 for q in qids if a_hits[q] and not b_hits[q])
    d = g + l
    if d == 0:
        return g, l, 1.0
    k = min(g, l)
    p = sum(comb(d, i) for i in range(0, k + 1)) / (2 ** d) * 2
    return g, l, min(1.0, p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--provider", default="CPUExecutionProvider")
    args = ap.parse_args()

    pools, stats = load_pools(HELDOUT)
    texts = turn_texts()
    n = len(pools)
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    cur = current_gold_ids(corpus)
    print(f"HELD-OUT pools: {n} queries, {stats['candidates']:,} candidates")

    ship = {q: [int(v) for v in shipped_order(p)] for q, p in pools.items()}
    cue = {q: [int(v) for v in cue_only_order(p)] for q, p in pools.items()}

    def rk(order):
        return {q: next((r for r, v in enumerate(order[q], 1) if pools[q].gold[int(v)]), 10 ** 6)
                for q in pools}

    base_rk = rk(ship)
    base = {f"R@{k}": round(sum(1 for r in base_rk.values() if r <= k) / n, 4) for k in KS}
    base["R@1_current"] = round(sum(
        1 for q in pools if base_rk[q] == 1
        and pools[q].candidates[ship[q][0]].turn_id in cur.get(q, frozenset())) / n, 4)
    base["input_recall"] = round(
        sum(any(pools[q].gold[i] for i in cue[q][:10]) for q in pools) / n, 4)

    print("\nGATES")
    for key in ("R@1", "R@1_current", "R@5"):
        ok = abs(base[key] - PUBLISHED[key]) < 1e-9
        print(f"  G1/G2 {key:12s} {base[key]:.4f} == published {PUBLISHED[key]:.4f}   "
              f"{'PASS' if ok else 'FAIL'}")
        if not ok:
            raise SystemExit(f"REFUSING. {key} does not reproduce the published held-out figure. "
                             "The reconstruction is not the product and the read is not spent.")
    exact = sum(set(cue[q][:10]) == {i for i, c in enumerate(p.candidates)
                                     if c.rerank_score is not None} for q, p in pools.items())
    print(f"  G3    cue slate == the set the binary reranked: {exact}/{n} "
          f"{'PASS' if exact == n else 'FAIL'}")
    if exact != n:
        raise SystemExit("REFUSING (GATE 3).")
    print(f"  (published R@3 {PUBLISHED['R@3']} vs reconstructed {base['R@3']}, "
          f"input recall {PUBLISHED['input_recall']} vs {base['input_recall']})")

    ce2, ce6 = R.load(L2, provider=args.provider), R.load(L6, provider=args.provider)
    for m, ce in ((L2, ce2), (L6, ce6)):
        if not R.smoke_test(ce).get("pass"):
            raise SystemExit(f"REFUSING (GATE 4). {m} failed its smoke test.")
    print(f"  G4    both graphs smoke PASS ({ce2.params_m}M, {ce6.params_m}M)")

    slate = {q: cue[q][:SLATE] for q in pools}
    ir30 = sum(any(pools[q].gold[i] for i in slate[q]) for q in pools) / n
    s2, narrow = {}, {}
    for q, p in pools.items():
        docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in slate[q]]
        sc = ce2.score_batch(p.question, docs, MAX_SEQ)
        s2[q] = dict(zip(slate[q], sc))
        narrow[q] = [i for _, i in sorted(zip(sc, slate[q]), key=lambda t: (-t[0], t[1]))][:NARROW]
    s6 = {}
    for q, p in pools.items():
        docs = [texts.get(q, {}).get(p.candidates[i].turn_id) or "" for i in narrow[q]]
        s6[q] = dict(zip(narrow[q], ce6.score_batch(p.question, docs, MAX_SEQ)))

    r2 = {q: {i: r for r, i in enumerate(narrow[q])} for q in pools}
    r6 = {q: {i: r for r, i in enumerate(sorted(narrow[q], key=lambda i: (-s6[q][i], i)))}
          for q in pools}
    arms = {
        "PRIMARY   cascade-RRF": {q: sorted(narrow[q], key=lambda i: (
            -(1.0 / (RRF_K + r2[q][i]) + 1.0 / (RRF_K + r6[q][i])), i)) for q in pools},
    }
    zz = {}
    for q in pools:
        a = dict(zip(narrow[q], z([s2[q][i] for i in narrow[q]])))
        b = dict(zip(narrow[q], z([s6[q][i] for i in narrow[q]])))
        zz[q] = {i: a[i] + b[i] for i in narrow[q]}
    arms["SECONDARY cascade-zsum"] = {q: sorted(narrow[q], key=lambda i: (-zz[q][i], i))
                                      for q in pools}

    print("\n" + "=" * 104)
    print("HELD-OUT RESULT")
    print("=" * 104)
    print(f"  {'arm':26s} {'R@1':>8} {'R@1cur':>8} {'R@2':>8} {'R@3':>8} {'R@5':>8} "
          f"{'in.rec':>8} {'cond@3':>8}")
    print(f"  {'BASELINE shipped @10':26s} {base['R@1']:>8.4f} {base['R@1_current']:>8.4f} "
          f"{base['R@2']:>8.4f} {base['R@3']:>8.4f} {base['R@5']:>8.4f} "
          f"{base['input_recall']:>8.4f} {base['R@3'] / base['input_recall']:>8.4f}")
    cells = {"baseline": base}
    for name, o in arms.items():
        a_rk = rk(o)
        v = {k: sum(1 for r in a_rk.values() if r <= k) / n for k in KS}
        prev = 0.0
        for k in KS:
            if v[k] + 1e-12 < prev:
                raise SystemExit(f"REFUSING (GATE 5). R@k not monotone in {name}.")
            prev = v[k]
        cur_hit = round(sum(1 for q in pools if a_rk[q] == 1
                            and pools[q].candidates[o[q][0]].turn_id in cur.get(q, frozenset()))
                        / n, 4)
        c3 = v[3] / ir30
        cells[name] = {**{f"R@{k}": round(x, 4) for k, x in v.items()},
                       "R@1_current": cur_hit, "input_recall": round(ir30, 4),
                       "conditional_top1": round(v[1] / ir30, 4), "conditional_top3": round(c3, 4)}
        print(f"  {name:26s} {v[1]:>8.4f} {cur_hit:>8.4f} {v[2]:>8.4f} {v[3]:>8.4f} "
              f"{v[5]:>8.4f} {ir30:>8.4f} {c3:>8.4f}")
        cells[name]["_rk"] = a_rk

    print("\n  McNemar exact, paired against the shipped baseline:")
    qids = list(pools)
    for name in arms:
        a_rk = cells[name]["_rk"]
        for k in (1, 3):
            g, l, p = mcnemar({q: base_rk[q] <= k for q in qids},
                              {q: a_rk[q] <= k for q in qids}, qids)
            d = cells[name][f"R@{k}"] - base[f"R@{k}"]
            print(f"    {name:26s} R@{k}  delta {d:+.4f}   gained {g:>3} lost {l:>3}   "
                  f"p = {p:.4f}   {'SIGNIFICANT' if p < 0.05 else 'not significant'}")

    print("\n  Registered prediction, scored:")
    prim = cells["PRIMARY   cascade-RRF"]
    for key, (lo, hi) in PREDICTED.items():
        got = prim["conditional_top3"] if key == "cond@3" else prim[key]
        inside = lo <= got <= hi
        print(f"    {key:14s} predicted {lo:.3f}-{hi:.3f}   got {got:.4f}   "
              f"{'INSIDE' if inside else 'OUTSIDE'}")
    fals = prim["R@3"] <= PUBLISHED["R@3"] or prim["input_recall"] <= base["input_recall"]
    print(f"\n  FALSIFICATION CONDITION (R@3 <= {PUBLISHED['R@3']} or input recall did not rise): "
          f"{'MET -- the arm is refuted' if fals else 'not met'}")

    for c in cells.values():
        c.pop("_rk", None)
    art = {"_what": "HELD-OUT READ of the cascade -- one configuration, pre-registered",
           "_split": "heldout", "_preregistration":
               "runs/session-m0c-m/PREREGISTRATION-CASCADE-HELDOUT.json",
           "_config": {"slate": SLATE, "narrow": NARROW, "rrf_k": RRF_K,
                       "models": [L2, L6], "max_seq": MAX_SEQ},
           "_published_baseline": PUBLISHED, "_predicted": PREDICTED,
           "n": n, "cells": cells}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(art, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
