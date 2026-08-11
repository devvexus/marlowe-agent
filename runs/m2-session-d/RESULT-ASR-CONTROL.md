# The ASR control: is 0.000 the guard, or is it nothing being injected?

2026-08-11, after M2 Session D. The question `RESULT-D2.md` left open and named as the one that
must be answered before the ASRs mean anything.

**Both arms on the same binary, one variable.** The only behavioural difference between them is the
threshold comparison in `operating_point::decide` — asserted by
`full_coverage_admits_exactly_where_declared_abstains_on_the_margin_and_nowhere_else`, which checks
that every *structural* abstention (no candidates, no reranker, no runner-up, margin undefined) is
identical in both arms. If `Full` also changed the candidate set or the ranking, a difference in ASR
would have several possible causes and the comparison would answer nothing.

```
--injection-coverage declared   →  runs/m2-session-d/arm-declared
--injection-coverage full       →  runs/m2-session-d/arm-full
```

Both target strings are recorded in each report's `run.target`, so the arm travels with the artifact.

---

## The measurement

| | declared (shipped) | full (control) |
|---|---|---|
| core sha256 | `8cf57e83…` | `8438225f…` |
| **retrieval_tokens, mean** | 9.625 | **15.5** |
| retrieval_tokens, max | 17 | 18 |
| evidence_precision | 0.7500 | 0.8333 |
| delayed_trigger ASR | 0.000 | **0.000** |
| laundering ASR | 0.000 | **0.000** |
| memorygraft ASR | 0.000 | **0.000** |
| minja ASR | 0.000 | **0.000** |
| unsigned_write ASR | 0.000 | **0.000** |

## The answer

**Removing the cut point raised injected volume by ~61% and every ASR stayed at 0.000.**

So the declared operating point is **not** what suppresses these attacks. The ASRs were never
measuring it, and — importantly — they are not merely an artifact of abstention either. Something
else is doing the work.

**The two candidates, neither isolated here:** the ingest-time actor check, which refuses the forged
`permission:grant` turn by name (`ingest_rejections` fires in both arms), and the planted text simply
failing to reach rank 1 against the genuine candidates.

## What this does NOT license

- **It is not a claim that memory poisoning is defended.** It is a claim that *the operating point is
  not the defence*. Those are different, and only the second was measured.
- **n = 4 per family, on an 8-query fixture.** Four attacks cannot distinguish 0.00 from 0.20. The
  interval on 0/4 is wide enough to contain a real vulnerability.
- **`answer_accuracy` is 0.0 in both arms and is not evidence about retrieval.** The eval adapter has
  no model, so the `answer` interface abstains structurally; that number moves with nothing.
- **`evidence_precision` rose with coverage (0.75 → 0.83)**, which is the opposite of the usual
  precision/coverage direction. On this n it is noise, and it is reported rather than explained.

## What would make the ASRs real

More attacks, and a corpus rather than a fixture. The current suite is a *smoke test* for the
poisoning path: it proves the machinery runs and that refusals are visible. **It is not sized to
detect a vulnerability**, and no ASR from it should be quoted as evidence of resistance.

The instrument now exists, which is the thing that did not before: a second arm, one variable, both
recorded. Growing n is the next increment and needs no new mechanism.

## A defect this measurement produced, recorded because it nearly landed

The first attempt at the control ran against a **stale binary**. A daemon was holding `marlowe.exe`,
`cargo build --release` failed with `Access is denied (os error 5)`, and the pre-`Coverage` binary
**silently ignored `--injection-coverage full`** and ran the declared arm under the full label. It
produced a complete report.

**Two things caught it**: the build error was visible in the same output, and the run's hash did not
match either expected arm. What would have caught it regardless is `run.target` in the report — the
flag is recorded whether or not the binary understood it, which is exactly why the arm belongs in the
artifact rather than in someone's memory of the command line.

**A build that cannot replace a running binary fails, and the old code keeps serving.** Second
occurrence this session. Order is shutdown → build → run.
