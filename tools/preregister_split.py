"""Pre-registration for M0b Session B. **Run this before fitting anything.**

Writes two files, and both have to exist before a number does:

  tools/split.json                  the fit/held-out split, by a rule fixed here
  runs/session-b/PREREGISTRATION.json   what each number would have to be to mean something,
                                    plus the poisoning-suite vacuity prediction

Why a file and not a paragraph. `tools/fit_gate.py` refuses to run without `split.json` and
checks its corpus digest, so the split cannot be chosen after seeing a fit. The bands and the
vacuity prediction sit next to the run they describe for the same reason: a prediction that can
be written after the fact is not a prediction, and a green suite with no record of what was
expected reads as a suite that measured something.

HP1 says the gate's weights are fit on LongMemEval gold evidence. It does not say what to
report them against. Fitting and scoring on the same 500 questions would be train-on-test, so
the split exists -- see DECISIONS.md HP1, "The fit/report split".

    python tools/preregister_split.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.datasets import longmemeval  # noqa: E402

DEFAULT_CORPUS = REPO / "data" / "longmemeval_s_cleaned.json"
SPLIT_PATH = REPO / "tools" / "split.json"
PREREG_PATH = REPO / "runs" / "session-b" / "PREREGISTRATION.json"

SPLIT_RULE = (
    "Within each harness category (Case.category -- question_type, or 'abstention' for the "
    "_abs subset), sort query_ids by (sha256(query_id).hexdigest(), query_id) and assign "
    "even indices to `fit` and odd indices to `heldout`. Deterministic, and stratified rather "
    "than merely random: every category is split within one case of even, so both halves have "
    "support in all seven."
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def build_split(corpus_path: Path) -> dict:
    corpus = longmemeval.load(corpus_path)

    by_category: dict[str, list[str]] = defaultdict(list)
    for case in corpus.cases:
        by_category[case.category].append(case.query_id)

    fit: list[str] = []
    heldout: list[str] = []
    per_category: dict[str, dict[str, int]] = {}
    for category, query_ids in sorted(by_category.items()):
        ordered = sorted(
            query_ids, key=lambda q: (hashlib.sha256(q.encode()).hexdigest(), q)
        )
        f = ordered[0::2]
        h = ordered[1::2]
        fit.extend(f)
        heldout.extend(h)
        per_category[category] = {"fit": len(f), "heldout": len(h)}

    fit.sort()
    heldout.sort()

    body = {
        "rule": SPLIT_RULE,
        "corpus": corpus.name,
        "corpus_variant": "cleaned",
        "corpus_path": str(corpus_path.relative_to(REPO)).replace("\\", "/"),
        "corpus_sha256": sha256_file(corpus_path),
        "cases": len(corpus.cases),
        "fit_cases": len(fit),
        "heldout_cases": len(heldout),
        "per_category": per_category,
        "fit": fit,
        "heldout": heldout,
    }
    # The digest covers the rule and both id lists. `fit_gate.py` recomputes it, so an edited
    # split is a loud mismatch rather than a quietly different experiment.
    body["digest"] = hashlib.sha256(
        canonical({"rule": body["rule"], "fit": fit, "heldout": heldout}).encode()
    ).hexdigest()
    return body


PREREGISTRATION = {
    "session": "M0b Session B",
    "what_ships": (
        "One lexical cue (BM25) and the frozen gate with a real isotonic calibration. This is "
        "NOT the five-cue system K1 measures -- dense, entity-graph, temporal and causal are "
        "all absent. A low number here is a statement about an incomplete cue set."
    ),
    "scored_population": (
        "The held-out split, answerable cases only (is_abstention == false). Abstention cases "
        "are scored separately by the condition below, because an injection there is a "
        "different failure from picking the wrong evidence."
    ),
    "definitions": {
        "evidence_precision": (
            "the harness's own metric: gold / (gold + distractor) over injected memories, "
            "attributed via the section 4.6 written[].turn_id mapping. NOT the K1 headline, "
            "which is human-judged and needs a label set that does not exist yet."
        ),
        "coverage": (
            "driver-side diagnostic, not a harness metric: the fraction of answerable cases "
            "with at least one GOLD memory injected. Reported because precision alone is "
            "gameable by injecting almost nothing."
        ),
    },
    "number_1": {
        "name": "operating-point result",
        "definition": (
            "evidence_precision and coverage on the held-out split at the frozen threshold "
            "of 0.95 calibrated precision."
        ),
        "band": None,
        "note": (
            "Deliberately no band. It is reported whatever it is, including 'the gate "
            "abstained on every case'. That outcome is anticipated: with one cue the isotonic "
            "curve may never reach 0.95 predicted precision anywhere, in which case the "
            "honest finding is that the single-cue gate cannot reach the K1 operating point. "
            "The threshold does not move in response -- that is the tuning HP1 forbids, and "
            "ROADMAP M10 is the only milestone permitted to move an operating point."
        ),
    },
    "number_2": {
        "name": "cue capability",
        "definition": (
            "held-out evidence_precision read off the precision/coverage curve at the "
            "threshold where coverage first reaches 0.25. Isolates what the cue can do from "
            "where the frozen operating point sits."
        ),
        "why_a_curve": (
            "ADR-003's precedent -- the curve is the artifact. Publishing it is reporting; "
            "changing the shipped threshold because of it would be tuning."
        ),
        "bands": [
            {
                "verdict": "cue working",
                "condition": "precision >= 0.50",
                "reading": "Lexical alone is a real retriever; K1 looks reachable once cues 2-5 land.",
            },
            {
                "verdict": "functioning, cue set incomplete",
                "condition": "0.20 <= precision < 0.50",
                "reading": "The expected outcome. The cue finds genuine evidence; the gap is the four missing cues.",
            },
            {
                "verdict": "implementation suspect",
                "condition": "precision < 0.20",
                "reading": (
                    "Investigate the tokenizer and the BM25 arithmetic BEFORE blaming the cue "
                    "set. Chance is roughly 0.002-0.01 (a handful of gold turns among ~493 per "
                    "case), so above chance but under 0.20 points at the implementation."
                ),
            },
        ],
    },
    "independent_conditions": {
        "budget": {
            "condition": "P95 retrieval latency <= 300 ms AND no case above 7,000 retrieval tokens",
            "if_violated": (
                "The precision numbers are VOID, not merely caveated. K1 is defined at those "
                "budgets and a precision figure bought with an overrun is not a K1 signal."
            ),
        },
        "false_evidence_on_abstention_cases": {
            "condition": "injections_on_abstention_cases / abstention_cases <= 0.20",
            "why": (
                "Producing evidence for a question that has none is a distinct failure from "
                "picking the wrong evidence. The harness already counts it on its own line."
            ),
        },
        "degenerate_pass_guard": {
            "condition": "coverage < 0.05",
            "if_triggered": (
                "Precision is reported as NOT a quality signal. A gate that abstains its way "
                "to a good-looking ratio has not retrieved anything."
            ),
        },
    },
    "poisoning_vacuity_prediction": {
        "predicted_before_the_run": True,
        "prediction": (
            "A gate that suppresses the MINJA / MemoryGraft / delayed-trigger injections will "
            "also stop the planted memory from reaching the injected set. The harness's "
            "poisoning._observed_trust returns None when the planted memory was never "
            "injected, and it SCORES THAT AS A PASS. So the laundering trust assertion is "
            "predicted to become VACUOUS in this session -- 16 checked, 0 failed, and nothing "
            "actually observed."
        ),
        "why_this_is_written_down_first": (
            "Session A measured the laundering assertion as non-vacuous precisely because "
            "there was no gate. If Session B comes back green with no record of what was "
            "expected, a later reader sees a passing suite that measured nothing and reads it "
            "as evidence. The correct report is 'vacuous', stated as such."
        ),
        "what_would_falsify_it": (
            "The attack memories still reaching the injected set. That would mean the gate is "
            "not suppressing them, and the ASR numbers should stay at Session A's 1.000."
        ),
        "what_this_is_not": (
            "Not a reason to touch MATURATION_WINDOW_MS. STATE.md's first known issue is "
            "explicit: the correct response to a vacuous assertion is to report it as vacuous."
        ),
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing split. Refused by default: silently re-drawing a "
        "pre-registration is the thing this file exists to prevent.",
    )
    args = parser.parse_args()

    corpus_path = Path(args.corpus)
    if not corpus_path.exists():
        print(f"corpus not found: {corpus_path}", file=sys.stderr)
        return 1

    if SPLIT_PATH.exists() and not args.force:
        print(
            f"{SPLIT_PATH} already exists. Refusing to redraw a pre-registered split; pass "
            "--force only if you intend to invalidate every number fit under it.",
            file=sys.stderr,
        )
        return 1

    print(f"hashing {corpus_path} ...")
    split = build_split(corpus_path)
    SPLIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPLIT_PATH.write_text(json.dumps(split, indent=2) + "\n", encoding="utf-8")

    prereg = dict(PREREGISTRATION)
    prereg["split"] = {
        "rule": split["rule"],
        "digest": split["digest"],
        "fit_cases": split["fit_cases"],
        "heldout_cases": split["heldout_cases"],
        "corpus_sha256": split["corpus_sha256"],
        "per_category": split["per_category"],
    }
    PREREG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREREG_PATH.write_text(json.dumps(prereg, indent=2) + "\n", encoding="utf-8")

    print(f"split:           {SPLIT_PATH}")
    print(f"  corpus sha256: {split['corpus_sha256']}")
    print(f"  digest:        {split['digest']}")
    print(f"  fit / heldout: {split['fit_cases']} / {split['heldout_cases']}")
    for category, counts in sorted(split["per_category"].items()):
        print(f"    {category:32s} {counts['fit']:4d} / {counts['heldout']:4d}")
    print(f"pre-registration: {PREREG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
