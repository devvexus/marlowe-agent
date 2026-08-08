"""Session J — the pre-registration. Written BEFORE anything is fit.

Refuses without `tools/split.json` and without `runs/session-j/gate-resolution.json`, because the
Part 3 bands are *derived from* that reachability measurement rather than asserted. ADR-016 came
back negative — 0.95 is unreachable at the shipped calibration resolution for any feature, oracle
0.8483 — and a registration that predicted a refit ceiling without it would be predicting against
a bound it had not checked.

**Three deliverables, in order, and the order is Session I's finding rather than a preference.**
Capacity was a null WITH POWER (+0.0131 R@1, discordant 27, exact p = 0.7011), so this session does
not lead with a bigger model. Length normalization is the named lever, fine-tuning is the
domain-adaptation lever the null does not rule out, and the gate refit is the only work that has
ever produced a number against K1.

    python tools/preregister_session_j.py
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_PATH = REPO / "runs" / "session-j" / "PREREGISTRATION.json"
SPLIT_PATH = REPO / "tools" / "split.json"

REQUIRED = {
    "gate_resolution": "runs/session-j/gate-resolution.json",
    "session_i_result": "runs/session-i/PREREGISTRATION.json",
    "session_i_seqlen_l2": "runs/session-i/seqlen-fit-L2-f32.json",
    "session_i_seqlen_l6": "runs/session-i/seqlen-fit-L6-f32.json",
    "reranker_manifest": "runs/session-i/reranker-manifest.json",
}

# Exact McNemar is a binomial over the discordant pairs only, so the smallest attainable two-sided
# p is 2/2^n. ADR-014 is binding: a registration using a paired test MUST state the n at which its
# alpha becomes attainable, and the instrument check MUST confirm the arms disagree that often on
# the EXACT contrast the test consumes.
MIN_DISCORDANT_FOR_ALPHA = 6            # 2/2^6 = 0.03125, the first n where p < 0.05 is possible
ALPHA = 0.05


def canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def main() -> int:
    if OUT_PATH.exists():
        raise SystemExit(
            f"{OUT_PATH.relative_to(REPO)} already exists. A pre-registration is written once and "
            "never rewritten; editing one after a number exists is what it is designed to prevent."
        )

    art = {}
    for key, rel in REQUIRED.items():
        path = REPO / rel
        if not path.exists():
            raise SystemExit(
                f"{rel} is missing. This registration is derived from it; without it the bands "
                "below would be assertions rather than derivations."
            )
        art[key] = json.loads(io.open(path, encoding="utf-8").read())

    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    expected = hashlib.sha256(
        canonical({"rule": split["rule"], "fit": split["fit"], "heldout": split["heldout"]}).encode()
    ).hexdigest()
    if expected != split["digest"]:
        raise SystemExit(f"{SPLIT_PATH} has been edited since it was written; refusing.")

    res = art["gate_resolution"]
    oracle = res["oracle"]["max_calibrated_precision"]
    block = res["bound_on_gated_fit_population"]["top_block_rows"]

    prereg = {
        "_what": "M0b Session J pre-registration. Written before anything is fit.",
        "written_before": (
            "any Session J R@1 number, any fine-tuned checkpoint, any refit ceiling, and any "
            "point on the precision/coverage curve"
        ),
        "session": "M0b Session J",
        "split": {
            "digest": split["digest"],
            "corpus_sha256": split["corpus_sha256"],
            "fit_cases": split["fit_cases"],
            "heldout_cases": split["heldout_cases"],
        },

        # ---------------------------------------------------------------- inherited, not re-derived
        "inherited_and_not_repeated": {
            "adr_016_gate_resolution": {
                "status": "MEASURED THIS SESSION, in Part 0, before this file was written",
                "finding": (
                    f"max_calibrated_precision >= 0.95 is unreachable at CALIBRATION_BLOCKS = 256 "
                    f"for ANY feature including a perfect one; the oracle is {oracle}. The top "
                    f"block is {block} rows spanning 100% of queries, so the only operating point "
                    "the gate can express is full coverage."
                ),
                "consequence": "Part 3(a) reports the bound and STOPS. Conformal is the K1 answer.",
            },
            "adr_015_capacity_null_with_power": {
                "L6_vs_L2_f32": {"delta_r_at_1": 0.0131, "discordant": 27, "exact_p": 0.7011},
                "consequence": "this session does not spend itself on a bigger model",
            },
            "adr_015_seqlen": {
                "L2_f32_512_vs_256": {"delta_r_at_1": -0.0917, "discordant": 31, "exact_p": 0.0002},
                "L6_f32_512_vs_256": {"delta_r_at_1": -0.0088, "discordant": 8, "exact_p": 0.7266},
                "consequence": (
                    "the length bias is substantially a weak-model artifact, so arm 7 is measured "
                    "on at least two capacities"
                ),
            },
            "adr_015_int8_is_shape_bound": (
                "padding alone flips top-1 in 15% of cases on the quantized graph; all eight f32 "
                "graphs are invariant to 0.000000. ANY cell varying sequence length or padding "
                "runs f32."
            ),
        },

        # ---------------------------------------------------------------- Part 1
        "part_1_length_normalization": {
            "_what": "Arm 7. No training. A normalization term applied to the rerank score.",
            "population": "fit split only; held-out read once, at the end, after Part 2",
            "capacities": ["ms-marco-MiniLM-L-2-v2 f32", "ms-marco-MiniLM-L-6-v2 f32"],
            "control_point": "ms-marco-MiniLM-L-2-v2-int8 @256, the shipped configuration",
            "precision_rule": (
                "f32 for every cell that varies sequence length or padding (ADR-015). The int8 "
                "control is read at [1, 256] only, where its shape binding holds."
            ),
            "arms": {
                "7a_control": "the raw rerank logit, unmodified",
                "7b_subtractive": "s - lambda * f_hat(log wordpieces)",
                "7c_divisive": (
                    "sigmoid(s) / wordpieces^alpha. Defined on the PROBABILITY scale deliberately: "
                    "a cross-encoder logit is signed, and dividing a signed score by a positive "
                    "length factor moves negatives the wrong way."
                ),
                "7d_role_only": "s - beta * 1[speaker == assistant]",
                "7e_both": "7b and 7d together — the decomposition that says whether role adds "
                           "anything beyond length",
            },
            "how_f_hat_is_fitted": (
                "the conditional mean of the rerank score on log wordpieces, over ALL fit-split "
                "slate candidates, WITHOUT reference to R@1. Only the strength lambda is swept "
                "against the metric, over a registered five-point grid. This keeps the estimate of "
                "the length effect separate from the decision of how much to remove."
            ),
            "lambda_grid": [0.0, 0.25, 0.5, 0.75, 1.0],
            "adr_010_reach_check": {
                "rule": (
                    "before any band is read, each arm must be shown to CHANGE TOP-1 on at least "
                    f"{MIN_DISCORDANT_FOR_ALPHA} fit queries against 7a. An arm that reorders "
                    "nothing cannot move R@1 and its delta is an identity, not a result."
                ),
                "refuses_if": "the count is below the floor; the arm reports NOT MEASURED",
            },
            "adr_014_power": {
                "alpha": ALPHA,
                "min_discordant_for_alpha": MIN_DISCORDANT_FOR_ALPHA,
                "why": "exact McNemar's smallest two-sided p is 2/2^n",
                "binding": (
                    "the discordant count is reported beside every p-value, and where it is below "
                    "the floor the p-value is declared unattainable IN ADVANCE rather than quoted "
                    "as evidence of absence"
                ),
                "contrast_the_test_consumes": "best normalized arm vs 7a, same model, same seq, fit",
            },
            "bands": {
                "L2_f32_at_256": {"floor": 0.01, "predicted": [0.02, 0.06]},
                "L6_f32_at_256": {"floor": 0.0, "predicted": [0.0, 0.02]},
                "directional_prediction": (
                    "L-2 gains MORE than L-6. Derived from ADR-015: the seq-512 penalty is -0.0917 "
                    "on L-2 and -0.0088 on L-6, so most of the length bias belongs to the weaker "
                    "model. If L-6 gains more than L-2, this prediction is WRONG and the "
                    "weak-model-artifact reading of ADR-015 needs revisiting."
                ),
            },
            "seq_512_cell": {
                "_what": (
                    "the ONLY registered test of ADR-015's claim that raising sequence length is "
                    "viable alongside explicit length normalization and not otherwise"
                ),
                "cells": "L-2 f32 and L-6 f32, seq 512, best normalization arm, fit split",
                "closes_the_truncation_defect_if": (
                    "normalized seq-512 is NON-INFERIOR to normalized seq-256 — delta R@1 >= -0.01 "
                    "with no significant loss at the ADR-014 floor. If that holds, the 7.86% of "
                    "gold turns truncated at 256 are recovered WITHOUT paying the length-bias "
                    "cost, and the defect recorded in ADR-015 is closed properly rather than left "
                    "standing as 'do not attempt'."
                ),
                "predicted": (
                    "non-inferiority holds on L-6 and is marginal on L-2, because L-2 is where the "
                    "bias lives and where normalization has the most to undo"
                ),
            },
            "shipping_note_registered_in_advance": (
                "the role arm is measurable offline today but is NOT shippable as-is: speaker is "
                "carried on the section 4.6 wire (marlowe-contract/src/wire.rs) and DISCARDED by "
                "ingest, so MemoryEntry has no role field. Shipping 7d or 7e needs the same schema "
                "addition Session H made for occurred_at_ms, with a DERIVATION_VERSION bump. "
                "Recorded now so a winning arm is not discovered to be unshippable afterwards."
            ),
        },

        # ---------------------------------------------------------------- Part 2
        "part_2_fine_tuning": {
            "_what": "Domain-adapt the cross-encoder on same-session hard negatives, fit split only.",
            "expectation_tempered_on_the_record": (
                "capacity was a null WITH POWER, and fine-tuning is capacity-adjacent. What it "
                "offers that depth does not is DOMAIN adaptation: off-the-shelf rerankers learned "
                "to separate topically distinct web passages, and the failure here is separating "
                "turns inside one conversation with a length preference the training data "
                "rewarded. That is a different mechanism, so the null does not rule it out. **The "
                "research report's +0.06 to +0.10 projection is NOT inherited as a prior.** The "
                "band below is derived from this project's own fit-split evidence."
            ),
            "base_selection_rule": (
                "whichever pinned model Part 1 shows responds best to normalization, f32 — PLUS "
                "L-2 unconditionally, because L-6 f32 is 52.1 ms/pair = 521 ms/query at depth 10 "
                "against a 300 ms retrieval P95 budget and CANNOT ship on ADR-003's 1-vCPU "
                "target. L-2 is the only shipping candidate and must be measured as one."
            ),
            "negative_classes_ablated_separately": [
                "temporal adjacency: +/-1 and +/-2 turns from gold",
                "high entity overlap with gold",
                "opposite speaker role",
                "long assistant turns — the class Session I's decomposition earned, and the direct "
                "way to train out the length bias",
            ],
            "loss": {
                "registered": "MarginMSE",
                "deviation_and_its_reason": (
                    "MarginMSE as published distils TEACHER margins, and this project has no "
                    "admitted stronger teacher — capacity came back null, so calling any fetched "
                    "model 'stronger' would be unevidenced. The HARD-LABEL variant is used: the "
                    "(gold - negative) score gap is regressed toward a target margin delta. "
                    "**delta is taken from the BASE model's own margin distribution on fit cases "
                    "it already ranks correctly**, so it is not chosen against the outcome. This "
                    "preserves the distance calibration Part 3 reads, which is why MarginMSE was "
                    "specified at all."
                ),
            },
            "held_out_discipline": {
                "train_on": "fit only",
                "mine_and_split_by": "CONVERSATION ID, not query id, so history patterns cannot leak",
                "validation": "carved out of fit; no hyperparameter, checkpoint or early-stopping "
                              "decision touches held-out",
                "measured_leakage_channel_and_its_exclusion": (
                    "2182 haystack sessions appear in BOTH the fit and held-out haystacks — "
                    "measured, not assumed. Gold-session leakage is near zero (2 sessions). "
                    "Negatives are therefore mined ONLY from sessions absent from every held-out "
                    "haystack (8585 of 10767 fit sessions remain), and the 2 gold collisions are "
                    "dropped from training entirely. Without this, the model could learn that "
                    "specific texts are never relevant and carry that into held-out — a leak in "
                    "the direction that flatters the number."
                ),
            },
            "bands": {
                "floor": 0.02,
                "predicted": [0.02, 0.08],
                "measured_on": "the fit-carved validation slice, against the Part 1 best base",
            },
            "export_and_determinism": {
                "required_before_any_number": [
                    "sha256 pin at load, as every other model in this project",
                    "batch invariance re-verified PER GRAPH",
                    "PADDING invariance re-verified per graph (ADR-015)",
                    "ORT_ENABLE_BASIC on the Python side against ort's Level1",
                    "torch-vs-ORT agreement on frozen fixtures",
                ],
                "open_gap_this_creates_and_how_it_is_handled": (
                    "a PyTorch-to-ONNX export produced HERE is a second instance of the "
                    "unvalidated-export gap, and unlike a maintainer export it cannot be closed by "
                    "an external authority because none exists for a model this session trained. "
                    "It is SELF-VALIDATED ONLY: torch-vs-ORT fixture agreement plus digest "
                    "pinning. That is stated as a limitation rather than reported as closure."
                ),
            },
            "held_out_read": "CPU, single-threaded, f32 — the deterministic path",
        },

        # ---------------------------------------------------------------- Part 3
        "part_3_gate_refit_and_conformal": {
            "_what": "The only work this project has done that produces a number against K1.",
            "threshold": {"value": 0.95, "frozen": True,
                          "_note": "NOT lowered, and ADR-016 does not lower it"},

            "arm_a_isotonic_refit": {
                "instruction": "reports the ADR-016 bound and STOPS",
                "reason": (
                    f"the oracle at CALIBRATION_BLOCKS = 256 is {oracle}, below the 0.95 "
                    "threshold, so a refit cannot clear it whatever features it is given. Fitting "
                    "it anyway would produce a number whose only content is the bound."
                ),
                "predicted_refit_ceiling": [0.30, 0.45],
                "reported": "where max_calibrated_precision lands, beside the bound and the oracle",
            },

            "arm_b_conformal_risk_control": {
                "nonconformity_score": "the rerank logit margin between rank 1 and rank 2",
                "tau": "the (1-alpha)(1+1/n) quantile of that margin on the FIT split",
                "decision_rule": "inject rank 1 iff its margin >= tau, else abstain",
                "why_it_is_not_arm_6": (
                    "arm 6 was reclassified as an identity on R@1 because a within-query monotone "
                    "transform cannot change a within-query ordering. Abstention is a CROSS-QUERY "
                    "decision, which is exactly where that machinery is not an identity."
                ),
                "global_tau_first": True,
                "group_conditional_rule": (
                    "attempted ONLY where a group has n >= 40, so the (1-alpha)(1+1/n) quantile is "
                    "not simply the maximum of the calibration set. Per-group n is reported beside "
                    "any threshold. Session I measured per-category conditional accuracy swinging "
                    "0.7222 fit / 0.5690 held-out and single-session-preference at n=15; the "
                    "finite-sample bound degrades as 1/n per group."
                ),

                "THE_SEPARATION_THAT_MUST_NOT_BE_CONFLATED": {
                    "quantity_1_the_guarantee": (
                        "what the conformal construction actually bounds, and its scope. The plain "
                        "quantile rule gives a MARGINAL, distribution-free, finite-sample bound "
                        "over the draw of the calibration set."
                    ),
                    "quantity_2_the_measurement": (
                        "the EMPIRICAL held-out precision among the injected set at tau."
                    ),
                    "why_they_are_different": (
                        "K1 asks for precision CONDITIONAL ON HAVING INJECTED. That is a selective "
                        "risk, and the marginal bound does not cover it. Reporting the guarantee "
                        "as though it were the measurement, or the measurement as though it "
                        "carried the guarantee, would be a false claim on the record."
                    ),
                    "binding": "both are reported, separately, with the scope of each stated",
                },
            },

            "the_deliverable": {
                "_what": "the precision/coverage curve, held-out, BOTH arms",
                "swept": "the threshold, reporting precision at every coverage level down to 10%",
                "uncertainty": (
                    "every point carries a Clopper-Pearson 95% interval. At 10% coverage n is "
                    "about 23, where an observed 0.95 has a lower bound near 0.77. 'Reaches 0.95' "
                    "means the INTERVAL, not the point estimate."
                ),
                "k1_reading": (
                    "section 5.5 is precision-first with recall recovered through the explicit "
                    "recall tool, and K1 carries NO COVERAGE TERM. So >= 0.95 precision at ANY "
                    "coverage satisfies K1 as written. If that region exists, its coverage and "
                    "threshold are named. If no coverage level reaches it, THAT IS THE K1 ANSWER "
                    "and it is reported plainly."
                ),
                "predicted": (
                    "no coverage level reaches 0.95 with a lower interval bound above it. Derived "
                    "from fit-split evidence: conditional accuracy is 0.6730 and the most "
                    "confident decile would have to more than close a 0.28 gap."
                ),
            },

            "conformance_condition": (
                "IF the gate injects for the first time, conformance runs BEFORE any quality "
                "number. That is section 4.3's closing condition and the run where a defence lost "
                "during the work would surface."
            ),
        },

        # ---------------------------------------------------------------- process
        "output_path_rule": (
            "every varied parameter appears in the output filename — split, model, precision, "
            "sequence length, normalization arm. Session I's seqlen tool keyed on split alone and "
            "silently overwrote a prior run with different models."
        ),

        "out_of_scope_and_not_attempted": [
            "cues 3-5",
            "lowering the 0.95 threshold",
            "re-tuning the calibration resolution",
            "consolidation, PRF, entity expansion, HyDE",
            "session pruning as a quality mechanism",
            "raising sequence length WITHOUT length normalization alongside it",
            "modifying eval/ — it is the scoreboard and prints 72",
            "shipping: measurement is the deliverable this session, Session I's precedent",
        ],

        "standing_checks": [
            "repro --runs 2 WITHOUT a cache, run EARLY",
            "cargo test --workspace at 188, cd eval && pytest at 72",
            "a second implementation of a scored-path component must reproduce the first",
            "ONNX graph optimization level pinned on both sides — ORT_ENABLE_BASIC / Level1",
            "provider asserted against get_providers() AFTER construction, never merely requested",
            "any adopted model pinned by sha256",
            "any cell varying sequence length or padding runs f32 (ADR-015)",
        ],

        "artifacts_this_registration_rests_on": REQUIRED,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(prereg, indent=2) + "\n", encoding="utf-8")

    print("Session J pre-registration written.")
    print(f"  split digest {split['digest'][:16]}...  "
          f"{split['fit_cases']} fit / {split['heldout_cases']} heldout")
    print()
    print(f"  Part 1  arm 7, five arms, two capacities, plus the seq-512 x normalization cell")
    print(f"          bands: L-2 [{0.02}, {0.06}] floor 0.01 | L-6 [0.0, 0.02] floor 0.0")
    print(f"          directional prediction registered: L-2 gains MORE than L-6")
    print(f"  Part 2  hard-label MarginMSE, deviation recorded with its reason")
    print(f"          2182 shared sessions excluded from negative mining, measured not assumed")
    print(f"          band [0.02, 0.08] floor 0.02, derived here, NOT inherited from the report")
    print(f"  Part 3  arm (a) reports the ADR-016 bound and stops (oracle {oracle} < 0.95)")
    print(f"          arm (b) conformal; guarantee and measurement reported SEPARATELY")
    print(f"          predicted: no coverage reaches 0.95 with its lower interval bound above it")
    print()
    print(f"  ADR-014 floor: alpha {ALPHA} needs n >= {MIN_DISCORDANT_FOR_ALPHA} discordant")
    print(f"  ADR-010 reach: every arm must change top-1 on >= {MIN_DISCORDANT_FOR_ALPHA} queries")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
