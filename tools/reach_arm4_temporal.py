"""Session G, arm 4 — temporal anchoring, applied as a HARD CONSTRAINT.

Three dates per turn, per Mastra's structure:

  1. **observation date** — when the turn was said. Free: it is `haystack_dates` for the turn's
     session, already re-attached by `reach_pools`.
  2. **referenced date** — the date the turn's *text* points at ("last Tuesday", "on May 20",
     "three weeks ago"). Extracted here, rule-based, resolved against the observation date.
  3. **relative offset** — referenced minus observation, in days. Derived from the first two.

The candidate filter is a hard constraint over a window parsed from the question, not a weighted
cue. That is the registered shape.

**Registered read order** (`PREREGISTRATION.json -> arm_4_registered_reads`): extraction coverage
is reported FIRST, because a null here is ambiguous between "temporal filtering does not help" and
"the extractor missed the dates", and the oracle cannot separate those. The primary read is the
extraction-covered subset; the full-set number is reported beside it because that is what a build
would actually deliver.

---

## What the corpus turned out to be, and why it decides this arm

Read before writing the extractor, and it changes what the arm can measure. LongMemEval's
temporal-reasoning questions are almost entirely **interval arithmetic over two events**:

    "How many weeks ago did I meet up with my aunt and receive the crystal chandelier?"
    "How many days passed between the day I cancelled my FarmFresh subscription and ..."
    "How many days did it take me to finish 'The Nightingale' by Kristin Hannah?"

These name two **events** and ask for the span between them. They do not name a **window**. A hard
retrieval-side constraint needs a window to constrain on, so on this corpus it mostly has nothing
to bite on — and where a window does exist ("in the past three months") it is wide.

That is a claim about the data, so it is **measured, not asserted**: question-side window coverage
is the first number this script prints. The transferable reading is that Mastra's three-date
structure does its work at the **answer** stage, computing an offset once evidence is in hand,
rather than at the retrieval stage narrowing what evidence is fetched.
"""

from __future__ import annotations

import io
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from reach_pools import REPO, Pool, hit, load_pools, order_of

OUT_PATH = REPO / "runs" / "session-g" / "arm4-temporal.json"
DAY_MS = 86_400_000

MONTHS = {
    m: i + 1
    for i, m in enumerate(
        "january february march april may june july august september october november december".split()
    )
}
MONTHS.update({m[:3]: i + 1 for i, m in enumerate(MONTHS)})

_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

# --- turn-side referenced-date patterns -------------------------------------------------------
_ABS_YMD = re.compile(r"\b(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\b")
_ABS_MDY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b")
_MONTH_DAY = re.compile(
    r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?"
    r"(?:,?\s+(20\d{2}))?\b",
    re.I,
)
_MONTH_YEAR = re.compile(
    r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(20\d{2})\b", re.I
)
_AGO = re.compile(
    r"\b(" + "|".join(_NUMBER_WORDS) + r"|\d+)\s+(day|week|month|year)s?\s+ago\b", re.I
)
_LAST_UNIT = re.compile(r"\b(last|past|previous)\s+(day|week|month|year)\b", re.I)
_DEICTIC = {"yesterday": -1, "today": 0, "tonight": 0, "tomorrow": 1}

# --- question-side window patterns ------------------------------------------------------------
_Q_PAST_N = re.compile(
    r"\b(?:in|over|during|within)\s+the\s+(?:past|last)\s+"
    r"(" + "|".join(_NUMBER_WORDS) + r"|\d+)\s+(day|week|month|year)s?\b",
    re.I,
)
_Q_LAST_UNIT = re.compile(r"\b(?:in|over|during)\s+the\s+(?:past|last)\s+(day|week|month|year)\b", re.I)
_Q_IN_MONTH_YEAR = re.compile(
    r"\bin\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s*(20\d{2})?\b", re.I
)
_Q_SINCE = re.compile(r"\bsince\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s*(20\d{2})?\b", re.I)


# A turn can say "50000 years ago" in the middle of a history essay, and resolving it overflows
# `datetime`. Clamped rather than caught: an offset beyond this is not a date the speaker is
# situating their own life against, so treating it as an extraction MISS is the honest reading.
# Counted, so the clamp cannot hide how often it fires.
_MAX_OFFSET_DAYS = 365 * 50
_clamped = 0


def _n(tok: str) -> int:
    tok = tok.lower()
    return int(tok) if tok.isdigit() else _NUMBER_WORDS.get(tok, 1)


def _shift(obs: datetime, days: int) -> int | None:
    global _clamped
    if abs(days) > _MAX_OFFSET_DAYS:
        _clamped += 1
        return None
    return _ms(obs - timedelta(days=days))


def _ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _safe(y: int, m: int, d: int) -> datetime | None:
    try:
        return datetime(y, m, d)
    except ValueError:
        return None


def extract_referenced_date(text: str, observed_at_ms: int) -> int | None:
    """The second of the three dates. Returns a timestamp, or None if the text names no date.

    Deliberately returns the FIRST match rather than all of them. A turn mentioning several dates
    is common and choosing among them is a modelling decision this rule-based pass has no basis
    for; taking the first keeps the failure mode legible (under-extraction) instead of inventing
    a ranking. That limitation is reported as coverage, which is the point of the coverage gate.
    """
    obs = datetime.fromtimestamp(observed_at_ms / 1000, tz=timezone.utc).replace(tzinfo=None)

    if (m := _ABS_YMD.search(text)) and (dt := _safe(int(m[1]), int(m[2]), int(m[3]))):
        return _ms(dt)
    if (m := _ABS_MDY.search(text)) and (dt := _safe(int(m[3]), int(m[1]), int(m[2]))):
        return _ms(dt)
    if m := _MONTH_DAY.search(text):
        year = int(m[3]) if m[3] else obs.year
        if dt := _safe(year, MONTHS[m[1].lower()[:3]], int(m[2])):
            return _ms(dt)
    if m := _MONTH_YEAR.search(text):
        if dt := _safe(int(m[2]), MONTHS[m[1].lower()[:3]], 1):
            return _ms(dt)
    if m := _AGO.search(text):
        return _shift(obs, _n(m[1]) * _UNIT_DAYS[m[2].lower()])
    if m := _LAST_UNIT.search(text):
        return _shift(obs, _UNIT_DAYS[m[2].lower()])
    low = text.lower()
    for word, delta in _DEICTIC.items():
        if re.search(rf"\b{word}\b", low):
            return _ms(obs + timedelta(days=delta))
    return None


def extract_question_window(question: str, ask_at_ms: int) -> tuple[int, int] | None:
    """The filter's constraint. None means the question names no window to constrain on."""
    ask = datetime.fromtimestamp(ask_at_ms / 1000, tz=timezone.utc).replace(tzinfo=None)

    if m := _Q_PAST_N.search(question):
        span = _n(m[1]) * _UNIT_DAYS[m[2].lower()]
        if span > _MAX_OFFSET_DAYS:
            return None
        return _ms(ask - timedelta(days=span)), ask_at_ms
    if m := _Q_LAST_UNIT.search(question):
        return _ms(ask - timedelta(days=_UNIT_DAYS[m[1].lower()])), ask_at_ms
    if m := _Q_SINCE.search(question):
        year = int(m[2]) if m[2] else ask.year
        if dt := _safe(year, MONTHS[m[1].lower()[:3]], 1):
            return _ms(dt), ask_at_ms
    if m := _Q_IN_MONTH_YEAR.search(question):
        year = int(m[2]) if m[2] else ask.year
        mon = MONTHS[m[1].lower()[:3]]
        if (lo := _safe(year, mon, 1)) is None:
            return None
        hi = _safe(year + (mon == 12), 1 if mon == 12 else mon + 1, 1)
        return _ms(lo), _ms(hi) if hi else ask_at_ms
    return None


def _turn_text(corpus_path: Path) -> dict[str, dict[str, str]]:
    """query_id -> turn_id -> text. The pools carry scores, not text."""
    raw = json.loads(io.open(corpus_path, encoding="utf-8").read())
    out: dict[str, dict[str, str]] = {}
    for inst in raw:
        per: dict[str, str] = {}
        for sid, session in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            for t_idx, turn in enumerate(session):
                per[f"{sid}-{t_idx}"] = str(turn.get("content", ""))
        out[str(inst["question_id"])] = per
    return out


def _rates(pool: Pool, mask: np.ndarray, ks=(1, 5, 10)) -> dict:
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return {f"{n}@{k}": False for n in ("lexical", "dense", "oracle") for k in ks}
    gold = pool.gold[idx]
    out = {}
    for name, cue in (("lexical", "lexical_bm25"), ("dense", "dense_cosine")):
        o = order_of(pool.array(cue)[idx])
        for k in ks:
            out[f"{name}@{k}"] = hit(o, gold, k)
    for k in ks:
        out[f"oracle@{k}"] = out[f"lexical@{k}"] or out[f"dense@{k}"]
    return out


def main() -> int:
    pools, _stats = load_pools()
    split = json.loads(io.open(REPO / "tools" / "split.json", encoding="utf-8").read())
    texts = _turn_text(REPO / split["corpus_path"])

    # ---- coverage, reported FIRST per the registration -----------------------------------
    turn_total = turn_dated = 0
    offsets: list[int] = []
    windows: dict[str, tuple[int, int] | None] = {}
    ref_dates: dict[str, dict[int, int | None]] = {}

    for qid, pool in pools.items():
        windows[qid] = extract_question_window(pool.question, pool.ask_at_ms)
        per_idx: dict[int, int | None] = {}
        for i, cand in enumerate(pool.candidates):
            if cand.turn_id is None or cand.session_at_ms is None:
                per_idx[i] = None
                continue
            text = texts.get(qid, {}).get(cand.turn_id, "")
            turn_total += 1
            ref = extract_referenced_date(text, cand.session_at_ms)
            per_idx[i] = ref
            if ref is not None:
                turn_dated += 1
                offsets.append(round((ref - cand.session_at_ms) / DAY_MS))
        ref_dates[qid] = per_idx

    by_cat = defaultdict(lambda: {"n": 0, "windowed": 0})
    for qid, pool in pools.items():
        by_cat[pool.category]["n"] += 1
        by_cat[pool.category]["windowed"] += windows[qid] is not None

    coverage = {
        "turn_referenced_date": {
            "turns": turn_total,
            "with_referenced_date": turn_dated,
            "rate": round(turn_dated / turn_total, 4) if turn_total else 0.0,
            "offset_days_p50": int(np.median(offsets)) if offsets else None,
            "offset_days_mean": round(float(np.mean(offsets)), 2) if offsets else None,
            "clamped_as_miss_absurd_offset": _clamped,
            "_clamp_rule": f"|offset| > {_MAX_OFFSET_DAYS} days counted as an extraction miss",
        },
        "question_window": {
            "questions": len(pools),
            "with_window": sum(w is not None for w in windows.values()),
            "rate": round(sum(w is not None for w in windows.values()) / len(pools), 4),
            "by_category": {
                c: {**v, "rate": round(v["windowed"] / v["n"], 4)} for c, v in sorted(by_cat.items())
            },
        },
    }

    # ---- the hard constraint --------------------------------------------------------------
    covered = [q for q, w in windows.items() if w is not None]
    tallies = {"covered_filtered": defaultdict(int), "covered_base": defaultdict(int),
               "full_filtered": defaultdict(int), "full_base": defaultdict(int)}
    per_case: dict[str, bool] = {}
    emptied = 0
    gold_lost = 0

    for qid, pool in pools.items():
        window = windows[qid]
        base = _rates(pool, np.ones(len(pool.candidates), dtype=bool))
        if window is None:
            # No window: the hard constraint has nothing to apply, so the pool is unchanged.
            # This is the honest behaviour of a shipped filter, not an exclusion.
            filtered = base
        else:
            lo, hi = window
            keep = []
            for i, cand in enumerate(pool.candidates):
                stamp = ref_dates[qid].get(i) or cand.session_at_ms
                keep.append(stamp is not None and lo <= stamp <= hi)
            mask = np.array(keep)
            if not mask.any():
                emptied += 1
            if base["oracle@1"] and not pool.gold[mask].any():
                gold_lost += 1
            filtered = _rates(pool, mask)
        per_case[qid] = bool(filtered["oracle@1"])
        for k, v in filtered.items():
            tallies["full_filtered"][k] += v
        for k, v in base.items():
            tallies["full_base"][k] += v
        if qid in covered:
            for k, v in filtered.items():
                tallies["covered_filtered"][k] += v
            for k, v in base.items():
                tallies["covered_base"][k] += v

    n_full, n_cov = len(pools), len(covered)

    def rate(t, n):
        return {k: round(v / n, 4) for k, v in sorted(t.items())} if n else {}

    report = {
        "_what": "Session G arm 4 -- temporal anchoring as a hard constraint, held-out pools.",
        "coverage_reported_first": coverage,
        "primary_read_extraction_covered_subset": {
            "n": n_cov,
            "baseline": rate(tallies["covered_base"], n_cov),
            "filtered": rate(tallies["covered_filtered"], n_cov),
            "_power": (
                f"n={n_cov}. A subset this size cannot separate anything from noise; the Wilson "
                f"half-width alone exceeds every promotion band."
            ) if n_cov < 60 else f"n={n_cov}.",
        },
        "secondary_read_full_heldout": {
            "n": n_full,
            "baseline": rate(tallies["full_base"], n_full),
            "filtered": rate(tallies["full_filtered"], n_full),
        },
        "harm_accounting": {
            "cases_whose_pool_was_emptied": emptied,
            "cases_that_had_oracle_at_1_and_lost_all_gold": gold_lost,
        },
        "_per_case_oracle_at_1": per_case,
        "_the_finding_is_the_coverage": (
            "LongMemEval temporal-reasoning questions are interval arithmetic over two named "
            "EVENTS, not queries over a named WINDOW. A retrieval-side hard constraint needs a "
            "window; the coverage number above is how often one exists."
        ),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    c = coverage
    print("Arm 4 -- temporal anchoring, hard constraint.\n")
    print("COVERAGE FIRST (registered read order):")
    print(f"  turns with an extracted referenced date   "
          f"{c['turn_referenced_date']['with_referenced_date']:>7,} / "
          f"{c['turn_referenced_date']['turns']:,}  "
          f"({c['turn_referenced_date']['rate']:.4f})")
    print(f"  median referenced-minus-observed offset   "
          f"{c['turn_referenced_date']['offset_days_p50']} days")
    print(f"  questions with a parseable WINDOW         "
          f"{c['question_window']['with_window']:>7} / {c['question_window']['questions']}  "
          f"({c['question_window']['rate']:.4f})")
    print("\n  by category:")
    for cat, v in c["question_window"]["by_category"].items():
        print(f"    {cat:26s} {v['windowed']:>3} / {v['n']:<3}  {v['rate']:.4f}")

    print(f"\nPRIMARY -- extraction-covered subset (n={n_cov}):")
    if n_cov:
        b = report["primary_read_extraction_covered_subset"]["baseline"]
        f = report["primary_read_extraction_covered_subset"]["filtered"]
        for k in ("oracle@1", "oracle@5", "oracle@10"):
            print(f"  {k:10s} base {b[k]:.4f} -> filtered {f[k]:.4f}  ({f[k] - b[k]:+.4f})")
        print(f"  {report['primary_read_extraction_covered_subset']['_power']}")

    print(f"\nSECONDARY -- full held-out (n={n_full}):")
    b = report["secondary_read_full_heldout"]["baseline"]
    f = report["secondary_read_full_heldout"]["filtered"]
    for k in ("oracle@1", "oracle@5", "oracle@10"):
        print(f"  {k:10s} base {b[k]:.4f} -> filtered {f[k]:.4f}  ({f[k] - b[k]:+.4f})")

    h = report["harm_accounting"]
    print(f"\nHarm: {h['cases_whose_pool_was_emptied']} pools emptied, "
          f"{h['cases_that_had_oracle_at_1_and_lost_all_gold']} cases lost gold they had at rank 1.")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
