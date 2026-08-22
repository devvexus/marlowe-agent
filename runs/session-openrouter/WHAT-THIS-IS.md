# ADR-046 session evidence

## `suite.txt` — the workspace suite, once, `--no-fail-fast`, to a file

```
91 `test result` lines · 983 passed · 2 failed · 2 ignored
```

Master's last recorded figure was 944 passing. The delta is this session's tests plus the
`rerank_provider` target, which is **absent from the tally** — see below.

### The two failures, classified. **Neither is a regression, and one of them was checked twice.**

**1. `marlowe-memory` · `cuda_libs_wiring::both_loaders_read_the_cuda_lib_variable_and_refuse_in_its_words`
— ENVIRONMENTAL.**

Its own output says why: `SKIP embedder half: run python tools/fetch_model.py` /
`SKIP reranker half`, then *"neither model is present, so neither call site was exercised. This
test cannot distinguish a wired loader from an unwired one here."* **`models/` does not exist in
this worktree** (it is gitignored and never vendored). The test is refusing to be vacuous, which is
the correct behaviour. `crates/marlowe-memory` is untouched by this session — `git diff --stat
master` lists no file under it.

**2. `marlowe-daemon` · `socket_auth::a_silent_peer_does_not_wedge_the_daemon`
— LOAD-INDUCED, NOT A REGRESSION. Two independent readings say so.**

This one was reported to this session as *"a regression and it is yours"*, on the reasoning that
`daemon.rs` changed by ~547 lines and the test asserts a denial-of-service property. That reasoning
is sound and the conclusion is wrong, so the evidence is written down here rather than argued.

*Reading A — the code.* The test's subject is the accept loop and the 5-second socket read timeout
in `Daemon::serve` / `Daemon::serve_one`. **Neither appears anywhere in this session's diff:**

```bash
git diff -U0 master -- crates/marlowe-daemon/src/daemon.rs \
  | grep -E '^[+-]' | grep -E 'serve_one|incoming|set_read_timeout|TcpListener|accept\(\)|shutdown'
# (no output)
```

`serve` is at line 1339 and `serve_one` at 1369; the last diff hunk ends at 1199. Every changed
line is in `DaemonConfig`, `RunSummary`, `status()`, `set_model()` and `ask_streaming_with` — the
turn path, not the connection path.

*Reading B — the measurement.* The failure was `the silent peer was still holding the daemon after
7.0714001s` against a deadline the test sets from wall time. It was recorded **while the suite's own
16-core compilation was still running** — CLAUDE.md's hazard form 6, *"one session's build
invalidates another's measurement"*, self-inflicted rather than cross-session. Re-run alone on a
quiet machine, **twice**:

```
run 1: test a_silent_peer_does_not_wedge_the_daemon ... ok   (5 passed, 7.58s)
run 2: test a_silent_peer_does_not_wedge_the_daemon ... ok   (5 passed, 7.58s)
```

Both readings had to agree before this was called environmental, because a timing test failing
next to a large diff in the same crate is exactly the coincidence that should not be waved away.
**The standing risk this leaves is real and is not this session's to fix:** the test's margin is
thin enough that a loaded machine flips it, so it will do this again to someone else. That is a
note for whoever owns `socket_auth`, not a licence to widen the deadline from here.

*Also absent from the tally:* `marlowe-memory` · `rerank_provider` produced no `test result` line
because two of its tests — `a_reserve_for_an_installed_model_is_larger_than_the_rerank_graph` and
`a_reserve_for_an_uninstalled_model_is_zero_and_says_why` — **hung indefinitely** (>5 minutes, 0.06s
CPU, no child process) inside `std::process::Command::new("ollama").arg("list")`, with `ollama`
running and `127.0.0.1:11434` answering 200. The binary was killed so the rest of the suite could
finish. Pre-existing, environmental, outside this session's territory, and worth someone's
attention: a test that hangs rather than fails is a suite that cannot produce a count.

## `mutations.txt` — ten mutations, and the one that mattered

Ten deliberate reversions, each pointed at the test that should notice. The script refuses to run
when its pattern does not match exactly once, because a mutation that silently fails to apply
reports a clean bill of health.

**Nine were noticed on the first pass. The tenth was not, and it found a defect in this session's
own test rather than in the code.**

`unbounded_retry` raises `MAX_ATTEMPTS` from 4 to 40 — thirteen minutes of sleeping inside one
model call, which is audit finding E8's shape. The test named
`retrying_is_bounded_and_the_bound_is_the_named_constant` asserted
`transport_calls == MAX_ATTEMPTS as usize`, so **the expectation moved with the constant** and the
mutation stayed green.

That is *"assert the property you care about, not a proxy that moves with it"*, committed inside a
test written to prevent an unbounded retry loop. The proxy was *the code obeys the constant*; the
property is *a turn cannot be stalled indefinitely*, which is a statement about wall time, not a
count. Closed by `retry::MAX_TOTAL_RETRY_WAIT`, a **literal** 60-second ceiling asserted against
`worst_case_total_wait()` — with a control asserting the shipped policy sits two orders of magnitude
inside it, because a ceiling that only just holds is a number chosen to fit. The same proxy in
`a_server_supplied_wait_is_clamped_rather_than_obeyed` (`== MAX_BACKOFF`) was fixed in the same
pass. Re-run: **NOTICED.**

Final: **10 of 10 noticed.**

| mutation | what it reverts | noticed by |
|---|---|---|
| `no_redaction` | the redaction at the single error constructor | 3 key-containment tests |
| `key_in_body` | puts the credential in the request body | 3 key-containment tests |
| `unbounded_retry` | `MAX_ATTEMPTS` 4 → 40 | `retrying_cannot_stall_a_turn_for_longer_than_the_stated_ceiling` (**after the fix above**) |
| `retry_401` | retries a bad credential | `a_credential_failure_is_not_retried` |
| `assign_fragments` | assigns tool-call argument fragments instead of appending | `a_tool_call_split_across_chunks_reassembles_into_one_call` |
| `default_upstream` | fills an unreported upstream in from the requested model | `an_unreported_upstream_says_so_rather_than_defaulting_to_the_requested_model` |
| `done_is_json` | parses the `[DONE]` sentinel as JSON | 3 SSE tests |
| `env_flips_default` | lets `OPENROUTER_API_KEY` alone select the hosted path | did not compile — caught by the type system |
| `allow_header_injection` | accepts CR/LF in a header value | `a_header_value_carrying_crlf_is_refused_rather_than_stripped` |
| `tls_in_provider` | adds `marlowe-net` to `marlowe-provider` | `marlowe_provider_reaches_no_tls_crate` |

## What is NOT here

**No live call to openrouter.ai.** No API key was available. ADR-046 §9 lists the six wire
behaviours that leaves unverified and names the one command that closes five of them:

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
cargo run -p marlowe-openrouter --example live_probe -- anthropic/claude-sonnet-4.5
```

There are no latency or cost numbers anywhere in this session's output, deliberately.
