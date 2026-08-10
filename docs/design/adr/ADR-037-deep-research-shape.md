# ADR-037 — Four additions to §10, and orchestrator-worker as a consequence of ADR-023 rather than a preference

**Status:** PROPOSED — **design only. Do not build. M3 owns this and durable runs are its precondition.**
**Amends:** brief §10 (four additions), ADR-008 (a third model role)
**Depends on:** ADR-023 (taint), ADR-036 (channels), ADR-035 (search)

## 1. Position

Brief §10 already specifies orchestrator-worker, effort scaling, explicit subagent contracts,
condensed structured returns and a separate citation-verification pass. The open-source consensus
confirms that shape rather than complicating it — GPT Researcher runs planner → concurrent executors
→ publisher, with recursive tree exploration at configurable breadth, depth and concurrency.

So this ADR is four additions and one reclassification, not a redesign.

## 2. Addition 1 — three model roles, and ADR-008 is missing one

LangChain's Open Deep Research (#6 on Deep Research Bench) splits the work across **three** models,
not two:

1. a **research** model, powering search and reading,
2. a **compression** model, which compresses findings from a worker's raw reading into what leaves
   the worker,
3. a **report** model, which writes the final artifact.

**ADR-008 has roles 1 and 3 and does not have role 2.** Its table is *"strong model for
orchestration and synthesis; fast cheap models for subagent search, extraction, classification,
consolidation, and turn detection."* Compression is folded into "extraction", which is not the same
job: extraction pulls fields out of a document, compression decides **what survives contact with the
orchestrator**.

That makes compression the highest-leverage cheap-model call in the system, because §10's
*"condensed structured returns"* is not a formatting rule — it is the mechanism that stops the
orchestrator's context accumulating worker transcripts. **The component enforcing that requirement
currently has no entry in the routing table.** Add it.

It is also the role most likely to be quietly given to the strong model "just for now", which is how
a 15× multiplier becomes a 25× one with nobody deciding.

## 3. Addition 2 — collaborative planning, which is effort scaling made visible

Gemini's defining research feature: before reading any source, it presents a plan and asks the user
to confirm or modify it.

§10 requires the scaling rule be *"explicit and inspectable"*. A plan the user approves before it
spends **is** that requirement, in the one form that cannot rot: an inspectable rule that nobody
inspects is a comment, and a plan that blocks on approval is inspected every time by construction.

It is also cheap. The approval surface, the blast radius and `ModelStep::Ask` already exist; the
plan is a decision package with a budget attached. And it converts the 15× token multiplier from a
surprise into a quote — §10.3 requires cost-normalized reporting, and a plan is where the estimate
belongs.

**Design note:** the plan is composed by the orchestrator *before* any channel is read, so it is
composed in a clean run. After §5, a plan proposed by a run that has already read pages could not be
acted upon anyway.

## 4. Addition 3 — hybrid sourcing is free here, and it is the differentiator

GPT Researcher's `report_source="hybrid"` combines web results with local documents. **Marlowe's
memory *is* the local corpus**, already retrieved by a measured stack (R@1 0.6725, published
precision/coverage curve, declared operating point).

A research run should draw on both **by construction rather than as a mode**: what the user has
said, decided and stored is frequently better evidence than anything a SERP returns, and it is the
one corpus no competitor has. This connects directly to M5.5's project knowledge.

**Two constraints that fall out of ADR-023 and are easy to get wrong:**

- Retrieved memory carries its own trust class, which is often `UserAsserted`. It **must not** be
  merged into the same bucket as fetched content, or the worst-case rule quietly drags the whole
  synthesis to `UntrustedContent` — or worse, a laundering path appears in the other direction.
- Memory retrieval happens in the **orchestrator**, which is clean, not in a tainted worker. The
  orchestrator can read memory and cannot read pages; the workers are the inverse. That falls
  straight out of §5 and it is a pleasing property rather than a constraint to work around.

## 5. Addition 4 — citation verification is required for us specifically, and the reason is our model

§10 already requires a separate verification pass. **This ADR reclassifies it from a quality
improvement to a required stage**, and records why the reason is particular to Marlowe rather than
general good practice.

The 2026 *"Cited but Not Verified"* benchmark found **open-source models show materially lower
fact-check accuracy than frontier models**. Marlowe runs a **9B locally** (ADR-028). So §10's
verification pass is not defence-in-depth against a rare failure — it is **the mitigation for a
measured weakness of the model this project chose**, and skipping it ships the weakness directly
into the artifact a human hands to another human.

Stated as an acceptance rather than a hope: §10.3's **citation accuracy ≥ 95%** is measured on the
shipped model, and a run whose verification pass did not execute does not produce a report. It
produces a refusal naming what is missing.

## 6. Part 5 — orchestrator-worker is a consequence of ADR-023, not a design preference

**This is the security model producing the architecture, and §10 should read that way.**

ADR-023: a run that has read untrusted content can never compose a Target again. Proved live this
session against a real fetched page:

```
view floor: AgentInferred   run floor: UntrustedContent   pages in view: 0
7 composed shell commands issued, 7 refused, 0 executed
```

**Every channel in ADR-036 returns `UntrustedContent`** — arXiv, Crossref and Wikipedia included,
because §2.8 binds trust to origin and the origin is outside. Therefore:

> **Every research worker is a tainted run by construction. The orchestrator that acts on their
> findings must be a separate run that never touched a page. The reader and the actor cannot be the
> same run.**

That is not a recommendation to be traded off against latency or simplicity. It is a property of
the permission layer, and any research design that puts reading and acting in one run **will not
run** — the harness refuses it, at the `adjudicate` call, without consulting the model.

Three consequences worth stating because each is otherwise a surprise at M3:

1. **A worker cannot write memory.** ADR-022's quarantined reader may not hold `MemoryWrite`. So
   findings are written by the orchestrator, from the condensed return — which is also the only
   place the trust class can be assigned honestly.
2. **A worker cannot write the report.** Producing an artifact is an action on a target.
3. **The condensed return is the entire security interface**, not merely a context-budget device.
   Everything the orchestrator will ever act on passes through it, so its schema is a boundary and
   belongs in CONTRACTS when it is built.

## 7. Scale calibration, recorded so the numbers are not a surprise

| System | Cost |
|---|---|
| Gemini Deep Research, moderate query | ~80 search queries, ~250k input tokens, ~60k output |
| Gemini Deep Research, max variant | ~160 queries, ~900k input tokens |
| Anthropic multi-agent research | ~90% better than a single agent at **~15×** the token cost |

> **INDICATIVE, NOT LOAD-BEARING.** These came from the human's research and **neither of us
> re-verified them**. They are here for order-of-magnitude calibration — *a research run costs
> hundreds of thousands of tokens, not thousands* — and **nothing in this design depends on their
> precision.** No threshold, no budget default and no acceptance criterion is derived from them.
>
> Stated this explicitly because the failure family this project tracks is a number that arrives
> with a citation instead of a command and then becomes load-bearing by being quoted. The way that
> happens is never a decision; it is a later session reading a table and treating it as measured.
> **A session that wants to budget against these must measure them on this system first.**

**Budget ceilings and depth caps exist to stop these arriving as a surprise**, and `Budget`'s six
dimensions already express them. The budget backstop has fired once in anger (M2 C2c) and worked;
a research run is where it will be load-bearing rather than incidental.

## 8. The honest limit

**No open-source system matches a vendor deep-research mode for out-of-the-box polish.** The
open-source case is **control, cost and data residency** — not a better report on day one.

What open source does *not* remove is engineering effort. Recorded here so that a future session
comparing Marlowe's first research output against Gemini's is comparing against the right baseline
and drawing the right conclusion from a worse report.
