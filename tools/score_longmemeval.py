"""Score the fitted gate against LongMemEval-S, held-out and all-500.

**`eval/` is not modified by this script or by anything in `tools/`.** The harness exposes
fixtures through `--corpus` and reaches a real corpus only through `verify-corpus`; that
omission is the scoreboard's choice, and an M0b session adding `--corpus-path` would be the
implementation reshaping the measurement's interface for its own convenience. So this driver
imports `marlowe_eval` as a library and calls the same `run()` and `write_artifacts()` the CLI
calls. If `--corpus-path` is right long-term it is an M0a change, argued separately.

Reporting rule, and it is the reason this file exists rather than two CLI invocations:

  * the **held-out** figure is the headline
  * the **all-500** figure ships with its contamination attached to the value itself, the same
    treatment `corpus_variant` gets

A bare contaminated number next to a bare clean one gets quoted wrong, so there is no place in
the output where the all-500 value appears without the label.

Two driver-side diagnostics are computed from `run.jsonl` and are **labelled as driver-side**,
because they are not harness metrics and must not be mistaken for them:

  coverage      fraction of answerable cases with at least one GOLD memory injected. Precision
                without it is gameable by injecting almost nothing.
  curve         precision and coverage as a function of a swept calibrated-precision cut. This
                is where pre-registered Number 2 is read from. Sweeping a cut for REPORTING is
                not tuning; the shipped threshold is frozen at 0.95 and does not move.

    python tools/score_longmemeval.py --out runs/session-b
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.datasets import longmemeval  # noqa: E402
from marlowe_eval.datasets.model import Corpus  # noqa: E402
from marlowe_eval.metrics.records import Attributor  # noqa: E402
from marlowe_eval.runner import RunConfig, run, write_artifacts  # noqa: E402
from marlowe_eval_stubs import build_target  # noqa: E402

SPLIT_PATH = REPO / "tools" / "split.json"
ARTIFACT_PATH = REPO / "crates" / "marlowe-memory" / "artifacts" / "gate-frozen-v1.json"
BINARY = REPO / "target" / "release" / "marlowe.exe"

CONTAMINATION = (
    "the frozen gate's weights and isotonic calibration were fit on the {fit_cases} cases of "
    "the pre-registered fit split, which are a subset of these {n}. This value is "
    "optimistically biased and is NOT the headline. The headline is the held-out figure."
)

# Pre-registered in runs/session-b/PREREGISTRATION.json before any of this ran.
NUMBER_2_COVERAGE_TARGET = 0.25
BUDGET_TOKENS = 7000
BUDGET_P95_MS = 300
ABSTENTION_INJECTION_CEILING = 0.20
DEGENERATE_COVERAGE_FLOOR = 0.05


def subset(corpus: Corpus, query_ids: set[str], suffix: str) -> Corpus:
    cases = tuple(c for c in corpus.cases if c.query_id in query_ids)
    keep = {c.session_id for c in cases}
    return Corpus(
        name=f"{corpus.name}{suffix}",
        sessions=tuple(s for s in corpus.sessions if s.session_id in keep),
        cases=cases,
        categories=corpus.categories,
    )


def iter_ndjson(path: Path):
    """Yield one parsed object per NDJSON line.

    **File iteration, never `str.splitlines()`.** `splitlines()` also splits on U+2028, U+2029
    and U+0085, which JSON does not require to be escaped inside a string — and LongMemEval
    transcripts contain them. Splitting there tears a frame in half and the parse fails partway
    through a 470 KB line, which is how this was found. Python's file iterator splits on `\\n`
    alone, which is what section 4.0.2 defines a frame boundary to be.
    """
    with path.open("r", encoding="utf-8", newline="\n") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def read_records(transcript: Path, corpus: Corpus) -> list[dict]:
    """Rebuild per-query records from the harness's own `run.jsonl`.

    `run.jsonl` is the section 4.0.3 wire log, not a record dump, and `RunResult` does not
    expose the records the report was built from. So they are reconstructed here from the same
    two things the harness itself joins on:

      * the section 4.6 ingest responses, for `written[].turn_id -> memory_ids`
      * the section 4.7 answer responses, for the embedded retrieval result

    The join runs through the harness's **own** `Attributor`, imported rather than
    reimplemented. A hand-rolled attribution here would be a second, unvalidated definition of
    "gold" sitting beside the one the report uses, and the two would drift.
    """
    attributor = Attributor()
    responses: list[dict] = []

    for frame in iter_ndjson(transcript):
        body = frame.get("body")
        if not isinstance(body, dict):
            continue
        if frame.get("op") == "ingest" and "written" in body:
            for written in body["written"]:
                attributor.record(written["turn_id"], list(written["memory_ids"]))
        elif frame.get("op") == "answer" and "retrieval" in body:
            responses.append(body)

    gold_map = corpus.gold_map()
    case_of = {c.query_id: c for c in corpus.cases}

    records = []
    for body in responses:
        query_id = body["query_id"]
        case = case_of.get(query_id)
        if case is None:
            continue
        gold_turns = gold_map.get(query_id, frozenset())
        retrieval = body["retrieval"]
        injected = []
        for item in retrieval["injected"]:
            attribution, turn_id = attributor.attribute(item["memory_id"], gold_turns)
            injected.append(
                {
                    "memory_id": item["memory_id"],
                    "score": item["score"],
                    "calibrated_precision": item["calibrated_precision"],
                    "attribution": attribution,
                    "turn_id": turn_id,
                }
            )
        records.append(
            {
                "query_id": query_id,
                "category": case.category,
                "is_abstention": case.is_abstention,
                "injected": injected,
                "retrieval_tokens": retrieval["cost"]["retrieval_tokens"],
                "latency_ms": retrieval["cost"]["latency_ms"]["total"],
                "abstention_reason": retrieval.get("abstention_reason"),
                "considered": retrieval["considered"],
                "gate_version": retrieval["gate"]["version"],
            }
        )
    return records


def diagnostics(records: list[dict], scored: dict[str, list[dict]]) -> dict:
    """Driver-side only. Not harness metrics; labelled as such wherever they appear.

    `records` are what actually went on the wire (the injected set at the frozen threshold).
    `scored` is every candidate the gate judged, carrying the implementation's own
    `calibrated_precision` — that is what the swept curve is built from, because when the gate
    abstains everywhere the wire carries nothing to sweep.
    """
    answerable = [r for r in records if not r.get("is_abstention")]
    abstention = [r for r in records if r.get("is_abstention")]
    answerable_ids = [r["query_id"] for r in answerable]

    def at_cut(cut: float) -> dict:
        gold = distractor = 0
        covered = 0
        cases_with_any = 0
        kept_total = 0
        for query_id in answerable_ids:
            kept = [c for c in scored.get(query_id, ()) if c["calibrated_precision"] >= cut]
            if kept:
                cases_with_any += 1
            kept_total += len(kept)
            hit = False
            for item in kept:
                if item["attribution"] == "gold":
                    gold += 1
                    hit = True
                elif item["attribution"] == "distractor":
                    distractor += 1
            if hit:
                covered += 1
        attributed = gold + distractor
        n = len(answerable_ids)
        return {
            "cut": round(cut, 6),
            "precision": round(gold / attributed, 6) if attributed else None,
            "coverage": round(covered / n, 6) if n else 0.0,
            "cases_with_any_injection": cases_with_any,
            "mean_candidates_passing_per_case": round(kept_total / n, 3) if n else 0.0,
            "gold": gold,
            "distractor": distractor,
        }

    # Breakpoints where the gate's own calibration has them, plus a coarse grid.
    observed = sorted({round(c["calibrated_precision"], 6) for rows in scored.values() for c in rows})
    grid = sorted({round(x / 20, 4) for x in range(21)} | set(observed))
    curve = [at_cut(c) for c in grid]

    injections_on_abstention = sum(len(r["injected"]) for r in abstention)
    wire_gold = sum(
        1 for r in answerable for i in r["injected"] if i["attribution"] == "gold"
    )
    wire_attributed = sum(
        1 for r in answerable for i in r["injected"] if i["attribution"] in ("gold", "distractor")
    )
    wire_covered = sum(
        1 for r in answerable if any(i["attribution"] == "gold" for i in r["injected"])
    )

    return {
        "_note": (
            "DRIVER-SIDE DIAGNOSTICS, not harness metrics. `coverage` is reported beside every "
            "precision because precision alone is gameable by injecting almost nothing."
        ),
        "_curve_caveat": (
            "The swept curve applies the GATE only. The section 5.7 token budget is not "
            "re-applied at each cut, so at permissive cuts the curve's coverage is an UPPER "
            "BOUND on what would actually be injected. `mean_candidates_passing_per_case` is "
            "reported at every point so a reader can see where the budget would start to bite "
            "(roughly 15-40 LongMemEval turns fit in 7,000 estimated tokens)."
        ),
        "_curve_source": (
            "the implementation's own score and calibrated_precision for every scored "
            "candidate, read from --dump-gate-features. Not recomputed in Python: a second "
            "implementation of the gate's arithmetic with nothing comparing the two is the "
            "mismatch pattern this project keeps paying for."
        ),
        "answerable_cases": len(answerable),
        "abstention_cases": len(abstention),
        "injections_on_abstention_cases": injections_on_abstention,
        "scored_candidates": sum(len(v) for v in scored.values()),
        "on_the_wire_at_frozen_threshold": {
            "precision": round(wire_gold / wire_attributed, 6) if wire_attributed else None,
            "coverage": round(wire_covered / len(answerable), 6) if answerable else 0.0,
            "gold": wire_gold,
            "attributed": wire_attributed,
            "cases_with_any_injection": sum(1 for r in answerable if r["injected"]),
        },
        "curve": curve,
    }


def number_two(curve: list[dict]) -> dict:
    """Pre-registered Number 2: precision at the cut where coverage first reaches 0.25."""
    reachable = max((p["coverage"] for p in curve), default=0.0)
    if reachable < NUMBER_2_COVERAGE_TARGET:
        return {
            "value": None,
            "reason": (
                f"coverage never reaches {NUMBER_2_COVERAGE_TARGET} anywhere on the curve "
                f"(maximum {reachable:.4f}), so the pre-registered read point does not exist. "
                "Reported as unmeasurable rather than substituted with a nearby point."
            ),
            "max_coverage": round(reachable, 6),
        }
    # The cut is the highest one that still reaches the target coverage: the most selective
    # point that meets the pre-registered recall, which is the read the band was written for.
    eligible = [p for p in curve if p["coverage"] >= NUMBER_2_COVERAGE_TARGET]
    point = max(eligible, key=lambda p: p["cut"])
    if point["precision"] is None:
        return {"value": None, "reason": "no attributable injections at that cut"}
    value = point["precision"]
    if value >= 0.50:
        verdict = "cue working"
    elif value >= 0.20:
        verdict = "functioning, cue set incomplete"
    else:
        verdict = "implementation suspect"
    return {
        "value": value,
        "read_at_cut": point["cut"],
        "coverage_there": point["coverage"],
        "verdict": verdict,
        "band_source": "runs/session-b/PREREGISTRATION.json, written before the fit",
    }


def read_scored(dump: Path, transcript: Path, corpus: Corpus) -> dict[str, list[dict]]:
    """Every candidate the gate judged, joined to gold. Keyed by query_id.

    The gold join reuses the same `Attributor` the report was built with, rebuilt from the
    transcript's ingest responses.
    """
    attributor = Attributor()
    for frame in iter_ndjson(transcript):
        body = frame.get("body")
        if frame.get("op") == "ingest" and isinstance(body, dict) and "written" in body:
            for written in body["written"]:
                attributor.record(written["turn_id"], list(written["memory_ids"]))

    gold_map = corpus.gold_map()
    out: dict[str, list[dict]] = defaultdict(list)
    for row in iter_ndjson(dump):
        if "calibrated_precision" not in row:
            raise SystemExit(
                "the dump carries no calibrated_precision: it was produced in --fit-mode, "
                "which loads no gate. The scoring run must dump WITH the gate."
            )
        attribution, turn_id = attributor.attribute(
            row["memory_id"], gold_map.get(row["query_id"], frozenset())
        )
        out[row["query_id"]].append(
            {
                "memory_id": row["memory_id"],
                "score": row["score"],
                "calibrated_precision": row["calibrated_precision"],
                "passes": row["passes"],
                "attribution": attribution,
                "turn_id": turn_id,
            }
        )
    return dict(out)


def score_one(
    corpus: Corpus, out_dir: Path, seed: int, clock: int
) -> tuple[dict, list[dict], dict[str, list[dict]]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dump = out_dir / "scored-candidates.ndjson"
    target = (
        f"exec://{BINARY} --eval-adapter --profile-root {{profile_root}} "
        f"--dump-gate-features {dump}"
    )
    result = run(
        lambda c: build_target(target, c),
        {corpus.name: corpus},
        # **Benchmark only, and the dump is why.** The harness spawns a fresh process per
        # suite -- the clock probe alone spawns four -- and every spawn opens the dump with
        # truncate, so a probe running after the benchmark would leave a dump containing the
        # probe's candidates and nothing else. The curve would then be built from four
        # synthetic queries while every other number came from 249 real ones, and nothing in
        # the output would say so. The probes are run separately, without a dump.
        RunConfig(target=target, seed=seed, clock_ms=clock, suites=("benchmark",)),
    )
    paths = write_artifacts(result, out_dir)
    transcript = Path(paths["transcript"])
    return (
        result.report,
        read_records(transcript, corpus),
        read_scored(dump, transcript, corpus),
    )


def benchmark_block(report: dict) -> dict:
    """The per-corpus block the harness scored. One corpus per run here."""
    benchmarks = report.get("benchmarks") or {}
    if len(benchmarks) != 1:
        raise SystemExit(f"expected exactly one scored corpus, got {sorted(benchmarks)}")
    return next(iter(benchmarks.values()))


def budget_verdict(report: dict, records: list[dict]) -> dict:
    """Read from the harness's own cost block, never recomputed from the records."""
    block = benchmark_block(report)
    cost = (block.get("answer_accuracy") or {}).get("cost") or {}
    tokens = cost.get("retrieval_tokens") or {}
    latency = cost.get("latency_ms") or {}
    p95 = latency.get("p95")
    over_token = tokens.get("over_budget")
    if p95 is None or over_token is None:
        raise SystemExit(
            "the harness's cost block did not carry a p95 latency and an over-budget count. "
            "Refusing to substitute a number computed here: section 5.7's pair is the "
            "harness's to report."
        )
    passes = over_token == 0 and p95 <= BUDGET_P95_MS
    return {
        "passes": passes,
        "retrieval_p95_ms": p95,
        "p95_budget_ms": BUDGET_P95_MS,
        "retrieval_tokens_max": tokens.get("max"),
        "cases_over_token_budget": over_token,
        "token_budget": BUDGET_TOKENS,
        "source": "harness report.json cost block, not recomputed",
        "if_violated": (
            "the precision numbers are VOID, not caveated: K1 is defined at these budgets."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(REPO / "runs" / "session-b"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--clock", type=int, default=1_780_000_000_000)
    args = parser.parse_args()

    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    if artifact.get("state") != "fitted":
        raise SystemExit(
            f"{ARTIFACT_PATH} is not fitted. Run `python tools/fit_gate.py` and "
            "`cargo build --release` first."
        )
    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    if artifact["split_digest"] != split["digest"]:
        raise SystemExit(
            "the artifact was fit under a different split than tools/split.json now holds "
            f"({artifact['split_digest']} vs {split['digest']}). Refusing to report a "
            "held-out number against a split the gate did not actually hold out."
        )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    corpus = longmemeval.load(REPO / split["corpus_path"])

    runs = {}
    for name, ids, suffix in (
        ("heldout", set(split["heldout"]), "-heldout"),
        ("all", {c.query_id for c in corpus.cases}, ""),
    ):
        print(f"scoring {name} ({len(ids)} cases) ...")
        sub = subset(corpus, ids, suffix)
        report, records, scored = score_one(sub, out / name, args.seed, args.clock)
        runs[name] = {"report": report, "records": records, "scored": scored}
        print(f"  -> {out / name}")

    heldout_diag = diagnostics(runs["heldout"]["records"], runs["heldout"]["scored"])
    all_diag = diagnostics(runs["all"]["records"], runs["all"]["scored"])

    heldout_ep = benchmark_block(runs["heldout"]["report"])["evidence_precision"]
    all_ep = benchmark_block(runs["all"]["report"])["evidence_precision"]
    n2 = number_two(heldout_diag["curve"])
    budget = budget_verdict(runs["heldout"]["report"], runs["heldout"]["records"])

    at_op = heldout_diag["on_the_wire_at_frozen_threshold"]
    abstention_rate = (
        heldout_diag["injections_on_abstention_cases"] / heldout_diag["abstention_cases"]
        if heldout_diag["abstention_cases"]
        else 0.0
    )

    def precision_block(ep: dict, split_name: str, n: int) -> dict:
        """One reported precision, with everything that qualifies it attached to the value.

        `evidence_precision` is a ratio over ATTRIBUTED injections, so it reads 0.0 both when
        every injection was wrong and when there were no injections at all. Those are opposite
        findings and the field cannot tell them apart, so the distinction is carried here --
        beside the value, not in surrounding prose.
        """
        attributed = ep["gold"] + ep["distractor"]
        block = {
            "value": ep["value"],
            "split": split_name,
            "n": n,
            "corpus_variant": split["corpus_variant"],
            "metric": "evidence_precision",
            "gold": ep["gold"],
            "distractor": ep["distractor"],
            "attributed_injections": attributed,
            "note": (
                "precision against benchmark gold evidence. NOT the K1 headline, which is "
                "human-judged and needs a label set that does not exist yet."
            ),
        }
        if attributed == 0:
            block["value_is_vacuous"] = True
            block["vacuity"] = (
                "0.0 here means NOTHING WAS INJECTED, not that the injections were wrong. The "
                "ratio has an empty denominator and the metric cannot distinguish the two. "
                "Read number_1_operating_point and number_2_cue_capability instead."
            )
        return block

    summary = {
        "session": "M0b Session B",
        "what_this_is": (
            "One lexical cue and the frozen gate. NOT the five-cue system K1 measures; a low "
            "number is a statement about an incomplete cue set."
        ),
        "gate": {
            "version": artifact["version"],
            "threshold": artifact["threshold"],
            "max_calibrated_precision_on_the_curve": max(
                b[1] for b in artifact["isotonic_breakpoints"]
            ),
            "weights": dict(zip(artifact["feature_names"], artifact["weights"])),
            "bias": artifact["bias"],
            "pinned_zero_weights": artifact["pinned_zero_weights"],
            "fit_cases": artifact["fit_cases"],
            "fit_rows": artifact["fit_rows"],
            "fit_positives": artifact["fit_positives"],
        },
        "evidence_precision": {
            "headline": precision_block(heldout_ep, "heldout", split["heldout_cases"]),
            "all_cases": {
                **precision_block(all_ep, "all", split["cases"]),
                "contaminated": True,
                "contamination": CONTAMINATION.format(
                    fit_cases=split["fit_cases"], n=split["cases"]
                ),
            },
        },
        "number_1_operating_point": {
            "precision": at_op["precision"],
            "coverage": at_op["coverage"],
            "cases_with_any_injection": at_op["cases_with_any_injection"],
            "gate_abstained_everywhere": at_op["cases_with_any_injection"] == 0,
            "band": None,
            "note": (
                "No band by pre-registration. Reported whatever it is, including a gate that "
                "abstained everywhere. Read from the WIRE -- what the implementation actually "
                "injected at the frozen 0.95 threshold."
            ),
        },
        "number_2_cue_capability": n2,
        "conditions": {
            "budget": budget,
            "false_evidence_on_abstention_cases": {
                "value": round(abstention_rate, 6),
                "ceiling": ABSTENTION_INJECTION_CEILING,
                "passes": abstention_rate <= ABSTENTION_INJECTION_CEILING,
                "injections": heldout_diag["injections_on_abstention_cases"],
                "cases": heldout_diag["abstention_cases"],
            },
            "degenerate_pass_guard": {
                "coverage": at_op["coverage"],
                "floor": DEGENERATE_COVERAGE_FLOOR,
                "triggered": at_op["coverage"] < DEGENERATE_COVERAGE_FLOOR,
                "if_triggered": (
                    "the operating-point precision is NOT a quality signal: a gate that "
                    "abstains its way to a ratio has not retrieved anything."
                ),
            },
        },
        "diagnostics": {"heldout": heldout_diag, "all_cases": all_diag},
        "provenance": {
            "corpus_sha256": split["corpus_sha256"],
            "corpus_variant": split["corpus_variant"],
            "split_digest": split["digest"],
            "split_rule": split["rule"],
            "preregistration": "runs/session-b/PREREGISTRATION.json",
            "eval_unchanged": "no file under eval/ is modified by this driver",
            "reading_the_sub_reports": (
                "heldout/report.json is scored under the corpus name "
                "'longmemeval-s-heldout' so that nothing in it claims the full 500 cases were "
                "run -- its benchmark_coverage row correctly shows longmemeval-s as not_run. "
                "The cost of that naming is that the harness's corpus_variant block in THAT "
                "file reads 'unknown', because the manifest is keyed on the full corpus name. "
                "The variant is `cleaned` for both runs; it is stated here and beside every "
                "value in this file. all/report.json is the genuine full-corpus report and its "
                "variant block is correct."
            ),
        },
    }

    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"headline (held-out, n={split['heldout_cases']}): {summary['evidence_precision']['headline']['value']}")
    print(f"all-500 (CONTAMINATED):                {summary['evidence_precision']['all_cases']['value']}")
    print(f"Number 1 @ frozen 0.95: precision={at_op['precision']} coverage={at_op['coverage']}")
    print(f"Number 2 cue capability: {n2}")
    print(f"budget: {budget}")
    print(f"summary: {out / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
