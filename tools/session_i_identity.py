"""Session I, Phase 0.1 — are the fit and held-out rerank pipelines the same pipeline?

STATE.md lists this as an open issue: the fit split read **0.6201** for the shipped configuration
and held-out read **0.5764**, on a component with no fitted parameters. A cross-encoder is
pre-trained and applied as-is, so there is very little for it to overfit, and a 4-point gap on such
a component is either case mix or a defect. Session I derives every band on fit and reads every
verdict on held-out, so if it is a defect, every number this session produces is wrong in a way
that still prints.

**The check.** Score BOTH halves with ONE function, in one process, from one dump. Two identities
have to hold:

  * **held-out must reproduce 0.5764**, which the *binary* produced in Session H. That is the
    cross-implementation identity — offline reconstruction against shipped Rust.
  * **fit must reproduce 0.6201**, which `reach_rerank_fit.py` produced. That is the
    cross-implementation identity in the other direction — this script against Session H's script.

If both hold, the two halves differ only in which cases are in them, and the gap is case mix. If
either fails, the session stops here and the defect is found before any band is registered.

**Why one function and not two calls to Session H's script.** `reach_rerank_fit.py` only ever ran
on fit; there is no held-out entry point in it. Adding a flag to it would produce a held-out number
through *almost* the same path, and "almost the same path" is how this project has acquired seven
instances of two sides silently disagreeing. The slate construction lives in exactly one function
here and both halves call it.

**The decomposition, which is the session's headline read.** R@1 factors exactly:

    R@1 = input_recall x conditional_accuracy

where `input_recall` is how often gold is in the top-10 slate handed to the reranker, and
`conditional_accuracy` is how often the reranker puts it first GIVEN that it is there. A reranker
cannot promote what it never sees, so the first factor is a hard ceiling and the second is the only
thing capacity or context can move. Session I is read against the second factor; R@1 alone hides
which one moved.

Reranker configuration is inherited from `reach_rerank_fit` unchanged -- batch 1, seq 256, 1
thread, CPU asserted, ORT_ENABLE_BASIC pinned to match the Rust stage's Level1.

    python tools/session_i_identity.py
"""

from __future__ import annotations

import io
import json
import time
from collections import defaultdict

import numpy as np

from reach_pools import REPO, Pool
from reach_rerank_fit import (
    PREREG_PATH as SESSION_H_PREREG,
    build_session,
    gate_order,
    load_tokenizer,
    score_pair,
    top1_is_gold,
)
from reach_session_h_pruning import derived_keys, prune_mask
from session_h_pools import fidelity_gate, load_split_pools
from reach_pools import turn_texts

OUT_PATH = REPO / "runs" / "session-i" / "pipeline-identity.json"
BUDGET = 10

# The two numbers this script has to reproduce. Both are PUBLISHED, both were produced by a
# different implementation than this one, and neither is recomputed here from a source this script
# could have influenced.
TARGET_HELDOUT = 0.5764  # runs/session-h/cue-overlap.json -- produced by the BINARY
TARGET_FIT = 0.6201      # runs/session-h/rerank-fit.json  -- produced by reach_rerank_fit.py
TOLERANCE = 1e-4         # both targets are published to 4 decimals


def shipped_slate(pool: Pool, gap_ms: int, prune_n: int) -> np.ndarray:
    """The candidates the shipped configuration hands to the reranker, for one query.

    THE one definition in this file. Prune to the union of each cue's top-N derived sessions, then
    draw the top-`BUDGET` by the shipped ranking key (score desc, margin desc, dump order). Both
    splits call this; there is no per-split branch and no place for one to appear.
    """
    keys = derived_keys(pool, gap_ms)
    pruned_idx = np.flatnonzero(prune_mask(pool, keys, prune_n))
    return pruned_idx[gate_order(pool, pruned_idx)[:BUDGET]]


def measure(label, pools, texts, sess, tok, gap_ms, prune_n):
    """R@1, input recall and conditional accuracy for one split. Same code for both."""
    rows = []
    pairs = 0
    started = time.perf_counter()

    for n_done, pool in enumerate(pools.values(), 1):
        per_turn = texts.get(pool.query_id, {})
        slate = shipped_slate(pool, gap_ms, prune_n)

        scores = []
        for i in slate:
            tid = pool.candidates[int(i)].turn_id
            s, _ = score_pair(sess, tok, pool.question, per_turn.get(tid or "", ""))
            scores.append(s)
            pairs += 1

        order = np.argsort(-np.array(scores), kind="stable") if len(scores) else np.array([], int)
        gold_in_slate = bool(pool.gold[slate].any()) if slate.size else False
        rows.append({
            "query_id": pool.query_id,
            "category": pool.category,
            "slate_size": int(slate.size),
            "gold_in_slate": gold_in_slate,
            "top1_is_gold": top1_is_gold(pool, slate, order),
        })
        if n_done % 50 == 0:
            print(f"    {label}: {n_done}/{len(pools)} cases, {pairs} pairs")

    n = len(rows)
    hits = sum(r["top1_is_gold"] for r in rows)
    present = sum(r["gold_in_slate"] for r in rows)
    return {
        "split": label,
        "cases": n,
        "r_at_1": round(hits / n, 4),
        "input_recall": round(present / n, 4),
        # The factor capacity and context can move. Denominator is the cases where the reranker
        # could possibly have been right -- a miss on a slate with no gold in it is a slate
        # failure, not a discrimination failure, and averaging them together hides which is which.
        "conditional_accuracy": round(hits / present, 4) if present else None,
        "cases_gold_in_slate": present,
        "cases_top1_gold": hits,
        "pairs_scored": pairs,
        "wall_seconds": round(time.perf_counter() - started, 1),
        "_per_case": rows,
    }


def by_category(rows) -> dict:
    """Per-category R@1 / input recall / conditional accuracy. The case-mix evidence."""
    buckets: dict[str, list] = defaultdict(list)
    for r in rows:
        buckets[r["category"]].append(r)
    out = {}
    for cat, rs in sorted(buckets.items()):
        n = len(rs)
        present = sum(r["gold_in_slate"] for r in rs)
        hits = sum(r["top1_is_gold"] for r in rs)
        out[cat] = {
            "cases": n,
            "r_at_1": round(hits / n, 4),
            "input_recall": round(present / n, 4),
            "conditional_accuracy": round(hits / present, 4) if present else None,
        }
    return out


def main() -> int:
    prereg = json.loads(io.open(SESSION_H_PREREG, encoding="utf-8").read())
    gap_ms = prereg["frozen_parameters"]["session_gap_ms"]["value"]
    prune_n = prereg["frozen_parameters"]["prune_N"]["value"]

    fit, heldout, stats = load_split_pools()
    ok, gate = fidelity_gate(heldout)
    if not ok:
        print("Reconstruction licensing gate FAILED. Neither half is usable.")
        print(json.dumps(gate["checks"], indent=2))
        return 1
    print(f"Reconstruction licensing gate PASSED over {gate['heldout_cases_reconstructed']} "
          f"held-out cases (lexical / dense / either-cue reproduce Session F exactly).")
    print(f"  fit pools {len(fit)}   held-out pools {len(heldout)}   "
          f"candidates {stats['candidates']}\n")

    sess, digest = build_session()
    tok = load_tokenizer()
    print(f"Reranker L-2-int8 {digest[:16]}...  batch 1, seq 256, 1 thread, "
          f"CPUExecutionProvider asserted, ORT_ENABLE_BASIC pinned.")
    print(f"Shipped slate: prune to union of per-cue top-{prune_n} derived sessions "
          f"(gap {gap_ms} ms), then top-{BUDGET} by the gate key.\n")

    results = {
        "heldout": measure("heldout", heldout, turn_texts(), sess, tok, gap_ms, prune_n),
        "fit": measure("fit", fit, turn_texts(), sess, tok, gap_ms, prune_n),
    }

    checks = {
        "heldout_reproduces_binary": {
            "_source": "runs/session-h/cue-overlap.json -- produced by target/release/marlowe.exe",
            "target": TARGET_HELDOUT,
            "measured": results["heldout"]["r_at_1"],
            "delta": round(results["heldout"]["r_at_1"] - TARGET_HELDOUT, 4),
            "pass": abs(results["heldout"]["r_at_1"] - TARGET_HELDOUT) < TOLERANCE,
        },
        "fit_reproduces_session_h_offline": {
            "_source": "runs/session-h/rerank-fit.json -> q2_treatment_rerank_top10_pruned",
            "target": TARGET_FIT,
            "measured": results["fit"]["r_at_1"],
            "delta": round(results["fit"]["r_at_1"] - TARGET_FIT, 4),
            "pass": abs(results["fit"]["r_at_1"] - TARGET_FIT) < TOLERANCE,
        },
    }
    identical = all(c["pass"] for c in checks.values())

    print("\n" + "=" * 78)
    print("PIPELINE IDENTITY -- both halves, one function, one process")
    print("=" * 78)
    for name, c in checks.items():
        print(f"  {name:36s} target {c['target']:.4f}  measured {c['measured']:.4f}  "
              f"delta {c['delta']:+.4f}  {'PASS' if c['pass'] else 'FAIL'}")

    print("\nR@1 = input_recall x conditional_accuracy, both halves:\n")
    print(f"  {'split':>9}  {'n':>4}  {'R@1':>7}  {'input recall':>13}  {'cond. acc':>10}")
    for key in ("fit", "heldout"):
        r = results[key]
        ca = r["conditional_accuracy"]
        print(f"  {key:>9}  {r['cases']:>4}  {r['r_at_1']:>7.4f}  {r['input_recall']:>13.4f}  "
              f"{ca:>10.4f}")
    gap_r1 = results["fit"]["r_at_1"] - results["heldout"]["r_at_1"]
    gap_ir = results["fit"]["input_recall"] - results["heldout"]["input_recall"]
    gap_ca = results["fit"]["conditional_accuracy"] - results["heldout"]["conditional_accuracy"]
    print(f"\n  fit - heldout:   R@1 {gap_r1:+.4f}   input recall {gap_ir:+.4f}   "
          f"conditional accuracy {gap_ca:+.4f}")

    # What R@1 = 0.80 demands, restated as the factor the session can actually move.
    demands = {}
    for key in ("fit", "heldout"):
        ir = results[key]["input_recall"]
        demands[key] = {
            "input_recall": ir,
            "conditional_accuracy_now": results[key]["conditional_accuracy"],
            "conditional_accuracy_required_for_r1_080": round(0.80 / ir, 4) if ir else None,
            "attainable_at_this_depth": bool(ir and 0.80 / ir <= 1.0),
        }
    print("\nWhat R@1 >= 0.80 requires AT DEPTH 10, in conditional accuracy:")
    for key in ("fit", "heldout"):
        d = demands[key]
        req = d["conditional_accuracy_required_for_r1_080"]
        now = d["conditional_accuracy_now"]
        rel = (req / now - 1.0) * 100.0
        print(f"  {key:>9}  now {now:.4f}   required {req:.4f}   "
              f"a {rel:+.1f}% relative improvement in discrimination")

    report = {
        "_what": (
            "Session I Phase 0.1 -- the fit and held-out rerank pipelines measured through ONE "
            "function, to settle whether the 0.6201/0.5764 gap is case mix or a defect."
        ),
        "source_dump": "runs/session-f/all/",
        "reconstruction_licensing_gate": gate,
        "reranker": {"model": "L-2-int8", "sha256": digest, "batch": 1, "max_seq_len": 256,
                     "threads": 1, "provider": "CPUExecutionProvider",
                     "graph_optimization_level": "ORT_ENABLE_BASIC"},
        "shipped_slate": {"prune_N": prune_n, "session_gap_ms": gap_ms, "budget": BUDGET},
        "identity_checks": checks,
        "pipelines_identical": identical,
        "results": {k: {kk: vv for kk, vv in v.items() if kk != "_per_case"}
                    for k, v in results.items()},
        "gap_decomposition": {
            "_reading": (
                "R@1 factors exactly into input_recall x conditional_accuracy. Which factor moved "
                "between the splits is the whole content of the 'unexplained gap' issue."
            ),
            "r_at_1": round(gap_r1, 4),
            "input_recall": round(gap_ir, 4),
            "conditional_accuracy": round(gap_ca, 4),
        },
        "target_080_restated": demands,
        "per_category": {k: by_category(v["_per_case"]) for k, v in results.items()},
        "_per_case": {k: v["_per_case"] for k, v in results.items()},
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")

    if not identical:
        print("\nIDENTITY FAILED. Session I STOPS here. Every band in this session is derived on")
        print("fit and read on held-out; if the two halves are not the same pipeline, no band is")
        print("readable. Find the defect before registering anything.")
        return 1
    print("\nIDENTITY HOLDS. The two halves are the same pipeline and differ only in which cases")
    print("are in them. The gap is case mix, and the decomposition above says which factor carries")
    print("it. Bands may be derived on fit and read on held-out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
