"""Session I — the pre-registration. Written BEFORE any sweep number exists.

Refuses to run unless every Phase 0 and Phase 1 artifact is present, because this registration
rests on them: the arm order comes from a rule evaluated against the Phase 0.2 decomposition, and
the sweepable cells come from the Phase 1.2 reachability grid. A registration that asserted either
from memory would be a registration of an intention.

    python tools/preregister_session_i.py
"""

from __future__ import annotations

import io
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_PATH = REPO / "runs" / "session-i" / "PREREGISTRATION.json"

REQUIRED = {
    "identity": "runs/session-i/pipeline-identity.json",
    "decomposition": "runs/session-i/failure-decomposition.json",
    "truncation": "runs/session-i/truncation-grid.json",
    "model_gate": "runs/session-i/model-gate.json",
    "manifest": "runs/session-i/reranker-manifest.json",
}


def main() -> int:
    art = {}
    for key, rel in REQUIRED.items():
        path = REPO / rel
        if not path.exists():
            raise SystemExit(
                f"{rel} is missing. This registration is derived from the Phase 0 and Phase 1 "
                "measurements; without them it would be asserting reachability rather than "
                "recording it."
            )
        art[key] = json.loads(io.open(path, encoding="utf-8").read())

    admitted = art["model_gate"]["admitted"]
    depth_table = art["decomposition"]["input_recall_by_depth"]
    rule = art["decomposition"]["arm_selection_rule"]

    prereg = {
        "_what": "M0b Session I pre-registration. Rank-1 discrimination. Written before any sweep.",
        "written_before": "any Session I quality number at any depth, sequence length or window",
        "target": {
            "primary": "R@1 >= 0.80 on the held-out split",
            "read_against": (
                "CONDITIONAL ACCURACY, not R@1 alone. R@1 factors exactly into "
                "input_recall x conditional_accuracy. Held-out today: 0.5764 = 0.9039 x 0.6377. "
                "Only conditional accuracy is what capacity, sequence length or context can move; "
                "input recall is set by depth and by pruning."
            ),
            "what_080_demands": {
                "at_depth_10": {"input_recall": 0.9214, "conditional_accuracy_required": 0.8682},
                "at_depth_20": {"input_recall": 0.9738, "conditional_accuracy_required": 0.8215},
                "at_depth_30": {"input_recall": 0.9825, "conditional_accuracy_required": 0.8142},
                "_fit_split_figures": True,
                "_note": (
                    "Conditional accuracy is 0.6730 on fit today. Even the most favourable depth "
                    "asks for a 21% relative improvement in discrimination, and depth 10 asks for "
                    "29%. Registered so that a 0.72 outcome is read as the predicted range rather "
                    "than as a surprise."
                ),
            },
            "latency": "RECORDED, never a stop. Two columns: wins-on-quality and can-ship.",
            "no_llm_calls": True,
        },

        # -------------------------------------------------------------------------------------
        "arm_order": {
            "_chosen_by": (
                "the rule registered in tools/session_i_decompose.py's docstring, ABOVE the "
                "numbers it selects on, and evaluated mechanically against the Phase 0.2 "
                "decomposition. Not chosen by the order STATE.md lists the arms in."
            ),
            "rule_verdicts": rule,
            "order": [
                {"arm": "2 - capacity", "why": "RULE 1 fired: 49.4% of failures sit at rank 2-3."},
                {"arm": "3 - depth", "why": (
                    "RULE 3 fired: 20.7% of failures are gold absent from the slate. Depth is "
                    "mandatory, and the depth table below shows where it saturates.")},
                {"arm": "0 - sequence length", "why": (
                    "NEW, not in the approved plan. RULE 4 fired on both sub-conditions, and the "
                    "shipped seq 256 truncates gold in 7.86% of fit cases. Promoted ahead of arm 1 "
                    "because a context sweep at a fixed sequence length confounds context with "
                    "truncation and neither reading would be attributable.")},
                {"arm": "1 - context", "why": (
                    "RULE 2 was SILENT (spread 0.287 against a 0.15 bar), so context does NOT "
                    "lead. It runs at the sequence length and neighbour cap arm 0 selects.")},
                {"arm": "7 - structural features", "why": "RULE 4 fired; promoted from optional."},
                {"arm": "4 - cascade", "why": (
                    "CONDITIONAL. Becomes the SHIPPING question rather than an optional arm if a "
                    "large model wins on quality -- bge-base is 381 ms/pair, 7.6 s/query at depth "
                    "20, against ADR-003's 1-vCPU target.")},
                {"arm": "5 - ensemble", "why": "CONDITIONAL on Spearman < 0.7 between architectures."},
            ],
            "arm_6_reclassified": {
                "arm": "6 - per-query normalization of rerank scores",
                "verdict": "CANNOT MOVE R@1. No band is registered on it.",
                "proof": (
                    "Per-query normalization is a strictly increasing transform within a query; "
                    "R@1 is a within-query ordering read. The transform leaves the ordering "
                    "bit-identical, so the read is an identity -- the same defect as Session H's "
                    "arm 1 (ADR-011) and Session G's registered read (ADR-013). It is reclassified "
                    "into the precision-at-coverage deliverable, where it is a cross-query "
                    "decision and CAN vary."
                ),
            },
        },

        # -------------------------------------------------------------------------------------
        "scope": {
            "_narrowed": (
                "TIME-CONSTRAINED. The full sweep is NOT run. Registered here before any sweep "
                "number exists, so the narrowing is a recorded decision and not a result of "
                "looking at partial numbers and stopping where they were favourable."
            ),
            "P1_truncation_defect_fix": {
                "change": "MAX_SEQ_LEN 256 -> 512 on the shipped L-2-int8, depth 10, window 0",
                "everything_else": "identical -- same model, same digest, same pruning, same gate key",
                "status": "A DEFECT FIX, NOT AN ARM. The binary cannot fully read the correct "
                          "answer in 1 case in 13.",
                "measured_on": ["fit", "then held-out"],
                "reads": ["R@1", "conditional_accuracy", "input_recall"],
                "ship_if": "it holds on held-out",
            },
            "P2_arm_0_minimum_breadth": {
                "contrast": "seq 512 vs seq 256, same model, same depth, same window",
                "question": "was truncation MANUFACTURING the length bias?",
                "hypotheses": {
                    "a": "the reranker genuinely prefers long passages -- a known MS MARCO artifact",
                    "b": "truncation manufactures the score by cutting a long distractor down to "
                         "its most query-like opening",
                },
                "distinguishing_read": (
                    "the rank-1 distractor's word-piece distribution at BOTH sequence lengths. "
                    "Phase 0.2 measured it at seq 256: median 131, p75 406, p95 654, against gold's "
                    "median 70 and 47.1% assistant-authored against a 12.3% base rate. If long "
                    "assistant turns stop dominating failures at 512, hypothesis (b) is confirmed "
                    "and the defect fix IS the finding."
                ),
                "_predeclared": (
                    "This prediction is registered before the 512 measurement exists. If the "
                    "distribution is UNCHANGED at 512, hypothesis (a) holds, the length bias is a "
                    "property of the model rather than of the configuration, and the honest report "
                    "is that the defect fix did not explain the failures."
                ),
            },
            "P3_capacity_one_model_if_time": {
                "model": "ms-marco-MiniLM-L-6-v2 (f32)", "depth": 10, "seq": 512, "window": "0",
                "why_this_one": (
                    "RULE 1's block is the largest (49.4% of failures at ranks 2-3) and L-6 is 57 "
                    "ms/pair -- about 2 minutes on fit. It is the most capacity per minute available."
                ),
                "why_not_the_others": (
                    "L-12 at 113 ms/pair, and bge-base / jina-v2 / mxbai at 381-462 ms/pair are "
                    "7.6-9.2 s/query at depth 20. They cannot ship on ADR-003's 1-vCPU target "
                    "regardless of quality, and the cascade that would rescue them is deferred."
                ),
                "confound_noted": (
                    "L-6-f32 against L-2-int8 varies BOTH capacity and precision. The clean "
                    "comparison is L-6-f32 against L-2-f32; if time permits only one, the delta is "
                    "reported as capacity-plus-precision and NOT attributed to capacity alone."
                ),
            },
            "DEFERRED_and_why_a_later_session_starts_from_phase_1": {
                "arms": ["1 - context", "3 - depth grid", "4 - cascade", "5 - ensemble",
                         "7 - structural features"],
                "status": "UNMEASURED. Not closed, not refuted -- not run.",
                "already_done_and_reusable": [
                    "runs/session-i/reranker-manifest.json -- 8 models pinned by revision AND sha256",
                    "runs/session-i/model-gate.json -- all 9 admitted, with measured ms/pair",
                    "runs/session-i/truncation-grid.json -- the reachable (window, cap, seq) cells",
                    "runs/session-i/failure-decomposition.json -- the fit-split failure profile",
                    "runs/session-i/pipeline-identity.json -- fit and held-out proven identical",
                ],
                "_the_point": (
                    "A later session resumes at Phase 2 with the reachability, acquisition and "
                    "decomposition work already banked. It does not repeat Phase 0 or Phase 1."
                ),
            },
        },

        # -------------------------------------------------------------------------------------
        "adr_010_reachability": {
            "_rule": "an arm must be shown able to move the metric BEFORE a band is registered.",
            "arm_2_capacity": {
                "reachable": True,
                "evidence": (
                    "conditional accuracy is 0.6730 on fit against an in-slate ceiling of 1.0. "
                    "All nine models pass the discrimination gate with distinct score scales."
                ),
            },
            "arm_3_depth": {
                "reachable": True,
                "evidence": "input recall rises 0.9214 -> 0.9738 -> 0.9825 across depths 10/20/30.",
                "saturation": {"at_depth": 30, "value": 0.9825,
                               "_equals": "the whole pruned pool -- beyond 30 there is nothing to buy"},
                "depth_table": depth_table,
            },
            "arm_0_sequence_length": {
                "reachable": True,
                "evidence": (
                    "gold survives tokenization in 0.9214 at seq 256, 0.9782 at 384 and 0.9869 at "
                    "512 (MiniLM family, window 0). The shipped configuration is the unreachable "
                    "one."
                ),
            },
            "arm_1_context": {
                "reachable": "ONLY IN THE CELLS LISTED IN truncation-grid.json",
                "evidence": (
                    "an UNCAPPED +/-1 window is 733 word pieces at the median and survives in only "
                    "0.4148 of cases at seq 256 -- unreachable at every sequence length these "
                    "models support. With a per-neighbour cap of 32-64 at seq 512, survival is "
                    "0.982-0.987 and the arm becomes reachable. Cells below 0.98 are NOT SWEPT."
                ),
                "_the_trap_avoided": (
                    "run uncapped at 256, arm 1 would have read 'context does not help' while "
                    "measuring truncation."
                ),
            },
        },

        "adr_013_the_read_must_vary": {
            "_rule": "verify the READ can vary, not merely that the mechanism could move something.",
            "requirement": (
                "for every arm, count fit-split cases where the arm CHANGES top-1 against its "
                "comparator, and require movement in BOTH directions before reporting a delta."
            ),
            "min_discordant_for_a_reported_delta": 10,
        },

        "adr_014_power": {
            "_rule": "BINDING. Session H's registered alpha was unattainable at any outcome.",
            "arithmetic": (
                "Exact McNemar is a binomial over the DISCORDANT PAIRS ONLY. The smallest "
                "attainable two-sided p is 2/2^n: 1.000 at n=1, 0.250 at n=3, 0.0625 at n=5, "
                "0.03125 at n=6."
            ),
            "structural_floor": {"alpha": 0.05, "minimum_discordant_n": 6},
            "requirement": [
                "Discordance is measured ON FIT, on the EXACT CONTRAST the held-out test will "
                "consume -- not on a proxy, which is precisely what Session H's instrument check "
                "did wrong.",
                "If the fit-measured discordant count is below 6, alpha is declared UNATTAINABLE "
                "IN ADVANCE and no p-value is reported for that contrast; the delta carries the "
                "verdict alone and is labelled as such.",
                "A realistic split needs materially more than 6. The fit-measured n is reported "
                "beside every p-value so the reader can see what the test could have detected.",
            ],
            "contrasts_that_will_be_tested": [
                "C1 seq 512 vs seq 256, shipped L-2-int8, depth 10, window 0 -- the defect fix",
                "C3 L-6-f32 vs L-2-int8 at seq 512, depth 10 -- capacity, ONLY IF TIME",
            ],
            "_contrasts_not_tested_because_the_scope_narrowed": [
                "depth, context, cascade, ensemble, structural features -- see scope.DEFERRED",
            ],
            "_when_measured": (
                "fit discordance for each contrast is computed during the sweep and written into "
                "this session's results BEFORE the single held-out read is taken."
            ),
        },

        # -------------------------------------------------------------------------------------
        "structurally_pinned_rows": {
            "_what": "rows that CANNOT move in this session, registered in advance as pinned so no",
            "_what2": "later reading mistakes an identity for a measurement.",
            "ceiling_max_calibrated_precision": {
                "value": 0.3739,
                "why": (
                    "the gate is NOT refit in this session and reranking happens after "
                    "features::extract_all, so every candidate's calibrated_precision is "
                    "bit-identical to Session F's. Reordering a slate cannot change a maximum over "
                    "it."
                ),
            },
            "single_cue_and_either_cue_top1": {
                "why": (
                    "pruning is unchanged, and Session G's max-aggregation identity is "
                    "partition-independent. No arm in this session touches the first stage."
                ),
            },
            "input_recall_at_a_given_depth": {
                "why": (
                    "it is set by the gate key's rank of gold and by pruning, neither of which any "
                    "arm here modifies. It is a property of the DEPTH, not of the reranker -- "
                    "which is exactly why it is a ceiling on that depth's R@1."
                ),
            },
            "_the_gate_is_not_refit": (
                "changing depth changes which candidates the gate key DRAWS into the slate. The "
                "gate's weights are untouched. This is not a refit and must not be read as one."
            ),
        },

        # -------------------------------------------------------------------------------------
        "corrections_to_prior_sessions": {
            "_why_here": (
                "STATE.md is what a later session inherits. A correction that lives only in a "
                "runs/ artifact is a correction nobody reads."
            ),
            "shipped_binary_truncates_gold": {
                "finding": "query + gold turn fits in seq 256 in only 211/229 = 0.9214 of fit cases",
                "status": "A DEFECT IN THE SHIPPED BINARY, not a constraint on this sweep",
                "consequence": "R@1 0.5764 was measured on a configuration truncating 7.86% of gold",
                "independence_checked": {
                    "_question": "is 0.9214 appearing twice a coupling or a coincidence?",
                    "answer": "coincidence; the two sets of 211 are DIFFERENT sets",
                    "intersection": 194, "a_only": 17, "b_only": 17, "neither": 1,
                    "p_a_and_b": 0.8472, "independence_prediction": 0.8490,
                    "joint_headroom": (
                        "0.8472 of cases have gold both in the slate AND untruncated -- below "
                        "either factor alone, and the shipped configuration's real headroom"
                    ),
                },
            },
            "batch_invariance_was_quantization_not_architecture": {
                "finding": "all eight f32 graphs are batch-invariant to 0.000000; int8 L-2 fails at 0.0958",
                "supersedes": "STATE.md reading as though batching is unsafe for cross-encoders generally",
                "consequence": (
                    "batch = 1 is a constraint on the INT8 path, not a general law. A future f32 "
                    "stage may batch, after re-verifying per graph -- that rule stands."
                ),
            },
            "depth_saturates_at_30": {
                "finding": dict(depth_table),
                "supersedes": "Session H's 'reranking ~50 scores the same as 10', which was L-2-specific",
                "quantified": (
                    "depth handed L-2 +0.0611 of input recall and L-2 returned -0.0374 of "
                    "conditional accuracy, netting +0.0044. That is a weak reranker failing to "
                    "exploit a longer slate, not depth being closed."
                ),
                "unaffected": "session pruning remains closed as a QUALITY mechanism; different claim",
            },
            "failure_mode_is_only_58_percent_same_session": {
                "finding": "rank-1 distractor shares gold's true session 58.0%, derived session 59.4%",
                "corrects": (
                    "any brief framing this as same-session discrimination. "
                    "docs/RESEARCH-BRIEF-retrieval.md is named as carrying that framing and is NOT "
                    "in this repository; the correction must be applied wherever it lives."
                ),
            },
        },

        # -------------------------------------------------------------------------------------
        "reporting_requirements": {
            "frontier": "R@1 AND conditional accuracy against ms/query, for every configuration",
            "input_recall": "reported for every configuration, since it caps R@1",
            "two_columns": (
                "WINS-ON-QUALITY and CAN-SHIP are separate columns. If a large model wins, the "
                "cascade (arm 4) becomes the shipping question rather than an optional arm."
            ),
            "precision_at_coverage": {
                "for": "the best configuration, on held-out",
                "sweep": "rerank-score threshold, coverage 100% down to 10% in 5% steps",
                "reported_twice": (
                    "raw score AND per-query top1-minus-top2 margin. Session E's finding is that "
                    "the pooled version is the defective one, and which is used decides whether a "
                    "high-confidence region exists at all."
                ),
                "interpretation": "NOT this session's job. The gate refit reads it.",
            },
            "if_nothing_reaches_080": (
                "the failure decomposition at the best configuration IS the deliverable, in the "
                "form Session G's 19:1 took, plus fine-tuning recorded as the named next lever "
                "with its blocker (CUDA fails to load) attached."
            ),
        },

        "out_of_scope": [
            "refitting the gate -- a different number, and it would confound the R@1 read",
            "fine-tuning a cross-encoder -- needs GPU, its own registration, stricter held-out discipline",
            "adopting conformal risk control as the injection rule -- that is the gate refit's decision",
            "scoping cues 3-5; lowering the threshold; re-tuning calibration resolution",
            "consolidation, PRF, entity expansion, HyDE, session pruning as a quality mechanism",
            "any LLM call anywhere",
            "modifying eval/ -- it is the scoreboard and prints 72",
        ],

        "standing_checks": [
            "repro --runs 2 WITHOUT a cache, run EARLY",
            "conformance before any quality number",
            "a second implementation of a scored-path component must reproduce the first",
            "ONNX graph optimization level pinned on both sides -- ORT_ENABLE_BASIC / Level1",
            "cargo test --workspace, and cd eval && pytest at 72",
            "any adopted model pinned by BOTH repository revision and sha256",
        ],

        "artifacts_this_registration_rests_on": REQUIRED,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(prereg, indent=2) + "\n", encoding="utf-8")

    print("Session I pre-registration written.")
    print(f"  arms, in the order the RULE selected: "
          f"{', '.join(a['arm'] for a in prereg['arm_order']['order'])}")
    print(f"  arm 6 reclassified: cannot move R@1 (identity), moved to the coverage deliverable")
    print(f"  models admitted: {len(admitted)}  (scope narrowed: 2 of them are run)")
    print(f"  SCOPE: P1 truncation defect fix, P2 arm 0 minimum breadth, P3 L-6 if time")
    print(f"  DEFERRED as UNMEASURED: context, depth grid, cascade, ensemble, structural")
    print(f"  ADR-014 floor: alpha 0.05 needs n >= 6 discordant; measured per contrast, on fit")
    print(f"  corrections recorded: {len(prereg['corrections_to_prior_sessions']) - 1}")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
