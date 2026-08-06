"""Session G — a Python BM25 matching `cue/lexical.rs`, and the gate that licenses using it.

Arm 2 expands the *query* with new terms, so unlike arms that only reorder a fixed pool it needs
the lexical cue recomputed. That is a second implementation of a scored-path component, and the
pre-registration requires it to reproduce Session F's stored `lexical_bm25` column on the
UNMODIFIED query before any expanded-query number may be quoted.

Everything here is transcribed from `cue/lexical.rs` rather than reinvented, including the parts
that look like they should not matter:

  * corpus statistics are taken over **the candidate set being ranked**, not a global corpus;
  * IDF is the BM25+/Lucene form `ln(1 + (N - df + 0.5)/(df + 0.5))`, which never goes negative;
  * query terms are deduplicated **in order of first appearance**;
  * accumulation is in f64 and cast to f32 once at the end;
  * the stored column is *saturated*, `s / (s + 10)`, not raw.

Each of those changes the number, and the gate is what proves the transcription took.
"""

from __future__ import annotations

import numpy as np

BM25_K1 = 1.2
BM25_B = 0.75
BM25_SATURATION = 10.0


def tokenize(text: str) -> list[str]:
    """ASCII-lowercased; non-alphanumeric is a boundary. No stemming, no stop list.

    Non-ASCII alphanumerics pass through unchanged, matching `to_ascii_lowercase` being a no-op
    on them. Digits are kept deliberately -- the temporal category turns on dates.
    """
    out: list[str] = []
    current: list[str] = []
    for ch in text:
        if ch.isascii() and ch.isalnum():
            current.append(ch.lower())
        elif ch.isalnum():
            current.append(ch)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def score_all(doc_terms: list[list[str]], query_text: str) -> np.ndarray:
    """Raw BM25 for every document, in the order given. Mirrors `lexical::score_all`."""
    n = len(doc_terms)
    if n == 0:
        return np.zeros(0, dtype=np.float32)

    lengths = [len(t) for t in doc_terms]
    total = sum(lengths)
    avgdl = (total / n) if total else 1.0

    tf_maps: list[dict[str, int]] = []
    df: dict[str, int] = {}
    for terms in doc_terms:
        tf: dict[str, int] = {}
        for term in terms:
            tf[term] = tf.get(term, 0) + 1
        for term in tf:
            df[term] = df.get(term, 0) + 1
        tf_maps.append(tf)

    query_terms: list[str] = []
    for term in tokenize(query_text):
        if term not in query_terms:
            query_terms.append(term)

    scores = np.zeros(n, dtype=np.float64)
    for term in query_terms:
        df_t = df.get(term, 0)
        if df_t == 0:
            continue
        idf = np.log(1.0 + (n - df_t + 0.5) / (df_t + 0.5))
        for i, tf in enumerate(tf_maps):
            f = tf.get(term, 0)
            if f == 0:
                continue
            norm = 1.0 - BM25_B + BM25_B * (lengths[i] / avgdl)
            scores[i] += idf * (f * (BM25_K1 + 1.0)) / (f + BM25_K1 * norm)
    return scores.astype(np.float32)


def saturate(raw: np.ndarray) -> np.ndarray:
    """`s / (s + 10)`, clamped at zero. Absolute, never min-max over the candidate set."""
    s = raw.astype(np.float64)
    out = np.where(s <= 0.0, 0.0, s / (s + BM25_SATURATION))
    return out.astype(np.float32)


def gate(pools, texts, sample: int = 40) -> dict:
    """Reproduce the stored `lexical_bm25` column on the unmodified query.

    Registered tolerance is deliberately looser than the dense side's: BM25 depends on corpus
    statistics and tokenization that the Rust cue owns, so an exact match would be surprising and
    a rank-equivalent match is what the arm actually needs, because the arm reads top-1.
    """
    from scipy.stats import spearmanr

    qids = sorted(pools)[:sample]
    rhos: list[float] = []
    top1_same = 0
    max_abs = 0.0
    for qid in qids:
        pool = pools[qid]
        doc_terms = [tokenize(texts[qid].get(c.turn_id, "")) for c in pool.candidates]
        mine = saturate(score_all(doc_terms, pool.question))
        stored = pool.array("lexical_bm25").astype(np.float32)
        max_abs = max(max_abs, float(np.abs(mine - stored).max()))
        rho = spearmanr(mine, stored).statistic
        rhos.append(1.0 if np.isnan(rho) else float(rho))
        top1_same += int(np.argmax(mine) == np.argmax(stored))

    min_rho = float(np.min(rhos))
    top1_rate = top1_same / len(qids)
    return {
        "_what": "Python BM25 vs the stored lexical_bm25 column, unmodified query.",
        "cases_compared": len(qids),
        "min_spearman": round(min_rho, 6),
        "mean_spearman": round(float(np.mean(rhos)), 6),
        "top1_identical_rate": round(top1_rate, 4),
        "max_abs_diff": max_abs,
        "tolerance": {"min_spearman": 0.999, "top1_identical_rate": 0.99},
        "pass": min_rho >= 0.999 and top1_rate >= 0.99,
    }


def main() -> int:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from reach_pools import load_pools, turn_texts

    pools, _ = load_pools()
    report = gate(pools, turn_texts())
    print("Reproduction gate -- Python BM25 vs stored lexical_bm25\n")
    print(f"  cases compared          {report['cases_compared']}")
    print(f"  min / mean Spearman     {report['min_spearman']:.6f} / {report['mean_spearman']:.6f}"
          f"   (tolerance 0.999)")
    print(f"  top-1 identical         {report['top1_identical_rate']:.4f}   (tolerance 0.99)")
    print(f"  max abs diff            {report['max_abs_diff']:.3e}")
    print()
    print("GATE PASSED." if report["pass"] else "GATE FAILED -- arm 2's lexical half is NOT MEASURED.")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
