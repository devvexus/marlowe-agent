"""Session G, arms 2 and 3 — query expansion (PRF + entity discovery) and hypothetical-answer
embedding. Both behind the reproduction gates in `reach_embed.py` and `reach_lexical.py`.

Both arms change the QUERY, so both are exempt from the either-cue oracle cap (ADR-010 reach
check, registered). Document vectors are Rust's own, read from its embedding cache; only the
query side is computed here.

---

## Arm 3 has no LLM, and the substitute is better for a reachability check

HyDE normally generates a hypothetical answer with a model. Session G has no credentials, so the
generator is unavailable. Rather than skip the arm, the **ceiling** is measured directly:

> **Oracle-HyDE — embed the RELEASED GOLD ANSWER as the query.**

If embedding the *true* answer does not beat embedding the question, then no generated
approximation of that answer can, because the generator's best case is to reproduce it. That makes
this an upper bound on the whole technique, obtainable without a model, and a *stronger*
reachability statement than any single generator's output would be.

**It uses gold labels and is therefore NOT a shippable number.** It is an upper bound and is
labelled as one everywhere it appears. Quoting it as achievable performance would be reporting
label leakage as a result.

A realistic no-LLM variant (rule-based declarative rewrite) is reported beside it.

---

## Unregistered degrees of freedom, disclosed

As with arm 1's aggregation rule, the pre-registration fixed the arms but not their
hyperparameters. Handled the same way: **declared before running, all reported, best not
quotable.**

Arm 2 PRIMARY: feedback from top-5 first-pass docs, 10 expansion terms, appended once.
Arm 2 SENSITIVITY: top-3 docs, 5 terms, appended twice.
Arm 3 variants: oracle answer; oracle question+answer; template rewrite.

**Morphological expansion is not implemented**, per the standing instruction -- it was tested and
rejected in the source work because noisy candidates cascade.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import numpy as np

from reach_embed import JinaEmbedder, RustEmbeddingCache
from reach_lexical import saturate, score_all, tokenize
from reach_pools import REPO, gold_answers, hit, load_pools, order_of, turn_texts

OUT_PATH = REPO / "runs" / "session-g" / "arm23-query.json"

# Small, explicit, and not swept. A tuned stop list is a quality knob; this one exists only to
# stop PRF from "discovering" function words, and every term in it is closed-class.
STOP = set(
    """a an the and or but if then than that this these those i you he she it we they me him her
    us them my your his its our their mine yours am is are was were be been being do does did done
    have has had having will would shall should can could may might must of in on at to for with
    from by as about into over after before between out up down off again further once here there
    all any both each few more most other some such no nor not only own same so too very s t just
    dont should now what which who whom when where why how""".split()
)

_CAP_SPAN = re.compile(r"\b([A-Z][a-zA-Z0-9&'.-]*(?:\s+[A-Z][a-zA-Z0-9&'.-]*)*)\b")


def entity_terms(texts: list[str]) -> list[str]:
    """Capitalized multi-token spans: a cheap stand-in for person/org/location/event NER.

    No NER model is available offline, and adding one would be a third scored-path dependency with
    no gate behind it. Capitalization is a weak proxy and is named as one -- it over-fires on
    sentence-initial words, which is why single-token spans at a sentence start are dropped.
    """
    found: Counter[str] = Counter()
    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            for m in _CAP_SPAN.finditer(sentence):
                span = m.group(1)
                if m.start() == 0 and " " not in span:
                    continue
                for tok in tokenize(span):
                    if tok not in STOP and len(tok) > 2:
                        found[tok] += 1
    return [t for t, _ in found.most_common()]


def prf_terms(texts: list[str], exclude: set[str]) -> list[str]:
    counts = Counter()
    for text in texts:
        for tok in tokenize(text):
            if tok not in STOP and tok not in exclude and len(tok) > 2:
                counts[tok] += 1
    return [t for t, _ in counts.most_common()]


def template_hyde(question: str) -> str:
    """A declarative rewrite of the question. No model, no gold labels.

    Deliberately crude. Its job is to show what the shippable, model-free end of arm 3 looks like
    beside the oracle ceiling, not to be a good generator.
    """
    q = question.strip().rstrip("?").strip()
    q = re.sub(r"^(what|which|who|whom|whose|when|where|why|how many|how much|how long|how)\s+", "", q, flags=re.I)
    q = re.sub(r"\bdid\s+i\b", "I", q, flags=re.I)
    q = re.sub(r"\bdo\s+i\b", "I", q, flags=re.I)
    q = re.sub(r"\bhave\s+i\b", "I have", q, flags=re.I)
    q = re.sub(r"\bam\s+i\b", "I am", q, flags=re.I)
    q = re.sub(r"\bis\s+my\b", "my", q, flags=re.I)
    q = re.sub(r"\bare\s+my\b", "my", q, flags=re.I)
    q = re.sub(r"\bwas\s+i\b", "I was", q, flags=re.I)
    return f"I {q}." if not q.lower().startswith("i ") else f"{q}."


def _rates(lex: np.ndarray, den: np.ndarray, gold: np.ndarray, ks=(1, 5, 10)) -> dict:
    lo, do = order_of(lex), order_of(den)
    out = {}
    for k in ks:
        L, D = hit(lo, gold, k), hit(do, gold, k)
        out[f"lexical@{k}"], out[f"dense@{k}"], out[f"oracle@{k}"] = L, D, L or D
    return out


def main() -> int:
    pools, _ = load_pools()
    texts = turn_texts()
    answers = gold_answers()
    cache = RustEmbeddingCache()
    embedder = JinaEmbedder()

    qids = sorted(pools)
    print(f"Arms 2 and 3 over {len(qids)} held-out pools. Tokenizing documents once...")

    doc_terms: dict[str, list[list[str]]] = {}
    doc_vecs: dict[str, np.ndarray] = {}
    missing_vecs = 0
    for qid in qids:
        pool = pools[qid]
        tt = texts[qid]
        doc_terms[qid] = [tokenize(tt.get(c.turn_id, "")) for c in pool.candidates]
        vecs = []
        for c in pool.candidates:
            v = cache.get(tt.get(c.turn_id, ""))
            if v is None:
                missing_vecs += 1
                v = np.zeros(512, dtype=np.float32)
            vecs.append(v)
        doc_vecs[qid] = np.stack(vecs)

    # A third fidelity check, free from the setup: Rust's cached query vector against Rust's
    # cached document vectors must reproduce the stored dense_cosine column. If this disagrees,
    # the document-vector lookup is wrong and every dense number below is meaningless.
    worst = 0.0
    for qid in qids[:40]:
        qv = cache.get(pools[qid].question)
        recomputed = doc_vecs[qid] @ qv
        worst = max(worst, float(np.abs(recomputed - pools[qid].array("dense_cosine")).max()))
    print(f"  document-vector lookup check: max |recomputed - stored dense_cosine| = {worst:.3e}")
    if missing_vecs:
        print(f"  WARNING: {missing_vecs} document vectors missing from cache")
    if worst > 1e-4:
        print("  FAILED -- document vectors do not reproduce the stored column. Arms NOT MEASURED.")
        return 1

    variants: dict[str, dict[str, bool]] = {}
    tallies: dict[str, Counter] = {}

    def record(name: str, qid: str, r: dict) -> None:
        variants.setdefault(name, {})[qid] = bool(r["oracle@1"])
        tallies.setdefault(name, Counter()).update({k: int(v) for k, v in r.items()})

    for qid in qids:
        pool = pools[qid]
        gold = pool.gold
        base_lex = pool.array("lexical_bm25")
        base_den = pool.array("dense_cosine")
        record("baseline", qid, _rates(base_lex, base_den, gold))

        # ---- arm 2: PRF + entity discovery ------------------------------------------------
        qterms = set(tokenize(pool.question))
        for label, k_docs, n_terms, weight in (
            ("arm2_primary_k5_m10_w1", 5, 10, 1),
            ("arm2_sensitivity_k3_m5_w2", 3, 5, 2),
        ):
            expansions = {}
            for cue, base in (("lexical", base_lex), ("dense", base_den)):
                top = order_of(base)[:k_docs]
                fb = [texts[qid].get(pool.candidates[i].turn_id, "") for i in top]
                terms = (entity_terms(fb) + prf_terms(fb, qterms))[:n_terms]
                expansions[cue] = pool.question + (" " + " ".join(terms)) * weight
            lex = saturate(score_all(doc_terms[qid], expansions["lexical"]))
            den = doc_vecs[qid] @ embedder.embed(expansions["dense"])
            record(label, qid, _rates(lex, den, gold))

        # ---- arm 3: hypothetical answer embedding -----------------------------------------
        answer = answers.get(qid) or ""
        for label, text in (
            ("arm3_ORACLE_answer_UPPER_BOUND", answer),
            ("arm3_ORACLE_question_plus_answer_UPPER_BOUND", f"{pool.question} {answer}".strip()),
            ("arm3_template_rewrite_no_LLM", template_hyde(pool.question)),
        ):
            if not text:
                record(label, qid, _rates(base_lex, base_den, gold))
                continue
            lex = saturate(score_all(doc_terms[qid], text))
            den = doc_vecs[qid] @ embedder.embed(text)
            record(label, qid, _rates(lex, den, gold))

    n = len(qids)
    rates = {name: {k: round(v / n, 4) for k, v in sorted(t.items())} for name, t in tallies.items()}

    def mcnemar(a: dict[str, bool], b: dict[str, bool]) -> tuple[int, int, float]:
        """Exact two-sided McNemar on discordant pairs. b is the baseline."""
        from scipy.stats import binomtest

        b_only = sum(1 for q in a if b[q] and not a[q])
        a_only = sum(1 for q in a if a[q] and not b[q])
        if a_only + b_only == 0:
            return a_only, b_only, 1.0
        return a_only, b_only, float(binomtest(a_only, a_only + b_only, 0.5).pvalue)

    base = variants["baseline"]
    verdicts = {}
    for name, v in variants.items():
        if name == "baseline":
            continue
        gained, lost, p = mcnemar(v, base)
        delta = rates[name]["oracle@1"] - rates["baseline"]["oracle@1"]
        if delta >= 0.05 and p < 0.05:
            verdict = "PROMOTE"
        elif delta >= 0.02:
            verdict = "INCONCLUSIVE"
        elif delta > -0.02:
            verdict = "NOT REACHED"
        else:
            verdict = "HARMFUL"
        verdicts[name] = {
            "oracle_at_1": rates[name]["oracle@1"],
            "delta": round(delta, 4),
            "cases_gained": gained,
            "cases_lost": lost,
            "mcnemar_p": round(p, 6),
            "verdict": verdict,
            "_upper_bound_not_shippable": "ORACLE" in name,
        }

    report = {
        "_what": "Session G arms 2 and 3 -- query-side transforms, held-out pools.",
        "_gates_passed": ["python query embedder vs Rust cached vectors", "python BM25 vs stored column",
                          "document-vector lookup vs stored dense_cosine"],
        "document_vector_check_max_abs": worst,
        "rates": rates,
        "verdicts": verdicts,
        "_per_case_oracle_at_1": variants,
        "_oracle_variants_use_gold_labels": (
            "arm3_ORACLE_* embed the released gold answer. They are UPPER BOUNDS on the technique "
            "and are not achievable numbers. If they do not beat the baseline, no generator can."
        ),
    }
    OUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\nBaseline oracle@1 {rates['baseline']['oracle@1']:.4f}\n")
    print(f"  {'variant':46s} {'oracle@1':>8} {'delta':>8} {'+':>4} {'-':>4} {'p':>8}  verdict")
    for name, v in verdicts.items():
        print(f"  {name:46s} {v['oracle_at_1']:>8.4f} {v['delta']:>+8.4f} "
              f"{v['cases_gained']:>4} {v['cases_lost']:>4} {v['mcnemar_p']:>8.4f}  {v['verdict']}")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
