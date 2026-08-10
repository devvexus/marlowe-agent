# ADR-035 — General web search is a self-hosted SearXNG instance, and there is no API key anywhere

**Status:** PROPOSED — design only, no code (M2 C2f, 2026-08-10)
**Supersedes:** the "Brave or Google CSE, credential supplied by the human" note in STATE (C2f)
**Depends on:** ADR-031 (TLS), ADR-028 (local-first)
**Depended on by:** ADR-036 (the channel registry)

## 1. Decision

General web search is **SearXNG, self-hosted, reached at a configured URL, defaulting to
loopback**. A metasearch front end over 70+ upstreams — Google, Bing, DuckDuckGo, Wikipedia and
others — returning JSON, with no key, no quota and no third-party data-sharing relationship.

```
docker run -d --name searxng -p 8080:8080 searxng/searxng
GET /search?q=...&format=json
```

**No credential is stored, prompted for, bundled, or read from the environment.** This is not a
default that can be overridden; §3 makes it structural.

## 2. Why not a keyed API — and the argument is supply, not just principle

The previous position was "a keyed API is the only shape that does not break weekly." It was wrong
about the durability it was buying. **The keyed landscape is contracting:**

- Microsoft **deprecated the Bing Search API in August 2025**.
- Google's **Custom Search JSON API is closed to new customers** and **discontinues 1 January 2027**.
- Brave **requires a card at signup**, which is a barrier before the first query regardless of the
  free tier behind it.

> **INDICATIVE, NOT LOAD-BEARING.** From the human's research; **neither of us re-verified them.**
> They support a directional claim — *the keyed landscape is contracting* — and the decision rests
> on §3 and §4, which hold whatever the exact dates are. **Nothing here depends on their
> precision**, and a session acting on a specific date must re-check it.

A keyed backend is building on shrinking supply, and it puts the thing most likely to be withdrawn
on the path of the capability that most needs to keep working. It also fails K6 by construction: a
clean container cannot reach first useful output in five minutes if step one is "obtain an API
key".

**And it is the wrong shape for this product.** An embedded key ships the publisher's credential to
every user; a prompted key makes the user do procurement before Marlowe is useful. ADR-028 already
settled the equivalent question for models — local endpoint first, hosted later — and this is the
same answer for search.

## 3. There is no credential concept, and that is the enforcement

**The channel registry (ADR-036) has no field for a credential.** Not an `Option`, not a
`requires_key: bool` defaulting to false, not an environment lookup.

This is deliberately stronger than a load-time error. `reads_untrusted && !exposed_tools.is_empty()`
is a load-time refusal because the two fields must both exist and their combination is what is
illegal. Here the illegal state has no representation at all: **a channel that cannot be reached
without a key cannot be described by the registry, so it cannot be registered, so there is no path
by which it becomes enabled.**

A field that exists is a field a future session fills in — quietly, reasonably, with a good
justification — and then the default-off guard is the only thing standing between the project and a
key in the tree. Removing the representation removes the conversation.

**Consequence, stated so it is a decision and not a discovery:** adding a keyed source later is not
a config change or a new registry entry. It is a new ADR that argues for introducing the concept,
and it will have to argue against this section.

## 4. Local by default; a public instance is a named fallback, never the default

`searx.space` lists public instances. They are permitted as an explicitly configured fallback and
**never as the default**, because an unreliable third party in the search path is exactly the shape
this product exists not to have — and public instances rate-limit aggressively, block datacentre
egress, and vary in which upstreams they enable.

When a public instance is configured, its **rate limit is stated at configuration time**, in the
same way ADR-029 requires voice to state its budget consumption at enable time rather than as
discovered latency.

### 4.1 The transport asymmetry, which is not an inconsistency

| Instance | Client | Scheme | Egress policy |
|---|---|---|---|
| **Loopback** (default) | `marlowe-provider`'s loopback HTTP client, as Ollama uses | plaintext `http` | not a network destination; the same class as the Ollama endpoint |
| **Public** (fallback) | `marlowe-net` (ADR-031) | `https` only | an ordinary allowlisted host, adjudicated like any other |

`marlowe_net::Target::parse` refuses `http://` and does not upgrade it. A loopback SearXNG must
therefore **not** go through `marlowe-net` — it goes through the existing loopback-only client whose
`LocalEndpoint::new` refuses any non-loopback host. Two clients, each structurally unable to do the
other's job, which is why neither needs a flag to keep it honest.

## 5. Trust is unaffected by locality

**A result from a loopback SearXNG is `UntrustedContent`.** The instance is local; the *content* is
the open web. Locality is a fact about egress and says nothing about origin, and §2.8 binds trust to
origin.

This is worth stating because the mistake is available and would be quiet: "it came from localhost"
is true and irrelevant, and a trust class assigned from the transport rather than the origin is the
same error as a description assigned from the type system rather than the meaning.

Every consequence of ADR-023 therefore applies to search exactly as it applies to `web`. See Part 5
in ADR-036 §6.

## 6. Degrading honestly (invariant 4)

No reachable SearXNG is a **named degraded state**, not a crash and not a silent empty result set.

- A new `DegradedPath` variant — working name `SearchUnavailable` — with a headline and a remedy,
  following `Availability::remedy`'s existing shape: *"search offline — no SearXNG at
  `http://127.0.0.1:8080`. Start it with `docker run -d -p 8080:8080 searxng/searxng`."*
- The three distinguishable failures get distinguishable remedies, as `Availability::probe` already
  does for Ollama: **nothing listening**, **something listening that is not SearXNG**, and
  **SearXNG responding but JSON output disabled** (it is off in some default configs, and a
  404/415 there is otherwise indistinguishable from a bad query).
- **An empty result set is not a degraded state.** Zero results for a query is an answer. Conflating
  "found nothing" with "could not look" is the failure mode invariant 4 exists to prevent, and they
  must render differently.

## 7. Costs, accepted with eyes open

- **Maintenance, not money.** Container updates, `search.formats: [json]` enabled in
  `settings.yml`, and result quality that varies with which upstreams are active and whether they
  are currently rate-limiting the instance.
- **Result quality is not stable across time or instances**, in a way a keyed API's is. A research
  run's reproducibility is therefore bounded by its search backend — which is an argument for
  recording the backend and its configuration in the run's journal, not an argument against this
  decision.
- **Docker is a dependency for the default path.** K6's five-minute clean-container measurement
  must include bringing SearXNG up, or it is measuring a system the user does not have.

## 8. What this does not decide

- **Which upstreams SearXNG should enable.** A configuration question with quality consequences,
  deferred to whoever first measures result quality.
- **Ranking or re-ranking of search results.** M0b's cross-encoder exists and is pinned for memory
  retrieval; whether it applies to search results is a separate question with its own measurement.
- **Caching.** A research run repeating a query should probably not re-query. Not designed here.
- **That search is the primary research channel.** ADR-036 argues it is frequently the worst
  available source, and this ADR is about making one channel keyless, not about privileging it.
