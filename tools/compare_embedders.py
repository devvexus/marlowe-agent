"""Decide the dense cue's truncation problem with a measurement, not an argument.

`runs/session-c/truncation.json` found that **38.64% of the corpus's word pieces never reach the
embedder** at MAX_SEQ_LEN=256, and truncation lands preferentially on long assistant turns —
which are frequently where the gold evidence is. Left alone, Number 2 would substantially be a
measurement of truncation rather than of dense retrieval.

Two ways out, and this script measures both against the status quo:

  chunk    keep all-MiniLM-L6-v2, split a long turn into overlapping windows, score the turn as
           the MAX over its windows. More compute, same 384 dimensions, same RAM footprint.
  swap     replace the model with a long-context one (jina-embeddings-v2-small-en: 512 dims,
           4 layers, 8192-token ALiBi window). No truncation at all, 512 dims instead of 384.

**The metric is gold-turn recall@k under pure cosine ranking.** No gate, no fitted weights, no
calibration — just "does the embedder rank the gold turn near the top of its session". That
isolates the embedder from everything downstream, which is exactly the question being asked.

**Fit split only. The held-out split is not touched.** Choosing between candidate designs on the
fit split is what a fit split is *for*; doing it on held-out data would spend the split this
session's headline number depends on. Stated here because the distinction is the whole basis on
which this measurement is legitimate.

    python tools/compare_embedders.py --cases 60
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.datasets import longmemeval  # noqa: E402

SPLIT_PATH = REPO / "tools" / "split.json"
OUT_PATH = REPO / "runs" / "session-c" / "embedder-comparison.json"

MINILM = REPO / "models" / "all-MiniLM-L6-v2"
JINA = REPO / "models" / "jina-embeddings-v2-small-en"

KS = (1, 5, 10, 20, 50)


class Embedder:
    """One candidate configuration, reduced to `encode(texts) -> unit vectors`."""

    def __init__(self, name: str, model_dir: Path, max_len: int, window: int | None, stride: int):
        import onnxruntime as ort
        from transformers import AutoTokenizer

        self.name = name
        self.max_len = max_len
        self.window = window
        self.stride = stride
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)

        options = ort.SessionOptions()
        self.session = ort.InferenceSession(
            str(model_dir / "model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.dim = self.session.get_outputs()[0].shape[-1]
        if not isinstance(self.dim, int):
            self.dim = 512 if "jina" in name else 384

    def _forward(self, ids: list[int]) -> np.ndarray:
        arr = np.asarray([ids], dtype=np.int64)
        mask = np.ones_like(arr)
        feed = {"input_ids": arr, "attention_mask": mask}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(arr)
        hidden = self.session.run(None, {k: v for k, v in feed.items() if k in self.inputs})[0]
        pooled = hidden[0].mean(axis=0)
        norm = np.linalg.norm(pooled)
        return (pooled / norm if norm > 0 else pooled).astype(np.float32)

    def _pieces(self, text: str) -> list[int]:
        """Content word pieces, without [CLS]/[SEP]."""
        return self.tokenizer(text, add_special_tokens=False, truncation=False)["input_ids"]

    def encode_one(self, text: str) -> np.ndarray:
        cls = self.tokenizer.cls_token_id
        sep = self.tokenizer.sep_token_id
        pieces = self._pieces(text)

        if self.window is None:
            # Truncate, or (for the long-context model) simply fit.
            pieces = pieces[: self.max_len - 2]
            return self._forward([cls] + pieces + [sep])

        # Chunk-and-pool. MAX over windows, never mean: relevance to a long answer usually
        # lives in one passage, and averaging dilutes it toward the turn's overall topic.
        body = self.window - 2
        if len(pieces) <= body:
            return self._forward([cls] + pieces + [sep])
        vectors = []
        start = 0
        while start < len(pieces):
            chunk = pieces[start : start + body]
            vectors.append(self._forward([cls] + chunk + [sep]))
            if start + body >= len(pieces):
                break
            start += self.stride
        return np.stack(vectors)  # caller maxes over rows

    def encode_many(self, texts: list[str]) -> list[np.ndarray]:
        return [np.atleast_2d(self.encode_one(t)) for t in texts]


def score_case(embedder: Embedder, question: str, turns: list[str]) -> np.ndarray:
    """Cosine of the query against each turn; a chunked turn scores as its best window."""
    query = embedder.encode_one(question)
    query = query if query.ndim == 1 else query[0]
    scores = np.zeros(len(turns), dtype=np.float32)
    for index, text in enumerate(turns):
        vectors = np.atleast_2d(embedder.encode_one(text))
        scores[index] = float(np.max(vectors @ query))
    return scores


def recall_at_k(scores: np.ndarray, gold: set[int]) -> dict[int, float]:
    order = np.argsort(-scores, kind="stable")
    out = {}
    for k in KS:
        top = set(order[:k].tolist())
        out[k] = len(top & gold) / len(gold) if gold else 0.0
    return out


def throughput(embedder: Embedder, texts: list[str], seconds: float = 20.0) -> float:
    """Texts per second, single call at a time. Compared against the 25/s/core gate."""
    started = time.perf_counter()
    done = 0
    for text in texts:
        embedder.encode_one(text)
        done += 1
        if time.perf_counter() - started > seconds:
            break
    return done / (time.perf_counter() - started)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=60)
    args = parser.parse_args()

    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_map = corpus.gold_map()

    fit_ids = set(split["fit"])
    cases = [
        c
        for c in corpus.cases
        if c.query_id in fit_ids and not c.is_abstention and gold_map.get(c.query_id)
    ]
    # Deterministic, stratified by category so no single category dominates the verdict.
    by_category: dict[str, list] = {}
    for case in sorted(cases, key=lambda c: c.query_id):
        by_category.setdefault(case.category, []).append(case)
    chosen = []
    index = 0
    while len(chosen) < args.cases:
        added = False
        for category in sorted(by_category):
            if index < len(by_category[category]) and len(chosen) < args.cases:
                chosen.append(by_category[category][index])
                added = True
        if not added:
            break
        index += 1
    print(f"fit-split cases: {len(chosen)} (of {len(cases)} eligible), stratified by category")

    configs = [
        ("minilm-truncate-128", MINILM, 128, None, 0),
        ("minilm-truncate-256", MINILM, 256, None, 0),
        ("minilm-chunk-256/192", MINILM, 256, 256, 192),
        ("jina-small-full-8192", JINA, 8192, None, 0),
    ]

    sample = json.loads((REPO / "runs/session-c/spike-sample.json").read_text(encoding="utf-8"))
    results = {}

    for name, model_dir, max_len, window, stride in configs:
        if not (model_dir / "model.onnx").exists():
            print(f"{name}: model missing at {model_dir}, skipping")
            continue
        print(f"\n=== {name} ===")
        embedder = Embedder(name, model_dir, max_len, window, stride)

        rate = throughput(embedder, sample["turns"])
        print(f"  throughput (single call): {rate:.1f} texts/s")

        totals = {k: [] for k in KS}
        started = time.time()
        for number, case in enumerate(chosen, 1):
            session = corpus.session(case.session_id)
            turns = [t.text for t in session.turns]
            gold_ids = gold_map.get(case.query_id, frozenset())
            gold = {i for i, t in enumerate(session.turns) if t.turn_id in gold_ids}
            if not gold:
                continue
            scores = score_case(embedder, case.question, turns)
            for k, value in recall_at_k(scores, gold).items():
                totals[k].append(value)
            if number % 10 == 0:
                print(f"    {number}/{len(chosen)} cases, {time.time()-started:.0f}s")

        recalls = {k: round(float(np.mean(v)), 4) for k, v in totals.items()}
        results[name] = {
            "dimensions": embedder.dim,
            "max_len": max_len,
            "window": window,
            "stride": stride,
            "texts_per_sec_single_call": round(rate, 1),
            "recall_at_k": recalls,
            "cases": len(totals[1]),
        }
        print(f"  recall@k: {recalls}")

    OUT_PATH.write_text(
        json.dumps(
            {
                "_what": (
                    "Gold-turn recall@k under pure cosine ranking, no gate and no fitted "
                    "weights. Decides how the dense cue handles truncation."
                ),
                "_split": (
                    "FIT SPLIT ONLY. Choosing between candidate designs on the fit split is "
                    "what a fit split is for; the held-out split is untouched."
                ),
                "_ram_note": (
                    "ADR-003's hot array is float32 x dimensions. 1 GB holds 651,041 entries "
                    "at 384 dims, 488,281 at 512, 325,520 at 768."
                ),
                "cases": len(chosen),
                "configs": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
