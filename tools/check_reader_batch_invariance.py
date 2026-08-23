"""Batch-vs-single invariance for the mobilebert reader graph, done CORRECTLY.

Compares the derived answerability score (span - null) per pair, and the raw logits per row,
between one [10,256] batched forward and ten [1,256] single forwards.

    python tools/check_reader_batch_invariance.py --provider CUDAExecutionProvider
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

REPO = Path = None  # placeholder to keep import shape obvious
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import readers  # noqa: E402

DOCS = [
    "28. Kg3 would be my move.",
    "I took my niece to the Natural History Museum on 2/8.",
    "I planted 12 tomato saplings today.",
    "Golden Retriever collar recommendations for Max.",
    "Hoop Dance is performed by skilled dancers.",
    "Turbinado sugar adds a richer flavor to cookies.",
    "Fender Stratocaster vs Gibson Les Paul main differences.",
    "Budget hostel near the Red Light District, Amsterdam.",
    "Walked down the aisle as a bridesmaid at my cousin's wedding.",
    "Podcasts for my commute: true crime and self-improvement.",
]
Q = "What breed is my dog?"


def score_row(start: np.ndarray, end: np.ndarray, type_ids: list[int], mask: list[int]) -> float:
    null = float(start[0] + end[0])
    idx = [i for i, s in enumerate(type_ids) if s == 1 and mask[i] == 1]
    if not idx:
        return 0.0
    lo, hi = idx[0], idx[-1]
    s_win, e_win = start[lo:hi + 1], end[lo:hi + 1]
    best = np.maximum.accumulate(s_win)
    return float(np.max(best + e_win)) - null


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="CUDAExecutionProvider")
    args = ap.parse_args()
    r = readers.load("mobilebert-uncased-squad-v2", provider=args.provider)

    pairs = [r._encode(Q, d, readers.MAX_SEQ) for d in DOCS]  # noqa: SLF001
    ids = np.array([e.ids for e in pairs], dtype=np.int64)
    mask = np.array([e.attention_mask for e in pairs], dtype=np.int64)
    types = np.array([e.type_ids for e in pairs], dtype=np.int64)

    for _ in range(3):
        r.session.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": types})

    bout = r.session.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": types})
    b_start, b_end = np.asarray(bout[0]), np.asarray(bout[1])

    worst_logit = 0.0
    worst_score = 0.0
    for i, e in enumerate(pairs):
        out = r.session.run(None, {"input_ids": ids[i:i + 1], "attention_mask": mask[i:i + 1],
                                   "token_type_ids": types[i:i + 1]})
        s_start, s_end = np.asarray(out[0])[0], np.asarray(out[1])[0]
        worst_logit = max(worst_logit,
                          float(np.abs(b_start[i] - s_start).max()),
                          float(np.abs(b_end[i] - s_end).max()))
        bs = score_row(b_start[i], b_end[i], e.type_ids, e.attention_mask)
        ss = score_row(s_start, s_end, e.type_ids, e.attention_mask)
        worst_score = max(worst_score, abs(bs - ss))
    print(f"rows compared: {len(DOCS)}")
    print(f"max abs logit delta  (batched vs single): {worst_logit:.9f}")
    print(f"max abs SCORE delta  (batched vs single): {worst_score:.9f}")
    verdict = "PASS (bit-level)" if worst_score == 0.0 else (
        "PASS (sub-decision)" if worst_score < 1e-3 else "FAIL")
    print(f"verdict: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
