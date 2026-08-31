# ADR-032 — Egress is approved per host by a human, and that is only legitimate if the prompt shows the host

**Status:** **ACCEPTED 2026-08-29 by the human**, nineteen days after most of §3.1 and §3.2 shipped
**§3.1's third bullet — the session grant — shipped LAST, on 2026-08-29, and this line used to claim
otherwise.** *"Nineteen days after §3.1 and §3.2 shipped"* was written on the day of acceptance and
was already wrong: `EgressPolicy::grant` had no production caller, so an approved host was re-asked
about on every fetch. That is the ADR's own §3.1 unimplemented, recorded here rather than in a
changelog, because a status line that overstates what shipped is the same defect this ADR's status
line was already carrying in the other direction.
**Accepted late, and the gap is recorded rather than tidied away:** the decision was implemented in
M2 C2f and the status line was never moved, so §13 machinery ran in the product under an ADR nobody
had accepted. That is instance #16's shape aimed at a status line — a declared control (`PROPOSED`)
that nothing reads, while the thing it gates ships anyway. **§5's *"there is no interactive approval
surface in the daemon yet"* was already stale when written into the record**: `SocketApprovals` is
wired at `daemon.rs:3182`, and the profile's own signed journal shows **37 `web` approval decisions
since 2026-08-10, all `needs_approval`, 29 granted and 8 denied, none silently allowed.**
**RE-CONFIRMED ON REVIEW 2026-08-31 BY MATTHEW, AND THE ACCEPTANCE DATE DOES NOT MOVE.** M3 Session
C's review of the seven M3 ADRs carried this one on a list describing it as *"the only ADR in the set
that is unaccepted and built"*. **That sentence is `CLAUDE.md`'s and `ROADMAP.md`'s, and it is stale
against this file** — the status line above has read ACCEPTED since 2026-08-29. So the date stays
**2026-08-29** rather than being carried forward to tidy a list: an acceptance backdated forward is a
status line overstating what happened, which is the defect this line already carries two corrections
for. What 2026-08-31 adds is that the human read it again and moved nothing. **ROADMAP's *Waiting on
the human* item 1 is closed by the 2026-08-29 acceptance**, and the documents still calling this ADR
`PROPOSED` are what needs correcting; both are outside the edit list of the session recording this.
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

  **WIRED 2026-08-29, and the scope word in that bullet is worth reading precisely.** The bullet
  says *"for that run"* and then calls it *"session-scoped"*, and in the shipped daemon **those are
  not the same thing**: `Daemon::ask_streaming_with` builds a fresh `Run::root` with a fresh
  `CapabilityProfile` on every user message, so a grant covers every fetch inside one turn and is
  gone by the next. What is implemented is the **run**-scoped reading, which is what the normative
  first sentence says. The looser word in the third sentence is left standing and flagged rather
  than quietly resolved, because widening it to the session is the same question
  [`SECURITY-AUDIT.md`](../SECURITY-AUDIT.md) §8 raises about ADR-023's trust-floor latch — *"the
  latch belongs on the session, not the Run"* — and both are the human's to decide, not a session's.

  The route is `CapabilityProfile::grant_egress_host`, the **only** mutable method on that type: no
  `egress_mut`, no `set_egress`, and it takes a parsed `Host` rather than a string. It delegates to
  `EgressPolicy::grant`, whose no-op on every other variant is what keeps the widening incapable of
  violating `CapabilityProfile::new`'s `reads_untrusted ⟹ DenyAll` invariant — the reason the
  granted set lives on the profile rather than beside it on the `Run`. The host travels from the
  adjudicator in `Reason::EgressHostNeedsApproval` so that the enforcement site and the recording
  site cannot disagree about which host a call was for, and the widening lands in the
  `ApprovalGranted` journal payload — recorded on what actually widened, not on what was asked for.
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

### 3.4 Approval is a REACHABILITY decision. It confers NO authority on what comes back.

**Added 2026-08-29 (M3-D3/D4), because the wrong version is plausible enough to pass review as
ergonomics.** It reads: *the human was shown this host and approved it, so what it returns is
`UserAsserted`* — or the softer form, *don't quarantine a page from a host a person vouched for*.
Both are the human's authority laundering the page's, and both are refused.

An approved host returns `UntrustedContent` exactly as an unapproved one would. Approving
`docs.example.com` says **you may reach that host**; it does not say *and you may believe it*, and
it does not make the approver the origin. CONTRACTS §3.3 binds a trust class to the authority of
the **origin**, and a person permitting a fetch has not become the origin any more than opening a
door makes them the author of who walks through it. The two questions are orthogonal and the
mechanisms answering them are separate on purpose:

| Question | Mechanism | Where it is decided |
|---|---|---|
| May this run reach that host? | `EgressPolicy` + the manifest's declared hosts | the adjudicator, before any executor runs |
| What authority does what came back have? | `TrustClass`, from the origin | the executor, stamping its result |

**It currently holds structurally, and that is not the same as being checked.**
`trust_for_channel` takes only a `Channel`, so grant state cannot enter it;
`marlowe-permission`'s egress module imports no `TrustClass`; and the site that stamps the class —
`read_ref`, since ADR-042 moved the page out of `web`'s own result — holds no `EgressPolicy` and
has no route to one. An invariant that holds because two things never meet reports the same
reading whether or not anyone has wired them together, so it is now asserted:

- `marlowe-exec/tests/egress_approval_confers_no_authority.rs` — the class itself, on an observed
  value, **with a grant actually in hand** (`line_numbers.rs` asserts the same class under
  `DenyAll`, where nothing exists to launder). It carries a three-way adjudication control
  proving the grant changed the answer, and a negative control on `web`'s own `AgentObserved`
  reference so a build that stamped `UntrustedContent` everywhere fails rather than passes.
- `marlowe-loop/tests/egress_grant.rs::approving_a_host_does_not_change_what_the_loop_does_with_what_it_returns`
  — the **fate** of the bytes, over two arms (reached by approval, reached by a held grant),
  asserting they agree on containment and the parent's floor. This is the only coverage of the
  softer wrong version, in which an approved host's result skips the quarantined reader.

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
