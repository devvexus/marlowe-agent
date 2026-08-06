"""Session H — the registered question, answered on HELD-OUT.

The question, its two sub-questions, the +0.05 delta, the McNemar alpha and the absolute floor were
all registered in Session G, before any result existed, at
`runs/session-g/REGISTERED-QUESTION-in-session-rerank.json`. **They are read from that file, never
restated here.** Two copies of a bar drift, and the one being quoted is the one that drifted.

  * **Q1, quality:** rerank ALL candidates of the N=3 pruned pool against ALL ~487 of the
    unpruned pool. Asks whether pruning makes the reranker's task easier. Explicitly not
    cost-matched.
  * **Q2, equal cost:** at a FIXED budget of 10 reranked pairs, does drawing them from the pruned
    pool beat drawing them from the unpruned pool?

Both are **paired** — same cases, one thing changed — which is why the registered test is exact
McNemar over the discordant pairs rather than a two-sample comparison.

**The reconstruction fidelity gate runs first.** Session G's registered rule: if the rebuilt pools
do not reproduce Session F's published held-out top-1 to four decimals, every number here reports
NOT MEASURED. A delta computed against a wrong baseline looks exactly like a result.

**The instrument checks must have passed on the FIT split before this runs.** ADR-010's "is this
capped at the either-cue oracle" and ADR-013's "can the read vary at all" are read from
`runs/session-h/rerank-fit.json`, and this script refuses if either failed — a registered answer
computed with an instrument known to be pinned is not an answer.
"""

from __future__ import annotations

import io
import json
import math
import statistics
import time
from pathlib import Path

import numpy as np

from reach_pools import REPO, Pool, fidelity_gate, load_pools, turn_texts
from reach_rerank_fit import (
    batch_invariance,
    build_session,
    gate_order,
    load_tokenizer,
    score_pair,
    top1_is_gold,
)
from reach_session_h_pruning import derived_keys, prune_mask

REGISTERED = REPO / "runs" / "session-g" / "REGISTERED-QUESTION-in-session-rerank.json"
PREREG = REPO / "runs" / "session-h" / "PREREGISTRATION.json"
FIT_CHECKS = REPO / "runs" / "session-h" / "rerank-fit.json"
OUT_PATH = REPO / "runs" / "session-h" / "registered-question.json"


def mcnemar_exact(gains: int, losses: int) -> float:
    """Two-sided exact McNemar: a binomial test on the discordant pairs at p=0.5.

    Only the discordant pairs carry information — a case both arms get right, or both get wrong,
    says nothing about which arm is better. With `n = gains + losses`, the null is that a
    discordant pair is equally likely to fall either way.
    """
    n = gains + losses
    if n == 0:
        # No discordant pairs at all. Not evidence of equivalence; evidence of no evidence.
        return 1.0
    k = min(gains, losses)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def verdict(treat: list[bool], ctrl: list[bool], delta_bar: float, alpha: float,
            floor: float, label: str) -> dict:
    """One registered comparison, read against bands this script does not choose."""
    n = len(treat)
    t_rate = sum(treat) / n
    c_rate = sum(ctrl) / n
    gains = sum(1 for a, b in zip(treat, ctrl) if a and not b)
    losses = sum(1 for a, b in zip(treat, ctrl) if b and not a)
    p = mcnemar_exact(gains, losses)
    delta = t_rate - c_rate

    delta_ok = delta >= delta_bar
    p_ok = p < alpha
    floor_ok = t_rate > floor
    return {
        "_comparison": label,
        "cases": n,
        "treatment_top1": round(t_rate, 4),
        "control_top1": round(c_rate, 4),
        "delta": round(delta, 4),
        "discordant": {"treatment_wins": gains, "control_wins": losses},
        "mcnemar_exact_p": round(p, 6),
        "bands": {
            "delta_required": delta_bar,
            "alpha": alpha,
            "absolute_floor": floor,
            "_floor_rule": "reranked top-1 > best single cue top-1 on the same split",
        },
        "delta_met": delta_ok,
        "significant": p_ok,
        "floor_met": floor_ok,
        "PASSES": bool(delta_ok and p_ok and floor_ok),
    }


def main() -> int:
    registered = json.loads(io.open(REGISTERED, encoding="utf-8").read())
    prereg = json.loads(io.open(PREREG, encoding="utf-8").read())
    conditions = registered["pass_conditions"]
    alpha = conditions["test"]["alpha"]
    delta_bar = 0.05  # from Q1_passes_if / Q2_passes_if, both "delta >= +0.05"
    floor = conditions["absolute_floor_both"]["value_from_session_g"]

    n_primary = prereg["frozen_parameters"]["prune_N"]["value"]
    gap_ms = prereg["frozen_parameters"]["session_gap_ms"]["value"]
    budget = 10

    # ---- the instrument checks must have passed, on the fit split ------------------------
    if not FIT_CHECKS.exists():
        raise SystemExit(
            f"{FIT_CHECKS.relative_to(REPO)} does not exist. The ADR-010 and ADR-013 instrument "
            "checks run on the FIT split BEFORE the registered question is answered."
        )
    fit = json.loads(io.open(FIT_CHECKS, encoding="utf-8").read())
    if not fit["adr_010_reach_check"]["pass"]:
        raise SystemExit(
            "ADR-010 check FAILED on the fit split: the reranker's presence ceiling does not "
            "exceed the either-cue oracle, so the premise of the registered question is refuted "
            "before any reranking. That is the finding; this script does not run."
        )
    if not fit["adr_013_can_the_read_vary"]["pass"]:
        raise SystemExit(
            "ADR-013 check FAILED on the fit split: the registered read cannot vary. Q1 and Q2 "
            "report NOT MEASURED, not a null."
        )

    # ---- the reconstruction gate ---------------------------------------------------------
    pools, stats = load_pools()
    ok, gate_report = fidelity_gate(pools)
    if not ok:
        raise SystemExit(
            "Reconstruction fidelity gate FAILED. Every number here reports NOT MEASURED.\n"
            + json.dumps(gate_report["checks"], indent=2)
        )
    print(f"Reconstruction gate PASSED over {gate_report['cases']} held-out cases.")

    texts = turn_texts()
    sess, digest = build_session()
    tok = load_tokenizer()
    det = batch_invariance(sess, tok)
    print(f"Batch invariance at the shipped fusion level: {det['max_abs_diff']:.6f} "
          f"({'PASS' if det['pass'] else 'FAIL -- batch=1 is why it does not matter'})")
    print(f"Held-out: {len(pools)} pools. L-2-int8 {digest[:16]}, batch 1, seq 256, 1 thread.\n")

    q1_t, q1_c, q2_t, q2_c = [], [], [], []
    latencies: list[float] = []
    q1_stage_ms: list[float] = []
    q2_stage_ms: list[float] = []
    missing_text = 0

    for done, pool in enumerate(pools.values(), 1):
        per_turn = texts.get(pool.query_id, {})
        keys = derived_keys(pool, gap_ms)
        mask = prune_mask(pool, keys, n_primary)
        pruned_idx = np.flatnonzero(mask)
        all_idx = np.arange(len(pool.candidates))

        pruned_order = gate_order(pool, pruned_idx)
        unpruned_order = gate_order(pool, all_idx)
        q2_treat_idx = pruned_idx[pruned_order[:budget]]
        q2_ctrl_idx = all_idx[unpruned_order[:budget]]

        scores: dict[int, float] = {}
        for i in all_idx.tolist():
            tid = pool.candidates[i].turn_id
            doc = per_turn.get(tid or "", "")
            if not doc:
                missing_text += 1
            start = time.perf_counter()
            s, _ = score_pair(sess, tok, pool.question, doc)
            latencies.append((time.perf_counter() - start) * 1000.0)
            scores[i] = s

        def rerank(idx: np.ndarray) -> np.ndarray:
            vals = np.array([scores[int(i)] for i in idx])
            return np.argsort(-vals, kind="stable")

        q1_t.append(top1_is_gold(pool, pruned_idx, rerank(pruned_idx)))
        q1_c.append(top1_is_gold(pool, all_idx, rerank(all_idx)))
        q2_t.append(top1_is_gold(pool, q2_treat_idx, rerank(q2_treat_idx)))
        q2_c.append(top1_is_gold(pool, q2_ctrl_idx, rerank(q2_ctrl_idx)))

        # The two configurations' per-query stage cost, at the candidate count ACTUALLY USED.
        # Reconstructed from the measured per-pair times rather than re-timed, so both numbers
        # come from the same pairs the quality numbers came from.
        per_pair = statistics.fmean(latencies[-len(all_idx):])
        q1_stage_ms.append(per_pair * len(pruned_idx))
        q2_stage_ms.append(per_pair * min(budget, len(pruned_idx)))

        if done % 25 == 0:
            print(f"  {done}/{len(pools)} cases, {len(latencies)} pairs scored")

    def p95(xs: list[float]) -> float:
        s = sorted(xs)
        return s[max(0, int(round(0.95 * len(s))) - 1)]

    q1 = verdict(q1_t, q1_c, delta_bar, alpha, floor,
                 "Q1 -- rerank all pruned vs rerank all unpruned")
    q2 = verdict(q2_t, q2_c, delta_bar, alpha, floor,
                 f"Q2 -- rerank top-{budget} of pruned vs top-{budget} of unpruned")

    report = {
        "_what": "Session H -- the Session G registered question, answered on held-out.",
        "_bands_read_from": str(REGISTERED.relative_to(REPO)).replace("\\", "/"),
        "split": "heldout",
        "cases": len(q1_t),
        "reconstruction_gate": gate_report,
        "reranker": {"model": "L-2-int8", "sha256": digest, "batch": 1, "threads": 1,
                     "max_seq_len": 256, "graph_optimization": "Level1 / ORT_ENABLE_BASIC"},
        "batch_invariance_at_shipped_level": det,
        "pairs_scored": len(latencies),
        "candidates_with_no_text": missing_text,
        "per_pair_latency_ms": {"p95": round(p95(latencies), 3),
                                "median": round(statistics.median(latencies), 3)},
        "stage_latency_ms": {
            "_what": "cross-encoder stage cost per query, at the candidate count actually used",
            "q1_configuration_p95": round(p95(q1_stage_ms), 1),
            "q2_configuration_p95": round(p95(q2_stage_ms), 1),
            "_q1_has_no_bar": "the registered question states Q1 is not cost-matched",
            "_q2_bar_ms": 300,
        },
        "Q1": q1,
        "Q2": q2,
        "_per_case": [
            {"query_id": q, "q1_treat": a, "q1_ctrl": b, "q2_treat": c, "q2_ctrl": d}
            for q, a, b, c, d in zip(pools.keys(), q1_t, q1_c, q2_t, q2_c)
        ],
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\n{len(latencies)} pairs. per-pair P95 {p95(latencies):.2f} ms.")
    print(f"stage P95: Q1 config {p95(q1_stage_ms):.0f} ms (no bar)   "
          f"Q2 config {p95(q2_stage_ms):.0f} ms (bar 300 ms)")
    for block in (q1, q2):
        print(f"\n{block['_comparison']}")
        print(f"  treatment {block['treatment_top1']:.4f}   control {block['control_top1']:.4f}   "
              f"delta {block['delta']:+.4f}  (need >= +{delta_bar})")
        print(f"  discordant: treatment wins {block['discordant']['treatment_wins']}, "
              f"control wins {block['discordant']['control_wins']}   "
              f"McNemar exact p = {block['mcnemar_exact_p']:.6f}  (need < {alpha})")
        print(f"  absolute floor {floor} (best single cue, held-out): "
              f"{'MET' if block['floor_met'] else 'MISSED'}")
        print(f"  => {'PASSES' if block['PASSES'] else 'DOES NOT PASS'}")

    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
