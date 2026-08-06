"""Session H's pre-registration — written BEFORE the sessionizer is measured and before any
held-out number is produced.

Session H **ships code**, which is what makes this file different from Session G's. Session G
registered decision rules for offline arms. This one has to freeze the things an implementation
gets to choose, because an implementation has many more degrees of freedom than an analysis does
and every one of them is a place to tune until the number is good.

The primary question is NOT registered here. It was registered in Session G, before any result
existed, at `runs/session-g/REGISTERED-QUESTION-in-session-rerank.json`, and it is referenced
rather than restated -- restating a bar is how a bar moves.

What IS registered here:

  * every free parameter the build would otherwise get to pick, frozen with a reason that does not
    depend on the outcome -- including the session scoring rule, which ADR-013 records as the
    hyperparameter Session G's registration left free;
  * a band for the **sessionizer**, whose agreement with the true partition is measured AFTER this
    file is committed, together with the agreement level at which timestamp contiguity is declared
    unusable and the session STOPS;
  * two instrument checks that run on the FIT split before anything is built -- ADR-010's "is this
    capped by the either-cue oracle" and ADR-013's "can the read vary at all";
  * the rows of the headline table that are **structurally pinned** and therefore are not
    measurements, registered as pinned in advance rather than explained afterwards.

It refuses to overwrite itself.
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
GATE_ARTIFACT = ROOT / "crates" / "marlowe-memory" / "gate" / "frozen-v1.json"
REGISTERED_QUESTION = ROOT / "runs" / "session-g" / "REGISTERED-QUESTION-in-session-rerank.json"
RECOST = ROOT / "runs" / "session-g" / "cross-encoder-recost.json"
FIT_GATE_REPORT = ROOT / "runs" / "session-h" / "fit-pools-gate.json"
RUN_DIR = ROOT / "runs" / "session-h"
PREREG_PATH = RUN_DIR / "PREREGISTRATION.json"

# The session-boundary gap. THIRTY MINUTES, and it is not swept.
#
# Chosen as the web-analytics convention for an inactivity timeout -- a value that exists
# independently of this corpus and was not derived from it. That is the whole reason for picking a
# convention over a fitted value: any threshold selected by looking at LongMemEval's inter-session
# gaps would be a parameter fit on the data it is then evaluated against, and ADR-013's second
# lesson is that a registration which fixes bands but leaves a free hyperparameter has not fixed
# the experiment.
#
# It also has to be defensible for the PRODUCTION mechanism, not just the benchmark: Marlowe's real
# sessions are terminal sessions, and a 30-minute gap is a session boundary there too.
SESSION_GAP_MS = 30 * 60 * 1000

# Inherited, not chosen. The registered question names "the arm-1 N=3 pruned pool" explicitly.
PRUNE_N = 3

# Q2's registered budget. The SHIPPED configuration is Q2's, so the candidate count is fixed by the
# registered question and this build gets no say in it.
RERANK_BUDGET = 10

# Session G's re-costing configuration, re-used unchanged so the 92.41 ms figure remains the thing
# being checked rather than a different measurement wearing its name.
CROSS_ENCODER = "L-2-int8"
MAX_SEQ_LEN = 256
RERANK_BATCH = 1
RERANK_THREADS = 1
RERANK_PROVIDER = "CPUExecutionProvider"

# Section 5.7's total cold retrieval P95.
TOTAL_BUDGET_MS = 300

# The sessionizer's bands.
GOLD_RETENTION_TOLERANCE = 0.02
POOL_FRACTION_INFLATION_MAX = 1.5

# ADR-013's instrument check.
MIN_DISCORDANT_CASES = 10

# ADR-010's cap. The full-pool either-cue oracle, re-based, as STATE.md carries it.
EITHER_CUE_ORACLE = 0.6435


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if PREREG_PATH.exists():
        print(f"REFUSING: {PREREG_PATH.relative_to(ROOT)} already exists.")
        print("A pre-registration that can be re-run after seeing a number is a post-registration")
        print("with a misleading filename. Delete it deliberately if it is genuinely wrong.")
        return 1

    for required in (SPLIT_PATH, REGISTERED_QUESTION, RECOST, FIT_GATE_REPORT):
        if not required.exists():
            print(f"REFUSING: {required.relative_to(ROOT)} does not exist.")
            return 1

    split = json.loads(io.open(SPLIT_PATH, encoding="utf-8").read())
    recost = json.loads(io.open(RECOST, encoding="utf-8").read())
    fit_gate = json.loads(io.open(FIT_GATE_REPORT, encoding="utf-8").read())
    corpus_sha = sha256_file(CORPUS_PATH) if CORPUS_PATH.exists() else None
    model_digests = recost["results"][CROSS_ENCODER]["digests"]

    prereg = {
        "session": "M0b Session H",
        "_what_this_session_is": (
            "The first session since B/C to SHIP a change to the scored retrieval path. Session G "
            "measured the reframe offline and nothing in the binary used it. This session builds "
            "session-level pruning and in-session cross-encoder reranking in Rust, and reports the "
            "system's numbers rather than a reconstruction's."
        ),
        "_written_before": (
            "the sessionizer was measured, before any fit-split band was re-derived, and before "
            "any held-out number existed. The fit-split POOLS were reconstructed first (see "
            "runs/session-h/fit-pools-gate.json) because the reconstruction had to be shown "
            "faithful before it could be registered against; no band was read from them."
        ),
        "split": {
            "digest": split["digest"],
            "fit_cases": split["fit_cases"],
            "heldout_cases": split["heldout_cases"],
            "_never_re_run": "tools/preregister_split.py ran once, in Session B.",
        },
        "corpus_sha256": corpus_sha,
        "corpus_variant": split["corpus_variant"],

        "the_primary_question_is_registered_elsewhere": {
            "path": "runs/session-g/REGISTERED-QUESTION-in-session-rerank.json",
            "_registered_at": "Session G, before any result existed",
            "_not_restated_here": (
                "Q1, Q2, the +0.05 delta, the McNemar alpha and the absolute floor all live in "
                "that file and are read from it. Restating a bar in a second file is how a bar "
                "moves: two copies drift, and the one that drifts is the one being quoted."
            ),
            "_floor_is_split_relative": (
                "The floor rule is 'reranked top-1 > best single cue top-1 ON THE SAME SPLIT'. "
                "That is 0.5415 on held-out, as the file records. On the fit split the same rule "
                "reads 0.5633 (runs/session-h/fit-pools-gate.json), which is the number a "
                "fit-split sanity read is judged against."
            ),
        },

        "frozen_parameters": {
            "_why_this_block_exists": (
                "ADR-013's second lesson: a registration that fixes bands but leaves a free "
                "hyperparameter has not fixed the experiment. An implementation has more free "
                "parameters than an analysis, so every one of them is frozen here with a reason "
                "that does not depend on the outcome."
            ),
            "session_gap_ms": {
                "value": SESSION_GAP_MS,
                "_why": (
                    "The web-analytics inactivity-timeout convention. Chosen because it exists "
                    "independently of this corpus. A threshold picked by looking at LongMemEval's "
                    "inter-session gaps would be fit on the data it is evaluated against."
                ),
                "_not_swept": "One value. No ladder. If it fails the band, the session stops.",
            },
            "prune_N": {
                "value": PRUNE_N,
                "_why": "Inherited. The registered question names the arm-1 N=3 pruned pool.",
            },
            "session_scoring_rule": {
                "value": "max aggregation over a session's turns, union of per-cue top-N",
                "_why": (
                    "Session G's PRIMARY -- the first rule declared and the only one with no free "
                    "parameter. ADR-013 records that Session G's registration left this rule free "
                    "and that its best variant is therefore not quotable. Freezing it HERE, before "
                    "the fit-split re-derivation, is what closes that miss."
                ),
                "_not_improved": (
                    "ADR-013: a better session scorer is worth approximately four cases. Pruning "
                    "needs A scorer, not a good one. Improving it is out of scope and any "
                    "improvement found while implementing is to be recorded and NOT adopted."
                ),
            },
            "reranker": {
                "model": CROSS_ENCODER,
                "digests": model_digests,
                "max_seq_len": MAX_SEQ_LEN,
                "batch": RERANK_BATCH,
                "threads": RERANK_THREADS,
                "provider": RERANK_PROVIDER,
                "_batch_is_structural": (
                    "Batch invariance FAILED for int8 at 0.037 logits (L-2) where the spike's fp32 "
                    "L-6 passed at exactly 0.000e+00. A fixed batch of 1 removes the failure mode "
                    "instead of tolerating it. It is asserted on the input tensor's leading "
                    "dimension and there is no batch parameter to raise, so a later optimization "
                    "cannot reintroduce it without deleting an assertion."
                ),
                "_provider_is_asserted": (
                    "ADR-013: a provider that is LISTED is not a provider that LOADS. CUDA was "
                    "advertised, failed on missing cuBLAS/cuDNN, and ORT fell back to CPU silently "
                    "-- producing a 'GPU' figure within 1% of the 1-thread CPU one. The "
                    "constructed session's active provider is checked against the requested one."
                ),
                "_no_gpu": "No GPU work. CPU clears the budget and GPU needs its own ADR.",
            },
            "shipped_configuration": {
                "value": f"rerank the top {RERANK_BUDGET} of the N={PRUNE_N} pruned pool",
                "_why": (
                    "This is Q2's registered budget, so the shipped candidate count is fixed by "
                    "the registered question rather than chosen by the build."
                ),
            },
            "pruning_placement": {
                "value": "AFTER features::extract_all, BEFORE ranking",
                "_why": (
                    "The frozen gate's isotonic curves were fit on margin distributions drawn from "
                    "~487-candidate pools. Computing features over ~50 candidates would feed those "
                    "curves a distribution they were not fit on -- two sides silently disagreeing, "
                    "which is the pattern this project has produced six instances of. It also "
                    "matches what Session G measured (index masking over already-computed scores), "
                    "so the fit-split re-derivation validates the thing that ships."
                ),
                "_consequence_registered_in_advance": (
                    "calibrated_precision is UNCHANGED BY CONSTRUCTION. See "
                    "structurally_pinned_rows."
                ),
            },
            "gated_path_only": {
                "value": "pruning and reranking run on Scoring::Gated only; Scoring::FitDump is untouched",
                "_why": (
                    "FitDump is the population tools/fit_gate.py calibrates on. Pruning it would "
                    "refit the gate on a different population as a side effect of a ranking change "
                    "-- a gate refit nobody registered."
                ),
            },
        },

        "sessionizer_band": {
            "_what_the_mechanism_is": (
                "Section 4.6 carries NO internal session boundary. The harness flattens a case's "
                "~48 haystack sessions into one SessionHistory whose session_id is the question id, "
                "so the real session survives only inside the string turn_id = f'{sid}-{t_idx}'. "
                "The binary derives sessions instead: sort a scope's candidates by occurred_at_ms "
                "and start a new session at any gap exceeding session_gap_ms."
            ),
            "_why_not_parse_turn_id": (
                "That is the harness's private encoding, and reach_pools.py explicitly declined to "
                "parse it back -- 'a property of the data today and not of the format'. Teaching "
                "the SHIPPING retrieval path to parse a benchmark's id convention is the "
                "implementation reshaping itself around the scoreboard. There is no fallback to it."
            ),
            "measured_on": "the FIT split only, before anything is built",
            "primary_read": {
                "quantity": f"gold retention at N={PRUNE_N} under DERIVED sessions vs under TRUE sessions",
                "band": f"|derived - true| <= {GOLD_RETENTION_TOLERANCE}",
                "_why_this_and_not_an_agreement_score": (
                    "Rand index and friends are symmetric, and the two error directions are not. "
                    "SPLITTING a true session is dangerous -- gold's session is partly pruned and "
                    "the answer is thrown away. MERGING is merely wasteful -- the pool is bigger "
                    "than intended and gold is still there. Gold retention reads the dangerous "
                    "direction directly; the pool-fraction guard below reads the wasteful one."
                ),
                "_can_it_vary": (
                    "Yes, in both directions, and it is not pinned by the max-aggregation identity "
                    "-- that identity fixes top-1, not which turns survive. A sessionizer that "
                    "splits lowers retention; one that merges raises it toward 1.0."
                ),
            },
            "guard_read": {
                "quantity": f"surviving pool fraction at N={PRUNE_N}, derived vs true",
                "band": f"derived <= {POOL_FRACTION_INFLATION_MAX} x true",
                "_why": (
                    "Gold retention alone is gameable by a degenerate sessionizer: merge every "
                    "turn into one session and retention is 1.0 with no pruning at all. The guard "
                    "is what makes the primary read meaningful."
                ),
            },
            "diagnostics_reported_regardless": [
                "homogeneity: fraction of derived sessions drawn from a single true session",
                "completeness: fraction of true sessions contained in a single derived session",
                "derived session count per case vs true session count per case",
                "the number of cases where any true session is SPLIT across derived sessions",
            ],
            "UNUSABLE_IF": {
                "condition": (
                    f"gold retention at N={PRUNE_N} under derived sessions falls more than "
                    f"{GOLD_RETENTION_TOLERANCE} below the true-session figure, OR the surviving "
                    f"pool fraction exceeds {POOL_FRACTION_INFLATION_MAX}x the true-session figure"
                ),
                "then": (
                    "STOP AND RAISE IT. Timestamp contiguity is not a usable proxy for session "
                    "structure on this corpus, and the session reports the sessionizer as the "
                    "blocking finding. Do NOT fall back to parsing turn_id, do not sweep the gap "
                    "threshold to rescue it, and do not proceed to the reranker on a pool whose "
                    "session boundaries are known to be wrong."
                ),
                "_why_stated_in_advance": (
                    "So that a disappointing agreement number cannot be met with a second "
                    "threshold and a sentence about how the first was never really the right one."
                ),
            },
        },

        "instrument_checks_run_on_the_fit_split_before_building": {
            "_why": (
                "Both are checks on the MEASURING DEVICE, not on the result, so running them on "
                "the fit split costs no held-out power. Both are things Session G learned the hard "
                "way and neither is inherited."
            ),
            "adr_010_is_the_reranker_capped_at_the_either_cue_oracle": {
                "_the_worry": (
                    "ADR-010: a fusion that only ARBITRATES between two cues cannot exceed the "
                    "either-cue oracle, because it can only ever pick a candidate one of them "
                    "already ranked first. Sessions D and E both shipped into that cap."
                ),
                "_the_claim_to_be_confirmed_not_assumed": (
                    "A cross-encoder computes a NEW score over (query, turn) text and can promote "
                    "a candidate neither cue ranked first, so its ceiling is 'gold is present in "
                    "the slate handed to it', not 'some cue ranked gold first'."
                ),
                "registered_read": f"presence ceiling at N={PRUNE_N} on the fit split",
                "definition": "fraction of fit cases where at least one gold turn survives pruning",
                "passes_if": f"> {EITHER_CUE_ORACLE} strictly",
                "if_it_fails": (
                    "The reranker IS capped at or below the either-cue oracle for this pool, the "
                    "premise of the registered question is refuted before any reranking happens, "
                    "and that is the session's finding. Report it as a refutation, not a setback."
                ),
                "also_reported": [
                    f"presence ceiling of the pruned top-{RERANK_BUDGET} slate (Q2's treatment arm)",
                    f"presence ceiling of the unpruned top-{RERANK_BUDGET} slate (Q2's control arm)",
                ],
            },
            "adr_013_can_the_registered_read_vary": {
                "_the_worry": (
                    "Arm 1's registered primary read returned +0.0000 at every N because it was an "
                    "IDENTITY, not a null. The registration verified that the shape can move the "
                    "metric and never verified that the read can vary."
                ),
                "registered_reads": [
                    "discordant cases: reranked top-1 != fused-gate top-1, on the fit split",
                    "both directions observed: at least one case where reranking GAINS gold and at "
                    "least one where it LOSES gold",
                ],
                "passes_if": (
                    f"discordant cases >= {MIN_DISCORDANT_CASES} AND both directions observed"
                ),
                "_why_ten": (
                    "Below roughly ten discordant pairs the exact McNemar test the registered "
                    "question specifies has no power at alpha=0.05, so a read that can technically "
                    "vary but almost never does is not a read that test can use. Stated as a "
                    "number in advance rather than as a judgment afterwards."
                ),
                "_why_both_directions": (
                    "One-directional movement is the signature of a partial identity. Arm 1's read "
                    "could not move at all; a read that can only improve is a different bug with "
                    "the same smell."
                ),
                "if_it_fails": "Q1 and Q2 report NOT MEASURED. They are not reported as nulls.",
            },
        },

        "structurally_pinned_rows": {
            "_what_this_is": (
                "Rows of the headline table that CANNOT move, registered as pinned in advance so "
                "that an unchanged number is read as an identity rather than as a measurement. "
                "This is ADR-013's lesson turned on this session's own reporting."
            ),
            "_correcting_the_session_brief": (
                "STATE.md and the Session H kickoff both implied the ceiling could move and that "
                "the section 4.3 gap might close. Neither is true given the registered pruning "
                "placement, and the correction is recorded here rather than explained afterwards."
            ),
            "ceiling_max_calibrated_precision": {
                "prediction": "unchanged at 0.3739, or lower",
                "_why": (
                    "Pruning happens after features::extract_all, so every candidate's "
                    "calibrated_precision is bit-identical to Session F's. The max over a SUBSET "
                    "can only equal or fall below the max over the whole. It cannot rise."
                ),
                "_therefore": "This row is not a measurement and is not reported as one.",
            },
            "single_cue_and_either_cue_top_1": {
                "prediction": "lexical@1, dense@1 and either-cue oracle@1 EXACTLY unchanged",
                "_why": (
                    "Session G proved the max-aggregation identity: under max aggregation a "
                    "session's score IS its best turn's score, so the globally top-scoring turn "
                    "always lies in a top-scoring session and pruning to top-N>=1 cannot displace "
                    "it. 458/458 case-cue pairs, zero violations. The proof is PARTITION-"
                    "INDEPENDENT -- it never uses any property of the partition -- so it holds for "
                    "DERIVED sessions exactly as it held for true ones."
                ),
                "_the_one_caveat": (
                    "It holds modulo exact ties at the maximum, where the sid-ascending tiebreak "
                    "could in principle select a different tied session. Session G measured zero "
                    "such violations. This session MEASURES it again on the derived partition "
                    "rather than inheriting it, because the tiebreak key changes with the partition."
                ),
                "_therefore": "Also not measurements. Measured only to confirm the identity holds.",
            },
            "the_unchanged_cue_check_is_a_NULL_INSTRUMENT_here": {
                "prediction": "it will NOT fire",
                "_why": (
                    "It reads exactly lexical@1, dense@1 and either_oracle@1 -- the three "
                    "quantities the identity above pins. So it cannot detect anything this session "
                    "does to the pool."
                ),
                "_correcting_STATE_md": (
                    "STATE.md registered this check as expected-to-fire because the pool changes. "
                    "That was wrong, and it was wrong for an instructive reason: 'the pool changed' "
                    "does not imply 'a read over the pool changed'. This is ADR-013's lesson "
                    "arriving through a STANDING CHECK instead of through a registered read."
                ),
                "_binding": (
                    "Its silence is NOT evidence the pruned pool is sound. The sessionizer band is "
                    "the instrument that reads that, and it is separate for this reason. If the "
                    "check DOES fire, the identity has broken on the derived partition and that is "
                    "a real alarm requiring the session to stop and explain it."
                ),
            },
        },

        "latency": {
            "_registered_before_measurement": (
                "Session G's 92.41 ms is a STAGE P95 over 10 pairs run as ONE batched forward. At "
                "batch 1 that becomes 10 sequential forwards, and Session G's own single-vs-batch "
                "loop is direct evidence the difference is not free. The registered question "
                "already requires 'a latency pass at the candidate count actually used, at 1 "
                "thread', so this is in scope and not a re-costing."
            ),
            "shipped_configuration": {
                "what": f"retrieval P95, top-{RERANK_BUDGET} of the N={PRUNE_N} pruned pool, batch 1, 1 thread",
                "bar_ms": TOTAL_BUDGET_MS,
                "_source": "section 5.7's total cold retrieval P95",
            },
            "q1_configuration": {
                "what": f"retrieval P95 reranking ALL ~50 candidates of the N={PRUNE_N} pruned pool",
                "bar_ms": None,
                "_why_no_bar": (
                    "The registered question states Q1 is explicitly NOT cost-matched and answers "
                    "'nothing about budget'. Q1 is a quality question."
                ),
            },
            "BOTH_ARE_REPORTED": (
                "Even if the Q1 configuration busts 300 ms. They are different numbers and both "
                "matter: the offline Q1 answer says what in-session reranking is WORTH, and the "
                "shipped configuration says what FITS. If they diverge, the K1 question becomes "
                "whether 300 ms is the right budget -- which is a different conversation from "
                "whether 0.95 is the right bar, and it should not be collapsed into it."
            ),
        },

        "expected_check_outcomes": {
            "conformance": {
                "expected": "REJECTED, 0 section-4 findings, clock probe fail_no_time_dependence",
                "_why_that_is_still_correct": (
                    "The gate does not begin injecting this session. Pruning after "
                    "features::extract_all leaves calibrated_precision bit-identical, the max is "
                    "0.3739 against a 0.95 threshold, and nothing clears it. Section 4.3's gap "
                    "does NOT close in Session H."
                ),
                "_run_anyway": "Before any quality number, as the standing check requires.",
            },
            "repro_runs_2": {
                "expected": "PASS, byte-identical across two cold runs with no embedding cache",
                "_why_it_is_load_bearing_this_session": (
                    "It is the check that catches a batch-invariance regression in the reranker. "
                    "It runs EARLY, before the quality numbers, not after."
                ),
            },
            "unchanged_cue_check": {
                "will_fire_this_session": False,
                "_see": "structurally_pinned_rows.the_unchanged_cue_check_is_a_NULL_INSTRUMENT_here",
            },
            "eval_pytest": {"expected": 72, "_never_modified": "eval/ is the scoreboard."},
            "cargo_test_workspace": {
                "baseline_at_session_start": 175,
                "expected": "175 plus whatever this session adds; no test removed or weakened",
            },
        },

        "explicitly_not_scoped": {
            "_standing": [
                "cues 3 to 5",
                "lowering the 0.95 threshold",
                "re-tuning the calibration resolution",
                "re-attempting consolidation without a fresh pre-registration",
                "attacking arbitration over the full pool again",
                "arms 2, 3 and 4 -- closed, not revisited",
            ],
            "_new_this_session": [
                "improving the session scorer -- worth about four cases, frozen above",
                "GPU execution providers",
                "refitting the gate on pruned pools -- named as the next lever, see below",
                "QA accuracy -- needs a credential that is not in the environment",
            ],
        },

        "the_named_next_lever": {
            "what": "refit the frozen gate on pruned-pool margin distributions",
            "_why_it_is_the_next_one": (
                "It is the only thing that can move the ceiling and close section 4.3's gap. "
                "Margins inside a ~50-turn pool are larger than margins inside a ~487-turn one, so "
                "a curve fit on the pruned distribution would assign materially higher calibrated "
                "precision -- which is exactly why reading the CURRENT curve on a pruned pool "
                "would be a silent mismatch, and exactly why this session does not do it."
            ),
            "_requires": (
                "its own pre-registration, a new gate artifact version, and a fresh fit. It is a "
                "gate refit, not a ranking change, and it is not smuggled into a ranking session."
            ),
        },

        "_predicted_outcome": {
            "_why_recorded": (
                "So that whatever happens, it can be compared against what was expected, and a "
                "surprise is visible as a surprise."
            ),
            "reranked_top_1": (
                "The kickoff's stated expectation is 0.65 to 0.75, on the grounds that "
                "cross-encoders typically add 10 to 20 points over bi-encoder retrieval on a small "
                "pool. Recorded as the EXPECTATION, not as a band -- the band is the registered "
                "question's +0.05 with McNemar p < 0.05 and an absolute floor, and it is not moved."
            ),
            "the_real_negative": (
                "R@1 barely moves. That would say the in-session ranking problem carries a similar "
                "bound to the full-pool one, and it is a publishable answer to the registered "
                "question rather than a failure of the session."
            ),
        },
    }

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    PREREG_PATH.write_text(json.dumps(prereg, indent=2) + "\n", encoding="utf-8")

    print(f"WROTE {PREREG_PATH.relative_to(ROOT)}")
    print(f"  split digest          {split['digest']}")
    print(f"  corpus sha256         {corpus_sha}")
    print(f"  fit-split floor       {fit_gate['fit_split_baseline_top1']['lexical']} (best single cue, fit)")
    print(f"  session gap           {SESSION_GAP_MS} ms, not swept")
    print(f"  prune N               {PRUNE_N}, inherited from the registered question")
    print(f"  scoring rule          max aggregation, union of per-cue top-N -- FROZEN HERE")
    print(f"  reranker              {CROSS_ENCODER}, batch {RERANK_BATCH}, {RERANK_THREADS} thread, {RERANK_PROVIDER}")
    print(f"  shipped config        top {RERANK_BUDGET} of the N={PRUNE_N} pruned pool")
    print()
    print("  sessionizer UNUSABLE IF gold retention falls more than "
          f"{GOLD_RETENTION_TOLERANCE} below true,")
    print(f"  or pool fraction exceeds {POOL_FRACTION_INFLATION_MAX}x true. Then STOP -- no fallback to turn_id parsing.")
    print()
    print("  PINNED (not measurements): ceiling, lexical@1, dense@1, either-oracle@1.")
    print("  The unchanged-cue check is a NULL INSTRUMENT here and will not fire.")
    print()
    print("Registered BEFORE the sessionizer was measured. This file refuses to overwrite itself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
