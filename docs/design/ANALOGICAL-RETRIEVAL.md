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

## 7. THE TOURNAMENT — fourteen approaches, because one attempt proves nothing

**This is the section that matters.** If one implementation of analogical retrieval underperforms,
that is not evidence the idea is wrong — it is evidence *that implementation* is wrong. The failure
mode to avoid is building arm A, measuring it at 0.31 transfer@10, and concluding the thesis is dead
while arm F would have read 0.68.

**So: run many, score on one board, and let the winner be measured rather than argued.** M3's control
plane is a fan-out engine — use it on this.

### 7.1 Index-side — change what is stored

| | Approach | Mechanism | Cost | Fails when |
|---|---|---|---|---|
| **A** | **Structure extraction** | index assumption / transformation / invariant / argument-form (§3) | high — re-ingest | the extractor's schema does not fit a domain |
| **B** | **Abstraction ladder** | store each item three ways: concrete, domain-stripped paraphrase, bare formal skeleton; retrieve at the abstract rung, return the concrete | medium | stripping domain nouns destroys the discriminating detail |
| **C** | **Operator library** | a separate store of *named methods* — change of variables, conservation argument, fixed point — each with worked instances attached | high, and needs a seed taxonomy | the taxonomy is a human artifact and will have gaps |
| **D** | **Symbolic normalisation** | canonicalise equations — rename variables, order terms, normalise units — so isomorphic forms literally collide | low **where it applies** | only works on formal content; useless on prose reasoning |
| **E** | **Multi-vector** | several embeddings per item — topical, structural, methodological — retrieved against separately | medium | needs a training signal per view, which is arm J's problem |

### 7.2 Query-side — change what is asked

| | Approach | Mechanism | Cost | Fails when |
|---|---|---|---|---|
| **F** | **Query abstraction** | before retrieving, generate an abstracted/formalised restatement of the problem and retrieve with that | **very low — no re-index** | the abstraction drifts and retrieves a different problem |
| **G** | **Multi-query fan-out** | generate K framings of the problem, retrieve for each, union and rerank | low, K× retrieval | K framings that are all the same framing |
| **H** | **Hypothetical solution sketch** | generate a plausible *solution shape* and retrieve against that rather than the question | low | the model's guess anchors retrieval to what it already knows |

**F, G and H need no ingest changes and can be measured in a day.** See §7.6.

### 7.3 Scoring-side — change what ranks

| | Approach | Mechanism | Cost | Fails when |
|---|---|---|---|---|
| **I** | **Cross-encoder re-objective** | keep surface recall wide; retrain the reranker to score *structural correspondence* instead of topical relevance. **Uses the shipped cascade as-is** | medium — needs pairs | the true match never enters the depth-30 slate |
| **J** | **Contrastive bi-encoder fine-tune** | train the embedding space itself on structural pairs so distance means structure | **high** — and re-opens every pinned retrieval number | catastrophic forgetting of ordinary relevance |
| **K** | **LLM structural judge** | a wide cheap slate, then a model asked directly *"is this the same underlying structure?"* | high per query | latency; §5.7's 300 ms budget |

### 7.4 Orthogonal signals — evidence that is not text at all

| | Approach | Mechanism | Cost | Fails when |
|---|---|---|---|---|
| **L** | **Citation / co-citation graph** | papers citing across fields are a *human-labelled* transfer signal | low where metadata exists | absent outside academic corpora |
| **M** | **Co-retrieval statistics** | items retrieved together during *successful* tasks are probably related | free, accumulates | cold start; needs traffic before it says anything |

### 7.5 THEY ARE NOT ALL COMPETITORS — most of them stack

**This is the point that a naive bake-off would miss.** Query-side and index-side are orthogonal: F
composes with A, with B, with I. The tournament is therefore **staged and factorial, not
winner-take-all**:

1. Establish the **ceiling** (§7.7) and the **floor** (baseline, §4.4).
2. Run the **cheap query-side arms** alone — F, G, H — against the unchanged index.
3. Run the **scoring arm I** alone, since it reuses the shipped cascade.
4. Take the best of each layer and **compose**, then measure the composite. Report the interaction:
   if F+I is worse than I alone, that is a finding.
5. Only then commit to an expensive index-side arm — A, C or J — because those are the ones that
   cost a re-ingest or re-open pinned numbers.

**Report every arm, including the ones that lost.** A dropped arm with no number is how a future
session re-runs the same experiment.

### 7.6 Sequencing — cheap feasibility probe FIRST

**Arm F is one day of work and needs no re-index.** Run it before anything else, not because it will
win, but because it is a **feasibility probe on the whole thesis**: if abstracting the query moves
transfer@k at all, structure is recoverable from this corpus and the expensive arms are worth
funding. If F, G and H all read flat against baseline, that is a strong early signal that the
information is not in the text and arms A/C are unlikely to conjure it.

**One day, before anyone builds an extraction pipeline.**

### 7.7 THE CEILING CONTROL — the most important experiment on this page

**Hand the transfer set to a strong model with the correct operator already supplied, and ask it to
solve the problem.**

That number is the ceiling. It separates two failures that look identical from the outside:

- **Ceiling high, retrieval low** → retrieval is the bottleneck. The tournament is the right work.
- **Ceiling low** → **the model cannot apply the analogy even when handed it.** Retrieval was never
  the bottleneck, no arm above will help, and the honest conclusion is that transfer needs capability
  rather than context.

Run this **before** the tournament. It costs almost nothing and it decides whether the tournament is
worth running at all — which is precisely the question a session that only builds arm A can never ask.

### 7.8 If every arm fails

Three distinguishable causes, and they need telling apart rather than despairing over:

1. **The test set is wrong** — the pairs are not actually isomorphic, or they are so obscure that no
   corpus contains both sides. *Check: does a human expert score well on the same set?*
2. **The corpus lacks the reasoning** — abstracts and conclusions were ingested, derivations were not.
   *Check: is the argument present in the stored text at all? A grep, not an inference.*
3. **The thesis is narrower than hoped** — transfer works within a family and not across fields.
   *Check: score by pair distance. A monotone decline with distance is a real, publishable, useful
   result and bounds the product honestly.*

**Cause 2 is the most likely and the least discussed.** If the fan-in extractor (`SCOPED-MEMORY.md`
§7.2) writes summaries carrying *conclusions*, the derivation was discarded at ingest and every arm
above is retrieving from a corpus that no longer contains the thing it needs. **That question is
settled in the memory pipeline, before this tournament starts.**

## 8. Constraints that hold across every arm

1. **`[1, 256]` and batch-1 invariance are per-graph properties and are never inherited.** Any arm
   that re-quantises or re-pins re-opens ADR-015 on a graph nobody has measured.
2. **`ORT_ENABLE_BASIC` on both sides.** A Python-side measurement at a different optimisation level
   is a different scorer — 0.0699 logits apart, measured.
3. **Every arm reports tokens and wall-clock**, per M3's acceptance. An arm that wins on transfer and
   costs 4× is a different product decision, not a winner.
4. **§5.7's retrieval budget is 300 ms P95.** Arm K is the one most likely to breach it; measure
   before preferring it.
5. **Pre-register bands per arm before any fit.** A tournament with fourteen entrants and no
   pre-registration is fourteen chances to find noise.
6. **Held-out only for the published number.** Fit-set wins are how ADR-017 got withdrawn.

## 9. Open

1. **Who extracts the structure** — the quarantined reader that saw raw bytes and whose fidelity
   ADR-041 explicitly does not guarantee, or the fan-in pass over validated summaries that can only
   distort what already got through? Fidelity against blast radius.
2. Is the operator index **separate from** the fact store, or a tier within it?
3. Does an operator carry a trust class? It is derived from an untrusted source like everything
   else, but it authorizes no target — it shapes analysis, which Brief §5.6 permits explicitly.
4. What is the smallest domain that demonstrates transfer? Physics/finance PDEs is the obvious first
   pair and may be too easy; the interesting claim is cross-field.
