"""Generate the cross-encoder reference fixture: HuggingFace's tokenization AND ONNX's logits.

The standing check this serves, from STATE.md:

> **A second implementation of a scored-path component must reproduce the first on unmodified
> input.**

Session H hand-rolls a BERT *pair* encoder in Rust so the cross-encoder can run without a Python
dependency in the retrieval path. That is a second implementation of a scored-path component, and
the rule applies. This file writes what the real `tokenizers` library and the real ONNX graph
produce, and `crates/marlowe-memory/tests/cross_encoder_reference.rs` demands Rust match.

**It is never regenerated to make that test pass.** If Rust disagrees, Rust is wrong until proven
otherwise -- the rule `eval/` lives under, applied one layer down.

The cases are chosen to cover where a plausible-but-wrong implementation diverges:

  * an ordinary short pair -- the case that would pass under any implementation
  * a long document with a short query -- ordinary truncation
  * a LONG QUERY with a long document -- where HuggingFace's `longest_first` strategy differs from
    the obvious "truncate the document to fit". An implementation that truncated only the document
    matches every other case here and fails this one.
  * a pair that fits exactly, and one that overflows by a single token
  * text carrying U+2028/U+2029 and accented characters, which `score_longmemeval.py` records as
    present in LongMemEval transcripts
  * a document containing a special-token literal, which must match as a literal
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO / "models" / "ms-marco-MiniLM-L-2-v2-int8"
OUT = REPO / "crates" / "marlowe-memory" / "tests" / "fixtures" / "cross-encoder-reference.json"
MAX_SEQ_LEN = 256

LONG = (
    "I moved the analytics warehouse off Postgres in April because the nightly ingest job kept "
    "timing out under load, and the migration took about three weeks including the backfill. "
)
CASES = [
    ("short pair", "what database did I migrate to", "I moved off Postgres in April."),
    ("empty document", "what did I say about postgres", ""),
    ("long document, short query", "postgres migration", LONG * 12),
    # The case that separates `longest_first` from "truncate the document".
    ("long query AND long document", LONG * 6, LONG * 6),
    ("long query, short document", LONG * 12, "Yes, in April."),
    ("unicode line separators", "café latté preference", "I prefer café latté every morning."),
    ("special literal in the document", "what is masked", "the value is [MASK] and [SEP] follows"),
    ("accents kept not stripped", "naïve résumé", "my naïve résumé was rejected"),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    from tokenizers import Tokenizer
    import onnxruntime as ort

    tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tok.enable_truncation(max_length=MAX_SEQ_LEN)
    tok.enable_padding(length=MAX_SEQ_LEN)

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    # PINNED, and not left at ORT's default. The Rust stage builds at Level1 (ORT_ENABLE_BASIC),
    # and the default is ORT_ENABLE_ALL -- which fuses the int8 graph differently and returns a
    # DIFFERENT LOGIT for identical token ids. Measured at 0.0699 on one fixture case, nearly
    # twice the 0.037 batch-invariance failure that blocked adoption in Session G. Two sides
    # silently disagreeing, seventh instance; see runs/session-h/RESULT.md.
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    sess = ort.InferenceSession(
        str(MODEL_DIR / "model_int8.onnx"), opts, providers=["CPUExecutionProvider"]
    )
    active = sess.get_providers()
    if "CPUExecutionProvider" not in active:
        raise SystemExit(f"provider fell back: {active}")

    rows = []
    for name, query, document in CASES:
        enc = tok.encode(query, document)
        ids = np.array([enc.ids], dtype=np.int64)
        mask = np.array([enc.attention_mask], dtype=np.int64)
        types = np.array([enc.type_ids], dtype=np.int64)
        assert ids.shape == (1, MAX_SEQ_LEN), ids.shape

        logit = float(
            np.asarray(
                sess.run(
                    None,
                    {"input_ids": ids, "attention_mask": mask, "token_type_ids": types},
                )[0]
            ).reshape(-1)[0]
        )

        # Did the pair overflow? Measured on the unpadded, untruncated encoding rather than
        # inferred from the padded one, where truncation and padding are indistinguishable.
        tok.no_truncation()
        tok.no_padding()
        raw = tok.encode(query, document)
        truncated = len(raw.ids) > MAX_SEQ_LEN
        tok.enable_truncation(max_length=MAX_SEQ_LEN)
        tok.enable_padding(length=MAX_SEQ_LEN)

        rows.append({
            "name": name,
            "query": query,
            "document": document,
            "input_ids": enc.ids,
            "attention_mask": enc.attention_mask,
            "token_type_ids": enc.type_ids,
            "truncated": truncated,
            "logit": logit,
            "unpadded_length": len(raw.ids),
        })
        print(f"  {name:32s} len {len(raw.ids):>5}  trunc {str(truncated):5s}  logit {logit:+.6f}")

    fixture = {
        "_what": (
            "HuggingFace tokenizers + ONNX Runtime reference for the cross-encoder pair encoder. "
            "Never regenerated to make the Rust test pass."
        ),
        "_generated_by": "tools/make_cross_encoder_fixtures.py",
        "model": "Xenova/ms-marco-MiniLM-L-2-v2 onnx/model_int8.onnx",
        "digests": {
            "model_int8.onnx": sha256_file(MODEL_DIR / "model_int8.onnx"),
            "tokenizer.json": sha256_file(MODEL_DIR / "tokenizer.json"),
        },
        "max_seq_len": MAX_SEQ_LEN,
        "batch": 1,
        "threads": 1,
        "provider": "CPUExecutionProvider",
        "cases": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    print(f"\nWROTE {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
