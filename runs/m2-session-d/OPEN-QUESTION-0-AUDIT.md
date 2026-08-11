# Open question 0 — the four places, examined

M2 Session D, 2026-08-11. STATE.md's open question 0 names four places where untrusted content
could shape a decision through a path with **no tool, no argument and no permission check**, and
records that *"none of the four has been confirmed exploitable and none has been confirmed safe."*

All four are examined here. **Two are confirmed holes, one is safe, one does not exist yet.**

Per the human's instruction: this is a **finding, not a fix**. Nothing in `provenance.rs`, `trust.rs`
or the gate's feature set has been changed. Both holes need a §13 decision.

---

## 1. Ranking inputs — **CONFIRMED HOLE**

> *"query text and candidate text both reach the cross-encoder. A page that shapes a query shapes
> what is retrieved and what is injected."*

**Trust is computed, propagated, signed, stored — and then read by nothing that ranks.**

`effective_trust` is one of the gate's eleven `FEATURE_NAMES`. It is also declared **inert** in the
shipped artifact, and the artifact states the reason in its own words:

> `"effective_trust": "zero variance across the fit split (constant 1.0000); a calibration fit on it
> would be noise, **and would become load-bearing the moment the feature starts varying**"`

Under gate v5 only `lexical_margin` and `dense_margin` carry curves, and `calibrated_precision` is
`max` over those two. `effective_trust` contributes **nothing** — not a small weight, not a
mis-fitted weight: it is absent from the computation.

### Session D is the change the artifact warned about

That declaration was honest when it was written. Every belief reached the store through `ingest`,
and on LongMemEval every turn arrives `Channel::Terminal` → `UserAsserted`. The feature was constant
because the population was uniform.

**ADR-038 makes it vary for the first time.** A claim now writes at `min(AgentInferred, run_floor)`,
so a run that read a page writes at `UntrustedContent` — measured live this session:

```
claim-0   agent_inferred      'my favourite colour is green'
claim-2   untrusted_content   'example.com is a reserved test/example domain...'
```

The feature is varying. The curve fitted on a constant is still what ships. **So an untrusted memory
and a user-asserted memory with equally good text rank identically, and the operating point admits
whichever has the larger rerank margin.** ADR-038 labels correctly; nothing downstream reads the
label.

`recall` — written this session — has the same property and it is worse there: it ranks on lexical
score alone, with no trust term at all.

### The second half, which is about the cut point rather than the gate

The declared operating point thresholds the **rank-1/rank-2 cross-encoder margin**. A large margin
means *this candidate lexically and semantically dominates its rivals* — the one property an
attacker who writes memory text can optimise directly. Precision 0.9130 was measured against natural
LongMemEval distractors. **Conditioning on high margin filters noise and does not filter, and may
preferentially admit, crafted text.** The gate is a relevance filter; nothing in the injection path
is an authenticity filter.

### What this is not

It is **not** a trust-escalation. The stored class is correct, `min` propagation is correct, and the
run's floor still drops when an untrusted memory is injected — so composed targets are still blocked
(verified live: 7 composed shell commands issued, 7 refused). The hole is that trust does not
influence **what gets chosen**, only what the run may do afterwards.

### Owner

`gate/features.rs`'s feature set and the frozen artifact — **§13, the human's call.** The cheap
options are ordering by `effective_trust` before margin, or refusing to admit below a declared class.
Both change the scored path and both need a pre-registration, because either would move R@1 and the
number must not be discovered after the fact.

---

## 2. Cache keys — **SAFE, and my earlier claim was wrong**

> *"a key derived from attacker-influenced text lets one request's result be served for another.
> Why nobody has looked: there is no cache yet."*

**There is a cache**, and I repeated "there is no cache yet" from STATE without checking. There are
two, and both answer the authority question well:

| cache | key | verdict |
|---|---|---|
| `PrefixCache` (`context.rs:434`) | `(SessionId, epoch)` | **safe** — both harness-assigned |
| `--embedding-cache` | model digest + vocab digest + embedder version + sequence length, content-addressed | **safe** — a pure function of its input |

`SessionId` comes from the client's connection name via `SessionId::from_name`, and `epoch` is a
harness counter bumped on compaction. **Neither is reachable by untrusted content**: the model does
not choose the session, and a fetched page cannot influence either value. The embedding cache is
content-addressed over a deterministic function, where equal keys *must* give equal values.

**The tell that this is a real answer rather than an absence of one:** ask what an attacker would
have to control to poison either. For `PrefixCache` they would have to name the session, which is
the connecting client's privilege, not the content's.

---

## 3. Memory derivation lineage — **DOES NOT EXIST YET**

> *"`derived_from` is already a declared Target on `remember`, but the harness-side resolution of
> lineage during consolidation is not the same path."*

The **tool argument** is guarded: `derived_from` is `ArgumentRole::Target` on the `remember`
manifest, so ADR-023's `(action, target)` check applies, and `claim.rs` additionally **rejects an
unknown parent** rather than silently dropping it — dropping would raise the derived belief's
effective trust to whatever the claim asked for.

The **harness-side** path named in the question does not exist. Consolidation emits
`BeliefsMerged` and `Superseded`; it never writes a `derivation` array. No code path derives lineage
other than the guarded tool argument.

**This is a "not yet", not a "safe".** The moment consolidation or any future component computes
lineage on its own, it inherits question 1's shape, and the guard on the tool argument will say
nothing about it.

---

## 4. Consolidation merge decisions — **CONFIRMED HOLE**

> *"whether two memories are the same fact is the identity question of ADR-036 §4, inside the memory
> system, on content that may be untrusted."*

`plan()` clusters by **cosine similarity of text against a frozen threshold**. There is **no trust
term in the merge decision**. The representative is the **latest** member (`consolidate.rs:559`,
asserted by `the_survivor_is_the_latest_not_the_earliest`), and every other member is written
`Superseded`, which §4.3 exclusion (2) then removes from the injection candidate set.

### The attack, concretely

1. A run reads a page. The model calls `remember` with attacker-shaped text — permitted; the
   quarantined-reader guard covers `reads_untrusted && may_write_memory`, and an ordinary
   `interactive()` run is neither quarantined nor forbidden from writing.
2. The claim is written at `UntrustedContent` — correctly, by ADR-038.
3. Its text is cosine-similar to a genuine `UserAsserted` belief, and it is **newer**.
4. Consolidation elects the attacker's memory as representative. **The user's own asserted fact is
   superseded and leaves the injection candidate set.**

**This is eviction, not escalation.** The survivor keeps its own `UntrustedContent` class, so nothing
is laundered upward. What is lost is the genuine belief — untrusted content causing a trusted
memory to be forgotten.

**The recency rule is the lever, and it is load-bearing for a good reason.** *"LongMemEval's
knowledge-update category makes the LATEST statement gold; electing the earliest would suppress gold
across the whole category."* An attacker controls recency for free: they write later. So the rule
that makes knowledge-update work is the rule that makes this work.

### Reachability, stated precisely

**Not reachable in the product today.** Consolidation is not wired into the daemon — nothing calls
`consolidate::apply` outside the eval adapter, and `consolidation()` cannot spawn because the spawn
contract is unresolved (M3). It **is** reachable on the eval path, and it becomes reachable in the
product the moment consolidation is wired.

### Owner

The merge predicate. **§13-adjacent and the human's call**, because any trust term in clustering
changes what the frozen threshold means and the threshold is a registered artifact.

---

## What this exercise confirms about the framing

ADR-036 §5's generalization holds in all four places, and the taint floor helps in **none** of them —
exactly as the CLAUDE.md ledger entry predicts. In every case the population is uniform or the
mechanism is absent:

- ranking: every candidate is a memory; the floor does not order them
- merging: similarity is computed on text, where a class is not an input
- caching: the key never touches content

**The question that discriminates is not "how trusted is this value" but "who chose it".** In 1 and 4
the answer is *possibly a web page*, and nothing asks.

**One correction to the standing framing:** open question 0 says none of the four has been confirmed
either way. After this audit, **two are confirmed holes, one is confirmed safe, and one does not
exist yet** — and the safe one was previously described (by me, and by STATE) as "there is no cache
yet", which was simply not true.
