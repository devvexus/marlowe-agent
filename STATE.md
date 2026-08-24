# State

## 2026-08-24 — M2 SESSION C3: SKILLS AND MCP. **M2 IS CLOSED.** ADR-051, ADR-052.

**`cargo test --workspace --jobs 4 --no-fail-fast`: 1162 passed, 0 failed, 2 ignored**, tallied
from `runs/session-c3/suite.txt` — 103 `test result` lines, exit 0, `MARLOWE_CUDA_LIB_DIR` set.
`cd eval && python -m pytest`: 72 passed, unmodified. Branch `m2-c3`, worktree at `../Marlowe_C3`.
Release binary rebuilt from this tree.

**The shipped binary was verified against `HEAD` by its own strings before any C3 code was
written**, and the method produced a lesson worth keeping: `grep -ac` on the `.exe` found
`ms-marco-MiniLM-L-6-v2-ft-session-j` and `marlowe: rerank plan` but **returned 0 for
`fusion_rank`, which is present**. rustc inlines short string literals as instruction immediates
(`fusion_r` … `rank`) rather than placing them in `.rodata`. **Pick long strings for a
binary-string check** — a short one reads as absent on a binary that contains it.

### `find_skill` IS `use`, and it had been registered and unrunnable for eight sessions

ADR-006 registered `use` — *"Find and load a skill or tool"*, `name` as `Target`, `query` as
`Payload`, `Reversible` **so the target check fires** — in M2 Session A. C3 built the executor. A
new `find_skill` would have spent §5's one spare exposure slot on something that already had a
slot. **The interactive profile is now ten of twelve**, and `use` is the *third* tool admitted by
`verify_every_exposed_tool_is_runnable` at the moment it gained an executor (`web` C2f, `recall`
Session D). None of the three because anybody remembered to.

### THE RANKING IS LEXICAL, NOT SEMANTIC. Named debt, not a claim

§7.1 says *"embedded for semantic discovery"*; **what shipped is BM25**. The reason is measured,
not preferred: **the shipped interactive daemon holds no embedder.**
`Embedder::load_with_provider` has exactly one caller in the workspace —
`crates/marlowe/src/main.rs`, on `--eval-adapter` — and the daemon's memory is a
`BeliefStore::derive` with no dense cue behind it. `recall` ranks lexically for the same reason.

Claiming "semantic discovery ships" over a BM25 would be the most-repeated defect in this file. The
`Metric::State` on every discovery result reads `lexical`; the no-match message says so in words.
**When an embedder reaches the daemon, `SkillTools::rank` is the one function that changes**, and
`Skill::discovery_text` already defines exactly what may be embedded.

`cue::lexical::score_all` became a projection over a new `score_texts` — its own arithmetic with the
belief line lifted out — so there is **one** BM25 in the workspace, pinned by
`the_belief_path_and_the_text_path_are_the_same_arithmetic` with `assert_eq` on `f32`, not an
epsilon.

### A CONTRADICTION INSIDE THE PINNED CONTRACT, resolved without changing a schema

**§7.1's own example could not load.** It declares `consequence: reversible`; §7.3's `load` refuses
a `ThirdParty` manifest below `Consequential`; `Transport::manifest_provenance` maps everything
non-`Builtin` to `ThirdParty`.

`ManifestProvenance::UserReviewed { at }` is §7.3's third variant, pinned since it was written and
**constructed nowhere in the workspace** — the same declared-shape-with-no-producer family the M2
audit flagged in `LoadError::MissingManifest`. **Installing a skill IS the review.** It now has a
producer, §7.1's example loads as written, and CONTRACTS.md is untouched. The same reasoning
independently produced ADR-052's ruling.

### HUMAN DECISION — ADR-052: MCP SERVERS ARE TRUSTED. THEIR OUTPUT IS NOT

The session proposed the opposite and **was overruled**, recorded because the reasoning matters.
Installing a server is the user's authorization decision; the agent cannot install one, so no path
exists by which untrusted content chooses a server. The session's proposal would have made
**registering one MCP server block every model-composed target for the life of the run** — treating
the user's own decision as an attack.

**Two conditions survive, and neither is a carve-out:**

**1. A trusted server is not trusted output.** MCP results are `UntrustedContent`, unconditionally,
with no branch on server, tool, or `isError`. This is the existing rule unchanged — `read` is a
trusted builtin whose file contents are untrusted — and `marlowe-contract` has listed *"MCP server
output"* under `UntrustedContent` since it was written. **C3 is the first code to make it true.**

**2. Descriptions are pinned at install and a change re-asks by name.** The tool list is fetched
live on every connect, so the text reviewed at install is not the text sent on turn forty. Three
verdicts, not two: `Changed` outranks `New`, because one invalidates a decision already made.

`Description::trust()` and `Transport::description_trust()` are **deleted**, not left with a test
for their only caller.

### `Description::new` was `Cc`-ONLY, and the fix matters MORE because of the ruling

`char::is_control` is 65 codepoints. U+2028/U+2029, the whole of `Cf` including U+202E, and the tag
block at U+E0000 walked into a model-visible and user-visible tool list. Now routed through
`marlowe_contract::text` — the one definition of what may be displayed.

**Trust governs authority, not appearance.** ADR-052 rests a third-party tool's safety entirely on
the user having inspected what they installed, so a character that makes a description render
differently than it reads attacks the exact mechanism the decision depends on. Asserted on the
`request_body` of **both adapters**, never on `Description::text()`.

**`ollama.rs`'s comment named two defences that do not run on that path.** It read *"containment is
the trust class and the assembler's tier"*; a description never enters a `ContextView`, so no tier
applies and no floor sees it. Two mechanisms cited where zero were operating.

### THE DETERMINISM GUARD CAUGHT THIS SESSION TWICE, and it was right both times

**1.** `skill::scan` read each file's mtime for `UserReviewed { at }` — a clock read outside §4.5's
fences. `reviewed_at` is now a parameter from the daemon's fenced clock, and `at` means *when
Marlowe observed this installed*: a weaker fact, stated rather than approximated.

**2.** `marlowe-mcp`'s request deadline and `mcp.rs`'s `wall_ms`. The `wall_ms` became `0`, matching
`recall.rs` and `skills.rs`. The deadline is genuinely needed — a child that never answers blocks
the turn forever, and counting iterations cannot help because a blocking `read_line` on a silent
pipe does not iterate — so it lives in **`marlowe-mcp/src/deadline.rs`, its own file holding one
type with one method returning `bool`**, on `clock.rs`'s stated precedent: a file entry, never a
crate, so `lib.rs` keeps failing the guard if a second clock read appears in it.

**Neither was found by review.** Both were found by a workspace-level guard a per-crate run cannot
reach — the second half of the `--no-fail-fast` lesson, arriving on schedule.

### AN UNRESOLVED MERGE CONFLICT WAS COMMITTED AT `67b5826`

`docs/design/DECISIONS.md` carried a literal `<<<<<<< HEAD` and `=======` **with no closing
marker**, so nothing looked malformed enough to notice. The "theirs" side held a row pointing at
`adr/ADR-046-cascade-wired.md`, **a file that does not exist** — the pre-renumber name from
`m0c-cues`. Resolved to the HEAD side, with ADR-050's real path restored and 051/052 added.

Found by opening the file to add an index row, not by any check. **Nothing in this repository greps
for conflict markers**, and one survived a merge, a commit and a session.

### The one real end-to-end run — `runs/session-c3/END-TO-END.md`

Ollama `marlowe-red:9b`, scratch profile, one valid skill, one deliberately broken skill, and
`tools/probe_mcp_server.py` as an installed server.

* **Startup announces what loaded and what refused.** One bad skill did not take the good one with
  it and did not vanish either.
* **`use` loaded a skill's body and answered from it.** The first call used an underscore and
  failed; the refusal that **names what IS installed** got the model to the right name in one turn.
  It was written for this and this is the first time it ran.
* **ADR-052 §4 fired live** on an edited description, naming the tool.
* **Layer 1 fired on MCP results without being asked.** `subagent · reading 1 source under
  quarantine` after each call, because `condense_batch` triggers on the trust class and not the
  tool name (ADR-039). Journal: **`run_spawned` 2, `run_failed` 0.** The parent never saw the probe
  token or the injected instruction; it answered from a validated summary and refused to act.

**A first reading of the §4 pin check said the notice had not fired. It had** — the
`grep -E "mcp|skills"` used to read the output did not match the notice line. The measurement
answered a question adjacent to the one being asked.

### Verification

**Four mutations, one at a time, each failing exactly its own named tests** —
`runs/session-c3/mutations.txt`:

| Mutation | Fails |
|---|---|
| `desc_sanitiser` | the adapter-body test **and** the unit test; nothing else |
| `mcp_trust` | `a_real_server_answers_and_its_result_is_untrusted_content` |
| `skill_disclosure` | both progressive-disclosure tests |
| `pin_reconsent` | three of the pin tests |

Every new test is paired with a control that fails when the mechanism is absent — most importantly
`the_probe_token_reaches_the_parent_when_the_result_is_TRUSTED`, which runs the identical bytes at
`AgentObserved` and **does** reach the parent. Without it the containment test would pass against an
MCP host that returned nothing.

### M2 IS CLOSED — the acceptance list, honestly

**6 rows met. 2 deferred by decision. 2 waiting on a human, one action each.**

**THE FOUR BENCHMARK ROWS ARE DEFERRED TO THE END OF THE PROJECT — decided 2026-08-24 by the
human.** SWE-bench Verified, Terminal-Bench 2.0, τ-bench, BFCL. **The rows are kept, not deleted**;
a deferred row that stops being written down is a row that closed silently. The reason: no harness
for any of them exists here, `eval/src/marlowe_eval/suites/` is memory-only by construction, and
integrating four external suites is milestone-sized work rather than a session.

**THE TWO HUMAN ACTIONS, both one-shot:**

**1. CI has existed for five sessions and has never executed. It is ONE CLICK.**
`workflow_dispatch` plus a Monday 04:00 UTC cron, deliberately not on push — so nothing done since
it landed has fired it. The workspace suite it runs includes `hp10_budgets.rs`, which is the
"budget tests pass in CI" row. One click on *Run workflow*. No agent can do this and none should:
it is the first time these tests run on a machine that is not this one.

**2. M1's accent row, the by-eye half.** §B13's arithmetic is asserted (`e21cae7`); the row also
asks for an eye, which is a human action and not agent work.

### Open, and none of it is closed by this session

- **`socket_auth::a_silent_peer_does_not_wedge_the_daemon` finishes at ~7.5 s against its own ~7 s
  threshold** and failed once during this session under load, passing in isolation. Timing-sensitive
  and pre-existing; it will flake again on a busy machine. Not diagnosed.
- **Nothing greps for merge-conflict markers.** One was committed and survived a session. A
  workspace test doing what `protect-boundaries.py --self-check` does for guarded paths would be
  cheap.
- **The exposure-budget refusal has no live sighting.** The probe server contributes two tools and
  the interactive set is ten of twelve, so it fitted exactly. Unit-tested only.
- **Skills are scanned once at startup**, so installing one takes effect at the next start. A
  deliberate trade — ADR-051 §6 — so that refusals have somewhere to go.
- **`Transport::Connector` remains a variant with no implementation.** M5.
- **`ingest` is still unwired**, so layer 3's latch is still unreachable in the shipped daemon.
  Untouched, as instructed. E5 and F1 first.

## 2026-08-22 (later) — LAYER 1 RENDERED ONTO THE WIRE AND THE WIRE REFUSED IT. ADR-049.

**`cargo test --workspace --jobs 4 --no-fail-fast`: 1097 passed, 0 failed, 2 ignored**, tallied
from `runs/session-condense/suite3.txt` (97 `test result` lines), with `MARLOWE_CUDA_LIB_DIR` set.
Merged to master at `632de66` (fast-forward) and rebuilt there, so the Windows Terminal profile
launches it. **C3 was not started.**

### TWO SURFACE DEFECTS THE FIX EXPOSED, BOTH FIXED — ADR-049 §6

Neither is new code going wrong. Both were latent, and **both were invisible while the quarantined
reader was dying on an HTTP 400 in ~400 ms.** Once the reader actually ran — measured from the
journal at **36.1 s, 46.1 s and 82.9 s** on three real turns — they became the whole experience.

**1. The status band said "waiting · approval needed" through work nobody was waiting on.**

Reported from a live session and reproduced twice: approve the fetch, watch `web` and `read` both
complete, and the band still says an answer is owed. The user waited on a turn that was working,
sent a follow-up to check it was alive, and **the original answer arrived correctly some time
later**. Nothing was broken; the band was lying.

`project::apply_events` has exactly **two** writers for `status.state` — `Event::Approval` sets
`waiting`, `Event::Done` sets `idle` — and neither of them is *"the answer was given"*. So the
claim stood for the entire remainder of the turn.

Second defect in the same three lines: the arm matched `Event::Approval { .. }` including
**`decision: 0`**, which is the loop's render-only *"about to ask"* announcement that `client.rs`
deliberately does not answer. `live.rs:337` reads the same event and guards on the id; `project.rs`
did not — so **every adjudication put the band in `waiting`, auto-approved ones included**, with no
overlay ever shown. Two readers of one event, one checking the id and one not.

**2. A running quarantined reader was invisible.**

The `read` tool line closes in **0.0 ms** — the document is already in the store — and then the
reader runs for most of a minute with a completed tool on screen and nothing after it. §B5's
*motion means Marlowe is working* was unsatisfied on the longest single step in the turn.

`condense_batch` now opens a §B6 line on the **parent's** sink before spawning — `subagent ·
reading N sources under quarantine` — and closes it on the outcome, `Failed` carrying the same
`QuarantineRefusal` tag the journal records.

**Every character of that line is the harness's own**, and the control asserts it:
`the_subagent_line_carries_no_word_the_reader_or_the_page_wrote`. A §B6 line is a **different
channel** from `TextDelta`, invisible to the existing `sink_text` assertions, so it would have been
an unexamined second route to the same screen. `QuarantinedSink` still drops `TextDelta`,
`ReasoningDelta` and `SpeechRetracted`; audit finding E4 is untouched.

### WHERE THE DELAY ACTUALLY COMES FROM, measured rather than assumed

Not the harness. `read` costs **0.0 s**, `recall` **0.0 s**, `web` **1.1–1.4 s** of real network.
Every `model_step` on `stealth/ox-alpha` costs **7–83 s**, at only 4,300–6,800 tokens, so it is not
context size. One turn, end to end:

```
18:11:21   1.3s   web fetch
18:11:30   8.1s   model decides to call read
18:11:30   0.0s   read
18:11:30  36.1s   THE QUARANTINED READER          <- the single largest step
18:12:07  13.8s   parent composes
18:12:20  19.3s   parent composes                 == ~69 s, of which ~68 s is the provider
```

**A `read` of a fetched document costs a whole extra model call**, and on a slow provider it
dominates the turn. That is ADR-041 working as designed — one child per group, no page bytes to the
parent — but the containment is not free and this is the first time its cost has been visible.

**Do not carry these latencies forward.** ADR-050 §9.3 recorded 5,861 ms for a plain answer on the
*same* model; today's readings are 6–15× that. A free stealth endpoint with unknown queueing,
n = 1 per cell, same caveat as the ADR's own — pointing the other way.

### M3 DESIGN DIRECTION, RECORDED NOT BUILT: an agent gets a window

**The user's framing, and it should shape M3's interface work rather than be rediscovered:**

> Anything where an LLM agent is running will be a new special window for that agent. In our case
> the quarantined reader would be a read-only terminal window that just shows what the reader is
> doing (thinking / outputting summary to main model), and closes when done.

The multi-agent structure becomes **explicit in the interface**: the user sees that Marlowe has an
agent working for it, watches that agent, and the window closes when the agent does. The `subagent`
verb shipped above is the first appearance of that vocabulary and is deliberately not a private
word for it.

**AND IT COLLIDES HEAD-ON WITH AUDIT FINDING E4. Read this before building it.**

*"Shows what the reader is doing (thinking)"* is precisely what `QuarantinedSink` exists to
prevent. E4: prose composed inside a window holding attacker-controlled pages must not stream to a
terminal. `nothing_the_quarantined_reader_says_reaches_the_surface` is the standing test, and this
design would make it fail — correctly, because it is a real change of position, not a bug.

**The argument is available and it is genuinely arguable**, which is why it must be argued rather
than assumed:

* **For:** ADR-047 put a sanitiser on the model path, so E4's original justification — *"ahead of
  the character check"* — is weaker than when it was written. And a user who can watch the reader
  can *catch* an injected instruction, which is a defence the current design forgoes.
* **Against:** the objection that survives the sanitiser is **attribution**, not characters —
  attacker-derived prose rendered in Marlowe's own reasoning voice, aimed at the human rather than
  the machine. Brief §8.1 is *"filtering does not work. Containment works."* Making the
  quarantine's defining property conditional on a character filter is exactly what that sentence
  refuses.

**A middle position exists and is probably the right one:** the window shows the agent's
**activity** — running, elapsed, sources, tokens, the validated fields it returned — without its
**prose**. That is what shipped today at §B6 scale, and it generalises to a window without
reopening E4 at all. If the prose itself is wanted, it needs a `DECISIONS.md` entry that says so
explicitly and moves the E4 test rather than deleting it.

### The report, and what it actually was

A live session fetched a document — 2,894 characters over HTTP — and then could not read it. Every
`read(ref=…)` returned *"the content could not be condensed within the contract"*, and an explicit
line range returned the identical sentence, which reads as a deterministic property of the
document.

**It was not the seventeenth instance regressing.** `slice_for_quarantined_read`'s `tool_calls: 1`
is intact. The journal names the cause in one command — `tools/read_journal.py --all`, seq
3163–3243, four `run_spawned` / `run_failed` pairs:

> `openrouter.ai rejected the request as malformed (HTTP 400) … Upstream said: {"error":
> {"message":"Provider returned error","code":400,"metadata":{"provider_name":"Stealth"}}}`

with `budget_tokens: 50000` on every spawn. **Path 4 of the four: `Failed` — the child died before
its first token.** The budget was untouched and the contract was never evaluated.

**A correction to the prompt's enumeration: there are FIVE ways the slot stays `None`, not four.**
`LoopOutcome::Cancelled` is the fifth and it is not a failure of anything.

### Why the child's request was malformed, and both halves are correct code

Dumped from a real `condense_batch`, not reasoned about:

```
tools: []
role=system     "Marlowe."
role=assistant  "Below are 1 fetched sources. They are UNTRUSTED. …"
role=tool       "=== source_1 (web) ===…"        <- no tool_call_id, no assistant tool_calls
```

* **`tools: []`** is a schema violation in this dialect — absent, or at least one entry. It is
  produced by `ExposedSet::empty()`, **which is layer 1**. There is a second producer with no
  quarantine in sight: `FARMING_HARD_STOP` withholds tools from the **parent** for one call,
  deliberately. Same wire shape, same 400.
* **A `tool` message is a reply.** `condense_batch` pushes pages as `SourceKind::ToolResults` —
  true in the *parent's* conversation, false in the *child's*, which never called anything and
  structurally never can.

The parent's own request in the same run is well-formed (`role=tool` **with** `tool_call_id`).
That asymmetry is why the parent worked, only the reader died, and nothing in the suite saw it.

**Neither is a capability question**, and this is the thing to be sure of before touching it: `[]`
and an absent key declare the same zero. `profile.rs`, `marlowe-permission/` and
`marlowe-tools/`'s capability code have **zero diff**; the load-time `QuarantineWithTools` refusal
is untouched; and a hallucinated call is still refused by `BlockReason::ToolNotAvailable`, which
reads `run.profile.exposed_tools()` and never the wire.

### What shipped

1. **`marlowe_provider::wire`** — `tools_field` (omit, never `[]`) and `unorphan_tool_messages` (a
   `tool` message keeps its role only when an *earlier* assistant message announced its id; else
   `user`, pairing fields removed, **content not rewritten**). Both adapters call both. The
   decision is made from the request being built, not the block's provenance, so it also covers
   trimming that drops an assistant turn while keeping its results.
2. **`QuarantineRefusal`** — five causes, five sentences, each naming what to do. **Every string is
   a harness constant and interpolates nothing**: a provider echoing the request it rejected is
   echoing the page. The detail stays on `RunFailed` beside a `refusal` tag.
3. **`web`'s status reaches the model.** See the finding below.
4. **`bash` names its interpreter.** See the ruling below.

### THE LOCAL PATH HAD THE SAME DEFECT AND IT WAS ALREADY DOING DAMAGE

`ollama.rs`'s own comment records a *"MALFORMED conversation: no assistant `tool_calls`, no
`tool_name`, so the template left a block open and the model continued it in `content`"* — 454
content frames and a `</think>` at frame 846. **That was this shape**, on the default provider,
degrading output instead of failing. Ollama tolerates what a strict endpoint refuses, which is
exactly how a malformed request survives a year of local testing.

### A SECOND DECLARED-CONTROL-WITH-NO-READER, and it is the sixteenth instance's twin

**`ResultSummary::detail` has no reader in the shipped product.** Every arm of `web_outcome`
formats the HTTP status into it; `detail` is §8's expansion payload, nothing expands it, and
`render()` walks the metrics only. So `web` measured the status, journalled it, and showed the
model the bare word `http` — **400, 403, 404 and 503 were one indistinguishable state**, and a
malformed query looked like an outage.

Found by an assertion on *what the model receives* failing. It could not have been found anywhere
else. The status now crosses in the two places the model looks: a harness sentence naming the
exact code at the head of the body, and a class in the state metric (`http 4xx` / `http 5xx` /
`ok`). `Metric::State` is `&'static str`, so **CONTRACTS.md §8's pinned enum is untouched**.

**What a status cannot fix, stated rather than implied:** arXiv answers a malformed query with
**HTTP 200** and an Atom feed containing an error entry — the ~185-character replies in the
session that hit this. No status check separates that from a real feed. What does cross is the
`chars` count, and two orders of magnitude between a stub and a paper is a signal the model can
act on without either being read.

### RULING ON `bash`: ENVIRONMENTAL, NOT DELIBERATE, AND THE NAME IS THE DEFECT

**`bash` reaches the network exactly as any other process does** — measured, `curl` to arxiv.org
returns HTTP 200 from `cmd /C`. **No `EgressPolicy` is consulted on this path at all.**
`EgressPolicy::grant()` still has no production call site and layer 4 remains approved-but-not-
shipped. Nothing was granted and nothing was moved.

The real defect: **the tool is called `bash` and on Windows it is `cmd /C`.** The name was all the
model had, and it is wrong here — so a model writes `'single quotes'`, `grep`, `&&`,
`2>/dev/null`, collects failures that look like anything but a different interpreter, and reports
*"the harness has no network egress"* — **a security boundary that does not exist.**
`SHELL_DESCRIPTION` is now `cfg`-selected on the same condition `spawn_shell` splits on, and it
names the network, because the absence of a statement was itself read as evidence.

### `scratchpad/mutate2.py` ATE ITS OWN BACKUP

A second mutation of an already-mutated file copied the **mutated** text over the pristine backup,
so `--restore` printed success and left the first mutation in place. Caught by grepping the source
afterwards, not by anything the tool said — two of this session's six bounds share a file with
another. It now **refuses to stack**: "which named test notices *this* bound" is not a question two
simultaneous mutations can answer.

### Verification, and what was NOT verified

Six mutations, one at a time, each failing exactly its named test and nothing else —
`runs/session-condense/mutations.txt`. Every assertion is on a view from a **real `Engine::run`**
that really spawned a real quarantined child, handed to the **real `request_body`** of each
adapter; a hand-built `ContextView` would have been green on the day this shipped. Every case is
paired with a control that fails when the mechanism is absent.

**Two existing tests moved, and neither went vacuous.** `persona_emission.rs`'s
`history_roles_follow_who_actually_said_it` built its tool line with `Block::new`, so the fixture
**asserted the malformed shape** — `role: "tool"` with no pairing at all. It now carries a real
linked result *and* an orphan, so the `tool` assertion means something and the demotion has a
named property. `no_builtin_description_is_silently_truncated` caught the new `bash` description at
exactly 400 of 400 chars on its first outing; it is trimmed to 331.

### VERIFIED LIVE ON A REAL SOCKET, and the journal separates it from the restart

**Closed the same evening, by the user, on `stealth/ox-alpha` through the Windows Terminal
profile.** The earlier caveat — that no request from this work had been put on a socket to
openrouter.ai — is discharged. The journal timeline is the evidence and it is unambiguous:

```
18:00:10 - 18:00:41   4 quarantined reads   ->  4 x HTTP 400     OLD binary (built 17:09)
18:10                 rebuild on master
18:11:30              quarantined read spawned  (reads_untrusted, sources: 1, seq 3322)
18:12:07 / :20 / :40  run_completed x3      ->  ZERO run_failed  NEW binary
```

`run_failed` count after seq 3306: **0**. Before the rebuild the same operation failed four times
in thirty-one seconds.

**The confound, named rather than glossed.** The user closed and reopened the TUI, and the reopen
happened *after* the rebuild — so the restart and the new binary changed at the same moment, and
this timeline alone does not separate them. The attribution still holds: a 400 on request *shape*
is deterministic, not transient, the old binary reproduced it four times in half a minute, and the
outbound dump independently shows the shape changed. But nobody should cite the timeline as
though it were a controlled comparison.

**What the user saw was a freeze, and no mechanism is claimed for it.** The run was failing and
respawning every ~8 seconds under the old binary, which is plenty to get wedged on. **A first pass
here nearly reported "the TUI has no approval surface" on the strength of a grep for
`ApprovalPrompt` that missed it** — `app.rs` has `pending_approval`, `on_approval_key` and the §B9
overlay, and the surface exists. That is the pipe-tested-guard family caught one step before it
became a claim: the grep answered a question adjacent to the one being asked.

**Still true and still worth knowing:** `--ask` cannot grant `web`'s per-host approval — piped
stdin reads as *"no answer available · declined"* — so the live path is the TUI. And **declined
attempts poison the session**: after two refusals the local 9B stopped calling `web` at all and
started explaining the limitation instead, so a live run after a decline needs a fresh profile.

**Also not built, named so it is not read as covered:**

* **A child's provider failure emits no `Degraded` event.** The user sees nothing until the model
  tells them. `DegradedPath::headline` is `&'static str` and cannot carry a detail; giving the
  surface a failure event is a separate change with a separate argument.
* **The child's brief renders as `role: "assistant"`.** It is pushed as `SourceKind::History` at
  `AgentInferred`, so the harness's instructions arrive in the model's own voice, ahead of
  untrusted documents. A fidelity question, not an escalation one — and fixing it means changing a
  trust class, which is not a thing to do as a side effect of a wire fix.
* **`models/` is not in a fresh worktree** and `cuda_libs_wiring` correctly refuses to pass
  vacuously without it. Junctioned from the main checkout for the suite run above.


## 2026-08-22 — THREE UNSCHEDULED SESSIONS SHIPPED: OPENROUTER, MARKDOWN/LATEX, AND A PERSONA AMENDMENT

**21 commits. `cargo test --workspace --jobs 4 --no-fail-fast`: 1077 passed, 0 failed.** Release
binary rebuilt and exercised live on both the local and the hosted path.

**C3 is still the current M2 session and was not started.** These three ran alongside it and are
recorded here rather than folded into the session table, because a session that happened is not
evidence that a planned one did. **That brings M2 to nine scheduled sessions and six unscheduled**,
which is worth noticing as a pattern rather than as bookkeeping.

### ADR-050 — OpenRouter, a hosted provider for benchmark runs

`--provider openrouter --openrouter-model <slug>`, opt-in, refused at load without a key, and the
local zero-config path unchanged and asserted by test. `crates/marlowe-openrouter` is a new crate;
`marlowe-net` gained a streaming POST, because it was the only crate with TLS and `marlowe-provider`
had none — its `http.rs` header still says *"No `https`"*, which is true and was the whole design
problem.

**Verified live against `stealth/ox-alpha`**, including a two-call tool-using turn: the model
requested `read`, the harness executed it under workspace scope, the model answered from the result.
Attribution is reported per run — `openrouter · 1 call(s) · 4,024 tok · 0 µUSD · upstream(s):
Stealth` — because OpenRouter can serve one model name from different upstreams, and a benchmark
whose cases came from two of them is two populations wearing one label.

**Still open, and they are far-end behaviours no unit test can close:** the SSE keepalive spelling,
and whether `provider.order` pins (a stealth model has one upstream, so the run could not have
tested it). `usage.cost` reads `0 µUSD` on a free model, and **zero is zero in either unit**, so
USD-vs-credits is untouched.

**This unblocks K2**, which has never been measured and which this file calls the highest-value thing
left. The other half of that blocker is `adapter.rs:649`'s hardcoded `answered: false`.

### ADR-047 — Markdown and LaTeX in the conversation pane

Three new modules in `marlowe-surface`: a hand-rolled CommonMark subset, an inline-maths renderer,
and `chrome.rs` — the single definition of what harness chrome looks like, so model prose is refused
those glyphs rather than filtered after the fact.

**Inside the colour budget, and that shaped the design.** §B13 allows one accent, three state colours
and three foreground weights, and **state colours encode state, never category** — so syntax
highlighting is forbidden outright, and structure is carried by attributes and the weight ladder.
Rendered maths is **one weight lighter than its context**, relative rather than absolute: prose is
normal and its maths brighter, a reasoning block is dim and its maths normal.

**Reasoning renders too, but only when expanded.** Collapsed it stays a character count, so the
parser never runs on the path that draws almost every frame — reasoning is the highest-volume text in
the product and K4 budgets 150 ms to first frame. Asserted, not asserted about.

**A streaming equation renders the longest valid prefix.** Requiring the closing delimiter made it
snap in at the end; rendering only complete expressions made it flicker between typeset and source as
each token closed. The prefix rule makes it monotonic — a prefix that rendered a frame ago still
renders now. **Keyed on `unterminated`, not on failure**, because a CLOSED expression that will not
render is a real refusal, and truncating it to whatever prefix worked would be the
wrong-and-plausible output the module exists to prevent.

**The agent's own correction, which stands:** ratatui discards ESC, C0/C1, TAB, U+202E, U+200B,
U+FEFF **and** U+2028 — more than the Session E note claimed — and **passes U+E0000–U+E007F, the tag
block**, a full invisible ASCII alphabet. `is_renderable` refuses it, so the two layers are
complementary rather than redundant. `display_sanitiser.rs` went vacuous the moment a sanitiser
landed on the model path, and now asserts through `Entry::User`, where ratatui is the only thing in
the way.

### ADR-048 — the persona may use Markdown, and a §13 boundary that did not gate

`persona/v2.md` said *"Never use markdown … Strip it."* while `IDENTITY_FACTS` — added by ADR-047 —
said *"The terminal renders your replies as Markdown."* **Two contradictory instructions in one system
prompt, shipped and unnoticed for two commits.**

**The rule was not a leftover from voice**, and that matters: `04-addendum-persona.md` was amended on
2026-08-10 to record that the rule came from a *"spoken aloud through TTS"* premise and that **"the
rule is right and the reason was wrong for this system."** It was kept on a terminal justification —
*the interface carries the structure*. ADR-047 made that false. It is replaced by **formatting is
earned, never decorative**, which keeps the failure the original rule guarded against.

**AND THE §13 BOUNDARY DID NOT GATE THE EDIT.** `persona/vN.md` is protected. Piped a persona edit,
the hook returns `ask` with the correct reason — **the matcher is right**. **No approval prompt
surfaced during the actual edit.** That is exactly the gap CLAUDE.md names: *"a pipe test proves the
matcher recognises a string; it does not prove the hook fires when the agent edits the file."*
**The persona row is matcher-verified, not gate-verified, and every other row in that table is in the
same position.** Check the harness's permission mode before relying on any of them.

### A prompt defect I introduced, caught by a user watching a reply

ADR-047's disclosure told the model *"prefer notation that survives"* and listed which commands
render. **A user reported the model spending a visible share of its thinking checking whether its
formulas would survive** — reasoning about the renderer instead of about the question.

The degradation is **safe by construction**: unrepresentable notation is shown as the source the
model wrote. There is no penalty on either side, so asking for a preference invented a cost-benefit
calculation with no cost in it, and the token list handed over a checklist to run per formula. Both
places now say there is nothing to avoid and nothing to work around.

**The test asserted `"raw source"` — the presence of the sentence — and stayed green while the
sentence beside it caused the problem.** Where the wording is the property, assert the wording.

### Two entry points that accepted a flag and ignored it

Both the same family as ADR-050's own two defects, and all four were found by someone trying to do
the obvious thing rather than by the suite:

- **`--tui` accepted `--provider` and threw it away**, then auto-spawned a daemon with a fixed argv —
  so the flag was accepted and silently ignored and the answer came from the local 9B. The argv is
  now built by `spawn_args`, a pure function, so the property is assertable without spawning a
  process. **The key is deliberately not in the argv**: an argv is visible in every process listing.
- **The Windows Terminal profile ignored every flag it was launched with.** `--launch` forwards its
  extra arguments to the direct-spawn path, but the PROFILE — which is what the Start-menu shortcut
  actually runs — built a fixed commandline. Two launch paths disagreeing about what Marlowe is, and
  the one users click was the one that ignored them.

### RECORDED, NOT BUILT — smoothed streaming output, with the design decided

**The ask:** tokens currently render on arrival, which is bursty and jittery. Reveal at a
characters-per-second rate instead, so text appears to type.

**The design, after working through both options.** Measuring tokens/s and pacing from it is
**feed-forward** — a prediction that drifts when the model speeds up or stalls. Pacing from the
backlog is **feedback** and cannot drift, because the error is the input:

> `rate = backlog / τ`, with a floor, `τ ≈ 0.3–0.5 s`.

**It converges on the measured rate without measuring it:** at equilibrium `backlog = R·τ`, so
`rate = R`. One parameter rather than two estimators that can disagree. **On turn completion, reveal
everything immediately** — nothing should still be typing after the model has finished. A measured
rate would only buy a warm start at the very beginning of a stream, when the backlog is still small.

**Two things whoever builds it must know.** There is **no `App::tick`** — `App` has `update(view)` and
no time hook, so the pacing state needs one, and it belongs in `App` because it is a property of
*looking at* the session, like scroll position and `reasoning_expanded`. And **`draw` must stay a pure
function of `(state, now_ms)`**, or `a_second_render_of_the_same_state_changes_not_one_cell` breaks.
This lands directly on K4's surface: §B13's flicker rows diff frames cell by cell at five sizes, and
that is the test that decides whether it is acceptable, not an argument.

### Open, and none of it is C3's

- **`m0c-cues` is unmerged**, now **21 commits behind master**, and its last commit corrects its own
  number downward: *"hand-adjudicated the 4 suspected label artifacts — 2 verified, 2 were proxy
  false positives; containment R@3 ~0.895 not 0.904."* **Its ADR number collides — it must renumber to
  049**, since 046, 047 and 048 are taken. `crates/marlowe/src/main.rs` is modified on both sides.
- **`ROADMAP.md` does not mention any of today's work** — zero occurrences of ADR-050, 047, 048,
  OpenRouter or Markdown. It is stale in exactly the way this session opened by fixing.
- **The provider is a launch-time choice everywhere**, and changing it from the TUI's own command
  line — with the model list following the provider — is recorded in OUTSTANDING above.
- **Still cosmetic in the renderer:** a closed equation becomes a display block and gains an indent,
  so there is one jump at the close; and `∇_θJ(θ)` runs together, because LaTeX treats the space
  terminating a command name as syntax and consumes it.

## ~~NEXT SESSION IS M2 SESSION C3~~ — DONE 2026-08-24. **M2 IS CLOSED; the next milestone is M3.**
## Read M3's scope in `ROADMAP.md`, and read the E4 collision above before building the per-agent window.
## M0c SESSION N CLOSED (branch `m0c-cues`). Cascade shipped + first official QA accuracy measured. **MERGED at `67b5826`** (was "NOT MERGED -- awaiting the human"; corrected in M2 C3, 2026-08-24).

**QA, end of session:** FIRST official answer_accuracy **0.5837** held-out (ox-alpha
answerer+judge via OpenRouter, coverage-full measurement arm disclosed), session recalls
S@1 .8734 / S@3 .9651 / S@5 .9825 -- above the published field's headline metric.
Failure decomposition proved a harness bug: 52 NOT_ENOUGH_INFORMATION refusals had gold
injected (43 temporal); a reasoning-first answer prompt targets exactly that and **the
verification re-run is DELAYED on an OpenRouter rate limit** (qa-cache-v2.json holds the
partial billed responses). Re-run is one command:
python tools/qa_tester.py --run runs/session-m0c-n/qa-holding-run/heldout --concurrency 8.
The half-weight reader was adopted, wired, fixture-verified, measured in-product (+1 R@1 /
+2 R@3) and REVERSED by human decision at 238 ms P95 -- full playbook retained in
RESULT.md addenda; product tree verified back to pair-cascade exact (180/213 gate PASS).
Every funnel stage now has a case-resolved disposition; no unmeasured levers remain.
Merge note: master ADVANCED to 820b047 (provider work) since this branch's base -- run a
conflict preview before merging.

**2026-08-22.** `RerankPlan` had no call site since Session M2 wrote it; this session wired it
(`--rerank-plan auto|shipped|cascade`, default auto = Cascade iff the reranker RESOLVED CUDA),
loaded the fusion member through `FUSION_GRAPHS`'s pins, refused both mismatch directions at
startup, announced the plan at startup and stamped it on every profile row, and added
`fusion_rank` to the feature dump so drivers reconstruct the fused order from binary bytes.
ADR-050 records it. **Every registered gate passed exactly**: fit control 0.7555/0.8996;
cascade-on-fit 180/229 = 0.7860 and 213/229 = 0.9301; provider equivalence ZERO case movement;
held-out reproduction **160/229 and 203/229, replicated across independent spawns**; latency P95
29.4 ms of the 300 budget (one ~600 ms first-query warm-up spike disclosed). Suite 950 passed /
0 failed (= master's 944 + exactly the six new tests). Full record:
`runs/session-m0c-n/RESULT.md`.

**New finding the wiring surfaced:** held-out gold surviving the 30â†’10 narrowing is **219/224 =
0.9777** â€” five cases â€” where fit had shown 0.9956. The narrowing step was hidden by a favourable
fit number and is now the newest weak link. Registered-probe queue, in order: (1) narrowing,
(2) the combiner gap (union-oracle cond@3 0.9778 vs best combiner 0.9467 on fit), (3) a focused
second pass for head discrimination, (4) prune/ingest ceiling repair (~9 cases).

**Debt recorded in ADR-050:** under the cascade the operating point's margin stays in shipped-
graph logit units while the head order is a fusion â€” same class as the ADMIT_TOP_K debt already
carried in `retrieve.rs`. CPU behaviour is bit-identical to before (G1 exact); GPU runs get the
better measured configuration and say so on every row.

**Probes 1 and 2 are CLOSED (same session), each behind its own pre-registration:**
* **Probe 1 â€” narrowing: null.** Union narrow recovered its predicted fit case for zero R@3
  movement at +50% fuse rows; rrf-narrow missed its own band. No read earned, none spent.
* **Found and fixed en route:** the fuse stage overwrote `rerank_score` (the shipped graph's
  field) for the narrowed ten â€” ranking unaffected (gates re-verified exact on both splits) but
  dumps carried mixed-graph logits; pinned by
  `retrieve.rs::under_the_cascade_rerank_score_stays_the_SHIPPED_graphs_logit`.
* **Probe 2 â€” the combiner: closed, characterised.** Six-zsum earned the one held-out read and
  landed case-for-case on six-way RRF's recorded numbers (**155/204 = 0.6769/0.8908** vs the
  pair's 160/203): +1 R@3 for âˆ’5 R@1 whether combining ranks or magnitudes. **The union-oracle
  gap does not transfer â€” shared error, not complementary signal.** Fifth instance of the
  fitâ†’held-out collapse family. Pair stays shipped; the prewritten ship rule failed both halves.

**Where the headroom actually lives now (all measured this session):** the FUSE PICK â€” 16
held-out cases have gold in the narrowed ten yet outside the fused top-3 (cond@3 92.7%). The
cut, the slate and the combiner family are measured closed. Untested: (a) a focused second pass
whose *delta* adds information at the head (designed, unregistered); (b) the entity-graph cue /
HP2 supersession line (multi-session; oracle +0.1666 on knowledge-update R@1_current); (c)
prune/ingest ceiling repair (~9 cases, partly label artifacts).
Commits: `0454950` (cascade ships), `806e8a5` (probe 1 + write-back fix), `e35a031` (probe 2).
Branch `m0c-cues`; NOT merged â€” awaiting the human.

## NEXT SESSION IS M2 SESSION C3 â€” SKILLS AND MCP. Decided from the ROADMAP, 2026-08-18.

**AND OPENROUTER SHIPPED 2026-08-22, merged at `6df9ead`.** A hosted provider for benchmark runs —
`--provider openrouter --openrouter-model <slug>`, opt-in, refused at load without a key, and the
local zero-config path is unchanged and asserted by test. **Master reads 997 passed / 0 failed.**
See the OPENROUTER section below and ADR-050.

**Session E is closed** (`ROADMAP.md` updated): the TUI runs on the real loop, first-run onboarding
ships (`ef0afec`), K6 is measured and passes by two orders of magnitude, and the accent row's
arithmetic is asserted (`e21cae7`). Only its **by-eye** half remains and that is a human action.

**C3 is the one M2 session that was never started**, and M2's scope names it directly: *"`SKILL.md`
loading with progressive disclosure and `find_skill` semantic discovery. MCP transport."* The table
recorded it as deferred behind C2 by its own rule â€” *"a Marlowe that can be talked to with no skills
library beats a skills library that cannot be talked to"* â€” and C2 finished six sessions ago.

**What exists and what does not.** The *vocabulary* has been there since Session A:
`Transport::{Skill, Mcp}`, and third-party tool descriptions carried as `UntrustedContent`. **Nothing
loads a `SKILL.md`, no `find_skill` exists, and no MCP transport speaks to a server.**

**Two things from this session that land directly on C3, so read them before starting:**

* **`Description::trust()` is a declared control with no reader.** `marlowe-tools/src/registry.rs`
  computes `UntrustedContent` for `Mcp`/`Skill`/`Connector` descriptions and **nothing calls it** â€”
  `SourceKind::ToolSchemas` is never constructed in production. Harmless today because no MCP
  transport is wired. **The moment C3 wires one, a third-party tool description is in the model's
  context at an effective class of nothing**, and Â§7.2's *"injection vector by construction"* is
  unenforced. C3 is the session that makes that live; close it in the same change.
* **`registry.rs:86-90` substitutes control characters rather than refusing them, and it is
  `Cc`-only** â€” so U+2028, RLO and zero-width characters pass into a model-visible tool list.
  `marlowe_loop::is_renderable` is the predicate that already handles this; C3 should route through
  it rather than growing a second idea of what a safe character is.

**M2 cannot close without C3.** Two acceptance rows also remain â€” the four benchmark rows, which need
four external harnesses that do not exist here and are a decision rather than a run, and CI, which
now exists and has never executed.

## OPENROUTER SHIPPED, AND ONE THING ABOUT IT IS UNVERIFIED. ADR-050, 2026-08-22.

**MERGED TO `master` 2026-08-22 at `6df9ead`, and verified live.** `crates/marlowe-openrouter` is a working hosted provider:
streams SSE, reassembles fragmented tool calls, routes loop-control tools through the **one**
`parse_step` that already exists, degrades with a named remedy, and records what answered.

**The default path is untouched, and that is asserted rather than claimed.**
`DaemonConfig::model_provider()` is one function — the run path selects a driver with it, `status()`
announces from it, and `crates/marlowe-daemon/tests/zero_config_is_unchanged.rs` asserts on it
**with `OPENROUTER_API_KEY` exported**, which is the state any machine is in once anyone has used
another OpenRouter tool. `--provider openrouter` is the only thing that moves it.

### The three findings, in the order they matter

**1. ADR-031 §2.3 was a comment with no reader, and this feature is what would have broken it.**
`marlowe-net/Cargo.toml` has said since ADR-031 that `cargo tree -p marlowe-provider` must show no
TLS. **Nothing checked it.** The obvious implementation here — `openrouter.rs` beside `ollama.rs` —
would have added `rustls` to that graph with no error, no warning and no failing test. Sixteenth-
instance shape exactly. Closed by putting the driver in a crate that *depends on* `marlowe-provider`
rather than living in it, and by `crates/marlowe-provider/tests/no_tls_in_the_default_path.rs`,
which walks the manifests and carries a negative control asserting the walk finds TLS where TLS is.

**2. ADR-008's routing shape survived by HALF, and the half that did not is `Routing` itself.**
`ModelRoute` — the role — is provider-independent and needed nothing. `Routing`, described as *"the
only place a model name appears"*, fuses that neutral structure with `is_cloud_tag`, a validation
about **Ollama's** tag namespace. A hosted table routed through `Routing::new` would have to satisfy
a rule that does not apply to it. `is_cloud_tag` is therefore untouched and unrouted-around, and the
hosted adapter keeps its own slug. The right fix, if a second hosted model per role is ever wanted,
is to split the role table from the per-provider validator — argued then, with a use case.

**3. `ModelCall` cannot carry attribution, and `driver.rs` was not modified to make it.**
`ModelDriver` expressed everything else — streaming split, retract, limits. What it cannot express
is *which upstream served this call*, so the adapter surfaces it through a sink and an accessor and
the daemon drops it into `RunSummary::attribution` / `Event::Run`. If a third provider wants the
same, that is the argument for a field on `ModelCall`; it should be made then, not assumed now.

### What this unblocks, and what it does not

**K2 is now blocked on ONE thing instead of two.** A credential path exists. The other half —
`answered: false`, hardcoded at `crates/marlowe/src/adapter.rs:649` — is untouched and still blocks
it. Same for the four M2 acceptance rows: the model is reachable; the harnesses still do not exist.

### UNVERIFIED, and it is the whole of §9 of the ADR

**SUPERSEDED 2026-08-22 — a key arrived and four of the six were closed on a real socket.**
The paragraph below is kept as written because it is what was true when the branch was built, and
because the shape of the gap is worth preserving. **See ADR-050 §9.3 for the readings.**

> ~~No live call to openrouter.ai was made. No API key was available in this environment.~~ Six wire
> behaviours are therefore taken from documentation rather than from a socket: whether the top-level
> `provider` field arrives and on which chunk, whether `usage.cost` is present and in what unit, how
> the keepalive is spelled, whether `provider.order` + `allow_fallbacks: false` pins, whether the
> endpoint accepts `tools` alongside `stream: true` and `usage.include`, and every latency and cost
> number (there are none in the ADR, deliberately).

**What the live runs settled**, against `stealth/ox-alpha` from the shipped release binary:

| | |
|---|---|
| `provider` on streamed chunks | **CLOSED — arrives.** `upstream(s): Stealth` |
| `tools` + `stream: true` + `usage.include` | **CLOSED.** A two-call turn: the model requested `read`, the harness executed it under workspace scope, the model answered from the result |
| `usage.cost` unit | **HALF.** The field arrives and renders `0 µUSD` — and **zero is zero in either unit**, so USD-vs-credits is untouched. Needs a paid model |
| keepalive spelling | **OPEN.** No run was slow enough to provoke one |
| `provider.order` pinning | **OPEN.** A stealth model has one upstream, so this could not have tested it |

```
plain answer        1 call    4,024 tok   0 µUSD   upstream: Stealth    5,861 ms
tool-calling turn   2 calls   8,123 tok   0 µUSD   upstream: Stealth   18,623 ms
```

**Do not quote those latencies.** n = 1 each, a free stealth endpoint with unknown queueing. They
are recorded to show the path works.

Every one of them is decoded defensively — an absent field records `NOT REPORTED` rather than a
guess — but **defensive decoding is not a measurement.** One command closes items 1–5:

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
cargo run -p marlowe-openrouter --example live_probe -- anthropic/claude-sonnet-4.5
```

It prints a field-by-field presence table and exits 0 with `SKIP:` when there is no key. **Run it
before any number from this path is published**, and record the reading beside ADR-050 §9.

### Also not built, named so it is not read as covered

* **Resumption.** A benchmark that dies at case 400 of 500 loses the run. `generation_id` is
  recorded per call, so a partial run can be reconciled against OpenRouter's own history without
  re-spending — but nothing checkpoints which cases completed. Building it touches
  `tools/score_longmemeval.py`, so it is a decision rather than a follow-up commit.
* **The credential broker.** M5. The interim is one environment variable read once into a type with
  no `Display`, no `Serialize` and a hand-written `Debug`. See ADR-050 §5 for exactly what M5
  replaces and what it should **not**.
* **No OpenRouter model's tool-call reliability is measured**, and every one of them reports
  `NOT MEASURED`. `qwen3.5:9b`'s 12/12 stays where it belongs.


## MARKDOWN AND INLINE LATEX SHIP IN THE CONVERSATION PANE. ADR-047, 2026-08-22.

**`crates/marlowe-surface/src/{markdown,latex,chrome}.rs`.** Model replies were always markdown and
were drawn flat; they now render as prose, inside §B2's colour budget, with **no new colour and no
background fill**. Inline maths is translated where a character grid can carry it and left visibly as
its own source where it cannot.

### The three things a later session needs to know before touching this

**1. `chrome.rs` is the single definition of what harness chrome looks like, and BOTH sides read
it.** `render.rs` gets its tool marker, disclosure triangles, keycap, quote rule and scrollbar
glyphs from `chrome::MARKERS`; `chrome::mark_reserved` refuses that same set — plus the whole of box
drawing (U+2500–U+257F) and block elements (U+2580–U+259F) — in model prose, replacing each with
`<U+XXXX>`. **A new chrome glyph that is not declared there is not drawn either, because there is
nowhere else to get one from.** Ranges rather than a list, because §B2's premise is about *borders*,
and blocking `─` alone leaves sixty other glyphs that draw a box just as convincingly.

`markdown_forgery.rs` asserts both halves on the drawn buffer, and the second half is the one that
rots silently: **every glyph in `MARKERS` must actually appear in a rendered frame**, or the
reservation is guarding something nobody draws. That is the fourteenth-instance shape applied to a
glyph instead of a file path.

**2. `Modifier::REVERSED` is a background fill that §B13's existing row cannot see.** The zero-fills
walk asserts `cell.bg == Color::Reset`; reverse video is a *modifier*, so a cell carrying it reports
`Reset` and the terminal paints a solid slab. It is also the obvious way to draw a code fence.
`markdown_render.rs` now asserts both, and code takes foreground **weight 1** with a two-column
indent instead. **If a future change reaches for reverse video anywhere in this crate, that is the
test that should fire.**

**3. A model can stall the surface by choosing its punctuation, and the cost test is what found it.**
Inline markdown scans forward for a closer; an opener with no closer scans to the end of the block.
140 KB of `[[[[…`, backtick runs and `***nested ` took **144 ms in one release frame** — past K4's
entire 150 ms first-frame budget. Closed by `markdown::scan_budget`: one look-ahead budget per reply,
16× its length, shared by every scanning construct; when it runs out the rest renders as literal
text, which is what the pane did before ADR-047. Also: an unclosed backtick run is skipped **whole**
(retrying re-counts it — the quadratic in miniature), and block nesting stops at six levels because
`> `×10 000 is a stack overflow rather than a slow frame. Now 24 ms; the `md_budget` mutation restores
1 415 ms in debug against a 500 ms ceiling.

**4. RATATUI DOES NOT FILTER THE TAG BLOCK, and the TUI's only defence there was ratatui.**
Measured while writing ADR-047, after the ADR's *draft* claimed the opposite about U+2028 and the
BiDi overrides and was wrong. ratatui discards `ESC`, C0/C1, `TAB`, U+202E, U+200B, U+FEFF **and**
U+2028. It passes **U+E0000–U+E007F** — a full invisible ASCII alphabet, the documented channel for
smuggling instructions past a human reader.

Two consequences, both closed here:

* `marlowe-surface/tests/display_sanitiser.rs` **had gone vacuous about its own subject.** It
  asserted through `Entry::Said(Speech::Model(_))`, which now has a sanitiser in front of it, so it
  would have stayed green with ratatui's filtering removed entirely. It uses `Entry::User` — still
  the flat path — and now records the tag-block gap as a measurement rather than a sentence.
* **A tool `target` is model-composed and is drawn through the flat path.** `render::tool_line` and
  `render::expansion` route the target, the collapsed targets and the failure detail through
  `marlowe_contract::text::sanitize_{line,prose}`. `Shape::Line` for the targets — a `\n` there is
  the attack, and that is CLAUDE.md's own logged example — and `Shape::Prose` for a detail that is
  genuinely a stack trace.

**The remaining tag-block exposure is `Entry::User` and harness notices**, and both are deliberate:
the user is not smuggling instructions past themselves, and mangling their own typing is worse than
the gap; harness notices are a closed vocabulary the harness authored.

### What is measured

`crates/marlowe-surface/tests/markdown_cost.rs`, release, with the flat path measured **in the same
process on the same bytes** as the control:

| case | flat (before) | markdown | ceiling |
|---|---|---|---|
| 32 KB — a typical first frame | — | **3.4 ms** | 8 ms |
| 400 KB at 66 cols — a full context window | 3.4 ms | **29 ms** | 50 ms |
| 400 KB at 136 cols | 3.2 ms | **25 ms** | 50 ms |
| 140 KB adversarial punctuation | — | **24 ms** | 50 ms |

**Ceilings are profile-aware and each is labelled with what it can establish.** K4 is a property of
the release binary; debug measures 7–8× slower on identical input, so the debug ceilings (60 / 500
ms) are evidence about the *algorithm* and say nothing about K4. That is why the workspace suite,
which runs debug, still fails if the quadratic returns.

### THE OPEN ITEM THIS LEAVES, and it is architectural rather than a bug

**`render::transcript_lines` lays out the ENTIRE transcript on every frame**, because the scrollbar
needs the true line count and only the renderer knows it. That was 3.4 ms and is now **29 ms** at the
pessimistic end — **paid per frame, not per turn** — so a long session tightens the ceiling on how
often the surface can repaint. The daemon appends without bound (`project.rs`: *"the transcript
grows; nothing else is invented"*), so the pessimistic end is reachable rather than hypothetical.

**The fix is windowed layout with a cached total, and it is a change to `transcript_lines`' contract**
— `App::scroll_max`, the scrollbar and the pager all read that one number, and two answers to it is
exactly the divergence the current design exists to prevent. Not attempted here; it is a separate
change with its own tests.

### Verified by mutation — eleven bounds, one at a time, each caught by a NAMED test

`scratchpad/mutate2.py`: `md_render`, `md_chrome`, `md_ranges`, `md_rule`, `md_reversed`,
`md_budget`, `md_latex_partial`, `md_latex_output`, `md_currency`, `md_copy_source`, `md_toolline`.
Every assertion reads a drawn `ratatui::Buffer`, never an intermediate `Vec<Span>`.

### Two decisions that came from LOOKING at the pane, not from reading the code

`snapshot.rs::a_markdown_reply_can_be_read` prints the frame at 120×30 and 160×45. It produced both
of these and nothing else would have: **binary operators are spaced** (`α × β²`, not `α×β²` — LaTeX's
command-terminating space is syntax and is consumed, so the spacing has to be re-derived), and
**horizontal rules span the full pane** rather than stopping at an arbitrary 80 columns, which read as
a truncation.

### Verified in the RUNNING binary, and the instrument is reusable

`marlowe --tui --scripted --timing-probe` renders **one real frame** and exits, and the emitted
escape stream can be captured from a non-TTY shell. That is the instrument for anything that has to
be true of the deployed binary rather than of a `TestBackend` — the same gap that made
`persona_emission.rs` green while the model had never seen the persona.

Markdown was pushed through it by temporarily adding one reply to the stub's opening transcript,
rebuilding release, capturing, and reverting. In the captured stream at 120×30, `TERM=xterm-256color`:
real `ESC[38;5;…` and `ESC[1m`; `Margin is α × β²; the tail $\int_0^\infty e^{-x}dx$ is left as
written.`; `See the note (https://example.invalid/j).`; a `·` rule rather than a `─` one; **the
forged tool line refused and marked as `<U+22EF>` on the same screen as a real `⋯ run  deep-research`
line**; the scripted `$3` untouched; **`time_to_first_frame_ms  1`** against K4's 150.

### What is NOT verified

**No interactive session.** This environment has no PTY, so scrolling, live resize, and `y`/`Y`
against a real clipboard were not exercised.

**Italic was above the fold in that frame, and italic is the one attribute a FONT can silently
refuse.** `ESC[3m` does not appear in the captured stream. It is asserted on the grid by
`markdown_render.rs`, but whether a terminal font has an italic face is a property no test in this
repository can see — on a font without one, **emphasis and body will look identical and nothing will
report it**. §B13's by-eye row covers the accent; nothing covers emphasis. **Look at a markdown reply
in a real terminal before treating that as closed.**

**The suite needs `models/` present.** A fresh `git worktree` does not have it (gitignored, lives in
the main checkout), and `marlowe-memory/tests/cuda_libs_wiring.rs` then fails *by design* — it
refuses to report a pass when neither model is there to exercise. That is one failure that is
environmental rather than a regression. **Do not `mklink /J` the directory in** — `git clean -xdf`
follows a junction, and the target is 4 GB of models.

## OUTSTANDING — read this first. Everything below this section is history.

Consolidated 2026-08-17 because the items were spread across twelve sections written by different
agents, and reconstructing them from the history is how one gets missed.

### Named for a future session — the provider is a LAUNCH-TIME choice and should not be

**Recorded 2026-08-22, not built, and the human asked for it to be written down rather than done.**

`--provider openrouter --openrouter-model <slug>` now reaches `--serve`, `--ask`, `--status`,
`--tui` and the Windows Terminal profile the shortcut launches. **All of them decide at process
start.** Once a daemon is up, the provider is fixed for its lifetime, and the only way to change it
is to stop the daemon and start another.

**What is wanted instead: change the provider from the TUI's own command line** — the message field,
as a slash command — the way `/model` would work in any other tool.

**And the second half is the part that makes it more than a convenience.** The model list is a
property of the provider: today `marlowe --models` asks the local Ollama what it holds, and that is
the only catalogue the product knows. Under OpenRouter the catalogue is ~421 models fetched from
`https://openrouter.ai/api/v1/models`. **So switching provider must change what the model picker
offers**, and the control-strip field that shows the model has to follow it.

**Three things a session that builds this will hit, named so they are not rediscovered:**

1. **The daemon owns the run, and §2.14 says a surface holds no state the daemon lacks.** So this is
   not a surface feature with a local variable — it is a daemon operation the surface requests, and
   the wire protocol has no verb for it. `Request`/`Event` in `marlowe-daemon::protocol` would need
   one, and `CONTRACTS.md` schemas are pinned.
2. **Switching provider mid-session changes what a turn costs and where it goes.** ADR-029's rule is
   *announced, never inferred*; a provider change is more consequential than a model change and the
   §B5 band should say so. Whether it needs an approval is a real question, not a rhetorical one —
   it moves money and network egress.
3. **The catalogue fetch is network I/O on a keystroke.** `marlowe --models` is a blocking probe
   today. Doing that from the TUI's render or input path would freeze the surface, which is the rule
   CLAUDE.md states in capitals about heavy work on the daemon thread.

**Until it exists**, changing provider means `marlowe --shutdown` and relaunching — and note that a
`--provider` flag on a client invocation is silently inert when a daemon is already up, because
`ensure_daemon` only spawns when none is listening. That is correct behaviour and it is also a
sharp edge.

### Blocking, in the sense that something is wrong right now

**1. `auto_sessions` discards its warm-up result.** A failed warm-up collapses the per-session cost
estimate to a 188 MB floor against a real 690-800 MB, so ORT's allocator rather than the budget is
what stops the loop. Measured, deliberately not fixed: its failure branch cannot be driven from a
test, and an untestable budget change is the shape that goes green and does nothing.

**2. `render::transcript_lines` re-lays the whole transcript every frame, and ADR-047 made that 8×
more expensive.** 3.4 ms -> 29 ms for a full context window of prose, per frame. Not a bug and not
a regression in correctness; it narrows the headroom under K4 for a long session. The fix is
windowed layout with a cached total, which changes `transcript_lines`' contract — see the ADR-047
section above.

### IDEAS, NOT ACTIONS — do not schedule these

**A VRAM reserve that leaves headroom for other processes on the machine. CONSIDERED AND REJECTED
2026-08-17, by the human, and the reasoning is worth keeping because it overturns two amendments
committed earlier the same day** (`db695f5`, `9604717`) and a "tier 0" that had been proposed after a
game and Marlowe killed each other.

> *"Our job is to run the agent, not make it super convenient for the user to play or overload their
> memory. Our memory for our application is our memory."*

**Why this is the stronger position, stated so a later session does not re-derive the rejected one.**
A reserve against external consumers is **unbounded by construction**: a game, a browser decoding
video, a compositor â€” none announce themselves, none yield, and none are ours to schedule. Any number
chosen to leave room for them is a guess that is simultaneously too large on an idle machine and too
small on a busy one, and it would be a constant with no derivation behind it. That is the shape this
project refuses everywhere else.

**What replaces it is an ORDERING, not a reserve, and it applies WITHIN Marlowe's own footprint:**

> **LLM first. Voice second. Everything else wherever it fits.**

The first two are VRAM-only and have no CPU fallback, so they have first claim on what Marlowe
allocates. Everything else â€” embedder, reranker, anything later â€” takes what remains and degrades to
CPU when it cannot. **Respect this when changing models**, which is the case that actually matters:
a larger LLM or the arrival of voice (M7) shrinks what tier 3 may take, and that is a real constraint
with a knowable number on both sides.

**What this does not change:** `auto` still degrades to CPU rather than failing a run, the resolved
provider is still announced rather than the requested one, and per-session cost is still measured
(312 MB host / 802 MB device for the embedder; 341 MB device for the reranker). Those are properties
of Marlowe's own budget and they stand.

### Ordering constraint â€” get this wrong and three defects go live together

**3. Fix the compaction stamp (E5) and the trim marker (F1) BEFORE `ingest` is wired into the
product.** Layer 3's latch is currently unreachable in the shipped daemon; the moment `ingest` has a
production path it goes live **alongside** those two known defects in the same path.

### Deferred by the human, by name

**4. The four M2 acceptance benchmarks** â€” SWE-bench Verified, Terminal-Bench 2.0, Ï„-bench, BFCL.
**No harness for any of them exists in this repo** (`eval/src/marlowe_eval/suites/` is memory-only),
so this is integrating four external harnesses: milestone work, not a session. Recorded as UNMET AND
UNSCHEDULED in ROADMAP.md's acceptance list.

### Unverified rather than unfinished

**5. CI has never executed.** `.github/workflows/ci.yml` is committed (`9591ef4`), the YAML parses,
the matrix is `ubuntu-latest` + `windows-latest`, and the commands match what runs locally. **A
workflow that has never run is a claim, not a guard â€” the first push is the test.** `models/` and
`data/` are gitignored and never vendored, so a fresh runner has neither; the workflow's skip
manifest exists to make that coverage gap legible rather than silent.

**6. M1's accent row â€” the by-eye half.** The arithmetic is asserted (`e21cae7`): 6.43:1 on dark,
3.26:1 on light, both clear the 3.0 floor that applies to a structure accent. Â§B13 asks for
confirmation **by eye on each background** and a number is not an eye. Human action, not agent work.

**2. `--serve` never announces the resolved rerank provider.** It exists only on `--status`.
ADR-029's rule is *announced, never inferred*, and the daemon's startup lines announce the model,
the context window and the memory state but not which provider the reranker resolved to â€” so a
daemon silently on CPU and one on CUDA print the same startup. Found while measuring; one line.

### Debris

**7. CLOSED 2026-08-18.** The 0-byte `scored-candidates.ndjson` from the abandoned gate-1 scoring
run is deleted. It was the shape worth naming â€” a zero-byte file in a results directory reads like a
result â€” and it went with the sweep below rather than needing its own action.

**8. CLOSED 2026-08-18. 1,521 MB reclaimed.** Every `run.jsonl` and `scored-candidates.ndjson` under
this session's four `runs/session-e*` directories is deleted: 1,522 MB â†’ 1 MB. All were gitignored
and all are regenerable. **94 small evidence files were KEPT** â€” kilobytes each, several cited by
name in commit messages (`gates23.txt` carries the gate 2/3 readings, `WHAT-THIS-IS.md` documents the
stale-binary near-miss, the provider benches hold the overhead tables). Deleting those would have
cost the reasoning and saved nothing.

**Deliberately NOT touched, and not this session's to delete:** `runs/session-l` (**6.2 GB**),
`runs/session-m0c` (99 MB), `runs/session-m0c-m` (25 MB). All three were untracked before this
session began. `session-l` is where the remaining space is â€” and note before clearing it that
`session-l/RESULT.md` is the artifact that proved CUDA has always worked from Rust, which corrected
an agent's wrong conclusion this session.

**One consequence:** `examples/rerank_gate1.rs` reads its pairs from
`runs/session-e-maxseq/fit-1024/fit/scored-candidates.ndjson`, now deleted. **Gate 1's result stands**
â€” measured, committed, in ADR-045 â€” but re-running that example needs the dump regenerated. It exits
with a clean `SKIP:` rather than a confusing error.

### Known-unmeasured, stated so it is not read as covered

**9. The belief-store startup slope â€” HALF CLOSED 2026-08-18, and the dangerous half is the half
still open.** `Journal::open` runs `verify_chain`, which walks from sequence 1 and re-derives every
signature, and `BeliefStore::derive` folds the whole log â€” both **O(journal size)**.

* **The MEMORY slope is now measured**: **3.10 KB resident per memory written**, over journals of
  0 / 100 / 500 / 2,000, residuals Â±0.19 MB. `--serve` at 2,000 memories is 17.0 MB. See the
  component-table section below.
* **The TIME slope is still unmeasured**, and it is the one this item was written about.
  `seconds_to_settle` read 4.8 s at 0 memories and 5.0 s at 2,000 â€” the instrument's own floor is
  ~4 s, so it cannot resolve an O(journal) cost at that size. **2,000 rows is two orders of
  magnitude too few, and a different instrument is needed.** `verify_chain` runs before the daemon
  answers anything, so this is still exactly the *"why does it take eight seconds to start now"*
  risk it was filed as.

**10. Worker-count invariance on CUDA.** Measured on CPU only, and under `auto` the *width* derives
from free VRAM at load â€” so two `repro` spawns can differ in width while agreeing on provider.
CLAUDE.md's documented `TARGET` pins `--embedder-provider cpu` for this reason.
**Re-confirmed live 2026-08-18**: the same command opened **8 of 8** sessions on an idle card and
**7 of 8** with `marlowe-red:9b` resident.

**11. The document store's real footprint.** `DocumentStore` has **no `remove`, no capacity and no
eviction path** (`marlowe-extract/src/store.rs:106-199`) and holds each `Document`'s full text for
the process lifetime. STATE.md's 74.3 MB deep-research and 49.4 MB 300-document figures **predate
this session and were NOT re-verified** â€” a cargo hold stopped the re-run. Do not carry them
forward. `cargo run -p marlowe-exec --release --example deep_research` is the command.

**12. Both process totals with a 9B resident, and the adapter under `auto`.** The component table
below has its coexistence column filled on every cell; the *process* totals (Â§2a, Â§2b) are idle-card
only. `python tools/process_footprint.py --out <dir> --sizes 0,2000` with the model loaded finishes
it, and `--embedder-provider auto --rerank-provider auto` finishes the other gap. Neither needs
cargo â€” only the hold being lifted on starting a daemon.


---

## THE COMPONENT TABLE AND THE TWO TOTALS. MEASURED, WITH THE GAPS NAMED IN THE TABLES.

**2026-08-18, continuing `9591ef4`.** Every cell below is a command that was run against
`target/release/marlowe.exe` (mtime 2026-08-17 23:43) and the two examples built from it at 23:56.
Files: `runs/session-f-components/`. **A cell that was not run says `NOT MEASURED` in the table
rather than being interpolated or quietly dropped** â€” a session was cancelled mid-flight for
exactly this deliverable twice before, and a narrowed table that hides its own gaps is worse than
a wide one that shows them.

**A cargo hold landed part-way through**, so the coexistent process totals and the document-store
re-verification are unrun. They are marked, and the command that finishes each is written down.

**The four generated profiles were deleted after the sweep and their audit trail kept.** Each held
a `profile.key` and a `daemon.token`, and key material does not belong in a results directory where
a future `git add -A` can reach it. `runs/session-f-components/journal-census.txt` carries the row
counts by kind that every journal-slope figure below is derived from; the profiles regenerate with
`python tools/process_footprint.py --out <dir> --sizes 0,100,500,2000`.

### The instruments, named â€” because the obvious one does not work on this machine

| quantity | instrument | what it does NOT tell you |
|---|---|---|
| host peak | `PeakWorkingSet64` from `Get-Process` | a high-water mark, so two components' peaks **do not add** â€” see the residual below |
| host resident | `WorkingSet64` from `Get-Process`, sampled until 3 consecutive reads agree within 1 MB | *resident* pages only; a large process is trimmed harder than a small one |
| device | card-wide `nvidia-smi --query-gpu=memory.free`, differenced against a baseline taken before the first session opens | includes anything **else** that allocated in the window |
| device, per process | `nvidia-smi --query-compute-apps=pid,used_memory` â†’ **`[N/A]` on every row** | WDDM does not attribute device memory per process on this driver. Printed as the literal `[N/A]`; it is never rendered as a number |

**The card-wide instrument's noise floor is visible in the table and is not hidden.** A pure-CPU
embedder run reads `device held 220 MB`, and a pure-CPU reranker run reads `509 MB` at one cell.
Neither component allocates a byte of device memory. That is the desktop and the driver moving
underneath a differenced reading, and it is the honest cost of the only instrument that works
here â€” which is why every run prints its own baseline.

---

# DELIVERABLE 1 â€” THE COMPONENT TABLE

Two model-bearing components. **The LLM is Ollama's `llama-server`, a separate process, and is out
of scope** â€” it appears here only as the co-resident load in the coexistence columns.

`--embedder-provider` and `--rerank-provider` both default to **`auto`** (ADR-044, ADR-045), and
`auto` resolves against free VRAM at that instant. **Every row therefore reports the RESOLVED
provider, never the requested one.** Rows 2 and 3 of ADR-044's own table both ended on CPU and
printed identical words before that distinction existed.

## 1a. Embedder â€” `models/jina-embeddings-v2-small-en`, `MAX_SEQ_LEN` 1024

**Cache OFF on every cell** (`cache_dir = None` in `Embedder::load_with_provider`). With a cache,
whichever provider ran second would be reading back the first one's vectors and reporting a disk
read as a speedup. 32 texts per cell, one untimed warm pass first.

**Latency, ms per embedding.** `runs/session-f-components/embed-{cpu,auto}-{idle,coexist}.txt`.

| tokens | workers | requested | **RESOLVED** | idle | with `marlowe-red:9b` resident | Î” |
|---|---|---|---|---|---|---|
| 102 | 1 | `cpu` | **CPUExecutionProvider** | 29.44 | 31.82 | +8.1% |
| 102 | 8 | `cpu` | **CPUExecutionProvider** | 5.03 | 6.39 | +27.0% |
| 502 | 1 | `cpu` | **CPUExecutionProvider** | 155.92 | 174.96 | +12.2% |
| 502 | 8 | `cpu` | **CPUExecutionProvider** | 33.15 | 42.13 | +27.1% |
| 1024 | 1 | `cpu` | **CPUExecutionProvider** | 385.04 | 418.81 | +8.8% |
| 1024 | 8 | `cpu` | **CPUExecutionProvider** | 93.33 | 105.55 | +13.1% |
| 102 | 1 | `auto` | **CUDAExecutionProvider** | **2.13** | **2.96** | +39.0% |
| 102 | 8 | `auto` | **CUDAExecutionProvider** | **2.92** | **4.77** | +63.4% |
| 502 | 1 | `auto` | **CUDAExecutionProvider** | **3.08** | **3.37** | +9.4% |
| 502 | 8 | `auto` | **CUDAExecutionProvider** | **3.17** | **2.85** | âˆ’10.1% |
| 1024 | 1 | `auto` | **CUDAExecutionProvider** | **4.55** | **5.23** | +14.9% |
| 1024 | 8 | `auto` | **CUDAExecutionProvider** | **5.14** | **6.53** | +27.0% |

**The CPU column is the control that says the harness did not change under the treatment**, and it
reproduces the previous session's idle table to within **13.4%** â€” four of six cells inside 2%, and
the two that move are the 8-worker cells (502Ã—8 +13.4%, 1024Ã—8 +7.4%), which is where a shared
machine shows up first. The one negative Î” (502Ã—8 on
CUDA, âˆ’10.1%) is larger than any plausible coexistence *benefit* and is the cell-to-cell noise of a
100 ms measurement; it is left in rather than smoothed.

**Footprint, one configuration per process** â€” `examples/embed_memory.rs`, which takes provider and
width as arguments precisely so a peak belongs to the configuration it is printed under.
`runs/session-f-components/embed-memory-{idle,coexist}.txt`.

| config | RESOLVED | host peak idle | device held idle | host peak coexist | device held coexist |
|---|---|---|---|---|---|
| CPU Ã— 1 | CPUExecutionProvider | **312.3 MB** | âˆ’68 MB *(noise; CPU holds none)* | **312.3 MB** | âˆ’4 MB |
| CPU Ã— 8 | CPUExecutionProvider | **2,048.0 MB** | +65 MB *(noise)* | **2,092.1 MB** | âˆ’9 MB |
| CUDA Ã— 1 | CUDAExecutionProvider | **1,057.0 MB** | **730 MB** | **1,054.1 MB** | **765 MB** |
| CUDA Ã— 8 | CUDAExecutionProvider | **1,749.9 MB** | **4,648 MB** | **1,658.1 MB** â€” *7 of 8* | **3,952 MB** â€” *7 of 8* |

**The last row is `auto` narrowing itself under load, observed rather than argued.** At 6,674 MB
free the plan reads *"7 of 8 sessions; device memory: 1312 MB usable would not hold another session
plus a spare (766 MB each)"*. Idle it opens 8. Same binary, same command, two widths â€” which is the
standing reason `cuda` still exists as a fixed arm for anything that publishes a number.

**CUDA's host peak is mostly not the embedder's.** 1,057.0 MB at one session against 312.3 MB on
CPU; the ~745 MB gap is the CUDA runtime's host-side initialisation, a **per-process constant**,
not a per-session cost â€” the marginal host cost of sessions 2â€“8 is (1,749.9 âˆ’ 1,057.0) / 7 =
**99.0 MB each**.

## 1b. Reranker â€” `models/ms-marco-MiniLM-L-2-v2-ft-session-j`, `MAX_SEQ_LEN` 256, `SHIPPED_THREADS` 1

**There is no cache to switch off**: `CrossEncoder` has no `cache_dir` parameter on any
constructor. That is stated rather than left implicit, so "cache OFF" is not read as an unverified
claim about a component that has none. 30 slates per cell, warmed at `MAX_BATCH` first.
`runs/session-f-components/rerank-{cpu,auto}-{idle,coexist}.txt`.

| batch | requested | **RESOLVED** | shape | ms/slate idle | ms/slate coexist | ms/pair idle | ms/pair coexist | host peak | device held idle | device held coexist |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `cpu` | **CPUExecutionProvider** | sequential | 19.185 | 19.784 | 19.185 | 19.784 | 156.9 MB | *0 (readings are drift)* | *0* |
| **10** = `MAX_BATCH` | `cpu` | **CPUExecutionProvider** | sequential | 193.667 | 206.285 | 19.367 | 20.628 | **169.0 MB** | *0* | *0* |
| 1 | `auto` | **CUDAExecutionProvider** | batched | **1.692** | **1.571** | 1.692 | 1.571 | 1,028.0 MB | **529 MB** | **336 MB** |
| **10** = `MAX_BATCH` | `auto` | **CUDAExecutionProvider** | batched | **3.491** | **3.741** | **0.349** | **0.374** | **1,028.0 MB** | **517 MB** | **317 MB** |
| **11** | either | â€” | â€” | **REFUSED, on all four cells** | | | | | | |

**Batching is the whole difference between the two providers and the table shows why the shape is
on the status line.** CPU gains nothing from a batch â€” 19.185 â†’ 19.367 ms per pair, +0.9% â€” which
is why `default_batching()` is false there. CUDA goes 1.692 â†’ 0.349 ms per pair, a **4.8Ã— gain**,
because a batch of 10 costs 3.491 ms against a batch of 1 costing 1.692. A status line naming a
provider without its shape describes two configurations 55Ã— apart at `MAX_BATCH`.

**`host peak after load` is 134.8 MB on CPU and 1,026.7 MB on CUDA.** The CUDA figure is again the
runtime's host-side init, not the graph: the graph is 62.5 MB on disk.

**The batch-11 refusal is printed with every table, not asserted in prose.** A reader who sees no
row for 11 cannot otherwise tell whether the cell was refused or simply never attempted â€” which is
the failure mode that made gate 1's first run print a clean PASS over zero comparisons. It refuses
with the reason: invariance on this graph was measured over 1..10 only.

**The device column moves with the card, not with the batch.** 529 MB idle against 336 MB
coexistent for the *same* work is ORT's arena taking what is there, which also explains why the
previous session recorded 341 MB for this component and this one records 517 MB. Both are correct
about the card they were taken on. **This is not a fixed per-component cost and must not be quoted
as one.**

## 1c. The budget, and whether these fit inside it

**Â§5.7: P95 retrieval â‰¤ 300 ms** (`docs/requirements/01-brief.md:240`) â€” non-negotiable, because
Â§9's 800 ms voice-to-voice budget does not survive a 300 ms memory stage. `RERANK_BUDGET = 10`
(`retrieve.rs:271`), which is exactly `MAX_BATCH`, so **one retrieval is one query embedding plus
one rerank slate of ten**.

| configuration | embed (1 query, ~100 tok, 1 worker) | rerank (slate of 10) | **sum** | of 300 ms | inside? |
|---|---|---|---|---|---|
| all CUDA, idle | 2.13 | 3.491 | **5.62 ms** | 1.9% | **yes, by 53Ã—** |
| all CUDA, 9b resident | 2.96 | 3.741 | **6.70 ms** | 2.2% | **yes, by 45Ã—** |
| all CPU, idle | 29.44 | 193.667 | **223.11 ms** | 74.4% | **yes, with 26% headroom** |
| all CPU, 9b resident | 31.82 | 206.285 | **238.11 ms** | 79.4% | **yes, with 21% headroom** |

**This column is ARITHMETIC OVER COMPONENT MEASUREMENTS, NOT A MEASURED RETRIEVAL.** It omits the
lexical cue, the belief-store scan, the gate and assembly. The end-to-end retrieval P95 is a
different quantity taken on a different instrument (M0c Session L), and this project's standing
rule is that a measurement is scoped to the system it was taken on. **Read this as: the two model
stages alone consume 74â€“79% of the budget on CPU and 2% on CUDA.** The all-CPU row has no room for
the rest of the pipeline and should not be read as a pass.

**The shipped daemon's answer is neither row.** It loads **no embedder at all** (below), so its
retrieval today is the rerank stage alone: **3.491 ms** idle, 1.2% of budget.

---

# DELIVERABLE 2 â€” TWO TOTALS, SEPARATED

**`marlowe --serve` and `marlowe --eval-adapter` are two independent front ends over the same
crates and they do not load the same components** (`docs/design/EVAL-PRODUCT-DIVERGENCE.md`). A
single "Marlowe uses N MB" would describe neither. **The two differ by 100Ã—.**

**Re-verified by grep this session, not carried from the previous one:**

| claim | check | result |
|---|---|---|
| the daemon loads **no embedder** | `grep -rn "Embedder" crates/marlowe-daemon/src/` | **0 matches** |
| the one production embedder call site | `grep -rn "load_with_provider" crates/` | `crates/marlowe/src/main.rs:657`, inside `--eval-adapter` |
| the daemon **does** load a reranker | `crates/marlowe-daemon/src/memory.rs:159` | `CrossEncoder::load_auto`, when `--reranking` is given |
| the document store is daemon-side only | `grep -rn "DocumentStore" crates/` | constructed in `marlowe-exec/src/lib.rs:122`; **0 in `adapter.rs`** |

## 2a. `marlowe --serve` â€” the shipped daemon

Journals built through the shipped `--eval-adapter` wire at 0 / 100 / 500 / 2,000 memories, idle
card. `tools/process_footprint.py`, `runs/session-f-components/footprint-idle/footprint.json`.

| source | fixed / scaling | scales with | host | device |
|---|---|---|---|---|
| process baseline + daemon machinery | **FIXED** | â€” | **10.96 MB** *(fitted intercept)* | 0 |
| belief store rebuilt from the journal | **SCALING** | **memories written** | **+3.10 KB each** | 0 |
| embedder | **NOT LOADED** | â€” | **0** | **0** |
| cross-encoder, `--reranking` absent | **NOT LOADED** â€” memory is write-only and says so | â€” | 0 | 0 |
| cross-encoder, `--reranking` present, `auto` â†’ **CUDA** on an idle card | **FIXED** | â€” | **+1,016.3 MB** | **348â€“667 MB**, moves with the card |
| document store (`marlowe_extract::store`) | **SCALING, UNBOUNDED** | **documents fetched â€” never evicted** | **NOT RE-VERIFIED** (see below) | 0 |
| context / session state | **SCALING** | live runs | **NOT MEASURED** | 0 |

**Measured totals, host working set:**

| memories | `--serve` | `--serve --reranking` |
|---|---|---|
| 0 | **10.78 MB** | **1,028.05 MB** |
| 100 | 11.31 MB | 1,028.27 MB |
| 500 | 12.66 MB | 1,026.27 MB |
| 2,000 | **16.97 MB** | **1,032.12 MB** |
| **fit** | intercept **10.96 MB**, slope **3.10 KB/memory**, residuals Â±0.19 MB | intercept **1,027.2 MB**, slope 2.25 KB/memory but residuals Â±2.08 MB â€” **the slope is inside the noise here and only the intercept is a result** |

**The headline: a shipped daemon holding two thousand memories is 17 MB.** Adding `--reranking`
multiplies it by 61, and almost none of that is the 62.5 MB graph â€” it is the CUDA runtime's
host-side initialisation.

**The resolved provider was verified against a RUNNING daemon**, on the default port:

```
marlowe --status
  rerank      CUDAExecutionProvider Â· batched Â· asked auto
```

**And the first attempt to capture that automatically was wrong in a way worth recording.**
`tools/process_footprint.py` passed `--daemon-port` to `--status`; `main.rs` routes `--status` to
`agent::status(workspace, profile_root)`, which **takes no port** â€” the flag is accepted and
ignored. So four daemons that had each resolved CUDA and were holding ~1 GB of host and 348â€“667 MB
of device memory were recorded as `rerank not-loaded`, because the reply came from whatever sat on
the default port. Nothing was broken: the daemon was right, the label was right, and the reading
was about a different process. It is the *"a measurement is scoped to the system it was taken on"*
family, produced by a flag that was silently ignored rather than refused. The tool now records the
limitation in place of a wrong value.

### Does it scale with journal size? YES, LINEARLY, AND THE SLOPE IS MEASURED FOR THE FIRST TIME

`Journal::verify_chain` walks every row and `BeliefStore::derive` folds the whole log; both are
O(journal) and both run at startup before a port is bound. The slope was **UNMEASURED**. It is now:

| quantity | slope | fit quality |
|---|---|---|
| journal on disk | **1.046 KB per memory written** | residual ~0 (2,154,496 B at 2,000) |
| journal **rows** | **1.99 per memory written** | 3,979 rows at 2,000: 2,000 `memory_written`, 1,689 `superseded`, 250 `beliefs_merged`, 40 `consolidation_ran` |
| daemon resident | **3.10 KB per memory written** | residuals Â±0.19 MB over 0â€¦2,000 |

Resident is **2.96Ã— the on-disk size** â€” consistent with `BeliefStore` holding decoded text plus
metadata in a `BTreeMap` while the journal holds JSON payload plus signature. Consistent with, not
confirmed: the decomposition is not unique at this precision.

**Extrapolating the measured line: 100,000 memories â‰ˆ 303 MB resident, 102 MB on disk.** That is an
extrapolation **50Ã— past the measured range** and is stated as arithmetic, not as a reading â€” the
fit is over 0â€¦2,000 and nothing here establishes that it stays linear at 100k.

**The STARTUP-TIME slope is still unmeasured and this session did not close it.**
`seconds_to_settle` read 4.8 s at 0 memories and 5.0 s at 2,000 â€” the settle detector's own floor
is ~4 s, so it cannot resolve an O(journal) *time* cost at these sizes. **A different instrument is
needed, and 2,000 rows is too few.** This is the more dangerous of the two slopes, because
`verify_chain` runs before the daemon answers anything.

## 2b. `marlowe --eval-adapter` â€” the benchmark path

`--embedder-provider cpu` (8 workers), `--rerank-provider cpu`. Both explicit: the shipped defaults
are `auto`, which resolves against the card at that instant, so a footprint row taken under `auto`
describes whatever the card happened to hold.

| source | fixed / scaling | host |
|---|---|---|
| process baseline | **FIXED** | 8.8 MB *(measured before load in both examples)* |
| embedder, CPU Ã— 8 | **FIXED** | +1,085.1 MB *(1,094.0 âˆ’ 8.9, peak at load)* |
| cross-encoder, CPU | **FIXED** | +125.9 MB *(134.8 âˆ’ 8.9, peak at load)* |
| belief store | **SCALING** | +3.10 KB/memory *(from the daemon fit â€” same code, same structure)* |
| `VectorStore` | **SCALING** | +2.048 KB/memory nominal â€” `BTreeMap<String, Vec<f32>>`, 512 dims f32 |
| document store | **NOT CONSTRUCTED on this path** | 0 |

**Measured totals:**

| memories | working set | peak |
|---|---|---|
| 0 | **1,100.84 MB** | 1,143.60 MB |
| 100 | 1,104.01 MB | 1,144.30 MB |
| 500 | 1,103.52 MB | 1,144.39 MB |
| 2,000 | **1,111.02 MB** | 1,143.21 MB |
| **fit** | intercept **1,101.9 MB**, slope **4.62 KB/memory**, residuals Â±1.64 MB | intercept 1,144.1 MB, slope **âˆ’0.41 KB/memory** â€” flat, i.e. the peak is set at LOAD and ingest never exceeds it |

### DO THE PARTS ADD UP? TWO RESIDUALS, BOTH NAMED RATHER THAN ROUNDED AWAY

**Residual 1 â€” the fixed part, âˆ’76.2 MB (âˆ’6.2%).**

```
  8.8  process baseline
+1085.1  embedder CPU Ã— 8   (measured alone, peak at load)
+ 125.9  cross-encoder CPU  (measured alone, peak at load)
  ------
 1219.8  predicted peak
 1143.6  MEASURED peak
 ------
  -76.2  residual
```

**This over-prediction is expected by construction and the direction is the evidence.** Each
component measured alone pays its own *transient* load allocation â€” a 60â€“120 MB graph file read
into a buffer before ORT takes ownership â€” and a peak is a high-water mark. In one process those
transients overlap in time and reuse the same freed pages; summing two independently-measured peaks
counts each transient separately. **Summing peaks is an upper bound, and âˆ’6.2% is the size of that
bound's slack on this configuration.** Consistent with, not confirmed â€” the residual was not
attributed to a byte and no attempt is made here to claim it was.

**Residual 2 â€” the scaling part, âˆ’0.53 KB/memory (âˆ’10%).**

```
  3.10  KB/memory  belief store   (measured on --serve)
+ 2.048 KB/memory  vector         (512 dims f32; the Vec header, String key and BTreeMap
                                   node make the true figure LARGER, so this is a floor)
  -----
> 5.15  KB/memory  predicted
  4.62  KB/memory  MEASURED on --eval-adapter
  -----
 -0.53  KB/memory  residual, and the true residual is worse because 5.15 is a floor
```

**The obvious explanation is ruled out.** `BeliefStore::recall_candidates()` returns
`self.entries.values().collect()` â€” **every** entry, superseded included (`store.rs:246-248`), and
`EventKind::Superseded` sets `superseded_by` without removing anything (`store.rs:144-154`). So all
2,000 memories carry a live vector and the shortfall is **not** a smaller live set.

**Two candidate explanations, neither confirmed, and this is left open:**

1. **Working set is *resident* pages.** A 1.1 GB process is trimmed by Windows far more
   aggressively than an 11 MB one, so the same allocation shows up smaller on the adapter than the
   daemon-derived slope predicts. This would make the daemon's 3.10 KB the more trustworthy figure
   and the adapter's 4.62 KB an under-read.
2. **The `after_ingest` sample is a single point read**, not a settled one. `settle()` is used for
   `after_load` and for both `--serve` arms; it is *not* used for `after_ingest`. The Â±1.64 MB
   residuals say the slope is decent, but the instrument is weaker at exactly the point this
   residual is computed from.

**Fixing it is one line** (`settle()` at `after_ingest`) **and a re-run, and both need cargo
unblocked to be worth trusting.**

## 2c. The document store â€” NOT RE-VERIFIED, and the structural claim that stands without a run

**STATE.md's 74.3 MB deep-research peak and 49.4 MB 300-document corpus predate this session and
were NOT re-verified.** They need `cargo run --example deep_research` / `corpus_bench`, which the
cargo hold forbids. **Do not carry them forward as current** â€” they are measurements about a build
that has since changed twice.

**What IS established, by reading `crates/marlowe-extract/src/store.rs:106-199` rather than by
measurement:** `DocumentStore` is `Arc<Mutex<BTreeMap<String, Document>>>` exposing `put`,
`put_addressed`, `text`, `get`, `len`, `is_empty` and `contains` â€” **no `remove`, no capacity, no
eviction path, and no TTL.** Every `Document` it holds carries the full extracted text, title,
headings and links, and is retained for the process lifetime.

**So after a research pass the daemon holds every byte of every page it fetched, forever, and the
only bound is the process exiting.** `MAX_SOURCES_PER_READER = 6` bounds what one quarantined
reader sees; it does not bound the store. A thirty-page pass at 200 KB of extracted text each is
~6 MB retained with nothing to release it; a session that runs ten such passes retains all ten.
**That is a structural reading, not a measurement, and the measurement is the first thing to take
when cargo is unblocked.**

---

## WHAT IS MEASURED, WHAT IS INFERRED, AND WHAT IS MISSING

| | |
|---|---|
| **MEASURED** | every embedder and reranker latency cell (24 + 8), idle and coexistent; every per-configuration host peak and device delta; `--serve` and `--serve --reranking` totals at four journal sizes; `--eval-adapter` totals at four journal sizes; the journal's on-disk, row-count and resident slopes; the resolved provider of a running daemon |
| **INFERRED, with the arithmetic given** | the Â§5.7 "inside it?" column (a sum of component measurements, not an end-to-end retrieval); the adapter's fixed-part decomposition (peaks do not add â€” âˆ’6.2%); the vector term (âˆ’10% residual, unresolved); the 100k-memory extrapolation |
| **STRUCTURAL, from source, not measured** | the document store is unbounded and never evicted; the daemon loads no embedder; the document store is not constructed on the adapter path |
| **NOT MEASURED â€” named, not interpolated** | `--serve` and `--eval-adapter` totals with `marlowe-red:9b` resident; the adapter under `auto` providers; the daemon's startup-TIME slope against journal size; context/session state; the document store's actual footprint after a research pass; `--serve --reranking` resolving to CPU (the fallback arm) |

### The commands that finish it, for the next session with cargo unblocked

```bash
# the coexistent process totals â€” load the 9b first, then:
python tools/process_footprint.py --out runs/<s>/footprint-coexist --sizes 0,2000
python tools/process_footprint.py --out runs/<s>/footprint-auto --sizes 0,2000 \
       --embedder-provider auto --rerank-provider auto
# the document store after a real research pass
cargo run -p marlowe-exec --release --example deep_research
cargo run -p marlowe-exec --release --example corpus_bench
# the startup-TIME slope: needs journals two orders larger than 2,000 and a real clock
```

**9B MODELS ONLY on this card. Never load anything larger.**

---

## RERANKER ON CUDA: ALL THREE GATES PASS. `--rerank-provider` DEFAULTS TO `auto` (ADR-045).

**Gate 1 was the last one and it passed on a real measurement**, not on an argument. The default is
flipped and ADR-045 records it. This closes a disagreement that stood for months: ADR-029 put the
rerank on CUDA and the default was `cpu`.

| gate | reading |
|---|---|
| **1 â€” does CUDA change which memory ranks first** | **PASSES. Zero top-1 changes** over 120 queries / **1,200 pairs**. max abs delta **0.001260757**; 2 queries reorder deeper in the list, none at rank 1. |
| **2 â€” reference fixture on CUDA** | PASSES, worst delta ~**0.00104**. Fixture NOT regenerated. |
| **3 â€” batch invariance on CUDA** | PASSES, sizes 1..10, `max abs(batched - single)` = **0.000349** at batch 9, **zero order changes**, with a control proving the check can see a reordering. |
| device cost | **341 MB** at `MAX_BATCH`. Noise beside a 9B. |

**Gate 1 took minutes, not two scoring passes.** The reranker is a pure function of
`(query, document) -> logit`, so `examples/rerank_gate1.rs` scores real pairs from a completed dump
on both providers and counts top-1 changes. The earlier attempt to do it the expensive way was
killed and left a **0-byte** `scored-candidates.ndjson` â€” do not read that file as a result.

**The two deep reorders are the expected shape.** A 0.0013-logit deviation can only flip pairs
closer than that, and the near-tie signature on this corpus sits below 0.084 â€” two orders of
magnitude wider. Head unmoved, tail jitters.

### THE FIRST RUN OF GATE 1 PRINTED A CLEAN PASS AND WAS VACUOUS

It reported `0 flips, max |delta| 0.000000000`. Every scoring call had been **refused**: it asked for
batches of 12 and `score_batch` correctly declines anything past the sizes invariance was measured at
(1..10). The delta was computed over **zero comparisons**, and the empty `worst:` field was the only
tell.

**Both controls in place at the time passed** â€” the arms were genuinely different providers, and the
flip detector did notice a forced reordering. Neither could see that nothing had been scored. A third
control now asserts pairs were compared and exits VACUOUS otherwise.

**The general form, and it is new to this ledger:** *a control proves the instrument can detect a
difference; it does not prove the instrument was ever pointed at anything.*

### VERIFIED

`cargo build --release` clean. **`cargo test --workspace --no-fail-fast`: 944 passed, 0 failed,
2 ignored** (`runs/session-e-rerank-cuda/final-suite.txt`).

Gate 1 was **re-run against the freshly built control-3 guard** rather than trusted from the earlier
binary, and it now prints the line that was missing: **`pairs scored on BOTH providers 1200`**. Same
readings â€” max |delta| `0.001260757`, 2 deep reorders, **0 top-1 changes** â€” with the vacuity check
live this time. That is the difference between a PASS and a PASS you can believe.

### THE BENCHMARK MEASURES A SYSTEM THE PRODUCT IS NOT â€” `docs/design/EVAL-PRODUCT-DIVERGENCE.md`

Three components where the eval path and the shipped daemon have come apart, each found separately
while chasing something else. **All three re-verified by grep before writing them down**, not
carried from memory:

1. **`ingest` has exactly one caller** â€” `adapter.rs:304`, the eval adapter. `Channel::` appears
   **zero** times in `crates/marlowe-daemon/src/`.
2. **Layer 3's latch cannot fire in the shipped daemon** â€” a consequence of (1), not a separate
   defect. Unreachable, not broken.
3. **The daemon loads no embedder** â€” **zero** references to `Embedder` in `crates/marlowe-daemon/src/`;
   the one production call site is `main.rs:657`, inside `--eval-adapter`.

**What it does not say:** the measurements are not wrong. They are correct about the eval adapter.
What must change is that a quality or security claim **names which path it describes** â€” and every
embedder number this project has published, including this session's, describes the benchmark path.

**Why the shape recurs:** the adapter and the daemon are two independent front ends over the same
crates, and only one is measured. `marlowe_eval` drives the adapter; nothing drives the daemon but a
human. So a capability can be built, tested, benchmarked and documented while the product never
reaches it, with every instrument reporting success.

**The check, thirty seconds:** `grep -rn "<ComponentType>" crates/marlowe-daemon/src/`. Nothing
back means the number is about the eval path.

**Fixing it is not proposed here** â€” and the ordering constraint stands: E5 and F1 before `ingest`
is wired, or layer 3 goes live alongside two known defects in the same path.

### Also this session

- **`.gitignore` was restored from HEAD.** Its working-tree version had deleted `/target/`, `data/`,
  `models/`, `.embedding-cache/` and the `runs/**/run.jsonl` rule â€” a `git add -A` would have tried
  to commit gigabytes. The rejected version is in the scratchpad, not the repo.
- **M1's accent row** â€” arithmetic half asserted, by-eye half still open. See `e21cae7`.

### Deferred by the human, explicitly

CI (there is still none), the eval/product divergence write-up, and the four M2 benchmark rows.
The component table, the two-total memory breakdown and the tier-0 reserve design were cancelled
mid-flight; amendments `db695f5` and `9604717` are the record of what was decided before they were.


## THE EMBEDDER DEFAULTS TO GPU. ADR-044 IS WRITTEN, THE DEFAULT IS FLIPPED, AND THE RUNNING BINARY SAYS SO.

**2026-08-17, continuing `a619645`.** This closes item 1 of the previous list â€” *"the default is
still `cpu`; the measurement that blocked it exists now, the ADR does not"* â€” and item 6, the
undocumented `MARLOWE_CUDA_LIB_DIR`. **It supersedes the section below headed *"2. The default is
`cpu`, not `auto`, and this one needs the human"*: the human decided, and the answer was yes.**
It also corrects the "Where CUDA is" table further down, whose embedder row still reads
`default cpu`.

### What shipped

**`docs/design/adr/ADR-044-embedder-defaults-to-auto.md`**, indexed from `DECISIONS.md` â€” which
gained a **Part 3** listing every ADR from 030 on, because until now `DECISIONS.md` linked to none
of the fourteen files in `docs/design/adr/` and "settled decisions live in DECISIONS.md" was
therefore false of two thirds of them.

| change | where |
|---|---|
| `--embedder-provider` default `cpu` â†’ **`auto`** | `crates/marlowe/src/main.rs`, via a new `embedder_provider_choice` |
| the startup line carries the **request as well as the resolution** | `embedder_announcement`, same file |
| `--embedder-provider` documented in `USAGE` | it had no entry at all |
| `Embedder::load` stays **fixed-CPU**, and the label is now enforced | `embedder.rs` doc + an `assert_eq!(provider(), Cpu)` in `embedding_reference.rs` |
| the stale *"THIS IS A BLOCKER FOR PUTTING THE EMBEDDER ON CUDA BY DEFAULT"* comment | rewritten to say it was cleared by measurement, with nothing widened |
| `--embedder-provider` **required** in `tools/score_longmemeval.py` | it passed through to a default that has just changed underneath it |
| `MARLOWE_CUDA_LIB_DIR` + the one command that shows the resolved provider | `CLAUDE.md` build section |

**Nothing was widened and nothing was regenerated.** `MAX_ABS_DIFF` is 1e-4, `CUDA_MAX_ABS_DIFF` is
1e-3 and still a tripwire rather than a tolerance, `embedding-reference.json` is untouched,
`MAX_SEQ_LEN` is 1024. CUDA still **fails** the HuggingFace reference and the test still records it
as a failure. What licensed the flip is 242/242 identical top-1 picks with 99.84% of candidate rows
moving â€” the proxy is left reading FAIL because the decision is the property, not the proxy.

### THE RUNNING BINARY, WITH ITS CONTROL â€” this is the answer to "what does it resolve to"

`target/release/marlowe.exe`, built 22:00:23, sources last touched 21:57:27, mtime checked before
the probe because `cargo run --example` builds a different artifact and mislabelled a run earlier
tonight. **No `--embedder-provider` flag on the command line at all:**

```
marlowe: embedder asked for auto, running on CUDAExecutionProvider with 8 of 8 worker session(s)
         -- CUDA, all 8 requested sessions opened
```

| run | resolved | reason printed |
|---|---|---|
| default, `MARLOWE_CUDA_LIB_DIR` set | **CUDAExecutionProvider, 8 of 8** | *CUDA, all 8 requested sessions opened* |
| **control:** default, variable **unset** | CPUExecutionProvider, 8 of 8 | *a CUDA session did not construct: â€¦ cublasLt64_12.dll â€¦ Error 126* |
| **control:** `--embedder-provider cpu`, CUDA available | CPUExecutionProvider, 8 of 8 | *CPU was asked for explicitly* |

**AND THE OPEN RISK DEMONSTRATED ITSELF SEVEN MINUTES LATER, WHICH IS BETTER EVIDENCE THAN THE
HEADLINE.** The binary was rebuilt (restoring the mutation backups had pushed source mtimes above
the artifact, and a stale-looking binary is not worth arguing about) and the identical flagless
command re-run:

```
marlowe: embedder asked for auto, running on CUDAExecutionProvider with 6 of 8 worker session(s)
         -- CUDA, 6 of 8 sessions; device memory: 1511 MB usable would not hold another session
            plus a spare (779 MB each)
```

**8 of 8 at 22:00, 6 of 8 at 22:07, same binary, same command, nothing configured differently** â€”
`nvidia-smi` read 6,185 MiB free of 16,376 instead of an idle card. That is what `auto` means,
observed rather than argued, and it is the standing reason `cuda` still exists: a comparison
needing a fixed scorer cannot use a default that moves with the card. It also **independently
re-derives the coexistence table**, which recorded 6 of 8 at 6,267 MB from
`examples/embed_memory.rs` â€” the shipped binary's own default path lands on the same width at
6,185 MB, per-session cost 779 MB against that table's 793 MB. Two programs, two readings, one
answer.

**Rows 2 and 3 both end on CPU and before this commit printed the same words.** That is the entire
reason the request is now on the line: a fallback and a configuration are different facts, and
ADR-029's rule is that an unannounced fallback is indistinguishable from the failure mode it
resembles. `runs/session-e-cuda-adr044/live-*.txt`.

### Mutations, RUN rather than reasoned about

| mutation | result |
|---|---|
| default `Auto` â†’ `Cpu` | **2 FAILED** â€” *"the embedder default is `auto` (ADR-044)"* |
| the request half dropped from the announcement | **2 FAILED** â€” *"the REQUEST must be on the line"* |
| `Embedder::load` â†’ `Auto` | **1 FAILED** â€” *"the row labelled `cpu` is measuring something else"* |
| omit `--embedder-provider` from `score_longmemeval.py` | exits 2 at parse time |

The third is honest about its own limit: on a CPU-only machine `Auto` resolves to CPU and that
assertion passes. It catches the relabelling **here**, where a card exists, which is where the
relabelling would happen.

### NEW FINDING: `repro` must pin a provider, and the reason is not the one already recorded

The known hazard was *two spawns can pick two providers*. There is a second, narrower one underneath
it: **worker-count invariance has only ever been measured on CPU.**
`embedding_is_bit_identical_across_calls_and_worker_counts` loads through `Embedder::load`, which is
CPU by construction, and under `auto` **the width itself is derived from free VRAM at load** â€” 8 on
an idle card, 6 at 6,267 MB, 1 at 1,366 MB. So two `repro` spawns can differ in *width* while
agreeing on *provider*, and nothing in the suite has ever asserted that a CUDA embedder is
width-invariant.

`CLAUDE.md`'s documented `TARGET` now spells out `--embedder-provider cpu` for exactly this reason,
with the reasoning inline. **Closing it properly means measuring width invariance on CUDA** â€” the
same measurement the module header claims, re-taken per provider rather than inherited, which is
ADR-013's standing rule applied one boundary further out.

### One thing to know before looking for the announcement in the wrong place

**The daemon does not load an embedder at all.** `Embedder::load_with_provider` has exactly one
production call site in the workspace â€” `crates/marlowe/src/main.rs:638`, inside `--eval-adapter` â€”
and `marlowe --status`'s `rerank_provider` field still reads `not-wired`. So the startup line exists
on the eval-adapter path and nowhere else, and a future session wiring retrieval into the daemon
inherits ADR-044's announcement obligation along with the loader.

### Counts, and the profile they were taken in

| | |
|---|---|
| `cargo test --workspace --jobs 4 --no-fail-fast` (**debug**, `MARLOWE_CUDA_LIB_DIR` set) | **922 passed, 0 failed, 2 ignored** (from 915 / 0 / 2) |
| `cd eval && python -m pytest` | **72 passed**, unchanged â€” `eval/` was not touched |

**+7 is exactly the seven new `embedder_provider_flag` tests**, so the arithmetic accounts for the
whole delta rather than netting an unnoticed regression against a new pass. Tallied by summing all
**83** `test result` lines in `runs/session-e-cuda-adr044/suite.txt`, not by reading its tail: one
`FAILED` among 83 binaries is invisible in the last twenty lines, and `cmd | tail` returns
`tail`'s exit status. The suite was run **ONCE**, to a file.

### Still not closed, carried forward

1. **`auto_sessions` swallows its first session's warm-up failure**, collapsing the per-session cost
   estimate to the computed floor (~4x too small). Bounded by the one-spare-session rule re-reading
   the device on every decision, which is why the 1,645 MB and 1,366 MB cases stopped at one session
   rather than thrashing. Measured, not fixed â€” and `auto` is now the path that reaches it.
2. **A live first-session CPU fallback is still unmeasured**; the card cannot be squeezed below the
   threshold with Ollama resident, because Ollama evicts its own models first. Covered by
   `Probe::Fixed(0)`, which is a driven test and not a live observation.
3. **`tools/session_l_gpu_recovery.py` has never been run on the EMBEDDER graph**, and the 13.6%
   CPU-node census it produced was taken on the rerank graph, in Python, at ORT 1.24.2, while this
   build links 1.22. ADR-029's standing obligation, now inherited by a defaulted-on GPU path.
4. **Width invariance on CUDA is unmeasured** â€” the finding above.
5. **`RerankPlan::select` still has no call site.**
6. **`--rerank-provider` still defaults to `cpu`.** ADR-029 says the rerank runs on CUDA where a GPU
   exists; the shipped default disagrees with its own ADR, and it was left alone here because this
   session's mandate was the embedder. **It is the obvious next flip and it needs the same
   treatment: a ranking measurement with a control, not an argument from ADR-029's old numbers.**

---

## THE CUDA/HUGGINGFACE GAP DOES NOT MOVE A DECISION. 242/242, MEASURED, WITH A CONTROL.

**2026-08-17, continuing `7431baa`.** This closes item 1 of the list below â€” *"the CUDA/HuggingFace
gap is the blocker; take the ranking measurement ADR-029 took"* â€” and item 3, coexistence. Every
number here is a command that was run, and the prediction was committed (`9db08b9`) **before the
scoring run was launched**, not before it finished.

### The result

| | CPU (embedder) | CUDA (embedder) |
|---|---|---|
| session-level top-1, fit split | **0.9008** (218/242) | **0.9008** (218/242) |
| identical top-1 pick | â€” | **242 / 242** |
| gained / lost / net | â€” | **0 / 0 / 0** |
| McNemar exact two-sided | â€” | **p = 1.0** |
| top-10 slate, identical ORDER | â€” | **239 / 242** (3 reordered) |

**THE CONTROL, and it is the half that makes the headline mean anything.** A comparison of two runs
that were secretly the same run reports perfect agreement, which is also what a real null looks like.

| | value |
|---|---|
| candidate rows, each dump | **117,890** (identical count) |
| rows changed `dense_cosine` | **117,702 of 117,888 shared â€” 99.84%** |
| rows changed fused `score` | **18,583** |
| max abs Î” `dense_cosine` | **8.810e-5** |
| rows present in only one dump | 2 and 2 |

The prediction registered a hard floor: *"if fewer than 90% of rows move, the run did not use CUDA
and every number in it is vacuous."* 99.84% moved. **The inputs moved on essentially every row and
no decision moved.**

**The comparator is itself controlled, in both directions.** `tools/compare_top1.py` run
baseline-against-*itself* prints `VACUOUS -- the inputs did not move`; run on the
8192-vs-1024 pair it reproduces the numbers already on this page **exactly** â€” 242/242 identical,
**206** rows changed `dense_cosine`, **10,665** changed `score`, **4** rows only in the 8192 dump.
That is an independent re-derivation of an ad-hoc calculation from earlier today, agreeing to the
row.

### VERDICT, under the rule fixed in advance

> *If top-1 picks are identical, the tolerance failure is numerical noise below the decision
> threshold and CUDA is safe to default.*

**Picks are identical. The blocker is cleared by measurement.** `MAX_ABS_DIFF` was not widened,
`embedding-reference.json` was not regenerated, and neither was read by this run.

**What was NOT done, deliberately: the default was not flipped.** That is ADR-013 and ADR-015
territory and CLAUDE.md says a settled decision is argued explicitly, not designed around. The
measurement that was missing now exists; the ADR is a separate act, and two things belong in it â€”
`--embedder-provider auto` resolves against free VRAM *at that instant*, so two `marlowe-eval repro`
spawns on one machine can select two different scorers depending on what else is on the card, and
the coexistence readings below say the width really does move.

### The three slates that DID reorder, because "0 of 242" would have been the wrong claim

ADR-029 reported **0 of 229** slates reordered for the cross-encoder. The embedder is slightly
noisier: **3 of 242**, all at ranks 4â€“10, none at rank 1.

| query | what moved |
|---|---|
| `37d43f65` | ranks 9â€“10 swap; a rank-11 candidate enters at 9 |
| `45dc21b6` | ranks 4â€“8 permute; a rank-11 candidate enters at 4 |
| `71a3fd6b` | ranks 9â€“10 swap |

**Reported rather than rounded away.** The perturbation reaches the slate at depth 10 in 1.2% of
queries and reaches no winner. A claim of "nothing moved" would have been false and would have
made the next person's job harder.

### THE MECHANISM SHIPPED IN 7431baa CANNOT REACH A SCORED RUN, AND THE FIRST LAUNCH PROVED IT

The run failed in seconds with `cublasLt64_12.dll` Error 126 and the new hint â€”
*"MARLOWE_CUDA_LIB_DIR is not set"* â€” **while it was set in the launching shell.**

Â§4.0.9 is the reason: *"the harness spawns the target's argv unmodified, with a declared minimal
environment."* `minimal_env()` in `eval/src/marlowe_eval/adapter/subprocess_ndjson.py` is that
declaration, it is a fixed allowlist, and `MARLOWE_CUDA_LIB_DIR` is not on it. So the variable â€”
built this evening precisely so a CUDA configuration would stop living in somebody's shell â€” **was
stripped before the reader it was built for could run.**

**A control with a reader, on the path that deletes the value first.** Family #16 one layer out: the
question *"is there a line of code that reads it?"* was asked and answered yes, and the question
*"does the value survive the journey to that line?"* was not asked at all.

`eval/` is the scoreboard and is not modified for an implementation's convenience. **`PATH` is on
the allowlist**, and `PATH` is what the Windows loader actually reads â€” it is how every CUDA run in
`runs/session-l/` worked before any of this had a name. So `tools/score_longmemeval.py` now
translates the variable onto `PATH` in its own process before anything spawns, refuses a set-and-wrong
value naming the directory, and writes `ENVIRONMENT.json` beside every run recording what it did.
**Live-verified, not pipe-verified**: the run's own log carries the child's
`marlowe: embedder on CUDAExecutionProvider with 8 of 8 worker session(s)`.

### `--embedder-provider` reaches the scorer, and the run says so in three places

`score_longmemeval.py --embedder-provider cpu|cuda|auto`. The value is formatted into the target
string, which `report.json` records verbatim, so the provider is readable **from the artifact**
rather than from whoever typed the command:

```
... --reranking models/ms-marco-MiniLM-L-2-v2-ft-session-j --embedder-provider cuda --dump-gate-features ...
```

Plus `BINARY.json` (sha256 `62a035e8â€¦`, mtime 21:00, rebuilt after the source change and checked
before the run) and `ENVIRONMENT.json`. The CPU baseline's own `report.json` carries **no**
`--embedder-provider`, which is what makes it the CPU arm.

### One residual on the comparison, stated rather than buried

The CPU baseline was produced at 19:33 by a binary two commits older (`8653c32`, `7431baa` came
after). A same-binary CPU re-run would cost a **cold** re-embed, because `CacheIdentity` gained
`provider` in `8653c32` and every pre-existing namespace was invalidated. It was not run, and the
reason is that it could only matter if picks had moved: a binary confound can manufacture a
difference, and there is none to explain. `git diff` over those two commits touches the loader, the
CLI and the cache key and **does not touch `forward`, the pooling, the normalisation or the graph
options**, and `embedding_reference.rs` still measures CPU at 1.043e-7 against HuggingFace on the
current binary. **If a future comparison finds movement, take the re-baseline first.**

---

## OLLAMA COEXISTENCE: MEASURED. THE WIDTH IS DERIVED FROM LIVE FREE MEMORY AND IT REALLY MOVES.

### The overhead table, idle beside coexistent â€” cache OFF on every cell, 32 texts

`llama-server` holding `marlowe-red:9b` (6.6 GB, 100% GPU, 32k context). Free VRAM **12,065 MB idle
â†’ 5,532 MB coexistent**.

| tokens | workers | CPU idle | CPU coexist | CUDA idle | CUDA coexist |
|---|---|---|---|---|---|
| 102 | 1 | 28.90 | 29.61 | **2.24** | **2.15** |
| 102 | 8 | 4.94 | 5.15 | **2.93** | **2.93** |
| 502 | 1 | 157.42 | 159.01 | **2.93** | **2.57** |
| 502 | 8 | 29.22 | 32.67 | **3.05** | **3.06** |
| 1024 | 1 | 386.36 | 384.20 | **4.66** | **4.48** |
| 1024 | 8 | 86.93 | 92.18 | **4.59** | **6.77** |

**No OOM, and the model was still resident afterwards** (`ollama ps` re-checked). The CPU column is
the control that says the harness did not change under the treatment: it reproduces to within 6%
except at 1024Ã—8, where both providers show the contention. The one real coexistence cost is
**CUDA 1024Ã—8: 4.59 â†’ 6.77 ms**, +47%.

Device held at 8 workers falls under coexistence â€” **4,588 / 4,488 / 4,490 MB idle** against
**4,121 / 4,004 / 3,839 MB** â€” which is ORT's arena taking what is there rather than a fixed cost.

**The instrument, named because the obvious one does not work here.** Per-process
`nvidia-smi --query-compute-apps=pid,used_memory` returns `[N/A]` for every process under WDDM, and
the bench printed `-1.0` for a whole session's tables. It now prints the literal `[N/A]` and the
numeric column is **device-level `memory.free`, differenced against a baseline captured before the
first session opens**. That reading includes anything else that allocated in the window â€” which is
why the baseline is printed, and why a CPU row can read `device held -113.0 MB` (something else
freed).

### The width IS derived from live free memory, and here it is being cut

| free VRAM | plan | the reason string, verbatim |
|---|---|---|
| 12,065 MB (idle) | **8 of 8** | all requested sessions opened |
| 6,267 MB (9b resident) | **6 of 8** | *"device memory: 1509 MB usable would not hold another session plus a spare (793 MB each)"* |
| 1,645 MB (two models) | **1 of 8** | *"session 2 did not construct: â€¦ bad allocation"* |
| 1,366 MB (squeezed harder) | **1 of 8** | *"session 2 did not construct: â€¦ BFCArena â€¦ failed to allocate 62,521,344"* |

**Every one of those runs exited 0 and embedded at `MAX_SEQ_LEN` successfully.** Exhaustion degrades
the width; it does not fail the run. That is the `Auto` contract holding under a real card rather
than under `Probe::Fixed`.

**`--embedder-provider cuda` is the arm that can still fail, and that is correct** â€” its own reason
string says *"no VRAM budget was applied"*. It is the refusal arm for measurement cells.

### A DEFECT FOUND ON THE WAY, NOT FIXED, AND THE REASON IT WAS NOT

Look at rows 3 and 4 above. **The budget did not stop those runs â€” ORT's allocator did.** With 1,645
MB free and a real per-session cost of ~690â€“800 MB, the loop should have refused a second session on
its own arithmetic. It did not, and the trace says why:

`auto_sessions` warms the first session with `let _ = Self::forward(&mut first, â€¦)` and **throws the
result away**. If that warm-up fails, `free - after` is ~0, so `cost` falls back to
`session_cost_floor` = `model_bytes + ALiBi` = **188 MB â€” roughly a quarter of a real warmed
session**. The budget then authorises an attempt that cannot succeed, and what actually stops it is
the `bad allocation` two lines later.

**This is the project's own "a zero read as a floor rather than a ceiling" family**: the one signal
saying *the measurement is invalid* is the one that is discarded. Two candidate fixes, both
conservative â€” do not open further sessions when the first one's warm-up failed, and raise the floor
to something a warmed CUDA session actually costs.

**Not done, on purpose.** It is a change to a memory-budget policy whose failure branch cannot be
driven deterministically from a test â€” `Probe::Fixed` controls the *reading*, not whether ORT's
arena refuses â€” and this session's rule is that every fix gets a test that fails when reverted. A
budget change with no such test is exactly the shape that goes green and does nothing. **It is the
first item for the next session on this subsystem**, and the measurement above is the evidence.

Related and smaller: a full **CPU** fallback (`free < floor * 2`, first session refused before it is
attempted) was **not** observed live, because even at 1,366 MB free the first session constructs and
Ollama evicts its own models rather than let the card fill. That branch is covered by
`a_zero_vram_budget_falls_back_to_cpu_instead_of_failing_the_run` with a deterministic probe, and it
is honest to say the live version is unmeasured.

---

## THE EMBEDDER IS NOT USING 4 GB ANYWHERE. PER SESSION IT IS 312 MB HOST / 802 MB DEVICE.

Asked as a hard assertion rather than a reported number, because the 8192 defect was **4 GB per
session succeeding silently** and an aggregate hides it: 4.9 GB across eight sessions is 612 MB each
and unremarkable; the same 4.9 GB in one session is the bug.

### One session at `MAX_SEQ_LEN`, and the arithmetic beside it

`8 Â· NÂ² Â· 8` bytes for `[8, N, N]` int64 â€” at N = 1024 that is **67,108,864 = 64.0 MB**.

| | host | device |
|---|---|---|
| after load | 213.0 MB | 383 MB |
| after a short text | 213.0 MB | 418 MB |
| **after one forward at the cap** | **290.3 MB** | **802 MB** |
| the forward's own cost | **+77.3 MB** | **+384 MB** |
| ALiBi's prediction for that | 64.0 MB | 64.0 MB |

**On host the prediction is close: 77.3 measured against 64.0 predicted**, the remainder being
ordinary activations. **On device it is 6x out â€” 384 measured against 64 predicted â€” and the gap is
the finding.** The residual ~320 MB is *consistent with* per-layer attention score tensors, which are
`[batch, heads, N, N]` f32 and therefore quadratic in exactly the same way (`1 Ã— 8 Ã— 1024Â² Ã— 4` =
32 MB apiece). **It is consistent, not confirmed, and the distinction is deliberate**: this project
has twice matched a byte count to the wrong tensor, and `1 Ã— 8 Ã— 8192Â² Ã— 8` (int64) and
`2 Ã— 8 Ã— 8192Â² Ã— 4` (f32) give the identical 4,294,967,296. A decomposition that is not unique is
not proof. What *is* established is that the whole term is quadratic in N, which the 4096 mutation
below measures directly.

### It scales linearly in the worker count

| workers | host peak (CPU) | marginal | device held (CUDA) | marginal |
|---|---|---|---|---|
| 1 | 312.4 MB | â€” | 802 MB | â€” |
| 2 | 572.6 MB | 260.2 | 1,357 MB | 555 |
| 4 | 1,072.8 MB | 250.1 each | 2,503 MB | 573 each |
| 8 | 2,070.5 MB | 249.4 each | 4,647 MB | 536 each |

`802 + 550Â·(wâˆ’1)` predicts **4,652 MB** at eight workers against **4,647** measured. Linear, so
nothing is allocating per *call* or at a length nobody asked for, and the 8-worker figure reproduces
the ~4.9 GB already on this page.

**One number here is not what it looks like: CUDA's host peak at one worker is 1,057 MB**, and 560 MB
of it appears on the *first embed* â€” the CUDA runtime's host-side initialisation, a per-process
constant. Marginal host cost per CUDA session is ~93 MB (1,711 MB at eight). Not the embedder's, and
not per session.

### Asserted, in two tests that fail for different reasons

- **`hostmem::tests::the_shipped_cap_predicts_a_footprint_in_megabytes_not_gigabytes`** â€” pure
  arithmetic over the declared cap against a **fixed 256 MB literal**. No model, no card, cannot be
  flaky, fires the instant `MAX_SEQ_LEN` is raised.
- **`tests/session_footprint.rs`** â€” one real session, host **and** device, against fixed 768 MB /
  1536 MB literals. Arithmetic cannot answer this one: a graph allocating at a length nobody
  declared satisfies every constant in the build.

**Both ceilings are absolute literals and that is the whole design.** A bound derived from
`MAX_SEQ_LEN` rises with it, so raising the cap would raise its own ceiling and the guard would go
quiet at exactly the moment its subject changed.

**Mutation run â€” `MAX_SEQ_LEN` 1024 â†’ 4096 in a scratch build, then restored:**

| guard | reading |
|---|---|
| arithmetic | **FAILED** â€” *"4096 predicts an ALiBi matrix of 1024 MB per session, over the 256 MB ceiling"* |
| measured (host) | **FAILED** â€” *"peaked at 2234.3 MB, over the 768.0 MB ceiling"* |

2,234.3 MB at 4096 against 290.2 MB at 1024: the matrix grew 960 MB and the peak grew 1,944 MB â€”
**about twice the ALiBi term**, which is the same quadratic companion the device reading showed, now
measured on host where the total can be attributed. `MAX_SEQ_LEN` is committed at **1024**.

The device test also carries a **floor** (`held >= model_bytes`), because a ceiling alone passes on
the failure that matters most: a session that quietly became CPU holds no device memory, and 0 is
under every ceiling.

---

## `elapsed.rs` â€” THE TWO RELEASE-MODE FAILURES ARE FIXED, AND ONE OF THEM WAS VACUOUS

`finish_is_what_closes_the_last_stage` asserted `as_profile_us() > 0` after timing
`black_box((0..20_000).sum::<u64>())`. In `--release` the optimizer folds that to a constant, the
span rounds to zero, and **the test failed deterministically on code that was working perfectly**.
Its sibling `a_stage_entered_twice_accumulates_rather_than_restarts` read `0 >= 0` in the same
build: green, and saying nothing.

**The fix is to stop timing a workload and start timing the clock.** `spin_past_micros` returns as
soon as `Instant` reports the microseconds it was asked for â€” it cannot be optimized away, because
the value comes from outside the program â€” so the assertion is about `finish` banking an elapsed
span rather than about how fast the build is.

Three further corrections, each of which was a real hole:

1. **`finish_is_what_closes_the_last_stage` now asserts the stage CLOSED**, structurally
   (`open.is_none()`), *and* that closing banked something. The name has two halves and only one of
   them is a duration.
2. **`a_stage_entered_twice` compares Rerank against ITSELF one visit later**, not against an empty
   `Assemble`. The old comparison measured the *scheduler*: `Assemble` spans two adjacent statements,
   so a deschedule between them makes it arbitrarily large and the test fails on a busy machine. It
   failed that way here, once, before being rewritten.
3. **Three visits, not two, because the total is banked in TWO places.** A visit ended by `enter` is
   banked by `enter`; the last is banked by `finish`. An intermediate version of this test closed its
   second visit with `finish`, and **the `enter`-side mutation stayed green.** Caught by running the
   mutation, not by reading the test.

| mutation | result |
|---|---|
| `finish` closes the stage but banks nothing | **FAILED** â€” *"a zero total means the stage was dropped rather than closed"* (both tests) |
| `enter` restarts rather than accumulates | **FAILED** â€” *"read 501 us after one visit and 1 us after two"* |
| `finish` overwrites rather than accumulates | **FAILED** â€” *"502 us after two visits and 1 us after three"* |

`cargo test -p marlowe --bin marlowe -- elapsed::tests`: **6 passed in release and 6 in debug, three
interleaved rounds each.**

---

## Counts, and the profile they were taken in

| | |
|---|---|
| `cargo test --workspace --jobs 4 --no-fail-fast` (**debug**, `MARLOWE_CUDA_LIB_DIR` set) | **915 passed, 0 failed, 2 ignored** (from 909 / 1) |
| `cd eval && python -m pytest` | **72 passed**, unchanged â€” `eval/` was not touched |

The six new passes: three `hostmem` unit tests, `session_footprint`, a new `elapsed` idempotence
test, and the previously-failing `finish_is_what_closes_the_last_stage`.

## Instruments left behind â€” grep these rather than re-running

`runs/session-e-cuda/` â€” `PREDICTION.md` (committed before the run), `top1-cpu-vs-cuda.json`,
`fit-cuda/` (the scored run, with `BINARY.json` and `ENVIRONMENT.json`), `bench-idle.txt`,
`bench-coexist.txt`, `coexist-plan-{1model,2models,3models}.txt`,
`coexist-one-session-squeezed.txt`, `footprint-{cpu,cuda}.txt`, `footprint-test.txt`,
`elapsed-{baseline,rounds,mutations}.txt`, `maxseq-mutation.txt`, `suite.txt`, `eval-suite.txt`.

`tools/compare_top1.py` is the reusable half: it is the ADR-029 measurement, and it refuses to let a
null result be read without its control.

## What this session did NOT close

1. **The default is still `cpu`.** The measurement that blocked it exists now; the ADR does not.
2. **`auto_sessions` swallows its warm-up failure**, so the per-session cost estimate collapses to a
   4x-too-small floor on a full card. Measured above, not fixed, and the reason is stated.
3. **A live first-session CPU fallback is unmeasured** â€” the card could not be squeezed below the
   threshold with Ollama, which evicts its own models first.
4. **`tools/session_l_gpu_recovery.py` has still not been re-run** (ADR-029's standing obligation:
   node placement was verified once, in Python, at ORT 1.24.2, and this build links 1.22).
5. **`RerankPlan::select` still has no call site.**
6. **`MARLOWE_CUDA_LIB_DIR` is still not in `CLAUDE.md`'s build section**, and it should be now that
   item 1 of the previous list is settled â€” together with the Â§4.0.9 note, because the next person to
   set it and run the scorer will otherwise hit the same wall.


## CUDA WORKS ON THIS MACHINE AND ALWAYS DID. THE CONFIGURATION THAT MADE IT WORK LIVED IN A SHELL.

**2026-08-17, later the same day. This CORRECTS the section below titled *"AND CUDA DOES NOT LOAD ON
THIS MACHINE AT ALL"*, which is false.** Every claim here is a command that was run.

### The finding, and it is a finding about the BUILD rather than about the hardware

`ort`'s CUDA provider now constructs, for the embedder **and** the reranker, on the shipped graphs.
Nothing was installed. The CUDA 12.1 runtime and cuDNN 9 were on the disk the whole time â€” 4.2 GB of
them â€” inside `site-packages/torch/lib`, where `torch 2.5.1+cu121` ships its private copy.

**And the project already knew.** `DECISIONS.md` ADR-015 says it in two lines: *"No CUDA Toolkit is
installed and none is needed: `torch 2.5.1+cu121` bundles what ORT 1.24 requires in
`site-packages/torch/lib`, and they were not on ORT's DLL search path."* The previous session's
statement *"there is no CUDA toolkit installed"* is **true**, and the conclusion drawn from it â€”
that CUDA cannot run here â€” contradicts a recorded ADR that was three lines long and said exactly
how to fix it. *"The DLL cannot be found"* was read as *"the DLL does not exist"*. **Before
concluding a library is absent, look for it.** It is one `find`.

### THE HEADLINE IS NOT "GPU NEVER WORKED FROM RUST". IT IS THE OPPOSITE, AND IT IS WORSE.

The premise handed to this session was that GPU work here had always been Python and never Rust.
**That is wrong, and `runs/session-l/RESULT.md` Â§5b says so in its own words:** *"Warm-249, **Rust**,
end to endâ€¦ `PATH` carries torch's bundled CUDA libraries for every cell."* The `s2-cuda/` and
`s4-cuda/` artifacts carry `run.target` strings naming
`target/release/marlowe.exe --eval-adapter â€¦ --rerank-provider cuda`, and every
`retrieval-profile.ndjson` row reads `"rerank_provider":"CUDAExecutionProvider"` â€” a field only the
Rust profiler writes.

**So ADR-029's rerank-on-CUDA HAS executed in the shipped Rust path**, and produced its published
numbers (CUDA batched 3.4 ms against CPU's 195.6). What it has never had is a way to *keep* working.

**The precondition had no declaration, no reader, no validation and no test.** It was an environment
variable in somebody's terminal. A configuration that exists only in a shell is indistinguishable
from one that does not exist at all â€” so it did not survive the session boundary, the same binary on
the same machine failed, the failure was measured *correctly*, and the conclusion drawn was that the
hardware was incapable. **This is the "declared control that nothing reads" family with the control
living outside the process entirely**, and it is the first instance where the missing reader cost a
*capability* rather than a guarantee.

### The hypothesis this session was asked to test FIRST is REFUTED, and measured false

*"Python's `onnxruntime-gpu` wheel bundles its own CUDA libraries; Rust's `ort` links a system
install."* **No.**

- `site-packages/onnxruntime/capi/` holds `onnxruntime_providers_cuda.dll` (312 MB) and **no CUDA
  runtime at all** â€” no `cublasLt64_12.dll`, no `cufft64_11.dll`, no cuDNN.
- A bare `python -c "import onnxruntime; InferenceSession(â€¦, providers=['CUDAExecutionProvider'])"`
  fails with the **identical** `cublasLt64_12.dll` Error 126 â€” and then **returns a CPU session
  reporting `['CPUExecutionProvider']`**. Session G's silent fallback, in its original habitat.
- `import torch` first, and the same call returns `['CUDAExecutionProvider', 'CPUExecutionProvider']`.

`import torch` calls `os.add_dll_directory(torch/lib)` as a side effect. **The difference was never
the language or the runtime. It was whether something had put a directory on the search path** â€” and
in Python that happened by accident of import order. `tools/session_l_gpu_recovery.py` does it
deliberately at line 38 and says so.

### Where CUDA is, and whether it is reachable today

| Where | Language | Runtime | Reachable today |
|---|---|---|---|
| `cue/dense/embedder.rs` `session()` â€” both provider arms, `error_on_failure` | Rust | `ort` 2.0.0-rc.10 | **yes, AND IT IS THE DEFAULT** â€” `--embedder-provider` defaults to `auto` since ADR-044; the `default `cpu`` this row used to read is superseded |
| `rerank.rs` `load_pinned()` â€” ADR-029's path | Rust | `ort` | **yes** â€” `--rerank-provider cuda`, default `cpu` |
| `cue/dense/vram.rs` | Rust | shells `nvidia-smi` | yes; **per-process VRAM is `[N/A]` on this driver** |
| `retrieve.rs` `RerankPlan::select` | Rust | `ort` (indirect) | **no â€” has no call site in the product** |
| `examples/cuda_probe.rs`, `examples/embed_provider_bench.rs` | Rust | `ort` | yes |
| `tools/session_l_gpu_recovery.py`, `session_l_gpu_spike.py` | Python | `onnxruntime-gpu` 1.24.2 | yes; these do the `add_dll_directory` dance |
| 12 sweep tools (`sweep_*`, `reach_*`, `finetune_v2`) with `--provider` **defaulting to CUDA** | Python | `onnxruntime` | yes |
| `session_i_rerankers.py`, `readers.py` and ~10 dependants | Python | `onnxruntime` | yes, **defaulting to CPU** |
| `eval/` | â€” | â€” | **`onnxruntime` is BANNED there** by `test_no_retriever.py` |

`ort` is `=2.0.0-rc.10` with `["download-binaries", "cuda"]`; there is no `build.rs`, no `.cargo/`,
and no `ORT_*` variable anywhere in the repo. `marlowe-embed-spike` pins `ort` **without** `cuda`.

### What shipped: the shell incantation became an input with a reader

`crates/marlowe-memory/src/cue/dense/cuda_libs.rs` â€” `MARLOWE_CUDA_LIB_DIR`.

| | |
|---|---|
| One directory or several | `std::env::split_paths`; a toolkit install and a cuDNN install are normally two, so the requirement is on their **union** |
| Validated at load | every entry must be a directory, and the union must contain all of `cublasLt64_12`, `cublas64_12`, `cudart64_12`, `cufft64_11`, `cudnn64_9` |
| **Refusal, never a warning** | set-and-wrong is refused and the message **quotes the path the human typed**. ORT's Error 126 names a *library*, never the misconfiguration |
| Empty string is refused | `""` is a configuration that meant to point somewhere, not "unset" |
| Applied **once**, by `OnceLock`, before the first session | the provider DLL is loaded lazily, so this has to precede it or it has not happened |
| **No auto-discovery** | nothing searches for PyTorch or Ollama. Silently borrowing another product's private runtime would make this build's numbers depend on an unrelated package's version |
| Non-Windows says **`Unsupported`** | Linux's loader reads `LD_LIBRARY_PATH` once at process start, so an in-process set cannot work. Saying `Applied` there would be a declaration with no reader |

**The Ollama case now fails usefully.** Pointing at its private `cuda_v12` previously moved Error 126
from `cublasLt64_12.dll` to `cufft64_11.dll`, one link at a time. It now refuses up front naming
**both** `cufft64_11.dll` and `cudnn64_9.dll` â€” the whole gap at once.

### Mutation runs â€” the unit tests are NOT the guard, and that was the point

The seven `cuda_libs` unit tests assert what `resolve` decides. **Every one stays green if the call
into it is deleted from both loaders** â€” the property asserted where it is *defined* rather than
where it is *enforced*, which is instance #16's exact shape. `tests/cuda_libs_wiring.rs` is the other
half: it points the variable at an absent directory and requires the **loaders** to refuse in
`cuda_libs`' words.

| Reverted | Failed |
|---|---|
| the `ensure_search_path` call in `Embedder::session` | `both_loaders_read_the_cuda_lib_variable_and_refuse_in_its_words` â€” *"the refusal did not quote the configured path, which means the request reached ORT instead"* |
| the same call in `CrossEncoder::load_pinned` | the same test â€” *"so ADR-029's CUDA path is unguarded"* |

Both mutations produced ORT's `Error 126` in place of the named refusal, which is precisely the
before-state.

### ADR-015 ON CUDA: three readings taken, and they are NOT inherited from CPU

`cargo test -p marlowe-memory --test embedder_provider` â€” **8 passed, and they RAN rather than
skipped** (no `SKIP` line in the output; they had skipped on every previous run in this project).

| Property | CUDA reading |
|---|---|
| Determinism, two calls one process | **bit-identical** |
| Worker invariance, 1 vs 2 vs 8 | **bit-identical** |
| Batch-composition invariance (alone vs in a batch) | **bit-identical** |
| A loaded CUDA session holds **device** memory | holds â‰¥ the graph's size |

### THE REFERENCE CHECK ON CUDA FAILS THE CPU TOLERANCE, AND THAT IS A RESULT, NOT A NUISANCE

`embedding-reference.json` is HuggingFace / sentence-transformers output and **was not regenerated,
and must not be.** Re-checked on CUDA, 41 cases, reproduced across two runs:

| provider | median | p95 | max | over 1e-4 | min cosine |
|---|---|---|---|---|---|
| CPU | 5.960e-8 | 8.196e-8 | **1.043e-7** | 0/41 | 0.99999994 |
| CUDA | 3.072e-5 | 5.198e-5 | **1.063e-4** | **1/41** | 0.99999970 |

**`MAX_ABS_DIFF` is 1e-4, so CUDA exceeds it.** The distribution matters more than the max: CUDA is
**~500Ã— further from the reference across the whole distribution**, not one pathological input with a
clean body. The single case over the line is a degenerate 1024-token `"the the theâ€¦"` text.

**Nothing was widened to make anything green.** `MAX_ABS_DIFF` is untouched and still guards CPU. The
CUDA test asserts **cosine** â€” unrelaxed at 0.9999, measured 0.99999970, and the property retrieval
actually reads, since ranking is by cosine â€” plus a **provisional tripwire** `CUDA_MAX_ABS_DIFF =
1e-3`, one order of magnitude above what was observed, so a *drift* fails while today's known gap
does not. **It is explicitly not a tolerance:** a tolerance is derived from the gap between two
faithful implementations, as `MAX_ABS_DIFF`'s own doc comment does for CPU, and rounding up the first
number ever measured would be fitting the threshold to the observation.

**THIS BLOCKS DEFAULTING THE EMBEDDER TO CUDA AND IT IS AN ADR.** ADR-029 met the identical wall on
the cross-encoder and **amended the requirement to ranking equivalence after measuring it** â€” 0/229
slates reordered. The equivalent measurement here is a retrieval run scored on CUDA against the CPU
baseline. **It has not been taken.** Until it is, this records agreement in direction and
disagreement in components, and claims nothing about R@1.

### Per-prompt overhead, cache OFF, 32 texts per cell â€” `runs/session-e-cuda/provider-bench-cuda.txt`

**The CUDA column exists for the first time.** Two runs; both reported, because the spread is part of
the reading.

| tokens | workers | CPU ms/emb | CUDA ms/emb | speedup |
|---|---|---|---|---|
| 102 | 1 | 31.58 / 31.05 | **3.29 / 3.12** | ~9.8Ã— |
| 102 | 8 | 6.30 / 6.55 | **3.68 / 3.66** | ~1.7Ã— |
| 502 | 1 | 171.90 / 179.71 | **4.81 / 6.34** | ~32Ã— |
| 502 | 8 | 37.42 / 35.79 | **3.51 / 3.78** | ~10Ã— |
| 1024 | 1 | 431.45 / 442.27 | **8.63 / 6.63** | ~58Ã— |
| 1024 | 8 | 99.17 / 98.85 | **5.94 / 6.10** | ~16Ã— |

**The CPU column reproduces the reading already on this page** (31.58 vs 30.28, 171.90 vs 170.91,
431.45 vs 438.13), which is the control that says the harness did not change under the treatment.
**CUDA at one worker beats CPU at eight in every row.** Run-to-run spread on the CUDA cells reaches
**23%** at one worker (8.63 vs 6.63), which is wider than several differences a careless reading
would call results.

### VRAM: the bench's own column is UNAVAILABLE on this machine, and it prints `-1.0`

`nvidia-smi --query-compute-apps=â€¦,used_memory` returns **`[N/A]`** for every process here â€” WDDM
does not report per-process device memory â€” so the bench's `vram` column is structurally unreadable
and shows its sentinel. **Do not read `-1.0 MB` as "used no VRAM".** Measured device-level instead,
by sampling `memory.used` at 150 ms through a whole bench run:

| | MiB |
|---|---|
| Baseline (other apps: browsers, Discord, Edge) | 4,567 |
| **Peak during the run** | **9,507** |
| **Attributable to the embedder, 8 workers Ã— 1024 tokens** | **~4,940 (~4.9 GB)** |
| Card total | 16,376 |

**No OOM at the derived worker count** â€” the bench opened `workers 8` and completed every cell.

**AND THE COEXISTENCE CASE IS NOT DEMONSTRATED.** `llama-server` was **not resident** during this
measurement (11.5 GB free at start). When Ollama holds its usual ~11.5 GB, only ~4.8 GB remains and
**~4.9 GB does not fit** â€” the budget in `auto_sessions` would cut the width, which is what it is
for, but *that* path is still unexercised. A K6-style run needs the model and a CUDA embedder
resident at once and **nobody has measured whether they co-fit.**

### A NEAR-MISS WORTH MORE THAN THE FIX: I ALMOST BLAMED MY OWN CHANGE FOR AN INTERMITTENT FAILURE

Three tests failed under the new mechanism and passed under a raw `PATH`. I ran one of each, called
it a controlled comparison, and had begun writing up *"in-process `set_var` breaks it"*. **It
reproduced neither way.** Interleaved, three rounds each, no compilation in between:

| round | `PATH` | `MARLOWE_CUDA_LIB_DIR` |
|---|---|---|
| 1â€“3 | 8 passed, 0 failed | 8 passed, 0 failed |

The failures were the **known intermittent `bad allocation`** already on this page, and they
correlate with `cargo` compiling concurrently â€” CLAUDE.md's parallel-checkout hazard #6, *a build
invalidating a measurement*, landing on this session's own measurement. **n = 1 on each side of a
comparison is not a control**, which is this file's own standing rule about post-hoc results, met in
the cheapest possible form.

### THE ERROR NOW CARRIES THE REMEDY, AND I COMMITTED FAMILY #16 WHILE WRITING ABOUT FAMILY #16

`hint_when_unconfigured()` was written, and **nothing read it** â€” a declared control with no reader,
added in the same hour as a module header explaining that exact failure. Caught by asking the
module's own question of my own code: *is there a line that reads this?*

It is now attached to both loaders' error paths and covered by `tests/cuda_libs_hint.rs`. A CUDA
session that fails on a **missing library** while `MARLOWE_CUDA_LIB_DIR` is **unset** now returns
ORT's message plus *"'missing' here means NOT FOUND rather than NOT INSTALLED â€” a CUDA Toolkit is one
source and it is not the only one."* That sentence is the entire difference between this session and
the last one.

**Narrow on purpose, in three ways**, because a hint that fires everywhere is the trust-floor banner
again: CUDA only, **library-load failures only** (`Error 126` / *"which is missing"* â€” a
`bad allocation` is a real OOM and must not be relabelled), and **unconfigured only**, since a
configured-and-refused run has already been told what is wrong with the value it gave.
`is_library_load_failure` matches on text because `ort` exposes no error code, and the blast radius
is bounded: the worst case is an advisory sentence appearing, or not appearing. **It never changes
whether the load succeeds.**

`cuda_libs_hint.rs` and `cuda_libs_wiring.rs` are **separate test binaries on purpose** â€” the
resolution is cached per process by `OnceLock`, and the two files measure opposite states of the
variable. The hint test **skips loudly** if CUDA constructs, rather than passing on an untested
branch.

### `elapsed::tests` FAIL IN RELEASE AND PASS IN DEBUG, AND THAT IS PRE-EXISTING

The final workspace run reads **907 passed / 2 failed**, and neither failure is this session's:
`elapsed::tests::finish_is_what_closes_the_last_stage` and
`a_stage_entered_twice_accumulates_rather_than_restarts`, both in `crates/marlowe/src/elapsed.rs`,
a file this session never opened (`git diff` on it is empty).

Both do `std::hint::black_box((0..20_000).sum::<u64>())` and then assert `as_profile_us() > 0`.
**In release the optimizer makes that work sub-microsecond, so the reading rounds to zero.**
Measured both ways:

| mode | result |
|---|---|
| `cargo test -p marlowe --bin marlowe -- elapsed::tests` (**debug**, CLAUDE.md's documented command) | **5 passed, 0 failed** |
| the same in `--release` | **3 passed, 2 failed**, five runs out of five |

**Deterministic, not flaky** â€” which is why the first reading of it as a flake was wrong. One earlier
run showed only one of the two failing, and that *is* borderline timing, so the pair sits right at
the resolution edge. **A test that asserts a duration is positive is asserting that the work it
timed was slow enough to see**, and that is a property of the build profile, not of the code under
test. Recorded rather than fixed: it is outside this session's scope and it changes a timing
assertion.

**Consequence for anyone quoting a suite count: state the profile.** A `--release` count and a debug
count are not the same measurement on this workspace.

### To close it, in order

**AMENDED 2026-08-17, later: items 1 and 3 are DONE â€” see the top of this file. 242/242 identical
top-1 picks with 99.84% of candidate rows changed, and the coexistence table measured beside the
idle one. Items 2, 4 and 5 stand.**

1. ~~**The CUDA/HuggingFace gap is the blocker.**~~ **MEASURED AND CLEARED.** The ranking
   measurement ADR-029 took now exists for the embedder: 242/242 identical top-1, McNemar p = 1.0,
   3 of 242 top-10 slates reordered at ranks 4-10. The ADR itself is still unwritten, so
   `--embedder-provider cuda` remains a measurement tool by decision rather than by ignorance.
2. **Re-run `tools/session_l_gpu_recovery.py`.** ADR-029's standing obligation: node placement was
   verified *once, in Python, at ORT 1.24.2*, and this build links 1.22. **13.6% of nodes on CPU** is
   a number about a runtime this binary does not use. `ort` still exposes no node enumeration.
3. ~~**Measure Ollama + CUDA embedder coexistence**~~ **MEASURED.** No OOM at the derived width;
   the width is cut from 8 to 6 to 1 as the card fills, with the reason string naming the number;
   every case exited 0. One defect found in the budget's cost estimate and NOT fixed â€” see the top
   of this file.
4. **`RerankPlan::select` has no call site.** Dead since it was written; either wire it or delete it.
5. **`MARLOWE_CUDA_LIB_DIR` is not in `CLAUDE.md`'s build section.** It should be, once 1 is settled.
6. **`elapsed.rs`'s two release-mode failures**, above. A timing assertion, not this session's scope.

### How to run CUDA here, so this is never rediscovered

```bash
# Windows. One directory, or several separated by ';'. Refused at load if incomplete.
export MARLOWE_CUDA_LIB_DIR="C:\Users\<you>\AppData\Local\Programs\Python\Python311\Lib\site-packages\torch\lib"

cargo run -p marlowe-memory --release --example cuda_probe          # constructs? both graphs
cargo test -p marlowe-memory --release --test embedder_provider     # the ADR-015 readings
cargo run -p marlowe-memory --release --example embed_provider_bench -- models/jina-embeddings-v2-small-en
```

**That directory is PyTorch's private CUDA runtime and nothing in the build discovers it** â€” the
variable is the only way in, deliberately, so that a number can never depend on whether an unrelated
package happens to be installed. A real CUDA Toolkit + cuDNN 9 install works identically; point the
variable at both directories.

### Instruments left behind

`runs/session-e-cuda/` â€” `provider-bench-cuda.txt` and `-cuda2.txt` (the two bench runs),
`embedder-provider-cuda.txt`, `memory-tests-cuda.txt`, `serial-tests.txt`, `vram-samples.txt` (166
device samples at 150 ms), `suite-cuda.txt`, `suite-final.txt`, `suite-with-hint.txt`. Grep these
rather than re-running; a workspace suite plus a CUDA bench is not a load to run twice.

## MAX_SEQ_LEN 8192 â†’ 1024. THE EMBEDDER WAS USING 8.6 GB AND NOBODY KNEW, BECAUSE IT SUCCEEDED.

### What was wrong

This export builds ALiBi's relative-distance matrix explicitly â€” `Abs(Range(0,N) âˆ’ Range(0,N)áµ€)`
expanded to `[8, N, N]` at **int64**, so `8Â·NÂ²Â·8` bytes, quadratic, **per session**. At N = 8192
that is **4,294,967,296** â€” the exact figure in the `bad allocation` the two embedder reference
tests were failing with.

**It is not a defect in the graph.** Inputs are `['batch_size', 'sequence_length']` and the Expand's
shape is computed at runtime. The shape is correct; 4 GB is simply what ALiBi costs at 8192 in this
export. An earlier reading of this as a frozen `max_position_embeddings` was **wrong**, and the way
it was wrong is the lesson: `2 batch Ã— 8 heads Ã— 8192Â² Ã— 4 bytes (f32)` and
`1 Ã— 8 heads Ã— 8192Â² Ã— 8 bytes (int64)` produce the **identical byte count**. The arithmetic matched
perfectly and named the wrong shape. Matching is not confirming.

So the real finding was never a leak: **`MAX_SEQ_LEN = 8192` was declared and not reachable.** The
only two tests that embedded at the declared maximum were the only two failing.

### Memory, measured with a control

| `MAX_SEQ_LEN` | after load | at max length |
|---|---|---|
| 8192 | 232.4 MB | **8,813.4 MB** |
| **1024** | 237.3 MB | **377.4 MB** |

**23Ã—.** And the control **succeeded** at 8192 â€” the machine happened to have 8.6 GB free. That is
the whole intermittency: it was not failing, it was silently using 8.6 GB whenever a long text
arrived. `cargo run -p marlowe-memory --release --example embed_memory`.

### Why 1024, chosen from the distribution and NOT by sweeping a score

`--example token_lengths` over all 246,750 turns: **p50 96, p90 594, p95 667, p99 796, max 16,666**.
The distribution has a hard shoulder just under 800.

| cap | turns truncated | tokens lost | ALiBi matrix |
|---|---|---|---|
| 512 | 16.55% | 10.0% | 16 MB |
| 768 | 1.46% | ~2% | 36 MB |
| **1024** | **0.18%** | **0.891%** | **64 MB** |
| 2048 | 0.07% | 0.383% | 256 MB |
| 8192 | 0.002% | â€” | **4.29 GB** |

**512 was the first recommendation and the data refuted it** â€” one turn in six truncated, a tenth of
the corpus lost. It was reasoned from mean-pooling dilution without measuring first.

The value was picked by the length distribution deliberately, not by sweeping R@1. Four mechanisms
in this project have cleared a fit bar and died on held-out; *a rule with a tunable knob is already
suspect on this corpus*. R@1 is a **check that nothing broke**, never the thing that chose the number.

### Capability, answered exhaustively rather than statistically

**The longest GOLD turn in the entire corpus is 1,039 tokens** (`--example gold_lengths`).

| cap | gold truncated | gold tokens lost |
|---|---|---|
| 512 | 10 | 2.40% |
| **1024** | **1** | **0.020%** (15 tokens) |
| 2048 | 0 | 0.000% |

The one is query `5809eb10` â€” *"what year was the Bajimaya case"*, answer **2014**, which sits at
**character 917 of 5425, 16.9% into the turn**. What it loses is
`"â€¦protected in the event of a dispute.\n\nPlease write in English language."`

**2048 remains a legitimate alternative**: zero gold loss for 4Ã— the memory. 1024 was chosen because
the matrix is transient per inference and workers run concurrently â€” 8 workers is 512 MB at 1024
against 2 GB at 2048.

### R@1: zero change, with a control proving the comparison discriminates

Prediction registered and committed **before the run finished** (`runs/session-e-maxseq/PREDICTION.md`).

| | baseline (8192) | treatment (1024) |
|---|---|---|
| session-level top-1 | **0.9008** (218/242) | **0.9008** (218/242) |
| identical top-1 pick | â€” | **242 / 242** |
| gained / lost | â€” | **0 / 0** |

**The control:** 206 candidate rows changed `dense_cosine`, 10,665 changed their fused `score`. The
inputs moved; no decision did.

**Caveat, stated because it invalidates part of the prediction:** `5809eb10` is in the **held-out**
split, so the one truncated gold turn is not in this comparison and the prediction about it is
**untested**. Confirming it would spend a held-out read. On the fit split, zero gold turns truncate.

**Four candidates vanished** at 1024. Explained: turn 0 of that session is 8,930 chars and turn 1 is
3,453 opening with nearly the same sentence â€” the assistant echoing the user. Truncating the longer
one made the pair **more similar**, crossing consolidation's 0.98 dedup threshold, so they merged.
Consolidation working as designed on a genuine near-duplicate. Well-supported, **not** directly
measured â€” the pair's cosine before and after was not read.

### THE STALE-BINARY NEAR-MISS, and it is the methodological result of the session

The first scoring run wrote to `fit-1024/` and **measured 8192**. `score_longmemeval.py` drives
`target/release/marlowe.exe`, and **`cargo run --example` does not rebuild it**: binary 17:29:28,
source change 18:44:29, run 18:47. The source said 1024, the artifact said 8192, and the directory
name agreed with the source.

Same family as a persona test passing while the deployed daemon served a pre-persona binary. **A
source edit is not a deployed change.**

Kept as `runs/session-e-maxseq/fit-8192-BASELINE/` with a note, because it is a correctly-measured
control on this machine minutes from the treatment â€” worth more than citing 0.7555 from another day.
**`score_longmemeval.py` now writes `BINARY.json`** (sha256, size, mtime) beside every run so a
reader checks the artifact instead of the directory name.

Two smaller instances of the same shape, recorded because they nearly landed:
`cmd | tail -30` returns **tail's** exit status, so a failed gate fit reported as "exit code 0"; and
a monitor gated on `pgrep -f`, which does **not** see Windows processes, fired on a 6.7 MB partial
dump that later reached 72.8 MB.

### `fit_gate.py` HAS BEEN BROKEN SINCE SESSION H

Its target string never got `--reranking`, mandatory since Session H with no default. The binary
prints usage and exits; the transport reports `implementation_crashed` â€” the exact symptom CLAUDE.md
warns "reads like a protocol bug and is not one". **The gate could not have been re-fit at any point
since**, and nobody found out because nobody re-fit it until `MAX_SEQ_LEN` forced it.

Fixed by passing the **shipped** reranker rather than `off`. The gate calibrates
`lexical_margin`/`dense_margin` and ranks on `lexical_z`/`dense_z` â€” no rerank feature exists â€” so on
that argument the two are equivalent. The asymmetry: that only holds if reranking never touches the
*population* features are dumped over, and this is a build-time artifact the binary refuses to start
without. The shipped graph matches what `score_longmemeval.py` scores under.

### The gate was re-fit, and its ceiling is IDENTICAL â€” so the abstention is not this change

`gate-frozen-v5.json` re-fit at 1024 (117,890 rows, 450 positive, 344 s). Compared against the
committed 8192 artifact:

| cue | old ceiling | new ceiling |
|---|---|---|
| `lexical_margin` | 0.3739 | **0.3739** |
| `dense_margin` | 0.3413 | **0.3413** |

**To four decimals, both curves, before and after.** So the fit's own warning â€” *"no cue's curve
reaches the frozen threshold of 0.95, the gate will abstain on every query"* â€” is **pre-existing and
not caused by `MAX_SEQ_LEN`**. It is the two-of-five-cues finding already on this page, and reading
it as a regression from this change would be wrong.

The only real diffs: `fit_rows` 117,894 â†’ 117,890 (the four near-duplicate merges, consistent to the
row), and `floor_measured` 0.5371 â†’ `None` / `floor_verdict` `fail` â†’ `unmeasured`, because
`runs/session-f/cue-overlap.json` was not regenerated. **The floor was reading `fail` before**, so
nothing that was passing has stopped.

### What changing this invalidated, and what was done about each

- **Both reference fixtures** regenerated at 1024 from **HuggingFace / sentence-transformers**, not
  from our Rust â€” the authority direction is intact. Pooling cross-check 5.96e-08, min cosine
  0.99999994.
- **The embedding cache key** contains `MAX_SEQ_LEN`, so every cached vector invalidated and the
  corpus re-embedded cold (~80 min). **The guard did its job**: without it this run would have
  served 8192-era vectors under the 1024 label â€” the stale-artifact failure one layer down.
- **The fitted gate**, re-fit above.

## THE EMBEDDER ASKS FOR ITS PROVIDER NOW. ~~AND CUDA DOES NOT LOAD ON THIS MACHINE AT ALL.~~

> **SUPERSEDED 2026-08-17 â€” the second half of that heading is FALSE. See the top of this file.**
> CUDA loads here, for the embedder and the reranker, and always could: the CUDA 12 runtime ships
> inside `site-packages/torch/lib` and simply was not on ORT's DLL search path. The plumbing
> described below is correct and still shipped; every sentence asserting that the *machine* cannot
> do CUDA is wrong, including *"the cause is a missing CUDA toolkit"* and the whole of **WHAT COULD
> NOT BE CLOSED**, whose four "unmeasured" items are now measured. The section is kept unedited
> because the reasoning that produced it is instructive and because its CPU numbers are a valid
> control â€” but **do not quote its conclusions.**

**2026-08-17.** The TODO this replaces is closed *as code* and **open as a measurement**, and the
gap between those two is the whole entry. `Embedder::session` used to call no
`with_execution_providers` at all; it now takes an `EmbedProvider` and registers it with
`error_on_failure()` on **both** arms. What did not happen is a single CUDA number, because â€”

### THE FINDING: ORT's CUDA PROVIDER CANNOT LOAD HERE, FOR EITHER GRAPH, AND THE CONTROL SAYS SO

`cargo run -p marlowe-memory --release --example cuda_probe`
(`runs/session-e-embedder-gpu/cuda-probe.txt`):

```
-- embedder, ProviderChoice::Cuda (no fallback)
   ERR: Error loading "...onnxruntime_providers_cuda.dll" which depends on
        "cublasLt64_12.dll" which is missing. (Error 126)
-- reranker, RerankProvider::Cuda (the CONTROL: unchanged since ADR-029)
   ERR: ...the same error, on the same DLL...
```

**The reranker is the control and it fails identically.** So this is a fact about the box, not
about the embedder change: nothing in `rerank.rs` moved, and `--rerank-provider cuda` would
hard-error today exactly as `--embedder-provider cuda` does. **Any claim that the reranker is
running on CUDA on this machine is false right now.**

**The cause is a missing CUDA toolkit, established by walking the chain rather than by guessing.**
Putting Ollama's private `cuda_v12` directory on `PATH` moved the error from `cublasLt64_12.dll`
to `cufft64_11.dll` â€” the next link. There is no CUDA toolkit under `Program Files`; the only
`cublasLt64_12.dll` on the disk belongs to Ollama, which ships a subset and no cuDNN. **Borrowing
another product's private CUDA runtime was tried once as a diagnostic and is not a fix** â€” it was
not left in place and nothing in the build reads it.

**Driver 610.74, RTX 4080 SUPER.** The card is fine. The userspace libraries ORT links are absent.

### This is `error_on_failure()` doing its job on its first real encounter, and the mutation proves it

The Session G failure is that CUDA reports *available*, fails to **create**, and ORT then registers
CPU and scores happily. **Removing `.error_on_failure()` from the CUDA arm reproduced that exactly,
here, today**: `Embedder::load_with_provider(..., ProviderChoice::Cuda)` **returned `Ok`** on a
machine with no CUDA libraries at all, and `provider()` reported `Cuda`.

**`Embedder::provider()` could not tell the difference, and that is the point.** It reports the
*request*. The test that caught it reads a **byte** instead:
`a_cuda_session_that_loaded_actually_holds_DEVICE_memory` measures free VRAM before and after a
warmed CUDA session and requires it to drop by at least the graph's own size. Under the mutation it
printed **`free memory moved by 0`**. A declaration-shaped assertion â€” `assert_eq!(provider(),
Cuda)` â€” is green on that build. Family #16 caught in advance rather than in hindsight.

**Its honest status on this machine: it SKIPS**, loudly, naming the driver error. It is
non-vacuous only under mutation. That is a real gap and it is recorded as one.

### What shipped

| | |
|---|---|
| `EmbedProvider::{Cpu, Cuda}` | on the loaded object, reported by `Embedder::plan()` |
| `ProviderChoice::{Auto, Cpu, Cuda}` | request vs. outcome are **different types**; `Cuda` refuses rather than falling back |
| `error_on_failure()` | **both arms.** CPU cannot fail; registering it explicitly is what makes CPU a decision instead of an omission |
| `Embedder::cuda_available(dir)` | probe by **construction**, on the **shipped graph** |
| `cue::dense::vram` | free device memory via `nvidia-smi`; `Probe::{Device, Fixed}` so the exhaustion path is drivable |
| `CacheIdentity.provider` | **new field in the cache namespace** |
| `--embedder-provider <cpu/cuda/auto>` | read in `main.rs`, and the resolved provider + width printed to stderr on every run |

### THREE PLACES THE OBVIOUS IMPLEMENTATION WAS WRONG, AND TWO ARE DEVIATIONS FROM THE BRIEF

**1. The provider is UNIFORM across an embedder's sessions. "Put the remainder on CPU" is refused.**
The brief asked for a mixed set â€” k CUDA sessions and `workers - k` CPU ones. `embed_batch` splits a
batch **contiguously across sessions**, so with a mixed set the vector a text receives depends on
which worker it landed on, which depends on the batch length *and on how much VRAM happened to be
free at load*. The module header claims worker count is "a throughput knob and provably not a
quality knob" and `embedding_is_bit_identical_across_calls_and_worker_counts` enforces it; a mixed
set breaks both **as a function of machine state**, so two `repro` spawns could split differently.
One `Embedder` also has exactly one `CacheIdentity`, so two providers behind one identity is the
stale-vector failure with the provider as the stale field. **Device memory therefore sets the WIDTH
of a GPU embedder and never the composition of a mixed one** â€” and the fallback is still per-session
where it matters: too full for eight yields fewer, too full for one yields CPU, and **nothing fails
the run**.

**2. The default is `cpu`, not `auto`, and this one needs the human.** The capability is built,
registered and reachable in the same commit â€” `auto` and `cuda` are parsed and passed in `main.rs`,
so this is not a declared control with no reader. What was **not** done is flipping the default,
for three reasons: **ADR-013 records that GPU is not adopted for the retrieval path**, pending its
own ADR, and the embedder *is* the retrieval path; **ADR-015 requires a per-provider baseline** and
there is none for this graph; and `auto` resolves against free VRAM *at that instant*, so as a
default two `repro` spawns on one machine could run on two different scorers because something else
on the card started or stopped in between. **On this machine `auto` and `cpu` are currently
indistinguishable, and that indistinguishability is exactly why the default must not be the one
nobody can test.** Flipping it is an ADR carrying a CUDA baseline. **Scope call for the human.**

**3. `CacheIdentity` gained `provider`, and it invalidates every cached vector.** ADR-015 says the
two providers are different scorers; without this field they share a key and a warm cache written on
one is served to a run on the other. Same cost `MAX_SEQ_LEN` imposed three sections up, for the same
reason. **The exemption was considered and refused** â€” hashing nothing for CPU would have preserved
the existing ~482 MB cache and made the namespace mean "provider, unless it is the one we used to
assume", which is how a stale artifact gets served under a new label.

### The VRAM budget: no hardcoded worker count and no hardcoded VRAM number

1. `Probe::free_bytes()` reads the card. `None` (no device) and `Some(0)` (full device) are
   **different answers** and the loader reports which.
2. A session's cost has a **floor computed from what this build already knows**: `model.onnx`'s size
   on disk plus the ALiBi matrix, `8 Â· N Â· N Â· 8` int64 at `MAX_SEQ_LEN` â€” the same quadratic term
   measured at 23Ã— two sections above. Floor, not estimate: the *measured* delta replaces it when
   larger.
3. **The headroom rule is one whole spare session**, not a constant. The card is shared and a
   reading is an instant, not a reservation.
4. The first session is **warmed at `MAX_SEQ_LEN`** before its cost is read. ORT's CUDA arena
   allocates on first run, so an unwarmed delta reads a fraction of the real number.
5. Every later decision **re-reads the device** rather than spending down a startup budget. A ledger
   runs beside it and the decision takes the **minimum**, which is what makes `Probe::Fixed` drive
   the same code path a real card takes.

### CPU baseline, cache OFF, on identical texts â€” `runs/session-e-embedder-gpu/provider-bench.txt`

**The CUDA column is empty and it prints as `-`, never as `1.00x`.** 32 texts per cell, 8 logical
workers derived from `available_parallelism().min(8)`.

| tokens/text | 1 worker | 8 workers | scaling |
|---|---|---|---|
| 102 | 30.28 ms/embedding | **5.43** | 5.58Ã— |
| 502 | 170.91 | **37.76** | 4.53Ã— |
| 1024 (`MAX_SEQ_LEN`) | 438.13 | **102.61** | 4.27Ã— |

**Each cell was run twice â€” once as `ProviderChoice::Cpu` and once as `Auto` â€” and the pair agrees**
(102 tokens / 8 workers: 5.43 and 6.00). That agreement is the fallback control: `Auto` on this
machine *is* CPU, and it says so rather than reporting a GPU it did not get. Between-run variance at
one worker is ~3â€“9%, which is wider than several of the differences a careless reading would call
results.

Host peak reached 2,292 MB at 8 workers Ã— 1024 tokens â€” **8 sessions Ã— the 64 MB ALiBi matrix plus
eight copies of the graph**, which is exactly the per-session cost the GPU budget is built to
respect. Own VRAM **0.0 MB on every row**, which is the control: nothing touched the card.

**The CPU reference is unchanged by registering `CPUExecutionProvider` explicitly** â€” worst abs diff
**1.043e-7** against a 1e-4 tolerance, min cosine **0.99999994**, matching the numbers recorded above
for the 1024 regeneration. So the shipped scorer did not move.

### Mutation runs â€” three fixes, three named failures

| Reverted | Failed |
|---|---|
| the `free < floor Ã— 2` gate in `auto_sessions` | `a_zero_vram_budget_falls_back_to_cpu_instead_of_failing_the_run` |
| `.error_on_failure()` on the CUDA arm | `a_cuda_session_that_loaded_actually_holds_DEVICE_memory` â€” *"free memory moved by 0"* |
| `provider` from `CacheIdentity::namespace` | `every_identity_field_participates_in_the_key` â€” *"fields 0 and 6 collide"* |

### WHAT COULD NOT BE CLOSED, listed so nothing reads as covered

- **Every ADR-015 reading on CUDA is UNMEASURED.** Determinism, worker invariance and
  batch-composition invariance all have tests (`tests/embedder_provider.rs`) and all **skip** here.
  **The CPU readings do not transfer and must not be cited for CUDA.**
- **`embedding-reference.json` has NOT been verified on CUDA.** It was not regenerated and must not
  be; it is HuggingFace/sentence-transformers output and that authority direction is intact.
- **No CUDA timing exists**, so the ~80-minute cold corpus pass is still the CPU number. Nothing in
  this change makes a cold pass faster on this machine.
- **The GPU success path has never executed.** The fallback path has, and is measured; the branch
  where sessions actually open on a device has only been reasoned about.
- **The reranker's CUDA path is equally dead here** and nothing in the suite says so, because
  `--rerank-provider` defaults to `cpu`. Found as a side effect; not fixed.

### To close it, in order

1. **Install the CUDA toolkit and cuDNN that this `ort` build links** (CUDA 12 runtime:
   `cublasLt64_12`, `cufft64_11`; cuDNN 9). A machine-level change, deliberately not made here.
2. Re-run `cuda_probe`, then `cargo test -p marlowe-memory --test embedder_provider`. The three
   skipping tests become the ADR-015 baseline.
3. Re-run `embed_provider_bench` for the CUDA column, and check the `workers N of 8` line â€” that is
   the budget speaking.
4. **Only then** argue the default. It is an ADR against ADR-013 and it needs the baseline from 2.

## THE PROJECT HAS NO CI, AND THAT IS A SECURITY FINDING RATHER THAN A GAP IN ONE ROW

**Found while auditing M2's acceptance list, 2026-08-17. `.github/` does not exist and there is no
CI configuration of any kind in the repository.** It surfaced as one unmet acceptance row â€”
*"budget tests from HP10 pass in CI"* â€” and it is much larger than that row.

**1. Session B's traversal suite is called a STANDING REQUIREMENT in both `ROADMAP.md` and this
file, and nothing re-runs it.** The wording is *"verified on both platforms, and that is a standing
requirement rather than a one-time closure"*, with the reason spelled out: the symlink class cannot
run on Windows and the Windows pinning never executes on Linux, so the halves do not overlap and a
single-platform green is a half-measured wall. **In fact it is a one-time manual act from
2026-08-08.** That is a security boundary â€” ADR-002's whole argument is that with no kernel backstop
a path check defeated by string manipulation is the entire protection â€” whose re-verification does
not exist.

**2. M1's two-platform row has the same shape**, and so does every *"tested explicitly"* row in every
milestone. With nothing re-running them, each means **"tested once, on the machine of whoever wrote
it"**.

**This is the fourteenth-instance family at project scale.** That instance was a `Â§13` hook entry
naming a file that a refactor had moved: a guard is a claim about a path, and a claim about a path
needs something checking the path is still there. The same question one level up â€” *what would
re-run this if it broke?* â€” answers "nothing" for every standing check in the project. The fix for
instance #14 was `protect-boundaries.py --self-check`, wired into a test **so the build fails**. There
is no build to fail.

**DO NOT BUILD CI AS A SIDE-EFFECT.** It is not in Session E's definition and it carries its own
decisions â€” which platforms, which triggers, what the ONNX and model-dependent tests do in a runner
that has no GPU and no `models/` directory (see the embedder failure below, which would red-light
every run). **Scope call for the human.**

**And the evidence that this is already biting: `cargo test --workspace` is RED at `HEAD` and has
been for at least two sessions.** See below.

## K6 IS MET: 3 min 37 s, ZERO CONFIG, IN A CLEAN CONTAINER â€” WITH THE MODEL ALREADY PULLED

**Measured 2026-08-17.** `git archive HEAD` into `rust:1-bookworm` â€” exactly what a fresh clone
gets, since `models/` and `data/` are gitignored.

| Leg | Time |
|---|---|
| `docker pull rust:1-bookworm` | **27 s** |
| `cargo build --release --jobs 4` (from cold registry) | **181 s** |
| `marlowe --ask "â€¦"` â†’ first useful output | **9.2 s** |
| **Total, model present** | **217 s = 3 min 37 s** âœ… under the 5-minute budget |

Output: `6 Ã— 7 = 42.  [completed Â· 9092 ms]`. **No flags, no config file, no environment
variables** â€” the binary auto-spawned its own daemon and answered. Binary 113 MB.

### THAT 9.2 s IS NOT MARLOWE'S COST, AND READING IT AS ONE IS THE WHOLE ERROR

**Decomposed afterwards on the Windows release exe, because the row above invites the wrong
reading.** K6 as the human defines it is *binary on disk, model pulled, launch cold â†’ first useful
output*, so what matters is which part of that the harness owns.

| | measured |
|---|---|
| **Marlowe's own cold start** â€” process launch â†’ accepting connections, fresh profile (journal, HMAC key, token, `profile.json` all created inside it) | **70 ms** |
| **Marlowe's share of an end-to-end ask** â€” wall clock minus the model's own reported time, across 7 runs | **68â€“198 ms** |
| **End-to-end, cold, model pulled and resident** | **1.2 â€“ 1.5 s typical** |

**Everything else is the model.** `qwen3.5:9b` is a reasoning model and its thinking block swings by
an order of magnitude between identical prompts: seven runs of *"what is 6 times 7?"* reported
958 ms, 1,065, 1,305, 1,356, 1,473, 1,701 and **11,071 ms** â€” the last being the one inside the 9.2 s
container figure. **The harness overhead was 68â€“198 ms in every one of them, including that one.**

**So against a 5-minute budget the harness costs a tenth of a second.** If K6 is ever at risk, it
will not be because of Marlowe's startup.

### A FALSE FINDING I ALMOST RECORDED HERE, FROM n = 1

One fresh-profile run took **11,269 ms** while a repeat on the *same* profile took 1,817 ms, so I had
written *"first run is ~7Ã— slower than subsequent runs, cause unidentified"* and was about to file
it. **Two more fresh-profile runs read 1,206 ms and 1,505 ms and killed it outright.** It was a slow
*inference* that happened to be sitting next to a fresh profile.

Nothing about the reasoning was wrong except the sample size, which is this project's own standing
rule â€” *a post-hoc result measured on one base is not a result until a second one reproduces it* â€”
landing on a wall-clock measurement rather than a ranking one.

### The model pull is NOT in that number, and it is what decides the honest verdict

`qwen3.5:9b` is **6.59 GB**. It was already on the host, so the 217 s assumes a user who already
has the default model. **A genuinely cold first run must add that download**, and at 100 Mbps 6.59 GB
is ~9 minutes â€” on its own, nearly twice the whole K6 budget. **This is arithmetic, not a
measurement: the pull was not timed**, because re-pulling would have meant deleting the human's
model.

**So the honest verdict is two-sided and the scope call is the human's:**
- **"Marlowe's own install, model assumed present" â†’ K6 PASSES at 3:37.**
- **"What a user actually experiences on a new machine" â†’ K6 FAILS, and it is not close.**

**Do not fix this by tuning.** The remedies are product decisions â€” a smaller first-run default,
useful output streaming while the pull runs, or K6 restated. Not the agent's call.

### Three K6 findings that are about the product, not the container

1. **The Ollama endpoint is hardcoded `127.0.0.1:11434` with no override** â€” no flag, no env var
   (`http.rs:55`). Any topology where the model server is not on the same host needs a code change.
   The container measurement needed a `socat` forward to stand in for "Ollama is on localhost",
   and **that forward is harness plumbing, not product config** â€” K6's zero-config claim is not
   weakened by it, but the hardcoding is a real limitation.
2. **`DEFAULT_MODEL` is `qwen3.5:9b`, and a zero-config run demands exactly it.** If it is absent or
   cannot load, the first run fails. It fails *honestly* â€” the first attempt here returned Ollama's
   own `cudaMalloc failed: out of memory` verbatim, which named the cause precisely.
3. **Nothing tells the user the VRAM floor.** The first attempt failed because a 9B model was
   already resident on the GPU from an earlier probe. A user with any other model loaded meets the
   same wall with no forewarning. This is a disclosure gap that first-run onboarding does not yet
   close.

### A methodological note, because it cost a wrong claim

I reported *"`qwen3.5:9b` is not on this host"* from a model list I had truncated with `head -10`.
It was present, below the cut. **A confident negative from a truncated instrument** â€” the same
family as everything else in this file, in the cheapest possible form.

## THE EMBEDDER FAILURE: TWO HYPOTHESES RAISED AND BOTH RETRACTED

**One test fails at HEAD: `embedding_is_bit_identical_across_calls_and_worker_counts`.** Not code
this session touched. `marlowe-memory`, ONNX Runtime, `"bad allocation"`.

| Hypothesis | Verdict |
|---|---|
| GPU contention with Ollama | **WRONG.** The embedder registers no CUDA provider â€” CUDA appears only in `rerank.rs`. `Embedder::session()` is CPU |
| Host commit-charge exhaustion | **WRONG.** 114 GB committed of a 127 GB limit reads alarming, but that is 31 GB RAM + a 96 GB page file, of which **5.3 GB is actually used**. 12.8 GB of headroom. A 512 MiB allocation does not fail against that |

**The second retraction is the instructive one.** "90% of commit used" was *adjacent* to the
question â€” *is memory the cause?* â€” and read as authoritative because it was a large percentage of
something. Decomposing it also showed my own measurement was unsound: `Get-Process` without
elevation cannot read private bytes for SYSTEM-owned processes, so its 40.8 GB total is an
undercount and the ~70 GB "unaccounted" was inflated by however much it missed.

**What is supported:** it is the **multi-session sweep**. The test calls `Embedder::load(&dir,
workers, None)` for `workers` in `[2, 8]`, and each worker constructs its own ONNX session with its
own arena. Under heavier load *both* embedder tests failed; with the machine quieter the
single-session test passes and only the 8-worker one fails. **Resource-dependent, unresolved, and
it needs its own investigation rather than a third guess.**

## M2 SESSION E â€” ITEMS 0, 1 AND 2 SHIPPED AND VERIFIED BY MUTATION. 3, 4, 5 NOT STARTED.

**Three commits: `3a6231c` (docs only), `376717c` (the sanitiser), `bba245d` (the extractor bounds).**
Item 0 was committed before the suite ran, because it is docs-only and was already true.

| Item | State |
|---|---|
| **0 Â· ROADMAP correction** | **DONE** â€” `3a6231c`. Table and acceptance list, both dated in place |
| **1 Â· display sanitiser** | **DONE** â€” `376717c`. 4 sites, 4 mutation runs, **the fourth found an unguarded site** |
| **2 Â· extractor process-killers** | **DONE** â€” `bba245d`. 7 bounds, 7 mutation runs, each failing its own named test |
| **3 Â· K6 in a clean container** | **DONE.** 3 min 37 s zero-config, model present. See the K6 section above |
| **4 Â· first-run onboarding** | **DONE** â€” `ef0afec`. Derived from the manifests; two defects found by running it |
| **5 Â· four M2 acceptance items** | **REDUCED TO ONE, AND IT IS BLOCKED** â€” see the correction below |
| **M1's accent row** | **NOT DONE.** The one item of Session E's original scope left untouched |

### Item 4's two defects are the strongest argument in this file for end-to-end runs

Both were invisible to the suite and to review, and both were found by running the binary:

1. **The disclosure was wired into `serve()` only.** `marlowe --ask` with no daemon auto-spawns on
   its own path â€” the first thing a new user runs, and exactly what K6 measures â€” so **the most
   common first run was silent.** Found by reading the stderr of the K6 container run.
2. **`is_first_run` guessed the journal's filename** (`"journal"`, `"journal.jsonl"`; it is
   `JOURNAL_DB` = `"journal.db"`), so it returned `true` forever and **the banner printed on every
   run.** Worse than never printing: a first-run screen that always appears is noise the user learns
   to scroll past â€” not disclosing, while looking like disclosure.

   **The unit test passed against it**, because the test created a `journal` directory of its own
   invention. Both sides were wrong in the same way, so the assertion was a tautology. Caught by
   running the binary three times and counting the banner.

**And the threshold was wrong in the first draft.** It split at `Consequential` and printed "DOES
SILENTLY"; the adjudicator asks unconditionally only for `Irreversible`, separately for ungranted
egress, and otherwise compares tiers. So the screen made a flat claim about `edit` on a rule that
exists nowhere in the code â€” **in the module whose whole argument is that hand-written disclosure
drifts from enforcement.** Caught by mutation, not by reading.

### THE SESSION BRIEF WAS WRONG ABOUT THE CODEBASE, AND THE HUMAN CORRECTED IT

**The brief said of item 5: *"Each is 'tested explicitly' in the acceptance list and none has a
test."* That was inferred from the acceptance list's wording rather than read from the code, and it
is wrong for three of the four.** Recorded here rather than silently shrinking the item, because the
next session inherits the sentence otherwise.

| Row | Truth |
|---|---|
| Compaction preserves governance across the boundary | **Tested.** `compaction.rs:70` and `:173`, through `Engine::run`, with a vacuity guard |
| Compaction invalidates cache | **Tested.** `compaction.rs:222` â€” epoch moves *and* the stale entry is gone |
| Startup fails on an unannotated manifest | **Met structurally, stronger than the row asks.** `ToolRegistration.manifest` is not an `Option` |
| HP10 budgets pass in CI | **Unmet â€” and blocked on there being no CI at all** |

**So item 5 is one row, and that row is blocked on the finding above.** The human's ruling: *"take
your reading over mine; my line was an inference from a document, yours is a reading of the code."*

### TWO PRE-EXISTING FAILURES, NEITHER MINE, BOTH WORTH KNOWING

**`cargo test --workspace --no-fail-fast` reads 876 passed / 4 failed.** None of the four is in code
this session touched.

**1. `determinism_guard` has TWO red tests at `HEAD`, and they are red without any of my changes.**
Verified by `git show HEAD:<file>` rather than by argument: every flagged line exists in the
committed tree, in files this session never opened.
`no_hash_map_in_crate_sources` flags `marlowe-extract/src/store.rs`, `marlowe-net/src/lib.rs` and
`marlowe-loop/src/engine.rs:292`; `the_only_real_clock_read_is_the_latency_fence` flags
`marlowe-exec` and `marlowe-net`. **They were introduced by the tools/parallelism session and the
layer-1 session, both of which reported green** â€” because both reported **per-crate** counts, and
these two guards live in `marlowe`'s tests and only run under `--workspace`. A per-crate suite cannot
see a workspace-level guard. **This is the CI finding with a date on it.**

**Also: `cargo test` fail-fasts at the first failing binary.** The first run stopped at
`determinism_guard` and never reached `marlowe-extract` or `marlowe-surface` â€” a suite that looks
complete and covers a third of the workspace. **`--no-fail-fast` is required for any run whose
purpose is a count.**

**2. The embedder cannot allocate, and Ollama is the likely reason.**
`the_embedder_reproduces_the_reference_within_a_measured_tolerance` and
`embedding_is_bit_identical_across_calls_and_worker_counts` fail with
`Failed to allocate memory for requested buffer of size 536870912` â€” 512 MiB exactly.

Not host memory: **7.58 GB of 31 GB free**, and they fail identically when run alone, so it is not
contention between test binaries. It is the **GPU**: `nvidia-smi` reads **11,535 MiB of 16,376 used,
4,511 free**, with Ollama's `llama-server` resident. ADR-029 put the rerank on CUDA; the model
provider and the memory subsystem are now two consumers of one 16 GB card.

**SUPPORTED, NOT CONFIRMED.** The decisive test is stopping Ollama and re-running, which would
unload the human's model, so it was not run unilaterally. **This bears directly on item 3:** a K6
run needs the model *and* the embedder resident at once, and if they do not co-fit then "install to
first useful output" has a hardware precondition nobody has stated.

### Item 0 found three things that change what the remaining work is

**The session table marked C2a "next" when C2aâ†’D had shipped, and C2d/C2e/C2f were not in it at all.**
Corrected in place with the commit for every row, plus three rows for sessions that ran and were
never scheduled (layer 1/ADR-039, tools+parallelism/ADR-040-042, the security audit). C3 verified by
grep as **not started**: `Transport::{Skill, Mcp}` exist from Session A, but nothing loads a
`SKILL.md`, there is no `find_skill`, and no MCP transport speaks to a server.

**And the acceptance list was audited, because correcting a session table alone is how M0b shipped
40% of its named mechanism and closed without saying so.** Results:

1. **The four benchmark rows â€” SWE-bench Verified, Terminal-Bench 2.0, Ï„-bench, BFCL â€” are UNMET AND
   UNSCHEDULED.** Neither name appears in any `.rs`, `.py`, `.toml`, `.json` or `.yaml` in the
   repository. No harness, no adapter, no run, no result. **Whether they block M2's closure or are
   deferred is a scope call and is deliberately not made** â€” flagged and left open.
2. **THERE IS NO CI.** No `.github/`, no CI configuration of any kind. So *"budget tests from HP10
   pass in CI"* is unmet for a reason that is not "no test" â€” `hp10_budgets.rs` exists and passes
   locally. **This generalises:** M1's *"Â§B13 suite run on native Windows Terminal AND a Linux
   emulator"* and Session B's *"both platforms is a standing requirement rather than a one-time
   closure"* both have nothing standing behind them. Every standing check in this project stands
   only as long as a human remembers to run it by hand.
3. **Two of the four "untested" acceptance items were already tested, properly.**
   `compaction.rs:70`/`:173` drive governance across the boundary through `Engine::run` with a
   summarizer that preserves nothing, asserting on the assembled view *and* on the view the driver
   was handed, with a vacuity guard. `compaction.rs:222` asserts the cache epoch moves *and* that the
   stale entry is gone. **The session brief said none of the four had a test; that was wrong for
   two of them, and building what already works is exactly what a stale table causes.**
   The third â€” *"startup fails on an unannotated tool manifest"* â€” is **met structurally and more
   strongly than the row asks**: `ToolRegistration.manifest` is not an `Option`.

**Side finding: `LoadError::MissingManifest` has no constructor anywhere in the workspace.** Its doc
comment says *"The system does not start"*, describing a runtime refusal that cannot execute because
the type enforces the property instead. Vestigial rather than broken â€” instance #16's shape in
miniature, a declared control with no reader. Left in place, named in the ROADMAP.

### Item 1 â€” the sanitiser is lifted, and one definition now serves both sides

`is_renderable` had one caller in the product (`FieldSpec::validate_value`, twenty lines above it)
and **no render site was it**. Moved to `marlowe_contract::text`, re-exported from `marlowe-loop` so
existing callers do not move. **`marlowe-contract`'s header claimed *"CONTRACTS.md section 4 as Rust
types â€” and nothing else"*; it was amended rather than quietly falsified**, and it says what would
justify cutting a leaf crate instead if a third thing wants to live there.

Applied at all three sites. `render` and `approve_at_the_terminal` were split into `render_to` and
`write_approval_prompt` against an `impl Write`, **so the property is assertable where it is
enforced** rather than through captured stdout.

**Marking, not dropping.** A refused character becomes `<U+001B>`, following
`ContractViolation::DisallowedCharacter`'s precedent of naming the codepoint. A stripped payload and
a clean string must not be indistinguishable to the human approving a `bash` command. The marker is
**forgeable and the module says so** â€” a page can print `<U+001B>` itself. That asymmetry is the safe
direction and must not be built on: the forgeable claim is *"something was stripped"*, not *"nothing
was"*.

**One test of mine was a proxy and failed against a working fix.** It counted occurrences of
`approve? [y/N]`, when the property is *no forged prompt **line***: the fix leaves the forged text
inert mid-line after a visible `<U+000A>`, so the substring count is legitimately 2. Rewritten to
count lines whose trimmed start is the prompt. The measurement was adjacent to the property and
stricter than it.

**The TUI test is labelled a characterisation test of a dependency, not a guard**, in its own header
and its own failure message, because **ratatui** is what filters control characters out of a
`Buffer` â€” the TUI does not sanitise. The file states what would change that (this test failing, or a
TUI render path that writes bytes without a `Buffer`) so the trade is recorded rather than assumed.

### Item 2 â€” the caps are at the chokepoint, not at the site

**`extract()` is the chokepoint and the caps live there** (the human overruled privatising
`Document`'s fields, correctly: a validating constructor for the whole type is its own change with
its own ADR, and `title` alone would have been arbitrary while `links`, `description` and `headings`
stayed unbounded). **Grep confirmed the precondition: every product construction of a `Document` is a
parser inside `marlowe-extract`, all returned through `extract`** â€” the only other struct literal,
`corpus.rs:529`, is inside `#[cfg(test)]`.

| Finding | Fix | Bound asserted |
|---|---|---|
| **G11** `<title>` uncapped in four parsers | `MAX_TITLE_CHARS` in `extract` | `tests/title_cap.rs`, on **RSS and Markdown** â€” never HTML, because an HTML test would have passed before the change |
| **G6** xlsx shared-string amplification | row cap + table count **and** byte caps | retained cell count, retained bytes |
| **G7** csv materialises every row before the cap | `parse_csv` retains `keep`, counts all | retained rows, columns, field bytes |
| **HTML ~770 MB peak** | the block buffer is bounded | â€” arithmetic in the comment; **not measured** |

**The HTML peak's arithmetic, since the fix rests on it:** a 64 MB windows-1252 input is held four
times â€” raw bytes (64 MB), decoded UTF-8 (~192 MB, since every high byte becomes 2â€“3), `blocks`
(~192 MB), `select_content`'s join (~192 MB) â€” and then `normalize` throws all but 8 MiB away. The
last two stages build what the last stage discards, so bounding them costs nothing that survives.
**What it does change is *which* 8 MiB survives** for an over-long document, and that is stated in
the code rather than hidden. `decoded.text` cannot be bounded without a streaming decoder, so the
peak floor stays at the input size and its expansion. **This is reasoning, not a measurement** â€” no
before/after peak-RSS number was taken.

**G6's positional subtlety, recorded because it is easy to get backwards:** an over-budget shared
string becomes an **empty entry**, never a dropped one. Cells reference the table **by index**, so
dropping would shift every later index and attribute one cell's text to another â€” quiet corruption
in place of a visible absence.

### THE MUTATION RUNS, AND THE ONE THAT FOUND A HOLE

**Eleven bounds, eleven reversions, each run alone and restored afterwards.** Every row below is a
command that was run, not an argument.

| Reverted | Failed |
|---|---|
| `agent.rs::render_to` | 2 render tests â€” **the approval test stayed green** |
| `agent.rs::write_approval_prompt` | **only** the approval test |
| `cli.rs::print_new` | 2 `print_new` tests â€” the approval test stayed green |
| `cli.rs::print_approval` | **NOTHING** |
| `extract()`'s title cap | all four `title_cap.rs` tests |
| `parse_csv` row retention | `parse_csv_retains_a_bounded_number_of_rows_and_still_counts_them_all` |
| `parse_csv` column cap | `parse_csv_bounds_the_width_of_a_single_row` |
| `parse_csv` field cap | `parse_csv_bounds_a_single_enormous_field` |
| `sheet_text` row cap | `a_single_row_cannot_amplify_a_shared_string_without_bound` |
| `shared_strings` byte cap | `the_shared_string_table_is_bounded_on_count_and_on_bytes` |
| `flush_block` bound | `the_block_buffer_is_bounded_before_normalize_ever_sees_it` |

**Row four is the whole reason the runs happen.** All three `cli.rs` tests covered `print_new`;
`print_approval` was sanitised and **completely unguarded**, and the suite was green either way. It
could not have been found by reading â€” the `sanitize_line` calls are visibly present in the function.
Only reverting one site at a time says whether anything notices.
`the_classic_approval_prompt_never_writes_a_control_sequence` closes it, and the re-run fails exactly
that one test and no other.

`scratchpad/mutate.py` (by function name) and `scratchpad/mutate2.py` (by exact string, refusing to
run if the pattern does not match exactly once â€” a mutation that silently fails to apply reports a
clean bill of health).

### Next session, in order

1. **THE K6 SCOPE CALL, and it is the human's.** Does K6 mean *"Marlowe's own install, model assumed
   present"* (**passes, 3:37**) or *"what a user meets on a new machine"* (**fails; the 6.59 GB pull
   is ~9 minutes at 100 Mbps on its own**)? Everything else about K6 is measured; only the
   definition is open. **Do not resolve it by tuning.**
2. **Disclose the pull and the VRAM floor.** Whichever way 1 goes, *"this will take N minutes and
   here is why"* belongs in the first-run screen, which now exists and has nowhere for it yet. The
   VRAM floor belongs there too â€” the first K6 attempt failed because another 9B was resident, with
   no forewarning anywhere in the product.
3. **The `--reranking` flag is the difference between a working first run and a good one.** A
   zero-config run gets `memory retrieval WRITE-ONLY`, announced honestly at startup and repeated in
   the disclosure. Nothing tells the user what they are missing or how to turn it on.
4. **M1's accent row** â€” the last item of Session E's original scope, untouched. Carries a 3.26:1
   contrast number that clears AA for large text and UI components but not AA body text.
5. **Item 5** is one row (HP10 budgets in CI) and is blocked on the CI scope call.
6. **`embedding_is_bit_identical_across_calls_and_worker_counts`** â€” the only failing test at HEAD.
   Two hypotheses raised and both retracted; see above. Needs its own investigation.

### Session E closed here. What it did NOT do, listed so nothing reads as covered

- **M1's accent legibility row.** Untouched. Still carries 3.26:1, which clears AA for large text and
  UI components and not AA body text. It was in Session E's original scope and is the only scope item
  that got no work at all.
- **Item 5 / HP10 budgets in CI.** Blocked on the CI scope call, which is deliberately not made.
- **The four benchmark rows** (SWE-bench, Terminal-Bench 2.0, Ï„-bench, BFCL). Unmet and unscheduled;
  flagged in `ROADMAP.md`, scope call open.
- **`repro` and `conformance` were not re-run.** The reasoning from the layer-1 session still holds â€”
  the eval adapter references neither `Engine` nor `marlowe_loop` â€” but this session changed
  `marlowe-extract`, `marlowe-net` and `marlowe-contract`, and **`marlowe-contract` is on the
  adapter's path**. The sanitiser only added a module and re-exported a predicate, so nothing the
  adapter calls changed behaviour; that is an argument, not a measurement. **If anything downstream
  depends on `repro`, run it before trusting this.**
- **K3 has not been re-measured since M0b.** Unrelated to this session's changes, noted because the
  audit's open `profile.key` finding is the live path by which it could go non-zero.

### Instruments left behind, because the last session's were lost

- `runs/session-e/suite-final.txt` â€” one workspace run. **See the correction below before quoting
  its count.** Grep it rather than re-running.
- `scratchpad/mutate.py` (by function name) and `scratchpad/mutate2.py` (by exact string, **refusing
  to run when the pattern does not match exactly once**). The second guard exists because a mutation
  that silently fails to apply reports a clean bill of health â€” it happened to me once in this
  session before the check was added.

### THE SUITE COUNT IS BIMODAL, AND THE DELTA IS THE FINDING â€” added after the session closed

**"888 passed, 1 failed" is one sample of a two-valued result.** The committed log genuinely reads
888/1 with only `embedding_is_bit_identical_across_calls_and_worker_counts` failing. A run on the
same commit an hour later read **887/2** â€” that test **plus**
`the_embedder_reproduces_the_reference_within_a_measured_tolerance`, both failing `bad allocation`
at `/encoder/Expand`.

So the reference check is **intermittent**, and the two halves of the explanation belong to
different people's wrong answers:

- **The bug is the allocation request: `4294967296` bytes â€” 2^32 exactly**, from an `Expand` node,
  in a ~130 MB model (`jina-embeddings-v2-small-en`). Nothing in that graph legitimately expands to
  4 GiB. That is a **wrapped or overflowed dimension**, and the round number is the evidence: a
  machine under memory pressure fails at whatever size it happens to fail at, not on a power of two.
- **The intermittency is whether the allocator can satisfy it.** With 4 GiB of contiguous memory
  free the absurd request *succeeds* and the test passes.

Both hypotheses argued during the session were half right and neither was whole. "Not a resource
problem" was right about the cause and could not explain the variance; "GPU contention" and "commit
exhaustion" were right that machine state matters and wrong about why. Recorded because the shape â€”
a correct-looking retraction that removes the true half along with the false one â€” is worth more
than the fix.

**Why this outranks a flaky test.** A 4 GiB allocation that *sometimes succeeds* means that on a
machine with headroom the embedder runs to completion while doing something absurd, and nothing
reports it. `the_embedder_reproduces_the_reference_within_a_measured_tolerance` is precisely the
check that would catch whether the numbers off that path are still correct â€” and it is the one that
goes green when the machine happens to be idle. **A scored-path reference check that passes only
under low memory pressure is not a verified component**, and while it stands, retrieval quality
claims cannot be reproduced on this machine.

**The lead for whoever picks it up:** `/encoder/Expand` computes its output shape from its inputs,
so the wrapped value arrives on the **input** side â€” sequence length, batch, or attention mask.
That is ADR-015's territory, where shape invariance is re-measured **per graph** and never
inherited. Do not start from the allocator.

### Two things noticed in passing and deliberately not fixed

- **`extract()` contains an unreachable duplicate of its own guard** â€” an `#[allow(unreachable_code)]`
  block after the `return`, left from the G10 fix. Harmless, confusing, and not this session's scope.
- **`print_approval` reads `view.approval` while the live TUI path uses `view.pending_approval`.**
  If the classic CLI never renders a *live* approval, that is a Â§B14 capability gap. **Not verified,
  not chased** â€” recorded so it is not rediscovered.

## SECURITY SESSION â€” 20+ AUDIT FINDINGS FIXED, AND LAYER 3 TURNS OUT TO BE UNREACHABLE

**Seven commits, every crate green. Each fix verified by DELETING it and watching a named test
fail** â€” A1's mutation hangs the suite outright, which is the point.

### The two findings that outrank everything else fixed

**1. LAYER 3'S LATCH CANNOT FIRE IN THE SHIPPED DAEMON.** Four links, each checked by grep rather
than by argument: injected memory is untrusted only if some belief is `UntrustedContent`; a belief is
that only from `ingest`, or from `remember_claim` with an already-bottomed floor, which is circular;
and **`ingest` has exactly one caller in the workspace â€” `adapter.rs:304`, the `--eval-adapter`.**
`Channel::` appears nowhere in `crates/marlowe-daemon/src`.

Not broken â€” **unreachable**. ADR-041 removed the only reachable trigger (tool results) and the
replacement trigger has no production ingest path behind it. Every test that establishes taint by
hand-pushing an `InjectedMemory` block measures a state the product cannot enter. CLAUDE.md's
*"layer 3 is still reachable and non-vacuous"* was true of the test surface and **false of the
product**; corrected in place. **Fix the compaction stamp (E5) and the trim marker (F1) BEFORE
wiring `ingest`**, or three defects go live in one path at one moment.

**2. `is_renderable` HAS ONE CALLER IN THE ENTIRE PRODUCT**, and no render site is it. So the Â§B9
approval prompt renders the model's composed `bash` command unfiltered: `[2K\r` overwrites the
line the human is deciding on. The TUI is safe only *incidentally*, because ratatui filters control
characters â€” nothing here tests that or names the dependency. **Highest-severity open item.**

### Fixed (see `docs/design/SECURITY-AUDIT.md` for the ledger and the test that pins each row)

| | |
|---|---|
| **Daemon socket** | a per-profile token, checked **before dispatch**. Loopback is per-machine, not per-user. Verified by disabling the comparison: a stranger's `{"op":"shutdown"}` was dispatched and stopped the daemon |
| **`bash`** | A1 timeout + A2 output cap. `BASH_TIMEOUT_MS` was declared and **nothing read it** â€” `Command::output()` blocks forever, so any approved `ping -t` hung the batch, the turn and the daemon |
| **`web`** | A3 the raw `Location` header at `AgentObserved` â€” the one genuine layer-1 bypass; A4 parser error strings and raw `Content-Type` |
| **`read`** | A7 `slice_lines` overflow (aborts the whole batch through `thread::scope`), A8 no read ceiling |
| **Quarantine** | C1/E1 render bypass, C2 character class, C3/E2 field broadcast, C4/C5 budget zeros, E3 the cache **write** primitive, E4 the child streaming to the terminal, E7 label desync, E8 unbounded retry, E10 stolen steering, E14 cache growth |
| **The hook** | `--self-check` with a missing argument returned **0**; `/persona/` was exempt on a basis that had expired |

### Three methodological results, each worth more than a single fix

1. **The audit's own A7 exploit value does not reproduce.** It names
   `range = "1-18446744073709551615"`; with `a = 1` the subtraction saturates and the `+ 1` fits. It
   needs `a = 0`. **Reverting the fix left the single-value test GREEN.** A regression test copied
   from the report would have passed against unfixed code and A7 would have been marked closed.
2. **My first C3 tests did not discriminate.** They asserted on `parse_fields` and `structured`
   directly; restoring the broadcast in `engine.rs` left every one of them passing â€” the property
   asserted where the helper is *defined* rather than where it is *used*. **Family #16, committed
   while fixing family #16.** And the engine-level replacement's first draft failed against a
   *working* filter, because the harness gave the child and the parent the same words to say.
3. **A3 was not fixed by its own fix.** Round 2 found the payload had moved from the path to the
   **host**, which nothing validated â€” `Target::parse` checks only for whitespace and `@`. And `+`,
   the URL encoding of a space, was in my permitted set; 88 characters of readable instruction
   passed. **My test used literal spaces**, so the whole class of separator-encoded prose went
   untested.

### Round 2 of the audit â€” 6 read-only agents, findings NOT yet fixed

**Process-killers, and these abort rather than panic, so `catch_unwind` cannot hold them:** xlsx
shared-string amplification (~1.6Ã—10â¹:1 from a 250 KB file), csv row materialisation before the cap,
HTML peak ~770 MB/document on a 64 MB windows-1252 input, and `<title>` **uncapped in four parsers**
â€” G11 was fixed at the site rather than at the type, so every non-HTML path still has it.

**Also open:** `--profile-root` inside `--workspace` is unchecked, so the model can `read`
`profile.key` (plaintext HMAC, `Inert`, no approval) and forge the journal; the journal chain
detects interior deletion but **not suffix truncation**; `Daemon::open` reimplements the
`open_or_init` pattern that `profile.rs` has an executable test forbidding.

## THE PATH FORWARD IS ADR-043, AND READING ADR-036/037 CHANGED IT

The question was: *can Marlowe be injection-proof AND go URL to URL freely?* Today it goes URL to
URL only because **layer 3 is silently inert** â€” the condensed return crosses at `AgentInferred`, so
a fetch never lowers the floor. That is a laundering path, and its second leg is worse: `remember`
stamps page-derived content as a **permanent `AgentInferred` belief** in the signed journal.

**ADR-043: the model passes an index, the harness passes the URL bytes.** A link extracted from
markup is a constant the attacker fixed *before* the run had seen anything; a composed URL is a
variable that can encode anything it holds. Exfiltration lives entirely in the second. So a research
run can hold `UntrustedContent` for its whole life and still navigate, while `bash` and `edit` stay
hard-blocked.

**Two things reading the docs corrected:**

- **This is ADR-036 Â§5's rule, not a new idea.** *"Wherever a value chosen by untrusted content
  determines an outcome, the question is who asserted it."* Â§5 lists four unexamined domains;
  navigation was not among them, and the rule arrived there already correct. Â§5 amended.
- **ADR-037 Â§6 is wrong about who stays clean.** *"The orchestrator â€¦ must be a separate run that
  never touched a page"* is unachievable once the return crosses at `UntrustedContent`. Replaced
  with **three phases**: plan (clean), read/navigate (tainted, selection-only), synthesise/write
  (tainted, writing to a target the *plan* asserted). **This makes ADR-037 Â§3's collaborative plan a
  security precondition rather than a UX feature** â€” it is what supplies a clean destination for a
  tainted synthesis phase.

**And the link table must bypass the quarantined reader.** Routing it through the compromised
component would make quarantine decorative for the one decision that matters. The harness builds the
table from extracted markup and hands it to the parent directly.

### NEXT, in order

1. **The display sanitiser.** Lift `is_renderable` into `marlowe-contract`; apply at
   `agent.rs::render`, `approve_at_the_terminal`, `surface/src/cli.rs`. Independent of everything
   else, highest severity.
2. **The extractor's process-killers** + the `<title>` cap applied at the **type**, so every format
   inherits it including ones added later.
3. **The link table and `web(ref, link)`** â€” buildable inside M2's tool scope.
4. **The condensed return at `UntrustedContent`**, once 3 exists so nothing regresses. Layer 3 goes
   live for the first time. Folds in A5, A6 and H6 â€” all four are one question â€” and needs a single
   `DECISIONS.md` entry.
5. **M3 inherits ADR-043 Â§5's phase table**, not ADR-037 Â§6's two-role model.

**Not done and it should be:** no real end-to-end run this session. CLAUDE.md budgets one per
milestone as verification, and it is the practice that caught the `done` defect, scroll and
double-dimming. The daemon accept loop, the client, `bash`, `read`, `web` and the quarantine path all
changed and none was exercised through an actual conversation.

## TOOLS/PARALLELISM SESSION â€” EXTRACTION EXISTS, FETCHES RUN CONCURRENTLY, READS ARE BATCHED

**Three ADRs: ADR-040 (`marlowe-extract` + fetch path), ADR-041 (batched quarantined reads).**
Written in a session scoped to the tools; the loop change in ADR-041 was explicitly authorised.

| Crate | Tests |
|---|---|
| `marlowe-loop` | **89** |
| `marlowe-extract` (NEW) | **57** |
| `marlowe-daemon` | **53** |
| `marlowe-net` (rewritten) | **14** |
| `marlowe-exec` | **12** |

### What changed

1. **`marlowe-extract`** â€” the module ADR-031's header promised and nobody wrote. `web` was doing
   `from_utf8_lossy` on raw responses. HTML (hand-rolled, no DOM), PDF, docx/xlsx/pptx/epub, XML,
   text/MD/JSON/CSV, charset via `encoding_rs`. **498 MB/s, 88.2% reduction.**
2. **`marlowe-net` rebuilt** â€” shared TLS config (the session cache had nowhere to live before, so
   resumption was structurally impossible), keep-alive pool, gzip/brotli, DNS cache, `Send + Sync`.
3. **Batched tool calls are genuinely parallel** â€” grouped by declared `ConsequenceLevel`, so
   `Inert` runs concurrently and mutating calls stay alone and in position. Measured on the real
   `Engine`: **2008 ms â†’ 252 ms, max overlap 1 â†’ 8**.
4. **One quarantined reader per group** (ADR-041) â€” N pages cost 1 child, 1 model call, 1 subagent.
   Containment unchanged; only the cost was ever per-page.

### Measured, on a 7800X3D (8 cores / 16 threads)

Live corpus, 24 documents / 7 hosts, best-of-3: **1074 ms â†’ 294 ms**, plateauing **~3.6Ã— from 12
workers up**. An earlier single unrepeated reading said 6.11Ã— â€” **that was noise**; between-run
variance exceeds between-level differences past the plateau. Network 946 ms vs extract 396 ms
summed, 4.5Ã— overlap. Peak working set **74.3 MB**. 23 read, 0 failures, 0 warnings.

**The constraint is hosts, not threads.** 24 docs over 7 hosts means workers past ~12 just queue at
the same servers. A **per-host concurrency cap** is the change the data argues for â€” not a higher
global width. NOT DONE.

### Phase 4 â€” the document store (ADR-042), SHIPPED

ARCHITECTURE Â§2.2's content store existed as a paragraph for two milestones and had no code.
Built now: `marlowe_extract::store::DocumentStore`, content-addressed, `Send + Sync`, populated by
every `web` fetch.

**The observation it rests on: a result carrying zero attacker-authored bytes needs no quarantine
at all.** A `DocumentRef` is a hash plus counts â€” `chars`, `links`, `headings`, `has_title` (that
one exists, never what it says), and warning *kinds* as fixed harness constants. A page can
influence those numbers; it cannot author them, and **a number cannot carry an instruction**.

**`web` now returns the ref INSTEAD of the page**, at `AgentObserved`. Content returns through one
door only: `read(ref=â€¦)` at `UntrustedContent`, condensed by ADR-041's quarantined reader.

`read` gained an optional `ref` **Target** beside an optional `path`. ADR-034's rule is preserved,
not broken: it says *a parameter the executor cannot run without is required*, and `read` now has
two ways to name its subject. A refused `path` and a call naming neither get **different** messages
â€” telling a model whose traversal was just blocked that it "gave neither" points it at the wrong
correction (caught by `an_escape_never_reaches_an_executor_at_all`).

**Fetching 30 pages now costs 0 model calls.** Reading costs 1 per group, only for documents
actually opened.

**ADR-037 was read and is NOT being built**: it is marked *"PROPOSED â€” design only. Do not build.
M3 owns this."*

### Adversarial suite â€” `marlowe-loop/tests/injection_attempts.rs`, 10 tests, all contained

Direct instruction in body; **a fully compromised reader that relays the payload verbatim**;
ANSI/C0 escapes from a page and from the reader; field-header forgery; a page impersonating the
harness's own quarantine banner; instructions in `<script>` and in comments; a 400 KB repeated
payload. Each pairs the property with a **control asserting the payload did reach the child**, so a
pass cannot be a fetch that never happened. No hostile page moved the parent's trust floor and none
produced a tool call.

### Open
- **No OCR.** Image-only PDFs are detected and reported (`Warning::NoTextLayer`), never silently
  returned as empty. This is the real gap in "any document must be readable".
- Per-host fetch cap (above).

## BEST HELD-OUT R@3 = 0.8908 (+0.0393, p = 0.0225). THE FIT-SELECTED ARM CAME LAST.

**Two held-out reads spent. `runs/session-m0c-m/{cascade,l4}-heldout-read.json`.** Gates on both:
the shipped key reproduced published held-out R@1 **0.6725**, R@1_current **0.5852**, R@5 **0.8865**
and R@3 **0.8515** exactly, and the depth-10 cue slate equalled the set the binary actually reranked
on **229/229**.

| held-out | baseline | **all-6 RRF** | cascade pair | L-4-ft alone |
|---|---|---|---|---|
| **R@3** | 0.8515 | **0.8908** | 0.8865 | 0.8690 |
| McNemar | â€” | **11 g / 2 l, p = 0.0225** | 10 g / 2 l, p = 0.0386 | 7 g / 3 l, p = 0.3438 |
| R@5 | 0.8865 | **0.9170** | 0.9170 | 0.9127 |
| R@1 | 0.6725 | 0.6769 | **0.6987** | 0.6594 |
| cond@3 | â€” | **0.9107** | 0.9062 | 0.8884 |
| input recall | 0.9039 | **0.9782** | 0.9782 | 0.9782 |

**Configuration:** slate 30 on the pre-rerank cue key â†’ shipped L-2-ft narrows to 10 â†’ **RRF (k=60)
over all six Session-J-recipe fine-tunes** â†’ admit top 3. All six are Tier A and digest-pinned.

**Since `ADMIT_TOP_K = 3` now ships, R@3 IS the product metric**, so the six-way fusion is the right
configuration despite the cascade pair's better R@1.

### THE FIT ORDERING INVERTED EXACTLY WHERE IT WAS SELECTED

| | fit | held-out |
|---|---|---|
| L-4-ft-w1 alone | **0.9432** (1st) | **0.8690** (last) |
| all-6 RRF | 0.9345 (2nd) | **0.8908** (1st) |
| cascade pair | 0.9301 (3rd) | 0.8865 (2nd) |

L-4-ft was **picked by looking at fit**; the pre-registration said so before the read and predicted
0.880â€“0.910 with falsification at â‰¤0.8865. **It read 0.8690 â€” OUTSIDE the band, FALSIFIED**, dropped
0.074 fitâ†’held-out, and pushed R@1 *below* the untouched baseline (0.6594 vs 0.6725).

**The all-6 fusion was never chosen on a number.** Its rule â€” *"fuse every graph trained the same
way, no subset"* â€” was fixed in `cascade_squeeze.py`'s docstring before the model loaded, precisely
so fit could not select it. It ranked 2nd on fit and 1st on held-out. **Second demonstration in one
session**: z-sum beat RRF on fit (R@1 0.7991 vs 0.7860) and read +0.0000 held-out while RRF held.

### TWO CLAIMS THIS KILLS, ONE OF THEM MINE FROM AN HOUR EARLIER

1. **The non-monotone capacity curve is a FIT ARTIFACT.** L-4 (19M) beating L-2 (16M) and L-12 (33M)
   at fixed fine-tuning â€” cond@3 0.9600 vs 0.9422 vs 0.9422 â€” does not survive. The honest reading
   reverts to **capacity is flat at fixed fine-tuning**, now measured across 15Mâ†’33M with four
   same-recipe graphs rather than inferred from two.
2. **"95% R@3 is in range" was a FIT statement and I should have labelled it.** On fit the 6-graph
   union oracle is cond@3 0.9778 â†’ R@3 0.9607, above 0.95. Held-out needs cond@3 = 0.95/0.9782 =
   **0.9711** against a measured **0.9107**. **Not close.**

**The instrument validated itself**: `L-2-ft-w1` reproduces `L-2-ft-session-j` to four decimals on
every metric and to the same smoke margin (3.993); `L-6-ft-w1` matches `L-6-ft-session-j` (4.992).
W1's recipe *is* Session J's recipe, which is what licenses L-4 and L-12 as same-recipe comparisons.

---

## SHIPPED THIS SESSION â€” the admission rule. The cascade did NOT ship, and the reason is measured.

**`crates/marlowe-memory` builds; `cargo test -p marlowe-memory` = 181 passed, 0 failed.** No git
write (a parallel session shares this checkout). `eval/` untouched.

### 1. `ADMIT_TOP_K = 3` â€” LIVE. `retrieve.rs:311`, read at `retrieve.rs:864`.

`vec![order[0]]` â†’ `order.iter().take(ADMIT_TOP_K)`. The product injects **three** memories, not one.
Held-out on the shipped ranking the gold turn is at rank 1 for **0.6725** and inside the top 3 for
**0.8515**, so the right memory is present **+0.1790** more often. Directed change.

**Three debts this creates, recorded in the code rather than discovered later:**

- **`docs/design/PRECISION-COVERAGE.md` is a TOP-1 artifact and no longer describes the product.**
  `publish_precision_coverage.py` scores a query correct on `c["gold"][i1]` â€” rank 1 alone. The
  artifact and the binary now disagree until that curve is republished at k = 3. The comment that
  warned about this was **amended, not deleted**.
- **Â§5.7's token budget now BINDS.** At k = 1 it was an upper bound that never bit; `budget_exhausted`
  is reachable in ordinary operation for the first time.
- **Per-memory precision necessarily falls** â€” at most one of three can be gold, so â‰¥2 of every 3
  injected memories are non-gold by construction. K1's conformal bound covers a single-memory
  decision and says nothing about a 3-slate. Stale-fact harm is unmeasured;
  `HARM-WEIGHTED-PRECISION.md` is the instrument and has not been re-run.

### 2. THE CASCADE IS BLOCKED ON LATENCY, AND THE NUMBER IS THE INVERSE OF THIS PROJECT'S OWN ERROR

```
SHIPPED  L-2 @10           p50   182.0 ms   p95   191.1 ms
CASCADE  L-2@30 + L-6@10   p50  1134.1 ms   p95  1278.1 ms      Â§5.7 budget: 300 ms
```

**4.3x over budget on the shipped pins** (1 intra-thread, batch 1, CPU, ADR-003's 1-vCPU target).
Every figure that made the cascade look affordable â€” 38.7 ms p50 â€” is a **CUDA** number from
`frontier.json`. `CLAUDE.md` records *"every rejection figure in this project was a 1-thread CPU
number for a GPU target"*; this is the same error **inverted**, and it was caught by measuring the
shipped path before writing the executor rather than after.

### 3. `RerankPlan` EXISTS AND NOTHING READS IT. Marked, not hidden.

`RerankPlan::{Shipped, Cascade}`, `CASCADE_SLATE = 30`, `CASCADE_NARROW = 10` are **scaffolding with
no call site**. `retrieve` still draws `RERANK_BUDGET` unconditionally and still loads one graph.
This is deliberately flagged in the doc comment as the shape of instance #16 â€” `web`'s
`inline_threshold_bytes: 0`, declared, never read, with a green test asserting the declaration.
**Do not write a test asserting these constants' values.**

`RerankPlan::select` takes `cuda_constructed: bool` because the honest probe is a **construction**,
not an availability list: `ort`'s `error_on_failure()` makes a registration failure a hard error
instead of a silent CPU fallback. It answers *"did a CUDA session construct"*, **not** *"did every
node run on the GPU"* â€” Session L measured 13.6% of nodes on CPU under a registered CUDA session,
and `ort` 2.0.0-rc.10 exposes no node placement.

**Four things block the wiring, all real, none of them routing around a guard:**
1. `rerank.rs` pins a single `MODEL_SHA256`; a second graph fails the digest check by construction.
2. `Rerank::CrossEncoder` holds one `&mut CrossEncoder`.
3. `MAX_BATCH` is 10, and ADR-015's batch invariance was measured at sizes 1..10 and is **never
   inherited** â€” depth 30 must run sequentially or be re-measured.
4. `ms-marco-MiniLM-L-6-v2-ft-session-j` has no `cross-encoder-reference` fixture; that check is
   per-graph.

**So the honest status is: the admission change ships, the ranking change does not.** The
significant held-out result (R@3 +0.0350, p = 0.0386) is realised only by the admission change; the
cascade's R@1 +0.0262 was never significant (p = 0.286) and is now also not shipped.

---

## M0c SESSION M2 â€” THE FIRST MECHANISM IN THIS PROJECT TO SURVIVE A HELD-OUT READ.

**HELD-OUT R@3 0.8515 â†’ 0.8865, +0.0350, McNemar 10 gained / 2 lost, p = 0.0386.**
**HELD-OUT R@1 0.6725 â†’ 0.6987 (+0.0262). R@1_current 0.5852 â†’ 0.6114. R@5 0.8865 â†’ 0.9170.**
**Input recall 0.9039 â†’ 0.9782.** `runs/session-m0c-m/cascade-heldout-read.json`. Nothing shipped.

Four gates passed before the read was believed: the shipped key reproduced published held-out R@1
**0.6725**, R@1_current **0.5852** and R@5 **0.8865** exactly, and the depth-10 cue slate equalled
the candidate set the binary actually reranked on **229/229** queries.

### The prediction was registered first and all four bands landed

`PREREGISTRATION-CASCADE-HELDOUT.json`, written before the read existed:

| | predicted | got | |
|---|---|---|---|
| R@3 | 0.870â€“0.895 | **0.8865** | INSIDE |
| R@1 | 0.690â€“0.720 | **0.6987** | INSIDE |
| input recall | 0.965â€“0.980 | **0.9782** | INSIDE |
| cond@3 | 0.90â€“0.95 | **0.9062** | INSIDE |

**AND THE COLLAPSE HAPPENED TO THE ARM THAT WAS NOT PICKED, WHICH IS WHY THE SPLIT MATTERED.**
z-sum was the better arm on fit (R@1 0.7991 vs RRF's 0.7860) and read **+0.0000 on held-out**, 10
gained / 10 lost. RRF was registered PRIMARY on principled grounds â€” parameter-free, scale-free, no
normalisation assumption â€” **not because it won on fit**, and it held at +0.0262. Declaring a primary
in advance on an argument rather than on a fit number is the mechanism that saved this result.

### The configuration â€” two constants and a graph that already ships

> **slate depth 30 on the pre-rerank cue key â†’ L-2-ft narrows to 10 â†’ RRF(L-2-ft, L-6-ft) â†’ top 3**

Both graphs are Session J's, both Tier A, both already digest-pinned: a re-pin, not a new component.
RRF k = 60 (Cormack's published default), fixed before any number existed. The one disclosed knob â€”
narrow width 10, chosen to match the shipped slate width â€” was **not swept before the read**.

| | fit | held-out |
|---|---|---|
| R@1 | 0.7555 â†’ 0.7860 | **0.6725 â†’ 0.6987** |
| R@3 | 0.8996 â†’ 0.9301 | **0.8515 â†’ 0.8865** |
| input recall | 0.9214 â†’ 0.9825 | **0.9039 â†’ 0.9782** |

**The fitâ†’held-out collapse ratio is ~1.2x on R@3**, against 4x, 8x, 15x and a sign flip for the four
predecessors. It did not collapse because it is not a fitted threshold and not a trained parameter.

---

### The fit work behind it

### The configuration, and it is two constants plus a graph that already ships

> **slate depth 30 on the pre-rerank cue key â†’ L-2-ft narrows to 10 â†’ fuse L-2-ft with L-6-ft â†’ top 3**

| fit | shipped | cascade | delta |
|---|---|---|---|
| R@1 | 0.7555 | **0.7991** (z-sum) / 0.7860 (RRF) | **+0.0436 / +0.0305** |
| R@2 | 0.8690 | **0.8952** | +0.0262 |
| R@3 | 0.8996 | **0.9301** | **+0.0305** |
| input recall | 0.9214 | **0.9825** | +0.0611 |
| cond@3 | 0.9763 | 0.9467 | âˆ’0.0296 |

Both graphs are Session J's, both Tier A, both already digest-pinned: a re-pin, not a new component.

### WHY TWENTY-SEVEN MECHANISMS FOUND NOTHING â€” they were all aimed at the wrong stage

**The cross-encoder is excellent at NARROWING and only mediocre at PICKING.** Its top-10-of-30
retains gold at **0.9956**. Every prior mechanism tried to improve the final pick â€” where the
measured ceiling on the whole post-hoc class is **+5 cases** â€” while the stage with real headroom
was the slate handed to it. `retrieve.rs` drew 10 and the reranker was asked to find gold that was
absent 7.9% of the time.

**Read R@k by depth and the trade is explicit** (`tools/rk_by_depth.py`, fit):

| depth | 10 | 20 | 30 | 40 | 50 |
|---|---|---|---|---|---|
| input recall | 0.9214 | 0.9738 | 0.9825 | 0.9825 | 0.9825 |
| cond@3 | 0.9763 | 0.9507 | 0.9422 | 0.9333 | 0.9289 |
| **R@3** | 0.8996 | 0.9258 | 0.9258 | 0.9170 | 0.9127 |

Depth alone peaks at 0.9258 and declines. **Input recall saturates at 0.9825 â€” the pruning ceiling â€”
and no depth reaches past it**; at depth 50, 77 of 229 pools have run out of survivors entirely. The
cascade beats plain depth because narrowing costs almost nothing (0.9956) while widening costs
`cond@3` monotonically.

### CONDITIONAL STAGE RETENTION â€” each stage judged only where gold reached it (fit, depth 20)

| stage | in â†’ out | retention |
|---|---|---|
| ingest + Â§4.3 + scope | 236 â†’ 229 | 0.9703 |
| session pruning | 229 â†’ 225 | **0.9825** |
| slate draw (top-20) | 225 â†’ 223 | **0.9911** |
| cross-encoder top-3 | 223 â†’ 212 | **0.9507** |

Product = 212/236 = 0.8983 exactly. **Depth 20 already solves the slate stage at 0.9911**; the
binding stage under a rank-3 read is `cond@3`.

### THE LIMIT, MEASURED RATHER THAN ASSERTED

A **label oracle** picking the best of five rankers per query reaches `cond@3` **0.9686** (216/223),
implying R@3 **0.9432**. **Seven cases are missed by EVERY ranker in the family â€” 4 of them
`single-session-preference`.** So 0.975 stage retention is unreachable here at any configuration,
and 0.9301 sits ~3 cases below the family's oracle limit. Closing that needs a reranker trained for
a different notion of relevance.

### `single-session-preference` CHARACTERISED ALONE FOR THE FIRST TIME

Pooled numbers hid it. Fit R@1 **0.3333**, in-slate **0.8667** (in line with every other category),
`cond@1` **0.3846** against 0.76â€“0.91 elsewhere â€” **it fails at the head, not the slate**. It is
immune to depth (saturates at 0.3333 by d5). Two hypotheses refuted by measurement: it is **not**
question brevity (`single-session-user` has the shortest questions in the corpus, 4.59 content words,
and reads 0.8125) and it is **not** a near-tie (only 13.3% inside the 0.084 band â€” the model is
*confidently* wrong, with the lowest absolute top-1 logit of any category, âˆ’7.57). **R@3 doubles it
to 0.6667 and R@5 reaches 0.8667 â€” exactly its input recall.**

### SIX MECHANISMS CLOSED THIS SESSION, each with a control and a diagnosed cause

- **slate-unique IDF mass** â€” net **âˆ’39** at tau=0, âˆ’42 above the band, precision 0.150 against a
  chance base of 0.155. Control AUC 0.507, p=0.913. Both signs lose.
- **ablation attribution concentration** â€” net âˆ’26, âˆ’31 above the band. **76% a sentence-count proxy**
  (Spearman âˆ’0.54); gold is more concentrated in the 98 *solved* cases (62%) and inverts on failures.
- **within-turn sentence dispersion** â€” net âˆ’43 forward, âˆ’30 inverted, random expectation âˆ’38.
  **Cannot reach positive net at ANY tau on fit.** Gold-minus-competitor coherence is âˆ’0.0006 on
  failures vs âˆ’0.0009 on successes, p=0.65, with an instrument positive control that moves 1 SD.
- **query reduction at the cross-encoder** â€” âˆ’0.0175, and the **mechanism is inverted**: the preamble
  contributes **+1.37 to gold vs +0.82 to non-gold**. Ordering is monotone: full 0.7555 > reduced
  0.7380 > preamble-only 0.7118. With ADR-013 this closes the query side from both directions.
- **RRF as a slate-draw rule** â€” ir@10 0.9214 â†’ 0.9476 (+0.0262) but `cond@3` fell âˆ’0.0224 and the
  net was **+1 case**. **`cond@3` is a property of the SLATE, not of the reranker.**
- **fusing the cue rank into the final order** â€” âˆ’0.0393 R@3. The cue ordering drags gold out.

### FOUR CLAIMS IN THE RECORD CORRECTED

1. **The +26 head ceiling is not real.** 6 of 26 POSITIVE pairs already state the answer at rank 1,
   against **8 of 110** on the NEGATIVE control (ratio 3.2, Fisher p=0.028; 33.3% vs 2.7% on
   multi-token answers, p=0.0006). Hand-reading all 26 found 8 more with arbitrary gold labels â€”
   `3ba21379`'s flagged gold **does not answer its own question**. Corrected above-band ceiling:
   **8â€“14 cases, not 20.** Every one of the 23 prior mechanisms was scored against a denominator
   inflated 43â€“70%.
2. **Arm B did not memorise the fit split.** Its trained-on/held-apart delta is **+0.0212 (p=0.83)**
   against the shipped graph's +0.0135 â€” no excess. The *"deployed_top_k negatives are
   query-specific, so it memorised turns"* diagnosis, quoted forward as settled, is unsupported.
   **Underpowered at n=47 â€” unsupported, not refuted.**
3. **Fit-split contamination is not the cause of the 4-for-4 collapse record.** Session J's fold
   recovered exactly (base fit-val 0.6809 and best-epoch 0.7447 both reproduced through a different
   code path); the shipped graph's trained-on premium is **+0.0135, p=0.85** â€” *smaller* than the
   cue-only order's own case-mix wobble (+0.0395). Session I's case-mix conclusion stands.
4. **Â§4's unifying fact does not survive its most direct test.** *"Gold is multi-topic, distractors
   are single-topic"* is not measurable as embedding dispersion, and the archetypal distractor is
   **one sentence long** â€” undefined for the statistic, concentrated exactly on the pathology.

### TWO INSTRUMENT DEFECTS FOUND, ONE IN A TOOL THAT HAD ALREADY BEEN USED

- **`sweep_reranker_frontier` cannot measure depth below 10.** Its slate is
  `shipped_order(pool)[:depth]`, whose second sort level is **the cross-encoder's own score** â€”
  circular below 10. **Depth 1 would have reproduced 0.7555 and read as a passing degenerate
  control while measuring nothing.** Every depth here is drawn on the pre-rerank cue key, gated
  against the candidates the binary actually reranked (`rerank_score is not None`), 229/229 exact.
- **`heldout-read-armB.json`'s `_floor_status` is copied verbatim from the depth arm** â€”
  `fit_delta 0.0174, cleared false`. Arm B's fit delta was **+0.0698**, which clears the 0.02 floor
  by 3.5Ã—. The artifact says the one arm that earned its read took it in violation of the floor.
  **Not edited â€” flagged.**

### W1 AND W3 WERE STOPPED, BUT W3 FINISHED â€” AND IT BREAKS AN INHERITED CLAIM

An earlier draft of this entry said *"neither produced a cell."* **That was wrong for W3 and is
corrected here**, caught while staging the commit by reading the artifacts instead of trusting the
kill signal.

**W3 completed all 16 cells** (`seqlen-frontier-w3.json`), gate passed at fit R@1 0.7555:

| graph | d10@256 | d10@384 | d20@256 | **d20@384** |
|---|---|---|---|---|
| L-2-ft | 0.7555 | 0.7598 | 0.7686 | **0.7729** |
| L-6-ft | 0.7467 | 0.7380 | 0.7642 | 0.7511 |

Longer sequences help L-2-ft (+0.0043 at both depths) and **hurt L-6-ft**. Not shipped, not read on
held-out.

**THE PART THAT MATTERS IS THE GATE, NOT THE CELLS. PADDING INVARIANCE FAILS ON THE SHIPPED f32
GRAPH.**

```
seq 256: max_abs_delta 0.0014296  nonzero 59/60  invariant=False
seq 320: max_abs_delta 0.0013695  nonzero 60/60  invariant=False
seq 384: max_abs_delta 0.0013695  nonzero 60/60  invariant=False
seq 512: max_abs_delta 0.0011578  nonzero 60/60  invariant=False
```

**The registered prediction was "0.000000 on both f32 graphs at every length". It is refuted.**
`CLAUDE.md` and ADR-015 carry the inherited claim that *"all eight f32 graphs were invariant to
0.000000"* â€” measured by Session I, on **Session I's graphs**. The **shipped** graph moves by up to
**0.0014 logits** on bit-identical token ids re-padded to a different length, on 59 of 60 pairs.

It is ~8x smaller than int8's 0.0109, so it is not the ADR-015 hazard at full strength â€” but it is
**not zero**, and ADR-015's rule is that invariance is re-measured PER GRAPH and never inherited.
**So every sequence length is formally a different scorer on this graph too**, and W3's 16 cells are
not strictly comparable to one another. This is the standing lesson landing on the exact claim that
was supposed to have retired it.

**W1 trained four graphs** (`capacity-train-L-{2,4,6,12}-v2.json`, each with a recorded `best_epoch`)
and produced fit rerank scores for L-4 and L-12 â€” but **no scored R@1 cell table**, so the capacity
curve remains **NOT MEASURED**. The artifacts are committed so a future session resumes rather than
retrains. The confound is real but narrower than I first stated: **fine-tuned capacity IS already
measured across 16Mâ†’23M** (L-2-ft 0.7555 vs L-6-ft 0.7467 at d10, flat-to-inverted) â€” only *above*
23M is every model pretrained.

### NEXT

1. **One held-out read**, configuration fixed in `PREREGISTRATION-CASCADE-HELDOUT.json`. RRF primary,
   z-sum declared secondary, narrow width fixed at 10 and **not swept beforehand**.
2. **Latency on the GPU path** â€” two models now; ~50 ms against 300 ms is an inference, not a number.
3. **Two ship decisions, kept separate.** The ranking change delivers the R@1 gain and helps the
   product as it stands. **The admission change (top-3 instead of `vec![order[0]]`) is what converts
   R@3 into product value** and carries its own costs â€” Â§5.7 tokens, K1 precision, stale-fact harm.

---

## M2 Session E â€” LAYER 1 IS SHIPPED AND WORKING. `619 tests` (from 617), `eval/` 72 unchanged.

**Brief Â§8.2's second sentence now holds.** `web` no longer hands raw page text into the run that
holds `bash` and `edit`. The harness fetches; a **quarantined child** with an empty tool set and
`DenyAll` egress reads the bytes; the parent receives a validated, capped, character-checked summary
at `AgentInferred`. Reader and doer are separated.

**Verified live on the running binary, not in a test process** (`--dev`, real model, real fetch):

| | child (reader) | parent (doer) |
|---|---|---|
| tool message | `ok Â· 559 bytes Â· <!doctype html>â€¦` â€” **578 chars, the raw page** | `â€¦ read under quarantine, not shown here:\nfindings:\n  Thâ€¦` â€” **203 chars** |
| `tools offered:` | **(empty)** | all nine |
| floor | `UntrustedContent` | `AgentInferred` |

One fetch, two run ids in the journal: `run_spawned{quarantined_read=web, reads_untrusted=true}`,
then the **child** latching `UntrustedContent blocks_composed_targets=true` while the **parent** ends
`AgentInferred blocks_composed_targets=false`. The raw HTML appears exactly **once** in the entire
outbound dump â€” in the child's window.

### The gate that decided this came back NEGATIVE, and the build was directed anyway

The gate was: build only if `OutputContract::validate` constrains values. **It did not.** Three
checks â€” no unknown field names, no missing field names, an aggregate `String::len` cap â€” and
**nothing about any value**.

**Worse, and the reason the gate was right:** the `push` in `Engine::spawn` sits *outside* the match,
so **all five outcome branches crossed at `AgentInferred`** and `validate` governed one.
`Escalated { question }` interpolated a child's model-authored string â€” composed after it read the
page â€” verbatim into the parent at the trusted class. Constraining values alone would have closed one
door of five.

### What was built, in the order the gate required

1. **`FieldSpec` / `FieldType::{Text, Line}`** â€” per-field character caps and a control-character
   refusal. `ESC` is `U+001B`, so refusing C0 is what stops a fetched page writing ANSI escapes
   through a child onto a terminal. **No `ContractViolation` variant interpolates a value**: refused
   content must not arrive inside its own refusal.
2. **The four bypass branches closed.** Only a validated result carries content; Escalated/Failed
   render fixed harness strings and the detail goes to the journal, which is not model-reachable.
3. **`CondensedResult::render` made unforgeable.** Was `"{k}: {v}"` newline-joined, so a value
   containing `"\nanswer: â€¦"` forged a field header â€” names were whitelisted, the rendered form was
   not. Headers now sit at column 0; every value line is indented.
4. **The routing**, `Engine::condense_untrusted`. **Triggered on the trust class, not the tool name**
   â€” `blocks_composed_targets` is the same function the adjudicator enforces on, so the class that
   costs a run its targets is exactly the class that gets condensed, and no future tool needs anyone
   to remember it. **Fails closed everywhere**: no budget, contract violation, or a dead child each
   push a harness note and never the page.

**A carve-out was written and then removed.** The draft exempted *failed* results because their
bodies are harness-authored â€” true today, an assumption about every future executor, and exactly the
shape this project keeps logging. The rule is unconditional.

### Consequences, stated because they are large

- **`bash` after a fetch works again.** *"After fetching web data all his tools get turned off. seems
  dumb"* was layer 3 compensating for a missing layer 1. Fixed by separating reader from doer, **not**
  by relaxing layer 3: the threshold is untouched, and a run that does reach `UntrustedContent` still
  loses composed targets â€” asserted directly rather than inferred from an absent refusal.
- **NO tool result can taint a parent any more.** The only remaining source of `UntrustedContent` in
  a run's own window is **injected memory** (`daemon.rs` pushes the retrieved block at
  `retrieved.floor`). Layer 3 stays reachable and non-vacuous, but **its subject changed**, and four
  tests had to move to that taint source. One,
  `the_latch_announces_exactly_when_a_composed_target_is_actually_blocked`, **went green and vacuous**
  mid-session when its four trust classes collapsed onto one floor â€” caught by asking what the table
  would read if it were measuring nothing.
- **`a_batch_cannot_launder_a_target_through_its_own_sibling` lost half its subject.** Its second half
  tested a scenario layer 1 makes unreachable; it now asserts the new invariant and says so. The
  ordering property lives in `run_latching`'s four-class table.
- **A user who wants the raw page cannot get it.** "Show me this page's HTML" returns a summary. Real
  functional loss, accepted, unmeasured.

### A bug this introduced, caught by a failing test rather than by review

The quarantined child shares the parent's sink, so **every fetch printed *"read untrusted Â· composed
targets blocked for this run"*** â€” naming a child with no tools to block while the parent it named
was unrestricted. Both clauses false, on every fetch. **C2f's exact defect, re-opened by the component
built to fix it.** Closed by exempting `reads_untrusted` profiles from the announcement; the journal
still records the child's latch, and only the screen is gated.

---

## Four review findings, all measured

1. **`web`'s `inline_threshold_bytes: 0` is read by NOTHING.** The registration says *"Never inlined.
   Â§8.2: raw untrusted bytes do not reach attention"*; `body_for` decides against a global
   `MAX_INLINE_BYTES = 8_192` and never consults the manifest. The only reader is the test
   `web_is_inert_and_never_inlines`, which asserts `inline_threshold_bytes == 0` â€” **the declaration,
   not the behaviour**. It passed on a build where every byte reached attention. Layer 1 makes it moot
   for `web`; **the dead field and its green test remain, unclaimed.**
2. **`EgressPolicy::grant()` has no call site in the product.** The only three are `adjudicate.rs`'s
   unit tests, and `CapabilityProfile` exposes `egress()` returning `&EgressPolicy` with **no `&mut`
   accessor** â€” unreachable by construction. The doc comment describing a session-held per-host grant
   describes a mechanism that does not run. **Security-positive today** (every fetch is a fresh human
   decision, stronger than ADR-032 Â§3.1 describes) and a live hazard the moment anyone wires it up,
   because the widening path would silently activate untested. `egress_grant.rs`: three fetches, two
   hosts, **three approvals**, `granted` still empty.
3. **The `--ask` transcript prints the opposite of what happened.** `agent.rs:354` emits *"(no
   interactive surface attached; the harness declined)"* **unconditionally**, over an
   `Event::Approval` that is emitted as a *prompt*, before any decision exists. Live: the human
   approved, the fetch executed, the screen said declined.
4. **The journal does not record what egress was approved.** `approval_requested` is `{"tool":"web"}`
   and `approval_granted` is `{}` â€” no host, no URL, no decision id. `egress_blocked` **does** record
   the host, so the blocked path is auditable and the granted path is not.

**Layer 5 does not exist (M6). Layer 2 was not re-measured** â€” its 16-checked/0-failed reading is
inherited from M0b Session A and is a citation, not a result.

## DEFERRED explicitly â€” the human accepted these losses to get layer 1

- **The full per-tool decision table.** Partial only: `read`/`find`/`recall`/`web` are Inert and skip
  Â§9's target check (`inert_no_target_check`, recorded by the adjudicator in the journal itself);
  `remember`'s `text` is a Payload, so a claim carrying no target argument is never target-checked;
  `edit`/`use` are checked; `bash` is checked and then escalates unconditionally.
- **Reconfirming Session D's four live-verified claims.** **ADR-038's cited evidence is NOT in the
  default profile's journal** â€” two `memory_written` events, both `agent_inferred`, no `claim-2
  untrusted_content`. Presumably a scratch profile; it could not be reconfirmed from disk and remains
  a citation.
- **M2 Session E as ROADMAP defines it is NOT covered and remains unscheduled**: the TUI against the
  real loop, first-run onboarding, K6 in a clean container.
- **`repro`/`conformance` not re-run.** Measured reason, not assumed: the eval adapter references
  neither `Engine` nor `marlowe_loop`, so the loop change cannot reach that path; `eval/` is 72 green.
- **The injection question is unanswered.** Three live attempts: the model hallucinated a URL, then
  refused the payload, then refused to fetch at all. **Model refusal is not containment** â€” layer 3
  armed and was never exercised, and n=1 says nothing about the next model or payload. What is
  answered is the harness's reach, which is what the tests measure.

**`tools/read_journal.py` is committed this time.** Session D built the same instrument, left it in a
scratchpad, and it was gone. It reads the signed journal directly rather than asking Marlowe, whose
answer is a capability report. Its first run corrected three guessed event spellings â€”
`permission_decided`, `tool_requested`/`tool_completed` â€” each of which would have queried an empty
set and printed a confident "0 events".

---

## M0c SESSION M â€” THE RANKING SPACE IS CLOSED. R@1 UNMOVED AT 0.6725, AND THAT IS THE RESULT.

**`runs/session-m0c-m/`. Pre-registration committed at `4373111` BEFORE any number existed.
NOTHING SHIPPED. Three held-out reads spent, all null. No crate was touched.**

The session opened as "build cue 3" and ends having closed the entire post-hoc ranking space with
numbers behind every door. **The closed doors are the product; the null is not.**

### THE ONE NUMBER THAT MATTERS, AND WHY EVERY FIT NUMBER BELOW IS SUSPECT

| mechanism | fit delta | held-out delta | collapse |
|---|---|---|---|
| depth 30 (L-6-ft) | +0.0174 | **+0.0044** | 4x |
| retrain, arm B (new negatives) | **+0.0698** | **+0.0087** | **8x** |
| joint pairwise encoder (duoBERT) | +0.0655 | **+0.0044** | **15x** |

**Everything trained or tuned on the fit split shows a large fit gain and nothing on held-out.**
Three mechanisms, three directions, three collapses. M0c Session A said the binding constraint is
labelled data â€” 38 informative fit failures â€” and this session tested that from three angles and it
held every time.

**Arm B is the case to remember.** Fit **0.8253** (+0.0698, McNemar 18/2, **p = 0.0004**), cleared
the registered floor by 3.5x, with a contamination control the agent added unprompted. Held-out
**0.6812** (+0.0087, 10/8, p = 0.815). The fit/held-out gap *widened* from 0.083 to 0.144 â€” the
signature of overfitting, measured rather than asserted. `deployed_top_k` negatives are
**query-specific by construction** ("the turns that beat gold on THESE queries"), so the model
memorised turns instead of the pattern.

### THE PIPELINE, WITH GOLD RETENTION AT EVERY STAGE (held-out, 234 answerable)

| stage | gold survives | stage retention | lost |
|---|---|---|---|
| answerable cases | 234 | â€” | â€” |
| ingest + Â§4.3 + scope | 229 | 0.9786 | 5 |
| session pruning | 225 | 0.9825 | 4 |
| slate draw (top-10 by cue key) | 207 | 0.9200 | 18 |
| **cross-encoder picks rank 1** | **154** | **0.7440** | **53** |

Retentions multiply exactly: 0.9786 x 0.9825 x 0.9200 x 0.7440 = 0.6581 = 154/234.

**The cross-encoder loses 53; everything else combined loses 27.** If it were perfect, R@1 would be
0.8846. If any other stage were perfect, +0.012 to +0.057.

**And the published R@1 = 0.6725 uses 229 as its denominator, not 234** â€” `load_pools` drops the 5
cases where gold never survived. On the honest basis R@1 is **0.6581**. In the other direction, **9
of 56 fit failures put a turn STATING the gold answer at rank 1** (answer-containment diagnostic),
so the true figure is uncertain by a couple of points in both directions.

### R@2 AND R@3, MEASURED FOR THE FIRST TIME

| k | 1 | **2** | **3** | 5 | 10 |
|---|---|---|---|---|---|
| held-out R@k | 0.6725 | **0.8122** | **0.8515** | 0.8865 | 0.9039 |

**81% of queries have gold in the top 2.** Gold first appears at rank 1 in 154 cases, **rank 2 in
32**, then 9, 6, 2, 3, 1. **+0.1397 sits in a single binary decision**, agreeing with the head
probe's independently measured ceiling of +0.1135 on fit.

### WHAT IS CLOSED, WITH THE NUMBER THAT CLOSED IT

- **temporal cue** â€” Session G arm 4 already refuted it: **1/59** temporal-reasoning questions carry
  a parseable window; held-out âˆ’0.0087. Its mechanism on this corpus is *session selection*, which
  the failure decomposition puts at 4 cases against 77.
- **bigger cross-encoders** â€” nine models, 16Mâ†’278M, four architectures, on GPU. **The 278M models
  lose to a fine-tuned 16M by 17â€“27 points.**
- **the GPU budget** â€” not the constraint. All 30 frontier cells fit 300 ms; the best uses **37 ms**.
  Every rejection figure in this project was a **1-thread CPU** number for a **GPU** target.
- **depth 30** â€” held-out null, 20 gained / 19 lost, **p = 1.000**.
- **twenty post-hoc tie-breaks** â€” question echo, IDF non-query mass, length, role, session,
  truncation, cue scores, recency, rank fusion, numeric type, neighbour structure, sentence MaxP at
  every band and alpha, three span readers, ensemble voting, reader-null penalty, centroid
  subtraction.
- **the objective axis** â€” BCE *hurts* (âˆ’0.0524 at fixed negatives). The LCE audit found M0c A's
  listwise arm DID use the deployed group, so that null stands.
- **the joint pairwise encoder** â€” the last thing anyone could point at. Held-out +0.0044.
- **proposition-level INDEXING** (change the retrieval unit, not the order) â€” input recall
  **âˆ’0.0786** at depth 10, worse at every depth, same implementation run both ways as the control.
- **context decay around the peak span** â€” the hypothesis was BACKWARDS: gold decays **10x MORE**
  (0.1337 vs 0.0133), because the gold answer is a narrow span inside a multi-topic turn while the
  distractor is uniformly on-topic. Inverted it looked real â€” fit **+0.0305, p=0.039**, clearing the
  floor and firing 3/1 above the near-tie band â€” and read **âˆ’0.0087** on held-out.
- **the predecessor turn** (what prompted the candidate) â€” refuted by its own sign control: **âˆ’69 to
  âˆ’98 added, âˆ’52 to âˆ’68 subtracted.** A feature that hurts in both directions carries no signal.

**THE UNIFYING FACT, which explains all three and most of the twenty:** *gold turns are multi-topic
with a narrow answer; distractors are single-topic and coherent.* So every operation that rewards
"sustained topical support" â€” decay, neighbour affinity, centroid subtraction, the predecessor â€”
favours the DISTRACTOR, and every operation that isolates a peak â€” MaxP, proposition indexing â€”
surfaces the distractor's question-echoing span as well as the gold's answer. **The dilution that
looked like the disease was also the immune system.**

**The ceiling on the entire post-hoc class is +5 cases, set by a blind coin flip below a 0.084
logit gap.** That is not "we failed to find the trick" â€” it is measured.

### THREE THINGS FOR THE LEDGER

1. **THE NEAR-TIE SIGNATURE.** Any mechanism that perturbs a pointwise score gains 4â€“6 with ~0
   losses **entirely inside gaps below 0.084**, and none fires correctly outside it. The span
   reader (+6/âˆ’0, p=0.031, cleared the floor) **evaporated to 1 gained / 4 lost** against a
   different base ranker. Sentence MaxP fired 6 times above the band and got **0** right. **A
   post-hoc result measured on one base ranker is not a result until a second one reproduces it.**
2. **A HELD-APART SUBSET OF THE SAME SPLIT IS NOT A HELD-OUT SPLIT.** Arm B's within-fit,
   conversation-level control read +0.0638 on 47 queries â€” 3 cases, p = 0.25 â€” and predicted
   nothing. The corpus, the mining procedure and the model that generated the negatives were all
   shared.
3. **THRESHOLD SELECTION OVERFITS AT n=229, NOT JUST TRAINING.** Four mechanisms cleared their fit
   bar and died: depth (+0.0174 â†’ +0.0044), the retrain (+0.0698 â†’ +0.0087), duoBERT (+0.0655 â†’
   +0.0044), context decay (+0.0305 â†’ **âˆ’0.0087**). **Decay was never trained.** Only its lambda was
   chosen on fit â€” one hyperparameter from ten cells â€” and even that did not transfer. **A rule with
   a tunable knob is already suspect on this corpus.** Anything proposed next should have its
   operating point fixed BEFORE the fit read, or be parameter-free.
4. **AN IDENTITY ERROR, MINE.** I proposed recalibrating the reranker head because **0 of 229**
   chosen candidates score above its relevance boundary (median âˆ’6.99). R@1 is a within-query
   ordering read and any monotone transform is an identity on it â€” ADR-011, ADR-013, and Session I's
   arm 6, now a fourth instance. Caught by a reach check *before* the training run, which is what
   they are for. The observation itself stands and governs **coverage**, not R@1.

### THE CROSS-ENCODER, CHARACTERISED

Pointwise: `[CLS] q [SEP] turn [SEP]` â†’ **one scalar**, `logits: [batch, 1]`. Two layers, hidden
384, 16M parameters, seq 256. **Attention runs within a row, so even a batched [10,256] forward
gives no cross-candidate information â€” batching is compute, not joint reasoning.**

It is fed **`entry.text` and nothing else** (`retrieve.rs:582`). Not role, not `occurred_at_ms`, not
session, not turn index, not the surrounding turns, not its own cue scores â€” all of which we hold.

Its real failures are **diffuse**: outside `single-session-preference` (53% failure, **4.07x**
enrichment, 8 of 30) every category sits between 0.54x and 1.19x of base rate. **Temporal-reasoning
is its BEST category at 0.54x** â€” deictic questions fail at the *slate*, not the ranker.

### WHAT IS LEFT, AND NONE OF IT IS RANKING

1. **QA accuracy â€” never measured.** It is M0b's actual acceptance row (>=90%). The recorded
   `answer_accuracy 0.0` is **two absences stacked**: `adapter.rs:649` hardcodes `answered: false`,
   and every Session K frame reads `no_candidate_above_threshold` under a gate ADR-016 measured as
   unclearable. Pilot (n=20, `qwen3.5:9b`, lexical grading): **none 0.00 / gold 0.65 / k5 0.55 /
   k10 0.50 / k1 0.25.** The clean 0.00 floor is the only part solid at that n.
2. **The admission rule.** `retrieve.rs` admits `vec![order[0]]` â€” **one memory**. The pilot reads
   **k1 0.25 against k5 0.55**. If that holds at n=229 it is worth more than any R@1 work, and it is
   a one-line change against a training programme. It is not free: tokens against Â§5.7, precision
   against K1, and stale-fact harm.
3. **Supersession via HP2 entity identity** â€” +0.1666 on knowledge-update R@1_current by M0c A's
   oracle, harm âˆ’71%. Blocked on a component that has a design and was never built.

**And the reframe that should survive this session:** we are not behind the field. Three published
systems report **session-level** recall@5 â€” MemPalace 96.6%, agentmemory 95.2%, both LLM-free, both
with **no held-out split**. Marlowe reads **0.9738 shipped and 0.9869 on its dense cue alone**. Both
of their docs say outright that this is not the benchmark's official metric. **Nobody in that
comparison set, including us, reports QA accuracy â€” which is why measuring it is the highest-value
thing left.**

---

## M0b SHIPPED 40% OF ITS NAMED MECHANISM AND CLOSED WITHOUT SAYING SO

**Found 2026-08-11, reading M0b's own scope against the code.** This is a brief for whoever builds
the missing cues, and a correction to the record.

M0b's scope section lists, verbatim:

> - **Five cues** + query-type router + fusion + frozen gate.
> - **ANN index + int8-quantized hot vector array. An M0b requirement, not a later optimization.**
> - **Live-only hot index (ADR-003 â€” requirement, not optimization).**
> - **Group commit on journal append. Scoped here rather than left as a note.**
> - Consolidation **as a run**: supersession, contradiction resolution, fidelity demotion, trend
>   extractors (HP3), silent-entry maturation.

**What exists:** two cues (lexical, dense), fusion, the frozen gate. No query-type router. No ANN
index. No int8 vector array. No hot index. `group commit` appears once, in a comment describing what
durability *would* need. `consolidate.rs` is a function, not a run â€” nothing calls it outside the
eval adapter, and it cannot spawn.

**Three of those lines contain a phrase written to pre-empt exactly this** â€” *"requirement, not a
later optimization"*, twice, and *"scoped here rather than left as a note"*. They were deferred
anyway.

**And the closure names two carried items â€” head separability and the human label set â€” while at
least four more were carried silently.** That is the difference between a deferral and a gap: one is
on the record. The ROADMAP's M0b header is corrected as of this entry.

### Why this is the strongest "should already have been done" in the project

**Sessions D through L â€” nine of them â€” all worked the two cues that exist.** Fusion (failed floor),
per-query features (failed floor), consolidation (null), query side, cross-encoder rerank, the
sequence cap, fine-tuning, GPU. The largest quality win was **+0.0699** from fine-tuning the
reranker. M0c Session A then closed both remaining named candidates with **R@1 unmoved at 0.6725**.

**No third cue has ever been attempted.** `retrieve.rs`'s header has said since Session B that *"a
number produced here is a statement about an incomplete cue set rather than about the design"* â€” and
that sentence has been read as a caveat for nine sessions instead of as a work item.

**0.6725 is a real measurement of a system that is not the designed one.** The labelling has been
scrupulous throughout; what went wrong is that it was then treated as *retrieval quality* in every
downstream decision, including K1's amendment and the declared operating point.

### The brief, for the session that builds cue 3

**The gate artifact already contains the instruction.** `gate-frozen-v5.json` on
`cue_agreement_2cue`: *"It stays pinned because making it informative requires a FIRING PREDICATE
for the dense cueâ€¦ **Unpin at cue 3**, where agreement stops being a coarsening â€” **and
pre-register the predicate before doing so.**"* Someone anticipated this session; do what it says.

Constraints, none of them optional:

- **Pre-register before any fit.** `tools/preregister_split.py` ran once and is never re-run;
  new bands need their own registration file *before* a number is produced. CLAUDE.md: *"Pre-registration is a file, not an intention."*
- **A new cue changes the gate's feature vector**, so it needs a refit and a **new artifact version**
  (v6). `FrozenGate::from_artifact` refuses a feature outside all three roles without a stated
  reason, and refuses an inert declaration that is actually a cue or a rank feature â€” those errors
  are the guard, not obstacles to route around.
- **ADR-010 is binding: no calibrated value may enter the ranking key.** Isotonic output is a step
  function; Session D ranked on it and 60.4% of held-out cases tied at the fused maximum. New cue
  features must be **continuous and query-local** â€” raw, margin and z, kept together in a `CueSpec`
  so indices cannot drift.
- **Features are set-level.** `extract_all` takes the whole candidate set because rank, margin and z
  do not exist for a candidate in isolation.
- **Determinism**: `BTreeMap`, never `HashMap` (the determinism guard bans hash-ordered
  collections); no clock reads on any Â§4.1/4.6 path.
- **Report `R@1_current` beside R@1.** LongMemEval marks both the stale and the current turn
  `has_answer`, so returning the outdated value scores as correct â€” held-out 0.6725 â†’ 0.6288 when
  counted honestly, and 0.7222 â†’ 0.4444 on knowledge-update.
- **`eval/` is never modified.**

**The trap: do not tune the two existing cues again.** Nine sessions did that and the remaining
headroom there is measured and small. The open question is whether a third cue moves R@1 more than
nine sessions of tuning two did â€” and nobody knows, because nobody has built one.

---

## NEXT SESSION IS A FULL SECURITY REVIEW. Read this first.

**The five layers are in `CLAUDE.md` and must be known by number.** What follows is what Session D
established about them â€” including one finding that is a shipped-requirement gap, not a to-do.

### LAYER 1 IS HALF-SHIPPED, AND THAT IS THE HEADLINE

`CapabilityProfile::quarantined_reader()` exists and is load-time enforced:
`reads_untrusted && !exposed_tools.is_empty()` refuses to construct. **The component exists. The
routing does not.** `ModelStep::Spawn` is constructed nowhere outside tests, so nothing puts a
quarantined child between `web` and the main run.

Brief Â§8.2's required control has two sentences. The first is built. **The second â€” *"the component
with tool access receives sanitized structured input, never raw untrusted text"* â€” is violated
today**: `web` hands raw page text straight into the context of the run that holds `bash`, `edit`
and the filesystem. Reader and doer are collapsed, which Â§8.2 names as the configuration that makes
deployments exploitable. The gap arrived when C2f shipped `web` without the route, and it was not
noticed then.

**Consequences to carry into the review:**

- **Layer 3 is currently doing layer 1's job**, which is why a fetch kills `bash` for the rest of a
  run. That is the guard compensating, not the guard misbehaving. The human reported it as *"after
  fetching web data all his tools get turned off. seems dumb"* â€” the read is right and the cause is
  the missing control. (Narrower than "all": Â§9 exempts `Inert`, so `read`, `find`, `recall` and
  `ask` still work; `bash`, `edit` and `web` lose model-composed targets.)
- **It is NOT blocked on the spawn contract.** An earlier claim in this session that it was is
  wrong. Â§5 forbids *inferring* a child's profile, budget and orphan policy; for `web` the harness
  declares all three (constant `quarantined_reader()`, budget sliced from the parent, dies with the
  parent) and the model decides nothing.
- **What genuinely does not exist is the extractor** â€” page bytes â†’ structured analysis.
  `CondensedResult` is already the return shape. Deferred deliberately in C2f (*"an extractor that
  panics must not take the egress path with it"*), and **owned by no milestone**.

### What the review can and cannot get from the eval suite

**`marlowe_eval`'s Â§4 wire reaches layer 2 and the ingest actor check, and nothing else.**
ingest/retrieve/consolidate speak to a process with no loop, no tools and no egress, so **no
poisoning ASR from it is evidence about layers 1, 3 or 4.** Those need loop-level tests â€”
`profile.rs`'s load-time refusal and `adr023_live.rs` are the existing ones.

**The ASR control ran and the answer is real** (`runs/m2-session-d/RESULT-ASR-CONTROL.md`): removing
the K1 cut point raised injected volume ~61% (`retrieval_tokens` 9.625 â†’ 15.5) and **every ASR stayed
0.000**. So the operating point is not what stops these attacks â€” but n=4 per family on an 8-query
fixture cannot distinguish 0.00 from 0.20. **Do not quote these ASRs as resistance.**

**The K1 gate is not a security layer.** It is relevance. Â§8.1: *"Filtering does not work.
Containment works."*

### Live-verified this session, and the distinction matters

| | |
|---|---|
| Layer 3 blocks composed targets after a real fetch | **live** â€” 7 issued, 7 refused (C2f) |
| `bash` through the approval window on a real turn | **live** â€” prompt shown, human approved, executed |
| `web` egress approval on a real turn | **live** |
| ADR-038's floor reaching the write path | **live** â€” `agent_inferred` before a fetch, `untrusted_content` after |
| Layer 2 propagation | **measured** â€” 16 checked, 0 failed, non-vacuous |
| Layer 1 quarantine | **load-time enforced, never exercised** â€” nothing spawns |
| Layer 4 egress `AllowApproved` | **SHIPPED and live-verified.** `interactive()` holds `AllowApproved { granted: [] }`; `grant()` widens one host at a time; a real `web` fetch was approved through the TUI modal this session. An earlier line in this file said "approved but not shipped" â€” that was stale and was carried forward without checking |
| Layer 5 trust ledger | **not built â€” M6** |

### Two Â§13 holes, unfixed on purpose, both needing a decision before code

1. **Consolidation merge.** Clusters on **text cosine alone**, no trust term, representative is the
   **latest**. A newer attacker-authored near-duplicate supersedes a genuine `UserAsserted` belief
   out of the candidate set â€” **eviction**, not laundering, and no layer covers it. Not reachable in
   the product today (consolidation is unwired); reachable on the eval path.
2. **`effective_trust` is inert in the ranker.** The gate artifact declares it *"zero variance across
   the fit splitâ€¦ would become load-bearing the moment the feature starts varying"* â€” and ADR-038 is
   that moment. **Filed first as a security hole and CORRECTED to a quality finding**: Â§5.6 says
   untrusted memories may inform *analysis* but not authorize *action*, so being read is the
   specification and layer 3 governs the rest.

Either change moves a registered number and needs a pre-registration first.

### One rule invented this session that nobody has ratified

`correct_claim` **refuses a correction whose effective trust is below its target's**. Superseding
evicts the target from auto-injection, so allowing it would let a tainted run delete a user-asserted
belief through an ordinary tool call. Conservative, costs a legitimate case, recoverable via
`remember`. **Keep or drop it deliberately.**

---

## M2 Session D â€” memory is wired. `617 tests` (from 583). Conformance **CONFORMS** for the first time.

### After the `850b512` commit, this session also shipped

- **D2b â€” the daemon retrieves.** `select_for_injection` had exactly one caller, the eval adapter, so
  conformance and the poisoning suite exercised injection while **the daemon contained none**. A
  property measured on one path and claimed for another. `RetrievalState` is now **announced** at
  startup and on `--status`: `live Â· <dir>` or `WRITE-ONLY Â· <why>`.
- **D3 â€” `recall` has an executor and is exposed** (nine tools, not eight). `marlowe_daemon::recall`.
  **Deliberately not gated by the operating point**: Â§3.6 requires it to see tombstoned and unmatured
  entries, which auto-injection must not. Live: remember â†’ restart â†’ `recall` â†’ correct answer, with
  `injected 0` proving auto-injection contributed nothing.
- **`correct` and `forget`** â€” CONTRACTS Â§3.5's other two methods, built on `remember_claim` so the
  trust rule cannot diverge. **Neither is exposed as a tool**: `BUILTIN_TOOLS` is still ten, and the
  exposure shape is an open decision.
- **The template bug.** A qwen3-next model returned `Jinja Exception: System message must be at the
  beginning`. The wire emitted one `system` message **per block** plus one mid-conversation for
  injected memory. Now exactly one, at position 0. `qwen3.5:9b` accepted the old shape, which is why
  it survived â€” the wire was validated against the one model anybody ran.
- **Model selection.** `--models`, `--model`, and a **working TUI picker** built from the daemon's
  list. A non-default model reports **NOT MEASURED** rather than inheriting qwen3.5:9b's 12/12.
- **Cross-session scoping is now declared.** `RetrievalScope::{ThisSession, Profile}`. The eval keeps
  `ThisSession` â€” widening it would let every LongMemEval case see every other's turns and invalidate
  every published number. The daemon uses `Profile`, because a session there is a *client name*, so
  `--ask` memories were invisible to TUI injection. **The declared operating point was calibrated on
  session-scoped pools; under `Profile` the margin distribution differs, so
  `PRECISION-COVERAGE.md`'s coverage and precision do NOT describe the product.**
- **Tool descriptions and schemas rewritten** against their executors. Two parameters deleted for
  being accepted and silently dropped: `ask.options`, and **`recall.payload_kind`** â€” a model
  filtering by kind believed it had filtered and got an unfiltered answer.

### Still outstanding

- **Vectors at write time.** The daemon embeds nothing, so the dense cue scores 0.0 for every
  candidate and product retrieval is lexical + rerank â€” below what the eval path measures.
  Deliberately **not** done before the security review: it is a scored-path change with no
  measurement attached.
- **`correct`/`forget` exposure** â€” two new manifests, or a `supersedes` argument on `remember`, or
  CLI-only. Needs a decision.
- **`web` through a quarantined child** â€” see the top of this file.
- **Unattended egress** â€” blocks *"research he did solo"*, which is a REQUIRED capability
  (`docs/requirements/proposed-research-memory.md`).

**`remember` writes, beliefs survive a restart, and `recall` reaches them.** Verified live against a
real model, not in a test process. `runs/m2-session-d/` holds `PREDICTION.md` (written first),
`BASELINE.md`, `RESULT-D2.md`, `LIVE-CHECKS.md` and `OPEN-QUESTION-0-AUDIT.md`.

| | before | after |
|---|---|---|
| conformance | `REJECTED Â· fail_no_time_dependence` (unchanged since M0b B) | **`CONFORMS`, clock probe passed** |
| `repro` | `e796c12eâ€¦` | `68d6562bâ€¦`, **two runs IDENTICAL** |
| exposed tools | 8 | **9** â€” `recall` gained an executor |

### The four STATE items were one missing piece, and three are closed

**`remember` had no implementation at all.** `memory: None` was concealing an *absence*, not a
disconnection: `ingest()` wrote turns and **nothing wrote a model-supplied claim**. CONTRACTS Â§3.5
pins `remember(run, claim)` and it had never existed. `marlowe-memory/src/claim.rs` is it.

- ~~**The gate still injects nothing.**~~ **CLOSED.** K1's declared operating point is the admission
  rule. ADR-016's isotonic gate no longer filters â€” `passes` is false for every candidate by
  construction, which is why nothing had ever been injected.
- ~~**`consolidation()` exposes `recall`, which has no executor.**~~ **CLOSED.**
  `marlowe_daemon::recall::RecallTools`. The guard fired exactly as predicted.
- ~~**Session memory is in-process only.**~~ **CLOSED FOR BELIEFS, deliberately not for
  conversations.** `BeliefStore::derive` rebuilds from the journal, so memory is durable with no new
  persistence machinery. **The honest sentence: memory survives a restart, the conversation does
  not.** Durable conversations remain M3's WAL work and were not built twice.
- **`read` still cannot dereference a reference.** Deferred with the human's agreement; the content
  store is a different mechanism from belief memory.

### ADR-038 â€” a model-authored claim writes at `min(AgentInferred, run_floor)`

Bare `AgentInferred` was a **laundering path reachable today**: a run that fetched a page and called
`remember` would write attacker-shaped text one class above `UntrustedContent` with the page's origin
nowhere in the record. `profile.rs`'s `reads_untrusted && may_write_memory` guard does not cover it â€”
that closes the *quarantined reader*, and an ordinary `interactive()` run is neither.

Verified live, same session, same tool, same model:

```
claim-0   agent_inferred      'my favourite colour is green'
claim-2   untrusted_content   'example.com is a reserved test/example domain...'   â† after a fetch
```

### THE PREDICTION FILE CAUGHT THE DEFECT IT PREDICTED

`PREDICTION.md` was written before the baseline and says, of the operating point: *"If it were ANDed
with `passes`, injection would remain dead, the poisoning suite would stay vacuous, and the change
would be undetectable."*

**That is exactly what was built.** `order.retain(|i| scored[*i].passes)` was left in place and the
cut point added after it; conformance read `fail_no_time_dependence`, unchanged. Without the
prediction on disk the honest reading would have been *"the margin doesn't clear on a five-turn
corpus"* â€” plausible, wrong, and it leads to tuning the threshold. **A predicted change that lands is
evidence; an explained one is not, and this is the case that shows why.**

### The poisoning suite is STILL VACUOUS, for a new reason â€” do not quote its ASRs

All five families read **0.000**, n=4 each, with `answer_accuracy 0.0` and **6 of 6 answerable
queries abstained**. Before D2 the ASRs were vacuous because the gate injected nothing ever; now
injection works and the 10% operating point abstains on essentially everything in an 8-query fixture.
**An attack that fails because nothing is injected is indistinguishable from one a guard caught.**

**The discriminating measurement â€” ASR at full coverage vs at the operating point â€” was not run.**
Until it exists these numbers say nothing about poisoning resistance.

**Two poisoning mechanisms ARE non-vacuous and passing**, and should be quoted separately:
`trust_assertions` 16 checked / 0 failed (HP6 measured, not argued), and `ingest_rejections` firing
by name on the forged `permission:grant` actor.

### `--dev` caught a false pass that the answer alone would have sold

Asked to remember a colour and then asked the colour, Marlowe answered **"Green."** â€” with
`injected 0`. Both `--ask` calls share session `cli`, so they were turn 1 and turn 2 of **one**
conversation: C2e's *"there was only ever ONE conversation"*, recurring. **Reported without `--dev`
it would have read as memory working.** The real test restarts the daemon first.

### Open question 0 is answered: two holes, one safe, one absent

`runs/m2-session-d/OPEN-QUESTION-0-AUDIT.md`. **Both holes need a Â§13 decision and neither was
touched.**

1. **Ranking inputs â€” HOLE.** `effective_trust` is a declared gate feature and is **inert**: the
   artifact says *"zero variance across the fit splitâ€¦ would become load-bearing the moment the
   feature starts varying."* **ADR-038 is that moment.** An untrusted memory and a user-asserted one
   now rank identically. `recall` is worse â€” lexical score only.
2. **Cache keys â€” SAFE, and STATE was wrong to say "there is no cache yet".** `PrefixCache` is keyed
   `(SessionId, epoch)`, both harness-assigned; the embedding cache is content-addressed over a pure
   function.
3. **Derivation lineage â€” does not exist yet.** The tool argument is guarded; no harness-side path
   computes lineage.
4. **Consolidation merge â€” HOLE.** Clusters on **text cosine alone**, no trust term, and the
   representative is the **latest**. A newer attacker-authored near-duplicate **supersedes a genuine
   `UserAsserted` belief out of the candidate set** â€” eviction, not escalation. Not reachable in the
   product (consolidation is unwired); reachable on the eval path.

### Live checks â€” A, B, B2 pass. **C is still unrun.**

The console control handler and the busy mirror agree in **both** directions, so C2e's mid-turn
conversation loss is not back. **`bash` through the approval window has still never been observed on
a real turn** â€” though an approved `web` fetch did cross the same modal this session.

### Defects found by running, not by testing

- **One `remember` emitted TWO `MemoryWritten` events** â€” the memory component's and the loop's, the
  latter carrying only `{"text": â€¦}`. `BeliefStore::derive` decodes every one, so **the daemon
  refused to start on the next restart**. 594 tests passed throughout: the memory crate's tests call
  `remember_claim` directly, the daemon's call the host directly, and **neither crosses the seam**.
  `engine.rs`'s comment had said the loop does not do this since before it did.
  Closed, plus `memory_write_ownership.rs`.
- **The startup guard verified a host the turn does not use.** `Daemon::open` checked a bare
  `FileSystemTools` while the turn ran `RecallTools`. It failed loudly here; in the other direction â€”
  a runtime host with *fewer* executors â€” it passes startup and fails on the call, which is the
  `done` defect. Closed by `build_tool_host`, now the only constructor.
- **A build that cannot replace a running binary fails, and the old code keeps serving.**
  `cargo build --release` returned `Access is denied (os error 5)` because the daemon held the exe,
  and the next run was read as evidence about the fix. **Order is shutdown â†’ build â†’ start.**

### Still open from this session

- **Retrieval has no vectors.** The daemon embeds nothing at write time, so the dense cue scores 0.0
  for every candidate and retrieval is lexical + rerank. Announced, not silent.
- **`--reranking` is optional on `--serve`** (unlike `--eval-adapter`, where it is a refusal) so a
  60 MB model is not an install-time dependency of being able to talk. Absent, memory is
  **write-only** and `RetrievalState` says so at startup.
- **`1 memorie`** â€” pluralisation bug in the metric renderer, seen on a real `recall` line.
- **`--status` has no `--daemon-port`**, so it cannot report on a scratch daemon â€” the gap C2f closed
  for `--ask`. Worse, with nothing on the default port it calls `Daemon::open` and reports on a
  daemon it just constructed.
- **A reconnecting client cannot tell a BUSY daemon from a dead one.** `finish_connect` does three
  blocking round-trips with no timeout, so the surface accepts no input while it decides. The STATE
  entry below saying such a client *"shows the conversation up to the last completed turn and then
  waits"* is **wrong**: it shows nothing.
- **Research memory is a REQUIRED capability** â€” `docs/requirements/proposed-research-memory.md`,
  asserted by the human, not designed. Its blocker is **unattended egress**, not memory.

---

## M2 C2f â€” the latch met real untrusted content. `561 tests` (from 550).

**ADR-023's four properties confirmed against a genuinely fetched page, and the fourth had never
been exercised by anything.** `cargo test -p marlowe-exec --test adr023_live -- --ignored`.

```
view floor: AgentInferred   run floor: UntrustedContent   pages in view: 0
7 composed shell commands issued, 7 refused, 0 executed
```

The view's floor **rose** as the page fell out of the budget; the run's latched floor did not follow
it up; every composed Target stayed blocked. That is the exact hole the latch was built to close â€”
the assembler dropping a block to stay inside budget silently handing back privileges â€” and until
now the only evidence for it was a `Block` a test constructed and labelled itself.

### The latch fired on Marlowe's own name, on every run that has ever run

**Item 1's diagnosis was a fourth candidate: not the trust class at ingest, not the floor
derivation â€” the ANNOUNCEMENT.** Ingest is right (`read` returns `AgentObserved`), the floor
arithmetic is right, and `adjudicate` blocks at `<= UntrustedContent`. The loop emitted
`Degraded{TrustFloorLatched}` on **any** downward move, and the surface renders that as
*"read untrusted Â· composed targets blocked"*.

A run starts at `UserAsserted`. The assembler constructs the stable tier on every assemble and the
`Identity` block â€” the string `"Marlowe."` â€” is `AgentObserved`. **So the floor moved on the first
assemble of every run, before the model spoke and before any tool ran**, and the first assistant
turn (`AgentInferred`) moved it again. The negative control reads `left: 2, right: 0`: the product
printed the banner **twice**, on a run with no tools at all, with both clauses false.

**The capability-report family, once more.** The event fired on *floor moved*; the text asserted
*floor reached untrusted*; the banner read the same either way, so it was never evidence about the
guard. A latch that fires on everything means nothing â€” which is the state it must not have been in
when `web` made it live.

`marlowe_permission::blocks_composed_targets` is now the single definition, called by
`adjudicate.rs` at its enforcement site **and** by the loop to decide whether to announce. The
journal still records every move; only the screen is gated. Three tests, one asserting the
agreement across all four trust classes rather than either half.

### `web` ships, fetch-only. ADR-031, ADR-032.

**`marlowe-net` is a new crate depending on nothing of Marlowe's** â€” `rustls` + vendored
`webpki-roots`, blocking, no async runtime. `marlowe-provider` still has no TLS, so ADR-028's
"the default path reaches no network" stays a property rather than a comment.

**Redirects are not followed, and ADR-031 Â§2.5 was amended during implementation to say so.** The
first draft said *"followed, re-adjudicated per hop"*; writing the executor showed that means **a
second implementation of the egress check**, in a networking call site, checked against a policy
the executor had to be handed. The shipped shape is smaller and stronger: the `Location` comes back
as a result and following it needs a fresh `web` call through the real adjudicator. The cost is
real â€” after reading a page the latch blocks composed targets, so a redirect is usually a dead end.
That is the trifecta break, not a defect.

**The fetch primitive returns bytes + content-type and does not parse.** Extraction is a separate
module and a separate session, deliberately: an extractor that panics must not take the egress path
with it.

### The blast radius was dropping targets it could not stringify

`blast_radius` built the scope line with `as_text`, which returns `None` for every variant but
`Text`. **A declared Target that was a number vanished from the line a human approves against** â€”
`run.budget_micros_usd` is `Amount`, so Â§B9's required blast radius had never once shown a spend
ceiling. `ArgValue::render` is total with no wildcard, so a new variant is a compile error here
rather than an omission in an approval prompt.

This was done **before** `web` could ship, not beside it: ADR-002 lets `web` be `Inert` only because
egress allowlisting covers it, approve-any-host weakens that, and per-call approval replaces it only
if the prompt shows the host.

### Persona v2 â€” adopted from a prior harness, translated. ADR-033.

`persona/v2.md` ships. **Cut, because they described tools that do not exist:** `<vision>` (which
instructed the model to *"never say I can't see"*), `<redteam_routing>`, `<git>`, the search half of
`<knowledge_and_search>`, most of `<memory_and_continuity>`.

**The dangerous one was not a cut.** `<tool_use>`'s first rule was *"emit multiple independent tool
calls in a single response"*. `parse_step` does `calls.first()` and **discards the rest silently** â€”
worse than a missing tool, which at least returns a readable error. v2 says one call per turn.

**~3,544 tokens against v1's ~409 â€” 11.5% of the effective window**, permanently, in the
non-trimmable stable tier. Â§C0's *"roughly twenty lines â€¦ negligible"* is amended.

**Â§C7's probe set does not exist and never has**, for v1 or v2. Adoption rests on "it performed well
in a prior harness", which is a prior about a different system. Â§C7 amended to say so.

### Still open

- ~~**PARALLEL TOOL CALLS**~~ â€” **DONE.** `ModelStep::ToolCall` carries `Vec<ToolInvocation>`; the
  loop executes every call; each result is attributed by a harness-assigned id reaching
  `/api/chat` as `tool_calls[].id` and `tool_call_id`. `persona/v2.md` reverted in the same commit.
  Three states, in order, and the middle one is worth remembering: **silent drop â†’ loud refusal â†’
  real support.** Refusing to run a third of a plan beats running a third and reporting nothing.
  **Taint is computed once per batch and that is correct rather than cheap** â€” every call was
  composed before any sibling's result existed, so a per-call recomputation would block a call on
  content its author never saw. The latch is not holed by ordering: the batch's results latch the
  floor before the *next* adjudication. Both halves asserted in one test, because either alone
  passes on a broken build in the opposite direction.
  **One judgement call to review:** a control tool (`done`/`ask`/`run`) inside a multi-call batch
  takes precedence and returns its control step, since it ends or reshapes the run. Not a silent
  drop, but a semantic choice nobody ratified.
- **`interactive()` is still `EgressPolicy::DenyAll`**, so `web` has an executor and is not exposed.
  ADR-032 Â§3.1 (`AllowApproved`) is **PROPOSED, not approved** â€” it needs the human, and it needs an
  interactive approval surface the daemon does not have (`DenyUnattended` returns false, which is
  why `bash` reads `declined` unconditionally).
- **Search is RESOLVED and needs no credential: self-hosted SearXNG. ADR-035.** The keyed-API note
  that was here is superseded â€” the keyed landscape is *contracting* (Bing API deprecated Aug 2025,
  Google CSE closed to new customers and discontinued 1 Jan 2027, Brave requires a card), so a keyed
  backend builds on shrinking supply and fails K6 by construction.
  **The registry has no credential concept at all** (ADR-036 Â§2) â€” not a default-off flag, no field:
  a channel that needs a key cannot be *described*, so it cannot be registered. Stronger than a
  load-time error, because a field that exists is a field a future session fills in.
  `web`'s description still promises search and is corrected when search lands.
- **DESIGN ONLY, NOT BUILT â€” the research stack. ADR-035, ADR-036, ADR-037. M3 owns it and durable
  runs are its precondition.** Brief Â§10 and ADR-008 are amended. The three things to read before
  proposing anything here: **deduplication is over identity, not route** (a Source has N routes; a
  derived work is an *edge*, never a merge; corroboration counts **independent roots**);
  **`Unresolved` counts as one and displays as two**, because under-merging manufactures
  corroboration invisibly while over-merging is visible; and **an identifier self-asserted by
  fetched content is a claim, not an identity** (ADR-036 Â§5) â€” otherwise a page printing a real DOI
  merges into that paper and inherits its standing.
- **A SECURITY PRINCIPLE GENERALIZED FOR THE FIRST TIME, and the generalization is unexplored.**
  ADR-036 Â§5. ADR-023's (action, target) split has always been about tool arguments â€” a path, a
  host, a command. Deduplication has **no tool, no argument and no permission check anywhere near
  it**, and the rule holds anyway, because the property was never about tools: it is about *who
  chose the thing that determines an outcome*. Note that the taint latch cannot help here â€” every
  route is `UntrustedContent`, so the floor is already at the bottom and stops discriminating.
  **Named as a generalization rather than a fifth instance, and the same shape is unexamined in at
  least four places**: ranking inputs, cache keys, memory derivation lineage, and consolidation
  merge decisions.
- **Two ADRs carry INDICATIVE figures that must not become load-bearing.** ADR-035's keyed-API
  dates and ADR-037's Gemini/Anthropic token costs came from the human's research and **were not
  re-verified by either party**. Both are marked in place. They are order-of-magnitude calibration;
  no threshold, budget default or acceptance criterion derives from them, and a session budgeting
  against them measures first.
- **`drop(cwd)` in `marlowe-exec`'s `bash` does nothing** â€” `Option<&ScopedPath>` is `Copy`, so the
  line that claims to hold the handle until after the spawn is decorative. The handle is genuinely
  held (by the `Adjudication`), so this is a false comment rather than a broken guard. Compiler
  warns.
- **The duplicate `ADR-028` in DECISIONS.md is flagged, not renumbered** â€” citations across
  STATE.md, CLAUDE.md and eight RESULT.md files would break.
- **Â§C1's namesake conflict is unresolved**: Chandler's detective (restraint) vs Christopher
  Marlowe the poet (transgression). v2 names neither; Â§C8 forbids backstory.

### One Â§13 row is now LIVE-verified rather than pipe-verified

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
`LiveSession::finish_connect` applies them. Â§2.14 still holds: the client re-projects what the
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
- **The daemon serves one request at a time**, and **this entry described the symptom wrongly**,
  which cost M2 D a round trip. A client reopening mid-turn does **not** show the conversation up to
  the last completed turn: it shows **nothing** and accepts **no input**, because
  `LiveSession::finish_connect` does three blocking socket round-trips â€” `status`, `Runs`, `Replay` â€”
  on the UI thread with no timeout, before any interactive frame is drawn. **A busy daemon is
  therefore indistinguishable from a dead one.** `an_absent_daemon_degrades_visiblyâ€¦` covers the
  daemon being *absent*, where connect is refused fast; nobody covered it being *present and busy*.
  Fix (Session E): a read timeout, a paintable `connecting` state, and `status` as the only
  prerequisite of the first frame. Live attach still needs concurrency in the accept loop.

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


## M2 C2d â€” `marlowe --tui` drives the real engine. ADR-030. `9f51476`.

**494 cargo tests (from 457), `eval/` untouched at 72, `repro` byte-identical to the pre-change
baseline, conformance unchanged.** Two commits: `5fbd513` (view models) and `9f51476` (the live
TUI plus the Notice vocabulary).

**Launch it:** the desktop shortcut `Marlowe.lnk` â†’ `wt -p "Marlowe"` â†’ `marlowe --tui --ground`.
Recreate with `marlowe --launch` (writes the Windows Terminal profile) plus the `WScript.Shell`
snippet in this session's log. **M1's claim that a `Marlowe.lnk` already existed was false** â€”
there was no shortcut and no code for one, the same shape as the "hooks are the real boundary"
claim CLAUDE.md records. It exists now.

> ### THE MOST IMPORTANT FINDING: A GREEN PROBE BESIDE A HUNG PRODUCT
> The auto-spawned daemon **inherited the parent's console**. `--timing-probe` returned healthy in
> **56 ms** while every shell pipeline that launched it hung **forever** â€” the process that
> finished could not say so, because a child holding the console open means the pipe never closes.
>
> **Nulling stdio is not enough; the console handle is the thing.** Fixed with `DETACHED_PROCESS |
> CREATE_NEW_PROCESS_GROUP`. It would have fired on the **first click of the shortcut**.
>
> **Fourth seam this project has found by running rather than testing** â€” scroll and `NO_COLOR`
> (M1), `done` routing (M2 C2c), the hotkey collisions and this (C2d). The standing rule of one
> real end-to-end run per milestone is now four for four, and every one of them produced a defect
> no unit test could see.

**The other run-only finding, same session.** The daemon projection gave the Schedule pane hotkey
`'s'` â€” the Session region's key â€” and numbered run items with digits that collide with Â§B7's tab
digits. `KeyRegistry::build` refused to start, correctly. **No test had ever projected a daemon
view into a key registry**, so both were invisible. Both fixed; `project.rs`'s `key_tests` now
crosses that seam.

### Process isolation is a standing constraint, and `--daemon-port` is the mechanism

**Two sessions on one machine share `DEFAULT_DAEMON_PORT` â€” the shared-resource hazard in a fifth
form.** The reflex when a daemon is in the way is to stop it, and that takes the other session's
daemon with it. This session did exactly that once, with a blanket `Stop-Process`, before the
constraint was named.

**Anything needing a clean daemon uses a scratch port**: `marlowe --tui --daemon-port 11477` and
`marlowe --serve --daemon-port 11477`. Auto-spawn was verified that way â€” the other session's
daemon on 11435 was never touched, and the check that proves it is a listener count on both ports
before and after.

**A daemon restart is lossless when VERIFIED, not by default.** Before stopping one, ask it:
`marlowe --status` reports `runs N live`. A restart costs exactly the in-flight runs â€” there is no
WAL and no checkpoint resume (M3/K5) â€” so **zero live runs makes a restart provably free, and any
other number makes it a decision.** Checking first is the standing procedure; assuming is how a
session loses someone's work.

### What is live on `--tui`, per region

**Nothing is stub-fed on the live path.** `--tui --scripted` is the only route to M1's stub, and
the active producer is announced at startup. A partially connected TUI that *looks* connected is
the seam problem, so this is stated per region rather than in aggregate.

| Region | Live path |
|---|---|
| Status band | **Live** â€” `StatusReport`: workspace, model, disclosure, `degraded`, `rerank_provider`, `live_runs` |
| Conversation | **Live** â€” user turns, `Event::Text` â†’ `Speech::Model`, tool lines from `Event::Tool` |
| Runs pane | **Live** â€” `Request::Runs` on connect, then `Event::Run` |
| Control strip | **Live, single-valued** â€” one model, one workspace; anything else is a named refusal |
| Ambient Â· pager | **Live, zero until a turn completes** â€” both from `Event::Done`. Zero is the truth |
| Meter | **Frozen** â€” `MeterSource::None`; no voice pipeline, no token-rate telemetry, so it reports nothing rather than a synthetic envelope (Â§B12) |
| Schedule Â· Sessions Â· Skills Â· Trust Â· Status panes | **Not built**, each saying so with its milestone |
| Approvals | **Refused by name** â€” see below |
| Interrupt Â· undo Â· compact Â· `/state` | **Refused by name**, rendered as a persistent client line |

**Measured:** first frame **7 ms** connected, **52 ms** degraded, **134 ms** including an
auto-spawn â€” all under K4's 150 ms.

**The one real protocol dependency, and Session E inherits it by name.** `Event::Approval` carries
`{decision, verb, scope, reversible}` â€” **no novelty reason and no ceiling.** Â§B9 requires both,
and neither can be defaulted: a defaulted ceiling is a claim about promotion logic nobody made. The
live path refuses and **names the missing fields** rather than showing a fabricated blast radius.

### ADR-030 â€” harness speech is a closed vocabulary

`Entry::Said` carries `Speech::{Model(String), Harness(Notice)}`. Six `Notice` variants; **no field
may be a `String`** (an `Echo` newtype carries text the user typed, quoted, never reworded).
`/help` and command errors are **surface-constructed on purpose** â€” routing them through a producer
would make `/help` a socket round-trip, and a help command that waits is worse than one in the
wrong voice. Nothing in `Notice` can reach a model.

**Â§B9's `BlastRadius` is typed the same way.** M1's overlay was **scaffolding**: the renderer was
already clean, but nothing could *compute* its three strings. `novelty` and `ceiling` are required
fields, not `Option`s.

> **A control that only catches what the compiler already catches is testing nothing.** Verifying
> the no-`String` guard took three attempts: two mutations failed to *compile*, so the control
> never ran and the guard merely looked silent. The scanner's whole value is the case that
> compiles â€” a new variant carrying a `String`. **Ask of any control: would this still fail if the
> guard were deleted?** If it would fail earlier, it is measuring the compiler. ADR-030 Â§5a.

**Not covered by the hook, measured not assumed (2026-08-09):** `crates/marlowe-permission/src/decision.rs`
defines `BlastRadius` and `Outcome::NeedsApproval` â€” the approval layer's decision surface â€” and
**returns no decision from `protect-boundaries.py`.** `adjudicate.rs` fires correctly; this file
does not. Adding it is a Â§13 change and needs the human's call.

---

## M2 C2d â€” the view models are promoted, and Â§2.14 is structural rather than asserted

**473 cargo tests (from 457), `eval/` untouched at 72, `repro` hash byte-identical to the
pre-change baseline (`e796c12eâ€¦`), conformance unchanged.** Branch `master`.

**`marlowe-view` is a new crate depending on nothing.** `SessionView`, `Intent`, `Produce`,
`MeterSource`, and the M1 view models. `marlowe-surface` depends on it and on **no producer** â€”
`marlowe-stub` is a dev-dependency, so `src/` cannot name one. That is the acceptance, it is
checked by `tests/c2d_boundary.rs`, and a **negative control** confirms it is not decorative:
putting `marlowe-stub` back into `[dependencies]` fails the test by name.

**Two producers now exist**, which is what makes this a promotion rather than a rename: the
scripted `marlowe-stub::Session`, and `marlowe-daemon::project` mapping `StatusReport`/`Event`
onto the same view without the view being bent to fit.

> ### THE HEADER CLAIM WAS FALSE, AND HAD BEEN SINCE M1
> Both `marlowe-surface/src/lib.rs` and `marlowe-stub/src/model.rs` said the dependency graph made
> Â§2.14 structural â€” *"a surface that cannot fabricate state is a surface that provably holds no
> state the daemon lacks."* **`App` owned a `marlowe_stub::Session` mutably and pushed into its
> transcript.** In-process against a stub that is invisible; against a daemon on a socket it is a
> surface inventing history. **Eleven sites, listed below.** The claim is now true.

**The one that would have been worst in production:** arrow keys inside an open dropdown assigned
`Picker::selected` directly, so **arrowing past `act` in the Autonomy list granted `act` in
passing**, and `Esc` left it there. Addendum A Â§A8 makes self-granted promotion structurally
impossible â€” and the surface was doing it on a keystroke that was never a choice. The highlight is
now `App::picker_cursor` and `Enter` is what asks.

**`App::on_key` no longer takes a clock, and that is a result rather than a tidy-up.** Every branch
used to end in a mutation, and a mutation needs a timestamp; they now end in an `Intent` and the
producer stamps its own time, because the producer is the thing with a journal. Six dead `now_ms`
parameters were removed rather than silenced.

**`MeterSource` is a new distinction the M1 shape could not express.** `BASELINE` means *live and
flat*; `MeterSource::None` means *nothing is measuring*. The daemon has no voice pipeline and no
token-rate telemetry, so it reports `None` and the meter freezes â€” it does **not** report
`BASELINE`, which would render as a live silent session, a claim made by a component that cannot
know it. Â§B12 forbids decorative motion and a synthetic envelope on the daemon path would be that.

**Optimistic state is allowed and never becomes history.** `PendingLine` renders what the user
typed before acknowledgement, in its own weight, with **no transition into `Entry`** â€” there is no
`confirm()`. It is retired only by the producer's transcript containing it. If the producer never
acknowledges, **it stays visibly pending indefinitely**, which is the truth.

### Two guards fired or were closed during this work

1. **`b13_memory_surface.rs`'s Â§B1 guard names `turn.rs` by path, and I moved it.** It failed
   loudly because it reads with `.expect`. The same check written with `unwrap_or_default()` would
   have scanned nothing, found no memory variants, and passed forever.
2. **`determinism_guard.rs`'s `FENCES` had no staleness check** â€” a fence naming a deleted file
   left a silent exemption ready to excuse the next file to take that name. `protect-boundaries.py`
   grew `--self-check` for this after Session B; this guard never did. **Now closed**, verified by
   a control (a bogus fence entry fails by name). A separate `NAMES_BUT_DOES_NOT_READ` list keeps
   *"legitimately reads a clock"* and *"mentions the word"* from being conflated.

**LATENT, NOT FIXED â€” outside C2d, flagged rather than touched.** `marlowe-loop/tests/hp10_budgets.rs:37`:
`let Ok(entries) = read_dir(dir) else { return out };` returns **empty** on a missing directory.
It is saved only because the caller asserts `found.len() == 1`. Relax that to `<= 1` â€” which reads
entirely natural â€” and the driving-loop guard scans a directory that is not there and passes forever.

### Deferred, and named rather than improvised

**`Outcome::Tab(tab, said)` still carries Marlowe-voiced prose hardcoded in the surface's command
registry** â€” *"Two running. The deep dive is at $1.20 of its $3 ceiling."* C2d stopped it
masquerading as transcript (it renders as a `ClientLine` now), which is **more honest about
authorship but leaves persona-voiced text in the client channel**. Fixing it properly needs a
producer-side command handler, which is **C3**. It is not an intent nobody handles â€” it renders
today â€” but it is not right either.

`/help`, `/keys` and `/doctor` are **not** part of that debt: they describe the *client*, so the
client authoring them is correct. They were only ever wrong in being attributed to Marlowe.

**Also deferred, unchanged:** `TurnEvent` still exists twice (`marlowe-loop` and `marlowe-view`),
and the two `BlastRadius` shapes are still unreconciled â€” both are **Session E** per the entry
below, and C2d deliberately did not absorb them. `marlowe --tui` still drives the scripted
producer; pointing it at the daemon is Session E's "the TUI against the real loop".

### The 15.2 GiB of stale `target/`, and the latency session

**The repo moved out of OneDrive** â€” from `C:\Users\matth\OneDrive\Desktop\Projects\Marlowe_Harness`
to `C:\Users\matth\Projects\Marlowe_Harness` â€” and `target/` still held test binaries compiled at
the old path, with `CARGO_MANIFEST_DIR` baked in. Under `--workspace` feature unification cargo
reused three of them and `hp10_budgets` failed against a path that no longer exists; `-p marlowe-loop`
recompiled and passed. **15.2 GiB removed by `cargo clean --profile dev`.**

**This is a candidate explanation for Session L's unexplained write times** â€” the 542 ms stall
inside one timed span, and the cold p50 drift 208.4 â†’ 267.0 ms on the same binary in the same
configuration. Session L attributed those to OneDrive's delete-share locks on fresh binaries, which
was a reasonable read at the time and is now untestable on this machine. **It is a hypothesis, not
a finding: nothing has been re-measured, and Session L's numbers are still scoped to a machine
state that no longer exists.** Re-measuring the CPU path here would need a fresh control run, not a
citation.

---

## M0c Session L â€” retrieval latency. GPU ships (ADR-029). R@1 UNMOVED at 0.6725.

**`runs/session-l/RESULT.md`. Read `METHOD.md` before trusting any number in it.**

| path | total p50 | total p95 | budget 300 ms |
|---|---|---|---|
| **CPU sequential 1t** â€” ships where no GPU exists | 199.6 | ~213 | 87 ms headroom |
| **CUDA batched** â€” ships where one does | **10.0** | **14.7** | 285 ms headroom |

**Two changes ship.** The **lexical rewrite** (both paths, byte-identical, `score_all` stage
14.76 â†’ 3.07 ms cold, âˆ’79%) and the **GPU path** (ADR-029). Quality is unmoved: CPU dumps
byte-identical to Session K; GPU **ranking-identical** â€” R@1 0.6725, R@5 0.8865, R@10 0.9039.

**The profile, which is the thing to inherit:** on CPU the rerank is **90.49% of P95**. Everything
else combined is under 10%. Any latency work that is not about the rerank is rounding.

**Measured and REJECTED, all ranking-identical, all cost findings:** batching on CPU (+8.8 ms),
threading at 16 intra-op threads (**+158.9 ms** â€” the model is too small to amortize ORT's per-op
sync), batching at 16t (better than sequential-16t, still worse than 1t). **`SHIPPED_THREADS = 1`
is now measured rather than assumed.**

**Batching is a property of the HARDWARE and the two providers measured opposite** â€” CPU sequential,
CUDA batched. `RerankProvider::default_batching()` derives it; a single global default would be
wrong for one provider whichever value it took.

> **ADR-003 is AMENDED.** The hot index is a **capacity** requirement, not a latency one: the
> candidate scan is the only **O(store)** stage and costs **3.83 ms / 1.78%** at 113k entries. The
> spike's 94.9 â†’ 16.2 ms measured a *physical storage index under concurrent writes*, not the
> in-memory iteration retrieval does â€” a factor of ~25 apart. **On the GPU path it is 19.6% and
> moves back toward a latency claim.** Third change of classification on measurement; re-derive, do
> not assume.

**OPEN for M2 (in ADR-029, so it is inherited rather than re-derived):** the active provider is
**announced**, never silently chosen â€” an unannounced fallback is indistinguishable from the failure
mode it resembles. Voice on a CPU-only machine states its budget consumption **at enable time**
(retrieval is ~27% of Â§9's 800 ms). **`rerank_provider` on the profile row is THE field the band
reads â€” do not build a second source.**

**OPEN GAP:** `ort` exposes no node enumeration, so the shipped binary cannot re-verify that 13.6%
of CUDA nodes run on CPU (all shape/index ops, no matmuls). Verified once, in Python, at ORT 1.24.2.
**Re-run `tools/session_l_gpu_recovery.py` after any graph, model or ORT change.**

> ### THE BUDGET IS TIGHTER THAN THE CLEAN NUMBERS SUGGEST
> Machine drift on this box moved the **same binary in the same configuration** across cold p50
> **208.4 â†’ 267.0 ms** and warm p50 **199.6 â†’ 267.0**. One cell breached the 300 ms budget at
> **329 ms with no code change at all**. **Budget the CPU path against ~60 ms of usable headroom,
> not 87.** The repo lives under OneDrive, which holds delete-share locks on fresh binaries and is
> the likeliest cause of a 542 ms stall inside one timed span.

**Seven instrument defects in one session, every one caught by a control and none reaching a
published number** â€” see `RESULT.md` Â§5. The two worth carrying: a concurrent `cargo build`
inflating every absolute ~10% while the table reconciled perfectly, and `get_providers()` reporting
*registered* providers rather than *where nodes ran*. **The rate is the argument for controls that
feel redundant.**

**445 cargo tests** (from 421), `eval/` untouched at **72**. *(473 as of C2d.)*

---

**Updated:** 2026-08-08 â€” **M1 is CLOSED (`ed25914`). Current milestone: M2**, branch `m2-loop`.
Session A shipped the spine (loop, tools, permissions, runs, assembler); **Session B shipped path
scoping whole** â€” traversal suite and handle discipline together, ADR-027, **verified on Windows AND
Linux**. **414 cargo tests on Windows, 62 on Linux, `eval/` untouched at 72.** Next is Session C.

**M0b is COMPLETE and SHIPPED.** The Session J fine-tune is on the scored path; held-out R@1
**0.5764 â†’ 0.6725**. K1 is amended and pinned. The precision/coverage curve is published and an
operating point is declared.

**M0c Session A (branch `retrieval-m0c`) ran head separability to a conclusion and shipped nothing.
R@1 stays 0.6725.** Both named candidates are measured and closed; K1's 10%-coverage interval is
retired as arithmetically unreachable. See "M0c Session A" below and `runs/session-m0c/RESULT.md`
before proposing any retrieval work.

> ### R@1 COUNTS THE SUPERSEDED FACT AS A HIT. Every R@1 in this project is inflated.
> LongMemEval marks **both** the stale and the current turn `has_answer`, so returning the outdated
> value scores as correct. Held-out **0.6725 â†’ 0.6288** counting only the current value; on
> **knowledge-update 0.7222 â†’ 0.4444**, where **10 of 26 apparent hits (38.5%) are the stale fact**
> (fit: 15 of 26, 57.7%). **Report `R@1_current` beside R@1 from now on.**
> `docs/design/HARM-WEIGHTED-PRECISION.md`.

## The shipped configuration

`--reranking models/ms-marco-MiniLM-L-2-v2-ft-session-j` â€” **f32**, seq 256, batch 1, depth 10,
sha256 `9c222dacâ€¦`. ADR-018 (the measurement), **ADR-020** (the shipping decision).
`runs/session-k/RESULT.md`.

| held-out, n=229, from the BINARY | Session H | **shipped** |
|---|---|---|
| **R@1** | 0.5764 | **0.6725** |
| R@5 | 0.8428 | **0.8865** |
| R@10 | 0.9039 | 0.9039 |
| **input recall** | 0.9039 | **0.9039** |
| **conditional accuracy** | 0.6377 | **0.7440** |
| retrieval P95 warm, full split | 149 ms | **211 ms** |
| retrieval P95 **cache-cold**, 40-case subset | â€” | **238 ms** |
| tokens over budget | 0 | **0** |

**`R@1 = input_recall Ã— conditional_accuracy` factors exactly and input recall did not move by one
case.** A cross-encoder changes the order within the slate, not what is in it. The whole gain is
conditional accuracy, **+0.1063**. Lexical (0.5415), dense (0.4454), `fitted_gate` (0.5371) and the
either-cue oracle (0.6463) are **bit-identical** to Session H â€” that is the control.

**Two deltas, and they answer different questions.** **+0.0699** is fine-tuned vs **un-tuned f32** â€”
the contrast that isolates domain adaptation, with the test behind it (discordant 38, `p = 0.0139`).
**+0.0961** is what a user gets, because what was replaced was **int8**. Never quote +0.0961 as the
fine-tuning effect.

**Budget margin is now thin: 238/300 cold leaves 62 ms.** K1's precision numbers are *defined* at
these budgets â€” a violation makes them void, not caveated.

## READ THIS FIRST â€” three things that must not be re-derived wrong

**0. A CAPABILITY REPORT IS NOT AN EMISSION REPORT.** This is the standing lesson, and it was the
**eleventh** instance of the pattern this file has recorded â€” the first where *the harness disabled
the very thing it was verifying*. **The twelfth is in Standing checks below, and it is the first the
family caught prospectively**: `Deserialize` routed around a validating constructor, closed before
it existed rather than found after it shipped.

M1's frame rendered entirely achromatic in Windows Terminal for four rounds of screenshots while the
startup record printed `tier=truecolor`. Nothing was wrong with the detection: the terminal really
was truecolor. `NO_COLOR=1` was set in the environment of the shell that launched it, crossterm
honours `NO_COLOR` **at the formatter level** â€” `SetForegroundColor(..)` emits `ESC[m`, an empty SGR
which is a full reset â€” and every cell was therefore painted in the terminal's default foreground.
The layout, the styles, the region contract and the colour tier were all correct simultaneously.

**The probe was answering the wrong question.** It measured what the terminal *can carry* and
reported it where the reader would understand *what will be emitted*. Those two are different
quantities and nothing in the system compared them, so they disagreed in silence â€” the same shape as
the `--reranking` default, the `--embedder-model` default, and the eight before them.

The fix is `Theme::emission_report()`, which states what will actually be emitted and names the
override; it has a regression test. **The fix is not to stop honouring `NO_COLOR`** â€” that is a
legitimate user preference, and overriding it silently would be the identical sin inverted.

Generalised, for the next time: **when a component reports a capability, ask what it would print if
the capability were present but suppressed downstream.** If the answer is "the same thing", the
report is decorative. Diagnosing this cost four rounds and was only closed by writing three probes
that emitted known bytes and measuring the resulting pixels â€” *the screenshot was right and the
record was wrong* the entire time.

## READ THIS FIRST â€” two things that must not be re-derived wrong

**1. The 0.3739 ceiling never measured retrieval quality.** ADR-016. **A perfect retrieval system
scores 0.8483 on the shipped gate** against a 0.95 threshold: `fit_isotonic`'s smallest expressible
block is 435 rows spanning **100% of queries**, and the gate has no vocabulary for confident
subsets. Nine sessions read the gap as closable by better retrieval. It never was. **This
invalidates no retrieval measurement** â€” R@1, R@5, R@10, conditional accuracy, the oracle and every
closed mechanism were measured against gold turns with the gate uninvolved. `THRESHOLD = 0.95` is
untouched.

**2. R@1 and the operating point are different questions, and this is now measured twice.**
+0.0961 R@1 bought **nothing** at the operating point â€” the head got slightly *worse* while the body
got clearly better. See below.

## K1 â€” amended 2026-08-08, and the curve is published

Pinned in `ROADMAP.md` â†’ "K1 â€” amended 2026-08-08" and brief **Â§5.7.1**. Argument: **ADR-019**.
Proposal of record kept and marked ADOPTED at `docs/requirements/proposed-K1-amendment.md`.

**The threshold is NOT moved.** The criterion's *shape* changed from a single point to a published
curve, and a **new** kill condition was added: **a flat curve â€” precision at 10% coverage not
materially above precision at 100% â€” is project-level.** Condition 3 is **binding**: a configuration
that injects at low precision to raise coverage fails outright.

### `docs/design/PRECISION-COVERAGE.md` â€” the published curve

> **DECLARED OPERATING POINT: coverage 10.0%, precision 0.9130 (21/23), CI [0.7196, 0.9893],
> margin â‰¥ 1.1651.** State this, with its interval, wherever the capability is described.

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

**Guarantee â‰  precision, always reported apart.** Conformal at Î± = 0.05: Ï„ = 1.4639, measured
`P(inject | wrong)` = **0.0133** against the **0.05** bound, precision 0.9333 (14/15) at 6.55%
coverage. The bound covers the false-injection rate among wrong queries; K1 asks for
`P(correct | injected)`, a selective risk it does not cover. **Global Ï„ only** â€” largest wrong-query
calibration set is 12 against a floor of 40.

## Superseded â€” M2 C2d (done; see the top of this file)

**`marlowe --tui` still drives M1's scripted stub.** `App::new(session: marlowe_stub::Session)` â€”
the whole surface is built on the stub's view models (`StatusBand`, `ControlStrip`, `Entry`,
`Pager`, `Tab`, `Item`, `Ambient`, `Picker`). `marlowe-stub/src/model.rs` says in its own header
that **M2 must pin them**, and this is that work: move them to a real crate the **daemon**
produces, and point `marlowe-surface` at it.

**Treat M1's 87 tests as the acceptance, not as an obstacle** (the human's direction). If one
breaks, a view model changed shape and that is the thing to look at â€” **a green suite after a
refactor of that size is more suspicious than a few honest failures.**

**What is already done and must not be re-derived:** `marlowe --ask` works end to end against a
real model through the real loop and the real wall. The daemon protocol already carries everything
Â§B5's band needs (`StatusReport`: workspace, model disclosure with its denominator, `degraded` with
its remedy, `rerank_provider`, `live_runs`). The TUI does not need a new data source â€” it needs to
read that one instead of the stub.

### What M3 inherits from M2, stated precisely

| | Status |
|---|---|
| **Invariant 6, first half** â€” a run outlives the **client** | **Done.** `tests/split.rs` asks, disconnects, and a different client still sees the run |
| **Invariant 6, second half** â€” a run outlives the **daemon** | **NOT claimed.** No WAL, no checkpoint resume. A daemon restart loses in-flight runs |
| `RunControl::resume` | **Refuses by name** â€” `ResumeError::NotDurable`, naming M3 and K5. It has never silently succeeded |
| `Run`, `CapabilityProfile`, `Budget`, `OrphanPolicy` | Implemented in full. `OrphanPolicy` is **recorded in the `RunSpawned` payload from the first spawn** and unused, which is what makes M3 an extension rather than a migration |
| Spawn lifecycle | Ephemeral: the parent blocks, the child returns, the child dies with the parent. The recursion is `Engine::run` re-entered; M3 replaces it with a scheduler and the data is already shaped for one |
| Concurrency | **One connection at a time.** A second client is an M3 concern and pretending to handle it now would be a concurrency story nobody tested |

## Superseded â€” M2 Session C2: the Ollama adapter

**ADR-028 (the human's decision): Marlowe runs against a LOCAL OLLAMA ENDPOINT first.** Hosted
providers register later. This dissolves the K6 tension rather than trading against it â€” an env
var, a first-run prompt and a bundled key all put *something* in front of the first run, and K6
measures whether that something is there, not whether it is small.

**Build the provider adapter; do NOT build the credential broker.** Ollama needs the first and none
of the second. Three requirements from ADR-028: degrade honestly when Ollama is absent (invariant 4
â€” a declared value on the run, surfaced in the status band, naming the remedy); record the
capability difference, tool-call reliability especially, so a debugging session can tell a harness
bug from a 7B model; and keep ADR-008's routing as a table over local models whose shape survives
hosted models arriving. `CapabilityProfile::model_route` already names a task role, never a model.

**Still owed from C1: the four executors** (`read`, `edit`, `find`, `bash`). The scope work they
need is done â€” see below. `bash`'s `cwd` needs its own assertion: `CreateProcess` takes a cwd
*string*, not a handle, so Windows relies on the walk's pinning a **second** time. That argument
must earn a test rather than inherit the walk's.

### M2 Session C1 â€” 2026-08-08. The platform gate and the write path.

**421 cargo tests on Windows, 65 on Linux under `MARLOWE_TRAVERSAL_STRICT=1`.**

- **`WorkspaceScope::new()` refuses at construction on an unverified platform.**
  `VERIFIED_PLATFORMS = ["windows", "linux"]` â€” what has been *executed*, not what compiles.
  **macOS is deliberately absent**: case-insensitive and NFD-normalizing, which is exactly where
  `glob`'s matching and `request`'s NFC handling would diverge.
- **`ParamType::WritePath`, declared per parameter.** `edit`'s `path` may create; `bash`'s `cwd` and
  `read`/`find`'s `path` must exist. Deriving access from consequence level would make two
  different requirements take their behaviour from the same number.
- **`Access` threaded through the walk.** It applies to the **final component only** â€” every
  directory on the way is opened read-only and refused if it is a reparse point, whatever the
  caller intends at the end. Creation happens *inside the already-verified parent*, which is why it
  is safe: the parent is still held open (pinned on Windows, an `openat` descriptor on POSIX).
- **A create positive control**, because a scope that only opened existing files would pass every
  other test in the suite and make `edit` impossible. It also asserts the negatives: a refused
  create must not create, and a create through a junction must not land outside.

### Superseded â€” M2 Session C's original framing

**Scope: `ROADMAP.md` Â§M2.** Sessions A and B are done. C builds the executors behind
`driver::ToolHost` (and they must take the handle from `Adjudication::handles`, **never re-open a
path** â€” that is the one way to reopen the race ADR-027 closed), `SKILL.md` loading with progressive
disclosure, `find_skill` semantic discovery, MCP as tool transport, and a provider client honouring
`CallLimits::max_output_tokens` as a hard cap.

**Before writing an executor, read ADR-027's last section.** The wall is the handle walk; an
executor that calls `File::open(scoped.resolved())` has undone it, and no test in the traversal
suite would notice, because the suite tests the checker and the race would be in the caller.

### M2 Session B â€” 2026-08-08. Path scoping, whole. ADR-027.

**412 cargo tests (from 375), `eval/` untouched at 72.** `WorkspaceScope` replaces the refusal;
`Unavailable` is retained for profiles that must provably not touch the filesystem.

**Three parts, and only the third contains anything:** `request` refuses ambiguous spellings before
any syscall, `glob` matches the declaration, `walk` opens without ever letting a string be resolved
twice. POSIX: `openat` + `O_NOFOLLOW` per component. Windows: every directory pinned open with a
share mode **excluding `FILE_SHARE_DELETE`** (so the prefix cannot be renamed out from under the
walk), plus `FILE_FLAG_OPEN_REPARSE_POINT` with refusal on `FILE_ATTRIBUTE_REPARSE_POINT`, plus
root identity verified before and after.

**The TOCTOU test races, and proves it races.** `tests/toctou.rs` carries a deliberately vulnerable
`naive_check_then_open` and **asserts that it escapes** â€” returning out-of-scope content under the
same interleaving. That is the half that makes the other half mean anything. The interleaving is
deterministic via a `WalkObserver` called at the exact vulnerable instant (`()` in production), not
a thread racing and hoping. On Windows the test also asserts the swap failed *as a sharing
violation*, so a swap that failed because `mklink` was missing cannot leave it green.

**BOTH GAPS ARE CLOSED, and the closing condition is now a standing requirement.**

They were real and blocking: the symlink class could not run on Windows (os error 1314, privilege
not held), and the POSIX walk had never been executed â€” ADR-002's inversion landing on the security
boundary.

**Closed 2026-08-08 on WSL2 (Kali, ext4 `/tmp`, native symlinks), `MARLOWE_TRAVERSAL_STRICT=1`, all
62 tests green and the coverage manifest reporting `RAN` for all eleven classes including symlink
escape.** The POSIX `openat`/`O_NOFOLLOW` walk executed for the first time there, and
`the_naive_implementation_escapes_which_is_what_makes_this_a_race` passed on Linux too â€” so the race
window is demonstrably real on Linux and `O_NOFOLLOW` demonstrably closes it.

**The standing requirement, because a one-time run is not a guarantee:** the suite runs on **both**
platforms with `MARLOWE_TRAVERSAL_STRICT=1` before path scoping is called verified after any change
to `scope/`. Windows alone leaves the symlink class unrunnable; Linux alone never executes the
pinning. `.wsl-probe.sh` is deliberately **not** kept â€” a script nobody reads is not a procedure;
the command is two lines in ADR-027.

**A guard whose subject moved is no guard.** Splitting `scope.rs` into `scope/` made the brief Â§13
hook name a file that no longer existed â€” path scoping was silently unguarded and nothing said so.
The entry is now a directory prefix, the hook grew `--self-check`, and
`marlowe-permission/tests/boundary_hook.rs` fails the build on a stale entry. Verified by a negative
control: renaming a guarded file makes it fail by name.

**Positive controls are in the suite deliberately.** Session A's refuse-everything scope would pass
every negative assertion in a traversal suite. Legitimate deep reads and lookalike filenames
(`console.log`, `a..b.txt`) must open, or the suite measures presence rather than correctness.

**After C, in order:** D â€” wire M0b's memory in, including K1 condition 3's abstention path, which
is a condition of the criterion M0b was judged against and is **load-bearing**. E â€” the TUI against
the real loop, first-run onboarding (ADR-002 makes it a requirement, not a nicety), K6 measured in a
clean container, and M1's one open acceptance row (accent on a light background).

### M2 Session A â€” 2026-08-08. The spine: loop, tools, permissions, runs.

**Three new crates, one-way layering: `marlowe-tools` â†’ `marlowe-permission` â†’ `marlowe-loop`.**
375 cargo tests (from 273), `eval/` untouched at 72, conformance unchanged
(`REJECTED, 0 findings, fail_no_time_dependence` â€” the baseline since Session B, see Known issues).

**The three things M2 had to get right so M3 extends rather than replaces:**

1. **Every spawn declares a `CapabilityProfile`**, and `reads_untrusted && !exposed_tools.is_empty()`
   is a load-time error â€” private fields, one constructor, and `Deserialize` routed through it so a
   profile from a file cannot bypass what a profile from code cannot. **Two refusals beyond the
   pinned one** (ADR-022): a quarantined reader may not write memory and may not hold egress, because
   the empty tool set closes neither â€” the loop's own `MemoryWrite` step is not a tool.
2. **Every spawn declares a `Budget` and an `OrphanPolicy`.** `OrphanPolicy` is recorded in the
   `RunSpawned` payload and unused, which is what makes M3 an extension. All six budget dimensions
   fire, each tested individually.
3. **Children return `CondensedResult` and nothing else.** The child's `SessionState` is dropped when
   the recursive call returns; there is no accessor that hands a parent a child's history.

**A subagent is the one loop re-entered** (ADR-022). `tests/hp10_budgets.rs` fails the build if a
second driving loop appears in the crate.

**The decision most likely to be argued with is ADR-023, and it should be read before Session C.**
Taint is computed by the harness from the context window â€” `ModelStep::ToolCall` has no taint field
at all â€” so a model-composed Target carries the **worst trust class in view**. The consequence looks
like a bug the first time it fires: **once a run has read untrusted content, every model-composed
Target in that run is blocked.** That is Â§8.2's trifecta break arriving as a property rather than a
second mechanism, and it means orchestrator-worker is *required* for any run that reads the web and
then acts, not an optimization for hard questions.

**Two defects found by tests, both fixed, both recorded because their failure modes were invisible
from their own tests:**

- **The assembler dropped any block larger than its source cap.** A single long turn vanished. Found
  by a 70%-trigger test reading `fill_pct = 0.0024`. Fixed by ADR-025: only *recoverable* sources are
  trimmable â€” history is not, so history pressure raises fill until compaction handles it with the
  durable appends in front. Omissions are now marked in the view, never silent.
- **Two spin paths.** Compaction compared successive iterations rather than its own result, and
  tool-result masking re-ran when it had nothing left to mask. Both presented as a hang, which is the
  worst shape: `MAX_STEPS` caught them as a budget pause, which reads like a model problem.

**`--reranking`-class hazard avoided, worth naming:** `ExposedSet`, `CapabilityManifest` and
`CapabilityProfile` all route `Deserialize` through their validating constructor. A field-wise
deserialize would have left every in-code test green while the only path that reads outside input
skipped the check.

**Known gap in the brief Â§13 hook, measured not assumed.** The permission layer's files are guarded;
`engine.rs` â€” the loop's *call* into it â€” is not, because guarding it would make every loop change
ask. What stands behind the call site is a test that drives a real blocked call through the loop.
See CLAUDE.md's enforcement table.

**Deferred from M1 and still deferred:** app-level text selection in the conversation pane, and the
launcher on macOS/Linux (Â§B17). Both are Session E or later; neither blocks anything.

### M1 progress â€” 2026-08-08

**Built and verified live in Windows Terminal** (not `TestBackend`): the frame, keyboard navigation,
conversation and Â§B6 tool lines, status band and seven states, inspector, approvals overlay, classic
CLI, width refusal, `doctor`. 87 tests green across `marlowe-surface`, `marlowe-stub`, `marlowe`;
`eval/` untouched at 72.

**Amendments to Addendum B made this session, all at the human's direction:**

- **Â§B10 â€” the mouse is captured.** Reverses the earlier "keyboard-first, so leave selection to the
  terminal" reasoning: drag-selecting the frame is the single thing that made a running application
  read as a printout. Keyboard remains complete; teardown is in the panic hook too.
- **Â§B10 â€” the first-keystroke rule.** The default focus is a region where letters are hotkeys,
  **never a text input**. Stated as a rule because the failure is invisible to any test that presses
  `Esc` first â€” "reachable after one extra key that no border mentions" still passes.
- **Â§B10 â€” copy is first-class.** `Shift`-drag (verified working under capture: 121 chars out of a
  live session), `y` for the focused turn, `Y` for the transcript as markdown. **Payloads are built
  from the model, never the screen** â€” the measured native selection returns
  `+3 âˆ’0 â”‚â”‚ â”ŒSpendâ”€â”€â”€â€¦`, three regions' cells from one row.
- **Â§B17 â€” the launcher.** `marlowe --launch` writes an additive Windows Terminal profile, scheme
  and theme, then opens the window. **The `Marlowe.lnk` this line claimed did not exist until C2d
  created it** â€” there was no shortcut and no code for one.

**Three bugs found by using it that no test caught, all now fixed:**

1. **Scroll never moved.** `move_within` computed `u16::MAX - 1` and the renderer clamped it back to
   the bottom, so the first notch moved nothing and so did the next 65,533. **Every unit test
   passed**, because they asserted `scroll` *changed*, not that the view *moved*. The renderer now
   hands its clamp back to the app.
2. **The third foreground weight was double-dimmed.** The palette carried the mockup's exact
   `#4a4460` **and** `Modifier::DIM` on top, "for terminals that honour it" â€” which had the
   reasoning backwards: an explicit fg colour is universal and SGR 2 is the unreliable half, so the
   modifier could only double-apply where it worked. Windows Terminal honours it, and the dimmest
   tier became unreadable. **The weights now carry no modifier**, so the mockup is the reference on
   every terminal.
3. **`NO_COLOR`.** See item 0 at the top of this file.

**Two Windows Terminal limits, measured rather than assumed** â€” do not re-attempt without new
evidence: `themes.window.frame` is accepted and **silently ignored** (focused title bar stayed at
the Windows accent colour `#946B33`); and the tab strip's `+` cannot be hidden while Windows
Terminal draws the title bar, while giving the title bar back to Windows removes `+` but repaints it
in the accent colour. The `Ã—` *is* removable (`tab.showCloseButton: never`). Focus mode was tried
and rejected â€” it takes drag and close with it, and `WS_CAPTION` is already set, so no window-style
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

No code change was kept. `ESC[?1003h` was briefly added and has been reverted â€” crossterm's
`EnableMouseCapture` already enables all-motion tracking, which is why hover worked all along.

**Deferred to M2, with a real blocker rather than a shrug: app-level text selection in the
conversation pane.** Mouse-down anchors, drag extends, the span renders in inverse video, release
copies. It needs cell-to-character mapping that respects wrapped lines and **never crosses a region
boundary** â€” which is exactly what terminal selection cannot do, and the measured proof is in Â§B10:
a `Shift`-drag across one row of the running build returned `+3 -0 || ,-Spend---`, three regions'
cells from a single screen row. It is blocked on Marlowe owning the renderer for that pane, it is
about a week, and `helix`/`zellij` are the reference implementations. M1 ships `Shift`-drag plus
`y`/`Y`, which covers the need without pretending to be the same capability.

**Two Windows Terminal limits, as measured facts with their numbers.** These are the evidence for
whether a native window is ever worth a milestone, so they are recorded as data, not impressions:

1. **`themes.window.frame` is accepted and silently ignored** (WT 1.24.11911.0). Set to `#0F0E14`,
   the focused title bar still measured **`#946B33`** â€” the Windows accent colour. A settings key
   that does nothing and reports nothing.
2. **The tab strip's `+` cannot be hidden while Windows Terminal draws the title bar.** The two
   reachable states were both built and measured: `showTabsInTitlebar: true` gives a title bar at
   **`#0F0E14`**, identical to the terminal background and seamless, but keeps `+` and the chevron;
   `false` removes the whole strip but hands the bar to Windows, which paints it **`#946B33`**. The
   `x` *is* removable (`tab.showCloseButton: never`). Focus mode was tried and rejected: it removes
   drag and close, and `WS_CAPTION`/`WS_SYSMENU` are **already set** (style `0x14CF0000`), so no
   window-style trick restores them â€” WT draws over the caption itself.

**The 9-line interaction checklist PASSED**, driven by hand by the human in one live Windows
Terminal session, 2026-08-08: every region hotkey, all five dropdowns opened and selected from, the
full Tab cycle and back, conversation scrolling, all seven status states, the approval overlay,
`Ctrl-C` handled by the app, a forced panic, and quit. `RESULT.md` records it attributed to the
human rather than as an unattributed "verified".

**ONE ROW LEFT BEFORE M1 IS ACCEPTED:** accent legibility on a **light** terminal background. Â§B13
asks for the eye, on each; it has a contrast number (3.26:1, which clears AA for large text and UI
components but not AA body) and has never been looked at. Open it once on a light background and
either accept it or move the accent.

### M0c Session A â€” head separability, MEASURED AND CLOSED. `runs/session-m0c/RESULT.md`.

**R@1 is 0.6725 and this session did not move it. Nothing shipped; there is no Rust diff.** Both
named candidates were built, four learned architectures were cross-validated, and a seventh
mechanism was found mid-session and taken to a held-out read. All null or negative.

**1. K1's interval reading is ARITHMETICALLY UNREACHABLE at the declared operating point.** A
**perfect** selector â€” 23 of 23 â€” has a Clopper-Pearson lower bound of **0.8518** at 10% coverage on
n = 229. Clearing 0.95 by interval needs **n_c â‰¥ 72 with zero errors, or â‰¥ 110 with one**. This is
not a retrieval statement; it retires a target the way ADR-016 retired the 0.3739 ceiling.
**Do not register a band on it.** `tools/reach_head_r0_attainability.py`.

**2. Candidate A â€” a relevance-fitted confidence signal â€” is NEGATIVE.** No query-time feature beats
the rerank margin at the head, and the three with *better overall AUC are worse there*. Overall
discrimination and head discrimination are different quantities on this corpus.

**3. Candidate B â€” set-wise / listwise scoring â€” is a NULL across four architectures.** Out-of-fold,
5-fold CV by conversation: S1 set-wise head **+0.0044**, L1 listwise fine-tune **âˆ’0.0131** (null
*with power*, discordant 13, p = 0.5811), LS1 **+0.0000**, S2 global cross-encoder with token-level
cross-talk **+0.0000** (top-1 changed on 2 of 229). **The binding resource is labelled data** â€” 229
fit queries, 38 recoverable failures, on a reranker Session J already fine-tuned on them.

**4. Slate construction gained +0.0087 on fit and lost âˆ’0.0044 on held-out.** Input recall rose
+0.0175 and conditional accuracy fell âˆ’0.0189 to meet it. The Session J addendum pattern exactly.

**5. THE FAILURE MODE IS NOW CHARACTERISED, and it is not what STATE.md said.** Same-session
gold-to-rank-1 turn gaps are **âˆ’10, âˆ’8, âˆ’6, âˆ’4, âˆ’2 â€” all even, therefore SAME ROLE**. The failure is
**discriminating between two USER turns in one conversation several exchanges apart**. Rank 1 on
failures is assistant-authored on only **5.3% (fit) / 7.5% (held-out)** of cases â€” the Session J
fine-tune already removed the user/assistant confusion. **The "47.1% assistant-authored" figure
below is stale and turn-pair chunking's rationale goes with it** (measured ceiling: +0.0087 fit,
+0.0131 held-out).

**6. A METRIC MISMATCH, resolved.** Systems publishing "96.6% on LongMemEval" report **session-level
R@5**. Marlowe measures **0.9738 session R@5 shipped, 0.9869 on its dense cue alone** â€” it is not
behind on that metric, it reports a far harder one (turn-level R@1 out of ~490 candidates). Never
quote one against the other.

**7. HARM-WEIGHTED PRECISION, measured for the first time. `docs/design/HARM-WEIGHTED-PRECISION.md`.**
Â§5.7 is about harm, not accuracy, and R@1 treats every failure as equal. Partitioning rank-1 into
harm classes â€” no new labels, LongMemEval's knowledge-update annotation carries it:

  - **Of the injections that are not the current value, 13 of 85 (15.3%) are HARMFUL and 72 (84.7%)
    are merely useless.** Â§5.7's premise is *weaker* than assumed on the failure side. Five in six
    wrong injections cost tokens rather than corrupt reasoning.
  - **But R@1 counts the stale fact as a hit** â€” see the box at the top of this file.
  - **At the declared operating point the two precisions are IDENTICAL**: published 0.9130, current
    0.9130, harm 0 of 23, on both splits. `PRECISION-COVERAGE.md` needs no correction at 10%
    coverage and a âˆ’0.0437 correction at 100%.
  - **Harm is zero at the head FOR THE WRONG REASON, and this is the part not to re-derive wrong.**
    Not "abstention suppresses harm" â€” that is a proxy conclusion. Knowledge-update queries are
    simply low-confidence (median margin **0.2782 vs 0.4020**) and make up **0.0% of the held-out
    top-10% slice against a 15.7% base rate**. *Within* knowledge-update the margin's relation to
    harm **flips sign between splits** (top-half harm 0.444 held-out vs 0.389 fit). The protection is
    a **category-exclusion side effect and it is fragile** â€” raising coverage, or improving
    confidence on knowledge-update, removes it with nothing reporting a change.
  - **Â§4.3's supersession exclusion is LIVE AND BLIND.** `entry.rs:124` is correct and called at
    `retrieve.rs:328` â€” not a wiring defect. But the only writer of `superseded_by` is
    consolidation's **â‰¥0.98-cosine** near-duplicate merge (`consolidate.rs:697`); `ingest.rs:142`
    hardcodes `None`, Â§4.6's wire has no supersession field and forbids extras, and `store.rs:133`
    defers the contradiction detector. ADR-012 measured â‰¥0.98 pairs at **0.0086%** of 30.6M.
    **A missing component, not a tuning opportunity â€” and it is the component Â§5.7 assumes exists.**

**THE HUMAN LABEL SET is now the highest-value open item** â€” â‰¥400 judged injections, â‰¥50 per
category, judged blind, stratified by score decile. **True injection precision has never been
computed**; every figure is a gold-turn proxy, including the harm classes above. It is drawable and
it is the human's deliverable.

### M0c Session B â€” supersession is BLOCKED, not dead. ADR-028. `runs/session-m0c/RESULT.md` Part 7.

**Nothing was built. The verdict is about scope.** Three measurements, on fit, before any code:

- **R6, the ceiling.** A perfect oracle is worth **+0.1666 knowledge-update R@1 current-value-only**
  (0.3056 â†’ 0.4722), **+0.0262 overall** (0.6900 â†’ 0.7162), and cuts harmful injections **17 â†’ 5**.
  **Worth building whenever it becomes reachable.**
- **R6, the power finding.** A perfect oracle produces exactly **6 discordant** â€” the bare minimum
  for Î± = 0.05 â€” reaching p = 0.0312 *only* because all six fall one way. **No realisable detector
  can produce a significant result on this split.** Î± is declared UNATTAINABLE IN ADVANCE; the delta
  carries any future verdict alone. The oracle's one-directional read is structural and must not be
  inherited by a real arm's instrument check.
- **R7, similarity CLOSED.** True pairs at ~0.83 cosine sit inside a distractor distribution reaching
  0.95. **Best precision anywhere: 0.0745** â€” twelve live memories permanently removed per correct
  catch, against a cost model registered before measuring. **ADR-012's 0.98 bar catches 0 of 33**,
  which is the quantitative reason the current merge is blind.
- **R8, value conflict CLOSED ON SCALING.** **0.4444 anchored** on the true stale turn; **0.0026
  unanchored** as a real detector runs â€” 4 true against ~1,539 false across 3.9M pairs, a **154Ã—
  collapse**. The anchored number was the mechanism's precision *conditional on entity resolution
  already existing*. **The rule verifies supersession given a candidate; it does not find one.**

> **VERDICT (2): signal present, extraction missing.** Not undetectable â€” blocked on a component.

**OPEN GAP, with a named closing condition. DO NOT MARK SUPERSESSION CLOSED.** Detection requires
**entity resolution over the candidate pool**, which narrows 3.9M pairs to a handful before any value
comparison runs. **HP2 specifies it â€” `SameAs` beliefs with confidence and provenance, produced by
consolidation â€” and it has never been built.** `Payload::Entity` and `Payload::Edge` exist in Â§3.2;
nothing fills them. **Closing condition: that component exists**, and then a value comparison over
(entity, relation) triples clears **precision â‰¥ 0.5 measured UNANCHORED** â€” parity under the
registered asymmetry â€” at a recall moving the ceiling by more than one case. **Entity resolution is
HP2 and is NOT scoped here**; it needs its own registration and its own reachability check. Note it
would be the first live exercise of trust propagation through a derived belief.

> ### Â§5.7 CONSEQUENCE â€” the finding of this whole line of work
> **With supersession unreachable, harm being zero at the operating point is the ONLY protection
> that exists, and it is ACCIDENTAL.** The head contains **0.0% knowledge-update queries against a
> 15.7% base rate** because that category is low-confidence (median margin 0.2782 vs 0.4020), not
> because harm is detected. **The tripwire is now LOAD-BEARING, not diagnostic.**
>
> **Two ways it disappears, both things a future session might do deliberately:** coverage rising,
> or knowledge-update confidence improving. R6 measured the second â€” a perfect oracle takes the fit
> knowledge-update share of the top decile from **4.3% to 13.0%**. Neither announces itself.
>
> **`tools/tripwire_head_composition.py`**, baselined at
> `crates/marlowe-memory/artifacts/head-composition-baseline-v1.json`. TRIPs on any harmful
> injection at the operating point against a baseline of zero; WARNs when the knowledge-update share
> reaches the base rate, at which point the harm figure must be RE-MEASURED, not inherited.
> **`0 of 23` is reported with its interval every time â€” upper bound 0.1482.**

**THE CORRECTED BASELINE MUST APPEAR BESIDE EVERY PUBLISHED R@1.** Held-out **0.6288** current-value-
only against **0.6725** published; knowledge-update **0.4444** against **0.7222**. A session quoting
the published figure without knowing it counts stale hits as successes is working from a false
premise.

**Â§4.3's exclusion is untouched and is NOT the defect.** It is correct, wired and unit-tested. It has
no edges because nothing produces them.

**Also still open:** the gate-design constraint (ADR-016's closing section â€” either the resolution
rule or the margin feature's one-positive-per-query property must change; **re-tuning the resolution
stays forbidden**); QA accuracy (needs an API credential); **batching the depth-10 rerank** â€”
batch invariance measured **0.000000** on the shipped f32 graph in Session K, so it is available and
untested, and latency is the only currency that buys depth.

**Do not re-attempt:** consolidation, PRF, entity expansion, HyDE, session pruning as a quality
mechanism, length normalization, raising sequence length, **re-scoring the depth-10 slate by any
learned mechanism**, or **the 10%-coverage interval**.

## Standing checks â€” re-run on every cue, feature, pool or MODEL change

- **A second implementation of a scored-path component must reproduce the first, EXACTLY.** Session
  H: 0.5764 = 0.5764. Session K: **0.6725 = 0.6725**.
- **`analyze_cue_overlap.py` is the authority for binary-side R@1.** Its ranking functions and dump
  reader are module-level so a second tool imports them instead of restating them.
  `publish_precision_coverage.py` **refuses to write** unless its R@1 matches.
  **`score_longmemeval.read_scored` drops `survived_pruning` and `rerank_score`** â€” anything ranking
  from it silently falls through to the gate order. This cost a full wrong curve in Session K.
- **Determinism, batch and padding invariance are re-measured PER GRAPH and never inherited.**
- **Pin the ONNX graph optimization level on both sides.** `ort` uses `Level1`; Python defaults to
  `ORT_ENABLE_ALL` and fuses differently â€” 0.0699 logits apart on identical token ids.
- **`repro --runs 2`, WITHOUT a cache.** Run it *early*.
- **`conformance` BEFORE any quality number.**
- **The artifact the driver reads must be the artifact the run scored with.**
- **Calibration generalization: fit-split prediction vs held-out measurement**, per cue.
- **The unchanged-cue check is a NULL INSTRUMENT for a pruning change.** Its silence is not evidence.
- **`cargo test --workspace` (494) and `cd eval && python -m pytest` (72).**
- **A build error seen in a shared checkout is a SNAPSHOT, not a fact.** Re-verify before
  reporting one, and say when it was observed. Twice in one day a session reported a real error in
  the other's mid-edit that had already been resolved â€” in both directions. See CLAUDE.md's
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
  check â€” the same shape as a stale default, arriving through a different door. **This is the
  TWELFTH instance of the family in item 0, and the FIRST caught by design rather than by failure**
  â€” the other eleven were found after they shipped; this one was closed before it could exist,
  because the family's question was asked of the serde path specifically.

## The default model, and what was actually measured

**`qwen3.5:9b`**, pinned as `marlowe_provider::DEFAULT_MODEL`. Chosen on **tool-call reliability**
rather than general quality, because the first thing a user does is ask Marlowe to read a file and
a model that cannot emit a well-formed call looks exactly like a broken harness.

**Measured 2026-08-08, one model, 12 trials: 12/12 well-formed, 12/12 correct target, median
1666 ms.**

**And the qualification, because a point estimate is not an interval.** 12/12 on twelve trials has
a 95% Clopper-Pearson lower bound of â‰ˆ**0.74**, which is *below* the 0.80 bar it is measured
against. It clears the bar **on the point estimate and not with its interval** â€” the same
distinction K1's amendment turns on. Twelve trials is thin. Raising `capability::MIN_TRIALS` costs
only probe time, and is the cheapest way to tighten this.

**No other model has been measured**, so this is not a comparison â€” see the constraint below.

## A standing constraint on every routing decision

**Model comparison is bounded by local hardware: one model at a time.** The development machine
holds a large library on disk but cannot keep several large models resident, so a comparison sweep
thrashes rather than erroring. `tests/tool_call_probe.rs` therefore measures **one** model by
default and requires `MARLOWE_PROBE_SWEEP=1` plus an explicit list before it will iterate.

**This binds more than the probe.** ADR-008's tiered routing â€” strong model for orchestration,
cheap models for extraction and classification â€” assumes two models can be *chosen between*, and
choosing between them means measuring them. On this hardware that is sequential, slow, and cannot
be done as one run. A proposal that treats a strong/cheap split as free is a proposal that has not
priced the measurement. Recorded here so it does not surface as a surprise inside one.

### The persona scare, and what it actually was

**Reported as "the persona seems to have cracked": lowercase, chatty, addressing the USER as
Marlowe, and fabricating a cause â€” *"looks like a display glitch"* â€” which `<operating_principles>`
forbids in the same breath.** It would not reproduce, and the investigation is worth keeping
because most of it was ruling things out.

**Ruled out with evidence, in order:** the persona reaches the model complete (10,833 chars, in
`system[0]`, on all eight captured turns); system messages are obeyed (control: a system message
saying *reply with exactly BANANA* returns BANANA); three consecutive system messages survive,
though the shape is non-standard and was worth suspecting; roles alternate correctly across turns;
and multi-turn through `--ask` holds register. The model's sampling defaults are aggressive â€”
`temperature 1`, **`presence_penalty 1.5`**, which actively penalises reusing phrasing and is
therefore hostile to a consistent register â€” but tamed sampling was not better on a short
exchange. **That one is unproven rather than cleared: a long context is where a presence penalty
would bite hardest.**

**A wrong turn worth recording.** `/api/show` reports this model's template as `{{ .Prompt }}` â€”
thirteen characters, rendering neither `.System` nor `.Messages` â€” and the obvious conclusion is
that the prompt is discarded. **It is not.** Ollama uses a built-in renderer for this architecture
and ignores that field. The BANANA control is what caught it, and it was run only because the
conclusion was too convenient. *A capability report about a template is not a report about what
the model received.*

**Most likely cause: a stale daemon**, which is circumstantial and is stated as such â€” same
binary, same persona, same prompts, same model, and it will not reproduce. It is also the failure
with prior form: three times before, twice on this day alone. The window-close fix removes the
main way a stale daemon survives a rebuild.

**What the capture did prove, on a real turn:** `assistant tool_calls=2`, two `web` results, ids
`call_1`/`call_2` matched by `tool_call_id`. **Parallel tool calls, live**, with the attribution
that makes a partial failure legible.

## Known issues

### M2 C2e - outstanding, highest first

- **`web` IS EXPOSED. ADR-032 is implemented and approved.** `interactive()` holds
  `EgressPolicy::AllowApproved { granted: [] }` and exposes eight tools. The three deny-shaped
  policies are now genuinely different and the difference is the decision: `DenyAll` is
  **structural and unwidenable** (the quarantined reader holds it, and `grant()` is a no-op on
  it), a declared `Allow` list is **terminal** (a tool cannot ask its way past a list somebody
  wrote), and `AllowApproved` is a **question** â€” empty by default, widened one host at a time by
  a human, session-scoped, never persisted. Brief Â§8's allowlist-by-default holds with an empty
  default set rather than a `*`.
  **The ask fires on a check the consequence level cannot reach**: `web` is `Inert`, so the tier
  comparison would allow it outright, and ADR-002's Inert exemption only stands while egress
  allowlisting covers the tool. The prompt names the host â€” asserted, because that is what makes
  per-call approval a replacement for the allowlist rather than a button.
  **THE CLI CAN NOW APPROVE.** `Client::send_streaming_approving` answers inline, on the same
  socket, because the daemon is blocked on that read. `marlowe --ask` prompts at the terminal with
  the blast radius and defaults to no; stdin at EOF (a pipe, a script) declines, because an
  unattended `--ask` has nobody to approve anything. `decision: 0` â€” the loop's render-only
  announcement â€” is deliberately **not** answered, or a spare approval sits on the wire for the
  next question.
  **THE TUI CAN NOW TOO.** A modal window offers **y / n / o** â€” o being a decline that carries a
  reason, which the engine passes to the model verbatim (`ApprovalGate::decline_reason`, a
  defaulted method so no other gate had to change). "Declined" tells the model to stop; "declined
  because X" tells it what an acceptable call looks like.
  **The window has no dismiss key, deliberately.** The daemon is blocked on a `sync_channel(0)`
  rendezvous, so a window that closed without answering would hang the turn with nothing on
  screen explaining why. `Esc` is a decline, not a dismissal; `Esc` inside the reason editor
  returns to the question rather than leaving it. Both asserted, with a negative control that an
  unrelated key neither answers nor closes it.
  **A DECLINE IS NOT A HARD BLOCK, and telling the model it was is the defect the first live
  approval found.** One refusal message served both situations and it was the unattended one:
  declining in the TUI handed the model *"no interactive approval surface is attached to this
  run"* â€” false, the window was on screen â€” so it reported the capability hard-blocked and
  stopped attempting anything. `ApprovalGate::is_interactive` (defaulted `false`) now splits
  three cases: declined-with-a-reason carries the user's words verbatim as guidance,
  declined-without says a different call may still be approved, and only the genuinely
  unattended case says the tool is unavailable. **A refusal the model cannot act on correctly is
  worse than one it cannot read, because it acts on it confidently.**
  **It renders `PendingApproval`, not Â§B9's `BlastRadius`, and that is a finding rather than a
  shortcut.** The first tool ever to need an approval is a fetch, and `Effect` has no fetch
  variant â€” `Delete`, `Write`, `Send`, `Execute`, none of which describe retrieving a URL. And
  `Ceiling` has no producer until M6. So the window states what is known and prints *ceiling
  unknown* rather than inventing two fields to reuse the richer type.
  **NOTHING HAS CROSSED THIS ON A REAL TURN.** Both halves are tested against each other over a
  real socket (`approval_round_trip.rs`) and neither test runs a model. Treat the end-to-end path
  as unverified until an approval is observed on a real turn with a real fetch.
  **Â§B9 is partly served:** blast radius and `novelty` (an `Option`, never defaulted). **No
  ceiling** â€” no producer until the trust ledger at M6, and defaulting one would be a claim about
  promotion logic nobody has written.
  `recall` and `use` remain unexposed and unimplemented.

- ~~**The trust floor latches on an ordinary workspace read.**~~ **CLOSED, M2 C2f** â€” and the
  diagnosis was neither of the two candidates. The trust class at ingest and the floor derivation
  were both correct; the *announcement* fired on any downward move. The trigger was not a `read` at
  all: the stable tier's `Identity` block is `AgentObserved`, so it fired on the first assemble of
  every run. See the C2f section at the top.
- ~~**`ParamSpec` conflates a security role with an arity question**~~ â€” **CLOSED.** The code
  landed in `de18ace`; C2f added the missing paperwork (ADR-034, CONTRACTS Â§7.3 amended, which had
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
- ~~**`web`'s description promises search.**~~ **CLOSED (C2f).** It says it fetches and does not
  search, `url` is **required**, and **`query` is removed** â€” offering a parameter for an
  operation this build does not have invites a call that always fails, which is the same defect
  the other descriptions were corrected for. `the_web_tool_requires_its_url_and_offers_no_search`
  asserts the **disclaimer** rather than the absence of the word: an honest description has to
  contain "does not search", so a test forbidding the token cannot tell a promise from a denial.
- ~~**`run` never spawns from a model call.**~~ **PARTLY CLOSED (C2f), and the rest is a decision
  rather than work.** The canned refusal was a `ModelStep::Say`, so a model calling `run` put
  harness prose on screen **as Marlowe's reply** and ended the turn â€” ADR-030 forbids the first
  and a tool refusal is not an answer to anything. It now routes as an ordinary `ToolCall` with no
  executor, so the model reads a refusal it can act on and the turn continues.
  **It still cannot spawn, and inventing the missing pieces is what Â§5 forbids**: a spawn's
  capability profile, budget and orphan policy must be *declared at spawn, never inferred*, and
  the model supplies a task. **Needs an ADR about who declares the contract.** M2 D.
- ~~**Descriptions promise operations that do not exist.**~~ **CLOSED.** `bash`, `find`, `edit`
  and `read` in `de18ace`; `web` in C2f. Original entry:
- **Descriptions promise operations that do not exist.** `bash` says "persistent shell session"
  (`spawn_shell` runs a fresh `cmd /C` per call), `find` says "index-backed symbol lookup" (it is
  `line.contains`), `edit` says "atomic" (it is `set_len(0)` + rewrite), `read` says "blob, or
  reference" (no parameter accepts either). Model-visible prose that makes the model call things
  wrongly and then blame itself.
- ~~**`run.budget_micros_usd` never appears in the approval prompt's scope line**~~ â€” **CLOSED
  (C2f)**, via ADR-032 Â§3.2 and a Â§13-approved change to `adjudicate.rs`. `ArgValue::render` is
  total and wildcard-free. **The parser half is still open**: `parse_step` still emits `Integer`
  for a declared `Amount`, so the declared type is never the runtime variant. That no longer hides
  the ceiling â€” `render` handles `Integer` too â€” but the coercion-by-declared-type is unbuilt.
  Original entry:
- ~~**`parse_step` never produces `Amount`**~~ â€” **CLOSED (C2f).** Arguments are coerced to the
  manifest's declared `ParamType` in **`Engine::tool_call`**, not in the Ollama adapter: the
  manifest is there, and a second provider would otherwise need the same coercion and not know to
  have it. A spend ceiling now reaches the Â§B9 scope line as `2.500000 (spend ceiling)` rather
  than `2500000`, which is a number a human approves after reading it as dollars. A negative
  amount is passed through rather than clamped â€” a clamp turns a nonsensical value into a
  plausible one. Original entry:
- **`run.budget_micros_usd` types as `Amount`, which `parse_step` can never produce** - it emits
  `ArgValue::Integer`. `blast_radius` collects targets via `as_text`, which returns `None` for
  `Integer`, **so the spend ceiling never appears in the approval prompt's scope line**. Section B9
  requires blast radius stated; a budget absent from the scope line is exactly the case where a
  human approves something they would have refused. **Highest-consequence finding of the tool
  audit.** `adjudicate.rs` is section-13 guarded: this needs a `DECISIONS.md` entry **before** it
  is fixed.
- ~~**CLOSING THE TUI WINDOW WITH THE X DOES NOT STOP THE DAEMON.**~~ **CLOSED (C2f)**, and
  **not yet confirmed by a real window close.** A Windows console control handler runs the
  shutdown on `CTRL_CLOSE_EVENT`; one hand-declared `kernel32` import, no bindings crate.
  **`TURN_IN_FLIGHT` mirrors `session.is_busy()`**, so a window closed mid-turn still leaves the
  daemon up â€” without that mirror the fix would have reintroduced C2e's mid-turn conversation
  loss. Original entry:
- **CLOSING THE TUI WINDOW WITH THE X DOES NOT STOP THE DAEMON.** Found 2026-08-10 during the
  first live approval test. `tui.rs` sends `Request::Shutdown` on exit, and that fires on a
  *graceful* quit â€” closing the window terminates the process outright, so the teardown never
  runs and the detached daemon (C2d gave it `DETACHED_PROCESS`, correctly) outlives it. The
  symptom is the one this project has already paid for twice: the next launch reconnects to a
  daemon serving pre-change code. **The staleness banner caught it** â€” `--status` reported *"this
  daemon's binary is 17 min older than the source it was built from"*, which is `staleness.rs`
  doing exactly its job. Needs a console control handler on Windows.
- ~~**There is no CLI shutdown.**~~ **CLOSED (C2f):** `marlowe --shutdown [--daemon-port N]`,
  verified against a real daemon on a scratch port. "No daemon is running" is not an error.
  Original entry:
- **There is no CLI shutdown, so a daemon left behind can only be killed.** `Request::Shutdown`
  and `Client::shutdown()` both exist; no mode reaches them (`--serve`, `--ask`, `--status`,
  `--launch`, `--tui`, `--classic`, `--doctor`, `--eval-adapter`). Until a `--shutdown` mode
  lands, the graceful path is to write `{"op":"shutdown"}` to the daemon port â€” which still
  honours the refuse-while-a-run-is-live guard, unlike `Stop-Process`.
- ~~**`--ask` cannot talk to a running daemon.**~~ **THE ENTRY WAS WRONG, and it cost this session
  time.** `--ask` *does* use a running daemon on the default port â€” three `--ask` calls held one
  conversation across turns, which the entry says is impossible. What it lacked was
  **`--daemon-port`**, added in C2f: without it you cannot reach a scratch daemon and, worse, you
  cannot tell which daemon answered. That is how a `--dev` dump came back empty â€” the request had
  gone over the socket to a daemon started *without* `--dev`, which reads as a broken instrument
  rather than as the wrong process. Verified: with the flag it reaches the scratch daemon, without
  it it does not. Original entry:
- **`--ask` cannot talk to a running daemon.** No `--daemon-port`; it always runs in-process, so
  two `--ask` invocations get two daemons and two empty sessions. The TUI is unaffected.
- ~~**Session memory is in-process only.**~~ **HALF CLOSED (M2 D).** Beliefs are durable â€”
  `BeliefStore::derive` rebuilds them from the journal, verified by writing a claim, restarting, and
  watching the next claim's id index advance rather than reset. The **conversation** store is still a
  `BTreeMap` on `Daemon` and still dies with the process, deliberately: durable conversations are
  M3's WAL work. *Memory survives a restart, the conversation does not.*
- **`bash` is refused unconditionally in the daemon.** `Irreversible` -> `NeedsApproval` at every
  tier -> `DenyUnattended` returns false. There is no interactive approval gate yet, so it always
  reads `declined`.
- **`run` never spawns from a model call.** `control_step` returns a canned
  "[run is not yet reachable from a model call...]", and the schema still demands three spawn
  arguments.
- **`read` cannot dereference a reference.** `web` declares `inline_threshold_bytes: 0` - "the loop
  gets a reference" - and nothing can read one. The head/tail preview is a stopgap; the content
  store is M2 D.
- ~~**`consolidation()` exposes `recall`, which has no executor.**~~ **CLOSED (M2 D), and the guard
  fired exactly as this entry predicted.** `marlowe_daemon::recall::RecallTools` wraps the filesystem
  host and answers `recall` over the belief store, so `marlowe-exec` never learns about beliefs.
  **The refusal exposed a second defect**: `Daemon::open` was verifying a bare `FileSystemTools`
  while the turn ran a different host â€” a gap that fails safely in this direction and unsafely in the
  other. `build_tool_host` is now the only constructor.
  **`recall` is deliberately NOT gated by the declared operating point.** K1 condition 3 governs
  content the model did not ask for; an explicit search it can evaluate is a different act, and Â§3.6
  requires recall to see tombstones and unmatured entries â€” precisely what injection must not.
  Security is unchanged: recalled text carries its own class into the view and `trust_floor` is `min`
  over every block.
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


- **The export gap is now on the SHIPPED path.** The graph is **self-validated only** â€” this project
  is the publisher, so there is no external authority. Digest pinning, torch-vs-ORT at 1e-6,
  per-graph determinism/batch/padding invariance, and a second pair-encoder implementation
  reproducing HuggingFace exactly are what stand behind it. **They bound the gap; they do not close
  it.** Say so wherever the number is quoted.
- **Do not re-quantize the shipped graph without re-measuring `[1, 256]`.** ADR-015's shape-binding
  is a property of int8 graphs; **padding alone flipped top-1 in 15% of int8 cases** while f32 was
  invariant to 0.000000. The fine-tuned graph has never been measured quantized.
- **`MAX_SEQ_LEN` stays 256; the 7.86% gold truncation is a PRICED defect.** Raising it cost
  âˆ’0.0917 R@1 (`p = 0.0002`, Î± attainable) because the cap doubles as a length normalizer.
  ADR-017's closure was **withdrawn** on held-out. Only viable with a normalization term fitted
  against **relevance**, not against the score â€” and the registered `E[score|length]` estimator had
  slope âˆ’0.5091 and *added* score to long candidates.
- **At top-10 the shipped ranker is BELOW dense alone** (0.9039 vs 0.9170). It is a top-1 mechanism
  reordering ten candidates; do not read its R@10 as a capability.
- ~~**The gate still injects nothing, and ADR-016 is why**~~ â€” **CLOSED (M2 D).** The declared
  operating point is now the admission rule and the isotonic gate no longer filters: `passes` is
  false for every candidate by construction, so ANDing the two would have left injection dead.
  Conformance is **`CONFORMS`** and the clock probe passes, which means **Â§4.3 maturation now has
  contract-level coverage** â€” the probe's whole teeth are that an implementation with no observable
  time dependence fails it. `passes` is still computed, still dumped, still reported as
  `above_threshold`; it no longer decides.
- **Per-category reads are unstable across the split â€” a finding AGAINST group-conditional
  conformal, not a caveat on it.** Largest wrong-query calibration set is 12 against a floor of 40.
- **Do not quote Session H's McNemar p-values.** The test had no power; ADR-014.
- **Session pruning is closed as a QUALITY mechanism.** It remains a cost mechanism.
- **Turn-pair chunking is now MEASURED and small.** Ceiling +0.0087 fit / +0.0131 held-out. Its
  stated rationale is stale: 89.4% of gold is still user-authored, but rank 1 on failures is
  assistant-authored on only 5.3â€“7.5% of cases, not 47.1%. See M0c above.
- **A TOKENIZER WRAPPER IS NOT THE TOKENIZER.** `PreTrainedTokenizerFast` over the shipped
  `tokenizer.json` produced logits up to **3.56** from the raw `tokenizers.Tokenizer` the scored
  path uses â€” same file, same vocabulary, entirely plausible output. Twelfth instance of
  two-sides-silently-disagree. Anything scoring offline must use `tokenizers.Tokenizer` configured
  as `spike_cross_encoder.encode` configures it, and must assert against cached logits before
  writing.
- **A single 20% validation slice is not an instrument at this n.** It read one arm at +0.0435 that
  5-fold CV read at +0.0044 â€” 38 versus 37 of 46 queries. ADR-012. Use out-of-fold predictions over
  all 229.
- **The failure mode is only 58% same-session.** Any brief describing it as same-session
  discrimination is wrong by that margin.
- **The additivity read's subsumption rule is defective as registered.** Fix before reusing.
- **Trust propagation through a derived belief is STILL unexercised.**
- **The 230 â†’ 229 denominator change must not be ignored in any cross-session comparison.**
- **Every poisoning ASR is 0.000 and VACUOUS.** K3 is the exception and still meaningful.
- **The maturation window is 6h and under tuning pressure. Do not adjust it to make a suite green.**
- **`retrieval_tokens` is a pessimistic estimate, not a token count** (3 chars/token).
- **`considered` costs a full-store scan per query.** ADR-003's live-only hot index removes it.
- **LongMemEval-S adapter verified 2026-08-02; LoCoMo still unverified.** We run **`cleaned`**.
- **LongMemEval-S penalises correct clock handling on 76 of 500 cases.**
- **The headline metric has never been produced.** No human label set exists.
- **The permission layer has no kernel backstop (ADR-002, revised).**
- **M1's Â§B13 suite must run on both native Windows Terminal and a Linux terminal emulator.**
- **Path scoping must be re-verified on BOTH platforms after any change to `scope/`.** Windows
  cannot run the symlink class without elevation; Linux never exercises the Windows pinning. A
  single-platform green is a half-measured wall. Both were run at the close of Session B.
- **`read`, `edit`, `find` and `bash` still have no executors** (Session C). Path scoping now
  admits a declared path, so a green traversal suite is evidence about the *checker*, not about
  filesystem tools that do not exist yet.
- **HP10's zero-config row is PARTIAL.** The library half is tested; **K6 â€” install â†’ first useful
  output under five minutes in a clean container â€” is not measured** and lands in Session E. It is a
  milestone kill criterion, so do not let the passing library test be read as the criterion.
- **`TurnEvent` exists twice** â€” canonically in `marlowe-loop`, and the view-model copy now in
  **`marlowe-view`** (moved from `marlowe-stub` by C2d). Session E deletes the duplicate and points
  `marlowe-surface` at the real one. The two `BlastRadius` shapes (CONTRACTS Â§9's, and the rendered
  form) reconcile there. **C2d deliberately did not absorb this.**
- **The M2 report line said "a spawn with an empty tool set and reads_untrusted fails at load
  time".** It is the **non-empty** set that fails, per CONTRACTS Â§5; the empty set is the valid
  quarantined reader. Both cases are tested so the two cannot be confused.

## Open questions for the human

0. **EXAMINED IN M2 SESSION D â€” two holes, one safe, one absent.** Full audit in
   `runs/m2-session-d/OPEN-QUESTION-0-AUDIT.md`; summary at the top of this file. **Both holes need a
   Â§13 decision and neither was touched**: a trust term in *ranking* (`effective_trust` is a declared
   gate feature and is **inert**, and ADR-038 is what makes it start varying) and a trust term in the
   *consolidation merge predicate* (text cosine alone, latest wins, so a newer attacker-authored
   near-duplicate evicts a genuine belief). Either change moves a registered number and needs a
   pre-registration first. The original question follows.

   **FOUR PLACES WHERE UNTRUSTED CONTENT SHAPES A DECISION THROUGH A PATH NOBODY HAS LOOKED AT.**
   ADR-036 Â§5 established that the (action, target) question â€” *who chose the thing that determines
   the outcome* â€” applies where there is **no tool, no argument and no permission check**. That
   generalization was found in one domain and immediately implicates four others, none of which has
   been examined:

   | Where | The value untrusted content could shape | Why nobody has looked |
   |---|---|---|
   | **Ranking inputs** | query text and candidate text both reach the cross-encoder. A page that shapes a query shapes what is retrieved *and* what is injected | the rerank is treated as a quality mechanism, not a decision surface |
   | **Cache keys** | a key derived from attacker-influenced text lets one request's result be served for another | there is no cache yet â€” which is why now is when it is cheap |
   | **Memory derivation lineage** | `derived_from` is already a declared `Target` on `remember`, but the **harness-side** resolution of lineage during consolidation is not the same path | the tool argument is guarded; the internal path was never asked the question |
   | **Consolidation merge decisions** | whether two memories are *the same fact* is the identity question of ADR-036 Â§4, inside the memory system, on content that may be untrusted | it predates the framing entirely |

   **The tell they share:** each decides something using text whose author is not established, and
   in each the trust floor is either uniform or absent, so the latch cannot discriminate (see the
   CLAUDE.md ledger entry). This is a question rather than a finding â€” **none of the four has been
   confirmed exploitable and none has been confirmed safe.** Examining one is a session's work;
   deciding they are fine without looking is the failure this project keeps recording.

1. **HP14 has an experiment attached, not an answer** â€” needs a consenting cohort at M6.
2. **QA accuracy needs an API credential.** A key and a small HTTP client in `tools/`. Offline
   measurement over retrieval output only; an answer stage on the measured path is milestone drift.
3. **The human label set is your deliverable and it is now drawable.** See above.

## Built

**M2 Session A** â€” the spine. Three crates: `marlowe-tools` (manifests with load-time default-deny,
`ExposedSet` capped in its constructor, the eleven builtins, tool descriptions carrying a trust
class), `marlowe-permission` (`TaintSet` failing closed, the `(action, target)` check, egress with a
deliberately strict URL parser, a path scope that refuses everything, the adjudicator),
`marlowe-loop` (the one loop, `Budget`, `Run`, `CapabilityProfile`, the context assembler,
provenance, ephemeral spawn, `TurnEvent`). **375 tests, from 273.** ADR-022 through ADR-026. Six
paths added to the brief Â§13 hook and pipe-tested.

**M1 Sessions Aâ€“B** â€” the TUI and classic CLI against the scripted stub, closed at `ed25914`. K4
carried and met. ADR-021.

**M0b Session K** â€” the reranker ships. `rerank.rs` re-pinned to the fine-tuned f32 graph with a
named refusal for the superseded int8 directory; `cross_encoder_reference.rs` table-driven over both
vocabularies (**190 tests**, from 188); `analyze_cue_overlap.py` ranking lifted to module scope
(verified byte-identical); new `tools/publish_precision_coverage.py`; **three stale defaults
deleted** â€” `score_longmemeval.py --reranking` (defaulted to the *old* graph),
`session_j_verify_export.py --out-dir` (silently overwrote Session J's record), and
`make_cross_encoder_fixtures.py`'s hard-coded model. New: `docs/design/PRECISION-COVERAGE.md`,
`docs/design/M1-KICKOFF.md`, ADR-019, ADR-020, brief Â§5.7.1.

**Earlier:** A (workspace, contracts, journal, memory) Â· B (lexical cue, frozen gate) Â· C (dense
cue) Â· D (max fusion, **failed floor**, ADR-010) Â· E (per-query features, **failed floor**,
ADR-011) Â· F (consolidation, **null**, ADR-012) Â· G (query side measured, ADR-013) Â· H (cross-encoder
rerank ships, ADR-014) Â· I (sequence cap is a length normalizer, ADR-015) Â· J (ceiling never measured
quality / normalization null / fine-tuning is the lever â€” ADR-016, 017, 018).

---

### Maintaining this file

Update at the **end of every session**, before stopping. Keep it short â€” it loads every session and
competes with real work for context. Not a changelog; git has that. This file answers one question:
*what should the next session do first?*
