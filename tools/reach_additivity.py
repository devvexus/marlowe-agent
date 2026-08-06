"""Session G — the registered additivity read, plus the one combination worth measuring.

`PREREGISTRATION.json -> additivity_read` requires, for each ordered pair of arms, the set of cases
each moves from miss to hit and a stated subsumption verdict. The reason it is registered: three
arms each recovering the same 5% of cases is **one arm**, and a combined oracle cannot show that.

Subsumption rule, as registered:
  * A subsumes B      if |recovered_by_B \\ recovered_by_A| <= 2 cases
  * complementary     if |A only| >= 3 and |B only| >= 3
  * overlapping       otherwise

Thresholds are in CASES rather than rates because that is what the evidence is -- at n=229 a
one-or-two-case difference is not separable from noise.

## The combined measurement

"Individually and combined" was the instruction. A full cross-product is not worth computing:
arm 2 is measured HARMFUL at both configurations, and arm 4 is NOT REACHED with 1 of 59 temporal
questions carrying a window. Combining a harmful arm with a neutral one measures nothing.

The combination that is worth measuring is **arm 1 (session pruning) + arm 3 (template rewrite)** --
the two arms that are not harmful, one changing the candidate set and one changing the query. It is
computed here directly rather than inferred from the per-case sets, because pruning changes what
the rewritten query is ranked against and the two cannot be composed on paper.
"""

from __future__ import annotations

import io
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from reach_arm23_query import template_hyde
from reach_embed import JinaEmbedder, RustEmbeddingCache
from reach_lexical import saturate, score_all, tokenize
from reach_pools import REPO, hit, load_pools, order_of, turn_texts

RUN = REPO / "runs" / "session-g"
OUT_PATH = RUN / "additivity.json"
SUBSUME_MAX = 2
COMPLEMENTARY_MIN = 3


def _load(name: str) -> dict:
    return json.loads(io.open(RUN / name, encoding="utf-8").read())


def _session_scores_max(pool, cue: str) -> dict[str, float]:
    by: dict[str, float] = {}
    for cand in pool.candidates:
        if cand.sid is not None:
            v = getattr(cand, cue)
            if v > by.get(cand.sid, -np.inf):
                by[cand.sid] = v
    return by


def combined(pools, texts, cache, embedder, n_sessions: int = 3) -> dict:
    """Arm 1 pruning at N=3, then rank the pruned pool with arm 3's template-rewritten query."""
    tally = Counter()
    per_case: dict[str, bool] = {}
    for qid, pool in pools.items():
        keep: set[str] = set()
        for cue in ("lexical_bm25", "dense_cosine"):
            scores = _session_scores_max(pool, cue)
            keep |= {s for s, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:n_sessions]}
        mask = np.array([c.sid in keep for c in pool.candidates])
        idx = np.flatnonzero(mask)
        if idx.size == 0:
            per_case[qid] = False
            continue
        rewritten = template_hyde(pool.question)
        terms = [tokenize(texts[qid].get(pool.candidates[i].turn_id, "")) for i in idx]
        lex = saturate(score_all(terms, rewritten))
        vecs = np.stack([
            cache.get(texts[qid].get(pool.candidates[i].turn_id, ""))
            if cache.get(texts[qid].get(pool.candidates[i].turn_id, "")) is not None
            else np.zeros(512, dtype=np.float32)
            for i in idx
        ])
        den = vecs @ embedder.embed(rewritten)
        gold = pool.gold[idx]
        for k in (1, 5, 10):
            L, D = hit(order_of(lex), gold, k), hit(order_of(den), gold, k)
            tally[f"lexical@{k}"] += L
            tally[f"dense@{k}"] += D
            tally[f"oracle@{k}"] += L or D
        per_case[qid] = bool(hit(order_of(lex), gold, 1) or hit(order_of(den), gold, 1))
    n = len(pools)
    return {"rates": {k: round(v / n, 4) for k, v in sorted(tally.items())},
            "_per_case_oracle_at_1": per_case}


def main() -> int:
    arm1 = _load("arm1-pruning.json")
    arm4 = _load("arm4-temporal.json")
    arm23 = _load("arm23-query.json")

    baseline = arm23["_per_case_oracle_at_1"]["baseline"]
    qids = sorted(baseline)

    per_arm: dict[str, dict[str, bool]] = {
        "arm1_pruning_N3": next(
            r for r in arm1["results"]
            if r["aggregation"] == "max" and r["mode"] == "union" and r["N"] == 3
        )["_per_case_oracle_at_1"],
        "arm4_temporal": arm4["_per_case_oracle_at_1"],
    }
    for name, v in arm23["_per_case_oracle_at_1"].items():
        if name != "baseline":
            per_arm[name] = v

    pools, _ = load_pools()
    texts = turn_texts()
    cache = RustEmbeddingCache()
    embedder = JinaEmbedder()
    print("Computing the combined arm (pruning N=3 + template rewrite)...")
    comb = combined(pools, texts, cache, embedder)
    per_arm["COMBINED_prune_N3_plus_template"] = comb["_per_case_oracle_at_1"]

    recovered = {
        name: {q for q in qids if v.get(q) and not baseline[q]} for name, v in per_arm.items()
    }
    broken = {
        name: {q for q in qids if baseline[q] and not v.get(q, False)} for name, v in per_arm.items()
    }

    pairs = []
    names = sorted(recovered)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            A, B = recovered[a], recovered[b]
            a_only, b_only, both = len(A - B), len(B - A), len(A & B)
            if len(B - A) <= SUBSUME_MAX and A:
                verdict = f"{a} subsumes {b}"
            elif len(A - B) <= SUBSUME_MAX and B:
                verdict = f"{b} subsumes {a}"
            elif a_only >= COMPLEMENTARY_MIN and b_only >= COMPLEMENTARY_MIN:
                verdict = "complementary"
            else:
                verdict = "overlapping"
            pairs.append({"a": a, "b": b, "a_only": a_only, "b_only": b_only,
                          "both": both, "verdict": verdict})

    report = {
        "_what": "Session G registered additivity read plus the combined arm.",
        "baseline_oracle_at_1": arm23["rates"]["baseline"]["oracle@1"],
        "combined_arm": {
            "_what": "arm 1 pruning at N=3, then arm 3's template-rewritten query over the pruned pool",
            "rates": comb["rates"],
            "delta_vs_baseline": round(
                comb["rates"]["oracle@1"] - arm23["rates"]["baseline"]["oracle@1"], 4
            ),
        },
        "per_arm": {
            name: {"recovered": len(recovered[name]), "broken": len(broken[name]),
                   "net": len(recovered[name]) - len(broken[name])}
            for name in names
        },
        "pairwise_subsumption": pairs,
        "_why_no_full_cross_product": (
            "Arm 2 is HARMFUL at both configurations and arm 4 is NOT REACHED. Combining a harmful "
            "arm with a neutral one measures nothing."
        ),
    }
    OUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\nBaseline oracle@1 {report['baseline_oracle_at_1']:.4f}")
    c = report["combined_arm"]
    print(f"COMBINED (prune N=3 + template rewrite): oracle@1 {c['rates']['oracle@1']:.4f} "
          f"({c['delta_vs_baseline']:+.4f})\n")
    print(f"  {'arm':46s} {'recovered':>9} {'broken':>7} {'net':>5}")
    for name in names:
        v = report["per_arm"][name]
        print(f"  {name:46s} {v['recovered']:>9} {v['broken']:>7} {v['net']:>+5}")

    print(f"\n  {'pair':>60}  {'A only':>6} {'B only':>6} {'both':>5}  verdict")
    for p in pairs:
        print(f"  {p['a'][:28]:>29} / {p['b'][:28]:<29}  {p['a_only']:>6} {p['b_only']:>6} "
              f"{p['both']:>5}  {p['verdict']}")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
