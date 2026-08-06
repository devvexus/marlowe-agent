"""Session G — a Python query embedder, and the registered gate that licenses using it.

Arms 2 and 3 change the *query*, so they cannot be computed from Session F's stored scores: a new
query text needs a new vector. That means a second implementation of the embedding path alongside
the Rust one, which is the pattern CLAUDE.md flags and that has produced five bugs in this project.

**The second-implementation surface is kept as small as it can be.** Session F's run left a 377 MB
embedding cache written by the Rust embedder, and every held-out question and turn text is in it,
keyed by `blake3(namespace || \\0 || text)`. So:

  * **document vectors are Rust's own**, read from that cache, never recomputed here;
  * only the **query** vector is computed in Python — which is exactly, and only, what arms 2 and 3
    change.

That also makes the gate far stronger than the pre-registration required. It registered "reproduce
the stored `dense_cosine` to 1e-4", a downstream check on a scalar. Because the cache holds Rust's
own vector for every unmodified question, this compares **the vectors themselves**, elementwise. A
query embedder that agrees on 512 components for 249 questions is not accidentally right.

The BM25 side is deliberately *not* reimplemented; see `reach_arm2_expansion.py` for how arm 2
avoids needing it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO / "models" / "jina-embeddings-v2-small-en"
CACHE_DIR = REPO / ".embedding-cache"
DIMENSIONS = 512
# `cue/dense/mod.rs`. Not a Python-side choice -- if these disagree with the Rust build the gate
# below is what fails, which is the point of having it.
MAX_SEQ_LEN = 8192


class RustEmbeddingCache:
    """Read-only view of the Rust embedder's content-addressed cache.

    The namespace is taken from the FILENAME rather than recomputed from model hashes. Recomputing
    it would mean re-deriving `CacheIdentity::namespace` in Python -- a second implementation of
    the very thing whose disagreement this module exists to detect -- and getting it subtly wrong
    would silently produce zero cache hits, which reads as "no data" rather than as a bug.
    """

    def __init__(self, directory: Path = CACHE_DIR):
        files = sorted(directory.glob("embeddings-*.bin"))
        if len(files) != 1:
            raise SystemExit(
                f"expected exactly one cache file in {directory}, found {len(files)}. "
                "Two identities means two embedder builds and the vectors are not comparable."
            )
        self.path = files[0]
        self.namespace = self.path.stem.removeprefix("embeddings-").encode("ascii")

        raw = self.path.read_bytes()
        record = 32 + DIMENSIONS * 4
        if len(raw) % record:
            raise SystemExit(
                f"{self.path} is not a whole number of {record}-byte records. The Rust loader "
                "treats this as a hard error and so does this one -- a truncated tail would make "
                "the cache's contents depend on how a previous process died."
            )
        n = len(raw) // record
        keys = np.frombuffer(raw, dtype=np.uint8).reshape(n, record)[:, :32]
        vecs = np.frombuffer(raw, dtype="<f4").reshape(n, record // 4)[:, 8:]
        self._index = {keys[i].tobytes(): i for i in range(n)}
        self._vectors = np.ascontiguousarray(vecs)

    def __len__(self) -> int:
        return len(self._index)

    def key(self, text: str) -> bytes:
        import blake3

        h = blake3.blake3()
        h.update(self.namespace)
        h.update(b"\0")
        h.update(text.encode("utf-8"))
        return h.digest()

    def get(self, text: str) -> np.ndarray | None:
        i = self._index.get(self.key(text))
        return None if i is None else self._vectors[i]


class JinaEmbedder:
    """jina-embeddings-v2-small-en, mean-pooled and L2-normalized, matching `dense/mod.rs`.

    Pooling accumulates in float64 and normalizes in float64 before casting down, because
    `mean_pool_and_normalize` does. Pooling in float32 changes the last few bits and would show up
    as a gate failure that looks like a tokenizer bug.
    """

    def __init__(self, providers: list[str] | None = None):
        import onnxruntime as ort
        from tokenizers import BertWordPieceTokenizer

        self.tok = BertWordPieceTokenizer(
            str(MODEL_DIR / "vocab.txt"), lowercase=True, strip_accents=True
        )
        self.tok.enable_truncation(max_length=MAX_SEQ_LEN)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(MODEL_DIR / "model.onnx"),
            sess_options=opts,
            providers=providers or ["CPUExecutionProvider"],
        )
        self.input_names = {i.name for i in self.session.get_inputs()}

    def embed(self, text: str) -> np.ndarray:
        ids = self.tok.encode(text).ids
        arr = np.asarray([ids], dtype=np.int64)
        feed = {"input_ids": arr}
        if "attention_mask" in self.input_names:
            feed["attention_mask"] = np.ones_like(arr)
        if "token_type_ids" in self.input_names:
            feed["token_type_ids"] = np.zeros_like(arr)
        hidden = self.session.run(None, feed)[0][0].astype(np.float64)
        pooled = hidden.sum(axis=0) / max(len(ids), 1)
        norm = float(np.sqrt((pooled * pooled).sum()))
        if norm == 0.0:
            return np.zeros(DIMENSIONS, dtype=np.float32)
        return (pooled / norm).astype(np.float32)


def gate(sample: int = 60) -> dict:
    """The registered reproduction gate, strengthened to an elementwise vector comparison.

    Returns a report; the caller decides what to do with a failure. Arms 2 and 3 must refuse to
    report a number if this does not pass.
    """
    import sys

    sys.path.insert(0, str(REPO / "tools"))
    from reach_pools import load_pools

    pools, _ = load_pools()
    cache = RustEmbeddingCache()
    embedder = JinaEmbedder()

    qids = sorted(pools)[:sample]
    max_abs = 0.0
    min_cos = 1.0
    missing = 0
    for qid in qids:
        rust = cache.get(pools[qid].question)
        if rust is None:
            missing += 1
            continue
        mine = embedder.embed(pools[qid].question)
        max_abs = max(max_abs, float(np.abs(rust - mine).max()))
        min_cos = min(min_cos, float(np.dot(rust, mine)))

    return {
        "_what": "Python query embedder vs the Rust embedder's own cached vectors.",
        "_stronger_than_registered": (
            "The pre-registration required reproducing the stored dense_cosine scalar to 1e-4. "
            "Because the cache holds Rust's vector for every unmodified question, this compares "
            "all 512 components directly."
        ),
        "questions_compared": len(qids) - missing,
        "questions_missing_from_cache": missing,
        "max_abs_component_diff": max_abs,
        "min_cosine_agreement": min_cos,
        "tolerance": {"max_abs_component_diff": 1e-4, "min_cosine_agreement": 0.9999},
        "pass": missing == 0 and max_abs <= 1e-4 and min_cos >= 0.9999,
    }


def main() -> int:
    report = gate()
    print("Reproduction gate -- Python query embedder vs Rust cached vectors\n")
    print(f"  questions compared         {report['questions_compared']}")
    print(f"  missing from cache         {report['questions_missing_from_cache']}")
    print(f"  max abs component diff     {report['max_abs_component_diff']:.3e}  "
          f"(tolerance 1e-4)")
    print(f"  min cosine agreement       {report['min_cosine_agreement']:.8f}  "
          f"(tolerance 0.9999)")
    print()
    if report["pass"]:
        print("GATE PASSED. Arms 2 and 3 may compute new query vectors in Python.")
        return 0
    print("GATE FAILED. Arms 2 and 3 report NOT MEASURED -- an unvalidated re-implementation")
    print("produces a number of exactly the right shape and nothing catches it being wrong.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
