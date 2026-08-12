"""Is the cross-encoder CONFIDENTLY WRONG on preference questions, or UNCONFIDENT?

    PYTHONIOENCODING=utf-8 python tools/preference_spread.py

## The question, and why the two answers need opposite fixes

`tools/preference_probe.py` established that `single-session-preference` fails at the HEAD, not at
the slate: gold is in the depth-10 slate on **86.7%** of queries -- in line with every other
category -- and conditional accuracy is **0.3846** against 0.76-0.91 elsewhere. Reading the ten fit
failures, five have top-3 turns that are WILDLY off topic (a sneezing question answered with
audiobooks and airline prices; a bedroom-furniture question answered with a wifi router).

The queries share an obvious surface property: they are short generic REQUESTS -- *"Any tips?"*,
*"Any suggestions?"*, *"What do you think?"* -- carrying little for a scorer to bind to.

Two rival explanations, and they are distinguishable by the score geometry alone:

  **(a) CONFIDENTLY WRONG.** The slate's logits are well separated and the model puts an unrelated
  turn decisively on top. Large rank1-rank2 gaps, large slate spread. The fault is the model's
  judgement; the fix is training.

  **(b) UNCONFIDENT.** The slate's logits are compressed into a narrow band, so rank 1 is close to
  arbitrary among ten near-tied candidates. Small gaps, small spread. The fault is that the query
  carries no discriminative signal; the fix is the query representation, and a better-trained model
  of the same shape will not help.

Conditional accuracy of 0.3846 against a ~1/10 random baseline for a 10-candidate slate is already
suggestive of (b), but that is an inference from an aggregate and this measures the geometry
directly.

## What is measured, per category, on the fit split

  * **slate spread** -- max minus min rerank logit over the depth-10 slate.
  * **head gap** -- rank1 minus rank2, the quantity the 0.084 near-tie band is defined on.
  * **share of queries whose head gap is inside the 0.084 band**, where a blind swap is a coin flip.
  * **question length** in content words, and in wordpieces of the scored pair.
  * the same, split by HIT and MISS, because a category-level mean can hide the contrast.

**Diagnosis only. No mechanism, no threshold, nothing tuned, nothing shipped.**

## The gate

The shipped key must reconstruct fit R@1 = **0.7555** exactly, or this refuses before printing.

## Reuse, not re-implementation

Ranking key and gate constant from `sweep_reranker_frontier`; pools and texts from `reach_pools`;
the content-word tokenizer from `correct_case_control`. Rerank logits are READ FROM THE DUMP the
binary produced -- nothing is re-scored here, so no second scorer can disagree with the first.

**Fit split only. Held-out is not opened.**
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from correct_case_control import content_words  # noqa: E402
from failure_forensics import SLATE_DEPTH  # noqa: E402
from reach_pools import load_pools  # noqa: E402
from sweep_reranker_frontier import CONTROL_R1, FIT_POOLS, shipped_order  # noqa: E402

from marlowe_eval.datasets import longmemeval  # noqa: E402

OUT = REPO / "runs" / "session-m0c-m" / "preference-spread.json"
BAND = 0.084


def med(xs):
    return round(st.median(xs), 4) if xs else float("nan")


def mean(xs):
    return round(sum(xs) / len(xs), 4) if xs else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    pools, stats = load_pools(FIT_POOLS)
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    questions = {c.query_id: c.question for c in corpus.cases}
    print(f"fit pools: {stats['pools']} queries, {stats['candidates']:,} candidates")

    recs = []
    for qid, pool in pools.items():
        order = shipped_order(pool)
        scored = [pool.candidates[int(i)].rerank_score for i in order[:SLATE_DEPTH]]
        scored = [s for s in scored if s is not None]
        if len(scored) < 2:
            continue
        q = questions.get(qid) or ""
        recs.append({
            "query_id": qid,
            "category": pool.category,
            "hit": bool(pool.gold[int(order[0])]),
            "spread": round(max(scored) - min(scored), 4),
            "head_gap": round(scored[0] - scored[1], 4),
            "top1": round(scored[0], 4),
            "q_words": len(content_words(q)),
            "q_chars": len(q),
        })

    r1 = round(sum(r["hit"] for r in recs) / len(recs), 4)
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(f"REFUSING. Reconstructed fit R@1 {r1}; published {CONTROL_R1}.")
    print(f"\nGATE  shipped key fit R@1 {r1} == published {CONTROL_R1}   PASSED  (n={len(recs)})")

    cats = sorted({r["category"] for r in recs})
    print("\n" + "=" * 112)
    print("SCORE GEOMETRY PER CATEGORY -- confidently wrong (big gaps) or unconfident (small)?")
    print("=" * 112)
    print(f"  {'category':28s} {'n':>4} {'spread':>8} {'headgap':>8} {'med gap':>8} "
          f"{'in band':>8} {'top1':>8} {'q words':>8} {'q chars':>8}")
    per_cat = {}
    for c in cats:
        rs = [r for r in recs if r["category"] == c]
        gaps = [r["head_gap"] for r in rs]
        inband = sum(1 for g in gaps if g <= BAND) / len(rs)
        per_cat[c] = {
            "n": len(rs), "mean_spread": mean([r["spread"] for r in rs]),
            "mean_head_gap": mean(gaps), "median_head_gap": med(gaps),
            "share_in_band": round(inband, 4), "mean_top1": mean([r["top1"] for r in rs]),
            "mean_q_words": mean([r["q_words"] for r in rs]),
            "mean_q_chars": mean([r["q_chars"] for r in rs]),
        }
        v = per_cat[c]
        print(f"  {c:28s} {v['n']:>4} {v['mean_spread']:>8.4f} {v['mean_head_gap']:>8.4f} "
              f"{v['median_head_gap']:>8.4f} {v['share_in_band']:>8.2%} {v['mean_top1']:>8.3f} "
              f"{v['mean_q_words']:>8.2f} {v['mean_q_chars']:>8.1f}")

    print("\n" + "=" * 112)
    print("THE SAME, SPLIT BY HIT / MISS -- a category mean can hide the contrast")
    print("=" * 112)
    print(f"  {'category':28s} {'':>6} {'n':>4} {'spread':>8} {'headgap':>8} {'in band':>8} "
          f"{'q words':>8}")
    by_hit = {}
    for c in cats:
        for lab, want in (("HIT", True), ("MISS", False)):
            rs = [r for r in recs if r["category"] == c and r["hit"] is want]
            if not rs:
                continue
            gaps = [r["head_gap"] for r in rs]
            row = {"n": len(rs), "mean_spread": mean([r["spread"] for r in rs]),
                   "mean_head_gap": mean(gaps),
                   "share_in_band": round(sum(1 for g in gaps if g <= BAND) / len(rs), 4),
                   "mean_q_words": mean([r["q_words"] for r in rs])}
            by_hit[f"{c}|{lab}"] = row
            print(f"  {c:28s} {lab:>6} {row['n']:>4} {row['mean_spread']:>8.4f} "
                  f"{row['mean_head_gap']:>8.4f} {row['share_in_band']:>8.2%} "
                  f"{row['mean_q_words']:>8.2f}")

    # -- the direct contrast: preference vs everything else -----------------------------------------
    pref = [r for r in recs if r["category"] == "single-session-preference"]
    rest = [r for r in recs if r["category"] != "single-session-preference"]
    print("\n" + "=" * 112)
    print("PREFERENCE vs THE REST")
    print("=" * 112)
    for name, key in (("slate spread (max-min logit)", "spread"),
                      ("head gap (rank1 - rank2)", "head_gap"),
                      ("top-1 logit", "top1"),
                      ("question content words", "q_words")):
        p = [r[key] for r in pref]
        o = [r[key] for r in rest]
        print(f"  {name:32s} preference mean {mean(p):>9.4f} median {med(p):>9.4f}   |   "
              f"rest mean {mean(o):>9.4f} median {med(o):>9.4f}")
    pin = sum(1 for r in pref if r["head_gap"] <= BAND) / len(pref)
    oin = sum(1 for r in rest if r["head_gap"] <= BAND) / len(rest)
    print(f"  {'share with head gap <= 0.084':32s} preference {pin:>9.2%}"
          f"                        |   rest {oin:>9.2%}")

    art = {"_what": "score geometry per category: is the reranker confidently wrong on preference "
                    "questions, or unconfident? Logits are read from the dump, not re-scored.",
           "_split": "fit", "_band": BAND, "_gate": {"fit_R@1": r1, "published": CONTROL_R1},
           "per_category": per_cat, "by_hit": by_hit, "records": recs}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(art, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
