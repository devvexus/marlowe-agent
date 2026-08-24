# Analogical retrieval — what embedding similarity cannot index

**The thesis, stated by the human 2026-08-24:** a small model that has researched a domain should
compete with a frontier model trained on it. Recall is the easy half and retrieval already wins it.
The hard half is **synthesis** — answering questions that span facts never stored together — and the
proposal is to close it by retrieving *the reasoning* rather than the conclusion. Someone already did
the derivation; index the derivation.

**This page exists because the obvious implementation measures well and does nothing.**

| | |
|---|---|
| **Status** | **Not built, not decided.** A research direction with a measurement plan. |
| **Scheduled as** | its own session, post-M3, with the test sets built before any retriever changes |
| **Depends on** | the Session K cascade (`RerankPlan::Cascade`), ADR-018 / ADR-050 |
| **Blocked by** | nothing technical; blocked on the labelled sets in §4 existing |
| **Owner** | unassigned |

## 0. The standing constraint — the brief already priced this

**Brief line 341, quoted in full because it is about this design specifically:**

> **Memory writes are the highest-privilege operation in the system.** See §5.6. Poisoning is
> temporally decoupled from its trigger — poison planted today fires weeks later when semantically
> retrieved — which defeats every defense that watches for malicious *actions* rather than corrupted
> *beliefs*. Note the uncomfortable finding that more capable models are not more secure here, and
> that agents which write and retrieve memory more aggressively are *more* exploitable. Our
> aggressive memory system therefore requires proportionally aggressive write-time provenance.

The thesis in this page is *"research all day and learn heavily."* That is the aggressive-write case
the brief names, and it does not forbid it — **it prices it.** The price is write-time provenance,
paid in full, at every write.

Three consequences that are not negotiable downstream:

1. **Lineage rides on every operator and every fact, permanently.** Not a debug field. The retrieval
   path reads it.
2. **Nothing untrusted-derived consolidates into the stable tier without corroboration.**
   Consolidation is the moment a claim stops carrying its origin and starts reading as background
   truth. That is where temporally-decoupled poisoning becomes permanent.
3. **Attribution survives the fan-in.** Facts leave the extractor tagged with which source produced
   them, so a source discovered to be poisoned six months later is revocable by lineage instead of
   contaminating a batch invisibly.

**"Watch for malicious actions" is explicitly named as the defence that does not work here.** Layer 3
guards targets and holds; it says nothing about a belief that was false when written.

## 1. What is actually being proposed

Not "find similar documents." **Retrieve an operator and apply it.**

A *value* answers one question: `Hubble constant ≈ 73 km/s/Mpc`. An **operator** answers a class of
questions: *reduce to a conserved quantity*, *change variables until the second-order term is
diffusive*, *take the limiting case and check dimensions*. An operator applies to inputs nobody
indexed, which is the nearest thing a retrieval system has to additional weights.

**Weights encode composition; retrieval encodes lookup.** That difference is why a frontier model
answers questions spanning facts it never saw together, and it cannot be converted away. But
retrieving operators narrows it, because an operator is *already* a composition rule.

## 2. The trap, and it is this project's most-repeated failure family

**Embedding similarity retrieves surface form.** That is what an embedding is — lexical and
distributional shape. So "find equations similar to this one" returns equations that *look* alike,
and both error directions are severe:

| | |
|---|---|
| **False positive** | `∇²φ = 0` and `∇²φ = ρ` — nearly identical to look at, completely different solution behaviour |
| **False negative** | the heat equation and Black–Scholes — no lexical overlap, **the same equation** under a change of variables |

The false negative is where all the value is. Cross-domain transfer — recognising a finance problem
as a diffusion problem — is exactly what makes a smaller model punch above its weight, and surface
similarity will never surface it.

**Surface similarity is a proxy that moves with structural relatedness.** It reads correct when it is
wrong, the hits look plausible every time, and no ordinary retrieval metric separates the two. This
is the #13 failure family in a new subsystem: *ask what this measurement would read if the property
you care about were broken.* A retriever that indexes looks and one that indexes structure both
return same-looking equations. Only the negative set in §4.2 tells them apart.

## 3. What to index instead

Not the symbols. The shape of the argument, extracted at ingest:

- what was **assumed** (and what was assumed away)
- what **transformation** was applied
- what **invariant** or conserved quantity carried the argument
- what **argument form** — contradiction, induction, symmetry, limiting case, dimensional analysis,
  change of variables
- what **class of object** it operates on

Indexed this way, *"second-order parabolic PDE, diffusive term, solved by change of variables"*
connects heat flow to option pricing. Indexed as LaTeX, it never does.

**The extraction is the whole design.** Everything downstream is the existing cascade. Trust is
bound to **origin** — ADR-036 §"arXiv, GitHub and Wikipedia are not more trustworthy than a random
page *for this purpose*" — so this extraction runs on validated summaries in the fan-in stage, never
on raw source.

## 4. The measurement — three sets, and the negative one is the test

**Every numeric target becomes an executable test.** Build all three sets BEFORE touching a
retriever, and pre-register the predicted numbers, following the `tools/preregister_split.py`
discipline.

### 4.1 Set P — transfer (structurally isomorphic, lexically distant)

Hand-built pairs known to be the same structure in different clothes. Heat ↔ Black–Scholes.
SIR epidemic ↔ rumour propagation. Lagrange multipliers in mechanics ↔ in consumer choice.
Target ~50 pairs, built by a human, never by the system under test.

**Metric: transfer@k** — does the true structural match appear in the top k.

### 4.2 Set N — the lure (lexically near, structurally unrelated)

Pairs that share notation, vocabulary or visual form and nothing else. `∇²φ = 0` against
`∇²φ = ρ`. Two papers sharing a symbol table across unrelated domains.

**Metric: lure rate** — how often a look-alike outranks the true match.

**THIS IS THE VACUITY CONTROL AND WITHOUT IT THE OTHER TWO NUMBERS ARE UNINTERPRETABLE.** A
retriever that returns "anything vaguely mathematical" scores respectably on P. It is only
distinguishable from a working one by failing N. Report P and N on the same line, always.

### 4.3 Application — retrieval is not the thesis

**Retrieving the right operator and applying it fail separately, and the second one is the claim.**
The analogical-transfer literature is consistent that subjects given the relevant worked example
still fail to apply it unless the correspondence is made explicit — a small model will do the same.

**Metric: application rate** — given the retrieved operator, is the target problem solved.
**With an ablation: the same problems, retrieval disabled.** Without the ablation, application rate
measures the base model's competence, not the retrieval's contribution.

### 4.4 Baseline

The shipped bi-encoder plus the Session K cascade, unchanged, on all three sets. Any claimed
improvement is a delta against this and is **re-measured, never inherited** — the retriever, the
graph and the provider all move, and a measurement is scoped to the system it was taken on.

## 5. The cascade is already the right architecture

Bi-encoder retrieves wide on surface. **A cross-encoder scores the pair jointly**, which is
structurally far better at *"is this the same kind of problem"* than cosine distance between two
independent embeddings. Depth 30 narrowed to 10 with a fused second opinion (ADR-050) is already
"cast wide on looks, judge narrow on structure."

**So this is an objective and training-data question, not an architecture rebuild.** What changes is
what the reranker is asked to judge. That is a much smaller session than it first appears, and it is
the reason to attempt it at all.

## 6. The honest limit, recorded so the thesis is not oversold

Retrieval hands the model a candidate analogy. **Seeing the mapping is still the hard part, and it
scales with model capability.** This narrows the frontier gap; it does not close it. The bet is that
operator retrieval plus synthesis in a loaded context recovers most of what parametric composition
gives, on the domains that matter here. That is defensible. It is not proven, and §4.3 is what would
prove it.

## 7. Open

1. **Who extracts the structure** — the quarantined reader that saw raw bytes and whose fidelity
   ADR-041 explicitly does not guarantee, or the fan-in pass over validated summaries that can only
   distort what already got through? Fidelity against blast radius.
2. Is the operator index **separate from** the fact store, or a tier within it?
3. Does an operator carry a trust class? It is derived from an untrusted source like everything
   else, but it authorizes no target — it shapes analysis, which Brief §5.6 permits explicitly.
4. What is the smallest domain that demonstrates transfer? Physics/finance PDEs is the obvious first
   pair and may be too easy; the interesting claim is cross-field.
