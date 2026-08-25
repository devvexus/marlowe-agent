# ADR-053 — What a checkpoint must carry, and why a step number is not it

| | |
|---|---|
| **Status** | Accepted, M3 Session A, 2026-08-25 |
| **Supersedes** | nothing. `EventKind::Checkpointed`'s `{"step": n}` payload is widened, not replaced |
| **Depends on** | ADR-023 (the trust-floor latch), ADR-041 (batched quarantined reads) |
| **Implements** | CONTRACTS.md §5's `RunControl::checkpoint` / `resume`; ROADMAP M3's *100% resume from last checkpoint* |
| **Contract change** | **None.** §5 is implemented as pinned. `Checkpoint` was named there and never defined; this defines it |

---

## §1. The decision

**A checkpoint carries the run's whole resumable state, inline, in one signed journal event.**
Twelve fields, and five of them exist because their absence is a defect rather than an
inconvenience:

| Field | What its absence does on resume |
|---|---|
| `trust_floor` | **The latch un-latches.** §2 — this is the one that made this an ADR. |
| `spent` | The budget resets, so a run costs its declared ceiling **per restart**. |
| `profile` | A quarantined reader could come back holding tools. |
| `step` | `MAX_STEPS` never fires; a looping run loops forever across restarts. |
| `contract_retries` | Audit finding E8's bound resets, so the unsatisfiable-contract loop returns. |

The rest — `run`, `parent`, `session`, `trace_id`, `status`, `budget`, `orphan_policy`,
`output_contract`, `state`, `version` — are identity, addressing and the window.

Before this, the loop recorded `{"step": steps}` and **the live journal holds 895 of them.** That
was an honest record that a step completed. It was not a resumable state, and the gap was not "a
few more fields".

---

## §2. The reason this is an ADR and not a commit

ADR-023 says the floor is *"monotonic and latched per run"*. The latch exists because the floor
used to be **derived** from the current window: `ToolResults` is trimmable, so the assembler could
drop the untrusted block to stay inside its budget and the floor would rise again — a run silently
regaining privileges it was supposed to have lost, with no error and no event.

**A resume that rebuilt the run through `Run::root` reopens that hole by a different route.**
`root` starts at `TrustClass::UserAsserted`. So a run that read a hostile page, latched to
`UntrustedContent`, checkpointed, and came back after a daemon restart would compose targets again.

> **The restart would have become the trim.**

And it would have been invisible. Every existing ADR-023 test runs inside one process, so the
whole family is structurally incapable of seeing it — the property they assert is true for the
whole of each test's life. This is the *"a measurement is scoped to the system it was taken on"*
family arriving in a place nobody had a system to measure yet.

`Run::restored` is therefore the **only** constructor that sets `trust_floor` from outside
`run.rs`, and the mutation that makes it hard-code `UserAsserted` fails exactly one test —
`the_trust_floor_survives_a_restart` — with `a_clean_run_resumes_with_a_clean_floor` as the
control that fails if `restore` ever hard-codes the *other* value to make its sibling pass.

---

## §3. Inline, not by reference

The state travels **inside the signed payload**, not behind a `ContentRef`.

A checkpoint that referenced mutable state elsewhere would be a durability claim resting on
something the signature does not cover: the log would say a run is resumable and the thing it
resumes from could have changed underneath. `Journal::verify_chain` runs on open, so an inline
payload is verified as a condition of the daemon starting at all.

**The cost is real and is stated rather than hidden.** A checkpoint is written every iteration, so
a run writes its whole window `steps` times. Two things bound it:

1. **One checkpoint is bounded by the window**, not by the run. Compaction triggers at
   `COMPACTION_TRIGGER` of the effective context, so the window cannot grow without bound.
   `a_checkpoint_is_bounded_by_the_window_not_by_the_run` measures the real number and asserts
   the size does not grow with the step count — a measurement, not the argument for one.
2. `MAX_STEPS` is 400, so a single run's checkpoint traffic is bounded by `400 × window`.

Compressing, de-duplicating against the previous checkpoint, or writing every *N*th step are all
available and **none is done now**. Each is a second mechanism in a path that needs one, and the
project's rule is that a measurement decides. When the journal's growth becomes a number somebody
has, this is the decision to revisit.

**A consequence to know: the journal now holds raw conversation content, including untrusted tool
results.** It always held tool-result *summaries*; it now holds the window. The journal is not
model-reachable (invariant 8) so this is not a laundering path, but it is a change in what a
profile directory contains, and §3.4's redaction machinery now has a second place to reach.

---

## §4. Versioned, and an unknown version is refused

`CHECKPOINT_VERSION = 1`, with `deny_unknown_fields`.

**A checkpoint of an unknown version is refused by name, never interpreted.** `serde` would happily
fill a missing field with a default, and *every default this struct could take is a security
property reset to its permissive value* — the floor to `UserAsserted`, `spent` to zero,
`contract_retries` to zero. `ResumeError::UnknownVersion` carries both numbers.

**A pre-M3 payload is skipped, not fatal.** The 895 `{"step": n}` events in the live journal do
not decode; `JournalCheckpoints::latest` filters them out, so a run that only ever wrote those
answers `ResumeError::NoCheckpoint` — which is true. Refusing to start on them would have made
this change a migration; interpreting them would have resumed a run with every security field
defaulted.

---

## §5. Provenance is reconstructed, not stored

`Provenance` is a cache of *"the user literally typed this string"*, and it lives behind brief
§13's boundary (`crates/marlowe-loop/src/provenance.rs` is a guarded path). Its inputs are already
in the checkpointed state: every `SourceKind::History` block at `TrustClass::UserAsserted` is a
user message or a steer, which is exactly what `attribute_user_message` was called with.
`Checkpoint::restore` replays those calls.

**Losing it entirely would have been safe**, and that is worth stating because it decides how much
this needs to be trusted: `taint_for` falls back to the run's floor for any unattributed value, and
`TaintSet::of` defaults to untrusted for an absent key. So the reconstruction buys usability, not
safety, and the failure direction is *more* refusals rather than fewer.

---

## §6. Orphan policy is enforced by writing the child a new checkpoint

`OrphanPolicy` has been declared at spawn and journalled since M2 Session A, and **nothing read
it**. Enforcement is not a flag — it is an observable change to the child, and the three variants
have to be distinguishable by looking at the child alone.

So settlement writes a **new checkpoint for the child**, which is the only durable record a run
has:

| Policy | Child's checkpoint after | `resume(child)` then |
|---|---|---|
| `Terminate` | status `Cancelled` | refuses — `ResumeError::Terminated` |
| `Detach` | `parent: None` | resumes, parentless |
| `Adopt { by }` | `parent: Some(by)` | resumes, under the new parent |

**No new `EventKind`.** CONTRACTS §1.1 pins the kind list, and a settlement is exactly what a
checkpoint already expresses: the state of a run at a moment. Adding a kind would have been a
schema change to a pinned contract for something the existing one already says.

`settle_orphan` is **pure** — it returns the amended checkpoint and leaves writing to the caller —
because the two callers write through different paths (the loop through `Recorder`, the daemon
through a `CheckpointStore`), and a decision with two implementations is a decision that drifts.

A child that already finished is **not** settled. Marking a completed run cancelled because its
parent later ended would rewrite history.

---

## §7. Budgets are granted, never sliced

`Budget::slice_for` is **replaced** by `Budget::grant`, rather than kept beside it. Two functions
that hand out budgets is the shape that drifts, and `slice_for_quarantined_read` already existed
precisely because `slice_for` was wrong for a repeated operation.

`slice_for` took its share of what **remained**, which decays geometrically. CLAUDE.md records
what that produced at depth one: the eighth quarantined reader held **~0.3%** of the budget, and
nothing reported it — the reader simply returned a worse summary of an attacker-controlled page.
M3's tree is depth four before tool-spawned agents, so the decay compounds three more times.

`grant` takes its share of the **original**, clamped by what remains, and refuses **with both
numbers** when an explicit grant exceeds the pool. A model told only "refused" retries the same
request; one told the numbers can ask for less.

**The share numerators moved, and the acceptance row is why.** `Standard` was 2/8 of the
remainder; four levels of that is 0.39% of the root, under M3 §11's *never `< 1%`* line before any
sibling decay is counted. It is now **3/8 of the original**, which measures **1.98%** at depth 4
from a 200k root. `a_leaf_at_depth_four_is_inside_the_declared_band` is the command that prints it
and the band — **[1%, 5%]** — is declared in the assertion rather than in prose.

`Large` is 5/8 rather than 4/8, for the reason the old comment gave and could not enforce: *never
all of it*, because a parent that hands over everything cannot synthesise the result it asked for.

**Every dimension still floors at 1 while the parent has any.** Instance 17 is unchanged: a granted
dimension that rounds to zero means *already exhausted*, not *may not use*.

---

## §8. Steering is routed by run id

`Control::cancelled` and `Control::take_steer` now take a `RunId`.

They took none, and answered for the whole stack. That was honest while the only addressable run
was the one in front of the user. A depth-four tree needs `cancel(child)` not to kill the parent,
and §5's *"children outlive parents"* needs it not to kill a sibling either — and scope item 3,
*"`steer` injects guidance into a running child"*, is unexpressible with one broadcast queue,
because the parent is the run at the top of the stack and takes the message first.

`EphemeralControl` keeps the broadcast behaviour it always had, **stated rather than inherited**,
so every M2 test still means what it meant.

**A steer cannot restore a privilege, and that is structural rather than checked.** A steer enters
the window as a `SourceKind::History` block at `TrustClass::UserAsserted`, and the floor is a
monotonic latch — `Run::latch_trust_floor` only ever lowers it. M3-DESIGN §6.1 requires the run
window's steer field to take the same adjudication as `/steer`; what that adjudication amounts to
is this, and it is asserted where it is enforced.

---

## §9. A second listener, and the port is advertised rather than derived

The daemon serves one connection at a time. Its own comments say so — *"a second client is a M3
concern and pretending to handle it now would be a concurrency story nobody tested"*, and
`Request::Approve`'s arm says *"Concurrency is M3."*

This is M3, and this is the **smallest** amount of that concurrency that makes the milestone's
scope true. A steer sent from a second terminal to a serial daemon is not *read* until the turn it
was meant to change has ended; queuing it and calling that mid-flight would be a control that looks
like it works and cannot.

`crate::control_plane` listens on its own port and shares exactly two things with the turn in
flight: the run table and the `DurableControl`. It **never touches `Daemon`** — the model, the
memory, the tool host, the session store and the journal-for-writing all stay behind the daemon's
own lock. The loop reaches the shared state through `SharedControl`, which locks **per call** at
iteration boundaries; nothing holds the lock across a model call.

### 9.1 `port + 1` was wrong, and two tests found it within minutes

The first version derived the control port. The default is 11435, so a daemon deliberately started
on 11436 lands on the first one's control plane; a client then offers the second profile's token to
the first profile's listener and is refused, which reads as a mysterious auth failure and is not
one.

`socket_auth` and `split` both call `free_port()`, and the OS handed one fixture a port another
fixture's control plane had just taken. That is the *defaults that make a mismatch unobservable*
family with the sign flipped: the derivation made a collision **silent** everywhere except where
two daemons happened to be adjacent.

The port is now **bound at 0 — the OS picks — and written to the profile root**, next to
`daemon.token` and under the same directory ACL. Discovery, not arithmetic. A client that finds no
advertised port falls back to the main port, which is slower and always correct.

**The second listener is a second door, and it takes the same lock**: the same token, checked the
same way, before anything is parsed as a request.

---

## §10. What this does NOT do

Stated so it is not read as more, which is the failure this file's neighbours record most often.

- **A run is still per-turn in the daemon.** `Request::Ask` creates a `RunId`; the conversation is
  the *session*, and `self.sessions` is still in memory. So a daemon restart still loses the
  conversation, and what resumes is **the interrupted turn**. Making the session durable is a
  separate change with its own compaction-lineage questions.
- **Nothing resumes automatically.** `marlowe --resume <run>` is a person deciding. An
  auto-resume-on-boot sweep needs the orphan settlement to run against the journal at startup,
  which `settle_orphan_in` exists for and nothing calls yet.
- **`ingest` is not wired**, so layer 3's latch is still unreachable in the shipped daemon, exactly
  as CLAUDE.md records. `the_trust_floor_survives_a_restart` sets the floor by hand, and is
  therefore a test of the *checkpoint*, not evidence that the boundary holds in the product. That
  remains Session B's, in the order M3-DESIGN §8 fixes: the compaction stamp and the trim marker
  first, then the channel, then the boundary test.
- **The control plane is not the full window.** §6.2's fields are all in `Event::RunDetail`;
  rendering them as a window is Session F's, against this frame.
