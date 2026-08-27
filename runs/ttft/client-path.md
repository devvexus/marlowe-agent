# The client side of time-to-first-token

**Static analysis only. Nothing was built, run, measured or started.** A peer agent (`ttft-measure`)
owned the machine for the duration; CLAUDE.md hazard form 6 forbids taking a wall-clock number
beside a build, and it equally forbids *creating* the build beside somebody else's number. Every
claim below is either **PROVEN** (a line of code says so) or **INFERRED / UNKNOWN** (with the
experiment that would settle it). Nothing is stated as measured that was not measured.

The peer's wire numbers are taken as given: warm TTFT from Ollama **1,064 ms** median (n=22) —
226 ms `load_duration`, 782 ms prompt eval, ~54 ms scheduling, 0.5 ms TCP.

---

## 0. The one-paragraph answer

**The read path is genuinely incremental and the first thinking token is forwarded, projected and
painted — no hop between the socket and the screen buffers a whole turn.** What Marlowe adds is
three things, in descending size: a **synchronous cross-encoder rerank before the request is sent**
(up to ~190 ms on CPU, ~0 on an empty belief store), a **50 ms input-poll that a token cannot
wake** (mean 25 ms, worst 50 ms, derived from code), and a **redundant `/api/tags` round trip per
turn** (cost unknown). There is also one **conditional total failure**: if the model puts its
reasoning in `content` rather than in Ollama's `thinking` field, every byte is held unrendered
until `</think>` arrives — measured in the source's own header at **frame 846 of 848**. And on the
`marlowe --ask` path there is no streaming at all: the whole turn is buffered and reasoning is
discarded, so perceived TTFT there is the entire turn.

---

## 1. The latency budget, Enter keypress → first painted character

TUI path, warm daemon, warm Ollama, no tools, a session that already exists.

| # | Stage | On critical path | Cost | Evidence |
|---|---|---|---|---|
| A | Key → `Intent::Send` → worker thread spawned | yes | µs | `crates/marlowe/src/tui.rs:609`, `:760`; `crates/marlowe-daemon/src/live.rs:246`, `:192`, `:201` |
| B | Client connect, token file read, request write | yes | sub-ms, **unmeasured** | `crates/marlowe-daemon/src/client.rs:131`–`:144`, `:203`; `crates/marlowe-daemon/src/auth.rs:79` |
| C | Daemon accept, auth preamble, request parse | yes | sub-ms; **serialising** | `crates/marlowe-daemon/src/daemon.rs:2004`–`:2013`, `:2041`, `:2089` |
| **D** | **`Availability::probe` — a whole `/api/tags` HTTP round trip, per turn** | **yes** | **UNKNOWN — needs measurement** | `crates/marlowe-daemon/src/daemon.rs:1191` → `crates/marlowe-provider/src/ollama.rs:128`–`:161` → `crates/marlowe-provider/src/http.rs:96`–`:210` |
| E | Registry built **twice**, scope built twice, engine + tool host constructed | yes | µs (wasteful, not slow) | `crates/marlowe-daemon/src/daemon.rs:1235`, `:1279`, `:1243`, `:1490`, `:1257`, `:1503`; `:491`–`:505` |
| F | `workspace_map` — BFS `read_dir`, depth 2, ≤200 entries | **first turn of a session only** | UNKNOWN | `crates/marlowe-daemon/src/daemon.rs:1599` → `:2219`–`:2285` |
| **G** | **§4.2 retrieval: lexical over every belief + up to 10 cross-encoder pairs** | **yes** | **~182 ms p50 / 191 ms p95 on CPU (crate's own figure, NOT re-measured here); ~0 with an empty store** | `crates/marlowe-daemon/src/daemon.rs:1656`–`:1661` → `crates/marlowe-daemon/src/memory.rs:245`–`:327` → `crates/marlowe-memory/src/retrieve.rs:696`, `:289`, `:298`–`:304` |
| H | Skills surfaced and ranked against the message | yes | µs | `crates/marlowe-daemon/src/daemon.rs:1695` → `crates/marlowe-daemon/src/skills.rs:263`–`:287` |
| I | `Assembler::assemble` — clones every block, trims to per-source budgets | yes | sub-ms (≤~100 KB memcpy) | `crates/marlowe-loop/src/engine.rs:736` → `crates/marlowe-loop/src/context.rs:585`–`:686` |
| J | `request_body` — concatenate the system tier, `to_string()` the JSON | yes | sub-ms | `crates/marlowe-provider/src/ollama.rs:393`–`:419`, `:369` |
| K | Fresh TCP connect (`Connection: close`), two `write_all`s, **no `TCP_NODELAY`** | yes | sub-ms, **unmeasured** | `crates/marlowe-provider/src/http.rs:364`–`:378`; the only `set_nodelay` in the workspace is `crates/marlowe-net/src/lib.rs:403` |
| — | **WIRE — the peer's 1,064 ms** | — | 1,064 ms | measured by `ttft-measure` |
| L | First NDJSON line read | yes | **incremental — PROVEN** | `crates/marlowe-provider/src/http.rs:274`–`:307`, `:317`–`:345` |
| M | Provider folds the frame, `thinking` → `on_reasoning` | yes | µs — **immediate, PROVEN**, but see §3 | `crates/marlowe-provider/src/ollama.rs:704`–`:717` |
| N | Loop emits `TurnEvent::ReasoningDelta` synchronously | yes | µs | `crates/marlowe-loop/src/engine.rs:912`–`:915` |
| O | Daemon: `to_wire`, push a `RunFrame` under the plane mutex, `write_all` + `flush` per event | yes | µs | `crates/marlowe-daemon/src/daemon.rs:238`, `:285`–`:289`, `:1529`–`:1536`, `:2138`; `crates/marlowe-daemon/src/protocol.rs:308`–`:316` |
| P | Client `read_line` → `mpsc::send` | yes | µs | `crates/marlowe-daemon/src/client.rs:206`–`:245`; `crates/marlowe-daemon/src/live.rs:214` |
| **Q** | **mpsc → UI thread: `event::poll(50 ms)`, which a token cannot wake** | **yes** | **[0, 50] ms uniform; mean 25 ms — DERIVED FROM CODE** | `crates/marlowe/src/tui.rs:35`, `:594`–`:603`, `:760`–`:761`; `crates/marlowe-daemon/src/live.rs:416`–`:449`, `:456`–`:458` |
| R | Project to `Entry::Reasoning`; rebuild **the whole transcript** into lines | yes | UNKNOWN, grows with conversation | `crates/marlowe-daemon/src/project.rs:226`–`:231`; `crates/marlowe-surface/src/render.rs:557`, `:630`, `:655`–`:672` |
| S | ratatui cell diff + terminal write | yes | UNKNOWN, typically single-digit ms | `crates/marlowe/src/tui.rs:761` |

**Client-added total, TUI, warm, populated belief store, CPU rerank:**
roughly **25 ms (mean) + up to ~190 ms + one `/api/tags` round trip + one full-transcript render**,
against a 1,064 ms wire. On an **empty** belief store, G collapses to ~0 and the client's
contribution is dominated by Q's 25 ms and D's unknown.

---

## 2. What I proved about the read path (question 1)

**`post_ndjson` does not buffer. This is the thing you asked me to look hardest for, and it is
clean.**

- `crates/marlowe-provider/src/http.rs:353`–`:425` writes the request, reads the status line and
  headers, and returns an `NdjsonStream` holding a live `BufRead`. It never reads the body.
- `NdjsonStream::next_value` (`:274`–`:307`) does one `read_line` and parses that line. It yields
  per JSON object, which for Ollama is per token.
- `ChunkedBody` (`:311`–`:345`) implements `Read` over `Transfer-Encoding: chunked` framing. The
  outer `BufReader::read_line` calls `fill_buf` → `ChunkedBody::read` with an 8 KiB buffer;
  `want = buf.len().min(self.remaining)` (`:341`) clamps to the current chunk, and the inner
  `BufReader::read` returns whatever bytes are already there. **Nothing blocks waiting to fill a
  buffer.**
- The only `read_to_string` on the streaming path is `:411`, inside the **non-2xx error branch**.
  The `read_to_end`-shaped code at `:163`–`:199` belongs to `request()`, which serves `post_json` /
  `get_json` only — and which its own doc comment (`:248`–`:265`) correctly identifies as fatal to
  streaming.

The comment at `crates/marlowe-provider/src/ollama.rs:627`–`:629` is **stale**: it says *"Layer 2
of the loop still emits one `TextDelta` per `Say`, so this alone does not put tokens on screen."*
That has not been true since `engine.rs:909`–`:915` wired the split callbacks; `engine.rs:1038`
now *suppresses* the whole-`Say` re-emit for a streaming driver. Harmless, but it reads as a
description of a defect that no longer exists.

## Buffering between layers (question 2)

Every hop forwards immediately. Stated as boundaries, because that was the question:

| Hop | Waits for a boundary? |
|---|---|
| socket → `NdjsonStream` | one **line** = one Ollama frame = one token. Correct granularity. |
| `NdjsonStream` → provider fold | no. `ollama.rs:689` loops per frame. |
| provider → `on_reasoning` / `on_delta` | **no for reasoning** (`:711`). **Yes for speech, conditionally** — see §3. |
| loop → `TurnSink` | no. Synchronous `emit` inside the callback (`engine.rs:914`). |
| daemon sink → socket | no. `write_all` + `flush` per event (`daemon.rs:2138`, `protocol.rs:315`). |
| socket → client callback | no. `read_line` per event (`client.rs:210`). |
| client → UI thread | **unbounded mpsc, non-blocking send** (`live.rs:214`) — but the *receiver* only runs on a tick. See §4. |
| UI → terminal | one full `term.draw` per tick. |

---

## 3. Does the model's first token reach the surface? (question 3) — **mostly yes, with one
conditional total failure**

**In the TUI it does, and it paints.** `thinking` / `reasoning` / `reasoning_content` deltas are
forwarded verbatim the moment they arrive (`crates/marlowe-provider/src/ollama.rs:708`–`:717`),
carried as `Event::Reasoning` (`daemon.rs:238`), folded into `Entry::Reasoning`
(`crates/marlowe-daemon/src/project.rs:226`–`:231`), and drawn as a collapsed one-liner
`thinking… N characters` (`crates/marlowe-surface/src/render.rs:655`–`:672`). Nothing is dropped,
nothing waits for `content` to start.

**But there is a path where nothing is painted for the whole reasoning phase.**
`crates/marlowe-provider/src/ollama.rs:685`:

```rust
let mut closed = !self.thinking;
```

`config.thinking` defaults to `true` (`crates/marlowe-daemon/src/daemon.rs:157`), so `closed`
starts **false**. `ThinkSplitter` starts `inside: false` (`crates/marlowe-provider/src/think.rs:94`–
`:106`, `Default`), because the opening `<think>` is consumed by the chat template and never
reaches the wire. So for a model that emits its reasoning as **plain `content` before a closing
`</think>`** — rather than in Ollama's `thinking` field — every segment classifies as
`Segment::Speech`, and `ollama.rs:747`–`:750` pushes it into `held` and renders **nothing**. It is
only resolved after the stream closes (`:798`–`:806`).

The source's own header records the measured instance (`ollama.rs:655`–`:658`): a **848-frame turn
where `</think>` arrived at frame 846**. On such a model the user's perceived TTFT is not
1,064 ms — it is the whole turn.

This is a deliberate, documented trade (the rule *"nothing renders as speech until the think block
is known shut"*), and it is correct for its stated purpose. What it is not is free, and it is
invisible to any test that asserts on the final answer. It fires on **model choice**, not on
configuration — so a model swap can turn TTFT from 1 s into 30 s with no code change and nothing
reporting it.

**On `marlowe --ask` the answer is flatly no.** `crates/marlowe/src/agent.rs:257`–`:265` collects
every event into a `Vec` and calls `render` only after the daemon closes the connection; the
comment at `:251`–`:256` states the reason (retraction resolution needs the whole list, and stdout
cannot be un-written). And `agent.rs:580` is `Event::Reasoning { .. } => {}` — reasoning is
discarded outright. **Perceived TTFT on `--ask` is the entire turn duration.** If any TTFT number
in this project was taken with `--ask`, it is measuring something else.

---

## 4. The repaint cadence (question 4) — **the coalescing defect**

`crates/marlowe/src/tui.rs:587`–`:603`, `:760`–`:761`:

```
loop {
    advance(session, app, now);          // drains the mpsc
    let timeout = 50;                     // ANIMATION_TICK_MS, or next_beat_in() == 50
    if event::poll(timeout)? { ...handle terminal input... }
    advance(session, app, now);          // drains the mpsc
    term.draw(...)?;                      // paints
}
```

- `ANIMATION_TICK_MS = 50` (`tui.rs:35`).
- `LiveSession::next_beat_in` returns `Some(50)` while a turn is in flight
  (`crates/marlowe-daemon/src/live.rs:456`–`:458`).
- `StatusState::Thinking.samples_amplitude()` is `true`
  (`crates/marlowe-view/src/model.rs:90`–`:92`), so the animation branch also yields 50.

**`crossterm::event::poll` blocks on terminal input. A message on the mpsc channel cannot wake
it.** A delta that lands 1 ms after the poll begins waits 49 ms for `advance` at `:760` to drain it
and `term.draw` at `:761` to paint it.

**Added latency: uniform on [0, 50] ms, mean 25 ms, worst case 50 ms.** This is derived from the
code, not measured — but it is derived from a constant and a blocking call, so the derivation is
tight. It applies to *every* token, not only the first, which also means streaming renders in 20 fps
bursts rather than smoothly.

Two secondary notes on the render:

- `render::transcript_lines` (`crates/marlowe-surface/src/render.rs:557`) rebuilds the **entire**
  transcript every frame, markdown-parsing every model turn (`:630`), with **no memoization**. At
  20 fps for a whole turn this is O(conversation) CPU on the UI thread, and one frame's worth of it
  sits between "the channel was drained" and "characters appeared". Unmeasured. The reasoning block
  itself is exempt while collapsed (`:680`–`:683` says so explicitly, and it is right).
- The `--watch` window is a different surface and polls the control plane every **120 ms**
  (`crates/marlowe/src/watch.rs:56`). Not the conversation path, but if a TTFT reading was taken
  in a watch window, that is a 120 ms floor plus a round trip.

---

## 5. Work before the request is sent (question 5)

**Retrieval runs synchronously on the turn's critical path and nothing about it is cached or
precomputed.** `crates/marlowe-daemon/src/daemon.rs:1656`–`:1661` calls `self.memory.retrieve(...)`
between the user's message being pushed and `engine.continue_from`. Inside
(`crates/marlowe-daemon/src/memory.rs:245`–`:327` → `crates/marlowe-memory/src/retrieve.rs:696`):

- `injection_candidates` + a `RetrievalScope::Profile` filter — every belief in the store, not just
  the session's (`memory.rs:302`, and the comment there is honest about the consequence).
- `lexical::score_all` over all of them (`retrieve.rs:761`).
- `dense_for` — **a no-op.** `DaemonMemory.vectors` is `VectorStore::default()`
  (`memory.rs:112`, `:199`), so the dense cue scores 0.0 for every candidate. **The embedder is not
  on the daemon's retrieval path at all.** That is a stated limitation (`memory.rs:107`–`:111`),
  and for TTFT purposes it is good news: no query embedding, no ONNX session, no GPU call.
- features, frozen gate, session pruning — all in-memory arithmetic.
- **the rerank**: `RERANK_BUDGET = 10` cross-encoder pairs (`retrieve.rs:289`, `:846`–`:847`).

The cost figure is the crate's own, at `retrieve.rs:298`–`:304`: *"On the shipped pins (1
intra-thread, batch 1, CPU) … **182 / 191 ms** for the shipped depth-10 path."* **That is a number
taken on a different system for a different question and I am citing it, not measuring it** —
CLAUDE.md's own rule about carrying a measurement across a boundary applies to me here. It is the
right order of magnitude and it is not evidence about this daemon.

Two things make it conditional:

- **An empty belief store costs ~0.** `score_slate` returns `None` immediately on an empty slate
  (`retrieve.rs:584`–`:586`). So this defect is invisible on a fresh profile and appears as the
  profile fills.
- **The provider is resolved at daemon boot, not pinned.** `CrossEncoder::load_auto(..., RerankChoice::Auto, Probe::Device, ...)`
  (`memory.rs:172`–`:178`). On CUDA the same stage is far cheaper (the crate quotes CUDA batched
  3.4 ms vs CPU sequential 15.2 ms per pair at `memory.rs:255`–`:259`). **So this cost depends on
  how much VRAM was free when the daemon started.** `marlowe --status` reports which one resolved
  (`memory.rs:220`–`:233`) — read it before believing any TTFT number.

**The other pre-request work**, all on the critical path:

- **A full `/api/tags` HTTP round trip, every turn** (`daemon.rs:1191`). See defect 1.
- `builtin_registry()` constructed **twice** per turn (`daemon.rs:1235` and `:1279`), each building
  ~11 registrations with heap-allocated description strings. Microseconds; pure waste.
- `WorkspaceScope::new()` twice (`:1243`, `:1490`). Free — it is a `cfg` check
  (`crates/marlowe-permission/src/scope/mod.rs:232`–`:240`).
- `workspace_map` — a BFS `read_dir` to depth 2, ≤200 entries, sorted (`daemon.rs:2219`–`:2285`).
  **First turn of a session only**, because it sits inside the `sessions.remove(...).unwrap_or_else`
  closure at `:1567`–`:1608`. On this checkout (`runs/`, `target/`, `.claude/worktrees/`) a cold
  walk is not obviously cheap. `WALK_SKIP` prunes at depth 1 (`:2256`).
- **No journal read and no fsync before the model call.** `drive_inner` records nothing before the
  driver call on a first iteration (`crates/marlowe-loop/src/engine.rs:696`–`:927`); the
  `Checkpointed` append is after the loop (`:657`). The journal *is* `synchronous = FULL` WAL
  (`crates/marlowe-journal/src/store.rs:51`–`:52`) and `verify_chain` is O(n) with an Ed25519
  recompute per event (`crates/marlowe-journal/src/journal.rs:138`), but both are **daemon
  startup**, not per turn. That matters only for `marlowe --ask` with no daemon running, which
  opens one in-process (`crates/marlowe/src/agent.rs:230`).

---

## 6. Findings of the "declared control nothing reads" family

**`PrefixCache` is dead. Nothing stores into it and nothing looks it up.**
`crates/marlowe-loop/src/context.rs:519`–`:552` defines it; `Engine` holds one (`engine.rs:401`,
`:543`) and exposes it (`:557`). The **only** production call anywhere in the workspace is
`cache.invalidate(parent)` at `context.rs:762`. `store()` and `lookup()` are called from
`context.rs:809`–`:821` and `crates/marlowe-loop/tests/compaction.rs:275`–`:279` — **both inside
test modules.** `ContextView.cache_epoch` is carried on every view and read by no provider.

So the cache exists, is epoch-keyed, is correctly invalidated on compaction, has a test asserting
the invalidation works in both directions — and **has never held a prefix.** This is CLAUDE.md
instance #16 exactly: a control asserted where it is declared rather than where it is enforced.
The test is green and would stay green if the type were replaced by an empty struct.

It also means there is **no client-side prefix reuse of any kind** to build on for the KV-cache
work STATE.md describes.

**Stale comment, not a defect:** `crates/marlowe-provider/src/ollama.rs:627`–`:629` claims the
loop re-emits per `Say` so streaming "does not put tokens on screen". Untrue since
`engine.rs:909`–`:915` / `:1038`.

---

## 7. Defects worth fixing, in priority order

### 1. `Availability::probe` puts a whole HTTP round trip in front of every turn
**Where:** `crates/marlowe-daemon/src/daemon.rs:1191`, calling
`crates/marlowe-provider/src/ollama.rs:128`.
**Why it costs time:** a fresh `TcpStream::connect`, a `GET /api/tags`, and a **full chunked body
read into a `String` followed by a `serde_json` parse** (`http.rs:163`–`:199`) — Ollama enumerates
every pulled model's manifest from disk to answer it. It runs **before** the model request, on the
daemon thread, every single turn. It answers a question the model call answers anyway: if the
endpoint is down or the model is missing, `post_ndjson` fails and the failure is already typed and
already degrades with a remedy.
**Cost:** UNKNOWN. This is the highest-value unmeasured number in the budget.
**Fix:** probe once at daemon open and cache the result; re-probe **only** on a failed model call,
turning the probe into the diagnostic it actually is rather than a precondition. The OpenRouter arm
already does exactly this and says why (`daemon.rs:1210`–`:1212`: *"No network here. A startup probe
would put a round trip in front of every turn and would answer a question the first call answers
anyway"*). **The right behaviour is already written down, in the same match statement, in the other
arm.**
**Experiment if you want the number first:** `curl -o /dev/null -s -w '%{time_total}\n'
http://127.0.0.1:11434/api/tags`, twenty times, on an idle machine.

### 2. The 50 ms input poll that a token cannot wake
**Where:** `crates/marlowe/src/tui.rs:594`–`:603`; `crates/marlowe-daemon/src/live.rs:456`–`:458`.
**Why it costs time:** `event::poll` blocks on terminal input only. A delta on the mpsc waits for
the timeout. **Mean 25 ms, worst 50 ms, on every token including the first.**
**Fix, cheapest first:**
  a. Lower the in-flight beat from 50 to ~16 ms (`live.rs:457`) — caps the add at 16 ms, mean 8 ms,
     and 60 fps is still under any diff budget the meter needs. One-line change, no new machinery.
  b. Properly: make the poll wakeable. `crossterm` has no cross-platform way to inject a wakeup, so
     the honest version is to stop blocking in `event::poll` at all — spin a reader thread that
     pushes `crossterm::Event`s into the *same* channel the daemon events use, and have the UI
     thread `recv_timeout` on one merged channel. Then a token wakes the loop immediately and the
     tick only paces the animation.
**Do (a) now; (b) is a real change and wants its own session.**

### 3. `marlowe --ask` does not stream and drops reasoning
**Where:** `crates/marlowe/src/agent.rs:257`–`:265` (collect-then-render) and `:580`
(`Event::Reasoning { .. } => {}`).
**Why it costs time:** perceived TTFT on this path is the **whole turn**, not 1,064 ms. If any TTFT
figure in this project was taken with `--ask`, it is not a TTFT figure.
**Fix:** the buffering exists only because `resolve_retractions` needs the whole list
(`agent.rs:251`–`:256`), and retraction is *specifically* the case where speech turned out to be
reasoning. Stream `Event::Text` as it arrives and handle a retraction the way a terminal can: emit
a visible marker rather than trying to un-write. Separately, a progress signal for reasoning
(a spinner, a character count on stderr) costs nothing and would not pollute piped stdout — the
stated objection at `:577`–`:579` is to dumping the chain of thought into stdout, which a counter
on stderr does not do.
**Lower priority than 1 and 2 only if the TUI is the surface being measured. If `--ask` is how
TTFT is being measured, this is #1.**

### 4. Retrieval runs synchronously in front of the model call
**Where:** `crates/marlowe-daemon/src/daemon.rs:1656`–`:1661`.
**Why it costs time:** up to 10 cross-encoder pairs on the turn's critical path. Cited (not
measured here) at ~182 ms p50 / 191 ms p95 on the shipped CPU pins,
`crates/marlowe-memory/src/retrieve.rs:298`–`:304`. Zero on an empty store
(`retrieve.rs:584`–`:586`), so it grows silently as a profile fills.
**Fix — and this one needs a decision, not just a patch.** The retrieval *result* must be in the
system prefix before the request goes out, so it cannot simply be moved off the path. Three options,
in increasing honesty:
  a. **Measure first.** Confirm which provider resolved (`marlowe --status`, `memory.rs:220`) and
     time the stage on this daemon. If it resolved to CUDA the cost may already be ~3 ms and there
     is nothing to fix.
  b. If CPU: pin the rerank provider rather than letting `RerankChoice::Auto` decide against free
     VRAM at boot (`memory.rs:172`–`:178`) — a TTFT that changes depending on what else was on the
     card is not a TTFT you can regress-test.
  c. Structural: overlap retrieval with the connect/serialise work, or start the model call without
     injected memory and accept it lands a turn later. **(c) changes what the model sees and must
     not be done quietly** — it is a `DECISIONS.md` question, not an optimisation.

### 5. The held-speech path can hide the entire reasoning phase
**Where:** `crates/marlowe-provider/src/ollama.rs:685` (`closed = !self.thinking`), `:747`–`:750`
(`held.push_str`), `:798`–`:806` (resolved only after the stream closes).
**Why it costs time:** on a model whose reasoning arrives in `content` rather than in
`message.thinking`, nothing is painted until `</think>`. The source's own header records `</think>`
at **frame 846 of 848**.
**Fix:** do not paper over the rule — it is right. Make the *state* visible instead: when
`!closed && !held.is_empty()`, emit a `ReasoningDelta`-shaped progress signal (a byte count, not
the held text) so the surface can show `thinking… N characters` exactly as it does for native
thinking. The containment property — *held text never renders as speech* — is untouched, because
a count is not the text.
**And add the negative control this family always needs:** a test that fails when nothing was held.
An assertion about held speech that passes on a turn with no held speech is measuring nothing —
CLAUDE.md's trim-marker lesson, in a new place.

### 6. `TCP_NODELAY` is set on exactly one socket in the workspace, and it is the wrong one
**Where:** the only `set_nodelay` is `crates/marlowe-net/src/lib.rs:403`, which is the `web` tool's
egress path. Not set on: the Ollama socket (`crates/marlowe-provider/src/http.rs:364`), the daemon
listener / `serve_one` writer (`crates/marlowe-daemon/src/daemon.rs:2004`, `:2026`), or the client
connection (`crates/marlowe-daemon/src/client.rs:131`).
**Why it might cost time:** every one of these does small, latency-sensitive writes — a per-token
event line, a request head followed by a separate body write (`http.rs:376`–`:377`). Nagle
interacts badly with exactly that shape. On loopback the ACK is fast enough that the effect is
probably small, so I am **not** claiming it costs milliseconds — I am claiming it is unmeasured, is
free to remove, and is the standard first thing to rule out.
**Fix:** `set_nodelay(true)` on all four, and merge `http.rs:376`–`:377` into one `write_all` of
head + body.
**Experiment:** set it, then re-run the peer's instrument. If the 0.5 ms TCP figure does not move,
close the question.

### 7. Two constructions of the tool registry per turn
**Where:** `crates/marlowe-daemon/src/daemon.rs:1235` and `:1279` (and `:1412` on the OpenRouter
arm), each calling `builtin_registry()` (`:491`–`:505`).
**Why it costs time:** microseconds, honestly. It is on the list because the second call carries the
comment `"the registry loaded a moment ago"` — the code already knows it is redundant.
**Fix:** build once, pass it.

### 8. `PrefixCache` is dead code with a green test
**Where:** `crates/marlowe-loop/src/context.rs:519`–`:552`; only production caller is
`invalidate` at `:762`.
**Why it matters here:** it is not a latency cost — it is the *absence* of one lever. Anyone reading
this crate would reasonably conclude Marlowe has prefix caching. It does not. It should be either
wired or deleted, and the choice belongs with the KV-cache-prefix work STATE.md already has open.

---

## 8. Two things I did not measure and think you should

**(i) The single most valuable client-side number is `/api/tags`.** It is the one stage in the
budget that is both on the critical path every turn and completely unknown. One `curl` settles it.

**(ii) The retrieval stage on *this* daemon.** The 182 ms figure I quoted is the crate's own, taken
on a 1-vCPU CPU target for a §5.7 budget question. Whether it describes this machine depends on
what `CrossEncoder::load_auto` resolved to at daemon boot, which depends on free VRAM at that
instant. Read `marlowe --status` first; if it says CUDA, defect 4 may not exist. **A number that
arrives with a citation instead of a command is the tell, and I am flagging my own.**

---

## 9. On the server side, briefly, because it is ours to cause

STATE.md's diagnosis is confirmed by reading `crates/marlowe-provider/src/ollama.rs:393`–`:419`:
the system message is `view.stable ++ view.context ++ every InjectedMemory block`, joined with
`\n\n` into **one** string. Injected memory is retrieved per turn, so **the prefix changes every
turn** and `llama.cpp` re-evaluates from the first differing byte. That is what the peer measures as
782 ms of prompt evaluation — charged on the wire, caused here.

Two additional prefix-instability sources not named in STATE.md, both found in the same read:

- **The ephemeral nudge is pushed onto `view.stable`** (`crates/marlowe-loop/src/engine.rs:806`–
  `:810`), which places it *between* the last stable block and the first context block — mid-prefix.
  It fires after tool calls (`:1017`–`:1030`), so any turn following a tool chain invalidates the
  cache earlier than the injected-memory block would.
- `PERSONA` is ~3,544 tokens, **11.5% of the effective window, in every request**, and the stable
  tier is not trimmable (`crates/marlowe-daemon/src/daemon.rs:2159`–`:2166`, which says so
  explicitly). Stable across turns, so it is cache-friendly — but it sets the floor on what a cold
  or invalidated prefix costs.

Not my lane to fix, but worth handing to whoever takes the prefix work: **the injected-memory block
and the nudge both need to move to the end of the prefix, or out of the system message entirely,
and STATE.md is right that neither is a simple move.**
