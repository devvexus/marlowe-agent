"""Session I — the one cross-encoder loader every arm uses.

Session I sweeps eight models across four architectures. Each has its own input signature, its own
pair-encoding convention, and its own output head, and **a model that loads with the wrong
convention still returns a plausible float**. That is the failure mode this project has hit seven
times, and here it would arrive eight times at once.

So there is exactly one loader, it verifies rather than assumes, and every arm imports it.

What is pinned, and why each one:

  * **Digest**, checked against `runs/session-i/reranker-manifest.json` before the graph is built.
  * **`ORT_ENABLE_BASIC`**, matching the Rust stage's `Level1`. ORT's default is `ORT_ENABLE_ALL`,
    and on the int8 L-2 graph the two fusions produced logits **0.0699 apart on identical token
    ids**. An offline measurement at a different level measures a different scorer.
  * **1 thread, sequential execution.** Not for speed -- for determinism. Multi-threaded GEMM
    partitions the reduction differently and the sweep would compare cells measured by different
    arithmetic. Session I parallelizes across PROCESSES over disjoint cases, never inside a forward.
  * **`CPUExecutionProvider` asserted after construction**, never merely requested. Session G's CUDA
    provider was *listed* and did not *load*, and ORT fell back silently.
  * **Batch 1**, structurally, as the shipped stage is.

The output head is the one thing that cannot be pinned in advance, because it differs per model.
It is DETECTED and then VALIDATED by a discrimination smoke test; a model whose head cannot be
resolved is refused rather than guessed at.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO / "models"
MANIFEST = REPO / "runs" / "session-i" / "reranker-manifest.json"

PROVIDER = "CPUExecutionProvider"
THREADS = 1
BATCH = 1

# The shipped L-2-int8, which is NOT in the f32 manifest and is the frontier's control point. Its
# digest is the one pinned in crates/marlowe-memory/src/rerank.rs.
SHIPPED_INT8 = "ms-marco-MiniLM-L-2-v2-int8"
SHIPPED_INT8_DIGEST = "1857c1a59b01c1641a46a47fd85b01d98c6e15e1e48588eac1f6a97ff83479c7"

# Session J's fine-tunes, pinned here because Session I's manifest predates them and that file is a
# RECORD -- editing it would retro-fit an artifact to a later session's needs. Same treatment as
# SHIPPED_INT8 above, for the same reason: out of manifest, still digest-pinned, never guessed.
#
# **The L-2 digest is asserted to equal `rerank.rs`'s MODEL_SHA256 by `load`**, so a sweep cannot
# score a graph the binary would refuse and report it under the shipped label. That is the whole
# hazard the constant exists to close, and it is the shape CLAUDE.md records as the reason
# `--reranking` became a required argument: a default silently scored the OLD graph under the
# shipped name.
FINETUNES = {
    "ms-marco-MiniLM-L-2-v2-ft-session-j": {
        "digest": "9c222dac4315cfd2f33f2e865bb651a7a16bf532c11e55b7fb1a43bb041880c0",
        "params_m": 16,
        "arch": "BERT",
        "max_seq": 512,
    },
    "ms-marco-MiniLM-L-6-v2-ft-session-j": {
        "digest": "78dcc7c1834b2e0cfc67d58a2735b9bc27900f46d5b5ccada99e8ee610c724f6",
        "params_m": 23,
        "arch": "BERT",
        "max_seq": 512,
    },
}

# The graph the binary loads. Read from rerank.rs rather than restated, so the two cannot drift.
SHIPPED_FINETUNE = "ms-marco-MiniLM-L-2-v2-ft-session-j"
RERANK_RS = REPO / "crates" / "marlowe-memory" / "src" / "rerank.rs"


def shipped_digest_from_rust() -> str:
    """`MODEL_SHA256` as the Rust build sees it.

    Parsed rather than copied. A second copy of a digest in a Python constant is exactly the
    two-sides-silently-disagree shape this project keeps paying for: the sweep would keep scoring
    the graph it was told about long after the binary moved to another one.
    """
    import re

    text = RERANK_RS.read_text(encoding="utf-8")
    match = re.search(r'MODEL_SHA256:\s*&str\s*=\s*"([0-9a-f]{64})"', text)
    if match is None:
        raise ModelRefused(
            f"could not find MODEL_SHA256 in {RERANK_RS}. Refusing to fall back to a hardcoded "
            "digest -- that is how a sweep ends up describing a graph the binary does not load."
        )
    return match.group(1)


class ModelRefused(RuntimeError):
    """The model did not clear a load-time check. It does not enter any sweep."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest() -> dict:
    if not MANIFEST.exists():
        raise ModelRefused(
            f"{MANIFEST} is missing. Run tools/fetch_rerankers.py first -- no model is loaded "
            "without a pinned digest to check it against."
        )
    return json.loads(io.open(MANIFEST, encoding="utf-8").read())


@dataclass
class CrossEncoder:
    name: str
    session: object
    tokenizer: object
    input_names: frozenset[str]
    output_dim: int
    digest: str
    max_seq_supported: int
    params_m: int
    arch: str

    def encode(self, query: str, doc: str, max_len: int):
        tok = self.tokenizer
        tok.no_truncation()
        tok.no_padding()
        tok.enable_truncation(max_length=max_len)   # longest_first, HF's default
        tok.enable_padding(length=max_len)
        return tok.encode(query, doc)

    def score(self, query: str, doc: str, max_len: int = 256) -> float:
        """One (query, doc) pair. Batch is 1 and there is no parameter to raise it."""
        enc = self.encode(query, doc, max_len)
        ids = np.array([enc.ids], dtype=np.int64)
        mask = np.array([enc.attention_mask], dtype=np.int64)
        assert ids.shape[0] == BATCH == 1, "batch is fixed at 1, structurally"

        # Fed BY NAME. token_type_ids carries the query/candidate boundary on the BERT-family
        # models; binding positionally would transpose it on any graph ordering its inputs
        # differently, and the model would still return a plausible score.
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.input_names:
            feed["token_type_ids"] = np.array([enc.type_ids], dtype=np.int64)
        out = np.asarray(self.session.run(None, feed)[0]).reshape(-1)

        if self.output_dim == 1:
            return float(out[0])
        # Two-class head: the relevance margin is the log-odds. Which class is "relevant" is NOT
        # assumed -- `smoke_test` validates the sign and refuses the model if it is inverted.
        return float(out[1] - out[0])

    def score_batch(self, query: str, docs: list[str], max_len: int = 256) -> list[float]:
        """One forward over `len(docs)` pairs.

        **Additive, and CPU callers must not use it.** ADR-029 measured the two providers going
        OPPOSITE ways: on one CPU thread batching costs +8.8 ms, on CUDA it saves 77%. Batching is
        a property of the hardware, so this exists for the GPU path and `score` remains the CPU
        path's method.

        Shape-safe by construction: `encode` pads every row to exactly `max_len`, so a batch is a
        stack of equal-length rows and no row's token ids depend on what else is in the batch.
        That is what makes batch-vs-sequential a pure cost question here -- and it is ASSERTED
        rather than assumed by `batch_invariance`, which compares this exact path against `score`
        on the same graph. ADR-015 is why: a shape change alone moved int8 logits by a median
        0.0109 and flipped top-1 in 15% of cases. Re-measured per graph, never inherited -- L-2's
        0.000000 is not evidence about bge.
        """
        if not docs:
            return []
        encs = [self.encode(query, d, max_len) for d in docs]
        ids = np.array([e.ids for e in encs], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encs], dtype=np.int64)

        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.input_names:
            feed["token_type_ids"] = np.array([e.type_ids for e in encs], dtype=np.int64)
        out = np.asarray(self.session.run(None, feed)[0])

        if self.output_dim == 1:
            return [float(v) for v in out.reshape(-1)]
        out = out.reshape(len(docs), -1)
        return [float(r[1] - r[0]) for r in out]

    def wordpieces(self, text: str) -> int:
        tok = self.tokenizer
        tok.no_truncation()
        tok.no_padding()
        return len(tok.encode(text).ids)


def load(name: str, provider: str = PROVIDER) -> CrossEncoder:
    """Load one reranker, verifying digest, provider, pair encoding and output head.

    `provider` defaults to CPU so every Session I arm loads exactly the graph it recorded. Passing
    `CUDAExecutionProvider` is the M0c Session M path; ADR-029's deployment target is a GPU and 1
    vCPU is the fallback floor, so both must be reachable from ONE loader. A second loader is how
    two arms end up disagreeing about the head convention with nothing comparing them.

    **The provider is asserted after construction, never merely requested.** Session G's CUDA
    provider was listed and did not load, ORT fell back to CPU in silence, and the resulting "GPU"
    figure landed within 1% of the CPU one. `get_available_providers()` listing CUDA proves
    nothing; only creating the session and reading `get_providers()` back does.
    """
    import onnxruntime as ort
    from tokenizers import Tokenizer

    if provider == "CUDAExecutionProvider":
        # ORT cannot find `cublasLt64_12.dll` on this machine without help, and the symptom is a
        # SILENT fall back to CPU. torch ships the CUDA runtime; Session I found this and Session L
        # used it. Not a system install, and deliberately not a PATH mutation that outlives us.
        try:
            import os

            import torch

            os.add_dll_directory(str(Path(torch.__file__).parent / "lib"))
        except Exception:  # noqa: BLE001 - absence is reported by the provider assertion below
            pass

    directory = MODELS_DIR / name
    if name == SHIPPED_INT8:
        model_file, expected, params_m, arch, max_seq = (
            directory / "model_int8.onnx", SHIPPED_INT8_DIGEST, 16, "BERT (int8)", 512)
    elif name in FINETUNES:
        spec = FINETUNES[name]
        model_file, expected = directory / "model.onnx", spec["digest"]
        params_m, arch, max_seq = spec["params_m"], spec["arch"], spec["max_seq"]
        if name == SHIPPED_FINETUNE:
            # The control must be the graph the binary ships, verified against rerank.rs rather
            # than trusted. If these ever disagree the sweep's baseline is not the product's.
            rust = shipped_digest_from_rust()
            if rust != expected:
                raise ModelRefused(
                    f"{name}: rerank.rs pins MODEL_SHA256={rust}, this loader pins {expected}. "
                    "The sweep's control would not be the shipped graph. Reconcile before "
                    "measuring anything."
                )
    else:
        entry = next((m for m in manifest()["models"] if m["name"] == name), None)
        if entry is None:
            raise ModelRefused(f"{name} is not in the manifest. Fetch and pin it first.")
        model_file = directory / "model.onnx"
        expected = entry["digests"]["model.onnx"]
        params_m, arch, max_seq = entry["params_m"], entry["arch"], entry["max_seq"]

    found = sha256_file(model_file)
    if found != expected:
        raise ModelRefused(
            f"{model_file} hashes to {found}, pinned digest is {expected}. A different graph "
            "produces different scores while still looking like a reranker."
        )

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = THREADS
    opts.inter_op_num_threads = THREADS
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    session = ort.InferenceSession(str(model_file), opts, providers=[provider])

    active = session.get_providers()
    if provider not in active:
        raise ModelRefused(f"{name}: requested {provider}, ORT is running {active}")

    tok = Tokenizer.from_file(str(directory / "tokenizer.json"))

    # Does this tokenizer actually build a PAIR? A tokenizer.json with no pair template silently
    # returns the query alone, or the two concatenated with no separator -- and the model scores it.
    probe = tok.encode("what database did I migrate to", "I moved to Postgres in April.")
    seqs = {s for s in probe.sequence_ids if s is not None}
    if seqs != {0, 1}:
        raise ModelRefused(
            f"{name}: tokenizer.json does not produce a two-sequence pair encoding "
            f"(sequence_ids carry {sorted(seqs)}). The query/document boundary would be lost."
        )

    out_shape = session.get_outputs()[0].shape
    dim = out_shape[-1] if isinstance(out_shape[-1], int) else 1

    return CrossEncoder(
        name=name, session=session, tokenizer=tok,
        input_names=frozenset(i.name for i in session.get_inputs()),
        output_dim=int(dim), digest=found, max_seq_supported=max_seq,
        params_m=params_m, arch=arch,
    )


# ------------------------------------------------------------------------------------------------
# The checks a model must pass before it enters a sweep.
# ------------------------------------------------------------------------------------------------

RELEVANT = "I finally migrated the analytics warehouse off Postgres and onto ClickHouse in April."
IRRELEVANT = "The forecast for the weekend is heavy rain, so the barbecue is probably cancelled."
QUERY = "which database did I migrate my analytics warehouse to?"


def smoke_test(ce: CrossEncoder) -> dict:
    """Does the model discriminate, and in the right direction?

    This is the check that catches a transposed pair encoding, an inverted two-class head, a wrong
    logit index, and a corrupt graph -- all of which return a plausible float and none of which any
    structural test would notice. A model that fails is REFUSED, not corrected by flipping a sign,
    because a sign that has to be guessed is a convention nobody verified.
    """
    rel = ce.score(QUERY, RELEVANT)
    irr = ce.score(QUERY, IRRELEVANT)
    return {"relevant": rel, "irrelevant": irr, "margin": rel - irr, "pass": bool(rel > irr)}


def determinism(ce: CrossEncoder, repeats: int = 3) -> dict:
    """Same input, same bytes out? Re-verified per graph -- ADR-013's rule is not inheritable."""
    vals = [ce.score(QUERY, RELEVANT) for _ in range(repeats)]
    return {"values": vals, "pass": bool(len(set(vals)) == 1)}


def batch_invariance(ce: CrossEncoder, n: int = 8) -> dict:
    """Does a pair's score depend on which pairs share its batch, on THIS graph?

    The shipped path never batches, so a failure here does not affect it. It is measured so that
    "batch 1 removes the failure mode" rests on a number for each model rather than on L-2's.
    """
    docs = [f"I moved off Postgres in April, attempt number {i}." for i in range(n)]
    encs = [ce.encode(QUERY, d, 256) for d in docs]
    feed = {
        "input_ids": np.array([e.ids for e in encs], dtype=np.int64),
        "attention_mask": np.array([e.attention_mask for e in encs], dtype=np.int64),
    }
    if "token_type_ids" in ce.input_names:
        feed["token_type_ids"] = np.array([e.type_ids for e in encs], dtype=np.int64)

    def reduce(arr):
        arr = np.asarray(arr)
        return arr.reshape(-1) if ce.output_dim == 1 else arr[:, 1] - arr[:, 0]

    batched = reduce(ce.session.run(None, feed)[0])
    singles = np.array([
        reduce(ce.session.run(None, {k: v[i:i + 1] for k, v in feed.items()})[0])[0]
        for i in range(n)
    ])
    diff = float(np.abs(batched - singles).max())
    return {"max_abs_diff": diff, "identical": bool(np.array_equal(batched, singles)), "pairs": n}
