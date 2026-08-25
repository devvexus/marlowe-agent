# ADR-054 — A steer is a write, it has exactly one door, and the door is where authority is checked

**Status:** ACCEPTED and BUILT. `crates/marlowe-loop/src/steer.rs`.
**Binding on:** `M3-DESIGN.md` §6.1 and §6.6; CONTRACTS.md §5 (`RunControl::steer`); ADR-023.
**Depends on:** layer 2 (trust propagation), layer 3 (the latched `(action, target)` split),
`marlowe_contract::text` (the display predicate).
**Corrects:** `M3-DESIGN.md`'s earlier draft, which justified building windows in parallel on the
grounds that a window *"reads the control plane and writes nothing."*

---

## 1. The correction, stated as the thing it actually is

A window has a steer field. **A steer field is a write.** The earlier justification was not merely
imprecise — it was the kind of sentence that gets a second write path into a control plane built
without anyone reviewing it as one, because the design document said there wasn't one.

The parallelism argument survives on its real basis: **a window depends on the run object, not on
the agent tree.** That is why it can be built beside step 1. It is not because it is read-only.

## 2. Why a steer is the most authority-bearing string in the system

Not obvious, so it is written out. `Engine::run`, at the iteration boundary:

```rust
if let Some(steer) = ports.control.take_steer() {
    provenance.attribute_user_message(&steer.text);
    state.push(Block::new(SourceKind::History, format!("[steer] {}", steer.text),
                          TrustClass::UserAsserted));
}
```

`attribute_user_message` inserts **the whole message and every whitespace-separated token** into the
provenance map at `UserAsserted`. And `Provenance::taint_for` reads that map **before** it reaches
for the floor:

```rust
ArgValue::Text(s) => self.attributed.get(s.as_str()).copied().unwrap_or(floor),
```

So an attributed token does **not** carry the run's latched floor. That is correct by design — ADR-023
blocks targets **composed by untrusted content**, and a target the human typed is not model-composed;
a floor that swallowed the user's own words would make a poisoned run unusable rather than safe. But
it means one thing precisely:

> **A steer is the only channel that writes new strings into `UserAsserted` in a run that is already
> latched at `UntrustedContent`.**

Whoever can send a steer can hand a latched run a target it would otherwise refuse. The question is
therefore not *how trusted is this text* — in a latched run everything else is at the bottom and the
floor has no discriminating power left. It is CLAUDE.md's saturation question: **who asserted it.**

## 3. The decision

**One door.** `marlowe_loop::steer::admit` is the only function in the workspace that constructs a
`SteerMessage`, and `steer.rs` is the only file outside tests where the literal `SteerMessage {`
appears. `tests/steer_has_one_door.rs` greps for that and fails by name, the same construction
`region_contract.rs` uses to keep `Block::bordered` inside `Region::block`.

The window's field and `/steer` are **not two paths that happen to agree**. They are the same call
with a different `SteerOrigin`, and the window has no way to reach a run except through it.

**Admission checks three things, in this order:**

1. **Authority — the channel, not the content.** `SteerOrigin::Human` is the only origin admitted at
   `UserAsserted`, and it is reachable only from an authenticated control-plane connection carrying a
   line a person typed. Every other origin is refused outright rather than admitted at a lower class,
   because a "steer that cannot assert anything" is a feature nobody asked for and a shape somebody
   would later widen.
2. **Shape — before it is attributed, not after.** The text is `sanitize_prose`'d and length-capped at
   `MAX_STEER_CHARS`. Both are load-bearing and neither is hygiene: the tokeniser inserts *every*
   whitespace-separated token at `UserAsserted`, so an uncapped steer is an uncapped budget of
   laundered targets, and an unsanitised one writes C1 and BiDi into a block that renders in two
   surfaces.
3. **Emptiness.** A steer that is only whitespace is refused rather than queued, so a stray Enter in
   a window does not push an empty `[steer]` block into a run's history.

**What admission does NOT do — and this is the part to check before believing the guard:**

* **It does not lift the run's latched floor, and it cannot.** `Run::latch_trust_floor` only ever
  lowers. A steer arriving in a latched run leaves every *model-composed* value exactly as blocked as
  it was; what it does is attribute the **specific strings the human typed**. That distinction is the
  whole of ADR-023 and `a_steer_does_not_restore_composed_targets_in_a_latched_run` asserts it by
  driving a blocked call through the loop after a steer, not by reading the floor.
* **It does not adjudicate a tool call.** `Adjudicator::adjudicate` takes a `Request` over a manifest
  and args; a steer is neither. Calling it here would be a decision record for something that is not
  a decision, and the reasons in the journal would be about a tool nobody named.

## 4. The alternative rejected

**Letting the window construct a `SteerMessage` and hand it to `RunControl::steer` directly.** It is
one line shorter and it is exactly the side door §6.1 names. The failure mode is not that somebody
writes a malicious window; it is that the second call site drifts — a cap added in one place, a
sanitiser in the other — and the two agree until the day they do not. This project has logged that
shape as *"two definitions of X"* enough times to stop paying for it.

**Rejected also: adjudicating a steer through the tool path** by synthesising a pseudo-tool. It would
make the wire look uniform and would put a `PermissionDecision` in the journal naming a tool that
does not exist, which is worse than no record — it is a record that reads as evidence.

## 5. Cost accepted

**`MAX_STEER_CHARS` truncates nothing; it refuses.** A long steer comes back as a refusal the user can
read and shorten, because a silently truncated instruction is an instruction the model receives half
of, and half an instruction is worse than none. The cap is generous enough that no ordinary correction
reaches it, and the refusal names the limit and the length.

**`/steer` from outside a window still works, and must.** §10.1 requires steering from another
terminal, with no TUI, from a script. If steering only worked in the window, closing one would remove
a capability — which is why the window is a second *caller* of one door and never a second door.
