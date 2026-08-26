# ADR-057 — Who declares a child's contract

| | |
|---|---|
| **Status** | Accepted, M3 Session B1, 2026-08-26 |
| **Supersedes** | nothing. It removes the refusal `builtin.rs` shipped in place of a spawn |
| **Depends on** | ADR-023 (the trust-floor latch), ADR-053 (what a checkpoint carries), M3-DESIGN §1, §4, §5 |
| **Implements** | ROADMAP M3's *runs are first-class*; M3-DESIGN §1.1 *"the only agent Marlowe ever creates is a top-agent"* |
| **Contract change** | **None.** `SpawnRequest` is unchanged in shape. `run`'s registered parameter `budget_micros_usd` is renamed `budget_tokens` — see §6 |

---

## §1. The decision

**The parent declares every field of a child's contract at the call, and the harness supplies by a
fixed rule — stated here, once — every field the parent did not name. Nothing is read out of the
task.**

`SpawnRequest` has seven fields. The model supplies one of them. The blocker recorded in
`ollama.rs`'s `run` arm was that synthesising the other six is what M3-DESIGN §5 forbids:

> §5 requires a spawn's capability profile, budget and orphan policy to be *declared at spawn, never
> inferred*, and the model supplies a task. Synthesising the rest is precisely what that rule
> forbids.

That reading is right about inference and wrong about defaults, and the distinction is the whole
decision. **Inference is reading the task and concluding something about the contract** — seeing
"search for X" and giving the child `web`. **A default is a fixed constant that does not vary with
the task**, and a constant chosen once and written down is a declaration, not a synthesis.

So the rule is per-field, and it is total:

| Field | Declared by | Rule when the parent does not name it |
|---|---|---|
| `task` | the model, **required** | there is none; an empty task is refused by name |
| `contract` | the model's `output_contract` line | `"what you found"`, one `findings` field — a **shape** the harness fixes, never a shape read from the task |
| `tools` | the model's `exposed_tools` | **empty.** Not the parent's set |
| `grant_tokens` | the model's `budget_tokens` | `None` → `share` of the parent's *original* pool |
| `share` | **the harness, always** | `Standard`. Not model-reachable at all — see §5 |
| `orphan` | the model's `orphan_policy` | `Terminate` — the child dies with its parent |
| `reads_untrusted` | **the harness, always** | `false`. Not model-reachable at all — see §5 |

Every default above is the **conservative end** of its field: no tools, the smallest lifetime, a
share rather than a grant. A model that names nothing gets a child that can think and return a
string, and nothing else.

---

## §2. Why the defaults are safe to have at all — the receipt

A default is safe when a mismatch between what was asked for and what was granted is **observable**.
CLAUDE.md's standing rule is *"watch for defaults that make a mismatch unobservable"*, and the
answer here is not to refuse — it is to say what was granted.

**`Engine::spawn` pushes a receipt into the parent's context at spawn time**, before the child runs:

```
[spawned] tools: none · budget: 37500 tokens · orphan: terminate · returns: what you found
```

Before this there was nothing at all until the child finished. A model that asked for `read` and got
`none` — because the parent did not hold `read` — could not previously tell; now the next model call
sees the granted contract in its own window and can correct or complain.

This is also why an unrecognised `orphan_policy` is **not** refused. The model's vocabulary is two
words, the shipped model is a 9B local model, and a dead turn on a misspelling is a worse product
than the safe value plus a line saying which value was used.

**`adopt` is the third `OrphanPolicy` variant and it is not in the model's vocabulary at all.**
`OrphanPolicy::Adopt { by }` names a run id; the model has no way to name one, there is no `await`
for it to name one from, and a policy whose argument cannot be supplied is a policy that cannot be
declared. It is withheld the way §5 withholds `share` — the word is not accepted, rather than
accepted and quietly turned into something else. `settle_orphan` still implements all three, and the
harness may still declare `Adopt` at a spawn site of its own.

---

## §3. Narrowing is the engine's, and it already refuses

`engine.rs`'s spawn checks every requested tool against `run.profile.exposed_tools()` and refuses by
name. That is the *"parent's set narrowed, never widened"* half of M3-DESIGN §1, it predates this
ADR, and this ADR does not move it. What this ADR adds is that **the default is the empty set rather
than the parent's set**, so the narrowing check is the ceiling and not the floor.

A child that inherited its parent's tools by default would make privilege constant with depth, which
is the property `WidenedPastParent` exists to prevent, reintroduced one level up.

---

## §4. A SPAWN IS ADJUDICATED, AND IT WAS NOT

**This is the part that is a decision rather than a wiring, and it is the reason `run` could not
simply be switched on.**

`run`'s registration has always declared `exposed_tools`, `budget_*` and `orphan_policy` as
**Targets**, with the comment that untrusted content choosing a child's tool set *"is the trifecta
reassembling itself one level down"*. That declaration was enforced by nothing.
`ModelStep::Spawn` is matched in the loop and goes straight to `Engine::spawn`. It never reaches
`self.adjudicator.adjudicate`, which only `tool_batch` calls. `ModelStep::MemoryWrite` hands
`run.trust_floor()` to the memory host; `ModelStep::Spawn` handed the floor to nobody.

It was invisible because **the path was unreachable** — no model call could produce a
`ModelStep::Spawn`, so the only spawns in the workspace were hand-built in tests, at
`TrustClass::UserAsserted`, where the check would not have fired. This is the *"declared control that
nothing reads"* family (instance #16) with the reachability of instance #17 layered on top: the
control was inert **and** the path was dead, so neither half could be noticed from the other.

**Making `run` spawn is what makes it reachable, so the check ships in the same commit.**

### 4.1 The rule

> Under a latched floor that blocks composed targets, a spawn's **targets must be exactly the
> harness defaults**. Its payload — the task and the contract's description — may be anything.

Concretely, `Engine::spawn` refuses when `blocks_composed_targets(run.trust_floor())` and the request
carries a non-empty tool set, an explicit token grant, or an orphan policy other than `Terminate`.
The threshold is `marlowe_permission::blocks_composed_targets` — the single definition the
adjudicator enforces on and the loop's banner reads, per M2 C2f. There is no second constant.

**A tainted run may still spawn.** Refusing the spawn outright would be wrong: delegation is how a
tainted parent gets work done without acting itself, the child inherits the parent's floor
(`Run::child` copies `trust_floor`, so there is no laundering), and a child with no tools composes no
targets by construction. What is refused is untrusted content choosing *which* tools the child gets
and *how much* it may spend. That is ADR-023's split applied at the one call site that was missing
it: the payload flows, the target does not.

### 4.2 Why not route the spawn through `adjudicate`

Because `Request` is shaped around a tool call the tool host will execute — a manifest, a blast
radius, an egress policy, an approval. A spawn executes nothing and its blast radius is a run, not a
path. Reusing that machinery would need a manifest for a thing with no executor, which is the
`done`-to-the-tool-host defect in a new place. **What must be shared is the threshold, not the
plumbing**, and the threshold is one function.

---

## §5. Two fields the model may never name

`share` and `reads_untrusted` are absent from `run`'s parameter list, and their absence is
structural rather than an omission to be filled in later.

- **`reads_untrusted`** sets the quarantined-reader profile. Layer 1 decides when a read is
  quarantined — `Engine::condense_batch` keyed on the trust class, per ADR-039 — and a model asking
  for that profile is a model choosing a security posture. It happens that the posture is a
  *restriction*, so the immediate risk is nil; the reason it stays unreachable is that the next
  change to `CapabilityProfile::new`'s `reads_untrusted` arm should not have to ask whether a model
  can reach it.
- **`share`** is the slicing path M3-DESIGN §4 exists to displace: *"a budget is an explicit grant at
  spawn, deducted from the parent's pool."* Leaving it fixed at `Standard` means the model's only
  budget lever is the explicit grant, which `Budget::grant` refuses **with both numbers** when it
  exceeds what remains. A model given both levers would use the one that never refuses.

---

## §6. `budget_micros_usd` becomes `budget_tokens`

The registered parameter was `budget_micros_usd`, typed `Amount`. `SpawnRequest::grant_tokens` and
`Budget::grant`'s `explicit` are **tokens**. Wiring the declared parameter to the field it names
would have handed a micro-dollar count to a token grant — two sides silently disagreeing, with the
number correct and about the wrong quantity.

`Amount` is documented as *"money, in micros of the profile's currency"*, and a token count is not
money, so the type changes to `Integer` with it.

**What that costs, stated rather than left to be discovered.** `run.budget_micros_usd` was the
**only** builtin parameter typed `Amount`, and `Engine::coerce_to_declared_types` is one arm wide:
`Amount` declared, `Integer` supplied. So the function is now **a no-op on every shipped path**,
correct and unexercised, until a spend ceiling returns with the trust ledger at M6. It is recorded
here and in a comment at the function rather than deleted — the arm is right; its subject left.

Its two tests moved onto a **hand-built manifest** rather than being retargeted at `budget_tokens`.
Retargeting was the obvious edit and it would have been vacuous: `Integer` declared and `Integer`
supplied means the function does nothing, and the test would be green against
`fn coerce(_, args) { args }`. A third test was added for the live half — that the coercion is driven
by the *declared type*, so a version turning every non-negative integer into an `Amount` would render
a 12,000-token grant as `0.012000` on the line a human approves.

---

## §7. The consequence nobody could have seen until now: children were in no listing

Making `run` reachable made a second gap visible immediately, and it is recorded here because it is
a consequence of this decision rather than a separate defect.

**`Daemon::ask_streaming_with` was the only writer of the live run table.** It inserts one
`RunSummary` — the turn the daemon accepted. `Engine::spawn` creates a child, journals `RunSpawned`,
and knows nothing about a control plane, because the loop is a state machine over injected ports and
must not acquire a dependency on the daemon. So a spawned child existed **in the log and in no
listing**: `/runs` showed the parent alone, and the run window's roster panel is a hardcoded
`subagents: Vec::new()`.

A roster that is empty because the tree is empty and a roster that is empty because nothing fills it
read identically. The product was in the first state for the whole of M2, so nothing looked wrong.

`marlowe-daemon/src/roster.rs` closes it by **listening on the port the daemon already owns**: a
decorator over the journal recorder that folds `RunSpawned`, `Checkpointed` and `RunCompleted` into
the run table. The journal write happens first and is never conditional on the projection — the log
is the record, the table is a view over it.

**Two tests, because the property has two halves and one test cannot see both.** One drives a model
reply through `parse_step` into a real engine over a real signed journal and asserts on the frame
`/runs` renders; it would stay green if `ask_streaming_with` stopped installing the recorder. The
other reads the composition root for that installation — the `persona_emission.rs` lesson, where a
test on the source could not see that the running daemon served a binary from before the commit.

### 7.1 The defect the first live spawn produced, in the code this ADR added

`ControlPlane::detail` reads *"final when there is one, live otherwise"*: a row whose `elapsed_ms` is
`0` is reported as `now - started_ms`. `roster.rs` inserted the child's row and never closed it, so
the first real delegation listed **a completed child at 32,804 ms inside a parent that took
3,536 ms** — impossible for a blocking spawn, and reading longer every time anyone looked.

Zero was doing two jobs: *not finished yet* and *finished having taken almost none*. It could not
arise while `ask_streaming_with` owned every row, because a turn containing a model call never takes
zero. **Both halves are fixed** — `roster.rs` closes the row from the child's last terminal
checkpoint, and `detail` no longer times a stopped run live whatever its final number was — because
either alone leaves a stable answer, so *"it did not move"* cannot distinguish them. A mutation
proved exactly that, and the assertion is now on the child's own measured wall time.

Worth keeping for the reason CLAUDE.md budgets a real run per milestone: **eighteen tests written for
this feature saw none of it**, and one delegation did.

---

## §8. What this does not do

- **No `await` and no steer target.** `run` spawns and blocks, exactly as `Engine::spawn` always
  has. The model cannot name a run id, so it cannot address one. M3-DESIGN §5's meetings and §3's
  escalation are Session C.
- **No agent tree.** One level of `run` is the primitive; the five levels, the roles and the create
  grant are built on it, not by it.
- **No concurrency.** A spawn still runs to completion inside the parent's step.
