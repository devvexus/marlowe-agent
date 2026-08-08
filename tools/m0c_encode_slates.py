"""Precompute pair-encoder representations for every slate, and CHECK them against the shipped
ONNX logits on the way past.

The set-wise head (arm S1) attends across candidates over the frozen encoder's per-candidate
representation. That representation has to come from somewhere, and the only honest somewhere is
the same weights the shipped graph runs. So this script runs the PyTorch reference checkpoint over
every slate pair and, before writing anything, asserts that its logits reproduce the ONNX logits
already cached in runs/session-j/rerank-scores-*.json.

**That assertion is the point, not a formality.** A representation extracted from a checkpoint that
scores differently from the shipped graph would train a head against a scorer that does not exist,
and every downstream number would be internally consistent and wrong -- the Session K defect exactly.
CLAUDE.md pins the tolerance context: `ort` builds at Level1 and Python's ORT default fuses
differently, worth 0.0699 logits on this family. This path is torch, not ORT, so the comparison is
torch-vs-ORT and Session J measured that at 1e-6 on the same checkpoint.

Writes runs/session-m0c/encoded-{split}.npz  (float16 reps, float32 logits) and a JSON verdict.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from tokenizers import Tokenizer
from transformers import AutoModelForSequenceClassification

REPO = Path(__file__).resolve().parents[1]
SLATES = REPO / "runs" / "session-m0c" / "slates-{split}.json"
MODEL_DIR = REPO / "models" / "ms-marco-MiniLM-L-2-v2-ft-session-j"
OUT = REPO / "runs" / "session-m0c" / "encoded-{split}.npz"
VERDICT = REPO / "runs" / "session-m0c" / "encode-verification.json"

MAX_LEN = 256          # ADR-015: the shipped pair encoder's sequence length. Not a knob.
TORCH_VS_ORT_TOL = 1e-3  # Session J measured 1e-6; 1e-3 is the reporting gate, and the MEASURED
                         # max is printed so a drift toward the gate is visible rather than hidden.


def build(device: str):
    """The tokenizer is the raw `tokenizers.Tokenizer`, configured exactly as
    `spike_cross_encoder.encode` configures it. This is not interchangeable with
    `PreTrainedTokenizerFast` over the same tokenizer.json: the wrapper was tried first and
    produced logits up to **3.56** from the shipped graph's on identical text, which the
    verification below refused. Same file, same vocabulary, different encoding -- and the scores it
    produced were entirely plausible. Use the tokenizer the scored path uses."""
    tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tok.enable_truncation(max_length=MAX_LEN)
    tok.enable_padding(length=MAX_LEN)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_DIR / "pytorch-reference", dtype=torch.float32,
    ).to(device).eval()
    return tok, model


def encode_pairs(tok, queries: list[str], docs: list[str], device: str) -> dict:
    encs = tok.encode_batch(list(zip(queries, docs)))
    return {
        "input_ids": torch.tensor([e.ids for e in encs], dtype=torch.long, device=device),
        "attention_mask": torch.tensor([e.attention_mask for e in encs], dtype=torch.long,
                                       device=device),
        "token_type_ids": torch.tensor([e.type_ids for e in encs], dtype=torch.long, device=device),
    }


@torch.no_grad()
def encode_split(split: str, tok, model, device: str, batch: int) -> dict:
    d = json.loads(Path(str(SLATES).format(split=split)).read_text(encoding="utf-8"))
    recs = d["records"]
    n, k = len(recs), len(recs[0]["texts"])

    pairs_q, pairs_t, want = [], [], []
    for r in recs:
        for j in range(k):
            pairs_q.append(r["question"])
            pairs_t.append(r["texts"][j])
            want.append(r["rerank_scores"][j])
    want = np.asarray(want, dtype=np.float64)

    logits = np.zeros(len(pairs_q), dtype=np.float32)
    reps = np.zeros((len(pairs_q), model.config.hidden_size), dtype=np.float16)
    for i in range(0, len(pairs_q), batch):
        enc = encode_pairs(tok, pairs_q[i:i + batch], pairs_t[i:i + batch], device)
        out = model.bert(**enc)
        pooled = out.pooler_output                       # [B, 384] -- what the classifier reads
        lg = model.classifier(model.dropout(pooled)).squeeze(-1)
        logits[i:i + batch] = lg.float().cpu().numpy()
        reps[i:i + batch] = pooled.half().cpu().numpy()

    err = np.abs(logits.astype(np.float64) - want)
    verdict = {
        "split": split, "pairs": int(len(pairs_q)),
        "max_abs_err_torch_vs_onnx": float(err.max()),
        "mean_abs_err": float(err.mean()),
        "p99_abs_err": float(np.quantile(err, 0.99)),
        "tolerance": TORCH_VS_ORT_TOL,
        "pass": bool(err.max() <= TORCH_VS_ORT_TOL),
    }
    print(f"  {split}: {len(pairs_q)} pairs   max|torch-onnx| = {err.max():.6f}  "
          f"mean {err.mean():.6f}   {'PASS' if verdict['pass'] else 'FAIL'}")
    if not verdict["pass"]:
        raise SystemExit(
            f"REFUSING to write {split}: the PyTorch checkpoint does not reproduce the shipped "
            f"ONNX logits (max {err.max():.6f} > {TORCH_VS_ORT_TOL}). A head trained on these "
            f"representations would be trained against a scorer that is not the one shipped."
        )

    # rank-1 agreement is the read that actually matters, checked separately from the logit norm
    lg = logits.reshape(n, k)
    wt = want.reshape(n, k)
    same_top1 = int((lg.argmax(1) == wt.argmax(1)).sum())
    verdict["top1_agreement"] = f"{same_top1}/{n}"
    print(f"           top-1 agreement {same_top1}/{n}")
    if same_top1 != n:
        raise SystemExit("REFUSING: top-1 disagrees on at least one slate despite a passing "
                         "logit tolerance. The ranking is the read; the norm is not.")

    out = Path(str(OUT).format(split=split))
    np.savez_compressed(
        out,
        reps=reps.reshape(n, k, -1),
        logits=lg,
        gold=np.asarray([r["gold"] for r in recs], dtype=bool),
        wordpieces=np.asarray([r["wordpieces"] for r in recs], dtype=np.int32),
        is_assistant=np.asarray([[x == "assistant" for x in r["roles"]] for r in recs], dtype=bool),
        query_ids=np.asarray([r["query_id"] for r in recs]),
    )
    print(f"           -> {out.relative_to(REPO)}  ({out.stat().st_size/1e6:.1f} MB)")
    return verdict


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--splits", nargs="+", default=["fit", "heldout"])
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    torch.manual_seed(7)
    print(f"device={args.device}  model={MODEL_DIR.name}  max_len={MAX_LEN}")
    tok, model = build(args.device)
    verdicts = [encode_split(s, tok, model, args.device, args.batch) for s in args.splits]

    VERDICT.write_text(json.dumps({
        "_what": "torch reference vs shipped ONNX logits, checked before any head is trained",
        "_why": "a head trained on representations from a checkpoint that scores differently from "
                "the shipped graph would be trained against a scorer that does not exist",
        "model": MODEL_DIR.name,
        "max_len": MAX_LEN,
        "splits": verdicts,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {VERDICT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
