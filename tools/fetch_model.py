"""Acquire ADR-004's embedding model, with integrity pinned.

Same two rules as `eval/src/marlowe_eval/datasets/fetch.py`, for the same reasons:

  * **Never vendored.** `models/` is gitignored. The repo carries a manifest and digests, not
    a 90 MB binary that one `git add -A` puts in the history permanently.
  * **Fails on mismatch. Never warns.** A silently-different model produces embeddings that
    look fine and are not comparable to anything — and unlike a wrong corpus, a wrong model
    would still score, still pass every structural test, and quietly move a published number.

**The URL is pinned to a commit, not to `main`.** `resolve/main` is a moving pointer: the same
URL can return different bytes next week with nothing in this repo changing. That is the FTS5
hazard in a different costume, and the fix is the same — name the exact revision.

**Which ONNX file, and why the plain one.** The repo publishes `model.onnx` plus `model_O1..O4`
(graph-optimized) and several `qint8` quantizations. We take the **unoptimized f32 export**.
The optimized variants bake an optimizer's fusion choices into the file, which means the
numerics of a frozen path would be inherited from a tool nobody in this repo ran, at a version
nobody recorded. Optimization is the *engine's* decision, made at a level this project pins
explicitly.

Digests are UNPINNED until someone downloads the files and pins them. That is a deliberate hole
with a loud edge: this script refuses to leave an unpinned file in place, prints the digest it
computed, and tells you where to paste it.

    python tools/fetch_model.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO / "models"

# The exact repository revision. Pinning the commit rather than `main` is what makes the URL
# immutable; HuggingFace serves `resolve/<sha>/...` for any commit that exists.
REVISION = "44e7d1d6caec8c883c2d4b207588504d519788d0"
HF_REPO = "jinaai/jina-embeddings-v2-small-en"

# The model this replaced, kept so the comparison in runs/session-c/embedder-comparison.json
# can be reproduced and so a revert has somewhere to go. NOT fetched by default.
PREVIOUS = {
    "repo": "sentence-transformers/all-MiniLM-L6-v2",
    "revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    "model.onnx": "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452",
    "vocab.txt": "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
    "why_replaced": (
        "recall@1 0.345 against jina-v2-small's 0.452 on 42 fit-split cases. See "
        "docs/design/DECISIONS.md ADR-004 and runs/session-c/PREREGISTRATION-model.json."
    ),
}


@dataclass(frozen=True)
class FileSpec:
    """One file of the model, pinned by digest."""

    remote: str
    local: str
    sha256: str | None
    why: str


MODEL_NAME = "jina-embeddings-v2-small-en"

FILES: tuple[FileSpec, ...] = (
    FileSpec(
        remote="model.onnx",
        local="model.onnx",
        sha256="974fdefe71fc9889258f569132b35acae6278874c8d09dbdf7806d23ad0b4497",
        why=(
            "The unoptimized f32 ONNX export, NOT model-w-mean-pooling.onnx: pooling belongs in "
            "our code where it is asserted against a reference, not baked into a graph where a "
            "wrong mask convention would be invisible."
        ),
    ),
    FileSpec(
        remote="vocab.txt",
        local="vocab.txt",
        sha256="109753d618dbb576a35112f9c20ef35cf3517d46106175bcf010c986a4bef1df",
        why="The WordPiece vocabulary, 30,522 entries. Read by the hand-rolled tokenizer.",
    ),
    FileSpec(
        remote="tokenizer_config.json",
        local="tokenizer_config.json",
        sha256="25cbd867af916b5a5718e80e9a702cf72c61bf890a1bc141c6fbce6d74c99632",
        why=(
            "Carried so the tokenizer's settings are auditable beside the vocabulary rather "
            "than only asserted in Rust source. do_lower_case=true, strip_accents=null "
            "(BertTokenizer derives accent-stripping from do_lower_case, so accents ARE "
            "stripped), tokenize_chinese_chars=true."
        ),
    ),
)

# ADR-004's numbers, verified against the repo's own config.json rather than assumed.
EXPECTED = {
    "hidden_size": 512,
    "num_hidden_layers": 4,
    "vocab_size": 30528,
    "max_position_embeddings": 8192,
    "pooling": "mean over the attention mask, then L2 normalize",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def url_for(remote: str) -> str:
    return f"https://huggingface.co/{HF_REPO}/resolve/{REVISION}/{remote}"


def download(spec: FileSpec, dest: Path) -> None:
    url = url_for(spec.remote)
    print(f"  downloading {spec.remote} ...")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=300) as response, tmp.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    tmp.replace(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download even if the file is present and its digest matches",
    )
    args = parser.parse_args()

    target = MODELS_DIR / MODEL_NAME
    target.mkdir(parents=True, exist_ok=True)
    print(f"model:    {HF_REPO}")
    print(f"revision: {REVISION}")
    print(f"into:     {target}")

    unpinned: list[tuple[str, str]] = []
    for spec in FILES:
        dest = target / spec.local
        if args.force or not dest.exists():
            download(spec, dest)

        digest = sha256_file(dest)
        if spec.sha256 is None:
            unpinned.append((spec.local, digest))
            print(f"  {spec.local:24s} UNPINNED, computed {digest}")
            continue
        if digest != spec.sha256:
            print(
                f"\nDIGEST MISMATCH for {dest}\n"
                f"  manifest: {spec.sha256}\n"
                f"  on disk:  {digest}\n\n"
                "Refusing. A silently-different model still embeds, still scores, and still "
                "passes every structural test -- it only moves the number. Delete the file and "
                "re-run, or if the change is intended, pin the new digest deliberately and "
                "expect every number fit under the old one to be unreproducible.",
                file=sys.stderr,
            )
            return 1
        print(f"  {spec.local:24s} ok  {digest[:16]}...")

    if unpinned:
        print(
            "\nRefusing to leave unpinned files in place. Paste these into FILES in this "
            "script, then re-run:\n",
            file=sys.stderr,
        )
        for name, digest in unpinned:
            print(f'    {name}: sha256="{digest}"', file=sys.stderr)
        return 1

    # Cross-check ADR-004's claims against the model's own config rather than trusting them.
    config = json.loads((target / "tokenizer_config.json").read_text(encoding="utf-8"))
    if config.get("do_lower_case") is not True:
        print(
            f"tokenizer_config.json says do_lower_case={config.get('do_lower_case')!r}; the "
            "hand-rolled tokenizer assumes true. Refusing rather than embedding with a "
            "casefold the vocabulary was not built for.",
            file=sys.stderr,
        )
        return 1

    print(f"\nmodel ready: {target}")
    print(f"  dimensions {EXPECTED['hidden_size']}, {EXPECTED['num_hidden_layers']} layers, "
          f"vocab {EXPECTED['vocab_size']}")
    print(f"  pooling: {EXPECTED['pooling']}")
    print(
        f"  the model's own configured maximum is "
        f"{EXPECTED['max_position_embeddings']} word pieces (ALiBi, so no learned position "
        "table). Truncation is no longer the binding constraint -- see "
        "runs/session-c/embedder-comparison.json."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
