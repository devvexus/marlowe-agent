# Marlowe — Decisions

ADR format. **Settled.** Argue explicitly to revisit one; do not quietly design around it.

Part 1 answers all sixteen Hard Problems (brief §14, addendum §A15). Each states the choice,
the alternative rejected, and the cost accepted. Where a problem is genuinely unsolved it says
so and names the experiment that would resolve it.

Part 2 records infrastructure choices.

---

# Part 1 — The Hard Problems

## HP1 · The salience problem

**Context.** Auto-injection must decide relevance before knowing what the user wants. §5.7 sets
injection precision ≥0.95 as the project kill criterion. §B1 forbids the interface from ever
indicating that retrieval occurred, which removes the obvious label source. The 300 ms P95
rules out an LLM judge in the hot path.

**Decision.** The gate is a small learned scorer over cheap features, **frozen in M0** — fixed
weights, fixed threshold, no online learning. Three properties:

1. **Weights are a build-time artifact**, trained on benchmark gold evidence. LongMemEval
   supplies real supervised (query, gold-evidence) pairs; this is genuine training data, not a
   bootstrap hack.
2. **Features are user-specific even though weights are not** — entity frequency in *this*
   profile's graph, recency, access count, activation, effective trust class, and cue-agreement
   count. The gate adapts to a user's data without the model drifting.
3. **The threshold is expressed in calibrated precision units, not raw score.** An isotonic
   calibration curve maps score → predicted precision, so "0.95" means *predicted precision
   ≥0.95*. This is what makes the operating point portable across profiles.

All three supervision tiers are **built and logged in M0, feeding back into nothing**: build-time
gold evidence; runtime implicit signals (utilization, explicit `recall` after injection,
restatement, correction); and an offline consolidation-time judge calibrated against human
labels. A clean baseline that is not moving while it is being measured.

**Pinned regardless of any later adaptivity milestone — the supervision asymmetry:**
utilization is a **weak negative only**; positives come only from the offline judge and explicit
corrections. Recorded because it is easy to "optimise" away: a naive utilization reward would
let a poisoned memory train the gate to prefer it. Attention-grabbing and correct are not the
same property.

### The freeze scope — normative for the whole system

The freeze is **not** "the injection gate only," and it is **not** "everything." Other ADRs must
cite this rule rather than granting themselves an exemption. A component may adapt in M0 only if
**both** conditions hold:

1. **It is off the measured path.** Anything influencing what the M0a suite measures — query →
   routing → cues → fusion → gate → injected set — is on the path and is frozen. This
   deliberately includes components that do not feel like "the gate": **cue and fusion weights,
   the query-type router, entity-resolution thresholds (HP2), and consolidation merge thresholds
   (HP5)** all change what is retrievable and are therefore frozen in M0.
2. **It adapts from an explicit user act, not an inferred reward.** A tier change because the
   user granted, corrected, or dismissed is a *recorded decision* — discrete, attributable,
   auditable, and revertible. Learning weights from a proxy signal is an *inferred reward*.
   Inferred rewards are frozen in M0 everywhere, regardless of position.

| Component | M0 | Why |
|---|---|---|
| Injection gate, cue/fusion weights, router | **Frozen** | On the measured path |
| Entity-resolution and merge thresholds | **Frozen** | Change what is retrievable |
| Trust ledger tiers (§A8) | **Adapts** | Recorded user decisions, off the path |
| Noticing per-class suppression (HP11) | **Adapts** | Same mechanism as the ledger |
| Commitment mid-band handling (HP15) | **Adapts, narrowly** | See HP15 — the *band classifier* stays frozen |
| Voice model from sent mail (§A3) | **Adapts** | Off the path; not a reward signal |

The rule in one line: **recorded decisions are always permitted; inferred rewards wait for
M10.** The reason is measurement integrity, not caution — a baseline that moves while it is
being measured cannot support K1.

Proactive salience runs **outside the hot path**, pre-staging candidates continuously, so the
eleven-week callback is not computed inside a 300 ms budget.

**Rejected.** Per-profile online learning from turn one. A moving baseline cannot be measured,
and §5.7 requires results reproducible with a published harness.

**Cost accepted.** No gate personalization in v1. A user whose memory density is far from the
benchmark distribution gets benchmark-tuned behaviour until M10.

**Failure mode, recorded explicitly.** If M0b lands well below 0.95 with the gate frozen, **the
answer is not "add learning."** That treats a retrieval problem as a tuning problem. The correct
responses are better cues, a better query-type router, or accepting lower recall at the same
precision — recall is recovered through `recall`, per §5.5.

### Amendment (2026-08-03) · The fit/report split

**This closes an underspecification in HP1, not a deviation from it.** Property 1 says the
weights are a build-time artifact trained on benchmark gold evidence, and that stands unchanged.
What it does not say is what the fitted gate is then *reported against* — and M0b Session B, the
first session to actually fit one, could not proceed without an answer.

Read literally, the omission licenses fitting on all 500 LongMemEval-S cases and reporting
evidence precision on the same 500. That is train-on-test. The isotonic curve has enough freedom
to memorize the score distribution it was fit on, so the reported number would be optimistically
biased by an unknown amount — and "unknown" is the problem, since the bias cannot be subtracted
out or bounded from the number itself.

**Decision.** The corpus is split before any fitting, by a rule fixed in advance:

| | |
|---|---|
| Rule | Within each harness category, sort `query_id`s by `(sha256(query_id), query_id)`; even indices to `fit`, odd to `heldout` |
| Stratification | Per category, so all seven are split within one case — not merely random assignment that happens to balance |
| Recorded in | `tools/split.json`, with the corpus digest and its own content digest |
| Enforced by | `tools/fit_gate.py`, which refuses to run without that file and refuses if either digest disagrees |
| Copied into | the gate artifact, so a gate and the split it was fit under travel together |

**The held-out figure is the headline everywhere it appears.** The all-cases figure is still
reported — it is the one comparable to a published 500-case number — but its contamination is
attached to the value itself, the same treatment `corpus_variant` already gets, and there is no
place in the output where it appears bare. A contaminated number sitting beside a clean one with
the caveat in surrounding prose will be quoted without the prose.

**Cost accepted.** The headline is computed over ~250 cases rather than 500, so its confidence
interval is wider, and it is not directly comparable to a vendor's 500-case figure. That is the
right trade: a wider interval around an honest number beats a tight one around a biased one.

**A related hazard, recorded because it generalizes — and because the first fit found two
different versions of it.** A coefficient can be meaningless in two ways, and only one of them
is detectable by looking at the fit data:

| | Detected by | Example | Why the weight is meaningless |
|---|---|---|---|
| **No variance** | the fitter, automatically | `effective_trust`, `fidelity` — constant across LongMemEval, since every turn is terminal-origin and no demotion has run | fit on noise; becomes load-bearing the moment the feature starts varying |
| **Varies, but is collinear and will change meaning** | nobody — it must be **declared** | `cue_agreement` — with one cue it is exactly `1[lexical_bm25 > 0]` | the split between its weight and the cue's cannot change any ranking, and its semantics change from a 0/1 indicator to a 0..2 count when cue 2 lands |

The second is the dangerous one precisely because a variance check passes it. The first fit did
hand `cue_agreement` a weight of 4.998, which looked like a finding and was an artifact of
collinearity; re-fitting with it pinned produced a **bit-identical isotonic curve** (230 blocks,
same maximum) with the bias absorbing the difference, which is the evidence that the pin was free.

Both kinds are therefore **pinned to zero in the artifact, with the reason stored per feature,
and the pin is enforced at load time.** This is not a comment: `FrozenGate::load` rejects a pinned
weight that is not zero. **Refit deliberately when the cue set changes** — a pin is a statement
about the current cue set, not a permanent property of the feature.

---

## HP2 · Cross-session identity

**Context.** When is "the API" in session 47 the same entity as in session 3? Resolution
failures cascade through every graph-based memory system.

**Decision.** Identity is a **belief, not a lookup.** Sameness is an `Edge { rel: SameAs }`
memory entry with confidence and provenance, produced by consolidation and correctable in plain
speech. Blocking on normalized surface form and channel address; scoring on embedding
similarity, co-occurrence, temporal contiguity, and handle match. Below threshold the system
keeps **two** entities and traverses `SameAs` at query time — a cheap one-hop union.

Asymmetry, mirroring the trust ledger: merges are proposed, recorded, and reversible by
supersession; splits are automatic on contradiction.

**Rejected.** Eager global entity resolution at write time (Graphiti-style). A wrong merge is
effectively unrecoverable and contaminates every subsequent graph query.

**Cost accepted.** Recall loss on under-merged entities. Deliberate: under-merging costs recall,
which `recall` recovers; over-merging costs *precision* and, when the entities are two people,
leaks one person's data into another's context. The asymmetry of harm sets the direction.

---

## HP3 · Temporal abstraction at scale

**Context.** "The user has been getting steadily more frustrated with this project over six
weeks" is a fact no single episode contains and no summarizer will surface.

**Decision.** Trends are **derived beliefs over windows**, computed by consolidation and stored
as `Fact` payloads carrying an explicit window, slope, and fit quality. A fixed set of
extractors runs over sliding 7/30/90-day windows on signals the harness already logs: sentiment
per session, correction rate, task abandonment, response latency, contact-cadence drift per
relationship. A `Trend` fact is emitted when |slope| clears a threshold and fit is adequate.

**Rejected.** Asking a summarizer to notice trends. No single episode contains one, and
summarizing a window is both expensive and unreliable at detecting monotone drift.

**Cost accepted, and it is a real limit.** Only trends over **pre-declared signals** are
detectable. A trend in something we do not measure is invisible, and no amount of model quality
fixes that.

**Partially unsolved.** *Which* signals matter is empirical. **Experiment:** instrument the full
signal set from M0b; at M5, correlate detected trends against user-confirmed ones and prune the
extractors that never confirm.

---

## HP4 · Staleness

**Context.** How does the system know a fact has expired without being told? Confidence decay is
a proxy, not an answer.

**Decision.** Three detectors, no one of which is decay alone:

1. **Contradiction at retrieval** (reconsolidation, §5.3). When two candidates for the same
   (entity, relation) disagree, resolve at retrieval time on recency and source trust. The loser
   is superseded then and there, not left to rot.
2. **Typed volatility priors.** Stability is a property of the relation, not a global constant.
   An employer changes on a ~2-year scale, a birthday never, a current sprint weekly. Confidence
   decays at its class's rate.
3. **Observation beats memory.** A harness-observed (`AgentObserved`) fact contradicting a
   stored belief supersedes it immediately and unconditionally.

**Rejected.** A single global decay half-life. It is simultaneously too fast for stable facts and
too slow for volatile ones, which is the worst of both.

**Cost accepted.** This is a proxy stack, not a solution.

**Genuinely unsolved.** *Silent* staleness — a fact that expired with no contradicting
observation ever arriving — is undetected by all three. **Experiment:** staleness half-life is a
first-class measured metric in M0a, reported on LongMemEval's knowledge-update category. If it
measures poorly, the fallback is to *ask* occasionally rather than to pretend, and the cost of
asking is bounded by the same interruption budget as noticing.

---

## HP5 · The consolidation failure taxonomy

**Context.** Consolidation introduces its own errors. Which are accepted, which detected, how?

| Failure | Stance | Mechanism |
|---|---|---|
| **Detail loss** | **Accept** | It is the point. The journal retains availability; only accessibility is reduced. |
| **Temporal compression** | **Detect** | A merged belief records the `Seq` range it covers. A belief whose derivation spans a wider range than its claimed window is flagged. |
| **Over-eager merging** | **Detect + reverse** | Merges are `supersedes` edges and are therefore undoable. Merge requires entity agreement above threshold and no contradicting `SameAs`. |
| **Wrong side of a contradiction** | **Detect, then refuse** | When confidence delta falls inside a band, **do not resolve.** Keep both, mark contested, and let retrieval abstain or surface the conflict. |

Consolidation is itself an episodic event: what it merged and what it discarded is journaled,
which is what makes the memory system auditable and debuggable (§5.3).

**Rejected.** Always resolving contradictions. A confidently-wrong resolution is worse than a
visible conflict, because the conflict is recoverable and the resolution is not.

**Cost accepted.** Contested beliefs are held back from injection, reducing recall.

---

## HP6 · Memory laundering

**Context.** Untrusted content transformed through several LLM derivations into an
authentic-looking agent-written memory. Content signals and coarse taint tracking are
structurally insufficient.

**Decision.** Three mechanisms, all structural:

1. **Worst-case trust propagation over the full lineage** (`CONTRACTS.md` §3.3), computed at
   write time. No content signal is consulted, because content signals cannot survive
   derivation.
2. **The `(action, target)` split.** Untrusted-derived content may shape inert *payload* fields
   freely — a draft body, a summary — and may never shape *targets*: tool selection, recipient,
   path, host, amount, identifier. The dangerous thing is not the text; it is the pair.
3. **Default-deny at load time.** An undeclared or malformed manifest is a startup error, not a
   call-time warning. Third-party tools cannot self-declare low consequence.

**Rejected.** Content-based filtering and message-level quarantine. Both are demonstrably
defeated by laundering through derivation.

**Cost accepted.** Untrusted-derived beliefs can never target a consequential action *even when
correct*. Some legitimate work is blocked. The escape hatch is a blocking approval that displays
the provenance chain — deliberately not frictionless, because frictionless is how the CVE-class
failures happened.

---

## HP7 · The 15× cost problem

**Context.** Deep research quality tracks token spend almost linearly. How does the user control
that dial without understanding it?

**Decision.** **Effort is a property of the ask, not a setting.** The orchestrator sizes the
investigation from assessed complexity, and the only user-facing control is a per-run ceiling in
money and wall-clock, defaulted, and stated in the same breath as the plan: *"About twenty
minutes and roughly $3 — go?"* Caps are harness-enforced; hitting one pauses and asks.

**Rejected.** A depth slider — users cannot calibrate an abstract effort scale. And silent
auto-scaling — a surprise 15× bill destroys trust permanently.

**Cost accepted.** An explicit confirmation on expensive runs, which is friction on exactly the
runs the user most wants to fire and forget. Justified by §10.2: a 15× multiplier is acceptable
when disclosed and controllable, not as a surprise.

---

## HP8 · Approval fatigue

**Context.** Users click through prompts within a day. What keeps approval meaningful in week
ten?

**Decision.** Three mechanisms, none of which is "write better prompts":

1. **Risk tiering so most actions never prompt.** Approval scarcity is what preserves meaning;
   a prompt on every action is a prompt on none.
2. **Rubber-stamping is measured** (§B9): approval latency and approve-without-expand rate,
   per class. When the user is clicking through, the system says so and proposes either
   promoting the class (stop asking) or tightening it.
3. **Novelty gating**, so the prompts that do fire skew toward the genuinely unusual.

**Rejected.** Escalating prominence — bigger warnings, more friction. Habituation defeats
salience; the answer is fewer prompts, not louder ones.

**Cost accepted.** Measuring rubber-stamping means measuring the user. Disclosed in `/trust`
rather than hidden.

---

## HP9 · Voice and deep work

**Context.** A voice turn runs at 800 ms; a research task runs ten minutes. How do they coexist
in one session model without blocking or fragmenting?

**Decision.** **Runs are decoupled from sessions.** A session is a conversation identity; a run
is a unit of work. A voice turn is a short run, research is a long run, and they share one
session. The voice path never blocks on a run: long work is announced, handed to a background
run, and notified on completion.

**Rejected.** A separate async mode — that is a second loop wearing a costume, and §4 forbids it.

**Cost accepted.** The voice user must tolerate *"I'll ping you."* Some users dislike it. Holding
a voice channel open through a ten-minute task is worse on every axis.

---

## HP10 · Simplicity under accumulation

**Context.** Every requirement adds surface. What is the *mechanism* — not the intention — that
keeps this from becoming another framework in eighteen months?

**Decision.** Four **executable budget tests that fail the build**:

| Test | Enforcement |
|---|---|
| Model-visible tools ≤ 12 | `ExposedSet` constructor asserts; a test enumerates every capability profile |
| User-facing nouns ≤ 7 | A test greps CLI help, the slash-command table, and `/status` against an allowlist |
| Agent loops == 1 | A test fails if a second driving loop appears in the loop crate |
| Zero-config first run | A test runs install → first useful output in a clean container with no config file |

Plus a process rule: every new user-facing concept must delete one, and the PR template asks
which.

**Rejected.** Architectural review as the mechanism. Intentions do not survive eighteen months
and a contributor rotation; a failing build does.

**Cost accepted.** These tests are crude — noun-grepping especially will produce false positives
and require an allowlist that itself needs maintenance. A crude enforced mechanism beats an
elegant unenforced one.

---

## HP11 · Proactive precision without labels (cold start)

**Context.** §A5 requires ≥0.80 precision on unprompted surfacing with no training data at
install, and ≤5 interruptions per day.

**Decision.** **Week one has no judgment-based proactive surfacing at all.** Noticing classes
enter at tier 0 (Observe — records, surfaces nothing) and promote individually on the standard
evidence ramp, seeded by the user's dismissals. Per-class precision is tracked and classes that
consistently miss are suppressed.

The cold-start bootstrap is that **some noticing classes are deterministic, not learned**:

| Ships on at day one (facts) | Starts in shadow (judgment) |
|---|---|
| **Conflict** — a calendar collision is a fact | **Drift** — "your norm is two weeks" |
| **Approach** — a renewal date is a fact | **Pattern break** — "you've moved this four times" |
| **Silence** — an unanswered ask past its SLA is a fact | **Anomaly** — "this invoice is 3× usual" |
| **Preparation** — who you're meeting and what you promised | |

**Rejected.** Shipping all classes on at a conservative global threshold. One system-wide
threshold cannot serve both a calendar collision and a tone-drift inference, and being wrong
five times in week one is how users disable noticing permanently.

**Cost accepted.** The *impressive* noticings arrive last. Week one is useful but not uncanny —
which is the honest trade, since the alternative risks never reaching week ten.

---

## HP12 · Voice without impersonation harm

**Context.** How faithfully should the system imitate a person, and what prevents an assistant
that is too convincing from becoming a liability?

**Decision.** Fidelity is bounded **by channel and permission, not by quality**. Matching
register, length, greeting and sign-off conventions, and vocabulary is permitted. Two hard
lines:

1. **Sending as the user is a distinct permission from sending as the assistant.** Off by
   default, granted per channel, with a **hard ceiling in the trust ledger that no amount of
   evidence lifts.** Some lines are chosen, not earned.
2. **Attribution never lies.** Asked directly whether it is an AI — any channel, any tier — the
   answer is yes. This is not a sentence in a system prompt. It is an action class whose only
   permitted response is truthful and which cannot be tier-promoted, so no autonomy setting can
   route around it.

**Rejected.** Capping voice-match quality as the safety mechanism. It degrades the product
without addressing the harm, which comes from *unattributed* action, not from good prose.

**Cost accepted.** The assistant is occasionally less smooth than perfect impersonation would
be, and the user must grant an explicit per-channel permission to send under their own name.

---

## HP13 · Multi-party etiquette

**Context.** When the assistant is CC'd on a thread, what are its manners?

**Decision.** A declared, inspectable policy — not a vibe:

- **Speaks** when it holds the action (scheduling, chasing, confirming) or is directly addressed.
- **Stays silent** on threads where its principal replied within the last turn.
- **Checks first** before: first contact with a new counterparty, anything touching money or
  commitments, and anything the principal has not seen.
- **Identifies itself** in its first message on any thread.
- **Never speaks as the principal** in a multi-party thread. Having its own address is what
  makes that unnecessary.

**Rejected.** Letting the model infer etiquette per thread. Third-party-visible behaviour is
exactly where an inference failure is least recoverable.

**Cost accepted.** Occasionally silent when it could have helped. Erring toward silence in front
of third parties is the right asymmetry, because that embarrassment is externalized onto the
principal.

---

## HP14 · The complacency-competence tension

**Context.** The more reliable a system appears, the less vigilant its overseers become — and
this is worse in high-performing systems than mediocre ones.

**Decision.** Four mechanisms: **verification sampling** at a rate that scales with consequence
*and* with time-since-last-review (not a flat rate); **drift detection** that demotes before the
user complains; **novelty gating**; and — the one the requirements do not name — **failures
shown as prominently as successes** in the dashboard (§A9.3), so the user's mental model is
calibrated by what they see rather than by what they remember.

**Rejected.** Flat-rate sampling. It is predictable, and predictable review is skimmed review.

**Cost accepted.** Sampling deliberately spends user attention on actions that were probably
fine.

**Partially unsolved, and stated as such.** Human-factors research does not support the claim
that complacency is designable-away.

**Experiment.** At M6, inject known-bad actions into the verification sample stream for a
consenting cohort and measure catch rate against a control that receives no samples.

**Falsification condition — declared before the experiment runs, per the pre-registration rule
in ADR-003.** Verification sampling is **theatre** if any of these holds:

| Result | Reading |
|---|---|
| Sampled-cohort catch rate is within noise of control (≤5 pp absolute, at the cohort's power) | Sampling does not create vigilance; it creates the *feeling* of vigilance, which is worse than nothing because it licenses higher tiers. |
| Catch rate is above control initially but decays to control within 30 days | Habituation defeats it on the timescale that matters. A mechanism that works for a month and then silently stops is the most dangerous outcome. |
| Catch rate improves but review latency collapses (median review time falls below a plausible reading time) | Users are clearing samples, not reviewing them — the same rubber-stamping failure the mechanism exists to prevent. |

**Replacement if falsified — decided now so the failure has somewhere to go.** Verification
sampling is removed rather than tuned, and tier ≥4 classes get **hard periodic re-consent**: the
tier expires on a consequence-scaled interval and returns to Confirm until the user re-grants it
against fresh evidence. This is worse UX and is chosen deliberately — an expiring grant does not
depend on the user being vigilant, only on their being present, and presence is observable while
vigilance is not.

Note what this trades: re-consent converts a continuous oversight claim into a discrete one. We
would stop asserting that the user is watching and assert only that they periodically re-decide.
That is a weaker claim, and if the experiment falsifies sampling it is the true one.

---

## HP15 · Commitment extraction precision

**Context.** "I'll take a look" is not a commitment. "I'll send it Thursday" is. "Let me get
back to you" is ambiguous. Where is the line and what happens at it?

**Decision.** The line is *whether a disinterested third party would say you promised*.
Extraction emits a confidence, and **status is gated by the band**:

| Band | Example | Behaviour |
|---|---|---|
| **High** — explicit object + explicit time | "I'll send the pricing sheet Thursday" | Open commitment, chase policy active |
| **Mid** — intent without object or time | "Let me get back to you" | Open, appears in the open-loop list, **never chased autonomously**; chaseable on one tap |
| **Low** — acknowledgement only | "I'll take a look" | Not a commitment. Recorded as an episode. |

The mid band is the mechanism: it lets extraction recall stay ≥90% (§A12) without the chase
policy firing on ambiguity, which is what would produce false closures and awkward chases.

**Rejected.** A single threshold. It forces a choice between missing real commitments and
chasing imagined ones, and both failures are visible to third parties.

**Cost accepted.** The open-loop list carries noise in the mid band.

**Freeze status, per HP1's rule — not self-granted.** Two components here, and they are treated
differently:

- **The band classifier** — what assigns high/mid/low to an utterance — is **frozen in M0**. It
  determines what enters the commitment index and is therefore on the measured path.
- **Per-phrasing mid-band handling** adapts, narrowly: an explicit user dismissal of a specific
  open-loop item records a decision ("this user does not treat *let me get back to you* as a
  commitment"), which is a recorded decision under HP1 condition 2.

The distinction is load-bearing: recording dismissals as **rules** is permitted; training a
classifier on dismissal-as-negative-label is an inferred reward and waits for M10. If an
implementation finds itself fitting weights to dismissals, it has crossed the line.

---

## HP16 · The self-hosting split

**Context.** A managed auth broker is the right engineering answer and the wrong answer for the
most trust-sensitive users.

**Decision.** **Ship both**, behind one `Broker` trait: a managed adapter (Nango / Composio /
Arcade class) and a local keychain broker.

**What breaks, stated plainly.** The local path supports far fewer apps — those with device-code
OAuth, app passwords, or plain API keys — and receives no token-refresh maintenance across
hundreds of providers. The product must state which apps are available on the local path
**before** the user chooses, not after they have committed.

**Rejected.** Managed-only (unacceptable for the highest-trust install a person makes, and it
violates §15's no-cloud-dependency-for-core-function) and local-only (connector maintenance is a
permanent tax with zero differentiation, per §A2.1).

**Cost accepted.** Two code paths and a disclosed capability difference at onboarding.

---

# Part 2 — Infrastructure

## ADR-001 · Language and runtime: Rust

**Context.** Single-binary install, useful on a $5 VPS, <150 ms first frame, kernel-enforced
sandboxing, local embeddings, durable runs.

**Decision.** Rust for daemon, client, and TUI — `tokio`, `rusqlite`, `ratatui`, `ort` (ONNX
Runtime). Python only for the M0a eval harness, which is a separate artifact.

**Rejected.** *Go* — genuinely competitive (single binary, fast start, Bubble Tea is good) but a
weaker local-inference story and less control over allocation for the frame budget.
*TypeScript/Node* — the best MCP ecosystem, the worst startup and memory profile for a $5 VPS.
*Python for the core* — cannot meet the frame budget or the single-binary requirement.

**Cost accepted.** Implementation cost is materially higher and the contributor pool is smaller.
Mitigated by skills being subprocess-executed in any language, so the extension surface is not
Rust-bound.

## ADR-002 · Process model: thin client + daemon, one binary, two roles

**Decision.** `marlowe` (client) and `marlowe --serve` (daemon), same binary. The daemon owns
journal, indexes, runs, triggers, gateway, voice. Client holds no run state and auto-spawns the
daemon. One daemon per profile. Local socket transport.

Forced by invariant 6 — if the client owned the run, closing the terminal would end it. It also
buys the 150 ms first frame, since the client has almost nothing to initialize.

### Execution model — revised 2026-08-02

> **This revision supersedes the original sandbox-by-default position and the WSL2 development
> rule.** Brief **§8.2 was amended in the same change** rather than left to contradict this ADR —
> a requirement and an ADR that disagree get reconciled by whoever reads them next, and that is
> not a decision to leave to a default six months out. The brief now carries the divergence and
> its cost at the point where it states the claim; this ADR carries the engineering detail.

**Decision. Marlowe runs on the user's real filesystem by default.** No kernel sandbox on the
ordinary path.

The reason is the product, not the platform: Marlowe is a secretary. A secretary that cannot
reach your files is useless. An assistant that can only see a copied-in subset of your work is
one you have to feed, and feeding it is the work. Claude Code reaches the real filesystem for
the same reason, and it is the right call.

**What replaces kernel sandboxing is not nothing.** It is the layer this design already
specifies, and every part of it is platform-independent and native on Windows:

| Mechanism | Where it is pinned | What it stops |
|---|---|---|
| Declared paths and hosts in the capability manifest, default-deny at load time | `CONTRACTS.md` §7.3 | A tool touching anything it did not declare |
| The `(action, target)` split | §9, HP6 | Untrusted content choosing a recipient, path, host, amount, or identifier |
| Worst-case trust propagation over full lineage | §3.3, HP6 | Laundering — untrusted content acquiring authority through derivation |
| Egress allowlisting, deny-by-default | §5 `CapabilityProfile` | Exfiltration, the third leg of the trifecta |
| Risk-tiered approval with blast radius | §9, HP8 | Consequential actions happening unseen |

**Sandboxing is retained, scoped to one profile.** The quarantined reader —
`reads_untrusted: true`, `exposed_tools` empty — keeps a sandbox backend. That is §8.2's
structural trifecta break, and `CONTRACTS.md` §5 already makes
`reads_untrusted && !exposed_tools.is_empty()` a load-time error. It is a small, isolated
component with no interactive path, so a container backend covers it on Windows without the
override-erosion problem that killed the general case.

**Development happens on native Windows.** No WSL2 move. The original argument for WSL2 was that
a sandbox default erodes when its override becomes a daily convenience — with no sandbox default
on the ordinary path, there is no override, and the argument no longer applies. Linux and macOS
remain first-class deployment targets and the $5 VPS target is unchanged; CI is where
cross-platform divergence gets caught, not the developer's desk.

**Cost accepted, and it is the real one: a permission-layer bug has no kernel backstop.** Under
the original design, a defect in path handling or argument provenance was contained by the
kernel — the sandbox was a second wall behind a first. It is now the only wall on the ordinary
path. **The permission layer therefore carries materially more weight than it was designed to
carry**, and three things follow that are not optional:

1. **It is the highest-value target in the system for review and testing.** §8.3's AgentDojo-style
   suite stops being a check on defence-in-depth and becomes the primary evidence that
   containment works at all. ASR there is now a first-order number.
2. **The red-team classes in §8.3 gain weight** — particularly sandbox-boundary redefinition via
   agent output, which is why §9 checks `Reversible` tools and not only `Consequential` ones. A
   workspace write is a durable channel into a later run's context, and there is no longer a
   kernel boundary underneath that check.
3. **`Inert` reads stay unchecked on targets, and that is now a narrower call than it was.** The
   containment for reads is that fetched content returns `UntrustedContent`, returns by
   reference, and cannot reach a Target downstream — three mechanisms, none of them the kernel.
   If any one of them weakens, this exemption must be revisited.

#### Path scoping is a security boundary, not a convenience

Under the original design, `paths: ["./out/**"]` in a capability manifest was a declaration the
kernel would have enforced anyway. It is now the enforcement. **A path check that can be defeated
by string manipulation is the whole protection gone** — there is nothing behind it.

**AMENDED 2026-08-08, at the close of M2 Session B.** The original wording is kept, because a
future session must be able to see what was strengthened and why.

> **Original — SUPERSEDED. An implementation that satisfies this wording exactly is still
> vulnerable: it produces a resolved path, compares it, and then opens it, and a link planted
> between the comparison and the open defeats it. Do not implement to this paragraph. The binding
> rule is the amended one below.**
>
> *"Canonicalize first, then check. Never check, then canonicalize. Every comparison happens on the
> fully resolved path: symlinks and reparse points followed, relative segments collapsed, case
> folded on case-insensitive volumes, extended-length and UNC forms normalized. A check performed
> against the string the model supplied is a check against an attacker-chosen encoding of a path,
> not against the path."*

**The amended rule: the hostile string is never canonicalized at all.**

The original is right about the ordering and wrong about what it permits. It describes a resolved
path being produced and then compared — and **an implementation doing exactly that complies with
every word of it and is still defeated by a link planted between the comparison and the open.** The
resolved string is a value that exists, is trusted, and can go stale. The wording admits the very
window the paragraph below it was added to close, so a session implementing to its letter could ship
a check-then-open resolver and believe it had complied.

The rule is therefore stated as the property, not the ordering:

> **No resolved path string is ever produced for the purpose of being trusted.** A requested path is
> (1) refused if its *spelling* is ambiguous — `..`, rooted, UNC, extended-length, device,
> drive-relative, alternate data stream, reserved device name, 8.3 short name, munged trailing dot
> or space, homoglyph separator; (2) matched against the manifest's declared globs as a relative
> string, before any syscall; and (3) **walked open one component at a time**, with the kernel
> resolving each component under supervision and the handle retained. There is no step in which a
> canonical path is computed and then relied upon.
>
> The only normalization applied to a path is Unicode NFC, applied to **both sides of one
> comparison** and to nothing used afterwards. Every other ambiguous form is refused rather than
> normalized: a normalizer must be right about every encoding, a refusal about one thing.

Concretely: `openat` with `O_NOFOLLOW` per component on POSIX; on Windows, every directory on the
path pinned open with a share mode excluding `FILE_SHARE_DELETE`, each component opened with
`FILE_FLAG_OPEN_REPARSE_POINT` and refused on `FILE_ATTRIBUTE_REPARSE_POINT`, and the root's identity
verified before and after. **ADR-027** carries the implementation, its measured gaps, and the test
that defeats a check-then-open reference implementation on purpose.

**Nothing is relaxed.** The original's intent — never compare against the string the model supplied —
is preserved and strengthened; what is removed is the implicit permission to hold a resolved path and
trust it.

**M2 acceptance gains a path-traversal suite.** Not a smoke test — an adversarial one, covering
at minimum:

| Class | Examples |
|---|---|
| Relative traversal | `../`, `..\`, doubled and interleaved separators, over-long `../` chains |
| Symlinks and junctions | POSIX symlinks, Windows directory junctions and reparse points, links planted *inside* a declared path that resolve outside it |
| Windows path forms | `\\?\` extended-length, `\\.\` device, UNC `\\server\share`, drive-relative `C:foo` |
| 8.3 short names | `PROGRA~1` and generated short names aliasing a long-named directory |
| Case collisions | `C:\Users\X` vs `c:\users\x`; case-sensitive checks on a case-insensitive volume |
| Win32 name munging | Trailing dots and spaces silently stripped, reserved device names (`CON`, `NUL`, `COM1`) |
| Alternate data streams | `allowed.txt:hidden`, `dir::$INDEX_ALLOCATION` |
| Unicode | Normalization forms, homoglyphs, and overlong UTF-8 encodings of separators |

**One addition to that list, because canonicalization alone does not close it: the check-then-use
race.** Canonicalizing and then opening by path leaves a window in which the resolved path can be
swapped — a symlink planted between the check and the open. The check is correct and the open
still lands outside the scope. Closing it means operating on a handle rather than re-resolving a
string: `openat`/`O_NOFOLLOW` on POSIX, and on Windows opening with reparse-point semantics made
explicit and verifying the final handle's identity. Worth pinning at M2 alongside the suite,
because a traversal suite that passes against a TOCTOU-vulnerable implementation reports a
boundary that is not there.

**Requirement, not a nicety: first-run onboarding states plainly what Marlowe can reach.** In
plain language, before the first action — which directories, which hosts, what it will ask before
doing versus do silently. A user who does not know the blast radius cannot consent to it, and
"it runs on your real filesystem" is exactly the fact that must not be discovered later. This is
an M2 acceptance item (the zero-config first run must not become a zero-disclosure first run).

**Rejected.** Sandbox-on-by-default with a loud override (the original position): on Windows it
degrades to "refuse to run without a container", which for a secretary means refuse to run. And
the override, used daily, stops reading as a warning inside a week — the erosion argument was
right, which is why the answer is to remove the default rather than to keep a default nobody
exercises.

**Consequence for M1.** The §B13 suite must still run on native Windows Terminal *and* on a Linux
terminal emulator. The direction of the gap has inverted — development is now on Windows, so
**Linux is the surface at risk of being verified only in CI** — but the requirement is symmetric
and unchanged.

## ADR-003 · Storage substrate: one journal, one live-only hot index

**Context.** The plan pre-committed to pinning the single-journal design only if it measured.
See `docs/design/spike-2026-08-01.md` for the full method and raw table.

**Decision. Single append-only journal**; memory, runs, sessions, lineage, and audit are
materialized views over it. **The split (live-only) hot index is a requirement, not an
optimization** — it is what makes the single journal viable.

**The measured curve, at 100k live memories, 1 pinned vCPU, concurrent durable writes:**

| tombstone fraction | naive P95 | split P95 |
|---|---|---|
| 0.00 | 106.2 ms | 16.7 ms |
| 0.20 | 101.6 ms | 18.1 ms |
| **0.30 (nominal)** | **94.9 ms** | **16.2 ms** |
| 0.40 | 113.9 ms | 18.6 ms |
| 0.60 | 143.6 ms | 18.7 ms |
| 0.80 | 258.4 ms | 23.3 ms |

Auto-injection reads an index containing only injectable entries; tombstones and superseded
entries never enter it, reaching only the explicit `recall` tool and the abstention check.
**An unpartitioned index crosses the 120 ms storage budget at f ≈ 0.45 and reaches 258 ms by
f = 0.80. The partitioned index is flat across the entire range** because its cost is bounded by
the live set, not the total. Note f = 0.00 already carries 3.0× over-fetch: with chain depth 3,
two-thirds of rows are superseded before a single tombstone exists — supersession, not
forgetting, is what makes an unpartitioned index expensive.

**The nominal operating point (tombstone fraction 0.30, chain depth 3) is PRE-REGISTERED for
decidability, not derived.** It is a decision procedure fixed before the run, not a measured
property of any real workload. **The curve is the artifact.** A later session must not inherit
0.30 as if it were measured.

**Other gates at nominal, all passed:**

| Measurement | Result | Gate |
|---|---|---|
| Sustained durable append | 633.2/s | ≥50/s |
| Full index rebuild (replaying fidelity + supersession events) | 11.7 s | ≤10 min |
| **Rebuild correctness — exact per-entry fidelity** | **exact match, 0 mismatches** | exact |
| Page bloat vs. compacted | 1.091× | report |

**The append number travels with its caveat, never alone.** 633/s was measured on workstation
NVMe with fsync p50 = 1.14 ms / p95 = 2.12 ms. **VPS shared storage is typically 5–20× slower**,
which puts the same workload at roughly 175/s (5×) down to ~44/s (20×) — *at or below the 50/s
gate at the pessimistic end.* Mitigation, and it is a design requirement rather than a
contingency: **group commit** — batch N events per fsync — which restores an order of magnitude
and is standard for append-only logs.

**Scaling ceiling (Tier C), and it changes an M0b requirement.** The Tier B sweep held the live
set constant and grew only the dead set. Sweeping the *live* set at nominal shape:

| live set | vec MB (f32) | P95 |
|---|---|---|
| 100k | 154 | 22.6 ms |
| 250k | 384 | 57.3 ms |
| 500k | 768 | 96.0 ms |
| 1M | 1,536 | 264.7 ms |

Two ceilings, and **RAM binds before latency**:

- **RAM.** Float32 vectors at 500k live are 768 MB, which does not fit a 1 GB VPS beside the
  daemon and page cache. With ~600 MB available the float32 ceiling is ≈390k vectors.
  **int8 quantization** at 384 B/vector (4× smaller; 384 MB at 1M live) lifts that ceiling to
  ≈1.56M.
- **Latency.** Brute-force scan crosses the 120 ms storage budget between 500k and 1M live —
  interpolating, ≈600k.

**Therefore: ANN indexing is an M0b requirement, not a later optimization**, together with int8
quantization of the hot vector array. Brute force is acceptable only below ~250k live memories,
which a multi-year heavy user will exceed.

**ANN is accepted on recall, not on latency.** The 120 ms storage budget above was derived under
**brute-force (exact) assumptions**, so latency alone cannot accept an approximate index. An ANN
index that is fast and silently drops true neighbours passes the latency gate and fails K1 — and
the failure would present as a retrieval-*quality* problem, sending investigation to the cues,
the router, or the gate, none of which are at fault. That misdiagnosis is the expensive part.

Acceptance therefore requires **recall@k measured against brute-force ground truth on the same
corpus**:

| Measurement | Target |
|---|---|
| ANN recall@50 vs. exact search, at each Tier-C size point | ≥0.99 |
| Reported alongside | the latency that recall was achieved at |

Two implementation consequences, both binding:

- **M0b retains an exact search path permanently**, as validation ground truth. It is not
  scaffolding to be deleted once ANN works.
- **This is a standing test, not a tuning step.** ANN recall degrades as the index grows and as
  parameters drift, so it runs at every size point on every change to the index, the embedder,
  or the quantization.

Quantization sits inside the same gate: int8 is accepted only if recall@50 against *unquantized
exact* search clears the same floor. A recall loss from quantization is indistinguishable
downstream from a recall loss from the index, so both are measured against the same ground
truth.

**Rejected.** A shared event-log substrate with separate materialized stores — the pre-committed
fallback had either gate failed. Not taken, because both passed.

**Cost accepted.** One hot substrate serves retrieval, rendering, and writes, so schema evolution
touches every subsystem at once. The mitigation is that every index is rebuildable from the log,
which makes migration a rebuild rather than a data migration — bounded at 11.7 s.

**Forgetting, and the honest qualification.** Graduated fidelity is a property of the retrieval
index, not of storage: the log preserves **availability**, forgetting removes **accessibility**.
That split is the reason this design holds and is not a convenient reframing — it is what lets
§5.4's ladder and the append-only log coexist without contradiction. Two things nonetheless
write outside the append-only model and are named rather than absorbed:

- **Blob eviction** — content-addressed, evictable, leaving hash + typed summary + tombstone.
- **Privacy redaction** — destructive and audited, because a logical tombstone is not a delete
  when the user asked for a delete. **Crypto-shredding key granularity is per-`(profile,
  person)` at minimum**, with per-record DEKs wrapped once per subject, so deleting one contact
  never forces shredding a scope that takes others with it. **Accepted limitation:** a
  multi-subject record survives until its last subject wrap is destroyed, so deleting person A
  does not remove A's contribution from a record also keyed to B.

## ADR-004 · Embedding strategy

**Decision.** Local ONNX small model, 384 dimensions, **int8-quantized in the hot array** (see
ADR-003). Optional API embedder for users who prefer it, behind the same interface. Skills embed
**description + trigger phrases only** — never full instruction prose, which pollutes the vector
space (§7.1).

**Rejected.** API-only embedding — it breaks the offline path and puts a network round-trip
inside a 300 ms budget. Large local models — they do not fit the VPS target.

**Cost accepted.** A small local embedder is weaker than a frontier API embedder. Precision is
bought by the gate, not by the embedder, so this is the right place to economize — but if M0b
misses on recall rather than precision, the embedder is the first thing to revisit.

### Amended 2026-08-04 (M0b Session C) — the runtime and the model are now named

ADR-004 said "local ONNX small model, 384 dimensions" and named **neither an inference engine nor
a model**. Both gaps are load-bearing, because `marlowe-eval repro` hashes the injected set byte
for byte: anything that can change an embedding can move a published number. Both are now closed
by measurement, and the measurements are in
`docs/design/spike-2026-08-04-embedder.md`, `runs/session-c/embedder-comparison.json` and
`runs/session-c/PREREGISTRATION-model.json`.

**Runtime: `ort` 2.0.0-rc.10, threads pinned to 1, `GraphOptimizationLevel::Level1`.**

Chosen by a gate pre-committed before either engine was built (≥25 texts/s/core, ≤120 ms
retrieval P95, loads the pinned file, byte-identical across calls / spawns / worker counts).
tract 0.23.4 passed every gate except throughput — 21.8/s/core against 25, missing by 13% — and
the rule selected ort. **The gate was not revisited after seeing 21.8.** Both engines were fully
deterministic; throughput was the only separator.

The FTS5 hazard this was written against turns out to be substantially mitigated: `ort-sys`
pins **ONNX Runtime 1.22.0 by SHA256 per target** in its `dist.txt` and links it statically, so
the chain from `Cargo.lock` to the machine code computing an embedding is digest-pinned end to
end. That is unlike FTS5, where the ranking function rode on whatever SQLite the build bundled
with nothing recording it.

*Quantified, because it stopped being hypothetical:* the same graph under ONNX Runtime 1.22.0
(Rust) and 1.24.2 (Python) differs by **2.75e-6 max abs**. Small, non-zero, and exactly why the
version is pinned rather than tracked.

*Costs accepted:* ort has **no stable release** — 2.0.0-rc.13 is newest and there has never been
a 2.0.0, so it is pinned with `=`. Determinism is measured rather than structural (tract has no
thread pool; ort has one, pinned to 1), so the standing test is the mitigation, not the config.
Cross-hardware bit-identity is not claimed by either engine and no tolerance window is introduced
to pretend otherwise. Binary size ~46 MB.

**Model: `jinaai/jina-embeddings-v2-small-en`, 512 dimensions, 8192-token ALiBi window.**
Not all-MiniLM-L6-v2, and **not 384 dimensions**.

Measured on 42 fit-split cases (held-out untouched), gold-turn recall@k under pure cosine — no
gate, no fitted weights:

| config | dim | turns truncated | texts/s/core | R@1 | R@10 | R@20 |
|---|---|---|---|---|---|---|
| all-MiniLM-L6-v2, truncate 128 | 384 | 46% | — | 0.314 | 0.869 | 0.913 |
| all-MiniLM-L6-v2, truncate 256 | 384 | 34% | 46.7 | 0.345 | 0.833 | 0.913 |
| all-MiniLM-L6-v2, chunk 256/192 | 384 | 0% | 23.9 | 0.309 | 0.794 | 0.913 |
| **jina-embeddings-v2-small-en** | **512** | **0.002%** | **20.1** | **0.452** | **0.885** | **0.968** |

**Three findings, and two of them corrected beliefs held before the measurement:**

1. **Truncation was not the binding constraint.** `runs/session-c/truncation.json` found 38.64%
   of the corpus's word pieces never reached the embedder at 256 tokens, and both the operator
   and the agent reasoned that the dense number would substantially measure truncation rather
   than retrieval. **That was wrong.** Within a *fixed* model, 46% / 34% / 0% of turns truncated
   gives recall@1 of 0.314 / 0.345 / 0.309 — flat, and not monotone in how much text reached the
   encoder. The first 256 word pieces carry essentially all the retrievable signal despite being
   61% of the tokens. Recorded as a wrong call caught by measurement, not softened into a
   near-miss: neither party had data, and the data disagreed with both.
2. **jina's win is model quality, not window length.** Because the comparison above is flat, the
   8192-token context is *not* what bought the +31% relative recall@1. **A later session must not
   read "longer context helped" from this record.**
3. **Chunk-and-pool was measured and rejected**, not skipped. Max-over-windows lost on both axes:
   recall@1 0.309 against 0.345, at 23.9 texts/s/core against a 25 gate. The mechanism was
   predicted in advance and then observed — a long turn gets more windows and so more chances for
   one to look relevant in isolation, crowding the gold turn out of the top ranks.

**The throughput gate was replaced, not overridden.** jina fails the engine gate at 20.1/s/core.
That gate was scoped to a choice between engines producing *identical* vectors, where throughput
was the only axis; it cannot adjudicate a trade of quality against throughput. Overriding it
would have made it advisory — and this project's thresholds hold because none has been overridden
once. So a **new** condition was derived, scoped to the model decision, from the same underlying
constraint that produced the 25/s figure ("a full fit-and-score cycle must run twice in a
session"): **two consecutive full cycles ≤ 90 minutes of embedding work**, against a measured
493,500 embeddings per cycle. jina fails that uncached (142.5 min) and passes it with the
content-addressed embedding cache specified in the plan *before* any model comparison existed
(71.3 min, second cycle free). **The cache is therefore load-bearing for the model choice, not an
optimization**, and if it fails its byte-identity test the pre-registered branch is to revert to
all-MiniLM-L6-v2.

**Dimensions: 384 → 512.** Under the int8 hot array this ADR already mandates, 512 holds ~1.95M
entries per GB against 384's ~2.6M, so it does not bind. What *does* get tighter is the
exact-search f32 path ROADMAP keeps permanently as ANN validation ground truth: **0.75× as dense
per GB** — ~488k entries against ~651k. The ANN session inherits that budget and should size its
Tier-C validation points accordingly.

**Unchanged by this amendment:** int8 in the hot array; the rejection of API-only embedding,
which does not weaken under latency pressure because a network round-trip inside a 300 ms budget
is the reason the budget exists; and skills embedding description + trigger phrases only.

**If cues 3–5 exhaust the remaining latency budget**, the response is pre-committed in
`runs/session-c/PREREGISTRATION-model.json` and is, in order: ADR-003's hot index and the ANN
index first (both already M0b requirements, and `considered` still costs a full-store scan);
then the embedder's sequence length and model size; then the engine. The 300 ms budget does not
move — it is K1's definition, and a cue set that cannot fit inside it is a finding about the cue
set.

## ADR-005 · Auth broker

Covered by HP16. One `Broker` trait, two implementations, disclosed capability difference.

## ADR-006 · Eleven model-visible tools

`bash · read · edit · find · web · recall · remember · use · run · ask · done`

One slot spare against the ≤12 budget. `use` deliberately unifies skill-load and tool-load behind
one discriminated return rather than spending two slots. Registration is unlimited; twenty
connected apps still expose ≤12 because connectors are found through `use`, not front-loaded.

**Cost accepted.** `bash` carries enormous surface area for a single tool, which is precisely the
§7.2 bet: code execution as the universal adapter is the largest simplicity lever available, and
it trades tool-count for sandbox-quality dependence.

## ADR-007 · Seven nouns

`session · memory · skill · tool · run · trigger · profile`. The full mapping of every secretary
concept onto these is in `ARCHITECTURE.md` §5. Enforced by the budget test in HP10.

## ADR-008 · Tiered model routing

**Decision.** Strong model for orchestration and synthesis; fast cheap models for subagent
search, extraction, classification, consolidation, and semantic turn detection. Routing is by
task role, declared in `CapabilityProfile`, not by user preference.

This is the single largest cost lever in the system (§12), and it is what makes continuous
offline consolidation affordable enough to be the default rather than a paid feature.

## ADR-009 · No structural signature on the memory envelope

**Context.** `CONTRACTS.md` §3.1 pins `MemoryEntry` with `embedding_ref: Option<VectorId>`. M9's
candidate direction — analogical retrieval, matching on structure rather than surface — would want
a second derived key beside it, so that two problems with the same shape and different vocabulary
can match. All five cues match on surface features, so today they cannot.

`STATE.md` carried this as an open question for the human, framed on **schema cost**: adding the
field at M0b is one nullable column; adding it at M9 was priced as a contract major version bump, a
journal migration, and re-deriving signatures across the full history. On that framing the choice
is "preserve the option cheaply or foreclose it deliberately," and leaving it undecided decays into
foreclosed-at-the-worst-price.

That framing is answered below, but it is **not** the load-bearing reason. The order matters,
because a later session will reuse whichever argument is stated first.

**Decision. `MemoryEntry` does not carry a structural-signature field — not at M0b, and not in this
shape later.** The option is preserved by the rebuild path instead.

### The primary reason is correctness: a write-time structural signature is a forgetting leak

A signature computed at write time and stored on the envelope is a derivative of the entry's
content **that does not demote when the entry's fidelity does.** §5.4's ladder (record → summary →
gist → tombstone) and `ARCHITECTURE.md`'s availability/accessibility split are what let real
forgetting and an append-only log coexist: the log keeps the record **available**, and demotion
removes its **accessibility**. A signature derived from the Record survives at full strength on the
Gist and keeps matching at full strength — accessibility restored through a side channel. That is
§5.4's worst-failure clause exactly: *a memory the user can no longer surface but the system
silently acted on.*

Under §3.4 it is worse than a leak. Redaction is crypto-shredding — per-record DEKs, wrapped once
per subject, destroyed on `Redacted`. A plaintext signature on the envelope, outside the encrypted
record, is **residue of a redacted record**: it survives the shred and still matches. That is an
invariant 5 hole (*see, edit, delete* — a real delete, not a logical tombstone), not a schema-cost
question.

Making a signature demote with fidelity and shred with its subject is possible, and is specified
nowhere. It is a second lifecycle running beside the entry's, with its own correctness burden, and
nobody has costed it. A field that must not be populated until that machinery exists is not an
option being preserved; it is a hazard being parked.

### The cost model in the original framing was also wrong

Recorded so the prices are not reused as precedent:

| Priced as | What the pinned documents say |
|---|---|
| A contract **major** bump | `MemoryEntry` is §3. It crosses no process or language line — §4 is the only contract that does, which is why §4 alone pins a JSON wire format. An **optional** field is additive, and this document's own precedents make additive changes minor: §1.1 *"Adding a kind is a minor version bump; changing one is major"*; §3.2 *"Adding a variant is a minor bump."* |
| A **journal migration** | The belief store is a materialized view over the log (`ARCHITECTURE.md` §1, §2.3 *"fully rebuildable from the log"*). Adding a field to a derived view changes no journal event payload, so §1's forever-decodable rule is not engaged at all. ADR-003's stated purpose is that this class of change *"makes migration a rebuild rather than a data migration."* |
| **Re-deriving across full history** | Invariant 9: the index *"rebuilds to current state, not full fidelity"*, and *"a rebuild that resurrects forgotten memories is a correctness failure."* A derivation at rebuild time may run only over live entries at their then-current fidelity. Deriving over the forgotten tail is not expensive — it is **forbidden**, and it is the leak above wearing a different hat. |

The real late-adoption price is a minor bump plus one rebuild — the rebuild ADR-003 already commits
to and measured at 11.7 s — not a three-part migration.

### What preserves the option, since it is not a column

Journal payloads stay decodable forever (§1), and the belief store is a *derivation* over them. One
M0b requirement therefore carries the whole option:

> The belief-store rebuild is expressed as a **versioned derivation** over the event stream, with
> `derivation_version` recorded in the profile. Adding a derived per-entry field is a version bump
> and a rebuild, never a migration.

That is a testable property. A nullable column with no producer and no consumer is not — and an
untested nullable field is the same shape as every other unobservable-mismatch defect this project
has logged.

**Rejected.** Reserving one nullable `structural_signature` at M0b. It buys a minor bump and a
rebuild we would pay anyway, parks the demotion/shred hazard where a later session meets it as an
existing field rather than as a decision, and adds a field nothing writes and nothing reads — so
nothing observes it being wrong until something starts filling it.

**Cost accepted, and it is real.** If M9's analogical retrieval needs signatures derived from
**pre-demotion** content, that content is legitimately less accessible by then, and signatures
derived at M9 will be weaker than write-time ones would have been. We are choosing weaker
analogical matching over a forgetting leak. Brief §5.4 makes forgetting mandatory and names silent
influence as the worst failure, so the direction is right — but it is a loss, not a free choice.

Gated as M9 always was: nothing before M9 needs the field to work, and if M0b misses K1 a sixth cue
is irrelevant.

---

## ADR-010 · Cue fusion: calibration cannot both compare cues and order within one

**Status: the shape this ADR tests FAILED its pre-registered floor.** It is recorded anyway,
because the reason it failed is a constraint on every future fusion shape and is more valuable
than the shape was.

**Context.** Session C measured the two-cue combiner against its own inputs
(`runs/session-c/cue-overlap.json`). The cues are complementary — per-case Spearman 0.233, the
either-cue oracle reaching 0.652 at top-1 — but the fitted logistic reached **0.4957 at top-1
against lexical alone at 0.5478**. It won at k=5 and k=10 and lost only at k=1, which is where the
operating point reads.

The mechanism was the loss function, not the parameters. IRLS minimises log-loss over all 119,340
rows; dense is the better cue in aggregate and lexical is the better cue at rank 1, so the fit came
out `lexical 4.539 / dense 26.468` and was dense-shaped everywhere. **One global weight vector
cannot be dense-shaped in the middle and lexical-shaped at the top.**

**What was tried (Session D, `frozen-v3`).** Calibrate each cue separately against gold with its
own isotonic curve; fuse by taking the max. This removes the global weight entirely, and
calibration is the only thing that makes two cues comparable at all: a BM25 score whose empirical
gold rate is 0.6 should outrank a cosine whose empirical gold rate is 0.3, which raw-score linear
fusion cannot express at any weighting.

### It failed, and the failure is the finding

Floor: **0.4783 at top-1** against a required 0.5478 — worse than its best single input, and worse
than the v2 linear gate at every k. Measured mechanism
(`runs/session-d/fusion-failure.json`, 230 held-out cases):

| | |
|---|---|
| `lexical_bm25` curve | everything above 0.68293 collapses to one value |
| Cases with a tie at the fused maximum | **60.4%** (mean 2.72 candidates, max 19) |
| Lexical's head reordered by the tiebreak | **23.0%** of cases |
| Gold inside the unorderable band, not picked | **20.9%** of cases |

> **Isotonic calibration maps a continuous score to a step function. `max` over step functions has
> no resolution at the top — exactly where the operating point reads.**

Lexical alone orders its head by continuous BM25. Max-fusion flattens that head to a single value
and hands the decision to the tiebreak — and the tiebreak, `min_calibrated_precision`, is *the
other cue's opinion*, so inside a lexical-dominated tie it defers to the weaker cue at top-1.

**Decision, and it binds future shapes:** *calibration puts cues in common units by destroying the
ordering inside each cue. A fusion may use calibrated values to CHOOSE BETWEEN cues, but the
ordering that decides the top of the ranking must come from a continuous score.*

### Consequence for the cascade, which is the next shape

Recorded here so it is inherited rather than rediscovered:

> Dense filters by **calibrated precision**; lexical reranks by **raw BM25**. A cascade that
> reranked by *calibrated* lexical precision would reproduce Session D exactly.

### The second cost, which was missed when the shape was argued

Under max fusion, `max_calibrated_precision = max_c (cue c's own top block)`. **The fusion enters
the ranking and cannot enter the ceiling at all.** v2's joint logistic could, and did — 0.3176
above both cues' solo ceilings of 0.3090 and 0.2876, because blending produced a joint score whose
top block was marginally purer than either cue's own. The shape was argued on ranking; its
structural cap on the ceiling was not identified until after the fit.

This has a methodological consequence recorded with it:

> **A band on a quantity the tested shape cannot structurally move is not a valid read.** Check
> that a shape can move the metric it will be judged on, before registering the band.

Session D's ceiling band fired at `< 0.35` and its registered words called for escalation on the
grounds that *two* structural fixes had each failed to move the ceiling. That reading does not
hold: one fix moved it (+0.0086) and one could not move it by construction. **One trajectory data
point, not two, and the escalation is not licensed by it.**

**Rejected alternatives, with the evidence against each.**

| Shape | Why not |
|---|---|
| Fitted combination on **rank features** | Measured null: RRF scores 0.4957 at top-1, identical to the fitted gate to four decimals. A fitted rank combiner differs only by weights — same global weight vector, same aggregate loss, strictly less information, since ranks discard the magnitude calibration reads. |
| **Cascade** (dense filters, lexical reranks) | Not rejected — **deferred and now promoted.** It was ranked second because `N` is an unmeasured constant on the frozen path, which is verbatim the objection that keeps `cue_agreement_2cue` pinned. It is now the only candidate left, and `N` must be registered from dense's held-out recall curve before any reranker exists. |
| Lowering the threshold to make the gate inject | HP1 freezes it; ROADMAP M10 is the only milestone permitted to move an operating point, and says in as many words that adaptivity is not the remedy for a missed K1. |

**What ships, and the interlock that makes it safe.** `frozen-v3` stays the embedded artifact even
though it failed. The gate abstains on 100% of queries under both v2 and v3 (ceilings 0.3176 and
0.3090, both far under the frozen 0.95), so the ranking difference is invisible on the wire and
costs nothing operationally; and v3's per-cue curve structure is a strict superset of what the
cascade needs — a filter curve and a reranker. Reverting would discard the expanded refusal set and
the diagnostic for no measurable gain.

**That justification expires exactly when the next session succeeds**, because the cascade's whole
purpose is to make the gate inject — the worst possible timing for an argument to lapse, and the
kind of thing a session is guaranteed not to be thinking about on the day it finally gets a number
above the threshold.

So it is **not** left to anyone's memory. The artifact carries `floor_verdict`
(`pass` | `fail` | `unmeasured`) alongside `floor_required`, `floor_measured` and
`floor_read_from`, and `FrozenGate::load` refuses:

> **A gate whose recorded floor verdict is `fail` cannot load if its calibration would reach the
> frozen threshold.** A fusion measured below its own best single cue must not decide what reaches
> the model.

v3 therefore stays usable as scaffolding *because* it injects nothing, and becomes unloadable the
instant that stops being true. Checked on `fail` only, not `unmeasured`: the floor is read from a
scoring run's feature dump, which requires the gate to load in order to produce it, so refusing
`unmeasured` would deadlock the measurement. `fit_gate.py` writes `unmeasured` because the fitter
cannot know a held-out number; `tools/analyze_cue_overlap.py --record-verdict` stamps the measured
verdict and the build embeds it.

**This replaced an open question addressed to the human.** An earlier draft of this ADR flagged
"confirm or reverse shipping v3" for a human decision. A structural interlock is strictly better
than a question someone has to remember to answer, and the question was withdrawn when the
interlock landed.

---

## ADR-011 · The calibration was asking an incoherent cross-query question

**Status: the hypothesis is CONFIRMED and the shape still FAILED its floor.** Both are recorded,
because the second is what the next session has to solve and the first is why it is now a different
problem.

**Context.** Through `frozen-v3` every cue curve was fit on that cue's **pooled raw score** across
all fit queries — one isotonic curve over ~119,340 candidates, asking *what fraction of this score
band is gold*. That question requires BM25 and cosine to be comparable **across** queries.

They are not, and Session B made them that way on purpose. `lexical::BM25_SATURATION` is an
*absolute* map (`s/(s+10)`) rather than min-max, because min-max forces the best candidate of every
query to 1.0 — including queries where nothing matches — and a gate whose top feature is 1.0 by
construction cannot abstain. The cost of that correct choice is that a query whose wording matches a
lot of text has *all* its candidates scoring high.

The symptom: lexical put gold at rank 1 in **54.8%** of held-out queries while the calibration's
best block was **31.0%** gold.

### The diagnosis, measured before any curve was fit

Count the **distinct queries** represented in the top block. If the block were a uniform random
sample of candidates, occupancy gives `m·(1−(1−1/m)ⁿ)` = **206.9 ± 4.5** of 242 queries.

| ranked by | distinct queries | z |
|---|---|---|
| `lexical_bm25` (pooled) | **133** | **−16.4** |
| `dense_cosine` (pooled) | 138 | −15.3 |

**The pooled top block really does fill from a minority of queries.** Concentration alone would not
prove it *harmful* — high-BM25 queries might genuinely have better matches — but the conjunction
does: that block is 31% gold while each query's own rank-1 is 56%.

### The fix, and what it bought

Calibrate on **`{cue}_margin`** — the candidate's lead over its own runner-up, in raw score units —
and rank by **`{cue}_z`**, dimensionless so it can order a lexical-won candidate against a dense-won
one. Same cue, same scores, query-local question:

| swept feature | precision | coverage |
|---|---|---|
| `lexical_bm25` pooled | 0.418 | 0.261 |
| **`lexical_margin`** | **0.579** | **0.483** |

Both terms improved at once. The ceiling moved **0.309013 → 0.371245**, against **+0.0086** for
adding an entire new cue in Session C.

**Why margin is calibrated and z is not.** Within a query the two give the identical order, so the
choice only bites in two places and they want opposite properties. The ranking needs something
*dimensionless*; the threshold needs something that *preserves absolute magnitude*, because
σ-normalized z carries Session B's min-max defect in weaker form — a candidate that barely beats
noise in a tight distribution still scores high. A query where everything is near zero has a tiny
margin, and that is what keeps abstention possible.

### It still failed the floor, and the failure changed kind

**0.5435 at top-1 against a required 0.5478 — one case in 230.** Session D scored 0.4783 against the
same floor, so v4 recovers 0.065 and lands at parity-minus-one-case with always-lexical.

> **Session D's failure was a CALIBRATION failure; this one is an ARBITRATION failure.** A step
> function deciding rank cannot recur — no calibrated value appears in the v4 ranking key at all.
> What remains is that every cue scores a memory *in isolation* and the gate compares isolated
> opinions. Choosing between them by calibrated margin picks wrong slightly more often than never
> choosing at all.

**Decision, and it binds the next shape:** *per-query normalization fixes the question the
calibration asks. It cannot fix cue selection at rank 1, and no fusion over per-cue scores can —
the top-1 either-cue oracle is 0.652 and that is the exact ceiling on perfect arbitration. Moving
past it requires a scorer that reads query and candidate together.*

### A structural cap, accepted knowingly

`margin` is positive for **at most one candidate per cue per query**, and an isotonic curve is
non-decreasing, so at most 2 candidates per query can ever clear the threshold — usually one.
Coverage is therefore capped by the top-1 hit rate, and `m` is bounded by 2.

This is not a defect to fix by widening the feature. §5.5 is precision-first and recovers recall
through the explicit search tool. It is the cost of asking a decisiveness question, it was
registered before the fit, and it is asserted by test.

### The pre-registration lesson — ADR-010's mirror image

ADR-010 recorded: *a band on a quantity the tested shape cannot structurally move is not a valid
read.* The symmetric failure is now on the record too:

> **A band whose confirming and falsifying regions OVERLAP is equally unreadable.** Session E's
> ceiling band had CONFIRMED at ≥0.337 and UNMOVED at <0.354, because the predicted movement was
> smaller than two binomial standard errors on a 466-row block. Check separation *before*
> registering, with the same discipline that checks reachability.

**And the response to a failed separation check is not to narrow the band.** δ was derived from the
block size; shrinking it after seeing non-separation would be tuning the instrument to guarantee an
answer. The band was left exactly as derived, demoted to a secondary read, and a **well-powered**
diagnostic — top-block query concentration, where the difference between concentrated and diffuse is
hundreds of queries rather than hundredths of a rate — became the primary. The measured ceiling then
cleared *both* boundaries, so the overlap was never entered; that was luck, and the demotion was not
contingent on it.

### Two arithmetic traps in deriving a band from block structure

Both are Session D's inverted selectivity comparison in new clothes, and both were caught pre-fit:

1. **The top block fills from ALL cases, but only gold-bearing ones can contribute gold.** 229 of
   251 fit cases have gold in scope; the other 22 contribute a row to every rank slice and a hit to
   none. Scale each slice by the gold-bearing fraction.
2. **The block is not a random sample of ranks.** Only one candidate per query has a positive
   margin, so the remainder is the *least-negative* margins — rank-2s from queries where s₁ ≈ s₂,
   whose gold rate is below the rank-2 average. The prediction is an **upper bound**, not a point
   estimate, and was registered as one.

**Part of the 54.8% / 31% gap was never a bug.** A 466-row block and a 251-row rank-1 set are
different populations. The arithmetic above is what separates the real defect from that arithmetic
difference, and predicting "the ceiling should approach 0.548" would have repeated Session D's error
exactly.

---

## ADR-012 · Consolidation is a supersession edge, and it does not move retrieval on this corpus

**Status: the pre-registered prediction is CONFIRMED. Consolidation is built, journaled,
reversible, and measured — and it moves nothing.** The either-cue top-1 oracle goes
**0.6522 → 0.6435** like-for-like (−0.0087, two cases in 230). Recorded because the null is the
last named lever closing, and because two of the decisions taken on the way are binding regardless
of the result.

**Context.** Sessions B–E moved the ceiling 0.309 → 0.371 against a frozen 0.95 and left the
two-cue oracle at 0.652, which caps perfect arbitration. The cross-encoder — the one named lever
that could exceed that oracle — was ruled out at M0b on latency (ADR-011, spike 2026-08-04).
Consolidation was the last named lever, and its claim was different in kind: it changes *which
candidates exist* rather than how they are ranked, so unlike Session E's per-query features it is
not rank-preserving and **can** move the oracle.

### The shape, and why it mints no new belief

A near-duplicate cluster elects one of its **existing** members and the rest get `Superseded`;
§4.3's exclusion (2) then removes them from the candidate set. **HP5 already specified this** —
*"merges are supersedes edges and are therefore undoable"* — and two properties follow:

1. **Reversibility.** An over-eager merge is an appended edge over untouched beliefs, so HP5's
   *detect + reverse* is structural rather than aspirational.
2. **Attribution survives.** M0a's `Attributor` builds its reverse map as
   `_turn_of[memory_id] = turn_id`, **last write wins**, and `evidence_precision` drops
   unattributable injections from its denominator entirely. A merge minting a *new* id would
   therefore be scored against whichever constituent turn happened to be recorded last, silently —
   or, reported under no turn, would leave precision as a ratio over an empty set. Neither failure
   is visible in any number the harness prints.

> **Decision, and it binds any future consolidation work at M0b: a merged memory must remain
> attributable to exactly one ingested turn.** Distillation that rewrites text under a new id is
> not measurable on a per-turn evidence key, and making it measurable is an M0a change argued
> separately — not something an implementation session grants itself.

### Two decisions that measurement changed, before any band was written

**Single-link clustering is wrong on dense embeddings of conversation.** jina's similarity over
chat turns is anisotropic: **40.8%** of all 30.6M fit-split pairs reach cosine 0.70. A transitive
linkage therefore chains — at threshold 0.70 single link removed **99.8%** of the candidate pool
and built a **616-member** cluster, declaring an entire session one memory. Complete link ships.
Both are swept in the dry run and both tables are in the pre-registration, so the rejection stays
measured rather than becoming folklore.

**The survivor is the LATEST cluster member, not the earliest.** Supersession means a newer belief
displaces an older one, and LongMemEval's **knowledge-update** category is built on exactly that:
gold is the latest statement of a fact whose earlier statements are distractors. Electing the
earliest would have systematically suppressed gold across the one category whose whole difficulty
is recency — and would have presented as an unexplained retrieval regression with no visible cause.

### The result, with both halves attached

| | |
|---|---|
| Held-out pool reduction | **1.186%** — the pre-registered `< 0.03` band, **PREMISE REFUTED** |
| Pairs at cosine ≥ 0.98 | **0.0086%** of 30,587,870 |
| Oracle, like-for-like | 0.6522 → **0.6435** |
| Largest movement anywhere in the R@k table | 0.0087, against a Wilson half-width of **0.062** |
| Cost | **123 ms P95** per session close, 0.41% of the §4.0.7 ingest deadline |

`STATE.md` carried the claim that the pool is *"~493 turns where near-duplicates compete with
gold."* It is ~493 **distinct** turns. There is very little for a near-duplicate rule to remove
because there is very little duplication present.

> **This is a property of the corpus, not of consolidation.** LongMemEval-S haystacks are assembled
> from *distinct real sessions*, so distractors are topically related rather than textually
> duplicated.
>
> **It does not generalize to real user history**, where the same thing genuinely does get said
> repeatedly across months. A null here is evidence about *this benchmark's candidate pool*. It is
> **not** evidence that §5.3 consolidation is unnecessary in production.

Both halves were registered before the fit, so neither can be quoted without the other.

### The oracle carried no band, and that is ADR-011's lesson mirrored

The reach check passed — removal changes ranks, so the metric is structurally movable, unlike
Session E's monotone within-query transforms. But the measured fit-split headroom was **+0.0044,
one case in 229**, against a Wilson half-width of 0.062. **A band an order of magnitude narrower
than the instrument's resolution cannot be read.** ADR-010 says do not register a band on a
quantity the shape cannot move; ADR-011's mirror image says do not register one the *split* cannot
resolve. Both checks now run before bands are written.

### The floor, re-based, fails for the third consecutive session

The floor was the prior session's best single cue, which was safe only while the cues were fixed.
Consolidation changes the cues, so an inherited floor could be cleared on a cue improvement the
fusion did not earn. **Re-based before the fit to the best single cue measured in the same run:
required ≥ 0.5415, measured 0.5371.** It fails against the superseded 0.5478 basis too.

Three sessions of the fused gate losing to its own best input at top-1 is now a stable property of
two-cue arbitration, not an accident of one shape.

### What closes here

The named-lever list. Registered before the result existed, so it cannot read as a reaction to a
disappointing number: **there is no further named mechanism that raises the either-cue oracle
within M0b's budget.** The next conversation is about K1's definition — what 0.95 injection
precision means, and whether it is the right bar for a two-cue content-similarity system whose
oracle caps at 0.65 — and not about the next lever.

---

## ADR-013 · The query side is measured, and the problem is inside the session

**Status: the direction change is recorded, the four named query-side mechanisms are measured, and
three of four are closed.** Session G ships nothing. Its value is that it moves the open question
from *"which arbitration shape"* to *"which pool is being arbitrated over"*, and it closes named
levers rather than accumulating them.

**Context, and why this does not violate Session F's registration.** Session F registered, before
its result existed, that *"there is no further named mechanism that raises the either-cue oracle
within M0b's budget."* That statement stands as written and was true of the project's option space
at the time. External research then named mechanisms the project had not — SmartSearch's
cross-encoder-carries-all-precision result, Supermemory's session-level ingest granularity, Mastra's
three-date temporal structure. **The option space was extended from outside; a registered escalation
was not quietly reversed after a disappointing number.** ADR-012 records the same distinction.

### What was measured

All four arms were verified against ADR-010 **before** any band was registered: none is an
arbitration change, so none is capped by the either-cue oracle. Arms 1 and 4 change the candidate
set; arms 2 and 3 change the per-cue scores via a new query representation.

| arm | verdict | number |
|---|---|---|
| 1 · session-level pruning | **oracle read VACUOUS**; value is pool reduction | 10.3% pool at 98.25% gold retention, N=3 |
| 2 · PRF + entity expansion | **HARMFUL**, both configurations | −0.2358 / −0.1179, p < 0.001 |
| 3 · hypothetical answer embedding | **PREMISE REFUTED** | answer-for-question −0.2227; realizable +0.0218, p=0.27 |
| 4 · temporal anchoring, hard constraint | **NOT REACHED**, and the corpus explains it | 1 of 59 temporal questions carries a window |

### The decision, and it binds the next session

> **Session selection is close to solved; ranking inside a correct session is not.** At N=3 the
> failure decomposition is 4 wrong-session against 77 right-session-wrong-rank — **19.2 to 1**.

Sessions D, E and F attacked arbitration over a ~487-turn pool, which is what carries the 0.6435
oracle cap. Ranking ~47 topically coherent turns is a different problem and is **not known** to
carry the same bound. Session G did not measure it and did not claim it. The question is registered
forward and unmeasured in `runs/session-g/REGISTERED-QUESTION-in-session-rerank.json`, with its pass
condition fixed in advance.

**A better session scorer is worth approximately nothing** — four cases. Do not build one.

### Two things that are closed, and one that is not

**Closed: query expansion.** PRF draws feedback from the first pass, and the first pass is worst
exactly where help is needed. This was predicted before measurement and confirmed at −0.2358.

**Closed: HyDE as specified.** Embedding a plausible answer *instead of* the question costs 22 points
**with a perfect generator** — the released gold answer. The premise that answers resemble the
searched turns better than questions do is refuted, not merely unsupported. What helps is the answer
*augmenting* the question, and that is only visible at an upper bound requiring the answer to be
known already.

**Not closed: temporal anchoring.** It is closed *as a retrieval-side hard constraint on this
corpus*, because LongMemEval's temporal questions name events rather than windows. Mastra's
mechanism does its work at the **answer stage**, computing an offset once evidence is in hand. That
is untested here and remains open.

### The cross-encoder, re-costed and still not adopted

`L-2-int8` clears the registered latency bar with room to spare — **92.41 ms P95 at 1 thread against
240 ms** — and is still NOT ADOPTED, on two independent grounds registered before measurement:

1. **Batch invariance FAILS for int8**, max logit difference 0.050 (L-6) and 0.037 (L-2), where the
   spike's fp32 L-6 passed at exactly 0.000e+00. Quantization changes the reduction order. A stage
   whose score depends on batch composition breaks `repro --runs 2`.
2. **Arm 1's shortlist-equivalence condition failed** at every N and every ranker, so the budget
   argument that justified re-opening the question does not hold.

> **Determinism is re-verified per graph, never inherited across a quantization or a model change.**
> This is the rule the session earned and it is binding.

### The pre-registration lesson, which is the durable part

Arm 1's registered primary read returned **+0.0000 at every N in both modes** — an identity, not a
null. Under max aggregation a session's score *is* its best turn's score, so the top-scoring turn
always lies in the top-scoring session and pruning cannot displace it. Proven, not argued: 458/458
case-cue pairs, zero violations.

The registration performed the ADR-010 reach check correctly. It verified that **the shape can move
the metric** — and pruning genuinely can. It did not verify that **the read, under the chosen
aggregation, can vary at all.**

> **Binding on every future pre-registration: check that the READ can vary, not only that the SHAPE
> can move the metric. They are different questions and only the first has been asked so far.**

A quantity that cannot move produces a clean, confident, meaningless number with nothing downstream
looking wrong. That is the same failure mode ADR-011 records for Session D's calibration, arriving
through the measurement instead of the mechanism.

**A second, smaller miss, recorded because it recurred:** the registration fixed N and every read but
not the session **scoring rule**. Three variants were declared before running and all reported, and
the best is not quotable as the arm's result. A registration that fixes the bands but leaves a free
hyperparameter has not fixed the experiment.

### Also recorded

**A provider that is listed is not a provider that loads.** `get_available_providers()` advertised
CUDA; it failed on missing cuBLAS/cuDNN and ORT fell back to CPU **silently**, producing a "GPU"
figure within 1% of the 1-thread CPU one. Execution providers are now asserted against
`get_providers()` on the constructed session. Sixth instance of the two-sides-silently-disagree
pattern, and the first in a hardware binding.

**GPU is not adopted for the retrieval path** and no number is reported. Determinism across
execution providers and the VPS deployment target each need their own ADR.

---

## ADR-014 · The cross-encoder is the gain; the in-session framing is not

**Status: shipped and measured. The retrieval path prunes and reranks; the registered question that
motivated the pruning half FAILS.** Both halves are this session's result.

### What was built

Session G measured the reframe offline and nothing in the binary used it. Session H ships it:
sessions derived from `occurred_at_ms` contiguity at a frozen 30-minute gap, pruned to the union of
each cue's top-3 by max aggregation, and the top 10 survivors reranked by `ms-marco-MiniLM-L-2-v2`
int8 at batch 1.

| | before | after |
|---|---|---|
| R@1 | 0.5348 | **0.5764** |
| R@5 | 0.8130 | **0.8428** |
| R@10 | 0.8826 | **0.9039** |
| oracle R@1 | 0.6435 | 0.6463 (**pinned**) |
| ceiling | 0.3739 | 0.3739 (**pinned**) |
| retrieval P95 | 33 ms cold subset | 149 ms warm, full split |

**The shipped ranker beats the best single cue for the first time in this project** — 0.5764 against
lexical's 0.5415. Sessions D, E and F each shipped a fusion that did not.

### The decision, and it binds the next session

> **The gain is the cross-encoder. It is not the in-session framing.** The reranker gains +0.0393
> over the fitted gate **whether or not the pool was pruned first**. Q1 and Q2 differ on 3 and 1
> cases out of 229: feeding the reranker a 10.3% shortlist instead of the whole ~487-turn pool
> changes its top-1 almost never.

ADR-013 reframed the problem as ranking inside a correct ~47-turn session, on a 19:1 failure
decomposition. That decomposition was a **true description of where the errors are and a false lead
about what fixes them.** Knowing gold survives into the kept session does not help a reranker that
was going to consider it regardless. **Session pruning is closed as a quality mechanism.** It
remains a cost mechanism and reduces `considered` as a side effect.

### The number that matters for K1

**The reranker is NOT capped by the either-cue oracle, and lands below it anyway.** Its presence
ceiling on the pruned pool is **0.9825** against the 0.6435 cap — measured on the fit split before
anything was built, per ADR-010, and confirmed rather than assumed. It is structurally free to reach
~0.98. It reads **0.5764** against a held-out oracle of **0.6463**.

Sessions D and E were bounded by that oracle **because of their shape**. This mechanism is not, and
performs in the same neighbourhood regardless.

> **The bound is a property of the task, not of the combiner.** A better arbitration shape is not
> the missing piece — this was not an arbitration and did not clear the bar either.

### The pre-registration lesson: verify the CONTRAST can vary, not just the read

**The registered α was unreachable.** Exact McNemar is a binomial over the discordant pairs, so the
smallest attainable p is `2/2^n`: 0.25 at n=3, 1.0 at n=1. Q1 had **3** discordant pairs and Q2 had
**1**. `p < 0.05` was **not attainable at any outcome**, and the significance half of both verdicts
is uninformative by construction.

The ADR-013 instrument check **passed** — 62 discordant, both directions — and measured the wrong
thing. It compared reranked top-1 against **the ranking the reranker replaces**. The registered test
consumes a different contrast: **reranked-pruned against reranked-unpruned**, two arms sharing one
reranker.

Third member of one family, arriving a level deeper each time:

1. **ADR-011** — the *mechanism* could not move the metric.
2. **ADR-013** — the *read* could not vary.
3. **ADR-014, here** — the read varies; the **contrast the test consumes** does not.

> **Binding: a pre-registration using a paired test MUST state the minimum discordant count at which
> its α is attainable, and its instrument check MUST confirm the arms disagree that often — on the
> exact contrast, not on a proxy for it.**

The **delta** criterion is unaffected and carries the conclusion: +0.0131 and +0.0044 against +0.05
are an order of magnitude short.

### Also decided

**Pruning runs after `features::extract_all`, and the ceiling is therefore pinned.** The frozen
gate's isotonic curves were fit on ~487-candidate margin distributions; feeding them a ~50-candidate
distribution is two sides silently disagreeing. Every `calibrated_precision` is bit-identical to
Session F's. **Refitting the gate on pruned pools is the named next lever and needs its own
registration.**

**The max-aggregation identity is partition-independent**, so it holds for derived sessions —
re-measured, 458/458, zero violations, both partitions. Consequently **the unchanged-cue check is a
null instrument for a pruning change** and its silence is not evidence.

**Seventh instance of the two-sides-silently-disagree pattern.** Session G re-costed at ORT's
default `ENABLE_ALL`; the Rust builds at `Level1`. Same pinned graph, same token ids, **logits
0.0699 apart** — nearly twice the batch-invariance failure that blocked adoption. Caught by the
reference fixture. Both sides now pin `ORT_ENABLE_BASIC`.

**Batch is 1 structurally**, not by configuration: one pair per call, asserted leading dimension, no
slice entry point. Batch invariance at Level1 is **0.0958**, worse than at `ENABLE_ALL`.
`repro --runs 2` is byte-identical with the reranker live.

**§4.6 carries no session structure and that is the real defect.** Deriving sessions from timestamps
is an approximation of something the contract could carry. **An M0a change with its own
registration**, not absorbed as a permanent workaround.

---

## ADR-015 · The sequence cap is an accidental length normalizer, and quantized graphs are shape-bound

**Status: measured, and NOTHING SHIPPED. `rerank.rs` is unchanged.** Session I's scope was narrowed
twice; the sweep was not run. Three findings are the result, and the first one is why no code
changed.

### The decision, and it binds the next session

> **Do not raise `MAX_SEQ_LEN` on its own. It is a −0.0917 R@1 regression, and the reason is that
> the 256 cap is doing two opposing jobs.** It costs the 7.86% of gold turns that do not fit, and it
> earns more than that back by capping how much score a long distractor can accumulate. **Removing
> the cap removes the normalization.** Raising sequence length is viable only alongside **explicit
> length normalization of the rerank score** — which is therefore promoted to the named next lever.

L-2 f32, depth 10, window 0, fit split, everything but sequence length identical:

| | R@1 | conditional accuracy |
|---|---|---|
| seq 256 | 0.5983 | 0.6493 |
| seq 512 | 0.5066 | 0.5498 |

Discordant 31 (5 gained, 26 lost), exact McNemar **p = 0.0002, α attainable** — the first
significance statement in this project since ADR-014's defect that actually carries information.

**The mechanism was registered as a two-way prediction before the measurement.** Either (a) the
model genuinely prefers long passages, or (b) truncation manufactures the score by cutting a
distractor to its most query-like opening. **(a) holds.** The rank-1 distractor on failures moves
from 50.0% assistant-authored at 157 median word pieces to **74.3% at 487**, against gold that is
87.7% user-authored at a median of 70. Truncation was *suppressing* the bias, not creating it.

### Quantized graphs are bound to their tensor shape, in every dimension

**`[1, 256]` is load-bearing on the shipped int8 graph exactly as batch = 1 is.** With bit-identical
token ids, stripped of padding and re-padded to a longer tensor — only the shape differing:

| padding-only, 600 pairs | median \|Δlogit\| | p95 | max | top-1 flips from padding alone |
|---|---|---|---|---|
| L-2 **int8** | 0.010904 | 0.046044 | 0.417379 | **9/60 = 15%** |
| L-2 **f32** | 0.000000 | 0.000000 | 0.000000 | **0/60** |

**Standing check: any sweep that varies sequence length runs f32, or its cells are different
scorers.** The first read of the contrast above was taken on int8 and is void for that reason;
int8 and f32 both landing on −0.0917 is coincidence, not corroboration. Eighth instance of the
two-sides-silently-disagree pattern. It also corrects ADR-014's neighbourhood: batch invariance
failed because of **quantization, not architecture** — all eight f32 graphs are invariant to
0.000000.

### CUDA is unblocked, and nothing was missing

Session G's CUDA figure landed within 1% of CPU because the provider was *listed* and never
*loaded*. No CUDA Toolkit is installed and none is needed: `torch 2.5.1+cu121` bundles what ORT 1.24
requires in `site-packages/torch/lib`, and they were not on ORT's DLL search path.
`os.add_dll_directory(torch/lib)` **before** importing onnxruntime, provider asserted against
`get_providers()` after construction. **This unblocks fine-tuning, now the strongest remaining lever
after length normalization.** GPU is **not** adopted for shipped inference; that needs its own ADR
covering determinism and the VPS target.

### What this session banked rather than spent

The fit/held-out identity (+0.0000 on both halves, the gap is case mix), the failure decomposition,
the depth table (**saturates at 30**, and depth 30 *is* the whole pruned pool), 8 rerankers pinned by
repository revision **and** sha256, the model gate, and the truncation reachability grid. **A later
session resumes at Phase 2 and does not repeat Phase 0 or Phase 1.**

**Arm 6 is reclassified rather than deferred: per-query normalization CANNOT move R@1** — a strictly
increasing within-query transform against a within-query ordering read is an identity, the same
defect as ADR-011 and ADR-013. It belongs to the coverage curve, where the decision is cross-query.

---

## ADR-016 · The 0.95 injection threshold was unreachable by construction, and 0.3739 never measured retrieval quality

**Status: measured in Session J Part 0, before any band was registered. This is an ADR-010
reachability check that came back NEGATIVE, and it reframes nine sessions retroactively.**

`runs/session-j/gate-resolution.json`. Licensed by the standing reconstruction fidelity gate —
lexical 0.5415, dense 0.4454, either-cue 0.6463, all reproduced exactly.

### The decision

> **A perfect retrieval system scores 0.8483 on this gate, against a threshold of 0.95.**
>
> `max_calibrated_precision >= 0.95` is therefore unreachable at `CALIBRATION_BLOCKS = 256` for
> **any** feature, including a perfect one. The gap between 0.3739 and 0.95 was
> never a quality gap and could not have been closed by improving retrieval. **Do not read any
> historical statement of the form "max calibrated precision 0.3739 against a 0.95 threshold" as
> evidence about the retrieval system.** It is a statement about the calibration's resolution.

### The mechanism, in three steps

**1. The calibration cannot express an operating point smaller than one block.** `fit_isotonic`
buckets fit rows into 256 **equal-count** blocks and then pools — adjacent blocks sharing a score
bound, then adjacent PAVA violators. Every one of those operations makes a block *larger*. On the
licensed gated fit population (111510 rows, 445 gold, 229 cases) the smallest expressible block is
**435 rows = 1.90 candidates per query**.

**2. That block is forced to span every query, so the only operating point is FULL COVERAGE.**
The calibrated features are `{cue}_margin` — the candidate's lead over its own query's runner-up —
so **exactly one candidate per query has a positive value**. The global top block is therefore
structurally "one row from every query, then the least-negative rank-2s". Measured, not asserted:

| | rows in top block | of which their query's rank-1 | distinct queries touched |
|---|---|---|---|
| `lexical_margin` | 435 | **229 — one per query** | **229 of 229 = 100%** |
| `dense_margin` | 435 | **229 — one per query** | **229 of 229 = 100%** |

**A precision threshold is a request for a confident SUBSET. The gate has no vocabulary for
subsets.** It can only answer at 100% coverage.

**3. At full coverage the value is a diluted single-cue R@1.** The 206 non-rank-1 rows are forced
into the block and are almost all negative:

| | gold among the 229 rank-1 rows | cue R@1 | gold among the other 206 | top block |
|---|---|---|---|---|
| `lexical_margin` | 129 | 0.5633 | 40 | **0.3885** |
| `dense_margin` | 106 | 0.4629 | 48 | **0.3540** |

### The oracle, which is the number that closes it

The naive bound `min(positives, block) / block` is **1.0000 here and is vacuous** — it ignores
*where* gold rows can be. Under the forced composition a query contributes a gold row at rank 2
only if it *has* a second gold row, and **89 of 229 fit queries have exactly one**:

| gold rows per query | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| queries | **89** | 99 | 21 | 9 | 7 | 4 |

    perfect cue:  229 rank-1 rows all gold
                + min(206 rank-2 slots, 140 queries with a second gold) = 140
                = 369 / 435  =  0.8483   <   0.95

**A perfect retrieval system scores 0.8483 on this gate.** The threshold is 0.95.

### Scope of the claim, stated exactly

- **The resolution bound is general**: at 256 equal-count blocks over ~111k rows, no operating
  point narrower than ~435 rows exists, whatever is calibrated.
- **The 0.8483 oracle is specific to the `{cue}_margin` composition** — one positive per query.
  A gate calibrating a feature that is *not* query-local would fill its top block differently.
  That is a different gate design, and it is not what has been shipped since v4.
- **`THRESHOLD = 0.95` is untouched and stays untouched.** This ADR does not lower it; it records
  that the quantity being compared to it does not mean what nine sessions took it to mean.

### What this does and does not change

**Does not change:** any R@1, R@5 or R@10 number. Those are within-query ordering reads computed
from the ranking, never from the calibration, and none of them passes through a block.

**Does change, retroactively:** every statement that the gate "abstains on every query" *because
retrieval is not good enough*. It abstains because the only operating point it can express is full
coverage, where no achievable value clears 0.95. The §4.3 maturation gap's closing condition — "the
gate begins injecting" — was therefore not reachable through the work Sessions B through I did.

**Consequence for Session J:** Part 3(a) reports this bound and stops, as instructed. **Conformal
risk control is the K1 answer**, and the reason is now mechanical rather than preferential: it
thresholds a per-query margin and abstains per query, so its operating point has resolution 1/229
instead of 435 rows, and it can name a confident subset at all.

### A constraint for whoever owns the gate design after M0b — recorded, not discovered

**This is not Session J's scope and re-tuning the calibration resolution stays forbidden.** But the
0.8483 oracle is now a measured fact and it forecloses something, so it is written down here rather
than left to be rediscovered by the session that tries.

> **If a perfect cue cannot reach the operating point, isotonic gating in its current shape cannot
> be made viable by better retrieval. Either the resolution rule or the margin feature's
> one-positive-per-query property has to change.**

The two are the only load-bearing inputs to the bound, and they fail differently:

- **The resolution rule** (`CALIBRATION_BLOCKS = 256`, equal-count) sets the block at ~1.9
  candidates per query. Finer blocks raise the reachable precision — which is exactly why
  `fit_gate.py` fixes the resolution on a stated principle and why choosing it after seeing whether
  the curve clears 0.95 is tuning the operating point through the back door. **Any future change
  here must be argued and pre-registered before the fit, not selected against the outcome.**
- **The one-positive-per-query property** is what forces the top block to span 100% of queries.
  It is a consequence of calibrating a *within-query margin*, which Session E adopted for a good
  reason — pooled raw scores ask an incoherent cross-query question (ADR, v4). Changing it means
  re-opening that decision, not tweaking a constant.

**The claim is bounded and should stay bounded.** The 0.8483 figure is specific to the
`{cue}_margin` composition on this population. A gate calibrating a feature that is not query-local
would fill its top block differently — and would inherit Session E's incoherence problem instead.
Neither escape is free, and this ADR does not pick one.

---

## ADR-017 · Length normalization works, the registered estimator had the wrong sign, and the defect closes only on a model that cannot ship

**Status: measured in Session J Part 1, fit split, five cells.** Pre-registration
`runs/session-j/PREREGISTRATION.json`; post-hoc addendum `ADDENDUM-post-hoc-length-form.json`,
written before any held-out read.

### 1. The decision on estimators, and it generalizes past this arm

> **A length-normalization term must be fitted against RELEVANCE, not against the score.** An
> estimator of the form `E[score | length]` measures the model's length response. The quantity that
> needs correcting is the model's length response **relative to relevance's**, and on this corpus
> those two differ by more than an order of magnitude.

Measured on the fit slate, L-2 f32 at seq 256:

| length bin (median word pieces) | 32 | 51 | 68 | 88 | 186 | 368 | 530 | 656 |
|---|---|---|---|---|---|---|---|---|
| mean logit | -6.94 | -6.90 | -6.02 | -5.87 | -6.73 | -7.07 | -8.03 | -8.62 |
| **gold rate** | 0.115 | 0.248 | **0.353** | 0.329 | 0.063 | 0.039 | **0.007** | **0.007** |

**The mean logit moves 2.6 across the whole range and is not even monotone. The gold rate falls
50-fold.** The model under-penalizes length by a wide margin, and relevance never enters
`E[s | len]`, so that estimator cannot see the gap it was registered to close.

The consequence was not subtle. The fitted slope came out **-0.5091** logits per log word piece and
the fitted role coefficient **-0.9352** — on the slate the model *already* scores long and
assistant-authored candidates lower on average — so subtracting the fitted mean **added** score to
exactly the candidates that needed penalizing:

| registered arm | best on grid | delta R@1 |
|---|---|---|
| 7b subtractive | lambda 0.25 | **-0.0262** |
| 7d role only | lambda 0.25 | **-0.0088** |
| 7e both | lambda 0.25 | **-0.0350** |
| **7c divisive** | alpha 0.5 | **+0.0349** |

Confirmed by the failure profile moving the wrong way: rank-1 on failures goes from 50.0%
assistant-authored at 157 median word pieces to 71.4% at 430 as lambda rises.

**Ninth instance of the family.** ADR-011: the mechanism could not move the metric. ADR-013: the
read could not vary. ADR-014: the contrast could not reach significance. **Here: the estimator
could not have measured the quantity it was registered to correct.**

### 2. Normalization works, and the registered directional prediction is falsified

Fit split, R@1. `7c` is the registered divisive arm; `7f` is the post-hoc `s - 2.0*log(len)` form,
**selection-biased and not a result** — see the addendum.

| cell | control | 7c registered | delta | discordant | exact p | 7f post-hoc |
|---|---|---|---|---|---|---|
| L-2 f32 @256 | 0.5983 | 0.6332 | **+0.0349** | 24 | 0.1516 | 0.6769 |
| L-2 f32 @512 | 0.5066 | 0.6114 | **+0.1048** | 50 | 0.0009 | 0.6419 |
| L-6 f32 @256 | 0.6114 | 0.6638 | **+0.0524** | 32 | 0.0501 | 0.6856 |
| L-6 f32 @512 | 0.6026 | 0.6638 | **+0.0612** | 34 | 0.0243 | 0.6856 |
| L-2 int8 @256 *(shipped)* | 0.6201 | 0.6463 | +0.0262 | — | — | 0.6681 |

**The registered prediction that L-2 gains MORE than L-6 is wrong.** At the registered comparison
point — seq 256 — L-2 gains +0.0349 and L-6 gains +0.0524.

**ADR-015's weak-model reading is not overturned, it is bounded.** The length bias is a weak-model
artifact *when long documents are actually present*: at seq 512, L-2 gains +0.1048 against L-6's
+0.0612. At seq 256 the cap already suppresses most of it, and the residual bias is if anything
larger on the stronger model. **The correct statement is that the seq-256 cap hides a bias both
models carry, and hides more of L-2's.**

### 3. The truncation defect closes on a model that cannot ship — and this is the finding

ADR-015 left `MAX_SEQ_LEN = 256` standing as "do not raise on its own", with explicit length
normalization named as the only route by which raising it becomes viable. That route was tested.

| normalized (7c@0.5) | seq 256 | seq 512 | delta |
|---|---|---|---|
| **L-6 f32** | 0.6638 | **0.6638** | **0.0000** |
| **L-2 f32** | 0.6332 | 0.6114 | **-0.0218** |

The registered closing condition was non-inferiority at `delta >= -0.01`.

> **On L-6 f32 the truncation defect is CLOSED.** Raising the sequence length to 512 alongside
> length normalization costs exactly 0.0000 R@1 while recovering the 7.86% of gold turns that were
> being scored on a fragment. The equality is not trivial — the two configurations decide top-1
> differently on 9 of 229 queries and net to zero. Discordant is 2, so **no significance statement
> is available in either direction** and the delta carries the verdict, per ADR-014.
>
> **On L-2 f32 it is NOT closed**, at -0.0218 against a -0.01 bar.

**And that is the tension, stated as a finding rather than a footnote:**

> **The defect closes on the configuration that cannot ship, and does not close on the one that
> can.** L-6 f32 costs **57.0 ms/pair = 570 ms/query** at depth 10, against a 300 ms retrieval P95
> budget and ADR-003's 1-vCPU target. The shipped L-2 int8 costs 8.9 ms/pair. There is no
> configuration on the table today that both closes the truncation defect and ships.

**This is what makes fine-tuning L-2 load-bearing rather than a completeness exercise.** If domain
adaptation moves L-2 into the region where normalization holds at seq 512, the defect closes on a
shippable model. If it does not, then the honest position is that the defect is closed only in
principle, and `MAX_SEQ_LEN = 256` stays exactly where ADR-015 left it — with the 7.86% gold
truncation now understood as the price of shipping rather than as an unexamined constant.

### 4. What ships free, and what does not

The `7c` and `7f` forms need only the candidate's word-piece count, which `rerank.rs` already
computes when it encodes the pair. **No schema change, no `DERIVATION_VERSION` bump.**

The **role arms are a different matter and were flagged before they were measured**: `speaker` is
carried on the section 4.6 wire (`marlowe-contract/src/wire.rs`) and **discarded by ingest**, so
`MemoryEntry` has no role field. Shipping 7d or 7e would need the schema addition Session H made
for `occurred_at_ms`. They failed on their merits, so the question does not arise — but the check
was made in advance rather than discovered afterwards.

### ADR-017 · AMENDMENT, same session — arm 7 does not survive held-out, and the closure claim is withdrawn

**The sections above were written from fit-split numbers. The held-out read contradicts them, and
the correction is recorded here rather than by editing them.**

**1. Length normalization is a NULL on held-out, with power.** Every contrast below has alpha
attainable (discordant 24-43) and none comes close to significance:

| held-out, seq 256 | control | 7c@0.5 | delta | discordant | exact p | 7f@2.0 (post-hoc) | delta |
|---|---|---|---|---|---|---|---|
| L-2 int8 *(shipped)* | 0.5764 | 0.5764 | +0.0000 | 24 | 1.0000 | 0.5895 | +0.0131 |
| L-2 f32 | 0.6026 | 0.5939 | **-0.0087** | 30 | 0.8555 | 0.5983 | -0.0043 |
| L-6 f32 | 0.6201 | 0.6419 | +0.0218 | 43 | 0.5424 | 0.6201 | +0.0000 |

- **The registered floor of +0.01 FAILS on L-2 f32.** L-6's +0.0218 sits at the top of its
  registered band but at p = 0.5424 on 43 discordant pairs, so it is not a detected effect.
- **The post-hoc `s - 2.0*log(len)` form FAILS its registered floor of +0.02 on every cell** - and
  it is the form that looked *strongest* on fit (+0.0786 on L-2 f32, +0.0742 on L-6). That is
  exactly what post-hoc selection predicts, and exactly why the addendum pinned its held-out
  prediction before the read.

**It is not covariate shift.** The gold length distribution is the same on both splits - median 70
word pieces, p75 84, p95 239 vs 224; assistant-authored gold 8.4% vs 7.0%. The signal the
normalization exploits is present identically on held-out. The fit gain was 8 net cases of 229 at
p = 0.1516, which was already not significant, and it does not reproduce.

**2. The truncation-defect closure is WITHDRAWN as stated.** Re-read on held-out:

| normalized 7c@0.5, seq 512 vs 256 | fit delta | held-out delta | discordant |
|---|---|---|---|
| **L-6 f32** | 0.0000 | **-0.0087** | 2 |
| **L-2 f32** | -0.0437 | **-0.0611** | 16 (p = 0.0005) |

L-6 remains numerically inside the registered -0.01 bar on both splits, but the held-out margin
rests on **2 discordant cases** and the precondition - that normalization works at all - is itself
a held-out null. **"The defect is CLOSED on L-6" overstates the evidence and is withdrawn.** The
accurate statement:

> Raising the sequence length is still not viable on the model that ships. On L-6 f32 it is
> numerically neutral on both splits, but that neutrality rides on a normalization term that shows
> no held-out effect, so nothing here licenses raising `MAX_SEQ_LEN`. **It stays at 256, and the
> 7.86% gold truncation stays a known, priced defect.**

**3. What survives from the sections above.** The estimator finding - *fit a normalization term
against relevance, not against the score* - stands, because it is a statement about the measured
relationship between length, score and gold rate, and that relationship holds on both splits. What
does not survive is the claim that any of the resulting arms improves ranking.

**4. The ship/close tension is resolved in the other direction, and by fine-tuning rather than by
normalization.** See ADR-018.

---

## ADR-018 · Domain adaptation is the lever. Fine-tuning L-2 on same-session hard negatives is +0.0699 R@1 on held-out, significant, and it ships.

**Status: measured in Session J Part 2.** Held-out, paired, alpha attainable.
`runs/session-j/finetune-*.json`, `export-verification-*.json`.

### The decision

> **Fine-tuning the cross-encoder on same-session hard negatives mined from the fit split moves
> held-out R@1 from 0.6026 to 0.6725 on L-2 f32 - `+0.0699`, discordant 38 (27 gained, 11 lost),
> exact McNemar `p = 0.0139`, alpha attainable. It is the first change this project has made to the
> scored path that is significant on held-out with the power to have detected an effect.**

| held-out, seq 256, depth 10 | R@1 | delta vs own base | discordant | exact p | ms/pair | ms/query |
|---|---|---|---|---|---|---|
| L-2 int8 *(shipped today)* | 0.5764 | - | - | - | 8.9 | 89 |
| L-2 f32 | 0.6026 | - | - | - | 20.1 | 201 |
| **L-2 f32 FINE-TUNED** | **0.6725** | **+0.0699** | 38 | **0.0139** | **21.4** | **214** |
| L-6 f32 | 0.6201 | - | - | - | 57.0 | 570 |
| L-6 f32 fine-tuned | 0.6681 | +0.0480 | 43 | 0.1263 | 74.1 | 741 |

**The registered band was floor +0.02, predicted [+0.02, +0.08], derived from this project's own
fit-split evidence and explicitly NOT inherited from the research report's +0.06 to +0.10. The
measured +0.0699 lands inside it.**

### Why this is not the capacity null in disguise

ADR-015 measured capacity as a null WITH power: L-6 vs L-2 f32 gave +0.0131 at p = 0.7011. The
registration recorded in advance that fine-tuning is capacity-adjacent and that the null therefore
had to be taken seriously - and also why it does not rule this out. **The measurement now separates
the two cleanly: tripling depth buys +0.0131 and is noise, while domain-adapting the SMALLER model
buys +0.0699 and is significant.** The fine-tuned L-2 (16M parameters) beats the un-tuned L-6 (22M)
by +0.0524 held-out. The gap was never capacity.

### It ships, and that is the point

**L-6 f32 fine-tuned is the better model on fit and the worse deal on every other axis**: 74.1
ms/pair is 741 ms/query at depth 10, against a 300 ms retrieval P95 budget and ADR-003's 1-vCPU
target. **L-2 f32 fine-tuned is 21.4 ms/pair = 214 ms/query, inside the budget**, and it is also
the better model on held-out (0.6725 vs 0.6681).

**This resolves the tension ADR-017 raised** - the defect that closed only on an unshippable
configuration - though not the way that ADR anticipated. Length normalization did not survive
held-out at all. Domain adaptation did, on the shippable model, and by a margin that makes the
un-tuned L-6 irrelevant.

### Discipline, and what it cost

- **Trained on fit only.** Mined and split **by conversation id**, not query id - 3 gold sessions
  are shared between fit queries, so the two are genuinely different, and queries sharing a
  conversation are grouped inseparably.
- **Measured leakage channel, excluded rather than argued about.** 2182 haystack sessions appear in
  both splits; because negatives come only from the gold turn's own session, exactly **one** fit
  query collides and it is dropped.
- **No held-out signal touched training.** Checkpoint chosen on a fit-carved validation slice.
- **The loss is a REGISTERED DEVIATION.** MarginMSE as published distils teacher margins and this
  project has no admitted stronger teacher, so the hard-label variant is used with the target
  margin taken from the base model's own margins on cases it already ranks first. Recorded with its
  reason in the pre-registration, before training.

### The export gap is bounded, not closed

**The comparability check passed before any training**: the Xenova ONNX baseline and the
`cross-encoder/...` PyTorch checkpoint agree at Pearson **1.000000**, max |delta logit|
**0.000014**, identical R@1 - so the fine-tuning delta is measured against the existing baseline
rather than against a self-export.

All five post-export checks pass on both models: discrimination, determinism, **batch invariance
0.000000**, **padding invariance 0.000000** (ADR-015), and **torch-vs-ORT** at max |delta|
0.000003 (L-6) and 0.000001 (L-2). Training itself reproduces bit-identically under its seed.

> **It remains SELF-VALIDATED ONLY.** There is no external authority for a model this session
> trained, because this session is the publisher. What the checks establish is that the graph is
> deterministic, shape-invariant, and faithful to the module it was exported from. What they cannot
> establish is that the module is what its publisher intended. **The unvalidated-export gap is not
> closed by this - it is bounded by it, and a second instance now exists.**

### Not shipped in this session

Measurement was the deliverable, per Session I's precedent. `rerank.rs` is unchanged. Shipping this
means a new pinned digest, a `--reranking` path pointing at the fine-tuned graph, a conformance run,
and a decision about whether an f32 graph at 214 ms/query is the right trade against int8 at 89 -
including whether the fine-tuned model should be quantized, which would re-open ADR-015's
shape-binding on a graph nobody has measured that way.

---

## ADR-019 · K1 is judged on a published precision/coverage curve, the threshold is not moved, and a new kill condition is added

**Status: adopted 2026-08-08, M0b Session K.** Pinned text in `ROADMAP.md` → "K1 — amended
2026-08-08" and in brief §5.7.1. Proposal of record: `docs/requirements/proposed-K1-amendment.md`
(Part A adopted verbatim; this ADR is Part B). Measurement: `runs/session-j/RESULT.md` Part 3.

### The decision

> **K1 is measured against a published precision/coverage curve rather than a single threshold.**
> Three conditions bind — the curve ships with the product, the operating point is declared on it,
> and the abstention path is real. **The 0.95 threshold is NOT lowered**, and a **new** kill
> condition is added: a flat curve, meaning precision at 10% coverage not materially above
> precision at 100% coverage, is a project-level finding.

### 1 · The instrument could not have passed

**ADR-016, measured not derived: a perfect retrieval system scores 0.8483 on the shipped gate
against a 0.95 threshold.** Three steps, each measured on the fit split:

1. Every pooling operation in `fit_isotonic` makes a block larger, never smaller. The smallest
   expressible block is 435 rows — 1.90 candidates per query.
2. `{cue}_margin` is positive for exactly one candidate per query, so the top block is forced to be
   "one row from every query, then the least-negative rank-2s." Measured: the top block spans
   **229 of 229 queries** for both cues. **The gate has no vocabulary for confident subsets.**
3. 89 of 229 fit queries have exactly one gold row, so their rank-2 slot is necessarily a
   distractor. A perfect cue gets 229 rank-1 rows plus at most 140 rank-2 rows: 369/435 = 0.8483.

Sessions B through H each read the 0.3739 ceiling as evidence retrieval was not improving. It was
reporting a structural property of the calibration shape and would have read approximately the same
with a flawless retriever. **The honest K1 number was first produced in Session J, from a conformal
reading at query resolution — the only resolution that can express a subset.**

**This does not invalidate any retrieval measurement.** R@1, R@5, R@10, conditional accuracy, the
oracle, every closed mechanism and every failure decomposition were measured against gold turns
**with the gate uninvolved**. It invalidates the *interpretation* of one number.

### 2 · The measured answer is a real negative, not an instrument artifact

The conformal arm is not subject to §1's defect. It operates at query resolution (1/229), sets tau
at the `(1-alpha)(1+1/n)` quantile of the rank-1 minus rank-2 rerank margin, and produces a genuine
coverage curve. **It still does not reach 0.95 with a bounded interval.**

The guarantee and the measurement are reported as separate quantities throughout, because they are:
conformal at alpha=0.05 gives measured `P(inject | wrong) = 0.0133` against the 0.05 marginal bound,
and **that marginal guarantee does not cover precision conditional on having injected**, which is
the selective-risk quantity K1 asks about. Reporting one as the other would be the same category
error the isotonic ceiling was read with for nine sessions.

### 3 · More retrieval quality is not the lever

**Session J's highest-weighted finding: +0.0699 R@1 from fine-tuning bought nothing at the operating
point.** Fine-tuning dominates the precision/coverage curve from 100% down to roughly 25% coverage
and stops helping at the head — which is exactly where K1 reads.

So this amendment is not "the target was too hard and we tried our best." Nine sessions of work
established, with measurements, that the binding constraint is **separability at the head of the
ranking**, and that the rerank margin is not the signal that provides it. That is a specific
unsolved problem, not a shortfall.

### 4 · The field context, which is why there was no prior art to borrow

No published system reports injection precision at all. Headline LongMemEval results in the 90s are
QA accuracy or Recall@k. The closest independent work on admission thresholds tops out near 0.58.
Every system reaching 90%+ spends materially more than 300 ms, or performs no retrieval and keeps
the log in context. **K1 set a bar the field does not measure, at a budget the field does not meet.**
That was a deliberate and defensible choice, and it is why the answer had to be measured.

### 5 · What the amended criterion preserves

The original K1 exists to prevent one specific failure: a memory system that injects confidently and
wrongly, corrupting reasoning while appearing to work. **The amended criterion prevents the same
failure by a different route** — the curve makes precision at any chosen coverage a published number
rather than an assumption, and condition 3 forbids buying coverage with precision.

### What this ADR deliberately does NOT do

**It does not lower a threshold to match a result.** The frozen-gate discipline has held for ten
sessions specifically to prevent that, and this amendment would be worthless if it were that move
wearing a longer argument. The threshold is not moved; the *criterion shape* changes, and a kill
condition is **added**.

**It does not claim K1 was wrong.** K1 was a reasonable bar written before anyone knew what was
reachable. The measurement is what changed.

**It does not close the two remaining directions.** Both are carried forward as named work rather
than as preconditions, per the human decision of 2026-08-08 — option (a) with (c)'s directions
retained:

1. **A separability mechanism at the head.** Something must make the top decile separable and the
   rerank margin does not. Unexplored candidates: a distinct confidence signal fit against
   **relevance** rather than against score (ADR-017's rule), and set-wise or listwise scoring that
   observes candidates jointly rather than independently.
2. **The human label set.** >=400 judged injections, >=50 per category, judged blind, stratified by
   score decile. **True injection precision — the quantity K1 actually names — has never been
   computed.** Every figure to date is a gold-turn proxy. It is drawable now that a conformal
   operating point exists to sample from.

**It does not authorize skipping the abstention path.** §5.5 is precision-first with recall
recovered through the explicit `recall` tool. At a 10% operating point the other 90% must abstain
and the agent must be able to search explicitly. That is M2 work and it is now load-bearing.

---

## ADR-020 · The fine-tuned L-2 ships, the scored path moves from int8 to f32, and the loader accepts exactly one graph

**Status: shipped 2026-08-08, M0b Session K.** `runs/session-k/RESULT.md`,
`runs/session-k/export-verification-ms-marco-MiniLM-L-2-v2-ft-session-j.json`,
`runs/session-k/cue-overlap.json`. Supersedes the "measured, NOT shipped" status ADR-018 left.

### The decision

> **`rerank.rs` is re-pinned to `ms-marco-MiniLM-L-2-v2-ft-session-j/model.onnx`, f32, sha256
> `9c222dac...`. Held-out R@1 moves 0.5764 -> 0.6725 in the binary. `MAX_SEQ_LEN` stays 256,
> `BATCH` stays 1, and the loader accepts exactly one graph.**

| held-out, n=229, from the BINARY | Session H (int8) | Session K (shipped) |
|---|---|---|
| R@1 | 0.5764 | **0.6725** |
| R@5 | 0.8428 | **0.8865** |
| R@10 | 0.9039 | 0.9039 |
| input recall | 0.9039 | 0.9039 |
| **conditional accuracy** | 0.6377 | **0.7440** |
| retrieval P95, warm, full split | 149 ms | **211 ms** (budget 300) |

**`R@1 = input_recall x conditional_accuracy` factors exactly, and input recall did not move by one
case.** A cross-encoder cannot change what is in the slate handed to it, only the order within it.
The entire gain is conditional accuracy, +0.1063. Lexical, dense, `fitted_gate` and the either-cue
oracle are **bit-identical** to Session H, which is the control.

### Two deltas, and they answer different questions

**+0.0699** (ADR-018) is fine-tuned L-2 f32 against **un-tuned L-2 f32** — the contrast that
isolates domain adaptation, with the McNemar test behind it (discordant 38, exact `p = 0.0139`,
alpha attainable). **+0.0961** is what a user gets, because what was replaced was the **int8** graph.

> **Quote +0.0699 for the effect of fine-tuning and +0.0961 for the effect of this session. Do not
> quote +0.0961 as the fine-tuning effect** — part of it is the precision change, which ADR-015
> measured as a separate thing.

### The precision change removes a hazard rather than adding one

ADR-015 measured the shipped int8 graph as **shape-bound in every dimension**: bit-identical token
ids re-padded to a longer tensor moved the logit by a median 0.0109 and **padding alone flipped
top-1 in 15% of cases**, while all eight f32 graphs were invariant to 0.000000.

**Re-verified on the shipped graph, not inherited** (ADR-013's rule): discrimination, determinism,
batch invariance **0.000000**, padding invariance **0.000000**, torch-vs-ORT **0.000001**. The Rust
graph also reproduces the Python ONNX reference to 1e-3 on 8 fixture cases through a hand-rolled
pair encoder.

**Do not re-quantize this graph without re-measuring `[1, 256]`.** Shape-binding is a property of
int8 graphs and the fine-tuned graph has never been measured that way. Quantizing it re-opens
ADR-015 on an unmeasured graph — which is exactly the trade this ADR declined.

### Batch stays 1, and the REASON changed — which is why the docs were rewritten rather than patched

Session G's original reason was that int8 batch invariance failed at 0.037 logits. **That reason no
longer applies to the shipped graph.** Leaving it in place would have been a stale comment defending
a constant nobody had re-examined. Two reasons replace it:

1. **Invariance is a per-graph measurement and is never inherited.** A future re-pin arrives with no
   invariance result until one is taken, and a batch parameter in the code is a way for that re-pin
   to silently score candidates against whoever shares their batch.
2. **Batching buys nothing.** 214 ms/query against a 300 ms budget on a 1-vCPU target.

### The loader accepts exactly ONE graph, deliberately

There is **no table of accepted graphs**. A loader that accepts two lets a target string name one
scorer and measure another — the failure this project has recorded ten instances of. The superseded
int8 directory produces a **named** load error pointing at ADR-018, not a missing-file error, because
a stale `--reranking` path is the most likely way this stage gets loaded wrong. The int8 graph stays
reachable through the offline tools, which is where ablations belong.

### Two defaults deleted, and one of them had already broken something

1. **`score_longmemeval.py --reranking` defaulted to the int8 directory.** The moment the shipped
   graph moved, that default would have scored the OLD graph and written the result under the
   shipped label, with nothing observing the mismatch.
2. **`session_j_verify_export.py --out-dir` defaulted to `runs/session-j/`** — so re-running it in a
   later session **silently overwrote Session J's record of what Session J measured**. A
   verification artifact a re-run can replace is not a record.

### The export gap is bounded, not closed — and it is now on the SHIPPED path

ADR-018 recorded the fine-tuned graphs as self-validated only. **That gap has now moved from an
offline measurement into the running binary.** There is no external authority for a model this
project trained, because this project is the publisher. What stands behind the shipped graph is
digest pinning, torch-vs-ORT agreement at 1e-6, per-graph determinism / batch / padding invariance,
and a second implementation of the pair encoder reproducing HuggingFace exactly. **What none of that
establishes is that the module is what its publisher intended.** This is the first time that gap sits
on the scored path rather than beside it, and it should be stated plainly wherever the number is.

### The tokenizer is a different file, and the difference was measured

The fine-tune carries `cross-encoder/ms-marco-MiniLM-L-2-v2`'s `tokenizer.json`, not the Xenova
export's. `vocab` (30522), `normalizer`, `pre_tokenizer`, `post_processor`, `decoder` and
`added_tokens` are byte-identical; they differ only in embedded `padding`/`truncation` blocks that
`rerank.rs` implements itself and never reads. **Confirmed empirically rather than argued:** token
ids, attention mask, token type ids and the truncation flag agree on all 8 reference cases across
both vocabularies, and that agreement is now a test.

---

## ADR-021 · The status indicator is a braille amplitude meter, 6×2 cells, and it has no fallback

**Status: decided 2026-08-08, at the start of M1, before implementation.** §B5 requires the glyph
form to be decided and recorded first, because the choice is not reversible once seven states and an
acceptance suite are written against it.

### The decision

> **The status indicator is a braille column meter over U+2800–U+28FF, six cells wide by two rows
> tall — twelve horizontal samples at eight vertical levels. There is exactly one glyph set. There
> is no capability probe and no fallback.**

Braille packs 2×4 dots into a character cell. Two rows of six cells is therefore a 12×8 sample grid
in the space a 6×2 block-character meter would give 6 columns at 8 levels with no vertical
subdivision inside a row. **That resolution is the point.** It is the form `btop` and `bottom` use,
and it is the register §B0 is aiming for — an engineer opens it and thinks someone who uses
terminals every day built this.

### What was considered and rejected

**Block characters (`▁▂▃▄▅▆▇█`), rejected.** Two arguments were made for them and both were wrong.

The first was font coverage, and it is **largely stale**. Cascadia Code, DejaVu Sans Mono, JetBrains
Mono, Fira Code and the Nerd Fonts patch set all cover U+2800–U+28FF. The terminal fonts that do not
are not the fonts this product's users run.

The second was legibility — that braille is too fine to read `waiting` from across a room. That
**misattributes the work.** `waiting` is legible because three signals fire together: the indicator
**freezes**, the state name reads `waiting`, and the region goes amber. §B5's requirement is carried
by the combination, not by one glyph's stroke weight. Choosing a coarser glyph to make a single
signal do three signals' work is the wrong trade.

### The widget renders what the source reports, and animates nothing

**The widget has no animation of its own.** It draws whatever its sample source last reported and
**holds the last frame when sampling stops.** This is what makes §B5's central rule structural rather
than a special case:

> Motion means Marlowe is working. Stillness means the ball is in the user's court.

`waiting` freezes because `waiting` **stops sampling** — not because a branch somewhere disables an
animation timer for that one state. A frozen indicator is the absence of a source, which is exactly
what the state means.

| state | what the source reports |
|---|---|
| listening, speaking | microphone amplitude |
| thinking, writing | token/stream progress |
| running | elapsed against expected duration |
| **waiting** | **nothing — sampling stops, last frame held** |
| idle | a flat zero baseline, still and dim |

### M1's source is a scripted envelope, not a microphone

**Stated plainly, because §B12 forbids decorative motion and this is the seam where that could rot.**
M1 has no microphone and no model. The M1 sample source is the stub's scripted amplitude envelope.
Real data flows through the real path and the widget still invents nothing — but a scripted envelope
is not a microphone. §B12's "reports real state" is **structurally satisfied, not done.** M2 replaces
the *source*; the widget does not change.

### The cost of braille, and how it is paid

**There is no way to detect whether a font renders U+2800–U+28FF.** The terminal reports no glyph
coverage; a missing glyph surfaces as tofu, a blank, or a width-2 replacement, and none of those are
distinguishable from a correctly rendered dim frame by anything the program can measure.

**No fallback is added, and that is deliberate.** A silent block-character fallback would mean two
users see two different indicators with nothing observing the divergence — the exact class of defect
CLAUDE.md warns about, and the fifth instance of it in this project. Instead:

1. **The font requirement is documented** — a terminal font covering U+2800–U+28FF.
2. **`marlowe doctor` prints the glyph row and asks the user to confirm it by eye.** One honest
   one-time check, at a moment the user is looking, beats a silent divergence that never surfaces.

A capability probe here would be a guess dressed as a measurement. A human eye is the only instrument
that actually reads this, so the check is given to the human.

### Consequences

- The meter is a custom `ratatui` widget over a 6×2 cell rect (§B15's last row).
- Sampling is pull-based from a source trait. `waiting` is the absence of a source, not a flag.
- `marlowe doctor` is an M1 deliverable, not a later convenience.
- Any future re-decision re-opens this ADR. **Do not add a fallback to make a font problem go away** —
  fix the font, or change the decision here in the open.

---

## ADR-022 · The loop is a state machine over ports, and a subagent is that loop re-entered

**Context.** M2 builds ARCHITECTURE §3. Two shapes were available. The loop could own its
provider client, its tool executors and its journal directly, or it could take them as injected
ports. And a subagent could be a scheduler entry, or the same function called again.

**Decision. Ports, and recursion.**

`Engine::run(run, state, provenance, ports)` is the only driving loop in `marlowe-loop`.
`Ports` carries nine trait objects — driver, summarizer, tool host, memory, approvals, sink,
control, clock, recorder. A **spawn is `Engine::run` calling itself** with a fresh `Run`, a
fresh `SessionState` and a fresh `Provenance`.

**Why ports.** *"One loop, many capability profiles"* is only checkable if consolidation and a
coding turn are the same code. With a concrete provider inside the loop, a consolidation run
would need either a fake provider or its own entry point, and the second is how a second loop
gets written. It also keeps the M2 session order honest: the loop is complete and tested before
a provider client, a tool executor or a memory binding exists, and each of those absences is a
port with no production implementation rather than a branch inside the loop.

**Why recursion, given that M3 replaces it.** M2's stated lifecycle is *the parent blocks, the
child returns, the child dies with the parent*. That is exactly a call. Building a scheduler now
would be building M3's mechanism against M2's semantics and getting a queue nobody dequeues
concurrently. What matters for M3 extending rather than replacing this is the **data**, not the
control flow: `Run`, `CapabilityProfile`, `Budget` and `OrphanPolicy` are implemented in full,
and `OrphanPolicy` is recorded in the `RunSpawned` payload from the first spawn even though M2
cannot orphan anything. When M3 arrives, the journal already says what every child was supposed
to do when its parent ended.

**Depth is the bound on the recursion**, checked before a child is created. `Budget::depth`
decrements per level and `slice_for` returns `None` at zero, which the loop turns into a refusal
the model can read. Anthropic's documented deep-research failures were excessive subagent
spawning and endless loops; depth, subagent count, and a `MAX_STEPS` cap are the structural
answers, and all three are tested.

### Two refusals on `CapabilityProfile` that CONTRACTS §5 does not state

§5 pins one load-time error: `reads_untrusted && !exposed_tools.is_empty()`. Two more are
enforced, and they are **strictly narrower** — no profile that satisfied §5 is rejected unless it
also recombines a trifecta leg:

- `reads_untrusted && may_write_memory` — the empty tool set does not close memory writing,
  because the loop's own `MemoryWrite` step is not a tool. A quarantined reader that can write
  beliefs is laundering with the derivation step built in (HP6).
- `reads_untrusted && egress != DenyAll` — egress needs no tool either, if the profile grants it.

Recorded here rather than left in the code because they are additions to a pinned contract's
validation, and a later reader is entitled to know they were deliberate. If §5 should carry them,
that is a contract amendment and a separate change.

**Consequences.**

- `tests/hp10_budgets.rs` scans this crate's source and fails the build on a second driving loop.
  The exemption marker is a comment on the line, so an exemption appears in the diff.
- The layering is one-way: `marlowe-tools` then `marlowe-permission` then `marlowe-loop`. The
  permission layer reads manifests, the loop calls the permission layer before execution, and
  nothing depends on the loop except a surface (§2.14).
- A `Recorder` port rather than an `Option<Journal>`. A write path that sometimes does not write
  makes an audit trail unfalsifiable; the in-memory recorder records the same sequence.

## ADR-023 · Argument provenance is computed from the context window, never declared by the model

**Context.** ARCHITECTURE §3 calls `taint.of(args)` inside adjudication, and CONTRACTS §12 pins
`TaintSet` as per-value provenance. Neither says **who computes it**. The convenient answer is
that the model's tool call carries it, because the model knows where it got each value.

**Decision. The harness computes it, and `ModelStep::ToolCall` has no taint field at all.**

Two sources of truth, in order:

1. **Attribution.** The harness records the exact strings the user typed and the exact fields it
   itself computed. An argument whose value matches one **exactly** carries that class.
2. **The floor.** Everything else is model-composed and carries §3.3's worst-case rule applied to
   the window it was composed in: the **minimum trust class of any block in the context view**.

**A model that could label its own arguments trusted would be the security boundary**, which
invariant 3 says it is not. That is the whole argument, and it is why the field is absent from the
type rather than ignored by the adjudicator.

**The consequence, stated because it looks like a bug the first time it fires.** Once a run has
read untrusted content, **every model-composed Target in that run is blocked** — a fetched page in
the window drags the floor to `UntrustedContent`, and the (action, target) check refuses any
target that is not separately attributable.

That is §8.2's structural trifecta break arriving as a property of provenance rather than as a
second mechanism bolted beside it. The way to act on what a page said is to spawn a quarantined
reader that returns structured findings, and let the orchestrator — which never saw the page —
act. The design already required that; this makes it the path of least resistance instead of a
rule somebody has to remember.

**Matching is exact.** A value differing by a trailing space falls to the floor. A fuzzy match here
would be an attacker-shaped near-miss away from promoting untrusted text to user-asserted, and the
false-positive cost of exactness is one blocked call the user can restate.

**A child does not inherit its parent's attributions.** A fresh `Provenance` per spawn, so a string
the user typed to a parent is not user-asserted inside a child that never saw the user say it.
Without this a spawn is a laundering step. Tested.

**Rejected.** Substring or normalized matching (promotes by similarity). Per-message taint rather
than per-value (§12 pins per-value, and a call mixing a trusted recipient with an untrusted body is
the case that has to adjudicate correctly). Trusting the driver (invariant 3).

**Cost accepted, and it is real.** Research-then-act in a single run is not possible. That is the
intended shape, but it means the orchestrator-worker split is not an optimization for hard
questions — it is **required** for any run that reads the web and then does anything. If that
proves too strict in practice, the fix is a narrower attribution path for specific harness-computed
fields, argued here — not a wider floor.

## ADR-024 · Path scoping ships with its traversal suite and its handle discipline, or it does not ship

**Context.** ADR-002 (revised) removed the kernel backstop from the ordinary path, and brief §8.3
states the consequence: *"inseparable from handle-based access: canonicalize-then-open leaves a
check-then-use race, so a traversal suite passing against a check-then-open implementation reports
a boundary that is not there. The suite and the handle discipline are one requirement and ship
together."* M2 Session A had room for a path check but not for the suite and the handles.

**Decision. Session A ships no path check at all. It ships a refusal.**

`marlowe_permission::scope` contains a `PathScope` trait and exactly one implementation,
`Unavailable`, which refuses every path with a message naming the reason. The adjudicator routes
every `ParamType::Path` argument through it at **every** consequence level — path scoping is a
different question from target provenance, and the `Inert` exemption does not reach it.

**The consequence is loud and intended: `read`, `edit`, `find` and `bash` cannot run in this
build.** Their executors do not exist either, so nothing regresses; what is bought is that no path
ever passes through a check that does not exist.

**Why not a textual check now, improved later.** Because it would work. A `fs::canonicalize` plus a
prefix comparison passes every obvious test, reads as done in a review, and certifies a boundary
that a symlink planted between the check and the open walks straight through. The next session
would then be *improving* a passing check rather than *building* a missing one, and the traversal
suite written against it would be measuring the wrong thing. §8.3 calls that worse than no suite,
because it is believed.

**`ScopedPath` has no constructor from a string.** It holds an open handle and a resolved path,
both private, and the only accessor for the path is documented as *not for re-opening*. An
implementation that resolved without opening cannot produce the type the adjudicator requires.
`Adjudication` carries the handles it opened, and the tool host is expected to use them — otherwise
the check-then-use race reopens **across the permission boundary**, which is the one place a
traversal suite would not look, because the suite tests the checker and the race is in the caller.

**What Session B owes.** `openat`/`O_NOFOLLOW` on POSIX; explicit reparse semantics plus
final-handle identity verification on Windows; and the suite from ADR-002's table — relative
traversal, symlinks and junctions, extended-length and UNC and device forms, 8.3 short names, case
collisions, Win32 name munging, alternate data streams, Unicode normalization. Together, in one
session, or neither.

## ADR-025 · A source may be trimmed out of the context view only if its content is recoverable

**Context.** Brief §6 requires an explicit token budget per source, enforced by the assembler. The
obvious enforcement drops a source's oldest blocks when it exceeds its cap. Applied uniformly, that
silently evicts old conversation turns to stay under a history budget.

**Decision. Only recoverable sources are trimmable.** Tool results (behind a `ContentRef`), project
files (re-readable), skills, tool schemas, injected memory (re-retrievable) and child results may be
shortened. **Identity, governance and history may not.**

Dropping conversation turns to stay under a cap is eviction with no durable append — invariant 1's
failure — and it would present as a working budget. History pressure therefore raises `fill_pct`
until **compaction** handles it, with `SessionSummarized` and `SessionSpawned` durable first. History
keeps its budget entry, because §6 asks for per-source accounting; what the entry does not do is
authorise a silent drop.

**Nothing is omitted silently even where trimming is allowed.** A block that does not fit is replaced
by a marker naming the count; one that partially fits is truncated with a marker. A view that quietly
lacked a source would leave the model reasoning about a gap it cannot see, and would leave the
per-source accounting describing a different view than the one that was sent.

**This was found by a failing test, not by design.** The first implementation dropped any block whose
own size exceeded its source cap, which made a single large turn vanish. The test that caught it was
asserting the 70% trigger and got `fill_pct = 0.0024`. Recorded because the failure mode — a budget
that enforces correctly and loses data while doing it — is not visible from the budget's own tests.

## ADR-026 · A manifest's declared consequence is the ceiling a tool can reach, and `bash` is Irreversible

**Context.** CONTRACTS §7.3 pins `consequence` per tool. A shell tool can do anything, so the honest
declaration is `Irreversible` — which means every `bash` call needs approval, which is approval
fatigue (HP8) on the most-used tool in a coding agent.

**Decision. The declared level is the ceiling, `bash` declares `Irreversible`, and per-command
refinement is refused as a convenience change.**

Refining a shell call's consequence means parsing the command to decide whether it is safe. That is
the Cursor CVE in brief §8.1 exactly: *"an allowlist made the attack easier by auto-approving exactly
the commands the attacker needed."* A command classifier is an allowlist with extra steps, and its
failure mode is silent.

This is not a claim that `bash` must always block. It is a claim about **where** the relief comes
from: M6's trust ledger, per action class, on observed agreement evidence, with novelty gating and
hard ceilings — mechanisms that accumulate evidence about a class rather than pattern-matching a
string. Until then the honest behaviour is to ask.

**The rest of the column, with reasons, is in `crates/marlowe-tools/src/builtin.rs`.** Two entries are
worth naming here because they are the ones a reader will question:

- **`web` is `Inert`.** §9's own example: following a link found on a page is how research works. Its
  containment is three non-kernel mechanisms — the result returns `UntrustedContent`, it returns by
  reference (`inline_threshold_bytes: 0`, never inlined), and egress allowlisting closes the
  exfiltration leg. ADR-002 records that if any one weakens, this is revisited rather than inherited.
- **`use` is `Reversible` rather than `Inert`, specifically so its target check fires.** Loading a
  skill chosen by untrusted content is supply-chain steering, and §9 checks `Reversible`.

**And one role assignment carries more weight than the rest: `bash.command` is a `Target`.** It is not
body content a tool happens to carry — it *is* the action. As a `Payload` it would be unchecked by
design, and untrusted content composing a shell line would pass.

## ADR-027 · Containment is the handle walk; the string check is the weaker of two walls, and it is named as such

**Context.** ADR-024 deferred path scoping until it could ship with its traversal suite and its
handle discipline. This is what shipped. ADR-002 removed the kernel backstop, so everything below
is the only wall there is.

**Decision. Three parts, in a fixed order, and the third is the one that contains.**

| Part | Job | Strength |
|---|---|---|
| `scope::request` | refuse ambiguous **spellings** before any syscall | weak — it only closes forms where two strings name one file |
| `scope::glob` | decide whether a well-formed request is inside what the manifest declared | weak — it is a comparison on a string nobody has resolved yet |
| `scope::walk` | open it without ever letting a string be resolved twice | **this is the containment** |

The order is ADR-002's *"canonicalize before the check, never after"*, taken to its strongest
reading: **the hostile string is never canonicalized at all.** It is validated, matched against the
declaration, then *walked* — the kernel resolves one component at a time under supervision. There is
no moment at which a resolved string exists and is trusted, so there is nothing for a check to be
performed against and then invalidated.

### The walk, per platform

**POSIX.** `openat` from the parent's descriptor, one component at a time, with `O_NOFOLLOW`. A
symlink in any position fails with `ELOOP` rather than being followed. There is no string for anyone
to swap: each step names a single component relative to a descriptor already held. `rustix` supplies
the safe wrapper; std exposes no handle-relative open, and without one this walk is not expressible.

**Windows.** There is no `openat` in Win32, so containment comes from **pinning**: every directory on
the path is opened with a share mode that **excludes `FILE_SHARE_DELETE`**, and every handle is held
for the whole walk. A directory cannot be renamed or deleted while such a handle is open, so the
prefix cannot be swapped underneath the next open. Each component is additionally opened with
`FILE_FLAG_OPEN_REPARSE_POINT` and refused if it carries `FILE_ATTRIBUTE_REPARSE_POINT` — junctions
and symlinks are caught rather than traversed. The root's identity (volume serial + file index, via
`same-file`) is compared before and after.

**Rejected: `NtCreateFile` with a `RootDirectory` handle**, which is the true `openat` equivalent on
Windows. It would remove the reliance on share-mode semantics, and it costs an `ntdll` FFI surface
and `unsafe` in the one crate where a memory-safety bug would be worst. Pinning plus reparse refusal
plus identity verification is three independent mechanisms in safe Rust, and the TOCTOU test
exercises the first of them directly. If a future measurement shows pinning failing on some
filesystem, this is the decision to revisit.

**Rejected: `cap-std`.** Capability-based, well-maintained, and it solves exactly this. It was not
adopted because the direction given was explicit about the primitives, and because a dependency here
would move the wall into a crate whose changes this project does not review. Recorded so that the
option is visible rather than merely unused; if hand-rolled Windows containment ever looks shakier
than a reviewed dependency, that trade should be made deliberately.

### The TOCTOU test races, and it proves it races

The requirement is that a suite must not pass against a check-then-open implementation. So
`tests/toctou.rs` contains one — `naive_check_then_open`, which canonicalizes, verifies the result
is under the workspace, and then opens by path — and **asserts that it escapes**, returning the
contents of a file outside the workspace.

That is the load-bearing half. Without it, a green suite is equally consistent with a test that never
landed in the window at all, and "the boundary held" would be indistinguishable from "the attack
never ran".

**The interleaving is deterministic, not hopeful.** The walk calls a `WalkObserver` at exactly the
instant a race must land — after component *k* is open, before *k+1*. In production the observer is
`()`, a zero-sized no-op. A thread racing a resolver and hoping to hit a microsecond window is a test
that passes for the wrong reason most of the time.

**And the mechanism is asserted, not only the outcome.** On Windows the test asserts the swap fails
*with a sharing or access violation* — the pinning firing. A swap that failed because `mklink` was
missing would leave the outcome assertion green while measuring nothing.

### What is verified, and where — measured on both platforms

| | Windows 11 (MSVC) | Linux (WSL2 Kali, ext4) |
|---|---|---|
| String-level classes | run | run |
| Junction / directory-link escape | run | run (as symlink) |
| **Symlink escape** | **cannot run — needs Developer Mode or elevation (os error 1314)** | **run** |
| TOCTOU race, incl. the naive-escapes control | run | **run** |
| Windows pinning mechanism assertion | run | n/a |
| Suite under `MARLOWE_TRAVERSAL_STRICT=1` | **fails** (symlink class unrunnable) | **passes**, 11/11 classes `RAN` |
| Totals | 414 workspace tests | 62 crate tests |

**Both gaps that this ADR originally recorded as open are closed.** The POSIX `openat`/`O_NOFOLLOW`
walk executed for the first time on WSL2 at the close of Session B, and the symlink class ran there.
`the_naive_implementation_escapes_which_is_what_makes_this_a_race` passes on Linux as well, so the
race window is demonstrably real on Linux and `O_NOFOLLOW` demonstrably closes it — the same pair of
assertions the Windows run makes about pinning.

**The command, so it does not need a script:**

```bash
# Windows
cargo test -p marlowe-permission
# Linux, from the same checkout. A separate target dir keeps the Windows one intact and puts
# build artifacts on ext4; fixtures already live in $TMPDIR, which must not be on DrvFs --
# /mnt/c does not have Linux symlink or openat semantics, so a suite run there measures DrvFs.
wsl -d <distro> -- bash -lc 'cd /mnt/c/<repo> && CARGO_TARGET_DIR=/tmp/marlowe-target-linux   MARLOWE_TRAVERSAL_STRICT=1 cargo test -p marlowe-permission'
```

**This is a standing requirement, not a one-time closure.** Any change under `scope/` re-runs both.
Windows alone leaves the symlink class unrunnable; Linux alone never exercises the pinning. A
single-platform green is a half-measured wall, and the halves do not overlap.

### A suite of refusals can be passed by refusing everything

M2 Session A shipped a scope that refused every path, and it would satisfy every negative assertion
in this suite. So the suite carries **positive controls**: a legitimate deep read, a narrow
declaration admitting its own subtree, and filenames that merely look dangerous (`console.log`,
`nullable.rs`, `a..b.txt`) which must all open. Without them the suite measures whether a scope is
present, not whether it is correct.

### Accepted costs, each with its false positive

- **8.3 short names are refused by shape**, so a legitimate `backup~1.txt` is refused and must be
  renamed. The alternative is a second spelling of a path that a glob written against the long name
  does not match.
- **Unicode normalization is the one thing here that is normalized rather than refused.** Refusing
  non-NFC would make legitimate macOS filenames unreachable, with no attacker behind it. Both the
  request and the glob are normalized to NFC, and the normalization is applied to both sides of one
  comparison rather than to a value used for something else. Homoglyph separators are a different
  problem and *are* refused.
- **A backslash is a separator on every platform**, so a POSIX filename containing one is split.
  That fails closed — the request reaches a deeper, narrower path or is refused, never a wider one.
- **The glob language is two wildcards.** No `?`, no classes, no braces, no negation. Every one is a
  feature whose interaction with the others must be reasoned about, on a comparison that decides
  whether a path is inside a security boundary.

### A guard whose subject moved is no guard, and it says nothing

**This is the fourteenth instance of the adjacent-measurement family and the first where the guard
itself is what quietly stopped existing.** CLAUDE.md carries the generalised form.


Splitting `scope.rs` into `scope/{mod,request,glob,walk}.rs` made the brief §13 hook's entry name a
file that no longer existed. **Path scoping was silently unguarded**, and nothing reported it — the
same family as every other unobservable mismatch this project has logged.

Two changes: the entry is now a **directory** prefix, which survives a split; and the hook grew a
`--self-check` mode that fails when any guarded path does not exist, run by
`marlowe-permission/tests/boundary_hook.rs` so it fails the build. A negative control confirms the
check is not decorative — renaming a guarded file makes it fail by name.

---

## ADR-028 · Supersession detection: the signal is present, the extraction is missing

**Status: NOT BUILT. The verdict is about SCOPE, not about the mechanism — supersession is BLOCKED,
not dead.** Measured on the fit split before anything was implemented. Three measurements make the
argument and separately none of them does: `runs/session-m0c/reach-r6-supersession-ceiling-fit.json`
(the ceiling), `reach-r7-separability-fit.json` (the similarity floor), `reach-r8-valueconflict-fit.json`
(the value-conflict probe and its unanchored collapse).

**Context.** §4.3's supersession exclusion is correct, wired and unit-tested (`entry.rs:124`, called
at `retrieve.rs:328`). It is also blind: the only writer of `superseded_by` is consolidation's
near-duplicate merge at cosine ≥ 0.98, `ingest.rs:142` hardcodes `None`, §4.6's `IngestRequest` has
no supersession field and forbids extras, and `store.rs:133` defers the contradiction detector.
§5.7's entire harm argument assumes a component that has never existed.

### The cost model, registered before any threshold was measured

**A false supersession removes a live memory from injection permanently and silently. A missed
supersession leaves a stale one injectable, where it surfaces as a wrong answer.** These are not
symmetric. Merges are reversible via the `supersedes` edge (HP5, ADR-012), so a false supersession
is recoverable — but it does not announce itself, and a silent permanent removal is worse than a
visible stale injection. **The threshold is chosen against the false-positive direction, not against
F1.** Parity — one false supersession per correct one — is the floor, not the target.

### 1. The ceiling, measured first

A perfect oracle marking every stale knowledge-update belief superseded, simulated at the
**candidate-set** level so a surviving candidate is promoted into the freed slate slot:

| fit, n = 229 | shipped | perfect oracle |
|---|---|---|
| R@1, current-value only | 0.6900 | **0.7162** (+0.0262) |
| knowledge-update R@1, current-value only | 0.3056 | **0.4722** (+0.1666) |
| harm rate | 0.0742 | **0.0218** (−71%) |
| precision at the operating point | 0.9130 | 0.9565 |
| top-1 changed | — | 15 of 229 |

**This is what is at stake if the blocker is ever removed**, and it is why supersession is recorded
as blocked rather than closed.

**ADR-014, and it is a stop signal on the statistical claim.** The oracle produces exactly **6
discordant** — the bare minimum at which α = 0.05 is attainable — and reaches p = 0.0312 *only*
because all 6 fall one way. A detector at half the ceiling gives 3 discordant, where the smallest
attainable p is 0.25. One with 6 gains and a single false supersession gives 7 and p = 0.125.
**Significance would need ≥ 9 discordant, more than a perfect oracle produces.** α is declared
unattainable in advance for every real arm; the delta carries the verdict alone.

**ADR-013, stated so it is not inherited.** The oracle's read is one-directional — gained 6, lost 0 —
and that is *structural*: an oracle only removes definitionally-stale turns. A real detector moves
both ways and its instrument check must be re-run on its own contrast, never on the oracle's.

### 2. Signal 2 — temporal precedence on high similarity — is DEAD, and the cost model is why

Cosine between the 33 true supersession pairs and the 15,789 pool turns they must be separated from:

| threshold | recall | false positives | precision |
|---|---|---|---|
| **0.98** — ADR-012's duplicate bar | **0 of 33** | 0 | — |
| 0.95 | 0 of 33 | 3 | 0.0000 |
| **0.85** | 14 of 33 | 174 | **0.0745** — best anywhere on the grid |
| 0.75 | 33 of 33 | 1,874 | 0.0173 |

**Best precision anywhere is 0.0745**, which under the registered cost model destroys roughly
**twelve live memories per correct supersession**. That is not a threshold to tune; it is a signal
that is absent. The true pairs sit inside the distractor distribution — median true cosine 0.8284
against a distractor p99 of 0.8526 — and the true partner is the nearest neighbour in **1 of 33**
cases, median rank 7 of a 479-turn pool.

> **`0 of 33` at cosine 0.98 is the quantitative reason the current merge is blind**, and it is the
> number to quote. ADR-012 measured ≥ 0.98 pairs at 0.0086% of 30.6M and recorded that LongMemEval
> distractors are "topically related rather than textually duplicated". This is that finding
> localised to the pairs supersession actually cares about.

### 3. Signal 1 — entity-relation conflict — is PRESENT, and the missing half is identity

Real entity and relation extraction does not exist in this workspace, so what was measured is an
approximation: context Jaccard × value-token disjointness, over numbers, times, money and
non-sentence-initial capitalised words. **What it cannot see, stated before the result:** a
supersession whose value is a common noun (tea → coffee); a turn recapping the old value while
stating the new; negation and hedging; and anything requiring the *relation* to be identified. It
abstains on 7 of 33 true pairs because one side carries no extractable value.

| | anchored on the true stale turn | **unanchored, as a detector runs** |
|---|---|---|
| pairs considered, 34 fit cases | 15,789 | **3,941,120** — 241× more |
| true positives at threshold 0.20 | 4 | 4 |
| false positives | 6 | **~1,539** |
| **precision** | **0.4000** | **0.0026** |

**Precision collapses 154× when the anchor is removed, and that collapse is the finding.**

> **0.4000 was never a detector's number. It is the value-comparison rule's precision *conditional
> on already knowing which two beliefs are about the same thing*.** The rule was not *detecting*
> supersession — it was *verifying* it, given a candidate something else had found. Those are two
> components and only one of them was probed. Unanchored, "same context, different value" fires on
> about fifteen hundred unrelated pairs per 34 cases.

> **Verdict: signal present, extraction missing.** Not "supersession is undetectable on this
> corpus". Value conflict beats similarity **6×** when anchored (0.4444 against 0.0745), and the
> entire gap between anchored and unanchored is the same-thing question. What is missing is the
> component that narrows 3.9 million pairs to a handful before the value comparison runs.

**Two honest limits on that verdict.** The anchor is *stronger* than entity resolution — it names one
turn, where identity would yield a candidate set — so 0.4000 is an **upper bound** on what identity
buys, not an estimate. And even at 0.4000 the rule sits at 4 true against 6 false, below the parity
floor. Whether a real (entity, relation, value) comparison clears the bar is **not measured, and
cannot be** without building the component.

### 4. The missing component already has a design, and it was never built

**HP2 specifies it:** *"Identity is a belief, not a lookup. Sameness is an `Edge { rel: SameAs }`
memory entry with confidence and provenance, produced by consolidation and correctable in plain
speech. Blocking on normalized surface form and channel address; scoring on embedding similarity,
co-occurrence, temporal contiguity, and handle match."* `Payload::Entity` and `Payload::Edge` exist
in §3.2. The slot is there; nothing fills it.

**Recorded, not scoped — this session does not design it.** Entity resolution is HP2 and needs its
own registration and its own reachability check. What is worth writing down is that it would touch
the ingest path, mint `Payload::Entity`/`Edge` beliefs in consolidation, and — because consolidation
mints no new belief today — would be **the first live exercise of trust propagation through a
derived belief**, which STATE.md carries as unexercised and which needs its own test.

### Decision

1. **Supersession detection is not built, and no approximation is shipped to avoid a null.**
2. **Signal 2 is CLOSED** on this corpus, on the cost model, with 0.0745 and the 0-of-33 as the record.
3. **Signal 1 is OPEN and BLOCKED on HP2 entity identity**, not on a threshold. Supersession is
   **blocked, not dead**: the ceiling says it is worth +0.1666 on knowledge-update and a 71% cut in
   harmful injections if it is ever unblocked.
4. **§4.3's exclusion is untouched.** It is correct. It has no edges because nothing produces them.
5. **The tripwire ships regardless** — `tools/tripwire_head_composition.py`, baselined at
   `crates/marlowe-memory/artifacts/head-composition-baseline-v1.json`.

**Closing condition, named now so a later session need not invent one:** supersession detection
reopens when HP2's `SameAs` edges exist, and closes when a value comparison over (entity, relation)
triples clears **precision ≥ 0.5 measured UNANCHORED** — parity under the registered asymmetry — at
a recall that moves the ceiling by more than one case. Anything below parity fails the cost model
regardless of its recall, and any figure measured anchored is not the number this condition asks for.

### 5. The consequence for §5.7, which is the finding of this whole line of work

With supersession unreachable on this corpus with available components, **harm being zero at the
operating point is the only protection that exists, and it is accidental.** It holds because the
head contains ~0% knowledge-update queries against a 15.7% base rate — a category-exclusion side
effect of those queries being low-confidence (median margin 0.2782 against 0.4020), not a harm-aware
mechanism. Within knowledge-update the margin's relation to harm flips sign between splits.

**It is fragile in two named directions.** Coverage rising pulls lower-confidence queries into the
injected set. Knowledge-update confidence improving pulls that category into the head — R6 measured
exactly this, a perfect oracle taking the fit knowledge-update share of the top decile from **4.3%
to 13.0%**. Either removes the protection with no component reporting a change.

> **The tripwire is therefore load-bearing rather than diagnostic.** It is the only thing standing
> between §5.7's guarantee and a silent regression. It TRIPs on any harmful injection at the
> operating point against a baseline of zero, and WARNs when the knowledge-update share reaches the
> base rate — the point at which the harm figure must be re-measured rather than inherited.
>
> And **`0 of 23` is reported with its interval every time.** Its Clopper-Pearson upper bound is
> **0.1482**. Three configurations agreeing on zero is three configurations agreeing on a number
> that cannot distinguish zero from one in seven.
