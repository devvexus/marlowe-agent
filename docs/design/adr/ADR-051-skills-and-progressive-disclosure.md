# ADR-051 — `SKILL.md`, progressive disclosure, and `use`

**Status:** accepted, shipped
**Date:** 2026-08-24
**Milestone:** M2 Session C3
**Supersedes / amends:** nothing. Implements CONTRACTS §7.1 and §7.2, which were pinned and unbuilt.

---

## Context

CONTRACTS §7.1 has pinned the skill manifest since it was written and nothing loaded one. §7.2 has
pinned registration-vs-exposure and nothing registered a skill. ROADMAP M2 C3 named
*"`SKILL.md` + progressive disclosure + `find_skill`"* and the row said, accurately, *"the
**vocabulary** exists from Session A … nothing loads a `SKILL.md`, no `find_skill` exists"*.

---

## 1. `find_skill` is `use`, and there is no new tool

**ADR-006 already registered it.** `builtin.rs` has carried, since M2 Session A:

```rust
registration("use", "Find and load a skill or tool.", "use", 4_096,
    // Reversible rather than Inert *so that the target check fires*. Loading a skill
    // chosen by untrusted content is supply-chain steering, and §9 checks Reversible.
    Reversible, &[], &[],
    vec![target_opt("name", Text), payload_opt("query", Text)])
```

Two parameters, and they are exactly the two operations: `query` searches, `name` loads.
`ExposureError::TooMany`'s message has said *"expose fewer and let the model reach the rest through
`use`"* for as long as the budget has existed.

So C3 built an **executor** for a tool that had been registered and unrunnable for eight sessions.
A `find_skill` would have spent ARCHITECTURE §5's one spare exposure slot on something that already
had a slot, and would have needed a ninth user-facing noun argued for — `skill` is already one of
the eight and `/skills` is already in HP10's command table.

**`use` is exposed as of this session**, taking the interactive profile from nine to ten of twelve.
It is the **third** tool admitted by `verify_every_exposed_tool_is_runnable` at the moment it gained
an executor — `web` in C2f, `recall` in Session D — and none of the three by anybody remembering to.
That guard is the reason the exposed set is derived from what is runnable rather than maintained
beside it.

## 2. Progressive disclosure is enforced by the TYPE, not by a promise

§7.1: *"Only `description` + `trigger_phrases` are embedded for semantic discovery. Embedding full
instruction prose pollutes the vector space."*

`Skill` holds a `BodyRef` — a path and a byte count — and **there is no `body: String` field to
read by accident**. `Skill::discovery_text()` is the single definition of what may be embedded, so
the embedding site and any test of it cannot come to disagree; `BodyRef::read()` is the disclosure
step, called when the model asks for the skill by name.

A `Skill` that eagerly loaded its own body would satisfy every assertion about *what gets embedded*
while defeating the reason for the rule. That is why the field is absent rather than merely unused.

`BodyRef::read` re-splits the front matter and returns only what follows it: the header is metadata
*about* the skill, and a `capability` block inside the model's window reads as something the model
may negotiate.

## 3. An installed skill is `UserReviewed`, and this resolves a contradiction inside the contract

**§7.1's own example could not load, and the fix required no schema change.**

§7.1 declares `consequence: reversible`. §7.3's `load` refuses any `ThirdParty` manifest below
`Consequential` — *"third-party code cannot self-declare its way down"* — and
`Transport::manifest_provenance` maps everything that is not `Builtin` to `ThirdParty`. Read
together, the pinned example is unloadable.

`ManifestProvenance::UserReviewed { at }` is §7.3's third variant, pinned since it was written and
**constructed nowhere in the workspace** — a declared shape with no producer, the same family the
M2 acceptance audit flagged in `LoadError::MissingManifest`.

It is the right one. **Installing a skill into the profile is the review**: the user chose it,
placed it, and can read it, and the agent cannot install one on its own initiative. That is the same
reasoning ADR-052 gives for an installed MCP server being trusted, arrived at independently and
before that decision was made.

`the_pinned_example_loads_including_its_reversible_consequence` is the assertion. Nothing in
CONTRACTS.md changed.

## 4. The signature field is parsed and is NOT verified, and there is no verifier at all

§7.1 pins `signature: "ed25519:..."`. This project has no key infrastructure, no trusted-publisher
set, and nothing to check a signature against.

The field parses into `DeclaredSignature` — named so no reader can mistake it for a checked one —
and **there is deliberately no `verify` function, not even one returning `false`**. A `verify` that
always refused would break every signed skill, so it would be deleted, and its absence would then
read as *"signatures are fine"*. A declared control with nothing behind it is instance #16 and this
one is closed before it exists.

`signature_is_declared_but_never_verified` scans this module's own source for `fn verify` and its
neighbours. **Its needles are assembled at runtime**, because spelled as literals they appear in the
file being scanned and the test failed against itself on its first run — a source-scanning guard has
to stay out of its own haystack.

## 5. THE RANKING IS LEXICAL, NOT SEMANTIC. This is named debt, not a claim

§7.1 says *"embedded for semantic discovery"* and the ROADMAP row says "semantic". **What shipped is
BM25.**

**The shipped interactive daemon holds no embedder.** `Embedder::load_with_provider` has exactly one
caller in the workspace — `crates/marlowe/src/main.rs`, on the `--eval-adapter` path — and the
daemon's memory is a `BeliefStore::derive` with no dense cue behind it. `recall`, the tool `use` sits
beside, ranks with `cue::lexical` for the same reason.

The choice was: rank lexically and say so, or wire an ONNX session into the daemon as a side effect
of a skills session. **Claiming "semantic discovery ships" over a BM25 would be this repository's
most-repeated defect** — a property asserted where it is declared rather than where it is enforced.
The `Metric::State` on every discovery result reads `lexical`, and the no-match message tells the
model in words that *"this search is lexical, so a skill whose description uses different words will
not be found by meaning alone."*

**Debt, stated so a future session does not rediscover it:** when an embedder reaches the daemon,
`SkillTools::rank` is the one function that changes and `Skill::discovery_text` already defines
exactly what may be embedded.

**There is no second ranker.** `cue::lexical::score_all` became a projection over a new
`score_texts`, which is its own arithmetic with the belief-specific line lifted out. A second BM25
would have put the tokenizer — the part most likely to be wrong — in two places that could disagree
silently. `the_belief_path_and_the_text_path_are_the_same_arithmetic` asserts `assert_eq` on `f32`,
not an epsilon: the claim is *identical*, because `repro` compares runs byte for byte.

## 6. Skills are scanned ONCE, at startup, and the refusals are announced

Rescanning per turn would let a newly dropped `SKILL.md` work without a restart, which is nicer. It
would also leave a malformed skill's refusal with nowhere to go — produced on the turn path, where
there is nothing to print it to, once per turn, forever.

One scan in one place where the refusals can be seen is worth the restart:

```
marlowe: skills 1 installed, 1 refused
marlowe:   ! skill at `…\skills\broken\SKILL.md`: line 1: a SKILL.md must open with `---` …
```

**A bad skill does not stop the scan and does not vanish from it.** Failing the whole scan would let
one broken file take away every other skill; a silent skip would leave the user wondering where
their skill went.

## 7. The front-matter parser is a STRICT SUBSET that refuses rather than guesses

§7.1 pins *"the open Agent Skills standard — unmodified where the standard specifies it"*, and the
standard specifies YAML. That is an argument for a real parser and it was weighed.

Against it: the pinned shape is eight keys of scalars and string lists, and a general YAML parser
brings anchors, aliases, merge keys, tags, implicit typing and multi-document streams — a large
surface reached by a file the user dropped in a directory, in service of constructs the shape never
uses.

**What decided it is the failure mode a subset parser must not have.** One that *guessed* at what it
did not understand would diverge from the standard silently, and a skill authored against a real
YAML implementation would load here meaning something else. So every construct outside the subset is
a **named load error citing its line** — anchors, aliases, tags, block scalars, flow maps, nested
sequences, duplicate keys, tab indentation, multi-document markers. The subset is closed under
refusal: a file that loads here means what a YAML parser would say it means, or it does not load.

`every_construct_outside_the_subset_refuses_and_says_which` is paired with
`the_subset_itself_still_parses`, without which a `parse` that returned `Err` unconditionally would
satisfy every case.

**A skill with no `x-marlowe` block loads.** The block is ours; the rest is the standard, and a
skill authored for another harness must not refuse. It gets the strictest capability — absent
consequence is `Irreversible`, §7.3's own rule. An **unknown key inside** `x-marlowe` refuses,
because that vocabulary is closed and silently ignoring one would let a skill ship a capability
nobody applies.

## 8. Consequences

- `use` is exposed; the interactive profile is ten of twelve. **Two slots remain**, and ADR-052
  spends them on MCP tools.
- `ManifestProvenance::UserReviewed` has a producer for the first time.
- `marlowe-memory`'s lexical cue has a public text entry point. The scored path is unchanged and
  pinned bit-for-bit.
- Installing a skill takes effect at the next daemon start. Stated, not implied.
- A skill's body enters the window at `UserAsserted` — see ADR-052 §6, which argues the class.

## Verification

- `cargo test -p marlowe-tools` — the parser, the loader, the pinned §7.1 example, the signature
  absence, the scan.
- `cargo test -p marlowe-daemon --lib skills::` — discovery, disclosure, and the control that the
  body crosses on exactly one of the two.
- **Mutation `skill_disclosure`** — put the body into the discovery result; fails
  `discovery_returns_names_and_descriptions_and_not_one_word_of_a_body` and
  `the_body_crosses_on_disclosure_and_not_on_discovery`, and nothing else.
- **One real end-to-end run**, `runs/session-c3/END-TO-END.md` §3: the model loaded a skill by name
  and answered from its body, having first failed on a wrong name and recovered from the refusal
  that names what is installed.

**The determinism guard caught a real defect in this work.** `skill::scan` read each file's mtime
for `UserReviewed { at }` — a clock read outside §4.5's fences — and
`the_only_real_clock_read_is_the_latency_fence` refused it on the first workspace run after it was
written. `reviewed_at` is now a parameter supplied from the daemon's fenced clock, and `at` means
*when Marlowe observed this installed* rather than when the file was written: a slightly weaker
fact, stated rather than approximated.
