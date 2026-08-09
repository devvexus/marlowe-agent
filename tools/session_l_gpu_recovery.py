"""GPU recovery: is determinism recoverable, does the delta reorder, and what falls back to CPU?

Registered in `runs/session-l/PREREGISTRATION-gpu-amendment.json` BEFORE any cell ran. The
amended acceptance:

  GATE 1  GPU-to-GPU BYTE-IDENTITY within the provider -- the bar, and possibly recoverable
  GATE 2  cross-provider RANKING EQUIVALENCE against CPU -- the top-10 order, not the bytes
  GATE 3  identify the ops in the 13.6% of nodes running on CPU

**Gate 2 is the one that can still stop this.** A logit delta that never reorders a slate is a
different fact from one that does. If the two providers disagree about what to RETRIEVE, no amount
of speed makes them one system -- that is a report-and-stop outcome, not a tolerance.

Three quantities the original spike did not produce, because max |delta| answers a narrower
question than it appears to:

  the DISTRIBUTION of |delta|, not its maximum -- is 0.0021 typical or the tail?
  how many slates REORDER, and how many change TOP-1
  whether held-out R@1 moves by even one case
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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))


def _add_torch_cuda_libs():
    """torch bundles cuBLAS 12 and cuDNN 9; ORT just cannot find them. Session I's finding.

    Must run BEFORE `import onnxruntime` -- `add_dll_directory` only affects later loads.
    """
    import glob
    try:
        import torch
    except ImportError:
        return {"added": False}
    lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    present = {n: bool(glob.glob(os.path.join(lib, n + "*.dll")))
               for n in ("cublasLt64_12", "cudnn64_9", "cudart64_12")}
    try:
        os.add_dll_directory(lib)
        return {"added": True, "torch_lib": lib, "libraries_present": present}
    except (AttributeError, OSError):
        return {"added": False, "torch_lib": lib, "libraries_present": present}


from session_j_models import MODELS_DIR, manifest, sha256_file  # noqa: E402

SHIPPED = "ms-marco-MiniLM-L-2-v2-ft-session-j"
SLATES = REPO / "runs" / "session-m0c" / "slates-{split}.json"
OUT = REPO / "runs" / "session-l" / "gpu-recovery.json"
MAX_SEQ_LEN = 256
RERANK_BUDGET = 10

# The determinism sweep. Named in the registration before any of it ran; nondeterministic kernel
# selection and atomic reductions are the usual causes, so the knobs that bear on both are swept.
SWEEP = [
    ("default", {}),
    ("heuristic", {"cudnn_conv_algo_search": "HEURISTIC"}),
    ("algo_default", {"cudnn_conv_algo_search": "DEFAULT"}),
    ("heuristic+copy+arena", {
        "cudnn_conv_algo_search": "HEURISTIC",
        "do_copy_in_default_stream": "1",
        "arena_extend_strategy": "kSameAsRequested",
    }),
]


def build(provider, options, profile_dir, tag):
    import onnxruntime as ort

    directory = MODELS_DIR / SHIPPED
    model_file = directory / "model.onnx"
    entry = next(m for m in manifest()["models"] if m["name"] == SHIPPED)
    if sha256_file(model_file) != entry["digests"]["model.onnx"]:
        raise SystemExit("digest mismatch on the shipped graph")

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    opts.enable_profiling = True
    profile_dir.mkdir(parents=True, exist_ok=True)
    opts.profile_file_prefix = str(profile_dir / f"rec_{tag}")

    providers = [(provider, options)] if options else [provider]
    session = ort.InferenceSession(str(model_file), opts, providers=providers)
    registered = session.get_providers()
    if provider not in registered:
        raise SystemExit(f"VOID: requested {provider}, registered {registered}")
    return session, registered


def placement_by_op(profile_path: Path):
    """Node placement AND the op types that fell back. get_providers() sees none of this."""
    events = json.loads(profile_path.read_text(encoding="utf-8"))
    by_provider: Counter = Counter()
    cpu_ops: Counter = Counter()
    for e in events:
        if e.get("cat") != "Node":
            continue
        args = e.get("args") or {}
        ep = args.get("provider")
        if not ep:
            continue
        by_provider[ep] += 1
        if "CPU" in ep:
            cpu_ops[args.get("op_name", "?")] += 1
    return by_provider, cpu_ops


def encode_all(records, tokenizer):
    tokenizer.no_truncation(); tokenizer.no_padding()
    tokenizer.enable_truncation(max_length=MAX_SEQ_LEN)
    tokenizer.enable_padding(length=MAX_SEQ_LEN)
    blocks, golds = [], []
    for r in records:
        texts = r["texts"][:RERANK_BUDGET]
        if len(texts) != RERANK_BUDGET:
            continue
        encs = [tokenizer.encode(r["question"], t) for t in texts]
        blocks.append({
            "input_ids": np.array([e.ids for e in encs], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encs], dtype=np.int64),
            "token_type_ids": np.array([e.type_ids for e in encs], dtype=np.int64),
        })
        golds.append(np.array(r["gold"][:RERANK_BUDGET], dtype=bool))
    return blocks, golds


def score_all(session, blocks, names, batched=True):
    per_slate, timings = [], []
    for b in blocks[:3]:                                   # warm-up, untimed
        session.run(None, {k: v for k, v in b.items() if k in names})
    for b in blocks:
        f = {k: v for k, v in b.items() if k in names}
        t0 = time.perf_counter()
        out = np.asarray(session.run(None, f)[0]).reshape(-1)
        timings.append((time.perf_counter() - t0) * 1000.0)
        per_slate.append(out)
    return per_slate, timings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    libs = _add_torch_cuda_libs()
    print(f"CUDA libs from torch: {libs.get('added')} {libs.get('libraries_present')}")

    from tokenizers import Tokenizer
    import onnxruntime as ort

    records = json.loads(Path(str(SLATES).format(split="heldout")).read_text(encoding="utf-8"))["records"]
    tokenizer = Tokenizer.from_file(str(MODELS_DIR / SHIPPED / "tokenizer.json"))
    blocks, golds = encode_all(records, tokenizer)
    profile_dir = REPO / "runs" / "session-l" / "ort-profiles"

    probe = ort.InferenceSession(str(MODELS_DIR / SHIPPED / "model.onnx"),
                                 providers=["CPUExecutionProvider"])
    names = {i.name for i in probe.get_inputs()}
    del probe
    print(f"onnxruntime {ort.__version__}   slates {len(blocks)}\n")

    # ---- CPU reference ------------------------------------------------------------------------
    cpu_session, _ = build("CPUExecutionProvider", {}, profile_dir, "cpu")
    cpu_slates, cpu_ms = score_all(cpu_session, blocks, names)
    cpu_prof = Path(cpu_session.end_profiling())
    cpu_flat = np.concatenate(cpu_slates)
    print(f"CPU reference   p50 {np.median(cpu_ms):7.3f} ms/slate")

    # ---- GATE 1: is GPU-to-GPU determinism recoverable? ---------------------------------------
    sweep_results = []
    for tag, options in SWEEP:
        runs, times = [], []
        for i in range(args.repeats):
            s, _ = build("CUDAExecutionProvider", options, profile_dir, f"{tag}_{i}")
            slates_out, ms = score_all(s, blocks, names)
            by_provider, cpu_ops = placement_by_op(Path(s.end_profiling()))
            runs.append(np.concatenate(slates_out))
            times.append(float(np.median(ms)))
        identical = all(np.array_equal(runs[0], r) for r in runs[1:])
        spread = float(max(np.abs(r - runs[0]).max() for r in runs[1:])) if len(runs) > 1 else 0.0
        total_nodes = sum(by_provider.values())
        cpu_nodes = sum(v for k, v in by_provider.items() if "CPU" in k)
        sweep_results.append({
            "options": options or "(provider defaults)",
            "runs": args.repeats,
            "gpu_to_gpu_bit_identical": bool(identical),
            "max_run_to_run_delta": spread,
            "p50_ms_per_slate": round(float(np.median(times)), 3),
            "node_placement": dict(by_provider),
            "cpu_fallback_fraction": round(cpu_nodes / total_nodes, 4) if total_nodes else None,
            "cpu_fallback_ops": dict(cpu_ops.most_common()),
        })
        print(f"  {tag:<22} repeatable={identical}  run-to-run max delta {spread:.9f}  "
              f"p50 {np.median(times):6.3f} ms  cpu-nodes {cpu_nodes}/{total_nodes}")

    best = next((s for s in sweep_results if s["gpu_to_gpu_bit_identical"]), None)
    reference = best or sweep_results[0]

    # ---- GATE 2: ranking equivalence, which is what actually decides retrieval ------------------
    gpu_session, _ = build(
        "CUDAExecutionProvider",
        reference["options"] if isinstance(reference["options"], dict) else {},
        profile_dir, "rank")
    gpu_slates, _ = score_all(gpu_session, blocks, names)
    gpu_session.end_profiling()

    deltas = np.abs(np.concatenate(gpu_slates) - cpu_flat)
    reorder = top1 = 0
    cpu_hits = gpu_hits = 0
    for cpu_s, gpu_s, gold in zip(cpu_slates, gpu_slates, golds):
        c_order = np.argsort(-cpu_s, kind="stable")
        g_order = np.argsort(-gpu_s, kind="stable")
        if not np.array_equal(c_order, g_order):
            reorder += 1
        if c_order[0] != g_order[0]:
            top1 += 1
        cpu_hits += int(gold[c_order[0]])
        gpu_hits += int(gold[g_order[0]])

    n = len(cpu_slates)
    ranking_equivalent = (reorder == 0)
    r_at_1 = {"cpu": round(cpu_hits / n, 4), "gpu": round(gpu_hits / n, 4),
              "cases_moved": abs(cpu_hits - gpu_hits)}

    if not ranking_equivalent and r_at_1["cpu"] != r_at_1["gpu"]:
        verdict = ("REPORT AND STOP -- ranking equivalence FAILS and R@1 moves. The two providers "
                   "disagree about what to retrieve; speed does not reconcile that.")
    elif not ranking_equivalent:
        verdict = ("RANKING REORDERS but R@1 is unchanged. This is the distinction the amended "
                   "acceptance was written against and it needs the human's read.")
    else:
        verdict = "RANKING EQUIVALENT -- top-10 order matches CPU on every slate."

    report = {
        "_registration": "runs/session-l/PREREGISTRATION-gpu-amendment.json",
        "onnxruntime": ort.__version__,
        "cuda_library_search_path": libs,
        "slates": n,
        "cpu_p50_ms_per_slate": round(float(np.median(cpu_ms)), 3),
        "gate_1_gpu_to_gpu_determinism": sweep_results,
        "gate_1_recovered": bool(best is not None),
        "gate_2_ranking_equivalence": {
            "top10_order_matches_cpu_on_every_slate": ranking_equivalent,
            "slates_reordered": reorder,
            "slates_with_changed_top1": top1,
            "r_at_1": r_at_1,
        },
        "cross_provider_delta_distribution": {
            "note": "the ORIGINAL spike reported only the MAX. This is the distribution, which is "
                    "the question 'is 0.0021 typical or the tail' actually asks.",
            "median": float(np.median(deltas)),
            "p95": float(np.percentile(deltas, 95)),
            "p99": float(np.percentile(deltas, 99)),
            "max": float(deltas.max()),
            "exactly_zero_fraction": float((deltas == 0).mean()),
        },
        "gate_3_cpu_fallback_ops": reference["cpu_fallback_ops"],
        "verdict": verdict,
        "cpu_stays": "the fallback, shipped wherever no GPU exists. Two paths, both measured.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    d = report["cross_provider_delta_distribution"]
    print(f"\ncross-provider |delta|: median {d['median']:.9f}  p95 {d['p95']:.9f}  max {d['max']:.9f}")
    print(f"                        exactly zero on {d['exactly_zero_fraction']:.2%} of pairs")
    print(f"ranking: {reorder}/{n} slates reordered, {top1} changed top-1")
    print(f"R@1: cpu {r_at_1['cpu']}  gpu {r_at_1['gpu']}  ({r_at_1['cases_moved']} cases moved)")
    print(f"CPU-fallback ops: {reference['cpu_fallback_ops']}")
    print(f"\nVERDICT: {verdict}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
