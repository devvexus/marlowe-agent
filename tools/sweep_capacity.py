"""M0c Session M, W1 — score the capacity curve, and check the instrument per query.

    python tools/sweep_capacity.py --sweep
    python tools/sweep_capacity.py --discordant ms-marco-MiniLM-L-2-v2-ft-w1

## Nothing about the ranking is re-implemented here

`sweep_reranker_frontier.main` is CALLED, not copied — including its control, which refuses to
sweep unless the shipped key reproduces fit R@1 **0.7555** exactly. This file supplies a model list
and two registry updates and gets out of the way. A second implementation of the five-level key is
the failure family this project keeps a ledger of, and it has at least four subtly-wrong forms that
all yield a plausible number.

Two runtime registrations, both stated rather than silent:

  * `capacity_register` adds W1's digest pins to `session_i_rerankers.FINETUNES`, so
    `tools/session_i_rerankers.py` is not edited.
  * `TIER_A` gains W1's four names. All four are BERT on the 30522-token WordPiece vocab — the
    downloaded L-4 and L-12 checkpoints ship **the same `tokenizer.json` digest** as L-2
    (`d241a60d…`) — so each loads in the shipped `rerank.rs` with a digest re-pin and nothing else.
    That is a claim about shippability and it is asserted here, not assumed: `assert_tier_a`
    compares each graph's tokenizer digest against the shipped fine-tune's before the sweep runs.

## --discordant is the instrument check, and it is stronger than an R@1 match

Arm A's reproduction in `RETRAIN-RESULT.md` §1 rests on **0 discordant queries out of 229** — the
retrained graph making the *same top-1 decision on every fit query* as the shipped one, not merely
landing on the same aggregate. At this granularity an R@1 that matches by coincidence is a real
possibility; a per-query identity is not. Same check, same 229 queries, run on W1's L-2 arm.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import capacity_register  # noqa: E402,F401  — registers W1's pins in the ONE loader
import session_i_rerankers as R  # noqa: E402
import sweep_reranker_frontier as SW  # noqa: E402

OUT_DIR = REPO / "runs" / "session-m0c-m"

# The curve, fine-tuning held constant. The shipped graph is first because it is the control the
# sweep gates on. L-6-ft-session-j is Session J's own graph and is carried unchanged: retraining it
# here as `-ft-w1` is a reproduction check on the trainer, not a replacement for Session J's point.
CURVE = [
    "ms-marco-MiniLM-L-2-v2-ft-session-j",   # SHIPPED CONTROL, 16M, Session J
    "ms-marco-MiniLM-L-2-v2-ft-w1",          # 16M, W1  — THE INSTRUMENT
    "ms-marco-MiniLM-L-4-v2-ft-w1",          # 19M, W1  — never fine-tuned before
    "ms-marco-MiniLM-L-6-v2-ft-session-j",   # 23M, Session J
    "ms-marco-MiniLM-L-6-v2-ft-w1",          # 23M, W1  — second reproduction check
    "ms-marco-MiniLM-L-12-v2-ft-w1",         # 33M, W1  — never fine-tuned before
]


def assert_tier_a() -> dict[str, str]:
    """Tier A means: loads in `rerank.rs` with a digest re-pin and nothing else.

    `rerank.rs` is a WordPiece pair encoder with a DIGEST-PINNED tokenizer, so the claim reduces to
    a file comparison: does this graph ship the same `tokenizer.json` as the shipped fine-tune? A
    tier label asserted in a constant is a declaration nothing reads — the failure family CLAUDE.md
    records as instance sixteen — so it is computed here from the bytes.
    """
    shipped = R.sha256_file(R.MODELS_DIR / R.SHIPPED_FINETUNE / "tokenizer.json")
    out = {}
    for name in CURVE:
        d = R.sha256_file(R.MODELS_DIR / name / "tokenizer.json")
        out[name] = d
        same = d == shipped
        print(f"  tokenizer {d[:16]}...  {'SAME as shipped -> Tier A' if same else 'DIFFERS -> NOT Tier A'}   {name}")
        if same:
            SW.TIER_A.add(name)
    return out


def discordant(names: list[str], provider: str) -> int:
    """Per-query top-1 agreement with the shipped graph, on the 229 fit queries.

    Also splits each model's fit R@1 into the 182 queries Session J's pairs file trained on and the
    **47 held apart by conversation** — the same fold `finetune_v2.py --fold-report` reads. Two
    cautions travel with that column and are printed rather than left implicit: n = 47 is small, and
    those 47 ARE the model-selection set, since best epoch is chosen by fit-val R@1 over exactly
    them. It is a consistency check on the aggregate, not an independent test.
    """
    import torch

    lib = Path(torch.__file__).parent / "lib"
    if lib.is_dir():
        try:
            import os

            os.add_dll_directory(str(lib))
        except (AttributeError, OSError):
            pass

    from reach_pools import load_pools, turn_texts

    from marlowe_eval.datasets import longmemeval

    pools, _ = load_pools(SW.FIT_POOLS)
    split = json.loads((REPO / "tools" / "split.json").read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])
    gold_current = SW.current_gold_ids(corpus)
    texts = turn_texts()
    baseline = {qid: SW.shipped_order(p) for qid, p in pools.items()}

    control = SW.evaluate(pools, baseline, gold_current)
    print(f"CONTROL  shipped key, depth 10: R@1 {control['R@1']}  (published {SW.CONTROL_R1})")
    if abs(control["R@1"] - SW.CONTROL_R1) < 1e-9:
        print("control reproduces the published fit R@1 exactly. proceeding.\n")
    else:
        raise SystemExit(f"REFUSING. reconstruction reads R@1 {control['R@1']}, published "
                         f"{SW.CONTROL_R1}.")

    from session_i_seqlen import mcnemar_exact

    val_queries = {json.loads(line)["query_id"]
                   for line in io.open(REPO / "runs" / "session-j" / "training-pairs.jsonl",
                                       encoding="utf-8")
                   if line.strip() and json.loads(line)["fold"] == "val"}
    qids = sorted(pools)
    held_apart = [q for q in qids if q in val_queries]
    trained_on = [q for q in qids if q not in val_queries]
    print(f"fold: trained-on {len(trained_on)}   held-apart {len(held_apart)} "
          f"(by conversation; ALSO the best-epoch selection set, so not an independent test)\n")

    def top1(model: str) -> dict[str, tuple[str, bool]]:
        ce = R.load(model, provider=provider)
        out = {}
        for qid, pool in pools.items():
            slate = [int(i) for i in baseline[qid][:10]]
            docs = [texts.get(qid, {}).get(pool.candidates[i].turn_id) or "" for i in slate]
            order = SW.reordered(pool, slate, ce.score_batch(pool.question, docs, SW.MAX_SEQ))
            t = int(order[0])
            out[qid] = (pool.candidates[t].turn_id or "", bool(pool.gold[t]))
        return out

    a = top1(R.SHIPPED_FINETUNE)
    rows = []
    print(f"{'model':<40}{'R@1':>8}{'diff top1':>11}{'won':>6}{'lost':>6}{'p':>9}"
          f"{'train182':>10}{'apart47':>9}")
    for name in names:
        b = a if name == R.SHIPPED_FINETUNE else top1(name)
        diff = [q for q in qids if a[q][0] != b[q][0]]
        won = [q for q in qids if b[q][1] and not a[q][1]]
        lost = [q for q in qids if a[q][1] and not b[q][1]]
        p, p_min = mcnemar_exact(len(lost), len(won))
        r1 = sum(b[q][1] for q in qids) / len(qids)
        r1_tr = sum(b[q][1] for q in trained_on) / len(trained_on)
        r1_va = sum(b[q][1] for q in held_apart) / len(held_apart)
        print(f"{name:<40}{r1:>8.4f}{len(diff):>11}{len(won):>6}{len(lost):>6}{p:>9.4f}"
              f"{r1_tr:>10.4f}{r1_va:>9.4f}")
        rows.append({"model": name, "r_at_1": round(r1, 4), "different_top1": len(diff),
                     "different_top1_query_ids": diff, "won": len(won), "lost": len(lost),
                     "gold_flips_won": won, "gold_flips_lost": lost,
                     "mcnemar_exact_p": round(p, 4),
                     "smallest_attainable_p_at_this_n": round(p_min, 4),
                     "r_at_1_trained_on_182": round(r1_tr, 4),
                     "r_at_1_held_apart_47": round(r1_va, 4)})

    out = OUT_DIR / "capacity-paired.json"
    out.write_text(json.dumps({
        "_what": "M0c Session M W1 — per-query top-1 agreement with the SHIPPED graph, fit, depth "
                 "10. This is the instrument check: an aggregate R@1 can match by coincidence at "
                 "n=229, a per-query identity cannot.",
        "reference": R.SHIPPED_FINETUNE, "provider": provider, "n": len(qids),
        "n_trained_on": len(trained_on), "n_held_apart": len(held_apart),
        "held_apart_caveat": "the 47 are the best-epoch selection set; a consistency check on the "
                             "aggregate, NOT an independent test",
        "control_r_at_1": control["R@1"], "models": rows,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nWROTE {out.relative_to(REPO)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--discordant", nargs="*", metavar="MODEL_NAME",
                    help="paired per-query comparison against the shipped graph; "
                         "defaults to the whole curve")
    ap.add_argument("--depths", type=int, nargs="+", default=[10, 20, 30])
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    ap.add_argument("--out", default=str(OUT_DIR / "capacity-frontier.json"))
    args = ap.parse_args()

    print(f"registered at runtime, from runs/session-m0c-m/capacity-manifest.json: "
          f"{capacity_register.REGISTERED}")
    print("tokenizer identity check (Tier A is a claim about bytes, not a label):")
    tokenizers = assert_tier_a()
    (OUT_DIR / "capacity-tokenizer-identity.json").write_text(json.dumps({
        "_what": "M0c Session M W1 — tokenizer.json digests. Tier A == same WordPiece tokenizer as "
                 "the shipped fine-tune, so rerank.rs needs a digest re-pin and nothing else.",
        "shipped": R.SHIPPED_FINETUNE, "digests": tokenizers,
    }, indent=2) + "\n", encoding="utf-8")
    print()

    if args.discordant is not None:
        return discordant(args.discordant or CURVE, args.provider)
    if not args.sweep:
        raise SystemExit("pass --sweep or --discordant")

    sys.argv = ["sweep_reranker_frontier.py",
                "--depths", *[str(d) for d in args.depths],
                "--models", *CURVE,
                "--provider", args.provider,
                "--out", args.out]
    return SW.main()


if __name__ == "__main__":
    raise SystemExit(main())
