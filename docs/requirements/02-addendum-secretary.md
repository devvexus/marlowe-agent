# Marlowe Addendum A: The Secretary Layer

**Companion to:** Marlowe — Requirements for a Memory-First Agent Harness (v1.0)
**Status:** Requirements specification.
**Read v1.0 first.** That brief specifies the engine. This one specifies the person.

---

## A0. Why This Addendum Exists

Brief v1.0 specifies *capability*: memory, tools, orchestration, research, voice, automation, security. Everything in it is necessary. None of it is sufficient.

A secretary's value was never capability. It is **access, initiative, and earned trust**. A person with a perfect memory, excellent research skills, and no access to your calendar is a consultant. A person with access but no initiative is a search box. A person with access and initiative but no earned trust is a liability you supervise so closely they cost more than they save.

This addendum specifies the three things v1.0 left out, plus the four operational requirements added since: automated app connection, automation transparency, universal reach, and onboarding that works for someone who has never configured anything.

**Design rule for this entire layer:** every requirement here must work for a user who does not know what an API is, has never seen a terminal, and will not read documentation. If a capability requires technical literacy to access, it does not exist for most of the people who need it.

---

## A1. Competitive Landscape — The Secretary Category

Different competitors than v1.0. The harness competitors (Hermes, OpenClaw, Claude Code) do not play here. These do:

**Lindy** — relaunched February 2026 from no-code agent builder to personal executive assistant. Connect Gmail or Outlook and it triages autonomously, drafts in your voice, schedules, preps you before calls, records meetings, sends a daily brief. Operated heavily through iMessage and SMS. Thousands of integrations. **Soft spots:** cloud-only, no local file access, opaque usage metering with overage multipliers, and — per its own reviewers — it is an assistant you *supervise* rather than one you *delegate to*.

**alfred_** — autonomy-first, overnight email triage, voice-matched drafts, calendar management, task extraction, daily brief, Gmail and Outlook. Positions on the autonomous-vs-reactive split: reactive tools idle between uses, autonomous ones compound.

**Carly** — the sharpest single idea in the category: **each agent gets its own real email address.** You CC it on a thread and it replies to your client directly, negotiates times across calendars, books, follows up, updates the CRM. That is delegation, not supervision, and it is the correct target.

**Martin** — voice-first proactive scheduling, Slack and email.

**Vellum** — on-device, persistent identity, and **credentials the model can never read**. That last property is architecturally important and most competitors do not have it.

**Motion / Reclaim** — calendar specialists. Narrow, but they own the schedule aggressively and users like it.

**Gemini / Copilot Daily Brief** — strong inside one ecosystem, degrades sharply outside it, and assists inside apps rather than acting across them.

**The structural gap in all of them:** every one is either cloud-only-with-integrations (no local files, no code execution, no deep research) or local-and-capable (no inbox, no calendar, no ambient presence). **Nobody has both.** v1.0 specifies the capable half. This addendum specifies the other half. Building both in one system, with one memory, is the position no competitor currently occupies.

Secondary observation: the whole category reports time-savings against the ~11.7 hours per week knowledge workers spend on email. That is the benchmark users will judge against, whether or not we choose it.

---

## A2. S1 — The Connection Layer

*"Easy to connect it to your apps, should be automated."*

This is the requirement that determines whether the system is a secretary or a chatbot, and it is where the most engineering discipline is required because credentials are involved.

### A2.1 Architecture

- **Managed auth broker, credentials never in the model.** The agent holds a *connection ID*, never a token. Credentials stay server-side, encrypted at rest, injected at the transport layer at call time. The model cannot read, log, echo, or exfiltrate a credential because it never has one. This is the single most important security property in the entire secretary layer — it makes credential leakage structurally impossible rather than probabilistically unlikely.
- **Do not build the OAuth broker.** The auth-aggregation layer is a solved, maintained, thankless problem: hundreds to ~1,000 pre-built connectors, token refresh, multi-tenant isolation, per-provider quirks. Integrate a managed or self-hostable broker (the Nango/Composio/Arcade class) behind our own abstraction so it stays swappable. Building connector maintenance in-house is a permanent tax with no differentiation.
- **Support MCP Auth for spec-compliant servers** alongside classic OAuth, API keys, and JWT, through one flow. The user should never learn which auth type an app uses.
- **Just-in-time authorization checks before execution.** Verify the connection is live and scoped *at call time*, not at connect time. Expired tokens must produce a clean re-auth prompt, not a failed task and a confused user.
- **Self-hostable path required.** A secretary with inbox access is the highest-trust software a person installs. Some users will not accept a cloud broker, and they are not wrong.

### A2.2 Connection UX — "should be automated"

- **Detect, don't ask.** On setup, the system infers the likely stack from a single signal — the email domain, the OS, the default browser's signed-in accounts — and proposes: *"Looks like Google Workspace and Slack. Connect those?"* One tap.
- **Progressive connection, driven by need.** Do not present a 900-app directory on day one. When the user asks for something that requires an unconnected app, the agent asks for that one app, in context, at the moment its value is obvious: *"I can do that — I need your calendar. Connect?"* Connection requests earn their interruption.
- **Bundles, not apps.** The user thinks in jobs, not integrations. Offer "Email & Calendar," "Team Chat," "Files," "Notes & Tasks," "CRM." One tap connects the bundle.
- **Scope minimization, stated in plain language.** Request the narrowest scope that does the job and say what it means: *"Read and send email as you. It cannot delete anything."*
- **Connection health is visible and self-healing.** A broken connection surfaces proactively with a one-tap fix, before a task fails because of it.
- **One-tap revocation, per app, with a stated blast radius:** *"Disconnecting Gmail stops 4 automations. Show me."*

### A2.3 Tool exposure under many connections

Connecting 20 apps must not put 400 tools in the context window. v1.0 §4 caps model-visible tools at 12; connections do not change that.

- Connectors register into the registry; exposure stays budgeted and task-scoped.
- Prefer **high-level intent tools over low-level API wrappers**. `schedule_meeting(with, duration, constraints)` beats eleven calendar endpoints — it reduces hallucination, token cost, and failure surface simultaneously.
- Tools are found via search, loaded on demand, and dropped when the task ends.

### A2.4 Acceptance criteria

| Metric | Target |
|---|---|
| Time from install to first connected app | < 90 seconds |
| Taps to connect a bundle | ≤ 3 |
| Credential exposure to model context | Zero, structurally enforced and tested |
| Connection failure surfaced before task failure | 100% |
| Model-visible tools with 20 apps connected | ≤ 12 |
| Broken-connection self-heal without user action | > 80% |

---

## A3. S2 — Identity: Acting *As* You

Drafting is a different capability class from sending. Sending under your name requires a model of you.

- **Voice model, learned from sent mail, not described in a settings panel.** Formality gradient per recipient, greeting and sign-off conventions, sentence length, the things you never say, how you decline, how you chase, how you apologize. Learned from the user's own outbound history with explicit consent, held as procedural memory (v1.0 §5.2).
- **Voice is per-relationship, not global.** How you write to your co-founder is not how you write to a vendor. Store voice parameters on the relationship edge (§A4), not on the user.
- **Drafts are labeled by confidence.** *"I'd send this as-is"* versus *"you should read this one"* — and the labels must be calibrated, meaning measured against how often the user actually edits each class. An uncalibrated confidence signal is worse than none.
- **The agent's own identity, addressable.** Adopt the strongest idea in the category: **the assistant has its own email address and its own handle on messaging platforms.** You CC it into a thread and it participates — negotiating times, chasing replies, confirming details — visibly, as an assistant, not impersonating you. This is the concrete difference between an assistant you supervise and one you delegate to, and it sidesteps the impersonation problem entirely for multi-party coordination.
- **Impersonation boundary, hard-coded.** Sending *as* the user is a distinct permission from sending *as the assistant*, defaults off, is granted per channel, and is never promoted automatically by the trust ramp (§A8). Some lines are not earned; they are chosen.
- **Attribution never lies.** The system does not deny being an AI when directly asked, in any channel, under any autonomy tier.

---

## A4. S3 — The People Model

Not facts about people. The social graph, with obligations on the edges.

```
Person { id, names[], handles{channel: address}, org, role, timezone }
Relationship {
  person_id, closeness, formality_level, response_sla_expected,
  last_contact, contact_cadence_norm, voice_params,
  open_threads[], owed_by_me[], owed_to_me[],
  do_not_contact_windows[], notes[]
}
```

Requirements:

- **Built from observed interaction**, not manual entry. The user will never fill in a CRM.
- **Cadence norms and drift detection.** The system knows you talk to this person roughly monthly and notices when it has been three.
- **Obligation tracking on the edge** — what you owe them, what they owe you. This is the substrate for §A6.
- **Entity resolution across channels.** The same human is an email address, a Slack handle, a phone number, and a name in a calendar invite. Cross-session identity is a named open problem (v1.0 §14.2) and it bites hardest here.
- **Fully inspectable and correctable.** The user can open the people model, read what the system believes about a relationship, and fix it. Per v1.0 invariant 5.
- **Privacy-scoped.** People data does not cross profile boundaries. Work contacts stay in the work profile.

---

## A5. S4 — Noticing (Undeclared Triggers)

v1.0 §11 specifies triggers: schedule, event, condition, manual. All declarative — the user has to think of them first. A real secretary's value is the thing you never asked for.

**Required: a background salience process** that evaluates world-state against user goals on a cadence and surfaces what a competent assistant would raise unprompted.

Target classes:

- **Conflict** — "Your 3pm just became impossible; the flight lands at 2:50."
- **Silence** — "You asked them for the contract eight days ago. Nothing back."
- **Approach** — "That renews Tuesday and auto-charges."
- **Drift** — "You haven't talked to your biggest client in six weeks; your norm is two."
- **Preparation** — "Tomorrow's meeting is with someone you last met in March; here's what you discussed and what you promised."
- **Pattern break** — "You've moved this task four times. Kill it or schedule it properly?"
- **Anomaly** — "This invoice is 3× the usual amount."

Design requirements:

- **Salience is scored, thresholded, and budgeted.** A daily cap on unprompted interruptions, enforced. Being right is not sufficient justification for interrupting.
- **Batched by default, interrupt by exception.** Most noticings belong in a daily brief. Only time-critical items break through, and "time-critical" is a defined predicate, not a vibe.
- **Every noticing is rated.** The user's dismissal is training signal. **Track precision per noticing class and suppress classes that consistently miss.** This is the only defense against a system that cries wolf into irrelevance.
- **Noticing is explainable on demand.** *"Why did you tell me this?"* returns the actual reasoning and the memories involved.
- **This is the hardest requirement in the addendum.** It is the salience problem from v1.0 §14.1 with a higher cost of error, because a wrong proactive interruption is more expensive than a wrong retrieved memory. Prototype it early.

---

## A6. S5 — Commitments and Loop Closure

Agents complete steps. Secretaries close loops.

```
Commitment {
  id, description, direction: owed_by_user | owed_to_user,
  counterparty_id, source: {channel, message_id, extracted_at},
  expected_by, confidence, status: open | chased | fulfilled | dropped | renegotiated,
  chase_policy: {after, escalation_ladder[], max_chases},
  evidence[]   // what closed it, or what proves it is still open
}
```

Requirements:

- **Extracted automatically** from email, chat, meeting transcripts, and voice. "I'll send that over Thursday" is a commitment whether or not anyone logged it.
- **Both directions tracked.** What you owe and what you are owed. The second is where most value sits, because it is the part humans drop.
- **Chase policy per commitment,** with autonomy tiering (§A8): draft the chase, send the chase, escalate the chase.
- **Closure requires evidence,** not assumption. A commitment closes when something observable happened — a reply, a file, a calendar entry — not because time passed.
- **The open-loop list is a first-class user-facing view.** This is the artifact that makes the system feel like a secretary rather than a tool. It is the thing that, when a user sees it for the first time and it is *correct*, converts them.

---

## A7. S6 — Escalation Judgment

When to interrupt, when to handle it, when to queue it.

- **Threshold-based escalation on measurable signals** — retry count, tool-call count, elapsed time, spend, and calibrated confidence. Exceeding a limit escalates rather than looping. Non-converging retry loops are a known failure signature and must be bounded structurally, not by hoping the model stops.
- **Escalation carries a decision package**, never a raw trace: what it was doing, where it stopped, what it needs, the two or three options, and its recommendation. A one-tap answer must be possible from a phone.
- **Calibrated abstention.** The system must be able to say "I'm not confident enough to do this." v1.0 §5.5 requires abstention for memory; this requires it for action. Fluent, confident, wrong is the characteristic failure of long-horizon agents.
- **Escalation policy is learned per action class,** from whether the user's answer matched what the agent would have done. Over time, classes with high agreement stop escalating (§A8).
- **Right channel, right urgency.** Push for time-critical, batch for routine, and never wake someone for something that keeps until morning. This is an explicit policy the user can see and adjust.

---

## A8. S7 — The Trust Ledger (The Crux)

**This is the mechanism that makes everything else possible.** v1.0 specified tiered autonomy but no way to move between tiers. Without an evidence-based ramp, the user never grants meaningful autonomy, every capability above stays theoretical, and you have built a very sophisticated draft generator.

### A8.1 The ladder

Per **action class** — not per app, not globally. "Reply to routine scheduling email" is a class. "Send a contract" is a different class.

```
0  Observe   — records, surfaces nothing
1  Suggest   — proposes in the brief, user acts
2  Draft     — prepares the action, user reviews and fires
3  Confirm   — executes on one-tap approval
4  Act       — executes autonomously, reports after
5  Silent    — executes autonomously, appears in the log only
```

### A8.2 Promotion and demotion

- **Shadow mode is the default entry point for every new class.** The agent proposes; the human disposes; the system records agreement. Shadow mode is the single most important discipline in agentic deployment — it surfaces missing data, hallucination classes, fragile integrations, false escalations, injection exposure, and the hidden correction work users do silently. Run it before autonomy, always.
- **Promotion requires evidence, is proposed to the user, and is never self-granted.** Proposal form: *"I've drafted 23 scheduling replies. You sent 21 unedited, edited 2 lightly, rejected 0. Want me to send these without asking?"* The user decides. The evidence is the argument.
- **Promotion thresholds are per-class and reversibility-weighted.** Reversible actions promote on modest evidence. Irreversible ones require far more, and some — money movement, contract execution, sending as the user, anything legally binding, anything touching the permission system itself — have a **hard ceiling below full autonomy that no amount of evidence lifts.**
- **Demotion is automatic and immediate.** A user correction, an undo, a complaint, or an error demotes the class instantly and re-enters shadow mode. Demotion is silent and fast; promotion is slow and asked-for. Asymmetry is the point.
- **Every autonomous action carries an undo** where the medium allows, and where it does not (a sent email), that class faces a higher promotion bar.

### A8.3 Automation complacency — design against it

Trust ramps have a documented failure mode running the other way. Anthropic's own usage data shows experienced users auto-approve actions in over 40% of Claude Code sessions — roughly double the ~20% rate of new users. Human-factors research on automation complacency is unambiguous: **the more reliable a system appears, the less vigilant its overseers become.** Users rationalize anomalies and stop questioning outputs, and this is worse in high-performing systems than in mediocre ones.

Required countermeasures:

- **Periodic verification sampling.** Occasionally surface a completed autonomous action for explicit review even at tier 4–5. Frame it honestly: *"Spot check — I sent this yesterday. Right call?"* Sampling rate scales with consequence.
- **Drift detection.** If agreement rate in a class declines, demote before the user notices. Do not wait for a complaint.
- **Novelty gating.** An action that is unusual *for its class* — unfamiliar recipient, unusual amount, first-time counterparty — drops one tier automatically regardless of the class's standing.
- **Never present confidence the system has not earned.** Calibration is a shipping requirement, not a polish item.

### A8.4 Acceptance criteria

| Metric | Target |
|---|---|
| Classes at tier ≥3 after 30 days of typical use | ≥ 5 |
| Promotion proposals accepted by user | ≥ 70% (low = miscalibrated evidence) |
| Post-promotion correction rate | < 5% per class |
| Time from user correction to demotion | Immediate, same session |
| Self-granted promotions | Zero, structurally impossible |
| Confidence calibration error (stated vs. actual) | < 10% |

---

## A9. S8 — The Automation Dashboard

*"Easy to track and see how much the AI is automating."*

This is not a nice-to-have. It is the **trust interface**, and it is what makes the trust ledger legible enough for a non-technical user to operate. It is also increasingly a compliance artifact — the EU AI Act's human-oversight provisions and NIST's AI RMF both require oversight that is demonstrable rather than assumed.

### A9.1 The three views

**1. Today** *(default, phone-first)*

Plain language, no jargon:
> **Handled: 14 things.** 9 emails triaged, 3 meetings scheduled, 2 follow-ups sent.
> **Waiting on you: 3.** [one-tap each]
> **Noticed: 2.** [expandable]
> **Cost: $0.42.**

**2. Trust** *(the autonomy control panel)*

Every action class as a row: current tier, actions taken, agreement rate, trend arrow, and a tier slider the user can move in either direction at any time. Pending promotion proposals sit at the top with their evidence. **This one screen is where a non-technical user understands and controls the entire autonomy model** — if it needs explaining, redesign it.

**3. Ledger** *(the audit trail)*

Every action, filterable by time, app, class, and outcome. Each entry expands to: what triggered it, what it did, what it cost, what memories it used, and what it would have done differently. Per v1.0 invariant 7, fully replayable.

### A9.2 The headline metric

The user asked to see *how much* is being automated. Give one number they can feel:

> **Time saved this week: 6.2 hours** — 4.1 email, 1.3 scheduling, 0.8 research.

Requirements:

- **Estimated honestly and stated as an estimate.** Derive from measured human baselines per action class, calibrated against the user's own pre-automation timings where available. **Do not inflate.** A number the user does not believe destroys the credibility of everything else on the screen.
- **Alongside it: autonomy rate** (share of actions at tier ≥4), **intervention rate** (share requiring the user), and **cost**. Four numbers, one line each.
- **Trend over time is the point.** Week over week, is the agent handling more with fewer interventions? That single curve is the product's whole value proposition, rendered.

### A9.3 Design constraints

- **Transparency must not overburden.** Research is explicit that increasing transparency past a point degrades oversight rather than improving it. Three levels of depth: a number, a sentence, a full trace. Most users never leave level one, and that is correct.
- **Interrogable, not just visible.** *"Why did you do that?"* must work on any row and return real reasoning, not a generated post-hoc rationalization.
- **Failures are as prominent as successes.** A dashboard that shows only wins is marketing. Show what it dropped, what it got wrong, and what it declined to touch.
- **One-tap kill switch, global and per-class,** always reachable. The user must never feel they cannot stop it.

---

## A10. S9 — Reach

*"Easy to reach out to and communicate from anywhere."*

- **Every channel is a full channel.** SMS, iMessage, WhatsApp, Telegram, Slack, Discord, email, voice call, native mobile app, desktop, web, CLI. Not a notification surface — a full interaction surface. Anything you can do in one, you can do in all, subject to what the medium supports.
- **One session identity across all of them.** Start by voice, continue by text, finish in the terminal. No restatement, no re-context. Per v1.0 §9 and §12.
- **The assistant is addressable, not just reachable.** Its own email address and messaging handles, so it can be CC'd, added to a group, or looped into a thread by someone who is not the user. This is what makes it usable *with other people* rather than only *by you*.
- **Message-first, not app-first.** The user should be able to run their entire relationship with the agent through SMS if they want. The best-performing products in this category are operated primarily through iMessage — that is a real finding about how people prefer to work, not a limitation.
- **Zero-install path.** Text a number, get a working assistant. Apps are an upgrade, not a gate.
- **Async by default.** Fire a request, walk away, get pinged. Nothing requires you to sit and watch.
- **Presence awareness.** Do not push a routine notification at 2am. Know the user's timezone, working hours, and current channel, and route accordingly.

---

## A11. S10 — Onboarding for Any User

The first ten minutes determine whether this is a secretary or an abandoned subscription.

**Required sequence:**

1. **Minute 0** — Talk to it. Voice or text. No configuration, no account wizard, no tour.
2. **Minute 1** — It asks for one thing: email. Infers the rest of the stack from the domain and proposes connections.
3. **Minute 2** — Connected. It reads history *with visible consent* and starts building the people model and voice model.
4. **Minute 5** — First real output: *"Here's your day. Three things need answers. Two people are waiting on you. Want me to draft the replies?"* Everything is at tier 1–2. Nothing has been sent.
5. **Day 1–7** — Shadow mode across the board. It proposes; the user disposes; the ledger fills.
6. **Day 7** — First promotion proposal, with evidence.
7. **Day 30** — Several classes autonomous, the dashboard shows a real time-saved trend, and the user has stopped checking most of what it does.

**Constraints:**

- **No configuration file, ever, for a normal user.** Power users get files. Everyone else gets conversation.
- **The agent onboards itself by asking.** Preferences are learned from behavior and gaps filled by asking in context, one question at a time, never a settings form.
- **Consent is explicit and legible** at the moment history is first read. This is the highest-trust moment in the product; do not bury it.
- **Value before autonomy.** The user must receive something useful before being asked to grant anything meaningful.

---

## A12. Consolidated Acceptance Bar

| Domain | Metric | Target |
|---|---|---|
| Connection | Install → first connected app | < 90 s |
| Connection | Credential exposure to model | Zero, structurally enforced |
| Connection | Model-visible tools at 20 apps | ≤ 12 |
| Identity | Drafts sent unedited (tier ≥3 classes) | ≥ 85% |
| Identity | Voice-match blind test vs. real user mail | ≥ 70% indistinguishable |
| People | Cross-channel entity resolution accuracy | ≥ 95% |
| Noticing | Proactive surfacing precision | ≥ 0.80 |
| Noticing | Unprompted interruptions per day | ≤ 5, user-adjustable |
| Commitments | Extraction recall from conversation | ≥ 90% |
| Commitments | False-closure rate | < 2% |
| Escalation | Escalations resolvable in one tap | ≥ 80% |
| Trust | Classes at tier ≥3 by day 30 | ≥ 5 |
| Trust | Post-promotion correction rate | < 5% |
| Trust | Confidence calibration error | < 10% |
| Dashboard | Non-technical users who can find and change an autonomy tier unaided | ≥ 90% |
| Dashboard | Users who believe the time-saved number | ≥ 80% (survey) |
| Reach | Capability parity across channels | 100% of medium-supported actions |
| Onboarding | Install → first useful output | < 5 min, zero config |
| Retention | Day-30 users with ≥1 class at tier ≥4 | ≥ 60% |

**Note the last row.** It is the real one. Everything else is a leading indicator of whether people actually let it work.

---

## A13. The "Blown Away" Tests — Secretary Edition

Extends v1.0 §17.

1. **The CC.** You CC the assistant on a thread with three people. It negotiates a time across everyone's calendars, books it, sends the invite, and reports back. You did nothing else.
2. **The catch.** "Your 4pm is with the person you promised a pricing sheet to in March. You never sent it. Want me to draft it now?" You had forgotten completely.
3. **The promotion.** "I've drafted 23 of these. You sent 21 unedited. Want me to stop asking?" The evidence is right, the offer is well-timed, and you say yes without hesitation.
4. **The demotion.** You edit one draft heavily. Without being told, it goes back to asking for that class — and says so, briefly, without drama.
5. **The chase.** Someone owed you a contract eight days ago. It notices, drafts a follow-up in exactly your register — polite, not passive-aggressive, the way you actually write — and asks once whether to send.
6. **The number.** You open the dashboard, see "6.2 hours saved this week," and your reaction is *that sounds about right* rather than *sure it did.*
7. **The silence.** It handled fourteen things today and interrupted you zero times, because none of them needed you. The log proves it after the fact.
8. **The stranger's test.** Your co-founder texts your assistant directly to reschedule. It handles it, tells them what it did, and tells you afterward.
9. **The install.** Your least technical friend installs it, texts it, and it does something useful before they configure anything at all.
10. **The stop.** You say "stop sending emails for a while." It stops, everything drops to draft, the dashboard shows it, and nothing is lost.

---

## A14. What This Will and Will Not Give You — Read This

You asked directly whether this produces a Jarvis-level secretary. Straight answer, in two parts.

### What this gets you

Everything in v1.0 plus everything here is genuinely achievable with current models and known engineering. It produces a system that: knows your history and surfaces it unprompted; reaches you anywhere and is reachable by others; connects to your apps in seconds; handles the recurring administrative layer of your work autonomously within earned bounds; notices what you missed; closes loops you dropped; runs deep research overnight and hands you real files; and shows you exactly what it did and what it saved you.

**That is a real secretary for the 80% of secretarial work that is recurring, bounded, and pattern-following.** No product currently on the market does all of that in one system, and the gap you would be filling — cloud-connected *and* locally capable, on one memory — is genuinely unoccupied.

### What it will not give you, and why

**Reliability on novel, long, unbounded tasks is model-bound, not harness-bound.** The math is unforgiving: at 95% per-step reliability, a 20-step task succeeds about 36% of the time, and that formula is an *optimistic upper bound* because real errors correlate and cascade. METR's measurements put the 50%-reliability task-length horizon for frontier agents at roughly 55 minutes in early 2025, with projections reaching a few hours around 2027. **No harness fixes this.** A harness can checkpoint, verify, retry, abstain, and escalate — all of which we specify — but it cannot make a model's judgment on step 14 better than it is.

The practical consequence: **for recurring bounded work, you will stop checking it within a month. For novel, high-stakes, or long-horizon work, you will be reviewing it for the foreseeable future.** The trust ledger exists precisely to make that boundary visible and honest rather than something you discover through a bad surprise.

The three things most likely to make this fall short of the feeling you are describing, in order:

1. **Noticing precision (§A5).** If proactive surfacing is wrong more than ~20% of the time, users disable it, and without it the system is reactive — capable, but not a secretary.
2. **Voice authenticity (§A3).** If drafts do not sound like you, you rewrite them, and the time savings evaporate along with the trust.
3. **The trust ramp not ramping (§A8).** If promotion proposals feel premature or the evidence is unconvincing, users stay at tier 2 forever and the system is an expensive draft generator.

**All three are the same underlying problem** — calibrated judgment about a specific person — and all three are addressable with the memory architecture in v1.0 §5 *if it works*. That is why the memory prototype is the right first build, and why it is the thing to prove before anything else is worth building.

---

## A15. Hard Problems (Extends v1.0 §14)

11. **Proactive precision without labels.** §A5 requires ≥0.80 precision on unprompted surfacing with no training data at install. What is the cold-start strategy, and how does the system avoid being either useless or annoying in week one?
12. **Voice without impersonation harm.** How faithfully should the system imitate a person, and what is the boundary that prevents an assistant that is *too* convincing from becoming a liability?
13. **Multi-party etiquette.** When the assistant is CC'd on a thread, what are its manners? When does it speak, when does it stay silent, when does it check with its principal first?
14. **The complacency-competence tension.** Better performance produces less oversight produces worse outcomes on the tail. Verification sampling is a partial answer. What else?
15. **Commitment extraction precision.** "I'll take a look" is not a commitment. "I'll send it Thursday" is. "Let me get back to you" is ambiguous. Where is the line, and what happens at it?
16. **The self-hosting split.** A managed auth broker is the right engineering answer and the wrong answer for the most trust-sensitive users. Do you ship both, and what breaks if you do?

---

## A16. Sources

**Category landscape:** 2026 comparative reviews of personal AI assistants (Mastra, Fastio, Arahi, Agentic.ai, Lindy, alfred_, Vellum, Carly, Dume); Lindy's February 2026 relaunch coverage; Carly's per-agent email-address delegation model; Vellum's credential-isolation architecture.

**Connection layer:** Composio, Nango, Arcade, Merge, Paragon, and WorkOS comparative analyses (2026); Nango's MCP Auth support (February 2026) and connection-ID credential model; Arcade's just-in-time authorization pattern; documented tool-overload effects on agent performance.

**Trust, autonomy, and oversight:** shadow-mode and graduated-autonomy literature (supervised-agency spectrum; CMU SEI human-centered pillar); Anthropic usage data on auto-approval rates across user experience levels; automation-complacency research in human factors; EU AI Act Article 14 and NIST AI RMF human-oversight requirements; threshold-based escalation patterns; agentic confidence calibration.

**Reliability:** compositional reliability under multiplicative decay (p^n); METR task-length reliability horizon measurements and projections; control-theoretic analysis of non-converging agent retry loops; verification gates and calibrated abstention in agentic trajectories.

**Transparency and interface:** agentic-era HCI patterns (interrogable reasoning, adjustable autonomy, visibility without overload); three-pillar transparency/accountability model with dashboard-supported autonomy escalation; CHI 2026 work on anthropomorphism as a design variable.

---

*Written August 2026. §A1 moves fastest — re-verify the competitive landscape before committing.*