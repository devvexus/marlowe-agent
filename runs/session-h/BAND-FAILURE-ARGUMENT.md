# Session H — the sessionizer guard failed, and the argument for proceeding

**Written immediately after the measurement and before the reranker was built**, so that
`RESULT.md` and the ADR quote it rather than reconstruct it later from memory. The registered
question's own file sanctions exactly one way past a bar — *"if the bar looks wrong when the result
arrives, argue it explicitly and record the argument — do not move it"* — and this file is that
argument. The band in `PREREGISTRATION.json` is **not edited**. It failed, and it stays failed.

## What failed

`runs/session-h/PREREGISTRATION.json → sessionizer_band.guard_read`

| read | derived | true | band | verdict |
|---|---|---|---|---|
| **primary** — gold retention @ N=3 | 0.9825 | 0.9825 | \|Δ\| ≤ 0.02 | **PASS**, Δ = +0.0000 |
| **guard** — surviving pool fraction @ N=3 | 0.1550 | 0.1003 | ≤ 1.5× | **FAIL**, 1.546× |

## The claim being made, stated exactly

> **The guard is a proxy for gold damage. The quantity it proxies for was measured directly, and it
> is exactly zero. The guard fired on a failure mode that was independently measured not to exist.**

That is the reason, and it is the whole reason.

**This is not "proceeded past a failed band because the miss was small."** The miss being 0.046×
is not load-bearing and is not part of the argument. A future session must not inherit the claim
that a near-miss on a registered band is grounds for proceeding, because that is not what happened
here and it is not a rule this project holds.

### Why the guard is a proxy

The registration states the guard's purpose in its own words:

> *"Gold retention alone is gameable by a degenerate sessionizer: merge every turn into one session
> and retention is 1.0 with no pruning at all. The guard is what makes the primary read meaningful."*

The concern is **gold damage disguised as retention** — a partition that keeps gold only by failing
to prune. Pool inflation is the observable that normally travels with that failure, which is why it
was registered as the guard.

### Why the proxy was superseded here

Inflation and gold loss travel together when a sessionizer **splits**. Splitting is the mechanism by
which pruning discards the fragment holding gold, and it is the only way this partition can lose the
answer. All three direct reads of that mechanism are clean:

- **gold retention Δ = +0.0000** — identical to the true partition, not merely within band
- **completeness = 1.0000** — every true session lies inside a single derived session
- **true sessions split across derived sessions = 0**
- **cases where a gold session is split = 0**

The sessionizer **merges and never splits** — 39.02 derived sessions per case against 47.65 true,
homogeneity 0.8705. Merging is the benign direction: the surviving pool is larger than intended and
every gold turn that the true partition would have kept is still in it. The pruning is 6.5× rather
than 10×, and that is the entire consequence.

So the guard did not detect the thing it was registered to detect. It detected merging, and merging
was measured — directly, by the primary read and by three independent diagnostics — not to cause the
harm the guard exists to prevent.

**The counterfactual, stated so the argument cannot be reused where it does not apply:** if gold
retention had moved at all, nothing below would rescue it and the session would have stopped. The
primary read is what carries the decision. The guard was subordinate to it and was not registered
that way, which is the defect recorded below.

## Secondary support, and it is secondary

The inflation makes the registered question **harder to pass, not easier**:

- **Q1** reranks every candidate in the pruned pool, so it faces ~75 distractors instead of ~50.
- **Q2** draws a fixed budget of 10, so its cost is unchanged and its slate is drawn from a
  *larger*, more diluted pool.

If in-session reranking clears its registered bars on a 15.5% pool, it would clear them at least as
well on a 10.0% one. This is a direction-of-bias argument. **It is support, not the reason.** It
would not by itself justify proceeding, because a conservative bias on the outcome says nothing
about whether the pool being reranked still contains the answer — which is what the primary read
says, and which is why the primary read is the reason.

## The registration defect this exposes — an ADR-013 corollary

ADR-013's binding lesson is *check that the READ can vary, not only that the SHAPE can move the
metric*. This session adds a corollary about how reads relate to one another:

> **A guard whose primary read directly measures the guard's own concern is redundant, and must be
> registered as SUBORDINATE to that read rather than as an independent stop condition.**

The guard was registered as an independent stop: either band failing halts the session. But its
stated concern — gold damage hidden behind a retention number — is precisely what the primary read
measures, and measures better, because it reads the harm instead of a correlate of the harm. Two
stop conditions were registered where the second is a weaker view of the first.

The correct registration would have been:

> *The guard fires only when the primary read is ambiguous — that is, when gold retention is high
> AND the pool fraction is inflated enough that retention could be an artifact of not pruning.
> A gold retention delta of exactly 0.0000 against the true partition is not ambiguous.*

This generalizes past this session and past sessionizers. It belongs in the ADR, not in this file
alone.

## Carried forward as findings, not fixed here

**1. §4.6 carries no session structure, and that is the real defect.** The harness flattens a case's
~48 haystack sessions into one `SessionHistory` whose `session_id` is the question id, so the real
session boundary survives only inside the harness's private `turn_id` encoding. Every derived
sessionizer, including this one, is an approximation of something the contract could simply carry.
Supermemory's session-level ingest granularity — the external work that motivated arm 1 in the first
place — treats the session as a first-class ingest unit. **That is an M0a contract change with its
own registration and it is not this session's scope.** Recorded so it is argued on its merits rather
than absorbed as a workaround that quietly becomes permanent.

**2. The binary drops `occurred_at_ms`.** `crates/marlowe-memory/src/ingest.rs:99` sets
`created_at` from the ingest clock and discards the turn's `occurred_at_ms`, which §4.6 does carry on
the wire. Because the harness ingests a whole case in **one** §4.6 call, `created_at` is identical
for every turn in that call and carries no ordering at all.

**Does this block Phase 2 shipping? Yes — and it is in scope to unblock.** A contiguity sessionizer
in the binary needs a per-turn timestamp that survives into the belief store, so
`occurred_at_ms` must be added to `MemoryWrittenPayload` and `MemoryEntry` before pruning can ship.
That is an **internal** schema — `store.rs`, not a pinned `CONTRACTS.md` type — and the change is
additive, carrying a field the wire already provides and the implementation currently throws away.
`DERIVATION_VERSION` is bumped with it, so an existing journal fails to open with a version mismatch
rather than a deserialization error. It does **not** touch maturation, which deliberately uses the
ingest clock so a backdated turn cannot arrive pre-matured; that reasoning is unchanged and the new
field is never read by the maturation path.
