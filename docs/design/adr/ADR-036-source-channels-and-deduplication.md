# ADR-036 — Source channels are an extensible keyless registry, and corroboration is counted over independent roots

**Status:** PROPOSED — **design only, no code** (M2 C2f, 2026-08-10)
**Depends on:** ADR-035 (SearXNG), ADR-031 (TLS), ADR-023 (taint)
**Amends by consequence:** brief §10 (see ADR-037)
**Build milestone:** M3. Recorded now because these decisions are cheap today and expensive later.

## 1. Position

General web search is **one** channel, and for most questions a research agent asks it is the
*worst* available source: a SERP is a ranked list of pages that mention words, where the question
usually wants a paper, a citation graph, a commit, or a dated discussion.

The channels below are free, keyless, structured, and **rate-limited rather than gated** — the
distinction that matters, because a rate limit is a scheduling problem and a gate is a procurement
problem.

| Channel | Returns | Owns an identifier namespace |
|---|---|---|
| arXiv API | papers, abstracts, full text, by category/author | `arxiv_id` |
| PubMed / E-utilities | biomedical literature | `pmid`, `pmcid` |
| Crossref | DOI metadata, citations, 150M+ records | `doi` (authoritative) |
| Semantic Scholar | citation graph, references, influential citations | `corpus_id` |
| Wikipedia / Wikidata | structured facts, entity resolution | `qid` |
| GitHub REST | code, issues, releases, READMEs | `owner/repo@sha` |
| Hacker News (Algolia) | technical discussion, dated | `hn_item` |
| Stack Exchange | technical Q&A | `se_post` |
| RSS / Atom | any site publishing a feed | — (URL only) |
| `sitemap.xml` | site structure without blind crawling | — (URL only) |
| SearXNG (ADR-035) | general web | — (URL only) |

## 2. The registry has no credential concept

**There is no `api_key` field, no `Option<Credential>`, no `requires_key: bool`, and no environment
lookup.** A channel that cannot be reached without a key **cannot be described by this registry**,
so it cannot be registered, so there is no path by which it is enabled — by default or otherwise.

This is stronger than a load-time refusal and it is stronger on purpose. A default-off flag is a
line a future session flips with a good reason at 2 a.m.; a field that exists is a field somebody
fills in. Removing the representation removes the conversation. The illegal state is not guarded —
it is *unspeakable*.

Adding a keyed source later is therefore not a registry entry and not a config change. It is an ADR
that must argue for introducing the concept, against this section.

### 2.1 Shape

A channel declares, and all of it is known at load time:

- **`name`** — stable, model-visible.
- **`endpoint`** — the base URL. `https` only via `marlowe-net`, or loopback via the plaintext
  client (ADR-035 §4.1). No other transport exists.
- **`rate_limit`** — requests per interval, **declared, not discovered**. A channel with an unknown
  limit declares the most conservative one; there is no "unlimited" and no `None`. The scheduler
  reads this; a channel cannot exceed a limit it did not declare because the declaration is what
  the scheduler schedules against.
- **`shape`** — what one result contains, so a worker can parse without guessing.
- **`identity_authority`** — which identifier namespaces, if any, this channel is *authoritative*
  for (§5). Most channels are authoritative for none.
- **`indexes`** — the channels this one mirrors or aggregates (Semantic Scholar indexes arXiv;
  SearXNG aggregates everything). **Load-bearing for independence**, §4.5.

**`indexes` must be declared and must not be inferred.** A channel that silently under-declares what
it mirrors makes two routes look independent, which is the exact defect this ADR exists to prevent —
so the field has no default and an empty list is an explicit claim of independence.

## 3. Channel selection is routing, not fan-out

Querying every channel for every question is the excessive-subagent-spawning failure brief §10
already names, wearing different clothes: eleven channels queried in parallel is eleven times the
tokens for a question that three could answer, and it degrades synthesis by burying the good source.

**The orchestrator picks channels from the question's shape**, and it picks *before* spending. This
is the same table-over-roles discipline as ADR-008's model routing — a task role selects channels,
never a hardcoded list, so the mapping survives channels being added.

Rough shape, to be measured rather than asserted: a claim about published research routes to
Crossref + Semantic Scholar + arXiv; a question about a library's behaviour routes to GitHub +
Stack Exchange; a "what happened recently" question routes to HN + RSS + SearXNG; an entity
question routes to Wikidata first because it answers in one call what a SERP answers in five.

**Fan-out is permitted and is a declared escalation**, tied to §10's effort scaling and visible in
the plan the user approves (ADR-037 §3).

## 4. Deduplication

The failure this prevents: **a research agent that counts one source three times has manufactured
corroboration, and it is invisible in the output.** Three citations look like three witnesses. The
synthesis reads as well-supported and is not.

### 4.1 The distinction that does most of the work

> **Recorded as a correction to the framing this ADR was commissioned with.** The instruction was
> *"the same paper via arXiv, Semantic Scholar and a blog post is one source with three routes"* —
> and **the unit is wrong**. It is one source with **two** routes, plus a **second source that
> derives from it**. The human's framing collapsed two mechanisms into one and named the wrong
> unit of account; the right unit is **independent roots of the derivation graph** (§4.5).
>
> It matters rather than being a pedantry: modelling the blog post as a route would merge its text
> into the paper and lose it, and modelling it as an independent source would count it as
> corroboration. Both are wrong, in opposite directions, and one shape cannot avoid both.

The example is **two different collapses**, and modelling them the same way loses information:

- **arXiv and Semantic Scholar are ROUTES to one artifact.** Same work, same claims, two ways in.
  Merging is lossless. Corroboration value of the second route: **zero**.
- **A blog post about the paper is a DIFFERENT artifact that DERIVES from it.** It has its own text,
  which may add, omit, or distort. Merging it into the paper would destroy content; counting it as
  independent would manufacture corroboration. Corroboration value: **zero, for a different
  reason** — it is downstream, not parallel.

So the model is two-level:

```
Source          one artifact = one identity + N Routes + the routes' conflicts
Route           one channel's record of that artifact, kept VERBATIM
derives_from    a directed edge between Sources
```

A `Source` is never merged into another `Source`. Routes merge into a Source. Derivation is an edge,
never a merge.

### 4.2 The identity key, as a cascade

Evaluated in order; the first tier that fires decides.

**Tier 1 — a controlled identifier.**

- **DOI**, normalized: strip `https://doi.org/`, `http://dx.doi.org/`, `doi:`; casefold (DOIs are
  case-insensitive by spec); strip trailing punctuation and whitespace.
  **One carve-out:** `10.48550/arXiv.*` is arXiv's own DOI, not a publisher DOI. It is read as an
  **arXiv id**, not as the work's DOI — otherwise a preprint and its published version look like
  two works with two DOIs when they are one work with two identifiers.
- **Native ids**: `arxiv_id` (**version-stripped**: `2401.12345v3` → `2401.12345`), `pmid`, `pmcid`,
  `corpus_id`, `qid`, `owner/repo@sha`.

Result: **`Same`**.

**Tier 2 — normalized title + first author.** NFKC, casefold, strip diacritics, remove all
non-alphanumerics, collapse whitespace. First author **surname only**, same normalization.

- **Subtitles are NOT stripped.** A colon frequently separates genuinely different papers in a
  series, and stripping it merges them.
- **No stemming, no fuzzy distance.** A near-miss falls through to the next tier rather than
  matching, for the same reason `Provenance::attribute` matches exactly: a fuzzy identity key is an
  attacker-shaped near-miss away from merging two things that are not the same.

Result: **`Probable`**, promoted to **`Same`** when the publication year also agrees within ±1.
Title collisions are real ("Deep Learning", "Introduction", conference vs journal versions), so
title+author alone does not earn `Same`.

**Tier 3 — canonical URL.** Scheme forced to `https`; host casefolded; leading `www.` stripped;
fragment dropped; tracking parameters removed (`utm_*`, `fbclid`, `gclid`, `ref`, `source`);
remaining query parameters sorted; trailing `/` and `/index.html` stripped.

**Meaningful query parameters are kept.** `?id=447` is the resource on a great many sites, and
stripping it merges a whole CMS into one source.

Result: **`Same`** — it is literally the same resource. Two *different* URLs serving identical
content are not detectable here and are left separate; that is under-merging and §4.3 says what
happens to it.

**No tier fires: `Distinct`.**

### 4.3 Three resolution states, and the asymmetry is the design

`Same` · `Distinct` · **`Unresolved`** (the `Probable` tier without its year confirmation, or any
tier with a partial match).

**An `Unresolved` cluster counts as ONE for corroboration and displays as SEPARATE sources.**

That asymmetry is the whole point and it is chosen from the relative cost of the two errors:

| | Effect | Visibility |
|---|---|---|
| **Under-merge** | manufactures corroboration | **invisible** — the output looks better supported |
| **Over-merge** | loses a distinct source | visible — a source the user expected is absent |

Under-merging is the dangerous direction because it fails silently and in the flattering direction.
So counting is conservative — uncertainty collapses — while display is honest, and uncertainty is
shown. **Neither behaviour is a default that can be flipped**; they are two different questions with
two different right answers, and a single "merge or not" boolean cannot express it. That is why the
state is three-valued rather than two.

### 4.4 When two routes disagree — and who is allowed to assert an identity

**The harness never resolves a conflict silently. Precedence decides what is displayed first; it
never decides what is true.**

Every route keeps its own metadata verbatim. The `Source` exposes a reconciled view **plus an
explicit conflict set**, and a conflict is *evidence* — a preprint and its published version
disagreeing on a number is precisely what a research agent should surface, not smooth over.

- **Metadata** (title, authors, date, venue): per-field precedence — Crossref for DOI metadata,
  arXiv for preprint text, the publisher for the version of record. Recorded as a conflict.
- **Version** (`v1` vs `v3`, preprint vs published): a **first-class conflict**, never a merge
  detail. A claim taken from v1 may not survive to v3, and a synthesis that cites "the paper"
  without knowing which is unfalsifiable.
- **Retraction: asymmetric and unconditional.** *Any* route reporting a retraction wins, whatever
  the precedence table says. A retraction is not a field to reconcile — treating it as one means a
  higher-precedence channel that has not caught up can suppress it.
- **Trust: `min` across routes, always.** §3.3's worst-case rule. Dedup must never launder trust,
  and every route here is `UntrustedContent` anyway (§6).

Who is permitted to *assert* the identity a conflict is being reconciled under is a separate and
larger question. It is §5.

### 4.5 Corroboration is counted over independent roots

Two Sources corroborate only when **neither derives from the other and they share no common
ancestor** in the derivation graph. The count reported to synthesis is the number of independent
roots — not Sources, and emphatically not routes.

This is the number that has to be right, because it is the one a reader will read as "how well
supported is this".

### 4.6 It runs in the tainted worker, and only the graph comes back

Dedup happens where the content is: inside the quarantined reader. What returns to the orchestrator
is identities, routes, derivation edges, conflicts and counts — **no page text**. That is §10's
condensed structured return, and it is what lets an orchestrator count corroboration having never
read a page. See §6.

## 5. An identifier asserted by untrusted content is a CLAIM, not an identity

**This is the (action, target) split arriving in a domain nobody had connected it to, and it is the
first time a security principle in this project has *generalized* rather than been reapplied.**

ADR-023 governs tool arguments: an argument that chooses *what a tool acts on* may never be shaped
by untrusted content. Every prior use of that rule has been another instance of the same shape — a
path, a host, a command, a recipient. This is not another instance. **Identity is not a tool
argument, dedup is not a tool call, and no permission check runs anywhere near it** — and the rule
holds anyway, because the underlying property was never about tools. It is about *who chose the
thing that determines an outcome*.

Without it, deduplication is an attack surface with two cheap, invisible exploits:

| Attack | Mechanism | Effect on the output |
|---|---|---|
| **Merge injection** | a page prints a legitimate paper's DOI | it merges into that paper, inheriting its routes and standing — a fabricated claim now travels under a real citation |
| **Split injection** | a page varies its title slightly across mirrors | it fails to merge, and one source is counted as three — **manufactured corroboration**, the failure §4 exists to prevent |

Both are invisible in the report. Neither trips any existing check, because dedup runs on metadata
inside a worker that has already read everything and is already fully tainted — **the taint latch
cannot help here, since every route is `UntrustedContent` and the floor is already at the bottom.**
A uniformly-tainted population is exactly where a trust *floor* stops discriminating and something
else has to.

**The rule:**

- An identifier from a channel **authoritative for that namespace** (`identity_authority`, §2.1) —
  a DOI from Crossref, a PMID from PubMed, an arXiv id from arXiv — **is an identity**.
- An identifier **self-asserted by fetched content** — a DOI printed on a page, a title in an HTML
  `<meta>` tag — **is a claim**. It must be confirmed against the authoritative channel for that
  namespace before it may merge anything. Unconfirmed, it yields **`Unresolved`**, never `Same`.

So the authority to *reach* a record and the authority to *name* it are different powers, and only
the second can merge. Note the direction this fails in: an unconfirmed claim collapses into
`Unresolved`, which counts as one and displays as two (§4.3) — conservative on corroboration, honest
on display, without a special case.

**The generalization, stated for whoever finds the next domain:** *wherever a value chosen by
untrusted content determines an outcome, the question is who asserted it — even when there is no
tool, no argument, and no permission check in sight.* Ranking inputs, cache keys, memory derivation
lineage and consolidation merge decisions are all the same shape and none of them has been examined.

## 6. How this gets measured, because otherwise it drifts

Per CLAUDE.md, a target that is not a command printing a number does not exist.

1. **A fixture corpus with known duplicates**, spanning the real cases: preprint/published pairs,
   the same paper via three channels, same-title-different-paper, versioned arXiv entries, a URL
   with tracking parameters.
2. **Merge precision and recall reported separately.** They fail in opposite directions and one
   number hides that.
3. **A NEGATIVE CONTROL fixture where nothing should merge.** A dedup that merges everything scores
   perfect recall — the control is the only thing that catches it. Ask of the number: *what would it
   read if the merger were broken?*
4. **An independence control**: a Source and a blog post derived from it must report **1**
   independent root, not 2. This is the property the whole ADR exists for and it needs its own
   assertion.

## 7. Every channel returns untrusted content — see ADR-037 §5

arXiv, GitHub and Wikipedia are not more trustworthy than a random page *for this purpose*. §2.8
binds trust to origin, and the origin is outside. A channel's reputation is an argument about
content quality; the trust class is a statement about who could have shaped it.

The consequence is structural and is stated in full in ADR-037 §5: **every research worker is a
tainted run by construction, so orchestrator-worker is required rather than preferred.**

## 8. Deliberately not decided

- **Scheduling across rate limits.** Declared limits make it possible; the scheduler is M3.
- **Caching and its invalidation.**
- **Full-text extraction** — a separate module on `marlowe-net`'s bytes (ADR-031 §2.7), separate
  session.
- **Which channels are in the first build.** The registry is extensible precisely so this is not a
  decision made once and inherited.
