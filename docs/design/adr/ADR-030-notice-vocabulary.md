# ADR-030 — Harness speech is a closed vocabulary, not a `String`

**Status:** ACCEPTED (M2 C2d, 2026-08-09)
**Supersedes nothing. Extends:** ADR-022 (the loop), ARCHITECTURE §2.14, Addendum C.

## 1. Context

M1's surface had `App::say(String)`, which pushed `Entry::Said` into the transcript. It was used
for `/help` output, for `No /foo. Closest is /bar.`, for `Opened for editing. Nothing sent.` Three
things were wrong with it at once, and only the first was obvious:

1. **The surface was authoring session state** — ARCHITECTURE §2.14. Closed by C2d's view-model
   promotion.
2. **The surface was authoring persona-bearing prose.** CLAUDE.md's third fixed decision says
   *anything* producing user-visible prose carries the persona. Not *anything Marlowe-voiced* —
   anything. The rationalisation that command errors are "the tool answering, like a shell" is
   contradicted by the project's own binding rule.
3. **Moving composition to the producer would not have fixed it.** A producer with
   `Entry::Said(String)` can write anything a surface could. The defect would have been displaced
   by one layer, not removed — and displaced defects are harder to see, because the obvious
   violation is gone.

## 2. Decision

**Harness-composed speech is a closed enum, `marlowe_view::Notice`, with one renderer.**

`Entry::Said` carries `Speech`, not `String`:

```rust
Speech::Model(String)     // tokens from the model; a String is unavoidable
Speech::Harness(Notice)   // closed, type-checked
```

The model half stays a `String` because model output *is* one, and pretending otherwise would be a
fiction. The harness half cannot be widened without adding a variant and defending it against §5.

## 3. Who constructs, and why that is not who speaks

The voice is always Marlowe's, rendered in exactly one place. What differs is who holds the facts.

| Variant | Constructed by | Because |
|---|---|---|
| `Listing(Listing)` | **surface** | `/help`, `/keys`, `/model` — the surface already has the registry and the view |
| `Refused(Refusal)` | **surface** | unknown command, bad usage, no such option — all knowable locally |
| `NotBuilt { capability, arrives }` | either | a static fact about the build |
| `PaneOpened { tab, summary }` | **producer** | composed from live session data |
| `ApprovalResolved { disposition }` | **producer** | follows a decision the surface did not make |
| `Undone { turns }` | **producer** | only the producer knows what was actually removed |

**Surface construction is a requirement, not an optimization.** Routing `/help` through a producer
would make it a socket round-trip on the daemon path. A help command that waits is worse than one
in the wrong voice, and no variant here ever reaches a model — nothing in `Notice` can perform
inference.

## 4. `unknown_slash` is the shape to copy

`Outcome::Unknown` → `Notice::Refused(Refusal::UnknownCommand { name: Echo, nearest })`.

**The surface cannot send prose because the signature has no `String` in it.** That is stronger
than a rule saying it shouldn't: `client_note("whatever I like")` does not compile. Prefer this
shape wherever a rule would otherwise have to be remembered.

## 5. THE GROWTH RULE

> **A variant is added only when a producer must say something the existing set cannot express.
> Never to carry a string the surface already has.**

This is the whole of what stops `Notice` becoming `say(String)` with extra steps. A vocabulary that
grows one variant per call site *is* `say(String)`, spelled differently and with more ceremony.

**Mechanical form:** no field may be a free-text `String`. A field is

- a compile-time `&'static str` (cannot be composed at runtime), or
- a typed value (`u32` cents, `(u8, u8)` time, an enum), or
- an `Echo` — text the **user** typed, quoted back verbatim and never reworded.

`Echo` and `PathLabel` are newtypes precisely so the check can tell "we are quoting" apart from "we
composed a sentence". Enforced by `marlowe-view/tests/vocabulary.rs`, verified by a negative
control: a new variant carrying a `String` fails by name.

**Growth bound on `PaneSummary`:** one arm per noun, capped at **seven** — ADR-007's nouns. An
eighth means the split is wrong, not that the enum needs widening.

**Two candidates were dropped while writing this**, and they are recorded because the pressure to
add them was real: `Requested(Intent)` (echoing `model → sonnet-5`; the picker moving *is* the
confirmation) and `Lineage { generations, compacted }` (already in `Pager`, which the surface
renders).

## 5a. A control that only catches what the compiler catches is testing nothing

**The `String`-field guard took three attempts to verify, and the two failures are the lesson.**

1. Added a new `Notice` variant with a `String`. **Did not compile** — the variant broke `render`'s
   exhaustive match. Control never ran; grep found nothing; it *looked* like the guard was silent.
2. Added a `String` field to an existing variant. **Did not compile** — it broke every construction
   site, including the test file's own.
3. Added a new variant with a `String`, handled in `render`, constructed nowhere. **Compiles, and
   the guard fails by name.**

The type system already prevents cases 1 and 2. So a control built from either would have "passed"
while proving only that Rust checks enum arity — the scanner's entire value is **case 3, the one
that compiles**, and that is the only case worth controlling against.

**Generalise this to every structural guard in this project.** A negative control has to break the
property the guard is *for*, not a property something else already enforces. If the control fails
to build, it has not run, and a guard that has never been observed failing is a guard nobody has
tested. Ask of any control: *would this still fail if the guard were deleted?* If the answer is
"no, it would fail earlier", it is measuring the compiler.

This is the same family as the fourteen instances in CLAUDE.md — a measurement answering a question
adjacent to the one being asked — arriving in the verification of a guard rather than in the guard.

## 6. An unhandled intent is a build error

`Intent` is closed and every `Produce::apply` matches it exhaustively — **no `_` arm**. Adding a
variant is a compile error in every producer, which is construction-time rather than runtime.

A surface emitting an intent nobody handles would be **worse than the violation it replaced**: it
fails silently, and a working build and a broken one look identical. That is the failure family
this project has logged more than any other.

Three parts, because the compiler alone is defeated by one lazy arm:

1. `no_produce_impl_has_a_catch_all_arm` scans every `fn apply(&mut self, intent` for `_ =>` /
   `_ if`, with a positive control asserting it found implementations at all.
2. A producer that *cannot* perform an intent returns a **named** `IntentError` — refusing out loud
   is correct; refusing in silence is not.
3. `Intent::Help` does not exist. Help is surface-side, so the class of unhandleable intents is
   smaller by construction.

## 7. What `Notice` deliberately does not cover

Named so C3 does not inherit a vocabulary sized for two cases:

1. **Model-originated prose** — `Event::Text` → `Speech::Model`. Notice is *harness* speech only;
   conflating them would put the persona in two places.
2. **The stub's scripted replies** (`Action::Say`) — fixtures standing in for model output, so (1).
3. **Tool summaries** — `Metric` / `ResultSummary`, already closed.
4. **Approval blast radius** — its own typed shape, below.
5. **Diagnostics** — `/doctor`. A terminal capability report is not speech, and the carve-out is
   bounded at two entry points by `marlowe-surface/tests/diagnostic_bound.rs`.

## 8. §B9's blast radius gets the same treatment

`BlastRadius` carried three free `String` fields. The *renderer* was already clean — `overlay.rs`
reads them and composes nothing, and the type has no field for the command. What was scaffolding is
that **nothing could compute those strings**: the stub hand-wrote them, and the daemon had no path
to them at all. **M1's overlay was scaffolding, and the record should say so.**

A surface can never compute this. `Delete 1,204 files in ./build · not recoverable` needs a
filesystem walk against the permission layer — a surface computing it would be **inventing a claim
about a filesystem it does not own**, at the moment the user is deciding whether to trust it.

So `BlastRadius` is now `{ effect, tier, novelty, ceiling, offered }`:

- **`novelty` is required, not `Option`.** It is a judgment about *history*, so only something
  holding the interaction record can make it. `Novelty::Routine` is a value meaning "nothing
  unusual" — a claim a producer makes on purpose. An `Option` would let a producer omit the line
  with nothing reporting the omission, and the violation would return at M6.
- **`ceiling` is required** for the same reason. *"This class sits at its ceiling and cannot be
  promoted"* is the **trust ledger's** statement; a surface asserting it would be guessing about
  promotion logic §13 puts out of reach.
- **`offered` derives §B9's four keys** — `↵ send · e edit first · s send as marlowe · esc deny`.
  Accept and deny are never withheld. The third is Addendum A §A3's delegation escape hatch and is
  **the producer's to offer or withhold**: offering it when nothing can perform a delegated send is
  a key that does nothing.

## 9. Consequences

**Good.** The answer to *"what can Marlowe say without a model?"* is one enum, readable in one
place. §C1/§C4 become executable over the whole vocabulary. `/help` stays instant.

**Costs.** `Notice` is constructible by the surface, which is what buys round-trip-free `/help` —
so a surface *could* construct `PaneOpened { running: 47 }` and invent a number. That exposure is
identical to `SessionView` already being constructible and is weaker than producer-only
construction would have been. Stated rather than buried.

**`marlowe --tui` drives the real engine, and the object was `Produce for LiveSession`, not
`Produce for Daemon`.** The daemon is a separate process, so implementing the trait on `Daemon`
would have connected nothing. `LiveSession` is the client-side producer: it holds a `SessionView`,
turns `Intent` into `Request`, and folds `Event`s back through `project::apply_events`. The turn
runs on a worker thread with a channel `tick()` drains, because `Client::send` blocks and M2's
first real run spent 155 seconds in one turn.

### Exactly what is live and what is not, on `marlowe --tui`

A partially connected TUI that *looks* connected is the seam problem, so this is stated per region
rather than in aggregate. **Nothing is stub-fed on the live path** — `--tui --scripted` is the only
way to reach the stub, and the active producer is announced at startup and in the band.

| Region | Live path |
|---|---|
| Status band | **Live.** `StatusReport` — workspace, model, disclosure, `degraded`, `rerank_provider`, `live_runs` |
| Conversation | **Live.** User turns, `Event::Text` → `Speech::Model`, tool lines from `Event::Tool` |
| Runs pane | **Live.** `Request::Runs` on connect, then `Event::Run` |
| Control strip | **Live but single-valued** — the daemon runs one model in one workspace; profile/session/autonomy show the floor. Selecting anything else is a named refusal |
| Ambient · pager | **Live, and zero until a turn completes** — both come from `Event::Done`. Zero is the truth, not a placeholder |
| Meter | **Frozen** — `MeterSource::None`. No voice pipeline and no token-rate telemetry, so it reports nothing rather than a synthetic envelope (§B12) |
| Schedule · Sessions · Skills · Trust · Status panes | **Not built**, each saying so with its milestone |
| Approvals | **Refused by name**, below |
| Interrupt · undo · compact · `/state` | **Refused by name** — `IntentError`, rendered as a persistent client line |

**The approval refusal is the one real protocol dependency, and Session E inherits it by name.**
`Event::Approval` carries `{decision, verb, scope, reversible}` — **no novelty reason and no
ceiling**. Both are required by §B9 and neither can be defaulted: a defaulted ceiling is a claim
about promotion logic nobody made. So the live path refuses and *says which fields are missing*,
rather than showing a fabricated blast radius or a silently absent dialog.

**Open, and not this ADR's to close.** `marlowe-permission`'s own `BlastRadius` (`decision.rs`) is
a different shape — `{verb, scope, reversible, novelty}` — with no ceiling and no count. Reconciling
the two is Session E and needs a `DECISIONS.md` entry, because it is the approval layer.
**`decision.rs` is also not covered by the brief §13 hook**, verified by pipe test on 2026-08-09;
see STATE.md.
