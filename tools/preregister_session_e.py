"""Pre-registration for M0b Session E — per-query features. **Run this before fitting anything.**

Writes one file:

  runs/session-e/PREREGISTRATION.json

`tools/fit_gate.py` refuses to run without it, and refuses if it was registered against a
different split. Pre-registration is a file, not an intention.

**What this session changes is what the calibration READS, not the cue set and not the threshold.**
Session D's finding (ADR-010) is inherited, not revisited: calibration puts cues in common units by
destroying the ordering inside each cue, so the ordering that decides the top of the ranking must
come from a continuous score.

The hypothesis: the isotonic curve pools ~119,340 candidates across all fit queries and asks what
fraction of a raw-score band is gold. That requires BM25 and cosine to be comparable ACROSS
queries, and they are not -- Session B deliberately chose absolute normalization (`s/(s+10)`) over
min-max, so a query whose wording matches a lot of text has all its candidates scoring high. The
top block therefore fills with candidates from high-scoring QUERIES rather than high-scoring
MATCHES.

**The ceiling band is derived from measured rank-1 and rank-2 gold rates on the FIT split, plus
block-size arithmetic** -- not from a round number, and not from the naive reading of the
54.8% / 31% gap. See `ceiling_band` below for why that naive reading is wrong.

    python tools/preregister_session_e.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.adapter.base import Client  # noqa: E402
from marlowe_eval.datasets import longmemeval  # noqa: E402
from marlowe_eval.datasets.model import Corpus  # noqa: E402
from marlowe_eval.suites import benchmark as bench  # noqa: E402
from marlowe_eval_stubs import build_target  # noqa: E402

SPLIT_PATH = REPO / "tools" / "split.json"
PREREG_PATH = REPO / "runs" / "session-e" / "PREREGISTRATION.json"
SESSION_C_SUMMARY = REPO / "runs" / "session-c" / "summary.json"
SESSION_C_OVERLAP = REPO / "runs" / "session-c" / "cue-overlap.json"
SESSION_D_SUMMARY = REPO / "runs" / "session-d" / "summary.json"
SESSION_D_OVERLAP = REPO / "runs" / "session-d" / "cue-overlap.json"

BINARY = REPO / "target" / "release" / "marlowe.exe"
MODEL_DIR = REPO / "models" / "jina-embeddings-v2-small-en"
CACHE_DIR = REPO / ".embedding-cache"

# Session B's digest, unchanged through C, D and E. A redrawn split is a loud refusal.
EXPECTED_SPLIT_DIGEST = "3a685798a4fcac4cb97b645394d4935906a4f67e605398e7d659d48c8f685a3d"

# Unchanged from Session B. STATE.md forbids re-tuning it, and it is an INPUT to the ceiling band
# below -- the top block's width is `fit_rows / CALIBRATION_BLOCKS`, so changing it would move the
# very number the band predicts.
CALIBRATION_BLOCKS = 256

# K1's operating point and the frozen threshold. Neither moves here.
THRESHOLD = 0.95

# The power floor's parameters. `p_hat` is the precision being claimed; `floor` is the value the
# claim must be distinguishable FROM. Both are fixed here, before any number exists.
POWER_P_HAT = 0.95
POWER_FLOOR = 0.90
POWER_Z = 1.959963984540054  # two-sided 95%

# ROADMAP, "The human label set". Not this session's deliverable -- reported as a companion so a
# later session knows whether K1's validation instrument is reachable at this operating point.
LABEL_SET_TOTAL = 400
LABEL_SET_PER_CATEGORY = 50


def canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wilson_lower_bound(p_hat: float, n: int, z: float = POWER_Z) -> float:
    """Wilson score interval, lower bound. Never the normal approximation.

    At p near 1 the Wald interval extends above 1.0 and its coverage collapses, which is exactly
    the regime this floor is read in -- the claim being certified is 0.95.
    """
    if n <= 0:
        return 0.0
    z2 = z * z
    centre = p_hat + z2 / (2 * n)
    spread = z * math.sqrt(p_hat * (1 - p_hat) / n + z2 / (4 * n * n))
    return (centre - spread) / (1 + z2 / n)


def min_n_for_power(p_hat: float, floor: float, z: float = POWER_Z) -> int:
    """Smallest N whose Wilson lower bound at `p_hat` clears `floor`.

    Searched rather than solved in closed form: the closed form is a quadratic whose root has to
    be rounded, and a rounding that lands one short would silently register an underpowered floor.
    """
    n = 1
    while n < 100_000:
        if wilson_lower_bound(p_hat, n, z) > floor:
            return n
        n += 1
    raise SystemExit(
        f"no N below 100,000 gives a Wilson lower bound above {floor} at p={p_hat}; the power "
        "floor is unreachable and the condition would be vacuous."
    )


def load_split() -> dict:
    if not SPLIT_PATH.exists():
        raise SystemExit(f"{SPLIT_PATH} does not exist. Session E does not redraw it; it reads it.")
    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))

    if split["digest"] != EXPECTED_SPLIT_DIGEST:
        raise SystemExit(
            f"{SPLIT_PATH} has digest {split['digest']}, but the pre-registered split is "
            f"{EXPECTED_SPLIT_DIGEST}. The split was redrawn. Every number fit under the old "
            "split -- Sessions B, C and D -- is now unreproducible. Refusing."
        )
    recomputed = hashlib.sha256(
        canonical({"rule": split["rule"], "fit": split["fit"], "heldout": split["heldout"]}).encode()
    ).hexdigest()
    if recomputed != split["digest"]:
        raise SystemExit(
            f"{SPLIT_PATH} has been edited since it was written: declares {split['digest']}, "
            f"contents hash to {recomputed}."
        )
    corpus_path = REPO / split["corpus_path"]
    actual = sha256_file(corpus_path)
    if actual != split["corpus_sha256"]:
        raise SystemExit(
            f"corpus digest mismatch. {SPLIT_PATH} pre-registered {split['corpus_sha256']}, "
            f"{corpus_path} hashes to {actual}."
        )
    return split


def subset(corpus: Corpus, query_ids: set[str], suffix: str) -> Corpus:
    cases = tuple(c for c in corpus.cases if c.query_id in query_ids)
    keep = {c.session_id for c in cases}
    return Corpus(
        name=f"{corpus.name}{suffix}",
        sessions=tuple(s for s in corpus.sessions if s.session_id in keep),
        cases=cases,
        categories=corpus.categories,
    )


def rank_gold_rates(corpus: Corpus, dump_path: Path, max_rank: int = 5) -> dict:
    """Drive the FIT split in --fit-mode and measure per-cue rank-k gold rates.

    **This is a property of the CUE SCORES, which are unchanged from Session C.** It is not a
    property of the v4 calibration, which does not exist yet -- that is what makes deriving a band
    from it legitimate rather than circular. It is the same move Session D made when it derived its
    bands from Session C's published Number 3.

    Fit-mode loads NO gate, so the dump carries the five raw features and no verdict. Ranks are
    taken on `lexical_bm25` and `dense_cosine` as dumped. `saturate` is strictly monotone, so
    ranking on the saturated lexical value gives exactly the ranks raw BM25 would.
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
            f"{len(run.failures)} queries failed during the pre-registration run; refusing to "
            f"derive a band from a partial sample. First: {run.failures[0]}"
        )

    gold_map = corpus.gold_map()
    case_of = {c.query_id: c for c in corpus.cases}

    per_query: dict[str, list[tuple[float, float, int]]] = defaultdict(list)
    rows = 0
    unattributable = 0
    for line in dump_path.open("r", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        rows += 1
        turn_id = run.attributor.turn_of(row["memory_id"])
        if turn_id is None:
            unattributable += 1
            continue
        gold = gold_map.get(row["query_id"], frozenset())
        per_query[row["query_id"]].append(
            (float(row["lexical_bm25"]), float(row["dense_cosine"]), 1 if turn_id in gold else 0)
        )

    # Answerable cases with at least one gold candidate in scope -- the same population
    # `analyze_cue_overlap.py` uses, so the rates are comparable to the floor's 0.5478.
    queries = [
        q
        for q in per_query
        if q in case_of and not case_of[q].is_abstention and any(r[2] for r in per_query[q])
    ]

    # ALL fit cases that produced candidates, gold-bearing or not. The top block fills with
    # rank-1s from EVERY case -- including abstention cases and answerable cases whose gold is out
    # of scope -- and those contribute rows without ever contributing gold. Counting only the
    # gold-bearing cases would model the block as if every case could contribute a hit, which
    # inflates the predicted ceiling.
    all_cases = len([q for q in per_query if q in case_of])

    out: dict = {
        "_rows_for_concentration": per_query,
        "_population": (
            "FIT split. `fit_cases_with_gold` uses the same case-selection rule "
            "analyze_cue_overlap.py applies on held-out, so the rank rates are comparable to the "
            "0.5478 the floor is drawn from. `fit_cases_all` is every case that produced "
            "candidates, and it is the row count the block arithmetic needs -- the two differ, and "
            "using the wrong one is how a ceiling band gets inflated."
        ),
        "fit_cases_with_gold": len(queries),
        "fit_cases_all": all_cases,
        "gold_bearing_fraction": round(len(queries) / all_cases, 6) if all_cases else None,
        "fit_rows": rows,
        "unattributable_rows": unattributable,
        "seconds": round(elapsed, 1),
        "per_cue": {},
    }

    for cue, index in (("lexical_bm25", 0), ("dense_cosine", 1)):
        rates = []
        for k in range(1, max_rank + 1):
            hits = 0
            eligible = 0
            for q in queries:
                candidates = per_query[q]
                if len(candidates) < k:
                    continue
                eligible += 1
                # Descending by the cue score; ties broken by memory order, which is the dump's
                # own id-ascending order -- the same final tiebreak the gate uses.
                ordered = sorted(candidates, key=lambda r: -r[index])
                hits += ordered[k - 1][2]
            rates.append(
                {
                    "rank": k,
                    "gold_rate": round(hits / eligible, 6) if eligible else None,
                    "cases": eligible,
                    "gold": hits,
                }
            )
        out["per_cue"][cue] = rates
    return out


def block_concentration(per_query: dict, rows: int) -> dict:
    """**The primary diagnostic, and the only well-powered test of this session's hypothesis.**

    The hypothesis is a claim about WHERE THE TOP BLOCK'S ROWS COME FROM: under a pooled raw score
    it should fill with candidates from high-scoring *queries* rather than high-scoring *matches*.
    That is directly measurable on the existing fit-split features, before any curve is fit, by
    counting how many DISTINCT QUERIES are represented in the top block.

    Why this and not the ceiling: the ceiling's predicted movement (0.309 -> ~0.38) is smaller than
    two binomial standard errors on a 466-row block, so its bands do not separate. This count does
    not have that problem -- the difference between a concentrated block and a diffuse one is
    hundreds of queries, not hundredths of a rate.

    **The null is derived, not chosen.** If the top block were a uniform random sample of
    candidates -- no query effect at all -- the expected number of distinct queries covered is the
    classic occupancy result `m * (1 - (1 - 1/m)^n)` for `n` rows over `m` queries, with the
    matching occupancy variance. Concentration is a value materially BELOW that null.

    Falsifiable in the direction that matters: if the pooled block already covers about as many
    queries as chance predicts, then pooling was never concentrating anything, this session's
    diagnosis is wrong, and the ceiling will not move for the reason claimed.
    """
    m = len(per_query)
    n = int(rows)

    def occupancy(m: int, n: int) -> tuple[float, float]:
        """Expected distinct bins and its standard deviation, for n balls in m bins."""
        q = 1.0 - 1.0 / m
        mean = m * (1.0 - q**n)
        var = (
            m * (m - 1) * (1.0 - 2.0 / m) ** n
            + m * q**n
            - (m * q**n) ** 2
        )
        return mean, math.sqrt(max(var, 0.0))

    null_mean, null_sd = occupancy(m, n)

    out = {
        "_this_is_the_PRIMARY_diagnostic": True,
        "_why_primary": (
            "It is the only well-powered test of the hypothesis. The ceiling band's confirming "
            "and falsifying regions OVERLAP -- the predicted movement is smaller than two "
            "binomial standard errors on a 466-row block -- so the ceiling cannot return a clean "
            "verdict at this resolution. That was found by the band-separation check BEFORE the "
            "fit, and the response is to add a better-powered read rather than to narrow the "
            "band until it separates, which would be tuning the instrument to guarantee an answer."
        ),
        "definition": (
            "the number of DISTINCT QUERIES represented in the top `fit_rows / 256` rows, ranked "
            "by a given feature over the pooled fit split."
        ),
        "measured_on": "the fit split, from the SAME feature dump the rank rates come from",
        "top_block_rows": n,
        "queries": m,
        "null_if_there_were_no_query_effect": {
            "expected_distinct_queries": round(null_mean, 2),
            "sd": round(null_sd, 3),
            "derivation": (
                f"occupancy of {n} rows over {m} queries: m * (1 - (1 - 1/m)^n), with the matching "
                "occupancy variance. Derived, not chosen."
            ),
        },
        "by_feature": {},
    }

    for feature, index in (
        ("lexical_bm25", 0),
        ("dense_cosine", 1),
    ):
        rows_flat = [
            (r[index], q) for q, rs in per_query.items() for r in rs
        ]
        rows_flat.sort(key=lambda t: -t[0])
        top = rows_flat[:n]
        distinct = len({q for _, q in top})
        z = (distinct - null_mean) / null_sd if null_sd else 0.0
        out["by_feature"][feature] = {
            "distinct_queries_in_top_block": distinct,
            "fraction_of_queries_covered": round(distinct / m, 4),
            "z_against_the_no_query_effect_null": round(z, 2),
            "concentrated": bool(z < -3.0),
        }

    lex = out["by_feature"]["lexical_bm25"]
    out["bands"] = [
        {
            "condition": "distinct queries in the POOLED lexical top block is >3 sd BELOW the null",
            "verdict": "CONCENTRATION CONFIRMED -- pooling really does fill the block from a "
            "minority of queries, which is this session's diagnosis",
            "implication": (
                "the per-query fix addresses a real mechanism. Whether it moves the CEILING far "
                "enough to matter is a separate and underpowered question."
            ),
        },
        {
            "condition": "distinct queries is within 3 sd of the null",
            "verdict": "DIAGNOSIS FALSIFIED -- the pooled block already covers about as many "
            "queries as chance predicts, so pooling was not concentrating anything",
            "implication": (
                "the 54.8% / 31% gap has another cause, and the named next levers are the "
                "CROSS-ENCODER then CONSOLIDATION. Cues 3-5 stay deferred either way."
            ),
        },
    ]
    out["measured_verdict"] = (
        "CONCENTRATION CONFIRMED" if lex["concentrated"] else "DIAGNOSIS FALSIFIED"
    )
    out["_note_on_v4"] = (
        "The margin feature's own concentration is NOT a test: margin is positive for exactly one "
        "candidate per query, so a margin-ranked top block covers ~every query BY CONSTRUCTION. "
        "Reporting it as evidence would be circular. The test is entirely on the POOLED features, "
        "which is why only those are measured here."
    )
    return out


def ceiling_band(rank_rates: dict, session_d_ceiling: float) -> dict:
    """The ceiling band, derived from block-size arithmetic and measured rank-k gold rates.

    **Session D's ceiling band was anchored on an inverted selectivity comparison and the same
    trap is live here.** Its band assumed a per-cue curve's top block is "far more selective than
    0.261 coverage"; it is the opposite. The top block holds `fit_rows / CALIBRATION_BLOCKS` rows,
    which is ~1.86 candidates PER CASE -- so it is not rank-1, and it CANNOT reach the rank-1 gold
    rate no matter how well per-query normalization works.

    The naive reading of the 54.8% / 31% gap is therefore wrong in a way worth stating: part of
    that gap was never a bug. A 466-row block and a 251-row rank-1 set are different populations.
    What per-query normalization can do is make the top block hold *each query's own best
    candidates* rather than *the highest-scoring queries' candidates*, and the reachable value of
    that is the rank-mixture below.
    """
    rows = rank_rates["fit_rows"]
    cases = rank_rates["fit_cases_with_gold"]
    all_cases = rank_rates["fit_cases_all"]
    # A rank-k slice contributes one row per case that HAS a k-th candidate -- every case -- but
    # gold only from the gold-bearing ones. `p_k` is measured over gold-bearing cases, so the gold
    # rate across the whole slice is `p_k * gold_bearing_fraction`.
    gold_fraction = cases / all_cases if all_cases else 0.0
    top_block_rows = rows / CALIBRATION_BLOCKS

    best = None
    for cue, rates in rank_rates["per_cue"].items():
        by_rank = {r["rank"]: r["gold_rate"] for r in rates if r["gold_rate"] is not None}
        if 1 not in by_rank:
            continue
        # How the top block fills under a perfectly query-local feature: every case's rank-1
        # first, then rank-2s, then rank-3s, until the block is full.
        remaining = top_block_rows
        gold = 0.0
        composition = []
        rank = 1
        while remaining > 0 and rank in by_rank:
            take = min(float(all_cases), remaining)
            slice_rate = by_rank[rank] * gold_fraction
            gold += take * slice_rate
            composition.append(
                {
                    "rank": rank,
                    "rows": round(take, 1),
                    "gold_rate_among_gold_bearing_cases": by_rank[rank],
                    "gold_rate_across_the_whole_slice": round(slice_rate, 6),
                }
            )
            remaining -= take
            rank += 1
        if remaining > 0:
            # The measured ranks did not fill the block. Refusing rather than extrapolating a
            # gold rate for ranks nobody measured.
            raise SystemExit(
                f"the top block holds {top_block_rows:.0f} rows over {all_cases} cases, which needs "
                f"rank-{rank} gold rates to fill; only {max(by_rank)} were measured. Raise "
                "--max-rank rather than extrapolating."
            )
        predicted = gold / top_block_rows
        if best is None or predicted > best["predicted_ceiling"]:
            best = {
                "cue": cue,
                "predicted_ceiling": round(predicted, 6),
                "composition": composition,
            }

    predicted = best["predicted_ceiling"]
    # Binomial standard error of a rate `predicted` measured over the top block. This is the
    # width the band is drawn at -- derived, not chosen. Two SE either side.
    se = math.sqrt(predicted * (1 - predicted) / top_block_rows)
    delta = round(2 * se, 6)

    upper_boundary = round(predicted - delta, 6)
    lower_boundary = round(session_d_ceiling + delta, 6)

    band = {
        "_this_is_the_headline": False,
        "_demoted_to_SECONDARY_before_the_fit": (
            "The band-separation check below FIRED: the confirming and falsifying regions "
            "overlap, because the predicted movement is smaller than two binomial standard errors "
            "on a top block of this width. A band that cannot return a clean verdict is not a "
            "headline. It is registered anyway -- the number is still worth reporting and the "
            "trajectory still matters -- but the session's primary read is "
            "`block_concentration`, which tests the same hypothesis directly and is not "
            "resolution-limited. Narrowing the band until it separated would have been tuning the "
            "instrument to guarantee an answer, so the band is left exactly as derived."
        ),
        "definition": (
            "max_calibrated_precision = the max over the per-cue curves' top blocks, on the FIT "
            "split. A per-cue quantity; the fusion does not enter it."
        ),
        "trajectory": {
            "session_b_one_cue": 0.309013,
            "session_c_two_cues": 0.317597,
            "session_d_max_fusion": session_d_ceiling,
            "session_e": "to be measured",
        },
        "why_the_naive_reading_of_the_gap_is_WRONG": (
            "Lexical puts gold at rank 1 in 54.8% of held-out queries and the calibration's best "
            "block is 31.0% gold, but predicting 'the ceiling should approach 0.548' would repeat "
            f"Session D's exact error. TWO reasons, and both are arithmetic rather than "
            f"retrieval. (1) The top block holds fit_rows / {CALIBRATION_BLOCKS} = "
            f"{top_block_rows:.0f} rows over {all_cases} cases -- about "
            f"{top_block_rows / all_cases:.2f} candidates per case. It is NOT rank-1, so it "
            "cannot reach the rank-1 gold rate however well per-query normalization works. "
            f"(2) Only {cases} of those {all_cases} cases have gold in scope at all "
            f"({gold_fraction:.1%}); the rest contribute rows to the block and can never "
            "contribute a hit. Part of the 54.8% / 31% gap was never a bug -- it was always a "
            "population difference, and this is the size of it."
        ),
        "block_arithmetic": {
            "fit_rows": rows,
            "calibration_blocks": CALIBRATION_BLOCKS,
            "top_block_rows": round(top_block_rows, 1),
            "fit_cases_all": all_cases,
            "fit_cases_with_gold": cases,
            "gold_bearing_fraction": round(gold_fraction, 6),
            "candidates_per_case_in_top_block": round(top_block_rows / all_cases, 4),
        },
        "derivation": (
            "Under a perfectly query-local feature the top block fills with every case's rank-1, "
            "then rank-2, and so on until it is full. The predicted ceiling is the row-weighted "
            "gold rate of that mixture, using rank-k gold rates measured on the fit split BEFORE "
            "any curve exists -- and scaling each rank's rate by the gold-bearing fraction, "
            "because a case with no gold in scope contributes a row to every rank slice and a hit "
            "to none."
        ),
        "measured_inputs": rank_rates["per_cue"],
        "predicted_from": best,
        "prediction_before_the_fit": predicted,
        "the_prediction_is_an_UPPER_BOUND_and_here_is_the_bias": (
            "Identified before the fit. The mixture model assumes the rank-2 rows that enter the "
            "top block are a random sample of rank-2 candidates. They are not. Only ~"
            f"{cases} candidates per cue can have a POSITIVE margin (one leader per query), so the "
            f"remaining ~{max(0.0, top_block_rows - all_cases):.0f} rows of the block are the "
            "LEAST-NEGATIVE margins -- which are the rank-2s from queries where s1 is closest to "
            "s2, i.e. precisely the queries with no decisive leader. Those are the queries where "
            "the leader is least likely to be uniquely gold, so their rank-2 gold rate is "
            "probably BELOW the average rank-2 rate this model uses. "
            "The predicted value is therefore an UPPER BOUND on what a margin calibration can "
            "reach, not a point estimate. That is the right shape for the CONFIRMED boundary -- "
            "clearing an upper bound is strong evidence -- and it is stated here so a landing "
            "between the boundaries is read as 'partly explained by a known bias' rather than as "
            "a surprise."
        ),
        "band_half_width": delta,
        "band_half_width_derivation": (
            f"two binomial standard errors of a rate {predicted} measured over "
            f"{top_block_rows:.0f} rows: 2 * sqrt(p(1-p)/n) = {delta}. Derived from the block "
            "size, not chosen."
        ),
        "bands": [
            {
                "condition": f"max_calibrated_precision >= {upper_boundary}",
                "verdict": "pooling across queries WAS the constraint, and it is removed",
                "reading": (
                    "The ceiling has moved to the rank-mixture value the cues' own rank structure "
                    "supports. The calibration was asking an incoherent question and now asks a "
                    "coherent one."
                ),
                "implication_for_the_roadmap": (
                    "The named next levers are the CROSS-ENCODER, then CONSOLIDATION. Cues 3-5 "
                    "stay deferred: a ceiling that moved on a feature-space fix says the "
                    "combiner/feature layer still had headroom, not that more cues are needed. "
                    "State plainly anyway -- a gain of this size does NOT extrapolate to 0.95."
                ),
            },
            {
                "condition": f"{lower_boundary} <= max_calibrated_precision < {upper_boundary}",
                "verdict": "per-query normalization helped, and something else also binds",
                "reading": (
                    "Real movement, short of what the rank structure supports. The residual is "
                    "the quantity to name before proceeding."
                ),
                "implication_for_the_roadmap": (
                    "The named next levers are the CROSS-ENCODER, then CONSOLIDATION. Cues 3-5 "
                    "stay deferred."
                ),
            },
            {
                "condition": f"max_calibrated_precision < {lower_boundary}",
                "verdict": "pooling was NOT the constraint; the gap has another cause",
                "reading": (
                    "The hypothesis this session tests is FALSIFIED. The named alternative "
                    "causes, in the order they should be examined: (a) the gap is arithmetic, not "
                    "a bug -- a top block and a rank-1 set are different populations and always "
                    "were; (b) near-duplicate turns, where several turns say the same thing and "
                    "attribution credits only the annotated one, so the ceiling is bounded by the "
                    "labels rather than by retrieval; (c) the candidate pool itself, ~493 raw "
                    "turns per case with near-duplicates competing against gold."
                ),
                "implication_for_the_roadmap": (
                    "The named next levers are STILL the CROSS-ENCODER, then CONSOLIDATION -- and "
                    "cause (b) or (c) makes consolidation the higher-leverage of the two. Cues "
                    "3-5 stay deferred EITHER WAY. Registered here explicitly so a flat result "
                    "does not reopen the cue question by default: a falsified feature-space "
                    "hypothesis is not evidence for more cues, because 34.8% of held-out cases "
                    "have gold at rank 1 from neither content cue and that population is "
                    "unreachable by any content-similarity cue, third or otherwise."
                ),
            },
        ],
    }

    # Does this experiment have the power to distinguish its own hypotheses? Session D's ceiling
    # band was well-derived and measured something its shape could not move; the mirror-image
    # failure is a band whose "confirmed" and "unmoved" regions overlap.
    band["band_separation_check"] = {
        "confirmed_at_or_above": upper_boundary,
        "unmoved_below": lower_boundary,
        "separated": upper_boundary > lower_boundary,
        "why_checked": (
            "A band whose confirming and falsifying regions overlap cannot return either verdict. "
            "Checked BEFORE registering, on the same discipline ADR-010 added after Session D "
            "registered a band on a quantity its shape could not move."
        ),
    }
    if upper_boundary <= lower_boundary:
        band["band_separation_check"]["consequence"] = (
            "NOT SEPARATED. The predicted ceiling is within measurement noise of Session D's, so "
            "this experiment cannot distinguish its hypothesis from the null. The band is "
            "registered anyway, with the middle band understood as 'no readable verdict'."
        )
    return band


def power_floor(split: dict, heldout_answerable: int) -> dict:
    n_min = min_n_for_power(POWER_P_HAT, POWER_FLOOR)
    return {
        "_registered_explicitly": (
            "PARTIAL COVERAGE AT HIGH PRECISION IS A PASS. Brief section 5.5 is precision-first "
            "-- 'the gate must be tuned for precision, with recall recovered by making the "
            "agent's explicit memory search tool excellent' -- and K1's wording carries no "
            "coverage term at all. A gate firing on 30% of queries at >= 0.95 precision MEETS "
            "K1's stated requirement. It is not a partial success and must not be reported as one."
        ),
        "name": "power floor on attributed injections",
        "why_injections_and_not_coverage": (
            "The injection count is the primitive that decides whether the precision number is "
            "readable at all, and it is exactly computable before the fit. A coverage fraction is "
            "not: it depends on the mean injections per firing case, which does not exist until "
            "the gate has been fit."
        ),
        "condition": (
            f"at least {n_min} ATTRIBUTED injections (gold + distractor) on the held-out split at "
            "the reported operating point"
        ),
        "n_min": n_min,
        "derivation": (
            f"the smallest N whose Wilson 95% lower bound at p_hat = {POWER_P_HAT} exceeds "
            f"{POWER_FLOOR}. Wilson, never Wald: at p near 1 the normal approximation extends "
            "above 1.0 and its coverage collapses, which is exactly the regime a 0.95 claim is "
            "read in."
        ),
        "wilson_lower_bound_at_n_min": round(wilson_lower_bound(POWER_P_HAT, n_min), 6),
        "wilson_lower_bound_at_n_min_minus_1": round(
            wilson_lower_bound(POWER_P_HAT, n_min - 1), 6
        ),
        "if_violated": (
            "the precision number is reported as UNDERPOWERED -- not as a pass, and not as a "
            "failure. It means the held-out split could not certify the claim at this coverage, "
            "which is a statement about the INSTRUMENT, not about the gate."
        ),
        "implied_coverage_floor": (
            f"derived after the fact as {n_min} / ({heldout_answerable} * m), with m the measured "
            "mean attributed injections per firing case. Reported, never used to move the floor."
        ),
        "predicted_difficulty": (
            f"At m = 1 this needs coverage {n_min / heldout_answerable:.3f} on "
            f"{heldout_answerable} answerable held-out cases, and at m = 2 it needs "
            f"{n_min / (2 * heldout_answerable):.3f}. **And m is structurally bounded by 2 under "
            "this shape** -- see shape.STRUCTURAL_CAP: margin is positive for at most one "
            "candidate per cue per query, so the gate can inject at most one memory per cue. The "
            "realistic case is m ~ 1, which needs coverage "
            f"{n_min / heldout_answerable:.3f} -- above this cue set's measured top-1 hit rate. "
            "**So UNDERPOWERED is the PREDICTED outcome, not a surprise.** Written down before "
            "the fit so it cannot later be read as a failure of the gate. The response is to "
            "report it and name what would fix it -- a larger scored population, since the "
            "all-500 run has twice the cases -- never to lower the floor and never to widen the "
            "feature until it injects more."
        ),
        "degenerate_pass_guard_still_applies": (
            "coverage < 0.05 still reports the operating-point precision as NOT a quality signal. "
            "The power floor sits beside that guard, not in place of it."
        ),
    }


def label_set_companion(corpus: Corpus, split: dict) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for case in corpus.cases:
        counts[case.category] += 1
    answerable_counts = {
        c: n for c, n in sorted(counts.items()) if c != "abstention"
    }
    smallest = min(answerable_counts.items(), key=lambda kv: kv[1])
    return {
        "_status": "COMPANION. REPORTED WITH NO VERDICT. It does not decide this session's result.",
        "_why_no_verdict": (
            "At m = 1 injection per firing case and a "
            f"{smallest[1]}-case smallest category, the >= {LABEL_SET_PER_CATEGORY}-per-category "
            f"requirement needs coverage {LABEL_SET_PER_CATEGORY / smallest[1]:.2f} -- above 1.0, "
            "so it is unmeetable by construction. Registering it as a pass/fail floor would be "
            "exactly the ADR-010 error: a band on a quantity the tested shape cannot reach."
        ),
        "what_it_answers": (
            "whether K1's own validation instrument is reachable at this operating point. K1's "
            "headline is human-judged, and the label set is what makes it measurable at all -- so "
            "a gate whose output cannot support a label draw has a headline nobody can compute."
        ),
        "requirement": {
            "source": "ROADMAP.md, 'The human label set -- your deliverable, not the agent's'",
            "total_judged_injections": LABEL_SET_TOTAL,
            "per_category": LABEL_SET_PER_CATEGORY,
            "stratified_by": "category and gate score decile",
        },
        "corpus_category_counts": dict(sorted(counts.items())),
        "smallest_answerable_category": {"category": smallest[0], "cases": smallest[1]},
        "to_be_reported": (
            "projected judged injections per category on a full-500 run at the MEASURED coverage "
            "and m, against both thresholds. Reported in summary.json beside the power floor."
        ),
    }


def build(
    split: dict, corpus: Corpus, rank_rates: dict, session_c: dict, session_d: dict
) -> dict:
    heldout_answerable = session_d["heldout_answerable_with_gold"]
    concentration = block_concentration(
        rank_rates.pop("_rows_for_concentration"),
        rank_rates["fit_rows"] / CALIBRATION_BLOCKS,
    )
    band = ceiling_band(rank_rates, session_d["ceiling"])

    return {
        "session": "M0b Session E",
        "what_ships": (
            "PER-QUERY FEATURES. What the calibration READS changes; the cue set does not, the "
            "threshold does not, and the split does not. Still two of five cues -- no "
            "entity-graph, temporal or causal cue -- so a number here remains a statement about "
            "an incomplete cue set, now normalized within each query rather than pooled across "
            "queries."
        ),
        "scored_population": (
            "The held-out split, answerable cases only (is_abstention == false). Unchanged from "
            "Sessions B, C and D so the four numbers are comparable."
        ),
        "session_c_baseline": session_c,
        "session_d_baseline": session_d,
        "the_hypothesis": {
            "claim": (
                "The isotonic curve pools candidates across all fit queries and asks what "
                "fraction of a raw-score band is gold. That requires BM25 and cosine to be "
                "comparable ACROSS queries. They are not: Session B deliberately chose absolute "
                "normalization (s/(s+10)) over min-max, so a query whose wording matches a lot of "
                "text has all its candidates scoring high and one with unusual phrasing has all "
                "of them scoring low. The top block fills with candidates from high-scoring "
                "QUERIES rather than high-scoring MATCHES -- the gate ranks queries against each "
                "other when it should rank candidates within a query."
            ),
            "the_fix": (
                "Replace the calibration's inputs with within-query normalized features, so the "
                "curve asks a coherent question: when a candidate is decisively better than its "
                "OWN competition, how often is it gold?"
            ),
            "it_also_resolves_ADR_010s_step_function": (
                "Margin is continuous and query-local, so it does not collapse at the head the "
                "way pooled calibrated precision did. And under this shape the calibration never "
                "enters the ordering at all, so Session D's failure mode is impossible by "
                "construction rather than merely mitigated."
            ),
        },
        # -------------------------------------------------- what this shape can and cannot move
        "structural_reach_check": {
            "_why": (
                "ADR-010's pre-registration lesson, applied one session after it was written: a "
                "band on a quantity the tested shape cannot structurally move is not a valid "
                "read. Checked BEFORE registering, not after the fit."
            ),
            "can_move": {
                "max_calibrated_precision (the ceiling)": (
                    f"YES -- this is the headline. Currently {session_d['ceiling']}."
                ),
                "top-1 gold-hit rate": (
                    f"YES, up to the oracle. Currently {session_d['top1_fitted_gate']}."
                ),
            },
            "cannot_move": {
                "either_cue_oracle_at_top_1": (
                    f"NO, STRUCTURALLY. It is {session_d['top1_oracle']} and no band is registered "
                    "on it. Within a query, z-score and margin are strictly monotone transforms "
                    "of a cue's raw score, so each cue's rank-1 candidate is UNCHANGED -- and "
                    "analyze_cue_overlap.py's oracle is exactly 'either cue's rank-1 is gold'. "
                    "Only a cross-encoder, which reads query and candidate together and can "
                    "promote a candidate neither cue ranked first, can move it. Registering an "
                    "oracle band here would repeat Session D's error verbatim."
                )
            },
        },
        # -------------------------------------------------- the shape
        "shape": {
            "cue_features_calibrated": ["lexical_margin", "dense_margin"],
            "rank_features_ordering": ["lexical_z", "dense_z"],
            "ranking_key": (
                "(winning cue's z DESC, winning cue's margin DESC, entry.id ASC), where the "
                "winning cue is argmax over cues of that cue's calibrated precision"
            ),
            "passes": "max over cues of calibrated precision >= 0.95. Threshold and units unchanged.",
            "how_it_obeys_ADR_010": (
                "ADR-010 permits calibrated values to CHOOSE BETWEEN cues and forbids them from "
                "deciding the order at the top. Here the calibration does exactly the permitted "
                "job -- it picks which cue speaks for a candidate, and it decides pass/fail -- and "
                "the ordering is a continuous query-local score. A step function cannot decide a "
                "rank in this shape at all."
            ),
            "why_margin_is_CALIBRATED_and_z_is_not": (
                "Session B rejected min-max normalization because it forces the best candidate of "
                "EVERY query to 1.0, including queries where nothing matches, so a gate reading "
                "it could never abstain. Sigma-normalized z carries the same defect in weaker "
                "form: a candidate that barely beats noise in a tight distribution still scores "
                "high. Margin over the runner-up in RAW units does not -- a query where "
                "everything is near zero has a tiny margin. Absolute-magnitude preservation is "
                "what precision-first needs from the quantity the threshold reads."
            ),
            "why_z_is_the_RANKING_key_and_margin_is_not": (
                "Across cues the units differ: a margin in BM25 units cannot be compared to a "
                "margin in cosine units. z is dimensionless, so it is the only one of the two "
                "that can order a lexical-won candidate against a dense-won one. Within a query "
                "the two give the IDENTICAL order -- both are monotone in the raw score -- so "
                "this choice costs nothing and only matters across cues."
            ),
            "lexical_margin_is_computed_on_RAW_bm25_before_saturation": (
                "Identified before the fit. saturate(s) = s/(s+10) compresses the top of the "
                "range: at s=30->0.750 and s=40->0.800 the margin is 0.050, while at s=0->0.000 "
                "and s=1->0.091 it is 0.091. Computing margin on the saturated value would make "
                "LOW-score margins look LARGER than high-score ones, inverting the very property "
                "margin is chosen for. Ranks are unaffected either way because saturate is "
                "monotone, which is why the rank rates measured above are valid regardless."
            ),
            "STRUCTURAL_CAP_at_most_one_injection_per_cue_per_query": (
                "IDENTIFIED BEFORE THE FIT, and it is a real cost of this shape rather than a "
                "detail. `margin` is the lead over the runner-up, so within one query at most ONE "
                "candidate per cue has a POSITIVE margin -- every other candidate's is <= 0 by "
                "construction. An isotonic curve is non-decreasing, so it cannot give high "
                "precision to a negative margin and low precision to a positive one. Therefore AT "
                "MOST 2 candidates per query (one per cue) can ever clear the threshold, and in "
                "the common case where both cues favour the same memory, exactly one. Asserted by "
                "test in retrieve.rs. "
                "Consequences, stated now rather than discovered in the results: (1) coverage is "
                "capped by the top-1 hit rate, so this shape cannot cover a query whose gold is "
                "not some cue's rank-1; (2) the mean attributed injections per firing case m is "
                "bounded by 2 and will usually be ~1, which is what makes the power floor hard to "
                "reach on a 249-case split; (3) it is NOT a defect to fix by widening the "
                "feature -- section 5.5 is precision-first and recovers recall through the "
                "explicit search tool. It is the cost of asking a decisiveness question, and it "
                "is accepted knowingly."
            ),
            "sigma_zero_is_defined_not_defaulted": (
                "A query where every candidate scores identically -- the common all-zero-BM25 "
                "case -- has sigma 0. z is defined as 0.0 there, matching dense_for's existing "
                "rule that absent evidence is worth 0.0 and never a skip. Asserted by test, not "
                "left to fall out of a division."
            ),
        },
        # -------------------------------------------------- 1. the floor
        "floor_condition": {
            "_status": "INHERITED UNCHANGED from Session D, which inherited it from STATE.md.",
            "name": "any fusion must score at or above its best single input at the operating point",
            "condition": f"top-1 gold-hit rate on the held-out split >= {session_d['top1_best_single']}",
            "read_by": (
                "tools/analyze_cue_overlap.py, over the same "
                f"{heldout_answerable} answerable-with-gold held-out cases that produced "
                f"{session_d['top1_best_single']}. The hit() definition and the case-selection "
                "filter are NOT modified -- a number computed a second way is not comparable to "
                "the one it is judged against."
            ),
            "why_it_is_a_real_test_and_not_a_formality": (
                "A shape that always picked lexical would score exactly the floor. So the floor "
                "asks precisely one question: does calibrated cue-SELECTION beat always-lexical? "
                "It is meetable, and it can fail."
            ),
            "if_violated": (
                "The session FAILS OUTRIGHT. No partial credit and no re-tuning. Session D's "
                f"{session_d['top1_fitted_gate']} against this same floor is the precedent."
            ),
        },
        # -------------------------------------------------- 2a. the PRIMARY diagnostic
        "block_concentration": concentration,
        # -------------------------------------------------- 2b. the ceiling (underpowered)
        "ceiling_band": band,
        # -------------------------------------------------- 3. coverage / power
        "power_floor": power_floor(split, heldout_answerable),
        "label_set_feasibility": label_set_companion(corpus, split),
        # -------------------------------------------------- 4. numbers carried forward
        "number_1": {
            "name": "operating-point result",
            "definition": (
                "evidence_precision and coverage on the held-out split at the frozen threshold of "
                "0.95 calibrated precision."
            ),
            "band": None,
            "note": (
                "Deliberately no band, exactly as Sessions B, C and D. Reported whatever it is, "
                "including 'the gate abstained on every case' for a fourth session. The threshold "
                "does not move."
            ),
        },
        "number_2": {
            "name": "cue capability",
            "definition": (
                "held-out evidence_precision read off the precision/coverage curve at the most "
                "selective cut where coverage reaches 0.25. UNCHANGED from Sessions B, C and D."
            ),
            "read_rule_unchanged": True,
            "band": None,
        },
        "number_2b": {
            "name": "cue capability at matched coverage",
            "_status": "CARRIED FORWARD from Session D, anchored on the same point.",
            "definition": (
                "held-out evidence_precision read at the most selective cut whose coverage is at "
                f"least {session_c['number_2']['coverage_there']} -- Session C's REALISED "
                "coverage, not its floor."
            ),
            "session_c_reference_at_this_coverage": session_c["number_2"]["value"],
            "band": None,
            "note": (
                "Reported as a companion, never a replacement. Number 2's verdict stands on "
                "Number 2's own rule. Session D could not read this at matched coverage -- its "
                "step function offered no cut near the read point -- and reported it as unmatched "
                "rather than quoting the delta. A shape whose calibration is continuous at the "
                "head should be able to offer the read point; whether it does is itself a signal."
            ),
        },
        "number_3": {
            "name": "per-cue diagnostic",
            "definition": (
                "held-out precision at coverage 0.25, sweeping each RAW cue score alone. "
                "UNCHANGED. This is why lexical_bm25 and dense_cosine stay in the feature vector "
                "as declared-inert rather than being deleted: they are the cross-session anchor, "
                "and Session D's unchanged-cue check reads them."
            ),
            "expected": (
                "IDENTICAL to Sessions C and D -- lexical 0.418182, dense 0.298387. The cue set "
                "did not change, so a move here means the held-out population changed rather than "
                "the features, and every cross-session comparison would be invalid."
            ),
        },
        # -------------------------------------------------- conditions
        "independent_conditions": {
            "determinism": {
                "condition": "`repro --runs 2` produces two identical sha256",
                "checked": "BEFORE the quality numbers are read, and again after the v4 build.",
                "session_e_step_0_result": (
                    "PASS on the v3 binary -- a4be3bf8... twice, run WITHOUT an embedding cache, "
                    "so it also proves the embedder is deterministic across process spawns. This "
                    "closes the item Session D left NOT MEASURED."
                ),
                "new_surface_this_session": (
                    "Per-query features add a REDUCTION over the candidate set (mean, variance, "
                    "runner-up). Floating-point summation is order-dependent, so the reduction "
                    "order is pinned to candidate-slice index order and asserted by test. This is "
                    "the determinism surface the change introduces and it is named before it is "
                    "built."
                ),
                "if_violated": "EVERY number in this session is VOID, not caveated.",
            },
            "budget": {
                "condition": "P95 retrieval latency <= 300 ms AND no case above 7,000 retrieval tokens",
                "read_from": (
                    "a CACHE-COLD run. A cache hit removes the query's forward pass from the "
                    "timed span, so the warm figure understates what a user pays on a fresh "
                    "profile."
                ),
                "may_not_be_fixed_by": (
                    "excluding the embedding from the timed span. It is a real per-query cost."
                ),
                "if_violated": "the precision numbers are VOID, not caveated.",
            },
            "false_evidence_on_abstention_cases": {
                "condition": "injections_on_abstention_cases / abstention_cases <= 0.20",
                "_this_condition_becomes_NON_VACUOUS_if_the_gate_injects": (
                    "It has been vacuous for three sessions because nothing was injected. If v4 "
                    "injects, it becomes live for the first time -- AND IT IS THE CHECK THAT "
                    "CATCHES THIS SESSION'S OWN MOST LIKELY DEFECT. A query with no good "
                    "candidate still has a BEST candidate; if query-local normalization inflates "
                    "it, the gate fires on abstention cases. That is Session B's rejected min-max "
                    "failure re-entering through the feature space, and this is the instrument "
                    "that sees it. Registered before the fit so a green result cannot be read as "
                    "evidence for something nobody predicted."
                ),
            },
            "degenerate_pass_guard": {
                "condition": "coverage < 0.05",
                "if_triggered": "precision is reported as NOT a quality signal.",
            },
            "eval_unchanged": {
                "condition": "`cd eval && python -m pytest` prints 72, and `git status -- eval/` is clean",
                "why": (
                    "a changed count means the scoreboard was modified to accommodate the "
                    "implementation."
                ),
            },
        },
        "ordered_gates": [
            {
                "order": 1,
                "action": "run `conformance` and the clock probe BEFORE reading any quality number",
                "session_e_step_0_result": (
                    "REJECTED with 0 section-4 findings, clock probe fail_no_time_dependence -- "
                    "both consequences of the empty injected set, exactly as predicted. Re-run "
                    "after the v4 fit: if the gate injects, section 4.3 maturation becomes "
                    "verifiable through the contract again, and that is the run where a silent "
                    "loss of the defence would show."
                ),
                "if_it_fails_for_a_NEW_reason": "stop and fix. Do not score.",
            },
            {
                "order": 2,
                "action": "record the calibration generalization pair, one per cue",
                "rule": (
                    "held-out below the fit-split prediction by MORE THAN 0.05 absolute is a "
                    "signal about the CALIBRATION, not about the cue: investigate the fit before "
                    "anything else."
                ),
                "session_b_reference": "0.309 predicted -> 0.334 measured",
                "session_c_reference": "0.3176 predicted -> 0.371 measured",
                "session_d_reference": "0.309013 predicted -> 0.334123 measured",
            },
        ],
        # -------------------------------------------------- predicted outcomes
        "predicted_before_the_run": {
            "_why": (
                "A green suite with no record of what was expected reads as a suite that measured "
                "something. Each of these is a VACUITY that persists, not a result."
            ),
            "if_the_ceiling_stays_below_0_95": [
                "the gate still abstains on all 249 held-out cases",
                "conformance stays REJECTED with 0 section 4 findings",
                "the clock probe still fails no_time_dependence",
                "MINJA / MemoryGraft / delayed-trigger ASR stay 0.000 and remain VACUOUS",
                "the laundering trust assertion stays vacuous",
                "evidence_precision on the wire stays 0.0 with an empty denominator",
                "utility_retention stays 0.0",
                "section 4.3 maturation stays uncovered at contract level",
                "the degenerate-pass guard triggers",
                "the power floor is not reached, and is reported as UNDERPOWERED rather than failed",
            ],
            "none_of_these_is_a_session_e_regression": True,
            "what_would_be_a_regression": (
                "conformance failing for a reason OTHER than the empty injected set; the clock "
                "probe failing a check other than no_time_dependence; Number 3 moving when the "
                "cue set did not; or repro producing two different hashes."
            ),
        },
        # -------------------------------------------------- the cross-encoder spike
        "cross_encoder_spike": {
            "_status": (
                "CONDITIONS REGISTERED BEFORE THE SPIKE IS MEASURED. A spike whose bar is set "
                "after the number is not a spike. Same discipline as the engine gate and ADR-004."
            ),
            "gated_on": (
                "the ceiling band landing at or above its middle boundary. If the ceiling does "
                "not move, the spike does not run this session."
            ),
            "scope_this_session": (
                "FETCH, PIN, PROVE, MEASURE. Pair tokenizer with token_type_ids, digest "
                "verification, the three determinism checks, cold P95 over 20 candidates. The "
                "rerank stage, the refit and the oracle-after-rerank read land NEXT session, on a "
                "measured budget rather than a projected one."
            ),
            "why_it_is_the_only_thing_that_can_move_the_oracle": (
                "Every cue scores a memory in isolation and the fusion compares those scores, so "
                "any fusion is bounded by 'one of the cues ranked it first'. A cross-encoder "
                "reads query and candidate together in one pass, so its top-1 ceiling is the "
                "RECALL of the candidate pool it reranks, not the either-cue oracle."
            ),
            "conditions": {
                "latency": {
                    "condition": (
                        "total COLD retrieval P95 <= 300 ms with the reranker inside the timed "
                        "span, over the top 20 candidates"
                    ),
                    "why_not_a_sub_budget": (
                        "section 5.7's requirement is on total retrieval latency. An invented "
                        "~50 ms sub-budget would be a constant nobody measured entering the "
                        "frozen path -- the objection that killed the cosine firing floor."
                    ),
                    "also_reported": "the rerank stage's own P95, beside the total.",
                },
                "determinism": {
                    "condition": (
                        "bit-identical logit for the same (query, candidate) across: (a) two "
                        "process spawns, (b) two ONNX worker-thread counts, (c) batch size 1 vs "
                        "batch size 20"
                    ),
                    "which_one_matters": (
                        "(c). Batching changes the reduction order inside the graph, and a "
                        "batch-dependent logit would make the injected set depend on how many "
                        "candidates happened to survive the filter -- which repro would catch "
                        "only intermittently."
                    ),
                    "if_c_fails": (
                        "batching is not used, and the latency condition is re-read without it. "
                        "Determinism is not traded for latency."
                    ),
                },
                "digest": {
                    "condition": (
                        "model and tokenizer vocab sha256 pinned in a fetch script and verified "
                        "at BOTH download and load"
                    ),
                    "precedent": "embedder.rs already does exactly this.",
                },
                "reference": {
                    "condition": (
                        "Rust output matches Python onnxruntime on the same pinned graph across "
                        "pair-encoding hazards: long-candidate truncation, empty query, unicode, "
                        "token_type_ids boundaries"
                    ),
                    "prefer_a_maintainer_published_export": (
                        "STATE.md carries an open gap -- our jina ONNX export is not "
                        "independently validated against the published model, because "
                        "transformers.onnx was removed in transformers 5.x and the authority is "
                        "gone. Using a maintainer-published ONNX export here avoids acquiring a "
                        "SECOND instance of that gap. If no such export exists, the gap is "
                        "recorded for this model too rather than papered over."
                    ),
                },
                "one_fallback_decided_now": {
                    "condition": (
                        "if L-6 at max_seq_len 512 misses the latency bar, the single "
                        "pre-registered fallback is max_seq_len 256 with the truncation rate "
                        "measured and reported. If that also misses, THE RERANKER IS NOT ADOPTED "
                        "AT M0b."
                    ),
                    "why_only_one": (
                        "a ladder of fallbacks chosen after seeing the number is tuning. One "
                        "step, decided before measuring, with a named stopping point."
                    ),
                },
            },
        },
        # -------------------------------------------------- carried decisions
        "calibration_resolution": {
            "decision": f"CALIBRATION_BLOCKS = {CALIBRATION_BLOCKS}, unchanged",
            "why_this_is_not_a_re_tune": (
                "STATE.md forbids re-tuning the calibration resolution. It is also an INPUT to "
                "this session's ceiling band -- the top block's width is fit_rows / blocks -- so "
                "changing it would move the very number the band predicts. Held fixed for both "
                "reasons."
            ),
        },
        "gate_artifact_version": {
            "bump": "frozen-v3 -> frozen-v4",
            "why_structural": (
                "The feature vector changes shape and the fusion changes name. feature_names and "
                "fusion are both asserted at load, and serde deny_unknown_fields refuses in both "
                "directions. The refusal set GROWS and never shrinks -- rank_features is a new "
                "role and gains its own refusals, so a feature cannot silently leave the ordering "
                "any more than it can silently leave the calibration."
            ),
            "the_floor_interlock_carries_forward": (
                "FailedFloorWouldInject is what stops a shape measured below its own best input "
                "from deciding what reaches the model. This is the session that could make it "
                "bite, since the whole point is to make the gate inject."
            ),
        },
        "split": {
            "redrawn": False,
            "rule": split["rule"],
            "digest": split["digest"],
            "fit_cases": split["fit_cases"],
            "heldout_cases": split["heldout_cases"],
            "corpus_sha256": split["corpus_sha256"],
            "note": (
                "Session B's split, unchanged through C, D and E and asserted by digest. "
                "Redrawing it would invalidate every number fit under it."
            ),
        },
    }


def session_c_baseline() -> dict:
    """Session C's Number 2 read point, from its own file rather than retyped.

    Carried forward because Number 2b is defined against Session C's **realised** coverage, and
    that anchor must not drift as sessions accumulate. Session D registered it; Session E inherits
    the same anchor so B, C, D and E all read at one point.
    """
    if not SESSION_C_SUMMARY.exists():
        raise SystemExit(
            f"{SESSION_C_SUMMARY} does not exist. Number 2b is defined against Session C's "
            "realised coverage; refusing to invent an anchor."
        )
    summary = json.loads(SESSION_C_SUMMARY.read_text(encoding="utf-8"))
    n2 = summary["number_2_cue_capability"]
    return {
        "number_2": {
            "value": n2["value"],
            "read_at_cut": n2["read_at_cut"],
            "coverage_there": n2["coverage_there"],
        },
        "_note": "Read from runs/session-c/summary.json, not retyped.",
    }


def session_d_baseline() -> dict:
    """Session D's read points, from its own files rather than retyped."""
    for path in (SESSION_D_SUMMARY, SESSION_D_OVERLAP):
        if not path.exists():
            raise SystemExit(
                f"{path} does not exist. Session E's bands are derived from Session D's recorded "
                "numbers; refusing to invent a baseline."
            )
    summary = json.loads(SESSION_D_SUMMARY.read_text(encoding="utf-8"))
    overlap = json.loads(SESSION_D_OVERLAP.read_text(encoding="utf-8"))
    top1 = overlap["gold_in_top_k"]["1"]
    return {
        "ceiling": summary["gate"]["max_calibrated_precision_on_the_curve"],
        "top1_fitted_gate": top1["fitted_gate"],
        "top1_lexical": top1["lexical"],
        "top1_dense": top1["dense"],
        "top1_best_single": max(top1["lexical"], top1["dense"]),
        "top1_oracle": top1["either_oracle"],
        "heldout_answerable_with_gold": overlap["cases"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing pre-registration. Refused by default.",
    )
    parser.add_argument("--keep-dump", help="write the fit-split feature dump here and keep it")
    parser.add_argument("--max-rank", type=int, default=5)
    args = parser.parse_args()

    if not BINARY.exists():
        raise SystemExit(f"{BINARY} not found. Build it first: cargo build --release.")

    if PREREG_PATH.exists() and not args.force:
        print(
            f"{PREREG_PATH} already exists. Refusing to rewrite a pre-registration; pass --force "
            "only if you intend to invalidate every number registered under it.",
            file=sys.stderr,
        )
        return 1

    split = load_split()
    session_c = session_c_baseline()
    session_d = session_d_baseline()
    corpus = longmemeval.load(REPO / split["corpus_path"])
    fit_corpus = subset(corpus, set(split["fit"]), "-fit")
    if len(fit_corpus.cases) != split["fit_cases"]:
        raise SystemExit(
            f"the split names {split['fit_cases']} fit cases but {len(fit_corpus.cases)} are "
            "present in the corpus"
        )

    if args.keep_dump:
        tmp = Path(args.keep_dump)
    else:
        handle, name = tempfile.mkstemp(suffix=".ndjson")
        os.close(handle)
        tmp = Path(name)

    print(f"corpus:  {REPO / split['corpus_path']}")
    print(f"split:   {split['fit_cases']} fit / {split['heldout_cases']} heldout")
    print(f"dump:    {tmp}")
    print("measuring rank-k gold rates on the FIT split (no gate is loaded) ...")
    rank_rates = rank_gold_rates(fit_corpus, tmp, args.max_rank)
    print(
        f"  {rank_rates['fit_rows']} rows, {rank_rates['fit_cases_with_gold']} cases with gold, "
        f"{rank_rates['seconds']}s"
    )
    for cue, rates in rank_rates["per_cue"].items():
        shown = "  ".join(f"r{r['rank']}={r['gold_rate']:.4f}" for r in rates if r["gold_rate"] is not None)
        print(f"  {cue:16s} {shown}")

    prereg = build(split, corpus, rank_rates, session_c, session_d)

    PREREG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREREG_PATH.write_text(json.dumps(prereg, indent=2) + "\n", encoding="utf-8")
    if not args.keep_dump:
        tmp.unlink(missing_ok=True)

    band = prereg["ceiling_band"]
    power = prereg["power_floor"]
    print()
    print(f"pre-registration: {PREREG_PATH}")
    print(f"  split digest (unchanged): {split['digest']}")
    print()
    print("  THE FLOOR (inherited, hard, no partial credit)")
    print(f"    top-1 must reach >= {session_d['top1_best_single']}   "
          f"(Session D measured {session_d['top1_fitted_gate']} and FAILED)")
    print()
    print("  THE CEILING (the headline)")
    print(f"    trajectory        0.309013 -> 0.317597 -> {session_d['ceiling']} -> ?")
    print(f"    top block holds   {band['block_arithmetic']['top_block_rows']} rows over "
          f"{band['block_arithmetic']['fit_cases_with_gold']} cases "
          f"= {band['block_arithmetic']['candidates_per_case_in_top_block']} per case")
    print(f"    predicted         {band['prediction_before_the_fit']}  "
          f"(+/- {band['band_half_width']}, two binomial SE)")
    for b in band["bands"]:
        print(f"    {b['condition']:48s} -> {b['verdict']}")
    sep = band["band_separation_check"]
    print(f"    bands separated:  {sep['separated']}")
    conc = prereg["block_concentration"]
    print()
    print("  THE PRIMARY DIAGNOSTIC -- top-block query concentration (well-powered)")
    print(f"    null if no query effect: {conc['null_if_there_were_no_query_effect']['expected_distinct_queries']}"
          f" +/- {conc['null_if_there_were_no_query_effect']['sd']} distinct queries")
    for feature, blk in conc["by_feature"].items():
        print(f"    {feature:16s} {blk['distinct_queries_in_top_block']:4d} distinct "
              f"({blk['fraction_of_queries_covered']:.1%})  z={blk['z_against_the_no_query_effect_null']:+.1f}"
              f"  concentrated={blk['concentrated']}")
    print(f"    VERDICT: {conc['measured_verdict']}")
    print()
    print("  THE POWER FLOOR (derived, not a round number)")
    print(f"    N_min             {power['n_min']} attributed injections")
    print(f"    Wilson LB there   {power['wilson_lower_bound_at_n_min']} > {POWER_FLOOR}")
    print(f"    one fewer         {power['wilson_lower_bound_at_n_min_minus_1']}")
    print()
    print("  PARTIAL COVERAGE AT HIGH PRECISION IS A PASS -- registered explicitly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
