"""H-G: within-turn sentence dispersion, measured WITHOUT the query. Parameter-free, tau = 0.

    python tools/turn_dispersion.py

## The hypothesis, stated mechanically

The unifying fact of this corpus is *gold turns are multi-topic with a narrow answer; distractors
are single-topic and coherent*. Every mechanism tried so far measured that indirectly -- SUPPORT
(context decay, neighbour similarity, centroid subtraction) or PEAKS (sentence MaxP, proposition
indexing). Nobody has measured **topic count directly**, and nobody has measured it **with the
query out of the loop**.

  * split each head-pair member into sentences (`sentence_maxp.sentences` -- the same splitter, not
    a second one);
  * embed each sentence with `models/jina-embeddings-v2-small-en` (`reach_embed.JinaEmbedder` --
    the product's own dense cue, not an LLM, and not a second embedding path);
  * feature = **mean pairwise cosine among the turn's own sentences** = internal coherence;
  * FLIP the head pair when rank 2 is LESS coherent than rank 1, i.e. when
    `coherence(rank1) - coherence(rank2) >= 0`. **tau = 0. No hyperparameter anywhere.**

There is no query in this statistic, no peak, no score profile, and nothing selected on fit. That is
the whole point: STATE.md names threshold selection at n=229 as what killed context decay
(+0.0305 fit -> -0.0087 held-out), which was itself never trained -- only its lambda was chosen from
ten cells. If the family is real, the parameter-free form is the honest test of it. If the family is
noise, this reads null and closes it more firmly than decay did.

A turn with fewer than 2 sentences has no pairwise mean and is UNDEFINED. An undefined pair is
NEVER flipped and is counted separately.

## Registered prediction, written before the run

  * **+3 to +8 net cases at tau = 0 on fit.**
  * **It fails the above-0.084 test** -- <= 0 net above the band, matching every predecessor.
  * It will correlate with turn length; `length / ln(words)` is already dead (0.554 vs 0.520,
    p=0.758), so the length control is reported: the flip table restricted to pairs whose sentence
    counts are within +/-1, and the correlation of the coherence gap with `ln_words_ratio`.

## Reuse, not re-implementation

`head_probe.build()` builds and GATES the 229-pair population (fit R@1 must be exactly 0.7555);
`head_probe.evaluate` / `score_feature` / `print_curve` are the flip harness with its sign-inverted
control. `head_probe.FEATURES` is mutated at runtime rather than edited in place. Nothing in
`tools/head_probe.py`, `tools/sentence_maxp.py` or `tools/reach_embed.py` is modified.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

import head_probe as HP  # noqa: E402
from sentence_maxp import sentences  # noqa: E402  -- the splitter, reused
from reach_embed import JinaEmbedder  # noqa: E402  -- the embedder loader, reused

OUT = REPO / "runs" / "session-m0c-m" / "turn-dispersion.json"
CONTROL_PATH = REPO / "runs" / "session-m0c-m" / "control.json"

# The band from the bar. Below it the two cross-encoder logits are effectively identical and blind
# swapping scores +5; a rule that only helps inside it is a coin flip with extra steps.
BAND = 0.084

POSITIVE, NEGATIVE, AMBIGUOUS = HP.POSITIVE, HP.NEGATIVE, HP.AMBIGUOUS


# -- the statistic ---------------------------------------------------------------------------------


class Coherence:
    """text -> mean pairwise cosine among its own sentence embeddings. None if < 2 sentences."""

    def __init__(self, embedder: JinaEmbedder):
        self.emb = embedder
        self._vec: dict[str, np.ndarray] = {}
        self._coh: dict[str, tuple[float | None, int]] = {}
        self.n_embedded = 0

    def _v(self, s: str) -> np.ndarray:
        v = self._vec.get(s)
        if v is None:
            v = self.emb.embed(s)
            self._vec[s] = v
            self.n_embedded += 1
        return v

    def of(self, text: str) -> tuple[float | None, int]:
        """Returns (mean pairwise cosine or None, n_sentences)."""
        key = text or ""
        hit = self._coh.get(key)
        if hit is not None:
            return hit
        ss = sentences(key)
        if len(ss) < 2:
            out = (None, len(ss))
        else:
            M = np.stack([self._v(s) for s in ss])  # already L2-normalised by the embedder
            G = M @ M.T
            iu = np.triu_indices(len(ss), k=1)
            out = (float(G[iu].mean()), len(ss))
        self._coh[key] = out
        return out


# -- the feature, registered into head_probe.FEATURES at runtime ------------------------------------

NAME = "internal_coherence_gap"
DESC = ("mean pairwise sentence cosine of rank1 minus that of rank2 "
        "(rank2 LESS coherent = more multi-topic = gold-shaped -> flip). No query, tau=0.")


def f_coherence_gap(p):
    c1, c2 = p["_coh_r1"], p["_coh_r2"]
    if c1 is None or c2 is None:
        return None
    return c1 - c2


# -- flip tables at a FIXED tau ---------------------------------------------------------------------


def flip_table(pairs, fn, tau: float, n_queries: int, subset=None) -> dict:
    """The primary read: flip when fn(pair) >= tau, on a fixed tau. No selection anywhere."""
    gained = lost = amb = flips = undefined = 0
    considered = 0
    for p in pairs:
        if subset is not None and not subset(p):
            continue
        considered += 1
        v = fn(p)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            undefined += 1
            continue
        if v >= tau:
            flips += 1
            gained += p["label"] == POSITIVE
            lost += p["label"] == NEGATIVE
            amb += p["label"] == AMBIGUOUS
    return {
        "tau": tau,
        "considered": considered,
        "n_undefined": undefined,
        "n_flipped": flips,
        "flips_gained": gained,
        "flips_lost": lost,
        "flips_ambiguous": amb,
        "net_cases": gained - lost,
        "net_r1_delta": round((gained - lost) / n_queries, 4),
    }


def show(title: str, t: dict) -> None:
    print(f"  {title:<44} gained {t['flips_gained']:>3}  lost {t['flips_lost']:>3}  "
          f"amb {t['flips_ambiguous']:>3}  net {t['net_cases']:>+4}  "
          f"dR@1 {t['net_r1_delta']:>+7.4f}   ({t['n_flipped']}/{t['considered']} flipped, "
          f"{t['n_undefined']} undefined)")


# -- the instrument's own POSITIVE CONTROL ----------------------------------------------------------
#
# A null from a broken statistic is not a null. Before reporting that internal coherence does not
# discriminate gold from distractor, show that it discriminates AT ALL: take a single-topic
# paragraph and interleave sentences from unrelated topics, changing nothing else. If coherence does
# not fall, the statistic is inert and every number below is a measurement of nothing.

SINGLE_TOPIC = (
    "I went for a long run this morning along the river. My pace was better than last week. "
    "I am training for a half marathon in October. My knees held up fine on the downhills. "
    "I think the new running shoes are helping a lot."
)
MIXED_TOPIC = (
    "I went for a long run this morning along the river. The quarterly tax filing deadline is "
    "next Tuesday. I am training for a half marathon in October. My landlord is raising the rent "
    "by two hundred dollars. I think the new running shoes are helping a lot."
)


def pearson(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def spearman(x, y):
    def rank(a):
        a = np.asarray(a, float)
        o = a.argsort()
        r = np.empty(len(a), float)
        r[o] = np.arange(len(a), dtype=float)
        return r
    if len(x) < 3:
        return None
    return pearson(rank(x), rank(y))


# -- main --------------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    print("=" * 96)
    print("H-G  WITHIN-TURN SENTENCE DISPERSION, MEASURED WITHOUT THE QUERY  (tau = 0, no knobs)")
    print("=" * 96)
    print("REGISTERED PREDICTION (written before this ran):")
    print("  +3 to +8 net cases at tau = 0 on fit; FAILS the above-0.084 test (<=0 net above band);")
    print("  correlates with turn length -- length control reported.")
    print()

    # -- the gate. head_probe.build() refuses unless fit R@1 == 0.7555 exactly --------------------
    _pools, pairs, r1 = HP.build()
    n = len(pairs)
    print(f"population: {n} head pairs  "
          f"POS {sum(p['label']==POSITIVE for p in pairs)}  "
          f"NEG {sum(p['label']==NEGATIVE for p in pairs)}  "
          f"AMB {sum(p['label']==AMBIGUOUS for p in pairs)}")

    # -- the statistic ----------------------------------------------------------------------------
    print("\nloading jina-embeddings-v2-small-en (reach_embed.JinaEmbedder, CPU)...")
    coh = Coherence(JinaEmbedder())

    # -- 0. the instrument's positive control -----------------------------------------------------
    print("\n" + "=" * 96)
    print("0. INSTRUMENT POSITIVE CONTROL -- does the statistic move when topics are mixed?")
    print("=" * 96)
    c_single, s_single = coh.of(SINGLE_TOPIC)
    c_mixed, s_mixed = coh.of(MIXED_TOPIC)
    print(f"  single-topic (running only)          coherence {c_single:.4f}  ({s_single} sentences)")
    print(f"  mixed-topic  (running + tax + rent)  coherence {c_mixed:.4f}  ({s_mixed} sentences)")
    print(f"  delta {c_mixed - c_single:+.4f}   -- must be clearly NEGATIVE or the statistic is "
          f"inert and nothing below is evidence.")
    instrument = {
        "single_topic": round(c_single, 4), "mixed_topic": round(c_mixed, 4),
        "delta": round(c_mixed - c_single, 4),
        "live": bool(c_mixed < c_single),
    }
    if not instrument["live"]:
        raise SystemExit("REFUSING. Interleaving unrelated sentences did not reduce internal "
                         "coherence. The statistic is inert; a null from it is not a null.")

    print("\ncomputing internal coherence over the 229 head pairs...")
    for i, p in enumerate(pairs, 1):
        c1, n1 = coh.of(p["rank1"]["text"])
        c2, n2 = coh.of(p["rank2"]["text"])
        p["_coh_r1"], p["_coh_r2"] = c1, c2
        p["_nsent_r1"], p["_nsent_r2"] = n1, n2
        if i % 60 == 0:
            print(f"  {i}/{n}  ({coh.n_embedded} sentence vectors so far)")

    n_short_r1 = sum(p["_nsent_r1"] < 2 for p in pairs)
    n_short_r2 = sum(p["_nsent_r2"] < 2 for p in pairs)
    n_undef = sum(p["_coh_r1"] is None or p["_coh_r2"] is None for p in pairs)
    allsent = [p["_nsent_r1"] for p in pairs] + [p["_nsent_r2"] for p in pairs]
    print(f"\nsentences/turn: mean {np.mean(allsent):.2f}  median {np.median(allsent):.0f}  "
          f"max {max(allsent)}")
    print(f"UNDEFINED (a member with < 2 sentences, never flipped): "
          f"{n_undef}/{n} pairs   (rank1 short {n_short_r1}, rank2 short {n_short_r2})")

    # -- 1. PRIMARY: tau = 0 -----------------------------------------------------------------------
    print("\n" + "=" * 96)
    print("1. PRIMARY -- tau = 0, parameter-free.  flip when coherence(rank1) >= coherence(rank2)")
    print("=" * 96)
    primary = flip_table(pairs, f_coherence_gap, 0.0, n)
    show("FORWARD  (rank2 less coherent -> flip)", primary)
    inv = flip_table(pairs, lambda p: (None if f_coherence_gap(p) is None
                                       else -f_coherence_gap(p)), 0.0, n)
    show("SIGN-INVERTED CONTROL at tau = 0", inv)

    # -- 2. the full curve, via the existing harness -------------------------------------------------
    HP.FEATURES[NAME] = (DESC, f_coherence_gap)
    res = HP.evaluate(pairs, NAME, f_coherence_gap, n)
    print("\n" + "=" * 96)
    print("2. THE CURVE (shown, never used as a result -- a fit-selected tau is a design signal)")
    print("=" * 96)
    print(f"   defined on {res['forward']['n_defined']}/{n} pairs "
          f"({res['forward']['n_undefined']} undefined)")
    HP.print_curve(NAME, res["forward"])
    b = res["forward"]["best"]
    ib = res["negative_control_sign_inverted"]["best"]
    m = res["negative_control_at_matched_budget"]
    print(f"   BEST (fit-selected)  net {b['net_cases']:+d} ({b['flips_gained']} gained, "
          f"{b['flips_lost']} lost) at tau {b['tau']:.4f}, {b['n_flipped']} flips, "
          f"dR@1 {b['net_r1_delta']:+.4f}")
    print(f"   CONTROL sign-inverted BEST  net {ib['net_cases']:+d} at {ib['n_flipped']} flips")
    print(f"   CONTROL at MATCHED {b['n_flipped']}-flip budget  net {m['net_cases']:+d} "
          f"({m['flips_gained']} gained, {m['flips_lost']} lost)")
    print(f"   separation from control  {b['net_cases'] - ib['net_cases']:+d}")

    # -- 3. THE DECISIVE TEST: above / below the 0.084 band -------------------------------------------
    print("\n" + "=" * 96)
    print(f"3. THE DECISIVE TEST -- does it fire correctly where the rerank gap is ABOVE {BAND}?")
    print("=" * 96)
    gaps = [p["rerank_gap"] for p in pairs]
    n_nogap = sum(g is None for g in gaps)

    def above(p):
        g = p["rerank_gap"]
        return g is not None and abs(g) > BAND

    def below(p):
        g = p["rerank_gap"]
        return g is not None and abs(g) <= BAND

    n_above = sum(above(p) for p in pairs)
    n_below = sum(below(p) for p in pairs)
    lab_above = {L: sum(above(p) and p["label"] == L for p in pairs)
                 for L in (POSITIVE, NEGATIVE, AMBIGUOUS)}
    lab_below = {L: sum(below(p) and p["label"] == L for p in pairs)
                 for L in (POSITIVE, NEGATIVE, AMBIGUOUS)}
    print(f"  pairs with a rerank gap: {n - n_nogap}   (no gap on {n_nogap})")
    print(f"  ABOVE band |gap| > {BAND}: {n_above:3d}  POS {lab_above[POSITIVE]:3d} "
          f"NEG {lab_above[NEGATIVE]:3d} AMB {lab_above[AMBIGUOUS]:3d}")
    print(f"  BELOW band |gap| <= {BAND}: {n_below:3d}  POS {lab_below[POSITIVE]:3d} "
          f"NEG {lab_below[NEGATIVE]:3d} AMB {lab_below[AMBIGUOUS]:3d}")
    print()
    t_above = flip_table(pairs, f_coherence_gap, 0.0, n, subset=above)
    t_below = flip_table(pairs, f_coherence_gap, 0.0, n, subset=below)
    show(f"tau=0, ABOVE band (|gap| > {BAND})", t_above)
    show(f"tau=0, BELOW band (|gap| <= {BAND})", t_below)
    ia = flip_table(pairs, lambda p: (None if f_coherence_gap(p) is None
                                      else -f_coherence_gap(p)), 0.0, n, subset=above)
    show("  sign-inverted, ABOVE band", ia)
    print("  blind-swap reference BELOW band: net "
          f"{lab_below[POSITIVE] - lab_below[NEGATIVE]:+d} "
          f"({lab_below[POSITIVE]} gained, {lab_below[NEGATIVE]} lost)")

    # -- 4. THE LENGTH CONTROL --------------------------------------------------------------------
    print("\n" + "=" * 96)
    print("4. LENGTH CONTROL -- is this just length again? (length / ln(words) is already dead)")
    print("=" * 96)

    def matched_len(p):
        return abs(p["_nsent_r1"] - p["_nsent_r2"]) <= 1

    t_len = flip_table(pairs, f_coherence_gap, 0.0, n, subset=matched_len)
    show("tau=0, sentence counts within +/-1", t_len)
    t_len_inv = flip_table(pairs, lambda p: (None if f_coherence_gap(p) is None
                                             else -f_coherence_gap(p)), 0.0, n, subset=matched_len)
    show("  sign-inverted, same subset", t_len_inv)
    t_len_ab = flip_table(pairs, f_coherence_gap, 0.0, n,
                          subset=lambda p: matched_len(p) and above(p))
    show(f"tau=0, matched length AND |gap| > {BAND}", t_len_ab)

    defined = [p for p in pairs if f_coherence_gap(p) is not None]
    gapv = [f_coherence_gap(p) for p in defined]
    lnw = [p["ln_words_ratio"] for p in defined]
    dsent = [p["_nsent_r1"] - p["_nsent_r2"] for p in defined]
    r_lnw, rho_lnw = pearson(gapv, lnw), spearman(gapv, lnw)
    r_ds, rho_ds = pearson(gapv, dsent), spearman(gapv, dsent)
    print(f"\n  corr(coherence gap, ln_words_ratio)      pearson {r_lnw:+.4f}   "
          f"spearman {rho_lnw:+.4f}   (n={len(defined)})")
    print(f"  corr(coherence gap, sentence-count diff) pearson {r_ds:+.4f}   "
          f"spearman {rho_ds:+.4f}")
    # within-turn: does coherence itself just track length?
    cvals = [c for p in pairs for c in (p["_coh_r1"], p["_coh_r2"]) if c is not None]
    svals = [s for p in pairs for c, s in ((p["_coh_r1"], p["_nsent_r1"]),
                                           (p["_coh_r2"], p["_nsent_r2"])) if c is not None]
    print(f"  corr(coherence, n_sentences) over turns  pearson {pearson(cvals, svals):+.4f}   "
          f"spearman {spearman(cvals, svals):+.4f}   (n={len(cvals)} turns)")

    # -- 5. THE control.json READ ------------------------------------------------------------------
    print("\n" + "=" * 96)
    print("5. control.json -- gold vs the beating distractor, on FAILURES *and* on the 173 SOLVED")
    print("=" * 96)
    ctrl = json.loads(io.open(CONTROL_PATH, encoding="utf-8").read())
    recs = ctrl["records"]
    assert ctrl["summary"]["correct"] == 173 and ctrl["summary"]["failures"] == 56, ctrl["summary"]
    print(f"  control.json: {len(recs)} records, {ctrl['summary']['correct']} correct, "
          f"{ctrl['summary']['failures']} failures  (contrast: {ctrl['_contrast']})")

    pops = {"FAILURES (56): competitor = the rank-1 winner": [],
            "SOLVED (173): competitor = the rank-2 runner-up": []}
    for r in recs:
        key = ("FAILURES (56): competitor = the rank-1 winner" if r["outcome"] != "correct"
               else "SOLVED (173): competitor = the rank-2 runner-up")
        cg, sg = coh.of(r["gold"]["text"])
        cc, sc = coh.of(r["competitor"]["text"])
        pops[key].append((cg, cc, sg, sc))

    ctrl_out = {}
    print(f"\n  {'population':<48} {'n_def':>6} {'gold':>8} {'compet':>8} {'gold-comp':>10} "
          f"{'gold LESS coh':>14}")
    for key, rows in pops.items():
        d = [(a, b) for a, b, _, _ in rows if a is not None and b is not None]
        g = np.array([a for a, _ in d])
        c = np.array([b for _, b in d])
        frac = float(np.mean(g < c)) if len(d) else float("nan")
        print(f"  {key:<48} {len(d):>6} {g.mean():>8.4f} {c.mean():>8.4f} "
              f"{(g - c).mean():>+10.4f} {frac:>13.1%}")
        ctrl_out[key] = {
            "n_records": len(rows),
            "n_both_defined": len(d),
            "mean_gold_coherence": round(float(g.mean()), 4),
            "mean_competitor_coherence": round(float(c.mean()), 4),
            "mean_gap_gold_minus_competitor": round(float((g - c).mean()), 4),
            "fraction_gold_less_coherent": round(frac, 4),
        }
    print("\n  READ: if gold is less coherent in BOTH populations it is a CORPUS property, not a")
    print("  failure property -- exactly what killed 9 of 10 predecessors.")

    # -- 6. the two canonical cases from the brief -------------------------------------------------
    print("\n" + "=" * 96)
    print("6. THE TWO CANONICAL CASES the unifying fact is stated from")
    print("=" * 96)
    by_qid = {r["query_id"]: r for r in recs}
    canonical = {}
    for qid in ("9a707b82", "505af2f5"):
        r = by_qid.get(qid)
        if r is None:
            print(f"  {qid}: not in control.json")
            continue
        print(f"  {qid}  ({r['outcome']}, {r['category']})")
        entry = {}
        for role in ("gold", "competitor"):
            c, s = coh.of(r[role]["text"])
            entry[role] = {"coherence": c, "n_sentences": s, "words": r[role]["words"]}
            print(f"    {role:<11} coherence {('UNDEFINED' if c is None else f'{c:.4f}'):>9}  "
                  f"({s} sentences, {r[role]['words']} words)")
        canonical[qid] = entry

    # -- verdict ------------------------------------------------------------------------------------
    print("\n" + "=" * 96)
    print("VERDICT vs THE REGISTERED PREDICTION")
    print("=" * 96)
    print(f"  predicted +3..+8 net at tau=0    MEASURED net {primary['net_cases']:+d} "
          f"(dR@1 {primary['net_r1_delta']:+.4f})")
    print(f"  predicted <=0 net above the band MEASURED net {t_above['net_cases']:+d} above "
          f"|gap| > {BAND}")

    artifact = {
        "_what": "H-G: within-turn sentence dispersion (mean pairwise cosine among a turn's own "
                 "sentences), measured WITHOUT the query. Parameter-free, tau = 0.",
        "_split": "fit",
        "_measurement_only": True,
        "_registered_prediction": {
            "primary_net_cases_at_tau_0": "+3 to +8",
            "above_band": "<= 0 net (expected to fail the decisive test)",
            "length": "expected to correlate with turn length; length control reported",
        },
        "gate": {"published_fit_r1": HP.CONTROL_R1, "reconstructed_fit_r1": r1, "pairs": n},
        "instrument_positive_control": instrument,
        "mechanism": {
            "splitter": "tools/sentence_maxp.py::sentences (reused, unmodified)",
            "embedder": "tools/reach_embed.py::JinaEmbedder -> models/jina-embeddings-v2-small-en",
            "statistic": "mean pairwise cosine among a turn's own sentence embeddings",
            "feature": DESC,
            "tau": 0.0,
            "hyperparameters": "none",
            "llm_used": False,
        },
        "sentences": {
            "mean_per_turn": round(float(np.mean(allsent)), 3),
            "median_per_turn": float(np.median(allsent)),
            "undefined_pairs": n_undef,
            "rank1_under_2_sentences": n_short_r1,
            "rank2_under_2_sentences": n_short_r2,
            "sentence_vectors_embedded": coh.n_embedded,
        },
        "primary_tau_0": primary,
        "primary_tau_0_sign_inverted": inv,
        "curve_and_controls": res,
        "band": {
            "threshold": BAND,
            "n_above": n_above, "n_below": n_below, "n_without_gap": n_nogap,
            "labels_above": lab_above, "labels_below": lab_below,
            "tau_0_above": t_above, "tau_0_below": t_below,
            "tau_0_above_sign_inverted": ia,
            "blind_swap_below_band_net": lab_below[POSITIVE] - lab_below[NEGATIVE],
        },
        "length_control": {
            "tau_0_sentence_counts_within_1": t_len,
            "tau_0_sentence_counts_within_1_sign_inverted": t_len_inv,
            "tau_0_matched_length_and_above_band": t_len_ab,
            "corr_gap_vs_ln_words_ratio": {"pearson": r_lnw, "spearman": rho_lnw},
            "corr_gap_vs_sentence_count_diff": {"pearson": r_ds, "spearman": rho_ds},
            "corr_coherence_vs_n_sentences_over_turns": {
                "pearson": pearson(cvals, svals), "spearman": spearman(cvals, svals),
                "n_turns": len(cvals),
            },
        },
        "control_json_read": ctrl_out,
        "canonical_cases": canonical,
        "per_pair": [
            {
                "query_id": p["query_id"], "label": p["label"], "category": p["category"],
                "coh_r1": p["_coh_r1"], "coh_r2": p["_coh_r2"],
                "nsent_r1": p["_nsent_r1"], "nsent_r2": p["_nsent_r2"],
                "coherence_gap": f_coherence_gap(p),
                "rerank_gap": p["rerank_gap"], "ln_words_ratio": p["ln_words_ratio"],
            }
            for p in pairs
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
