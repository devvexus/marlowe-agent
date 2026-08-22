# ADR-046 — OpenRouter: a hosted provider, built as a measurement instrument

**Status:** Accepted, implemented, **partially verified against the live endpoint** — the transport,
the credential header, the refusal path and the no-fallback rule were exercised against
openrouter.ai for real; every success-path wire field was not. See §9.
**Date:** 2026-08-22.
**Supersedes nothing. Amends nothing.** ADR-028 (local-first default), ADR-031 (rustls in
`marlowe-net`), ADR-008 (tiered routing) and ADR-023 (the action/target latch) all stand as
written; this ADR is what happens the first time a hosted model arrives beside them.

> **Numbering hazard.** ADRs 001–029 live inside `docs/design/DECISIONS.md`; 030+ are separate
> files in `docs/design/adr/`. The memory track also reused some numbers below 030. 046 is the next
> free number in the *file* series. If you are adding one, check both.

---

## 1. What this is for, and what it is not for

Marlowe's default is local: `127.0.0.1:11434`, no account, no key, no network. **That does not
change.** K6 — *install → first useful output, zero config* — is a kill criterion, it is currently
met, and §7 is the part of this document that exists to keep it met.

What this path is *for*, primarily, is **benchmark runs**:

* **K2** — LongMemEval-S QA accuracy ≥90% / abstention ≥85%. A kill criterion that has **never been
  measured**, blocked on a hardcoded `answered: false` at `crates/marlowe/src/adapter.rs:649` and on
  a credential. This ADR supplies the credential half and nothing else; `adapter.rs` is untouched.
* **M2's four unmet acceptance rows** — SWE-bench Verified, Terminal-Bench 2.0, τ-bench, BFCL, all
  *"competitive on the same model"*, all needing a model a local 9B is not.

So the adapter is designed as an **instrument first** and a user-facing option second. That
ordering is visible in three places — §3 (attribution), §3.2 (cost and retry), §6 (determinism,
honestly bounded) — and it is why those sections are longer than the transport section.

**It is a second adapter, not a migration.** Nothing about the Ollama path is deprecated, and no
default anywhere moves.

---

## 2. The TLS decision

`marlowe-provider` has no TLS. Its `http.rs` is a plain `TcpStream` whose header says *"no `https`,
no redirect following, no keep-alive, no compression"* and *"the TLS question is deferred to the
session that adds a hosted provider"*. This is that session. OpenRouter is HTTPS-only.

**Three options were on the table.**

| Option | Rejected because |
|---|---|
| **Grow `marlowe-provider/src/http.rs` a TLS stack** | It would put `rustls` and a root store in the crate whose dependency tree is *evidence* for ADR-028, and `http.rs`'s own header says the signal to stop growing it is exactly this. A hand-rolled HTTP client that has started doing TLS is a hand-rolled HTTP client with a supply-chain surface. |
| **A cargo feature on `marlowe-provider`** | `cargo tree -p marlowe-provider` would be clean by default and dirty under `--all-features`, so the property would hold or not hold depending on how you looked. That is the permissive-default shape this project deletes on sight. |
| **A second `rustls` dependency in a new crate** | ADR-031 §2.3 makes `marlowe-net` *"the whole of the TLS supply-chain surface"*. Two rustls users ends that, and the whole value of §2.3 is that there is one place to audit. |

**Chosen: extend `marlowe-net` with one primitive, and put the driver in a new crate that depends
on it.**

* `marlowe-net` gains `Client::post_streaming` — a POST whose response body is returned undrained,
  with chunked framing decoded incrementally. ~120 lines, no policy, no redirect following, no
  pooling (a streamed body has no unambiguous end until it is read, and a half-drained connection
  returned to the pool desynchronises the next request on it). It reuses the existing
  `ClientConfig`, session cache, DNS cache and pinned `webpki-roots` set.
* `crates/marlowe-openrouter` is a **new crate** that depends on `marlowe-provider`, not the other
  way round. `cargo tree -p marlowe-provider` is therefore unchanged, and ADR-031 §2.3 survives
  verbatim.

**And the property is now read by a line of code.** ADR-031 §2.3 was a comment in a `Cargo.toml`
with nothing checking it — CLAUDE.md's *sixteenth instance*, a declared control nothing reads. The
obvious implementation of this feature (`openrouter.rs` beside `ollama.rs`) would have ended it
with no error, no warning and no failing test. `crates/marlowe-provider/tests/
no_tls_in_the_default_path.rs` walks the workspace manifests and fails if any TLS crate becomes
reachable from `marlowe-provider`, with a negative control asserting the walk finds TLS where TLS
actually is.

**What `post_streaming` also gained, and why it is not incidental:** header values are written
verbatim, so `validate_header` refuses CR, LF and NUL in any name or value — **refused, not
stripped**, because a silently-removed newline is a mismatch nothing observes. The two values that
pass through it are an API key and a user-supplied model name. The refusal never quotes the value.

---

## 3. Attribution — the requirement that makes this an instrument

**OpenRouter routes one model name to several upstream providers**, at different quantizations,
with different context limits and different tokenizers, and it may change that routing between two
requests without the name changing. Two benchmark runs can therefore differ materially while every
label in the output reads identical.

This is CLAUDE.md's most-logged family — *a measurement is scoped to the system it was taken on* —
arriving through a boundary that **moves on its own, with nobody choosing anything**. The four
recorded instances are a graph, a split, a code path and a machine; all four required a person to
carry a number across. This one does not.

So `CallAttribution` records, per call:

| field | source | why |
|---|---|---|
| `requested_model` | ours | the label a benchmark would otherwise report alone |
| `served_model` | response `model` | a `:floor`/`:nitro` variant or a fallback resolves to something else |
| `upstream_provider` | response `provider` | **the field that decides whether two runs are comparable** |
| `generation_id` | response `id` | the only way to reconcile the *settled* cost later, via `/api/v1/generation?id=` |
| `prompt_tokens` / `completion_tokens` / `micros_usd` | response `usage` | §3.2 |
| `attempts` | ours | a retry is latency a benchmark must not silently absorb |
| `upstream_pinned` | ours | a pinned run and an unpinned one are different experiments |

**An absent field is recorded as `NOT REPORTED`, never filled in.** Substituting the requested
model for an unreported upstream would make a call whose provider was never reported render
identically to one whose was — the exact failure the field exists to catch, committed by the field
that exists to catch it. There is a test and a control for this.

`RunAttribution` folds a run and **flags `upstream_changed_mid_run`**. That is not an error —
OpenRouter is allowed to do it and it is often why a run finished at all — but a per-run average
across two quantizations is a number about no system, so the run record says so.

It reaches the run record (`RunSummary::attribution`, `Event::Run { attribution }`) and the
daemon's stderr **unconditionally, not behind `--dev`**: whether a number is reproducible is not a
diagnostic.

**Pinning.** `--openrouter-upstream <NAME>` sends `provider.order` with `allow_fallbacks: false`.
The `false` is load-bearing: with fallbacks allowed, `order` is a *preference*, and a pin that is a
preference is the unrecorded-upstream problem with a control that looks like it closed it.

**Sanitised where it arrives.** `provider`, `model` and `id` are strings a *server* chooses, and
they end up on a terminal, in the classic CLI's renderer, and in the run record. They pass through
`marlowe_contract::text::sanitize_line` and a length bound at the point of absorption — one door,
rather than three sites that each have to remember.

### 3.2 Cost and rate limits

* **Cost is reported, never estimated.** `usage: {include: true}` on every request; `usage.cost`
  (USD) becomes `Usage::micros_usd`, which is what `Event::Done`'s `spend_micros_usd` reads. That
  field has been zero for the whole of M2 because nothing ever put a number in it. A per-token
  price table committed to this repo would be stale the week it was written, and a wrong cost that
  looks precise is worse than no cost.
* **Retry is bounded and the bound is named.** `MAX_ATTEMPTS = 4`, exponential backoff from 500 ms,
  every wait clamped by `MAX_BACKOFF = 20s` — **including one a `Retry-After` header asks for**.
  `Retry-After: 3600` is well-formed and honouring it stalls a turn for an hour inside a wall-clock
  budget; the far end does not set our deadline. Retried: 429, 500, 502, 503, 504. Not retried:
  everything else, because the next attempt sends the same request. Audit finding E8 already
  records one unbounded retry loop in this project; the test asserts on the **count of attempts the
  transport saw**, not on the error message, which would read identically for a loop that ran
  forever.
* **Resumption is NOT built, and here is the state of it.** A run that dies at case 400 of 500 loses
  the run. What exists to make resumption *possible* later: every call's `generation_id` is
  recorded, so a partially-scored run can be reconciled against OpenRouter's own generation history
  without re-spending; and the harness spawns a fresh profile per case, so cases are independent.
  What does not exist: any checkpoint of which cases completed. Building it is a change to
  `tools/score_longmemeval.py` and `eval/`, and `eval/` is the scoreboard and is never modified for
  an implementation's convenience — so it is a decision, not a follow-up commit.

---

## 4. Egress — the ruling

**A model call is the harness's own infrastructure, and is NOT subject to layer 4's egress
policy.** The argument, and the condition the argument depends on:

Layer 4 exists so that **untrusted content cannot select an outbound destination**. Every element
of a `web` fetch's target is chosen inside a run — a URL from a page, a redirect from a server, a
path from a model — which is why deny-by-default plus per-host human approval is the right shape
there.

None of that is true of a model call. The host is a compile-time constant; the operator chose the
provider at startup with an explicit flag; the request body is the run's own context by
construction. There is nothing for a target-selection guard to adjudicate. The mirror-image case
already settles it in the other direction: the Ollama path also makes an outbound request, to
`127.0.0.1:11434`, and nobody has ever proposed adjudicating it — the reason is not that loopback is
safe, it is that **the destination is not chosen by anything inside the run.**

And the practical half: routing model calls through a per-host approval held for the session would
mean approving the model provider before Marlowe can answer anything, which is K6-adjacent friction
in exchange for adjudicating a decision the user already made at the command line.

**The ruling holds only while the destination cannot be chosen from inside a run, and that is
enforced structurally, not by this paragraph:**

* `transport::OPENROUTER_HOST` is a `const`. There is **no base-URL setting** and no environment
  variable that can move it. This mirrors `LocalEndpoint::new`, which returns `None` for any host
  that is not loopback.
* `marlowe_net::Target::parse` refuses plaintext `http` rather than upgrading it, and refuses
  userinfo in the authority.
* `marlowe-net` does not follow redirects, and `post_streaming` does not add any.

**If someone later adds a configurable base URL, this ruling lapses** and the model call becomes
ordinary egress. Say so in the same commit.

**What taking a `marlowe-net` dependency does *not* drag in.** `marlowe-net`'s own header is
explicit: *"this crate does not know the run's `EgressPolicy` and must not, or the permission layer
would have a second implementation inside a networking crate."* It holds no policy. Depending on it
imports a socket, not an adjudicator.

**Layers 1–3 are untouched.** An OpenRouter response is model output, class `AgentInferred`,
exactly as an Ollama response is. Nothing here creates a new source of `UntrustedContent`, and
`marlowe_permission::blocks_composed_targets` remains the single definition the adjudicator and the
loop both call.

---

## 5. The credential — an interim, named as one

STATE.md's ruling for this session: *"build the provider adapter; do NOT build the credential
broker."* The broker is **M5**, whose acceptance row is **"credential exposure to model context:
zero, structurally enforced and tested."**

**The interim.** One environment variable, `OPENROUTER_API_KEY`, read once by
`ApiKey::from_environment`, held in a type that cannot be printed.

**Why a variable and not a flag.** A `--openrouter-key` flag lands in shell history, in `ps`
output, and in any CI log that echoes its own command line. The variable is not *safe*; it is
**less bad**, and this document says so rather than glossing it.

**What is structural, and where each property is enforced:**

| Property | Enforced at |
|---|---|
| `{}` cannot print it | there is **no** `Display` impl — `format!("{key}")` does not compile |
| `{:?}` cannot print it | a hand-written `Debug`, which is what a panic, an `unwrap`, a `dbg!`, an `assert_eq!` failure and **every derived `Debug` on a struct holding one** will use |
| it cannot be serialised | no `Serialize`, so it cannot reach the journal or a wire frame by being a field of something that can |
| an upstream echoing it back is redacted | `OpenRouterDriver::provider_error` — **the single error constructor**, so a new error site cannot skip it by forgetting |
| it is not in the model's context | the request body carries no credential; the key is in an `Authorization` header |
| the fingerprint does not narrow a search | length + FNV over the whole value. **Not a prefix**: every OpenRouter key begins `sk-or-v1-`, so a "first eight characters" fingerprint identifies nothing and still leaks |

**The test asserts where it would leak, not where it is declared.** The adjacent worthless version
of this test would assert that `ApiKey` has no `Display`, or that `redact()` replaces a substring —
both true of a build where the driver calls neither, which is precisely `web`'s
`inline_threshold_bytes: 0`. So `crates/marlowe-openrouter/tests/key_containment.rs` drives the
**real driver** — real request assembly, real header construction, real error mapping — with only
the socket replaced by a `ScriptedTransport`, and asserts on the request body, the returned
`ModelStep`, the serialised run record, the `ProviderError` from a server that **echoes the key back
in its error body**, and the `--dev` request dump. It carries a negative control asserting the key
*is* on the wire, without which deleting the `Authorization` header would make the file greener.

**What M5 replaces:** the *sourcing* and the *lifetime* — storage, rotation, per-tool scoping, an
audit trail of every use. None of that exists here and none of it is faked.
**What M5 should NOT replace:** the containment properties in the table above. A broker that hands
out a `String` has moved the leak rather than closed it.

**Not covered by this interim, stated so it is not read as covered:** the variable is visible to
every child process the daemon spawns and to anything that can read the process environment; there
is no scoping, no expiry, and no record of which run used the credential.

---

## 6. Determinism — what is available, and what is not

`marlowe_eval repro --runs 2` reproduces **bit-identically** at a fixed seed and clock, and a
workspace test bans `HashMap` and stray clock reads to keep it that way.

**That guarantee is not available on a hosted model and this ADR does not pretend otherwise.**
Temperature, batching, upstream routing and silent model revisions all break it, and none of them
is ours.

**What is sent, and what each is worth:**

| Control | Worth |
|---|---|
| `temperature: 0` | removes *our* sampling contribution. Does not make an upstream deterministic — batching alone does not. |
| `seed` (passed through when supplied) | honoured by some upstreams, ignored by others. **Sending it is not the same as it working**, and nothing here can tell which happened. |
| `provider.order` + `allow_fallbacks: false` | pins *which system answered*, which is the only one of the three that bears on comparability at all. |

**What replaces the guarantee is the record**: §3's per-call resolved model, upstream, generation
id, token counts and cost. An honest *"not reproducible; here is exactly what was recorded"* is
worth more than a claim that does not hold.

**The local guarantees are untouched.** The eval adapter constructs no `Daemon` and cannot reach
this path; `ModelProviderChoice::Ollama` is the default and no environment variable moves it (§7);
the determinism guard's clock fences are unchanged — the driver's only time read is
`marlowe_net::age::Mark`, already fenced, which exposes `elapsed()` and no way to obtain a time
value, so a duration taken there cannot become a timestamp in a payload. The tool-call accumulator
is a `BTreeMap` because its iteration order decides the emitted batch order.

---

## 7. Zero-config must not regress — K6

**The default is `ModelProviderChoice::Ollama` and the only thing that moves it is
`--provider openrouter`.** Not an environment variable, not a config file, not a fallback.

`DaemonConfig::model_provider()` is **one function**, called by the run path to select a driver and
by `status()` to announce one. That is this project's `blocks_composed_targets` pattern: a test
asserting on it is asserting on the thing that decides, so the two cannot disagree.
`crates/marlowe-daemon/tests/zero_config_is_unchanged.rs` asserts it **with `OPENROUTER_API_KEY`
set** — which is the state any machine is in once someone has used any other OpenRouter tool — and
carries a control showing an explicit choice *does* move it.

**Load-time refusals, all exit(2), none falling back:**

* `--provider openrouter` with no `--openrouter-model` → names the flag, says there is deliberately
  no default, links the catalogue.
* `--provider openrouter` with `OPENROUTER_API_KEY` unset **or set to empty** → names the variable,
  distinguishes the two cases, and says explicitly that it does **not** fall back to the local
  model.
* `--provider <anything else>` → names the two valid values.

The refusal-not-fallback choice is the one worth restating: a benchmark launched at a frontier
model that silently measured a local 9B would not be a degraded result, it would be a **wrong** one,
and nothing downstream would ever observe the substitution because every label would read the name
that was asked for.

**`--serve` announces the resolved provider**, and `--status` carries `model_provider`. ADR-029's
rule — announced, never inferred — applied to the thing that decides whether a turn costs money.

---

## 8. ADR-008's routing, and the cloud-tag refusal

**The role abstraction survived. The table type did not, and this is a finding rather than a
complaint.**

`ModelRoute` — `Orchestrator | Worker | Summarizer` — is provider-independent and needed no change.
That is the half ADR-008 got right and it is the half that matters.

`Routing` — described as *"the only place a model name appears"* — **did not survive**, because it
fuses a provider-neutral structure (role → model) with a provider-*specific* validation:
`is_cloud_tag`, which refuses Ollama's `*-cloud` / `:cloud` proxy tags. A hosted table routed
through `Routing::new` would have to satisfy a rule about Ollama's tag namespace, and a slug like
`x/some-cloud-model` would be refused for a reason that does not apply to it.

**So `is_cloud_tag` is untouched, not routed around and not deleted, and the OpenRouter path never
constructs a `Routing`.** The refusal's purpose is to stop a *silent* local-to-hosted transition: a
tag that looks local, resolves through the local endpoint, and quietly bills an account. Choosing
`--provider openrouter` is the opposite of silent — it is an explicit flag, a named model, a
required key, and an announced startup line. The mechanism is correct where it is and inapplicable
here.

The hosted adapter holds its own single model slug. If a *second* hosted model per role is ever
wanted, the right change is to split `Routing` into the role table and the per-provider validator —
argued then, with a use case, not now.

**Capability.** `capability_for` is untouched. Every OpenRouter model reports
`ModelCapability::unmeasured`, which renders *"tool-call reliability NOT MEASURED on this
machine"*. **No OpenRouter model's tool-call reliability has been measured by this project and none
is claimed.** The measured `12/12 on 2026-08-08` belongs to `qwen3.5:9b` and stays there.

---

## 9. What IS verified live, and what is not

### 9.0 The real end-to-end run — three commands, and one of them reached openrouter.ai

**No valid API key was available.** A *bogus* one still produces a real round trip, and that turned
out to verify most of the transport:

```
marlowe --ask "..." --provider openrouter --openrouter-model anthropic/claude-sonnet-4.5
  → openrouter.ai refused the credential (HTTP 401). The key in `OPENROUTER_API_KEY` is not
    valid — check it at https://openrouter.ai/keys. Upstream said:
    {"error":{"message":"User not found.","code":401}}
    [failed · 0 ms]
```

**What that reading actually settles**, because a 401 is a real response from a real server:

* the rustls handshake to `openrouter.ai` through `marlowe-net::post_streaming` **works** — this is
  the first HTTPS request this project has made outside the `web` tool;
* the `Authorization` header reached the far end **intact and parseable** — "User not found" is the
  answer to a credential it read, not to one it could not find;
* a non-retriable status is **not retried**, is explained with the remedy, and quotes the upstream's
  own message **attributed** (`Upstream said:`) so harness prose and provider prose stay distinct
  (ADR-030);
* **the key is not in the error string** — the live path, not a scripted one;
* **Marlowe did not fall back to Ollama.** The turn failed, loudly, by name.

**And two defects were found by running it, neither of which any test in the suite could see** —
which is CLAUDE.md's *"budget one real end-to-end run per milestone as verification, not as a
demo"* earning its place for the third time in this project:

1. **`--status` never rendered `model_provider`.** The field was added to `StatusReport`, the daemon
   filled it from the right function, and **no renderer printed it** — so a daemon on openrouter.ai
   and one on loopback produced identical output. A declared control with no reader, shipped by the
   session whose §2 is about a declared control with no reader.
2. **`--status --provider openrouter` reported `provider ollama` and `qwen3.5:9b`'s measured
   reliability.** `agent::status` built its own `DaemonConfig` and was never handed the choice.
   `Daemon::status()` was correct throughout; the *caller* one function away was not — the same
   shape as the first-run disclosure being wired into `serve` and not into `ask`. The existing test
   asserted at the daemon, where the field is **set**, and nothing asserted at the CLI, where it
   comes **from**.

Both are fixed, and `status_shows_which_provider_answers_and_the_two_providers_do_not_render_alike`
asserts the render at `render_to` with a control that the two providers do not read alike.

The zero-config control was run in the same session, **with `OPENROUTER_API_KEY` exported**:
`marlowe --ask` with no `--provider` started a local daemon, printed the first-run disclosure, and
answered from `qwen3.5:9b` in 12.2 s. `marlowe --status` printed `provider ollama`. And the
load-time refusals fire: no model named → exit 2 naming the flag; no key → exit 2 naming the
variable and stating that it does not fall back.

### 9.1 What remains unverified

A 401 short-circuits before the request body is evaluated, so **every success-path wire claim below
is still taken from documentation rather than from a socket**:

1. Whether the top-level `provider` field appears on streamed chunks, and on which chunk.
2. Whether `usage.cost` is present in the final streaming chunk with `usage: {include: true}`, and
   whether it is USD or credits.
3. Whether the SSE keepalive is spelled `: OPENROUTER PROCESSING`.
4. Whether `provider.order` + `allow_fallbacks: false` pins as expected.
5. Whether the endpoint tolerates the exact request shape sent, in particular `tools` alongside
   `stream: true` and `usage.include`.
6. Every latency, cost and rate-limit number — there are none in this document, deliberately.

**All six are behaviours of the far end. None can be closed by a unit test**, and every one of them
is decoded defensively: an absent field records `NOT REPORTED` rather than a guess, an unrecognised
SSE line is ignored per the specification, and a mid-stream `error` object fails the call with the
upstream's own message.

`cargo run -p marlowe-openrouter --example live_probe` is the one command that closes items 1–5. It
requires a key and it prints what actually arrived, including whether each field was present.

---

## 9.2 No pinned contract was changed, and here is the check

`CONTRACTS.md`'s §4 pins the **M0a↔M0b eval boundary** — the JSON the eval harness and the
implementation speak over stdio. That is a different wire from the daemon↔client protocol in
`crates/marlowe-daemon/src/protocol.rs`, which this ADR does touch. Neither `StatusReport` nor
`Event` appears anywhere in `CONTRACTS.md`; the check is `grep -n 'StatusReport\|Event::' docs/design/CONTRACTS.md`,
which returns nothing.

The two protocol changes are **additive and both `#[serde(default)]`**: `Event::Run` gains
`attribution: Option<String>`, `StatusReport` gains `model_provider: String`. A client built before
this parses both frames. The eval adapter is untouched and constructs no `Daemon`, so §4's wire is
not on any path this ADR changes.

**What the size of the `daemon.rs` diff is, since it is larger than "wire a second driver" sounds.**
~549 changed lines, of which the single hunk replacing 122 lines with 230 is the existing `--dev`
sink block **re-indented into a match arm** plus the new OpenRouter arm beside it. The rest is
`ModelProviderChoice`, one field on `DaemonConfig`, one field on `RunSummary`, the `status()` branch,
the `set_model` refusal, and the attribution fold. **Deliberately not touched:** the accept loop,
`serve_one`, the socket token, the approval round-trip, the assembler window derivation, the
retrieval call, and every existing `--dev` line — all of which the diff can be grepped for and none
of which appears in it.

## 10. Consequences

* One new crate, one new `marlowe-net` primitive, one new CLI flag group, no behaviour change on
  any existing path.
* `Event::Run` and `StatusReport` gain one `#[serde(default)]` field each. Additive; an older
  client parses both.
* `ModelDriver` was **not** modified. It expressed everything OpenRouter needed — including the
  streaming split and the retract signal. The one thing it cannot express is **attribution**:
  `ModelCall` has nowhere to put "which upstream served this", so the adapter surfaces it
  out-of-band through a sink and an accessor. If a third provider needs the same, that is the
  argument for a field on `ModelCall`, and it should be made then.
* `spend_micros_usd` on `Event::Done` carries a real number for the first time — on this path only.

---

## 11. The mutation that found a defect in this ADR's own test

Ten mutations, each pointed at the test that should notice. **Nine were noticed. The tenth was not,
and the defect was in the test rather than the code.**

`MAX_ATTEMPTS` raised from 4 to 40 — thirteen minutes of sleeping inside one model call, which is
audit finding E8's shape exactly — left
`retrying_is_bounded_and_the_bound_is_the_named_constant` **green**, because it asserted
`transport_calls == MAX_ATTEMPTS as usize` and the expectation moved with the constant.

That is *"assert the property you care about, not a proxy that moves with it"*, committed inside a
test written to prevent an unbounded retry loop, by someone who had just written §3.2 about
unbounded retry loops. The proxy was *the code obeys the constant*. **The property is that a turn
cannot be stalled indefinitely, and that is a statement about wall time, not about a count.**

Closed by `retry::MAX_TOTAL_RETRY_WAIT` — a **literal** 60-second ceiling, asserted against
`worst_case_total_wait()`, with a control asserting the shipped schedule sits two orders of
magnitude inside it (a ceiling that only just holds is a number chosen to fit). The identical proxy
in the `Retry-After` clamp test (`== MAX_BACKOFF`, green for every value of `MAX_BACKOFF` including
an hour) was fixed in the same pass.

**The general form, for the next bound anyone writes:** a test that reads the constant it is
checking is green for every value of that constant. A bound needs a literal somewhere, and the
literal is the thing a future change has to argue with. Full table in
`runs/session-openrouter/WHAT-THIS-IS.md`.
