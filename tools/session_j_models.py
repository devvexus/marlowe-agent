"""Session J — loading a model this session produced, under Session I's rules.

Session I's loader refuses anything absent from `runs/session-i/reranker-manifest.json`, and that
refusal is correct: no graph is scored without a pinned digest to check it against. A model
fine-tuned here is not in that manifest and **must not be added to it** — Session I's artifacts
describe what Session I fetched and pinned, and editing one so a later session's file passes its
own check would make the manifest a record of nothing.

So this module keeps a **separate** manifest for models produced in Session J, and enforces the
same rules against it: digest checked before the graph is built, `ORT_ENABLE_BASIC` matching the
Rust stage's `Level1`, one thread, sequential execution, batch 1, and the provider asserted after
construction rather than merely requested.

The `CrossEncoder` dataclass and every constant are imported from `session_i_rerankers`, not
restated. Two loaders that agreed by coincidence would be the same defect this project has now
recorded nine instances of.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from session_i_rerankers import (
    BATCH,
    MODELS_DIR,
    PROVIDER,
    THREADS,
    CrossEncoder,
    ModelRefused,
    sha256_file,
)

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "runs" / "session-j" / "finetuned-manifest.json"


def manifest() -> dict:
    if not MANIFEST.exists():
        raise ModelRefused(
            f"{MANIFEST} is missing. Run tools/session_j_finetune.py first — a model this session "
            "trained is still not loaded without a pinned digest."
        )
    return json.loads(io.open(MANIFEST, encoding="utf-8").read())


def record(name: str, model_path: Path, tokenizer_path: Path, meta: dict) -> None:
    """Pin a model this session produced. Called by the trainer immediately after export."""
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(io.open(MANIFEST, encoding="utf-8").read()) if MANIFEST.exists() else {"models": []}
    data["models"] = [m for m in data["models"] if m["name"] != name]
    data["models"].append({
        "name": name,
        "digests": {
            "model.onnx": sha256_file(model_path),
            "tokenizer.json": sha256_file(tokenizer_path),
        },
        **meta,
    })
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_finetuned(name: str) -> CrossEncoder:
    import onnxruntime as ort
    from tokenizers import Tokenizer

    entry = next((m for m in manifest()["models"] if m["name"] == name), None)
    if entry is None:
        raise ModelRefused(f"{name} is not in {MANIFEST.name}. Train and pin it first.")

    directory = MODELS_DIR / name
    model_file = directory / "model.onnx"
    found = sha256_file(model_file)
    expected = entry["digests"]["model.onnx"]
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
    session = ort.InferenceSession(str(model_file), opts, providers=[PROVIDER])

    active = session.get_providers()
    if PROVIDER not in active:
        raise ModelRefused(f"{name}: requested {PROVIDER}, ORT is running {active}")

    tok = Tokenizer.from_file(str(directory / "tokenizer.json"))
    probe = tok.encode("what database did I migrate to", "I moved to Postgres in April.")
    seqs = {s for s in probe.sequence_ids if s is not None}
    if seqs != {0, 1}:
        raise ModelRefused(
            f"{name}: tokenizer.json does not produce a two-sequence pair encoding "
            f"(sequence_ids carry {sorted(seqs)}). The query/document boundary would be lost."
        )

    out_shape = session.get_outputs()[0].shape
    dim = out_shape[-1] if isinstance(out_shape[-1], int) else 1
    assert BATCH == 1, "batch is fixed at 1, structurally"

    return CrossEncoder(
        name=name, session=session, tokenizer=tok,
        input_names=frozenset(i.name for i in session.get_inputs()),
        output_dim=int(dim), digest=found,
        max_seq_supported=int(entry.get("max_seq", 512)),
        params_m=int(entry.get("params_m", 0)), arch=str(entry.get("arch", "BERT")),
    )
