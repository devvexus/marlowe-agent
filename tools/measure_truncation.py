"""Measure the truncation rate at MAX_SEQ_LEN over the real corpus.

**Pre-registered in `runs/session-c/PREREGISTRATION.json` under `max_seq_len_falsification`,
and measured HERE — before the fit, and before any quality number exists.** That ordering is the
whole point. The truncation rate is a property of the corpus and the tokenizer alone: nothing
about it depends on the gate, the weights, precision, or coverage. So choosing the parameter
against this number is not tuning, while choosing it against a precision figure would be.

The bands and the single permitted adjustment were written down first. This script only
measures; it does not decide, and it deliberately prints the pre-registered rule beside the
result so the two are read together.

What is measured: `Turn.text` for every turn in the corpus, because `ingest.rs` sets
`text: turn.text.clone()` verbatim — the entry text IS the turn text. Query texts are measured
separately, since the query takes the same forward pass at retrieval time.

    python tools/measure_truncation.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.datasets import longmemeval  # noqa: E402

MODEL_DIR = REPO / "models" / "all-MiniLM-L6-v2"
SPLIT_PATH = REPO / "tools" / "split.json"
PREREG_PATH = REPO / "runs" / "session-c" / "PREREGISTRATION.json"
OUT_PATH = REPO / "runs" / "session-c" / "truncation.json"

# The candidate lengths, in the order the pre-registered rule considers them.
CANDIDATES = (128, 192, 256)


def token_lengths(tokenizer, texts: list[str]) -> np.ndarray:
    """Wordpiece length INCLUDING [CLS] and [SEP], which is what the limit applies to."""
    lengths = np.zeros(len(texts), dtype=np.int32)
    batch = 2000
    for start in range(0, len(texts), batch):
        chunk = texts[start : start + batch]
        encoded = tokenizer(chunk, add_special_tokens=True, truncation=False, padding=False)
        lengths[start : start + len(chunk)] = [len(ids) for ids in encoded["input_ids"]]
    return lengths


def describe(lengths: np.ndarray) -> dict:
    percentiles = [50, 75, 90, 95, 99, 99.9]
    return {
        "n": int(lengths.size),
        "mean": round(float(lengths.mean()), 2),
        "max": int(lengths.max()),
        "percentiles": {
            str(p): int(np.percentile(lengths, p)) for p in percentiles
        },
        "truncation_rate": {
            str(limit): round(float((lengths > limit).mean()), 6) for limit in CANDIDATES
        },
        "tokens_lost_fraction": {
            # Of all wordpiece tokens in the corpus, the fraction that would be cut. A rate of
            # 20% of TURNS truncated means something very different if each loses two tokens
            # than if each loses two hundred, and the rate alone cannot tell them apart.
            str(limit): round(
                float(np.clip(lengths - limit, 0, None).sum() / lengths.sum()), 6
            )
            for limit in CANDIDATES
        },
    }


def verdict(rate: float) -> tuple[str, str]:
    if rate <= 0.10:
        return ("principle confirmed", "128 stands. Reported as a statistic.")
    if rate <= 0.25:
        return (
            "principle weakened but directionally intact",
            "128 stands for this session; the rate is reported beside every number.",
        )
    return (
        "principle falsified",
        "ONE pre-committed adjustment: the smallest of [192, 256] whose rate is <= 0.10, "
        "else 256 (the model's own configured maximum).",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    del args

    if not MODEL_DIR.exists():
        raise SystemExit(f"{MODEL_DIR} not found. Run `python tools/fetch_model.py` first.")
    if not PREREG_PATH.exists():
        raise SystemExit(
            f"{PREREG_PATH} not found. The bands this measurement is read against are "
            "pre-registered; measuring first and deciding the rule afterwards is the thing "
            "that file exists to prevent."
        )

    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    falsification = prereg["max_seq_len_falsification"]
    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR), local_files_only=True)

    corpus_path = REPO / split["corpus_path"]
    print(f"corpus: {corpus_path}")
    corpus = longmemeval.load(corpus_path)

    turns = [t.text for s in corpus.sessions for t in s.turns]
    queries = [c.question for c in corpus.cases]
    print(f"tokenizing {len(turns):,} turns and {len(queries):,} queries ...")

    turn_lengths = token_lengths(tokenizer, turns)
    query_lengths = token_lengths(tokenizer, queries)

    turn_stats = describe(turn_lengths)
    query_stats = describe(query_lengths)

    rate_128 = turn_stats["truncation_rate"]["128"]
    band, action = verdict(rate_128)

    # The pre-registered adjustment, evaluated but NOT applied here. Applying a parameter change
    # from inside the script that measures it is how a measurement quietly becomes a decision.
    adjustment = None
    if rate_128 > 0.25:
        chosen = next(
            (limit for limit in (192, 256) if turn_stats["truncation_rate"][str(limit)] <= 0.10),
            256,
        )
        adjustment = {
            "required": True,
            "new_max_seq_len": chosen,
            "its_truncation_rate": turn_stats["truncation_rate"][str(chosen)],
            "note": (
                "Determined by the pre-registered rule, not chosen here. Apply it deliberately "
                "in the Rust constant and re-run the engine gate: a longer sequence costs "
                "throughput, and the pre-registration says the ENGINE is re-decided rather "
                "than the length lowered back."
            ),
        }

    result = {
        "_what": (
            "Truncation rate at MAX_SEQ_LEN over LongMemEval-S (cleaned), measured before the "
            "fit and before any quality number exists."
        ),
        "_pre_registered_rule": falsification,
        "corpus": corpus.name,
        "corpus_sha256": split["corpus_sha256"],
        "tokenizer": "BertTokenizer from the pinned models/all-MiniLM-L6-v2",
        "turns": turn_stats,
        "queries": query_stats,
        "measured_at_128": {
            "truncation_rate": rate_128,
            "tokens_lost_fraction": turn_stats["tokens_lost_fraction"]["128"],
            "verdict": band,
            "action": action,
        },
        "adjustment": adjustment,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"turns:   n={turn_stats['n']:,}  mean={turn_stats['mean']}  max={turn_stats['max']}")
    print(f"         percentiles {turn_stats['percentiles']}")
    for limit in CANDIDATES:
        print(
            f"         > {limit:3d} tokens: {turn_stats['truncation_rate'][str(limit)]:.4f} of turns, "
            f"{turn_stats['tokens_lost_fraction'][str(limit)]:.4f} of all tokens lost"
        )
    print(f"queries: n={query_stats['n']:,}  mean={query_stats['mean']}  max={query_stats['max']}")
    print()
    print(f"PRE-REGISTERED VERDICT at 128: {band}")
    print(f"  {action}")
    if adjustment:
        print(f"  -> the rule selects MAX_SEQ_LEN = {adjustment['new_max_seq_len']}")
    print(f"\nwrote {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
