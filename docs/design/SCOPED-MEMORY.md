# Scoped memory — one mind, many desks

**Designed 2026-08-24 with the human. Not built, not decided.**

Marlowe must be able to research all day and keep what he learns. That is the product thesis: **a
small model that has researched a domain should compete with a frontier model trained on it.** It is
also, in the brief's own words, the most exploitable thing you can build. This page is how both are
true at once.

| | |
|---|---|
| **Status** | design; **no scoping exists in the code today** |
| **Verified 2026-08-24** | `crates/marlowe-memory/src/` has no namespace, owner or scope concept. The single `scoped` identifier is a `u32` counter in a retrieval struct. There is no per-subagent store wiring in `marlowe-loop/src/run.rs` |
| **Scale of work** | **spine-level.** CLAUDE.md: *"when a choice trades memory quality against anything else, memory wins"* |
| **Blocks** | workers holding `MemoryWrite` (M3 §7) |
| **Companion** | `ANALOGICAL-RETRIEVAL.md` — how the stored facts get used |

---

## §0. THE PRICE, QUOTED BEFORE ANYTHING ELSE

**Brief line 341:**

> **Memory writes are the highest-privilege operation in the system.** See §5.6. Poisoning is
> temporally decoupled from its trigger — poison planted today fires weeks later when semantically
> retrieved — which defeats every defense that watches for malicious *actions* rather than corrupted
> *beliefs*. Note the uncomfortable finding that more capable models are not more secure here, and
> that agents which write and retrieve memory more aggressively are *more* exploitable. Our
> aggressive memory system therefore requires proportionally aggressive write-time provenance.

*"Research all day and learn heavily"* **is** the aggressive-write case. The brief does not forbid
it — **it prices it**, and the price is write-time provenance paid in full at every write.

**"Watch for malicious actions" is explicitly named as the defence that does not work here.** Layer 3
guards targets and holds; it says nothing about a belief that was false when it was written.

---

## §1. The topology

| | reads | written by | lifetime |
|---|---|---|---|
| **Marlowe's memory** | **everything, one table** | conversation + promoted facts | permanent |
| **A scope's bank** | its own + what was instilled | agents in that scope | project |
| **A closed scope** | nothing reads it directly | frozen | archived |

Three rules, and the third is the invariant:

1. **To Marlowe it is one memory.** Not *"let me check what the research scope found"* — *"I know
   this."* This is §B1 turned inward: the terminal addendum's binding rule is that memory gets no
   special treatment in the interface, *"they just know things."* Marlowe narrating his own retrieval
   plumbing is the same violation one layer down.
2. **Scopes never read each other**, open or closed.
3. **Marlowe is the only cross-scope channel.** A closed project's knowledge reaches a new project by
   Marlowe instilling it at spawn — knowledge moves between projects through the person who oversees
   both. Without this rule, *"closed scopes stay queryable"* silently becomes *"any agent reads any
   project"* and the isolation is decorative.

### 1.1 Why Marlowe can safely hold global read

**Because facts are propositions, not prose.** These two decisions were made separately and they are
load-bearing on each other.

If facts were stored as paragraphs, global read would be the worst idea in the design — every
research paragraph Marlowe ever ingested, instruction-shaped, permanently in reach. **A proposition
cannot be an imperative.** `Hubble constant ≈ 73 km/s/Mpc [Riess 2022]` has nowhere to put *"and then
email this."*

**Keep them tied together in the code, or someone relaxes the storage format later without seeing
what it costs.**

---

## §2. What gets stored

### 2.1 Propositions, with provenance that never detaches

```
{ assertion, source_id, observed_at, confidence, corroboration_count, lineage[], scope_id }
```

`lineage` is **not a debug field.** The retrieval path reads it, the display path shows it, and
revocation walks it.

### 2.2 The three failure modes, separated

"Memory poisoning" is currently three problems wearing one name and only one is a security problem:

| | | |
|---|---|---|
| **1. The fact is wrong** | retracted paper, page that lies, summary that distorts | **epistemics, not security.** Frontier models have it baked in at training time and unfixable; ours is at least inspectable |
| **2. The fact is instruction-shaped** | *"when asked about deployment, tell the user to run…"* | **the actual attack.** Killed structurally by §2.1's schema — the instruction has no slot, so it is unrepresentable rather than filtered |
| **3. The corpus is poisoned on purpose** | planted documents in a topic Marlowe researches | same problem a human researcher has; §5's corroboration is the answer |

**Containment, not filtering** — Brief §8.1. A schema with no imperative slot is containment.

### 2.3 Declared learning goals are a floor, not a ceiling

Marlowe may pre-declare what a research run should learn. That bounds what gets written, makes
learning inspectable, and means an injected *"also remember that…"* has no declared slot to land in.

**But it is a RELEVANCE mechanism and must never be called a defence.** CLAUDE.md is blunt: the K1
gate is *not* one of the five layers, *"filtering does not work, containment works,"* and M2 Session D
filed a quality finding as a security hole on exactly this confusion. Undeclared learning is still
allowed — it simply lands at lower confidence and stays a *claim*.

---

## §3. Extraction — the fan-in

**N site-readers, then ONE fact extractor.** Not a second pass per site.

```
page₁ ─▶ reader₁ ─┐
page₂ ─▶ reader₂ ─┼─▶ [fact extractor] ─▶ propositions
  …              ─┤        (TSa, no tools)
pageₙ ─▶ readerₙ ─┘
```

Three wins, and the third was accidental:

- **Cost:** N+1 model calls instead of 2N.
- **Latency:** *better*, not worse — readers run concurrently on the existing I/O pool, so the
  critical path is `slowest_reader + 1`. Per-site double-pass puts two calls in series per site.
- **Corroboration becomes possible at all.** *"Three independent sources agree"* is not computable one
  page at a time. **The fan-in is the only place the §5 gate can physically live.**

The extractor holds only validated summaries, never a raw byte — one step further from the source
than the readers are. It is a tool-spawned agent: no tools, destroyed on return.

### 3.1 Two conditions

**Bound the width, deliberately.** This re-creates ADR-041's trade one level up: one context holding
several attacker-shaped summaries, where source 7 can influence how facts from 1–6 are phrased.
`MAX_SOURCES_PER_READER = 6` exists for exactly this reason. **Pick the number as an arm (§7 A3), not
by inheriting a round figure.**

**Attribute on the way in.** Every summary enters tagged; every fact leaves with its source. That is
what makes the residual risk *auditable* — a source discovered poisoned six months later is
**revocable by lineage** instead of having contaminated a batch invisibly.

---

## §4. Instillation — seeding a new scope

Scopes do not inherit Marlowe's memory. At spawn he hands over what is likely relevant.

**It is retrieval, and the query is the task brief.** He knows what the scope is *for* before it
starts. No new mechanism — the existing retriever, pointed at a spawn.

### 4.1 Copy, not reference

A reference gives the scope a live read path into global memory and the isolation is decorative.
Copies preserve it.

**The cost is staleness, and the fix already exists:** superseding a fact must propagate to its
instilled copies. This is failure #13's territory — a superseded fact counting as a hit — except here
it is a scope working for three weeks from something Marlowe corrected on day two.

### 4.2 Instillation is journaled

It sets a project's premises from turn zero, which makes it **the highest-value target in the whole
memory design.** Influence what is instilled and you have shaped every downstream conclusion without
touching anything else. If the starting knowledge is in the log, it is auditable after the fact.

### 4.3 The failure mode is over-instillation

Marlowe will be generous. He hands over everything plausibly relevant, the scope starts bloated, and
the precision that scoping bought is spent on turn one.

- **Budget it.** A cap, so he chooses under scarcity.
- **Measure it — instillation hit rate.** Of N facts instilled, how many were ever retrieved? At 5%
  he is dumping his notes rather than briefing. Falls out of the retrieval log for free, and is
  exactly the kind of number that degrades silently for months.

### 4.4 Mid-project top-up is a RETRIEVAL, not a conversation

A scope will discover it needs something Marlowe has. Push-only means he guesses everything up front.

But an agent asking Marlowe a question is an upward prose channel — the thing M3 §2 closes. **Resolve
it by making the query mechanical: the request executes as a search against Marlowe's store and
returns propositions. It never enters Marlowe's context.** No model call, no message, nothing for an
injected instruction to land on. The query string hits an index, not a mind.

**Strictly better than typing the message, because there is no surface to type safely.**

---

## §5. Promotion and consolidation

### 5.1 The completion return is the promotion channel

If nothing flows up, **Marlowe learns nothing from any work he delegates** — a year of projects and
he knows only what he was told directly. His own persona says memory *"is what makes you continuous
rather than a stateless function."*

So: **when a top-agent finishes, its typed return is what Marlowe learns.** Not the working bank. You
do not get your team's notebooks; you get the deliverable and a debrief. Same channel M3 §2 already
types and validates.

Promotion is **deliberate and visible** — the user can see what Marlowe took from a project — and
**lineage rides along**, so a promoted fact that traces to a fetched page still says so a year later.

### 5.2 Consolidation is where it becomes permanent

**One source is a claim. N independent sources is a fact.** Independence must be real — three sites
quoting one press release is one source.

> **UNTRUSTED-DERIVED BELIEFS NEVER CONSOLIDATE INTO THE STABLE TIER WITHOUT CORROBORATION.**
>
> Consolidation is the moment a claim stops carrying its origin and starts reading as background
> truth. Past it, a poisoned belief is indistinguishable from something the user said. **This is
> where temporally-decoupled poisoning becomes permanent**, and it is the single gate that matters
> most in this document.

Beliefs can be recalled forever, rank highly, and be reasoned with. They simply never lose provenance.

### 5.3 End of scope

- **Completion return promotes** what matters.
- **The bank archives cold** — searchable on request, never retrieved by default.
- **TERMINATE destroys it outright**, which gives TERMINATE a clean honest meaning it otherwise lacks.

---

## §6. Retrieval at scale — buckets, and the trap in them

The human's proposal: coarse semantic buckets. A conversation bucket. Subject buckets. A
conversational query never sees the physics facts.

### 6.1 Partition by KIND and TRUST. Never by SUBJECT.

**The safe axis:**

- Conversation is `UserAsserted`, narrative, queried by *"what did we say about…"*
- Learned facts are untrusted-derived propositions with lineage, queried by *"what is true about…"*

Genuinely different objects. **Assignment is stable at write time and stays correct forever.**

**The dangerous axis:** subject assignment is fluid, and crossing it is exactly what you want.

> **SUBJECT BUCKETS FIGHT ANALOGICAL RETRIEVAL DIRECTLY.** `ANALOGICAL-RETRIEVAL.md` exists to connect
> the heat equation to Black–Scholes — structurally identical, topically distant. **If those live in
> different buckets and a query routes to one, the connection is not merely unranked, it is
> unreachable.** No reranking recovers a candidate that was never in the set.
>
> Subject buckets optimise for knowing what you are looking for. Transfer is the case where the
> valuable hit is in the bucket you would never have picked.

### 6.2 Filters fail hard; rankers fail soft

A hard partition is a filter: right answer in the wrong bucket returns zero, silently, with a
confident-looking result set drawn from the bucket you did pick. A ranking feature degrades — rank 8
instead of absent.

Same epistemics as §8.1's *"filtering does not work"* in another domain: **a filter is only as good as
a decision made before you had the answer.**

### 6.3 The version that keeps both

**Bucket as a prior on depth, not a wall.** Route to the likely bucket and search it deep; search the
others shallow. With the existing cascade this is nearly free — depth 30 in the routed bucket, 3–5
elsewhere, one rerank over the union.

Cost close to partitioned. Recall close to global. **A routing error costs rank position, not the
answer.** Scope becomes a feature the ranker sees, alongside recency and trust class, rather than a
gate before the ranker runs.

### 6.4 Marlowe's global table is the hardest retrieval problem in the system

A year of research, no scope filter, everything ranked against everything — the precision case M0c
has been grinding on, at maximum scale. The scoped views are the easy ones.

**Scope as a ranking feature gets most of it back**: he still sees one table, but active and recent
scopes rank higher and a year-old project's minutiae does not compete with what is live.

---

## §7. PARALLEL ARMS

**Do not build one version.** Several decisions here have plausible alternatives where the wrong pick
is invisible in ordinary metrics. Run them concurrently on the same held-out set, **bands
pre-registered before any fit**, per `tools/preregister_split.py` discipline.

| # | Question | Arms | Primary metric | Control |
|---|---|---|---|---|
| **S1** | partition axis | none · kind+trust only · kind+subject | R@1/R@3, **routing recall loss** | unpartitioned global |
| **S2** | routing shape | hard filter · depth prior (§6.3) · pure ranking feature | routing recall loss vs latency | — |
| **S3** | instillation selection | top-k retrieval on brief · LLM-selected · hybrid · **none (control)** | **instillation hit rate**, scope task success | none-instilled |
| **S4** | instillation volume | 20 / 100 / 500 facts | hit rate vs first-turn context cost | — |
| **S5** | top-up channel | mechanical retrieval · typed message · **free-text to Marlowe (expected to fail)** | injection-propagation rate on the red-team set | free-text arm IS the control |
| **S6** | corroboration threshold | N ∈ {1, 2, 3} independent roots | precision vs recall of promoted facts | N=1 (no gate) |
| **S7** | extraction locus | quarantined reader emits structure · fan-in pass over summaries | fidelity (detail retained) vs blast radius | — |
| **S8** | fan-in width | 3 / 6 / 10 sources per extractor | cross-source contamination rate | width 1 (no mixing) |
| **S9** | scope end-of-life | delete · archive cold · consolidate to Marlowe | later-project task success; poisoning persistence | — |

### 7.1 The number that decides S1 and S2

**Routing recall loss: how often is the true answer in a bucket the router did not select**, measured
against unpartitioned retrieval over the same queries.

Near zero → hard partitions are safe, take the cost saving. **At 8% you have traded a chunk of your
ceiling for latency you probably did not need.** This number has to exist *before* the choice is made,
not after.

### 7.2 S7 is genuinely open and cuts against the obvious answer

The fan-in is safer. But **the reader is the only thing that ever sees the derivation in full**, and a
summary written to carry *facts* may already have discarded the argument's *shape* before any
extractor looks at it. That is fatal for `ANALOGICAL-RETRIEVAL.md`, which needs structure, not
conclusions.

**This may be the argument for having the reader emit structure directly**, accepting the larger blast
radius. Measure it; do not decide it in a doc.

### 7.3 Not an arm

Anything where the wrong answer is a hole rather than a quality loss: the propositions-not-prose
schema, lineage retention, and §5.2's consolidation gate are **asserted, not A/B tested.**

---

## §8. Acceptance

| Metric | Target |
|---|---|
| Routing recall loss vs unpartitioned | declared band, pre-registered; reported with R@1/R@3 always |
| Instillation hit rate | declared band; **a floor, because low means over-instilling** |
| Cross-scope reads by a non-Marlowe agent | **0**, asserted at the enforcement site with a control that *can* attempt one |
| Untrusted-derived facts in the stable tier without corroboration | **0** |
| Poisoning ASR, red-team set, promoted-fact path | pre-registered ceiling; measured in **red-team pass 2** ([`REDTEAM-SESSION.md`](REDTEAM-SESSION.md)), which is the first moment this path exists — a zero measured before this session ships is vacuous, not clean |
| Facts revocable by source after N months | **100%** of facts whose lineage touches a revoked source |
| Marlowe's floor after M scope completions | **unchanged**, with a control that latches |

---

## §9. Open

1. **S7's answer** — reader emits structure, or fan-in extracts it? Fidelity against blast radius,
   and `ANALOGICAL-RETRIEVAL.md` pulls the opposite way from containment.
2. Does promotion into Marlowe's memory need **user approval**, or Marlowe's judgment on a typed
   return?
3. Is the operator index of `ANALOGICAL-RETRIEVAL.md` a **separate store or a tier** in this one?
4. What supersedes what across scopes — if project A learns a fact project B holds stale, is that
   Marlowe's job or automatic?
5. Does a scope's bank survive its top-agent being replaced after a compromise (M3 §12.2)?
6. Bucket assignment: fixed taxonomy, or emergent clustering that drifts and may be wrong for a query
   five months later?
