# M3-DESIGN §3 — escalation routing and a harness-rendered TERMINATE

Built 2026-08-31 against HEAD `3219297`. **No `cargo test` was run** (all suite runs and card loads
are held until the end of the session); every claim below that is not a compile result is a
prediction, and this file says which is which.

## Commands run, and their results

| command | result | file |
|---|---|---|
| `cargo check --workspace --tests --jobs 4` | **exit 0, 0 errors** | `cargo-check-tests.txt` |
| `python .claude/hooks/protect-boundaries.py --self-check .` | **exit 0** | `self-check.txt` |
| `python tools/preregister_redteam_pass1.py` | **exit 0**, layer 3 unreachable: True, arm selector read inside `spawn` (3 reads) | `preregister.txt` |
| `grep -rn "ingest_external(" --include=*.rs crates/*/src/ \| grep -v "fn ingest_external"` | **0 hits** | — |

**No test was executed.** Everything under "the mutation that reddens it" in the new test files is a
prediction, exactly as ADR-065 §8 says of its own table.

## The §13 file

`crates/marlowe-loop/src/driver.rs`, +74 lines, no deletions: `ModelStep::Escalate`,
`EscalationRequest`, `EscalationPort`. Its `DECISIONS.md` entry is dated `## 2026-08-31`. No other
guarded path was touched — `profile.rs`, `adjudicate.rs`, `taint.rs`, `provenance.rs`, `scope.rs`,
`egress.rs`, `steer.rs`, `memory.rs`, `mcp.rs`, `pin.rs`, `journal.rs`, `signature.rs` and
`persona/` are all unchanged. No path was added to `PROTECTED`, so CLAUDE.md's table and
`EXPECTED_PROTECTED` need no row.

## Where TERMINATE's invisibility is asserted, and why it is about bytes

Three places, and only the third has teeth:

1. `marlowe-provider/tests/terminate_is_absent_from_the_request_body.rs` — 6 profiles × 2 local
   adapters = 12 **serialized request bodies**, scanned for `TERMINATE_CANARY` and
   `TERMINATE_LABEL`. It carries a persona positive control (a body that failed to build cannot
   report a clean zero) and a **leak control** that builds a thirteenth body deliberately containing
   the canary and asserts the same scan finds it, so a zero cannot mean "the substring scan is
   broken".
2. `the_word_terminate_is_in_these_bodies_and_that_is_correct`, in the same file — the red cell
   stated out loud. `terminate` IS in every body, from `orphan_policy`'s description and from the
   spawn receipt, and this asserts it is, so nobody can "fix" §11's old row by renaming a live tool
   parameter.
3. `marlowe-surface/tests/escalation_overlay.rs` — **§11's amended row 3**. The agent writes the
   harness's own row into its option list and into A8's sentence, glyph and all; the test walks the
   rendered `Buffer` at 80×24 **and 40×10** and asserts the reserved glyph appears in exactly one
   cell, that the reserved region is flush with the overlay's bottom, and that the option region
   cannot overlap it.

**Why bytes and not a flag**: `EscalationView` has no field for the terminate row, so there is no
flag to assert. §3.4's own last line — *"asserting a flag is set is the declaration, not the
enforcement"* — is why. The strongest assertion available is over rendered cells and serialized
bodies, and that is what these are.

**What is NOT closed here**: no body was read from the **running** process. §11's amended row 2 asks
for the `--dev` outbound dump, and taking it needs a daemon turn against a loaded model, which this
session was told not to do. The provider test's header says so in place, so a future reader cannot
mistake it for the acceptance measurement — the `persona_emission.rs` lesson, written down before
it can be repeated.

## What is not built, named rather than implied

* **`ModelStep::Escalate` has no production producer.** No adapter maps a tool call to it, because
  reaching it needs an `escalate` tool in an exposed set, and that is a `profile.rs` change this
  session was told not to make. `DECISIONS.md`'s 2026-08-30 entry already settles the tool question
  — *"`escalate` is not a thirteenth builtin"*. So the routing is **enforced and unreachable**, in
  the way ADR-062 records layer 3 being, and this is the sentence the next session should read
  rather than rediscover.
* **`EscalationDesk::from_journal`.** The loop's raise event carries only the id, so a rebuild
  written against today's events would return a set of empty escalations and *look* like durability.
  The prerequisite is writing the full record through `Recorder`.
* **`Choice::Terminate` has no keybind**, so §11's amended row 2 ("its label **and keybind** appear
  in no `request_body`") cannot be fully satisfied. `Choice::wire()` is the canary's product reader.
* **`CONTRACTS.md` is unedited.** ADR-065 names two pins: `Run::raises_to` — void, because no such
  field was added — and a §5.2 escalation record. The second was not taken: pinning a shape whose
  producer does not exist commits other work to it, and ADR-065 §6.1 says the pin is the human's.
