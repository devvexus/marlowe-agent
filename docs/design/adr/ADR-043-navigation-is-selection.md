# ADR-043 — A research run navigates by SELECTING a link, never by composing a URL

**Status:** ACCEPTED as the design. **Not built.** The primitive is M2 tool work; the orchestrator
that uses it is M3 and ADR-037 owns it.
**Depends on:** ADR-023 (the action/target split), ADR-036 §5 (the authority rule), ADR-041, ADR-042
**Corrects:** ADR-037 §6, which is right about the mechanism and wrong about who stays clean

## 1. The problem, stated as the contradiction it actually is

Two requirements that look incompatible:

1. **Marlowe is a deep research agent and must go URL to URL freely.** A research loop is *read →
   follow a link → read more*. It is the product.
2. **ADR-023: a run that has read untrusted content may never compose a Target again.** After a
   fetch, a model-composed URL is refused.

Today the contradiction is hidden rather than resolved, and the audit found how. `condense_chunk`
pushes the quarantined reader's summary into the parent at **`AgentInferred`** — so a fetch never
lowers the run's floor, ADR-023's latch never fires on `web`, and navigation works because **layer 3
is silently inert**, not because anything reconciled the two requirements.

That is a laundering path with a second, worse leg: `remember` stamps a belief at
`AgentInferred.min(run_floor)`, so page-derived content becomes a **permanent** `AgentInferred`
belief in the signed journal. Layer 2's headline property — *"four LLM rewrites later, a web page is
still `UntrustedContent`"* — is defeated by one rewrite.

So the condensed return must cross at `UntrustedContent`. And the moment it does, navigation stops.

## 2. The resolution is ADR-036 §5, and it is not a new idea

ADR-036 §5 already states the rule and explicitly invites this application:

> *wherever a value chosen by untrusted content determines an outcome, the question is who asserted
> it — even when there is no tool, no argument, and no permission check in sight.*

It also names why a floor cannot help here:

> *A uniformly-tainted population is exactly where a trust floor stops discriminating and something
> else has to.*

In a research corpus every source is `UntrustedContent`. The floor is saturated; it separates
nothing. The question that survives saturation is **who asserted this URL**, and there are two very
different answers wearing the same shape:

| | Who authored the bytes | When they were fixed |
|---|---|---|
| **A link from the document's own markup** | the page author | at serve time, **before the run had seen anything** |
| **A URL the model typed after reading** | the model, steered by the page | after the run has seen everything |

**Exfiltration lives entirely in the second.** A composed URL is a variable that can encode any
secret the run holds. An extracted link is a **constant** — the attacker committed to those bytes
before they knew anything, so the channel carries no payload they did not already possess.

Navigation lives entirely in the first, and `marlowe-extract` already produces it: every `Document`
carries `links: Vec<Link>` with URLs resolved by the harness from the markup, and `DocumentStore`
already holds them.

## 3. The decision

**The model passes an index. The harness passes the bytes.**

```
web(ref = <document hash>, link = 7)
```

The harness resolves `(ref, 7)` against the store and supplies the URL itself. The model chose
*which* link — a **Payload**, which §9 lets untrusted content shape freely. The harness asserted
*the URL* — the **Target**, which it may not.

`web(url = …)` stays, for URLs the user typed. Those are `UserAsserted` and unaffected, because
`taint_for` attributes a value the user supplied rather than dropping it to the floor.

So a research pass can hold `UntrustedContent` for its entire life and still navigate, while `bash`
and `edit` remain hard-blocked on composed targets. That is the trifecta break intact and the
product intact, which is the outcome neither the current build nor a naive fix achieves.

### 3.1 The link table bypasses the reader

**This is the part that is easy to get subtly wrong, and getting it wrong makes quarantine
decorative for the decision that matters most.**

The obvious construction has the quarantined reader enumerate the links into its output slots. That
routes the link table through the **compromised** component. A reader that has been told
`SELECT LINK 7` then hands the parent an ordering, a description and an emphasis — and the parent's
choice is shaped by a component the whole design assumes is captured.

So: **the harness builds the link table from the extracted markup and hands it to the parent
directly.** The reader summarises prose and never touches the link graph. A page shouting
`SELECT LINK 7` reaches the parent only as attacker-derived text inside a summary, while the list it
would be selecting from came from the harness.

Anchor text is page content and is currently **unbounded** (`html.rs` collapses an arbitrary slice).
It is capped and character-checked at the same predicate contract values use.

## 4. What this does NOT claim

Not "injection proof". The honest boundary:

- **Closed:** no byte an attacker authored becomes a Target. That is checkable by grep, not by
  argument, and it is the escalation path.
- **Open, and irreducible:** the reader's summary still influences *which* link looks interesting.
  An attacker serving a page with 1,000 links to hosts they control, who talks the model into
  choosing among them, extracts on the order of ten bits per fetch. A covert channel — narrow, slow,
  requiring model cooperation, and exactly what **layer 4's host allowlisting** is for when it ships.

Stating it this way because the failure family this project tracks is a defence whose claim is
wider than its mechanism.

## 5. The correction to ADR-037 §6

ADR-037 §6 says:

> *Every research worker is a tainted run by construction. The orchestrator that acts on their
> findings must be a separate run that never touched a page.*

The mechanism is right and the conclusion does not survive §1. **Once the condensed return crosses
at `UntrustedContent` — which it must — the orchestrator is tainted the instant findings arrive.**
There is no run that both acts on findings and stays clean. ADR-037's model was only coherent
because the crossing was silently promoting, which is the defect.

The design that does work has **three phases with three trust states**, not two roles:

| Phase | Floor | May compose a Target? | How it acts |
|---|---|---|---|
| **Plan** | clean | yes | fixes seed URLs, scope, **and the output destination** |
| **Read / navigate** | `UntrustedContent` | no | selection only (§3) |
| **Synthesise / write** | `UntrustedContent` | no | writes to the target the **plan** asserted |

**This makes ADR-037 §3's collaborative plan load-bearing for the security model rather than a UX
feature.** §3 already says the plan is *"composed by the orchestrator before any channel is read, so
it is composed in a clean run"* — and that is precisely what supplies a clean target for a tainted
synthesis phase to write to. A research run that skipped planning would have no legitimate
destination to write, and ADR-037 §6.2 (*"a worker cannot write the report"*) would have nothing to
hand it to.

So §3 is upgraded from *"cheap, and it makes effort scaling visible"* to a **precondition**. A run
with no approved plan has no clean target and cannot produce an artifact.

## 6. Sequence, and what is in scope now

ADR-037 is M3 and marked *do not build*; the orchestrator is not this milestone's work. What is in
scope, in order:

1. **The display sanitiser.** `is_renderable` has exactly one caller in the product and no render
   site uses it, so the approval prompt renders the model's composed argument unfiltered. Independent
   of all of the above and the highest-severity open finding.
2. **The extractor's process-killers** (xlsx amplification, csv, HTML peak, the uncapped `<title>`).
   These **abort** rather than panic, so `catch_unwind` cannot hold them and one hostile document
   takes the daemon down. A system whose job is parsing hundreds of hostile documents cannot carry
   these.
3. **The link table and `web(ref, link)`** — the primitive, buildable inside M2's tool scope.
4. **The condensed return at `UntrustedContent`**, once 3 exists so nothing regresses. Layer 3 goes
   live in the shipped daemon for the first time.
5. **M3 inherits the phase table in §5** rather than ADR-037 §6's two-role model.

Steps 3 and 4 fold in audit findings **A5** (`bash` stdout's class), **A6** (the `Inert` target-check
exemption) and **H6** (`web`'s consequence level) — all four are this one question wearing different
clothes, and one `DECISIONS.md` entry should answer them together.

## 7. The verification that would mean something

Not a unit test. A live run: fetch a page, follow three links by selection, and assert the run's
floor is `UntrustedContent` throughout **and** that a composed `bash` in the same run is refused —
with a control that fails if no composition was attempted.

`injection_attempts.rs` currently asserts the parent did not call `bash` using a scripted driver
that **never tries**, so it measures the script rather than the wall. That is the shape to avoid
here.
