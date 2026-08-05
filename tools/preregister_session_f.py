"""Session F's pre-registration — written from the FIT split, before any held-out number.

Refuses without `tools/split.json` and without the dry-run sweep, and writes two files:

  runs/session-f/PREREGISTRATION.json                          the bands and the predictions
  crates/marlowe-memory/artifacts/consolidation-frozen-v1.json the frozen merge threshold

Both are inputs to `tools/fit_gate.py`, which refuses without the first, and to the build, which
embeds the second with `include_str!`. That is what makes "pre-registered" a property of the
filesystem rather than of somebody's recollection.

**The threshold is chosen by a rule that never reads gold.** `most selective threshold in the
binary's own SWEEP_THRESHOLDS whose fit-split candidate-pool reduction is at least
MIN_POOL_REDUCTION` — pool reduction is a property of the clustering alone. The alternative was to
pick the threshold that maximised the fit-split oracle, which would be choosing a parameter by the
metric it is about to be judged on, on gold labels, one split away from the number that gets
published.

    python tools/dump_consolidation.py --out runs/session-f    # the sweep, applying nothing
    python tools/preregister_session_f.py                      # this
    python tools/fit_gate.py
    cargo build --release
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.datasets import longmemeval  # noqa: E402

SPLIT_PATH = REPO / "tools" / "split.json"
RUN_DIR = REPO / "runs" / "session-f"
SWEEP_PATH = RUN_DIR / "consolidation-sweep.ndjson"
FEATURES_PATH = RUN_DIR / "fit-features.ndjson"
PREREG_PATH = RUN_DIR / "PREREGISTRATION.json"
ARTIFACT_PATH = REPO / "crates" / "marlowe-memory" / "artifacts" / "consolidation-frozen-v1.json"

# The linkage that ships. Swept both ways; single link was measured to chain — see the sweep table
# this script writes and `consolidate::Linkage`.
APPLIED_LINKAGE = "complete"

# The gold-blind selection rule. A threshold merging less than this is not doing anything the rest
# of the session could measure; the most selective one that clears it is the most conservative
# merge that still has an observable effect.
MIN_POOL_REDUCTION = 0.01

# Session E's published held-out numbers, the "before" side of every comparison. Read from its
# committed artifact rather than retyped.
SESSION_E_OVERLAP = REPO / "runs" / "session-e" / "cue-overlap.json"


def iter_ndjson(path: Path):
    with path.open("r", encoding="utf-8", newline="\n") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def wilson_half_width(p: float, n: int, z: float = 1.96) -> float:
    """Half-width of the Wilson interval — the resolution the held-out split actually has.

    Used to decide whether a band could be READ, not to decide a verdict. ADR-011's lesson is
    that a band narrower than the instrument is not a band.
    """
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(centre + spread - p, p - (centre - spread))


def main() -> int:
    for path in (SPLIT_PATH, SWEEP_PATH, FEATURES_PATH):
        if not path.exists():
            raise SystemExit(
                f"{path} does not exist. Run `python tools/dump_consolidation.py` first — the "
                "bands are derived from the dry-run sweep, and a pre-registration written "
                "without it would be a guess with a filename."
            )
    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))

    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold = corpus.gold_map()
    cases = {c.query_id: c for c in corpus.cases}
    turn_of = {
        f"m-{s.session_id}-{t.turn_id}-{i}": t.turn_id
        for s in corpus.sessions
        for i, t in enumerate(s.turns)
    }

    # -- the sweep -------------------------------------------------------------------------
    sweep: dict[str, dict] = {}
    histogram = None
    scanned = []
    for row in iter_ndjson(SWEEP_PATH):
        sweep[row["session_id"]] = {
            (p["linkage"], round(p["threshold"], 4)): p for p in row["sweep"]
        }
        h = np.array(row["histogram"], dtype=np.int64)
        histogram = h if histogram is None else histogram + h
        scanned.append(row["scanned"])
    if len(sweep) != split["fit_cases"]:
        raise SystemExit(
            f"the sweep covers {len(sweep)} sessions; the fit split has {split['fit_cases']}."
        )
    keys = sorted(next(iter(sweep.values())).keys())

    # -- the fit split's candidate scores --------------------------------------------------
    per: dict[str, list] = {}
    for row in iter_ndjson(FEATURES_PATH):
        per.setdefault(row["query_id"], []).append(
            (row["memory_id"], row["lexical_bm25"], row["dense_cosine"])
        )

    stats = {k: dict(lex=0, den=0, orc=0, goldsup=0, removed=0, largest=0) for k in keys}
    base = dict(lex=0, den=0, orc=0)
    n = 0
    pool = 0
    for query_id, rows in per.items():
        case = cases.get(query_id)
        if case is None or case.is_abstention:
            continue
        gold_turns = gold.get(query_id, frozenset())
        ids = [r[0] for r in rows]
        lexical = np.array([r[1] for r in rows])
        dense = np.array([r[2] for r in rows])
        is_gold = np.array([turn_of[i] in gold_turns for i in ids])
        if not is_gold.any():
            continue
        n += 1
        pool += len(rows)
        index = {m: k for k, m in enumerate(ids)}

        def top1(scores, keep=None):
            return int(np.argmax(np.where(keep, scores, -np.inf) if keep is not None else scores))

        by_lexical = is_gold[top1(lexical)]
        by_dense = is_gold[top1(dense)]
        base["lex"] += int(by_lexical)
        base["den"] += int(by_dense)
        base["orc"] += int(by_lexical or by_dense)

        for key in keys:
            point = sweep[case.session_id][key]
            keep = np.ones(len(ids), dtype=bool)
            for cluster in point["clusters"]:
                for member in cluster["merged"]:
                    if member in index:
                        keep[index[member]] = False
            slot = stats[key]
            slot["removed"] += int((~keep).sum())
            slot["largest"] = max(slot["largest"], point["largest_cluster"])
            if (is_gold & ~keep).any():
                slot["goldsup"] += 1
            if not keep.any():
                continue
            after_lexical = is_gold[top1(lexical, keep)]
            after_dense = is_gold[top1(dense, keep)]
            slot["lex"] += int(after_lexical)
            slot["den"] += int(after_dense)
            slot["orc"] += int(after_lexical or after_dense)

    table = []
    for key in keys:
        s = stats[key]
        table.append(
            {
                "linkage": key[0],
                "threshold": key[1],
                "pool_reduction": round(s["removed"] / pool, 6),
                "lexical_top1": round(s["lex"] / n, 4),
                "dense_top1": round(s["den"] / n, 4),
                "either_oracle_top1": round(s["orc"] / n, 4),
                "delta_oracle": round((s["orc"] - base["orc"]) / n, 4),
                "cases_with_gold_suppressed": s["goldsup"],
                "largest_cluster": s["largest"],
            }
        )

    # -- the gold-blind choice -------------------------------------------------------------
    eligible = [
        r
        for r in table
        if r["linkage"] == APPLIED_LINKAGE and r["pool_reduction"] >= MIN_POOL_REDUCTION
    ]
    if not eligible:
        raise SystemExit(
            f"no swept threshold under {APPLIED_LINKAGE} linkage reduces the fit-split pool by "
            f"{MIN_POOL_REDUCTION:.0%}. That is itself a finding — record it — but there is no "
            "threshold to freeze."
        )
    chosen = max(eligible, key=lambda r: r["threshold"])
    threshold = chosen["threshold"]

    total_pairs = int(histogram.sum())
    tail = {
        f"{b / len(histogram):.2f}": int(histogram[b:].sum()) for b in range(len(histogram))
    }

    heldout_n = 230  # Session E's held-out answerable-with-gold population, for the power read.
    prereg = {
        "session": "M0b Session F",
        "what_is_tested": (
            "Brief section 5.2/5.3 consolidation, measured on retrieval. Near-duplicate merging "
            "as a SUPERSESSION edge: a cluster elects one of its existing members and the rest "
            "leave the section 4.3 candidate set. No new belief is minted, so every retrievable "
            "memory keeps the id ingest returned for exactly one turn."
        ),
        "registered_against_split": split["digest"],
        "corpus_sha256": split["corpus_sha256"],
        "corpus_variant": split["corpus_variant"],
        "derived_from": {
            "sweep": "runs/session-f/consolidation-sweep.ndjson",
            "features": "runs/session-f/fit-features.ndjson",
            "population": "the FIT split only",
            "why": (
                "A threshold chosen against held-out cases is a threshold fit on the number it "
                "will later be judged by."
            ),
        },
        # ---------------------------------------------------------------------------------
        "disclosure": {
            "_what": (
                "Before any of this was measured, a PROXY reachability check was run on the "
                "HELD-OUT split, using token-Jaccard and TF-IDF cosine as stand-ins for the jina "
                "rule. It answered one question -- can pool reduction move the oracle at all -- "
                "and it reported +0.000 to +0.017 depending on the proxy and threshold."
            ),
            "_why_it_is_recorded": (
                "It touched held-out data, so it cannot be laundered into a prediction. Every "
                "band below is re-derived on the FIT split with the real rule. Recording the "
                "earlier read is what stops the re-derivation from being quoted as if no "
                "held-out data had ever been seen."
            ),
            "proxy_range_seen_on_heldout": [0.0, 0.0174],
            "proxy_rules": ["token Jaccard", "TF-IDF cosine"],
        },
        # ---------------------------------------------------------------------------------
        "reach_check": {
            "_what": (
                "ADR-010: check that a shape can move the metric it will be judged on, BEFORE "
                "registering the band."
            ),
            "can_consolidation_move_the_oracle": True,
            "why": (
                "Rank is defined over the candidate set. Removing a non-gold candidate ranked "
                "above gold strictly improves gold's rank, so the oracle is structurally "
                "reachable -- unlike Session E's per-query features, which were monotone "
                "within-query transforms and therefore rank-preserving by construction."
            ),
            "measured_headroom_on_the_fit_split": {
                "max_delta_oracle_over_the_whole_sweep": max(r["delta_oracle"] for r in table),
                "at": [
                    {"linkage": r["linkage"], "threshold": r["threshold"]}
                    for r in table
                    if r["delta_oracle"] == max(x["delta_oracle"] for x in table)
                ],
                "in_cases": round(max(r["delta_oracle"] for r in table) * n),
                "of_cases": n,
            },
        },
        # ---------------------------------------------------------------------------------
        "number_1_pool_reduction": {
            "_what": (
                "The session's PRIMARY quantity, and the only well-powered one. Fraction of the "
                "section 4.3 candidate pool removed by consolidation, on the held-out split."
            ),
            "_why_primary": (
                "It is counted over ~113,000 candidates rather than over 230 cases, so it has "
                "the resolution the top-1 rates do not. Session E's block-concentration played "
                "the same role."
            ),
            "predicted": chosen["pool_reduction"],
            "bands": [
                {
                    "condition": "reduction >= 0.10",
                    "verdict": (
                        "PREMISE CONFIRMED -- near-duplicates are a material fraction of the "
                        "pool and consolidation has something to work with"
                    ),
                },
                {
                    "condition": "0.03 <= reduction < 0.10",
                    "verdict": "PREMISE PARTLY HELD -- a small but non-trivial duplicate mass",
                },
                {
                    "condition": "reduction < 0.03",
                    "verdict": (
                        "PREMISE REFUTED -- the candidate pool is not meaningfully duplicated, "
                        "and the ~493-turn pool named in STATE.md is ~493 DISTINCT turns"
                    ),
                },
            ],
        },
        # ---------------------------------------------------------------------------------
        "number_2_oracle": {
            "_what": "The either-cue top-1 oracle after consolidation, against Session E's 0.6522.",
            "band": None,
            "_why_no_band": (
                "The reach check passes -- the metric is movable -- but the measured fit-split "
                "headroom is at most "
                f"{max(r['delta_oracle'] for r in table):+.4f}, which is one case in {n}. The "
                f"Wilson half-width at p=0.65 over {heldout_n} held-out cases is "
                f"{wilson_half_width(0.65, heldout_n):.4f}. A band whose width is an order of "
                "magnitude below the instrument's resolution cannot be read, and registering one "
                "anyway is ADR-011's error in the opposite direction from ADR-010's. Reported as "
                "a DIAGNOSTIC, beside 0.6522."
            ),
            "session_e_reference": 0.6522,
        },
        # ---------------------------------------------------------------------------------
        "number_3_floor": {
            "_what": "The fused gate's top-1 against the best single cue, both measured AFTER consolidation.",
            "_why_rebased": (
                "Through Session E the floor was Session C's best single cue, 0.5478. "
                "Consolidation changes the cues themselves, so a fusion could clear the "
                "inherited floor while still losing to its own inputs -- exactly what the floor "
                "exists to catch. The floor is therefore the post-consolidation best single cue "
                "measured in the SAME run. Session C's 0.5478 is reported beside it as the "
                "superseded basis so the five-session series stays readable."
            ),
            "rule": "fitted_gate_top1 >= max(lexical_top1, dense_top1), same run, same split",
            "superseded_basis": 0.5478,
            "hard": True,
            "partial_credit": False,
        },
        # ---------------------------------------------------------------------------------
        "predicted_outcome": {
            "_status": "REGISTERED AS THE PREDICTION, before the held-out run exists",
            "prediction": (
                "Consolidation does not move the either-cue oracle on this benchmark. The "
                "held-out pool reduction lands near "
                f"{chosen['pool_reduction']:.4f} and the oracle moves by at most one or two "
                "cases in either direction."
            ),
            "the_reason_and_it_has_two_halves": {
                "half_1_this_is_a_property_of_the_corpus": (
                    "LongMemEval-S haystacks are assembled from DISTINCT real sessions, so "
                    "distractors are topically related rather than textually duplicated. "
                    f"Measured over {total_pairs:,} pairwise similarities on the fit split, only "
                    f"{tail.get('0.98', 0) / total_pairs:.6%} of pairs reach 0.98 and "
                    f"{tail.get('0.90', 0) / total_pairs:.6%} reach 0.90. There is very little "
                    "for a near-duplicate rule to remove because there is very little "
                    "duplication present."
                ),
                "half_2_it_does_not_generalize_to_real_user_history": (
                    "On real history the same thing genuinely does get said repeatedly across "
                    "months, and the duplicate density would be higher. A null here is evidence "
                    "about THIS BENCHMARK'S candidate pool. It is NOT evidence that section 5.3 "
                    "consolidation is unnecessary in production."
                ),
                "_why_both_are_registered": (
                    "A bare null invites two opposite misreadings and both are wrong. Neither "
                    "half may be quoted without the other."
                ),
            },
            "what_would_refute_this": (
                "The proxies used lexical overlap and could not see semantic restatement; the "
                "jina rule can. If the real rule had found materially more structure than the "
                "proxies did, the prediction would be refuted and that would be the finding. It "
                f"did not: the largest oracle movement anywhere in the sweep is "
                f"{max(r['delta_oracle'] for r in table):+.4f}."
            ),
        },
        # ---------------------------------------------------------------------------------
        "the_named_lever_list_closes_here": {
            "_status": "REGISTERED BEFORE THE RESULT EXISTS",
            "statement": (
                "After this session the cross-encoder is out on latency (measured, "
                "docs/design/spike-2026-08-04-cross-encoder.md) and consolidation is measured. "
                "There is no further named mechanism that raises the either-cue oracle within "
                "M0b's budget. Whatever this session returns, the next conversation is about "
                "K1's DEFINITION -- what 0.95 injection precision means and whether it is the "
                "right bar for this cue set -- and not about the next lever."
            ),
            "_why_registered_rather_than_concluded": (
                "Session D's escalation read was recorded as confounded precisely because it was "
                "assembled after seeing a disappointing number. This is written first, so it "
                "cannot read as a reaction to one."
            ),
            "_this_is_not": "an escalation, or a recommendation to stop. It is a statement about the option space.",
        },
        # ---------------------------------------------------------------------------------
        "expected_check_failures": {
            "unchanged_cue_check": {
                "_what": (
                    "tools/analyze_cue_overlap.py asserts lexical / dense / oracle at top-1 are "
                    "identical to Session C, and warns that a move means the held-out POPULATION "
                    "changed rather than the ranking."
                ),
                "will_fire": True,
                "and_that_is_correct": (
                    "This session changes the candidate set on purpose. The check is doing its "
                    "job; it is registered as expected here so that a real invariant is not "
                    "quietly reinterpreted on the day it fires."
                ),
                "what_would_still_be_alarming": (
                    "a move in the UNCONSOLIDATED numbers, or a move larger than the pool "
                    "reduction can account for."
                ),
            }
        },
        # ---------------------------------------------------------------------------------
        "attribution_rule": {
            "_the_registered_risk": (
                "LongMemEval's gold labels are per-turn. If consolidation merged a gold turn "
                "into a belief with other turns, attribution could break -- a correct retrieval "
                "scoring as a miss because the merged memory is not the annotated turn."
            ),
            "resolution": (
                "The merge is a SUPERSESSION edge and the survivor is an existing per-turn "
                "belief, so every retrievable memory keeps the id ingest returned for exactly "
                "one turn. Attributor.attribute is exact and eval/ is untouched. This is what "
                "HP5 already specifies -- 'merges are supersedes edges and are therefore "
                "undoable' -- so the attribution property falls out of the designed mechanism "
                "rather than being arranged for the benchmark."
            ),
            "what_was_ruled_out_and_why": (
                "A merged belief with a NEW id. Attributor.record builds its reverse map as "
                "_turn_of[memory_id] = turn_id, LAST WRITE WINS, so a belief reported under "
                "several turns resolves to whichever was recorded last, silently; and "
                "evidence_precision drops unattributable injections from its denominator "
                "entirely, so a store of merged beliefs would report a vacuous precision over an "
                "empty set. Neither failure is visible in any number the harness prints."
            ),
            "the_cost_is_measured_not_corrected": (
                "When a cluster contains gold and elects a different member, that case is lost. "
                "Under a per-turn evidence key that is a GENUINE retrieval failure, not an "
                "attribution artifact, and correcting it would be the implementation authoring "
                "its own measurement. Reported as cases_with_gold_suppressed."
            ),
            "fit_split_cost_at_the_chosen_threshold": chosen["cases_with_gold_suppressed"],
        },
        # ---------------------------------------------------------------------------------
        "frozen_parameters": {
            "threshold": threshold,
            "linkage": APPLIED_LINKAGE,
            "survivor_rule": "latest origin_event, then id ascending",
            "_survivor_rule_why": (
                "Supersession means a newer belief displaces an older one, and LongMemEval's "
                "knowledge-update category makes the LATEST statement gold. Electing the "
                "earliest member would systematically suppress gold across that whole category "
                "and present as an unexplained retrieval regression."
            ),
            "selection_rule": (
                f"most selective threshold in the binary's SWEEP_THRESHOLDS whose FIT-SPLIT pool "
                f"reduction is at least {MIN_POOL_REDUCTION}, under {APPLIED_LINKAGE} linkage"
            ),
            "_selection_rule_is_gold_blind": (
                "Pool reduction is a property of the clustering alone. Choosing the threshold "
                "that maximised the fit-split oracle would be selecting a parameter by the "
                "metric it is about to be judged on, using gold labels, one split away from the "
                "published number."
            ),
            "_frozen_under": (
                "HP1's freeze scope, which names 'consolidation merge thresholds (HP5)' "
                "explicitly. It is on the measured path and is not a quality knob."
            ),
            "linkage_choice_is_measured": {
                "rejected": "single",
                "why": (
                    "jina's similarity distribution over chat turns is anisotropic -- "
                    f"{tail.get('0.70', 0) / total_pairs:.2%} of all pairs reach 0.70 -- so a "
                    "transitive linkage chains. At threshold 0.70 single link removed 99.8% of "
                    "the fit-split pool and built a 616-member cluster: the entire session "
                    "declared one near-duplicate. Complete link bounds a cluster's diameter by "
                    "the threshold. Both are swept and both tables are recorded."
                ),
            },
        },
        "fit_split_sweep": table,
        "fit_split_baseline": {
            "cases": n,
            "mean_pool": round(pool / n, 2),
            "lexical_top1": round(base["lex"] / n, 4),
            "dense_top1": round(base["den"] / n, 4),
            "either_oracle_top1": round(base["orc"] / n, 4),
        },
        "similarity_distribution": {
            "_what": "every pairwise cosine on the fit split, as a survival function",
            "total_pairs": total_pairs,
            "mean_candidates_per_session": round(float(np.mean(scanned)), 2),
            "at_or_above": {k: v for k, v in tail.items() if v > 0},
        },
    }

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    PREREG_PATH.write_text(json.dumps(prereg, indent=2) + "\n", encoding="utf-8")

    artifact = {
        "version": "consolidation-v1",
        "state": "registered",
        "rule": (
            f"{APPLIED_LINKAGE}-link near-duplicate merge over dense cosine; survivor = latest "
            "origin_event, then id ascending; losers superseded"
        ),
        "threshold": threshold,
        "derived_from": "runs/session-f/PREREGISTRATION.json",
        "split_digest": split["digest"],
        "notes": (
            f"Chosen by a gold-blind rule: the most selective swept threshold whose FIT-SPLIT "
            f"candidate-pool reduction is at least {MIN_POOL_REDUCTION}. Measured reduction at "
            f"this threshold: {chosen['pool_reduction']:.4f}."
        ),
    }
    ARTIFACT_PATH.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")

    print(f"fit split: {n} cases with gold, mean pool {pool / n:.1f}")
    print(f"baseline:  lexical {base['lex'] / n:.4f}  dense {base['den'] / n:.4f}  "
          f"oracle {base['orc'] / n:.4f}")
    print()
    print(f"{'link':>9} {'thr':>6} {'pool-':>7} {'oracle':>8} {'d-orc':>8} {'goldsup':>8} {'maxclu':>7}")
    for row in table:
        print(
            f"{row['linkage']:>9} {row['threshold']:6.2f} {row['pool_reduction']:7.2%} "
            f"{row['either_oracle_top1']:8.4f} {row['delta_oracle']:+8.4f} "
            f"{row['cases_with_gold_suppressed']:8d} {row['largest_cluster']:7d}"
        )
    print()
    print(f"CHOSEN: {APPLIED_LINKAGE} linkage at {threshold} "
          f"(pool -{chosen['pool_reduction']:.2%}, gold suppressed in "
          f"{chosen['cases_with_gold_suppressed']} fit cases)")
    print(f"wrote {PREREG_PATH.relative_to(REPO)}")
    print(f"wrote {ARTIFACT_PATH.relative_to(REPO)}")
    print("\nnow rebuild so the threshold is embedded:  cargo build --release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
