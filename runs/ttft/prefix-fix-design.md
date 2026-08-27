# Keeping the model-request prefix byte-identical between turns

**Design only. Nothing was built, run, started or edited.** No `cargo` invocation, no daemon, no
model call — a peer agent held the machine for a timed measurement and CLAUDE.md hazard form 6
forbids putting a build beside somebody else's number. Every claim below is either **PROVEN** (a
line of code says so, cited `file.rs:line`) or **INFERRED** (marked, with the command that would
settle it).

**Scope boundary.** This is the *prefix* half of `STATE.md`'s TTFT entry. The *runtime* half —
Ollama's fixed ~225 ms scheduler tax and its 19% prompt-eval penalty against llama.cpp — is a
separate ADR being drafted by another agent and is not touched here. The two are independent and
they multiply: llama.cpp takes warm TTFT from 275 ms to 52 ms; this takes a churning prefix back to
warm. Neither substitutes for the other.

**The target, from the measurement already taken** (`STATE.md`, 2026-08-27):

```text
byte-identical prefix       peval    31 ms    TTFT   275 ms
one char at the END         peval   233 ms    TTFT   474 ms
one char at the START       peval   763 ms    TTFT  1064 ms   <- exactly cold
```

Marlowe's system message is 12,556–17,353 chars (~3,200–4,500 tokens) at 5,227 tok/s, so churn at
its head costs **610–860 ms per model call** — and the loop makes one call per *iteration*, not per
turn. The production-shaped cell measured the growth: **1,146 ms at turn 1 → 1,873 ms at turn 9**,
with the counterfactual (same content, changing block moved after the history) **flat**.

---

## 1. The churn inventory

Every site whose bytes can differ between two model calls of the same session. "Position" is where
the first differing byte lands, because that is what decides the cost: everything from there to the
end of the prompt is re-evaluated.

| # | Site | What changes it | Position of divergence | Status |
|---|---|---|---|---|
| 1 | `crates/marlowe-provider/src/ollama.rs:393-419` / `crates/marlowe-openrouter/src/driver.rs:251-263` — the system message is `stable ++ context ++ every InjectedMemory block`, joined `\n\n` | a new `InjectedMemory` block every turn (`crates/marlowe-daemon/src/daemon.rs:1671-1677`) | **end of the system message, before ALL conversation history** | PROVEN |
| 2 | `crates/marlowe-loop/src/engine.rs:804-811` — the ephemeral nudge is pushed onto `view.stable` | fires at 5 / 7 / 10 tool calls in a turn (`:1015-1030`) and on an empty turn (`:983-990`); appears for one call and vanishes | **immediately after governance — before the workspace map and before all history** | PROVEN |
| 3 | `crates/marlowe-daemon/src/daemon.rs:1697-1707` — a `SourceKind::Skills` block is pushed **every turn**, ranked against that turn's message | `skills::surface` (`crates/marlowe-daemon/src/skills.rs:262-287`) re-ranks per message; `SessionState::push` **appends** (`context.rs:424`) and `context_blocks` is never pruned | **end of the context tier, still inside the system message, before all history** | PROVEN — and **not named in `STATE.md` or `runs/ttft/client-path.md`** |
| 4 | `crates/marlowe-loop/src/context.rs:641-686` — `trim_to_budget` truncation and omission markers | a source going over its per-source cap rewrites the **oldest** blocks and prepends `[N earlier … omitted]` (markers land first after `kept.reverse()` at `:684`) | **wherever the oldest over-budget block sits — arbitrarily early** | PROVEN |
| 5 | `crates/marlowe-provider/src/ollama.rs:504-514` — `thinking` is stripped from every assistant message except the newest | the previous turn's assistant message **loses** its `thinking` on the next call | **at the previous assistant turn** | PROVEN that the JSON changes; **INFERRED** that the rendered prompt changes (template-dependent). Ollama only — `marlowe-openrouter` never sends `thinking` (grep for `thinking` in `driver.rs`: no hits) |
| 6 | `crates/marlowe-loop/src/engine.rs:895-900` — `FARMING_HARD_STOP` withholds tools for one call | `tools` omitted entirely (`crate::wire::tools_field`); chat templates render the tool list into the prompt | **the tool block, at or near the head of the prompt** | PROVEN that the field disappears; **INFERRED** that qwen3.5's template renders tools into the prefix |
| 7 | `crates/marlowe-loop/src/context.rs:705-731` — `clear_tool_results` masks older results in place | tool-result pressure over 20% of the window | **at the oldest masked result** | PROVEN |
| 8 | `crates/marlowe-loop/src/context.rs:735-765` — compaction | `fill_pct >= 0.70` | **everything** | PROVEN, and **legitimate**: `cache_epoch` is bumped at `:761` precisely to say so |

### What is *not* churn, checked rather than assumed

- **`identity_block()`** is `PERSONA` (`include_str!("../../../persona/v2.md")`, `daemon.rs:2166`)
  plus a `const IDENTITY_FACTS` — no clock, no interpolation. Constant for the life of the binary.
  (`daemon.rs:2185-2196`)
- **Governance** is asserted exactly once, inside the session-creation closure
  (`daemon.rs:1571`, `:1579`), with a comment saying why. `governance_prompt()` is `&'static str`
  (`daemon.rs:2293-2296`). Constant per session.
- **`workspace_map`** is computed once per session, inside the same `unwrap_or_else`
  (`daemon.rs:1599-1605`), and sorts its entries deliberately (`daemon.rs:2274-2277`). **The
  instinct survives** — because the map is not recomputed at all.
- **`SourceKind::ToolSchemas` has no producer.** A grep across `crates/` returns only `context.rs`
  and tests. Tool schemas travel in the `tools` field, not as a block — so the only way the schema
  set churns is #6.
- **`num_predict` shrinks as the budget is spent** (`ollama.rs:526-535`, from
  `run.budget.call_limits`). It is a generation option, not part of the prompt. No prefix effect.
- **`unorphan_tool_messages` (`crates/marlowe-provider/src/wire.rs:74-104`) is deterministic** given
  the view; it introduces no churn of its own.

### Two defects found in the same read, both load-bearing for the design

**(a) `trim_to_budget` drops `wire` on truncation.** `context.rs:669` is
`let truncated = Block::new(b.source, text, b.trust);` and `Block::new` sets `wire: None`
(`context.rs:243-247`). So a truncated tool result loses its `tool_name` and `tool_call_id`,
`unorphan_tool_messages` cannot link it, and it is **demoted to a `user` message**
(`wire.rs:50-53`). Today that is a legibility bug. Under §2 it would silently re-attribute a
recalled memory to the user — the exact thing that was rejected on purpose.

**(b) An assistant `tool_calls` with no answering `tool` message is already reachable, and nothing
guards it.** `SourceKind::ChildResults` is **trimmable** (`context.rs:130-136`) while the assistant
turn that announces the spawn is `SourceKind::History`, which is **not** (`context.rs:125-129`). So
the trimmer can drop a child's return and leave the parent's `run` call unanswered.
`unorphan_tool_messages` handles the mirror case — a result with no call — and **not this one**. On
the OpenAI dialect an assistant message with `tool_calls` must be followed by a `tool` message for
each id; this is the shape that produced the four HTTP 400s already recorded in `wire.rs:113-118`,
arriving from the other direction. **INFERRED** for the hosted path (no live 400 observed for this
specific direction); PROVEN that the shape is constructible.

### The cost attribution, restated

Sources 1 and 3 both put their first differing byte **inside the system message**, ahead of every
conversation message. That is why the production-shaped cell grows with turn count: the cost is not
the memory block, it is *everything after it*. Source 2 is worse per occurrence — it diverges before
the workspace map — but fires only on tool-using turns. Sources 4–7 are real and bounded; source 8
is correct behaviour.

---

## 2. The design

Four changes, in dependency order. Each is stated as the call site and what it becomes.

### The rule the design is derived from

> **The system message contains only what is constant for the life of a session-generation.
> Anything computed from the current user message rides the conversation tail. Nothing already sent
> is ever rewritten. The wire prefix changes when — and only when — `cache_epoch` changes.**

`cache_epoch` is pinned in `CONTRACTS.md` §12 as *"bumped on compaction; a stale epoch invalidates
the prefix"*. Today nothing reads it for that purpose (see §2.5). Under this design it becomes the
single declared invalidation point, and the test in §4 is its reader.

### 2.1 Injected memory rides the conversation tail as a paired tool result

This is the leading candidate from the brief, and it survives interrogation. The precedent is
`Engine::spawn`: an assistant turn carrying a `WireToolCall`, paired with a `tool` message carrying
the result (`crates/marlowe-loop/src/engine.rs:2654-2680` and `:2917-2932`), pinned on the wire by
`crates/marlowe-provider/tests/spawned_child_wire.rs`.

**The `SourceKind` does not change.** Memory stays `SourceKind::InjectedMemory`. This is the
load-bearing choice and it buys four things at once:

1. `SourceBudgets` keeps `MEMORY_TOKEN_BUDGET` = 7,000 for it (`context.rs:504`), so §5.7's pinned
   figure — *"a pinned figure that K1's precision numbers are defined at"* — is untouched.
2. `SourceKind::tier()` already maps it to `Tier::Volatile` (`context.rs:96-108`), which is where
   the conversation lives, so no tier moves.
3. `ContextView::trust_floor()` is `min` over `stable ∪ context ∪ volatile` (`context.rs:464-468`)
   and does not read `SourceKind` at all. **Layer 2 and layer 3 are bit-for-bit unaffected** — see
   §3.4.
4. The transcript projection at `daemon.rs:1851-1899` matches on `SourceKind` and sends
   `InjectedMemory` to its `_ => {}` arm (`:1898`). Keeping the announcement under the same kind
   means §B1's *"memory gets no representation in the interface"* — and `CONTRACTS.md` §13's
   *"there is no `MemoryInjected` variant in `TurnEvent`, and there must never be one"* — stay
   **structural**, not remembered. A new `SourceKind` would have fallen through to a new arm and
   nothing would have said so.

**New in `crates/marlowe-loop/src/context.rs`, beside `Block::tool_result_for` (`:283-296`):**

```rust
impl Block {
    /// The harness announcing the retrieval it performed for this turn, so the memories that
    /// follow are a REPLY rather than an instruction with no author.
    ///
    /// `SourceKind::InjectedMemory` on purpose, for BOTH blocks: the budget, the tier and the
    /// transcript projection's `_ => {}` arm all key on it, so §B1 stays structural.
    ///
    /// The class is `AgentObserved` -- the HARNESS composed this line. The memories' own floor
    /// travels on the result block below, which is what `trust_floor` reads.
    pub fn memory_call(query: &str, call_id: &str) -> Self {
        // `sanitize_line` + cap, for `Engine::spawn`'s reason at engine.rs:2665-2671: under a
        // latched floor this is a payload untrusted content may have shaped, and a newline in it
        // would let that content contribute something shaped like a harness line.
        let q = marlowe_contract::text::sanitize_line(query.trim());
        let q = match q.char_indices().nth(MEMORY_QUERY_MAX_CHARS) {
            Some((cut, _)) => format!("{}…", &q[..cut]),
            None => q.into_owned(),
        };
        let mut b = Self::new(SourceKind::InjectedMemory, String::new(), TrustClass::AgentObserved);
        b.wire = Some(WireTurn {
            tool_calls: vec![WireToolCall {
                id: call_id.to_string(),
                name: "recall".to_string(),
                arguments: serde_json::json!({ "query": q }),
            }],
            ..WireTurn::default()
        });
        b
    }

    /// The memories, as the answer to `memory_call`. The trust class is the retrieval's own floor
    /// and is never chosen here.
    pub fn memory_result(text: impl Into<String>, trust: TrustClass, call_id: &str) -> Self {
        let mut b = Self::new(SourceKind::InjectedMemory, text, trust);
        b.wire = Some(WireTurn {
            tool_name: Some("recall".to_string()),
            tool_call_id: Some(call_id.to_string()),
            ..WireTurn::default()
        });
        b
    }
}

/// Long enough to be legible in a transcript, short enough not to double the user's message.
const MEMORY_QUERY_MAX_CHARS: usize = 200;
```

**`crates/marlowe-daemon/src/daemon.rs:1671-1677` becomes** (inside `open_turn`, §4):

```rust
if !retrieved.is_empty() {
    // One id per turn. Monotonic within the session so a transcript and a journal name the
    // same call, exactly as `spawn-{n}` does at engine.rs:2656.
    let call_id = format!("mem-{}", state.volatile.len());
    state.push(marlowe_loop::Block::memory_call(message, &call_id));
    state.push(marlowe_loop::Block::memory_result(
        retrieved.text.clone(),
        retrieved.floor,
        &call_id,
    ));
}
```

Ordering: the user's message is pushed at `daemon.rs:1628-1633`, so volatile becomes
`[…, user, assistant(recall), tool(memories)]`. That is exactly the shape the loop already produces
after any real tool call, so nothing new is asked of any template. The alternative — memory *before*
the user turn, so the conversation ends on the user — was considered and not chosen: it needs the
retrieval moved above the user push for no prefix benefit (both are appends), and it makes the
recall precede the message it was keyed on.

**Both drivers, `ollama.rs:440` and `openrouter/driver.rs:278`, change from `continue` to:**

```rust
SourceKind::InjectedMemory => match block.wire.as_ref() {
    // The harness's announcement. Empty content plus tool_calls -- the shape
    // `Block::assistant_turn(String::new(), ..)` already produces for every real tool call.
    Some(w) if !w.tool_calls.is_empty() => "assistant",
    // The memories themselves, paired by id.
    Some(w) if w.tool_call_id.is_some() => "tool",
    // A trimmer note ABOUT the tier -- "[N earlier InjectedMemory block(s) omitted…]",
    // generated at context.rs:677-683 and structurally incapable of containing memory text.
    // Not a memory, so the no-user-attribution rule does not reach it.
    _ => "user",
},
```

and the `.chain(view.volatile.iter().filter(|b| b.source == SourceKind::InjectedMemory))` clause is
**deleted** from the system builder (`ollama.rs:406-410`, `openrouter/driver.rs:255`). The system
message becomes `view.stable ++ view.context`, full stop.

### 2.2 Nothing already sent is rewritten: `InjectedMemory` becomes non-trimmable

`SourceKind::trimmable` (`context.rs:124-137`) moves `InjectedMemory` into the non-trimmable arm,
beside `History` and `Brief`.

**Why this is forced rather than tidy.** Trimming and pairing are in direct opposition:

- Trimming a memory *result* orphans its assistant call → a malformed request on the hosted dialect
  (defect (b), §1).
- Repairing that orphan means deleting the assistant message → a **mid-conversation rewrite**, which
  is the thing this whole document exists to stop.
- And it bites sooner than it looks. `MEMORY_TOKEN_BUDGET` is used for **two different quantities**:
  the per-retrieval budget handed to `select_for_injection` (`daemon.rs:1660`) and the assembler's
  **cumulative, whole-session** per-source cap (`context.rs:504`). K1 defines the first. Nobody
  defined the second, and under it turn 2's injection can push turn 1's out — rewriting bytes the
  model has already been sent.

Non-trimmable resolves all three. Memory pressure then raises `fill_pct` and is answered by
compaction, which **replaces the whole volatile tier** (`context.rs:747-757`) — so the pressure is
resolvable and the *"compaction left context still above the trigger"* failure at
`engine.rs:768-780` stays unreachable from this source.

**This is not a revision of ADR-025.** ADR-025 says a source may be trimmed *only if* recoverable —
a necessary condition, not a sufficient one. Memory remains recoverable via `recall`; we are simply
declining to trim it. It is still a deliberate change to a budgeted behaviour and **should arrive
with a `DECISIONS.md` entry** (next free number is ADR-060; coordinate — the local-runtime ADR may
claim it).

**Two supporting fixes, both required and both small:**

- **`context.rs:669`** — preserve the pairing across truncation:
  ```rust
  let mut truncated = Block::new(b.source, text, b.trust);
  // `wire` is the PAIRING, not the content. A truncated result is still the answer to the call
  // that produced it; dropping the id turns it into an orphan and `unorphan_tool_messages`
  // demotes it to `user`.
  truncated.wire = b.wire.clone();
  ```
- **New in `crates/marlowe-provider/src/wire.rs`**, the mirror of `unorphan_tool_messages`, closing
  defect (b) for `ChildResults` — which stays trimmable, because a child's return can be large and
  is recoverable through `/runs`:
  ```rust
  /// Strip `tool_calls` from any assistant message whose ids are not ALL answered by a LATER
  /// `tool` message in this same request, and drop the message if that leaves it empty.
  ///
  /// Runs AFTER `unorphan_tool_messages`, which can demote an answer out of existence.
  ///
  /// The empty-message drop is not tidiness: an assistant turn with no content and no calls
  /// "reads as a turn already taken" and made a live model return nothing three turns running
  /// (engine.rs:812-828).
  pub fn unanswer_orphan_tool_calls(messages: &mut Vec<Value>) { … }
  ```
  Called at `ollama.rs:497` and `openrouter/driver.rs:319`, immediately after
  `unorphan_tool_messages`.

### 2.3 The nudge moves to the tail — and there it is free

**`crates/marlowe-loop/src/engine.rs:804-811` becomes:**

```rust
let mut view = view;
if !pending_nudge.is_empty() {
    // **The TAIL of the view, not the stable tier.** In `view.stable` this landed between
    // governance and the workspace map -- ahead of the map, ahead of every conversation
    // message -- so one nudge re-evaluated the whole prompt. At the tail it costs NOTHING:
    // it is the last thing in the prompt, and everything the next call appends after it is
    // new anyway, so no reusable bytes sit behind it.
    //
    // `[harness]` + `History` + `AgentObserved` is the channel this codebase already uses for
    // out-of-band injections into a live run -- `[steer]` at :728-732 and
    // `[user, interrupting]` at :961-965 are the same shape. It renders as `role: "user"`
    // (History + not-AgentInferred, ollama.rs:433-438). It is NOT the user's words and does
    // not claim to be: the label says harness and the trust class says AgentObserved, so
    // nothing is laundered upward.
    view.volatile.push(Block::new(
        SourceKind::History,
        format!("[harness] {}", std::mem::take(&mut pending_nudge)),
        TrustClass::AgentObserved,
    ));
}
```

Still ephemeral (pushed to the view, never to `state`), so the compounding the original comment
warns about is unchanged. The two rejected alternatives, named so nobody re-proposes them: an
**assistant**-role nudge is the model appearing to instruct itself; a **tool**-role nudge puts an
imperative in data the persona teaches the model to distrust — the argument `skills.rs:257-259`
already makes.

**Churn source #6 is deliberately left alone.** `FARMING_HARD_STOP` withholding tools
(`engine.rs:895-900`) changes the `tools` field and therefore, on a template that renders tools into
the prompt, invalidates at the head. It fires at most once per turn, it is an emergency brake, and
CLAUDE.md's own rule is that capabilities are withheld **structurally**. Paying a cold prefix there
is the right trade. Named, measured (§5), not fixed.

### 2.4 Skills: the constant half stays in the system message, the per-message half rides the tail

`skills::surface` (`crates/marlowe-daemon/src/skills.rs:262-287`) already builds two things that
answer two different questions, and its own doc comment says so (`:250-255`):

- **the count line** — *"N skill(s) installed in this profile. Search them with `use`."* — constant
  for the session;
- **the ranked hits** — *"Possibly relevant here: …"* — computed from this turn's message.

**Split it.**

```rust
/// Constant for the life of the profile. Pushed ONCE, at session creation.
pub(crate) fn library_line(skills: &SkillRegistry) -> Option<String>

/// Ranked against this turn's message. Rides the conversation tail.
pub(crate) fn hits(skills: &SkillRegistry, message: &str) -> Option<String>
```

`library_line` is pushed in the session-creation closure beside the workspace map
(`daemon.rs:1599-1605`), as `SourceKind::Skills` at `TrustClass::UserAsserted` — unchanged tier,
unchanged budget, and now constant. **It keeps the closing imperative** *"Load one with `use` and
its name to read its instructions"*, which is what makes ADR-051's argument survive: the operating
instruction stays in harness-authored system context, which `skills.rs:257-259` argues is the only
legitimate channel for it.

`hits` rides the tail on the same rails as memory, under a **new** `SourceKind::SkillHits`:

| `context.rs` site | change |
|---|---|
| `:50-90` enum | add `SkillHits` |
| `:96-108` `tier()` | `SkillHits => Tier::Volatile` |
| `:124-137` `trimmable()` | `SkillHits` joins the **non**-trimmable arm, for §2.2's reason |
| `:139-150` `ALL` | `[SourceKind; 11]` |
| `:497-517` `default_for` | `by_source.insert(SourceKind::SkillHits, pct(2))` — a reporting line, since it is not trimmable |

and the drivers get the same three-arm `match` as `InjectedMemory`, with `name: "use"`. The pair is
`assistant(use{query}) → tool(hits)`. `use`'s real results are already harness-authored
`TrustClass::AgentObserved` (`skills.rs:295-305`), so the synthetic pair is indistinguishable in
class from a real one and nothing is laundered.

**The transcript-projection trap, and it must not be skipped.** `daemon.rs:1851-1899` walks
`state.volatile`; a `SourceKind::History` block carrying `tool_calls` sets `pending = (name, target)`
(`:1857-1870`), and the **next** `SourceKind::ToolResults` block consumes it (`:1879-1899`). A
synthetic announcement pushed under `History` would therefore mislabel the next *real* tool line as
`recall` or `use`. Both pairs are kept off `History` precisely so they fall into the `_ => {}` arm at
`:1898` and set no `pending`. **A `SourceKind::SkillHits` arm must not be added to that match.**
A test pins it in §4.

**The fallback, if the new `SourceKind` is judged out of scope:** push the count line once at session
creation and drop the per-turn hits entirely. Fully prefix-stable, zero new surface, and it regresses
ADR-051's second line — the model would learn a library exists but not that one matches. Stated so
the choice is a choice.

**A bug found on the way, worth fixing whatever is decided:** `SessionState::push` for a context
block appends (`context.rs:424`), `context_blocks` is never pruned (a grep for `context_blocks`
returns exactly three sites: the field at `:394`, `assemble` at `:603`, and `durable.rs:148`), and
compaction replaces only `volatile` (`:747`). So **a Skills block accumulates every turn, for the
life of the session**, bounded on the wire only by the 10% `SourceBudgets` cap — at which point the
trimmer starts rewriting the oldest ones, which is churn source #4 firing on churn source #3.

### 2.5 `PrefixCache`: **delete it**, and give `cache_epoch` a real reader

**Delete.** Not wire up.

The argument for wiring it up would be that a cached prefix saves work. It saves nothing. What
`PrefixCache` stores is an **assembled string on our side of the socket** (`context.rs:525-548`), and
the concatenation it would avoid is a `Vec<&str>::join` over a dozen blocks — microseconds. The cache
that matters is **llama.cpp's KV cache, on the server**, and no client-side string cache can reach
it. The only client-side lever on a server-side KV cache is *emitting byte-identical bytes*, which
§§2.1–2.4 achieve **by construction** — the blocks do not change, so there is nothing to look up.

Meanwhile the cost of keeping it is precisely CLAUDE.md instance #16.
`crates/marlowe-loop/tests/compaction.rs:273-281` asserts `e.cache().lookup(…) == None` **twice**, on
a cache that has never had `store()` called on it in production — the assertion is true on a build
where the cache works, true on a build where it is broken, and true if the type were deleted. A
control asserted where it is declared rather than where it is enforced.

**Deletions, exactly:**

| File | What goes |
|---|---|
| `crates/marlowe-loop/src/context.rs:520-548` | the `PrefixCache` struct and impl |
| `crates/marlowe-loop/src/context.rs:735-765` | `compact`'s `cache: &mut PrefixCache` parameter and the `cache.invalidate(parent)` call at `:762`. **`self.cache_epoch += 1` at `:761` STAYS.** |
| `crates/marlowe-loop/src/context.rs:784`, `:801-825` | the two test uses, including `compaction_invalidates_the_cache_in_both_directions` |
| `crates/marlowe-loop/src/engine.rs:123`, `:401`, `:543`, `:557-559` | the import, the field, the initializer, the `cache()` accessor |
| `crates/marlowe-loop/src/lib.rs:42` | the re-export |
| `crates/marlowe-loop/tests/compaction.rs:273-281` | the two vacuous assertions — **replaced**, not merely deleted, by the epoch assertion below |

**`cache_epoch` stays**, for three reasons: it is pinned in `CONTRACTS.md` §12 and removing it is a
schema change; it is the *correct* signal (a compaction genuinely does invalidate the server's
prefix, and that is the one time it should); and under this design it becomes the invariant's
observable. `compaction.rs`'s deleted assertions are replaced by the honest one that was always
available:

```rust
assert!(
    e.assembler().cache_epoch() > epoch_before,
    "the epoch is now the ONLY declared invalidation point for the wire prefix"
);
```

paired with the §4 test asserting the system message is byte-identical **exactly when** the epoch has
not moved.

---

## 3. What it costs and what it risks

### 3.1 The synthetic tool call, honestly

**Does the model try to call `recall` itself?** Probably, sometimes — **INFERRED**, not measured. A
conversation containing one assistant `recall` call per turn is a strong few-shot pattern. Three
mitigating facts and one measurement:

- `recall` is a **real, exposed, runnable** builtin (`crates/marlowe-tools/src/builtin.rs:36-39`;
  exposed by `CapabilityProfile::interactive`, `crates/marlowe-loop/src/profile.rs:183-189`). So the
  synthetic call names a tool that is in the request's `tools` array — no dialect risk, and an
  imitation executes correctly rather than erroring.
- §5.5 *wants* `recall` used: *"recall is recovered by making the agent's explicit memory search tool
  excellent"*. Auto-injection is gated at the declared operating point and withholds unmatured
  beliefs entirely, so `recall` is the only path to those. Demonstrating the tool is closer to the
  discovery bootstrap ADR-051 had to build for skills than it is to a cost.
- Runaway imitation is already bounded by `FARMING_SOFT_NUDGE` / `FIRM` / `HARD_STOP`
  (`engine.rs:390-395`).
- **The measurement:** count `recall` invocations per turn in the journal, before and after, on the
  same ten prompts. If it rises materially, the fallback is a reserved name — at the cost that the
  call then names a tool absent from `tools`, whose legality on hosted providers is **UNKNOWN**.

**Does it appear in the transcript?** No, and structurally so — §2.1 point 4 and the §2.4 trap. Both
synthetic pairs sit on `SourceKind`s that the projection's `match` sends to `_ => {}`
(`daemon.rs:1898`), and nothing emits a `TurnEvent::ToolLine` for them (the only emitters are the
engine's real tool path and `Engine::spawn`, `engine.rs:2906-2917`). §B1 and `CONTRACTS.md` §13 hold.
It **does** appear in `--dev`'s conversation dump, which is where instrumentation belongs.

**Does it confuse `(action, target)` adjudication?** No. Adjudication runs on `ModelStep::ToolCall`
inside `Engine::prepare_call`; the synthetic pair is pushed into `SessionState` by the daemon and
never becomes a `ModelStep`. It is history, not a request. **One thing the implementer must not do:**
call `Provenance::attribute` on the memory text. `taint_for` looks up argument values in the
attributed map (`provenance.rs:89-102`), and a memory attributed as `AgentObserved` would let an
untrusted belief's exact tokens ride into a Target at a class they did not earn. Today the daemon
attributes only the user's message (`daemon.rs:1626`); that must stay true.

**Does it interact with `MAX_EXPOSED_TOOLS`?** No. The cap is 14
(`crates/marlowe-tools/src/exposure.rs:35`) against 12 builtins plus two MCP slots, and it governs
**exposure**, not history. `recall` and `use` are already exposed; the design adds no tool, registers
nothing, and consumes no slot.

### 3.2 The real behavioural risk: memory arrives as *data* rather than as *context*

This is the cost I would flag first, and it is not about the wire. As a system message, recalled
facts were unattributed truth. As a `tool` result they are data — and the persona correctly teaches
the model to weigh tool data as claims. **The mechanism could be made less effective while every
shape test stays green**, which is this project's signature failure.

**Mitigation, and it is cheap and churn-free:** state the convention once, in `governance_prompt()`
(`daemon.rs:2293-2296`) — stable tier, harness-authored, constant, so it costs no prefix. One
sentence to the effect that results from `recall` are the harness's own record of this profile, not
third-party content. That puts the operating instruction in the channel `skills.rs:257-259` argues is
the legitimate one, and leaves the memories themselves unframed.

**It must be verified behaviourally, not by a shape test.** `marlowe_eval`'s §4 wire is unaffected —
it never builds a request body — so a quality regression here is invisible to the scoreboard. It
needs the live probe in §5, item 4.

### 3.3 Costs and second-order effects, listed

| Cost | Size |
|---|---|
| Two extra messages per turn instead of one system fragment | ~30–60 tokens of framing. Against 610–860 ms saved per call, this is not close. |
| `estimate_tokens` counts `text` only (`context.rs:157-159`), so the announcement's `arguments` are budgeted at 0 | Pre-existing and consistent — every real assistant tool-call block already under-counts this way. Named, not fixed here. |
| `InjectedMemory` and `SkillHits` become non-trimmable | Memory pressure now reaches compaction instead of being trimmed. Compaction replaces the whole volatile tier, so it is bounded. Deliberate; needs the ADR. |
| A new `SourceKind` variant | `SourceKind` is not pinned in `CONTRACTS.md`; `ContextView`'s shape (§12) is unchanged. `SourceKind::ALL` and `SourceBudgets::default_for` are the two sites that must move together. |
| Two provider adapters change identically | The standing hazard: a fix in one is not a fix in both. `openrouter/driver.rs:251-263` and `:278` must move with `ollama.rs:393-419` and `:440`. The §4 test runs against **both** drivers. |

### 3.4 Layer 2 and layer 3: what happens to the `TrustClass` and to the floor

**Nothing.** Stated precisely, because the brief treats any change here as blocking:

- The memory result block keeps `retrieved.floor` verbatim (`daemon.rs:1675`), which is `min` over
  the injected memories' `effective_trust` (`crates/marlowe-daemon/src/memory.rs:307-312`).
- `ContextView::trust_floor()` is `self.blocks().map(|b| b.trust).min()` (`context.rs:464-468`).
  `blocks()` chains all three tiers (`:448-450`) and **never reads `SourceKind` or the wire role**.
  The block stays in `volatile` with the same class, so the floor is the same value.
- `Run::latch_trust_floor` (`engine.rs:865`) reads that floor and latches monotonically; the
  threshold is `marlowe_permission::blocks_composed_targets`, the same function the adjudicator
  refuses on. Unchanged input, unchanged output.
- `Provenance::taint_for` takes `view.trust_floor().min(latched)` (`provenance.rs:89-92`). Unchanged.
- The announcement block is `AgentObserved` — above `UntrustedContent`, so it cannot *lower* the
  floor, and it does not raise it, because `min` is taken over every block.
- The two existing tests that establish taint through an `InjectedMemory` block
  (`crates/marlowe-loop/tests/spawn_and_budget.rs:797`, `:909`) push the block directly and assert on
  the floor. They are unaffected and must stay green **and non-vacuous** — they were the family
  CLAUDE.md flagged, and this design does not touch the state they measure.

**CLAUDE.md's standing correction is untouched.** Injected memory remains the only source of
`UntrustedContent` in a parent run's window, and `ingest` still has exactly one caller
(`crates/marlowe/src/adapter.rs:304`, the eval adapter), so layer 3's latch remains unreachable in the
shipped interactive product. This design neither closes that nor makes it worse, and it does not
change what `blocks_composed_targets` sees.

**One asymmetry the implementer should know:** with `InjectedMemory` non-trimmable, the hole
`provenance.rs:82-88` describes — *"the assembler could drop an untrusted block to stay inside its
budget and the floor would rise again"* — becomes **unreachable from the memory path** rather than
merely covered by the latch. That is a strict improvement, and it is a side effect, not the goal.

---

## 4. The test that proves it

`crates/marlowe-provider/tests/prefix_stability.rs`, patterned on
`crates/marlowe-provider/tests/spawned_child_wire.rs`.

### What it must not be

A test that hand-builds two `ContextView`s and compares `request_body` outputs proves that
`request_body` is a function. The defect is a **seam**: the daemon decides what goes into the
session, the assembler decides what goes into the view, and the driver decides what goes into the
system message. Nothing that tests halves can see a seam — the third time this project has said so
(`spawned_child_wire.rs:1-24`).

### The seam this needs, and the one refactor it requires

The per-turn state mutation lives inline in `Daemon::ask_streaming_with` (`daemon.rs:1085`, body
`:1556-1748`) and cannot be reached without a model. Extract it — it is ~190 lines inside a ~700-line
function, and the extraction is good independent of the test:

```rust
/// Everything a turn does to the session BEFORE the loop is entered: session creation with
/// identity, governance, the workspace map and the skills library line; the user's turn and its
/// attribution; §4.2 retrieval and its paired blocks; this turn's skill hits.
///
/// `pub` so it can be asserted on -- the same reason `workspace_map` and `governance_prompt`
/// are (daemon.rs:2219, :2293). `ask_streaming_with` calls this and does none of it itself.
pub fn open_turn(
    &mut self,
    session: &str,
    message: &str,
    resumed: Option<Checkpoint>,
    now_ms: i64,
) -> SessionMemory
```

`daemon.rs:1556-1748` becomes
`let SessionMemory { mut state, mut provenance } = self.open_turn(session, message, resumed, clock.now_ms());`

**Guarded, because a `pub` function a test calls and production does not is instance #16 again.** Two
guards, in `crates/marlowe-daemon/tests/`, in the style of the existing `skills.rs:528-545` source
grep:

```rust
let src = include_str!("../src/daemon.rs");
assert!(src.contains("self.open_turn("),
    "ask_streaming_with must open its turn through open_turn, or this test asserts about a \
     function the product does not call");
assert_eq!(src.matches("Block::memory_call(").count(), 1,
    "open_turn is the ONLY producer of the memory pair; a second one would churn the prefix \
     from a site nothing checks");
```

A grep is weaker than a call graph, and it is the pattern already in this tree. Named as weak.

### The test

```rust
#[test]
fn the_system_message_is_byte_identical_across_two_turns_of_one_session() {
    // 1. A real daemon, in-process (control_plane.rs:86 and provider_switching.rs:31 do this;
    //    `Daemon::open` needs no socket). A profile with at least one belief that will be
    //    retrieved, and at least one installed skill.
    let mut daemon = Daemon::open(fixture_config()).expect("the daemon opens");

    // 2. TURN ONE, through the real seam -- not a hand-built SessionState.
    daemon.open_turn("tui", "what did I say my favourite colour was?", None, T0);

    // 3. The REAL loop over the state the daemon just built, so a view no driver was ever called
    //    with cannot be what is asserted on. ViewRecorder is spawned_child_wire.rs:44-68: it keeps
    //    the ContextView itself, not its rendering -- a test that reconstructed a view from a
    //    rendered string would be asserting about its own reconstruction.
    let view1 = drive_one_turn(&mut daemon, ViewRecorder::default()).last_view();

    // 4. TURN TWO, same session, a DIFFERENT message so retrieval and skill ranking both move.
    daemon.open_turn("tui", "and what car do I drive?", None, T1);
    let view2 = drive_one_turn(&mut daemon, ViewRecorder::default()).last_view();

    // 5. The real request_body, BOTH drivers -- a fix in one is not a fix in both.
    for (name, sys1, sys2) in [
        ("ollama",     ollama_system(&view1),     ollama_system(&view2)),
        ("openrouter", openrouter_system(&view1), openrouter_system(&view2)),
    ] {
        // ── THE PRECONDITIONS. Without these the equality below is vacuous. ──────────
        assert!(!memory_text(&view2).is_empty(),
            "{name}: nothing was injected on turn 2; an empty belief store passes the equality \
             below on a build with no fix at all");
        assert!(memory_text(&view2) != memory_text(&view1),
            "{name}: the fixture retrieved the same memory twice, so nothing was being asked");
        assert_eq!(view1.cache_epoch, view2.cache_epoch,
            "{name}: no compaction happened, so the epoch must not have moved");

        // ── THE ASSERTION. ──────────────────────────────────────────────────────────
        assert_eq!(sys1, sys2,
            "{name}: the system message changed between two turns of one session. llama.cpp \
             reuses its KV cache only for a byte-identical prefix, and a change HERE is ahead of \
             every conversation message, so the WHOLE prompt is re-evaluated. Measured: \
             275 ms -> 1,064 ms, growing 1,146 -> 1,873 ms by turn 9. First difference at byte {}",
            first_diff(&sys1, &sys2));

        // ── AND THE MEMORY STILL REACHED THE MODEL, on the right role. ──────────────
        // Without this, deleting retrieval entirely passes the assertion above -- a far worse
        // bug. Same reasoning as system_message_shape.rs:96-99.
        assert_eq!(roles_carrying(&view2, memory_text(&view2)), vec!["tool"],
            "{name}: a recalled fact must reach the model, and must NOT arrive as `user` -- \
             indistinguishable from something they just said");
        assert_eq!(count_role(&view2, "system"), 1, "{name}");
        assert_eq!(first_role(&view2), "system", "{name}");
    }
}
```

### What it would read **if the fix were absent**

Turn 1's system message ends `… ++ skills_hits_1 ++ memory_1`. Turn 2's ends
`… ++ skills_hits_1 ++ skills_hits_2 ++ memory_1 ++ memory_2` — the drivers chain **all**
`InjectedMemory` blocks (`ollama.rs:406-410`) and the assembler carries every accumulated `Skills`
block (`context.rs:603`). The strings differ, `assert_eq!` fails, and `first_diff` names the byte,
which is inside the system message and ahead of the whole conversation. **It is not a proxy.**

### The negative controls

Three, because the positive assertion has three distinct ways to be vacuously true.

**Control 1 — the fixture is inert.** The most likely silent failure is an empty belief store or a
gate that abstains on both turns: the system messages then match on *any* build. Closed by the
preconditions above **and** by a second test that rebuilds the **old** concatenation rule from the
same two recorded views and asserts those two **differ**:

```rust
#[test]
fn control_the_fixture_would_have_churned_under_the_old_rule() {
    // stable ++ context ++ every InjectedMemory block -- ollama.rs:393-419 as it was.
    assert_ne!(old_system_rule(&view1), old_system_rule(&view2),
        "the fixture injects nothing that differs between turns, so the equality test above is \
         green for a reason that has nothing to do with the fix");
}
```

**Control 2 — the comparison cannot fail.** Assert a mutation the design says *should* change the
system message actually does: assert a governance constraint between the turns and assert
`sys2 != sys3`. A test that compares two identical constants also passes.

**Control 3 — the epoch is a real reader.** Force a compaction between turns (seed history past
`COMPACTION_TRIGGER`), and assert the system message **does** change and `cache_epoch` moved,
together. This is what makes §2.5's retained `cache_epoch` a live control rather than the dead
`PrefixCache` in new clothes.

### The three companion tests

```rust
#[test] fn a_nudge_does_not_touch_the_system_message()          // §2.3
// Drive a turn to FARMING_SOFT_NUDGE (5 tool calls). Capture the view on the call BEFORE and the
// call AFTER the nudge fires; assert the system messages are equal AND the nudge text is in the
// LAST message of the later one. Today the nudge is in system[0] between governance and the
// workspace map, so this fails loudly.

#[test] fn the_synthetic_pairs_never_reach_the_transcript()      // §2.4's trap
// Drive one memory-injected turn AND one real tool call, replay through the projection at
// daemon.rs:1851-1899, and assert (a) no Event::Tool names `recall` or `use`, and (b) the real
// tool line names ITS OWN verb -- the `pending` leak, which would mislabel it.

#[test] fn a_trimmed_pairing_never_becomes_a_user_message()      // defects (a) and (b)
// A view over the InjectedMemory / ChildResults budget. Assert no message carrying memory or a
// child's return has role `user`, and no assistant `tool_calls` id is left unanswered.
```

### The live confirmation, which no unit test replaces

CLAUDE.md: *"Budget one real end-to-end run per milestone as verification, not as a demo"*, and
*"the instrument that closes it is `--dev`'s outbound-request dump — the bytes the running process
sent."* A test on the source cannot see a stale deployment (`persona_emission.rs`, M2 C2d).

```bash
# Two turns of one session against the SHIPPED binary, daemon under --dev.
# daemon.rs:1294 dumps each outbound system message; diff turn 1's against turn 2's.
# Expect: zero differing bytes, and Ollama's prompt_eval_count on call 2 near zero.
```

Recorded as `runs/ttft/prefix-fix-live.txt`. **Not run here** — it needs a build and a model, and both
were forbidden.

---

## 5. What I could not establish, and the command that settles each

| # | Open | Why it is open | The command |
|---|---|---|---|
| 1 | **Does dropping `thinking` from an older assistant message change the rendered prompt?** (churn #5) | `ollama.rs:504-514` provably removes the field; whether qwen3.5's built-in renderer emits prior-turn `<think>` blocks at all is a property of the template, and `/api/show`'s template field is known to lie on this architecture (M2 C2f). | Two `/api/chat` calls, identical but for `thinking` on the second-to-last assistant message; compare `prompt_eval_count`. Equal ⇒ no prefix cost, close the item. |
| 2 | **Does withholding `tools` invalidate at the head?** (churn #6) | Same reason. The tool list is rendered by the template, and where it lands in the token stream is not visible from our side. | Two calls, identical but for the presence of `tools`; compare `prompt_eval_count` and `prompt_eval_duration`. |
| 3 | **How often does the model imitate the synthetic `recall` call?** (§3.1) | Behavioural; unmeasurable by reading. | Ten fixed prompts before and after; count `tool_completed` journal events with `tool=recall` per turn. |
| 4 | **Does memory-as-tool-result reduce how much the model uses recalled facts?** (§3.2) | The real risk of this design, and `marlowe_eval` cannot see it — the §4 wire never builds a request body. | A live A/B on a fixed set of memory-dependent prompts, judged on whether the answer uses the recalled fact. Run it **with and without** the `governance_prompt()` sentence, or the mitigation is asserted rather than measured. |
| 5 | **Is an assistant `tool_calls` naming a tool absent from `tools` accepted?** (§3.1 fallback) | Only matters if the reserved-name fallback is taken. Not in any spec readable from here. | Send such a request to OpenRouter and to Ollama; record the status. |
| 6 | **What does the whole fix buy, end to end?** | Everything above is a component measurement. | Re-run the peer's production-shaped growth cell (`runs/ttft/phase_i.py`) against the fixed binary. Expect the turn-1→turn-9 curve to go flat, matching the counterfactual already measured. **It needs a control:** the same run on the unfixed binary, on an otherwise idle machine (hazard form 6). |
| 7 | **Do all consumers of `SourceKind::ALL` handle an eleventh variant?** | I did not read `hp10_budgets.rs` or every consumer. | `grep -rn "SourceKind::ALL" crates/` and read each. |

### One thing I deliberately did not decide

The next free ADR number is **060** (`DECISIONS.md` runs to ADR-059). The local-runtime agent may be
claiming it. Whoever lands first takes it; this design needs an entry for two things and only two:
**`InjectedMemory` and `SkillHits` become non-trimmable** (a deliberate change to a budgeted
behaviour, arguing that ADR-025 states a necessary condition and not a sufficient one), and
**`PrefixCache` is deleted while `cache_epoch` is retained and given a reader**.
