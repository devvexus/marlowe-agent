"""Extractive SQuAD-v2 span readers — the single loader, gated before use.

    python tools/readers.py            # gate all three and print the table

One loader, importable by every arm, for the reason `session_i_rerankers.py` gives: several models
across two architectures, each with its own input signature and pair convention, and **a model
loaded with the wrong convention still returns a plausible float**.

## Why a reader at all

The reranker's failure mode is discriminating a turn that RESTATES THE QUESTION'S TOPIC from one
that CONTAINS THE ANSWER. Nine cross-encoders from 16M to 278M failed to separate them, and the
head probe measured the ceiling on any rank-1/rank-2 tie-break at **+0.1135 R@1**.

A SQuAD-v2 span reader asks precisely the missing question. It is **discriminative** — it points at
(start, end) offsets and generates nothing.

## THE HEAD, and why it is the whole gate

These graphs expose `start_logits` and `end_logits` and **nothing else**. There is no separate
no-answer output: SQuAD v2 encodes "unanswerable" as the span collapsing onto position 0, the
CLS/BOS token. So the answerability signal is a DIFFERENCE:

    score = max_{i<=j, i,j in passage} (start[i] + end[j])  -  (start[0] + end[0])

That is the standard SQuAD-v2 null-threshold decision, and it is exactly our discriminator: *how
much better is the best answer span in this passage than declaring there is no answer.*

**Two ways to get this wrong, both of which return a plausible number:**

* **Not masking to the passage.** The span must be searched over the CANDIDATE's tokens only. Search
  the whole sequence and the model can "answer" by pointing at the question, which scores every
  candidate alike and destroys the discrimination.
* **Feeding positionally.** `mobilebert` is BERT-family and takes `token_type_ids`; the two RoBERTa
  models do not have them at all and carry the question/passage boundary in the tokenizer's pair
  template instead. Binding by position would transpose the boundary on one family and the model
  would still return floats.

Both are checked below rather than assumed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO / "models"

PROVIDER_CPU = "CPUExecutionProvider"
PROVIDER_CUDA = "CUDAExecutionProvider"

# Scope. `bert-large-uncased-wwm-squad2` was fetched and EXCLUDED: its download stalled at 591 MB
# with a `.part` file. Excluded on availability, NOT refused on merit -- recorded so it is not
# silently absent from a frontier that reports three points.
READERS = ("mobilebert-uncased-squad-v2", "tinyroberta-squad2", "roberta-base-squad2")

MAX_SEQ = 256  # the shipped rerank sequence length, so the reader sees what the reranker saw


class ReaderRefused(RuntimeError):
    """A model that fails a gate is refused by name, never silently downgraded."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Reader:
    name: str
    session: object
    tokenizer: object
    input_names: frozenset[str]
    digest: str
    provider: str

    def _encode(self, question: str, passage: str, max_len: int):
        tok = self.tokenizer
        tok.no_truncation()
        tok.no_padding()
        tok.enable_truncation(max_length=max_len)
        tok.enable_padding(length=max_len)
        return tok.encode(question, passage)

    def score(self, question: str, passage: str, max_len: int = MAX_SEQ) -> dict:
        """Answerability score for one (question, passage) pair.

        Returns the span score, the null score, and their difference. The DIFFERENCE is the
        quantity to rank on; the two halves are returned so a degenerate reading (every passage
        scoring identically because the span search escaped into the question) is visible.
        """
        enc = self._encode(question, passage, max_len)
        feed = {
            "input_ids": np.array([enc.ids], dtype=np.int64),
            "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
        }
        # BY NAME. mobilebert needs token_type_ids; the RoBERTa pair carries the boundary in the
        # template and has no such input. Positional binding would transpose one of the two.
        if "token_type_ids" in self.input_names:
            feed["token_type_ids"] = np.array([enc.type_ids], dtype=np.int64)

        out = self.session.run(None, feed)
        start = np.asarray(out[0]).reshape(-1).astype(np.float64)
        end = np.asarray(out[1]).reshape(-1).astype(np.float64)

        # The null (no-answer) score is the span collapsed onto position 0.
        null = float(start[0] + end[0])

        # **Passage tokens only.** sequence_ids marks question=0, passage=1, specials=None.
        seq = enc.sequence_ids
        idx = [i for i, s in enumerate(seq) if s == 1 and enc.attention_mask[i] == 1]
        if not idx:
            return {"span": null, "null": null, "score": 0.0, "n_passage_tokens": 0}

        lo, hi = idx[0], idx[-1]
        s_win, e_win = start[lo : hi + 1], end[lo : hi + 1]
        # Best i<=j without the O(n^2) scan: for each j, the best start at or before j.
        best_start_so_far = np.maximum.accumulate(s_win)
        span = float(np.max(best_start_so_far + e_win))
        return {
            "span": span,
            "null": null,
            "score": span - null,
            "n_passage_tokens": len(idx),
        }


def load(name: str, provider: str = PROVIDER_CPU) -> Reader:
    import onnxruntime as ort
    from tokenizers import Tokenizer

    directory = MODELS_DIR / name
    model_file = directory / "model.onnx"
    if not model_file.exists():
        raise ReaderRefused(f"{model_file} does not exist")

    if provider == PROVIDER_CUDA:
        # ORT cannot find cublasLt without help and the symptom is a SILENT fall back to CPU.
        try:
            import os

            import torch

            os.add_dll_directory(str(Path(torch.__file__).parent / "lib"))
        except Exception:  # noqa: BLE001 - the provider assertion below is the real check
            pass

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    # Matching the Rust rerank stage's Level1. ORT defaults to ORT_ENABLE_ALL and the two fusions
    # produced logits 0.0699 apart on identical token ids on one int8 graph.
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    session = ort.InferenceSession(str(model_file), opts, providers=[provider])

    # ASSERTED after construction, never merely requested. A listed-but-not-created CUDA provider
    # already produced one VOID result in this project.
    active = session.get_providers()
    if provider not in active:
        raise ReaderRefused(f"{name}: requested {provider}, ORT is running {active}")

    outs = [o.name for o in session.get_outputs()]
    if outs[:2] != ["start_logits", "end_logits"]:
        raise ReaderRefused(
            f"{name}: outputs are {outs}; expected start_logits then end_logits. The head "
            "convention is not what this loader decodes and a wrong reading returns plausible "
            "floats."
        )

    tok = Tokenizer.from_file(str(directory / "tokenizer.json"))
    probe = tok.encode("what database did I migrate to", "I moved to Postgres in April.")
    seqs = {s for s in probe.sequence_ids if s is not None}
    if seqs != {0, 1}:
        raise ReaderRefused(
            f"{name}: tokenizer.json does not produce a two-sequence pair encoding (sequence_ids "
            f"carry {sorted(seqs)}). The question/passage boundary would be lost, and the span "
            "search could not be masked to the passage."
        )

    return Reader(
        name=name,
        session=session,
        tokenizer=tok,
        input_names=frozenset(i.name for i in session.get_inputs()),
        digest=sha256_file(model_file),
        provider=provider,
    )


# ---------------------------------------------------------------------------------------------
# The gate. A model that fails is refused by name.
# ---------------------------------------------------------------------------------------------

QUESTION = "which database did I migrate my analytics warehouse to?"
ANSWERING = "I finally migrated the analytics warehouse off Postgres and onto ClickHouse in April."
# Deliberately ON TOPIC and answer-free -- this is the exact distractor shape that beats us, not a
# random sentence. A reader that separates a weather report from an answer proves nothing.
TOPICAL_NO_ANSWER = (
    "I've been thinking about migrating my analytics warehouse to something faster, and I keep "
    "going back and forth about which database would suit the workload best."
)


def smoke_test(r: Reader) -> dict:
    """Does it discriminate ANSWER-BEARING from ON-TOPIC-BUT-ANSWER-FREE, in the right direction?

    The check that catches an inverted head, an escaped span search, and a transposed pair
    encoding -- all of which return plausible floats and none of which any other check here sees.
    """
    a = r.score(QUESTION, ANSWERING)
    b = r.score(QUESTION, TOPICAL_NO_ANSWER)
    return {
        "answering": round(a["score"], 4),
        "topical_no_answer": round(b["score"], 4),
        "margin": round(a["score"] - b["score"], 4),
        "pass": bool(a["score"] > b["score"]),
        "_detail": {"answering": a, "topical_no_answer": b},
    }


def determinism(r: Reader, repeats: int = 3) -> dict:
    vals = [r.score(QUESTION, ANSWERING)["score"] for _ in range(repeats)]
    return {"values": vals, "pass": bool(len(set(vals)) == 1)}


def padding_invariance(r: Reader) -> dict:
    """ADR-015's check: same content, different padded length. Never inherited across graphs."""
    vals = {n: r.score(QUESTION, ANSWERING, n)["score"] for n in (256, 320, 384)}
    spread = max(vals.values()) - min(vals.values())
    return {"by_length": {str(k): round(v, 6) for k, v in vals.items()},
            "max_abs_diff": round(spread, 9), "identical": bool(spread == 0.0)}


def main() -> int:
    import time

    results = {}
    for name in READERS:
        try:
            r = load(name)
        except ReaderRefused as e:
            print(f"{name:<34} REFUSED — {e}")
            results[name] = {"refused": str(e)}
            continue
        smoke = smoke_test(r)
        det = determinism(r)
        pad = padding_invariance(r)
        t0 = time.perf_counter()
        for _ in range(20):
            r.score(QUESTION, ANSWERING)
        ms = (time.perf_counter() - t0) / 20 * 1000
        results[name] = {
            "digest": r.digest, "provider": r.provider, "inputs": sorted(r.input_names),
            "smoke": smoke, "determinism": det, "padding_invariance": pad,
            "cpu_ms_per_pair": round(ms, 2),
            "admitted": bool(smoke["pass"] and det["pass"]),
        }
        print(
            f"{name:<34} smoke {'PASS' if smoke['pass'] else 'FAIL'} "
            f"(ans {smoke['answering']:+8.3f} vs topical {smoke['topical_no_answer']:+8.3f}, "
            f"margin {smoke['margin']:+7.3f})  det {det['pass']}  "
            f"pad d{pad['max_abs_diff']:.6f}  {ms:6.1f} ms/pair"
        )

    out = REPO / "runs" / "session-m0c-m" / "reader-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "_what": "SQuAD-v2 span readers, gated. Head = best passage span minus null span.",
                "_max_seq": MAX_SEQ,
                "_excluded": {
                    "bert-large-uncased-wwm-squad2": (
                        "download stalled at 591 MB (model.onnx.part). EXCLUDED ON AVAILABILITY, "
                        "not refused on merit."
                    )
                },
                "results": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
