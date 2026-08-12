"""Did arm B actually MEMORISE the fit split? The diagnosis has never been measured.

    PYTHONIOENCODING=utf-8 python tools/armb_fold_check.py

## Why this exists

`STATE.md` and `NEGATIVE-RESULTS.md` both record arm B's collapse with a stated cause:

> retrain, arm B (new negatives): fit **0.8253** (+0.0698, McNemar 18/2, p = 0.0004)
> -> held-out **0.6812** (+0.0087, 10/8, p = 0.815). `deployed_top_k` negatives are
> **query-specific by construction** ("the turns that beat gold on THESE queries"), so the
> model **memorised turns instead of the pattern**.

That last clause is an *inference from the collapse*, not a measurement. It has been quoted
forward as settled ever since, and a whole class of future work is being planned against it --
specifically, "use negatives that cannot be memorised" only makes sense if memorisation is what
happened.

`tools/fold_contamination.py` (W7) built exactly the instrument that can test it, and applied it
to the SHIPPED graph, where it found no contamination (+0.0135, p = 0.85). It did not apply it to
**arm B's graph**, which is the one the memorisation claim is about. This file does.

If arm B memorised query-specific turns from the fit split, its advantage on conversations it
trained on must exceed its advantage on conversations it did not -- and by much more than the
shipped graph's null.

## THE REGISTERED PREDICTION, written before the model was loaded

The naive form of the memorisation hypothesis predicts a LARGE trained-on premium: arm B at
~0.85-0.88 on the 182 and ~0.72-0.78 on the 47, a delta of +0.10 or more.

**I do not believe that, and the reason is already on disk.** `RETRAIN-RESULT.md` records a
within-fit, conversation-level control for arm B reading **+0.0638 on 47 queries**. If those are
the same 47 -- Session J's held-apart fold -- then arm B's held-apart R@1 is about
0.7447 + 0.0638 = **0.8085**, and against an overall 0.8253 its trained-on/held-apart delta is
roughly **+0.02**: near-null, and no larger than the shipped graph's.

So the registration is:

  * **delta < +0.05 with p > 0.2** -- i.e. NULL, matching the shipped graph.
  * If that holds, **the memorisation diagnosis for arm B is REFUTED**: arm B generalises within
    the fit split just fine and fails only across the fit/held-out boundary. The cause of the 8x
    collapse is then NOT "it memorised turns" but something that distinguishes the two splits --
    which puts the standing explanation (selection at n=229, plus case mix) back in sole charge.
  * That would also remove the central premise from the "train on external data because it cannot
    memorise the evaluation" proposal, and it must be said plainly rather than quietly dropped.
  * If instead the delta IS large (>= +0.10), the memorisation diagnosis is confirmed by direct
    measurement for the first time, and the external-data direction is strengthened.

## The gates

1. `fold_contamination.gate_shipped` -- the shipped key must reconstruct fit R@1 0.7555 exactly.
2. `fold_contamination.gate_fold` -- the recovered fold's held-apart set must equal the set in
   `retrain-fold-breakdown.json`, written by a different session through a different code path.
3. Arm B must reproduce its published fit cell, **R@1 0.8253 at depth 10** (`retrain-B.json`), or
   its fold difference is a number about a different scorer.
4. The partition R@1 values must RECOMBINE to the whole at the partition weights.

## Reuse, not re-implementation

Everything is imported: the fold recovery, the per-query evaluator, the summariser, the exact
test and the recombination check from `fold_contamination`; the ranking key, reorder and gate
constant from `sweep_reranker_frontier`; the pools from `reach_pools`; the ONE cross-encoder
loader from `session_i_rerankers`. No scoring rule is restated here.

**Held-out is NOT read.** Fit split only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import session_i_rerankers as R  # noqa: E402
from fold_contamination import (  # noqa: E402
    DEPTH,
    MAX_SEQ,
    SHIPPED,
    clopper_pearson,
    fisher_exact_2x2,
    gate_fold,
    gate_shipped,
    per_query,
    recombination_check,
    recover_fold,
    summarise,
)
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import (  # noqa: E402
    CONTROL_R1,
    FIT_POOLS,
    current_gold_ids,
    reordered,
    shipped_order,
)

from marlowe_eval.datasets import longmemeval  # noqa: E402

ARM_B = "ms-marco-MiniLM-L-2-v2-ft-m-B"
ARM_B_PUBLISHED_R1 = 0.8253  # runs/session-m0c-m/retrain-B.json, cells[0], depth 10
SHIPPED_FOLD_DELTA = 0.0135  # runs/session-m0c-m/fold-contamination.json -- the comparison point
OUT_PATH = REPO / "runs" / "session-m0c-m" / "armb-fold-check.json"


def score(pools, ce, texts, base_order, gold_current):
    order = {}
    for qid, pool in pools.items():
        slate = [int(i) for i in base_order[qid][:DEPTH]]
        docs = [texts.get(qid, {}).get(pool.candidates[i].turn_id) or "" for i in slate]
        order[qid] = reordered(pool, slate, ce.score_batch(pool.question, docs, MAX_SEQ))
    return per_query(pools, order, gold_current, base_order)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    ap.add_argument("--provider", default="CPUExecutionProvider")
    args = ap.parse_args()

    pools, stats = load_pools(FIT_POOLS)
    print(f"fit pools: {stats['pools']} queries, {stats['candidates']:,} candidates")

    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_current = current_gold_ids(corpus)
    texts = turn_texts()

    base_order = {qid: shipped_order(p) for qid, p in pools.items()}
    shipped_pq = per_query(pools, base_order, gold_current, base_order)
    whole_shipped = summarise(shipped_pq, list(pools))
    print("\nGATE 1 -- shipped key over the full fit split")
    print(f"  R@1 {whole_shipped['R@1']}  (published {CONTROL_R1})")
    gate_shipped(whole_shipped["R@1"])
    print("  GATE 1 PASSED")

    fold = recover_fold(set(pools))
    fold_check = gate_fold(fold)
    trained_on = sorted(set(fold["trained_on_query_ids"]) | set(fold["unassigned_query_ids"]))
    held_apart = fold["held_apart_query_ids"]
    print(f"\nGATE 2 -- held-apart set vs retrain-fold-breakdown.json: "
          f"{fold_check['here']} == {fold_check['there']}, identical: {fold_check['identical']}")
    print(f"  TRAINED-ON {len(trained_on)}   HELD-APART {len(held_apart)}")

    print(f"\nloading {ARM_B} ...")
    ce = R.load(ARM_B, provider=args.provider)
    smoke = R.smoke_test(ce)
    if not smoke.get("pass"):
        raise SystemExit("REFUSING. Arm B failed its discrimination smoke test.")
    print(f"  {ARM_B}  ({ce.params_m}M, {ce.arch}, {args.provider})  smoke PASS "
          f"(relevant {smoke['relevant']:.4f} vs irrelevant {smoke['irrelevant']:.4f})")

    b_pq = score(pools, ce, texts, base_order, gold_current)
    whole_b = summarise(b_pq, list(pools))
    print(f"\nGATE 3 -- arm B over the full fit split")
    print(f"  R@1 {whole_b['R@1']}  (published {ARM_B_PUBLISHED_R1})  "
          f"cur {whole_b['R@1_current']}  ir {whole_b['input_recall']}  "
          f"ca {whole_b['conditional_accuracy']}")
    if abs(whole_b["R@1"] - ARM_B_PUBLISHED_R1) > 1e-9:
        raise SystemExit(
            f"REFUSING (GATE 3). Arm B reads R@1 {whole_b['R@1']}; retrain-B.json publishes "
            f"{ARM_B_PUBLISHED_R1}. Its fold difference would be a number about a different scorer."
        )
    print("  GATE 3 PASSED -- arm B reproduces its published cell exactly.")

    rows = []
    for name, pq in ((ARM_B + " (arm B -- the graph the memorisation claim is about)", b_pq),
                     (SHIPPED + " (shipped -- W7's comparison point)", shipped_pq)):
        tr = summarise(pq, trained_on)
        ha = summarise(pq, held_apart)
        whole = summarise(pq, list(pools))
        rec = recombination_check([("trained_on", tr), ("held_apart", ha)], whole)
        a = int(round(tr["R@1"] * len(trained_on)))
        c = int(round(ha["R@1"] * len(held_apart)))
        p = fisher_exact_2x2(a, len(trained_on) - a, c, len(held_apart) - c)
        delta = round(tr["R@1"] - ha["R@1"], 4)
        print("\n" + "=" * 96)
        print(f"-- {name}")
        print("=" * 96)
        print(f"  {'partition':22s} {'n':>4} {'R@1':>8} {'R@1_cur':>8} {'in.rec':>8} "
              f"{'cond.acc':>9}   95% CI")
        for label, s, n in (("ALL", whole, len(pools)),
                            ("TRAINED-ON", tr, len(trained_on)),
                            ("HELD-APART", ha, len(held_apart))):
            lo, hi = clopper_pearson(int(round(s["R@1"] * n)), n)
            print(f"  {label:22s} {n:>4} {s['R@1']:>8.4f} {s['R@1_current']:>8.4f} "
                  f"{s['input_recall']:>8.4f} {s['conditional_accuracy']:>9.4f}   "
                  f"[{lo:.4f}, {hi:.4f}]")
        print(f"  DELTA trained-on - held-apart = {delta:+.4f}   Fisher exact two-sided p = {p:.4f}")
        print(f"  RECOMBINATION: reconstructs whole = {rec.get('reconstructs', rec)}")
        rows.append({"model": name, "all": whole, "trained_on": tr, "held_apart": ha,
                     "delta": delta, "fisher_p": p, "recombination": rec})

    b_delta, s_delta = rows[0]["delta"], rows[1]["delta"]
    print("\n" + "=" * 96)
    print("THE VERDICT ON THE MEMORISATION DIAGNOSIS")
    print("=" * 96)
    print(f"  arm B   trained-on minus held-apart : {b_delta:+.4f}  (p {rows[0]['fisher_p']:.4f})")
    print(f"  shipped trained-on minus held-apart : {s_delta:+.4f}  (p {rows[1]['fisher_p']:.4f})")
    print(f"  arm B's excess over the shipped graph: {b_delta - s_delta:+.4f}")
    if b_delta >= 0.10:
        verdict = ("CONFIRMED -- arm B's trained-on premium is large. It did memorise the "
                   "conversations it trained on, measured directly for the first time.")
    elif b_delta < 0.05 and rows[0]["fisher_p"] > 0.2:
        verdict = ("REFUTED -- arm B generalises WITHIN the fit split as well as the shipped "
                   "graph does. The 8x collapse is not explained by memorisation of fit-split "
                   "turns, and the standing account (selection at n=229 plus case mix) is back "
                   "in sole charge. The 'external data cannot memorise the evaluation' argument "
                   "loses its premise.")
    else:
        verdict = ("INDETERMINATE -- the delta falls between the registered bands. Report the "
                   "number, claim nothing.")
    print(f"\n  {verdict}")

    artifact = {
        "_what": "Does arm B show a trained-on premium on Session J's conversation fold? The "
                 "memorisation diagnosis for the 8x collapse, measured rather than inferred.",
        "_split": "fit",
        "_registered_prediction": "delta < +0.05 with p > 0.2, i.e. NULL, matching the shipped "
                                  "graph -- which would REFUTE the memorisation diagnosis. "
                                  "Written before the model was loaded; see the module docstring.",
        "shipped_fold_delta_from_W7": SHIPPED_FOLD_DELTA,
        "gates": {
            "shipped_fit_r1": whole_shipped["R@1"],
            "published_fit_r1": CONTROL_R1,
            "arm_b_fit_r1": whole_b["R@1"],
            "arm_b_published_fit_r1": ARM_B_PUBLISHED_R1,
            "fold_check": fold_check,
        },
        "fold": {"trained_on": trained_on, "held_apart": held_apart},
        "rows": rows,
        "verdict": verdict,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
