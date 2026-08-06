"""Are the lexical and dense cues redundant or complementary?

Number 3 reports what each cue can do alone. It cannot say whether they find the *same* gold
turns, and that distinction decides what the next session builds:

  redundant     -> content-similarity cues stack poorly because they see the same thing. Build
                   ONE structurally different cue (entity-graph or temporal, scoring on
                   relations rather than content) and measure the ceiling immediately.
  complementary -> the information is present and the FUSION is losing it. A third cue would
                   likely repeat the result; fix the combiner first.

Three measurements, driver-side, on the held-out split only:

  1. per-case Spearman rank correlation between the two cue scores
  2. which cue's top-k contains a gold turn, and the union over both
  3. the FITTED GATE's own top-k against those bounds -- the number that says whether the
     fusion captures what the cues jointly know

    python tools/analyze_cue_overlap.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.datasets import longmemeval  # noqa: E402
from marlowe_eval.metrics.records import Attributor  # noqa: E402

DEFAULT_RUN = REPO / "runs" / "session-f" / "heldout"
DEFAULT_OUT = REPO / "runs" / "session-f" / "cue-overlap.json"

# The immediately preceding published run, and the "before" side of every before/after number in
# this session. Read from its file rather than retyped; absent is not fatal.
#
# **Session E, not Session C.** Sessions C, D and E all reported the same lexical / dense / oracle
# because none of them changed the cue set -- that identity IS the unchanged-cue check. Session F
# changes the candidate pool, so it is the first session where the prior run has to be named
# precisely: the comparison is against what was last published, which is Session E.
PRIOR_OVERLAP = REPO / "runs" / "session-e" / "cue-overlap.json"

ARTIFACT = REPO / "crates" / "marlowe-memory" / "artifacts" / "gate-frozen-v5.json"


def iter_ndjson(path: Path):
    with path.open("r", encoding="utf-8", newline="\n") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    rx -= rx.mean()
    ry -= ry.mean()
    d = np.sqrt((rx**2).sum() * (ry**2).sum())
    return float((rx * ry).sum() / d) if d else 0.0


def rrf(a: np.ndarray, b: np.ndarray, k: int = 60) -> np.ndarray:
    """Reciprocal rank fusion — a fusion that uses only RANKS, so the cues' incomparable score
    scales cannot let one dominate. Included as a cheap reference point for the fitted gate."""
    ra = np.argsort(np.argsort(-a, kind="stable"))
    rb = np.argsort(np.argsort(-b, kind="stable"))
    return 1.0 / (k + 1 + ra) + 1.0 / (k + 1 + rb)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN, help="a run directory")
    parser.add_argument("--out", type=Path, default=None, help="where to write the JSON")
    parser.add_argument(
        "--record-verdict",
        action="store_true",
        help="stamp the measured floor verdict into the gate artifact, then REBUILD. "
        "`FrozenGate::load` refuses an artifact whose floor verdict is `fail` when its "
        "calibration would inject, so this is what arms that interlock.",
    )
    args = parser.parse_args()
    run_dir: Path = args.run.resolve()
    out_path: Path = (args.out.resolve() if args.out else run_dir.parent / "cue-overlap.json")

    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_map = corpus.gold_map()

    attributor = Attributor()
    for frame in iter_ndjson(run_dir / "run.jsonl"):
        body = frame.get("body")
        if frame.get("op") == "ingest" and isinstance(body, dict) and "written" in body:
            for written in body["written"]:
                attributor.record(written["turn_id"], list(written["memory_ids"]))

    per = defaultdict(list)
    for row in iter_ndjson(run_dir / "scored-candidates.ndjson"):
        # The v4 gate ranks on THREE keys -- `(score desc, margin desc, id asc)` -- and gates on a
        # fourth, `passes`. Reproducing its own top-1 needs all of them.
        #
        # Refused by name rather than defaulted. A pre-v4 dump carries
        # `min_calibrated_precision` and no `margin`; falling back to `score` alone would silently
        # compare a DIFFERENT ordering to the floor it is judged against, and the resulting number
        # would look entirely reasonable.
        for required in ("calibrated_precision", "score", "margin", "passes"):
            if required not in row:
                raise SystemExit(
                    f"{run_dir / 'scored-candidates.ndjson'} has no {required!r}. This is a "
                    "pre-v4 dump, or the run was made with --fit-mode (which loads no gate). "
                    "The fitted-gate ranking cannot be reproduced from it, and guessing an "
                    "ordering would produce a top-1 number that is not the gate's."
                )
        attribution, _ = attributor.attribute(
            row["memory_id"], gold_map.get(row["query_id"], frozenset())
        )
        # Session H's two extra ranking levels. Read with `.get` and a NAMED absence rather than
        # refused, because a Session F dump legitimately predates them -- and the shipped ranker
        # is reported as NOT AVAILABLE on such a dump rather than silently falling back to the
        # fused-gate order and being labelled as the shipped one.
        per[row["query_id"]].append(
            (
                row["lexical_bm25"],
                row["dense_cosine"],
                row["score"],
                row["margin"],
                attribution == "gold",
                row.get("survived_pruning"),
                row.get("rerank_score"),
            )
        )

    cases = {c.query_id: c for c in corpus.cases}
    queries = [q for q in per if q in cases and not cases[q].is_abstention]

    def order_of(scores: np.ndarray) -> np.ndarray:
        """Descending rank order for a single score. Stable, so ties keep the dump's own order,
        which is entry-id ascending -- the gate's final tiebreak."""
        return np.argsort(-scores, kind="stable")

    def gate_order(score: np.ndarray, margin: np.ndarray) -> np.ndarray:
        """The v4 gate's own ranking key, reproduced exactly.

        `(score desc, margin desc, id asc)` where `score` is the winning cue's within-query z and
        `margin` is its lead over its own runner-up -- pre-registered before the fit. np.lexsort
        takes its PRIMARY key last and is stable, so the trailing id-ascending tiebreak comes free
        from the dump's own row order.

        **No calibrated value appears here, and that is the point.** ADR-010: the ordering that
        decides the top of the ranking must come from a continuous score. Session D's key led with
        `calibrated_precision`, which is a step function, and 60.4% of cases ended in a tie at the
        maximum with the tiebreak deciding top-1 outright.
        """
        return np.lexsort((-margin, -score))

    def shipped_order(
        score: np.ndarray, margin: np.ndarray, survived: np.ndarray, rerank: np.ndarray
    ) -> np.ndarray:
        """The order the BINARY produces, reproduced from the dump's own columns.

        Five levels, matching `retrieve.rs::select_for_injection` exactly:

          1. survived pruning, survivors first
          2. rerank score descending, for candidates that were reranked
          3. score  -- the winning cue's z
          4. margin -- its lead over its own runner-up
          5. id     -- free, from the dump's stable row order

        `rerank` carries NaN where a candidate was not reranked (JSON `null`). NaN must sort
        LAST, and that is the whole subtlety: np.lexsort places NaN last under an ascending key,
        so the rerank level is expressed as `-rerank` with NaN mapped to +inf rather than by
        negating a NaN, which stays NaN and would sort unreranked candidates to the TOP.
        """
        rerank_key = np.where(np.isnan(rerank), np.inf, -rerank)
        # PRIMARY key last, per np.lexsort.
        return np.lexsort((-margin, -score, rerank_key, ~survived))

    def hit(order: np.ndarray, gold: np.ndarray, k: int) -> bool:
        """Unchanged in meaning from Session C: does the top-k intersect gold?

        It now takes an ORDER rather than a score array, so every ranker -- single-cue, RRF and
        the four-key gate -- is truncated and intersected by the same code. For a single score
        `order_of` is exactly what this function used to compute internally, so the lexical,
        dense and oracle numbers are bit-identical to the ones the floor is judged against.
        """
        return bool(set(order[:k].tolist()) & set(np.flatnonzero(gold).tolist()))

    # Is this a dump that carries Session H's columns at all? Decided ONCE over the whole dump
    # rather than per row: a dump where only some rows carry them is a mixed dump, and a
    # per-row fallback would quietly rank half the pool by one key and half by another.
    has_shipped = any(
        r[5] is not None or r[6] is not None for rows in per.values() for r in rows
    )

    rhos: list[float] = []
    ks = (1, 5, 10)
    tally = {k: defaultdict(int) for k in ks}
    n = 0
    for query in queries:
        lex = np.array([r[0] for r in per[query]])
        den = np.array([r[1] for r in per[query]])
        score = np.array([r[2] for r in per[query]])
        margin = np.array([r[3] for r in per[query]])
        gold = np.array([r[4] for r in per[query]])
        survived = np.array([True if r[5] is None else bool(r[5]) for r in per[query]])
        rerank = np.array([np.nan if r[6] is None else float(r[6]) for r in per[query]])
        if gold.sum() == 0:
            continue
        n += 1
        rhos.append(spearman(lex, den))
        lex_order = order_of(lex)
        den_order = order_of(den)
        rrf_order = order_of(rrf(lex, den))
        fused_order = gate_order(score, margin)
        shipped = shipped_order(score, margin, survived, rerank)
        for k in ks:
            L, D = hit(lex_order, gold, k), hit(den_order, gold, k)
            tally[k]["lexical"] += L
            tally[k]["dense"] += D
            tally[k]["both"] += L and D
            tally[k]["either"] += L or D
            tally[k]["neither"] += not L and not D
            tally[k]["fitted_gate"] += hit(fused_order, gold, k)
            tally[k]["rank_fusion_rrf"] += hit(rrf_order, gold, k)
            if has_shipped:
                tally[k]["shipped"] += hit(shipped, gold, k)

    baseline = {}
    if PRIOR_OVERLAP.exists() and PRIOR_OVERLAP.resolve() != out_path.resolve():
        baseline = json.loads(PRIOR_OVERLAP.read_text(encoding="utf-8"))["gold_in_top_k"]

    rho = np.array(rhos)
    by_k = {}
    for k in ks:
        t = tally[k]
        best_single = max(t["lexical"], t["dense"])
        fusion = t["fitted_gate"] / n
        entry = {
            "lexical": round(t["lexical"] / n, 4),
            "dense": round(t["dense"] / n, 4),
            "both": round(t["both"] / n, 4),
            "lexical_only": round((t["lexical"] - t["both"]) / n, 4),
            "dense_only": round((t["dense"] - t["both"]) / n, 4),
            "either_oracle": round(t["either"] / n, 4),
            "neither": round(t["neither"] / n, 4),
            "fitted_gate": round(fusion, 4),
            "rank_fusion_rrf": round(t["rank_fusion_rrf"] / n, 4),
            "oracle_gain_over_best_single": round((t["either"] - best_single) / n, 4),
            "fusion_gap_to_oracle": round((t["either"] - t["fitted_gate"]) / n, 4),
            "fusion_vs_best_single": round((t["fitted_gate"] - best_single) / n, 4),
        }
        if has_shipped:
            # The order the BINARY produces: pruning, then reranking, then the three levels the
            # fused gate already used. Reported BESIDE `fitted_gate` rather than replacing it,
            # so the pruning-and-rerank delta is readable off one table -- `fitted_gate` here is
            # the same ranker Session F published, computed over the same dump.
            entry["shipped"] = round(t["shipped"] / n, 4)
            entry["shipped_vs_fitted_gate"] = round((t["shipped"] - t["fitted_gate"]) / n, 4)
            entry["shipped_vs_best_single"] = round((t["shipped"] - best_single) / n, 4)

        # The pre-registered oracle read. Both denominators, because they answer different
        # questions and quoting only the larger fraction would be denominator-shopping.
        prior = baseline.get(str(k))
        if prior:
            oracle = prior["either_oracle"]
            v2_gate = prior["fitted_gate"]
            v2_best = max(prior["lexical"], prior["dense"])
            primary_denom = oracle - v2_gate
            secondary_denom = oracle - v2_best
            entry["fraction_of_gap_closed"] = (
                round((fusion - v2_gate) / primary_denom, 4) if primary_denom else None
            )
            entry["fraction_of_headroom_over_best_single"] = (
                round((fusion - v2_best) / secondary_denom, 4) if secondary_denom else None
            )
            entry["_gap_basis"] = {
                "prior_session": "session-e",
                "prior_fitted_gate": v2_gate,
                "prior_best_single": v2_best,
                "prior_either_oracle": oracle,
                "primary_denominator": round(primary_denom, 4),
                "secondary_denominator": round(secondary_denom, 4),
            }
        by_k[str(k)] = entry

    result = {
        "_what": "Do the two cues find the SAME gold turns? Held-out split, driver-side.",
        "_why": (
            "Number 3 says what each cue does alone. It cannot say whether a third cue or a "
            "better combiner is the higher-leverage next step, and this can."
        ),
        "cases": n,
        "rank_correlation": {
            "mean": round(float(rho.mean()), 4),
            "median": round(float(np.median(rho)), 4),
            "p10": round(float(np.percentile(rho, 10)), 4),
            "p90": round(float(np.percentile(rho, 90)), 4),
            "reading": (
                "Low correlation means the cues rank candidates differently, which is the "
                "precondition for them being complementary rather than redundant."
            ),
        },
        "gold_in_top_k": by_k,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"run: {run_dir.relative_to(REPO)}")
    print(f"held-out answerable cases: {n}")
    print(f"Spearman rho: mean {rho.mean():.3f}  median {np.median(rho):.3f}")
    print()
    print(f"{'ranker':22s} " + " ".join(f"{'top-'+str(k):>8}" for k in ks))
    rankers = ["lexical", "dense", "fitted_gate", "rank_fusion_rrf"]
    if has_shipped:
        rankers.append("shipped")
    rankers.append("either_oracle")
    for name in rankers:
        print(f"{name:22s} " + " ".join(f"{by_k[str(k)][name]:>8.3f}" for k in ks))
    if not has_shipped:
        print()
        print("  NOTE: this dump carries no `survived_pruning` / `rerank_score` columns, so the")
        print("  SHIPPED ranker is NOT AVAILABLE and is not reported. `fitted_gate` is Session F's")
        print("  ranker and is not a stand-in for it.")
    print()
    for k in ks:
        b = by_k[str(k)]
        print(
            f"top-{k:<2} lexical-only {b['lexical_only']:.3f}  dense-only {b['dense_only']:.3f}  "
            f"neither {b['neither']:.3f}  |  fusion vs best single {b['fusion_vs_best_single']:+.3f}  "
            f"gap to oracle {b['fusion_gap_to_oracle']:+.3f}"
        )

    # --- the pre-registered floor, stated as a verdict rather than left to the reader ---------
    top1 = by_k["1"]
    if baseline.get("1"):
        prior = baseline["1"]
        # **Re-based in Session F, and it makes the floor HARDER rather than easier.**
        #
        # Through Session E the floor was the prior session's best single cue, which was safe only
        # while the cues themselves were fixed. Consolidation changes the candidate pool, so it
        # changes the cues -- and against a frozen historical number a fusion could clear the floor
        # on a cue improvement it did not earn, which is precisely the comparison the floor exists
        # to prevent. The floor is therefore the best single cue measured in the SAME run.
        #
        # The superseded basis is printed beside it so the five-session series stays readable.
        floor = max(top1["lexical"], top1["dense"])
        superseded = max(prior["lexical"], prior["dense"])
        print()
        print("=" * 78)
        print("THE FLOOR (pre-registered, hard, no partial credit)")
        print(f"  required   >= {floor}   (THIS RUN's best single cue at top-1, post-consolidation)")
        print(f"  measured      {top1['fitted_gate']}")
        print(f"  superseded basis: {superseded} (Session E's best single cue; reported for")
        print("                    continuity only, and NOT the condition)")
        if top1["fitted_gate"] >= floor:
            print("  VERDICT: PASS")
        else:
            print("  VERDICT: FAIL -- the session fails outright. The finding is that calibrated")
            print("           precision is not a valid cross-cue arbitration signal at the top")
            print("           of the ranking. Not a tuning result.")
        print()
        print("THE ORACLE READ (fraction of the pre-committed +0.157 gap closed)")
        for k in ks:
            b = by_k[str(k)]
            if b.get("fraction_of_gap_closed") is None:
                continue
            print(
                f"  top-{k:<2} primary {b['fraction_of_gap_closed']:+.1%} "
                f"(/{b['_gap_basis']['primary_denominator']}, from the v2 gate)   "
                f"secondary {b['fraction_of_headroom_over_best_single']:+.1%} "
                f"(/{b['_gap_basis']['secondary_denominator']}, from best single)"
            )
        # The unchanged-cue check. Its normal reading is: the cue set did not change, so these
        # three must not move, and a move means the held-out POPULATION changed rather than the
        # ranking -- which invalidates every cross-session comparison.
        #
        # **Session F changes the candidate pool deliberately, so it is EXPECTED to fire**, and
        # that expectation is pre-registered in runs/session-f/PREREGISTRATION.json under
        # `expected_check_failures` -- written before the fit, precisely so that a real invariant
        # is not quietly reinterpreted on the day it first goes off.
        #
        # What would still be alarming is a move LARGER than the pool reduction can account for.
        # That is printed beside the drift rather than left for a reader to work out.
        drift = {
            name: (prior[name], top1[name])
            for name in ("lexical", "dense", "either_oracle")
            if abs(prior[name] - top1[name]) > 1e-9
        }
        print()
        if drift:
            print("  unchanged-cue check FIRED -- pre-registered as EXPECTED this session:")
            for name, (was, now) in drift.items():
                print(f"     {name}: {was} -> {now}  ({now - was:+.4f})")
            print("     Consolidation changes the candidate set on purpose, so these move. The")
            print("     check is doing its job; see PREREGISTRATION.json expected_check_failures.")
            print("     Still alarming would be a move the pool reduction cannot account for.")
        else:
            print("  unchanged-cue check: lexical / dense / oracle identical to the prior session")
            print("  NOTE: this session consolidates, so NO movement is itself surprising --")
            print("        it would mean the merge removed nothing that any cue ranked highly.")
        print("=" * 78)

        if args.record_verdict:
            verdict = "pass" if top1["fitted_gate"] >= floor else "fail"
            artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
            if artifact.get("state") != "fitted":
                raise SystemExit(
                    f"{ARTIFACT} is not fitted; there is no shape whose floor this verdict "
                    "would describe."
                )
            artifact["floor_verdict"] = verdict
            artifact["floor_required"] = floor
            artifact["floor_measured"] = top1["fitted_gate"]
            artifact["floor_read_from"] = str(out_path.relative_to(REPO)).replace("\\", "/")
            ARTIFACT.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
            print()
            print(f"recorded floor_verdict={verdict!r} into {ARTIFACT.relative_to(REPO)}")
            print("  now rebuild so the artifact is embedded:  cargo build --release")
            if verdict == "fail":
                print(
                    "  NOTE: this artifact is now REFUSED AT LOAD if its calibration ever "
                    "reaches the\n"
                    "  frozen threshold. It loads today only because it injects nothing. That is "
                    "the point:\n"
                    "  the shape cannot survive into the run that makes the gate inject."
                )

    print(f"\nwrote {out_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
