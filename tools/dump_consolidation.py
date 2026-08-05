"""Drive the **fit split** through a dry-run consolidation pass and keep both dumps.

This is the evidence `tools/preregister_session_f.py` chooses the frozen merge threshold from,
and it is produced by a pass that **applied nothing** — `--consolidation-dry-run` loads no
consolidation artifact and journals no supersession, so the threshold cannot be derived from a
run that had already assumed one.

Two dumps come out of the single pass, deliberately:

  consolidation-sweep.ndjson   one row per ingested session: the full pairwise-similarity
                               histogram, plus that session clustered at every threshold in the
                               binary's own `SWEEP_THRESHOLDS`.
  fit-features.ndjson          one row per scored candidate: `lexical_bm25` and `dense_cosine`
                               for the UNCONSOLIDATED pool.

They have to come from one pass. Computing the ranking effect of a merge needs the cluster
membership and the cue scores over *the same* candidate set, and two runs would give two
`profile_root`s and no guarantee the pools matched.

**The fit split, never the held-out one.** A threshold chosen against held-out cases is a
threshold fit on the number it will later be judged by. `tools/split.json` is the authority and
this script refuses to run without it.

    python tools/dump_consolidation.py --out runs/session-f
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.datasets import longmemeval  # noqa: E402
from marlowe_eval.datasets.model import Corpus  # noqa: E402
from marlowe_eval.runner import RunConfig, run, write_artifacts  # noqa: E402
from marlowe_eval_stubs import build_target  # noqa: E402

SPLIT_PATH = REPO / "tools" / "split.json"
BINARY = REPO / "target" / "release" / "marlowe.exe"
MODEL_DIR = REPO / "models" / "jina-embeddings-v2-small-en"
CACHE_DIR = REPO / ".embedding-cache"


def subset(corpus: Corpus, query_ids: set[str], suffix: str) -> Corpus:
    """The same restriction `score_longmemeval.py` performs, and it is imported nowhere from
    here on purpose: this script must keep working if that one is mid-edit."""
    cases = tuple(c for c in corpus.cases if c.query_id in query_ids)
    keep = {c.session_id for c in cases}
    return Corpus(
        name=f"{corpus.name}{suffix}",
        sessions=tuple(s for s in corpus.sessions if s.session_id in keep),
        cases=cases,
        categories=corpus.categories,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(REPO / "runs" / "session-f"))
    parser.add_argument(
        "--applied",
        action="store_true",
        help="run with the FROZEN policy instead of the dry-run sweep, and dump what was "
        "actually merged. This is how consolidation's share of the section 4.6 call is measured: "
        "the ingest cost block carries a single `total`, and splitting that into invented halves "
        "would be worse than reporting the measured span on the side channel. Not a substitute "
        "for the dry run -- it cannot produce the sweep, because it has already assumed a "
        "threshold.",
    )
    parser.add_argument("--embedding-cache", default=str(CACHE_DIR))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--clock", type=int, default=1_780_000_000_000)
    args = parser.parse_args()

    if not SPLIT_PATH.exists():
        raise SystemExit(
            f"{SPLIT_PATH} does not exist. The split is pre-registered in Session B and is "
            "never re-drawn; without it there is no fit half to sweep on."
        )
    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sweep_path = out / ("consolidation-applied.ndjson" if args.applied else "consolidation-sweep.ndjson")
    features_path = out / "fit-features.ndjson"

    corpus = longmemeval.load(REPO / split["corpus_path"])
    fit = subset(corpus, set(split["fit"]), "-fit")
    mode = "APPLIED (frozen policy)" if args.applied else "dry-run sweep"
    print(f"{mode} over the FIT split: {len(fit.cases)} cases, {len(fit.sessions)} sessions")

    if args.applied:
        # The frozen policy, with the gate loaded — the shipping configuration. The point of this
        # pass is the measured `consolidation_ms` per session, so it must not run under `--fit-mode`
        # (which would change what else the call does) or under the dry run (which applies nothing).
        target = (
            f"exec://{BINARY} --eval-adapter --profile-root {{profile_root}} "
            f"--embedder-model {MODEL_DIR} --embedding-cache {args.embedding_cache} "
            f"--dump-consolidation {sweep_path}"
        )
    else:
        # `--fit-mode` loads no gate and `--consolidation-dry-run` loads no consolidation artifact.
        # Neither calibrates nor applies anything, which is what makes this pass usable as the
        # evidence for both artifacts that follow it.
        target = (
            f"exec://{BINARY} --eval-adapter --profile-root {{profile_root}} "
            f"--embedder-model {MODEL_DIR} --embedding-cache {args.embedding_cache} "
            f"--fit-mode --dump-gate-features {features_path} "
            f"--consolidation-dry-run --dump-consolidation {sweep_path}"
        )
    result = run(
        lambda c: build_target(target, c),
        {fit.name: fit},
        # Benchmark only. Every process spawn opens the dumps with truncate, so a probe running
        # afterwards would leave a sweep containing four synthetic sessions and nothing else --
        # the same hazard `score_longmemeval.py` records for the feature dump.
        RunConfig(target=target, seed=args.seed, clock_ms=args.clock, suites=("benchmark",)),
    )
    paths = write_artifacts(result, out / ("fit-applied" if args.applied else "fit-dryrun"))

    sessions = sum(1 for _ in sweep_path.open(encoding="utf-8", newline="\n") if _.strip())
    rows = (
        sum(1 for _ in features_path.open(encoding="utf-8", newline="\n") if _.strip())
        if features_path.exists() and not args.applied
        else 0
    )
    # **Completeness, checked against the corpus rather than against a failure list.**
    # `RunResult` carries only the report and the transcript, so there is no failure collection
    # to consult here — and counting rows is the stronger check anyway: a session that errored
    # mid-ingest could still have reported no failure while writing no sweep row, and the
    # threshold would then be chosen from a silently partial sample.
    if sessions != len(fit.sessions):
        raise SystemExit(
            f"the sweep has {sessions} sessions but the fit split has {len(fit.sessions)}. "
            "Refusing to choose a threshold from a partial sweep."
        )
    print(f"\nsweep:     {sweep_path}  ({sessions} sessions)")
    print(f"features:  {features_path}  ({rows} scored candidates)")
    print(f"transcript: {paths['transcript']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
