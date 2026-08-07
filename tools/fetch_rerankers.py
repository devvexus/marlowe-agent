"""Session I, Phase 1.1 — acquire the candidate rerankers, with integrity pinned.

Same two rules as `fetch_model.py`, for the same reasons, and one addition.

  * **Never vendored.** `models/` is gitignored.
  * **Fails on mismatch, never warns.** A silently-different reranker still scores, still passes
    every structural test, and only moves the number.
  * **The URL is pinned to a COMMIT, not to `main`.** `reach_cross_encoder.py` fetched L-2 and L-6
    from `resolve/main`; the bytes ended up pinned by digest, but the URL is not reproducible and a
    fresh clone can silently get different weights. Every revision below came from
    `probe_reranker_exports.py` and is recorded in `runs/session-i/reranker-export-probe.json`.

**Which ONNX variant, and why f32 for every model.**

`fetch_model.py` takes the unoptimized f32 export for the embedder, because an optimized variant
bakes some other tool's fusion choices into the file at a version nobody recorded. The same
argument applies here, and two more join it:

  1. **Quantization is a confound in a capacity sweep.** The shipped reranker is L-2 *int8*.
     Comparing it against a f32 bge-base would measure capacity and precision at once and report
     the sum as capacity. Holding precision constant across the ladder is what makes the arm-2
     result attributable.
  2. **f32 is the only variant all ten repositories publish.** BAAI and mixedbread ship
     `model.onnx` and one quantization; Xenova ships eight. f32 is the common denominator, so it
     is the only choice that does not vary the variant across the sweep.

The latency bar that bought int8 in Session G is lifted for Session I, so int8's reason for
existing is gone. **The shipped L-2-int8 stays as the control point on the frontier**, and fetching
L-2 f32 beside it yields a measurement nobody has taken: what int8 quantization costs in QUALITY.
Sessions G and H only ever measured int8's latency and its quality, never the gap to f32.

**Tiers, because scoring is the expensive half, not downloading.** Tier 1 is one architecture and
one training set at four depths, which is the cleanest possible capacity read. Tier 2 changes the
training data and the architecture. Tier 3 is only fetched if Tier 2 earns it.

    python tools/fetch_rerankers.py --tier 1 --tier 2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO / "models"


@dataclass(frozen=True)
class Reranker:
    name: str
    repo: str
    revision: str
    tier: int
    params_m: int
    """Approximate parameter count, in millions. Recorded for the cost axis of the frontier."""
    arch: str
    max_seq: int
    """The model's own positional limit. Arm 0 sweeps sequence length and cannot exceed this."""
    files: dict[str, str] = field(default_factory=dict)
    """remote path -> local filename."""
    digests: dict[str, str | None] = field(default_factory=dict)


def _std(extra: dict[str, str] | None = None) -> dict[str, str]:
    f = {"onnx/model.onnx": "model.onnx", "tokenizer.json": "tokenizer.json"}
    f.update(extra or {})
    return f


RERANKERS: tuple[Reranker, ...] = (
    # -- Tier 1: the MiniLM ladder. One architecture, one training set (MS MARCO passage), four
    #    depths. The only clean capacity read available, because nothing else varies.
    Reranker("ms-marco-MiniLM-L-2-v2", "Xenova/ms-marco-MiniLM-L-2-v2",
             "b84c4fa7efd7b4801931e75773c940f002a494f5", 1, 16, "BERT", 512, _std(),
             {"model.onnx": "ceb39caaebb66f421f82b9051e466d817c8f715e8e1d663e020168c5e2af7914",
              "tokenizer.json": "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"}),
    Reranker("ms-marco-MiniLM-L-4-v2", "Xenova/ms-marco-MiniLM-L-4-v2",
             "e8fdba61d478d042b338f7bcf7ba4e48ed7d46d7", 1, 19, "BERT", 512, _std(),
             {"model.onnx": "f03e07422f9f723146d9e65ee52cef262ac4ada5997dce0f9e72422327cf8252",
              "tokenizer.json": "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"}),
    Reranker("ms-marco-MiniLM-L-6-v2", "Xenova/ms-marco-MiniLM-L-6-v2",
             "a09144355adeed5f58c8ed011d209bf8ee5a1fec", 1, 23, "BERT", 512, _std(),
             {"model.onnx": "c623d0bcb99f4622beb413eaef00cfbe5db20df9f1dd982da4b4f26022881870",
              "tokenizer.json": "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"}),
    Reranker("ms-marco-MiniLM-L-12-v2", "Xenova/ms-marco-MiniLM-L-12-v2",
             "42a4a787e30451cf9dbd09080c2a5b8dde332c1e", 1, 33, "BERT", 512, _std(),
             {"model.onnx": "3a6d50ce60de831c8c68197df674eeb878d4ff34bb1aca5d1f3cb346c9075dba",
              "tokenizer.json": "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"}),

    # -- Tier 2: modern rerankers. Different training data, different architecture, five years
    #    newer. This is where the "L-2 is a 2021-era model" argument is actually tested.
    Reranker("bge-reranker-base", "BAAI/bge-reranker-base",
             "2cfc18c9415c912f9d8155881c133215df768a70", 2, 278, "XLM-RoBERTa", 512, _std(),
             {"model.onnx": "15b9a8c3da82eddf263df571281166e00e9308fe19d077084b642ebfcaf06d2b",
              "tokenizer.json": "9eb652ac4e40cc093272bbbe0f55d521cf67570060227109b5cdc20945a4489e"}),
    Reranker("jina-reranker-v2-base-multilingual", "jinaai/jina-reranker-v2-base-multilingual",
             "9cfeff2df7d40d1b78e75e5e9cebec92a99813c9", 2, 278, "XLM-RoBERTa", 1024, _std(),
             {"model.onnx": "0ef3f7978f7bc52360864d74edc1a0e03d159af770a7767c4d5943496e616012",
              "tokenizer.json": "3a56def25aa40facc030ea8b0b87f3688e4b3c39eb8b45d5702b3a1300fe2a20"}),
    Reranker("mxbai-rerank-base-v1", "mixedbread-ai/mxbai-rerank-base-v1",
             "800f24c113213a187e65bde9db00c15a2bb12738", 2, 184, "DeBERTa-v3", 512, _std(),
             {"model.onnx": "acd44aff3ed526079ed44cffac2e549ce70805ea193d70973c98b67e09efec1a",
              "tokenizer.json": "305674b4d785287feecfb5f73f24aa75e9b57c87c579cfe24fbd207987d4b4c4"}),
    Reranker("jina-reranker-v1-turbo-en", "jinaai/jina-reranker-v1-turbo-en",
             "b8c14f4e723d9e0aab4732a7b7b93741eeeb77c2", 2, 38, "JinaBERT", 8192, _std(),
             {"model.onnx": "c1296c66c119de645fa9cdee536d8637740efe85224cfa270281e50f213aa565",
              "tokenizer.json": "0046da43cc8c424b317f56b092b0512aaaa65c4f925d2f16af9d9eeb4d0ef902"}),

    # -- Tier 3: the large models. NOT fetched unless tier 2 earns them -- a 560M model at 1 thread
    #    on CPU is roughly an order of magnitude per pair, and depth 20 multiplies it again.
    #    bge-large's graph exceeds the 2 GB protobuf limit and ships external weights beside it;
    #    omitting `model.onnx_data` yields a graph that LOADS and produces garbage.
    Reranker("bge-reranker-large", "BAAI/bge-reranker-large",
             "55611d7bca2a7133960a6d3b71e083071bbfc312", 3, 560, "XLM-RoBERTa", 512,
             _std({"onnx/model.onnx_data": "model.onnx_data"}),
             {"model.onnx": None, "model.onnx_data": None, "tokenizer.json": None}),
    Reranker("mxbai-rerank-large-v1", "mixedbread-ai/mxbai-rerank-large-v1",
             "98f655841d5caf0b16eaff79c2b4ca109d920d17", 3, 435, "DeBERTa-v3", 512, _std(),
             {"model.onnx": None, "tokenizer.json": None}),
)

# Named, so a later session does not quietly "add" them believing they were overlooked.
REFUSED = {
    "BAAI/bge-reranker-v2-m3": (
        "no ONNX export published by the maintainer. Adopting it would require a self-made "
        "transformers.onnx export -- the exact artifact behind this project's existing open gap "
        "on the embedder. NOT ADOPTED, and NOT substituted."
    ),
    "mixedbread-ai/mxbai-rerank-base-v2": ("same: no maintainer-published ONNX export."),
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(model: Reranker, remote: str, dest: Path) -> None:
    url = f"https://huggingface.co/{model.repo}/resolve/{model.revision}/{remote}"
    print(f"    downloading {remote} ...", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "marlowe-session-i"})
    with urllib.request.urlopen(req, timeout=900) as response, tmp.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    tmp.replace(dest)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", type=int, action="append", default=None,
                    help="which tiers to fetch; repeatable. Default: 1 and 2.")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    tiers = set(args.tier or [1, 2])

    print("REFUSED, recorded so they are not silently re-added later:")
    for repo, why in REFUSED.items():
        print(f"  {repo}\n    {why}")
    print()

    unpinned: list[tuple[str, str, str]] = []
    fetched = []
    for model in RERANKERS:
        if model.tier not in tiers:
            continue
        target = MODELS_DIR / model.name
        target.mkdir(parents=True, exist_ok=True)
        print(f"{model.name}  ({model.arch}, ~{model.params_m}M, max_seq {model.max_seq})")
        print(f"  {model.repo} @ {model.revision[:12]}")

        for remote, local in model.files.items():
            dest = target / local
            if args.force or not dest.exists():
                download(model, remote, dest)
            digest = sha256_file(dest)
            expected = model.digests.get(local)
            if expected is None:
                unpinned.append((model.name, local, digest))
                print(f"    {local:20s} UNPINNED  {digest}")
            elif digest != expected:
                print(
                    f"\nDIGEST MISMATCH for {dest}\n"
                    f"  manifest: {expected}\n  on disk:  {digest}\n\n"
                    "Refusing. A silently-different reranker still scores and still passes every "
                    "structural test -- it only moves the number.", file=sys.stderr)
                return 1
            else:
                print(f"    {local:20s} ok  {digest[:16]}...")
        fetched.append(model)
        print()

    if unpinned:
        print("\nRefusing to leave unpinned files in place. Paste these into RERANKERS in this "
              "script, then re-run:\n", file=sys.stderr)
        by_model: dict[str, list[tuple[str, str]]] = {}
        for name, local, digest in unpinned:
            by_model.setdefault(name, []).append((local, digest))
        for name, entries in by_model.items():
            print(f"  {name}:", file=sys.stderr)
            for local, digest in entries:
                print(f'    "{local}": "{digest}",', file=sys.stderr)
        return 1

    manifest = {
        "_what": "Session I candidate rerankers, pinned by repository revision AND file digest.",
        "_variant_choice": (
            "f32 onnx/model.onnx for every model. Follows fetch_model.py's reasoning, and holds "
            "precision constant across the capacity sweep so arm 2's result is attributable to "
            "capacity. The shipped L-2-int8 remains on the frontier as the control."
        ),
        "refused": REFUSED,
        "models": [
            {"name": m.name, "repo": m.repo, "revision": m.revision, "tier": m.tier,
             "arch": m.arch, "params_m": m.params_m, "max_seq": m.max_seq,
             "digests": {k: sha256_file(MODELS_DIR / m.name / k) for k in m.digests}}
            for m in fetched
        ],
    }
    out = REPO / "runs" / "session-i" / "reranker-manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(fetched)} rerankers ready, all digests pinned.")
    print(f"WROTE {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
