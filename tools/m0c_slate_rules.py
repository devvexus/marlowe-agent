"""Does a higher-recall slate actually convert into R@1?

R3 measured input recall under several slate-construction rules and found that the shipped gate
order is not the best way to choose which ten candidates the cross-encoder sees. Recall is not the
read, though: the reranker still has to pick correctly out of whatever it is handed, and a slate
with more gold in it also has more near-miss distractors. `R@1 = input_recall x conditional
accuracy` and this script measures BOTH factors under each rule, by actually reranking the
alternative slates with the shipped cross-encoder.

The scorer is the PyTorch reference checkpoint, which `m0c_encode_slates.py` verified reproduces
the shipped ONNX graph to 1e-5 with 229/229 top-1 agreement. Nothing about the reranker changes
here -- only which candidates reach it.

**Why a union is not the closed fusion.** ADR-010 and ADR-011 close *fusion over per-cue scores
deciding the ranking*: "calibration puts cues in common units by destroying the ordering inside
each cue", and "no fusion over per-cue scores can fix cue selection at rank 1 -- the top-1
either-cue oracle is 0.652 and that is the exact ceiling on perfect arbitration". A union of two
cues' top-k does not combine scores and does not arbitrate: every candidate admitted is ranked by
the cross-encoder, which already scores 0.6725 against that 0.6463 oracle precisely because it is
not arbitrating between cues. The closed item is a RANKING mechanism; this is an ADMISSION rule.
Stated here so the distinction is argued rather than assumed, and it belongs in a DECISIONS entry
before anything ships.

Fit split is the selection read. `--split heldout` exists for the single final read and prints a
warning saying so.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import torch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from reach_head_r3_slate import load_pool, ranks_desc, rrf  # noqa: E402

MODEL_DIR = REPO / "models" / "ms-marco-MiniLM-L-2-v2-ft-session-j"
SPLIT_PATH = REPO / "tools" / "split.json"
OUT = REPO / "runs" / "session-m0c" / "slate-rules-{split}.json"
MAX_LEN = 256
DEPTH = 10

# The published shipped figures, per split, so a rule that fails to reproduce the control is caught.
SHIPPED = {"fit": {"r_at_1": 0.7555, "input_recall": 0.9214},
           "heldout": {"r_at_1": 0.6725, "input_recall": 0.9039}}


def gate_order(p) -> np.ndarray:
    return np.lexsort((-p["margin"], -p["score"], ~p["survived"]))


def dense_order(p) -> np.ndarray:
    return np.lexsort((-p["den"], ~p["survived"]))


def lex_order(p) -> np.ndarray:
    return np.lexsort((-p["lex"], ~p["survived"]))


def union_rule(a, b, take: int):
    """Union of two orders' top-`take`, emitted in a DETERMINISTIC order: everything the first
    order admits, in its order, then whatever the second adds, in its order. The emitted order does
    not matter to R@1 -- the cross-encoder re-scores all of them -- but it must be a function of
    the inputs alone, or two runs of the same configuration could hand the reranker different
    slates and the determinism check would fail for a reason nothing points at."""
    def rule(p):
        oa, ob = a(p)[:take].tolist(), b(p)[:take].tolist()
        seen, out = set(), []
        for i in oa + ob:
            if i not in seen:
                seen.add(i)
                out.append(i)
        return np.asarray(out, dtype=int)
    return rule


RULES = {
    "gate top10 (SHIPPED CONTROL)":      lambda p: gate_order(p)[:10],
    "dense top10":                       lambda p: dense_order(p)[:10],
    "gate8 UNION dense8":                union_rule(gate_order, dense_order, 8),
    "gate7 UNION dense7":                union_rule(gate_order, dense_order, 7),
    "gate6 UNION dense6 UNION lex6":     None,     # filled below
    "gate10 UNION dense10":              union_rule(gate_order, dense_order, 10),
    "gate top15":                        lambda p: gate_order(p)[:15],
    "dense top15":                       lambda p: dense_order(p)[:15],
}


def _tri(p):
    outs = [gate_order(p)[:6].tolist(), dense_order(p)[:6].tolist(), lex_order(p)[:6].tolist()]
    seen, out = set(), []
    for lst in outs:
        for i in lst:
            if i not in seen:
                seen.add(i)
                out.append(i)
    return np.asarray(out, dtype=int)


RULES["gate6 UNION dense6 UNION lex6"] = _tri

RULES["gate9 UNION dense9"] = union_rule(gate_order, dense_order, 9)
RULES["gate top12"] = lambda p: gate_order(p)[:12]
RULES["gate top20"] = lambda p: gate_order(p)[:20]
RULES["gate12 UNION dense6"] = union_rule(gate_order, dense_order, 0)  # placeholder
def _g12d6(p):
    a, b = gate_order(p)[:12].tolist(), dense_order(p)[:6].tolist()
    seen, out = set(), []
    for i in a + b:
        if i not in seen: seen.add(i); out.append(i)
    return __import__("numpy").asarray(out, dtype=int)
RULES["gate12 UNION dense6"] = _g12d6



def load_texts(corpus_path: Path, wanted: set[str]) -> dict[str, str]:
    raw = json.loads(corpus_path.read_text(encoding="utf-8"))
    texts = {}
    for inst in raw:
        for sid, session in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            for t_idx, turn in enumerate(session):
                tid = f"{sid}-{t_idx}"
                if tid in wanted:
                    texts[tid] = str(turn["content"])
    return texts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="fit", choices=["fit", "heldout"])
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    if args.split == "heldout":
        print("*" * 92)
        print("* HELD-OUT READ. This is the single final read and every selection must already be")
        print("* made. If a rule is being CHOSEN from this output, the discipline has been broken.")
        print("*" * 92)

    from marlowe_eval.datasets import longmemeval
    from tokenizers import Tokenizer
    from transformers import AutoModelForSequenceClassification

    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_map = corpus.gold_map()
    cases = {c.query_id: c for c in corpus.cases}
    questions = {c.query_id: c.question for c in corpus.cases}

    pool = load_pool(args.split, gold_map)
    eligible = sorted(q for q in pool
                      if q in cases and not cases[q].is_abstention and pool[q]["gold"].any())
    n = len(eligible)
    print(f"\nsplit={args.split}  eligible={n}  device={args.device}")

    slates = {}
    wanted = set()
    for name, rule in RULES.items():
        slates[name] = {q: rule(pool[q]) for q in eligible}
        for q in eligible:
            wanted.update(pool[q]["turn_id"][slates[name][q]].tolist())
    print(f"joining text for {len(wanted)} distinct turn_ids ...")
    texts = load_texts(REPO / split["corpus_path"], wanted)
    missing = wanted - set(texts)
    if missing:
        raise SystemExit(f"REFUSING: {len(missing)} turn_ids absent from the corpus")

    tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tok.enable_truncation(max_length=MAX_LEN)
    tok.enable_padding(length=MAX_LEN)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_DIR / "pytorch-reference", dtype=torch.float32).to(args.device).eval()

    # one score per (query, turn) pair, computed ONCE and shared across rules -- the cross-encoder
    # is pairwise, so a candidate's score does not depend on which slate it appears in
    need = sorted({(q, t) for name in RULES for q in eligible
                   for t in pool[q]["turn_id"][slates[name][q]].tolist()})
    print(f"scoring {len(need)} distinct (query, candidate) pairs with the shipped cross-encoder ...")
    cache: dict[tuple[str, str], float] = {}
    with torch.no_grad():
        for i in range(0, len(need), args.batch):
            chunk = need[i:i + args.batch]
            enc = tok.encode_batch([(questions[q], texts[t]) for q, t in chunk])
            out = model(
                input_ids=torch.tensor([e.ids for e in enc], device=args.device),
                attention_mask=torch.tensor([e.attention_mask for e in enc], device=args.device),
                token_type_ids=torch.tensor([e.type_ids for e in enc], device=args.device),
            ).logits.reshape(-1).float().cpu().numpy()
            for (q, t), s in zip(chunk, out):
                cache[(q, t)] = float(s)

    def outcomes(name) -> tuple[np.ndarray, float, float, float, float]:
        """Per-query correctness under a rule, plus the three factored reads."""
        ok = np.zeros(n, dtype=bool)
        inrec = 0
        depths = []
        for i, q in enumerate(eligible):
            idx = slates[name][q]
            depths.append(len(idx))
            tids = pool[q]["turn_id"][idx]
            gold = pool[q]["gold"][idx]
            if not gold.any():
                continue
            inrec += 1
            s = np.asarray([cache[(q, t)] for t in tids])
            ok[i] = bool(gold[int(np.argmax(s))])
        hits = int(ok.sum())
        return (ok, hits / n, inrec / n, hits / inrec if inrec else float("nan"),
                float(np.median(depths)))

    def mcnemar(b: int, c: int) -> float:
        m = b + c
        if m == 0:
            return float("nan")
        k = min(b, c)
        return min(1.0, 2.0 * sum(math.comb(m, i) for i in range(k + 1)) / 2.0 ** m)

    ctrl_name = next(k for k in RULES if "SHIPPED CONTROL" in k)
    ctrl_ok, ctrl_r1, *_ = outcomes(ctrl_name)

    print()
    print(f"{'slate rule':<34} {'depth':>6} {'in-rec':>8} {'cond-acc':>9} {'R@1':>8} {'delta':>8} "
          f"{'g/l':>7} {'disc':>5} {'p':>7}")
    print("-" * 100)
    ctrl = SHIPPED[args.split]["r_at_1"]
    rows = []
    for name in RULES:
        ok, r1, ir, ca, med = outcomes(name)
        gained = int((ok & ~ctrl_ok).sum())
        lost = int((ctrl_ok & ~ok).sum())
        disc = gained + lost
        p = mcnemar(gained, lost)
        rows.append({"rule": name, "median_depth": med,
                     "input_recall": round(ir, 4), "conditional_accuracy": round(ca, 4),
                     "r_at_1": round(r1, 4), "delta_vs_shipped": round(r1 - ctrl, 4),
                     "gained_vs_control": gained, "lost_vs_control": lost, "discordant": disc,
                     "exact_mcnemar_p": None if disc == 0 else round(p, 4),
                     "alpha_attainable": disc >= 6})
        print(f"{name:<34} {med:>6.0f} {ir:>8.4f} {ca:>9.4f} {r1:>8.4f} {r1-ctrl:>+8.4f} "
              f"{gained:>3d}/{lost:<3d} {disc:>5d} "
              f"{'—' if disc == 0 else format(p, '.4f'):>7}")

    control = next(r for r in rows if "SHIPPED CONTROL" in r["rule"])
    ok = round(control["r_at_1"], 4) == SHIPPED[args.split]["r_at_1"]
    print()
    print(f"  CONTROL CHECK: gate top10 reproduces the published {args.split} R@1 "
          f"{SHIPPED[args.split]['r_at_1']} -> {control['r_at_1']}  "
          f"{'PASS' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit("REFUSING to write: the control does not reproduce the shipped number, so "
                         "no delta measured against it means anything.")

    p = Path(str(OUT).format(split=args.split))
    p.write_text(json.dumps({
        "_what": "input recall, conditional accuracy and R@1 under alternative slate-construction "
                 "rules, reranked by the shipped cross-encoder",
        "_the_reranker_is_unchanged": "only which candidates reach it changes",
        "split": args.split, "n": n, "control_reproduces_shipped": ok,
        "shipped": SHIPPED[args.split], "rules": rows,
    }, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"wrote {p.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
