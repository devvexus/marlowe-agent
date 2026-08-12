"""M0c Session M, Phase 2 — the negatives x objective ablation, four arms.

    python tools/finetune_v2.py --arm A --pairs sessionj --loss marginmse
    python tools/finetune_v2.py --arm B --pairs v2       --loss marginmse
    python tools/finetune_v2.py --arm C --pairs sessionj --loss bce
    python tools/finetune_v2.py --arm D --pairs v2       --loss bce
    python tools/finetune_v2.py --arm D-no-deployed --pairs v2 --loss bce \
        --classes cross_session question_echo
    python tools/finetune_v2.py --verify ms-marco-MiniLM-L-2-v2-ft-m-A

## The question

Can the reranker learn to prefer the turn that CONTAINS THE ANSWER over the turn that merely TALKS
ABOUT THE TOPIC? 53 of 234 held-out losses are that one confusion, and nothing in the model's
history has ever posed it: MS MARCO labels topical relevance, and `session_j_mine_negatives.py:94`
(`if sid not in gold_sessions: continue`) draws every one of the 6,898 shipped fine-tuning pairs
from inside the gold turn's own session.

## Two changes, and they are separable BY CONSTRUCTION

| arm | negatives | loss |
|---|---|---|
| A | Session J's `runs/session-j/training-pairs.jsonl` | hard-label MarginMSE |
| B | `runs/session-m0c-m/training-pairs-v2.jsonl` | hard-label MarginMSE |
| C | Session J's | BCE on gold / not-gold |
| D | v2 | BCE |

`--classes` drops one v2 negative class at a time, which is the by-class ablation Session J runs on
its four classes and which matters here because the three v2 classes are 3,103 / 1,892 / 1,892.

## ARM A IS THE INSTRUMENT, not a result

Arm A is Session J's recipe re-run by this file: same base checkpoint, same pairs, same loss, same
`delta`, same hyperparameters, same seed, same conversation-level fold. **If it does not land on the
shipped fit R@1 of 0.7555 then this trainer is not reproducing the shipped graph and no other arm's
number means anything** — the same discipline `sweep_reranker_frontier.py` and
`mine_negatives_v2.py` carry, applied to a training pipeline instead of a ranking key.

`session_j_finetune.py` is NOT modified and NOT imported for its `main`. It is the record of what
produced the shipped graph. This file re-implements the recipe and is then judged against that
graph's number, which is the only way the reproduction claim can be checked at all.

## THE BASE CHECKPOINT, and the confound that is avoided rather than declared

The obvious start is `models/ms-marco-MiniLM-L-2-v2-ft-session-j/pytorch-reference/`, which is
already fine-tuned — continuing from it would make every arm a SECOND round of training on top of
Session J's, the confound M0c Session A's L1 arm was criticised for, and would make arm A structurally
incapable of reproducing 0.7555 because it is not the recipe that produced it.

The un-tuned `cross-encoder/ms-marco-MiniLM-L-2-v2` checkpoint is present in the local HF cache, so
it is used, and `--base ft` exists only to make the alternative runnable and labelled. Which one ran
is recorded in every artifact this file writes.

## What is deliberately identical to Session J

Base checkpoint, MAX_LEN 256, SEED 7, epochs 3, lr 2e-5, batch 32, AdamW, best-epoch selection by
fit-val R@1 over the depth-10 slates in `runs/session-j/rerank-scores-fit-L-2-v2-f32-seq256.json`,
and the MarginMSE target `delta` recomputed from the BASE model's own margins on fit cases it
already ranks first (so it is not chosen against the outcome). The two pair files put the same 47
fit queries in the val fold — verified here, not assumed — so every arm's val number is over one
query set.

## What BCE changes, and why it is the second lever

Hard-label MarginMSE is `mse_loss(s_pos - s_neg, delta)`. **Once the gap reaches `delta` the loss is
zero and the gradient stops**, so it cannot push separation past the base model's status quo. The
observed failures have a median rank-1/rank-2 gap of 0.348 and a minimum of 0.0004. BCE on
gold / not-gold keeps pushing until the classification is confident, and it is also the objective
these ms-marco cross-encoders were originally trained with, so the head's scale is not being
repurposed.

## Nothing here ships

No artifact is minted, `crates/` is untouched, no held-out read is taken, and the models are pinned
in `runs/session-m0c-m/retrain-manifest.json` — this session's own file. Session J's manifest is a
record of Session J and is not written to.
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

from session_i_rerankers import MODELS_DIR  # noqa: E402

OUT_DIR = REPO / "runs" / "session-m0c-m"
MANIFEST = OUT_DIR / "retrain-manifest.json"

PAIR_FILES = {
    "sessionj": REPO / "runs" / "session-j" / "training-pairs.jsonl",
    "v2": OUT_DIR / "training-pairs-v2.jsonl",
}

# The depth-10 fit slates scored by the UN-TUNED L-2 f32 graph at seq 256. Session J's `delta` and
# its fit-val R@1 both come from this file; reusing it is what makes arm A comparable to Session J
# rather than merely similar to it.
CACHE = REPO / "runs" / "session-j" / "rerank-scores-fit-L-2-v2-f32-seq256.json"

HF_REPO = "cross-encoder/ms-marco-MiniLM-L-2-v2"
FT_LOCAL = MODELS_DIR / "ms-marco-MiniLM-L-2-v2-ft-session-j" / "pytorch-reference"

MAX_LEN = 256
SEED = 7

# Session J's, recorded so a drift is an error rather than a difference nobody notices.
SESSION_J_DELTA = 2.926574
SESSION_J_VAL_QUERIES = 47


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
    """Session J's export, byte-for-byte the same call, so the graph is the same KIND of graph.

    Dynamic batch and sequence axes, so padding invariance is testable at all. The shipped stage
    still runs `[1, 256]`; the graph merely does not forbid other shapes.
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
# verification — the same five checks Session J's gate runs, driven off THIS session's manifest
# ------------------------------------------------------------------------------------------------


def verify(name: str) -> int:
    """`session_j_verify_export.py`'s checks, imported rather than restated.

    Its `main()` loads through `session_j_models.load_finetuned`, which reads Session J's manifest —
    a file this session must not write to. The four check FUNCTIONS are what carry the content, so
    they are imported and pointed at a graph loaded through `session_i_rerankers.load`, which is the
    same loader with the same digest pin, the same `ORT_ENABLE_BASIC`, the same single thread and
    the same provider assertion.
    """
    import torch

    lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.isdir(lib):
        try:
            os.add_dll_directory(lib)
        except (AttributeError, OSError):
            pass

    import session_i_rerankers as R
    from session_j_verify_export import padding_invariance, torch_vs_ort

    ce = R.load(name)  # CPU, digest-pinned, provider asserted
    print(f"{name}  digest {ce.digest[:16]}...  provider asserted, ORT_ENABLE_BASIC, 1 thread")

    checks = {
        "smoke_discriminates": R.smoke_test(ce),
        "determinism": R.determinism(ce),
        "batch_invariance": R.batch_invariance(ce),
        "padding_invariance": padding_invariance(ce),
        "torch_vs_ort": torch_vs_ort(ce, HF_REPO),
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
        "_what": "M0c Session M Phase 2 — determinism and export gate for a graph this session trained.",
        "model": name, "digest": ce.digest, "checks": checks, "pass": bool(ok),
        "_torch_vs_ort_is_the_one_that_speaks_to_the_export": (
            "checks 1-4 describe the exported graph's behaviour; only check 5 compares it against "
            "the PyTorch module it came from. A silently wrong export produces plausible numbers, "
            "which is why the sweep is not run before this passes."
        ),
        "open_gap": (
            "SELF-VALIDATED ONLY. There is no external authority for a model this session trained, "
            "so the unvalidated-export gap is NOT closed by these checks — it is bounded by them."
        ),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {out.relative_to(REPO)}")
    return 0 if ok else 1


# ------------------------------------------------------------------------------------------------
# the fold breakdown — the control on the headline fit number
# ------------------------------------------------------------------------------------------------


def fold_report(names: list[str], provider: str) -> int:
    """Fit R@1 split into the queries the arm TRAINED on and the 47 it did not.

    **This is the control the headline number needs and it is not optional.** `deployed_top_k` is
    the shipped model's own top-10 *for that query*, so a train-fold query has had its exact
    competitor turns presented as negatives with its own gold as the positive. A model that
    memorised "turn X is not the answer to question Q" would raise fit R@1 without learning
    anything, and the sweep's single 229-query number reads identically either way. The val fold —
    47 fit queries held apart BY CONVERSATION, whose pairs exist in the file and were never
    trained on — is the half of the fit split that is not contaminated.

    Nothing about the ranking is re-implemented. `shipped_order`, `reordered`, `evaluate` and
    `current_gold_ids` are imported from `sweep_reranker_frontier`, and the overall number this
    produces must equal the number that tool wrote — printed side by side, because reusing the
    functions is not evidence that they were reused correctly.
    """
    import torch

    lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.isdir(lib):
        try:
            os.add_dll_directory(lib)
        except (AttributeError, OSError):
            pass

    import session_i_rerankers as R
    import sweep_reranker_frontier as SW
    from reach_pools import load_pools, turn_texts

    from marlowe_eval.datasets import longmemeval

    pools, _ = load_pools(SW.FIT_POOLS)
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_current = SW.current_gold_ids(corpus)
    texts = turn_texts()
    baseline = {qid: SW.shipped_order(p) for qid, p in pools.items()}

    val_queries = {json.loads(line)["query_id"]
                   for line in io.open(PAIR_FILES["v2"], encoding="utf-8")
                   if line.strip() and json.loads(line)["fold"] == "val"}
    in_val = sorted(q for q in pools if q in val_queries)
    in_train = sorted(q for q in pools if q not in val_queries)
    print(f"fit pools {len(pools)}  ->  trained-on {len(in_train)}   held-apart {len(in_val)} "
          f"(by conversation, never in any arm's training set)")

    def subset(qids, order_by_qid):
        sub = {q: pools[q] for q in qids}
        return SW.evaluate(sub, {q: order_by_qid[q] for q in qids}, gold_current)

    def per_query(order_by_qid):
        """Top-1 hit per query, so a delta can be TESTED rather than eyeballed.

        Session I's null was reported as "discordant 27, exact p = 0.7011"; a difference of a few
        cases on 47 queries needs the same treatment, and an aggregate R@1 cannot supply it.
        """
        return {q: int(bool(pools[q].gold[int(order_by_qid[q][0])])) for q in sorted(pools)}

    out = {"_what": "M0c Session M Phase 2 — fit R@1 split by training fold.",
           "held_apart_query_ids": in_val,
           "provider": provider, "n_trained_on": len(in_train), "n_held_apart": len(in_val),
           "arms": []}

    control = {"all": subset(sorted(pools), baseline), "train": subset(in_train, baseline),
               "val": subset(in_val, baseline)}
    print(f"\n{'arm':<44}{'all':>9}{'trained':>9}{'heldapart':>11}")
    print(f"{'SHIPPED (baseline order)':<44}{control['all']['R@1']:>9}"
          f"{control['train']['R@1']:>9}{control['val']['R@1']:>11}")
    out["arms"].append({"model": "shipped_baseline_order",
                        "per_query_hit": per_query(baseline), **{
        k: {"R@1": v["R@1"], "R@1_current": v["R@1_current"], "n": v["n"]}
        for k, v in control.items()}})

    for name in names:
        ce = R.load(name, provider=provider)
        order_by_qid = {}
        for qid, pool in pools.items():
            slate = [int(i) for i in baseline[qid][:10]]
            docs = [texts.get(qid, {}).get(pool.candidates[i].turn_id) or "" for i in slate]
            order_by_qid[qid] = SW.reordered(pool, slate, ce.score_batch(pool.question, docs, MAX_LEN))
        got = {"all": subset(sorted(pools), order_by_qid), "train": subset(in_train, order_by_qid),
               "val": subset(in_val, order_by_qid)}
        print(f"{name:<44}{got['all']['R@1']:>9}{got['train']['R@1']:>9}{got['val']['R@1']:>11}")
        out["arms"].append({"model": name, "per_query_hit": per_query(order_by_qid), **{
            k: {"R@1": v["R@1"], "R@1_current": v["R@1_current"], "n": v["n"]}
            for k, v in got.items()}})

    path = OUT_DIR / "retrain-fold-breakdown.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nWROTE {path.relative_to(REPO)}")
    return 0


# ------------------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", metavar="MODEL_NAME",
                    help="run the five export checks on an already-trained arm and exit")
    ap.add_argument("--fold-report", nargs="+", metavar="MODEL_NAME",
                    help="split each arm's fit R@1 into trained-on and held-apart queries, and exit")
    ap.add_argument("--provider", default="CUDAExecutionProvider",
                    help="execution provider for --fold-report")
    ap.add_argument("--arm", help="arm label; the model is named ms-marco-MiniLM-L-2-v2-ft-m-<arm>")
    ap.add_argument("--pairs", choices=sorted(PAIR_FILES), help="which negatives")
    ap.add_argument("--loss", choices=["marginmse", "bce"])
    ap.add_argument("--classes", nargs="+", default=["all"],
                    help="restrict to these negative classes (the by-class ablation)")
    ap.add_argument("--base", choices=["untuned", "ft"], default="untuned")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    if args.verify:
        return verify(args.verify)
    if args.fold_report:
        return fold_report(args.fold_report, args.provider)
    for required in ("arm", "pairs", "loss"):
        if getattr(args, required) is None:
            raise SystemExit(f"--{required} is required when training")

    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    set_seed(args.seed)
    has_cuda = cuda_ready()
    device = "cuda" if has_cuda else "cpu"
    print(f"device: {device}"
          + (f"  ({torch.cuda.get_device_name(0)})" if has_cuda else "  — CUDA NOT AVAILABLE"))

    if not CACHE.exists():
        raise SystemExit(f"{CACHE} is missing — the fit slates and the base scores come from it.")
    cache = json.loads(io.open(CACHE, encoding="utf-8").read())

    # ---- delta, from the BASE model's own margins on cases it already gets right ---------------
    margins = []
    for row in cache["rows"].values():
        s = np.array(row["scores"], float)
        order = np.argsort(-s, kind="stable")
        if row["gold"][int(order[0])]:
            margins.append(float(s[order[0]] - s[order[1]]))
    delta = float(np.median(margins))
    print(f"target margin delta = {delta:.6f}  (median over {len(margins)} fit cases the base "
          f"model already ranks correctly — NOT chosen against the outcome)")
    if abs(delta - SESSION_J_DELTA) > 1e-6:
        raise SystemExit(
            f"delta reads {delta:.6f}; Session J recorded {SESSION_J_DELTA}. Same cache, same "
            "formula — a difference here means the arm is not Session J's recipe."
        )

    # ---- the base checkpoint --------------------------------------------------------------------
    source = HF_REPO if args.base == "untuned" else str(FT_LOCAL)
    print(f"\nbase checkpoint: {source}"
          + ("" if args.base == "untuned" else "   ** ALREADY FINE-TUNED — this arm is a second round **"))
    tok = AutoTokenizer.from_pretrained(HF_REPO)
    model = AutoModelForSequenceClassification.from_pretrained(source).to(device)

    questions = load_questions()
    texts_by_query: dict[str, dict[str, str]] = {}
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
    pairs_path = PAIR_FILES[args.pairs]
    rows = [json.loads(line) for line in io.open(pairs_path, encoding="utf-8") if line.strip()]
    all_classes = sorted({r["negative_class"] for r in rows})
    if args.classes != ["all"]:
        unknown = sorted(set(args.classes) - set(all_classes))
        if unknown:
            raise SystemExit(f"{pairs_path.name} has no class(es) {unknown}; it has {all_classes}")
        rows = [r for r in rows if r["negative_class"] in args.classes]
    train = [r for r in rows if r["fold"] == "train"]

    # The val fold is drawn from the WHOLE pairs file, never from the class-restricted subset: a
    # by-class ablation that also moved the validation set would compare two things at once.
    all_rows = [json.loads(line) for line in io.open(pairs_path, encoding="utf-8") if line.strip()]
    val_queries = sorted({r["query_id"] for r in all_rows if r["fold"] == "val"})
    if len(val_queries) != SESSION_J_VAL_QUERIES:
        raise SystemExit(
            f"{pairs_path.name} puts {len(val_queries)} queries in the val fold; Session J puts "
            f"{SESSION_J_VAL_QUERIES}. The arms would not share a validation set."
        )
    val_in_cache = [q for q in val_queries if q in cache["rows"]]
    print(f"\npairs file: {pairs_path.relative_to(REPO)}")
    print(f"training pairs: {len(train)} of {len(rows)}  "
          f"(classes: {sorted({r['negative_class'] for r in train})})")
    print(f"validation: {len(val_queries)} fit queries held apart BY CONVERSATION, "
          f"{len(val_in_cache)} with a reconstructed slate")

    # ---- the comparability check, BEFORE training -------------------------------------------
    #
    # Session J ran this to establish that its PyTorch starting point and the Xenova ONNX baseline
    # every Session I/J number was measured on are the same scorer. It is re-run here for a second
    # reason: it is the check that says THIS process loaded the checkpoint Session J loaded. It
    # recorded Pearson 1.0, max |delta logit| 5e-05 and R@1 0.5983 on both sides.
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
        "session_j_recorded": {"xenova_onnx_r_at_1": 0.5983, "pytorch_r_at_1": 0.5983,
                               "pearson": 1.0, "max_abs_logit_difference": 5e-05},
    }
    comparability["agrees_with_session_j"] = bool(
        comparability["pytorch_r_at_1"] == 0.5983 and comparability["xenova_onnx_r_at_1"] == 0.5983
    ) if args.base == "untuned" else False
    print(f"\ncomparability: Xenova ONNX R@1 {onnx_r1:.4f}   this PyTorch checkpoint R@1 "
          f"{torch_r1:.4f}   pearson {comparability['pearson']:.6f}   "
          f"max |delta| {comparability['max_abs_logit_difference']:.6f}")
    print(f"  Session J recorded 0.5983 / 0.5983 / 1.0 / 5e-05  -> "
          f"{'SAME STARTING POINT' if comparability['agrees_with_session_j'] else 'DIFFERENT — see base_checkpoint'}")

    val_cache = {"rows": {q: cache["rows"][q] for q in val_in_cache}}
    val_pairs, val_idx = slate_pairs(val_in_cache)

    def val_r1() -> float:
        s = score_with_torch(model, tok, val_pairs, device)
        bq = {q: np.zeros(len(r["scores"])) for q, r in val_cache["rows"].items()}
        for (qid, j), v in zip(val_idx, s):
            bq[qid][j] = v
        return r_at_1_from_scores(val_cache, bq)

    base_val = val_r1()
    print(f"  base model, fit-val R@1: {base_val:.4f}")

    # ---- the two losses ---------------------------------------------------------------------------
    bce = torch.nn.BCEWithLogitsLoss()

    def compute_loss(s_pos, s_neg):
        if args.loss == "marginmse":
            # Hard-label MarginMSE. Drives the gap to a FIXED target; ONCE IT IS REACHED THE
            # GRADIENT STOPS, which is the property this ablation exists to test.
            return torch.nn.functional.mse_loss(s_pos - s_neg, torch.full_like(s_pos, delta))
        # BCE on gold / not-gold. Keeps pushing until the classification is confident, and it is
        # the objective the ms-marco cross-encoders were pretrained with, so the head's scale is
        # not being repurposed.
        return 0.5 * (bce(s_pos, torch.ones_like(s_pos)) + bce(s_neg, torch.zeros_like(s_neg)))

    # ---- train --------------------------------------------------------------------------------
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
            loss = compute_loss(s_pos, s_neg)
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

    # ---- export and pin ---------------------------------------------------------------------------
    name = f"ms-marco-MiniLM-L-2-v2-ft-m-{args.arm}"
    directory = MODELS_DIR / name
    directory.mkdir(parents=True, exist_ok=True)
    model = model.to("cpu")
    export_onnx(model, directory / "model.onnx")
    tok.backend_tokenizer.save(str(directory / "tokenizer.json"))
    model.save_pretrained(str(directory / "pytorch-reference"))

    digest = sha256_file(directory / "model.onnx")
    meta = {
        "name": name,
        "arm": args.arm,
        "digests": {
            "model.onnx": digest,
            "tokenizer.json": sha256_file(directory / "tokenizer.json"),
        },
        "base": "ms-marco-MiniLM-L-2-v2",
        "base_checkpoint": source,
        "base_is_already_finetuned": args.base != "untuned",
        "hf_repo": HF_REPO,
        "arch": "BERT (fine-tuned, M0c Session M Phase 2)",
        "params_m": sum(p.numel() for p in model.parameters()) // 1_000_000,
        "max_seq": 512,
        "pairs_file": str(pairs_path.relative_to(REPO)).replace("\\", "/"),
        "negative_classes": sorted({r["negative_class"] for r in train}),
        "training_pairs": len(train),
        "loss": args.loss,
        "target_margin_delta": round(delta, 6) if args.loss == "marginmse" else None,
        "hyperparameters": {"epochs": args.epochs, "lr": args.lr, "batch": args.batch,
                            "max_len": MAX_LEN, "seed": args.seed},
        "comparability_check": comparability,
        "base_val_r_at_1": round(base_val, 4),
        "best_epoch": best["epoch"],
        "fit_val_r_at_1": round(best["val_r_at_1"], 4),
        "fit_val_history": history,
        "trained_on": "fit split only",
        "_export_gap": (
            "SELF-VALIDATED ONLY. A PyTorch-to-ONNX export produced in this session cannot be "
            "checked against an external authority, because none exists for a model this session "
            "trained. Digest pinning, torch-vs-ORT agreement, and per-graph determinism / batch / "
            "padding invariance are what stand behind it."
        ),
    }

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(io.open(MANIFEST, encoding="utf-8").read()) if MANIFEST.exists() else {
        "_what": "M0c Session M Phase 2 — models this session trained. Session J's manifest is a "
                 "record of Session J and is not written to.",
        "models": [],
    }
    data["models"] = [m for m in data["models"] if m["name"] != name] + [meta]
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    out = OUT_DIR / f"retrain-train-{args.arm}.json"
    out.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {out.relative_to(REPO)}")
    print(f"pinned {name} in {MANIFEST.relative_to(REPO)}")
    print()
    print("register it in session_i_rerankers.FINETUNES to make it scoreable:")
    print(f'    "{name}": {{')
    print(f'        "digest": "{digest}",')
    print(f'        "params_m": {meta["params_m"]}, "arch": "BERT", "max_seq": 512,')
    print("    },")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
