"""Does the gold turn sit APART from its neighbours in the top-5, or WITH them?

    python tools/neighbour_structure.py

**Measurement only. ADR-010 reach check. Nothing ships.**

## The question, and why it has never been asked

Every scorer in this pipeline compares a candidate to the QUERY. BM25, dense cosine, the
cross-encoder -- all of them answer "how relevant is this one turn to this one question". The cue
features (`margin`, `z`) are set-level, but they are set-level over *query-relevance scores*.

**Nothing has ever compared candidates to EACH OTHER.** The 5x5 similarity structure among the top
candidates is information the system computes nowhere and has never looked at.

Two opposite hypotheses, both plausible, and the point of this file is that only a measurement
separates them:

* **OUTLIER** -- the distractors are drawn from the same session on the same topic, so they are
  similar TO EACH OTHER, and the gold is the one carrying distinctive content. The worked example
  fits: four candidates about "cooking", one about "a chocolate cake".
* **CONSENSUS** -- when the answer appears in several turns, agreement corroborates it. 26 of 56 fit
  failures have >= 2 gold turns, which would favour this.

## THE CONTROL, and it is what makes the reading mean anything

A statistic that describes gold is useless if it equally describes rank-1-when-rank-1-is-correct.
So the same quantity is computed on both halves of the head-probe population:

* **POSITIVE** (26 on fit) -- rank 2 is gold, rank 1 is not. A swap FIXES.
* **NEGATIVE** (110 on fit) -- rank 1 is gold, rank 2 is not. A swap BREAKS.

**Rank 1 is already right 110 times against 26.** Any rule that reorders must be correct on more
than 81% of the pairs it touches or it loses ground. So the feature is scored as `flips_gained` vs
`flips_lost` against that bar -- never as a correlation, which would look encouraging and mean
nothing.

## Two similarity measures, cheapest first

1. **IDF-weighted token cosine** -- instant, no model, and it is the measure under which "the
   distractors share the session's topic vocabulary" would show up most directly.
2. **dense cosine** via the shipped jina embedder -- only run if (1) shows something, because it
   costs a model load and 5 embeddings per query.

A null under both closes the last hand-built option in this space.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "neighbour-structure.json"
TOP = 5

_WORD = re.compile(r"[a-z0-9]+")
STOP = frozenset(
    "a an the of to in on at is are was were be been being it its this that these those and or but "
    "if then as by from for with i my me we our you your do did does have has had will would can "
    "could should not no yes so just really very about there here what when where which who how".split()
)


def toks(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in STOP and len(w) > 1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=TOP)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    pools, _ = load_pools(FIT_POOLS)
    texts_all = turn_texts()

    orders, hits = {}, 0
    for qid, pool in pools.items():
        orders[qid] = shipped_order(pool)
        hits += int(pool.gold[orders[qid][0]])
    r1 = round(hits / len(pools), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING: reconstructed fit R@1 {r1} != published {CONTROL_R1}")
    print(f"control: fit R@1 {r1}  ({len(pools)} queries)  top-{args.top}\n")

    # IDF over the whole fit candidate population -- the same corpus the cues index.
    df: Counter[str] = Counter()
    ndocs = 0
    for qid, pool in pools.items():
        seen_q = texts_all.get(qid, {})
        for c in pool.candidates:
            t = seen_q.get(c.turn_id)
            if t:
                ndocs += 1
                df.update(set(toks(t)))
    idf = {w: math.log(1.0 + ndocs / (1 + n)) for w, n in df.items()}
    print(f"idf over {ndocs:,} fit turns, {len(idf):,} terms")

    def vec(text: str) -> dict[str, float]:
        c = Counter(toks(text))
        v = {w: (1 + math.log(n)) * idf.get(w, math.log(1.0 + ndocs)) for w, n in c.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / norm for w, x in v.items()}

    def cos(a: dict[str, float], b: dict[str, float]) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(x * b.get(w, 0.0) for w, x in a.items())

    rows = []
    for qid, pool in pools.items():
        texts = texts_all.get(qid, {})
        idxs = [int(i) for i in orders[qid][: args.top]]
        vs = [vec(texts.get(pool.candidates[i].turn_id) or "") for i in idxs]
        n = len(vs)
        if n < 2:
            continue
        # affinity = mean similarity to the OTHER candidates in the slate
        aff = []
        for a in range(n):
            sims = [cos(vs[a], vs[b]) for b in range(n) if b != a]
            aff.append(sum(sims) / len(sims))
        rows.append(
            {
                "query_id": qid,
                "category": pool.category,
                "gold": [bool(pool.gold[i]) for i in idxs],
                "affinity": aff,
            }
        )

    # ---- is gold more or less similar to its neighbours than a non-gold candidate? -------------
    g_aff = [a for r in rows for a, g in zip(r["affinity"], r["gold"]) if g]
    n_aff = [a for r in rows for a, g in zip(r["affinity"], r["gold"]) if not g]
    print(f"\nneighbour affinity within the top-{args.top}:")
    print(f"  GOLD      n={len(g_aff):<5} mean {np.mean(g_aff):.4f}  median {np.median(g_aff):.4f}")
    print(f"  NON-GOLD  n={len(n_aff):<5} mean {np.mean(n_aff):.4f}  median {np.median(n_aff):.4f}")
    print(f"  difference (gold - nongold): {np.mean(g_aff) - np.mean(n_aff):+.4f}")

    # ---- THE CONTROL: rank1 vs rank2, split by which one is gold ------------------------------
    pos = [r for r in rows if (not r["gold"][0]) and len(r["gold"]) > 1 and r["gold"][1]]
    neg = [r for r in rows if r["gold"][0] and len(r["gold"]) > 1 and not r["gold"][1]]
    print(f"\nCONTROL -- rank1 vs rank2 affinity delta (rank2 minus rank1):")
    for name, grp in (("POSITIVE (swap FIXES)", pos), ("NEGATIVE (swap BREAKS)", neg)):
        d = [r["affinity"][1] - r["affinity"][0] for r in grp]
        print(f"  {name:<24} n={len(d):<4} mean {np.mean(d):+.4f}  median {np.median(d):+.4f}  "
              f"frac>0 {np.mean([x > 0 for x in d]):.3f}")

    # ---- score it as a swap rule, gained vs lost ------------------------------------------------
    print(f"\nas a rank1/rank2 swap rule (swap when rank2 affinity - rank1 affinity > tau):")
    print(f"{'tau':>8}{'flips':>7}{'gain':>6}{'lost':>6}{'net':>6}{'R@1':>9}")
    deltas = sorted({round(r["affinity"][1] - r["affinity"][0], 4) for r in rows})
    curve = []
    for tau in [-0.2, -0.1, -0.05, -0.02, 0.0, 0.02, 0.05, 0.1, 0.2]:
        gain = lost = flips = 0
        for r in rows:
            if len(r["gold"]) < 2:
                continue
            if (r["affinity"][1] - r["affinity"][0]) <= tau:
                continue
            flips += 1
            if r["gold"][1] and not r["gold"][0]:
                gain += 1
            elif r["gold"][0] and not r["gold"][1]:
                lost += 1
        net = gain - lost
        curve.append({"tau": tau, "flips": flips, "gained": gain, "lost": lost, "net": net,
                      "r1": round(r1 + net / len(pools), 4)})
        print(f"{tau:>8.2f}{flips:>7}{gain:>6}{lost:>6}{net:>6}{r1 + net/len(pools):>9.4f}")

    best = max(curve, key=lambda c: c["net"])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "_what": f"candidate-candidate neighbour structure in the top-{args.top}, fit split",
                "_measurement_only": True,
                "_similarity": "IDF-weighted token cosine over the fit candidate population",
                "control_fit_r1": r1,
                "affinity": {
                    "gold": {"n": len(g_aff), "mean": float(np.mean(g_aff)),
                             "median": float(np.median(g_aff))},
                    "non_gold": {"n": len(n_aff), "mean": float(np.mean(n_aff)),
                                 "median": float(np.median(n_aff))},
                    "difference": float(np.mean(g_aff) - np.mean(n_aff)),
                },
                "control_rank1_vs_rank2": {
                    "positive_swap_fixes": {
                        "n": len(pos),
                        "mean_delta": float(np.mean([r["affinity"][1] - r["affinity"][0] for r in pos])) if pos else None,
                    },
                    "negative_swap_breaks": {
                        "n": len(neg),
                        "mean_delta": float(np.mean([r["affinity"][1] - r["affinity"][0] for r in neg])) if neg else None,
                    },
                    "_why": (
                        "rank 1 is already gold 110 times against 26. A statistic that describes "
                        "gold must NOT equally describe rank-1-when-correct, or it is not a "
                        "discriminator."
                    ),
                },
                "swap_rule_curve": curve,
                "best_cell": best,
                "rows": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nbest cell: net {best['net']:+d} at tau {best['tau']}  ->  R@1 {best['r1']}")
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
