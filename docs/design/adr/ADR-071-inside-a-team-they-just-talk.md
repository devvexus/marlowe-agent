# ADR-071 · Inside a team they just talk — typing and quarantine are Marlowe's boundary, not the team's

**Status:** **Accepted 2026-08-31 by Matthew.** **DESIGN ONLY — NOTHING IS BUILT.** It depends on
[`ADR-070`](ADR-070-one-sandbox-per-team-and-it-wraps-bash.md)'s box existing, and that box has not
been spiked.

| | |
|---|---|
| **Supersedes** | nothing |
| **Amends** | **M3-DESIGN §2's headline invariant**, by inserting two words. Also §2.2, §2.3, §1.4, §9.1's arm A8, and ADR-039's trust-class trigger for the quarantined reader |
| **Depends on** | ADR-070 (the box), ADR-039 / ADR-041 (layer 1), M3-DESIGN §2.1 (why Marlowe is a liaison), `PI-MODEL.md` §1 |
| **Contract change** | **None yet.** `OutputContract` and `FieldSpec` are unchanged and still govern the Marlowe boundary |
| **Code change** | Specified, not written |

---

## 0 · THE INVARIANT, RESTATED — and it is two words, not a weakening

M3-DESIGN §2 reads:

> *"Nothing but typed structure and artifact references crosses upward. **Ever.**"*

**It becomes:**

> **"Nothing but typed structure and artifact references crosses upward INTO MARLOWE. Ever."**

**That is the whole amendment, and the "Ever" is untouched.** The human's own correction, and it is
better than the framing this ADR was first written with — *"the boundary moved"* — because it says
what the rule always meant rather than describing a change to it.

**The rule was never about height. It was about Marlowe.** §2.1 gives the reason and gives it in the
first person: ADR-023's floor is monotonic and latched per run, Marlowe is the one *permanent* run,
so *"a Marlowe who ingests one research finding can never compose a target again — not for that task,
for his life."* Every other run in the tree is task-scoped and disposable. **The protection was
always for the one agent that cannot be restarted**, and applying it at every hop was generalising
from the case that needed it to cases that did not.

So an intern talking to its PI was never the thing §2 was defending, and the sentence now says so.

---

## 1 · The decision

> *"Just let them talk like an intern would to the PI. We don't want to hinder their work together.
> The PI is insanely smart and can catch the intern if they say something dumb. Do not hinder the
> research team's capabilities — no summaries, no typed-up channel. That's only for Marlowe."*

**Inside a top-agent's team, agents communicate in ordinary prose, both directions.** No
`OutputContract` between an intern and its PI, no quarantined reader condensing pages before a worker
sees them, no field validation on what a subordinate reports.

**The typed channel and layer 1 survive at exactly one boundary: the team's edge with Marlowe.**

## 2 · What this changes, precisely

| hop | before | after |
|---|---|---|
| page → intern | quarantined reader condenses it | **the intern reads the page whole, itself** |
| intern → PI | validated `OutputContract` fields | **prose** |
| PI → Marlowe | prose became a harness constant | **unchanged — typed, and this is the only place it matters** |
| PI → user | artifact the user opens | unchanged |

**Two costs disappear.** A model call per six sources, serialised behind `NUM_PARALLEL=1`; and the
fidelity loss of reading someone's summary instead of the source. For research where the exact
wording *is* the finding — a formula, a constant, a quoted claim — the second one was the expensive
one.

## 3 · Why this is defensible, and it rests on ADR-070

**The team is in a box.** No network, no filesystem outside its workspace. An attacker who owns a
page owns an intern in a disposable directory. Nothing it can *do* matters, so the only thing that
leaves is what it *says* upward — and upward, within the team, is another model reading prose.

**So the team's security model is two mechanisms with a clean split**, replacing five overlapping
ones:

* **The sandbox bounds what an agent can DO.**
* **The Marlowe boundary bounds what an agent can INFLUENCE outside the team.**

**And typing was never protecting against persuasion.** `validate` checks shape, length and
character class — attacker-shaped prose inside a declared field crosses either way. What typing
actually bought was protection against **forged structure**: a child cannot invent a field, cannot
forge a header (ADR-039), and the parent attributes by harness-assigned slot. That matters when the
receiver is a **machine parsing slots**. Between two models reading each other's prose it has far
less purchase, and it costs fidelity to buy.

## 4 · THE BET THIS TAKES, STATED ONCE AND NOT ARGUED AWAY

> *"The PI is insanely smart and can catch the intern if they say something dumb."*

**That is a claim about model capability, and this project has spent its whole life preferring
structure to model behaviour.** §1.2's own reversed rule said it in the opposite direction — *"not
because it is disobedient, because it is capable and the work is right there."*

Two things make it a considered bet rather than an oversight, and one thing keeps it honest:

1. **The downside is bounded by the box.** A PI fooled by an intern acts inside a sandbox. The
   failure mode is a wrong finding, not a compromised machine.
2. **A human reads the output.** M3-DESIGN §3 puts the decision on a person deliberately, and a
   wrong finding in a report is the failure mode a reader is best placed to catch.
3. **The bet is testable and is NOT yet tested.** `runs/m3-c/prefilter/FINDING.md` measured that
   *polite* injections — the plausible ones — beat every small model on every carrier, while the
   shouting ones were caught. **A smart reader may be no better at the polite case than a small
   one**, and nothing here establishes that a PI catches what a detector missed. That is the
   measurement this ADR owes.

## 5 · What A8 becomes

M3-DESIGN §9.1's arm **A8** — fully typed / typed + one sentence / free text — **no longer describes
the intern→PI hop, because that hop is now free text by decision rather than by arm.**

**A8 narrows to the boundary that still has one: the team's edge with Marlowe.** Its question is
unchanged and its importance is undiminished — Marlowe is the permanent run whose floor must never
latch (§2.1), and if typing is decorative *there*, the liaison pattern is decorative with it.

**Red-team pass 1's four defects still stand and still need fixing** before any A8 number means
anything (`runs/m3-c/redteam/PASS1-REPORT.md`).

## 6 · What this does NOT change

* **Marlowe is not boxed and his securities stay heavy.** §2.1's invariant is untouched: nothing
  here can latch the Secretary.
* **Layer 1 still exists** — for Marlowe. What moves is its *scope*, and that is a real amendment to
  ADR-039, whose whole argument was that the trigger is **the trust class, not the tool name**, so a
  new untrusted tool is covered without anyone remembering. Keying it on *who is reading* instead is
  a different shape and §7 records it as unfinished.
* **The artifact path is unchanged.** A team writes files; the user opens them.
* **Egress is unchanged.** `web` is harness-executed and the box does not constrain it, so the
  allowlist remains the only thing between a team and an attacker-named host.

## 7 · Open, and none of it is decided here

1. **How layer 1 becomes Marlowe-only in code.** `Engine::condense_batch` triggers on
   `blocks_composed_targets` — the trust class — which is ADR-039's deliberate design. Scoping it by
   the reading run's level, or by whether that run is boxed, is a change to a §13-adjacent path and
   needs its own argument.
2. **Whether the PI actually catches a polite injection.** §4's bet, untested. The cheapest
   experiment is the pre-filter corpus re-run with the PI as the reader.
3. **What "the team's edge with Marlowe" is in code.** Today `Engine::spawn`'s note match is the
   only such hop, and it does not distinguish a team boundary from any other spawn.
4. **Whether a team without a box gets the old rules back.** If ADR-070's spike fails and there is no
   sandbox, this ADR's premise is gone. **It must not survive its own precondition.**
