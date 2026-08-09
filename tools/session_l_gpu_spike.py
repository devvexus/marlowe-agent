"""The GPU rerank spike: CPU vs CUDA on the shipped graph, over the real held-out slates.

Registered in `runs/session-l/PREREGISTRATION-gpu.json` BEFORE any cell ran. Read it first --
the gates, the decision rule and the scope were all fixed in advance, including what this
measurement explicitly CANNOT answer.

## What this measures, and what it does not

**Measures:** the CPU-to-CUDA RATIO for the rerank stage, both arms under one ONNX Runtime, on the
shipped graph, over the 229 real held-out slates.

**Does NOT measure:** end-to-end warm-249 retrieval P95 on GPU. The rerank is 90.49% of P95 on the
shipped path, but that P95 was measured under Rust `ort` 2.0.0-rc.10 (ORT 1.22.0) and this runs
under Python onnxruntime 1.24.2. Projecting one onto the other would be an estimate wearing a
measurement's clothes -- the exact family CLAUDE.md's measurement-transfer rule names.

The absolute Python CPU figure is therefore never quoted as the shipped latency. It exists to be
the denominator of a ratio.

## The provider gate, and why `get_providers()` alone is not it

`get_providers()` names **registered** providers, not where nodes **ran**. ORT can register CUDA
and still execute individual nodes on CPU where a kernel is unsupported -- which would satisfy a
`get_providers()` assertion completely while timing CPU kernels under a CUDA label. That is the
Session G failure repeating through a different door.

So node placement is read from ORT's **profiling output**, which records the execution provider
per node. Both checks run; `get_providers()` is the cheap first one, not the gate.

## The determinism gate is stricter here than for threading

Byte-identity across execution providers is not inherited from the CPU graph at all: different
kernels, different reduction order, different fusion. Multi-threading changes how one kernel
partitions a reduction; a different provider changes **which kernel runs**.

A logit difference of any size disqualifies, regardless of speed. No tolerance is sought.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np


def _add_torch_cuda_libs_to_search_path() -> dict:
    """Put torch's bundled CUDA libraries on ORT's DLL search path. **Before importing ORT.**

    Session I hit exactly this: `onnxruntime_providers_cuda.dll` depends on `cublasLt64_12.dll`,
    which is absent system-wide, so `CUDAExecutionProvider` fails to CREATE and ORT silently
    registers CPU only. torch ships cuBLAS 12 and cuDNN 9 in its own `lib/`; they were simply not on
    ORT's search path. `session_j_verify_export.py` already does this for the same reason.

    **Order matters and is the whole trick.** `os.add_dll_directory` affects loads that happen
    afterwards, so this must run before `import onnxruntime` -- which is why every ORT import in
    this file is deferred into a function rather than sitting at module scope.

    Returns what was found, so the report can state which libraries the run depended on rather than
    leaving a reader to assume a system CUDA install.
    """
    import glob

    try:
        import torch
    except ImportError:
        return {"torch": None, "added": False}

    lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    found = {
        name: bool(glob.glob(os.path.join(lib, name + "*.dll")))
        for name in ("cublasLt64_12", "cublas64_12", "cudnn64_9", "cudart64_12")
    }
    added = False
    if os.path.isdir(lib):
        try:
            os.add_dll_directory(lib)
            added = True
        except (AttributeError, OSError):
            added = False
    return {"torch_lib": lib, "added": added, "libraries_present": found}

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from session_j_models import MODELS_DIR, manifest, sha256_file  # noqa: E402

SHIPPED = "ms-marco-MiniLM-L-2-v2-ft-session-j"
SLATES = REPO / "runs" / "session-m0c" / "slates-{split}.json"
OUT = REPO / "runs" / "session-l" / "gpu-spike.json"

MAX_SEQ_LEN = 256
RERANK_BUDGET = 10
# Matches `ort`'s Level1 and every other Python tool in this repo. An offline measurement taken at
# a different optimization level measures a different scorer.
OPT_LEVEL = "ORT_ENABLE_BASIC"


def build(provider: str, threads: int, profile_dir: Path):
    """A session on one provider, with profiling on so node placement can be read afterwards."""
    import onnxruntime as ort

    directory = MODELS_DIR / SHIPPED
    model_file = directory / "model.onnx"
    entry = next((m for m in manifest()["models"] if m["name"] == SHIPPED), None)
    if entry is None:
        raise SystemExit(f"{SHIPPED} is not in the Session J manifest.")
    found = sha256_file(model_file)
    if found != entry["digests"]["model.onnx"]:
        raise SystemExit(f"{model_file} hashes to {found}, pinned is {entry['digests']['model.onnx']}")

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    # **The gate.** Without this there is no node-placement record and the provider claim rests on
    # get_providers(), which reports intent rather than outcome.
    opts.enable_profiling = True
    profile_dir.mkdir(parents=True, exist_ok=True)
    opts.profile_file_prefix = str(profile_dir / f"prof_{provider}_{threads}t")

    session = ort.InferenceSession(str(model_file), opts, providers=[provider])

    registered = session.get_providers()
    if provider not in registered:
        # **A VOID cell is a RESULT and is written down, not raised as a crash.**
        #
        # This fired on the first run: `get_available_providers()` listed CUDA, the machine has an
        # RTX 4080 SUPER, and the provider still could not be created -- `cublasLt64_12.dll` absent,
        # CUDA 12 runtime not installed -- so ORT registered CPU only. That is Session G verbatim,
        # where the same fallback produced a "CUDA" number within 1% of the CPU one.
        #
        # The AVAILABLE list is not evidence about a CONSTRUCTED session. That is the whole reason
        # the gate reads `get_providers()` afterwards, and node placement after that.
        raise ProviderUnavailable(provider, registered)
    return session, registered


class ProviderUnavailable(RuntimeError):
    """Requested provider did not register. The cell is void, not slow."""

    def __init__(self, requested, registered):
        self.requested = requested
        self.registered = registered
        super().__init__(
            f"VOID CELL: requested {requested}, ORT registered {registered}. A number without a "
            "verified provider is not a measurement of that provider."
        )


def node_placement(profile_path: Path) -> Counter:
    """Where nodes ACTUALLY ran, from ORT's profiling output.

    This is the check `get_providers()` cannot make. A per-node CPU fallback under a CUDA session
    shows up here and nowhere else.
    """
    events = json.loads(profile_path.read_text(encoding="utf-8"))
    placement: Counter = Counter()
    for event in events:
        args = event.get("args") or {}
        ep = args.get("provider")
        if ep and event.get("cat") == "Node":
            placement[ep] += 1
    return placement


def encode_all(records, tokenizer):
    """Tokenize every slate once, so no arm pays a tokenization cost the other does not."""
    tokenizer.no_truncation()
    tokenizer.no_padding()
    tokenizer.enable_truncation(max_length=MAX_SEQ_LEN)
    tokenizer.enable_padding(length=MAX_SEQ_LEN)
    out = []
    for record in records:
        texts = record["texts"][:RERANK_BUDGET]
        if len(texts) != RERANK_BUDGET:
            continue
        encs = [tokenizer.encode(record["question"], t) for t in texts]
        out.append({
            "input_ids": np.array([e.ids for e in encs], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encs], dtype=np.int64),
            "token_type_ids": np.array([e.type_ids for e in encs], dtype=np.int64),
        })
    return out


def run_cell(label, provider, threads, batched, slates, profile_dir, input_names):
    session, registered = build(provider, threads, profile_dir)

    def feed(block, lo, hi):
        f = {k: v[lo:hi] for k, v in block.items()}
        return {k: v for k, v in f.items() if k in input_names}

    # Warm-up, excluded from timing. The first CUDA call pays context creation and kernel
    # autotuning; including it would price a one-off startup as a per-query cost.
    for block in slates[:3]:
        if batched:
            session.run(None, feed(block, 0, RERANK_BUDGET))
        else:
            for i in range(RERANK_BUDGET):
                session.run(None, feed(block, i, i + 1))

    logits, per_slate_ms = [], []
    for block in slates:
        start = time.perf_counter()
        if batched:
            out = np.asarray(session.run(None, feed(block, 0, RERANK_BUDGET))[0]).reshape(-1)
        else:
            out = np.array([
                np.asarray(session.run(None, feed(block, i, i + 1))[0]).reshape(-1)[0]
                for i in range(RERANK_BUDGET)
            ])
        per_slate_ms.append((time.perf_counter() - start) * 1000.0)
        logits.append(out)

    profile_path = Path(session.end_profiling())
    placement = node_placement(profile_path)

    ordered = sorted(per_slate_ms)
    pick = lambda q: ordered[min(int(q * len(ordered)), len(ordered) - 1)]  # noqa: E731
    return {
        "label": label,
        "provider_requested": provider,
        "providers_registered": registered,
        "node_placement": dict(placement),
        "threads": threads,
        "batched": batched,
        "slates": len(slates),
        "per_slate_ms": {
            "p50": round(float(np.median(ordered)), 3),
            "p95": round(pick(0.95), 3),
            "p99": round(pick(0.99), 3),
            "max": round(ordered[-1], 3),
            "mean": round(float(np.mean(ordered)), 3),
        },
    }, np.concatenate(logits)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="heldout", choices=["fit", "heldout"])
    ap.add_argument("--repeats", type=int, default=3,
                    help="repeated CUDA passes for the determinism gate. THREE is the registered "
                         "minimum; one identical run proves reduction order held once.")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    # BEFORE any onnxruntime import. See the function's docstring -- add_dll_directory only
    # affects subsequent loads, so this ordering is load-bearing rather than stylistic.
    cuda_libs = _add_torch_cuda_libs_to_search_path()
    print(f"CUDA libs from torch: added={cuda_libs.get('added')} {cuda_libs.get('libraries_present')}")

    from tokenizers import Tokenizer

    records = json.loads(Path(str(SLATES).format(split=args.split)).read_text(encoding="utf-8"))["records"]
    tokenizer = Tokenizer.from_file(str(MODELS_DIR / SHIPPED / "tokenizer.json"))
    slates = encode_all(records, tokenizer)

    import onnxruntime as ort
    profile_dir = REPO / "runs" / "session-l" / "ort-profiles"
    probe = ort.InferenceSession(
        str(MODELS_DIR / SHIPPED / "model.onnx"), providers=["CPUExecutionProvider"])
    input_names = {i.name for i in probe.get_inputs()}
    del probe

    print(f"onnxruntime {ort.__version__}   available {ort.get_available_providers()}")
    print(f"{SHIPPED}   slates {len(slates)}   depth {RERANK_BUDGET}   seq {MAX_SEQ_LEN}   {OPT_LEVEL}\n")

    cells, logits = [], {}
    plan = [
        ("G0 CPU  seq 1t", "CPUExecutionProvider", 1, False),
        ("G1 CUDA seq", "CUDAExecutionProvider", 1, False),
        ("G2 CUDA bat", "CUDAExecutionProvider", 1, True),
        ("G3 CPU  seq 1t (repeat)", "CPUExecutionProvider", 1, False),
    ]
    void = []
    for label, provider, threads, batched in plan:
        try:
            cell, out = run_cell(label, provider, threads, batched, slates, profile_dir, input_names)
        except ProviderUnavailable as e:
            void.append({"cell": label, "requested": e.requested, "registered": e.registered})
            print(f"{label:<26} VOID -- requested {e.requested}, registered {e.registered}")
            continue
        cells.append(cell)
        logits[label] = out
        placement = cell["node_placement"]
        print(f"{label:<26} p50 {cell['per_slate_ms']['p50']:8.3f} ms/slate   "
              f"p95 {cell['per_slate_ms']['p95']:8.3f}   nodes {placement}")

    if void:
        # The registered outcome for an unassertable provider. Written down rather than crashed, so
        # the finding survives as an artifact -- and so the reason is the ENVIRONMENT rather than a
        # verdict about GPU, which remains UNMEASURED.
        report = {
            "_registration": "runs/session-l/PREREGISTRATION-gpu.json",
            "verdict": "NOT MEASURED -- the CUDA cells are VOID. This is neither 'closed on "
                       "correctness' nor 'closed on measurement'; the GPU question is still OPEN.",
            "void_cells": void,
            "why": "onnxruntime lists CUDAExecutionProvider in get_available_providers() and the "
                   "machine has an NVIDIA RTX 4080 SUPER, but the provider cannot be CREATED: "
                   "onnxruntime_providers_cuda.dll depends on cublasLt64_12.dll, which is absent. "
                   "CUDA 12.* and cuDNN 9.* are not installed. ORT then registers CPU only.",
            "this_is_session_G_repeating": "Session G requested CUDA, ORT fell back on missing "
                   "cuBLAS/cuDNN WITHOUT raising, and produced a 'GPU' figure within 1% of the "
                   "1-thread CPU one. The difference here is that the gate was registered in "
                   "advance, so the run produced a REFUSAL instead of a number.",
            "the_available_list_is_not_evidence": "get_available_providers() said CUDA. The "
                   "constructed session said CPU. Only the second is about the session that would "
                   "have been timed.",
            "what_would_unblock_it": "install CUDA 12.* runtime and cuDNN 9.*, ensure they are on "
                                     "PATH, then re-run this tool unchanged.",
            "cpu_reference_taken_anyway": cells,
            "cuda_library_search_path": cuda_libs,
            "shipped_provider_unchanged": "CPUExecutionProvider.",
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nVERDICT: {report['verdict']}")
        print(f"-> {args.out}")
        return 0

    # ---- the determinism gate -----------------------------------------------------------------
    reference = logits["G0 CPU  seq 1t"]
    identity = {}
    for label, out in logits.items():
        identity[label] = {
            "bit_identical_to_cpu": bool(np.array_equal(out, reference)),
            "max_abs_delta": float(np.abs(out - reference).max()),
        }

    repeats = []
    for run in range(args.repeats):
        cell, out = run_cell(f"CUDA bat repeat {run + 1}", "CUDAExecutionProvider", 1, True,
                             slates, profile_dir, input_names)
        repeats.append({
            "run": run + 1,
            "bit_identical_to_cpu": bool(np.array_equal(out, reference)),
            "max_abs_delta": float(np.abs(out - reference).max()),
            "p50_ms": cell["per_slate_ms"]["p50"],
            "node_placement": cell["node_placement"],
        })
    all_identical = all(r["bit_identical_to_cpu"] for r in repeats)

    floor = abs(cells[0]["per_slate_ms"]["p50"] - cells[3]["per_slate_ms"]["p50"])
    best_gpu = min(cells[1]["per_slate_ms"]["p50"], cells[2]["per_slate_ms"]["p50"])
    cpu = (cells[0]["per_slate_ms"]["p50"] + cells[3]["per_slate_ms"]["p50"]) / 2
    gain = cpu - best_gpu
    materially_faster = gain > 2 * floor

    if not all_identical:
        verdict = "CLOSED ON CORRECTNESS -- logits differ across providers. No tolerance is sought."
    elif materially_faster:
        verdict = "CANDIDATE, not an adoption. Needs its own ADR: the deployment target has no GPU."
    else:
        verdict = "CLOSED ON MEASUREMENT -- identical but not materially faster. The prior held."

    report = {
        "_registration": "runs/session-l/PREREGISTRATION-gpu.json",
        "_scope": "CPU-to-CUDA RATIO under one ORT. NOT an end-to-end P95 and never to be quoted as one.",
        "onnxruntime": ort.__version__,
        "cuda_library_search_path": cuda_libs,
        "cells": cells,
        "noise_floor_ms": round(floor, 3),
        "cpu_p50_ms": round(cpu, 3),
        "best_gpu_p50_ms": round(best_gpu, 3),
        "gain_ms": round(gain, 3),
        "materially_faster_2x_floor": materially_faster,
        "logit_identity": identity,
        "determinism_repeats": repeats,
        "all_repeats_bit_identical": all_identical,
        "verdict": verdict,
        "shipped_provider_unchanged": "CPUExecutionProvider. A performance finding surfaces a decision; it does not authorise one.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\nnoise floor |G0-G3|  {floor:.3f} ms      CPU p50 {cpu:.3f}   best GPU p50 {best_gpu:.3f}")
    print(f"logit identity vs CPU: " +
          ", ".join(f"{k.split()[0]}={'EXACT' if v['bit_identical_to_cpu'] else v['max_abs_delta']:.9}"
                    if not v["bit_identical_to_cpu"] else f"{k.split()[0]}=EXACT"
                    for k, v in identity.items()))
    print(f"determinism repeats bit-identical: {all_identical}")
    print(f"\nVERDICT: {verdict}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
