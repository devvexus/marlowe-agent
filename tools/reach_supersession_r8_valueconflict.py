"""R8 -- candidate signal 1: entity-relation conflict, and whether an approximation of it exists.

R7 killed signal 2. A global cosine threshold reaches 0.0745 precision at best, and under the
registered asymmetry -- a false supersession removes a live memory permanently and silently -- that
destroys roughly twelve live memories per correct supersession.

Signal 1 is HP4's contradiction detector: two beliefs asserting DIFFERENT VALUES for the same
(entity, relation) pair. **Real entity and relation extraction does not exist in this workspace and
building it is a milestone, not a session.** So the question here is narrower and answerable today:

  is there an APPROXIMATION of "same slot, different value" that separates the 33 true supersession
  pairs from the 15,789 distractor pairs the similarity signal could not?

The approximation measured is deliberately crude and its blind spots are stated rather than
discovered later:

  VALUE TOKENS -- numbers, times, dates, money and capitalised non-sentence-initial words. A
  supersession of a *measured* fact ("27:12" -> "25:50", "$40" -> "$55") changes one of these while
  the surrounding context stays similar. The pattern is: high context overlap, DISJOINT value sets.

  What it CANNOT see, listed before the result so a null is not later explained away:
    * a supersession with no extractable value -- "I prefer tea" -> "I prefer coffee" carries its
      value in a common noun, which this does not tokenise as a value;
    * a supersession where both values appear in both turns (a turn that recaps the old value while
      stating the new one);
    * negation and hedging -- "I no longer run" supersedes without contradicting a number;
    * anything requiring the RELATION to be identified, which is the actual HP4 component.

The read is the same one R7 used: precision against the false-positive direction, over the same
pairs, so the two signals are directly comparable.

Fit split. Prints numbers. Applies nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from reach_harm_r5_classes import load_case_structure  # noqa: E402
from reach_head_r3_slate import load_pool  # noqa: E402

SPLIT_PATH = REPO / "tools" / "split.json"
CACHE = REPO / "runs" / "session-m0c" / "r7-turn-embeddings.npz"
OUT = REPO / "runs" / "session-m0c" / "reach-r8-valueconflict-{split}.json"

NUMERIC = re.compile(r"\b\d[\d,:./]*\b")
MONEY = re.compile(r"[$£€]\s?\d[\d,.]*")
CAPS = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b")
STOP = {"I", "The", "A", "An", "My", "It", "That", "This", "You", "We", "They", "He", "She"}


def value_tokens(text: str) -> set[str]:
    v = set(NUMERIC.findall(text)) | set(m.replace(" ", "") for m in MONEY.findall(text))
    v |= {w for w in CAPS.findall(text) if w not in STOP}
    return {t.strip(".,").lower() for t in v if t.strip(".,")}


def context_tokens(text: str) -> set[str]:
    t = re.sub(r"[^a-z ]+", " ", text.lower())
    return {w for w in t.split() if len(w) > 3}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / max(len(a | b), 1)


def conflict_score(t1: str, t2: str) -> tuple[float, float, float]:
    """(context overlap, value disjointness, product). A supersession candidate is high on both."""
    c = jaccard(context_tokens(t1), context_tokens(t2))
    v1, v2 = value_tokens(t1), value_tokens(t2)
    if not v1 or not v2:
        return c, 0.0, 0.0                    # no extractable value -> the rule abstains
    disj = 1.0 - jaccard(v1, v2)
    return c, disj, c * disj


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="fit", choices=["fit", "heldout"])
    args = ap.parse_args()

    from marlowe_eval.datasets import longmemeval

    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    corpus_path = REPO / split["corpus_path"]
    cases = load_case_structure(corpus_path)
    corpus = longmemeval.load(corpus_path)
    gold_map = corpus.gold_map()
    harness = {c.query_id: c for c in corpus.cases}

    raw = json.loads(corpus_path.read_text(encoding="utf-8"))
    texts: dict[str, str] = {}
    for inst in raw:
        for sid, sess in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            for i, t in enumerate(sess):
                texts[f"{sid}-{i}"] = str(t["content"])

    pool = load_pool(args.split, gold_map)
    ku = sorted(q for q in pool if q in harness and not harness[q].is_abstention
                and cases[q]["question_type"] == "knowledge-update"
                and cases[q]["current_session"] is not None)

    # the exact same pair population R7 measured, so the two signals are comparable
    if not CACHE.exists():
        raise SystemExit("REFUSING: run reach_supersession_r7_separability.py first -- this "
                         "compares against the SAME pair population and reuses its cache.")
    z = np.load(CACHE, allow_pickle=True)
    vecs = {t: v for t, v in zip(z["ids"], z["emb"])}

    true_pairs, distractor_pairs = [], []
    no_value_true = 0
    for q in ku:
        cur = cases[q]["current_session"]
        stale_sess = cases[q]["answer_sessions"] - {cur}
        pool_tids = [t for t in pool[q]["turn_id"].tolist() if t in texts and t in vecs]
        pool_set = set(pool_tids)
        stale_gold = [t for t in cases[q]["gold"]
                      if t.rsplit("-", 1)[0] in stale_sess and t in pool_set]
        cur_gold = [t for t in cases[q]["gold"] if t.rsplit("-", 1)[0] == cur]
        if not stale_gold or not cur_gold or len(pool_tids) < 10:
            continue
        s = stale_gold[0]
        best = max(cur_gold, key=lambda t: float(vecs[s] @ vecs[t]) if t in vecs else -1)
        c, d, p = conflict_score(texts[s], texts[best])
        if not value_tokens(texts[s]) or not value_tokens(texts[best]):
            no_value_true += 1
        true_pairs.append(p)
        for t in pool_tids:
            if t == s or t in set(cur_gold):
                continue
            distractor_pairs.append(conflict_score(texts[s], texts[t])[2])

    tp = np.asarray(true_pairs)
    dp = np.asarray(distractor_pairs)
    print(f"\nsplit={args.split}  true pairs {len(tp)}  distractor pairs {len(dp):,}")
    print(f"  true pairs where one side has NO extractable value (the rule abstains): "
          f"{no_value_true}/{len(tp)}")

    print()
    print("=" * 96)
    print("R8 -- VALUE-CONFLICT APPROXIMATION OF ENTITY-RELATION CONFLICT")
    print("=" * 96)
    print("  score = context Jaccard x value disjointness; 0 when either side has no value token")
    print(f"  true pairs      p25 {np.quantile(tp,0.25):.4f}  p50 {np.quantile(tp,0.5):.4f}  "
          f"p75 {np.quantile(tp,0.75):.4f}  max {tp.max():.4f}")
    print(f"  distractors     p50 {np.quantile(dp,0.5):.4f}  p99 {np.quantile(dp,0.99):.4f}  "
          f"p99.9 {np.quantile(dp,0.999):.4f}  max {dp.max():.4f}")

    print()
    print(f"{'threshold':>10} {'recall':>18} {'false positives':>17} {'precision':>10}")
    rows = []
    grid = [round(x, 3) for x in np.quantile(tp[tp > 0], [0.9, 0.75, 0.5, 0.25, 0.1])] \
        if (tp > 0).any() else []
    for th in sorted(set(grid + [0.30, 0.20, 0.15, 0.10, 0.05]), reverse=True):
        t_hit = int((tp >= th).sum())
        f_hit = int((dp >= th).sum())
        prec = t_hit / (t_hit + f_hit) if (t_hit + f_hit) else float("nan")
        print(f"{th:>10.3f} {t_hit:>4d}/{len(tp):<4d} ({t_hit/len(tp):>5.1%}) {f_hit:>17,d} "
              f"{prec:>10.4f}")
        rows.append({"threshold": th, "true_positives": t_hit,
                     "recall": round(t_hit / len(tp), 4), "false_positives": f_hit,
                     "precision": round(prec, 6) if t_hit + f_hit else None})

    usable = [r for r in rows if r["precision"] is not None and r["true_positives"] > 0]
    best = max(usable, key=lambda r: r["precision"]) if usable else None
    print()
    print("-" * 96)
    print("READING -- compared against R7's similarity signal on the SAME pairs")
    print("-" * 96)
    print(f"  R7 similarity, best precision anywhere : 0.0745 (recall 42.4%)")
    if best:
        print(f"  R8 value conflict, best precision      : {best['precision']:.4f} "
              f"(recall {best['recall']:.1%}) at threshold {best['threshold']}")
    else:
        print("  R8 value conflict: NO threshold catches any true pair.")

    out = Path(str(OUT).format(split=args.split))
    out.write_text(json.dumps({
        "_what": "value-conflict approximation of HP4's entity-relation contradiction detector",
        "_this_is_an_approximation_not_the_component": (
            "real entity and relation extraction does not exist in this workspace. This measures "
            "whether a crude 'same context, disjoint values' rule separates the pairs at all."),
        "_what_the_approximation_cannot_see": [
            "supersession whose value is a common noun (tea -> coffee)",
            "a turn that recaps the old value while stating the new one",
            "negation and hedging that supersede without contradicting a number",
            "anything needing the RELATION identified, which is the actual HP4 component",
        ],
        "split": args.split, "true_pairs": len(tp), "distractor_pairs": int(len(dp)),
        "true_pairs_with_no_extractable_value": no_value_true,
        "threshold_grid": rows, "best": best,
        "r7_similarity_best_precision": 0.0745,
    }, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
