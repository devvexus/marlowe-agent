"""A FORWARD REGISTRATION, written in Session G for a future session to measure.

Session G's arm 1 produced a failure decomposition that reframes the problem:

    at N=3, wrong_session = 4    right_session_wrong_rank = 77    solved = 148

Session selection is close to solved. The residual failure is ranking **inside a correct session**
of ~47 turns, not ranking ~487 turns. Every prior session attacked the second problem.

This file registers the question that observation raises, **before** anyone measures it, so the
pass condition cannot be assembled around a result. It measures nothing itself.

---

## This is NOT a revival of Session G's failed condition, and the difference is the point

Session G registered a *shortlist-equivalence* condition -- `R@10 pruned >= R@20 unpruned - 0.01`
-- as the thing that would justify re-opening the cross-encoder on budget grounds. **It FAILED at
every N and every ranker** (oracle 0.9563 vs a required 0.9769). That verdict stands, is recorded
as a fail, and is not reinterpreted here.

The failed condition asked: *can a cheaper shortlist carry as much gold as a more expensive one?*
Answer: no.

This registration asks a different question that the decomposition is direct evidence for: *is
reranking a small, topically coherent, correct session an easier task than reranking a large mixed
pool?* Session G measured neither, and the 19:1 ratio between wrong-rank and wrong-session failures
is what motivates asking.

Registering it as a new question with a new bar -- rather than as a second reading of the old one
-- is the whole discipline. Session D's escalation read is on the record as confounded precisely
because it was assembled after a disappointing number.

**Nothing here reinstates the cross-encoder.** Adoption still requires its own latency pass at the
candidate count actually used, plus re-verified determinism. A quality win at an unaffordable cost
is not an adoption, and this file does not create one.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "runs" / "session-g" / "REGISTERED-QUESTION-in-session-rerank.json"
ARM1 = ROOT / "runs" / "session-g" / "arm1-pruning.json"

PROMOTE_DELTA = 0.05
MCNEMAR_ALPHA = 0.05


def main() -> int:
    if OUT.exists():
        print(f"REFUSING: {OUT.relative_to(ROOT)} already exists.", file=sys.stderr)
        print("A forward registration is written once, before the measurement.", file=sys.stderr)
        return 2
    if not ARM1.exists():
        print("REFUSING: arm 1's result is the motivating evidence and is missing.", file=sys.stderr)
        return 2

    arm1 = json.loads(io.open(ARM1, encoding="utf-8").read())
    primary = [r for r in arm1["results"] if r["aggregation"] == "max" and r["mode"] == "union"]
    at_n3 = next(r for r in primary if r["N"] == 3)
    decomp = at_n3["failure_decomposition"]
    baseline = arm1["unpruned_baseline"]

    doc = {
        "_status": "REGISTERED IN SESSION G, TO BE MEASURED IN A LATER SESSION. Not measured here.",
        "question": (
            "Does reranking the ~47 turns of a correctly-selected session beat ranking the ~487 "
            "turns of the full pool?"
        ),
        "motivating_evidence": {
            "source": "runs/session-g/arm1-pruning.json, primary variant at N=3",
            "wrong_session": decomp.get("wrong_session"),
            "right_session_wrong_rank": decomp.get("right_session_wrong_rank"),
            "solved": decomp.get("solved"),
            "ratio_wrong_rank_to_wrong_session": round(
                decomp.get("right_session_wrong_rank", 0) / max(decomp.get("wrong_session", 1), 1), 1
            ),
            "surviving_pool_fraction": at_n3["surviving_pool_fraction_mean"],
            "gold_retention": at_n3["gold_retention"],
            "reading": (
                "Session selection is close to solved and the residual is a within-session ranking "
                "failure. That is a different problem from the one Sessions D, E and F attacked."
            ),
        },
        "why_this_is_not_a_revival_of_the_failed_condition": {
            "the_failed_condition": "R@10 pruned at N >= R@20 unpruned - 0.01",
            "its_verdict": "FAILED at every N and every ranker; oracle 0.9563 against a required 0.9769",
            "it_stands": True,
            "what_it_asked": "can a cheaper shortlist carry as much gold as a more expensive one",
            "what_this_asks": (
                "is reranking a small, topically coherent, CORRECT session an easier task than "
                "reranking a large mixed pool"
            ),
            "_why_a_new_registration_and_not_a_second_reading": (
                "A second reading of a failed condition is how a null becomes a positive without "
                "new evidence. Session D's escalation read is already recorded as confounded for "
                "exactly that reason."
            ),
        },
        "two_sub_questions_registered_separately": {
            "Q1_quality_unequal_cost": {
                "_what": (
                    "Rerank ALL candidates in the arm-1 N=3 pruned pool (~50) against reranking ALL "
                    "candidates in the unpruned pool (~487), same reranker."
                ),
                "asks": "does pruning make the reranker's task easier",
                "_note": "Not cost-matched. Answers the question as posed, and nothing about budget.",
            },
            "Q2_quality_at_equal_cost": {
                "_what": (
                    "At a FIXED budget of 10 reranked pairs, does drawing those 10 from the pruned "
                    "pool beat drawing them from the unpruned pool?"
                ),
                "asks": "does pruning improve what a fixed reranking budget can buy",
                "_why_both": (
                    "Q1 alone can be won by spending more compute, which is not a finding. Q2 alone "
                    "cannot distinguish 'pruning helps' from 'the shortlist was already fine'."
                ),
            },
        },
        "pass_conditions": {
            "primary_quantity": "top-1 accuracy after reranking, held-out, paired",
            "test": {
                "name": "exact McNemar (two-sided binomial on discordant pairs)",
                "alpha": MCNEMAR_ALPHA,
                "_why": "The comparisons are paired -- same cases, one thing changed.",
            },
            "Q1_passes_if": f"delta >= +{PROMOTE_DELTA} vs reranking the unpruned pool, p < {MCNEMAR_ALPHA}",
            "Q2_passes_if": f"delta >= +{PROMOTE_DELTA} vs the unpruned top-10, p < {MCNEMAR_ALPHA}",
            "absolute_floor_both": {
                "rule": "reranked top-1 > best single cue top-1 on the same split",
                "value_from_session_g": baseline["lexical@1"],
                "_why": (
                    "A reranker that does not beat BM25 alone is not a reranker. Session D shipped "
                    "a fusion worse than its best input and the floor exists because of it."
                ),
            },
        },
        "what_would_refute_the_premise": (
            "In-session reranking landing at or below full-pool reranking. That would say the "
            "distractors that outrank gold are gold's own session-mates, and removing "
            "cross-session distractors removes nothing that was winning -- which is exactly what "
            "Session G's registered prediction for arm 1 said, and which the vacuous oracle read "
            "left untested at top-1."
        ),
        "explicitly_still_required_before_any_adoption": [
            "a latency pass at the candidate count actually used, at 1 thread, per ADR-003's VPS shape",
            "re-verified determinism for the specific graph (int8 and L-2 are not the graph the spike proved)",
            "a fit-split band, because every number in Session G is held-out and is headroom, not validation",
        ],
        "_this_file_measures_nothing": (
            "It exists so that whoever runs the experiment cannot choose the bar after seeing the "
            "number. If the bar looks wrong when the result arrives, argue it explicitly and record "
            "the argument -- do not move it."
        ),
    }

    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {OUT.relative_to(ROOT)}")
    print(f"  motivating ratio   {doc['motivating_evidence']['ratio_wrong_rank_to_wrong_session']}:1 "
          f"wrong-rank to wrong-session at N=3")
    print(f"  Q1 / Q2 pass at    delta >= +{PROMOTE_DELTA}, McNemar p < {MCNEMAR_ALPHA}")
    print(f"  absolute floor     top-1 > {baseline['lexical@1']} (best single cue)")
    print("\nRegistered for a LATER session. Nothing is measured here, and this does not")
    print("reinstate the cross-encoder -- Session G's shortlist condition failed and stands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
