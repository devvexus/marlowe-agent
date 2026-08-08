"""R6 -- the ceiling on supersession detection, measured before anything is built.

Given a PERFECT oracle that marks every stale knowledge-update belief as superseded, what does
Sec 4.3's exclusion buy? That number bounds this entire line of work. Sessions F, G and the harm
session each turned a session-long question into an afternoon by asking it first.

**The simulation is of the candidate set, not of the slate.** Supersession removes an entry from
`injection_candidates` (entry.rs:124), which happens BEFORE pruning and before the depth-10 slate
is built -- so a surviving candidate is promoted into the freed slot and must be scored. Removing
rows from the cached slate instead would silently under-count, because the promoted eleventh
candidate can out-score everything left. Both are computed and printed side by side so the
difference is visible rather than assumed.

**Two oracles, because they claim different things.**

  narrow  only the GOLD-marked turns of the superseded session are excluded. This is what a
          contradiction detector operating on beliefs would actually do: supersede the belief that
          asserts the old value. This is the headline.
  broad   every turn of the superseded session is excluded. An upper bound that no realisable
          detector reaches, printed so the narrow number is not mistaken for the maximum.

The stale session is identified by `reach_harm_r5_classes.load_case_structure`, which reads which
turn's TEXT states the answer. Not `haystack_dates` -- those agree with the `_N` suffix on 166 of
250 cases on a corpus that dates 76 of 500 questions after their own content.

Fit split is the selection read. Prints numbers, applies nothing, writes one artifact.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import torch
from scipy.stats import beta

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "eval" / "src"))

from reach_harm_r5_classes import HARMFUL, classify, load_case_structure  # noqa: E402
from reach_head_r3_slate import load_pool  # noqa: E402

MODEL_DIR = REPO / "models" / "ms-marco-MiniLM-L-2-v2-ft-session-j"
SPLIT_PATH = REPO / "tools" / "split.json"
OUT = REPO / "runs" / "session-m0c" / "reach-r6-supersession-ceiling-{split}.json"
MAX_LEN = 256
DEPTH = 10
OPERATING_COVERAGE = 0.10

ALPHA = 0.05
MIN_DISCORDANT_MCNEMAR = 6      # 2/2^n <= 0.05
MIN_DISCORDANT_REPORTABLE = 10  # ADR-013's numeric form

# controls, from HARM-WEIGHTED-PRECISION.md -- the tool refuses to write if it cannot reproduce them
CONTROL = {
    "fit":     {"r_at_1_published": 0.7555, "r_at_1_current": 0.6900, "ku_current": 0.3056},
    "heldout": {"r_at_1_published": 0.6725, "r_at_1_current": 0.6288, "ku_current": 0.4444},
}


def clopper_pearson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    a = 1.0 - conf
    lo = 0.0 if k == 0 else float(beta.ppf(a / 2.0, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1.0 - a / 2.0, k + 1, n - k))
    return (lo, hi)


def mcnemar_exact(b: int, c: int) -> float:
    m = b + c
    if m == 0:
        return float("nan")
    k = min(b, c)
    return min(1.0, 2.0 * sum(math.comb(m, i) for i in range(k + 1)) / 2.0 ** m)


def gate_order(p) -> np.ndarray:
    return np.lexsort((-p["margin"], -p["score"], ~p["survived"]))


def stale_turn_ids(case: dict, mode: str, all_turns_in: dict[str, list[str]]) -> set[str]:
    """Turn ids a perfect oracle would mark superseded, for this case."""
    cur = case["current_session"]
    if cur is None:
        return set()
    stale_sessions = case["answer_sessions"] - {cur}
    if mode == "narrow":
        return {t for t in case["gold"] if t.rsplit("-", 1)[0] in stale_sessions}
    return {t for s in stale_sessions for t in all_turns_in.get(s, [])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="fit", choices=["fit", "heldout"])
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    if args.split == "heldout":
        print("*" * 96)
        print("* HELD-OUT. This is the single final read. Every threshold must already be derived.")
        print("*" * 96)

    from marlowe_eval.datasets import longmemeval
    from tokenizers import Tokenizer
    from transformers import AutoModelForSequenceClassification

    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    corpus_path = REPO / split["corpus_path"]
    cases = load_case_structure(corpus_path)
    corpus = longmemeval.load(corpus_path)
    gold_map = corpus.gold_map()
    harness_cases = {c.query_id: c for c in corpus.cases}
    questions = {c.query_id: c.question for c in corpus.cases}

    # every turn id per session, for the broad oracle, and every turn's text
    raw = json.loads(corpus_path.read_text(encoding="utf-8"))
    turns_in: dict[str, list[str]] = {}
    texts: dict[str, str] = {}
    for inst in raw:
        for sid, sess in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            ids = [f"{sid}-{i}" for i in range(len(sess))]
            turns_in[sid] = ids
            for tid, t in zip(ids, sess):
                texts[tid] = str(t["content"])

    pool = load_pool(args.split, gold_map)
    eligible = sorted(q for q in pool if q in harness_cases
                      and not harness_cases[q].is_abstention and pool[q]["gold"].any())
    n = len(eligible)
    print(f"\nsplit={args.split}  eligible={n}  device={args.device}")

    # ---- build the three candidate sets: shipped, narrow-oracle, broad-oracle ---------------
    arms = {"shipped": None, "oracle_narrow": "narrow", "oracle_broad": "broad"}
    slates: dict[str, dict[str, np.ndarray]] = {}
    removed_counts: dict[str, int] = {}
    for arm, mode in arms.items():
        sl, removed = {}, 0
        for q in eligible:
            p = pool[q]
            keep = np.ones(len(p["turn_id"]), dtype=bool)
            if mode is not None:
                stale = stale_turn_ids(cases[q], mode, turns_in)
                if stale:
                    keep = ~np.isin(p["turn_id"], list(stale))
                    removed += int((~keep).sum())
            # gate order over the SURVIVING candidate set, then depth 10 -- this is
            # injection_candidates -> pruning -> slate, in that order
            order = [i for i in gate_order(p) if keep[i]]
            sl[q] = np.asarray(order[:DEPTH], dtype=int)
        slates[arm] = sl
        removed_counts[arm] = removed
        print(f"  {arm:<14} candidates removed from the pool: {removed}")

    # ---- score every (query, candidate) pair once -------------------------------------------
    tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tok.enable_truncation(max_length=MAX_LEN)
    tok.enable_padding(length=MAX_LEN)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_DIR / "pytorch-reference", dtype=torch.float32).to(args.device).eval()

    need = sorted({(q, t) for arm in arms for q in eligible
                   for t in pool[q]["turn_id"][slates[arm][q]].tolist()})
    print(f"  scoring {len(need)} distinct (query, candidate) pairs ...")
    cache: dict[tuple[str, str], float] = {}
    with torch.no_grad():
        for i in range(0, len(need), args.batch):
            ch = need[i:i + args.batch]
            enc = tok.encode_batch([(questions[q], texts[t]) for q, t in ch])
            out = model(
                input_ids=torch.tensor([e.ids for e in enc], device=args.device),
                attention_mask=torch.tensor([e.attention_mask for e in enc], device=args.device),
                token_type_ids=torch.tensor([e.type_ids for e in enc], device=args.device),
            ).logits.reshape(-1).float().cpu().numpy()
            for (q, t), s in zip(ch, out):
                cache[(q, t)] = float(s)

    # ---- evaluate each arm -------------------------------------------------------------------
    ku = np.array([cases[q]["question_type"] == "knowledge-update" for q in eligible])
    results = {}
    for arm in arms:
        top1, margins = [], []
        for q in eligible:
            idx = slates[arm][q]
            tids = pool[q]["turn_id"][idx]
            s = np.asarray([cache[(q, t)] for t in tids])
            o = np.argsort(-s, kind="stable")
            top1.append(tids[o[0]])
            margins.append(float(s[o[0]] - s[o[1]]) if len(s) > 1 else float("inf"))
        cls = np.array([classify(t, cases[q]) for t, q in zip(top1, eligible)])
        published = np.isin(cls, ["current", "superseded"])
        current = cls == "current"
        harmful = np.isin(cls, list(HARMFUL))
        results[arm] = {"top1": np.array(top1), "cls": cls, "margin": np.asarray(margins),
                        "published": published, "current": current, "harmful": harmful}

    # control: the shipped arm must reproduce the published figures
    sh = results["shipped"]
    c = CONTROL[args.split]
    got = (round(float(sh["published"].mean()), 4), round(float(sh["current"].mean()), 4),
           round(float(sh["current"][ku].mean()), 4))
    want = (c["r_at_1_published"], c["r_at_1_current"], c["ku_current"])
    print(f"\n  CONTROL: published {got[0]} vs {want[0]} | current {got[1]} vs {want[1]} | "
          f"KU current {got[2]} vs {want[2]}")
    if got != want:
        raise SystemExit("REFUSING: the shipped arm does not reproduce HARM-WEIGHTED-PRECISION.md. "
                         "No ceiling measured against it means anything.")
    print("           PASS")

    # ---- the ceiling table --------------------------------------------------------------------
    print()
    print("=" * 100)
    print(f"R6 -- THE SUPERSESSION CEILING, {args.split} split, n={n} "
          f"(knowledge-update n={int(ku.sum())})")
    print("=" * 100)
    print(f"{'arm':<16} {'R@1 pub':>9} {'R@1 CURRENT':>12} {'KU current':>11} "
          f"{'harm rate':>10} {'top-1 changed':>14}")
    print("-" * 100)
    rows = {}
    for arm in arms:
        r = results[arm]
        changed = int((r["top1"] != sh["top1"]).sum())
        print(f"{arm:<16} {r['published'].mean():>9.4f} {r['current'].mean():>12.4f} "
              f"{r['current'][ku].mean():>11.4f} {r['harmful'].mean():>10.4f} {changed:>14d}")
        rows[arm] = {
            "r_at_1_published": round(float(r["published"].mean()), 4),
            "r_at_1_current": round(float(r["current"].mean()), 4),
            "ku_r_at_1_current": round(float(r["current"][ku].mean()), 4),
            "ku_n": int(ku.sum()),
            "harm_rate": round(float(r["harmful"].mean()), 4),
            "harmful_count": int(r["harmful"].sum()),
            "top1_changed_vs_shipped": changed,
            "candidates_removed": removed_counts[arm],
        }

    # ---- harm and precision at the declared operating point -----------------------------------
    print()
    print("-" * 100)
    print(f"AT THE DECLARED OPERATING POINT ({OPERATING_COVERAGE:.0%} coverage, by each arm's own "
          f"margin)")
    print("-" * 100)
    k = max(1, round(OPERATING_COVERAGE * n))
    for arm in arms:
        r = results[arm]
        cut = float(np.sort(r["margin"])[::-1][k - 1])
        sel = r["margin"] >= cut
        m = int(sel.sum())
        kc, kh = int(r["current"][sel].sum()), int(r["harmful"][sel].sum())
        clo, chi = clopper_pearson(kc, m)
        hlo, hhi = clopper_pearson(kh, m)
        ku_share = float(ku[sel].mean())
        print(f"  {arm:<16} n_c={m:<4d} precision_current {kc/m:.4f} [{clo:.4f},{chi:.4f}]  "
              f"harm {kh}/{m} [{hlo:.4f},{hhi:.4f}]  KU share {ku_share:.1%}")
        rows[arm]["operating_point"] = {
            "n_c": m, "precision_current": round(kc / m, 4),
            "ci95_precision_current": [round(clo, 4), round(chi, 4)],
            "harm_count": kh, "harm_rate": round(kh / m, 4),
            "ci95_harm": [round(hlo, 4), round(hhi, 4)],
            "knowledge_update_share": round(ku_share, 4),
        }

    # ---- ADR-010 / 013 / 014 on the narrow oracle, the arm that would be built -----------------
    print()
    print("-" * 100)
    print("ADR-010 REACH / ADR-013 READ / ADR-014 POWER -- on the NARROW oracle")
    print("-" * 100)
    orc = results["oracle_narrow"]
    changed = int((orc["top1"] != sh["top1"]).sum())
    gained = int((orc["current"] & ~sh["current"]).sum())
    lost = int((sh["current"] & ~orc["current"]).sum())
    disc = gained + lost
    p = mcnemar_exact(gained, lost)
    print(f"  contrast the test consumes: perfect-narrow-supersession top-1 vs SHIPPED top-1,")
    print(f"                              read as CURRENT-VALUE-ONLY correctness, same split, n={n}")
    print(f"  ADR-010 reach : top-1 changed on {changed}/{n} queries  -> "
          f"{'PASS' if changed >= MIN_DISCORDANT_REPORTABLE else 'BELOW THE FLOOR OF 10'}")
    print(f"  ADR-013 read  : gained {gained}, lost {lost}  -> "
          f"{'both directions' if gained and lost else 'ONE-DIRECTIONAL'}")
    print(f"  ADR-014 power : discordant {disc}; alpha={ALPHA} needs n>={MIN_DISCORDANT_MCNEMAR} "
          f"(2/2^n <= alpha); smallest attainable p here = {2/2**disc if disc else 1.0:.4f}")
    print(f"                  exact McNemar p = {p:.4f}  -> "
          f"{'alpha ATTAINABLE' if disc >= MIN_DISCORDANT_MCNEMAR else 'alpha UNATTAINABLE, declared in advance'}")

    # what the oracle costs: live memories removed that were NOT stale
    wrongly_removed = 0
    for q in eligible:
        stale = stale_turn_ids(cases[q], "narrow", turns_in)
        cur = cases[q]["current_session"]
        if cur is None:
            continue
        wrongly_removed += sum(1 for t in stale if t.rsplit("-", 1)[0] == cur)
    print(f"  oracle self-check: turns the narrow oracle removes from the CURRENT session "
          f"(must be 0): {wrongly_removed}")

    verdict = {
        "adr_010_top1_changed": changed,
        "adr_010_pass": changed >= MIN_DISCORDANT_REPORTABLE,
        "adr_013_gained": gained, "adr_013_lost": lost,
        "adr_013_both_directions": bool(gained and lost),
        "adr_014_discordant": disc, "adr_014_alpha": ALPHA,
        "adr_014_min_discordant_for_alpha": MIN_DISCORDANT_MCNEMAR,
        "adr_014_smallest_attainable_p": round(2 / 2 ** disc, 6) if disc else 1.0,
        "adr_014_exact_mcnemar_p": round(p, 4) if disc else None,
        "adr_014_alpha_attainable": disc >= MIN_DISCORDANT_MCNEMAR,
        "contrast": "perfect narrow supersession top-1 vs shipped top-1, read as current-value-only "
                    "correctness",
        "oracle_removes_nothing_from_the_current_session": wrongly_removed == 0,
    }

    # ---- the headline --------------------------------------------------------------------------
    d_ku = rows["oracle_narrow"]["ku_r_at_1_current"] - rows["shipped"]["ku_r_at_1_current"]
    d_all = rows["oracle_narrow"]["r_at_1_current"] - rows["shipped"]["r_at_1_current"]
    print()
    print("=" * 100)
    print("THE CEILING ON THIS ENTIRE LINE OF WORK")
    print("=" * 100)
    print(f"  knowledge-update R@1 (current-value only): "
          f"{rows['shipped']['ku_r_at_1_current']:.4f} -> "
          f"{rows['oracle_narrow']['ku_r_at_1_current']:.4f}   ({d_ku:+.4f})")
    print(f"  overall R@1 (current-value only)         : "
          f"{rows['shipped']['r_at_1_current']:.4f} -> "
          f"{rows['oracle_narrow']['r_at_1_current']:.4f}   ({d_all:+.4f})")
    print(f"  harm rate overall                        : "
          f"{rows['shipped']['harm_rate']:.4f} -> {rows['oracle_narrow']['harm_rate']:.4f}")
    print(f"  cases whose top-1 changes at all         : {changed} of {n}")
    print()
    print(f"  A PERFECT detector is worth {d_all:+.4f} overall and {d_ku:+.4f} on "
          f"knowledge-update.")
    print("  Any real detector reaches some fraction of that, and pays a false-supersession cost")
    print("  the oracle does not pay.")

    out = Path(str(OUT).format(split=args.split))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "_what": "the ceiling on supersession detection, under a perfect oracle",
        "_simulation": "candidate-set level: superseded turns are removed BEFORE gate ordering and "
                       "slate construction, so a surviving candidate is promoted and scored",
        "split": args.split, "n": n, "knowledge_update_n": int(ku.sum()),
        "control_reproduces_harm_weighted_precision": True,
        "arms": rows, "verdict": verdict,
        "ceiling": {"delta_ku_r_at_1_current": round(d_ku, 4),
                    "delta_overall_r_at_1_current": round(d_all, 4),
                    "top1_changed": changed},
    }, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
