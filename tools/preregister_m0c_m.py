"""M0c Session M's pre-registration — the reranker frontier on the GPU deployment target.

Written BEFORE any reranker is scored. Refuses without the frozen split and without the fit-split
candidate dump the sweep reads, because a pre-registration whose inputs do not exist is a guess
with a filename.

    python tools/preregister_m0c_m.py          # this, first
    python tools/sweep_reranker_frontier.py    # the sweep it judges

## Why this session is not the third cue

The session opened as "build cue 3". That premise did not survive contact with the record, and the
refutation is recorded here rather than in prose so it cannot be softened later.

  * **Temporal was already measured and refuted.** Session G arm 4. Questions carrying a parseable
    window: 12/229 (5.24%); within temporal-reasoning, **1/59 (1.69%)**. Full held-out effect
    **-0.0087**, one pool emptied, one case lost gold it held at rank 1. LongMemEval's temporal
    questions are interval arithmetic over two NAMED EVENTS, not window queries.
  * **The mechanism was aimed at a solved sub-problem.** Session G's failure decomposition: solved
    148, right-session-wrong-rank 77, wrong-session 4 -- 19.2 to 1. A temporal cue over this corpus
    is a SESSION selector (turns within a session are 1 s apart, sessions are days apart), and
    session selection is worth ~4 cases.
  * **The binding constraint was never the cue set.** It was ADR-003's 300 ms P95 read against a
    1-vCPU CPU target, which admits exactly one reranker: a 2-layer, 16M-parameter MiniLM at
    depth 10.

## The correction that opened this session, stated as the measurement error it is

Every reranker cost figure this project has used to reject a model is a **1-thread CPU** number.
The deployment target is a **GPU**; 1 vCPU is the fallback floor, and the 300 ms budget derives from
brief section 9's voice path, which is only enabled where a good GPU exists.

**So the rejection numbers were scoped to the fallback and read as if they described the target.**
That is this project's standing failure family -- a measurement is scoped to the system it was taken
on -- applied to a hardware boundary.

ADR-029 (adopted, M0c Session L) already ships the CUDA path: rerank p50 **3.4 ms**, total p95
**14.7 ms** against 300 ms. **~285 ms of headroom, i.e. the rerank stage may grow ~85x.** No model
above L-2 has ever been scored for QUALITY on any hardware; Session I fetched, digest-pinned and
gated 8 of them and recorded them "deferred as UNMEASURED -- not closed, not refuted, not run".
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SPLIT_PATH = REPO / "tools" / "split.json"
FIT_POOLS = REPO / "runs" / "session-k" / "fit"
MANIFEST = REPO / "runs" / "session-i" / "reranker-manifest.json"
OUT = REPO / "runs" / "session-m0c-m" / "PREREGISTRATION.json"

# The shipped configuration, read from the immediately preceding published run rather than retyped.
SHIPPED_FIT_R1 = 0.7555
SHIPPED_FIT_R1_CURRENT = 0.6900
SHIPPED_HELDOUT_R1 = 0.6725
SHIPPED_HELDOUT_R1_CURRENT = 0.6288

# M0c Session A's floor, REUSED DELIBERATELY rather than chosen. A floor invented in the session
# that will be judged by it is a floor chosen to fit; this one predates the result by a session.
PROMOTION_FLOOR = 0.02

DEPTHS = (10, 20, 30)


def main() -> int:
    for path in (SPLIT_PATH, FIT_POOLS / "scored-candidates.ndjson", MANIFEST):
        if not path.exists():
            raise SystemExit(
                f"{path} does not exist. The pre-registration's bands are stated against these "
                "inputs; writing it without them would be a prediction about nothing."
            )
    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    rev = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO
    ).stdout.strip()

    prereg = {
        "session": "M0c Session M",
        "title": "The reranker frontier on the GPU deployment target",
        "_status": "REGISTERED BEFORE ANY RERANKER WAS SCORED",
        "registered_at_git_rev": rev,
        "registered_against_split": split["digest"],
        "corpus_sha256": split["corpus_sha256"],
        "corpus_variant": split["corpus_variant"],
        "split": {
            "redrawn": False,
            "rule": split["rule"],
            "digest": split["digest"],
            "fit_cases": split["fit_cases"],
            "heldout_cases": split["heldout_cases"],
            "note": (
                "Session B's split, unchanged since. Redrawing it would invalidate every number "
                "fit under it."
            ),
        },
        # ------------------------------------------------------------------ what is tested
        "what_is_tested": (
            "Given ADR-029's shipped CUDA path and its ~285 ms of unused budget, which admitted "
            "cross-encoder at which rerank depth maximises fit-split R@1 -- and at what GPU "
            "latency. The sweep is offline (Python/ORT) over reconstructed fit pools; the shipped "
            "Rust path is not touched until a winner exists."
        ),
        "why_offline_python_and_not_the_binary": (
            "crates/marlowe-memory/src/rerank.rs is a hand-rolled BERT WordPiece pair encoder with "
            "a digest-pinned tokenizer. bge-reranker-base and jina-v2 are XLM-RoBERTa and cannot "
            "load there at all. Measuring in Python via tools/session_i_rerankers.py -- the "
            "verified 8-model loader, per-model tokenizer, digest-checked, ORT_ENABLE_BASIC, head "
            "DETECTED then validated -- costs nothing and risks nothing. Build once, for the "
            "winner only."
        ),
        # ------------------------------------------------------------------ the disclosure
        "disclosure": {
            "_what": (
                "Before this registration was written, held-out numbers from Sessions F, G, I, K "
                "and M0c A were read while diagnosing why R@1 sits at 0.6725: the failure "
                "decomposition, input recall by depth, the L-2-vs-L-6 null, the arm-4 temporal "
                "coverage figures, and the harm/staleness analysis."
            ),
            "_why_it_is_recorded": (
                "Those reads shaped the CHOICE of this experiment. They did not produce any band "
                "below: every band is stated against the FIT split, and the held-out split is "
                "touched exactly once, at the end, for the single chosen configuration. Recording "
                "the earlier reads is what stops this from being quoted as though the design were "
                "arrived at blind."
            ),
            "heldout_values_already_seen": {
                "R@1": SHIPPED_HELDOUT_R1,
                "R@1_current": SHIPPED_HELDOUT_R1_CURRENT,
                "input_recall_depth10": 0.9039,
                "conditional_accuracy": 0.7440,
            },
        },
        # ------------------------------------------------------------------ reach check
        "reach_check": {
            "_what": "ADR-010: can the read move at all, before a band is registered on it.",
            "can_depth_move_R1": True,
            "why": (
                "Input recall by depth is measured (Session I, fit): 0.9214 at depth 10, 0.9738 at "
                "20, 0.9825 at 30, where 30 IS the whole pruned pool. Depth 10 -> 30 makes "
                "+0.0611 of gold REACHABLE that the reranker currently never sees. R@1 = "
                "input_recall x conditional_accuracy factors exactly, so the ceiling is movable."
            ),
            "can_capacity_move_R1": "UNKNOWN, and that is the point",
            "capacity_prior": (
                "L-2 -> L-6 measured +0.0131, discordant 27, exact p = 0.7011 -- a NULL WITH "
                "POWER, not an underpowered one. Session I recorded its own limit: that is a "
                "2->6 layer step inside one 16M-parameter family and 'says nothing about bge, "
                "jina or mxbai' at 278M. The prior is genuinely against capacity; the untested "
                "region is a 17x parameter jump with different pretraining."
            ),
        },
        # ------------------------------------------------------------------ the predictions
        "predicted_outcome": {
            "_status": "REGISTERED BEFORE THE SWEEP EXISTS",
            "p1_best_configuration_fit_R1": {
                "predicted_range": [0.78, 0.85],
                "against_shipped": SHIPPED_FIT_R1,
                "reasoning": (
                    "Depth 30 unlocks +0.0611 of input recall. A 278M cross-encoder should hold "
                    "conditional accuracy better than L-2 did (L-2 returned -0.0374 of it when "
                    "handed depth). Both effects are real and neither is large."
                ),
            },
            "p2_nothing_reaches_0_95": {
                "prediction": (
                    "NO configuration in this sweep reaches fit R@1 0.95, and none reaches 0.90."
                ),
                "reasoning": (
                    "R@1 0.95 at the 0.9825 recall ceiling requires conditional accuracy 0.967. "
                    "The current failures are near-ties -- median logit gap 0.435, 60% of "
                    "recoverable failures have gold at rank 2 -- and M0c Session A put four "
                    "architectures on exactly that separation, including a global cross-encoder "
                    "with no information bottleneck, and moved top-1 on 2 of 229 queries. A "
                    "bigger pretrained scorer is a different bet from a bigger head, but it is "
                    "not obviously a 22-point one."
                ),
                "_why_registered": (
                    "The goal stated for this session is 'R@1 as close to 100% as possible'. "
                    "Registering the ceiling prediction FIRST is what stops a 0.82 from being "
                    "reported as either a triumph or a failure after the fact."
                ),
            },
            "p3_depth_beats_capacity": {
                "prediction": (
                    "Depth 10 -> 30 contributes more of the total gain than model capacity does, "
                    "for every model that holds conditional accuracy."
                ),
                "what_would_refute_it": (
                    "A large model gaining at FIXED depth 10. That would reinstate the capacity "
                    "hypothesis Session I downgraded, and would be the more interesting result."
                ),
            },
            "p4_latency": {
                "prediction": (
                    "The best-quality configuration lands inside the 300 ms GPU budget. Crude "
                    "FLOP scaling from ADR-029's measured 3.4 ms: bge-base is ~24x L-2's compute "
                    "(12 layers vs 2, hidden 768 vs 384) and depth 30 is 3x, giving ~245 ms plus "
                    "~6.6 ms of non-rerank stages."
                ),
                "_this_is_an_ESTIMATE_not_a_measurement": (
                    "It is FLOP arithmetic on a 4080 SUPER, not a reading. It is registered so "
                    "that the measured value can be compared against a stated expectation rather "
                    "than rationalised. Batch 30 offers more parallelism than batch 10, so the "
                    "estimate is more likely conservative than optimistic."
                ),
            },
        },
        # ------------------------------------------------------------------ bands
        "promotion_floor": {
            "value": PROMOTION_FLOOR,
            "rule": (
                f"A configuration is promoted to a held-out confirmation only if it beats the "
                f"shipped fit R@1 of {SHIPPED_FIT_R1} by at least +{PROMOTION_FLOOR}."
            ),
            "_why_this_number": (
                "It is M0c Session A's registered floor, reused verbatim. That session's arms "
                "failed it and shipped nothing. A floor invented here would be a floor chosen by "
                "the person about to be judged by it."
            ),
            "if_nothing_clears_it": (
                "The session closes NULL and ships nothing, exactly as M0c Session A did. That is "
                "a real outcome and it is available only because this file exists first."
            ),
        },
        "absolute_floor": {
            "rule": "reranked top-1 > best single cue top-1, same split, same run",
            "_why": (
                "Session D shipped a fusion worse than its best input; the floor exists because "
                "of it. Carried from the Session G registered question."
            ),
        },
        "hard_latency_gate": {
            "budget_ms_p95": 300,
            "measured_on": "CUDA, batched, this machine (RTX 4080 SUPER), per ADR-029's shipped path",
            "rule": (
                "A configuration exceeding 300 ms P95 total retrieval on the GPU path is reported "
                "on the frontier and is NOT promotable."
            ),
            "the_cpu_fallback_is_not_gated_on_this": (
                "1 vCPU is the capability floor, not the target. A model that ships on GPU must "
                "still RUN on CPU, and its CPU latency is reported as information. The 300 ms "
                "budget derives from brief section 9's voice path, which requires a GPU."
            ),
        },
        # ------------------------------------------------------------------ reporting rules
        "reporting_rules": {
            "R1_current_beside_R1_always": (
                "LongMemEval marks both the stale and the current turn has_answer, so retrieving "
                "an outdated value scores as an R@1 hit. Fit 0.7555 -> 0.6900; held-out 0.6725 -> "
                "0.6288; knowledge-update 0.7222 -> 0.4444. A configuration that trades a "
                "merely-useless injection for a superseded one is a regression under section 5.7 "
                "and is INVISIBLE under R@1 alone. M0c Session A's slate arm was judged on R@1 "
                "only and that was insufficient."
            ),
            "factorization_reported": (
                "R@1 = input_recall x conditional_accuracy, reported as both factors for every "
                "cell. A depth change that raises recall and loses conditional accuracy nets to "
                "nothing and must be visible as that rather than as a flat number."
            ),
            "shippability_tier_reported": {
                "tier_A_drop_in": (
                    "BERT WordPiece, 30522 vocab -- L-4, L-6, L-12 and their fine-tunes. Ships "
                    "with a digest re-pin in rerank.rs and nothing else."
                ),
                "tier_B_needs_a_rust_tokenizer": (
                    "bge-reranker-base and jina-v2 are XLM-RoBERTa; mxbai and jina-turbo carry "
                    "their own conventions. Shipping one means a second tokenizer implementation "
                    "in Rust, which is real work and a real risk surface. Reported as a COST "
                    "COLUMN on the frontier, not discovered after a winner is chosen."
                ),
            },
        },
        # ------------------------------------------------------------------ what must be re-measured
        "gates_that_are_never_inherited": {
            "_the_standing_rule": (
                "Determinism, batch invariance and padding invariance are re-measured PER GRAPH "
                "and never inherited. ADR-015: re-padding bit-identical token ids moved int8 by a "
                "median 0.0109 logits and flipped top-1 in 15% of cases."
            ),
            "required_before_any_model_ships": [
                "GPU->GPU byte-identity across repeated runs (ADR-029's amended gate)",
                "cross-provider RANKING equivalence against the CPU path, top-k order",
                "node placement re-verified with tools/session_l_gpu_recovery.py -- ADR-029's "
                "explicit interim obligation after any change of graph, model or ORT version",
                "a fit-split band, because a sweep number is headroom and not validation",
            ],
            "_not_required_for_the_sweep_itself": (
                "The sweep RANKS candidates offline; it ships nothing. Applying the shipping "
                "gates to a measurement would be theatre. They bind at promotion."
            ),
        },
        # ------------------------------------------------------------------ scope fence
        "explicitly_out_of_scope": {
            "llm_reranker": (
                "Declined by the human. Not measured, not proposed, and NOT refuted -- it is the "
                "one mechanism plausibly capable of the conditional accuracy 0.95 would need, and "
                "it is recorded as untested rather than as closed."
            ),
            "trust_terms_in_the_ranker": (
                "effective_trust stays inert. The human has reserved that decision and it needs "
                "its own pre-registration."
            ),
            "the_two_existing_cues": (
                "No BM25 saturation, no cue tuning. Nine sessions of measured, mostly-negative "
                "results already cover it."
            ),
            "eval_directory": "Never modified. It is the scoreboard.",
        },
        "silently_carried_M0b_items_this_session_does_not_touch": [
            "ANN index + int8 hot vector array",
            "live-only hot index",
            "group commit on journal append",
            "consolidation as a run",
            "the query-type router",
            "cues 3, 4 and 5 -- entity-graph, temporal (refuted on this corpus) and causal",
        ],
        "depths_swept": list(DEPTHS),
        "shipped_reference": {
            "fit_R1": SHIPPED_FIT_R1,
            "fit_R1_current": SHIPPED_FIT_R1_CURRENT,
            "heldout_R1": SHIPPED_HELDOUT_R1,
            "heldout_R1_current": SHIPPED_HELDOUT_R1_CURRENT,
            "model": "ms-marco-MiniLM-L-2-v2-ft-session-j",
            "depth": 10,
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(prereg, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    print(f"  registered at {rev}")
    print(f"  split digest  {split['digest']}")
    print(f"  promotion floor +{PROMOTION_FLOOR} over fit R@1 {SHIPPED_FIT_R1}")
    print(f"  depths {DEPTHS}")
    print("\nnow run:  python tools/sweep_reranker_frontier.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
