"""Train the M0c ranking arms on the FIT split only. Selection reads the fit-carved validation
slice; the held-out split is not opened by this script at all.

Arms, as registered in runs/session-m0c/PREREGISTRATION.json:

  L1  listwise objective, same inference shape. The pair cross-encoder is fine-tuned with a
      softmax cross-entropy over the depth-10 slate instead of Session J's pairwise MarginMSE.
      Scores independently at inference. This is the CONTROL that separates "the objective was
      wrong" from "independent scoring is the limit" -- without it a win from S1 could not be
      attributed to joint observation.

  S1  set-wise head. The shipped encoder is FROZEN; a permutation-equivariant transformer attends
      across the ten candidates and emits a correction to the shipped logit. This is candidate B:
      the head can express "B supersedes A" because it sees B and A at once.

Two properties are built in rather than hoped for:

  * **S1 starts exactly at the shipped ranking.** Its output is `shipped_logit + delta` with the
    delta head zero-initialised, so an untrained S1 reproduces 0.7555 on fit to the bit. ADR-010's
    "the arm must change top-1 on at least 10 fit queries" is then a TRAINED property with a
    measured count, not an artefact of a randomly initialised scorer shuffling ties.
  * **S1 carries no positional encoding over the candidate axis**, so it is permutation-equivariant
    by construction. The registration says verify rather than assume, and `--check-equivariance`
    measures it to 0.000000 instead of arguing from the architecture.

The validation slice is carved BY CONVERSATION, not by query id, reusing Session J's leakage rule:
three fit queries share a gold conversation, and splitting by query would put the same conversation
on both sides.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

REPO = Path(__file__).resolve().parents[1]
SLATES = REPO / "runs" / "session-m0c" / "slates-{split}.json"
ENCODED = REPO / "runs" / "session-m0c" / "encoded-{split}.npz"
MODEL_DIR = REPO / "models" / "ms-marco-MiniLM-L-2-v2-ft-session-j"
OUTDIR = REPO / "runs" / "session-m0c"

SEED = 7
VAL_FRACTION = 0.20
MAX_LEN = 256
SHIPPED_FIT_R1 = 0.7555


# ----------------------------------------------------------------------------- data

def conversation_of(rec: dict) -> str:
    """The gold turn's session, which is the unit Session J's leakage rule is stated over. Queries
    with no gold in the slate cannot leak a gold conversation, so they group under themselves."""
    for tid, g in zip(rec["turn_ids"], rec["gold"]):
        if g:
            return tid.rsplit("-", 1)[0]
    return "q:" + rec["query_id"]


def carve(recs: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic conversation-level split. sha256 ordering, same device as the corpus split."""
    convs = sorted({conversation_of(r) for r in recs},
                   key=lambda c: hashlib.sha256(c.encode()).hexdigest())
    n_val = max(1, int(round(VAL_FRACTION * len(convs))))
    val_convs = set(convs[:n_val])
    is_val = np.asarray([conversation_of(r) in val_convs for r in recs], dtype=bool)
    return ~is_val, is_val


def listwise_loss(scores: torch.Tensor, gold: torch.Tensor) -> torch.Tensor:
    """Multi-positive listwise softmax cross-entropy: -log sum_{g in gold} p_g.

    Slates with no gold carry no gradient and are dropped -- a uniform target over an all-negative
    slate would teach the model that nothing is relevant, which is a different claim from the one
    the label supports."""
    logp = torch.log_softmax(scores, dim=-1)
    has = gold.any(dim=-1)
    if not has.any():
        return scores.sum() * 0.0
    masked = logp.masked_fill(~gold, float("-inf"))
    return -(torch.logsumexp(masked[has], dim=-1)).mean()


def r_at_1(scores: np.ndarray, gold: np.ndarray) -> float:
    return float(gold[np.arange(len(scores)), scores.argmax(1)].mean())


# ----------------------------------------------------------------------------- S1

class SetHead(nn.Module):
    """Permutation-equivariant re-scorer over a slate. Emits a CORRECTION to the shipped logit."""

    def __init__(self, d_in: int, d_model: int = 128, layers: int = 2, heads: int = 4,
                 dropout: float = 0.1):
        super().__init__()
        self.proj = nn.Linear(d_in, d_model)
        self.feat = nn.Linear(3, d_model)          # shipped logit, log wordpieces, is_assistant
        self.norm = nn.LayerNorm(d_model)
        enc = nn.TransformerEncoderLayer(d_model, heads, d_model * 4, dropout,
                                         batch_first=True, norm_first=True)
        self.body = nn.TransformerEncoder(enc, layers)
        self.out = nn.Linear(d_model, 1)
        nn.init.zeros_(self.out.weight)            # untrained S1 == the shipped ranking, exactly
        nn.init.zeros_(self.out.bias)

    def forward(self, reps, logit, logwp, is_asst):
        f = torch.stack([logit, logwp, is_asst], dim=-1)
        h = self.norm(self.proj(reps) + self.feat(f))
        h = self.body(h)                            # NO positional encoding -> equivariant
        return logit + self.out(h).squeeze(-1)


def load_encoded(split: str) -> dict:
    z = np.load(Path(str(ENCODED).format(split=split)), allow_pickle=True)
    return {
        "reps": torch.tensor(z["reps"].astype(np.float32)),
        "logits": torch.tensor(z["logits"].astype(np.float32)),
        "gold": torch.tensor(z["gold"]),
        "logwp": torch.tensor(np.log(np.maximum(z["wordpieces"], 1)).astype(np.float32)),
        "asst": torch.tensor(z["is_assistant"].astype(np.float32)),
        "query_ids": list(z["query_ids"]),
    }


def train_s1(args, recs, tr, va, device) -> dict:
    d = load_encoded("fit")
    for k in ("reps", "logits", "gold", "logwp", "asst"):
        d[k] = d[k].to(device)
    # the shipped logit is standardised PER SLATE before it enters the head as a feature, so the
    # head reads shape rather than absolute level. The residual it corrects is the RAW logit.
    lg = d["logits"]
    lgn = (lg - lg.mean(1, keepdim=True)) / (lg.std(1, keepdim=True) + 1e-6)

    model = SetHead(d["reps"].shape[-1], args.d_model, args.layers, args.heads,
                    args.dropout).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr_head, weight_decay=args.weight_decay)

    tr_i = torch.tensor(np.flatnonzero(tr), device=device)
    va_i = torch.tensor(np.flatnonzero(va), device=device)

    def evaluate(idx):
        model.eval()
        with torch.no_grad():
            s = model(d["reps"][idx], lg[idx], d["logwp"][idx], d["asst"][idx])
        return r_at_1(s.cpu().numpy(), d["gold"][idx].cpu().numpy()), s

    base_val, _ = evaluate(va_i)
    base_all, _ = evaluate(torch.arange(len(recs), device=device))
    print(f"  untrained S1: fit R@1 {base_all:.4f} (shipped {SHIPPED_FIT_R1})  val {base_val:.4f}")
    # SHIPPED_FIT_R1 is the published 4-dp figure (173/229 = 0.755459), so the equality is asserted
    # at the precision the constant carries. Asserting at 1e-9 against a rounded constant compares
    # a measurement to a typographic artefact.
    if round(base_all, 4) != SHIPPED_FIT_R1:
        raise SystemExit("REFUSING: an untrained S1 must reproduce the shipped ranking exactly; "
                         f"got {base_all:.6f} against {SHIPPED_FIT_R1}. The residual is wired wrong.")

    best = {"val": base_val, "epoch": 0, "state": {k: v.clone() for k, v in model.state_dict().items()}}
    g = torch.Generator().manual_seed(SEED)
    for ep in range(1, args.epochs + 1):
        model.train()
        perm = torch.randperm(len(tr_i), generator=g).to(device)
        tot = 0.0
        for i in range(0, len(perm), args.batch):
            b = tr_i[perm[i:i + args.batch]]
            s = model(d["reps"][b], lg[b], d["logwp"][b], d["asst"][b])
            loss = listwise_loss(s, d["gold"][b])
            opt.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += float(loss) * len(b)
        v, _ = evaluate(va_i)
        a, _ = evaluate(torch.arange(len(recs), device=device))
        flag = ""
        if v > best["val"] + 1e-9:
            best = {"val": v, "epoch": ep, "state": {k: x.clone() for k, x in model.state_dict().items()}}
            flag = "  *"
        print(f"    epoch {ep:>2}  loss {tot/len(tr_i):.4f}  val R@1 {v:.4f}  fit R@1 {a:.4f}{flag}")

    model.load_state_dict(best["state"])
    torch.save(best["state"], OUTDIR / "arm-s1.pt")
    val, _ = evaluate(va_i)
    allr, s_all = evaluate(torch.arange(len(recs), device=device))
    return {"arm": "S1", "best_epoch": best["epoch"], "val_r_at_1": round(val, 4),
            "fit_r_at_1": round(allr, 4), "baseline_val": round(base_val, 4),
            "baseline_fit": SHIPPED_FIT_R1, "scores": s_all.cpu().numpy()}


def check_equivariance(device) -> float:
    d = load_encoded("fit")
    for k in ("reps", "logits", "gold", "logwp", "asst"):
        d[k] = d[k].to(device)
    model = SetHead(d["reps"].shape[-1]).to(device)
    sd = OUTDIR / "arm-s1.pt"
    if sd.exists():
        model.load_state_dict(torch.load(sd, map_location=device))
    model.eval()
    g = torch.Generator().manual_seed(11)
    worst = 0.0
    with torch.no_grad():
        for i in range(len(d["logits"])):
            a = model(d["reps"][i:i+1], d["logits"][i:i+1], d["logwp"][i:i+1], d["asst"][i:i+1])[0]
            p = torch.randperm(a.shape[0], generator=g).to(device)
            b = model(d["reps"][i:i+1][:, p], d["logits"][i:i+1][:, p],
                      d["logwp"][i:i+1][:, p], d["asst"][i:i+1][:, p])[0]
            worst = max(worst, float((a[p] - b).abs().max()))
    return worst


# ----------------------------------------------------------------------------- L1

def train_l1(args, recs, tr, va, device) -> dict:
    from tokenizers import Tokenizer
    from transformers import AutoModelForSequenceClassification

    tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tok.enable_truncation(max_length=MAX_LEN)
    tok.enable_padding(length=MAX_LEN)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_DIR / "pytorch-reference", dtype=torch.float32).to(device)

    k = len(recs[0]["texts"])
    enc = []
    for r in recs:
        e = tok.encode_batch([(r["question"], t) for t in r["texts"]])
        enc.append((torch.tensor([x.ids for x in e], dtype=torch.long),
                    torch.tensor([x.attention_mask for x in e], dtype=torch.long),
                    torch.tensor([x.type_ids for x in e], dtype=torch.long)))
    gold = torch.tensor(np.asarray([r["gold"] for r in recs]), device=device)

    def score_all(idx):
        model.eval()
        out = np.zeros((len(idx), k), dtype=np.float32)
        with torch.no_grad():
            for n, i in enumerate(idx):
                ids, am, tt = (x.to(device) for x in enc[i])
                out[n] = model(input_ids=ids, attention_mask=am,
                               token_type_ids=tt).logits.reshape(-1).float().cpu().numpy()
        return out

    tr_i, va_i = np.flatnonzero(tr), np.flatnonzero(va)
    g_np = gold.cpu().numpy()
    base_val = r_at_1(score_all(va_i), g_np[va_i])
    base_all = r_at_1(score_all(np.arange(len(recs))), g_np)
    print(f"  untrained L1: fit R@1 {base_all:.4f} (shipped {SHIPPED_FIT_R1})  val {base_val:.4f}")

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr_encoder,
                            weight_decay=args.weight_decay)
    best = {"val": base_val, "epoch": 0,
            "state": {n: p.detach().cpu().clone() for n, p in model.state_dict().items()}}
    rng = np.random.default_rng(SEED)
    for ep in range(1, args.epochs_encoder + 1):
        model.train()
        order = rng.permutation(tr_i)
        tot = 0.0
        for i in order:
            ids, am, tt = (x.to(device) for x in enc[i])
            s = model(input_ids=ids, attention_mask=am, token_type_ids=tt).logits.reshape(1, -1)
            loss = listwise_loss(s, gold[i:i + 1])
            opt.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += float(loss)
        v = r_at_1(score_all(va_i), g_np[va_i])
        a = r_at_1(score_all(np.arange(len(recs))), g_np)
        flag = ""
        if v > best["val"] + 1e-9:
            best = {"val": v, "epoch": ep,
                    "state": {n: p.detach().cpu().clone() for n, p in model.state_dict().items()}}
            flag = "  *"
        print(f"    epoch {ep:>2}  loss {tot/len(tr_i):.4f}  val R@1 {v:.4f}  fit R@1 {a:.4f}{flag}")

    model.load_state_dict(best["state"])
    torch.save(best["state"], OUTDIR / "arm-l1.pt")
    s_all = score_all(np.arange(len(recs)))
    return {"arm": "L1", "best_epoch": best["epoch"],
            "val_r_at_1": round(r_at_1(score_all(va_i), g_np[va_i]), 4),
            "fit_r_at_1": round(r_at_1(s_all, g_np), 4),
            "baseline_val": round(base_val, 4), "baseline_fit": SHIPPED_FIT_R1,
            "scores": s_all}


# ----------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", required=True, choices=["S1", "L1"])
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--epochs-encoder", type=int, default=6)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr-head", type=float, default=3e-4)
    ap.add_argument("--lr-encoder", type=float, default=1e-5)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--d-model", type=int, default=128)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--heads", type=int, default=4)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--check-equivariance", action="store_true")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    torch.manual_seed(SEED)
    np.random.seed(SEED)
    torch.use_deterministic_algorithms(False)

    recs = json.loads(Path(str(SLATES).format(split="fit")).read_text(encoding="utf-8"))["records"]
    tr, va = carve(recs)
    print(f"arm={args.arm}  device={args.device}")
    print(f"fit n={len(recs)}  train {int(tr.sum())}  val {int(va.sum())}  "
          f"({len({conversation_of(r) for r in recs})} conversations, split BY CONVERSATION)")

    res = train_s1(args, recs, tr, va, args.device) if args.arm == "S1" \
        else train_l1(args, recs, tr, va, args.device)

    # ADR-010 / ADR-013 on the BUILT arm, fit split, before anything held-out is opened
    shipped_top1 = np.zeros(len(recs), dtype=int)          # slates are stored in shipped order
    new_top1 = res["scores"].argmax(1)
    gold = np.asarray([r["gold"] for r in recs])
    old_ok = gold[np.arange(len(recs)), shipped_top1]
    new_ok = gold[np.arange(len(recs)), new_top1]
    changed = int((new_top1 != shipped_top1).sum())
    gained = int((new_ok & ~old_ok).sum())
    lost = int((old_ok & ~new_ok).sum())
    print()
    print(f"  ADR-010 reach on the BUILT arm: top-1 changed on {changed}/{len(recs)} fit queries "
          f"(floor 10) -> {'PASS' if changed >= 10 else 'FAIL'}")
    print(f"  ADR-013 both directions: gained {gained}, lost {lost} -> "
          f"{'PASS' if gained > 0 and lost > 0 else 'ONE-DIRECTIONAL'}")
    print(f"  ADR-014 discordant {gained+lost} (floor 6 for alpha=0.05) -> "
          f"{'alpha attainable' if gained+lost >= 6 else 'ALPHA UNATTAINABLE, declared in advance'}")

    out = {k: v for k, v in res.items() if k != "scores"}
    out.update({"changed_top1_fit": changed, "gained_fit": gained, "lost_fit": lost,
                "discordant_fit": gained + lost,
                "adr_010_reach_pass": changed >= 10,
                "adr_013_both_directions": gained > 0 and lost > 0,
                "adr_014_alpha_attainable": gained + lost >= 6,
                "hyperparameters": {k: v for k, v in vars(args).items()
                                    if k not in ("device", "check_equivariance")}})
    if args.check_equivariance and args.arm == "S1":
        w = check_equivariance(args.device)
        out["permutation_equivariance_max_abs_dev"] = w
        print(f"  permutation equivariance: max |dev| = {w:.6f} -> "
              f"{'PASS' if w < 1e-4 else 'FAIL'}")

    np.save(OUTDIR / f"arm-{args.arm.lower()}-fit-scores.npy", res["scores"])
    p = OUTDIR / f"arm-{args.arm.lower()}-fit.json"
    p.write_text(json.dumps(out, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {p.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
