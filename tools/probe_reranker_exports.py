"""Session I, Phase 1.1 (probe) — which candidate rerankers actually have a pinnable ONNX export?

STATE.md's bar, inherited from the open gap on the embedder: *"any reranker adopted in Session I
must meet the same digest-pinning bar as the embedder, or it creates a second instance of this
gap."* An export I produce myself with `transformers.onnx` does NOT meet it -- that is precisely
the artifact nobody independently validated.

So this probe asks the registry, rather than assuming from reputation:

  * does a **maintainer-published** ONNX export exist (the model owner, or Xenova, whose export is
    the artifact the wider ecosystem uses and which Sessions G/H already adopted at this bar)?
  * what is the repository's **revision commit**? `fetch_model.py` pins commits precisely because
    `resolve/main` is a moving pointer. The existing reranker fetch in `reach_cross_encoder.py`
    used `resolve/main` -- the bytes ended up pinned by digest, but the URL is not reproducible.
    New models get the commit.
  * how large is the graph, since cost is recorded for the frontier.

Nothing is downloaded here. This writes a manifest that `fetch_rerankers.py` then consumes, so the
"what exists" step and the "acquire it" step cannot silently disagree about which file was meant.

    python tools/probe_reranker_exports.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_PATH = REPO / "runs" / "session-i" / "reranker-export-probe.json"

# Every model STATE.md names, plus the two already on disk as controls. Each entry lists the
# candidate repositories in preference order: the model OWNER's own export first, because an export
# by the people who trained the weights is a stronger authority than a third-party conversion.
CANDIDATES: dict[str, list[str]] = {
    "L-2":  ["Xenova/ms-marco-MiniLM-L-2-v2"],
    "L-4":  ["Xenova/ms-marco-MiniLM-L-4-v2", "cross-encoder/ms-marco-MiniLM-L-4-v2"],
    "L-6":  ["Xenova/ms-marco-MiniLM-L-6-v2", "cross-encoder/ms-marco-MiniLM-L-6-v2"],
    "L-12": ["Xenova/ms-marco-MiniLM-L-12-v2", "cross-encoder/ms-marco-MiniLM-L-12-v2"],
    "bge-base":   ["BAAI/bge-reranker-base", "Xenova/bge-reranker-base"],
    "bge-large":  ["BAAI/bge-reranker-large", "Xenova/bge-reranker-large"],
    "bge-v2-m3":  ["BAAI/bge-reranker-v2-m3"],
    "jina-v1-turbo": ["jinaai/jina-reranker-v1-turbo-en"],
    "jina-v2":    ["jinaai/jina-reranker-v2-base-multilingual"],
    "mxbai-base": ["mixedbread-ai/mxbai-rerank-base-v1", "Xenova/mxbai-rerank-base-v1"],
    "mxbai-large": ["mixedbread-ai/mxbai-rerank-large-v1", "Xenova/mxbai-rerank-large-v1"],
    "mxbai-base-v2": ["mixedbread-ai/mxbai-rerank-base-v2"],
}


def api(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "marlowe-session-i-probe"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def probe(repo: str) -> dict:
    try:
        info = api(f"https://huggingface.co/api/models/{repo}")
    except urllib.error.HTTPError as e:
        return {"repo": repo, "exists": False, "http_status": e.code}
    except Exception as e:  # noqa: BLE001
        return {"repo": repo, "exists": False, "error": repr(e)}

    files = [s["rfilename"] for s in info.get("siblings", [])]
    onnx = sorted(f for f in files if f.endswith(".onnx"))
    tokenizers = sorted(f for f in files if f.endswith("tokenizer.json"))
    return {
        "repo": repo,
        "exists": True,
        "revision": info.get("sha"),
        "gated": bool(info.get("gated")),
        "onnx_files": onnx,
        "has_tokenizer_json": tokenizers,
        # The bar, evaluated here rather than eyeballed later. A repo with no ONNX and no
        # tokenizer.json cannot be adopted at this project's pinning standard, full stop.
        "meets_pinning_bar": bool(onnx and tokenizers and not info.get("gated")),
    }


def main() -> int:
    results = {}
    print(f"{'model':>15}  {'repo':>46}  {'onnx':>5}  {'tok':>4}  revision")
    for name, repos in CANDIDATES.items():
        entries = []
        for repo in repos:
            p = probe(repo)
            entries.append(p)
            if p.get("exists"):
                print(f"{name:>15}  {repo:>46}  {len(p['onnx_files']):>5}  "
                      f"{'yes' if p['has_tokenizer_json'] else 'NO':>4}  "
                      f"{(p['revision'] or '')[:12]}")
            else:
                print(f"{name:>15}  {repo:>46}  {'--':>5}  {'--':>4}  "
                      f"NOT FOUND ({p.get('http_status', p.get('error'))})")
            if p.get("meets_pinning_bar"):
                break  # owner export preferred; stop at the first that clears the bar
        results[name] = entries

    adoptable = {k: v for k, v in results.items() if any(e.get("meets_pinning_bar") for e in v)}
    refused = sorted(set(results) - set(adoptable))

    print(f"\n{len(adoptable)}/{len(CANDIDATES)} candidates clear the pinning bar.")
    if refused:
        print("REFUSED -- no maintainer-published ONNX + tokenizer.json, so NOT ADOPTED and not")
        print("substituted with a self-made export:")
        for name in refused:
            print(f"  {name}")

    print("\nONNX files available per adoptable candidate (the variant choice is a separate,")
    print("recorded decision -- see fetch_rerankers.py):")
    for name, entries in adoptable.items():
        e = next(x for x in entries if x.get("meets_pinning_bar"))
        print(f"  {name:>15}  {e['repo']}")
        for f in e["onnx_files"]:
            print(f"                   {f}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "_what": "Session I Phase 1.1 probe -- which candidate rerankers have a pinnable export.",
        "_bar": (
            "maintainer-published ONNX + tokenizer.json + ungated. A self-made transformers.onnx "
            "export does NOT clear it; that is the artifact behind this project's existing open gap."
        ),
        "candidates": results,
        "adoptable": sorted(adoptable),
        "refused": refused,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
