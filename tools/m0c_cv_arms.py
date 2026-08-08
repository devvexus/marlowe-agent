"""Nested cross-validation over the FIT split, producing out-of-fold scores for all 229 fit
queries. This is the selection instrument; the held-out split is not opened by this script.

**Why this replaces the single 46-case validation slice.** The first pass carved one 20% slice and
selected on it. S1 read 0.8261 and L1 0.8043 there -- 38 against 37 of 46 queries. ADR-012's rule
is that a band an order of magnitude narrower than the instrument's resolution cannot be read, and
one case out of 46 is exactly that. Five-fold CV by conversation gives an out-of-fold prediction
for every fit query, so selection reads n = 229 instead of n = 46, at no cost in discipline: no
query is ever scored by a model that saw it.

Epoch selection is nested. Inside each outer fold an inner validation slice is carved from that
fold's training portion and used for early stopping, so the outer fold stays untouched until it is
predicted. The number of epochs is therefore chosen by data rather than by a constant somebody
picked, which is ADR-013's second lesson -- a registration that fixes the bands but leaves a free
hyperparameter has not fixed the experiment.

Arms:
  S1   frozen shipped encoder + permutation-equivariant set head over the ten candidates.
  L1   encoder fine-tuned with the listwise objective; scores independently at inference.
  LS1  both: the encoder is fine-tuned AND the set head sits on top, trained jointly. This is the
       full candidate-B shape -- token-level encoding adapted to the task, plus joint observation
       of the slate.

Every arm emits `shipped_logit + delta`, so an untrained arm reproduces the shipped ranking
exactly and every reported movement is trained movement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
MAX_LEN = 256
FOLDS = 5
INNER_VAL_FRACTION = 0.20
SHIPPED_FIT_R1 = 0.7555


def conversation_of(rec: dict) -> str:
    for tid, g in zip(rec["turn_ids"], rec["gold"]):
        if g:
            return tid.rsplit("-", 1)[0]
    return "q:" + rec["query_id"]


def fold_assignment(recs: list[dict], folds: int) -> np.ndarray:
    """Conversation -> fold, by sha256 order. Deterministic and independent of record order."""
    convs = sorted({conversation_of(r) for r in recs},
                   key=lambda c: hashlib.sha256(c.encode()).hexdigest())
    fold_of = {c: i % folds for i, c in enumerate(convs)}
    return np.asarray([fold_of[conversation_of(r)] for r in recs], dtype=int)


def inner_split(idx: np.ndarray, recs: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    convs = sorted({conversation_of(recs[i]) for i in idx},
                   key=lambda c: hashlib.sha256(("inner:" + c).encode()).hexdigest())
    n_val = max(1, int(round(INNER_VAL_FRACTION * len(convs))))
    val = set(convs[:n_val])
    m = np.asarray([conversation_of(recs[i]) in val for i in idx], dtype=bool)
    return idx[~m], idx[m]


def listwise_loss(scores: torch.Tensor, gold: torch.Tensor) -> torch.Tensor:
    logp = torch.log_softmax(scores, dim=-1)
    has = gold.any(dim=-1)
    if not has.any():
        return scores.sum() * 0.0
    return -(torch.logsumexp(logp.masked_fill(~gold, float("-inf"))[has], dim=-1)).mean()


def r_at_1(scores: np.ndarray, gold: np.ndarray) -> float:
    return float(gold[np.arange(len(scores)), scores.argmax(1)].mean())


class SetHead(nn.Module):
    def __init__(self, d_in: int, d_model: int, layers: int, heads: int, dropout: float):
        super().__init__()
        self.proj = nn.Linear(d_in, d_model)
        self.feat = nn.Linear(3, d_model)
        self.norm = nn.LayerNorm(d_model)
        enc = nn.TransformerEncoderLayer(d_model, heads, d_model * 4, dropout,
                                         batch_first=True, norm_first=True)
        self.body = nn.TransformerEncoder(enc, layers)
        self.out = nn.Linear(d_model, 1)
        nn.init.zeros_(self.out.weight)
        nn.init.zeros_(self.out.bias)

    def forward(self, reps, logit, logwp, is_asst):
        lgn = (logit - logit.mean(1, keepdim=True)) / (logit.std(1, keepdim=True) + 1e-6)
        f = torch.stack([lgn, logwp, is_asst], dim=-1)
        h = self.norm(self.proj(reps) + self.feat(f))
        return logit + self.out(self.body(h)).squeeze(-1)


class Arm(nn.Module):
    """One object for all three arms. `tune_encoder` and `use_head` are what distinguish them."""

    def __init__(self, args, tune_encoder: bool, use_head: bool, device: str):
        super().__init__()
        self.tune_encoder, self.use_head, self.device = tune_encoder, use_head, device
        self.encoder = None
        if tune_encoder:
            from transformers import AutoModelForSequenceClassification
            self.encoder = AutoModelForSequenceClassification.from_pretrained(
                MODEL_DIR / "pytorch-reference", dtype=torch.float32)
        self.head = SetHead(384, args.d_model, args.layers, args.heads,
                            args.dropout) if use_head else None

    def slate_scores(self, batch) -> torch.Tensor:
        """batch: dict of stacked per-slate tensors, first dim = slates, second = candidates."""
        b, k = batch["logwp"].shape
        if self.tune_encoder:
            out = self.encoder.bert(input_ids=batch["ids"].view(b * k, -1),
                                    attention_mask=batch["am"].view(b * k, -1),
                                    token_type_ids=batch["tt"].view(b * k, -1))
            pooled = out.pooler_output
            logit = self.encoder.classifier(self.encoder.dropout(pooled)).view(b, k)
            reps = pooled.view(b, k, -1)
        else:
            logit, reps = batch["logits"], batch["reps"]
        if self.use_head:
            return self.head(reps, logit, batch["logwp"], batch["asst"])
        return logit


def build_batches(recs, encoded, tokenized, idx, device, tune_encoder):
    out = []
    for i in idx:
        d = {"logwp": torch.tensor(np.log(np.maximum(encoded["wordpieces"][i], 1)),
                                   dtype=torch.float32, device=device).unsqueeze(0),
             "asst": torch.tensor(encoded["is_assistant"][i].astype(np.float32),
                                  device=device).unsqueeze(0),
             "gold": torch.tensor(encoded["gold"][i], device=device).unsqueeze(0),
             "logits": torch.tensor(encoded["logits"][i], device=device).unsqueeze(0),
             "reps": torch.tensor(encoded["reps"][i].astype(np.float32),
                                  device=device).unsqueeze(0)}
        if tune_encoder:
            ids, am, tt = tokenized[i]
            d |= {"ids": ids.to(device).unsqueeze(0), "am": am.to(device).unsqueeze(0),
                  "tt": tt.to(device).unsqueeze(0)}
        out.append(d)
    return out


def run_fold(args, recs, encoded, tokenized, tr_idx, te_idx, device, spec) -> tuple[np.ndarray, int]:
    torch.manual_seed(SEED)
    arm = Arm(args, spec["tune_encoder"], spec["use_head"], device).to(device)
    inner_tr, inner_va = inner_split(tr_idx, recs)

    params = []
    if spec["tune_encoder"]:
        params.append({"params": arm.encoder.parameters(), "lr": args.lr_encoder})
    if spec["use_head"]:
        params.append({"params": arm.head.parameters(), "lr": args.lr_head})
    opt = torch.optim.AdamW(params, weight_decay=args.weight_decay)

    b_tr = build_batches(recs, encoded, tokenized, inner_tr, device, spec["tune_encoder"])
    b_va = build_batches(recs, encoded, tokenized, inner_va, device, spec["tune_encoder"])
    b_te = build_batches(recs, encoded, tokenized, te_idx, device, spec["tune_encoder"])

    def predict(batches):
        arm.eval()
        with torch.no_grad():
            return np.concatenate([arm.slate_scores(b).cpu().numpy() for b in batches], axis=0)

    gold_va = encoded["gold"][inner_va]
    best = {"val": r_at_1(predict(b_va), gold_va), "epoch": 0,
            "state": {k: v.detach().cpu().clone() for k, v in arm.state_dict().items()}}
    rng = np.random.default_rng(SEED)
    for ep in range(1, args.epochs + 1):
        arm.train()
        for j in rng.permutation(len(b_tr)):
            b = b_tr[j]
            loss = listwise_loss(arm.slate_scores(b), b["gold"])
            opt.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(arm.parameters(), 1.0)
            opt.step()
        v = r_at_1(predict(b_va), gold_va)
        if v > best["val"] + 1e-9:
            best = {"val": v, "epoch": ep,
                    "state": {k: x.detach().cpu().clone() for k, x in arm.state_dict().items()}}
    arm.load_state_dict(best["state"])
    return predict(b_te), best["epoch"]


def load_all(split: str):
    recs = json.loads(Path(str(SLATES).format(split=split)).read_text(encoding="utf-8"))["records"]
    z = np.load(Path(str(ENCODED).format(split=split)), allow_pickle=True)
    encoded = {k: z[k] for k in ("reps", "logits", "gold", "wordpieces", "is_assistant")}
    return recs, encoded


def tokenize(recs):
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tok.enable_truncation(max_length=MAX_LEN)
    tok.enable_padding(length=MAX_LEN)
    out = []
    for r in recs:
        e = tok.encode_batch([(r["question"], t) for t in r["texts"]])
        out.append((torch.tensor([x.ids for x in e], dtype=torch.long),
                    torch.tensor([x.attention_mask for x in e], dtype=torch.long),
                    torch.tensor([x.type_ids for x in e], dtype=torch.long)))
    return out


ARMS = {
    "S1":  {"tune_encoder": False, "use_head": True},
    "L1":  {"tune_encoder": True,  "use_head": False},
    "LS1": {"tune_encoder": True,  "use_head": True},
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arms", nargs="+", default=["S1", "L1", "LS1"])
    ap.add_argument("--folds", type=int, default=FOLDS)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--lr-head", type=float, default=3e-4)
    ap.add_argument("--lr-encoder", type=float, default=1e-5)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--d-model", type=int, default=128)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--heads", type=int, default=4)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--tag", default="")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    torch.manual_seed(SEED)
    np.random.seed(SEED)
    recs, encoded = load_all("fit")
    n = len(recs)
    folds = fold_assignment(recs, args.folds)
    need_tok = any(ARMS[a]["tune_encoder"] for a in args.arms)
    tokenized = tokenize(recs) if need_tok else None

    print(f"device={args.device}  fit n={n}  folds={args.folds} (by conversation)  "
          f"epochs<={args.epochs}")
    print(f"fold sizes: {np.bincount(folds).tolist()}")
    print(f"shipped fit R@1 = {SHIPPED_FIT_R1}\n")

    gold = encoded["gold"]
    results = {}
    for name in args.arms:
        spec = ARMS[name]
        oof = np.zeros((n, gold.shape[1]), dtype=np.float32)
        eps = []
        for f in range(args.folds):
            te = np.flatnonzero(folds == f)
            tr = np.flatnonzero(folds != f)
            s, ep = run_fold(args, recs, encoded, tokenized, tr, te, args.device, spec)
            oof[te] = s
            eps.append(ep)
            print(f"  {name} fold {f}: train {len(tr)} test {len(te)}  best epoch {ep}  "
                  f"fold R@1 {r_at_1(s, gold[te]):.4f} (shipped "
                  f"{r_at_1(encoded['logits'][te], gold[te]):.4f})")

        oof_r1 = r_at_1(oof, gold)
        base_r1 = r_at_1(encoded["logits"], gold)
        new_top1, old_top1 = oof.argmax(1), encoded["logits"].argmax(1)
        new_ok = gold[np.arange(n), new_top1]
        old_ok = gold[np.arange(n), old_top1]
        gained = int((new_ok & ~old_ok).sum())
        lost = int((old_ok & ~new_ok).sum())
        disc = gained + lost
        p = (min(1.0, 2.0 * sum(math.comb(disc, i) for i in range(min(gained, lost) + 1))
                 / 2 ** disc) if disc else float("nan"))
        print(f"  {name}: OUT-OF-FOLD R@1 {oof_r1:.4f}  vs shipped {base_r1:.4f}  "
              f"delta {oof_r1-base_r1:+.4f}")
        print(f"       changed top-1 {int((new_top1!=old_top1).sum())}  "
              f"gained {gained} lost {lost} discordant {disc}  exact McNemar p={p:.4f}  "
              f"alpha {'attainable' if disc>=6 else 'UNATTAINABLE'}  epochs {eps}\n")
        np.save(OUTDIR / f"oof-{name.lower()}{args.tag}.npy", oof)
        results[name] = {"oof_r_at_1": round(oof_r1, 4), "shipped_r_at_1": round(base_r1, 4),
                         "delta": round(oof_r1 - base_r1, 4),
                         "changed_top1": int((new_top1 != old_top1).sum()),
                         "gained": gained, "lost": lost, "discordant": disc,
                         "exact_mcnemar_p": round(p, 4) if disc else None,
                         "alpha_attainable": disc >= 6, "best_epochs_per_fold": eps,
                         "median_best_epoch": int(np.median(eps))}

    out = {"_what": "nested 5-fold CV over the fit split; out-of-fold R@1 on all 229 fit queries",
           "_why": "a 46-case validation slice cannot resolve the differences being selected on "
                   "(ADR-012). No query is scored by a model that saw it.",
           "n": n, "folds": args.folds, "shipped_fit_r_at_1": SHIPPED_FIT_R1,
           "hyperparameters": {k: v for k, v in vars(args).items() if k != "device"},
           "arms": results}
    p_out = OUTDIR / f"cv-arms{args.tag}.json"
    p_out.write_text(json.dumps(out, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"wrote {p_out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
