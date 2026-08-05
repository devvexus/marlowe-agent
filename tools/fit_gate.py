"""Fit the frozen gate — HP1's build-time artifact.

Refuses to run without `tools/split.json`, and refuses if that file's corpus digest does not
match the corpus on disk. The split is pre-registered; a fit that could draw its own split
would make the held-out number meaningless.

Refuses equally without the **current session's pre-registration**, and refuses if that file
was registered against a different split. Bands written after a number exists are not bands,
and this refusal is what makes "pre-registered" a property of the filesystem rather than of
somebody's recollection.

What it does:

  1. restrict the corpus to the **fit** half of the pre-registered split
  2. drive `marlowe --eval-adapter --dump-gate-features` over it through the section 4.0
     transport, so the features come from the shipping code path rather than a reimplementation
  3. join each dumped candidate to its turn via the section 4.6 `written[].turn_id` mapping and
     label it against the benchmark's gold evidence
  4. fit **one isotonic curve per cue**, each on that cue's own WITHIN-QUERY MARGIN
  5. write `crates/marlowe-memory/artifacts/gate-frozen-v5.json`

Then rebuild: the artifact is embedded with `include_str!`.

**v4, Session E. The calibration reads a per-query feature, and it no longer orders anything.**

Through v3 each curve was fit on a cue's **pooled raw score** across all fit queries. That asks
whether a candidate's *absolute* BM25 or cosine predicts gold -- which requires the two to be
comparable ACROSS queries, and they are not. `lexical::BM25_SATURATION` is deliberately an
absolute map rather than min-max (min-max would force every query's best candidate to 1.0 and
destroy abstention), so a query whose wording matches a lot of text has all its candidates scoring
high. The top block therefore filled with candidates from high-scoring **queries** rather than
high-scoring **matches**: lexical puts gold at rank 1 in 54.8% of held-out queries while the
calibration's best block was 31.0% gold.

So the curves are fit on `{cue}_margin` -- the candidate's lead over its own query's runner-up, in
raw score units. Query-local, continuous, and **absolute-magnitude-preserving**, which is what
keeps abstention possible: a query where everything is near zero has a tiny margin, where a
sigma-normalized z would still hand its best candidate a large value.

**ADR-010 is discharged structurally.** Session D ranked on calibrated precision, isotonic output
is a step function, and 60.4% of held-out cases ended in a tie at the fused maximum with the
tiebreak deciding top-1. Under v4 the calibrated value decides only *pass/fail* and *which cue
speaks for a candidate*; the ordering is `{cue}_z`, continuous and dimensionless. A step function
cannot decide a rank here at all.

**Every feature carries a role or a stated reason.** Three roles now -- calibrated, ranking, inert
-- and `FrozenGate::load` refuses an artifact that leaves a feature out of all three. Calling a
feature that decides the ordering "inert" would be a false claim on the record, so it has its own
refusal.

    python tools/preregister_split.py       # ONCE, in Session B. Never re-run.
    python tools/preregister_session_f.py   # this session's bands, before the fit
    python tools/fit_gate.py
    cargo build --release
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.adapter.base import Client  # noqa: E402
from marlowe_eval.datasets import longmemeval  # noqa: E402
from marlowe_eval.datasets.model import Corpus  # noqa: E402
from marlowe_eval.suites import benchmark as bench  # noqa: E402
from marlowe_eval_stubs import build_target  # noqa: E402

SPLIT_PATH = REPO / "tools" / "split.json"
ARTIFACT_PATH = REPO / "crates" / "marlowe-memory" / "artifacts" / "gate-frozen-v5.json"
BINARY = REPO / "target" / "release" / "marlowe.exe"
MODEL_DIR = REPO / "models" / "jina-embeddings-v2-small-en"
# Outside the profile root by construction: --profile-root must be empty per spawn,
# and the harness spawns one process per corpus plus four for the clock probe.
CACHE_DIR = REPO / ".embedding-cache"

# The current session's pre-registration. Refused if absent, for the same reason the split is:
# bands written after a number exists are not bands, and this is the file that makes
# "pre-registered" a property of the filesystem rather than of someone's intention.
#
# It is a per-session path deliberately. Pointing this at a stale session's file would let a new
# cue be scored against bands written for a different cue set, which is the same failure the
# split digest check catches one level up.
PREREG_PATH = REPO / "runs" / "session-f" / "PREREGISTRATION.json"

# Must match `marlowe_memory::gate::features::FEATURE_NAMES`, in order. Asserted against the
# dump's own keys below, and again by `FrozenGate::load` against the Rust array.
FEATURE_NAMES = [
    "lexical_bm25",
    "dense_cosine",
    "lexical_margin",
    "dense_margin",
    "lexical_z",
    "dense_z",
    "lexical_rank_recip",
    "dense_rank_recip",
    "effective_trust",
    "fidelity",
    "cue_agreement_2cue",
]

# Must match `marlowe_memory::gate::features::CUE_FEATURES`, in order. `FrozenGate::load` asserts
# it against the Rust array by name AND order, so a cue cannot leave the calibration by editing
# this list alone.
#
# **These are the MARGINS, not the raw scores** -- the whole of Session E. See the module docstring.
CUE_FEATURES = ["lexical_margin", "dense_margin"]

# Must match `marlowe_memory::gate::features::RANK_FEATURES`, in order. The third role, new in v4:
# these order the ranking and are NEVER calibrated. `FrozenGate::load` refuses an artifact that
# disagrees, because the ranking key is pre-registered before the fit precisely so it cannot be
# chosen with top-1 in view.
RANK_FEATURES = ["lexical_z", "dense_z"]

# Must match `marlowe_memory::gate::FUSION`.
FUSION = "per-query-margin-calibration-continuous-z-ranking"
GATE_VERSION = "frozen-v5"

# Must match `marlowe_memory::gate::THRESHOLD`. Frozen under HP1; `load` rejects any other.
THRESHOLD = 0.95

# Features declared inert **by declaration**, whether or not they vary in the fit split.
#
# The variance check below catches constants. `cue_agreement_2cue` is the case it does not catch:
# with two cues it genuinely varies across 0 / 0.5 / 1, so a fit would happily calibrate it.
#
# Session B pinned its one-cue ancestor on COLLINEARITY -- it was exactly `1[lexical_bm25 > 0]`,
# monotone in the same underlying score, so its coefficient could not change any ranking. **That
# argument no longer applies**, and saying so matters: an inherited pin whose stated reason has
# quietly stopped being true is the same failure as an inherited weight. The reason it stays
# pinned is stated fresh below.
#
# **Session D note.** The v3 ranking key's second level is `min_calibrated_precision`, which does
# the job agreement was supposed to do -- among candidates the winning cue rates equally, prefer
# the one the other cue also rates highly -- and does it continuously, in calibrated units, with
# NO firing predicate. That does not unpin this feature: the tiebreak is a different mechanism,
# not the missing predicate. The unpin condition is unchanged.
#
# Enforced by `FrozenGate::load`, which refuses an artifact leaving any non-cue feature
# undeclared, and refuses one that declares a cue inert.
ALWAYS_PINNED = {
    "lexical_bm25": (
        "RETAINED, NOT DELETED, and deliberately not calibrated. Session E's whole finding is "
        "that a POOLED raw score asks an incoherent question -- it requires BM25 and cosine to be "
        "comparable across queries, and Session B's absolute saturation means they are not. The "
        "raw score stays in the vector because it is the cross-session anchor: "
        "score_longmemeval.py's Number 3 sweeps it, and analyze_cue_overlap.py's unchanged-cue "
        "check reads it to tell a changed cue set from a changed held-out population. Deleting it "
        "would silently end the only comparison that can distinguish those two"
    ),
    "dense_cosine": (
        "RETAINED, NOT DELETED, for the same reason as lexical_bm25 -- Number 3's cross-session "
        "anchor and the unchanged-cue check. Not calibrated; the dense cue is read through "
        "dense_margin"
    ),
    "lexical_rank_recip": (
        "diagnostic only. Rank is a COARSENING of the same within-query information margin and z "
        "carry continuously, and ADR-010's constraint is that the top of the ranking must be "
        "decided by a continuous score -- a reciprocal rank is a step function with the same "
        "defect the fusion just failed on. Dumped so the fit split's rank structure can be read, "
        "never fused"
    ),
    "dense_rank_recip": ("diagnostic only, exactly as lexical_rank_recip"),
    "cue_agreement_2cue": (
        "declared pin, and the reason is UNCHANGED from Session D. With two cues this is a "
        "genuine 0 / 0.5 / 1 count and is not collinear with either cue score. It stays pinned "
        "because making it informative requires a FIRING PREDICATE for the dense cue, and unlike "
        "BM25's `raw > 0` any cosine floor is an unmeasured constant entering the frozen path. A "
        "2-bit coarsening of continuous features already in the vector does not earn that. Unpin "
        "at cue 3, where agreement stops being a coarsening -- and pre-register the predicate "
        "before doing so"
    ),
}


def canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_preregistration(split: dict) -> dict:
    """Refuse to fit without a pre-registration bound to this split.

    Two checks, and the second is the one that matters. Existence alone would be satisfied by a
    file copied forward from an earlier session; the digest check is what ties the bands to the
    split the number will actually be reported against.
    """
    if not PREREG_PATH.exists():
        raise SystemExit(
            f"{PREREG_PATH} does not exist. Run `python tools/preregister_session_f.py` first — "
            "the bands are pre-registered, and a fit that runs before them makes every verdict "
            "in this session unfalsifiable."
        )
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    registered = prereg.get("split", {}).get("digest")
    if registered != split["digest"]:
        raise SystemExit(
            f"{PREREG_PATH} was registered against split {registered}, but {SPLIT_PATH} now "
            f"holds {split['digest']}. The bands describe a different experiment than the one "
            "about to run; refusing."
        )
    return prereg


def load_split() -> dict:
    if not SPLIT_PATH.exists():
        raise SystemExit(
            f"{SPLIT_PATH} does not exist. Run `python tools/preregister_split.py` first — "
            "the split is pre-registered, and a fit that draws its own split makes the "
            "held-out number meaningless."
        )
    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))

    expected = hashlib.sha256(
        canonical({"rule": split["rule"], "fit": split["fit"], "heldout": split["heldout"]}).encode()
    ).hexdigest()
    if expected != split["digest"]:
        raise SystemExit(
            f"{SPLIT_PATH} has been edited since it was written: digest {split['digest']} "
            f"but its contents hash to {expected}. Refusing to fit against a split that "
            "changed after pre-registration."
        )

    corpus_path = REPO / split["corpus_path"]
    actual = sha256_file(corpus_path)
    if actual != split["corpus_sha256"]:
        raise SystemExit(
            f"corpus digest mismatch. {SPLIT_PATH} pre-registered {split['corpus_sha256']}, "
            f"{corpus_path} hashes to {actual}. The split names case ids that may not exist "
            "in this file; refusing rather than fitting on a different corpus."
        )
    return split


def subset(corpus: Corpus, query_ids: set[str], name_suffix: str) -> Corpus:
    """The corpus restricted to a set of cases, with only the sessions those cases need."""
    cases = tuple(c for c in corpus.cases if c.query_id in query_ids)
    keep = {c.session_id for c in cases}
    return Corpus(
        name=f"{corpus.name}{name_suffix}",
        sessions=tuple(s for s in corpus.sessions if s.session_id in keep),
        cases=cases,
        categories=corpus.categories,
    )


def collect_rows(corpus: Corpus, dump_path: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    """Drive the implementation and return (X, y, stats).

    Runs the ordinary benchmark path, so ingest, retrieval and the section 4.6 mapping are all
    exactly what a scored run does. The only difference is the dump flag.
    """
    target = (
        f"exec://{BINARY} --eval-adapter --profile-root {{profile_root}} "
        f"--embedder-model {MODEL_DIR} --embedding-cache {CACHE_DIR} "
        f"--fit-mode --dump-gate-features {dump_path}"
    )
    client = Client(build_target(target, corpus))
    try:
        started = time.time()
        run = bench.run_benchmark(client, corpus)
    finally:
        client.close()
    elapsed = time.time() - started

    if run.failures:
        raise SystemExit(
            f"{len(run.failures)} queries failed during the fit run; refusing to fit on a "
            f"partial sample. First: {run.failures[0]}"
        )

    gold_map = corpus.gold_map()
    query_of_case = {c.query_id: c for c in corpus.cases}

    features: list[list[float]] = []
    labels: list[int] = []
    unattributable = 0
    seen_keys: set[str] | None = None

    with dump_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            keys = set(row) - {"query_id", "memory_id"}
            if seen_keys is None:
                seen_keys = keys
                if keys != set(FEATURE_NAMES):
                    raise SystemExit(
                        f"the dump carries features {sorted(keys)}; this fitter knows "
                        f"{FEATURE_NAMES}. The two must agree by NAME — a positional fit "
                        "against a reordered vector would apply every weight to the wrong "
                        "feature and nothing downstream would observe it."
                    )
            turn_id = run.attributor.turn_of(row["memory_id"])
            if turn_id is None:
                unattributable += 1
                continue
            case = query_of_case[row["query_id"]]
            gold = gold_map.get(case.query_id, frozenset())
            features.append([float(row[name]) for name in FEATURE_NAMES])
            labels.append(1 if turn_id in gold else 0)

    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    stats = {
        "cases": len(corpus.cases),
        "rows": int(x.shape[0]),
        "positives": int(y.sum()),
        "unattributable": unattributable,
        "seconds": round(elapsed, 1),
    }
    return x, y, stats


def pava(y: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Pool-adjacent-violators. Returns the isotonic (non-decreasing) fit of `y`."""
    values = list(y.astype(float))
    counts = list(weights.astype(float))
    i = 0
    while i < len(values) - 1:
        if values[i] <= values[i + 1]:
            i += 1
            continue
        total = counts[i] + counts[i + 1]
        pooled = (values[i] * counts[i] + values[i + 1] * counts[i + 1]) / total
        values[i : i + 2] = [pooled]
        counts[i : i + 2] = [total]
        if i > 0:
            i -= 1
    out = []
    for value, count in zip(values, counts):
        out.extend([value] * int(round(count)))
    return np.asarray(out)


# Calibration resolution, **chosen on a stated principle rather than on the resulting number**.
#
# The harness stratifies its human-label sample by gate-score decile and targets >=400 labels
# (ROADMAP, "The human label set"), so roughly 25 blocks per decile is already finer than the
# label set that has to validate it. A curve finer than its downstream support is precision the
# fit does not have.
#
# The choice is not neutral and the direction is worth naming: finer buckets at the top of the
# score range would raise the maximum reachable calibrated precision, because the top bucket
# would hold fewer, better candidates. Picking the resolution after seeing whether the curve
# clears 0.95 would be tuning the operating point through the back door.
CALIBRATION_BLOCKS = 256


def fit_isotonic(scores: np.ndarray, y: np.ndarray, max_blocks: int = CALIBRATION_BLOCKS) -> list[list[float]]:
    """Isotonic calibration: score -> predicted precision, as `[score_upper, precision]` blocks.

    Buckets are **equal-count (quantile), not equal-width**. Equal-width buckets over [0, 1]
    would be nearly empty everywhere: the positive rate is around 1%, so almost every row piles
    into the bottom of the score range and a uniform grid would spend 250 of its 256 blocks on
    empty space while the region that decides the operating point got one.

    **Buckets sharing a score bound are POOLED before PAVA.** This is not tidying. Both cue
    scores have a large atom at exactly 0 -- `lexical_bm25` for every candidate with no term
    overlap, and `dense_cosine` at its cosine floor -- so quantile bucketing hands several
    hundred consecutive blocks the same `score_upper` of 0.0. Emitting them would produce a curve
    whose `partition_point` lookup cannot say which block owns that score, and the Rust side's
    sortedness check uses `<` so it would NOT catch it: the curve is non-decreasing, just
    ambiguous. Pooling first makes the emitted breakpoints strictly increasing, which is what
    `CurveDuplicateBreakpoint` enforces at load.

    Pooling by score is also the only *correct* thing to do. Two rows with an identical cue score
    are indistinguishable to the cue; splitting them across blocks with different predicted
    precisions would assign two different probabilities to the same evidence.
    """
    order = np.argsort(scores, kind="stable")
    s = scores[order]
    labels = y[order]

    bucket = np.minimum((np.arange(len(s)) * max_blocks) // len(s), max_blocks - 1)

    bucket_scores: list[float] = []
    bucket_hits: list[float] = []
    bucket_counts: list[float] = []
    for b in range(max_blocks):
        mask = bucket == b
        count = int(mask.sum())
        if count == 0:
            continue
        upper = float(s[mask].max())
        hits = float(labels[mask].sum())
        # Pool into the previous block when the score bound repeats. Counts are carried so the
        # pooled mean is the true rate over the merged rows, not the mean of two means.
        if bucket_scores and upper == bucket_scores[-1]:
            bucket_hits[-1] += hits
            bucket_counts[-1] += count
        else:
            bucket_scores.append(upper)
            bucket_hits.append(hits)
            bucket_counts.append(float(count))

    means = np.asarray(
        [hits / count for hits, count in zip(bucket_hits, bucket_counts)], dtype=float
    )
    fitted = pava(means, np.ones(len(means)))

    blocks: list[list[float]] = []
    for score_upper, precision in zip(bucket_scores, fitted):
        if blocks and abs(blocks[-1][1] - precision) < 1e-12:
            blocks[-1][0] = round(float(score_upper), 6)
        else:
            blocks.append([round(float(score_upper), 6), round(float(precision), 6)])

    # Rounding to 6 dp can re-collide two bounds that differed in the 7th. Re-merge, keeping the
    # LAST precision -- the curve is non-decreasing so that is the higher of the two, and the
    # alternative would silently lower a block's prediction.
    merged: list[list[float]] = []
    for block in blocks:
        if merged and merged[-1][0] == block[0]:
            merged[-1][1] = block[1]
        else:
            merged.append(block)
    blocks = merged

    # **The 1.0 top-anchor is REMOVED in v4, and the removal is the point.** Through v3 the
    # calibrated features were `lexical_bm25` (saturated into [0,1]) and `dense_cosine` (a cosine),
    # so anchoring the last breakpoint at 1.0 marked the true end of the feature's range.
    #
    # `{cue}_margin` is NOT bounded to [0,1] -- a BM25 margin is unbounded above and negative for
    # every non-leader -- so that anchor would now assert a range boundary that does not exist. It
    # was harmless in effect (the lookup clamps above the last breakpoint either way), which is
    # exactly why it would have survived: an inherited rule whose stated reason has quietly stopped
    # being true, changing nothing and meaning nothing. This project has paid for that pattern
    # before, so the rule goes rather than being left to be re-derived by a later reader.
    return blocks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-dump", help="write the raw feature dump here and keep it")
    args = parser.parse_args()

    if not BINARY.exists():
        raise SystemExit(
            f"{BINARY} not found. Build it first: cargo build --release. (The placeholder "
            "artifact is enough to compile; fit mode loads no gate.)"
        )

    split = load_split()
    prereg = load_preregistration(split)
    corpus_path = REPO / split["corpus_path"]
    print(f"corpus:  {corpus_path}")
    print(f"split:   {split['fit_cases']} fit / {split['heldout_cases']} heldout")
    print(f"prereg:  {PREREG_PATH.relative_to(REPO)} ({prereg['session']})")

    corpus = longmemeval.load(corpus_path)
    fit_corpus = subset(corpus, set(split["fit"]), "-fit")
    if len(fit_corpus.cases) != split["fit_cases"]:
        raise SystemExit(
            f"the split names {split['fit_cases']} fit cases but only "
            f"{len(fit_corpus.cases)} are present in the corpus"
        )

    if args.keep_dump:
        tmp = Path(args.keep_dump)
    else:
        # mkstemp returns an OPEN descriptor; leaving it open makes the unlink at the end fail
        # on Windows with a sharing violation.
        handle, name = tempfile.mkstemp(suffix=".ndjson")
        import os

        os.close(handle)
        tmp = Path(name)
    print(f"dump:    {tmp}")
    print("driving the implementation over the fit split ...")
    x, y, stats = collect_rows(fit_corpus, tmp)
    print(f"  {stats['rows']} rows, {stats['positives']} positive, {stats['seconds']}s")
    if stats["unattributable"]:
        print(f"  {stats['unattributable']} unattributable rows skipped")

    if stats["positives"] == 0:
        raise SystemExit(
            "no positive rows: the join to gold evidence produced nothing. A calibration fit "
            "on all-negative data is a curve that predicts zero everywhere; refusing."
        )

    # Every feature outside the fusion carries a stated reason. v2 checked that a pinned WEIGHT
    # was zero; with no weight vector the property to enforce is COVERAGE -- a feature cannot
    # drop out of the gate without a reason on record. `FrozenGate::load` refuses an artifact
    # that leaves any non-cue feature undeclared.
    inert: dict[str, str] = {}
    for i, name in enumerate(FEATURE_NAMES):
        if name in CUE_FEATURES or name in RANK_FEATURES:
            continue
        if name in ALWAYS_PINNED:
            inert[name] = ALWAYS_PINNED[name]
            continue
        spread = float(x[:, i].max() - x[:, i].min())
        if spread == 0.0:
            inert[name] = (
                f"zero variance across the fit split (constant {x[:, i][0]:.4f}); a calibration "
                "fit on it would be noise, and would become load-bearing the moment the "
                "feature starts varying"
            )
        else:
            inert[name] = (
                "not a cue and not a rank key. Under v4 only CUE_FEATURES are calibrated and only "
                "RANK_FEATURES order the ranking; trust and fidelity are eligibility properties "
                "enforced by section 4.3's exclusions, not evidence of relevance, and giving them "
                "a curve would let a high-trust irrelevant memory outrank a low-trust exact match"
            )

    # One isotonic curve per cue, each fit on its OWN score distribution. This is the whole
    # change: there is no joint score, so lexical's top-end separation is never averaged against
    # dense's mid-range separation.
    curves: dict[str, list[list[float]]] = {}
    per_cue_reachable: dict[str, float] = {}
    for name in CUE_FEATURES:
        column = FEATURE_NAMES.index(name)
        values = x[:, column]
        spread = float(values.max() - values.min())
        if spread == 0.0:
            raise SystemExit(
                f"cue {name!r} is constant ({values[0]:.4f}) across the fit split. A cue that "
                "does not vary cannot be calibrated, and a curve fit on it would predict one "
                "precision for every candidate. Refusing rather than emitting a flat curve."
            )
        curve = fit_isotonic(values, y)
        curves[name] = curve
        per_cue_reachable[name] = max(block[1] for block in curve)
        print(f"  calibrated {name}: {len(curve)} blocks, top block {per_cue_reachable[name]:.4f}")

    for name, why in inert.items():
        print(f"  inert {name}: {why.split(';')[0]}")

    # The fusion is max over cues, so the reachable precision is the best cue's top block.
    reachable = max(per_cue_reachable.values())

    artifact = {
        "state": "fitted",
        "note": (
            "The frozen gate, HP1. Fit offline on the FIT half of the pre-registered split in "
            "tools/split.json; the held-out half is what the reported number is scored on. TWO "
            "cues, calibrated on WITHIN-QUERY MARGIN and ranked by WITHIN-QUERY Z -- this is not "
            "the five-cue system K1 measures. Regenerate with: python tools/fit_gate.py"
        ),
        "version": GATE_VERSION,
        "fusion": FUSION,
        "threshold": THRESHOLD,
        "feature_names": FEATURE_NAMES,
        "cue_features": CUE_FEATURES,
        "rank_features": RANK_FEATURES,
        "cue_curves": curves,
        "inert_features": inert,
        # The floor is measured on HELD-OUT after this artifact is built and scored, so the
        # fitter cannot know it and must not guess. `FrozenGate::load` permits "unmeasured" --
        # refusing it would deadlock, since the measurement needs this gate to load in order to
        # produce the feature dump it is read from. Record it with:
        #   python tools/analyze_cue_overlap.py --run <RUN> --record-verdict
        "floor_verdict": "unmeasured",
        "floor_required": None,
        "floor_measured": None,
        "floor_read_from": None,
        "corpus": split["corpus"],
        "corpus_variant": split["corpus_variant"],
        "corpus_sha256": split["corpus_sha256"],
        "split_rule": split["rule"],
        "split_digest": split["digest"],
        "fit_cases": split["fit_cases"],
        "heldout_cases": split["heldout_cases"],
        "fit_rows": stats["rows"],
        "fit_positives": stats["positives"],
        "fitted_at_clock_ms": 0,
    }
    ARTIFACT_PATH.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"artifact: {ARTIFACT_PATH}")
    print(f"  fusion:  {FUSION}")
    for name in CUE_FEATURES:
        print(f"  {name:20s} {len(curves[name]):4d} blocks, top {per_cue_reachable[name]:.4f}")
    print(f"  reachable (max over cues): {reachable:.4f}")
    if reachable < THRESHOLD:
        print()
        print(
            f"  NOTE: no cue's curve reaches the frozen threshold of {THRESHOLD}. The gate "
            "will abstain on every query.\n"
            "  This is a pre-registered possible outcome, not a defect: with two of five cues "
            "the calibration may have\n"
            "  no score region where predicted precision clears the K1 operating point. The "
            "threshold does not move,\n"
            "  and this number is the session's HEADLINE -- read it against the bands in "
            "runs/session-f/PREREGISTRATION.json."
        )
    print()
    print("now rebuild so the artifact is embedded:  cargo build --release")
    if not args.keep_dump:
        tmp.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
