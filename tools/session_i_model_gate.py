"""Session I, Phase 1.3 — the gate every candidate reranker passes before it enters a sweep.

Eight models, four architectures, two output-head conventions. Each one returns a float. **The
question is not whether it returns a float — it is whether the float means what the sweep will
assume it means**, and nothing downstream can tell the difference.

Five checks, and a model that fails any one is REFUSED rather than repaired:

  1. **digest** — the pinned graph, not a graph.
  2. **provider** — `CPUExecutionProvider` asserted after construction, never merely requested.
  3. **pair encoding** — the tokenizer produces two sequences, so the query/document boundary
     exists at all. (Both 1 and 3 are enforced inside `session_i_rerankers.load`.)
  4. **discrimination** — a relevant document must outscore an irrelevant one. This is the only
     check that catches a transposed pair encoding or an inverted two-class head, and both of
     those return entirely plausible numbers.
  5. **determinism** — identical input, identical bytes, re-verified per graph. ADR-013's rule is
     per graph and is not inheritable across a model swap.

Batch invariance is measured and REPORTED but is not a gate: the shipped path scores one pair per
call, so a batch failure cannot reach it. Session H's L-2-int8 read 0.0958 here and shipped anyway,
for exactly that reason.

Cost per pair is measured at the shipped sequence length so the frontier's cost axis exists before
any quality number does -- and so a model that is unaffordable is known to be unaffordable before
hours are spent on it.

    python tools/session_i_model_gate.py
"""

from __future__ import annotations

import json
import statistics
import time

from session_i_rerankers import (
    MODELS_DIR,
    REPO,
    SHIPPED_INT8,
    CrossEncoder,
    ModelRefused,
    batch_invariance,
    determinism,
    load,
    manifest,
    smoke_test,
)

OUT_PATH = REPO / "runs" / "session-i" / "model-gate.json"
COST_PAIRS = 40


def cost_per_pair(ce: CrossEncoder, max_len: int = 256) -> dict:
    """Median and p95 ms per pair at batch 1 -- the frontier's cost axis."""
    doc = ("I finally migrated the analytics warehouse off Postgres and onto ClickHouse in April, "
           "mostly because the nightly rollups were taking six hours. ") * 4
    ce.score("warm up the graph", doc, max_len)
    times = []
    for _ in range(COST_PAIRS):
        t = time.perf_counter()
        ce.score("which database did I migrate to", doc, max_len)
        times.append((time.perf_counter() - t) * 1000.0)
    times.sort()
    return {
        "median_ms": round(statistics.median(times), 3),
        "p95_ms": round(times[max(0, int(round(0.95 * len(times))) - 1)], 3),
        "pairs": COST_PAIRS, "max_len": max_len,
    }


def main() -> int:
    names = [SHIPPED_INT8] + [m["name"] for m in manifest()["models"]]
    results = {}
    refused = {}

    for name in names:
        print(f"\n{name}")
        try:
            ce = load(name)
        except ModelRefused as e:
            refused[name] = str(e)
            print(f"  REFUSED at load: {e}")
            continue
        except Exception as e:  # noqa: BLE001
            refused[name] = f"{type(e).__name__}: {e}"
            print(f"  REFUSED at load: {type(e).__name__}: {e}")
            continue

        print(f"  {ce.arch}, ~{ce.params_m}M, inputs {sorted(ce.input_names)}, "
              f"output_dim {ce.output_dim}, max_seq {ce.max_seq_supported}")

        smoke = smoke_test(ce)
        det = determinism(ce)
        inv = batch_invariance(ce)
        cost = cost_per_pair(ce)
        gated = smoke["pass"] and det["pass"]

        print(f"  discrimination  relevant {smoke['relevant']:+.4f}  "
              f"irrelevant {smoke['irrelevant']:+.4f}  margin {smoke['margin']:+.4f}  "
              f"{'PASS' if smoke['pass'] else 'FAIL -- REFUSED'}")
        print(f"  determinism     {'PASS' if det['pass'] else 'FAIL -- REFUSED'}  "
              f"({len(set(det['values']))} distinct over {len(det['values'])} runs)")
        print(f"  batch inv.      max |b1-bN| {inv['max_abs_diff']:.6f}  "
              f"({'identical' if inv['identical'] else 'differs -- reported, not a gate'})")
        print(f"  cost @256       median {cost['median_ms']:.2f} ms/pair  "
              f"p95 {cost['p95_ms']:.2f} ms")

        results[name] = {
            "arch": ce.arch, "params_m": ce.params_m, "digest": ce.digest,
            "inputs": sorted(ce.input_names), "output_dim": ce.output_dim,
            "max_seq_supported": ce.max_seq_supported,
            "discrimination": smoke, "determinism": det,
            "batch_invariance": inv, "cost": cost,
            "admitted": bool(gated),
        }
        if not gated:
            refused[name] = "failed discrimination or determinism; see model-gate.json"

    admitted = [n for n, r in results.items() if r["admitted"]]
    print("\n" + "=" * 78)
    print(f"ADMITTED TO THE SWEEP: {len(admitted)}/{len(names)}")
    print("=" * 78)
    print(f"  {'model':>36} {'arch':>14} {'params':>7} {'ms/pair':>8} {'margin':>9}")
    for n in sorted(admitted, key=lambda x: results[x]["cost"]["median_ms"]):
        r = results[n]
        print(f"  {n:>36} {r['arch']:>14} {r['params_m']:>6}M "
              f"{r['cost']['median_ms']:>8.2f} {r['discrimination']['margin']:>9.4f}")
    if refused:
        print("\nREFUSED:")
        for n, why in refused.items():
            print(f"  {n}\n    {why}")

    # The sweep's cost, projected from the measured per-pair cost, so the plan is sized before it
    # is run rather than discovered to be unaffordable halfway through.
    print("\nProjected fit-split cost (229 cases), per configuration:")
    print(f"  {'model':>36} {'depth 10':>10} {'depth 20':>10} {'depth 30':>10}")
    for n in sorted(admitted, key=lambda x: results[x]["cost"]["median_ms"]):
        ms = results[n]["cost"]["median_ms"]
        fmt = lambda d: f"{229 * d * ms / 60000:.1f} min"  # noqa: E731
        print(f"  {n:>36} {fmt(10):>10} {fmt(20):>10} {fmt(30):>10}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "_what": "Session I Phase 1.3 -- the load-time gate every candidate reranker must pass.",
        "_gates": ["digest", "provider asserted", "pair encoding", "discrimination", "determinism"],
        "_not_a_gate": (
            "batch invariance -- the shipped path scores one pair per call, so a batch failure "
            "cannot reach it. Measured per graph and reported."
        ),
        "results": results, "admitted": admitted, "refused": refused,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0 if admitted else 1


if __name__ == "__main__":
    raise SystemExit(main())
