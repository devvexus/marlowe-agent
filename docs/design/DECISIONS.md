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
2. **Rubber-stamping is measured** (§B6): approval latency and approve-without-expand rate,
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

**Canonicalize first, then check. Never check, then canonicalize.** Every comparison happens on
the fully resolved path: symlinks and reparse points followed, relative segments collapsed, case
folded on case-insensitive volumes, extended-length and UNC forms normalized. A check performed
against the string the model supplied is a check against an attacker-chosen encoding of a path,
not against the path.

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

**Consequence for M1.** The §B9 suite must still run on native Windows Terminal *and* on a Linux
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
