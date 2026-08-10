# ADR-032 — Egress is approved per host by a human, and that is only legitimate if the prompt shows the host

**Status:** PROPOSED — needs the human's approval (brief §13: the permission layer, and egress rules)
**Depends on:** ADR-031 (TLS)
**Revisits, as required:** ADR-002's `web` Inert exemption
**Touches §13-guarded files:** `marlowe-loop/src/profile.rs`, `marlowe-permission/src/adjudicate.rs`

## 1. Context

`CapabilityProfile::interactive()` declares `EgressPolicy::DenyAll`. A working `web` executor is
therefore blocked at the boundary regardless of ADR-031, and flipping that constant is brief §13
territory — the permission and approval layer, and path scoping and egress rules, are two of the six
do-not-touch entries.

The shape wanted is Claude Code's: **fetch, any host, with approval.** The constraint is that it
must not ship as a permanent allowlist, which would foreclose it.

## 2. The distinction this ADR rests on

**`DenyAll` and "an allowlist that happens to be empty" currently behave identically and must stop
being the same thing.**

- `DenyAll` is **structural**. It means *this run reaches no network, and no runtime event can
  change that*. The quarantined reader holds it. §5's narrowing rule and ADR-022's trifecta
  argument depend on it being unwidenable.
- An **extensible empty allowlist** means *this run reaches nothing yet, and a human may add a host
  to it*. Nothing is reachable by default. The set grows only by a human decision, one host at a
  time.

Brief §8's *allowlist by default* is satisfied by the second: **the default set is empty, not `*`.**
An approved host is an allowlist entry that a person wrote, at the moment they were shown what it
was for. That is a stronger position than a list authored months earlier by whoever guessed which
domains would be needed.

## 3. Decision

### 3.1 `EgressPolicy` gains `AllowApproved { granted: Vec<HostPattern> }`

`interactive()` moves from `DenyAll` to `AllowApproved { granted: vec![] }`.

- `grants()` returns true for a host already in `granted`, false otherwise.
- A host **not** in `granted` produces `Outcome::NeedsApproval`, not `Outcome::Blocked` — a
  distinct outcome from every other policy, and the only policy that produces it for an egress
  reason.
- On approval the host is added to `granted` **for that run**. It does not persist across runs and
  it is not written to a config file. Session-scoped grant is what stops the second fetch of the
  same host re-asking; anything longer-lived is a separate decision with a separate audit story.
- `DenyAll` and `Allow { hosts }` are unchanged, and neither can reach `NeedsApproval` by this
  route. A run that declared a list is held to its list.

### 3.2 The blast radius must name the host, and today it silently cannot

**This is the precondition, not a parallel improvement.**

ADR-002 permits `web` to be `Inert` — exempt from §9's target check — *only* because three
non-kernel mechanisms cover it, one of which is egress allowlisting. §3.1 weakens that mechanism:
the list is no longer fixed in advance. ADR-002 is explicit that when one of the three weakens, the
exemption is **revisited rather than inherited**.

**It is revisited here, and the answer is: per-call human approval replaces the allowlist as the
third mechanism — but only if the human can see what they are approving.** An approval prompt that
does not name the host is not a substitute for an allowlist. It is a button.

And today it would not name it in every case. `adjudicate::blast_radius` collects targets with:

```rust
.filter_map(|p| args.get(&p.name).and_then(ArgValue::as_text).map(|v| v.to_string()))
```

`ArgValue::as_text` returns `None` for `Integer`, `Amount` and `Boolean`. **A declared Target that
is not a `Text` is silently dropped from the scope line**, and the prompt renders as though that
argument were not there. The already-known instance is `run.budget_micros_usd`, typed `Amount`,
which means §B9's required blast radius has never shown a spend ceiling — the case where a human
approves something they would have refused.

**The fix is not "also render `Amount`".** The defect is the `filter_map`: a renderer that drops
what it cannot express fails silently, and the next non-`Text` Target reintroduces it. Every
declared Target present in the args appears in the scope line, rendered by variant, and a variant
with no rendering is a **compile error** via an exhaustive match rather than an omission.

### 3.3 A second parser defect, adjacent and worth fixing with it

`parse_step` never produces `ArgValue::Amount` — it maps JSON numbers to `Integer`
(`ollama.rs`). So `budget_micros_usd`'s declared `ParamType::Amount` is a type the runtime value
never takes, and any code branching on `Amount` is dead on the model path.

Argument values are coerced using the manifest's declared `ParamType` at parse time. This is the
lesser half — the renderer fix above is what closes the security-relevant gap, and it closes it for
`Integer` too, so the two are independent rather than one depending on the other.

## 4. What is deliberately not decided

- **Persisted grants.** A host approved today is not approved tomorrow. Persisting them needs the
  trust ledger (M6) and an answer to "what revokes this", which does not exist.
- **`AllowAnyHost` for any shipped profile.** Still unused. Still greppable.
- **Search.** Fetch only. See ADR-031 §4.
- **Whether `web` should stay `Inert`.** This ADR keeps it Inert with the third mechanism replaced
  rather than removed. If §3.2 is not implemented, that argument collapses and `web` must be
  reclassified `Reversible` so §9's target check fires on `url` — which is the fallback position,
  recorded so it is a decision rather than a discovery.

## 5. Consequences

- **The first refusal a user sees from `web` will be an approval prompt, not an error.** That is the
  intended behaviour and it is a visible change in what the interactive profile does.
- **There is no interactive approval surface in the daemon yet.** `DenyUnattended` returns false and
  `bash` already reads `declined` unconditionally for this reason. Until the approval gate is wired
  to the TUI, `web` in the daemon will decline every host — honestly, by name, with the remedy
  stated. **That is a known incomplete state and it must not be mistaken for the boundary
  working.**
- **ADR-023's latch becomes live.** `web` returning `UntrustedContent` is the first genuinely
  untrusted content this system has ever held. Every part of the taint path has been unit-tested
  and none of it has met a real page.
