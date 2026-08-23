"""M0c Session N gate checker: does the WIRED binary reproduce the pre-registered cascade?

One tool, one dump, two orderings reconstructed from the SAME bytes -- so the control and the
arm cannot come from different instruments:

  control  the shipped five-level key (survivors, rerank desc, z, margin, id)
           must reproduce this split's PUBLISHED numbers EXACTLY, or nothing here means anything
  arm      fusion_rank ascending (absent last, ties by candidate row order)
           must reproduce runs/session-m0c-n/PREREGISTRATION.json's registered case counts EXACTLY

A difference is a WIRING finding, never a quality finding: the configuration was measured and
pre-registered in session-m0c-m; what is under test is whether the Rust path is that path.

    python tools/cascade_verify.py --run runs/session-m0c-n/control-fit --split fit
    python tools/cascade_verify.py --run runs/session-m0c-n/cascade-fit  --split fit --expect-cascade
    python tools/cascade_verify.py --run runs/session-m0c-n/heldout-cascade --split heldout --expect-cascade
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from reach_pools import load_pools  # noqa: E402
from sweep_reranker_frontier import shipped_order  # noqa: E402

# The published shipped-path numbers, per split. The CONTROL half of every gate.
PUBLISHED = {
    "fit": {"R@1": 0.7555, "R@3": 0.8996},
    "heldout": {"R@1": 0.6725, "R@3": 0.8515},
}

# The pre-registered cascade expectations, as (cases, n) so a mismatch prints in cases.
# Source: runs/session-m0c-m PREREGISTRATION-CASCADE-HELDOUT.json (fit_results_being_tested)
# and cascade-heldout-read.json (the spent read). Re-stated in session N's own registration.
CASCADE_EXPECTED = {
    "fit": {"R@1": (180, 229), "R@3": (213, 229)},
    "heldout": {"R@1": (160, 229), "R@3": (203, 229)},
}


def gold_rank(order: list[int], gold: list[bool]) -> int | None:
    """1-based rank of the first gold candidate under `order`, or None."""
    return next((r for r, i in enumerate(order, 1) if gold[i]), None)


def rk(ranks: list[int | None], k: int, n: int) -> tuple[float, int]:
    hits = sum(1 for r in ranks if r is not None and r <= k)
    return hits / n, hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--split", choices=["fit", "heldout"], required=True)
    ap.add_argument("--expect-cascade", action="store_true",
                    help="enforce the registered cascade counts (else report them informationally)")
    args = ap.parse_args()

    pools, stats = load_pools(args.run)
    n = len(pools)
    print(f"pools: {n} queries, {stats['candidates']:,} candidates "
          f"(unattributable rows: {stats['unattributable_rows']})")
    failures: list[str] = []

    # ── control: the shipped key, from this run's own dump ──────────────────────────────
    ctl_r1: list[int | None] = []
    ctl_r3: list[int | None] = []
    fused_anywhere = False
    for q, p in pools.items():
        gold = [bool(c.is_gold) for c in p.candidates]
        order = [int(v) for v in shipped_order(p)]
        ctl_r1.append(gold_rank(order[:1], gold))
        # rank against the FULL ordering so R@3 is honest even when gold sits deeper
        full = gold_rank(order, gold)
        ctl_r1[-1] = full if (full == 1) else None
        ctl_r3.append(full if (full is not None and full <= 3) else None)
        fused_anywhere |= any(c.fusion_rank is not None for c in p.candidates)

    pub = PUBLISHED[args.split]
    for name, ranks in (("R@1", ctl_r1), ("R@3", ctl_r3)):
        value, hits = rk(ranks, 1 if name == "R@1" else 3, n)
        if args.expect_cascade:
            # In a cascade dump the shipped key reads the NARROWING graph's ordering over all 30
            # slate members -- a different quantity from the shipped depth-10 configuration, whose
            # control was discharged on its own run. Reported, never gated here.
            print(f"info shipped-key read of this dump {name}: {hits}/{n} = {value:.4f} "
                  f"(depth-30 population; NOT the shipped configuration)")
        else:
            ok = abs(value - pub[name]) < 5e-5
            print(f"GATE control {name}: {hits}/{n} = {value:.4f}  published {pub[name]:.4f}  "
                  f"{'PASS' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"control {name}")

    if args.expect_cascade:
        if not fused_anywhere:
            print("GATE cascade columns: FAIL -- no fusion_rank anywhere in the dump. "
                  "The cascade did not run under this label.")
            return 1
        print(f"cascade columns present: yes")
    elif not fused_anywhere and not any(
        c.rerank_score is not None for p in pools.values() for c in p.candidates
    ):
        print("NOTE: no rerank columns at all -- was --reranking off?")

    # ── arm: the cascade ordering, when this run produced one ────────────────────────────
    if fused_anywhere:
        cas_r1: list[int | None] = []
        cas_r3: list[int | None] = []
        ir30 = 0
        post_narrow = 0
        for q, p in pools.items():
            gold = [bool(c.is_gold) for c in p.candidates]
            idx_by_row = list(range(len(p.candidates)))
            # fusion_rank ascending; absent LAST; ties by row order (= id order = pool index),
            # which is exactly the binary's final-key behaviour below the fusion level.
            order = sorted(idx_by_row,
                           key=lambda i: ((p.candidates[i].fusion_rank is None),
                                          p.candidates[i].fusion_rank or 0, i))
            ir30 += any(gold[i] for i, c in enumerate(p.candidates) if c.rerank_score is not None)
            post_narrow += any(c.fusion_rank is not None and g
                               for c, g in zip(p.candidates, gold))
            full = gold_rank(order, gold)
            cas_r1.append(full if full == 1 else None)
            cas_r3.append(full if (full is not None and full <= 3) else None)

        exp = CASCADE_EXPECTED[args.split]
        for name, ranks in (("R@1", cas_r1), ("R@3", cas_r3)):
            _, hits = rk(ranks, 1 if name == "R@1" else 3, n)
            want, want_n = exp[name]
            ok = (hits == want) and n == want_n
            print(f"GATE cascade {name}: {hits}/{n} = {hits/n:.4f}  "
                  f"registered {want}/{want_n} = {want/want_n:.4f}  {'PASS' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"cascade {name}")
        print(f"info input_recall@slate {ir30}/{n} = {ir30/n:.4f}   "
              f"gold surviving the narrowing {post_narrow}/{n} = {post_narrow/n:.4f}   "
              f"cond@3 {(cas_r3 and sum(x is not None for x in cas_r3)/max(ir30,1)):.4f}")

    if failures:
        print(f"\nVERDICT: REFUSED -- {', '.join(failures)} failed. "
              "Fix the instrument before believing anything downstream.")
        return 1
    print("\nVERDICT: all gates PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
