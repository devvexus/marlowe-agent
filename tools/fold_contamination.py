"""W7 — is the FIT split contaminated for the SHIPPED reranker, and is that why everything collapses?

The shipped cross-encoder was fine-tuned ON THE FIT SPLIT (Session J). So `fit R@1 = 0.7555` is, at
least in part, an IN-SAMPLE number for the very stage that produces it, while `held-out R@1 = 0.6725`
is genuinely out-of-sample. If that is the dominant term, then the 0.083 fit/held-out gap that
Session I attributed to case mix is partly memorisation, and every fit-split head measurement in this
project is inflated by an unknown amount.

Session J used a CONVERSATION-LEVEL fold: part of the fit split supplied training pairs, the rest was
held apart and reported as `fit-val`. The fold is recoverable from
`runs/session-j/training-pairs.jsonl` (`fold` ∈ {train, val}, one row per training pair, carrying
`query_id` and `conversation_id`). This module recovers it, splits the 229 fit queries by it, and
reports the shipped graph's numbers on each half — plus the same partition on the UN-FINE-TUNED
`ms-marco-MiniLM-L-2-v2`, which never saw any of it and whose trained-on/held-apart difference is
therefore PURE CASE MIX and is the baseline to subtract.

    python tools/fold_contamination.py            # -> runs/session-m0c-m/fold-contamination.json

## Reuse, not re-implementation

The ranking key, the reorder, the R@1/R@1_current evaluator and the gate constant come from
`sweep_reranker_frontier`; the pools from `reach_pools`; the labelled head pairs from
`head_probe.build()`; the ONE cross-encoder loader from `session_i_rerankers`. Nothing here restates
a scoring rule.

## The gates

1. The shipped key must reconstruct fit R@1 = 0.7555 EXACTLY over the full 229, or the module refuses
   before emitting anything.
2. The recovered fold's held-apart query set must equal `runs/session-m0c-m/retrain-fold-breakdown.json`'s
   `held_apart_query_ids` — a set written by a different session through a different code path.
3. The partition R@1 values must RECOMBINE to the whole at the partition weights. If the parts do not
   reconstruct 0.7555, the partition is wrong and every number below is about a different split.
4. The pretrained control must reproduce its published frontier cell (R@1 0.5983 at depth 10), or its
   trained-on/held-apart difference is a number about the wrong scorer.

## Held-out is NOT read

`runs/session-k/heldout` is not opened. The 0.6725 comparison value is quoted from the record.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import numpy as np  # noqa: E402

import session_i_rerankers as R  # noqa: E402
import head_probe  # noqa: E402
from correct_case_control import cue_only_order  # noqa: E402
from reach_pools import load_pools, turn_texts  # noqa: E402
from sweep_reranker_frontier import (  # noqa: E402
    CONTROL_R1,
    FIT_POOLS,
    MAX_SEQ,
    current_gold_ids,
    reordered,
    shipped_order,
)

from marlowe_eval.datasets import longmemeval  # noqa: E402

OUT_DIR = REPO / "runs" / "session-m0c-m"
OUT_PATH = OUT_DIR / "fold-contamination.json"
PAIRS = REPO / "runs" / "session-j" / "training-pairs.jsonl"
FOLD_BREAKDOWN = OUT_DIR / "retrain-fold-breakdown.json"

SHIPPED = "ms-marco-MiniLM-L-2-v2-ft-session-j"
PRETRAINED = "ms-marco-MiniLM-L-2-v2"
PRETRAINED_PUBLISHED_R1 = 0.5983  # runs/session-m0c-m/frontier.json, depth 10
HELDOUT_PUBLISHED_R1 = 0.6725     # QUOTED from the record. Held-out is NOT read here.
DEPTH = 10


# -- gates ----------------------------------------------------------------------------------------


def gate_shipped(r1: float) -> None:
    if abs(r1 - CONTROL_R1) > 1e-9:
        raise SystemExit(
            f"REFUSING. The shipped key reconstructs fit R@1 {r1}; published is {CONTROL_R1}. "
            "Every partition below would be a plausible number about the wrong ranking."
        )


# -- the fold -------------------------------------------------------------------------------------


def recover_fold(pool_qids: set[str]) -> dict:
    """Session J's conversation-level fold, read off the pair file it was written into.

    Returns the two query-id sets restricted to the queries that actually have a reconstructed fit
    pool, plus the queries in neither (a fit query for which no training pair was mined at all).
    """
    if not PAIRS.exists():
        raise SystemExit(
            f"REFUSING. {PAIRS} does not exist. The fold is not recoverable from disk and a "
            "reconstructed fold would be a different partition."
        )
    rows = [json.loads(line) for line in io.open(PAIRS, encoding="utf-8") if line.strip()]
    train_q = {r["query_id"] for r in rows if r["fold"] == "train"}
    val_q = {r["query_id"] for r in rows if r["fold"] == "val"}
    train_c = {r["conversation_id"] for r in rows if r["fold"] == "train"}
    val_c = {r["conversation_id"] for r in rows if r["fold"] == "val"}
    if train_q & val_q:
        raise SystemExit(f"REFUSING. {len(train_q & val_q)} query ids appear in BOTH folds.")
    if train_c & val_c:
        raise SystemExit(
            f"REFUSING. {len(train_c & val_c)} CONVERSATION ids appear in both folds; the fold is "
            "not conversation-level and the held-apart half is not clean."
        )
    trained_on = sorted(train_q & pool_qids)
    held_apart = sorted(val_q & pool_qids)
    unassigned = sorted(pool_qids - train_q - val_q)
    return {
        "pairs_file": str(PAIRS.relative_to(REPO)),
        "n_pairs": len(rows),
        "n_pairs_train": sum(r["fold"] == "train" for r in rows),
        "n_pairs_val": sum(r["fold"] == "val" for r in rows),
        "train_conversation_ids": sorted(train_c),
        "val_conversation_ids": sorted(val_c),
        "n_train_conversations": len(train_c),
        "n_val_conversations": len(val_c),
        "train_query_ids_all": sorted(train_q),
        "val_query_ids_all": sorted(val_q),
        "trained_on_query_ids": trained_on,
        "held_apart_query_ids": held_apart,
        "unassigned_query_ids": unassigned,
        "n_trained_on": len(trained_on),
        "n_held_apart": len(held_apart),
        "n_unassigned": len(unassigned),
    }


def gate_fold(fold: dict) -> dict:
    """Gate 2. The recovered held-apart set must equal the one a different session wrote."""
    if not FOLD_BREAKDOWN.exists():
        raise SystemExit(f"REFUSING. {FOLD_BREAKDOWN} does not exist; the fold is unchecked.")
    there = set(json.loads(FOLD_BREAKDOWN.read_text(encoding="utf-8"))["held_apart_query_ids"])
    here = set(fold["held_apart_query_ids"])
    if here != there:
        raise SystemExit(
            "REFUSING. The recovered held-apart set disagrees with retrain-fold-breakdown.json: "
            f"{len(here - there)} here-only, {len(there - here)} there-only."
        )
    return {"here": len(here), "there": len(there), "identical": True}


# -- per-query evaluation, partitioned ------------------------------------------------------------


def per_query(pools, order_by_qid, gold_current, base_order) -> dict[str, dict]:
    """hit@1, hit@1_current and slate reach, one record per query. Same rules as `evaluate`."""
    out = {}
    for qid, pool in pools.items():
        order = order_by_qid[qid]
        top = int(order[0])
        hit1 = bool(pool.gold[top])
        cur = gold_current.get(qid, frozenset())
        slate = [int(i) for i in base_order[qid][:DEPTH]]
        out[qid] = {
            "hit1": int(hit1),
            "hit1_current": int(hit1 and pool.candidates[top].turn_id in cur),
            "hit5": int(any(pool.gold[int(i)] for i in order[:5])),
            "input_recall": int(any(pool.gold[i] for i in slate)),
            "category": pool.category,
        }
    return out


def summarise(pq: dict[str, dict], qids) -> dict:
    qids = [q for q in qids if q in pq]
    n = len(qids)
    if n == 0:
        return {"n": 0}
    r1 = sum(pq[q]["hit1"] for q in qids) / n
    cur = sum(pq[q]["hit1_current"] for q in qids) / n
    r5 = sum(pq[q]["hit5"] for q in qids) / n
    ir = sum(pq[q]["input_recall"] for q in qids) / n
    return {
        "n": n,
        "R@1": round(r1, 4),
        "hits": sum(pq[q]["hit1"] for q in qids),
        "R@1_current": round(cur, 4),
        "R@5": round(r5, 4),
        "input_recall": round(ir, 4),
        "conditional_accuracy": round(r1 / ir, 4) if ir else 0.0,
        "clopper_pearson_95": clopper_pearson(sum(pq[q]["hit1"] for q in qids), n),
    }


def clopper_pearson(k: int, n: int) -> list[float]:
    from scipy.stats import beta

    lo = 0.0 if k == 0 else float(beta.ppf(0.025, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(0.975, k + 1, n - k))
    return [round(lo, 4), round(hi, 4)]


def fisher_exact_2x2(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for [[a, b], [c, d]]."""
    from scipy.stats import fisher_exact

    return float(fisher_exact([[a, b], [c, d]])[1])


def recombination_check(parts: list[tuple[str, dict]], whole: dict) -> dict:
    """Gate 3. The partition R@1s must reconstruct the whole at the partition weights."""
    n_total = sum(p["n"] for _, p in parts)
    hits_total = sum(p["hits"] for _, p in parts)
    recomposed = hits_total / n_total if n_total else 0.0
    ok = (n_total == whole["n"]) and (hits_total == whole["hits"])
    return {
        "parts": {name: {"n": p["n"], "hits": p["hits"], "R@1": p["R@1"]} for name, p in parts},
        "sum_n": n_total,
        "sum_hits": hits_total,
        "whole_n": whole["n"],
        "whole_hits": whole["hits"],
        "recomposed_R@1": round(recomposed, 4),
        "whole_R@1": whole["R@1"],
        "reconstructs": bool(ok and abs(recomposed - whole["R@1"]) < 5e-5),
    }


# -- main -----------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
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

    print("\n" + "=" * 96)
    print("GATE 1 — the shipped key over the full fit split")
    print("=" * 96)
    print(f"  shipped key, depth {DEPTH}: R@1 {whole_shipped['R@1']}  (published {CONTROL_R1})  "
          f"R@1_current {whole_shipped['R@1_current']}  ir {whole_shipped['input_recall']}  "
          f"ca {whole_shipped['conditional_accuracy']}")
    gate_shipped(whole_shipped["R@1"])
    print("  GATE PASSED — the reconstruction reproduces the published fit R@1 exactly.\n")

    # ---- the fold -------------------------------------------------------------------------------
    fold = recover_fold(set(pools))
    fold_check = gate_fold(fold)
    trained_on = fold["trained_on_query_ids"]
    held_apart = fold["held_apart_query_ids"]
    unassigned = fold["unassigned_query_ids"]
    # The published breakdown groups the unassigned query with the trained-on half (182 = 181 + 1).
    trained_on_182 = sorted(set(trained_on) | set(unassigned))

    print("=" * 96)
    print("THE RECOVERED FOLD — Session J's conversation-level split")
    print("=" * 96)
    print(f"  source                          {fold['pairs_file']}  ({fold['n_pairs']} pairs: "
          f"{fold['n_pairs_train']} train, {fold['n_pairs_val']} val)")
    print(f"  TRAIN conversations             {fold['n_train_conversations']}")
    print(f"  VAL   conversations             {fold['n_val_conversations']}")
    print(f"  conversation-id overlap         0  (asserted; a non-zero overlap refuses)")
    print(f"  TRAIN queries (all)             {len(fold['train_query_ids_all'])}")
    print(f"  VAL   queries (all)             {len(fold['val_query_ids_all'])}")
    print(f"  -> with a reconstructed pool:   TRAINED-ON {len(trained_on)}   "
          f"HELD-APART {len(held_apart)}   UNASSIGNED {len(unassigned)}  "
          f"(total {len(trained_on) + len(held_apart) + len(unassigned)})")
    print(f"  UNASSIGNED query ids            {unassigned}  "
          "(a fit query for which no training pair was mined; grouped with trained-on to "
          "reproduce the published 182)")
    print(f"\n  GATE 2 — held-apart set vs retrain-fold-breakdown.json: "
          f"{fold_check['here']} == {fold_check['there']}, identical: {fold_check['identical']}")

    # ---- the pretrained control -----------------------------------------------------------------
    print("\n" + "=" * 96)
    print(f"THE NEGATIVE CONTROL — {PRETRAINED}, which never saw any of it")
    print("=" * 96)
    ce = R.load(PRETRAINED, provider=args.provider)
    smoke = R.smoke_test(ce)
    if not smoke.get("pass"):
        raise SystemExit("REFUSING. The pretrained control failed its discrimination smoke test.")
    print(f"  loaded {PRETRAINED}  ({ce.params_m}M, {ce.arch}, provider {args.provider})  "
          f"smoke test: PASS")
    pre_order = {}
    for qid, pool in pools.items():
        slate = [int(i) for i in base_order[qid][:DEPTH]]
        docs = [texts.get(qid, {}).get(pool.candidates[i].turn_id) or "" for i in slate]
        pre_order[qid] = reordered(pool, slate, ce.score_batch(pool.question, docs, MAX_SEQ))
    pre_pq = per_query(pools, pre_order, gold_current, base_order)
    whole_pre = summarise(pre_pq, list(pools))
    print(f"  full fit split: R@1 {whole_pre['R@1']}  (published frontier cell "
          f"{PRETRAINED_PUBLISHED_R1})  cur {whole_pre['R@1_current']}  "
          f"ir {whole_pre['input_recall']}  ca {whole_pre['conditional_accuracy']}")
    if abs(whole_pre["R@1"] - PRETRAINED_PUBLISHED_R1) > 1e-9:
        raise SystemExit(
            f"REFUSING (GATE 4). The pretrained control reads R@1 {whole_pre['R@1']}; the published "
            f"frontier cell is {PRETRAINED_PUBLISHED_R1}. Its fold difference would be a number "
            "about a different scorer."
        )
    print("  GATE 4 PASSED — the control reproduces its published cell exactly.")

    # ---- the partition --------------------------------------------------------------------------
    # A SECOND case-mix yardstick, and a purer one: the cue-only order is the shipped five-level key
    # with the cross-encoder level removed. No cross-encoder of any kind touches it, fine-tuned or
    # otherwise, so its trained-on/held-apart difference cannot contain a training effect at all.
    cue_order = {qid: cue_only_order(p) for qid, p in pools.items()}
    cue_pq = per_query(pools, cue_order, gold_current, base_order)

    models = {SHIPPED + " (SHIPPED, fine-tuned ON the fit split)": shipped_pq,
              PRETRAINED + " (PRETRAINED CONTROL, never trained)": pre_pq,
              "cue-only order (NO cross-encoder at all — purest case-mix yardstick)": cue_pq}
    partition_report = {}
    print("\n" + "=" * 96)
    print(f"THE PARTITION — fit split, depth {DEPTH}, split by Session J's training fold")
    print("=" * 96)
    for label, pq in models.items():
        whole = summarise(pq, list(pools))
        t = summarise(pq, trained_on)
        h = summarise(pq, held_apart)
        u = summarise(pq, unassigned)
        t182 = summarise(pq, trained_on_182)
        rec = recombination_check([("trained_on_181", t), ("held_apart_47", h),
                                   ("unassigned_1", u)], whole)
        # Is the trained-on/held-apart difference itself distinguishable from zero?
        p = fisher_exact_2x2(t182["hits"], t182["n"] - t182["hits"],
                             h["hits"], h["n"] - h["hits"])
        print(f"\n-- {label}")
        print(f"  {'partition':<22} {'n':>4} {'R@1':>8} {'R@1_cur':>8} {'in.rec':>8} "
              f"{'cond.acc':>9} {'95% CI on R@1':>18}")
        for name, s in (("ALL", whole), ("TRAINED-ON (182)", t182), ("  of which mined (181)", t),
                        ("  unassigned (1)", u), ("HELD-APART (47)", h)):
            if s["n"] == 0:
                continue
            ci = s["clopper_pearson_95"]
            print(f"  {name:<22} {s['n']:>4} {s['R@1']:>8.4f} {s['R@1_current']:>8.4f} "
                  f"{s['input_recall']:>8.4f} {s['conditional_accuracy']:>9.4f} "
                  f"{'[' + format(ci[0], '.4f') + ', ' + format(ci[1], '.4f') + ']':>18}")
        delta = round(t182["R@1"] - h["R@1"], 4)
        print(f"  DELTA trained-on(182) - held-apart(47) = {delta:+.4f}   "
              f"Fisher exact two-sided p = {p:.4f}")
        print(f"  RECOMBINATION: {rec['sum_hits']}/{rec['sum_n']} = {rec['recomposed_R@1']} vs "
              f"whole {rec['whole_R@1']}  -> reconstructs: {rec['reconstructs']}")
        if not rec["reconstructs"]:
            raise SystemExit("REFUSING (GATE 3). The parts do not reconstruct the whole. The "
                             "partition is wrong and every number above is about a different split.")
        partition_report[label] = {
            "all": whole, "trained_on_182": t182, "trained_on_mined_181": t,
            "unassigned_1": u, "held_apart_47": h,
            "delta_trained_minus_held_apart": delta,
            "fisher_exact_two_sided_p": round(p, 4),
            "recombination": rec,
        }

    # ---- the three-number comparison ------------------------------------------------------------
    sh = partition_report[SHIPPED + " (SHIPPED, fine-tuned ON the fit split)"]
    pr = partition_report[PRETRAINED + " (PRETRAINED CONTROL, never trained)"]
    contamination = round(sh["delta_trained_minus_held_apart"]
                          - pr["delta_trained_minus_held_apart"], 4)
    print("\n" + "=" * 96)
    print("THE COMPARISON THAT MATTERS")
    print("=" * 96)
    print(f"  R@1 on TRAINED-ON fit conversations (182)   {sh['trained_on_182']['R@1']:.4f}")
    print(f"  R@1 on the HELD-APART fit fold (47)         {sh['held_apart_47']['R@1']:.4f}  "
          f"95% CI [{sh['held_apart_47']['clopper_pearson_95'][0]:.4f}, "
          f"{sh['held_apart_47']['clopper_pearson_95'][1]:.4f}]")
    print(f"  R@1 on the full fit split (229)             {sh['all']['R@1']:.4f}")
    print(f"  HELD-OUT R@1 (QUOTED, not read)             {HELDOUT_PUBLISHED_R1:.4f}")
    print(f"\n  shipped     trained-on - held-apart = {sh['delta_trained_minus_held_apart']:+.4f}")
    print(f"  pretrained  trained-on - held-apart = {pr['delta_trained_minus_held_apart']:+.4f}"
          "   <- pure case mix; nothing to memorise")
    print(f"  CONTAMINATION ESTIMATE (difference of differences) = {contamination:+.4f}")
    print(f"  fit(229) - held-out gap                    "
          f"{sh['all']['R@1'] - HELDOUT_PUBLISHED_R1:+.4f}")
    print(f"  held-apart(47) - held-out gap              "
          f"{sh['held_apart_47']['R@1'] - HELDOUT_PUBLISHED_R1:+.4f}")

    # ---- the interaction, tested rather than eyeballed --------------------------------------------
    # The difference-of-differences is the estimate. At n = 47 on one side it needs a p-value, and a
    # permutation over the FOLD LABEL is the assumption-free one: reassign which queries are
    # "held apart" at random, keeping 182/47, and recompute the DiD. This asks exactly "would a
    # random split of the fit queries produce a gap this big?"
    print("\n" + "=" * 96)
    print("THE INTERACTION — permutation test over the fold label (10,000 draws, seed 7)")
    print("=" * 96)
    rng = np.random.default_rng(7)
    qids = sorted(pools)
    interaction = {}
    for ctrl_label, ctrl_pq in (("pretrained", pre_pq), ("cue-only", cue_pq)):
        sh_hits = np.array([shipped_pq[q]["hit1"] for q in qids], float)
        ct_hits = np.array([ctrl_pq[q]["hit1"] for q in qids], float)
        is_held = np.array([q in set(held_apart) for q in qids])

        def did(mask):
            t, h = ~mask, mask
            return ((sh_hits[t].mean() - sh_hits[h].mean())
                    - (ct_hits[t].mean() - ct_hits[h].mean()))

        obs = did(is_held)
        n_held = int(is_held.sum())
        draws = np.empty(10_000)
        idx = np.arange(len(qids))
        for i in range(10_000):
            m = np.zeros(len(qids), bool)
            m[rng.choice(idx, n_held, replace=False)] = True
            draws[i] = did(m)
        p = float((np.abs(draws) >= abs(obs) - 1e-12).mean())
        gain_t = sh_hits[~is_held].mean() - ct_hits[~is_held].mean()
        gain_h = sh_hits[is_held].mean() - ct_hits[is_held].mean()
        print(f"  vs {ctrl_label:<12} fine-tune gain on TRAINED-ON {gain_t:+.4f}   "
              f"on HELD-APART {gain_h:+.4f}   DiD {obs:+.4f}   permutation p = {p:.4f}")
        interaction[ctrl_label] = {
            "fine_tune_gain_trained_on": round(float(gain_t), 4),
            "fine_tune_gain_held_apart": round(float(gain_h), 4),
            "difference_of_differences": round(float(obs), 4),
            "permutation_p_two_sided": round(p, 4),
            "n_draws": 10_000, "seed": 7,
        }

    # ---- the head pairs -------------------------------------------------------------------------
    print("\n" + "=" * 96)
    print("THE HEAD PAIRS — head_probe.build(), split by the same fold")
    print("=" * 96)
    _hp_pools, pairs, hp_r1 = head_probe.build()
    label_by_qid = {p["query_id"]: p["label"] for p in pairs}
    head_split = {}
    print(f"  {'partition':<22} {'n':>5} {'POSITIVE':>9} {'NEGATIVE':>9} {'AMBIGUOUS':>10} "
          f"{'POS rate':>9} {'NEG rate':>9}")
    for name, qids in (("ALL", list(pools)), ("TRAINED-ON (182)", trained_on_182),
                       ("HELD-APART (47)", held_apart)):
        c = Counter(label_by_qid[q] for q in qids if q in label_by_qid)
        n = sum(c.values())
        head_split[name] = {"n": n, "POSITIVE": c["POSITIVE"], "NEGATIVE": c["NEGATIVE"],
                            "AMBIGUOUS": c["AMBIGUOUS"],
                            "positive_rate": round(c["POSITIVE"] / n, 4) if n else 0.0,
                            "negative_rate": round(c["NEGATIVE"] / n, 4) if n else 0.0}
        print(f"  {name:<22} {n:>5} {c['POSITIVE']:>9} {c['NEGATIVE']:>9} {c['AMBIGUOUS']:>10} "
              f"{head_split[name]['positive_rate']:>9.4f} "
              f"{head_split[name]['negative_rate']:>9.4f}")
    ts, hs = head_split["TRAINED-ON (182)"], head_split["HELD-APART (47)"]
    p_pos = fisher_exact_2x2(ts["POSITIVE"], ts["n"] - ts["POSITIVE"],
                             hs["POSITIVE"], hs["n"] - hs["POSITIVE"])
    p_neg = fisher_exact_2x2(ts["NEGATIVE"], ts["n"] - ts["NEGATIVE"],
                             hs["NEGATIVE"], hs["n"] - hs["NEGATIVE"])
    print(f"\n  POSITIVE rate, trained-on vs held-apart: Fisher exact two-sided p = {p_pos:.4f}")
    print(f"  NEGATIVE rate, trained-on vs held-apart: Fisher exact two-sided p = {p_neg:.4f}")
    print("  (POSITIVE = a rank-1/rank-2 flip FIXES the case; NEGATIVE = a flip BREAKS it. The "
          "26/110 ratio is the bar every tie-break rule has to beat.)")

    artifact = {
        "_what": "W7 — fit-split fold contamination. The shipped cross-encoder was fine-tuned on "
                 "the fit split (Session J); this splits the 229 fit queries by Session J's own "
                 "conversation-level fold and reports the shipped graph and an untrained control "
                 "on each half.",
        "_split": "fit ONLY. runs/session-k/heldout was not opened; 0.6725 is quoted from the record.",
        "_depth": DEPTH,
        "_provider": args.provider,
        "gates": {
            "1_shipped_key_reproduces_published_fit_r1": {
                "reconstructed": whole_shipped["R@1"], "published": CONTROL_R1, "passed": True},
            "2_held_apart_set_matches_retrain_fold_breakdown": fold_check,
            "3_recombination": {k: v["recombination"] for k, v in partition_report.items()},
            "4_pretrained_control_reproduces_frontier_cell": {
                "reconstructed": whole_pre["R@1"], "published": PRETRAINED_PUBLISHED_R1,
                "passed": True},
        },
        "fold": fold,
        "partition": partition_report,
        "contamination_estimate_difference_of_differences": contamination,
        "interaction_permutation_test": interaction,
        "heldout_r_at_1_quoted_not_read": HELDOUT_PUBLISHED_R1,
        "head_pairs": {
            "head_probe_gate_r1": hp_r1,
            "split": head_split,
            "fisher_positive_rate_p": round(p_pos, 4),
            "fisher_negative_rate_p": round(p_neg, 4),
        },
        "per_query": {
            SHIPPED: shipped_pq,
            PRETRAINED: pre_pq,
            "cue_only_order": cue_pq,
        },
        "_caveat_on_the_held_apart_47": (
            "The held-apart 47 IS Session J's model-selection set — the best epoch of the shipped "
            "graph was chosen by fit-val R@1 over exactly these queries. So it is not trained-on, "
            "but it is not an independent test either: it is selected-on. It bounds memorisation of "
            "specific competitor turns, not selection on the fold."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
