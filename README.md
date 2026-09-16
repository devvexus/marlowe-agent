# Marlowe

A local-first agent harness written in Rust. It gives a language model memory, tools, long-running tasks, and permissions it has to earn. Runs in the terminal as one binary.

**How it works**
- Everything goes into one append-only event log. Each entry is signed and records where it came from.
- Memory, sessions, running tasks, and the audit trail are all built from that log.
- Each agent step reads the current state, does one thing, and writes the result back to the log.
- Replay is just reading the log.

**Size**
- 18 Rust crates
- 83k lines of code, 46k lines of tests
- 1,749 tests
- 72 design decision records
- A separate Python eval harness scores the Rust build. The harness is never changed to make a score pass.

---

## What makes it worth a look

### 1 · Prompt injection is answered by construction, not by filtering

The design position is explicit: **filtering does not work; containment works.** There is no
classifier deciding whether a web page looks malicious. There are five numbered layers instead, and
the load-bearing ones are enforced by the type system and the loader rather than by review:

- **Quarantine.** The component that reads untrusted content declares `reads_untrusted: true` and
  carries an empty tool set. `reads_untrusted && !exposed_tools.is_empty()` is a **load-time
  error** — a reader that can act cannot be constructed, so the rule cannot be forgotten. It hands
  a validated summary to a parent that never sees the raw bytes.
- **Trust propagation.** Every belief carries its origin, and trust propagates **worst-case over
  full lineage**. Four LLM rewrites later, a web page is still `UntrustedContent`. This is what
  stops laundering.
- **The `(action, target)` split.** Untrusted content may shape a **payload** — a draft body, a
  summary — and may never shape a **target**: which tool, which recipient, which path, which
  amount. It is a monotonic latch on the run, because deriving the floor from the current context
  window meant that trimming the untrusted block silently restored privileges.
- **Egress allowlisting.** Deny by default, empty allowlist, per-host human approval, and the grant
  is held for the run rather than re-asked on every fetch.

Measured in the product's own signed journal rather than argued: **7 composed shell commands
issued, 7 refused**; **37 egress decisions, every one routed to a human, 29 granted and 8 declined**.

The same scepticism is turned on the defences themselves. The repository records, in its own
security ledger, that one of those layers is currently **unreachable in the shipped daemon** — the
production path that could taint a run has no caller — so a red-team zero taken today would read
identically whether the guard works or has been deleted. Advertising five defences and then writing
down which of them cannot presently fire is the unusual part.

### 2 · Every number is a command that prints a number

A target that is not executable does not exist. Concretely:

- **Pre-registered splits and predictions.** The split and the predicted bands are written to disk
  before any fit, and the fit gate refuses to run without them — so a result can never be read as
  evidence for something nobody predicted in advance.
- **Kill criteria written before the measurement**, each with its verdict stated up front,
  including project-level ones. K1 asked for ≥0.95 injection precision. The answer came back *no
  coverage level reaches it with its confidence interval above the threshold*, and that is
  published as a curve with exact Clopper–Pearson intervals at every coverage level from 100% down
  to 10% — shipped with the binary rather than quietly dropped.
- **A standing ledger of the project's own measurement failures** — twenty of them, each a case
  where a metric answered a question *adjacent* to the one being asked and read identically when
  the thing it described was broken. A security banner that fired on every run ever made. A recall
  metric counting a superseded fact as a hit, inflating every score in the project. A declared
  safety control that no line of code read, with a green test asserting the declaration. The
  standing question is *what would this read if the property I care about were broken?*

### 3 · Retrieval is a measured ML system, not a vector-store call

Hybrid lexical and dense retrieval, a fusion gate frozen after fitting on a pre-registered split,
and a **fine-tuned cross-encoder reranker** (+0.0699 R@1 over the stock checkpoint) served through
ONNX with the graph digest-pinned at load and a reference fixture that is never regenerated to make
a test pass.

The quantization finding is the part worth reading. An int8 graph turned out to be bound to its
tensor shape in *every* dimension, not just batch: re-padding bit-identical token ids to a longer
tensor moved logits by a median 0.0109 and **flipped top-1 in 15% of cases**, while all eight f32
graphs were invariant to 0.000000. The shipped path moved to f32 as a result. Determinism, batch
invariance and padding invariance are re-measured per graph and never inherited from a previous
one.

### 4 · Runs are durable objects, not in-flight function calls

The daemon owns runs and they outlive the client that started them. Checkpoint resume was
demonstrated live against a `taskkill /F`-ed daemon, with the run's context window, spend, step
count, capability profile and latched trust floor all surviving. Steering a run mid-flight from a
second process works — and a steer is treated as a write that takes the full adjudication path
rather than a side door into a running agent.

### 5 · Performance is measured before it is believed

Two earlier measurements of time-to-first-token disagreed and could not be reconciled, because
every candidate explanation lived in the difference between the two runs rather than the two
clocks. The fix was an instrument taking **both clock placements on the same request off one
`perf_counter`**, which turns the disagreement into a subtraction. It found llama.cpp **4.8× faster
to first token than Ollama** on the same GGUF blob — and that engine was then **shelved anyway**,
because its tool-call parsing did not survive real use. Speed lost to correctness, and the number
is still published along with the reason it did not ship.

---

## The numbers

| | measured | budget / baseline |
|---|---|---|
| Cold launch → accepting connections, fresh profile | **70 ms** | 300,000 ms (kill criterion K6) |
| Harness's own share of an end-to-end ask | **68–198 ms** | the rest is model inference |
| Time to first token, llama.cpp vs Ollama, one GGUF blob | **65.3 ms vs 313.4 ms — 4.8×** | median of 11 warm reps per arm |
| Retrieval P95, warm / cache-cold | **211 ms / 238 ms** | ≤ 300 ms |
| Held-out R@1 / R@5 / R@10, LongMemEval | **0.6725 / 0.8865 / 0.9039** | n = 229, pre-registered split |
| Declared retrieval operating point | **precision 0.9130 at 10.0% coverage**, 95% CI [0.7196, 0.9893] | below the margin, it abstains |
| Sustained durable journal append | **633/s** | ≥ 50/s, and the caveat travels with the number |
| Composed-target refusals in the live journal | **7 issued, 7 refused** | — |

Each is reproducible from a command in the repository. The operating point ships as a
machine-readable artifact alongside the binary, because a confidence signal the product does not
disclose is one nobody can check.

---

## Running it

```bash
cargo build --release
target/release/marlowe.exe --launch      # opens a terminal Marlowe configures for itself
target/release/marlowe.exe --tui         # or stay in the current one
```

The client auto-spawns the daemon, so `marlowe --serve` is only needed to run it yourself. There is
no default mode — every invocation names one. It needs Ollama serving `qwen3.5:9b` and a terminal
of at least 120×30. Twelve tools are exposed to the model: `read`, `write`, `edit`, `glob`, `grep`,
`bash`, `web`, `recall`, `use`, `ask`, `remember`, `run`.

```bash
cargo test --workspace --no-fail-fast    # the implementation
cd eval && python -m pytest              # the scoreboard, run against the shipped binary
```

---

## Status — built, and not

**Complete.** The evaluation harness (M0a), the memory prototype and its retrieval stack (M0b), the
terminal interface (M1), and the agent loop with tools, skills and the permission layer (M2).

**In progress.** The durable run control plane (M3): runs as first-class objects, WAL and
checkpoint resume, mid-flight steering and the watch surface are built; the agent tree and its
typed upward channels are in flight.

**Designed, not built, and labelled as such wherever it is described.** The per-team OS sandbox — an
accepted decision record with no code behind it — scoped memory, and the trust ledger that gates
consequential actions behind earned tiers.

---

## Where to look

| Path | What it is |
|---|---|
| [`docs/design/ARCHITECTURE.md`](docs/design/ARCHITECTURE.md) | Component boundaries and the agent loop |
| [`docs/design/DECISIONS.md`](docs/design/DECISIONS.md) · [`docs/design/adr/`](docs/design/adr/) | 72 decision records, with the arguments and the reversals |
| [`docs/design/SECURITY-AUDIT.md`](docs/design/SECURITY-AUDIT.md) | Open security findings — a standing ledger, not a closed report |
| [`docs/design/PRECISION-COVERAGE.md`](docs/design/PRECISION-COVERAGE.md) | The published precision/coverage curve |
| [`docs/design/ROADMAP.md`](docs/design/ROADMAP.md) | Milestones and the kill criteria |
| [`STATE.md`](STATE.md) | What is built, what is next, and what is known to be wrong |
| [`eval/`](eval/) | The Python scoreboard |
| [`persona/`](persona/) | The persona as a versioned, provider-independent artifact |

Rust, with a deliberately separate Python evaluation harness, against local models over loopback —
no account, no key, and no network on the default path.
