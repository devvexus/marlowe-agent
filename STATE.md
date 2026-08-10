# State

## M2 C2f — the latch met real untrusted content. `561 tests` (from 550).

**ADR-023's four properties confirmed against a genuinely fetched page, and the fourth had never
been exercised by anything.** `cargo test -p marlowe-exec --test adr023_live -- --ignored`.

```
view floor: AgentInferred   run floor: UntrustedContent   pages in view: 0
7 composed shell commands issued, 7 refused, 0 executed
```

The view's floor **rose** as the page fell out of the budget; the run's latched floor did not follow
it up; every composed Target stayed blocked. That is the exact hole the latch was built to close —
the assembler dropping a block to stay inside budget silently handing back privileges — and until
now the only evidence for it was a `Block` a test constructed and labelled itself.

### The latch fired on Marlowe's own name, on every run that has ever run

**Item 1's diagnosis was a fourth candidate: not the trust class at ingest, not the floor
derivation — the ANNOUNCEMENT.** Ingest is right (`read` returns `AgentObserved`), the floor
arithmetic is right, and `adjudicate` blocks at `<= UntrustedContent`. The loop emitted
`Degraded{TrustFloorLatched}` on **any** downward move, and the surface renders that as
*"read untrusted · composed targets blocked"*.

A run starts at `UserAsserted`. The assembler constructs the stable tier on every assemble and the
`Identity` block — the string `"Marlowe."` — is `AgentObserved`. **So the floor moved on the first
assemble of every run, before the model spoke and before any tool ran**, and the first assistant
turn (`AgentInferred`) moved it again. The negative control reads `left: 2, right: 0`: the product
printed the banner **twice**, on a run with no tools at all, with both clauses false.

**The capability-report family, once more.** The event fired on *floor moved*; the text asserted
*floor reached untrusted*; the banner read the same either way, so it was never evidence about the
guard. A latch that fires on everything means nothing — which is the state it must not have been in
when `web` made it live.

`marlowe_permission::blocks_composed_targets` is now the single definition, called by
`adjudicate.rs` at its enforcement site **and** by the loop to decide whether to announce. The
journal still records every move; only the screen is gated. Three tests, one asserting the
agreement across all four trust classes rather than either half.

### `web` ships, fetch-only. ADR-031, ADR-032.

**`marlowe-net` is a new crate depending on nothing of Marlowe's** — `rustls` + vendored
`webpki-roots`, blocking, no async runtime. `marlowe-provider` still has no TLS, so ADR-028's
"the default path reaches no network" stays a property rather than a comment.

**Redirects are not followed, and ADR-031 §2.5 was amended during implementation to say so.** The
first draft said *"followed, re-adjudicated per hop"*; writing the executor showed that means **a
second implementation of the egress check**, in a networking call site, checked against a policy
the executor had to be handed. The shipped shape is smaller and stronger: the `Location` comes back
as a result and following it needs a fresh `web` call through the real adjudicator. The cost is
real — after reading a page the latch blocks composed targets, so a redirect is usually a dead end.
That is the trifecta break, not a defect.

**The fetch primitive returns bytes + content-type and does not parse.** Extraction is a separate
module and a separate session, deliberately: an extractor that panics must not take the egress path
with it.

### The blast radius was dropping targets it could not stringify

`blast_radius` built the scope line with `as_text`, which returns `None` for every variant but
`Text`. **A declared Target that was a number vanished from the line a human approves against** —
`run.budget_micros_usd` is `Amount`, so §B9's required blast radius had never once shown a spend
ceiling. `ArgValue::render` is total with no wildcard, so a new variant is a compile error here
rather than an omission in an approval prompt.

This was done **before** `web` could ship, not beside it: ADR-002 lets `web` be `Inert` only because
egress allowlisting covers it, approve-any-host weakens that, and per-call approval replaces it only
if the prompt shows the host.

### Persona v2 — adopted from a prior harness, translated. ADR-033.

`persona/v2.md` ships. **Cut, because they described tools that do not exist:** `<vision>` (which
instructed the model to *"never say I can't see"*), `<redteam_routing>`, `<git>`, the search half of
`<knowledge_and_search>`, most of `<memory_and_continuity>`.

**The dangerous one was not a cut.** `<tool_use>`'s first rule was *"emit multiple independent tool
calls in a single response"*. `parse_step` does `calls.first()` and **discards the rest silently** —
worse than a missing tool, which at least returns a readable error. v2 says one call per turn.

**~3,544 tokens against v1's ~409 — 11.5% of the effective window**, permanently, in the
non-trimmable stable tier. §C0's *"roughly twenty lines … negligible"* is amended.

**§C7's probe set does not exist and never has**, for v1 or v2. Adoption rests on "it performed well
in a prior harness", which is a prior about a different system. §C7 amended to say so.

### Still open

- ~~**PARALLEL TOOL CALLS**~~ — **DONE.** `ModelStep::ToolCall` carries `Vec<ToolInvocation>`; the
  loop executes every call; each result is attributed by a harness-assigned id reaching
  `/api/chat` as `tool_calls[].id` and `tool_call_id`. `persona/v2.md` reverted in the same commit.
  Three states, in order, and the middle one is worth remembering: **silent drop → loud refusal →
  real support.** Refusing to run a third of a plan beats running a third and reporting nothing.
  **Taint is computed once per batch and that is correct rather than cheap** — every call was
  composed before any sibling's result existed, so a per-call recomputation would block a call on
  content its author never saw. The latch is not holed by ordering: the batch's results latch the
  floor before the *next* adjudication. Both halves asserted in one test, because either alone
  passes on a broken build in the opposite direction.
  **One judgement call to review:** a control tool (`done`/`ask`/`run`) inside a multi-call batch
  takes precedence and returns its control step, since it ends or reshapes the run. Not a silent
  drop, but a semantic choice nobody ratified.
- **`interactive()` is still `EgressPolicy::DenyAll`**, so `web` has an executor and is not exposed.
  ADR-032 §3.1 (`AllowApproved`) is **PROPOSED, not approved** — it needs the human, and it needs an
  interactive approval surface the daemon does not have (`DenyUnattended` returns false, which is
  why `bash` reads `declined` unconditionally).
- **Search is RESOLVED and needs no credential: self-hosted SearXNG. ADR-035.** The keyed-API note
  that was here is superseded — the keyed landscape is *contracting* (Bing API deprecated Aug 2025,
  Google CSE closed to new customers and discontinued 1 Jan 2027, Brave requires a card), so a keyed
  backend builds on shrinking supply and fails K6 by construction.
  **The registry has no credential concept at all** (ADR-036 §2) — not a default-off flag, no field:
  a channel that needs a key cannot be *described*, so it cannot be registered. Stronger than a
  load-time error, because a field that exists is a field a future session fills in.
  `web`'s description still promises search and is corrected when search lands.
- **DESIGN ONLY, NOT BUILT — the research stack. ADR-035, ADR-036, ADR-037. M3 owns it and durable
  runs are its precondition.** Brief §10 and ADR-008 are amended. The three things to read before
  proposing anything here: **deduplication is over identity, not route** (a Source has N routes; a
  derived work is an *edge*, never a merge; corroboration counts **independent roots**);
  **`Unresolved` counts as one and displays as two**, because under-merging manufactures
  corroboration invisibly while over-merging is visible; and **an identifier self-asserted by
  fetched content is a claim, not an identity** (ADR-036 §5) — otherwise a page printing a real DOI
  merges into that paper and inherits its standing.
- **A SECURITY PRINCIPLE GENERALIZED FOR THE FIRST TIME, and the generalization is unexplored.**
  ADR-036 §5. ADR-023's (action, target) split has always been about tool arguments — a path, a
  host, a command. Deduplication has **no tool, no argument and no permission check anywhere near
  it**, and the rule holds anyway, because the property was never about tools: it is about *who
  chose the thing that determines an outcome*. Note that the taint latch cannot help here — every
  route is `UntrustedContent`, so the floor is already at the bottom and stops discriminating.
  **Named as a generalization rather than a fifth instance, and the same shape is unexamined in at
  least four places**: ranking inputs, cache keys, memory derivation lineage, and consolidation
  merge decisions.
- **Two ADRs carry INDICATIVE figures that must not become load-bearing.** ADR-035's keyed-API
  dates and ADR-037's Gemini/Anthropic token costs came from the human's research and **were not
  re-verified by either party**. Both are marked in place. They are order-of-magnitude calibration;
  no threshold, budget default or acceptance criterion derives from them, and a session budgeting
  against them measures first.
- **`drop(cwd)` in `marlowe-exec`'s `bash` does nothing** — `Option<&ScopedPath>` is `Copy`, so the
  line that claims to hold the handle until after the spawn is decorative. The handle is genuinely
  held (by the `Adjudication`), so this is a false comment rather than a broken guard. Compiler
  warns.
- **The duplicate `ADR-028` in DECISIONS.md is flagged, not renumbered** — citations across
  STATE.md, CLAUDE.md and eight RESULT.md files would break.
- **§C1's namesake conflict is unresolved**: Chandler's detective (restraint) vs Christopher
  Marlowe the poet (transgression). v2 names neither; §C8 forbids backstory.

### One §13 row is now LIVE-verified rather than pipe-verified

Editing `crates/marlowe-permission/src/adjudicate.rs` **produced a real permission prompt, which
the human approved.** That is the stronger claim CLAUDE.md asks for and it now holds for exactly
one row. Every other row remains pipe-verified; one observed prompt says nothing about the others.


## M2 C2e addendum - five defects, every one reported from use. `550 tests`.

**Found by using it, in one sitting, after the milestone work was already committed.** Two of
them were defects in fixes made earlier the same day. None was caught by a test.

| # | Defect | How it presented |
|---|---|---|
| 1 | The user's words and the model's reasoning shared a foreground weight | *"user messages are indistinguishable colour-wise from thinking"* |
| 2 | No shutdown path existed at all | a closed window left a daemon that the next launch silently reconnected to |
| 3 | A reconnecting client rendered an empty transcript | looked like memory working, because the daemon never died |
| 4 | Replay dropped thinking blocks and tool detail | the conversation came back, the work behind it did not |
| 5 | Closing mid-turn destroyed the conversation | reopening answered `<tool_code>none</tool_code>` |


### There was only ever ONE conversation, and the screen did not show it

Found by the human, and it explains something that had been read as working memory: *"I closed
the window after each conversation but he remembered in the next one. Like I never closed it at
all."*

He had not. Three facts compounding:

1. **The window is not the session.** The daemon owns it and outlives the client. Closing the TUI
   closed a client; the daemon kept listening with the conversation intact.
2. **Every TUI connects under the same name.** `LiveSession::connecting("tui", port)` means one
   fixed session key, so every window mapped to the *same* session. Turn 1 of the "second"
   conversation was turn 40 of the only one there had ever been.
3. **A reconnecting client rendered nothing.** Its view came from `view_from_status`, which fills
   the control strip and the band and leaves `transcript: Vec::new()`. There was no replay op at
   all - `Request` had `Status`, `Ask`, `Runs`, `Approve`.

So the screen showed an empty transcript in front of a live conversation, and Marlowe answered
from context the user could not see. **The screen and the model disagreed, and the screen was the
one telling the truth about what would be displayed.**

`Request::Replay { session }` now re-sends the session's turns as ordinary render-only frames, and
`LiveSession::finish_connect` applies them. §2.14 still holds: the client re-projects what the
daemon owns rather than taking custody of it - which is why this is a replay of `Event`s and not a
frame carrying a transcript, a shape `protocol.rs` has a standing test against.

`Event::User { text }` had to be added: a live client appends its own user turn locally, so the
wire had never needed to express "the person said this". Without it a replayed conversation would
have been Marlowe talking to nobody.

Verified live across two turns and a reconnect:

```
user    'My favourite colour is green. Just acknowledge.'
marlowe 'Acknowledged: green.'
user    'What colour did I say? Colour only.'
marlowe 'Green'
```

**What this does NOT fix, and it is the more important half.** Nothing is persisted. The session
store is a `BTreeMap` on `Daemon`; with shutdown-on-close now landed, closing the window ends the
conversation for real. Replay only helps while a daemon outlives a window - a manual `--serve`, or
a second client. **Durable conversations across restarts are unbuilt.**

### Closing the window MID-TURN destroyed the conversation

Reported as: reasoning was in progress, the window was closed, and on reopening the reply was
`<tool_code>none</tool_code>`. *"This only happened when closing him mid reason."*

**The daemon is serial.** A shutdown request sent during a turn waits in the accept backlog until
that turn finishes - and by then the run is marked complete, so the daemon's own *"refuse while a
run is live"* check inspects a run table that is already quiet and **always agrees to stop**. The
guard could never fire. The turn completed, the daemon exited, and the conversation went with it.
Reopening produced a fresh session, and a first turn with no grounding produced the artifact.

Reproduced directly: hang up three reasoning deltas into a turn, send shutdown, and the daemon
finishes the turn and stops.

**The client is the only party that knows.** `tui.rs` now reads `session.is_busy()` before the
teardown and does not send shutdown when a turn was in flight. That is what honouring invariant 6
looks like from the client side: work that was running keeps running, and the conversation is
there on the way back in.

Verified end to end:

```
closed the window 3 reasoning deltas in
daemon ALIVE - the run survived its client
user    'Think carefully then tell me what 17*23 is.'
think   495 chars
marlowe '391.'
```

**One wrong guess on the way, recorded because the method matters.** The first hypothesis was that
adding `thinking` to assistant tool-call turns had broken the template - a plausible story, since
an empty assistant turn carrying only `thinking` had been measured earlier as making the model
return nothing. Measured instead of assumed: both shapes answer correctly. The change was innocent
and the real cause was elsewhere.

**Replay now reconstructs the whole turn, not a summary of it.** The first version emitted prose
and a bare tool verb, so a reopened window lost every thinking block and every tool line's target
and result. `WireTurn` carries `tool_summary` and `tool_failed`; `Engine::tool_call` stores each
model call's reasoning on the assistant turn that made it, so a multi-step turn keeps every
thinking block rather than only the last one. Ordering needs no buffering: an assistant turn is
pushed before the result it produced, so reasoning precedes its tool line exactly as it did live.

### Still open from this

- **`<tool_code>` is a leaked tool call we do not recover.** `recover_leaked_call` handles
  `<function=...>` only. A model emitting some other syntax renders it as prose.
- **The daemon serves one request at a time.** A second client cannot attach to a turn already in
  flight - reopening mid-turn shows the conversation up to the last completed turn and then waits.
  Live attach needs concurrency in the accept loop.

### The two fixes reported earlier in the same session

### The user's own words rendered at the same weight as the model's reasoning

Reported as *"user messages are indistinguishable colour-wise from thinking/reasoning."*

`Entry::User` rendered with `theme.dim()` - foreground weight 2, which is the weight the
reasoning block uses. A question the user typed and a chain of thought they did not write were the
same colour.

**The theme had already stated the intended scheme and the renderer contradicted it.** `speech`'s
own doc comment in `marlowe-surface/src/theme.rs` reads: *"The user's words stay in the terminal's
foreground (weight 1) and Marlowe's take this, which is the one place in the design where colour
marks WHO is speaking rather than state."* Nothing caught it because every colour in use was a
legitimate colour - the defect was two roles sharing one.

Three speakers now hold three weights:

| Who | Style |
|---|---|
| The user | weight 1, the terminal's own foreground |
| The model's reasoning | weight 2, `theme.dim()` |
| Marlowe's voice | `theme.speech()`, the accent tinted toward white |

Guarded by `b13_rendering.rs::the_user_the_reasoning_and_marlowe_do_not_share_a_colour`, which
reads the foreground of the rendered cells rather than inspecting the style the code asked for.

### The daemon could not be stopped

Reported as *"make closing the window shutdown the daemon. Otherwise I cant ever close the
daemon."*

There was no shutdown path at all - `Request` had `Status`, `Ask`, `Runs` and `Approve`. Closing
the TUI left the daemon listening, and the next launch reconnected to it, so a rebuilt binary was
never the one being exercised. **That happened three times in this session**: a fix was reported as
not working, twice, because the running daemon predated it.

`Request::Shutdown` now exists, `Client::shutdown()` sends it, and the TUI sends it on exit after
leaving the alternate screen.

**Invariant 6 is unchanged and this is not a weakening of it.** The invariant says a RUN survives
the client that started it; it does not say the daemon is immortal. The daemon **refuses to stop
while a run is in flight** and says how many are holding it. An idle daemon protects nothing and
was only ever in the way.

**One defect in the first version of this, found by checking rather than by reading.** Setting the
flag was not enough: `listener.incoming()` blocks, and the loop only tested the flag at the top of
the next iteration - so the daemon replied `{"outcome":"shutdown"}` and kept listening for a
connection that would never come. The reply was correct and the process was still there. The check
now also runs after serving a request, and the fix was verified by reconnecting afterwards rather
than by trusting the reply:

```
reply: {"event":"done","outcome":"shutdown",...}
connect after shutdown: refused - daemon stopped
```


### NEXT SESSION - past sessions in the TUI

The control strip already has the affordance and it is a stub: `project.rs` builds
`session: Picker::new(&["cli"], 0)`, one hardcoded option, with the comment that session switching
*"has no producer until M2 D and M3"*. `LiveSession::apply` refuses `Intent::Select` for anything
that is not the one live value.

Making it real is three pieces, in order:

1. **Persist sessions.** The journal exists and is signed; the session store is not written to it.
   Until a conversation survives a process, a picker lists things that are already gone.
2. **A `Request::Sessions` op** so the daemon can enumerate what it has, and the picker can be
   built from the answer rather than from a literal.
3. **Switching.** `Intent::Select { control: Session, .. }` starts replaying the chosen one - the
   `Replay` op above is already the mechanism, so this is the small piece once 1 and 2 exist.

Note that (1) overlaps M2 D's durable-memory work and should not be built twice.

## M2 C2e - the agent loop is honest about what it sends and what it shows. `2be2179`.

**542 tests. `cargo build --release` clean. Seven commits, and not one of these defects was found
by a test.** Every one was live-reproduced, and every fix verified against the running process
rather than against a body built in a test process.

### The one that explains most of the others

**The conversation sent to `/api/chat` was lossy in five ways, and they compounded.** Found by
fixing the instrument first: `--dev`'s outbound dump printed only the system tier, so the shape of
the conversation - the part deciding whether the model can see its own tool calls - was the one
thing it could not show.

```
[ 4] user       52 chars  tool_calls=0  tool_name=""
[ 5] tool       54 chars  tool_calls=0  tool_name=""  "983 lines - 69630 B - ref 225bfe8df7"
[ 6] tool       54 chars  tool_calls=0  tool_name=""  "983 lines - 69630 B - ref 225bfe8df7"
[ 9] assistant 1215 chars  "[your prior reasoning]\nThe user wants me to read..."
```

1. **No assistant message carried `tool_calls`.** A tool result appeared with nothing that produced
   it. Measured against the live endpoint: given that shape the model **abandons the task and
   narrates**; given the documented shape it **acts on the result**.
2. **No `tool_name`.** Five identical results, no way to tell them apart.
3. **The model never received the file.** `read` returned a hash for a 69 KB file and `read` has no
   parameter accepting one, so it called `read` five times chasing the same hash. `ToolOutcome` now
   carries a head/tail preview with the omission stated in words.
4. **Reasoning was replayed as text prefixed `[your prior reasoning]` - and the model imitated the
   marker.** The first leak reported this session contained `[your reasoning continues]`, a string
   that appears **nowhere in this repository**. Two tool calls were spent hunting it.
5. **Sliding-window reasoning**: only the newest assistant turn keeps `thinking`. Older reasoning
   compounds - three turns of "let me check one more thing" replayed together read as a standing
   instruction to keep checking.

**After: one read instead of five, correct answer, 3.4 s.**

### The `</think>` on the user's screen - three attempts, two of them my own bugs

| Attempt | What it did | Why it was wrong |
|---|---|---|
| 1 | Split the tags out of `content`, retract late | The retraction fired and the **projection ignored it** - it checked `transcript.last()`, found the reasoning block the provider had just created, and no-opped. The leak stayed on screen with a verbatim copy underneath |
| 2 | Provider stops re-sending; projection **searches** for the outstanding speech | Correct, but still showed purple text before taking it back - which the rule forbids |
| 3 | **Hold**: content never renders as speech until the block is known shut | Correct, and it stopped the reply streaming |

**The measurement that settled it.** `--dev` on an 848-frame turn: `<think>` **never appears on the
wire** (the chat template emits it), the closing tag arrived at frame **846**, and the whole answer
was frame 847 - seven bytes. That is why "start Outside and look for an open" could never work.

**Then fixing the wire shape changed the measurement.** Ollama began parsing the block itself:
`native_thinking=450B, content=31B, close_tag_in_content=false`. No closing tag ever arrives, so
the hold never resolved and the reply came out in one lump. **Resolved rule: a `thinking` delta
means the provider is separating the channels, so `content` is outside the block and streams.**
Verified live - 9 text events, ~30 ms apart.

### Fifth instance of the `done` defect, closed structurally

`web`, `recall` and `use` were exposed against a host with arms for **four** tools. Every call
returned `has no executor in this build` - a failure the model cannot interpret. `done` was the
first instance and cost a run 155 seconds.

`marlowe_loop::verify_every_exposed_tool_is_runnable` now refuses at **load time**;
`ToolHost::executes` is required with **no default**, because a permissive default is the thing it
exists to prevent. `interactive()` exposes **seven** - four executable builtins plus the three
loop-control tools. **Registered is still ten; the gap is the honest statement of what is built.**

### Other defects closed

- **No conversation history at all.** `ask_streaming` built a fresh `SessionState` on **every**
  request, so every turn was turn 1. The session *id* was stable, which is exactly why it was
  invisible - everything downstream was correctly keyed to a session nobody stored.
- **The system prompt told the model to call `done`**, long after `done` was removed. Found in the
  outbound dump. Guarded by a test **with a negative control**, because the new prompt has no
  backticks and the obvious assertion would have been vacuous.
- **A refused tool call emitted no section-B6 line.** Both refusal paths returned before the emit,
  so a run that tried three times and was refused three times rendered as one that never tried.
- **`think` is a declared setting** (`--no-thinking`), never inherited from the provider.

### Three lessons this session earned, stated for the next one

1. **A test used an event order the provider never produces.** `Text, Text, SpeechRetracted` - a
   real turn interleaves reasoning deltas and tool lines in between. The projection passed the test
   and failed on screen. *A test of a consumer must replay the producer's actual output.*
2. **A guard whose subject has no instances is vacuous.** The prompt-tool guard scanned backticked
   words; the new prompt has none, so it passed over an empty list. It now has a negative control
   pinned to the exact string that shipped broken.
3. **`--ask` has no `--daemon-port`.** A memory test ran two `--ask` commands against a running
   daemon, both said "no colour yet", and the fix was nearly reported broken. That was measuring
   the CLI's connection behaviour and reading it as a property of the session store.


## M2 C2d — `marlowe --tui` drives the real engine. ADR-030. `9f51476`.

**494 cargo tests (from 457), `eval/` untouched at 72, `repro` byte-identical to the pre-change
baseline, conformance unchanged.** Two commits: `5fbd513` (view models) and `9f51476` (the live
TUI plus the Notice vocabulary).

**Launch it:** the desktop shortcut `Marlowe.lnk` → `wt -p "Marlowe"` → `marlowe --tui --ground`.
Recreate with `marlowe --launch` (writes the Windows Terminal profile) plus the `WScript.Shell`
snippet in this session's log. **M1's claim that a `Marlowe.lnk` already existed was false** —
there was no shortcut and no code for one, the same shape as the "hooks are the real boundary"
claim CLAUDE.md records. It exists now.

> ### THE MOST IMPORTANT FINDING: A GREEN PROBE BESIDE A HUNG PRODUCT
> The auto-spawned daemon **inherited the parent's console**. `--timing-probe` returned healthy in
> **56 ms** while every shell pipeline that launched it hung **forever** — the process that
> finished could not say so, because a child holding the console open means the pipe never closes.
>
> **Nulling stdio is not enough; the console handle is the thing.** Fixed with `DETACHED_PROCESS |
> CREATE_NEW_PROCESS_GROUP`. It would have fired on the **first click of the shortcut**.
>
> **Fourth seam this project has found by running rather than testing** — scroll and `NO_COLOR`
> (M1), `done` routing (M2 C2c), the hotkey collisions and this (C2d). The standing rule of one
> real end-to-end run per milestone is now four for four, and every one of them produced a defect
> no unit test could see.

**The other run-only finding, same session.** The daemon projection gave the Schedule pane hotkey
`'s'` — the Session region's key — and numbered run items with digits that collide with §B7's tab
digits. `KeyRegistry::build` refused to start, correctly. **No test had ever projected a daemon
view into a key registry**, so both were invisible. Both fixed; `project.rs`'s `key_tests` now
crosses that seam.

### Process isolation is a standing constraint, and `--daemon-port` is the mechanism

**Two sessions on one machine share `DEFAULT_DAEMON_PORT` — the shared-resource hazard in a fifth
form.** The reflex when a daemon is in the way is to stop it, and that takes the other session's
daemon with it. This session did exactly that once, with a blanket `Stop-Process`, before the
constraint was named.

**Anything needing a clean daemon uses a scratch port**: `marlowe --tui --daemon-port 11477` and
`marlowe --serve --daemon-port 11477`. Auto-spawn was verified that way — the other session's
daemon on 11435 was never touched, and the check that proves it is a listener count on both ports
before and after.

**A daemon restart is lossless when VERIFIED, not by default.** Before stopping one, ask it:
`marlowe --status` reports `runs N live`. A restart costs exactly the in-flight runs — there is no
WAL and no checkpoint resume (M3/K5) — so **zero live runs makes a restart provably free, and any
other number makes it a decision.** Checking first is the standing procedure; assuming is how a
session loses someone's work.

### What is live on `--tui`, per region

**Nothing is stub-fed on the live path.** `--tui --scripted` is the only route to M1's stub, and
the active producer is announced at startup. A partially connected TUI that *looks* connected is
the seam problem, so this is stated per region rather than in aggregate.

| Region | Live path |
|---|---|
| Status band | **Live** — `StatusReport`: workspace, model, disclosure, `degraded`, `rerank_provider`, `live_runs` |
| Conversation | **Live** — user turns, `Event::Text` → `Speech::Model`, tool lines from `Event::Tool` |
| Runs pane | **Live** — `Request::Runs` on connect, then `Event::Run` |
| Control strip | **Live, single-valued** — one model, one workspace; anything else is a named refusal |
| Ambient · pager | **Live, zero until a turn completes** — both from `Event::Done`. Zero is the truth |
| Meter | **Frozen** — `MeterSource::None`; no voice pipeline, no token-rate telemetry, so it reports nothing rather than a synthetic envelope (§B12) |
| Schedule · Sessions · Skills · Trust · Status panes | **Not built**, each saying so with its milestone |
| Approvals | **Refused by name** — see below |
| Interrupt · undo · compact · `/state` | **Refused by name**, rendered as a persistent client line |

**Measured:** first frame **7 ms** connected, **52 ms** degraded, **134 ms** including an
auto-spawn — all under K4's 150 ms.

**The one real protocol dependency, and Session E inherits it by name.** `Event::Approval` carries
`{decision, verb, scope, reversible}` — **no novelty reason and no ceiling.** §B9 requires both,
and neither can be defaulted: a defaulted ceiling is a claim about promotion logic nobody made. The
live path refuses and **names the missing fields** rather than showing a fabricated blast radius.

### ADR-030 — harness speech is a closed vocabulary

`Entry::Said` carries `Speech::{Model(String), Harness(Notice)}`. Six `Notice` variants; **no field
may be a `String`** (an `Echo` newtype carries text the user typed, quoted, never reworded).
`/help` and command errors are **surface-constructed on purpose** — routing them through a producer
would make `/help` a socket round-trip, and a help command that waits is worse than one in the
wrong voice. Nothing in `Notice` can reach a model.

**§B9's `BlastRadius` is typed the same way.** M1's overlay was **scaffolding**: the renderer was
already clean, but nothing could *compute* its three strings. `novelty` and `ceiling` are required
fields, not `Option`s.

> **A control that only catches what the compiler already catches is testing nothing.** Verifying
> the no-`String` guard took three attempts: two mutations failed to *compile*, so the control
> never ran and the guard merely looked silent. The scanner's whole value is the case that
> compiles — a new variant carrying a `String`. **Ask of any control: would this still fail if the
> guard were deleted?** If it would fail earlier, it is measuring the compiler. ADR-030 §5a.

**Not covered by the hook, measured not assumed (2026-08-09):** `crates/marlowe-permission/src/decision.rs`
defines `BlastRadius` and `Outcome::NeedsApproval` — the approval layer's decision surface — and
**returns no decision from `protect-boundaries.py`.** `adjudicate.rs` fires correctly; this file
does not. Adding it is a §13 change and needs the human's call.

---

## M2 C2d — the view models are promoted, and §2.14 is structural rather than asserted

**473 cargo tests (from 457), `eval/` untouched at 72, `repro` hash byte-identical to the
pre-change baseline (`e796c12e…`), conformance unchanged.** Branch `master`.

**`marlowe-view` is a new crate depending on nothing.** `SessionView`, `Intent`, `Produce`,
`MeterSource`, and the M1 view models. `marlowe-surface` depends on it and on **no producer** —
`marlowe-stub` is a dev-dependency, so `src/` cannot name one. That is the acceptance, it is
checked by `tests/c2d_boundary.rs`, and a **negative control** confirms it is not decorative:
putting `marlowe-stub` back into `[dependencies]` fails the test by name.

**Two producers now exist**, which is what makes this a promotion rather than a rename: the
scripted `marlowe-stub::Session`, and `marlowe-daemon::project` mapping `StatusReport`/`Event`
onto the same view without the view being bent to fit.

> ### THE HEADER CLAIM WAS FALSE, AND HAD BEEN SINCE M1
> Both `marlowe-surface/src/lib.rs` and `marlowe-stub/src/model.rs` said the dependency graph made
> §2.14 structural — *"a surface that cannot fabricate state is a surface that provably holds no
> state the daemon lacks."* **`App` owned a `marlowe_stub::Session` mutably and pushed into its
> transcript.** In-process against a stub that is invisible; against a daemon on a socket it is a
> surface inventing history. **Eleven sites, listed below.** The claim is now true.

**The one that would have been worst in production:** arrow keys inside an open dropdown assigned
`Picker::selected` directly, so **arrowing past `act` in the Autonomy list granted `act` in
passing**, and `Esc` left it there. Addendum A §A8 makes self-granted promotion structurally
impossible — and the surface was doing it on a keystroke that was never a choice. The highlight is
now `App::picker_cursor` and `Enter` is what asks.

**`App::on_key` no longer takes a clock, and that is a result rather than a tidy-up.** Every branch
used to end in a mutation, and a mutation needs a timestamp; they now end in an `Intent` and the
producer stamps its own time, because the producer is the thing with a journal. Six dead `now_ms`
parameters were removed rather than silenced.

**`MeterSource` is a new distinction the M1 shape could not express.** `BASELINE` means *live and
flat*; `MeterSource::None` means *nothing is measuring*. The daemon has no voice pipeline and no
token-rate telemetry, so it reports `None` and the meter freezes — it does **not** report
`BASELINE`, which would render as a live silent session, a claim made by a component that cannot
know it. §B12 forbids decorative motion and a synthetic envelope on the daemon path would be that.

**Optimistic state is allowed and never becomes history.** `PendingLine` renders what the user
typed before acknowledgement, in its own weight, with **no transition into `Entry`** — there is no
`confirm()`. It is retired only by the producer's transcript containing it. If the producer never
acknowledges, **it stays visibly pending indefinitely**, which is the truth.

### Two guards fired or were closed during this work

1. **`b13_memory_surface.rs`'s §B1 guard names `turn.rs` by path, and I moved it.** It failed
   loudly because it reads with `.expect`. The same check written with `unwrap_or_default()` would
   have scanned nothing, found no memory variants, and passed forever.
2. **`determinism_guard.rs`'s `FENCES` had no staleness check** — a fence naming a deleted file
   left a silent exemption ready to excuse the next file to take that name. `protect-boundaries.py`
   grew `--self-check` for this after Session B; this guard never did. **Now closed**, verified by
   a control (a bogus fence entry fails by name). A separate `NAMES_BUT_DOES_NOT_READ` list keeps
   *"legitimately reads a clock"* and *"mentions the word"* from being conflated.

**LATENT, NOT FIXED — outside C2d, flagged rather than touched.** `marlowe-loop/tests/hp10_budgets.rs:37`:
`let Ok(entries) = read_dir(dir) else { return out };` returns **empty** on a missing directory.
It is saved only because the caller asserts `found.len() == 1`. Relax that to `<= 1` — which reads
entirely natural — and the driving-loop guard scans a directory that is not there and passes forever.

### Deferred, and named rather than improvised

**`Outcome::Tab(tab, said)` still carries Marlowe-voiced prose hardcoded in the surface's command
registry** — *"Two running. The deep dive is at $1.20 of its $3 ceiling."* C2d stopped it
masquerading as transcript (it renders as a `ClientLine` now), which is **more honest about
authorship but leaves persona-voiced text in the client channel**. Fixing it properly needs a
producer-side command handler, which is **C3**. It is not an intent nobody handles — it renders
today — but it is not right either.

`/help`, `/keys` and `/doctor` are **not** part of that debt: they describe the *client*, so the
client authoring them is correct. They were only ever wrong in being attributed to Marlowe.

**Also deferred, unchanged:** `TurnEvent` still exists twice (`marlowe-loop` and `marlowe-view`),
and the two `BlastRadius` shapes are still unreconciled — both are **Session E** per the entry
below, and C2d deliberately did not absorb them. `marlowe --tui` still drives the scripted
producer; pointing it at the daemon is Session E's "the TUI against the real loop".

### The 15.2 GiB of stale `target/`, and the latency session

**The repo moved out of OneDrive** — from `C:\Users\matth\OneDrive\Desktop\Projects\Marlowe_Harness`
to `C:\Users\matth\Projects\Marlowe_Harness` — and `target/` still held test binaries compiled at
the old path, with `CARGO_MANIFEST_DIR` baked in. Under `--workspace` feature unification cargo
reused three of them and `hp10_budgets` failed against a path that no longer exists; `-p marlowe-loop`
recompiled and passed. **15.2 GiB removed by `cargo clean --profile dev`.**

**This is a candidate explanation for Session L's unexplained write times** — the 542 ms stall
inside one timed span, and the cold p50 drift 208.4 → 267.0 ms on the same binary in the same
configuration. Session L attributed those to OneDrive's delete-share locks on fresh binaries, which
was a reasonable read at the time and is now untestable on this machine. **It is a hypothesis, not
a finding: nothing has been re-measured, and Session L's numbers are still scoped to a machine
state that no longer exists.** Re-measuring the CPU path here would need a fresh control run, not a
citation.

---

## M0c Session L — retrieval latency. GPU ships (ADR-029). R@1 UNMOVED at 0.6725.

**`runs/session-l/RESULT.md`. Read `METHOD.md` before trusting any number in it.**

| path | total p50 | total p95 | budget 300 ms |
|---|---|---|---|
| **CPU sequential 1t** — ships where no GPU exists | 199.6 | ~213 | 87 ms headroom |
| **CUDA batched** — ships where one does | **10.0** | **14.7** | 285 ms headroom |

**Two changes ship.** The **lexical rewrite** (both paths, byte-identical, `score_all` stage
14.76 → 3.07 ms cold, −79%) and the **GPU path** (ADR-029). Quality is unmoved: CPU dumps
byte-identical to Session K; GPU **ranking-identical** — R@1 0.6725, R@5 0.8865, R@10 0.9039.

**The profile, which is the thing to inherit:** on CPU the rerank is **90.49% of P95**. Everything
else combined is under 10%. Any latency work that is not about the rerank is rounding.

**Measured and REJECTED, all ranking-identical, all cost findings:** batching on CPU (+8.8 ms),
threading at 16 intra-op threads (**+158.9 ms** — the model is too small to amortize ORT's per-op
sync), batching at 16t (better than sequential-16t, still worse than 1t). **`SHIPPED_THREADS = 1`
is now measured rather than assumed.**

**Batching is a property of the HARDWARE and the two providers measured opposite** — CPU sequential,
CUDA batched. `RerankProvider::default_batching()` derives it; a single global default would be
wrong for one provider whichever value it took.

> **ADR-003 is AMENDED.** The hot index is a **capacity** requirement, not a latency one: the
> candidate scan is the only **O(store)** stage and costs **3.83 ms / 1.78%** at 113k entries. The
> spike's 94.9 → 16.2 ms measured a *physical storage index under concurrent writes*, not the
> in-memory iteration retrieval does — a factor of ~25 apart. **On the GPU path it is 19.6% and
> moves back toward a latency claim.** Third change of classification on measurement; re-derive, do
> not assume.

**OPEN for M2 (in ADR-029, so it is inherited rather than re-derived):** the active provider is
**announced**, never silently chosen — an unannounced fallback is indistinguishable from the failure
mode it resembles. Voice on a CPU-only machine states its budget consumption **at enable time**
(retrieval is ~27% of §9's 800 ms). **`rerank_provider` on the profile row is THE field the band
reads — do not build a second source.**

**OPEN GAP:** `ort` exposes no node enumeration, so the shipped binary cannot re-verify that 13.6%
of CUDA nodes run on CPU (all shape/index ops, no matmuls). Verified once, in Python, at ORT 1.24.2.
**Re-run `tools/session_l_gpu_recovery.py` after any graph, model or ORT change.**

> ### THE BUDGET IS TIGHTER THAN THE CLEAN NUMBERS SUGGEST
> Machine drift on this box moved the **same binary in the same configuration** across cold p50
> **208.4 → 267.0 ms** and warm p50 **199.6 → 267.0**. One cell breached the 300 ms budget at
> **329 ms with no code change at all**. **Budget the CPU path against ~60 ms of usable headroom,
> not 87.** The repo lives under OneDrive, which holds delete-share locks on fresh binaries and is
> the likeliest cause of a 542 ms stall inside one timed span.

**Seven instrument defects in one session, every one caught by a control and none reaching a
published number** — see `RESULT.md` §5. The two worth carrying: a concurrent `cargo build`
inflating every absolute ~10% while the table reconciled perfectly, and `get_providers()` reporting
*registered* providers rather than *where nodes ran*. **The rate is the argument for controls that
feel redundant.**

**445 cargo tests** (from 421), `eval/` untouched at **72**. *(473 as of C2d.)*

---

**Updated:** 2026-08-08 — **M1 is CLOSED (`ed25914`). Current milestone: M2**, branch `m2-loop`.
Session A shipped the spine (loop, tools, permissions, runs, assembler); **Session B shipped path
scoping whole** — traversal suite and handle discipline together, ADR-027, **verified on Windows AND
Linux**. **414 cargo tests on Windows, 62 on Linux, `eval/` untouched at 72.** Next is Session C.

**M0b is COMPLETE and SHIPPED.** The Session J fine-tune is on the scored path; held-out R@1
**0.5764 → 0.6725**. K1 is amended and pinned. The precision/coverage curve is published and an
operating point is declared.

**M0c Session A (branch `retrieval-m0c`) ran head separability to a conclusion and shipped nothing.
R@1 stays 0.6725.** Both named candidates are measured and closed; K1's 10%-coverage interval is
retired as arithmetically unreachable. See "M0c Session A" below and `runs/session-m0c/RESULT.md`
before proposing any retrieval work.

> ### R@1 COUNTS THE SUPERSEDED FACT AS A HIT. Every R@1 in this project is inflated.
> LongMemEval marks **both** the stale and the current turn `has_answer`, so returning the outdated
> value scores as correct. Held-out **0.6725 → 0.6288** counting only the current value; on
> **knowledge-update 0.7222 → 0.4444**, where **10 of 26 apparent hits (38.5%) are the stale fact**
> (fit: 15 of 26, 57.7%). **Report `R@1_current` beside R@1 from now on.**
> `docs/design/HARM-WEIGHTED-PRECISION.md`.

## The shipped configuration

`--reranking models/ms-marco-MiniLM-L-2-v2-ft-session-j` — **f32**, seq 256, batch 1, depth 10,
sha256 `9c222dac…`. ADR-018 (the measurement), **ADR-020** (the shipping decision).
`runs/session-k/RESULT.md`.

| held-out, n=229, from the BINARY | Session H | **shipped** |
|---|---|---|
| **R@1** | 0.5764 | **0.6725** |
| R@5 | 0.8428 | **0.8865** |
| R@10 | 0.9039 | 0.9039 |
| **input recall** | 0.9039 | **0.9039** |
| **conditional accuracy** | 0.6377 | **0.7440** |
| retrieval P95 warm, full split | 149 ms | **211 ms** |
| retrieval P95 **cache-cold**, 40-case subset | — | **238 ms** |
| tokens over budget | 0 | **0** |

**`R@1 = input_recall × conditional_accuracy` factors exactly and input recall did not move by one
case.** A cross-encoder changes the order within the slate, not what is in it. The whole gain is
conditional accuracy, **+0.1063**. Lexical (0.5415), dense (0.4454), `fitted_gate` (0.5371) and the
either-cue oracle (0.6463) are **bit-identical** to Session H — that is the control.

**Two deltas, and they answer different questions.** **+0.0699** is fine-tuned vs **un-tuned f32** —
the contrast that isolates domain adaptation, with the test behind it (discordant 38, `p = 0.0139`).
**+0.0961** is what a user gets, because what was replaced was **int8**. Never quote +0.0961 as the
fine-tuning effect.

**Budget margin is now thin: 238/300 cold leaves 62 ms.** K1's precision numbers are *defined* at
these budgets — a violation makes them void, not caveated.

## READ THIS FIRST — three things that must not be re-derived wrong

**0. A CAPABILITY REPORT IS NOT AN EMISSION REPORT.** This is the standing lesson, and it was the
**eleventh** instance of the pattern this file has recorded — the first where *the harness disabled
the very thing it was verifying*. **The twelfth is in Standing checks below, and it is the first the
family caught prospectively**: `Deserialize` routed around a validating constructor, closed before
it existed rather than found after it shipped.

M1's frame rendered entirely achromatic in Windows Terminal for four rounds of screenshots while the
startup record printed `tier=truecolor`. Nothing was wrong with the detection: the terminal really
was truecolor. `NO_COLOR=1` was set in the environment of the shell that launched it, crossterm
honours `NO_COLOR` **at the formatter level** — `SetForegroundColor(..)` emits `ESC[m`, an empty SGR
which is a full reset — and every cell was therefore painted in the terminal's default foreground.
The layout, the styles, the region contract and the colour tier were all correct simultaneously.

**The probe was answering the wrong question.** It measured what the terminal *can carry* and
reported it where the reader would understand *what will be emitted*. Those two are different
quantities and nothing in the system compared them, so they disagreed in silence — the same shape as
the `--reranking` default, the `--embedder-model` default, and the eight before them.

The fix is `Theme::emission_report()`, which states what will actually be emitted and names the
override; it has a regression test. **The fix is not to stop honouring `NO_COLOR`** — that is a
legitimate user preference, and overriding it silently would be the identical sin inverted.

Generalised, for the next time: **when a component reports a capability, ask what it would print if
the capability were present but suppressed downstream.** If the answer is "the same thing", the
report is decorative. Diagnosing this cost four rounds and was only closed by writing three probes
that emitted known bytes and measuring the resulting pixels — *the screenshot was right and the
record was wrong* the entire time.

## READ THIS FIRST — two things that must not be re-derived wrong

**1. The 0.3739 ceiling never measured retrieval quality.** ADR-016. **A perfect retrieval system
scores 0.8483 on the shipped gate** against a 0.95 threshold: `fit_isotonic`'s smallest expressible
block is 435 rows spanning **100% of queries**, and the gate has no vocabulary for confident
subsets. Nine sessions read the gap as closable by better retrieval. It never was. **This
invalidates no retrieval measurement** — R@1, R@5, R@10, conditional accuracy, the oracle and every
closed mechanism were measured against gold turns with the gate uninvolved. `THRESHOLD = 0.95` is
untouched.

**2. R@1 and the operating point are different questions, and this is now measured twice.**
+0.0961 R@1 bought **nothing** at the operating point — the head got slightly *worse* while the body
got clearly better. See below.

## K1 — amended 2026-08-08, and the curve is published

Pinned in `ROADMAP.md` → "K1 — amended 2026-08-08" and brief **§5.7.1**. Argument: **ADR-019**.
Proposal of record kept and marked ADOPTED at `docs/requirements/proposed-K1-amendment.md`.

**The threshold is NOT moved.** The criterion's *shape* changed from a single point to a published
curve, and a **new** kill condition was added: **a flat curve — precision at 10% coverage not
materially above precision at 100% — is project-level.** Condition 3 is **binding**: a configuration
that injects at low precision to raise coverage fails outright.

### `docs/design/PRECISION-COVERAGE.md` — the published curve

> **DECLARED OPERATING POINT: coverage 10.0%, precision 0.9130 (21/23), CI [0.7196, 0.9893],
> margin ≥ 1.1651.** State this, with its interval, wherever the capability is described.

**K1 original: still not reached.** No coverage level clears 0.95 with its interval lower bound above
the threshold. Shipping a materially better model did not change that answer.

**K1 amended, flatness kill: NOT met.** precision@10 `0.9130` vs precision@100 `0.6725`, delta
**+0.2405**, ci_low@10 `0.7196` > `0.6725`. The confidence signal carries real information.

**The prediction was published before the measurement and it held:**

| at 10% coverage | superseded int8 | **shipped fine-tune** |
|---|---|---|
| precision | 0.9565 (22/23) | **0.9130** (21/23) |
| at 100% coverage | 0.5764 | **0.6725** |

One case of 23 flipped at the head, against +22 of 229 across the split. Statistically
indistinguishable at the head, clearly better in the body.

**Guarantee ≠ precision, always reported apart.** Conformal at α = 0.05: τ = 1.4639, measured
`P(inject | wrong)` = **0.0133** against the **0.05** bound, precision 0.9333 (14/15) at 6.55%
coverage. The bound covers the false-injection rate among wrong queries; K1 asks for
`P(correct | injected)`, a selective risk it does not cover. **Global τ only** — largest wrong-query
calibration set is 12 against a floor of 40.

## Superseded — M2 C2d (done; see the top of this file)

**`marlowe --tui` still drives M1's scripted stub.** `App::new(session: marlowe_stub::Session)` —
the whole surface is built on the stub's view models (`StatusBand`, `ControlStrip`, `Entry`,
`Pager`, `Tab`, `Item`, `Ambient`, `Picker`). `marlowe-stub/src/model.rs` says in its own header
that **M2 must pin them**, and this is that work: move them to a real crate the **daemon**
produces, and point `marlowe-surface` at it.

**Treat M1's 87 tests as the acceptance, not as an obstacle** (the human's direction). If one
breaks, a view model changed shape and that is the thing to look at — **a green suite after a
refactor of that size is more suspicious than a few honest failures.**

**What is already done and must not be re-derived:** `marlowe --ask` works end to end against a
real model through the real loop and the real wall. The daemon protocol already carries everything
§B5's band needs (`StatusReport`: workspace, model disclosure with its denominator, `degraded` with
its remedy, `rerank_provider`, `live_runs`). The TUI does not need a new data source — it needs to
read that one instead of the stub.

### What M3 inherits from M2, stated precisely

| | Status |
|---|---|
| **Invariant 6, first half** — a run outlives the **client** | **Done.** `tests/split.rs` asks, disconnects, and a different client still sees the run |
| **Invariant 6, second half** — a run outlives the **daemon** | **NOT claimed.** No WAL, no checkpoint resume. A daemon restart loses in-flight runs |
| `RunControl::resume` | **Refuses by name** — `ResumeError::NotDurable`, naming M3 and K5. It has never silently succeeded |
| `Run`, `CapabilityProfile`, `Budget`, `OrphanPolicy` | Implemented in full. `OrphanPolicy` is **recorded in the `RunSpawned` payload from the first spawn** and unused, which is what makes M3 an extension rather than a migration |
| Spawn lifecycle | Ephemeral: the parent blocks, the child returns, the child dies with the parent. The recursion is `Engine::run` re-entered; M3 replaces it with a scheduler and the data is already shaped for one |
| Concurrency | **One connection at a time.** A second client is an M3 concern and pretending to handle it now would be a concurrency story nobody tested |

## Superseded — M2 Session C2: the Ollama adapter

**ADR-028 (the human's decision): Marlowe runs against a LOCAL OLLAMA ENDPOINT first.** Hosted
providers register later. This dissolves the K6 tension rather than trading against it — an env
var, a first-run prompt and a bundled key all put *something* in front of the first run, and K6
measures whether that something is there, not whether it is small.

**Build the provider adapter; do NOT build the credential broker.** Ollama needs the first and none
of the second. Three requirements from ADR-028: degrade honestly when Ollama is absent (invariant 4
— a declared value on the run, surfaced in the status band, naming the remedy); record the
capability difference, tool-call reliability especially, so a debugging session can tell a harness
bug from a 7B model; and keep ADR-008's routing as a table over local models whose shape survives
hosted models arriving. `CapabilityProfile::model_route` already names a task role, never a model.

**Still owed from C1: the four executors** (`read`, `edit`, `find`, `bash`). The scope work they
need is done — see below. `bash`'s `cwd` needs its own assertion: `CreateProcess` takes a cwd
*string*, not a handle, so Windows relies on the walk's pinning a **second** time. That argument
must earn a test rather than inherit the walk's.

### M2 Session C1 — 2026-08-08. The platform gate and the write path.

**421 cargo tests on Windows, 65 on Linux under `MARLOWE_TRAVERSAL_STRICT=1`.**

- **`WorkspaceScope::new()` refuses at construction on an unverified platform.**
  `VERIFIED_PLATFORMS = ["windows", "linux"]` — what has been *executed*, not what compiles.
  **macOS is deliberately absent**: case-insensitive and NFD-normalizing, which is exactly where
  `glob`'s matching and `request`'s NFC handling would diverge.
- **`ParamType::WritePath`, declared per parameter.** `edit`'s `path` may create; `bash`'s `cwd` and
  `read`/`find`'s `path` must exist. Deriving access from consequence level would make two
  different requirements take their behaviour from the same number.
- **`Access` threaded through the walk.** It applies to the **final component only** — every
  directory on the way is opened read-only and refused if it is a reparse point, whatever the
  caller intends at the end. Creation happens *inside the already-verified parent*, which is why it
  is safe: the parent is still held open (pinned on Windows, an `openat` descriptor on POSIX).
- **A create positive control**, because a scope that only opened existing files would pass every
  other test in the suite and make `edit` impossible. It also asserts the negatives: a refused
  create must not create, and a create through a junction must not land outside.

### Superseded — M2 Session C's original framing

**Scope: `ROADMAP.md` §M2.** Sessions A and B are done. C builds the executors behind
`driver::ToolHost` (and they must take the handle from `Adjudication::handles`, **never re-open a
path** — that is the one way to reopen the race ADR-027 closed), `SKILL.md` loading with progressive
disclosure, `find_skill` semantic discovery, MCP as tool transport, and a provider client honouring
`CallLimits::max_output_tokens` as a hard cap.

**Before writing an executor, read ADR-027's last section.** The wall is the handle walk; an
executor that calls `File::open(scoped.resolved())` has undone it, and no test in the traversal
suite would notice, because the suite tests the checker and the race would be in the caller.

### M2 Session B — 2026-08-08. Path scoping, whole. ADR-027.

**412 cargo tests (from 375), `eval/` untouched at 72.** `WorkspaceScope` replaces the refusal;
`Unavailable` is retained for profiles that must provably not touch the filesystem.

**Three parts, and only the third contains anything:** `request` refuses ambiguous spellings before
any syscall, `glob` matches the declaration, `walk` opens without ever letting a string be resolved
twice. POSIX: `openat` + `O_NOFOLLOW` per component. Windows: every directory pinned open with a
share mode **excluding `FILE_SHARE_DELETE`** (so the prefix cannot be renamed out from under the
walk), plus `FILE_FLAG_OPEN_REPARSE_POINT` with refusal on `FILE_ATTRIBUTE_REPARSE_POINT`, plus
root identity verified before and after.

**The TOCTOU test races, and proves it races.** `tests/toctou.rs` carries a deliberately vulnerable
`naive_check_then_open` and **asserts that it escapes** — returning out-of-scope content under the
same interleaving. That is the half that makes the other half mean anything. The interleaving is
deterministic via a `WalkObserver` called at the exact vulnerable instant (`()` in production), not
a thread racing and hoping. On Windows the test also asserts the swap failed *as a sharing
violation*, so a swap that failed because `mklink` was missing cannot leave it green.

**BOTH GAPS ARE CLOSED, and the closing condition is now a standing requirement.**

They were real and blocking: the symlink class could not run on Windows (os error 1314, privilege
not held), and the POSIX walk had never been executed — ADR-002's inversion landing on the security
boundary.

**Closed 2026-08-08 on WSL2 (Kali, ext4 `/tmp`, native symlinks), `MARLOWE_TRAVERSAL_STRICT=1`, all
62 tests green and the coverage manifest reporting `RAN` for all eleven classes including symlink
escape.** The POSIX `openat`/`O_NOFOLLOW` walk executed for the first time there, and
`the_naive_implementation_escapes_which_is_what_makes_this_a_race` passed on Linux too — so the race
window is demonstrably real on Linux and `O_NOFOLLOW` demonstrably closes it.

**The standing requirement, because a one-time run is not a guarantee:** the suite runs on **both**
platforms with `MARLOWE_TRAVERSAL_STRICT=1` before path scoping is called verified after any change
to `scope/`. Windows alone leaves the symlink class unrunnable; Linux alone never executes the
pinning. `.wsl-probe.sh` is deliberately **not** kept — a script nobody reads is not a procedure;
the command is two lines in ADR-027.

**A guard whose subject moved is no guard.** Splitting `scope.rs` into `scope/` made the brief §13
hook name a file that no longer existed — path scoping was silently unguarded and nothing said so.
The entry is now a directory prefix, the hook grew `--self-check`, and
`marlowe-permission/tests/boundary_hook.rs` fails the build on a stale entry. Verified by a negative
control: renaming a guarded file makes it fail by name.

**Positive controls are in the suite deliberately.** Session A's refuse-everything scope would pass
every negative assertion in a traversal suite. Legitimate deep reads and lookalike filenames
(`console.log`, `a..b.txt`) must open, or the suite measures presence rather than correctness.

**After C, in order:** D — wire M0b's memory in, including K1 condition 3's abstention path, which
is a condition of the criterion M0b was judged against and is **load-bearing**. E — the TUI against
the real loop, first-run onboarding (ADR-002 makes it a requirement, not a nicety), K6 measured in a
clean container, and M1's one open acceptance row (accent on a light background).

### M2 Session A — 2026-08-08. The spine: loop, tools, permissions, runs.

**Three new crates, one-way layering: `marlowe-tools` → `marlowe-permission` → `marlowe-loop`.**
375 cargo tests (from 273), `eval/` untouched at 72, conformance unchanged
(`REJECTED, 0 findings, fail_no_time_dependence` — the baseline since Session B, see Known issues).

**The three things M2 had to get right so M3 extends rather than replaces:**

1. **Every spawn declares a `CapabilityProfile`**, and `reads_untrusted && !exposed_tools.is_empty()`
   is a load-time error — private fields, one constructor, and `Deserialize` routed through it so a
   profile from a file cannot bypass what a profile from code cannot. **Two refusals beyond the
   pinned one** (ADR-022): a quarantined reader may not write memory and may not hold egress, because
   the empty tool set closes neither — the loop's own `MemoryWrite` step is not a tool.
2. **Every spawn declares a `Budget` and an `OrphanPolicy`.** `OrphanPolicy` is recorded in the
   `RunSpawned` payload and unused, which is what makes M3 an extension. All six budget dimensions
   fire, each tested individually.
3. **Children return `CondensedResult` and nothing else.** The child's `SessionState` is dropped when
   the recursive call returns; there is no accessor that hands a parent a child's history.

**A subagent is the one loop re-entered** (ADR-022). `tests/hp10_budgets.rs` fails the build if a
second driving loop appears in the crate.

**The decision most likely to be argued with is ADR-023, and it should be read before Session C.**
Taint is computed by the harness from the context window — `ModelStep::ToolCall` has no taint field
at all — so a model-composed Target carries the **worst trust class in view**. The consequence looks
like a bug the first time it fires: **once a run has read untrusted content, every model-composed
Target in that run is blocked.** That is §8.2's trifecta break arriving as a property rather than a
second mechanism, and it means orchestrator-worker is *required* for any run that reads the web and
then acts, not an optimization for hard questions.

**Two defects found by tests, both fixed, both recorded because their failure modes were invisible
from their own tests:**

- **The assembler dropped any block larger than its source cap.** A single long turn vanished. Found
  by a 70%-trigger test reading `fill_pct = 0.0024`. Fixed by ADR-025: only *recoverable* sources are
  trimmable — history is not, so history pressure raises fill until compaction handles it with the
  durable appends in front. Omissions are now marked in the view, never silent.
- **Two spin paths.** Compaction compared successive iterations rather than its own result, and
  tool-result masking re-ran when it had nothing left to mask. Both presented as a hang, which is the
  worst shape: `MAX_STEPS` caught them as a budget pause, which reads like a model problem.

**`--reranking`-class hazard avoided, worth naming:** `ExposedSet`, `CapabilityManifest` and
`CapabilityProfile` all route `Deserialize` through their validating constructor. A field-wise
deserialize would have left every in-code test green while the only path that reads outside input
skipped the check.

**Known gap in the brief §13 hook, measured not assumed.** The permission layer's files are guarded;
`engine.rs` — the loop's *call* into it — is not, because guarding it would make every loop change
ask. What stands behind the call site is a test that drives a real blocked call through the loop.
See CLAUDE.md's enforcement table.

**Deferred from M1 and still deferred:** app-level text selection in the conversation pane, and the
launcher on macOS/Linux (§B17). Both are Session E or later; neither blocks anything.

### M1 progress — 2026-08-08

**Built and verified live in Windows Terminal** (not `TestBackend`): the frame, keyboard navigation,
conversation and §B6 tool lines, status band and seven states, inspector, approvals overlay, classic
CLI, width refusal, `doctor`. 87 tests green across `marlowe-surface`, `marlowe-stub`, `marlowe`;
`eval/` untouched at 72.

**Amendments to Addendum B made this session, all at the human's direction:**

- **§B10 — the mouse is captured.** Reverses the earlier "keyboard-first, so leave selection to the
  terminal" reasoning: drag-selecting the frame is the single thing that made a running application
  read as a printout. Keyboard remains complete; teardown is in the panic hook too.
- **§B10 — the first-keystroke rule.** The default focus is a region where letters are hotkeys,
  **never a text input**. Stated as a rule because the failure is invisible to any test that presses
  `Esc` first — "reachable after one extra key that no border mentions" still passes.
- **§B10 — copy is first-class.** `Shift`-drag (verified working under capture: 121 chars out of a
  live session), `y` for the focused turn, `Y` for the transcript as markdown. **Payloads are built
  from the model, never the screen** — the measured native selection returns
  `+3 −0 ││ ┌Spend───…`, three regions' cells from one row.
- **§B17 — the launcher.** `marlowe --launch` writes an additive Windows Terminal profile, scheme
  and theme, then opens the window. **The `Marlowe.lnk` this line claimed did not exist until C2d
  created it** — there was no shortcut and no code for one.

**Three bugs found by using it that no test caught, all now fixed:**

1. **Scroll never moved.** `move_within` computed `u16::MAX - 1` and the renderer clamped it back to
   the bottom, so the first notch moved nothing and so did the next 65,533. **Every unit test
   passed**, because they asserted `scroll` *changed*, not that the view *moved*. The renderer now
   hands its clamp back to the app.
2. **The third foreground weight was double-dimmed.** The palette carried the mockup's exact
   `#4a4460` **and** `Modifier::DIM` on top, "for terminals that honour it" — which had the
   reasoning backwards: an explicit fg colour is universal and SGR 2 is the unreliable half, so the
   modifier could only double-apply where it worked. Windows Terminal honours it, and the dimmest
   tier became unreadable. **The weights now carry no modifier**, so the mockup is the reference on
   every terminal.
3. **`NO_COLOR`.** See item 0 at the top of this file.

**Two Windows Terminal limits, measured rather than assumed** — do not re-attempt without new
evidence: `themes.window.frame` is accepted and **silently ignored** (focused title bar stayed at
the Windows accent colour `#946B33`); and the tab strip's `+` cannot be hidden while Windows
Terminal draws the title bar, while giving the title bar back to Windows removes `+` but repaints it
in the accent colour. The `×` *is* removable (`tab.showCloseButton: never`). Focus mode was tried
and rejected — it takes drag and close with it, and `WS_CAPTION` is already set, so no window-style
trick restores them.

**HOVER WORKS. A CLAIM THAT IT DID NOT WAS WRONG, AND THE WAY IT WAS WRONG IS THE LESSON.**

An earlier version of this section recorded, as a measured fact, that mouse motion events were never
delivered and that every hover state was dead code. **That was false.** The human confirmed hover
working by using it.

What the measurement actually showed: a synthetic pointer sweep via `SetCursorPos` produced
`mouse=2`. The harness had failed `SetForegroundWindow` three times immediately beforehand
("target window refused focus"), and terminals report mouse motion only to a **focused** window.
So the number measured the harness's inability to activate the window, not the application's
ability to receive motion.

**This is the same error as the `NO_COLOR` bug in item 0, committed while writing up the `NO_COLOR`
bug.** A probe answered a question adjacent to the one being asked, and its answer was read as a
product failure. The specific trap for anything driving a GUI from outside: **synthetic input into an
unfocused window is not evidence about the application.** Assert focus, or do not report the result.

No code change was kept. `ESC[?1003h` was briefly added and has been reverted — crossterm's
`EnableMouseCapture` already enables all-motion tracking, which is why hover worked all along.

**Deferred to M2, with a real blocker rather than a shrug: app-level text selection in the
conversation pane.** Mouse-down anchors, drag extends, the span renders in inverse video, release
copies. It needs cell-to-character mapping that respects wrapped lines and **never crosses a region
boundary** — which is exactly what terminal selection cannot do, and the measured proof is in §B10:
a `Shift`-drag across one row of the running build returned `+3 -0 || ,-Spend---`, three regions'
cells from a single screen row. It is blocked on Marlowe owning the renderer for that pane, it is
about a week, and `helix`/`zellij` are the reference implementations. M1 ships `Shift`-drag plus
`y`/`Y`, which covers the need without pretending to be the same capability.

**Two Windows Terminal limits, as measured facts with their numbers.** These are the evidence for
whether a native window is ever worth a milestone, so they are recorded as data, not impressions:

1. **`themes.window.frame` is accepted and silently ignored** (WT 1.24.11911.0). Set to `#0F0E14`,
   the focused title bar still measured **`#946B33`** — the Windows accent colour. A settings key
   that does nothing and reports nothing.
2. **The tab strip's `+` cannot be hidden while Windows Terminal draws the title bar.** The two
   reachable states were both built and measured: `showTabsInTitlebar: true` gives a title bar at
   **`#0F0E14`**, identical to the terminal background and seamless, but keeps `+` and the chevron;
   `false` removes the whole strip but hands the bar to Windows, which paints it **`#946B33`**. The
   `x` *is* removable (`tab.showCloseButton: never`). Focus mode was tried and rejected: it removes
   drag and close, and `WS_CAPTION`/`WS_SYSMENU` are **already set** (style `0x14CF0000`), so no
   window-style trick restores them — WT draws over the caption itself.

**The 9-line interaction checklist PASSED**, driven by hand by the human in one live Windows
Terminal session, 2026-08-08: every region hotkey, all five dropdowns opened and selected from, the
full Tab cycle and back, conversation scrolling, all seven status states, the approval overlay,
`Ctrl-C` handled by the app, a forced panic, and quit. `RESULT.md` records it attributed to the
human rather than as an unattributed "verified".

**ONE ROW LEFT BEFORE M1 IS ACCEPTED:** accent legibility on a **light** terminal background. §B13
asks for the eye, on each; it has a contrast number (3.26:1, which clears AA for large text and UI
components but not AA body) and has never been looked at. Open it once on a light background and
either accept it or move the accent.

### M0c Session A — head separability, MEASURED AND CLOSED. `runs/session-m0c/RESULT.md`.

**R@1 is 0.6725 and this session did not move it. Nothing shipped; there is no Rust diff.** Both
named candidates were built, four learned architectures were cross-validated, and a seventh
mechanism was found mid-session and taken to a held-out read. All null or negative.

**1. K1's interval reading is ARITHMETICALLY UNREACHABLE at the declared operating point.** A
**perfect** selector — 23 of 23 — has a Clopper-Pearson lower bound of **0.8518** at 10% coverage on
n = 229. Clearing 0.95 by interval needs **n_c ≥ 72 with zero errors, or ≥ 110 with one**. This is
not a retrieval statement; it retires a target the way ADR-016 retired the 0.3739 ceiling.
**Do not register a band on it.** `tools/reach_head_r0_attainability.py`.

**2. Candidate A — a relevance-fitted confidence signal — is NEGATIVE.** No query-time feature beats
the rerank margin at the head, and the three with *better overall AUC are worse there*. Overall
discrimination and head discrimination are different quantities on this corpus.

**3. Candidate B — set-wise / listwise scoring — is a NULL across four architectures.** Out-of-fold,
5-fold CV by conversation: S1 set-wise head **+0.0044**, L1 listwise fine-tune **−0.0131** (null
*with power*, discordant 13, p = 0.5811), LS1 **+0.0000**, S2 global cross-encoder with token-level
cross-talk **+0.0000** (top-1 changed on 2 of 229). **The binding resource is labelled data** — 229
fit queries, 38 recoverable failures, on a reranker Session J already fine-tuned on them.

**4. Slate construction gained +0.0087 on fit and lost −0.0044 on held-out.** Input recall rose
+0.0175 and conditional accuracy fell −0.0189 to meet it. The Session J addendum pattern exactly.

**5. THE FAILURE MODE IS NOW CHARACTERISED, and it is not what STATE.md said.** Same-session
gold-to-rank-1 turn gaps are **−10, −8, −6, −4, −2 — all even, therefore SAME ROLE**. The failure is
**discriminating between two USER turns in one conversation several exchanges apart**. Rank 1 on
failures is assistant-authored on only **5.3% (fit) / 7.5% (held-out)** of cases — the Session J
fine-tune already removed the user/assistant confusion. **The "47.1% assistant-authored" figure
below is stale and turn-pair chunking's rationale goes with it** (measured ceiling: +0.0087 fit,
+0.0131 held-out).

**6. A METRIC MISMATCH, resolved.** Systems publishing "96.6% on LongMemEval" report **session-level
R@5**. Marlowe measures **0.9738 session R@5 shipped, 0.9869 on its dense cue alone** — it is not
behind on that metric, it reports a far harder one (turn-level R@1 out of ~490 candidates). Never
quote one against the other.

**7. HARM-WEIGHTED PRECISION, measured for the first time. `docs/design/HARM-WEIGHTED-PRECISION.md`.**
§5.7 is about harm, not accuracy, and R@1 treats every failure as equal. Partitioning rank-1 into
harm classes — no new labels, LongMemEval's knowledge-update annotation carries it:

  - **Of the injections that are not the current value, 13 of 85 (15.3%) are HARMFUL and 72 (84.7%)
    are merely useless.** §5.7's premise is *weaker* than assumed on the failure side. Five in six
    wrong injections cost tokens rather than corrupt reasoning.
  - **But R@1 counts the stale fact as a hit** — see the box at the top of this file.
  - **At the declared operating point the two precisions are IDENTICAL**: published 0.9130, current
    0.9130, harm 0 of 23, on both splits. `PRECISION-COVERAGE.md` needs no correction at 10%
    coverage and a −0.0437 correction at 100%.
  - **Harm is zero at the head FOR THE WRONG REASON, and this is the part not to re-derive wrong.**
    Not "abstention suppresses harm" — that is a proxy conclusion. Knowledge-update queries are
    simply low-confidence (median margin **0.2782 vs 0.4020**) and make up **0.0% of the held-out
    top-10% slice against a 15.7% base rate**. *Within* knowledge-update the margin's relation to
    harm **flips sign between splits** (top-half harm 0.444 held-out vs 0.389 fit). The protection is
    a **category-exclusion side effect and it is fragile** — raising coverage, or improving
    confidence on knowledge-update, removes it with nothing reporting a change.
  - **§4.3's supersession exclusion is LIVE AND BLIND.** `entry.rs:124` is correct and called at
    `retrieve.rs:328` — not a wiring defect. But the only writer of `superseded_by` is
    consolidation's **≥0.98-cosine** near-duplicate merge (`consolidate.rs:697`); `ingest.rs:142`
    hardcodes `None`, §4.6's wire has no supersession field and forbids extras, and `store.rs:133`
    defers the contradiction detector. ADR-012 measured ≥0.98 pairs at **0.0086%** of 30.6M.
    **A missing component, not a tuning opportunity — and it is the component §5.7 assumes exists.**

**THE HUMAN LABEL SET is now the highest-value open item** — ≥400 judged injections, ≥50 per
category, judged blind, stratified by score decile. **True injection precision has never been
computed**; every figure is a gold-turn proxy, including the harm classes above. It is drawable and
it is the human's deliverable.

### M0c Session B — supersession is BLOCKED, not dead. ADR-028. `runs/session-m0c/RESULT.md` Part 7.

**Nothing was built. The verdict is about scope.** Three measurements, on fit, before any code:

- **R6, the ceiling.** A perfect oracle is worth **+0.1666 knowledge-update R@1 current-value-only**
  (0.3056 → 0.4722), **+0.0262 overall** (0.6900 → 0.7162), and cuts harmful injections **17 → 5**.
  **Worth building whenever it becomes reachable.**
- **R6, the power finding.** A perfect oracle produces exactly **6 discordant** — the bare minimum
  for α = 0.05 — reaching p = 0.0312 *only* because all six fall one way. **No realisable detector
  can produce a significant result on this split.** α is declared UNATTAINABLE IN ADVANCE; the delta
  carries any future verdict alone. The oracle's one-directional read is structural and must not be
  inherited by a real arm's instrument check.
- **R7, similarity CLOSED.** True pairs at ~0.83 cosine sit inside a distractor distribution reaching
  0.95. **Best precision anywhere: 0.0745** — twelve live memories permanently removed per correct
  catch, against a cost model registered before measuring. **ADR-012's 0.98 bar catches 0 of 33**,
  which is the quantitative reason the current merge is blind.
- **R8, value conflict CLOSED ON SCALING.** **0.4444 anchored** on the true stale turn; **0.0026
  unanchored** as a real detector runs — 4 true against ~1,539 false across 3.9M pairs, a **154×
  collapse**. The anchored number was the mechanism's precision *conditional on entity resolution
  already existing*. **The rule verifies supersession given a candidate; it does not find one.**

> **VERDICT (2): signal present, extraction missing.** Not undetectable — blocked on a component.

**OPEN GAP, with a named closing condition. DO NOT MARK SUPERSESSION CLOSED.** Detection requires
**entity resolution over the candidate pool**, which narrows 3.9M pairs to a handful before any value
comparison runs. **HP2 specifies it — `SameAs` beliefs with confidence and provenance, produced by
consolidation — and it has never been built.** `Payload::Entity` and `Payload::Edge` exist in §3.2;
nothing fills them. **Closing condition: that component exists**, and then a value comparison over
(entity, relation) triples clears **precision ≥ 0.5 measured UNANCHORED** — parity under the
registered asymmetry — at a recall moving the ceiling by more than one case. **Entity resolution is
HP2 and is NOT scoped here**; it needs its own registration and its own reachability check. Note it
would be the first live exercise of trust propagation through a derived belief.

> ### §5.7 CONSEQUENCE — the finding of this whole line of work
> **With supersession unreachable, harm being zero at the operating point is the ONLY protection
> that exists, and it is ACCIDENTAL.** The head contains **0.0% knowledge-update queries against a
> 15.7% base rate** because that category is low-confidence (median margin 0.2782 vs 0.4020), not
> because harm is detected. **The tripwire is now LOAD-BEARING, not diagnostic.**
>
> **Two ways it disappears, both things a future session might do deliberately:** coverage rising,
> or knowledge-update confidence improving. R6 measured the second — a perfect oracle takes the fit
> knowledge-update share of the top decile from **4.3% to 13.0%**. Neither announces itself.
>
> **`tools/tripwire_head_composition.py`**, baselined at
> `crates/marlowe-memory/artifacts/head-composition-baseline-v1.json`. TRIPs on any harmful
> injection at the operating point against a baseline of zero; WARNs when the knowledge-update share
> reaches the base rate, at which point the harm figure must be RE-MEASURED, not inherited.
> **`0 of 23` is reported with its interval every time — upper bound 0.1482.**

**THE CORRECTED BASELINE MUST APPEAR BESIDE EVERY PUBLISHED R@1.** Held-out **0.6288** current-value-
only against **0.6725** published; knowledge-update **0.4444** against **0.7222**. A session quoting
the published figure without knowing it counts stale hits as successes is working from a false
premise.

**§4.3's exclusion is untouched and is NOT the defect.** It is correct, wired and unit-tested. It has
no edges because nothing produces them.

**Also still open:** the gate-design constraint (ADR-016's closing section — either the resolution
rule or the margin feature's one-positive-per-query property must change; **re-tuning the resolution
stays forbidden**); QA accuracy (needs an API credential); **batching the depth-10 rerank** —
batch invariance measured **0.000000** on the shipped f32 graph in Session K, so it is available and
untested, and latency is the only currency that buys depth.

**Do not re-attempt:** consolidation, PRF, entity expansion, HyDE, session pruning as a quality
mechanism, length normalization, raising sequence length, **re-scoring the depth-10 slate by any
learned mechanism**, or **the 10%-coverage interval**.

## Standing checks — re-run on every cue, feature, pool or MODEL change

- **A second implementation of a scored-path component must reproduce the first, EXACTLY.** Session
  H: 0.5764 = 0.5764. Session K: **0.6725 = 0.6725**.
- **`analyze_cue_overlap.py` is the authority for binary-side R@1.** Its ranking functions and dump
  reader are module-level so a second tool imports them instead of restating them.
  `publish_precision_coverage.py` **refuses to write** unless its R@1 matches.
  **`score_longmemeval.read_scored` drops `survived_pruning` and `rerank_score`** — anything ranking
  from it silently falls through to the gate order. This cost a full wrong curve in Session K.
- **Determinism, batch and padding invariance are re-measured PER GRAPH and never inherited.**
- **Pin the ONNX graph optimization level on both sides.** `ort` uses `Level1`; Python defaults to
  `ORT_ENABLE_ALL` and fuses differently — 0.0699 logits apart on identical token ids.
- **`repro --runs 2`, WITHOUT a cache.** Run it *early*.
- **`conformance` BEFORE any quality number.**
- **The artifact the driver reads must be the artifact the run scored with.**
- **Calibration generalization: fit-split prediction vs held-out measurement**, per cue.
- **The unchanged-cue check is a NULL INSTRUMENT for a pruning change.** Its silence is not evidence.
- **`cargo test --workspace` (494) and `cd eval && python -m pytest` (72).**
- **A build error seen in a shared checkout is a SNAPSHOT, not a fact.** Re-verify before
  reporting one, and say when it was observed. Twice in one day a session reported a real error in
  the other's mid-edit that had already been resolved — in both directions. See CLAUDE.md's
  parallel-sessions table.
- **A traversal suite must contain an implementation it DEFEATS.** `tests/toctou.rs` asserts that
  `naive_check_then_open` escapes under the same interleaving. Without that half, a green suite is
  equally consistent with a test that never landed in the race window.
- **A guarded path that moved is unguarded, and says nothing.** `protect-boundaries.py --self-check`
  fails on a stale entry and `tests/boundary_hook.rs` runs it. Re-run after any file move under a
  guarded component.
- **A validating constructor must be the ONLY way in, `serde` included.** `ExposedSet`,
  `CapabilityManifest` and `CapabilityProfile` route `Deserialize` through theirs. A field-wise
  deserialize leaves every in-code test green while the one path that reads outside input skips the
  check — the same shape as a stale default, arriving through a different door. **This is the
  TWELFTH instance of the family in item 0, and the FIRST caught by design rather than by failure**
  — the other eleven were found after they shipped; this one was closed before it could exist,
  because the family's question was asked of the serde path specifically.

## The default model, and what was actually measured

**`qwen3.5:9b`**, pinned as `marlowe_provider::DEFAULT_MODEL`. Chosen on **tool-call reliability**
rather than general quality, because the first thing a user does is ask Marlowe to read a file and
a model that cannot emit a well-formed call looks exactly like a broken harness.

**Measured 2026-08-08, one model, 12 trials: 12/12 well-formed, 12/12 correct target, median
1666 ms.**

**And the qualification, because a point estimate is not an interval.** 12/12 on twelve trials has
a 95% Clopper-Pearson lower bound of ≈**0.74**, which is *below* the 0.80 bar it is measured
against. It clears the bar **on the point estimate and not with its interval** — the same
distinction K1's amendment turns on. Twelve trials is thin. Raising `capability::MIN_TRIALS` costs
only probe time, and is the cheapest way to tighten this.

**No other model has been measured**, so this is not a comparison — see the constraint below.

## A standing constraint on every routing decision

**Model comparison is bounded by local hardware: one model at a time.** The development machine
holds a large library on disk but cannot keep several large models resident, so a comparison sweep
thrashes rather than erroring. `tests/tool_call_probe.rs` therefore measures **one** model by
default and requires `MARLOWE_PROBE_SWEEP=1` plus an explicit list before it will iterate.

**This binds more than the probe.** ADR-008's tiered routing — strong model for orchestration,
cheap models for extraction and classification — assumes two models can be *chosen between*, and
choosing between them means measuring them. On this hardware that is sequential, slow, and cannot
be done as one run. A proposal that treats a strong/cheap split as free is a proposal that has not
priced the measurement. Recorded here so it does not surface as a surprise inside one.

## Known issues

### M2 C2e - outstanding, highest first

- **`web` IS EXPOSED. ADR-032 is implemented and approved.** `interactive()` holds
  `EgressPolicy::AllowApproved { granted: [] }` and exposes eight tools. The three deny-shaped
  policies are now genuinely different and the difference is the decision: `DenyAll` is
  **structural and unwidenable** (the quarantined reader holds it, and `grant()` is a no-op on
  it), a declared `Allow` list is **terminal** (a tool cannot ask its way past a list somebody
  wrote), and `AllowApproved` is a **question** — empty by default, widened one host at a time by
  a human, session-scoped, never persisted. Brief §8's allowlist-by-default holds with an empty
  default set rather than a `*`.
  **The ask fires on a check the consequence level cannot reach**: `web` is `Inert`, so the tier
  comparison would allow it outright, and ADR-002's Inert exemption only stands while egress
  allowlisting covers the tool. The prompt names the host — asserted, because that is what makes
  per-call approval a replacement for the allowlist rather than a button.
  **THE CLI CAN NOW APPROVE.** `Client::send_streaming_approving` answers inline, on the same
  socket, because the daemon is blocked on that read. `marlowe --ask` prompts at the terminal with
  the blast radius and defaults to no; stdin at EOF (a pipe, a script) declines, because an
  unattended `--ask` has nobody to approve anything. `decision: 0` — the loop's render-only
  announcement — is deliberately **not** answered, or a spare approval sits on the wire for the
  next question.
  **THE TUI STILL CANNOT.** `live.rs` reads `Event::Approval` and drops it. `--tui` is therefore
  the wrong surface for testing approvals; use `--ask`.
  **NOTHING HAS CROSSED THIS ON A REAL TURN.** Both halves are tested against each other over a
  real socket (`approval_round_trip.rs`) and neither test runs a model. Treat the end-to-end path
  as unverified until an approval is observed on a real turn with a real fetch.
  **§B9 is partly served:** blast radius and `novelty` (an `Option`, never defaulted). **No
  ceiling** — no producer until the trust ledger at M6, and defaulting one would be a claim about
  promotion logic nobody has written.
  `recall` and `use` remain unexposed and unimplemented.

- ~~**The trust floor latches on an ordinary workspace read.**~~ **CLOSED, M2 C2f** — and the
  diagnosis was neither of the two candidates. The trust class at ingest and the floor derivation
  were both correct; the *announcement* fired on any downward move. The trigger was not a `read` at
  all: the stable tier's `Identity` block is `AgentObserved`, so it fired on the first assemble of
  every run. See the C2f section at the top.
- ~~**`ParamSpec` conflates a security role with an arity question**~~ — **CLOSED.** The code
  landed in `de18ace`; C2f added the missing paperwork (ADR-034, CONTRACTS §7.3 amended, which had
  been pinning a three-field struct that shipped code contradicted). Descriptions were corrected in
  the same commit; only `web`'s remains, pending search. Original entry:
- **`ParamSpec` conflates a security role with an arity question, and the pin is APPROVED to move.**
  `required` in the JSON schema is derived from `ArgumentRole::Target` - but Target answers *what
  untrusted content may never shape*, not *what the executor demands*. **11 measured mismatches**:
  9 params marked required that are not (`bash.cwd` is the clearest - the executor defaults it to
  the workspace while the schema forces the model to invent one), and 2 the executor demands that
  the schema calls optional (`find.pattern`, `edit.content` - schema-valid calls the executor
  rejects). Human approved: `ParamSpec` gains a requiredness field, CONTRACTS 7.3 amended,
  `DECISIONS.md` entry, **all three sites changed together** - the schema, `param_description`, and
  `Engine::expected_params`. A model told the wrong thing and then corrected with the same wrong
  thing is worse than one told nothing.
- **Descriptions promise operations that do not exist.** `bash` says "persistent shell session"
  (`spawn_shell` runs a fresh `cmd /C` per call), `find` says "index-backed symbol lookup" (it is
  `line.contains`), `edit` says "atomic" (it is `set_len(0)` + rewrite), `read` says "blob, or
  reference" (no parameter accepts either). Model-visible prose that makes the model call things
  wrongly and then blame itself.
- ~~**`run.budget_micros_usd` never appears in the approval prompt's scope line**~~ — **CLOSED
  (C2f)**, via ADR-032 §3.2 and a §13-approved change to `adjudicate.rs`. `ArgValue::render` is
  total and wildcard-free. **The parser half is still open**: `parse_step` still emits `Integer`
  for a declared `Amount`, so the declared type is never the runtime variant. That no longer hides
  the ceiling — `render` handles `Integer` too — but the coercion-by-declared-type is unbuilt.
  Original entry:
- **`run.budget_micros_usd` types as `Amount`, which `parse_step` can never produce** - it emits
  `ArgValue::Integer`. `blast_radius` collects targets via `as_text`, which returns `None` for
  `Integer`, **so the spend ceiling never appears in the approval prompt's scope line**. Section B9
  requires blast radius stated; a budget absent from the scope line is exactly the case where a
  human approves something they would have refused. **Highest-consequence finding of the tool
  audit.** `adjudicate.rs` is section-13 guarded: this needs a `DECISIONS.md` entry **before** it
  is fixed.
- **`--ask` cannot talk to a running daemon.** No `--daemon-port`; it always runs in-process, so
  two `--ask` invocations get two daemons and two empty sessions. The TUI is unaffected.
- **Session memory is in-process only.** The store lives on `Daemon`; it does not survive a restart.
- **`bash` is refused unconditionally in the daemon.** `Irreversible` -> `NeedsApproval` at every
  tier -> `DenyUnattended` returns false. There is no interactive approval gate yet, so it always
  reads `declined`.
- **`run` never spawns from a model call.** `control_step` returns a canned
  "[run is not yet reachable from a model call...]", and the schema still demands three spawn
  arguments.
- **`read` cannot dereference a reference.** `web` declares `inline_threshold_bytes: 0` - "the loop
  gets a reference" - and nothing can read one. The head/tail preview is a stopgap; the content
  store is M2 D.
- **`consolidation()` exposes `recall`, which has no executor.** It will fail
  `verify_every_exposed_tool_is_runnable` the moment it is wired at M2 D. Left as declared: the
  guard firing then is the guard working.
- **Tool lines render OUTSIDE the thinking block.** `Entry::Tools` is a peer of `Entry::Reasoning`,
  so lines land between reasoning blocks rather than nested. **Not intentional - it fell out of
  section B6's one-line-per-call being its own entry. The human has seen it and asked for it to
  stay.**
- **Nudges reach the model as `system` messages** mid-conversation. Observed in the dump. Whether
  they are journalled is the human's acceptance condition 2 and is still unanswered.
- **Never seen again, never explained:** one live reply contained a literal `[tool .]` marker. Not
  in the source. Possibly the model imitating a tool line, as it imitated `[your prior reasoning]`.

### Deferred with the human's agreement

- **Deep research is out of scope** (brief section 10).
- **Hermes agent-loop research** - asked for, displaced by live bugs, never done.
- **The `web` manifest cannot express search** (`url` required, `query` optional, description says
  "Search and fetch"). ADR-006 territory; folded into the `web` work above.
- **Acceptance conditions 6 -> 4 -> 5 -> 1** are partially covered by this session's tests. The
  unmeasured constants (1) - `MAX_AUTO_CONTINUE`, the three farming thresholds, `max_iterations` -
  are still unmeasured and still unmarked as placeholders.


- **The export gap is now on the SHIPPED path.** The graph is **self-validated only** — this project
  is the publisher, so there is no external authority. Digest pinning, torch-vs-ORT at 1e-6,
  per-graph determinism/batch/padding invariance, and a second pair-encoder implementation
  reproducing HuggingFace exactly are what stand behind it. **They bound the gap; they do not close
  it.** Say so wherever the number is quoted.
- **Do not re-quantize the shipped graph without re-measuring `[1, 256]`.** ADR-015's shape-binding
  is a property of int8 graphs; **padding alone flipped top-1 in 15% of int8 cases** while f32 was
  invariant to 0.000000. The fine-tuned graph has never been measured quantized.
- **`MAX_SEQ_LEN` stays 256; the 7.86% gold truncation is a PRICED defect.** Raising it cost
  −0.0917 R@1 (`p = 0.0002`, α attainable) because the cap doubles as a length normalizer.
  ADR-017's closure was **withdrawn** on held-out. Only viable with a normalization term fitted
  against **relevance**, not against the score — and the registered `E[score|length]` estimator had
  slope −0.5091 and *added* score to long candidates.
- **At top-10 the shipped ranker is BELOW dense alone** (0.9039 vs 0.9170). It is a top-1 mechanism
  reordering ten candidates; do not read its R@10 as a capability.
- **The gate still injects nothing, and ADR-016 is why** — not retrieval quality. Conformance is
  REJECTED with 0 findings and `fail_no_time_dependence`, the unchanged baseline since Session B.
  **§4.3 maturation still has no contract-level coverage.** Wiring the declared operating point into
  an injection path, with condition 3's abstention path, is **M2 work and now load-bearing**.
- **Per-category reads are unstable across the split — a finding AGAINST group-conditional
  conformal, not a caveat on it.** Largest wrong-query calibration set is 12 against a floor of 40.
- **Do not quote Session H's McNemar p-values.** The test had no power; ADR-014.
- **Session pruning is closed as a QUALITY mechanism.** It remains a cost mechanism.
- **Turn-pair chunking is now MEASURED and small.** Ceiling +0.0087 fit / +0.0131 held-out. Its
  stated rationale is stale: 89.4% of gold is still user-authored, but rank 1 on failures is
  assistant-authored on only 5.3–7.5% of cases, not 47.1%. See M0c above.
- **A TOKENIZER WRAPPER IS NOT THE TOKENIZER.** `PreTrainedTokenizerFast` over the shipped
  `tokenizer.json` produced logits up to **3.56** from the raw `tokenizers.Tokenizer` the scored
  path uses — same file, same vocabulary, entirely plausible output. Twelfth instance of
  two-sides-silently-disagree. Anything scoring offline must use `tokenizers.Tokenizer` configured
  as `spike_cross_encoder.encode` configures it, and must assert against cached logits before
  writing.
- **A single 20% validation slice is not an instrument at this n.** It read one arm at +0.0435 that
  5-fold CV read at +0.0044 — 38 versus 37 of 46 queries. ADR-012. Use out-of-fold predictions over
  all 229.
- **The failure mode is only 58% same-session.** Any brief describing it as same-session
  discrimination is wrong by that margin.
- **The additivity read's subsumption rule is defective as registered.** Fix before reusing.
- **Trust propagation through a derived belief is STILL unexercised.**
- **The 230 → 229 denominator change must not be ignored in any cross-session comparison.**
- **Every poisoning ASR is 0.000 and VACUOUS.** K3 is the exception and still meaningful.
- **The maturation window is 6h and under tuning pressure. Do not adjust it to make a suite green.**
- **`retrieval_tokens` is a pessimistic estimate, not a token count** (3 chars/token).
- **`considered` costs a full-store scan per query.** ADR-003's live-only hot index removes it.
- **LongMemEval-S adapter verified 2026-08-02; LoCoMo still unverified.** We run **`cleaned`**.
- **LongMemEval-S penalises correct clock handling on 76 of 500 cases.**
- **The headline metric has never been produced.** No human label set exists.
- **The permission layer has no kernel backstop (ADR-002, revised).**
- **M1's §B13 suite must run on both native Windows Terminal and a Linux terminal emulator.**
- **Path scoping must be re-verified on BOTH platforms after any change to `scope/`.** Windows
  cannot run the symlink class without elevation; Linux never exercises the Windows pinning. A
  single-platform green is a half-measured wall. Both were run at the close of Session B.
- **`read`, `edit`, `find` and `bash` still have no executors** (Session C). Path scoping now
  admits a declared path, so a green traversal suite is evidence about the *checker*, not about
  filesystem tools that do not exist yet.
- **HP10's zero-config row is PARTIAL.** The library half is tested; **K6 — install → first useful
  output under five minutes in a clean container — is not measured** and lands in Session E. It is a
  milestone kill criterion, so do not let the passing library test be read as the criterion.
- **`TurnEvent` exists twice** — canonically in `marlowe-loop`, and the view-model copy now in
  **`marlowe-view`** (moved from `marlowe-stub` by C2d). Session E deletes the duplicate and points
  `marlowe-surface` at the real one. The two `BlastRadius` shapes (CONTRACTS §9's, and the rendered
  form) reconcile there. **C2d deliberately did not absorb this.**
- **The M2 report line said "a spawn with an empty tool set and reads_untrusted fails at load
  time".** It is the **non-empty** set that fails, per CONTRACTS §5; the empty set is the valid
  quarantined reader. Both cases are tested so the two cannot be confused.

## Open questions for the human

0. **FOUR PLACES WHERE UNTRUSTED CONTENT SHAPES A DECISION THROUGH A PATH NOBODY HAS LOOKED AT.**
   ADR-036 §5 established that the (action, target) question — *who chose the thing that determines
   the outcome* — applies where there is **no tool, no argument and no permission check**. That
   generalization was found in one domain and immediately implicates four others, none of which has
   been examined:

   | Where | The value untrusted content could shape | Why nobody has looked |
   |---|---|---|
   | **Ranking inputs** | query text and candidate text both reach the cross-encoder. A page that shapes a query shapes what is retrieved *and* what is injected | the rerank is treated as a quality mechanism, not a decision surface |
   | **Cache keys** | a key derived from attacker-influenced text lets one request's result be served for another | there is no cache yet — which is why now is when it is cheap |
   | **Memory derivation lineage** | `derived_from` is already a declared `Target` on `remember`, but the **harness-side** resolution of lineage during consolidation is not the same path | the tool argument is guarded; the internal path was never asked the question |
   | **Consolidation merge decisions** | whether two memories are *the same fact* is the identity question of ADR-036 §4, inside the memory system, on content that may be untrusted | it predates the framing entirely |

   **The tell they share:** each decides something using text whose author is not established, and
   in each the trust floor is either uniform or absent, so the latch cannot discriminate (see the
   CLAUDE.md ledger entry). This is a question rather than a finding — **none of the four has been
   confirmed exploitable and none has been confirmed safe.** Examining one is a session's work;
   deciding they are fine without looking is the failure this project keeps recording.

1. **HP14 has an experiment attached, not an answer** — needs a consenting cohort at M6.
2. **QA accuracy needs an API credential.** A key and a small HTTP client in `tools/`. Offline
   measurement over retrieval output only; an answer stage on the measured path is milestone drift.
3. **The human label set is your deliverable and it is now drawable.** See above.

## Built

**M2 Session A** — the spine. Three crates: `marlowe-tools` (manifests with load-time default-deny,
`ExposedSet` capped in its constructor, the eleven builtins, tool descriptions carrying a trust
class), `marlowe-permission` (`TaintSet` failing closed, the `(action, target)` check, egress with a
deliberately strict URL parser, a path scope that refuses everything, the adjudicator),
`marlowe-loop` (the one loop, `Budget`, `Run`, `CapabilityProfile`, the context assembler,
provenance, ephemeral spawn, `TurnEvent`). **375 tests, from 273.** ADR-022 through ADR-026. Six
paths added to the brief §13 hook and pipe-tested.

**M1 Sessions A–B** — the TUI and classic CLI against the scripted stub, closed at `ed25914`. K4
carried and met. ADR-021.

**M0b Session K** — the reranker ships. `rerank.rs` re-pinned to the fine-tuned f32 graph with a
named refusal for the superseded int8 directory; `cross_encoder_reference.rs` table-driven over both
vocabularies (**190 tests**, from 188); `analyze_cue_overlap.py` ranking lifted to module scope
(verified byte-identical); new `tools/publish_precision_coverage.py`; **three stale defaults
deleted** — `score_longmemeval.py --reranking` (defaulted to the *old* graph),
`session_j_verify_export.py --out-dir` (silently overwrote Session J's record), and
`make_cross_encoder_fixtures.py`'s hard-coded model. New: `docs/design/PRECISION-COVERAGE.md`,
`docs/design/M1-KICKOFF.md`, ADR-019, ADR-020, brief §5.7.1.

**Earlier:** A (workspace, contracts, journal, memory) · B (lexical cue, frozen gate) · C (dense
cue) · D (max fusion, **failed floor**, ADR-010) · E (per-query features, **failed floor**,
ADR-011) · F (consolidation, **null**, ADR-012) · G (query side measured, ADR-013) · H (cross-encoder
rerank ships, ADR-014) · I (sequence cap is a length normalizer, ADR-015) · J (ceiling never measured
quality / normalization null / fine-tuning is the lever — ADR-016, 017, 018).

---

### Maintaining this file

Update at the **end of every session**, before stopping. Keep it short — it loads every session and
competes with real work for context. Not a changelog; git has that. This file answers one question:
*what should the next session do first?*
