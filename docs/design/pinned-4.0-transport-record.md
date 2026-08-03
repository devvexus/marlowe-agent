# ~~PROPOSED~~ **PINNED** — `CONTRACTS.md` §4.0, the eval transport

**Status: PINNED 2026-08-02. `CONTRACTS.md` is authoritative; this file is the record of
how each decision was made and why.** Read `CONTRACTS.md` §§4.0–4.7 for the contract itself.

## What was pinned

Part A went in verbatim as §4.0. Part C went in as the §4.2 clarification. All five Part D
cases were decided:

| Case | Decision |
|---|---|
| 1 · `abstained: false` with empty `injected` | **Protocol error.** Same outcome, so the schema says so. §4.2 now states the exclusivity in both directions and the mapping is total. |
| 2 · §4.7 symmetry | **Both, by symmetry.** `abstained: true` requires empty `grounded_in`; `answered: false` requires `abstained: true`. |
| 3 · `error` in the envelope | **Kept.** stderr-plus-exit would make a recoverable bug indistinguishable from a crash and throw away the rest of the run. |
| 4 · `channel` / `speaker` vocabularies | **Pinned as closed sets** — eight channels, three speakers. An unrecognized value is a load-time error on both sides, never a default. A silently-trusted default would make the laundering suite pass while measuring nothing. |
| 5 · The clock's shape | **Normalized to `clock: { now_ms }` on all three interfaces**, and §4.1's Rust binding updated to match. The top-level `now_ms` was a wart a third-party implementer would hit on their first request. |

**Version:** no major bump was taken. The clock normalization is breaking to the wire, but
no implementation has ever consumed this contract — the only reader was the M0a harness,
updated in the same change. Recorded in `CONTRACTS.md` under the version constant.

The harness was updated to match; 67 tests pass. Four new conformance fixtures
(`empty_without_abstention`, `grounded_while_abstained`, `unanswered_without_abstention`,
plus closed-set vocabulary checks) demonstrate that each newly-pinned rule discriminates.

---

*The original proposal follows unchanged, as the argument of record.*

Two things are proposed here:

1. **§4.0 — Transport.** New section. §§4.1–4.7 pin three payloads and no way to deliver one.
2. **A clarification to §4.2.** `abstained: true` with a non-empty `injected` is currently
   readable two ways. Two implementations could disagree, which means §4 is underspecified there.

Part A is the text to paste. Part B is the argument for each choice, kept out of the pinned text.
Part C is the §4.2 clarification. Part D lists what I could not decide alone.

---

# Part A — the proposed text

> ## 4.0 Transport
>
> §§4.1–4.7 pin *what* crosses the M0a↔M0b boundary. This section pins *how*. It is framing and
> nothing else: it adds no field that carries meaning, and it is not a fourth interface.
>
> ### 4.0.1 Channel
>
> The implementation exposes an **eval adapter**: a process that reads request frames on stdin
> and writes response frames on stdout. `stderr` is diagnostic only and is never parsed.
>
> The harness spawns the process, owns its lifetime, and closes stdin to end the run. It never
> attaches to a process it did not start.
>
> This does not conflict with ADR-002. The daemon still owns the journal, the indexes, and the
> socket; an implementation satisfies §4.0 with a thin forwarding mode
> (`marlowe --eval-adapter`) that reads a frame, hands `body` to the daemon, and writes the
> response back. That bridge belongs to the implementation, not to the harness.
>
> ### 4.0.2 Encoding and framing
>
> **Newline-delimited JSON.** One JSON value per line.
>
> - UTF-8, no BOM.
> - Each frame is terminated by a single `\n` (U+000A). A `\r\n` terminator is a protocol error.
>   Implementations on Windows must set stdout to binary/raw mode.
> - A frame contains no literal newline. RFC 8259 requires control characters inside strings to
>   be escaped, so a correctly serialized JSON value satisfies this without extra discipline.
>   **Pretty-printed output is a protocol error**, not a tolerated variation.
> - The implementation **must flush stdout after each response frame.** A response sitting in a
>   buffer is indistinguishable from a hang.
> - Maximum frame size is 64 MiB. An overlong line is `malformed_frame`.
>
> ### 4.0.3 Frames
>
> Request:
>
> ```json
> {"op": "ingest", "body": { "...": "the §4.6 request, verbatim" }}
> ```
>
> `op` ∈ `ingest` | `retrieve` | `answer`, selecting §4.6, §§4.1–4.4, and §4.7 respectively.
>
> Response, when a §4 response exists:
>
> ```json
> {"op": "ingest", "body": { "...": "the §4.6 response, verbatim" }}
> ```
>
> Response, when no §4 response exists:
>
> ```json
> {"op": "ingest", "error": {"kind": "internal_error", "detail": "index not loaded"}}
> ```
>
> **Frame rules.** `op` must echo the request's. Exactly one of `body` and `error` is present.
> Any additional key at frame level is a protocol error. `body` is the §4 JSON **verbatim,
> byte-for-byte** — no compression, no batching, no envelope metadata, no reordering of the
> payload's own fields required or permitted to carry meaning.
>
> ### 4.0.4 `error` is the absence of a §4 response, not a variant of one
>
> §4.6's `rejected` is a **successful** response: the implementation understood the request and
> refused a write, and the poisoning suite asserts on exactly that. It travels in `body`.
>
> `error` means the request produced no §4 response at all. `kind` is a closed set in two
> classes, and the classes are handled differently because they mean different things:
>
> | Class | `kind` | Meaning | Harness behaviour |
> |---|---|---|---|
> | **A — the request was bad** | `malformed_frame`, `unknown_op`, `malformed_body`, `contract_version_unsupported` | The harness or the version pairing is at fault | Abort the run. This is a defect, not a measurement. |
> | **B — the implementation failed** | `internal_error` | The system under test failed on a well-formed request | Record a failed unit and continue. This is a **result** and appears in the report. |
>
> ### 4.0.5 Ordering and correlation
>
> **Strictly serial.** The harness writes one request and reads exactly one response before
> writing the next. There is never more than one outstanding request, so **there are no
> correlation ids** — correlation is positional.
>
> It is additionally checked, so a desynchronized stream fails loudly rather than silently
> misattributing a result: the response `body` must echo the request's `query_id` (`retrieve`,
> `answer`) or `session_id` (`ingest`). A mismatch is a protocol error and aborts the run.
>
> ### 4.0.6 Startup and shutdown
>
> **No handshake.** `contract_version` is already present in every §4 body, so version
> disagreement is detectable per-message and needs no negotiation round. The first frame on the
> wire is a request.
>
> The harness signals end of run by closing stdin; the implementation flushes and exits 0.
> Anything an implementation wishes to announce at startup goes to stderr.
>
> ### 4.0.7 Failure semantics
>
> | Condition | Classification | Effect on the report |
> |---|---|---|
> | Class B `error` frame | Failed unit | Scored and reported |
> | EOF or process exit mid-request | `implementation_crashed`. **No retry** — a retry makes the outcome depend on timing | Run marked crashed; remaining units not attempted; the report is emitted, because a crash is a result |
> | Class A `error` frame, frame-rule violation, `op` mismatch, id mismatch | Protocol error | Run aborts; no report |
> | **Harness-imposed deadline exceeded** | A wall-clock decision by the harness | Run marked `timing_tainted`: **no headline report, hash not comparable** |
> | **Implementation exceeds `budget.max_latency_ms`** | **Not a transport event.** A valid §4 response was returned; the miss is in `cost.latency_ms` | **Scored and reported normally** |
>
> The last two rows are distinct and must not be conflated. An implementation missing the 300 ms
> P95 is a *result the eval exists to produce*; it is never a reason a run cannot report. The
> harness deadline exists only to bound a hung process, and is therefore set far above any
> budget: **no lower than 100× the request's `max_latency_ms`, floored at 30 s.**
>
> ### 4.0.8 Determinism
>
> The transport contributes nothing to a run's identity: no ids, no timestamps, no sequence
> numbers, no retries, no concurrency, no buffering-dependent ordering. For a given §4 body the
> frame bytes are a pure function of that body.
>
> `cost.latency_ms` is self-reported by the implementation and varies between runs by nature. It
> is therefore excluded from any bit-identity claim, recorded and scored rather than hashed.
>
> ### 4.0.9 Language-agnosticism
>
> A conforming implementation needs a UTF-8 line reader on stdin, a JSON parser, a JSON writer,
> and a flush. Nothing else — no shared library, no generated bindings, no runtime schema
> negotiation, nothing from the harness's side but the bytes. The harness's Python types are a
> *binding* of this contract; the wire format is the contract.
>
> The harness spawns the target's argv unmodified, with a declared minimal environment, so a run
> does not inherit ambient state a third party cannot reproduce.

---

# Part B — why, argued rather than asserted

## B1 · stdio, not a unix socket

You asked this be answered rather than assumed. The honest case for a socket is real, so it goes
first.

**For a socket:** ADR-002 already has the daemon listening on one, so a socket adapter is less
new code for M0b. And a per-run spawned process pays daemon startup once per run.

**Why stdio wins anyway:**

1. **Lifecycle ownership.** The harness spawns the process, so the run begins from a state the
   harness established. A socket invites attaching to an already-running daemon — and then the
   run's outcome depends on state the harness did not create and a third party cannot reproduce.
   That is fatal to the reproducibility claim, and it is fatal quietly.
2. **Unambiguous crash semantics.** EOF on stdout is a crash, full stop. A socket gives connection
   resets that are indistinguishable from permission, path, and stale-socket conditions — three
   failure modes that are not the system under test.
3. **Determinism by construction.** One stream, serial. Sockets invite multiplexing and
   concurrency, which is precisely the ordering nondeterminism the acceptance criterion forbids.
4. **Portability in fact.** AF_UNIX on Windows exists but is uneven, and named pipes are a
   different API. Stdio is identical everywhere. M0a must run wherever a third party runs it,
   which is not necessarily WSL2.
5. **Cost to a stub.** A conforming stub is ~20 lines. A socket stub needs a listener, path
   selection, permissions, and cleanup — all of it in the measurement instrument's dependency
   surface.

**On the daemon-startup cost:** it is real and it is bounded. The harness spawns one process per
*run*, not per query, so startup amortizes over 500–1,540 queries. And the forwarding bridge is
small and belongs in M0b, which is the point — connection policy, socket paths, and daemon
lifecycle are each a source of run-to-run variance, and none of them should live inside the thing
doing the measuring.

## B2 · NDJSON, not length-prefixed frames

Length-prefixing is more robust in general: no scanning, indifferent to embedded newlines. It
buys nothing here and costs the thing that matters most.

**The wire log is the reproducibility artifact.** `run.jsonl` is the full transcript of every
request and response, and *reproducible by a third party from the repo alone* is an M0a acceptance
criterion. A third party diffs two runs with `diff`, inspects a frame with `grep`, and replays one
with a one-line script. Length-prefixed frames require writing a decoder before you can look at
your own data.

The delimiter is safe without escaping discipline, per RFC 8259. The residual risk — an
implementation that pretty-prints — is handled by naming it `malformed_frame` and bounding line
length, so it surfaces as a loud protocol error rather than a hang or an OOM.

## B3 · No correlation ids

An id in the envelope would be an envelope field that carries meaning, which the constraint
forbids, and it would be dead weight: with one outstanding request there is nothing to correlate.
Echo-checking `query_id`/`session_id` gives the same desynchronization detection using fields §4
already pins, so the envelope stays meaningless and the check stays real.

## B4 · The `body`/`error` split, and the tension in it

This is the least comfortable part of the proposal and is flagged rather than smoothed.

The constraint is that the transport carries §4 messages unchanged. `error` is a frame-level key
that is not a §4 message, so it is fair to ask whether it violates that. The argument for keeping
it: an implementation needs a way to say *"no §4 response exists for this request"* without dying,
and the alternatives are worse — inventing an error shape inside a §4 payload would genuinely
change §4, and using process death for every internal failure would make a recoverable bug
indistinguishable from a crash and would throw away the rest of the run.

So `error` is defined as the **absence** of a §4 message rather than a variant of one, and `body`
remains verbatim in every frame that has one. If you would rather not have it, the fallback is
stderr plus exit, and the cost is that one bad query ends the run.

---

# Part C — proposed clarification to §4.2

**`abstained: true` with a non-empty `injected` is currently underspecified.** Two readings:

- **(a)** `abstained` means *"I am injecting nothing"* → `injected` must be empty.
- **(b)** `abstained` means *"I am flagging low confidence"* → `injected` may be populated.

Two implementations could reasonably differ, and the harness cannot score reading (b): if a
response both abstains and injects, an injected item is either a claim (scored for injection
precision) or a hedge (not scored), and nothing in §4 says which. That is the same blurring §4.7
already forecloses for `answered: false` with a populated `answer` — and §4.7's stated reason
applies verbatim here: *a schema that lets them blur is a schema that will let a confabulation
score as an abstention.*

Reading (a) is also what all four `abstention_reason` values entail. `no_candidate_above_threshold`,
`no_candidates`, `budget_exhausted`, and `degraded_path` each describe having nothing to inject.

**Proposed addition to §4.2**, after the `abstention_reason` paragraph:

> **`abstained: true` requires `injected` to be empty, and `abstained: false` requires
> `abstention_reason` to be null.** A response that abstains while injecting is a protocol error,
> not a hedge — the same distinction §4.7 draws for `answered: false` with a populated `answer`.
> All four `abstention_reason` values entail an empty candidate set: an implementation with
> something to inject has not abstained.

The harness enforces both directions as `ProtocolError`, identical treatment to the missing-`cost`
and hedged-`answered` rules.

---

# Part D — what I could not decide alone

Five cases §4 leaves open. Items 1–3 are adjacent to Part C; items 4–5 surfaced while building the
models and are load-bearing for M0a. I have **not** written harness rules for 1–3; they are
recorded at runtime instead, so a run against a real implementation surfaces which reading M0b took
rather than failing on my guess.

1. **`abstained: false` with an empty `injected`.** Legal? By any plain reading this *is* an
   abstention (`no_candidates`), but forcing it would be a third inference on top of the two above,
   and there may be an intended distinction between *"I found nothing"* and *"I declined"*. My
   inclination is that they are the same outcome and the schema should say so.
2. **§4.7 by symmetry.** The answer response also carries `abstained`/`abstention_reason`. Does
   `abstained: true` there require `grounded_in` to be empty, and does `answered: false` require
   `abstained: true`? The same confabulation-scores-as-abstention argument suggests yes to both,
   but §4.7's pinned text addresses only the `answer` field.
3. **Whether `error` belongs in the envelope at all** — see B4. The fallback is stderr plus exit,
   at the cost of one bad query ending a run.

4. **§4.6 pins `origin.channel` and `speaker` but not their vocabularies.** The field is pinned;
   the value set is not. The example shows `channel: "terminal"` and `channel: "web"`, and
   `speaker: "user"` and `speaker: "tool"`. This is load-bearing, not cosmetic: the laundering
   suite's entire assertion is that a claim entering as `channel: "web"` comes out
   `untrusted_content`, which requires both sides to agree on that string. Benchmark histories also
   carry assistant turns, which `speaker` has no pinned value for.

   The harness currently emits `terminal · voice · messaging · email · web · mcp · tool_output ·
   file` and `user · assistant · tool`, marked UNPINNED in `contract/common.py`. If M0b's derivation
   table keys off a different set, the laundering result is silently wrong rather than loudly
   broken — an unrecognized channel most plausibly maps to *some* default, and if that default is
   trusted, the suite passes while measuring nothing. Worth pinning as a closed set.

5. **The clock's shape differs across the three interfaces.** §4.1 puts `now_ms` at the top level
   of the retrieval request (and §4.2b's binding agrees: `pub now: Timestamp`), while §§4.6 and 4.7
   carry a `clock: { now_ms }` object. §4.5 says *"`clock` is required on all three interfaces"*,
   which reads as though retrieval should carry the object too.

   I implemented the pinned examples literally — `now_ms` for retrieve, `clock.now_ms` for ingest
   and answer — because the JSON is normative and normalizing it would be the harness quietly
   editing the contract. It is more likely a wart than a disagreement, but a third-party
   implementer will hit it on their first request, so it should either be made uniform or have a
   sentence saying it is deliberate.
