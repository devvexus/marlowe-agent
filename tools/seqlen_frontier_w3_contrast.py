"""W3's paired contrast, read off the artifact `seqlen_frontier_w3.py` wrote.

Separate from the sweep so the sweep is never re-run to obtain a statistic. `mcnemar_exact` is
imported from `session_i_seqlen`, not re-derived -- ADR-014's floor (the smallest two-sided p an
exact McNemar can produce at n discordant pairs is 2/2^n, so alpha 0.05 needs n >= 6) is that
file's rule and is reported beside every p.

    python tools/seqlen_frontier_w3_contrast.py --run runs/session-m0c-m/seqlen-frontier-w3-cpu.json
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

from session_i_seqlen import MIN_DISCORDANT_FOR_ALPHA, mcnemar_exact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    d = json.loads(io.open(args.run, encoding="utf-8").read())
    cells, pc = d["cells"], d["_per_case"]
    models = sorted({c["model"] for c in cells.values()})
    depths = sorted({c["depth"] for c in cells.values()})
    lengths = sorted({c["max_seq"] for c in cells.values()})

    print(f"provider: {d['provider']}   gate R@1 {d['gate']['R@1']} vs published "
          f"{d['gate']['published']}")
    print(f"ADR-014 floor: alpha 0.05 needs >= {MIN_DISCORDANT_FOR_ALPHA} discordant pairs\n")
    print(f"{'model':<38} {'d':>3} {'seq':>5} {'R@1':>7} {'dR@1':>8} {'cur':>7} {'ir':>7} "
          f"{'ca':>7} {'gain':>5} {'lost':>5} {'p':>7} {'pmin':>7} {'ms p50':>8}")
    for m in models:
        for dep in depths:
            base_key = f"{m}@d{dep}@{lengths[0]}"
            base_r1 = cells[base_key]["R@1"]
            a = pc[base_key]
            for L in lengths:
                k = f"{m}@d{dep}@{L}"
                c = cells[k]
                b = pc[k]
                shared = sorted(set(a) & set(b))
                gained = sum(1 for q in shared if b[q] and not a[q])
                lost = sum(1 for q in shared if a[q] and not b[q])
                p, pmin = mcnemar_exact(lost, gained)
                print(f"{m:<38} {dep:>3} {L:>5} {c['R@1']:>7.4f} {c['R@1'] - base_r1:>+8.4f} "
                      f"{c['R@1_current']:>7.4f} {c['input_recall']:>7.4f} "
                      f"{c['conditional_accuracy']:>7.4f} {gained:>5} {lost:>5} "
                      f"{p:>7.4f} {pmin:>7.4f} {c['rerank_ms_p50']:>8.2f}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
