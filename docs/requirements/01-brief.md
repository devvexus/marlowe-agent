# Marlowe: Requirements for a Memory-First Agent Harness

**Status:** Requirements specification, ready for design.
**Audience:** The AI system tasked with designing and architecting Marlowe.
**Version:** 1.0 — August 2026

---

## 0. Your Job (Output Contract)

You are being asked to design an agent harness. Not a model, not a wrapper, not a demo. A harness: the operating system that surrounds a language model and turns it into a system that remembers, acts, persists, and improves.

**Do not produce a feature list.** A feature list is what every one of our competitors already published. Produce an architecture with defended tradeoffs.

Your output must contain, at minimum:

1. **A named core abstraction** — the one idea the whole system reduces to. If you cannot state it in one sentence, you have not found it yet.
2. **A component architecture** with explicit boundaries: what each subsystem owns, what it must never touch, and what crosses each boundary.
3. **Data models** for memory, sessions, skills, runs, and permissions. Actual schemas, not prose.
4. **The agent loop**, in pseudocode, including every interrupt, checkpoint, and failure path.
5. **Defended tradeoffs.** For each of the "Hard Problems" in §14, state your choice, the alternative you rejected, and the cost you accepted.
6. **A build sequence** — what ships in v0.1 that is already useful, and what each subsequent milestone unlocks. A harness that only works when complete is a harness that never works.
7. **The kill criteria** — what measurement, if it came back bad, would tell us this design is wrong.

Where this brief specifies a number, treat it as a contract. Where it specifies a behavior, treat it as a constraint. Where it asks a question, answer it and defend the answer.

---

## 1. The Thesis

Agents do not fail because models are weak. They fail because harnesses are weak. The model provides raw reasoning; the harness provides continuity, judgment about what enters the context window, the ability to act safely, and the ability to survive a restart.

The 2026 harness ecosystem has converged on a nine-part reference model (Arize's framing, derived from analyzing production harnesses):

1. Outer iteration loop
2. Context management and compression
3. Skills and tools management
4. Subagent management
5. Built-in prepackaged skills
6. Session persistence and recovery
7. System prompt assembly with project context injection
8. Lifecycle hooks
9. Permission and safety layer

**Implementing all nine is table stakes, not differentiation.** Hermes Agent already does. Assume your competitors have all nine and design for what comes after.

The differentiation thesis for this project:

> **Every existing harness treats memory as storage. Memory is not storage. Memory is a compression policy over experience, with a retrieval policy that must be right the first time, and a trust policy that says which of its own beliefs it is allowed to act on.**

Everything else in this brief follows from taking that seriously.

### Marlowe

The system is called **Marlowe**. Two things are fixed before you begin.

**1. Memory is the spine, not a subsystem.**

§5 is not the longest requirement because it has the most features. It is the longest because it is the thing every other requirement resolves to. Read the rest of this brief as consequences of the memory design:

- **Context engineering** (§6) is memory deciding what enters the window this turn.
- **Skills** (§7) are procedural memory that happens to be executable.
- **Trust classes and provenance** (§8) are memory deciding which of its beliefs may authorize action.
- **Subagent returns** (§10) are memory writes with a different origin.
- **Voice** (§9) is memory under a 300 ms retrieval budget.
- **The trust ledger** (Addendum A §A8) is memory about the agent's own reliability.
- **Self-improvement** (§13) is consolidation applied to the agent's own behavior.

The practical consequence for your architecture: **if memory is a module the rest of the system calls, the design is wrong.** Memory is the substrate the rest of the system is built on. When a design choice trades memory quality for anything else, memory wins.

The kill criterion for the entire project is in §5.7: if auto-injection precision cannot reach 0.95 with a ≤300 ms P95 and a ≤7,000-token budget, Marlowe is a well-built harness with nothing distinguishing it, and the project should be reconsidered rather than continued. Build the memory prototype and its eval first, before anything else exists.

**2. The terminal is the primary surface — and memory is invisible in it.**

Marlowe is terminal-native. Every other surface — voice, messaging, mobile — is a projection of the same session, the same memory, and the same commands.

Memory gets no representation in the interface. The user experiences it the way they experience it in a good colleague: the agent simply knows things. No memory panel, no confidence scores, no inline citations, no status-bar field. An agent that narrates its own recall is not demonstrating good memory. Retrieval instrumentation exists only under `--dev`, for building and tuning, and is never part of the product surface.

The terminal is specified in **Addendum B**, which you must read alongside this brief.

---

## 2. Competitive Landscape — Who You Must Beat, and Where They Are Soft

Design against these specifically. Do not reinvent what they already do well; attack what they do badly.

### Hermes Agent (Nous Research, MIT license)

The most complete open harness available. Model-agnostic via provider adapters normalizing chat-completions, Anthropic Messages, Codex Responses, and Bedrock. Sessions live in SQLite with FTS5 search and WAL journaling. Compression produces *lineage chains* rather than rewritten transcripts — it closes the session row, spawns a child seeded by the summary, rotates the session ID, and records parent-child provenance. System prompt is explicitly tiered into stable / context / volatile. Tool *registration* is separated from tool *exposure*, so a large installed library can present a small model-visible surface. Cron is a first-class subsystem gated by the same permission machinery as interactive sessions. Messaging gateway spans Telegram, Discord, Slack, WhatsApp, Signal, email, and CLI. Profiles give isolated agent roots on one machine. It creates skills from experience and "nudges" itself to persist knowledge.

**Where it is soft:**
- **No durable child-run control plane.** Delegated subagents live under the parent call path — when the parent finishes, the child dies. There are no run IDs with independent lifecycle, no external steering of a running child, no cleanup semantics that survive parent completion. Arize names this explicitly as the gap. **This is your opening.**
- **Memory is retrieval-flavored, not memory-flavored.** Agent-curated facts plus FTS5 full-text search over session history plus LLM summarization. That is a good search index. It is not a memory system: no consolidation, no principled forgetting, no confidence decay, no contradiction resolution, no provenance-gated trust.

### OpenClaw

Infrastructure-first rather than framework-first. No LangChain, no LangGraph, no DAGs. A minimal agent core with a small tool set, tree-structured sessions supporting branching and recovery, a WebSocket Gateway control plane handling sessions, presence, config, cron, webhooks, and channel routing. Write-ahead queuing gives checkpoint-based resume. Durable task orchestration means flows survive gateway restarts and resume mid-step. Long-term memory is **the filesystem** — a workspace of injected prompt files and skills, with the invariant that memory is always flushed to disk before being dropped from context.

**Where it is soft:** the filesystem-as-memory bet keeps the system legible and cheap, but it makes precision retrieval at scale someone else's problem. The agent must know a file exists to read it. There is no mechanism for "you learned this eleven weeks ago in an unrelated context and it is relevant now."

### Claude Code and editor-first coding agents

Excellent execution quality on code. Separates planning from execution, with subagents for testing, documentation, debugging. OS-level sandboxing with kernel-enforced filesystem and network controls — but **opt-in**, not default. Editor-first and session-bound: close the tab, lose the thread. Single-vendor model path.

**Where it is soft:** it is a coding tool that grew a harness, not a harness that happens to code. No voice. No ambient presence. No cross-surface identity.

### Memory vendors (Mem0, Zep/Graphiti, Letta, and the 2026 cohort)

Strong published numbers, weak comparability. Vendor-reported scores cluster suspiciously: LongMemEval results in the low-to-mid 90s are claimed by several systems, while independent runs of LoCoMo put Mem0 near 67% and OpenAI's native memory near 53%. Zep/Graphiti reports ~71% on LongMemEval. The gap between vendor-reported and independently-run numbers is the story.

Letta (production MemGPT) is the reference implementation of LLM-managed tiered memory — core/archival/recall paged through function calls — and its acknowledged weakness is that LLM-managed paging adds latency and token cost to every interaction where the model decides to page.

**Where they are all soft:** none of them solve cross-session identity, temporal abstraction at scale, or memory staleness. Mem0's own state-of-the-field writeup names those three as the open problems. And essentially none of them treat memory poisoning as a first-class design constraint (§8).

### Durable-execution platforms (Cloudflare Workflows/Fibers, DBOS, LangGraph, Temporal)

They have solved the substrate you need for long-running work: persist each step, retry failures, sleep for hours, wait on external events like human approval, resume after interruption. LangGraph's weakness for our purposes is that it is a *graph-definition* framework — you encode nodes and edges ahead of time. Our agents spawn work at runtime based on what the model decides, not a pre-declared topology.

**Take the primitives. Reject the topology.**

---

## 3. Non-Negotiable Invariants

These are not requirements. They are properties that must hold at every point in the design. If a feature violates one, the feature loses.

1. **Nothing is lost on the boundary.** Every context eviction, compaction, crash, restart, provider failover, or session rotation writes durable state *before* discarding volatile state. Not after. Not concurrently. Before.
2. **Every belief has a birth certificate.** No fact enters long-term memory without recorded origin, timestamp, derivation path, and trust class. Untraceable memory is not memory; it is contamination.
3. **The model is not the security boundary.** Every policy — permissions, approvals, egress, redaction, spend caps — is enforced outside the model's cooperation, in code that runs whether or not the model agrees.
4. **Degrade, never break.** No dependency is fatal. Voice down → text works. Vector store down → lexical retrieval works. Provider down → failover. Network down → local model, reduced capability, clear disclosure to the user.
5. **The user can always see, edit, and delete what the system believes about them.** Memory is inspectable and correctable by construction, not through an admin panel bolted on later.
6. **A running task survives the thing that started it.** Closing a terminal, dropping a call, restarting the gateway, switching providers mid-run: none of these kill work in flight.
7. **Every autonomous action is reconstructable.** Given a trace ID, a human can replay exactly what the agent saw, decided, and did, including which memories were injected and why.

---

## 4. The Simplicity Budget (Hard Constraint)

The request was: *simple yet powerful, strength coming from simplicity*. That is only achievable if simplicity is a budget you spend, not an adjective you claim. Enforce it:

- **Core tool count: ≤ 12 model-visible tools in any single run.** Research is consistent that tool bloat degrades performance: 19 well-designed tools outperform 46 in the same window, and one documented case saw accuracy move from 80% to 100% purely by removing tools. Registration is unlimited; *exposure* is budgeted. Everything else reaches the model through search-and-load, not front-loading.
- **Core loop: one loop.** No mode-specific loops for research, voice, coding, or automation. Those are configurations of one loop, differing in tool exposure, budgets, and interrupt policy. If you need a second loop, you have failed.
- **Concept count: ≤ 7 user-facing nouns.** The user should be able to name every concept in the system on their fingers. Candidates: *session, memory, skill, tool, run, trigger, profile*. If you introduce an eighth, delete one.
- **Zero-config first run.** `install → run → useful` with no configuration file. Every knob has a defensible default. Configuration is for the second week, not the first hour.
- **Single-binary or single-command install**, running usefully on a $5/month VPS as well as on a workstation.
- **Plain files where plain files suffice.** Skills, identity, and project context are human-readable files a user can edit in any editor and version in git. Databases are for things that need indexes.

**The test:** a competent developer should understand the entire architecture in one sitting, and a non-developer should be able to use it without understanding any of it.

---

## 5. R1 — Memory (The Centerpiece)

This is the requirement the project lives or dies on. Everything below is mandatory.

### 5.1 What is wrong with the state of the art

Current systems do one of three things, all insufficient:

- **Search over transcripts** (Hermes FTS5, most RAG memory). Recall depends on lexical or embedding overlap with the current query. Fails when relevance is not similarity — when the useful memory shares no vocabulary with the question.
- **LLM-curated fact lists** (Letta, Mem0-style extraction). Better precision, but every write costs a model call, facts go stale silently, and contradictions accumulate without resolution.
- **Knowledge graphs with temporal edges** (Zep/Graphiti). Strong on relations and time, expensive to maintain, and brittle when entity resolution fails.

None of them forget correctly. None of them know how confident they are. None of them distinguish "the user told me this" from "I inferred this from a webpage I read."

### 5.2 Required architecture: four stores, one interface

Model this on complementary learning systems theory — fast episodic encoding, slow semantic extraction — because it is the only account we have of a memory system that works at human scale.

| Store | Holds | Written | Read | Decay |
|---|---|---|---|---|
| **Working** | Current task state, active goals | Continuously, in-context | Always present | Ends with the run |
| **Episodic** | Time-indexed events: what happened, when, in what session, with what outcome | Append-only at write time, cheap, no LLM call in the hot path | Retrieved by time, entity, similarity, or causal link | Progressive fidelity reduction, never silent deletion |
| **Semantic** | Consolidated facts, preferences, entity relations, stable beliefs | Offline consolidation only | Retrieved by entity, relation, and query | Confidence decay + contradiction resolution |
| **Procedural** | How-to knowledge — skills, learned workflows, environment quirks | Induced from repeated successful trajectories | Loaded as skills via progressive disclosure | Superseded by better versions, versioned not deleted |

**One interface.** The agent sees a small, uniform memory API. It must not need to know which store answers a query. Routing is the harness's job.

### 5.3 Consolidation (offline, mandatory)

Writes on the hot path must be cheap and dumb. Intelligence happens offline.

- A **consolidation pass** runs on idle, on schedule, and on session close. It replays recent episodic memory and extracts semantic facts, merges duplicates, resolves contradictions against recency and source trust, promotes recurring successful patterns into procedural skills, and clusters related episodes into narrative gists.
- Newly consolidated memories enter in a **low-activation "silent" state** and require corroboration or elapsed stability before they can influence high-stakes reasoning. This mirrors the engram-maturation finding that memories form immediately but stabilize slowly, and it is the cheapest available defense against single-exposure poisoning.
- **Reconsolidation:** retrieving a memory opens a lability window in which it can be updated by newer evidence. A retrieved fact that conflicts with current evidence must be resolved at retrieval time, not left to rot.
- Consolidation is itself an episodic event. The system remembers having consolidated, what it merged, and what it discarded. This makes the memory system auditable and debuggable.

### 5.4 Forgetting (mandatory, and the thing nobody builds)

Forgetting is not deletion. It is graduated fidelity loss with a permanent tombstone.

Required: a decay model combining exponential trace decay with **retrieval-induced interference** — when memories share entities and content, they compete, and low-value high-interference memories degrade first. Required: progressive fidelity levels from full episodic record → summary → gist → tombstone, where a tombstone records *that something was known and forgotten* so the system can answer "I used to know something about this."

**Never silently delete.** A memory the user can no longer surface but the system silently acted on is the worst possible failure.

### 5.5 Retrieval — the precision requirement

The user's phrasing — *"recall and inject relevant memories with high precision and low failure rate"* — is the hardest line in the original brief. Make it measurable:

**Required retrieval architecture:**
- **Multi-cue recall.** Never a single retriever. Minimum: dense semantic + lexical/BM25 + entity-graph traversal + temporal proximity + causal linkage. Fuse and rerank. Multi-cue is how biological recall works and it is the only defense against the single-retriever failure mode.
- **Query-type routing.** Classify the query before retrieving. Temporal and numeric queries route differently from historical and multi-hop ones; published work reports large accuracy swings from routing alone. Do not run one pipeline for all query shapes.
- **Precision-first injection.** Retrieval returns candidates; a gate decides what enters context. Injecting a wrong memory is worse than injecting none — it actively corrupts reasoning. The gate must be tuned for precision, with recall recovered by making the agent's explicit memory *search* tool excellent.
- **Abstention.** The system must be able to answer "I don't have that." LongMemEval scores abstention explicitly because confident fabrication from memory is the characteristic failure of these systems. **Abstention accuracy is a first-class metric, not a footnote.**
- **Salience-triggered proactive recall.** The user did not ask for search; they asked for *memory*. The system must surface relevant memory unprompted when salience crosses a threshold — and must be measured on how often that surfacing is unwanted, not just how often it is correct.

### 5.6 Provenance and trust classes (mandatory — see also §8)

Every memory entry carries:

```
{
  id, content, embedding_refs,
  created_at, last_accessed, access_count,
  source: { channel, actor, url|session_id|tool_call_id },
  trust_class: user_asserted | agent_observed | agent_inferred | untrusted_content,
  derivation: [parent_memory_ids],       // full lineage, not just immediate parent
  confidence: float, activation: float,
  supersedes: [memory_ids], superseded_by: memory_id|null,
  signature                              // write-time integrity binding
}
```

**Trust propagates by worst-case along the derivation chain.** A "fact" summarized by the agent from a webpage is `untrusted_content`-derived no matter how many LLM transformations sit between the webpage and the stored sentence. This is the memory-laundering attack, and content-based or coarse-taint filters demonstrably cannot catch it — only write-time origin binding with lineage propagation can.

**Action gating by trust class.** Memories derived from untrusted content may inform *analysis* but may not authorize *action*. High-consequence tool calls require parameters traceable to a trusted origin.

### 5.7 Memory acceptance criteria

| Metric | Target | Notes |
|---|---|---|
| LongMemEval-S (500 q, ~115k-token histories) | ≥ 90% overall | Report per-category; single-session, multi-session, temporal, knowledge-update, preference, abstention |
| LongMemEval abstention subset | ≥ 85% | Correctly declining on events that never happened |
| LongMemEval-M (~500 sessions/history) | Report honestly | Regime where context-stuffing fails entirely |
| LoCoMo (1,540 q) | ≥ 85% | Baseline only; do not treat as sufficient |
| BEAM-1M / BEAM-10M | Report | Deliberately unsaturated; a low score honestly reported beats a high score on a saturated benchmark |
| LongMemEval-V2 | Report | 100M+ token multimodal agent histories; the current frontier bar |
| **Injection precision** | ≥ 0.95 | Fraction of auto-injected memories a human judge rates relevant. **The headline metric.** **AMENDED 2026-08-08 — see the block below this table.** |
| **Tokens per query** | ≤ 7,000 | Accuracy without a token budget is not a result. Pair every accuracy number with its cost. |
| **P95 retrieval latency** | ≤ 300 ms | Non-negotiable for voice (§9) |
| **Poisoning resistance** | 0% ASR for unsigned writes | Measured against MINJA-, MemoryGraft-, and laundering-style attacks |
| **Staleness half-life** | Measured | Time before a superseded fact stops being retrieved |

**Report the pair.** Every accuracy number ships with its token cost and latency, or it does not ship. Vendor-reported memory numbers in this space are not comparable across systems; ours must be reproducible with a published harness.

#### 5.7.1 Injection precision — AMENDMENT, 2026-08-08

**The row above is left standing rather than rewritten.** It was a reasonable bar written before anyone knew what was reachable, and a requirements table that quietly changes its own numbers is not a record. What follows amends it; it does not replace the history. Pinned text: `docs/design/ROADMAP.md` → "K1 — amended 2026-08-08". Argument: ADR-019. Measurement: M0b Session J, `runs/session-j/RESULT.md`.

**Measured, held-out, n=229: no coverage level reaches 0.95 injection precision with its confidence interval above the threshold.** Best point estimate 0.9565 (22/23) at 10.0% coverage, Clopper-Pearson [0.7805, 0.9989]. This was the registered prediction, written before the read.

**Injection precision is now judged on a published precision/coverage curve rather than a single threshold**, under three conditions: the curve ships with the product (every level 100% → 10%, each with its binomial interval, on a held-out split the gate's parameters have never seen); the operating point is chosen on the curve and **declared** wherever the capability is described; and the abstention path is real, with **a configuration that injects at low precision to raise coverage failing outright**.

**A new kill condition replaces the old one and it is not weaker.** The project is reconsidered if the curve is **flat** — precision at 10% coverage not materially above precision at 100%. A confidence signal carrying no information is the failure this metric was written to catch, and it remains project-level. **The 0.95 threshold is not lowered.** The criterion's shape changed; its number did not.

**≤7,000 tokens and ≤300 ms P95 are unchanged and still bind.**

**One correction to how the historical numbers in this document were read.** Per ADR-016, the "max calibrated precision 0.3739 against a 0.95 threshold" figure quoted across nine sessions **never measured retrieval quality**: a perfect retrieval system scores **0.8483** on the shipped gate, because the calibration's smallest expressible operating point spans 100% of queries and it has no vocabulary for confident subsets. **This invalidates no retrieval measurement** — R@1, R@5, R@10, conditional accuracy, the oracle and every closed mechanism were measured against gold turns with the gate uninvolved. It invalidates the interpretation of one number.

**The human-judged quantity this row names has still never been computed.** Every figure to date is a gold-turn proxy. The ≥400-judgment blind label set (§5.7, M0a) remains the only path to the real number, and it is now drawable because a conformal operating point exists to sample from.

---

## 6. R2 — Context Engineering

Distinct from memory. Memory decides what *exists*; context engineering decides what *enters the window this turn*.

- **Budget by fill percentage, not absolute tokens.** Model attention degrades measurably as inputs grow — Chroma's context-rot work found degradation across all 18 frontier models tested, and practitioners report meaningful decline past ~50% fill and sharp decline past ~75%. **Trigger compaction at ~70% of the effective window, never at exhaustion** — a model already impaired by context rot writes a degraded summary.
- **Explicit token budget per source,** enforced by a budget-aware context assembler: system prompt, memory injection, tool definitions, retrieval, history, and a mandatory reserve buffer. Re-measure whenever a tool or source is added.
- **Tool-result clearing before compaction.** Observation masking — keeping the last N tool results and replacing older ones with placeholders — is the cheaper and better first lever. JetBrains reported 50%+ cost savings with a higher solve rate at roughly half the cost versus full-context approaches. Use clearing as primary; reserve compaction for preserving reasoning across long dialogues.
- **Compaction produces lineage, not rewrites.** Adopt the Hermes pattern: close the session row, spawn a child seeded by the summary, rotate the ID, record parent-child provenance. A long conversation becomes a chain, not a repeatedly-overwritten transcript. This is what makes post-hoc audit possible.
- **Governance survives compaction.** Published work shows compaction silently erases safety constraints from long-horizon agents, causing unsafe tool calls downstream. **Permissions, approvals, and user-asserted constraints live in the stable tier and are re-asserted post-compaction, structurally — never left to survive a summarizer's judgment.**
- **Cache-aware prompt assembly.** Tier the system prompt (stable / context / volatile) so prefixes stay cache-friendly. Note the documented failure mode: a caching change without a compaction-triggered invalidation served stale pre-compaction prefixes into post-compaction turns. **Compaction must invalidate cache. Test this explicitly.**
- **Sandbox tool output before it reaches context.** Let the agent query large results with code rather than reading them — reported reductions up to ~99% of tokens for large structured outputs. The raw data should never touch attention.

---

## 7. R3 — Tools and Skills

### 7.1 Skills

- **Adopt the open Agent Skills standard (SKILL.md, agentskills.io, Apache 2.0).** Do not invent a format. The spec is adopted across 26+ platforms including Claude Code, Codex, Gemini CLI, Copilot, and Cursor. Portability in, portability out. A skill written for us runs elsewhere; a skill written elsewhere runs here. Fighting this standard is a strategic error with no upside.
- **Progressive disclosure, strictly enforced.** Discovery (~30–100 tokens of name + description per skill, in the system prompt) → Activation (full SKILL.md, target under 5,000 tokens) → Execution (bundled scripts, references, assets loaded only on demand).
- **Semantic skill discovery at scale.** Once a library exceeds a few dozen skills, advertising all descriptions defeats the budget. Required: embed *description plus trigger phrases only* — not full instruction prose, which pollutes the vector space — and expose a `find_skill` tool. Do not embed the whole SKILL.md.
- **Authoring must be trivial.** A folder and a markdown file. `skill new` scaffolds it. The agent can author one from a conversation in a single turn.
- **Skills are signed and reviewed.** Skills carry executable code with filesystem, environment, and credential access. Publicly distributed skills have already been found containing prompt injection, tool poisoning, and malware. Required: signature verification, a declared capability manifest (what filesystem paths, network hosts, and credentials the skill needs), install-time diff review, and refusal to auto-execute unsigned third-party skills.

### 7.2 Tools

- **MCP as the tool transport.** Same reasoning as skills: do not invent a protocol. Skills supply judgment; MCP supplies capability. Neither replaces the other.
- **Registration ≠ exposure.** Adopt the Hermes separation. A large registry, a small per-run visible surface, scoped by profile, platform, task, and delegation depth. Enforce the ≤12 budget from §4.
- **Tool search over tool listing.** Beyond the exposed core, tools are found via search and loaded on demand.
- **Code execution as the universal adapter.** The most powerful tool is a sandboxed interpreter. Prefer "write and run a script" over adding a bespoke tool for every capability. This is the single largest simplicity lever available.
- **MCP servers are untrusted input.** Tool *descriptions* are an injection vector. Scan them, pin them, diff them on update, and never let a tool description alter system-prompt-level behavior.

### 7.3 Default skill set (must rival a top coding agent out of the box)

File operations with atomic edits. Shell in a persistent session. Code execution across major runtimes. Repo-aware code search — prefer index-backed symbol lookup over probabilistic text retrieval where an index is available. Test running and iteration. Git operations. Web search and fetch. Browser automation. Document generation (docx/pptx/xlsx/pdf). Data analysis and charting. Vision. Image generation. Text-to-speech. Scheduling. Email and messaging. Memory management. Subagent delegation.

**Ship these as skills, not as hardcoded tools.** If the default set is skills, users can read them, fork them, and fix them. That is the whole argument for the format.

---

## 8. R4 — Security, Permissions, and Blast Radius

The user did not list this. It is mandatory anyway, and it is where most harnesses are negligent.

### 8.1 The lethal trifecta

An agent with (a) access to private data, (b) exposure to untrusted content, and (c) the ability to communicate externally can be turned into an exfiltration tool by any text it reads. Each leg is safe alone. All three together is exploitable by construction. Our harness has all three by design — that is what makes it useful.

The threat is not theoretical. Google's April 2026 Common Crawl analysis found injections embedded across public web pages and reported a ~32% increase in malicious attempts between November 2025 and February 2026. Real CVEs have landed against major coding agents: one against Cursor where an allowlist made the attack *easier* by auto-approving exactly the commands the attacker needed, and one against Codex CLI where the agent's own output redefined its sandbox boundary.

**Filtering does not work. Containment works.** Design accordingly:

### 8.2 Required controls

- **Containment by permission layer, with the kernel sandbox scoped to the quarantined reader.** *(Amended 2026-08-02. This replaces the original requirement — "sandboxing on by default, not opt-in… ours is the default and the flag turns it off, loudly." See ADR-002.)*

  §8.1 is unchanged and remains the premise: the trifecta is real, filtering does not work, containment does. What changed is **where containment lives**, not whether it exists.

  **Primary containment is the permission layer**, and it is required to be exhaustive: capability manifests with declared paths and hosts and load-time default-deny, the `(action, target)` split, worst-case trust propagation over full lineage, egress allowlisting, and risk-tiered approval. Every one of these is platform-independent — they hold identically on Windows, Linux, and macOS, which kernel sandboxing does not.

  **Kernel-enforced sandboxing is retained for the quarantined reader** — the component of §8.2's next bullet that reads untrusted content with no tool access. That is a small, isolated, non-interactive component, so a container backend covers it everywhere without the erosion problem below.

  **This is a deliberate divergence from the original differentiator, and the reasons are these two:**

  1. **A secretary that cannot reach the user's files is not a secretary.** The product is an assistant that knows your work. An assistant that sees only a copied-in subset is one you have to feed, and feeding it is the work it was supposed to remove. Sandbox-by-default made the harness safer and the product not exist.
  2. **A default that must be overridden daily is not a default.** On Windows, sandbox-by-default degrades to *refuse to run without a container* — which for this product means refuse to run. The escape hatch then gets used every day, stops reading as a warning inside a week, and "sandboxed by default" becomes a claim about a code path nobody exercises. A default nobody keeps is worse than an honest absence, because it is believed.

  **The cost, recorded here and not only in the ADR: a permission-layer bug has no kernel backstop.** It was a second wall behind a first; on the ordinary path it is now the only wall. Three consequences bind:

  - The permission layer is **the highest-value target in the system** for review, testing, and red-teaming. §8.3's AgentDojo numbers stop measuring defence-in-depth and start measuring whether containment works at all.
  - **Path scoping is a security boundary, not a convenience.** A path check defeated by string manipulation is the whole protection gone — there is nothing behind it. Canonicalize before checking, never after, and operate on handles rather than re-resolved strings.
  - **`Inert` reads remain unchecked on targets only because three non-kernel mechanisms cover them** — untrusted-content classing, return-by-reference, and egress allowlisting. If any one weakens, that exemption must be revisited rather than inherited.
- **Structural trifecta-breaking.** The component that reads untrusted content has no tool access and returns structured analysis only. The component with tool access receives sanitized structured input, never raw untrusted text. A trusted orchestrator moves data across that boundary with validation and, where warranted, human approval. Collapsing reader and doer into one agent is what makes current deployments exploitable.
- **Egress allowlisting by default.** Outbound network is deny-by-default per run. Data leaves only to declared destinations. Rendered content cannot fetch external resources — that closes the image-beacon exfiltration channel.
- **Approval gates that scale.** Not a yes/no prompt on every action (users click through those within a day). Risk-tiered: silent for reversible reads, batched for routine writes, blocking for irreversible or high-consequence actions. Approvals are enforced by the harness, not requested by the model.
- **Capability manifests.** Every skill, tool, and MCP server declares required paths, hosts, and credentials up front. Undeclared access is denied at runtime, not warned about.
- **Spend and blast-radius caps.** Per-run and per-day ceilings on tokens, wall-clock, tool calls, subagent count, recursion depth, and money. Hitting a cap pauses and asks; it never fails silently or spends past the line.
- **Memory writes are the highest-privilege operation in the system.** See §5.6. Poisoning is temporally decoupled from its trigger — poison planted today fires weeks later when semantically retrieved — which defeats every defense that watches for malicious *actions* rather than corrupted *beliefs*. Note the uncomfortable finding that more capable models are not more secure here, and that agents which write and retrieve memory more aggressively are *more* exploitable. Our aggressive memory system therefore requires proportionally aggressive write-time provenance.
- **Full audit trail.** Every tool call, memory write, permission decision, and injected memory, keyed by trace ID and replayable.

### 8.3 Security acceptance criteria

- 0% attack success rate against unsigned memory writes.
- Measured resistance on an AgentDojo-style prompt-injection suite, reported as attack success rate *and* utility retention — a defense that blocks everything by breaking the agent is not a defense. **Since the §8.2 amendment this is a first-order result, not a defence-in-depth check**: with no kernel backstop on the ordinary path, it is the primary evidence that containment works.
- **Path-traversal resistance, tested adversarially.** Symlinks and Windows junctions, `..` sequences, UNC and `\\?\` forms, 8.3 short names, case-insensitivity collisions, Win32 name munging, alternate data streams, Unicode normalization. **Inseparable from handle-based access**: canonicalize-then-open leaves a check-then-use race, so a traversal suite passing against a check-then-open implementation reports a boundary that is not there. The suite and the handle discipline are one requirement and ship together.
- Red-team suite includes: memory laundering through LLM-mediated derivation, delayed-trigger poisoning, tool-description poisoning, skill supply-chain compromise, and sandbox-boundary redefinition via agent output.

---

## 9. R5 — Voice

The requirement is: *turn it on, talk to it, it talks back*. That is an interaction-design problem and a latency problem, not a transcription problem.

### 9.1 Latency contract

| Measurement | Target | Ceiling |
|---|---|---|
| Voice-to-voice (end of user speech → first agent audio), P50 | ≤ 800 ms | 1.5 s |
| Voice-to-voice, P95 | ≤ 1.5 s | 3.0 s |
| Barge-in (user speech onset → TTS flush) | ≤ 150 ms | 200 ms |
| Turn gap (end of agent speech → next turn ready) | 200–450 ms | — |

Context: human conversational response averages around 200 ms. As of spring 2026, end-to-end speech-to-speech TTFT across leading providers clustered roughly between 0.78 s and 2.98 s; cascaded pipelines in production typically land between 1.5 s and 3 s. Above ~1.5 s, users report the agent feels broken.

### 9.2 Architecture requirements

- **Cascade with streaming overlap as the default**, speech-to-speech as a pluggable path. Cascade keeps component-level control (STT choice, TTS voice, model choice) and remains where provider differentiation lives; S2S wins on latency and prosody. Support both; do not hard-couple.
- **Three-layer turn-taking, not one.** Acoustic VAD → endpointing → **semantic turn detection** scoring whether the transcript represents a completed thought. Silence thresholds alone produce either interruption or sluggishness. This layer is the single largest contributor to whether the agent feels human.
- **Backchannel discrimination.** "Mm-hm," "okay," and "right" are not turn claims. Require a minimum speech duration (~0.2 s) before treating detected speech as an interruption, and tune against real recordings. Barge-in occurs in roughly one in five conversations — this is a main path, not an edge case.
- **Mid-tool interrupt policy, specified.** When the user interrupts during a tool call: idempotent reads complete; mutations cancel on contradiction. State the policy in code, make it overridable in code, and never make it a config knob — tool semantics belong in code review.
- **Streaming everywhere.** STT streams while the user speaks; the model starts on partial context; TTS starts on the first sentence while generation continues. Sequential execution cannot meet the budget.
- **Memory retrieval must fit the budget.** §5.7 sets P95 retrieval at 300 ms specifically so that memory injection does not consume the voice budget. If memory cannot hit that, voice gets a degraded memory path and says so.
- **Voice is a surface, not a mode.** Same session, same memory, same tools. Start a task by voice, continue in text on a phone, finish in a terminal. One session identity across all of them.
- **Long-running work is announced, not blocked on.** "That'll take a few minutes — I'll ping you." The agent hands off to a background run and notifies on completion. It never holds a voice channel open through a ten-minute research task.
- **Graceful degradation.** Voice unavailable → text. TTS unavailable → text with a spoken apology if possible. Never silent failure.

---

## 10. R6 — Orchestration, Subagents, and Deep Research

### 10.1 The orchestration control plane (your primary competitive opening)

Hermes has strong delegation and no durable child-run control. Build the thing that is missing:

- **Runs are first-class control-plane objects with their own identity and lifecycle.** A run has an ID, a status, an owner, a budget, a parent (optional), and a result location. It is addressable, inspectable, steerable, and cancellable from outside.
- **Child runs outlive their parents.** Parent completion does not kill children. Orphan policy is explicit: adopt, detach, or terminate — declared at spawn time, not inferred.
- **Runs are durable.** Write-ahead logging with checkpoint-based resume. A run survives gateway restart, provider failover, and host reboot, resuming from the last completed step. Take the primitives from the durable-execution ecosystem: persist each step, retry, sleep for hours, wait on external events including human approval.
- **Runs are steerable mid-flight.** A human or a parent can inject guidance into a running child without killing and restarting it. This is what makes hour-long autonomous work tolerable — you can course-correct at minute 12 instead of discovering failure at minute 60.
- **Isolation is the default topology.** Orchestrator-worker, not swarm. Workers do not talk to each other; every decision about what happens next lives in the orchestrator. Each worker gets a self-contained task description, an output contract, and a fresh context window, and does not know the others exist. Swarms are flexible and unreasonable-about; constrained topology is what makes production behavior predictable.
- **Ad-hoc spawning, not predeclared graphs.** The model decides at runtime what to spawn. Do not require a DAG up front.

### 10.2 Deep research mode

Anthropic's published results give the shape and the price: an orchestrator-worker research system with parallel subagents outperformed a strong single agent by ~90.2% on their internal research eval, at roughly **15× the token cost of a normal chat**, with about 80% of performance variance attributable to token usage. Their documented early failures are the ones you must design against: spawning excessive subagents for simple queries, redundant searching, endless loops hunting nonexistent sources, and unnecessary status chatter.

**Requirements:**

- **Effort scaling.** The orchestrator sizes the investigation to the question — subagent count, search budget, and depth all scale with assessed complexity. Simple questions must not trigger fleets. Make the scaling rule explicit and inspectable.
- **Explicit subagent contracts.** Each gets an objective, a scope boundary, an output schema, a source-quality bar, and a budget. Ambiguity here is what produces duplicate work.
- **Condensed structured returns.** Subagents return findings, not transcripts. The orchestrator's context must never accumulate raw worker history.
- **A separate verification pass.** Citations are checked against sources *after* synthesis, by a component that did not write the report. Citation hallucination is the characteristic failure of deep research agents and the reason a separate pass exists in every serious implementation.
- **Real artifacts.** The output is a written file — report, dataset, spreadsheet, deck, repo, dashboard — with working citations, not a chat message. "Real outputs" was in the original brief and it means files a human can hand to another human.
- **Progressive delivery.** Findings stream as they land. A ten-minute research run that shows nothing for ten minutes is unusable regardless of final quality.
- **Research runs are resumable.** Interrupted at minute seven, resumed at minute seven.

### 10.3 Research acceptance criteria

- **DeepResearch Bench** (100 PhD-level tasks, 22 fields): report RACE (comprehensiveness, insight/depth, instruction-following, readability, scored against expert reference reports) and FACT (effective citation count and citation accuracy). Target: RACE at or above expert-reference parity; **citation accuracy ≥ 95%**.
- **GAIA** and **BrowseComp** for multi-step retrieval and hard-to-find information.
- **Cost-normalized reporting.** Every quality number reported alongside tokens and wall-clock. A 15× token multiplier is acceptable when disclosed and controllable; it is not acceptable as a surprise.

---

## 11. R7 — True Automation

*"True automation"* means the agent does useful work when nobody is watching, and the user trusts it enough to let it.

- **Triggers are first-class**, gated by the same permission machinery as interactive sessions: schedule (cron and natural language: "every weekday at 7am"), event (webhook, file change, inbox, repo activity, calendar), condition (a watched value crosses a threshold), and manual.
- **Unattended runs use the same loop, the same memory, the same skills.** No separate automation subsystem. If automation needs its own code path, the architecture is wrong.
- **Autonomy is tiered and declared per trigger:** notify-only → propose-and-await-approval → act-and-report → act-silently. New automations start conservative and are promoted by the user after demonstrated reliability. **The system may never promote itself.**
- **Failure is loud.** A failed unattended run notifies with a diagnosis and a proposed fix. Silent failure destroys trust faster than visible failure.
- **Cost ceilings per automation**, enforced. Runaway loops are the characteristic failure mode of unattended agents.
- **Every automation is auditable and revocable in one command.** The user can see everything scheduled, everything that ran, what it did, what it cost, and kill any of it instantly.
- **Idempotency and dedup.** Events fire twice. Design for it.

---

## 12. R8 — Surfaces, Identity, and Model Routing

- **One agent, one memory, every surface.** CLI, desktop, mobile, web, voice, and messaging platforms (Telegram, Discord, Slack, WhatsApp, Signal, email). Messages route to the correct session *before* inference, using gateway metadata. Hermes and OpenClaw both prove this pattern works; match it and add the durable-run layer they lack.
- **Profiles as isolated agent roots.** Two profiles on one machine behave as two different agents in state, memory, credentials, and permissions. Work agent and personal agent must not share memory unless explicitly bridged.
- **Provider abstraction with normalized adapters.** Multiple API shapes behind one loop-level surface, with tool-call format quirks normalized in the transport layer. Switch models with one command, no code changes, no lock-in. Support hosted frontier models, aggregators, and local endpoints.
- **Tiered model routing by role.** Strong model for orchestration and synthesis; fast cheap models for subagent search, extraction, classification, consolidation, and semantic turn detection. Route by task, not by preference. This is the main cost lever in the whole system.
- **Failover with per-channel retry policy**, preserving run state across provider transitions.
- **Local-model path** for privacy-sensitive work, with honest disclosure of the capability difference.

---

## 13. R9 — Self-Improvement (Bounded)

The original brief implies this; make it explicit and make it safe.

- **Skill induction from experience.** After repeated successful completions of similar tasks, distill a reusable skill. The strongest published approach analyzes a *pool* of diverse trajectories in parallel before distilling one comprehensive guide, rather than reacting to individual trajectories sequentially — sequential distillation overfits to trajectory-local lessons and produces fragile, fragmented skills. Contextual experience replay results support the payoff: ~1.7× skill reuse on seen environments and meaningful success-rate gains on unseen ones, with fewer steps.
- **Environment knowledge accumulation.** The agent learns that this repo's tests are slow, that this API rate-limits at 3 rps, that this user hates bullet points. This is procedural memory and it compounds.
- **Bounded self-edits.** The agent may propose changes to its own skills, prompts, and context artifacts. It may not modify its own permission system, sandbox configuration, audit logging, or memory provenance layer. **Ever.** State this boundary in the architecture, not in a policy document.
- **Two-split acceptance.** Self-proposed changes are validated on a held-out split before adoption, with automatic rollback on regression. Improvements that cannot be measured are not adopted.
- **Versioned and reversible.** Every self-modification is a diff the user can review, revert, and audit. The agent's evolution is a git history, not a mystery.

---

## 14. Hard Problems — Where Your Design Must Be Original

These are unsolved. Do not paper over them. Pick a position and defend it.

1. **The salience problem.** Proactive memory injection requires deciding relevance *before* knowing what the user wants. Too eager and you poison context with noise; too conservative and it is just search with extra steps. What is your salience function, and how do you tune the threshold without a labeled dataset?
2. **Cross-session identity.** Named as an open problem by practitioners in the field. When is "the API" in session 47 the same entity as "the API" in session 3? Entity resolution failures cascade through every graph-based memory system.
3. **Temporal abstraction at scale.** "The user has been getting steadily more frustrated with this project over six weeks" is a fact no single episode contains and no summarizer will surface. How do you represent trends and trajectories, not just events?
4. **Staleness.** How does the system know a fact has expired without being told? Confidence decay is a proxy, not an answer. What is the actual detection mechanism?
5. **The consolidation failure taxonomy.** Consolidation introduces its own errors — temporal compression, over-eager semantic merging, detail loss, and picking the wrong side of a contradiction. Which do you accept, which do you detect, and how?
6. **Memory laundering.** Untrusted content transformed through several LLM derivations into an authentic-looking agent-written memory. Content signals and coarse taint tracking are structurally insufficient here. How does your write-time origin binding survive derivation?
7. **The 15× cost problem.** Deep research quality tracks token spend almost linearly. How does the user control that dial without needing to understand it?
8. **Approval fatigue.** Users click through prompts. What is the mechanism that keeps approval meaningful in week ten?
9. **Voice and deep work.** A voice conversation runs at 800 ms per turn; a research task runs for ten minutes. How do these coexist in one session model without either blocking or fragmenting?
10. **Simplicity under accumulation.** Every requirement here adds surface. What is the mechanism — not the intention — that keeps this from becoming another framework in eighteen months?

---

## 15. Anti-Requirements

Explicitly do not build:

- A visual workflow builder or YAML-defined agent graph. The model decides at runtime; predeclared topology fights that.
- A general-purpose framework. This is a product with an extension surface, not a library with a product bolted on.
- A proprietary skill format. See §7.1.
- A proprietary tool protocol. See §7.2.
- A second agent loop for any mode. See §4.
- Memory that cannot be inspected, corrected, or deleted by the user.
- Any safety control the model can talk its way past.
- Cloud dependency for core function. It runs on a $5 VPS, offline-capable where the model allows.
- Benchmark numbers without cost and latency attached.
- Configuration required before first useful output.

---

## 16. Acceptance Bar — Summary

The system ships when it clears all of these, with reproducible published methodology:

| Domain | Benchmark | Target |
|---|---|---|
| Memory | LongMemEval-S / abstention subset | ≥90% / ≥85% |
| Memory | Injection precision (human-judged) | ≥0.95 |
| Memory | Tokens per query / P95 latency | ≤7,000 / ≤300 ms |
| Memory security | Unsigned-write attack success rate | 0% |
| Coding | SWE-bench Verified | Competitive with leading harnesses on the same model |
| Terminal | Terminal-Bench 2.0 (89 tasks, 16 categories) | Competitive on the same model |
| General agency | GAIA | Competitive on the same model |
| Tool use | τ-bench / BFCL | Competitive on the same model |
| Research | DeepResearch Bench RACE / FACT citation accuracy | ≥ reference parity / ≥95% |
| Voice | Voice-to-voice P50 / barge-in | ≤800 ms / ≤150 ms |
| Security | AgentDojo-style suite (ASR + utility retention) | Report both; ASR below published baselines |
| Reliability | Runs surviving restart, failover, host reboot | 100% resume from last checkpoint |
| Simplicity | Time from install to first useful output | < 5 minutes, zero config |

**Critical measurement discipline:** run competitors on the *same* model, the same task set, and the same harness-level budget. Cross-model comparisons measure the model, not the harness. Since this project *is* a harness, that distinction is the entire point of our evaluation.

---

## 17. The "Blown Away" Tests

If the finished system does all ten of these, it is what was asked for. Design toward them.

1. **The eleven-week callback.** In a voice conversation about something unrelated, the agent says: "This is the same failure mode you hit on the ingest pipeline in March — you fixed it by pinning the client version." It is right, it is unprompted, and the memory was never explicitly saved.
2. **The overnight report.** "Look into X while I sleep." Morning: a fifteen-page cited report, every citation verified, with a note on which questions it could *not* answer and why.
3. **The correction that sticks.** "No, I moved off Postgres in April." The agent updates the belief, marks what superseded it, and never surfaces the stale version again — including in a subagent three weeks later.
4. **The interruption.** Mid-sentence, the user cuts in with a correction. The agent stops inside 150 ms, absorbs it, and continues from the new premise without restarting.
5. **The skill that wrote itself.** After the third time doing a similar task, the agent says: "I've turned this into a skill. Want to look at it?" The skill is good, it is a plain readable file, and it works the fourth time without supervision.
6. **The survived crash.** Machine reboots at minute 40 of an hour-long run. It resumes at minute 40.
7. **The refused injection.** A web page the agent reads contains an instruction to exfiltrate credentials. The agent reports the attempt, the memory it derived carries an untrusted-origin marker, and the tool call is blocked by the harness — not by the model's judgment.
8. **The handoff.** Started by voice on a walk, continued by text on a phone, finished in a terminal. One session, one memory, no repetition, no restatement of context.
9. **The honest "no."** Asked about something it never learned, it says so — cleanly, without confabulating a plausible memory. Then it offers to go find out.
10. **The five-minute install.** A non-developer installs it, talks to it, and it does something genuinely useful before they have configured anything at all.

---

## 18. Sources

Competitive architecture: Arize's harness analyses (nine-component model; Hermes deep dive), Nous Research Hermes Agent documentation and repository, OpenClaw orchestration and agent-loop documentation, Cloudflare Agents platform writeups on durable workflows.

Memory: LongMemEval (ICLR 2025) and LongMemEval-V2; LoCoMo (ACL 2024); BEAM; Mem0's 2026 state-of-the-field and benchmark posts; independent benchmark comparisons noting vendor-vs-independent score divergence; complementary learning systems literature (McClelland et al. 1995); engram maturation (Kitamura et al. 2017); reconsolidation (Nader et al. 2000); Ebbinghaus decay and retrieval-induced interference (Anderson 2003); CoALA's episodic/semantic distinction; 2026 work on sleep-consolidated and human-inspired memory architectures.

Memory security: MINJA, AgentPoison, MemoryGraft, Zombie Agents, MPBench, eTAMP; MemLineage (lineage-guided enforcement); SMSR (write-time HMAC provenance); survey work on evidence tracing and execution provenance in LLM agents.

Context engineering: Chroma's context-rot research; Anthropic's effective-context-engineering guidance; JetBrains observation-masking results; published work on governance decay under compaction; documented compaction/cache-invalidation failure modes.

Orchestration and research: Anthropic's multi-agent research system writeup and managed-agents guidance; DeepResearch Bench (RACE and FACT); ReportBench; Terminal-Bench 2.0; GAIA; τ-bench.

Skills and tools: the Agent Skills specification (agentskills.io); progressive-disclosure implementations across Claude Code, Codex, and Microsoft Agent Framework; skills-over-MCP registry patterns.

Security: Simon Willison's lethal trifecta; OWASP LLM Top 10; Google's 2026 Common Crawl injection analysis; Sophos blast-radius analysis; CVE-2026-22708 (Cursor) and CVE-2025-59532 (Codex CLI); AgentDojo.

Voice: 2026 latency-budget and turn-taking guides; Artificial Analysis speech-to-speech TTFT measurements; Coval STT benchmark; Silero VAD, LiveKit semantic turn detection, Pipecat smart-turn.

Self-improvement: Contextual Experience Replay (ACL 2025); Trace2Skill; Self-Harness; Meta-Harness; SkillClaw; Darwin Gödel Machine.

---

*Written August 2026. Benchmark numbers and competitor capabilities move monthly — re-verify §2 and §16 before committing to a target.*