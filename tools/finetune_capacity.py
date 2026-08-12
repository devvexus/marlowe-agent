"""M0c Session M, W1 — CAPACITY AT FIXED FINE-TUNING. Session J's recipe, four base sizes.

    python tools/finetune_capacity.py --build-cache ms-marco-MiniLM-L-4-v2 ms-marco-MiniLM-L-12-v2
    python tools/finetune_capacity.py --base ms-marco-MiniLM-L-2-v2      # THE INSTRUMENT
    python tools/finetune_capacity.py --base ms-marco-MiniLM-L-6-v2      # second instrument
    python tools/finetune_capacity.py --base ms-marco-MiniLM-L-4-v2
    python tools/finetune_capacity.py --base ms-marco-MiniLM-L-12-v2
    python tools/finetune_capacity.py --verify ms-marco-MiniLM-L-12-v2-ft-w1

## The confound this file exists to break

`STATE.md` records the cross-encoder capacity question as closed: *"the 278M models lose to a
fine-tuned 16M by 17-27 points"*. Look at what was compared. **Only two models in this project's
history have ever been fine-tuned — L-2 and L-6, both in Session J.** Every larger model in
`runs/session-m0c-m/frontier.json` is a stock pretrained checkpoint. So the claim rests on
*fine-tuned small* against *pretrained large*: two variables moved at once.

This file holds fine-tuning constant and varies only base capacity, giving
**L-2-ft (16M) -> L-4-ft (19M) -> L-6-ft (23M) -> L-12-ft (33M)**.

## What "Session J's recipe" means, stated precisely, because one word of it is ambiguous

`session_j_finetune.py` is PARAMETERISED BY BASE and Session J ran it on two. Reading that file
rather than reasoning about it settles what transfers:

  * base checkpoint: the un-tuned `cross-encoder/...` PyTorch checkpoint. Never a second round on
    top of an existing fine-tune (M0c Session A's L1 confound).
  * pairs: `runs/session-j/training-pairs.jsonl`, unchanged, including its conversation-level fold.
  * loss: hard-label MarginMSE, `mse_loss(s_pos - s_neg, delta)`.
  * hyperparameters: 3 epochs, lr 2e-5, batch 32, MAX_LEN 256, AdamW, seed 7, best epoch by
    fit-val R@1 over the 47 held-apart fit queries.
  * **`delta` is RECOMPUTED PER BASE** — the median margin over the fit cases *that base model*
    already ranks first. Session J recorded 2.926574 for L-2 and **2.623647 for L-6**, from the
    same code, because a MarginMSE target is denominated in that model's own logit units. Carrying
    L-2's 2.926574 onto L-12 would be applying a NUMBER where the recipe applies a RULE, and it
    would make the target mean something different on every graph. Both recorded values are
    asserted here, so a drift is an error rather than a difference nobody notices.

## THE INSTRUMENT, and there are two of them

`--base ms-marco-MiniLM-L-2-v2` must land on the shipped fit R@1 of **0.7555** with **0 discordant
queries out of 229** against the shipped graph. That is `finetune_v2.py`'s arm A discipline, and if
it fails this trainer is not Session J's and no capacity number means anything.

**A second instrument runs at L-6.** Reproducing only L-2 would leave open that this file is
faithful at the size it was checked on and wrong in whatever it had to generalise — a per-base
`delta`, a per-base cache, a per-base checkpoint path. L-6 exercises every one of those and Session
J recorded its fit-val history to compare against. Two reproductions at two sizes is what licenses
the two sizes nobody has a reference for.

## The per-base slate cache, and its own control

`delta` and the fit-val selection both read `runs/session-j/rerank-scores-fit-<stem>-f32-seq256.json`
— the base model's own scores over the depth-10 fit slates. Session J's arm 7 wrote one per base
and only L-2 and L-6 exist. `--build-cache` writes the missing two, into THIS session's directory,
by importing `session_j_arm7.score_slates` rather than restating it.

**The slate is a property of the pre-rerank key, not of the reranker**, so every base's cache must
carry byte-identical `slate`, `turn_ids` and `gold`. That is verified against Session J's L-2 cache
before a new cache is written, and it is the check that says the reconstruction is Session J's
slate rather than a plausible slate of the same shape.

## Nothing here ships

No artifact is minted, `crates/` is untouched, no held-out read is taken. Session J's manifest and
`runs/session-m0c-m/retrain-manifest.json` are records of other work and are not written to; these
graphs are pinned in `runs/session-m0c-m/capacity-manifest.json` and registered into the loader at
runtime by `tools/capacity_register.py`, so `tools/session_i_rerankers.py` is not edited either.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from session_i_rerankers import MODELS_DIR  # noqa: E402

OUT_DIR = REPO / "runs" / "session-m0c-m"
SESSION_J = REPO / "runs" / "session-j"
MANIFEST = OUT_DIR / "capacity-manifest.json"

# Session J's pairs, unchanged. The negatives are NOT a variable in this experiment.
PAIRS = SESSION_J / "training-pairs.jsonl"

MAX_LEN = 256
SEED = 7
SESSION_J_VAL_QUERIES = 47

# Where each base's un-tuned PyTorch checkpoint lives. L-2 and L-6 were already in the local HF
# cache (Session J used them); L-4 and L-12 were NOT and were downloaded to models/hf-* with their
# digests recorded in runs/session-m0c-m/capacity-base-checkpoints.json.
BASES = {
    "ms-marco-MiniLM-L-2-v2": "cross-encoder/ms-marco-MiniLM-L-2-v2",
    "ms-marco-MiniLM-L-4-v2": str(MODELS_DIR / "hf-ms-marco-MiniLM-L-4-v2"),
    "ms-marco-MiniLM-L-6-v2": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "ms-marco-MiniLM-L-12-v2": str(MODELS_DIR / "hf-ms-marco-MiniLM-L-12-v2"),
}

# What Session J recorded, per base, from this same code path. Asserted, not consulted.
SESSION_J_RECORDED = {
    "ms-marco-MiniLM-L-2-v2": {"delta": 2.926574, "onnx_r1": 0.5983, "base_val": 0.6809,
                               "best_epoch": 2, "fit_val": 0.7447},
    "ms-marco-MiniLM-L-6-v2": {"delta": 2.623647, "onnx_r1": 0.6114, "base_val": 0.6383,
                               "best_epoch": 1, "fit_val": 0.7660},
}


def stem(base: str) -> str:
    return base.replace("ms-marco-MiniLM-", "")


def cache_path(base: str) -> Path:
    """Session J's cache when it exists; this session's when Session J never wrote one."""
    name = f"rerank-scores-fit-{stem(base)}-f32-seq256.json"
    sj = SESSION_J / name
    return sj if sj.exists() else OUT_DIR / name


def set_seed(seed: int) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def cuda_ready() -> bool:
    """ADR-015's fix, applied exactly. os.add_dll_directory BEFORE onnxruntime is imported."""
    import torch

    lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.isdir(lib):
        try:
            os.add_dll_directory(lib)
        except (AttributeError, OSError):
            pass
    return bool(torch.cuda.is_available())


def export_onnx(model, out_path: Path) -> None:
    """Session J's export call, unchanged, so the graph is the same KIND of graph."""
    import torch

    model.eval()
    ids = torch.ones(1, MAX_LEN, dtype=torch.long)
    mask = torch.ones(1, MAX_LEN, dtype=torch.long)
    types = torch.zeros(1, MAX_LEN, dtype=torch.long)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        (ids, mask, types),
        str(out_path),
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "token_type_ids": {0: "batch", 1: "seq"},
            "logits": {0: "batch"},
        },
        opset_version=14,
        do_constant_folding=True,
    )


def score_with_torch(model, tok, pairs, device, batch: int = 64) -> np.ndarray:
    import torch

    was_training = model.training
    model.eval()
    scores = []
    with torch.no_grad():
        for i in range(0, len(pairs), batch):
            chunk = pairs[i:i + batch]
            enc = tok([q for q, _ in chunk], [d for _, d in chunk], padding="max_length",
                      truncation=True, max_length=MAX_LEN, return_tensors="pt").to(device)
            logits = model(**enc).logits.reshape(-1)
            scores.extend(logits.float().cpu().numpy().tolist())
    if was_training:
        model.train()
    return np.asarray(scores)


def r_at_1_from_scores(cache: dict, scores_by_query: dict[str, np.ndarray]) -> float:
    hits = 0
    for qid, row in cache["rows"].items():
        s = scores_by_query[qid]
        order = np.argsort(-s, kind="stable")
        hits += bool(row["gold"][int(order[0])])
    return hits / len(cache["rows"])


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_questions() -> dict[str, str]:
    split = json.loads(io.open(REPO / "tools" / "split.json", encoding="utf-8").read())
    raw = json.loads(io.open(REPO / split["corpus_path"], encoding="utf-8").read())
    return {str(i["question_id"]): str(i["question"]) for i in raw}


# ------------------------------------------------------------------------------------------------
# --build-cache : the missing per-base slate caches, with a control on the slate itself
# ------------------------------------------------------------------------------------------------


def build_cache(bases: list[str]) -> int:
    """Session J's arm-7 cache for a base Session J never ran, by IMPORTING its scoring function.

    The control is what makes this usable. A slate is the top-10 under the *pre-rerank* key, so it
    cannot depend on which cross-encoder scores it — and Session J's L-2 and L-6 caches agree on
    `slate`, `turn_ids` and `gold` for all 229 queries, which is the fact this checks against. If a
    newly built cache disagrees anywhere, the reconstruction is a different slate of the same shape
    and nothing is written.
    """
    import session_j_arm7 as A7
    from reach_pools import turn_texts
    from reach_rerank_fit import PREREG_PATH as SESSION_H_PREREG
    from session_h_pools import fidelity_gate, load_split_pools
    from session_i_rerankers import load as load_pinned
    from session_i_seqlen import turn_roles

    h = json.loads(io.open(SESSION_H_PREREG, encoding="utf-8").read())
    gap_ms = h["frozen_parameters"]["session_gap_ms"]["value"]
    prune_n = h["frozen_parameters"]["prune_N"]["value"]

    fit, heldout, _ = load_split_pools()
    ok, _gate = fidelity_gate(heldout)
    if not ok:
        raise SystemExit("Reconstruction licensing gate FAILED. Nothing is scored.")
    print(f"licensing gate PASSED. fit split: {len(fit)} pools "
          f"(held-out loaded for the gate only and NOT scored)")

    reference = json.loads(io.open(SESSION_J / "rerank-scores-fit-L-2-v2-f32-seq256.json",
                                   encoding="utf-8").read())
    texts, roles = turn_texts(), turn_roles()

    for base in bases:
        out = OUT_DIR / f"rerank-scores-fit-{stem(base)}-f32-seq256.json"
        if out.exists():
            print(f"{base}: cache already at {out.name}; not rebuilt")
            continue
        ce = load_pinned(base)
        print(f"\n{base}  ({ce.arch}, ~{ce.params_m}M, digest {ce.digest[:16]}...)  "
              f"CPU, 1 thread, ORT_ENABLE_BASIC, batch 1")
        cache = A7.score_slates(ce, fit, texts, roles, 256, gap_ms, prune_n, base)
        cache.update({"model": base, "precision": "f32", "seq_len": 256, "split": "fit",
                      "digest": ce.digest,
                      "_what": "M0c Session M W1 — Session J's arm-7 fit cache for a base Session J "
                               "never ran. Written by tools/finetune_capacity.py --build-cache, "
                               "which imports session_j_arm7.score_slates."})

        bad = [q for q in reference["rows"]
               if (cache["rows"][q]["slate"] != reference["rows"][q]["slate"]
                   or cache["rows"][q]["turn_ids"] != reference["rows"][q]["turn_ids"]
                   or cache["rows"][q]["gold"] != reference["rows"][q]["gold"])]
        print(f"  slate control vs Session J's L-2 cache: {len(reference['rows']) - len(bad)}"
              f"/{len(reference['rows'])} queries byte-identical on slate/turn_ids/gold")
        if bad or set(cache["rows"]) != set(reference["rows"]):
            raise SystemExit(
                f"REFUSING to write {out.name}: {len(bad)} queries disagree with Session J's slate. "
                "The slate is a property of the pre-rerank key and cannot depend on the reranker, "
                "so a disagreement means this is not Session J's slate."
            )
        r1 = r_at_1_from_scores(cache, {q: np.array(r["scores"]) for q, r in cache["rows"].items()})
        print(f"  base ONNX fit R@1 over the depth-10 slates: {r1:.4f}  "
              f"({cache['ms_per_pair']['median']:.1f} ms/pair)")
        out.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
        print(f"  WROTE {out.relative_to(REPO)}")
    return 0


# ------------------------------------------------------------------------------------------------
# --verify : the same five export checks, on this session's manifest
# ------------------------------------------------------------------------------------------------


def verify(name: str) -> int:
    import torch

    lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.isdir(lib):
        try:
            os.add_dll_directory(lib)
        except (AttributeError, OSError):
            pass

    import capacity_register  # noqa: F401  — registers this session's graphs in the ONE loader
    import session_i_rerankers as R
    from session_j_verify_export import padding_invariance, torch_vs_ort

    entry = next(m for m in json.loads(io.open(MANIFEST, encoding="utf-8").read())["models"]
                 if m["name"] == name)
    ce = R.load(name)
    print(f"{name}  digest {ce.digest[:16]}...  provider asserted, ORT_ENABLE_BASIC, 1 thread")

    checks = {
        "smoke_discriminates": R.smoke_test(ce),
        "determinism": R.determinism(ce),
        "batch_invariance": R.batch_invariance(ce),
        "padding_invariance": padding_invariance(ce),
        # The tokenizer must be the one this graph's OWN base uses. A default here would encode the
        # pairs for check 5 with another model's tokenizer and still return plausible floats.
        "torch_vs_ort": torch_vs_ort(ce, entry["base_checkpoint"]),
    }

    print()
    s = checks["smoke_discriminates"]
    print(f"  1. discriminates          relevant {s['relevant']:+.4f} vs irrelevant "
          f"{s['irrelevant']:+.4f}   {'PASS' if s['pass'] else 'FAIL'}")
    d = checks["determinism"]
    print(f"  2. determinism            {len(set(d['values']))} distinct value(s) over "
          f"{len(d['values'])} runs   {'PASS' if d['pass'] else 'FAIL'}")
    b = checks["batch_invariance"]
    print(f"  3. batch invariance       max |delta| {b['max_abs_diff']:.6f}   "
          f"{'PASS' if b['identical'] else 'FAIL'}")
    p = checks["padding_invariance"]
    print(f"  4. padding invariance     median {p['median_abs_delta']:.6f}  p95 "
          f"{p['p95_abs_delta']:.6f}  max {p['max_abs_delta']:.6f}   "
          f"{'PASS' if p['invariant'] else 'FAIL'}")
    t = checks["torch_vs_ort"]
    if t.get("run"):
        print(f"  5. torch vs ORT           max |delta| {t['max_abs_delta']:.6f}   "
              f"{'PASS' if t['agrees'] else 'FAIL'}")
    else:
        print(f"  5. torch vs ORT           NOT RUN — {t['why']}")

    ok = (checks["smoke_discriminates"]["pass"] and checks["determinism"]["pass"]
          and checks["batch_invariance"]["identical"] and checks["padding_invariance"]["invariant"]
          and bool(checks["torch_vs_ort"].get("agrees")))
    print()
    print(f"  VERDICT: {'the graph may be scored' if ok else 'REFUSED — do not score with this graph'}")

    out = OUT_DIR / f"export-verification-{name}.json"
    out.write_text(json.dumps({
        "_what": "M0c Session M W1 — export gate for a graph this session trained.",
        "model": name, "digest": ce.digest, "checks": checks, "pass": bool(ok),
        "_per_graph_never_inherited": (
            "ADR-015. Batch and padding invariance are re-measured on EVERY graph. L-2-ft's "
            "0.000000 is a fact about that graph, not about the BERT architecture."
        ),
        "open_gap": (
            "SELF-VALIDATED ONLY. There is no external authority for a model this session trained, "
            "so the unvalidated-export gap is NOT closed by these checks — it is bounded by them."
        ),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {out.relative_to(REPO)}")
    return 0 if ok else 1


# ------------------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-cache", nargs="+", metavar="BASE",
                    help="write the missing per-base arm-7 fit cache(s) and exit")
    ap.add_argument("--verify", metavar="MODEL_NAME")
    ap.add_argument("--base", choices=sorted(BASES))
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--suffix", default="w1")
    args = ap.parse_args()

    if args.build_cache:
        return build_cache(args.build_cache)
    if args.verify:
        return verify(args.verify)
    if args.base is None:
        raise SystemExit("--base is required when training")

    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    set_seed(args.seed)
    has_cuda = cuda_ready()
    device = "cuda" if has_cuda else "cpu"
    print(f"device: {device}"
          + (f"  ({torch.cuda.get_device_name(0)})" if has_cuda else "  — CUDA NOT AVAILABLE"))

    cpath = cache_path(args.base)
    if not cpath.exists():
        raise SystemExit(f"{cpath} is missing — run --build-cache {args.base} first.")
    print(f"fit slate cache: {cpath.relative_to(REPO)}")
    cache = json.loads(io.open(cpath, encoding="utf-8").read())

    # ---- delta, from THIS BASE's own margins on cases it already gets right --------------------
    margins = []
    for row in cache["rows"].values():
        s = np.array(row["scores"], float)
        order = np.argsort(-s, kind="stable")
        if row["gold"][int(order[0])]:
            margins.append(float(s[order[0]] - s[order[1]]))
    delta = float(np.median(margins))
    print(f"target margin delta = {delta:.6f}  (median over {len(margins)} fit cases the base "
          f"model already ranks correctly — NOT chosen against the outcome)")
    recorded = SESSION_J_RECORDED.get(args.base)
    if recorded is not None and abs(delta - recorded["delta"]) > 1e-6:
        raise SystemExit(
            f"delta reads {delta:.6f}; Session J recorded {recorded['delta']} for {args.base}. "
            "Same cache, same formula — a difference means this is not Session J's recipe."
        )
    if recorded is not None:
        print(f"  Session J recorded {recorded['delta']} for this base — MATCHES")

    # ---- the base checkpoint --------------------------------------------------------------------
    source = BASES[args.base]
    print(f"\nbase checkpoint: {source}")
    tok = AutoTokenizer.from_pretrained(source)
    model = AutoModelForSequenceClassification.from_pretrained(source).to(device)
    print(f"  parameters: {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M   "
          f"layers: {model.config.num_hidden_layers}   hidden: {model.config.hidden_size}")

    questions = load_questions()
    from reach_pools import turn_texts

    texts_by_query = turn_texts()

    def slate_pairs(qids):
        pairs, idx = [], []
        for qid in qids:
            row = cache["rows"][qid]
            per = texts_by_query.get(qid, {})
            for j, tid in enumerate(row["turn_ids"]):
                pairs.append((questions[qid], per.get(tid, "")))
                idx.append((qid, j))
        return pairs, idx

    # ---- training data ---------------------------------------------------------------------------
    rows = [json.loads(line) for line in io.open(PAIRS, encoding="utf-8") if line.strip()]
    train = [r for r in rows if r["fold"] == "train"]
    val_queries = sorted({r["query_id"] for r in rows if r["fold"] == "val"})
    if len(val_queries) != SESSION_J_VAL_QUERIES:
        raise SystemExit(f"{PAIRS.name} puts {len(val_queries)} queries in the val fold; Session J "
                         f"puts {SESSION_J_VAL_QUERIES}.")
    val_in_cache = [q for q in val_queries if q in cache["rows"]]
    print(f"\npairs file: {PAIRS.relative_to(REPO)}   (Session J's, UNCHANGED — the negatives are "
          "not a variable here)")
    print(f"training pairs: {len(train)} of {len(rows)}  "
          f"(classes: {sorted({r['negative_class'] for r in train})})")
    print(f"validation: {len(val_queries)} fit queries held apart BY CONVERSATION, "
          f"{len(val_in_cache)} with a reconstructed slate")

    # ---- the comparability check, BEFORE training -----------------------------------------------
    all_qids = sorted(cache["rows"])
    cmp_pairs, cmp_idx = slate_pairs(all_qids)
    torch_scores = score_with_torch(model, tok, cmp_pairs, device)
    by_query = {q: np.zeros(len(r["scores"])) for q, r in cache["rows"].items()}
    for (qid, j), s in zip(cmp_idx, torch_scores):
        by_query[qid][j] = s
    onnx_flat = np.array([cache["rows"][q]["scores"][j] for q, j in cmp_idx])
    torch_flat = np.array([by_query[q][j] for q, j in cmp_idx])
    onnx_r1 = r_at_1_from_scores(cache, {q: np.array(r["scores"]) for q, r in cache["rows"].items()})
    torch_r1 = r_at_1_from_scores(cache, by_query)
    comparability = {
        "xenova_onnx_r_at_1": round(onnx_r1, 4),
        "pytorch_r_at_1": round(torch_r1, 4),
        "pearson": round(float(np.corrcoef(onnx_flat, torch_flat)[0, 1]), 6),
        "max_abs_logit_difference": round(float(np.abs(onnx_flat - torch_flat).max()), 6),
        "agree": None,
    }
    comparability["agree"] = bool(abs(torch_r1 - onnx_r1) < 1e-9
                                  and comparability["max_abs_logit_difference"] < 0.01)
    print(f"\ncomparability: Xenova ONNX R@1 {onnx_r1:.4f}   this PyTorch checkpoint R@1 "
          f"{torch_r1:.4f}   pearson {comparability['pearson']:.6f}   "
          f"max |delta| {comparability['max_abs_logit_difference']:.6f}")
    if recorded is not None:
        print(f"  Session J recorded ONNX R@1 {recorded['onnx_r1']} for this base -> "
              f"{'MATCHES' if abs(onnx_r1 - recorded['onnx_r1']) < 5e-5 else 'DIFFERS'}")
    print(f"  -> {'AGREE — the same scorer on both export paths' if comparability['agree'] else 'DISAGREE — see comparability_check'}")

    val_cache = {"rows": {q: cache["rows"][q] for q in val_in_cache}}
    val_pairs, val_idx = slate_pairs(val_in_cache)

    def val_r1() -> float:
        s = score_with_torch(model, tok, val_pairs, device)
        bq = {q: np.zeros(len(r["scores"])) for q, r in val_cache["rows"].items()}
        for (qid, j), v in zip(val_idx, s):
            bq[qid][j] = v
        return r_at_1_from_scores(val_cache, bq)

    base_val = val_r1()
    print(f"  base model, fit-val R@1: {base_val:.4f}"
          + (f"   (Session J recorded {recorded['base_val']} -> "
             f"{'MATCHES' if abs(base_val - recorded['base_val']) < 5e-5 else 'DIFFERS'})"
             if recorded else ""))

    # ---- train -----------------------------------------------------------------------------------
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    loader = DataLoader(train, batch_size=args.batch, shuffle=True,
                        collate_fn=lambda b: b,
                        generator=torch.Generator().manual_seed(args.seed))
    history = [{"epoch": 0, "val_r_at_1": round(base_val, 4), "train_loss": None}]
    best = {"epoch": 0, "val_r_at_1": base_val, "state": None}

    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for batch in loader:
            pos = tok([b["question"] for b in batch], [b["positive"] for b in batch],
                      padding="max_length", truncation=True, max_length=MAX_LEN,
                      return_tensors="pt").to(device)
            neg = tok([b["question"] for b in batch], [b["negative"] for b in batch],
                      padding="max_length", truncation=True, max_length=MAX_LEN,
                      return_tensors="pt").to(device)
            s_pos = model(**pos).logits.reshape(-1)
            s_neg = model(**neg).logits.reshape(-1)
            # Hard-label MarginMSE, exactly Session J's. The objective is NOT a variable here —
            # `finetune_v2.py` arm C measured BCE at -0.0524 and this arm changes one thing.
            loss = torch.nn.functional.mse_loss(s_pos - s_neg, torch.full_like(s_pos, delta))
            opt.zero_grad()
            loss.backward()
            opt.step()
            losses.append(float(loss.item()))
        v = val_r1()
        history.append({"epoch": epoch, "val_r_at_1": round(v, 4),
                        "train_loss": round(float(np.mean(losses)), 4)})
        print(f"  epoch {epoch}: loss {np.mean(losses):.4f}  fit-val R@1 {v:.4f}"
              f"  ({v - base_val:+.4f})")
        if v > best["val_r_at_1"]:
            best = {"epoch": epoch, "val_r_at_1": v,
                    "state": {k: t.detach().cpu().clone() for k, t in model.state_dict().items()}}

    print(f"\nbest epoch: {best['epoch']}  fit-val R@1 {best['val_r_at_1']:.4f}")
    if recorded is not None:
        print(f"  Session J recorded best epoch {recorded['best_epoch']}, fit-val "
              f"{recorded['fit_val']} -> "
              f"{'MATCHES' if (best['epoch'] == recorded['best_epoch'] and abs(best['val_r_at_1'] - recorded['fit_val']) < 5e-5) else 'DIFFERS'}")
    if best["state"] is not None:
        model.load_state_dict(best["state"])

    # ---- export and pin ---------------------------------------------------------------------------
    name = f"{args.base}-ft-{args.suffix}"
    directory = MODELS_DIR / name
    directory.mkdir(parents=True, exist_ok=True)
    model = model.to("cpu")
    export_onnx(model, directory / "model.onnx")
    tok.backend_tokenizer.save(str(directory / "tokenizer.json"))
    model.save_pretrained(str(directory / "pytorch-reference"))

    digest = sha256_file(directory / "model.onnx")
    meta = {
        "name": name,
        "base": args.base,
        "base_checkpoint": source,
        "base_is_already_finetuned": False,
        "arch": "BERT (fine-tuned, M0c Session M W1)",
        "params_m": sum(p.numel() for p in model.parameters()) // 1_000_000,
        "layers": int(model.config.num_hidden_layers),
        "hidden": int(model.config.hidden_size),
        "max_seq": 512,
        "digests": {"model.onnx": digest,
                    "tokenizer.json": sha256_file(directory / "tokenizer.json")},
        "pairs_file": str(PAIRS.relative_to(REPO)).replace("\\", "/"),
        "negative_classes": sorted({r["negative_class"] for r in train}),
        "training_pairs": len(train),
        "loss": "marginmse",
        "target_margin_delta": round(delta, 6),
        "delta_source": "median margin over fit cases THIS BASE already ranks first (Session J's "
                        "rule, recomputed per base exactly as session_j_finetune.py does)",
        "slate_cache": str(cpath.relative_to(REPO)).replace("\\", "/"),
        "hyperparameters": {"epochs": args.epochs, "lr": args.lr, "batch": args.batch,
                            "max_len": MAX_LEN, "seed": args.seed},
        "comparability_check": comparability,
        "session_j_recorded": recorded,
        "base_val_r_at_1": round(base_val, 4),
        "best_epoch": best["epoch"],
        "fit_val_r_at_1": round(best["val_r_at_1"], 4),
        "fit_val_history": history,
        "trained_on": "fit split only",
        "_export_gap": (
            "SELF-VALIDATED ONLY. A PyTorch-to-ONNX export produced in this session cannot be "
            "checked against an external authority. Digest pinning, torch-vs-ORT agreement, and "
            "per-graph determinism / batch / padding invariance are what stand behind it."
        ),
    }

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(io.open(MANIFEST, encoding="utf-8").read()) if MANIFEST.exists() else {
        "_what": "M0c Session M W1 — capacity at fixed fine-tuning. Models this arm trained. "
                 "Session J's manifest and Session M Phase 2's retrain-manifest.json are records "
                 "of other work and are not written to.",
        "models": [],
    }
    data["models"] = [m for m in data["models"] if m["name"] != name] + [meta]
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    out = OUT_DIR / f"capacity-train-{stem(args.base)}.json"
    out.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {out.relative_to(REPO)}")
    print(f"pinned {name} in {MANIFEST.relative_to(REPO)}  (digest {digest[:16]}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
