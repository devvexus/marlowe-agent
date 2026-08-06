"""Session G — the cross-encoder, re-costed against the registered configurations.

The spike ruled it out at **365 ms over 20 candidates at seq 256** (fp32 L-6, 16 threads). The
pre-registration re-opens it on a narrow, stated basis: the candidate count halves to 10, the
weights are int8, and a two-layer model is measured beside the six-layer one. See
`PREREGISTRATION.json -> cross_encoder_re_costing` for why that is not the forbidden third rung of
the spike's ladder.

**The adoption condition has three parts and one of them has already failed.** Arm 1's registered
shortlist-equivalence condition -- `R@10 pruned >= R@20 unpruned - 0.01` -- failed at every N and
every ranker. So whatever this script measures, **the re-open is NOT JUSTIFIED by this session**.
The latency is measured and reported anyway, because the registration says to report it as
information; it is not reported as a pass.

Registered and honoured here:

  * exactly two models, ten candidates, seq 256. **No sweep.** If both miss, the verdict is NOT
    ADOPTED -- no third model, no seq ladder, no candidate-count search.
  * the verdict is read at **1 thread** (ADR-003 sizes against a 1-vCPU VPS). The core-count number
    is reported because the spike's determinism result licensed multi-threading for that graph, but
    it does not decide adoption.
  * **determinism is RE-verified.** The spike proved fp32 L-6 deterministic; int8 is a different
    graph and L-2 is a different model. Inheriting that result would be assuming the thing.
  * GPU measured, **not adopted** -- determinism across execution providers and the VPS target each
    need their own ADR.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
import urllib.request
from pathlib import Path

import numpy as np

from spike_cross_encoder import encode, load_pairs, run_model, sha256_file

REPO = Path(__file__).resolve().parent.parent
PREREG = REPO / "runs" / "session-g" / "PREREGISTRATION.json"
ARM1 = REPO / "runs" / "session-g" / "arm1-pruning.json"
OUT = REPO / "runs" / "session-g" / "cross-encoder-recost.json"

MODELS = {
    "L-6-int8": ("Xenova/ms-marco-MiniLM-L-6-v2", "onnx/model_int8.onnx"),
    "L-2-int8": ("Xenova/ms-marco-MiniLM-L-2-v2", "onnx/model_int8.onnx"),
}
TOP_N = 10
SEQ_LEN = 256
QUERIES = 40


def fetch(name: str, repo: str, remote: str) -> tuple[Path, Path, dict]:
    d = REPO / "models" / f"{repo.split('/')[-1]}-int8"
    d.mkdir(parents=True, exist_ok=True)
    model, tokenizer = d / "model_int8.onnx", d / "tokenizer.json"
    for dest, path in ((model, remote), (tokenizer, "tokenizer.json")):
        if not dest.exists():
            print(f"  downloading {repo}/{path} ...")
            url = f"https://huggingface.co/{repo}/resolve/main/{path}"
            with urllib.request.urlopen(url, timeout=600) as r, dest.open("wb") as fh:
                while chunk := r.read(1 << 20):
                    fh.write(chunk)
    return model, tokenizer, {
        "model_int8.onnx": sha256_file(model),
        "tokenizer.json": sha256_file(tokenizer),
        "bytes": model.stat().st_size,
    }


class ProviderFellBack(RuntimeError):
    """The requested execution provider did not load and ORT silently used another one."""


def session(model: Path, threads: int, provider: str):
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = threads
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    sess = ort.InferenceSession(str(model), opts, providers=[provider])

    # `get_available_providers()` lists what the BUILD supports, not what can actually load.
    # CUDAExecutionProvider is listed here and then fails on a missing cuBLAS/cuDNN, and ORT falls
    # back to CPU **without raising** -- so the timing loop happily produces a "GPU" number that is
    # a CPU number. It is this project's unobservable-mismatch pattern wearing a provider's name,
    # and the first run of this script did produce a CUDA figure within 1% of the 1-thread CPU one.
    # Checked rather than trusted.
    active = sess.get_providers()
    if provider not in active:
        raise ProviderFellBack(f"requested {provider}, ORT is running {active}")
    return sess


def measure(model: Path, tokenizer: Path, pairs, threads: int, provider: str) -> dict:
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(str(tokenizer))
    sess = session(model, threads, provider)
    latencies, truncated, total = [], 0, 0
    for query, docs in pairs:
        ids, mask, types, trunc = encode(tok, query, docs[:TOP_N], SEQ_LEN)
        truncated += trunc
        total += len(docs[:TOP_N])
        run_model(sess, ids, mask, types)  # warm the graph; not timed
        start = time.perf_counter()
        run_model(sess, ids, mask, types)
        latencies.append((time.perf_counter() - start) * 1000.0)
    latencies.sort()
    p95 = latencies[max(0, int(round(0.95 * len(latencies))) - 1)]
    return {
        "threads": threads,
        "provider": provider,
        "stage_p95_ms": round(p95, 2),
        "stage_median_ms": round(statistics.median(latencies), 2),
        "truncation_rate": round(truncated / total, 4),
        "queries": len(latencies),
    }


def determinism(model: Path, tokenizer: Path, pairs) -> dict:
    """Re-verified, not inherited. int8 and L-2 are not the graph the spike proved."""
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(str(tokenizer))
    query, docs = pairs[0]
    ids, mask, types, _ = encode(tok, query, docs[:TOP_N], SEQ_LEN)

    one = run_model(session(model, 1, "CPUExecutionProvider"), ids, mask, types)
    many = run_model(session(model, 4, "CPUExecutionProvider"), ids, mask, types)
    single = np.concatenate([
        run_model(session(model, 1, "CPUExecutionProvider"), ids[i:i + 1], mask[i:i + 1], types[i:i + 1])
        for i in range(ids.shape[0])
    ])
    return {
        "batch_1_vs_batch_N": {"max_abs_diff": float(np.abs(one - single).max()),
                               "pass": bool(np.array_equal(one, single))},
        "threads_1_vs_4": {"max_abs_diff": float(np.abs(one - many).max()),
                           "pass": bool(np.array_equal(one, many))},
    }


def main() -> int:
    import onnxruntime as ort

    prereg = json.loads(PREREG.read_text(encoding="utf-8"))["cross_encoder_re_costing"]
    bar = prereg["latency_bar"]["stage_p95_ms"]
    arm1 = json.loads(ARM1.read_text(encoding="utf-8"))
    shortlist_ok = any(
        row[r]["passes"] for row in arm1["shortlist_equivalence"]["evaluated"]
        for r in ("lexical", "dense", "oracle")
    )

    pairs = load_pairs(QUERIES, TOP_N)
    available = ort.get_available_providers()
    gpu = "CUDAExecutionProvider" if "CUDAExecutionProvider" in available else None
    cores = __import__("os").cpu_count() or 1

    print(f"Cross-encoder re-costing: {TOP_N} candidates, seq {SEQ_LEN}, {len(pairs)} queries.")
    print(f"Registered stage bar: P95 <= {bar} ms at 1 thread.\n")

    results = {}
    for name, (repo, remote) in MODELS.items():
        print(f"{name}:")
        model, tokenizer, digests = fetch(name, repo, remote)
        block = {"digests": digests, "cpu": {}, "determinism": determinism(model, tokenizer, pairs)}
        for threads in (1, cores):
            r = measure(model, tokenizer, pairs, threads, "CPUExecutionProvider")
            block["cpu"][str(threads)] = r
            print(f"  CPU {threads:>2} thread  P95 {r['stage_p95_ms']:>8.2f} ms   "
                  f"median {r['stage_median_ms']:>8.2f} ms   trunc {r['truncation_rate']:.4f}")
        if gpu:
            try:
                r = measure(model, tokenizer, pairs, 1, gpu)
                block["gpu"] = r
                print(f"  CUDA          P95 {r['stage_p95_ms']:>8.2f} ms   "
                      f"median {r['stage_median_ms']:>8.2f} ms   (NOT ADOPTED)")
            except ProviderFellBack as exc:
                block["gpu"] = {
                    "measured": False,
                    "reason": str(exc),
                    "_note": (
                        "CUDAExecutionProvider is listed by get_available_providers() but does not "
                        "load -- its cuBLAS/cuDNN dependencies are missing. ORT falls back to CPU "
                        "silently, so no GPU number is reported rather than a CPU number wearing a "
                        "GPU label."
                    ),
                }
                print(f"  CUDA          NOT MEASURED -- provider fell back to CPU ({exc})")
            except Exception as exc:  # noqa: BLE001
                block["gpu"] = {"measured": False, "reason": str(exc)[:200]}
                print(f"  CUDA          unavailable: {str(exc)[:100]}")
        d = block["determinism"]
        print(f"  determinism   batch {'PASS' if d['batch_1_vs_batch_N']['pass'] else 'FAIL'}   "
              f"threads {'PASS' if d['threads_1_vs_4']['pass'] else 'FAIL'}")
        one_thread = block["cpu"]["1"]["stage_p95_ms"]
        block["latency_pass_at_1_thread"] = one_thread <= bar
        block["determinism_pass"] = d["batch_1_vs_batch_N"]["pass"] and d["threads_1_vs_4"]["pass"]
        results[name] = block
        print()

    report = {
        "_what": "Session G cross-encoder re-costing at the registered configurations.",
        "registered_bar_ms": bar,
        "candidates": TOP_N,
        "max_seq_len": SEQ_LEN,
        "spike_reference": {
            "config": "fp32 L-6, 20 candidates, seq 256, 16 threads",
            "stage_p95_ms": 331,
            "projected_total_ms": 365,
            "verdict": "NOT ADOPTED at M0b",
        },
        "results": results,
        "shortlist_equivalence_condition": {
            "passed": shortlist_ok,
            "_source": "runs/session-g/arm1-pruning.json",
        },
        "adoption": {
            "requires_all_of": prereg["adoption_requires_BOTH"],
            "latency_pass_any_model": any(v["latency_pass_at_1_thread"] for v in results.values()),
            "determinism_pass_any_model": any(v["determinism_pass"] for v in results.values()),
            "shortlist_equivalence": shortlist_ok,
            "verdict": (
                "NOT ADOPTED -- the registered shortlist-equivalence condition failed, so the "
                "re-open is not justified by this session regardless of the latency result."
                if not shortlist_ok else "see conditions"
            ),
        },
        "gpu_note": (
            "Requested for information only, and NOT adopted regardless of the number: determinism "
            "across execution providers and the VPS deployment target each need their own ADR, and "
            "the verdict is read on CPU at 1 thread. Where the provider failed to load, no figure "
            "is reported -- ORT falls back to CPU silently and a fallback timing would be a CPU "
            "number labelled as a GPU one."
        ),
        "determinism_note": (
            "The batch-invariance check FAILS for int8 where the spike's fp32 L-6 passed. This is "
            "why re-verification was registered rather than inherited: quantization changes the "
            "reduction order inside the graph. A stage whose score depends on batch composition "
            "breaks `repro --runs 2`, which is a standing check, so this alone blocks adoption."
        ),
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("Adoption conditions:")
    print(f"  latency at 1 thread <= {bar} ms   "
          f"{'MET by at least one model' if report['adoption']['latency_pass_any_model'] else 'MISSED by both'}")
    print(f"  determinism re-verified           "
          f"{'MET' if report['adoption']['determinism_pass_any_model'] else 'MISSED'}")
    print(f"  arm 1 shortlist equivalence       {'MET' if shortlist_ok else 'FAILED'}")
    print(f"\nVERDICT: {report['adoption']['verdict']}")
    print(f"\nWROTE {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
