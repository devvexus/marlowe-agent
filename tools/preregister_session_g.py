"""Session G's pre-registration — written BEFORE any pool is reconstructed or any arm measured.

Session G is a REACHABILITY CHECK, not a fit. Four query-side arms are measured offline against
the held-out pools Session F left on disk, and a cross-encoder is re-costed against a shortlist
that does not exist yet. Nothing is frozen here and no gate is refit; what is registered is the
DECISION RULE that turns each measurement into a build-or-drop verdict, plus the reporting
obligations that keep a null readable.

Why a pre-registration for a measurement session at all. Sessions D, E and F each failed a floor,
and the standing risk is that a fifth session assembles a favourable reading after the fact —
Session D's escalation read is already on the record as confounded for exactly that reason. The
cross-encoder additionally carries a STANDING INSTRUCTION that it is not re-attempted without a
fresh pre-registration (STATE.md, and the spike's own "no third attempt" clause). This file is
that registration.

It refuses to overwrite itself. A pre-registration that can be re-run after seeing a number is a
post-registration with a misleading filename.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPLIT_PATH = ROOT / "tools" / "split.json"
CORPUS_PATH = ROOT / "data" / "longmemeval_s_cleaned.json"
PRIOR_OVERLAP = ROOT / "runs" / "session-f" / "cue-overlap.json"
PRIOR_CANDIDATES = ROOT / "runs" / "session-f" / "heldout" / "scored-candidates.ndjson"
RUN_DIR = ROOT / "runs" / "session-g"
PREREG_PATH = RUN_DIR / "PREREGISTRATION.json"

# The oracle a promotion has to beat, and the noise floor it has to clear. Both are READ from
# Session F's committed artifact rather than retyped -- a retyped baseline is a second copy of a
# number with nothing comparing the two, and a drifted baseline is invisible because it produces
# a result of exactly the right shape.
#
# NOTE ON THE DENOMINATOR, which STATE.md is emphatic about. cue-overlap.json carries the RAW
# 229-case figures (either_oracle 0.6463). The re-based 230-case figures in STATE.md (0.6435) are
# the ones comparable to Session E. Session G quotes NEITHER as its baseline: every arm here is a
# PAIRED comparison inside one reconstruction, so the baseline is recomputed from the same dump
# under the same rule, and the raw 229 figure is used only as a reconstruction-fidelity target.
PROMOTE_DELTA = 0.05
INCONCLUSIVE_DELTA = 0.02
MCNEMAR_ALPHA = 0.05

# Section 5.7's total cold retrieval P95, and Session F's measured base for it.
TOTAL_BUDGET_MS = 300
MEASURED_BASE_P95_MS = 33
# The stage bar is deliberately tighter than 300 - 33 = 267. The spike's own method note records
# that a projected total is a SUM OF TWO SEPARATELY MEASURED SPANS and is optimistic by
# construction because it omits integration cost. Registering 267 would be registering the
# optimistic number as the bar.
INTEGRATION_RESERVE_MS = 27
CROSS_ENCODER_STAGE_BAR_MS = TOTAL_BUDGET_MS - MEASURED_BASE_P95_MS - INTEGRATION_RESERVE_MS


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if PREREG_PATH.exists():
        print(f"REFUSING: {PREREG_PATH.relative_to(ROOT)} already exists.", file=sys.stderr)
        print(
            "A pre-registration is written once, before the measurement. Re-running this after a\n"
            "number exists would be a post-registration. Delete it deliberately if the session is\n"
            "genuinely being restarted from before any arm was measured.",
            file=sys.stderr,
        )
        return 2

    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    prior = json.loads(io.open(PRIOR_OVERLAP, encoding="utf-8").read())

    corpus_sha = sha256_file(CORPUS_PATH)
    if corpus_sha != split["corpus_sha256"]:
        print(
            f"REFUSING: corpus sha256 {corpus_sha} does not match the split's "
            f"{split['corpus_sha256']}. The split was drawn against a different corpus.",
            file=sys.stderr,
        )
        return 2
    if not PRIOR_CANDIDATES.exists():
        print(f"REFUSING: {PRIOR_CANDIDATES} is missing; there is nothing to reconstruct.", file=sys.stderr)
        return 2

    k1 = prior["gold_in_top_k"]["1"]

    prereg = {
        "session": "M0b Session G",
        "_what_this_session_is": (
            "A REACHABILITY CHECK on the query side, plus a re-costing of the cross-encoder against "
            "a shortlist that pruning might make cheaper. No gate is refit, no artifact is frozen, "
            "and nothing ships from this session without a further fit-split registration."
        ),
        "split": {
            "digest": split["digest"],
            "rule": split["rule"],
            "fit_cases": split["fit_cases"],
            "heldout_cases": split["heldout_cases"],
            "corpus_sha256": split["corpus_sha256"],
            "redrawn": False,
            "note": (
                "Session B's split, unchanged through C, D, E, F and G, asserted by digest above."
            ),
        },
        "registered_against_split": split["digest"],
        "corpus_sha256": corpus_sha,
        "corpus_variant": split["corpus_variant"],
        "derived_from": {
            "candidates": "runs/session-f/heldout/scored-candidates.ndjson",
            "transcript": "runs/session-f/heldout/run.jsonl",
            "population": "the HELD-OUT split",
            "why_heldout_and_not_fit": (
                "The arms are measured against the pools that already exist on disk, and those are "
                "held-out pools. This is a deliberate choice for speed -- Session F's proxy check is "
                "the precedent -- and it has a cost that is disclosed below rather than hidden."
            ),
        },

        # --------------------------------------------------------------------------- disclosure
        "disclosure": {
            "_what": (
                "Every arm in this session is measured on HELD-OUT data. That is the instruction "
                "and it is the right call for a reachability check, but it means these numbers "
                "CANNOT later be quoted as held-out validation of whatever gets built."
            ),
            "_the_rule_this_creates": (
                "Any mechanism promoted by this session must have its band re-derived on the FIT "
                "split before it is built, and be re-measured on held-out afterwards. A Session G "
                "reachability number is an ESTIMATE OF HEADROOM, never a result."
            ),
            "_precedent": (
                "Session F disclosed its proxy reachability check the same way and re-derived every "
                "band on the fit split afterwards. This follows that pattern deliberately."
            ),
            "_what_would_be_laundering": (
                "Reporting an arm's held-out oracle gain in Session H as evidence the shipped "
                "mechanism generalizes. It is the same measurement on the same cases."
            ),
        },

        # ------------------------------------------------------------------- ADR-010 reach check
        "reach_check_adr_010": {
            "_what": (
                "ADR-010: check that a shape CAN move the metric it will be judged on, before "
                "registering any band. The either-cue top-1 oracle is capped at ~0.64 for anything "
                "that only re-arbitrates two fixed per-cue opinions over a fixed candidate set. An "
                "arm is exempt from that cap only if it changes the candidate set or the per-cue "
                "scores themselves."
            ),
            "_the_cap_and_why_it_binds": (
                "Sessions D, E and F all attacked arbitration and all failed their floor. The oracle "
                "is the ceiling on arbitration, so an arm that cannot move it cannot repay the code."
            ),
            "arms": {
                "arm_1_session_pruning": {
                    "changes": "the candidate set (a subset of it)",
                    "capped_by_the_oracle": False,
                    "why": (
                        "Rank is defined over the candidate set. Removing a non-gold candidate that "
                        "ranked above gold strictly improves gold's rank; removing gold strictly "
                        "destroys the case. Both directions are real, which is why gold retention "
                        "is reported beside the oracle and not after it."
                    ),
                },
                "arm_2_query_expansion_prf_entity": {
                    "changes": "the per-cue scores, via new query terms",
                    "capped_by_the_oracle": False,
                    "why": (
                        "BM25 over an expanded term set is a different scoring function, not a "
                        "re-weighting of a fixed lexical opinion. The per-candidate scores change, "
                        "so the oracle over them is a different quantity."
                    ),
                },
                "arm_3_hypothetical_answer_embedding": {
                    "changes": "the dense score, via a new query vector",
                    "capped_by_the_oracle": False,
                    "why": (
                        "A different query vector has different nearest neighbours. This is not "
                        "re-ordering a fixed dense opinion; it is a different dense opinion."
                    ),
                },
                "arm_4_temporal_anchoring": {
                    "changes": "the candidate set (a hard filter over it)",
                    "capped_by_the_oracle": False,
                    "why": "Same argument as arm 1. A filter is a subset operation.",
                },
            },
            "conclusion": (
                "No arm in this session is an arbitration change. All four are exempt from the "
                "~0.64 cap, so registering bands against the oracle is legitimate for all four."
            ),
            "what_is_NOT_exempt_and_is_not_scoped": (
                "Cues 3-5, threshold changes, calibration-resolution changes. All remain out, and "
                "SmartSearch's index-free result -- where adding ColBERT via RRF gained little -- "
                "reinforces rather than weakens that."
            ),
        },

        # ------------------------------------------------------------------ the fidelity gate
        "reconstruction_fidelity_gate": {
            "_what": (
                "Before ANY arm number is quoted, the offline reconstruction must reproduce Session "
                "F's published held-out top-1 rates from the same dump under the same rule."
            ),
            "targets_read_from_session_f_artifact": {
                "lexical_top1": k1["lexical"],
                "dense_top1": k1["dense"],
                "either_oracle_top1": k1["either_oracle"],
                "_denominator": "RAW 229, as committed in runs/session-f/cue-overlap.json",
            },
            "rule": "exact equality at 4 decimal places on all three",
            "on_failure": (
                "Every downstream arm reports NOT MEASURED. A reconstruction that does not "
                "reproduce the baseline is measuring something else, and an arm delta computed "
                "against a wrong baseline is worse than no number because it looks like one."
            ),
            "_why_this_is_the_first_gate": (
                "This project has produced five instances of the two-sides-silently-disagree "
                "pattern. An offline reconstruction of a pool is a sixth opportunity."
            ),
        },

        # ----------------------------------------------------- the second-implementation gate
        "python_cue_reimplementation_gate": {
            "_what": (
                "Arms 2 and 3 change the query, so they cannot be computed from the stored scores "
                "and require recomputing BM25 and cosine in Python over the held-out pool. That is "
                "a SECOND IMPLEMENTATION of both cues alongside the Rust ones."
            ),
            "_the_risk_named": (
                "This is exactly the pattern CLAUDE.md flags and that has produced five bugs here: "
                "two sides silently disagree and the test goes green because the failing path "
                "stopped existing."
            ),
            "rule": (
                "The Python path must first reproduce the stored lexical_bm25 and dense_cosine "
                "columns for the UNMODIFIED query before any expanded-query number is computed."
            ),
            "tolerance": {
                "dense_cosine": "max abs diff <= 1e-4 over all rows",
                "lexical_bm25": "Spearman >= 0.999 AND top-1 selection identical on >= 99% of cases",
                "_why_bm25_is_looser": (
                    "BM25 depends on corpus statistics (document count, average length, "
                    "tokenization) that the Rust cue owns. An exact match would be surprising; a "
                    "rank-equivalent match is what the arm actually needs, because the arm reads "
                    "top-1. If the looser bar is also missed, the arm is NOT MEASURED."
                ),
            },
            "on_failure": (
                "Arms 2 and 3 report NOT MEASURED. They are NOT reported with a caveat -- an "
                "unvalidated re-implementation produces a number of the right shape and there is "
                "nothing to catch it being wrong."
            ),
        },

        # ------------------------------------------------------------------ the promotion rule
        "promotion_rule": {
            "_what": "What each arm's measurement has to do to justify production Rust.",
            "primary_quantity": (
                "Delta in either-cue top-1 oracle vs the baseline recomputed in the same run, over "
                "the identical case set."
            ),
            "test": {
                "name": "exact McNemar (two-sided binomial on discordant pairs)",
                "alpha": MCNEMAR_ALPHA,
                "_why_mcnemar_and_not_wilson": (
                    "The arms are PAIRED by construction -- same cases, same dump, one thing "
                    "changed. Comparing two Wilson intervals on the marginal rates throws away the "
                    "pairing and is the wrong test; STATE.md's 0.062 half-width is the right "
                    "caution for cross-session comparison and the wrong one here. McNemar reads "
                    "only the cases that changed, which is the actual evidence."
                ),
            },
            "bands": [
                {
                    "condition": f"delta >= +{PROMOTE_DELTA} AND McNemar p < {MCNEMAR_ALPHA}",
                    "verdict": "PROMOTE",
                    "means": (
                        "Build it in Rust in Session H, with the band re-derived on the fit split "
                        "first. Registers the unchanged-cue check as expected-to-fire."
                    ),
                },
                {
                    "condition": (
                        f"+{INCONCLUSIVE_DELTA} <= delta < +{PROMOTE_DELTA}, OR "
                        f"delta >= +{PROMOTE_DELTA} with p >= {MCNEMAR_ALPHA}"
                    ),
                    "verdict": "INCONCLUSIVE",
                    "means": (
                        "Not built this milestone. Re-measure on the fit split before any build. "
                        "An underpowered positive is not a positive."
                    ),
                },
                {
                    "condition": f"-{INCONCLUSIVE_DELTA} < delta < +{INCONCLUSIVE_DELTA}",
                    "verdict": "NOT REACHED",
                    "means": "The named lever closes for this arm. Record it and do not retry it.",
                },
                {
                    "condition": f"delta <= -{INCONCLUSIVE_DELTA}",
                    "verdict": "HARMFUL",
                    "means": "Record the mechanism of the harm; it constrains future shapes.",
                },
            ],
            "_why_0_05": (
                "The fused gate sits 0.109 below the oracle and four sessions have failed to close "
                "that gap by arbitration. An oracle gain under 0.05 does not change what is "
                "reachable and does not repay a new retrieval stage on the measured path."
            ),
        },

        # ------------------------------------------------------- arm 1 reporting obligations
        "arm_1_registered_reads": {
            "_what": "Session-level pruning: score sessions, keep top N, rank turns only within them.",
            "N_values": [1, 3, 5],
            "reported_together_and_none_alone": [
                "surviving pool size (absolute and as a fraction of the unpruned pool)",
                "gold retention (fraction of cases with >= 1 gold turn surviving the cut)",
                "either-cue top-1 oracle over the pruned pool",
            ],
            "_why_all_three": (
                "Pruning raises top-1 only by removing a distractor above gold, and lowers it by "
                "removing gold. An oracle gain bought by dropping gold is a loss, and the oracle "
                "alone cannot show that."
            ),
            "failure_decomposition": {
                "_what": (
                    "Registered because 'pruning did not help' has two different causes with two "
                    "different fixes, and the oracle cannot distinguish them."
                ),
                "per_case_report": [
                    "which session was selected (top-N set)",
                    "which session actually contains gold",
                    "did the gold-containing session survive the cut (wrong-session failure if not)",
                    "if it survived, gold's rank inside the pruned pool (wrong-rank failure)",
                ],
                "counts_required": [
                    "wrong_session: gold's session did not survive top-N",
                    "right_session_wrong_rank: gold's session survived but gold is not top-1",
                    "solved: gold is top-1 under at least one cue after pruning",
                ],
                "_why": (
                    "A wrong-session failure is fixed by a better session scorer. A "
                    "right-session-wrong-rank failure is fixed by a reranker, and is exactly the "
                    "case the cross-encoder addresses. These imply different builds."
                ),
            },
            "shortlist_equivalence_condition": {
                "_what": (
                    "The condition that decides whether the cross-encoder re-costing is justified, "
                    "registered here so it is not chosen after seeing the latency number."
                ),
                "rule": "R@10 over the pruned pool at the chosen N >= R@20 over the unpruned pool - 0.01",
                "_both_sides_measured_in_the_same_run": (
                    "R@20 unpruned is NOT looked up first and then registered against. Both sides "
                    "are computed together in the same script from the same dump."
                ),
                "_why_it_matters": (
                    "The cross-encoder was ruled out at 365 ms over 20 candidates. If a pruned "
                    "top-10 is as good as today's top-20, the reranker's cost roughly halves. If it "
                    "is not, the budget math does not change and the re-open is not justified by "
                    "this session."
                ),
            },
        },

        # ------------------------------------------------------- arm 4 reporting obligations
        "arm_4_registered_reads": {
            "_what": (
                "Temporal anchoring: three dates per turn -- observation date, the date referenced "
                "in the text, and the computed relative offset -- applied as a HARD CONSTRAINT, "
                "not a weighted cue."
            ),
            "_why_this_category": (
                "temporal-reasoning is the largest category at 127 questions and currently receives "
                "no treatment beyond session scoping."
            ),
            "extraction_coverage_is_reported_first": {
                "_what": (
                    "Fraction of turns with a successfully extracted referenced date, and fraction "
                    "of temporal questions with a successfully parsed temporal constraint."
                ),
                "_why_registered": (
                    "The extractor is rule-based. A null here is AMBIGUOUS between 'temporal "
                    "filtering does not help' and 'the extractor missed the dates', and the oracle "
                    "cannot separate those. Coverage is the number that separates them."
                ),
            },
            "primary_read": "the extraction-covered subset",
            "secondary_read": "the full held-out set, reported beside it",
            "_why_the_covered_subset_is_primary": (
                "A hard constraint over a failed extraction discards gold for a reason that has "
                "nothing to do with the mechanism. The full-set number measures extractor plus "
                "mechanism; the covered subset measures the mechanism."
            ),
            "_and_the_full_set_number_is_still_reported": (
                "Because it is the number that would apply if this shipped as-is, and quoting only "
                "the covered subset would overstate what a build would deliver."
            ),
            "registered_risk": (
                "A hard constraint can only remove candidates. If extraction coverage is low, the "
                "full-set oracle is predicted to go DOWN, and that is a finding about the "
                "extractor, not a refutation of temporal anchoring."
            ),
        },

        # ------------------------------------------------------------------- the additivity read
        "additivity_read": {
            "_what": (
                "Registered explicitly: whether the arms COMPOSE or OVERLAP, stated as a "
                "subsumption relation and not only as a combined oracle."
            ),
            "_why": (
                "Three arms each recovering the same 5% of cases is ONE arm. The combined number "
                "cannot show that, and it determines what actually gets built."
            ),
            "required_report": [
                "per arm: the set of case ids it moves from miss to hit",
                "per ordered pair (A,B): |recovered_by_A|, |recovered_by_B|, |both|, |A only|, |B only|",
                "a stated subsumption verdict per pair",
            ],
            "subsumption_rule": {
                "A_subsumes_B": "|recovered_by_B \\ recovered_by_A| <= 2 cases",
                "complementary": "|A only| >= 3 AND |B only| >= 3",
                "overlapping": "neither of the above",
                "_why_2_and_3": (
                    "At n~230 a one- or two-case difference is not separable from noise, which is "
                    "the same caution STATE.md applies to every Session F movement. The threshold "
                    "is stated in CASES rather than rates because that is what the evidence is."
                ),
            },
            "consequence_registered": (
                "If arm X subsumes arm Y, only X is a build candidate. The subsumed arm is recorded "
                "as closed, not carried forward as a second option."
            ),
        },

        # ------------------------------------------------------------------ the cross-encoder
        "cross_encoder_re_costing": {
            "_status": "REGISTERED BEFORE MEASUREMENT, per the standing no-third-attempt instruction",
            "_why_this_is_not_the_forbidden_third_attempt": (
                "The spike registered a two-rung ladder (L-6 fp32 at seq 512, then seq 256) and "
                "forbade a third rung, because a ladder extended after seeing a number is tuning. "
                "This is not a third rung on that ladder: the ruled-out measurement was fp32 L-6 "
                "over TWENTY candidates, and what changes here is the CANDIDATE COUNT -- which is a "
                "consequence of arm 1, not of wanting the reranker to pass. The trigger is external: "
                "SmartSearch defers all precision to a cross-encoder and runs ~650 ms on CPU."
            ),
            "_and_if_arm_1_fails": (
                "The shortlist-equivalence condition is registered above. If it fails, the latency "
                "number is still reported as information, but the re-open is recorded as NOT "
                "JUSTIFIED by this session rather than as a pass."
            ),
            "configurations_registered_and_no_ladder": {
                "models": [
                    "Xenova/ms-marco-MiniLM-L-6-v2, onnx/model_int8.onnx",
                    "Xenova/ms-marco-MiniLM-L-2-v2, onnx/model_int8.onnx",
                ],
                "_why_these_two": (
                    "Both are MAINTAINER-PUBLISHED ONNX exports. STATE.md carries an open gap that "
                    "our jina export is not independently validated, and exporting or quantizing a "
                    "model ourselves would acquire a second instance of that gap."
                ),
                "candidates": 10,
                "max_seq_len": 256,
                "threads": [1, "machine core count"],
                "_which_thread_count_is_the_verdict": (
                    "1 thread. ADR-003 sizes against a 1-vCPU VPS. The core-count number is "
                    "reported because the spike's determinism result licensed multi-threading for "
                    "this graph, but it is not the deployment shape and does not decide adoption."
                ),
                "no_sweep": (
                    "Exactly these two models at exactly this candidate count and sequence length. "
                    "No third model, no seq sweep, no candidate-count sweep. If both miss, the "
                    "verdict is NOT ADOPTED."
                ),
            },
            "latency_bar": {
                "stage_p95_ms": CROSS_ENCODER_STAGE_BAR_MS,
                "derivation": (
                    f"section 5.7 total {TOTAL_BUDGET_MS} ms, minus Session F's measured "
                    f"{MEASURED_BASE_P95_MS} ms cold base, minus a {INTEGRATION_RESERVE_MS} ms "
                    "integration reserve."
                ),
                "_why_a_reserve": (
                    "The spike's own method note records that the projected total is a SUM OF TWO "
                    "SEPARATELY MEASURED SPANS and omits integration cost, so it is optimistic by "
                    "construction. Registering the full 267 ms would register the optimistic number "
                    "as the bar."
                ),
                "truncation_rate_reported": True,
            },
            "determinism_must_be_RE_verified": {
                "_what": (
                    "The spike's three determinism passes were measured on fp32 L-6. int8 "
                    "quantization changes the graph and L-2 is a different graph entirely."
                ),
                "rule": (
                    "batch-1-vs-batch-N, 1-thread-vs-N-thread, and two-separate-processes must all "
                    "pass for any configuration that passes latency."
                ),
                "on_failure": (
                    "NOT ADOPTED regardless of latency. A nondeterministic stage on the measured "
                    "path breaks repro --runs 2, which is a standing check."
                ),
            },
            "adoption_requires_BOTH": [
                "the latency bar at 1 thread",
                "arm 1's shortlist-equivalence condition",
                "re-verified determinism",
            ],
            "_why_both_and_not_either": (
                "A latency pass on a shortlist that lost quality is not a pass; it is a cheaper way "
                "to be wrong."
            ),
            "quality_is_measured_only_if_latency_passes": {
                "rule": (
                    "If and only if a configuration clears the latency bar, its top-1 after rerank "
                    "is measured on the held-out pool as a REACHABILITY number under the disclosure "
                    "above."
                ),
                "_why_gated": (
                    "Measuring rerank quality on a model that cannot ship produces an attractive "
                    "number attached to nothing, and invites adopting it anyway."
                ),
            },
            "gpu": {
                "measured": True,
                "providers": "CUDAExecutionProvider if available; DirectML is not available here",
                "adopted": False,
                "_why_not": (
                    "Determinism across execution providers and the VPS deployment target each need "
                    "their own ADR. The number informs that conversation and does not pre-empt it."
                ),
                "_and_it_does_not_decide_the_bar": (
                    "The latency verdict is read at 1 thread on CPU. A GPU pass does not convert a "
                    "CPU fail into an adoption."
                ),
            },
        },

        # ------------------------------------------------------------------ what is NOT in scope
        "explicitly_not_scoped": {
            "cues_3_to_5": (
                "Standing instruction, and now reinforced: SmartSearch's index-free variant scores "
                "88.4% and adding ColBERT via RRF gained little additional recall. More cues is "
                "MEASURED as not the answer."
            ),
            "morphological_query_expansion": (
                "Tested and rejected in the source work -- noisy candidates cascade through "
                "multi-hop and degrade precision more than they help recall. Arm 2 is PRF plus "
                "entity discovery ONLY."
            ),
            "threshold_lowering": "Standing instruction.",
            "calibration_resolution_retuning": "Standing instruction.",
            "consolidation_retry": "Standing instruction; needs its own fresh pre-registration.",
            "arbitration": (
                "Capped at the either-cue oracle and failed three consecutive floors. Not attacked "
                "again this session."
            ),
            "an_answer_stage_in_the_BINARY": (
                "ROADMAP M0b is exercised through the eval harness only -- no agent loop, no tools. "
                "An answer stage belongs in tools/ as an offline measurement over retrieval output. "
                "Putting one on the measured path would be milestone drift."
            ),
            "qa_accuracy_this_session": (
                "DROPPED from Session G by explicit decision: no LLM credentials are configured and "
                "no HTTP client exists in any crate. Rolls to Session H. Recorded so the absence "
                "reads as a scoping call and not as an omission."
            ),
        },

        # ----------------------------------------------------------------- the prediction
        "predicted_outcome": {
            "_status": "REGISTERED AS THE PREDICTION, before any pool is reconstructed",
            "prediction": (
                "No single arm moves the either-cue top-1 oracle by >= 0.05 with McNemar p < 0.05. "
                "Arm 1 delivers its value as POOL REDUCTION and shortlist equivalence rather than "
                "as oracle movement. The combined oracle is sub-additive."
            ),
            "per_arm": {
                "arm_1_session_pruning": (
                    "Large pool reduction and high gold retention at N=3, but a small oracle move. "
                    "The distractors that outrank gold are frequently in gold's OWN session, "
                    "because LongMemEval-S haystacks are assembled from distinct real sessions and "
                    "within-session turns are the most topically related text in the pool. Pruning "
                    "removes cross-session distractors, which are not the ones winning."
                ),
                "arm_2_prf_entity": (
                    "Small or negative. PRF's feedback is drawn from the first pass, and the first "
                    "pass is worst on exactly the ~36% of cases where neither cue has gold at rank "
                    "1 -- so feedback is drawn from distractors precisely where help is needed."
                ),
                "arm_3_hyde": (
                    "The largest of the three query-side arms, and still under 0.05. Concentrated "
                    "in categories where question and answer vocabulary diverge."
                ),
                "arm_4_temporal": (
                    "Extraction coverage is the binding constraint. As a hard constraint over "
                    "incomplete extraction the FULL-SET oracle is predicted to go DOWN; the "
                    "covered-subset number is predicted to be roughly flat to slightly positive."
                ),
            },
            "what_would_refute_this": (
                "Any arm reaching delta >= +0.05 with McNemar p < 0.05, or a combined oracle that "
                "is additive across arms rather than overlapping."
            ),
            "_why_a_prediction_is_registered_for_a_measurement_session": (
                "So that a null cannot be read as 'we knew that' and a hit cannot be read as 'we "
                "expected that'. Both readings are available for free after the fact."
            ),
        },

        # ------------------------------------------------------------- expected check behaviour
        "expected_check_failures": {
            "unchanged_cue_check": {
                "_what": (
                    "tools/analyze_cue_overlap.py asserts lexical / dense / oracle at top-1 are "
                    "identical to the prior session when neither the cue set nor the candidate pool "
                    "changed."
                ),
                "will_fire_this_session": False,
                "_why_not": (
                    "Session G ships NO implementation change. The arms are measured offline "
                    "against Session F's committed dump; the binary, the gate artifact and the "
                    "candidate pool are all untouched. A re-scored run this session must reproduce "
                    "Session F exactly, and if it does not, that is a real alarm."
                ),
                "when_it_WOULD_fire": (
                    "Session H, if an arm is promoted and changes the pool. That must be "
                    "pre-registered then, as Session F's was."
                ),
            },
            "conformance": {
                "expected": "REJECTED, 0 section-4 findings, clock probe fail_no_time_dependence",
                "_why_that_is_correct": (
                    "Both are consequences of the empty injected set and the probe is right to "
                    "fail. The closing condition is the gate beginning to inject, and nothing in "
                    "Session G changes that."
                ),
            },
        },

        "_frozen_parameters": {
            "_none": (
                "Session G freezes nothing. No gate is refit, no artifact version is minted, and "
                "the binary is not changed. If that stops being true, this file is wrong and the "
                "session has drifted."
            )
        },
    }

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    PREREG_PATH.write_text(json.dumps(prereg, indent=2) + "\n", encoding="utf-8")

    print(f"WROTE {PREREG_PATH.relative_to(ROOT)}")
    print(f"  split digest      {split['digest']}")
    print(f"  corpus sha256     {corpus_sha}")
    print(f"  fidelity targets  lexical {k1['lexical']} / dense {k1['dense']} / oracle {k1['either_oracle']}")
    print(f"  promote at        delta >= +{PROMOTE_DELTA} with McNemar p < {MCNEMAR_ALPHA}")
    print(f"  cross-encoder bar stage P95 <= {CROSS_ENCODER_STAGE_BAR_MS} ms at 1 thread")
    print()
    print("Registered BEFORE any pool was reconstructed. This file refuses to overwrite itself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
