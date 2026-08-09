"""Batch invariance at batch = 10, on the SHIPPED graph, over the REAL held-out slates.

Session K measured batch invariance at 0.000000 on this graph and STATE.md records the rule that
makes that insufficient: **determinism, batch and padding invariance are re-measured PER GRAPH and
never inherited.** This session adds a second reason the earlier number does not discharge the
question, and it is about the workload rather than the graph:

  * Session K's check (`session_i_rerankers.batch_invariance`) uses **n = 8** synthetic documents
    that differ only by a trailing integer -- `"...attempt number {i}."`. Every one encodes to
    nearly the same length. A batch effect that depends on heterogeneous sequence lengths inside
    the batch would not appear.
  * The change being gated batches **10** pairs, the real `RERANK_BUDGET`, drawn from a real slate
    whose members range from a few word-pieces to the full 256-token cap.

So this measures the thing the change will actually do: score one shipped depth-10 slate as a
`[10, 256]` batch, and compare against the same ten pairs scored one at a time.

**Padding is unchanged and stays at a fixed 256.** Batching alone is being gated here; trimming the
padding to the batch maximum is a SEPARATE change with its own invariance question, and rolling the
two together would leave a failure attributable to neither.

Three quantities, and the third is the one that decides adoption:

  max_abs_delta    largest |batched - single| logit difference anywhere
  exact_equality   fraction of pairs where the two are bit-identical
  order_changes    slates whose depth-10 ORDER differs, and slates whose TOP-1 differs

Adoption requires exact equality on every pair. Anything less means the batched path is a
different scorer and the byte-identity gate on `scored-candidates.ndjson` cannot hold.

Applies nothing, changes nothing, ships nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

# `session_j_models.load_finetuned`, not `session_i_rerankers.load`: the shipped graph is this
# project's own fine-tune and lives in the Session J manifest, not the fetched-model one. Both
# loaders pin ORT_ENABLE_BASIC, one thread, the asserted provider and the raw `tokenizers.Tokenizer`
# -- which is the combination STATE.md requires, and a `PreTrainedTokenizerFast` wrapper over the
# same file has already produced logits 3.56 apart in this project.
from session_j_models import load_finetuned  # noqa: E402

SHIPPED = "ms-marco-MiniLM-L-2-v2-ft-session-j"
SLATES = REPO / "runs" / "session-m0c" / "slates-{split}.json"
OUT = REPO / "runs" / "session-l" / "batch-invariance-batch10.json"

# The shipped constants. Named here so a drift in either is a loud mismatch rather than a quietly
# different measurement wearing this one's name.
MAX_SEQ_LEN = 256
RERANK_BUDGET = 10


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="heldout", choices=["fit", "heldout"])
    ap.add_argument("--slates", type=int, default=None, help="limit for a quick check")
    ap.add_argument("--sweep-slates", type=int, default=40,
                    help="slates used for the batch-size sweep 1..10. Smaller than the full "
                         "split because the sweep is 55 forwards per slate, and the question "
                         "it answers is categorical rather than statistical.")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    slates_path = Path(str(SLATES).format(split=args.split))
    data = json.loads(slates_path.read_text(encoding="utf-8"))
    records = data["records"]
    if args.slates:
        records = records[: args.slates]

    ce = load_finetuned(SHIPPED)
    print(f"{SHIPPED}  digest {ce.digest[:16]}...  ORT_ENABLE_BASIC, 1 thread, "
          f"provider asserted")
    print(f"slates: {len(records)} from {args.split}, depth {RERANK_BUDGET}, seq {MAX_SEQ_LEN}\n")

    def reduce(arr):
        arr = np.asarray(arr)
        return arr.reshape(-1) if ce.output_dim == 1 else arr[:, 1] - arr[:, 0]

    worst = 0.0
    identical_pairs = 0
    total_pairs = 0
    order_changes = 0
    top1_changes = 0
    wordpiece_spread = []

    for record in records:
        question = record["question"]
        texts = record["texts"][:RERANK_BUDGET]
        if len(texts) != RERANK_BUDGET:
            continue

        encs = [ce.encode(question, t, MAX_SEQ_LEN) for t in texts]
        feed = {
            "input_ids": np.array([e.ids for e in encs], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encs], dtype=np.int64),
        }
        if "token_type_ids" in ce.input_names:
            feed["token_type_ids"] = np.array([e.type_ids for e in encs], dtype=np.int64)

        # The shape the change will run: one [10, 256] forward.
        batched = reduce(ce.session.run(None, feed)[0])
        # The shape shipped today: ten [1, 256] forwards.
        singles = np.array([
            reduce(ce.session.run(None, {k: v[i:i + 1] for k, v in feed.items()})[0])[0]
            for i in range(RERANK_BUDGET)
        ])

        worst = max(worst, float(np.abs(batched - singles).max()))
        identical_pairs += int(np.sum(batched == singles))
        total_pairs += RERANK_BUDGET

        # Ordering is what actually reaches the wire. A delta too small to see in the logits can
        # still swap two adjacent candidates, and that is what would break byte-identity.
        if not np.array_equal(np.argsort(-batched, kind="stable"),
                              np.argsort(-singles, kind="stable")):
            order_changes += 1
        if int(np.argmax(batched)) != int(np.argmax(singles)):
            top1_changes += 1

        lengths = record.get("wordpieces") or []
        if lengths:
            wordpiece_spread.append((min(lengths), max(lengths)))

    # ---- the sweep: EVERY batch size the shipped path can actually produce ------------------
    #
    # The depth-10 slate is `budget` survivors truncated to 10, so a pool with fewer survivors
    # produces a SHORTER batch. Measuring only at 10 would leave every smaller batch unmeasured
    # and defended by an argument -- "BERT rows are independent given the mask" -- which is exactly
    # the shape of reasoning this project requires a number for. On the corpus the slate is
    # essentially always 10, so the untested sizes are the PRODUCTION ones, not the benchmark's.
    sweep = {}
    for size in range(1, RERANK_BUDGET + 1):
        worst_at_size = 0.0
        pairs_at_size = 0
        equal_at_size = 0
        for record in records[: args.sweep_slates]:
            texts = record["texts"][:size]
            if len(texts) != size:
                continue
            encs = [ce.encode(record["question"], t, MAX_SEQ_LEN) for t in texts]
            feed = {
                "input_ids": np.array([e.ids for e in encs], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in encs], dtype=np.int64),
            }
            if "token_type_ids" in ce.input_names:
                feed["token_type_ids"] = np.array([e.type_ids for e in encs], dtype=np.int64)
            batched = reduce(ce.session.run(None, feed)[0])
            singles = np.array([
                reduce(ce.session.run(None, {k: v[i:i + 1] for k, v in feed.items()})[0])[0]
                for i in range(size)
            ])
            worst_at_size = max(worst_at_size, float(np.abs(batched - singles).max()))
            equal_at_size += int(np.sum(batched == singles))
            pairs_at_size += size
        sweep[size] = {
            "max_abs_delta": worst_at_size,
            "pairs": pairs_at_size,
            "exact": (equal_at_size / pairs_at_size) if pairs_at_size else 0.0,
        }

    sweep_clean = all(v["max_abs_delta"] == 0.0 and v["exact"] == 1.0 for v in sweep.values())

    exact = identical_pairs / total_pairs if total_pairs else 0.0
    verdict = (worst == 0.0 and exact == 1.0 and order_changes == 0 and sweep_clean)

    spread_lo = min(s[0] for s in wordpiece_spread) if wordpiece_spread else None
    spread_hi = max(s[1] for s in wordpiece_spread) if wordpiece_spread else None

    report = {
        "_what": "batch invariance at batch=10 on the shipped graph, over real held-out slates",
        "_why_not_inherited": (
            "determinism, batch and padding invariance are re-measured PER GRAPH and never "
            "inherited (STATE.md standing checks). Session K's read was also taken at n=8 on "
            "synthetic near-equal-length documents, which cannot see a length-heterogeneity "
            "effect inside the batch."
        ),
        "model": SHIPPED,
        "digest": ce.digest,
        "split": args.split,
        "slates": len(records),
        "depth": RERANK_BUDGET,
        "max_seq_len": MAX_SEQ_LEN,
        "padding": "fixed 256, UNCHANGED -- only batching is gated here",
        "optimization_level": "ORT_ENABLE_BASIC (matches ort Level1)",
        "threads": 1,
        "wordpiece_range_across_slates": [spread_lo, spread_hi],
        "max_abs_delta": worst,
        "pairs_compared": total_pairs,
        "exact_equality_fraction": exact,
        "slates_with_changed_order": order_changes,
        "slates_with_changed_top1": top1_changes,
        "batch_size_sweep": {str(k): v for k, v in sweep.items()},
        "_why_the_sweep": (
            "a pool with fewer than `budget` survivors produces a SHORTER batch. Measuring "
            "only at 10 would leave every production-reachable smaller batch resting on the "
            "argument that BERT rows are independent given the mask, rather than on a number."
        ),
        "verdict": "INVARIANT" if verdict else "NOT INVARIANT",
        "adoption": (
            "batching may be adopted; it is quality-neutral by identity and the byte-identity "
            "gate on scored-candidates.ndjson can hold"
            if verdict else
            "batching MUST NOT be adopted: the batched path is a different scorer on this graph"
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"word-piece range across slates: {spread_lo} .. {spread_hi}")
    print(f"max |batched - single|        : {worst:.9f}")
    print(f"exact equality                : {identical_pairs}/{total_pairs} ({exact:.6%})")
    print(f"slates with changed order     : {order_changes}")
    print(f"slates with changed top-1     : {top1_changes}")
    print("\nbatch-size sweep (1..10), max |delta| / exact:")
    for k, v in sweep.items():
        print(f"  batch {k:>2}: {v['max_abs_delta']:.9f}  {v['exact']:.4%}  ({v['pairs']} pairs)")
    print(f"\nVERDICT: {report['verdict']}")
    print(f"-> {args.out}")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
