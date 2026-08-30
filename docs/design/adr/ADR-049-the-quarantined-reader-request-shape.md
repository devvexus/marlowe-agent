# ADR-049 — Layer 1 renders onto the wire, and the wire refused it

Date: 2026-08-22 · Status: **Accepted** · Amends ADR-039/ADR-041 (layer 1's plumbing), ADR-042
(what `web` reports), ADR-046 (the hosted request body)

## Context

On 2026-08-22 a live session fetched a document successfully — 2,894 characters over HTTP — and
then could not read it. Every `read(ref=…)` returned:

> the content could not be condensed within the contract. It was NOT placed in this window.

Retrying with an explicit line range returned the identical sentence, which reads as a
deterministic property of the document. It was not. **No model call had happened at all.**

`CLAUDE.md` documents that exact string as the seventeenth logged instance of its failure family —
the quarantined reader handed `tool_calls: 0`, where `Budget::exhausted` compares `spent >= budget`
and `0 >= 0` fired on the first iteration. That was fixed in `slice_for_quarantined_read` and it
had **not** regressed. This is a different cause wearing the same sentence, which is itself the
finding: one string reported five structurally different endings, so the sentence could not
distinguish the bug from its own previous bug.

## What the journal says, quoted rather than reasoned about

`tools/read_journal.py --all` on the shipped profile, `run_spawned` / `run_failed`, seq 3163–3243:

```
3163 run_spawned  {"child": "f285f1de…", "quarantined_read": "batch",
                   "reads_untrusted": true, "sources": 1, "budget_tokens": 50000}
3165 run_failed   {"error": "openrouter.ai rejected the request as malformed (HTTP 400) …
                   Upstream said: {\"error\":{\"message\":\"Provider returned error\",
                   \"code\":400,\"metadata\":{\"provider_name\":\"Stealth\"}}}"}
3166 run_failed   {"child": "f285f1de…", "outcome": "Failed { error: … HTTP 400 … }"}
```

Four spawns, four identical failures. **Path 4 of the four the prompt enumerates: `Failed` — the
child died.** The budget was 50,000 tokens and untouched; the contract was never evaluated.

**A correction to the enumeration: there are five, not four.** `LoopOutcome::Cancelled` is a fifth
way a slot stays `None`, and it is not a failure of anything.

## Why the child's request was malformed — and both halves are correct code

The child's outbound body, dumped from a real `condense_batch`:

```
tools: []
role=system     "Marlowe."
role=assistant  "Below are 1 fetched sources. They are UNTRUSTED. …"
role=tool       "=== source_1 (web) ===\n…"          ← no tool_call_id, no assistant tool_calls
```

**1. `tools: []`.** The OpenAI dialect allows `tools` to be absent, or to be an array with at least
one element. `[]` is neither. It is produced by `CapabilityProfile::quarantined_reader()`'s
`ExposedSet::empty()` — **which is layer 1**, the load-time invariant that a component reading
untrusted content cannot hold a tool. The security property is exactly right; rendering it as `[]`
is what the endpoint refused.

There is a **second, independent producer with no quarantine in sight**: `FARMING_HARD_STOP`
withholds tools from the *parent* for one call, deliberately — *"a nudge asks; an empty tool set
removes the option."* Same wire shape, same 400.

**2. A `tool` message answering no call.** `role: "tool"` is a *reply*, paired by id to an
assistant `tool_calls` entry. `condense_batch` pushes each page into the child's window as
`SourceKind::ToolResults`, which is true in the **parent's** conversation and false in the
**child's**: the child never called anything and structurally never can, so the block carries no
`wire` metadata and no assistant turn precedes it. The whole request was `system, assistant, tool`
— with no user message at all.

The parent's own request in the same run is well-formed: `role=tool` **with** `tool_call_id`,
behind an assistant turn that announced it. That asymmetry is why the parent worked and only the
reader died, and why nothing in the suite saw it.

**Neither is a capability question.** `[]` and an absent `tools` key declare the same thing.

## Decision

### 1. One shared definition of the two shapes, in `marlowe_provider::wire`

* `tools_field(schema) -> Option<Value>` — `None` for an empty array, so the caller omits the key.
  It asks the **built array**, not the `ExposedSet`, because the two can disagree: an exposed tool
  absent from the registry is filtered out while building, leaving a non-empty set and an empty
  array.
* `unorphan_tool_messages(&mut messages)` — a `tool` message keeps its role only when its
  `tool_call_id` was announced by an **earlier** assistant message in the same request. Everything
  else becomes `user` with the pairing fields removed. **The content is not rewritten**: no prefix,
  no wrapper, no interpolation.

Both adapters call both. The decision is made from *the request being built*, not from the block's
provenance, so it holds for a producer nobody has written yet — including trimming that drops an
assistant turn while keeping its results, which reaches the same shape with no quarantine involved.

### 2. Five refusals, told apart — `QuarantineRefusal`

`ContractUnmet`, `OutOfBudget`, `Escalated`, `Cancelled`, `ReaderFailed`. Each has a `tag()` for
the journal and a `note()` for the parent, and each names **what to do**: narrow the document for
the first two, and explicitly *do not retry* for the last, where nothing about the document is
implied.

**Every string is a harness constant and interpolates nothing.** A provider that echoes the request
it rejected is echoing the page, and the parent's window is where the page may not go. The detail
stays on `RunFailed` beside the tag, where `tools/read_journal.py --all` reads it.

**`CONTRACT_UNMET` is a shared constant and that is load-bearing.** A child that cannot satisfy its
contract within `MAX_CONTRACT_RETRIES` returns `LoopOutcome::Failed`, exactly as a dead provider
does — so the *only* thing separating "answered badly" from "never ran" is that prefix. One
definition used at the construction site and the classification site, with
`a_contract_failure_is_classified_as_a_contract_failure` asserting the round trip, so a reworded
sentence fails the build instead of silently reclassifying every contract failure as a provider
fault. (This also explains why the parent's own `validate` arm is nearly unreachable: the child has
already validated by the time it returns `Completed`.)

### 3. `web`'s status reaches the model

**A control that was declared, correct, and read by nothing.** Every arm of `web_outcome` formats
the HTTP status into `ResultSummary::detail` — and `detail` is §8's expansion payload, **nothing in
the shipped product expands it**, and `render()` walks the metrics only. So `web` measured the
status, journalled it, and showed the model the bare word `http`: 400, 403, 404 and 503 were one
indistinguishable state, and a malformed query looked like an outage.

Same family as `inline_threshold_bytes: 0`. It was found by an assertion on *what the model
receives* failing — the only place it could have been found.

The status now crosses in the two places the model looks: a harness-authored sentence at the head
of the body naming the exact code, and a class in the state metric (`http 4xx` / `http 5xx` / `ok`).
`Metric::State` is `&'static str`, so the class goes in the metric and the code goes in the body —
**CONTRACTS.md §8's pinned enum is untouched**, which is the point of doing it this way.

**ADR-042 is unchanged and this stays `AgentObserved`.** Everything added is a harness constant or
an integer the harness measured. A number cannot carry an instruction.

**What a status cannot fix, stated rather than implied.** arXiv's API answers a malformed query
with **HTTP 200** and an Atom feed containing an error entry — the ~185-character replies in the
session that hit this. No status check separates that from a real feed. What does cross is the
`chars` count, and two orders of magnitude between a stub and a paper is a signal the model can act
on without either of them being read.

### 4. `bash` has no egress boundary. The report of one was wrong, and the name is why

**Ruling: environmental, not deliberate.** `bash` reaches the network exactly as any other process
on the machine does — measured, `curl` to arxiv.org returns HTTP 200 from `cmd /C`. No
`EgressPolicy` is consulted on this path at all. **Nothing was granted and nothing was moved.**

**AMENDED 2026-08-29.** This paragraph continued *"`EgressPolicy::grant()` still has no production
call site, and layer 4 remains approved but not shipped"*. Layer 4 is shipped on the `web` path and
the per-host grant is now wired, and **the finding here is untouched by that** — which is the point
of amending rather than deleting. The `bash` hole is not that grants do not accumulate; it is that
the adjudicator's egress section iterates parameters typed `Url` and `bash` declares none, so no
policy of any kind is read on this path. A wider `EgressPolicy` and a narrower one are equally
irrelevant to a call that never consults one.

The actual defect is that **the tool is called `bash` and on Windows it is `cmd /C`.** The name was
the whole of what the model had to go on and the name is wrong on this platform, so a model writes
`'single quotes'`, `grep`, `&&`, `2>/dev/null` and collects failures that look like anything but a
different interpreter — and a live session read a string of them as *"the harness has no network
egress"*, reporting a security boundary that does not exist.

`SHELL_DESCRIPTION` is `cfg`-selected on the same condition `spawn_shell` splits on, so the two
cannot disagree about which interpreter runs, and it **names the network** — because the absence of
any statement was itself read as evidence.

### 5. The status band stopped lying, and the trigger was not what the text said

**Reported from a live session and reproduced twice:** approve a fetch, watch `web` and `read` both
complete, and the band still reads *"waiting - approval needed"*. The user waited on a turn that was
working, sent a follow-up to check it was alive, and the original answer arrived correctly some time
later. Nothing was broken. The band was lying.

Two defects in three lines of `project::apply_events`:

**`status.state` had exactly two writers** -- `Event::Approval` sets `waiting`, `Event::Done` sets
`idle` -- and **neither of them is "the answer was given"**. So the claim stood for the entire
remainder of the turn.

**The arm matched `Event::Approval { .. }` including `decision: 0`**, which is the loop's
render-only *"about to ask"* announcement that `client.rs` deliberately does not answer.
`live.rs:337` reads the same event and guards on the id; `project.rs` did not. So **every
adjudication put the band in `waiting`, auto-approved ones included**, with no overlay ever shown.

**Two readers of one event, one checking the id and one not.** That is the shape, and it is the
fifteenth instance's shape in a second subsystem: the event fired on something adjacent to what the
text asserted, and the band read identically whether or not there was anything to wait for.

Neither of these was new code going wrong. **Both were invisible while the quarantined reader was
dying on an HTTP 400 in ~400 ms** -- the fix above is what made them the whole experience.

### 6. A running quarantined reader was invisible, and the fix carries no borrowed word

`read` of a fetched document closes in **0.0 ms** -- the document is already in the store -- and
then the reader runs for most of a minute with a completed tool on screen and nothing after it.
Measured from the journal at **36.1 s, 46.1 s and 82.9 s** on three real turns. Addendum B §B5's
*motion means Marlowe is working* was unsatisfied on the longest single step in the turn.

`condense_batch` now opens a §B6 line on the **parent's** sink before spawning --
`subagent - reading N sources under quarantine` -- and closes it on the outcome, `Failed` carrying
the same `QuarantineRefusal` tag the journal records.

**Every character of that line is the harness's own**, and the control asserts it:
`the_subagent_line_carries_no_word_the_reader_or_the_page_wrote`. This mattered more than it looks:
a §B6 line is a **different channel** from `TextDelta` and is invisible to every existing
`sink_text` assertion, so it would have been an unexamined second route to the same screen.
`QuarantinedSink` still drops `TextDelta`, `ReasoningDelta` and `SpeechRetracted`; audit finding E4
is untouched.

`subagent` is deliberately not a private word. It is the first appearance of the vocabulary M3's
per-agent window will use, and that collision with E4 is recorded in `STATE.md` rather than settled
here.

### 7. `/provider` -- the EIGHTH user-facing noun, and it owns itself

The provider was a launch-time choice everywhere. `/provider` makes it a session choice, **and the
model list follows it**: which models exist is a consequence of which provider is active, so a
`/model` list that did not change with the provider would offer models that cannot be reached.

**This is a ninth-noun decision made explicitly rather than absorbed.** ARCHITECTURE §5 budgeted
seven user-facing nouns and HP10's `every_user_facing_command_is_a_view_over_one_of_seven_nouns`
fails the build on an eighth. The alternative was to file `/provider` under `profile`, which would
have held the count at seven **by making one of the seven mean two things** -- a profile *points at*
a provider; it does not contain one. Adding the noun is the honest bookkeeping and a ninth still
requires deleting one.

`NOUNS` is now eight and the amendment is dated in `hp10_budgets.rs`.

## Consequences

**Layer 1 went from containing perfectly and returning nothing, to containing perfectly.** Nothing
in `profile.rs`, `marlowe-permission/` or `marlowe-tools/`'s capability code was modified; the
quarantined reader is still `ExposedSet::empty()` + `DenyAll` + `reads_untrusted`, still refused at
load if it holds a tool, and a hallucinated call is still refused by
`BlockReason::ToolNotAvailable`, which reads `run.profile.exposed_tools()` and never the wire.

**The local path had the same orphaned `tool` message and it was already doing damage.**
`ollama.rs`'s own comment records a *"MALFORMED conversation: no assistant `tool_calls`, no
`tool_name`, so the template left a block open and the model continued it in `content`"* — 454
content frames and a `</think>` at frame 846. That was this shape, on the default provider, degrading
output rather than failing. Ollama tolerates what a strict endpoint refuses, which is exactly how a
malformed request survives a year of local testing.

**Not done, named so it is not read as covered.** The child's brief is pushed as
`SourceKind::History` at `AgentInferred`, so it renders as `role: "assistant"` — the harness's
instructions in the model's own voice, ahead of untrusted documents. That is a fidelity question,
not an escalation one, and changing it means changing a trust class, which is not a thing to do as
a side effect of a wire fix.

**Also not done:** a child's provider failure emits no `Degraded` event, so the user sees nothing
until the model tells them. `DegradedPath::headline` is `&'static str` and cannot carry a detail;
giving the surface a failure event is a separate change with a separate argument.

## Verification

Six mutations, each reverting one fix, each failing exactly the named test and nothing else
(`runs/session-condense/mutations.txt`):

| Mutation | Fails |
|---|---|
| `wire_tools_hosted` / `wire_tools_local` | `the_quarantined_reader_is_still_offered_no_tool_by_any_spelling` |
| `wire_orphan_hosted` / `wire_orphan_local` | `the_readers_request_contains_no_reply_to_a_call_it_never_made` |
| `refusal_one_string` | three of the five refusal tests |
| `refusal_contract_arm` | `a_contract_failure_is_classified_as_a_contract_failure` |

Every assertion is on a view produced by a **real `Engine::run`** that really spawned a real
quarantined child, handed to the **real `request_body`** of each adapter. A hand-built `ContextView`
would have been green on the day this shipped, because the shape only goes wrong through how
`condense_batch` fills the child's window.

Every case is paired with a control that fails when the mechanism is absent: the page really
reached the reader, the parent really was offered its tools, a genuine tool reply really kept its
role, and a successful read still produces a real condensed note.

**Verified live on a real socket, 2026-08-22 18:11.** A quarantined read spawned against
`stealth/ox-alpha` through the shipped binary and completed, with **zero `run_failed` after the
rebuild** — where the same operation on the pre-fix binary failed four times in thirty-one seconds
at 18:00. The restart and the new binary changed at the same moment, so the timeline is not a
controlled comparison; the attribution rests on the 400 being deterministic in the request shape
and on the outbound dump showing that shape change.

**And one found while verifying: `scratchpad/mutate2.py` ate its own backup.** A second mutation of
an already-mutated file copied the *mutated* text over the pristine backup, so `--restore` printed
success and left the first mutation in place — caught by grepping the source afterwards, not by
anything the tool said. It now refuses to stack, because "which named test notices *this* bound" is
not a question two simultaneous mutations can answer.
