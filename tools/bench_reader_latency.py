"""Latency bench for the answerability reader (mobilebert, seq 256) on CUDA.

Measures what shipping the half-weight reader would add to a cascade query: one score per
narrowed candidate, ten candidates. Warm timing, representative lengths, plus the projected
end-to-end total against the 300 ms budget.

    python tools/bench_reader_latency.py --provider CUDAExecutionProvider
"""

from __future__ import annotations

import argparse
import statistics as st
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import readers  # noqa: E402

CASES = [
    ("short", "What breed is my dog?",
     "28. Kg3 would be my move."),
    ("medium", "What should I serve for dinner this weekend with my homegrown ingredients?",
     "I've been using basil and mint in my cooking lately. I've even harvested some cherry tomatoes "
     "from my garden. Do you have any suggestions for companion plants that could help them grow?"),
    ("long", "What was the chord progression for the chorus in the second song?",
     "Sure, here's a song for you: " + ("Verse: G A B C D E D C B A G with lyrics about the sea "
                                        "and the wind and the waiting shore. " * 18)),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    args = ap.parse_args()
    r = readers.load("mobilebert-uncased-squad-v2", provider=args.provider)

    # warm
    for _ in range(5):
        r.score(CASES[0][1], CASES[0][2])

    per_call = {name: [] for name, _, _ in CASES}
    for rep in range(30):
        for name, q, d in CASES:
            t0 = time.perf_counter()
            r.score(q, d)
            per_call[name].append((time.perf_counter() - t0) * 1000)

    print(f"reader latency ms/call ({args.provider}, warm, n=30):")
    slate_total = 0.0
    worst = 0.0
    for name, _, _ in CASES:
        xs = sorted(per_call[name])
        p50 = xs[len(xs) // 2]
        p95 = xs[int(len(xs) * 0.95) - 1]
        slate_total += p50
        worst += p95
        print(f"  {name:6} p50 {p50:7.2f}   p95 {p95:7.2f}")
    # a real slate is ten candidates of mixed length; approximate as 4 short/4 medium/2 long
    projected = 4 * st.median(per_call["short"]) + 4 * st.median(per_call["medium"]) \
        + 2 * st.median(per_call["long"])
    print(f"\nprojected added cost per cascade query (10 candidates): {projected:.1f} ms")
    print(f"projected end-to-end P95 (cascade measured 29.4 ms + this): {29.4 + worst:.1f} ms "
          f"of the 300 ms budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
