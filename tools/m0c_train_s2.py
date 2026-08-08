"""Arm S2 -- the global cross-encoder over the top-k, with token-level cross-talk.

This is candidate B in its strongest form and the last registered arm. S1 gave a set head only the
384-dimensional POOLED vector per candidate, which is an information bottleneck exactly where the
measured failure lives: R4 found the gold and the wrong rank 1 are typically two USER turns in the
same session several exchanges apart, both topically on-target, differing in a specific detail. A
pooled relevance summary has already thrown that detail away. S2 keeps it:

    [CLS] Q [SEP] T_1 [SEP] T_2 [SEP] T_3 [SEP] T_4 [SEP]

so self-attention can compare candidate tokens against each other directly. k = 4 is fixed in
advance and not swept -- 89% of held-out recoverable gold sits at rank <= 4, and ADR-013's second
lesson is that a registration leaving a free hyperparameter has not fixed the experiment.

Candidates below rank 4 keep their shipped order beneath the re-scored head, so S2 can only
reorder the region it sees.

Scores are read from each candidate's LEADING [SEP] position. Using the [CLS] alone cannot work --
one vector cannot carry four scores -- and mean-pooling each segment would discard the positional
information that tells the model which segment it is scoring.

Selection is 5-fold cross-validation by conversation over the fit split, the same instrument the
other three arms were judged on. The held-out split is not opened here.
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
SLATES = REPO / "runs" / "session-m0c" / "slates-fit.json"
MODEL_DIR = REPO / "models" / "ms-marco-MiniLM-L-2-v2-ft-session-j"
OUTDIR = REPO / "runs" / "session-m0c"

SEED = 7
K = 4                    # fixed in advance; 89% of recoverable gold sits at rank <= 4
MAX_LEN = 512            # a NEW graph of a different shape, not MAX_SEQ_LEN raised on the pair
                         # encoder -- that is the closed item and the pair encoder stays at 256
PER_CAND = 112           # 512 - CLS - query - 5 SEPs, divided four ways
FOLDS = 5
INNER_VAL_FRACTION = 0.20
SHIPPED_FIT_R1 = 0.7555


def conversation_of(rec):
    for tid, g in zip(rec["turn_ids"], rec["gold"]):
        if g:
            return tid.rsplit("-", 1)[0]
    return "q:" + rec["query_id"]


def fold_assignment(recs, folds):
    convs = sorted({conversation_of(r) for r in recs},
                   key=lambda c: hashlib.sha256(c.encode()).hexdigest())
    fo = {c: i % folds for i, c in enumerate(convs)}
    return np.asarray([fo[conversation_of(r)] for r in recs], dtype=int)


def inner_split(idx, recs):
    convs = sorted({conversation_of(recs[i]) for i in idx},
                   key=lambda c: hashlib.sha256(("inner:" + c).encode()).hexdigest())
    val = set(convs[:max(1, int(round(INNER_VAL_FRACTION * len(convs))))])
    m = np.asarray([conversation_of(recs[i]) in val for i in idx], dtype=bool)
    return idx[~m], idx[m]


class GlobalCrossEncoder(nn.Module):
    """One BERT pass over the concatenated slate; one score per candidate, read at its [SEP]."""

    def __init__(self, device):
        super().__init__()
        from transformers import AutoModel
        self.bert = AutoModel.from_pretrained(MODEL_DIR / "pytorch-reference", dtype=torch.float32)
        h = self.bert.config.hidden_size
        self.score = nn.Sequential(nn.Linear(h, h), nn.GELU(), nn.Linear(h, 1))
        nn.init.zeros_(self.score[-1].weight)
        nn.init.zeros_(self.score[-1].bias)
        self.to(device)

    def forward(self, ids, am, tt, sep_pos, base_logit):
        """sep_pos: [B, K] index of each candidate's leading [SEP]. Output is a CORRECTION to the
        shipped logit, so an untrained S2 reproduces the shipped ranking exactly."""
        h = self.bert(input_ids=ids, attention_mask=am, token_type_ids=tt).last_hidden_state
        picked = torch.gather(h, 1, sep_pos.unsqueeze(-1).expand(-1, -1, h.shape[-1]))
        return base_logit + self.score(picked).squeeze(-1)


def build_inputs(recs, device):
    """Tokenise each slate's top-K into one sequence and record the [SEP] positions."""
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tok.no_truncation()
    tok.no_padding()
    vocab = tok.get_vocab()
    CLS, SEP, PAD = vocab["[CLS]"], vocab["[SEP]"], vocab["[PAD]"]

    out = []
    over = 0
    for r in recs:
        q = tok.encode(r["question"], add_special_tokens=False).ids[:64]
        ids = [CLS] + q + [SEP]
        tt = [0] * len(ids)
        seps = []
        for j in range(K):
            c = tok.encode(r["texts"][j], add_special_tokens=False).ids
            if len(c) > PER_CAND:
                over += 1
                c = c[:PER_CAND]
            seps.append(len(ids))          # the [SEP] that OPENS this candidate is the one before
            ids += c + [SEP]
            tt += [1] * (len(c) + 1)
        # seps currently point at the token index where the candidate STARTS minus one; recompute
        # as the index of the SEP that CLOSES each candidate, which is unambiguous
        closes, pos = [], 1 + len(q) + 1
        for j in range(K):
            c_len = min(len(tok.encode(r["texts"][j], add_special_tokens=False).ids), PER_CAND)
            pos += c_len
            closes.append(pos)
            pos += 1
        if len(ids) > MAX_LEN:
            raise SystemExit(f"REFUSING: slate {r['query_id']} tokenises to {len(ids)} > {MAX_LEN}. "
                             f"PER_CAND is wrong; a silently truncated tail would drop a candidate "
                             f"entirely and its [SEP] index would point into padding.")
        am = [1] * len(ids) + [0] * (MAX_LEN - len(ids))
        ids = ids + [PAD] * (MAX_LEN - len(ids))
        tt = tt + [0] * (MAX_LEN - len(tt))
        out.append({
            "ids": torch.tensor(ids, dtype=torch.long, device=device),
            "am": torch.tensor(am, dtype=torch.long, device=device),
            "tt": torch.tensor(tt, dtype=torch.long, device=device),
            "sep": torch.tensor(closes, dtype=torch.long, device=device),
            "base": torch.tensor(r["rerank_scores"][:K], dtype=torch.float32, device=device),
            "gold": torch.tensor(r["gold"][:K], dtype=torch.bool, device=device),
        })
    print(f"  tokenised {len(out)} slates; {over} candidate texts hit the {PER_CAND}-piece cap")
    return out


def listwise_loss(scores, gold):
    logp = torch.log_softmax(scores, dim=-1)
    has = gold.any(dim=-1)
    if not has.any():
        return scores.sum() * 0.0
    return -(torch.logsumexp(logp.masked_fill(~gold, float("-inf"))[has], dim=-1)).mean()


def stack(items, idx):
    return {k: torch.stack([items[i][k] for i in idx]) for k in
            ("ids", "am", "tt", "sep", "base", "gold")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--lr-head", type=float, default=3e-4)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--folds", type=int, default=FOLDS)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    torch.manual_seed(SEED)
    np.random.seed(SEED)
    recs = json.loads(SLATES.read_text(encoding="utf-8"))["records"]
    n = len(recs)
    items = build_inputs(recs, args.device)
    folds = fold_assignment(recs, args.folds)

    gold_full = np.asarray([r["gold"] for r in recs])
    base_full = np.asarray([r["rerank_scores"] for r in recs])
    print(f"device={args.device}  n={n}  K={K}  max_len={MAX_LEN}  folds={args.folds}")
    print(f"shipped fit R@1 {SHIPPED_FIT_R1}\n")

    oof = np.zeros((n, K), dtype=np.float32)
    eps = []
    for f in range(args.folds):
        te = np.flatnonzero(folds == f)
        tr = np.flatnonzero(folds != f)
        itr, iva = inner_split(tr, recs)
        torch.manual_seed(SEED)
        model = GlobalCrossEncoder(args.device)
        opt = torch.optim.AdamW(
            [{"params": model.bert.parameters(), "lr": args.lr},
             {"params": model.score.parameters(), "lr": args.lr_head}],
            weight_decay=args.weight_decay)

        def predict(idx):
            model.eval()
            outs = []
            with torch.no_grad():
                for i in range(0, len(idx), args.batch):
                    b = stack(items, idx[i:i + args.batch])
                    outs.append(model(b["ids"], b["am"], b["tt"], b["sep"],
                                      b["base"]).cpu().numpy())
            return np.concatenate(outs, axis=0)

        def r1(idx, s):
            return float(gold_full[idx][np.arange(len(idx)), s.argmax(1)].mean())

        best = {"v": r1(iva, predict(iva)), "e": 0,
                "s": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}}
        rng = np.random.default_rng(SEED)
        for ep in range(1, args.epochs + 1):
            model.train()
            order = rng.permutation(itr)
            for i in range(0, len(order), args.batch):
                b = stack(items, order[i:i + args.batch])
                loss = listwise_loss(model(b["ids"], b["am"], b["tt"], b["sep"], b["base"]),
                                     b["gold"])
                opt.zero_grad(set_to_none=True)
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
            v = r1(iva, predict(iva))
            if v > best["v"] + 1e-9:
                best = {"v": v, "e": ep,
                        "s": {k: x.detach().cpu().clone() for k, x in model.state_dict().items()}}
        model.load_state_dict(best["s"])
        oof[te] = predict(te)
        eps.append(best["e"])
        print(f"  fold {f}: train {len(tr)} test {len(te)}  best epoch {best['e']}  "
              f"fold R@1 {r1(te, oof[te]):.4f} (shipped "
              f"{float(gold_full[te][np.arange(len(te)), base_full[te].argmax(1)].mean()):.4f})")

    # S2 reorders only the top-K; ranks K..9 keep their shipped order beneath
    full = base_full.copy()
    lift = oof.max(1, keepdims=True) - base_full[:, :K].max(1, keepdims=True)
    full[:, :K] = oof + np.where(np.isfinite(lift), 0.0, 0.0)
    # keep the re-scored head strictly above the untouched tail
    full[:, K:] = np.minimum(base_full[:, K:], full[:, :K].min(1, keepdims=True) - 1e-6)

    new_top1, old_top1 = full.argmax(1), base_full.argmax(1)
    new_ok = gold_full[np.arange(n), new_top1]
    old_ok = gold_full[np.arange(n), old_top1]
    gained, lost = int((new_ok & ~old_ok).sum()), int((old_ok & ~new_ok).sum())
    disc = gained + lost
    p = (min(1.0, 2.0 * sum(math.comb(disc, i) for i in range(min(gained, lost) + 1)) / 2 ** disc)
         if disc else float("nan"))
    oof_r1, base_r1 = float(new_ok.mean()), float(old_ok.mean())

    print()
    print(f"  S2: OUT-OF-FOLD R@1 {oof_r1:.4f}  vs shipped {base_r1:.4f}  "
          f"delta {oof_r1-base_r1:+.4f}")
    print(f"      changed top-1 {int((new_top1!=old_top1).sum())}  gained {gained} lost {lost}  "
          f"discordant {disc}  exact McNemar p={p:.4f}  "
          f"alpha {'attainable' if disc >= 6 else 'UNATTAINABLE'}  epochs {eps}")

    np.save(OUTDIR / "oof-s2.npy", full)
    (OUTDIR / "cv-arm-s2.json").write_text(json.dumps({
        "_what": "arm S2, global cross-encoder over the top-4, 5-fold CV by conversation on fit",
        "k": K, "max_len": MAX_LEN, "per_candidate_tokens": PER_CAND,
        "oof_r_at_1": round(oof_r1, 4), "shipped_r_at_1": round(base_r1, 4),
        "delta": round(oof_r1 - base_r1, 4),
        "changed_top1": int((new_top1 != old_top1).sum()), "gained": gained, "lost": lost,
        "discordant": disc, "exact_mcnemar_p": round(p, 4) if disc else None,
        "alpha_attainable": disc >= 6, "best_epochs_per_fold": eps,
        "hyperparameters": {k: v for k, v in vars(args).items() if k != "device"},
    }, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote runs/session-m0c/cv-arm-s2.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
