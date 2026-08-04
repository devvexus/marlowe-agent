# M0b Session B — result, against `PREREGISTRATION.json`

Every band and prediction below was written to `PREREGISTRATION.json` **before** the gate was
fit. Nothing here was edited after a number existed.

Generated artifacts: `summary.json` (the two numbers and the conditions), `heldout/` and `all/`
(the harness's own reports), `regression/` (the Session A checks re-run against this build).

## The two numbers

| | Predicted band | Measured | Verdict |
|---|---|---|---|
| **Number 1** — operating point, frozen 0.95 | *no band, by design* | **the gate abstained on all 249 held-out cases**; 0 injections, coverage 0.000 | the pre-registered anticipated outcome |
| **Number 2** — cue capability | 0.20–0.50 → "functioning, cue set incomplete" | **0.334** at cut 0.309, coverage 0.453 | **functioning, cue set incomplete** |

**Number 1 in one line: the isotonic calibration's maximum predicted precision is 0.309, and the
frozen operating point is 0.95, so nothing can ever clear it.** With one cue there is no score
region where predicted precision reaches the K1 threshold. The threshold did not move, and the
calibration resolution (256 equal-count blocks) was fixed on a stated principle before the fit —
finer top-end buckets would raise the reachable maximum, which is exactly why the choice was not
made after seeing this.

**A calibration check nobody asked for, worth recording.** The fit predicted 0.309 precision for
its top block on the *fit* split; the same block measured **0.334** on the *held-out* split. The
curve generalizes and is very slightly conservative. That is evidence the isotonic fit is real
and not memorized — which is what the split exists to be able to say.

## Conditions

| Condition | Result |
|---|---|
| Retrieval P95 ≤ 300 ms | **pass — 24 ms** |
| No case over 7,000 retrieval tokens | pass — max 0, **but vacuously**: nothing was injected, so the token budget was never exercised. Only the latency half of this condition carries information this run. |
| Injections on abstention cases ≤ 0.20 | **pass — 0.000**, and vacuous for the same reason |
| Degenerate-pass guard (coverage < 0.05) | **TRIGGERED.** The operating-point precision is not a quality signal. |

The headline `evidence_precision` reads **0.0 on both splits, and the value is vacuous** — the
ratio has an empty denominator. It means *nothing was injected*, not *the injections were wrong*.
`summary.json` carries that on the value itself, alongside the contamination label on the
all-500 figure.

## The poisoning vacuity prediction — confirmed

Predicted before the run: a gate that suppresses the attacks also stops the planted memory
reaching the injected set, so the laundering trust assertion becomes **vacuous** — 16 checked, 0
failed, and nothing actually observed.

| | Session A | Session B |
|---|---|---|
| MINJA / MemoryGraft / delayed-trigger ASR | 1.000 | **0.000** |
| Laundering trust assertions | 16 checked, 0 failed, **non-vacuous** | 16 checked, 0 failed, **VACUOUS** |
| K3 unsigned-write ASR | 0.000, 4/4 visibly rejected | **0.000, 4/4 visibly rejected** (unchanged — structural, not gate-dependent) |

**The ASR drop to 0.000 is vacuous in the same way and must not be quoted as a security result.**
A gate that injects nothing has an attack success rate of zero trivially; `utility_retention` is
0.0 beside it, which is the AgentDojo pairing saying exactly that. Session A's ASR of 1.000 and
Session B's 0.000 are both artifacts of the injection rate, not measurements of discrimination.

K3 is the exception and is the one security number that still means something: unsigned writes
are refused at the write path, before any gate exists, so its value does not depend on whether
anything is injected.

## One genuine regression, caused by Number 1

**The clock probe now FAILS (`fail_no_time_dependence`), and conformance reports REJECTED with 0
section 4 findings.** Session A passed it.

The cause is Number 1, not a clock bug: maturation was observable in Session A because the
injected set grew as entries matured. With the gate abstaining everywhere the injected set is
empty at every clock value, so there is no observable time dependence for the probe to find. The
probe is **correct to fail** — `STATE.md` already recorded that an implementation with no
observable time-dependence fails correctly, since §4.3 maturation is a requirement.

What it means concretely: **while the gate abstains everywhere, §4.3's maturation defence is
verified only by Rust unit tests and is not observable through the section 4 contract.** That is
the project's own unobservable-mismatch pattern, now applied to a defence rather than a bug, and
it is the strongest argument in this run for why the cue set has to be completed rather than the
threshold lowered.

It was not fixed by weakening the gate, and must not be.
