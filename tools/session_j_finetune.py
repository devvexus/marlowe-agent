"""Session J, Part 2 — fine-tune the cross-encoder on same-session hard negatives.

**Tempered on the record, before any number exists.** Capacity came back a null WITH POWER in
Session I (+0.0131 R@1, discordant 27, exact p = 0.7011), and fine-tuning is capacity-adjacent.
What it offers that depth does not is DOMAIN adaptation: an off-the-shelf reranker learned to
separate topically distinct web passages, and the failure here is separating turns inside one
conversation. Part 1 measured that gap precisely — the gold rate falls 50-fold across length bins
while the model's mean logit moves 2.6 — so there is a specific thing to train, not a hope that
more parameters help. **The research report's +0.06 to +0.10 projection is not inherited.**

## The comparability check, which runs before any training

The baseline every Session I and J number was measured on is a **Xenova ONNX export**. Fine-tuning
starts from the **`cross-encoder/...` PyTorch checkpoint** and ends in an ONNX graph *this script*
exports. Those are two different export paths, and if they disagree even before training then the
fine-tuning delta would conflate training with export.

So the UNTRAINED PyTorch checkpoint is exported first and scored against the Xenova baseline on the
same fit slates. Three outcomes, all handled rather than assumed:

  * **agrees** — the delta may be reported against the Xenova baseline;
  * **disagrees** — the delta is reported against the SELF-EXPORTED baseline instead, and the
    disagreement is published;
  * **fails to load or produces a degenerate score** — refused, and nothing is trained.

## The unvalidated-export gap, stated rather than closed

A PyTorch-to-ONNX export produced here is a second instance of the gap STATE.md carries. Unlike a
maintainer export it **cannot** be closed by an external authority, because none exists for a model
this session trained. It is **self-validated only**: torch-vs-ORT agreement on frozen pairs, plus
digest pinning, plus per-graph determinism, batch and padding invariance. That is a limitation, and
it is reported as one.

## The loss, and the deviation it carries

MarginMSE as published distils **teacher** margins. This project has no admitted stronger teacher —
capacity came back null, so calling any fetched model "stronger" would be unevidenced. The
**hard-label variant** is used: the (gold - negative) score gap is regressed toward a target margin
`delta`, and **`delta` is taken from the base model's own margin distribution on fit cases it
already ranks correctly**, so it is not chosen against the outcome. Recorded as a deviation in
`runs/session-j/PREREGISTRATION.json`.

    python tools/session_j_finetune.py --base ms-marco-MiniLM-L-6-v2
    python tools/session_j_finetune.py --base ms-marco-MiniLM-L-2-v2
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent

from reach_pools import turn_texts  # noqa: E402
from session_i_rerankers import MODELS_DIR, load  # noqa: E402
import session_j_models  # noqa: E402

OUT_DIR = REPO / "runs" / "session-j"
PAIRS = OUT_DIR / "training-pairs.jsonl"

HF_REPO = {
    "ms-marco-MiniLM-L-6-v2": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "ms-marco-MiniLM-L-2-v2": "cross-encoder/ms-marco-MiniLM-L-2-v2",
}

MAX_LEN = 256
SEED = 7


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


def export_onnx(model, tokenizer_dir: Path, out_path: Path) -> None:
    """Export to ONNX with the same input signature the loader feeds BY NAME.

    Dynamic batch and sequence axes, so padding invariance is testable at all. The shipped stage
    still runs `[1, 256]`; the graph merely does not forbid other shapes, which is what makes the
    ADR-015 padding check meaningful rather than vacuous.
    """
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


def slate_texts(cache: dict) -> list[tuple[str, str, str, bool]]:
    """(query_id, question, document, is_gold) for every cached slate candidate."""
    texts = turn_texts()
    out = []
    for qid, row in cache["rows"].items():
        per = texts.get(qid, {})
        for tid, gold in zip(row["turn_ids"], row["gold"]):
            out.append((qid, row.get("question", ""), per.get(tid, ""), gold))
    return out


def score_with_torch(model, tok, pairs, device, batch: int = 64) -> np.ndarray:
    import torch

    model.eval()
    scores = []
    with torch.no_grad():
        for i in range(0, len(pairs), batch):
            chunk = pairs[i:i + batch]
            enc = tok([q for q, _ in chunk], [d for _, d in chunk], padding="max_length",
                      truncation=True, max_length=MAX_LEN, return_tensors="pt").to(device)
            logits = model(**enc).logits.reshape(-1)
            scores.extend(logits.float().cpu().numpy().tolist())
    return np.asarray(scores)


def r_at_1_from_scores(cache: dict, scores_by_query: dict[str, np.ndarray]) -> float:
    hits = 0
    for qid, row in cache["rows"].items():
        s = scores_by_query[qid]
        order = np.argsort(-s, kind="stable")
        hits += bool(row["gold"][int(order[0])])
    return hits / len(cache["rows"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="ms-marco-MiniLM-L-6-v2", choices=sorted(HF_REPO))
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--classes", nargs="+", default=["all"])
    args = ap.parse_args()

    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    set_seed(SEED)
    has_cuda = cuda_ready()
    device = "cuda" if has_cuda else "cpu"
    print(f"device: {device}"
          + (f"  ({torch.cuda.get_device_name(0)})" if has_cuda else "  — CUDA NOT AVAILABLE"))

    cache_path = OUT_DIR / f"rerank-scores-fit-{args.base.replace('ms-marco-MiniLM-', '')}-f32-seq256.json"
    if not cache_path.exists():
        raise SystemExit(f"{cache_path.name} is missing. Run session_j_arm7.py on this model first "
                         "— the fit slates and the baseline scores come from it.")
    cache = json.loads(io.open(cache_path, encoding="utf-8").read())

    # ---- delta, from the BASE model's own margins on cases it already gets right ---------------
    margins = []
    for row in cache["rows"].values():
        s = np.array(row["scores"], float)
        order = np.argsort(-s, kind="stable")
        if row["gold"][int(order[0])]:
            margins.append(float(s[order[0]] - s[order[1]]))
    delta = float(np.median(margins))
    print(f"target margin delta = {delta:.4f}  (median over {len(margins)} fit cases the base "
          f"model already ranks correctly — NOT chosen against the outcome)")

    # ---- the comparability check, BEFORE training ---------------------------------------------
    repo_id = HF_REPO[args.base]
    print(f"\ncomparability check: {repo_id} (PyTorch) vs {args.base} (Xenova ONNX baseline)")
    tok = AutoTokenizer.from_pretrained(repo_id)
    model = AutoModelForSequenceClassification.from_pretrained(repo_id).to(device)

    texts = turn_texts()
    questions = {}
    split = json.loads(io.open(REPO / "tools" / "split.json", encoding="utf-8").read())
    raw = json.loads(io.open(REPO / split["corpus_path"], encoding="utf-8").read())
    for inst in raw:
        questions[str(inst["question_id"])] = str(inst["question"])

    eval_pairs, index = [], []
    for qid, row in cache["rows"].items():
        per = texts.get(qid, {})
        for j, tid in enumerate(row["turn_ids"]):
            eval_pairs.append((questions[qid], per.get(tid, "")))
            index.append((qid, j))

    torch_scores = score_with_torch(model, tok, eval_pairs, device)
    by_query: dict[str, np.ndarray] = {q: np.zeros(len(r["scores"])) for q, r in cache["rows"].items()}
    for (qid, j), s in zip(index, torch_scores):
        by_query[qid][j] = s

    onnx_flat = np.array([s for r in cache["rows"].values() for s in r["scores"]])
    torch_flat = np.array([by_query[q][j] for q, j in index])
    baseline_r1 = r_at_1_from_scores(cache, {q: np.array(r["scores"]) for q, r in cache["rows"].items()})
    torch_r1 = r_at_1_from_scores(cache, by_query)
    corr = float(np.corrcoef(onnx_flat, torch_flat)[0, 1])
    max_abs = float(np.abs(onnx_flat - torch_flat).max())

    print(f"  Xenova ONNX  R@1 {baseline_r1:.4f}")
    print(f"  PyTorch      R@1 {torch_r1:.4f}")
    print(f"  Pearson {corr:.6f}   max |delta logit| {max_abs:.6f}")
    agrees = bool(abs(torch_r1 - baseline_r1) < 1e-9 and max_abs < 0.01)
    print(f"  -> {'AGREE — the delta may be reported against the Xenova baseline' if agrees else 'DISAGREE — the delta will be reported against the SELF-EXPORTED baseline'}")

    comparability = {
        "xenova_onnx_r_at_1": round(baseline_r1, 4),
        "pytorch_r_at_1": round(torch_r1, 4),
        "pearson": round(corr, 6),
        "max_abs_logit_difference": round(max_abs, 6),
        "agree": agrees,
        "baseline_the_delta_is_reported_against": "xenova_onnx" if agrees else "self_export",
    }

    # ---- training data -------------------------------------------------------------------------
    rows = [json.loads(line) for line in io.open(PAIRS, encoding="utf-8") if line.strip()]
    if args.classes != ["all"]:
        rows = [r for r in rows if r["negative_class"] in args.classes]
    train = [r for r in rows if r["fold"] == "train"]
    val_queries = sorted({r["query_id"] for r in rows if r["fold"] == "val"})
    print(f"\ntraining pairs: {len(train)} (classes: {sorted({r['negative_class'] for r in train})})")
    print(f"validation: {len(val_queries)} fit queries, held apart BY CONVERSATION")

    val_cache = {"rows": {q: r for q, r in cache["rows"].items() if q in set(val_queries)}}
    print(f"  {len(val_cache['rows'])} of them have a reconstructed slate")

    def val_r1() -> float:
        pairs, idx = [], []
        for qid, row in val_cache["rows"].items():
            per = texts.get(qid, {})
            for j, tid in enumerate(row["turn_ids"]):
                pairs.append((questions[qid], per.get(tid, "")))
                idx.append((qid, j))
        s = score_with_torch(model, tok, pairs, device)
        bq = {q: np.zeros(len(r["scores"])) for q, r in val_cache["rows"].items()}
        for (qid, j), v in zip(idx, s):
            bq[qid][j] = v
        return r_at_1_from_scores(val_cache, bq)

    base_val = val_r1()
    print(f"  base model, fit-val R@1: {base_val:.4f}")

    # ---- train -----------------------------------------------------------------------------
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    loader = DataLoader(train, batch_size=args.batch, shuffle=True,
                        collate_fn=lambda b: b, generator=torch.Generator().manual_seed(SEED))
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
            # Hard-label MarginMSE: drive the gap to a FIXED target rather than to infinity.
            # Saturating the logits would destroy the margin calibration Part 3 reads.
            loss = torch.nn.functional.mse_loss(s_pos - s_neg,
                                                torch.full_like(s_pos, delta))
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
    if best["state"] is not None:
        model.load_state_dict(best["state"])

    # ---- export and pin ------------------------------------------------------------------------
    name = f"{args.base}-ft-session-j"
    directory = MODELS_DIR / name
    directory.mkdir(parents=True, exist_ok=True)
    model = model.to("cpu")
    export_onnx(model, directory, directory / "model.onnx")
    tok.backend_tokenizer.save(str(directory / "tokenizer.json"))

    # The PyTorch module the graph was exported FROM, saved beside it. This is what makes
    # `session_j_verify_export.py`'s torch-vs-ORT check runnable at all, and that check is the only
    # one of the five that speaks to the EXPORT rather than to the exported graph's behaviour.
    # Without it "self-validated" would mean nothing more than "the graph is deterministic".
    model.save_pretrained(str(directory / "pytorch-reference"))

    session_j_models.record(
        name, directory / "model.onnx", directory / "tokenizer.json",
        {
            "base": args.base, "hf_repo": repo_id, "arch": "BERT (fine-tuned, Session J)",
            "params_m": sum(p.numel() for p in model.parameters()) // 1_000_000,
            "max_seq": 512,
            "trained_on": "fit split only, same-session hard negatives",
            "loss": "hard-label MarginMSE",
            "target_margin_delta": round(delta, 6),
            "best_epoch": best["epoch"],
            "fit_val_r_at_1": round(best["val_r_at_1"], 4),
            "classes": args.classes,
            "_export_gap": (
                "SELF-VALIDATED ONLY. A PyTorch-to-ONNX export produced in this session cannot be "
                "checked against an external authority, because none exists for a model this "
                "session trained. Digest pinning, torch-vs-ORT fixture agreement, and per-graph "
                "determinism / batch / padding invariance are what stand behind it."
            ),
        },
    )

    out = OUT_DIR / f"finetune-{args.base.replace('ms-marco-MiniLM-', '')}-{'-'.join(args.classes)}.json"
    out.write_text(json.dumps({
        "_what": "Session J Part 2 — fine-tuning on same-session hard negatives.",
        "base": args.base, "hf_repo": repo_id, "device": device,
        "hyperparameters": {"epochs": args.epochs, "lr": args.lr, "batch": args.batch,
                            "max_len": MAX_LEN, "seed": SEED},
        "loss": {"form": "hard-label MarginMSE", "target_margin_delta": round(delta, 6),
                 "delta_source": "median margin over fit cases the BASE model already ranks first"},
        "negative_classes": args.classes,
        "training_pairs": len(train),
        "comparability_check": comparability,
        "fit_val_history": history,
        "best_epoch": best["epoch"],
        "exported_model": name,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {out.relative_to(REPO)}")
    print(f"pinned {name} in runs/session-j/finetuned-manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
