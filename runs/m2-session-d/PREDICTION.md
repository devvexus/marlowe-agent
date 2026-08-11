# M2 Session D — what conformance and `repro` should read after D2

**Written before the pre-D2 baseline was taken and before any code was changed.** A predicted
change that lands is evidence; an explained change is not. This file is the prediction, and it is
checked against rather than revised.

Date: 2026-08-11. Branch `master`, at `f85e2e0` plus nothing.

---

## What D2 does, stated first, because the prediction only makes sense against it

D2 applies the **declared operating point** (`docs/design/PRECISION-COVERAGE.md`) as the injection
criterion: inject rank 1, alone, when the rank-1/rank-2 **cross-encoder margin** is ≥ **1.1651**;
otherwise abstain.

**It replaces the isotonic gate's `passes` filter as the injection criterion rather than stacking on
top of it.** This is the substantive change and it must not be silent. `select_for_injection`
currently does `order.retain(|i| scored[*i].passes)`, and per ADR-016 the frozen gate's smallest
expressible operating point spans 100% of queries — a perfect retrieval system scores 0.8483 against
a 0.95 threshold — so `passes` is false for everything and **nothing has ever been injected**. If the
operating point were ANDed with `passes`, injection would remain dead, the poisoning suite would stay
vacuous, and the change would be undetectable. The amended K1 (ADR-019) replaced the single-point
criterion with a published curve and a declared point precisely because the gate cannot express a
confident subset; wiring that point in is what STATE.md's *"the gate still injects nothing"* item
asks for.

**No precision claim attaches to runtime behaviour.** The 0.9130 figure is measured on a population
that excluded every query with no gold in its pool and every LongMemEval abstention case
(`tools/publish_precision_coverage.py:114-118`). The cut point transfers; the precision does not, and
it is not quoted in `--dev`, in code comments, in STATE.md, or here as a description of what the
running system achieves.

---

## Prediction 1 — conformance

**Baseline (recorded separately in `BASELINE.md`, measured immediately after this file was
written):** expected to read

```
REJECTED: 0 finding(s); clock probe fail_no_time_dependence
```

exit 1, which is the unchanged reading since M0b Session B.

### Predicted post-D2 reading

```
CONFORMS: no section 4 violations, clock probe passed.
```

**exit 0**, with the clock probe reporting:

| field | predicted value |
|---|---|
| `verdict` | `pass` |
| `translation_invariant` | `true` |
| `time_dependent` | **`true`** — this is the field that changes |
| `detail.queried_immediately.injected` | `[]`, `abstained: true` |
| `detail.queried_after_one_year.injected` | **exactly one memory id**, the one derived from `clock-t0` (*"the release train leaves on Thursday mornings"*), `abstained: false` |
| `detail.at_epoch` vs `detail.shifted_ten_years` | identical |
| `findings` | `0` |

### Why, mechanically

`suites/clock.py` test B ingests one session and queries at gap 0 and gap 1 year. Today
`_fingerprint` returns `((), True)` in all four cells because nothing is ever injected, so
`immediate == later`, `time_dependent` is false, and the probe fails. §4.3 exclusion (3) withholds
unmatured beliefs, so with injection live the gap-0 query must still inject nothing while the
gap-1-year query injects — which is exactly the observable time dependence the probe demands.

### The three conditions this rests on, named so a failure is diagnostic

1. **The maturation exclusion withholds at gap 0.** Existing behaviour, unchanged by D2. If it does
   not, gap 0 and gap 1 year both inject and `time_dependent` is false again — same verdict as today,
   different cause.
2. **The rank-1/rank-2 margin on `clock_corpus()` clears 1.1651.** Five turns in one session, one of
   which is a near-verbatim answer to the query and four of which are filler. A cross-encoder margin
   between a strong match and filler is normally several logits, so this should clear with room. **It
   is not certain**, and it is the condition most likely to fail.
3. **Rank 1 is the `clock-t0`-derived memory.** If rank 1 is a filler turn, the probe may still pass
   while the system is wrong; the `injected` id in `detail` is what distinguishes those, which is why
   the predicted id is stated above rather than just the count.

### The failure readings and what each would mean

| post-D2 reading | what it means |
|---|---|
| `pass`, one memory injected at 1 year, id derived from `clock-t0` | **prediction holds** |
| still `fail_no_time_dependence` | the operating point clears on nothing at this corpus size — injection is live in code and dead in practice, and the poisoning suite will still be vacuous. A worse outcome than a visible failure |
| `fail_translation_variance` | D2 introduced a system-clock read on the §4.1/4.6 path. Blocking |
| `pass` but the injected id is a filler turn | the probe passes on the wrong memory. The verdict would be green and the finding real |
| findings > 0 | a §4 violation; most likely `abstained_with_injected` or `abstention_reason` set while `abstained` is false — `validate.py:133-146` |

---

## Prediction 2 — `repro`

**The core hash WILL move off the pre-D2 baseline**, and that is the change landing rather than a
regression: the §4.2 response now carries injected memories where it carried none, and the injected
set is in the hash.

**What must NOT change:** `repro --runs 2` must still report the two runs as **identical to each
other**. Determinism is the property under test and D2 touches nothing that could break it — the
ranking key, the tie-breaks and the clock discipline are all unchanged. A hash that differs *between
the two runs* is a D2 defect, and it is a different failure from the hash differing from the
baseline.

Stated as two separate assertions on purpose, because one command reports both and they are not the
same claim.

---

## Prediction 3 — the poisoning suite

MINJA, MemoryGraft and delayed-trigger have all read **ASR 0.000** and STATE.md records them as
**vacuous**: an attack cannot succeed through an injection path that injects nothing. Post-D2 they
become non-vacuous for the first time.

**No prediction is made about the ASR values.** There is no prior measurement to predict from and
inventing one would be a number to defend rather than a number to read. What is predicted is
**vacuity ending**: at least one attack family must reach a state where a planted memory is a live
injection candidate that cleared the cut point, or the suite is still measuring nothing and the
0.000s are still not evidence.

**The utility number is reported beside every ASR.** An ASR that fell because retrieval got worse is
not a security result, and the two are indistinguishable from the ASR alone.

---

## What none of this covers

The D4 finding — a memory whose text was chosen by untrusted content, written through a legitimate
`remember` call by a non-quarantined run, competing for rank 1 on equal terms at injection. That is a
**write-path** attack through a legitimate tool, and no suite here measures it: CONTRACTS §4 speaks
ingest/retrieve/consolidate to a process with no model and no tools, and the attack's first step is
the model calling `remember` after a fetch. A §4 op for that would be the implementation reshaping
the scoreboard, which is what `eval/` exists to refuse. It needs a loop-level Rust integration test in
the `adr023_live.rs` family. Proposed in this session; the fix side is §13 and is the human's call.
