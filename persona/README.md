# The persona artifact

`v1.md` is the persona, pinned from Addendum C §C10 **verbatim**. It is loaded with `include_str!`
and placed in the stable tier of the system prompt (§C6).

**`v1.md` contains nothing but the persona text.** Not a header, not a version comment, not a note
like this one — every byte of it is sent to the model. Anything explanatory belongs in this file.

## Why an artifact and not a `const`

§C6: *"**Versioned as an artifact**, `persona/vN.md`, with changes reviewed as diffs. **Not a string
in the code** and not a user setting."*

Until M2 C2d it *was* a string in the code — a 40-word `const IDENTITY` in `daemon.rs` whose doc
comment claimed it "carries the persona (Addendum C)". It carried no part of Addendum C. The
comment was the only thing asserting otherwise, and nothing tested it.

## The check that matters is emission, not loading

**Loading the file proves the file loaded. It does not prove the persona is applied.** The standing
test asserts the persona text reaches the **outbound provider request** — the same distinction as
`get_providers()` reporting *registered* providers versus where nodes actually ran, which this
project has already paid for once (M0c Session L).

`marlowe-provider/tests/persona_emission.rs` builds the real request body and asserts a marker
phrase is present in the `system` role. A persona that loads and never reaches the wire fails it.

## DEFERRED: §C2's drop conditions are not enforced structurally in v1

§C2 requires the persona to drop entirely — to plain, warm, unadorned prose — in five cases:
distress, safety-relevant refusal, reporting its own error, third-party-visible output, and
factual reporting under uncertainty.

The addendum is explicit about the mechanism:

> **These conditions are a permission gate, not a prompt instruction.** A persona that drops
> because the model judged the moment correctly will fail exactly when it matters.

**v1 states the drop conditions as prompt text, which is the weaker form, and says so here rather
than implying otherwise.** The last paragraph of `v1.md` asks the model to drop character in those
cases; nothing in the harness suppresses the persona block when they fire.

**What closing it requires:** the wellbeing path §C2 names, so the distress condition can suppress
the stable-tier persona block structurally rather than asking the model to notice. Third-party
output (§A13/§A3) can be gated earlier — it is a known context, not a judgment — and is the
cheapest of the five to make structural.

**Milestone: M6**, with the trust ledger and the wellbeing path. Until then, §C2 is a prompt
instruction and its failure mode is exactly the one the addendum predicts.

## UNBUILT REQUIREMENT: a persona version bump must invalidate the prefix cache

§C6 puts the persona in the **stable tier**, which is the cached prefix. So bumping `v1.md` → `v2.md`
— or editing `v1.md` in place — **must invalidate the cache key**, or a stale system prompt survives
the change with nothing reporting it.

This is brief §6's compaction/cache-invalidation failure in a new place, and it is cheaper as a note
today than as a bug later: the symptom would be a persona change that appears to do nothing, on some
sessions but not others, with no error anywhere.

**There is no prefix cache yet, so there is nothing to invalidate.** When one lands, its key must
include a digest of this artifact. Recorded now so it is a requirement the cache is built against
rather than a patch after someone notices the persona did not take.

## Do not touch

`persona/` is on brief §13's do-not-touch list and is guarded by
`.claude/hooks/protect-boundaries.py`. A change here needs a `DECISIONS.md` entry and a human who
read the reason. Bounded self-improvement does not extend to Marlowe editing who it is (§C6).
