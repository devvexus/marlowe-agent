# ADR-060 — The 225 ms is Ollama's scheduler, not the runtime: four ways out, and what each one breaks

**Status:** PROPOSED — **a decision for the human. Nothing is built, nothing is changed, and
`DECISIONS.md` is untouched.** If adopted, this amends ADR-028, which chose Ollama and is still
right about *why* it chose it.

---

## 1 · The measurement, and what it is a measurement of

Taken 2026-08-27 on this machine (RTX 4080 SUPER, `qwen3.5:9b`), by the agent recorded in
`STATE.md` under *"TTFT IS 1,064 ms"*. The comparison is Ollama against **Ollama's own bundled**
`llama-server.exe` 0.32.5, pointed at the **same GGUF blob Ollama had already pulled**
(`sha256-dec52a44…`, confirmed in `runs/ttft/llama-server3.log:9`), `-c 32768 -ngl 99 -np 1`,
GPU-resident, same instrument, same unique-marker discipline, `qwen3.5:9b` unloaded from Ollama
first.

| cell | Ollama | llama.cpp | delta |
|---|---|---|---|
| tiny prompt, no system | 292.6 ms | **44.3 ms** | −248 ms |
| 15k-char system, prefix WARM | 275.1 ms | **52.0 ms** | −223 ms |
| 15k-char system, prefix COLD | 1,064.4 ms | 742.2 ms | −322 ms |
| 46,400-char system, cold | 2,660.3 ms | 2,061.7 ms | −599 ms |

**Two taxes, and they add.**

1. **A fixed ~225 ms per request.** It is exactly Ollama's own reported `load_duration` on a model
   that never left VRAM — the interval from request receipt to `sched.GetRunner` returning, i.e.
   pure scheduler overhead. llama.cpp's equivalent is ~16 ms.
2. **A proportional ~19% on prompt eval.** 5,227 vs 6,228 tok/s, same graph, same card, measured
   from 31 to 11,839 tokens on both. The 5,227 tok/s recorded elsewhere in `STATE.md` is **not the
   card's ceiling; it is ours by way of Ollama.**

**It is per REQUEST, not per stream, and that is the number that reframes the problem.** The loop
makes one model call per iteration and every tool call round-trips, so a five-call turn pays
**5 × 226 ms = 1.13 s** of scheduler tax before any thinking happens. On llama.cpp the same turn
pays ~80 ms.

**What this measurement does NOT cover, stated first because it is load-bearing.** Every cell used
`/v1/chat/completions` with a `system` and a `user` message and **no `tools` array**
(`runs/ttft/llama_direct.py:4-6`). Marlowe's request always carries one
(`crates/marlowe-provider/src/ollama.rs:544-546`). So the measurement establishes a **latency**
result on a **tool-free** request shape, and says nothing about tool-call reliability through
llama.cpp — which is ADR-028 requirement 2's whole subject. See §12.

---

## 2 · What actually depends on Ollama — read from the code

Each row is a `file:line` I opened, not a recollection.

| Dependency | Where | Hybrid (§7) keeps it | Full replace (§9) |
|---|---|---|---|
| `/provider` picker and its one definition | `crates/marlowe-daemon/src/project.rs:46` (`PROVIDERS`), validated at `daemon.rs:1003` | yes — a third entry | entry deleted |
| The model list `/model` shows | `crates/marlowe-daemon/src/daemon.rs:895-908`, filled from `Availability::probe`'s names | yes | must be built |
| Model-switch validation, refused by name | `crates/marlowe-daemon/src/daemon.rs:958-967` — probes before accepting | yes | must be built |
| Readiness, with a remedy per failure | `crates/marlowe-provider/src/ollama.rs:128-161`; called on the turn path at `crates/marlowe-daemon/src/daemon.rs:1191` | inventory yes; the server needs its **own** probe | new |
| **Model acquisition / downloader** | **Nothing. There is no downloader.** The dependency is two remedy strings — `crates/marlowe-provider/src/ollama.rs:117` (`ollama pull {model}`) and `crates/marlowe/src/agent.rs:55` | yes | **must be built — §9** |
| The chat template | Ollama renders it server-side. Nothing in this repo constructs one | **the open question — §4** | same question |
| Reasoning channel | `crates/marlowe-provider/src/ollama.rs:708-717` accepts `thinking` \| `reasoning` \| `reasoning_content`; painted at `crates/marlowe-surface/src/render.rs:655-672` | yes, with a caveat — §5 | same |
| `num_ctx` / `num_predict` per request | `crates/marlowe-provider/src/ollama.rs:521-536` | **no — becomes a launch flag. §7** | same |
| `keep_alive` | **Never sent.** `grep -rn keep_alive crates/` returns nothing. Ollama's default governs | n/a | n/a |
| Cloud-tag refusal | `crates/marlowe-provider/src/routing.rs::is_cloud_tag`, applied at `daemon.rs:903` | still needed for the picker | n/a |
| **The embedder's tier-1 VRAM reserve** | `crates/marlowe-memory/src/cue/dense/vram.rs:158` (`ollama ps`) and `:178` (`ollama list`), driven from `crates/marlowe/src/main.rs:799` and `crates/marlowe-daemon/src/memory.rs:177` | **BREAKS — §3** | **BREAKS** |

Two of these are worth pulling out of the table.

**The model store is a smaller dependency than it looks.** Marlowe never pulls anything. It reads
an inventory over `/api/tags` and it prints `ollama pull` when something is missing. That is the
entire relationship, and it means *"Ollama is our downloader"* is true only in the sense that the
user is our downloader and Ollama is their tool.

**`keep_alive` is a dependency in the other direction.** Because Marlowe never sends it, Ollama's
default idle unload governs, which is what lets the card be shared between turns. A `llama-server`
holds its weights until it is killed. On a 16 GB card with an embedder and a cross-encoder also
wanting CUDA (ADR-044, ADR-045), that is a change in kind, not in degree.

---

## 3 · The dependency nobody listed: moving inference silently moves the embedder to CPU

`vram.rs`'s `Reserve::ForTier1` decides how much device memory tier 3 must leave alone. Its
residency check is `ollama ps` (`vram.rs:158`) and its size lookup is `ollama list` (`:178`). The
comment at `:155-157` states the invariant exactly:

> Resident already? Then its bytes are ALREADY OUT of `memory.free` and reserving them a second
> time would double-count — which would read as a smaller card and quietly push tier 3 onto CPU
> for a reason that does not exist.

Serve the model from `llama-server` and that is precisely what happens. The blob is still in
`ollama list`, so the size lookup succeeds; `ollama ps` shows nothing resident, so the reserve is
applied — **on top of** the ~9.5 GB `llama-server` has already taken out of `memory.free`. The
embedder resolves to CPU, `--status` prints a reason string that is internally coherent, and
nothing anywhere reports a mismatch.

This is CLAUDE.md's standing family arriving in a new subsystem: **the guard is sound and its
subject moved.** Ask of the reserve what it would read if the language model were running somewhere
it cannot see, and the answer is *"a confident wrong number"*.

**Any option other than §8 must re-base this reading on the process that actually holds the
weights.** It is one function and one authority — not large work — but it is not optional and it is
not a footnote.

---

## 4 · The template question, which is the one most likely to be underestimated

CLAUDE.md has a section on this: *"A TEMPLATE IS NOT WHAT THE MODEL RECEIVED, and the control took
one command."* The lesson there was that Ollama's `/api/show` reports this model's template as
`{{ .Prompt }}` and **that field is not what Ollama uses** — it has a built-in renderer for the
architecture and ignores it. The conclusion drawn from the field was announced before it was tested
and was wrong; a BANANA control settled it in one command.

That history is the reason this section exists. Read what follows as the shape of the risk, with
each claim marked for what it rests on.

**Verified by reading the manifest on this machine.**
`~/.ollama/models/manifests/registry.ollama.ai/library/qwen3.5/9b` has three layers:
`application/vnd.ollama.image.model`, `.license`, `.params`. **There is no `.template` layer.** So
for this model the template is either embedded in the GGUF as `tokenizer.chat_template` or supplied
by Ollama's own renderer — and those two can differ.

**Verified from the measurement.** `runs/ttft/llama_direct.py` posted `system` + `user` to
`/v1/chat/completions` and got streaming deltas back, so llama.cpp applied *some* template and the
model answered coherently enough for the cells to be recorded. Prompt-token counts were close
enough across the two servers that a 19% throughput delta was legible (31 → 11,839 tokens on both).

**NOT verified, and this is the gap.** Nothing establishes that the two renderings are the *same*
prompt. Close token counts are consistent with identical templates and equally consistent with two
templates differing by a few control tokens. The launch flags are recorded nowhere in `runs/ttft/`
— in particular **whether `--jinja` was passed is unknown**, and that is the flag deciding whether
llama.cpp renders the GGUF's own Jinja template or falls back to a built-in chosen by heuristic.
`runs/ttft/llama-server*.log` contains no chat-template line at the verbosity used.

**The failure mode if it is wrong is silent.** A template differing in its tool-call block produces
a model that stops emitting tool calls, or emits them as prose — which presents as *the model got
worse*, not as *the prompt changed*. `parse_step` would report no call; the loop would narrate.
Every unit test would stay green, because they all build a request body in-process — the fourth row
of CLAUDE.md's pipe-tested-guard table, verbatim.

**Three controls that settle it, in order of cost.** None requires building anything.

1. **BANANA.** A system message saying *reply with exactly the word BANANA*, sent to both servers.
   Proves the system role reaches the model at all. This is the control that caught C2f.
2. **Token-count identity.** Same messages to both; compare Ollama's `prompt_eval_count` against
   llama.cpp's `timings.prompt_n`. **Equal is strong evidence; unequal is proof of divergence.**
   The instrument already reports both (`ollama.rs:772`, `llama_direct.py:31`).
3. **The rendered string itself.** `llama-server` exposes `/apply-template`; push the same messages
   through it and read the prompt. This is the only reading that answers the question directly
   rather than adjacently — the difference this project keeps having to relearn.

---

## 5 · The reasoning channel is already provider-independent, and this is the cheap part

The concern that llama.cpp has no `thinking` field is largely handled already, by two mechanisms
that exist and are exercised by two drivers:

* `crates/marlowe-provider/src/ollama.rs:708` loops over
  `["thinking", "reasoning", "reasoning_content"]`. llama.cpp's OpenAI-compatible deltas use
  `reasoning_content`, which is **already** in that list, and `llama_direct.py:27` reads it — so it
  is on the wire shape the measurement used.
* `marlowe_provider::ThinkSplitter` (`think.rs`) recovers reasoning from `<think>` tags in
  `content`. `OllamaDriver` uses it (`ollama.rs:640`) and `OpenRouterDriver` reuses the same type
  (`crates/marlowe-openrouter/src/driver.rs:576`). The surface consumes `Entry::Reasoning`
  (`render.rs:655-672`) and knows nothing about providers.

**The caveat, from `STATE.md`:** when reasoning arrives inside `content` rather than on its own
channel, `closed` starts `false` (`ollama.rs:685`) and speech is **held** until a `</think>` proves
the block shut. Reasoning still streams; the answer arrives in one piece at the end. On the measured
turn that tail was seven bytes at frame 847, so it is acceptable — but it is a behaviour change to
watch live, not to assert from the type system.

---

## 6 · What the provider seam already gives, and what a third driver costs

The port is `marlowe_loop::ModelDriver` (`crates/marlowe-loop/src/driver.rs:266`) — `call`,
`call_streaming`, `call_streaming_split`, `streams`, `failover`. The daemon holds a
`Box<dyn ModelDriver>` chosen once per turn at `daemon.rs:1269`.

**Nothing about `ModelDriver` is pinned in `CONTRACTS.md`.** The pinned types on that boundary are
`ContextView` (§12, including `cache_epoch`) and the `ProviderFailedOver` event kind (§1.1).
`ProviderId` in §11 is the credential broker's noun, unrelated, and has no implementation. **So a
third driver breaks no pinned contract.**

`marlowe-openrouter` is the worked example of a second driver and shows what is reusable:

| Reused from `marlowe-provider` | Site |
|---|---|
| `ollama::parse_step` — one definition of what `ask` / `remember` / `run` mean | `openrouter/src/driver.rs:788` |
| `wire::unorphan_tool_messages` | `:318` |
| `wire::tools_field` — omit, never send `[]` | `:345` |
| `ThinkSplitter` | `:576` |
| `ModelCapability` | `:36` |

Duplicated rather than shared: message building, transport, SSE decoding, availability, catalogue,
retry, attribution, key handling. For a local llama.cpp driver the last four are **not needed at
all** — no key, no billing, no catalogue, no upstream queue.

**One structural constraint, and it is real work rather than a refactor of taste.**
`crates/marlowe-openrouter/Cargo.toml` depends on `marlowe-net` for TLS, and
`crates/marlowe-provider/tests/no_tls_in_the_default_path.rs` fails the build if any TLS crate
becomes reachable from `marlowe-provider`'s dependency graph. So a local driver **cannot** depend on
`marlowe-openrouter` to get its SSE decoder. `openrouter/src/sse.rs` is pure `BufRead` with no TLS
in it; the clean move is to **relocate `sse.rs` down into `marlowe-provider`** and have
`marlowe-openrouter` use it from there. That keeps one SSE decoder and keeps the no-TLS test green.
The other way — a second decoder — is how two providers end up disagreeing about `data: [DONE]`.

---

## 7 · Option C, the hybrid — examined first, because the measurement literally did it

**Keep Ollama as the model store, the inventory and the downloader. Serve inference with the
`llama-server.exe` Ollama already ships, pointed at the blob Ollama already downloaded.**

### What is on this machine, verified by listing

| Thing | Path | How verified |
|---|---|---|
| The server binary | `%LOCALAPPDATA%\Programs\Ollama\lib\ollama\llama-server.exe` | listed; sits beside `libllama.dll`, `ggml*.dll`, `cuda_v12/`, `cuda_v13/` |
| The blob store | `%USERPROFILE%\.ollama\models\blobs\sha256-<digest>` | listed |
| The manifests | `%USERPROFILE%\.ollama\models\manifests\<registry>\<namespace>\<name>\<tag>` | listed; e.g. `registry.ollama.ai/library/qwen3.5/9b`, and `hf.co/unsloth/…` for HF pulls |
| Name → blob resolution | read the manifest JSON; take the layer whose `mediaType` is `application/vnd.ollama.image.model`; its `digest` is the blob filename with `:` → `-` | read the file; the digest matches the one `llama-server` was launched against in `runs/ttft/llama-server3.log:9` |
| Model load time, warm page cache, GPU | `load_model` at `0.01.065` → `model loaded` at `0.02.654` = **1.59 s** | `runs/ttft/llama-server3.log:9,17` |

### Is this officially supported? No — and that belongs in the cost column, not a footnote

**The blob and manifest layout under `~/.ollama/models` is not a documented public interface**, and
`lib/ollama/llama-server.exe` is a vendored private binary with no stability promise. Depending on
either is depending on Ollama's internals. Concrete evidence that the layout already varies: the
`qwen3.5:9b` manifest has **no template layer at all**, and the media types live in Ollama's own
`application/vnd.ollama.image.*` namespace — versioned by them, changed by them.

The honest framing: **this is the same class of dependency as parsing another program's cache
directory.** It works today, on this machine, because it was measured working today, on this
machine. It can break on any Ollama update, and it will break the way that class always breaks — at
startup with a path that is not there, or worse, with a layout that parses and means something else.

Two things reduce it; neither removes it:

* `ollama show --modelfile <name>` is a **documented CLI** and is the supported way to ask for a
  model's template and parameters. **Unverified: whether it also names the blob path on this
  version.** One command settles it, and it calls no model.
* Every read is a **load-time** read. A missing binary or an unparseable manifest becomes a refusal
  that names the remedy — CLAUDE.md's *prefer a load-time error to a sensible default* — rather than
  a wrong answer mid-turn.

### Cost to build

| Unit | New, or a copy of something that exists |
|---|---|
| Move `sse.rs` into `marlowe-provider` (§6) | mechanical; keeps the no-TLS test green |
| `llamacpp.rs`: OpenAI-shaped body, SSE fold, `parse_step` reuse | closely mirrors `openrouter/src/driver.rs` minus auth, retry, attribution, catalogue |
| Blob resolution from a model name | new, small, and the one part that reads Ollama's internals |
| Process supervisor: spawn, port, health, kill on daemon exit, restart on `/model` | **new, and the genuinely novel work — §10** |
| Third `PROVIDERS` entry and its `Availability` | mirrors the two that exist |
| Re-base the tier-1 VRAM reserve (§3) | **required, not optional** |
| `num_ctx` becomes a launch flag without diverging from the assembler window | extends `crates/marlowe-daemon/tests/context_window.rs`, which exists to catch exactly that divergence |

### What it breaks, and what it risks

**Breaks:** nothing in the picker, nothing in acquisition, nothing in the remedy strings — that is
the point of the hybrid. It breaks the VRAM reserve (§3), and it moves `num_ctx` from a per-request
field to a per-process launch flag, so changing the context window becomes a restart.

**Risks:** the template (§4); tool-call reliability through a template nobody has probed (§12);
version fragility on Ollama's layout. Plus one the measurement's own flags create — `-np 1` means
**one slot**: `n_slots = 1, n_ctx_slot = 32768` at `-c 32768` (`llama-server3.log:17`), so `-np 4`
would give four slots of 8,192 tokens each (arithmetic on that log line, not a separate
measurement). Concurrency and per-slot context trade directly, and llama.cpp's prefix reuse is
per-slot (`selected slot by LCP similarity, sim_best = …`, `llama-server3.log:26`). **This is the
one place where the runtime choice and the prefix-cache work are not independent.**

**TTFT delivered: 52 ms warm, 742 ms cold at 15k, ~16 ms per-iteration tax** — the measured
llama.cpp column unchanged, because this option *is* what was measured.

---

## 8 · Option A — stay on Ollama, and spend the effort on the prefix cache

Accept both taxes; fix the prefix churn instead. `STATE.md` names three sources: the
injected-memory concatenation at `ollama.rs:393-419`, the ephemeral nudge pushed onto `view.stable`
at `engine.rs:806-810`, and their interaction with conversation history.

**Cost:** zero new architecture. No new process, no new provider, no §3 breakage, ADR-028 stands as
written, K6 untouched.

**What TTFT it ceilings at, and this is the whole argument against it.** The measured warm-prefix
TTFT on Ollama is **275.1 ms**, of which **~226 ms is `load_duration` on a model that never left
VRAM**. Solving the prefix problem *perfectly* removes the variable term and lands at ~275 ms. It
cannot go below it, because 82% of it is not ours.

The target in `STATE.md` is the human's own: *"1 second is unacceptable in all scenarios, 0.2
seconds is a stretch."* **Option A cannot reach 200 ms.** That is arithmetic on measured numbers,
not an argument. The per-iteration structure makes it worse than the single figure suggests: a
five-call turn pays 1.13 s of scheduler tax that no prefix work touches.

This option is not thereby wrong. It is the right option if §4 or §12 turn out badly, or if §11's
free precondition closes the gap.

---

## 9 · Option B — replace Ollama outright

Marlowe owns the runtime, the process, the model store and acquisition. `PROVIDERS` loses its
`ollama` entry.

**It delivers the same TTFT as §7** — same binary, same blob format, same numbers.

**It costs everything §7 costs, plus a downloader, and the downloader re-opens a decision ADR-028
already made.** ADR-028 rejected *"a bundled local model in the installer"* explicitly, and its
governing constraint is K6: *install → first useful output, zero config*. Its argument was that
every way of putting something in front of the first run fails K6, because **K6 does not measure
whether that something is small; it measures whether it is there.**

Replacing Ollama means Marlowe must acquire a GGUF on first run. That is a registry client, HTTPS
egress on the default path — which collides with ADR-031 §2.3 and the no-TLS property
`marlowe-provider` currently holds — a content-addressed store, digest pinning, resumable multi-GB
downloads, and a progress surface. It is a milestone, not a task, and at the end of it Marlowe has a
worse version of something the user already has installed.

**Recommend against**, unless the hybrid's version fragility proves intolerable in practice — in
which case this is what *intolerable* costs, and it should be priced then rather than now.

---

## 10 · Process lifecycle — the question with no precedent in this codebase

Ollama is a **service**: already running, auto-loads on demand, unloads on idle, one endpoint for
every model. `llama-server` is a **process**: one model, one port, started by someone, stopped by
someone, no switching without a restart. Marlowe has never owned a long-lived child process, so
every answer below is new code.

**Who owns the lifetime.** The daemon. It is already the single long-lived process, it already
holds `config.model`, and a child it spawns dies with it. A user-managed server is the wrong answer
for the same reason a config file is: it fails K6.

**What `/model` does.** Under Ollama it is a validated config write (`daemon.rs:958-967`). Under
llama.cpp it is **stop the process, start a new one, wait**. Measured on this machine, warm page
cache, GPU: **1.59 s** (`llama-server3.log`). `/model` becomes a visible pause, and §B5 already has
the vocabulary for that. `set_model` must refuse mid-turn or queue behind the run; today it cannot
be called mid-turn because the daemon serves the turn synchronously — **but that is a property to
assert, not to assume** (§14.11).

**What happens on a crash mid-turn.** Today an unreachable endpoint is `HttpError::Unreachable` →
`ProviderError { retriable: true }` (`ollama.rs:633-640`) → `DegradedPath::ModelUnavailable`, with a
remedy of `ollama serve`. Under a supervised child the remedy is *ours*, and the honest behaviour is:
notice the exit, say so, restart once, and if the restart fails, degrade with the exit code — never
silently retry into a loop. `ModelDriver::failover` (`driver.rs:317`) is the existing hook and
returns `false` by default.

**What happens when it will not start.** VRAM already taken, port in use, binary missing. All three
must be load-time refusals naming the remedy, and none may fall back to Ollama silently.
`daemon.rs:1176-1178` states the rule for the existing pair — *"Neither arm falls back to the
other"* — for a reason that applies verbatim here.

**The port.** Ollama's 11434 is fixed and known. A child server needs an ephemeral port chosen at
spawn and handed to the driver; a hardcoded 8080 is a collision waiting for the user to be running
anything else. `LocalEndpoint` already refuses non-loopback hosts, which is the property to preserve.

---

## 11 · Two more options the reading turned up

**Option D — check whether a newer Ollama has already fixed it. Cost: near zero.** The 225 ms is
scheduler overhead in `sched.GetRunner`, not a design invariant. The bundled server is
`llama-server 0.32.5 (b1-b4d6c7d8f)`. Nothing here establishes that current Ollama still charges it.
**This is a short check that could close the entire ADR**, and it should be run before any option
above is costed further. `runs/ttft/phase_g.py` is the instrument and it already exists.

**Option E — ship llama.cpp as a THIRD provider, not as a replacement.** `PROVIDERS` becomes
`["ollama", "openrouter", "llamacpp"]` (`project.rs:46`), reachable by `/provider`, with Ollama
staying the default until the number is verified in the product rather than in an instrument. This
is the shape the architecture already has: ADR-046 added a provider exactly this way, `set_provider`
(`daemon.rs:1002`) is the seam, and the picker is built from the one list. It costs the same driver
work as §7 and defers every question about K6, defaults and acquisition — because Ollama is still
there, still the default, and still the answer when the child will not start.

---

## 12 · The comparison that has not been made, and it outranks the latency one

ADR-028 requirement 2 is **measured tool-call reliability**, and the recorded figure — 12/12
well-formed, 12/12 correct target, median 1666 ms, `2026-08-08` (`ollama.rs:64-76`,
`crates/marlowe-provider/tests/tool_call_probe.rs`) — **was measured through Ollama's template.** It
is a measurement taken on a system, and this project has a standing rule about carrying those across
a boundary: *the tell is that the number arrives with a citation instead of a command.*

A different server rendering a possibly-different template is a different system. So:

> **A 5.3× TTFT win with worse tool calling is a net loss, and nothing measured so far can tell the
> difference.**

The check is `tool_call_probe` pointed at a running `llama-server` — the harness exists, it is
endpoint-driven, and it produces the same twelve trials the pinned number came from. **That run,
not the latency table, is what should gate any change of default.** (`MIN_TRIALS` in `capability.rs`
is the knob if twelve is too thin; the doc comment at `ollama.rs:29-34` already records that the
95% Clopper-Pearson lower bound on 12/12 is ≈0.74, below `MIN_RATE`.)

---

## 13 · Recommendation — and it is a recommendation, not a decision

**Sequenced, because two of the four steps are free and might make the rest moot.**

1. **Run Option D first.** Check whether current Ollama still charges 225 ms. One install, one
   existing script. If it is gone, withdraw this ADR.
2. **Run the three template controls (§4) and the tool-call probe (§12).** No code, no build. Together
   they decide whether llama.cpp is a viable runtime for *this* harness rather than a faster
   prompt-eval engine.
3. **If 1 does not close it and 2 comes back clean: adopt Option C, delivered as Option E.** The
   hybrid, shipped as a third `PROVIDERS` entry, opt-in by `/provider`, **Ollama remaining the
   default** until it has been live-verified in the product. Resolve-and-announce it the way ADR-044
   resolves the embedder: the child server is attempted, the outcome is *announced*, and falling back
   to Ollama's HTTP endpoint is a stated degradation, never a silent one.
4. **Do the prefix-cache work regardless.** It is independent, it is the larger term at today's
   context sizes (610–860 ms per turn, by `STATE.md`'s arithmetic), and §8 is the right home for that
   effort whichever runtime wins. The one caveat is §7's last paragraph: llama.cpp's prefix reuse is
   per-slot, so the two interact at `-np`.

**Why not Option A alone:** it cannot reach the stated 200 ms target. The floor is 275 ms and 226 ms
of it is not ours.

**Why not Option B:** it re-opens ADR-028's K6 argument, and the price of re-opening it is a
model-acquisition milestone ending in a worse copy of a tool the user already runs.

**The cost that must be paid under C, B or E and is easy to forget:** the tier-1 VRAM reserve (§3).
Left alone, the first thing this change does is move the embedder to CPU and print a plausible
reason for it.

---

## 14 · What I could not establish

Read-only session: nothing was built, no model was called, no daemon was started. Each item names
the check that would settle it.

1. **Whether `--jinja` was passed to `llama-server` during the measurement.** No launch record exists
   in `runs/ttft/`; `STATE.md` records only `-c 32768 -ngl 99 -np 1`. *Check: ask the measuring
   agent, or relaunch with the argv recorded beside the log.*
2. **Whether the GGUF carries `tokenizer.chat_template`, and whether llama.cpp's rendering of it is
   byte-identical to Ollama's for the same messages.** The manifest has no template layer; the logs
   name no template. *Check: §4's three controls, in order.*
3. **Tool-call reliability through llama.cpp.** No cell sent a `tools` array. *Check: §12.*
4. **Whether current Ollama still charges the 225 ms.** *Check: Option D.*
5. **Whether the 225 ms is tunable by configuration** (`OLLAMA_*` environment). Not investigated at
   all. *Check: read the scheduler's own knobs before assuming there are none.*
6. **Whether `ollama show --modelfile` names the blob path on this version** — i.e. whether the hybrid
   can rest on a documented CLI instead of the on-disk layout. *Check: one command.*
7. **Whether the daemon ever has two model calls in flight at once.** `Engine::spawn`
   (`crates/marlowe-loop/src/engine.rs:2417`) is a synchronous method, so a child serializes with its
   parent within a run; whether two concurrent client sessions can overlap was not established.
   **This decides `-np`, and `-np` decides per-slot context.** *Check: read `serve_one`'s accept loop.*
8. **How much of the prefix problem llama.cpp's per-slot LCP reuse already solves.** The mechanism is
   visible in the log (`llama-server3.log:26`); its behaviour under Marlowe's actual churn is
   unmeasured. *Check: the production-shaped growth cell, re-run against llama.cpp.*
9. **The 9.5 GB vs 6.6 GB discrepancy.** `STATE.md` records `llama-server` resident at 9.5 GB;
   `vram.rs:70` records `marlowe-red:9b` at 6.6 GB under Ollama at 32k. Probably KV allocation
   policy, possibly a different context commitment. It matters because it is the number §3's fix
   would reserve. *Check: `nvidia-smi` beside each, same `-c`.*
10. **Whether a `llama-server` crash mid-turn is distinguishable, in the current error path, from a
    model that is merely slow.** `HttpError::Unreachable` is the only signal and it arrives the same
    way a dead Ollama does. *Check: kill the child mid-stream and read what the surface says.*
11. **Whether `set_model` can be reached mid-turn.** §10's restart story depends on the answer, and it
    was inferred from the daemon serving turns synchronously rather than verified.
12. **Whether `llama-server` 0.32.5's OpenAI endpoint emits `tool_calls` in the shape
    `ollama::parse_step` expects after `OpenRouterDriver`'s reassembly** (`openrouter/driver.rs:764-788`).
    Assumed from OpenAI-shape compatibility; not observed. *Check: falls out of §12's probe run.*
