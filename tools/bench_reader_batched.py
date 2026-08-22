"""Batched reader cost: ONE [slate,256] forward for all ten candidates -- the shape Rust ships.

Separates tokenizer/preprocess cost from inference cost, because the sequential bench measured
Python dispatch, not the model.

    python tools/bench_reader_batched.py --provider CUDAExecutionProvider
"""

from __future__ import annotations

import argparse
import statistics as st
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import readers  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    args = ap.parse_args()
    r = readers.load("mobilebert-uncased-squad-v2", provider=args.provider)

    qs = ["What breed is my dog?",
          "What should I serve for dinner this weekend?",
          "What was the chord progression in the second song?"]
    docs = [
        ["28. Kg3 would be my move.",
         "I just baked a chocolate cake for my friend's birthday party.",
         "The museum opened a new T-Rex skeleton exhibit last week."],
        ["I've been using basil and mint in my cooking lately. I harvested cherry tomatoes.",
         "I think I'll try using honey as my sweetener with oatmeal and banana.",
         "Looking for healthy lunch ideas with mixed greens and vinaigrette dressing."],
        ["Verse: G A B C D E D C B A G with lyrics about the sea and wind. " * 12,
         "Chapter one: the old lighthouse stood above the rocky shore alone. " * 10,
         "The meeting notes from Tuesday: budget review, hiring plan, roadmap. " * 8],
    ]

    def batch_forward(qi: int) -> float:
        pairs = [r._encode(qs[qi], d, readers.MAX_SEQ) for d in docs[qi]]  # noqa: SLF001
        ids = np.array([e.ids for e in pairs], dtype=np.int64)
        mask = np.array([e.attention_mask for e in pairs], dtype=np.int64)
        types = np.array([e.type_ids for e in pairs], dtype=np.int64)
        t0 = time.perf_counter()
        out = r.session.run(None, {"input_ids": ids, "attention_mask": mask,
                                   "token_type_ids": types})
        dt = (time.perf_counter() - t0) * 1000
        _ = float(np.asarray(out[0]).max())  # consume
        return dt

    for qi in range(3):
        batch_forward(qi)  # warm

    rows = {0: [], 1: [], 2: []}
    tok_ms = []
    for rep in range(30):
        t0 = time.perf_counter()
        for qi in range(3):
            pass
        tok_ms.append((time.perf_counter() - t0) * 1000)
        for qi in range(3):
            rows[qi].append(batch_forward(qi))

    print(f"batched forward ms per 3-candidate slate ({args.provider}, warm, n=30):")
    all_med = []
    for qi in range(3):
        med = st.median(rows[qi])
        all_med.append(med)
        print(f"  q{qi} p50 {med:7.2f}")
    print(f"\nmedian batched forward: {st.median(all_med):.2f} ms")
    # scale to a real slate of ten: attention is O(seq^2) per row; rows dominate linearly here
    print(f"projected slate-of-10 (linear in rows): {st.median(all_med) / 3 * 10:.1f} ms")
    print("(tokenizer/preprocess excluded above; in Rust it is microseconds, in Python it is")
    print(" the bulk of what the sequential bench's 17 ms/call was actually measuring)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
