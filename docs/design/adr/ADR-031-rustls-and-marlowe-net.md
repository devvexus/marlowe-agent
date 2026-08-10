# ADR-031 — TLS enters the workspace as `rustls`, in its own crate, and the first request is allowlisted

**Status:** ACCEPTED (M2 C2f, 2026-08-10)
**Extends:** ADR-002 (containment without a kernel backstop), ADR-028 (local Ollama first), brief §8
**Depended on by:** ADR-032 (approve-any-host egress), the `web` executor

## 1. Context

`web` is a core tool and it has never run. It is registered, it has a manifest, and it has no
executor — M2 C2e removed it from the exposed set rather than let the model call something that
returns `has no executor in this build`, which is a failure a model cannot interpret.

**There is no TLS anywhere in this workspace.** The only HTTP client is
`marlowe-provider/src/http.rs`, a hand-rolled blocking HTTP/1.1 client for loopback Ollama whose own
header states the constraint plainly:

> No `https`, no redirect following, no keep-alive, no compression. […] If anything beyond this
> becomes limiting, that is the signal to argue for a real client rather than to grow this one: a
> hand-rolled HTTP client that has started following redirects is a hand-rolled HTTP client with a
> security surface.

That header also said *"the TLS question is deferred to the session that adds a hosted provider."*
This is not that session — it is the session that adds `web` — and the question arrived early. It is
the same question either way.

## 2. Decision

### 2.1 `rustls`, not `native-tls`, not OpenSSL

Pure Rust, no C toolchain, no system library version to drift. The workspace already pays for
`rusqlite`'s bundled SQLite compiling C; adding OpenSSL would put a second C dependency on the
security-critical path, on a platform (Windows/MSVC) where it is the more awkward of the two.

`native-tls` would delegate to SChannel on Windows and to whatever the platform ships elsewhere,
which makes the trust decision platform-dependent — and this project has a standing rule that
platform behaviour is *verified per platform, never inherited* (`VERIFIED_PLATFORMS`, ADR-027). A
single verifier is one thing to verify.

### 2.2 Roots come from `webpki-roots`, not the platform store

**A pinned, vendored Mozilla root set, versioned as an ordinary dependency and diffable on update.**

The alternative — the OS trust store — is a set that changes underneath the binary with no diff, no
version, and no test. That is the same shape as the stale defaults this project has been bitten by
repeatedly: two sides silently disagreeing, with the failing path simply ceasing to exist.

**The cost, stated rather than discovered:** a corporate MITM proxy with a private root will fail to
verify, and `MARLOWE_EXTRA_CA` or similar is **not** being added now. A named refusal on an
unverifiable host is the correct behaviour for a tool whose whole job is fetching untrusted content;
an escape hatch that silently accepts an unknown root would be a hole in the one place it matters.
If a real deployment needs it, it arrives as its own decision with its own test.

### 2.3 It lives in a new crate, `marlowe-net`

Not in `marlowe-provider`. That crate's premise — stated in its header and load-bearing for ADR-028
— is that the default path reaches no network: `LocalEndpoint::new` *refuses any host that is not
loopback*. Putting a general TLS client beside it would make that premise a comment rather than a
property.

`marlowe-net` depends on `rustls` and nothing of Marlowe's. `marlowe-exec` depends on it. The
supply-chain surface is one crate, and `cargo tree -p marlowe-provider` continues to show no TLS.

### 2.4 Blocking, no async runtime

`rustls::StreamOwned` over `std::net::TcpStream`. The loop is synchronous — `Engine::run` is a
`while` loop and `ToolHost::execute` returns a value, not a future — and introducing `tokio` to
fetch a page would be a runtime on the critical path of a system whose selling point is that it
needs no network.

### 2.5 Redirects are **not followed at all**, and the `Location` is returned as a result

**A redirect is a second egress destination.** Following one without re-checking the allowlist is an
egress bypass with no event: the run was permitted to reach `docs.example.com`, and it reaches
`evil.example` because `docs.example.com` said so. The host that decides where the request goes is
the one being fetched — untrusted content choosing a target, the exact thing §9 exists to prevent,
arriving through a channel that never touches the taint layer.

> **AMENDED during implementation, 2026-08-10.** This clause first read *"followed, bounded at 3,
> re-adjudicated at every hop."* That is the wrong shape and writing the executor is what showed
> it: **re-adjudicating inside the fetch loop means a second implementation of the egress check**,
> living in a networking call site, where the taint layer cannot see it and where it would be
> checked against a policy the executor had to be handed for the purpose. Two implementations of
> one rule is the failure this project has recorded a dozen times.
>
> The shipped behaviour is stronger and smaller: **`marlowe-net::fetch` does not follow redirects**,
> and the executor returns the `Location` as an ordinary tool result. Following it requires a fresh
> `web` call, which goes through **the real adjudicator, with the real taint**, exactly like the
> first one. There is no second checker because there is no second check — there is one more call.
>
> **The cost is real and is accepted.** After reading any page, ADR-023's latch blocks
> model-composed targets, so in most runs the model *cannot* make that second call. A redirect will
> often be a dead end. That is the trifecta break behaving as specified rather than a defect, and
> the remedy is the one ADR-023 already names: a quarantined reader. If this proves intolerable in
> use, the fix is a harness-followed redirect **inside the adjudicated call**, not a checker in the
> executor.

A cross-scheme downgrade cannot arise, because `Target::parse` accepts `https` only and **refuses
`http` rather than upgrading it** — an upgrade would make the requested scheme and the used scheme
two different things with nothing observing the difference.

### 2.6 The default allowlist is **empty**, and off-list is a **refusal**, from the first request

Brief §8's egress-allowlist-by-default applies to the first request, not to a later hardening pass.
`EgressPolicy::default()` is already `DenyAll` and stays that way. **No host is reachable because
`web` was built.**

What happens to a request for a host not on the list depends on the run's policy, and the two cases
are deliberately different:

| Run's policy | Off-list host | Why |
|---|---|---|
| `DenyAll` | **Blocked**, terminal | Structural. The quarantined reader holds this and no approval may widen it. |
| extensible empty allowlist | **NeedsApproval** | The human is the allowlist. See ADR-032. |
| `Allow { hosts }` | **Blocked**, terminal | A declared list is a declaration; a tool cannot ask its way past it. |

**`AllowAnyHost` is not used by any shipped profile.** It exists so that "this run may reach the
open web" is greppable when something eventually needs it.

The second row is ADR-032 and is a §13 change to `interactive()`; it is not decided here. **This ADR
is complete without it** — a `web` executor against `DenyAll` is a tool that always refuses, which
is useless but not wrong, and it is the state the tree is in until ADR-032 is approved.

### 2.7 The fetch primitive returns bytes and a content type. Extraction is a separate module.

`marlowe-net` returns `{ status, content_type, bytes, final_url }` and does not parse. No HTML
stripping, no charset guessing beyond what the header states, no readability heuristic.

**Extraction is a separate module operating on that**, and it is a separate session's work (the
human's direction). The boundary is not stylistic: extraction is where the interesting parsing bugs
live, and parsing is the thing you least want entangled with the code that decides whether a request
is permitted to happen at all. An extractor that panics must not be able to take the egress path
with it, and an egress rule must not be expressible as a parser option.

`final_url` is returned because after §2.5 the caller cannot assume it matches the requested URL.

## 3. Consequences

- **A new dependency on the security-critical path**, which is the cost. `rustls` is widely audited
  and is the least-bad option; that is an argument about likelihood, not a guarantee.
- **ADR-002's `web` exemption is now under pressure.** `web` is `Inert`, so §9's target check does
  not fire on it, and ADR-002 permits that *only* because three mechanisms cover it — untrusted-content
  classing, return-by-reference, and **egress allowlisting**. This ADR keeps the third intact
  (empty default, refusal off-list). **ADR-032 is the one that weakens it**, and ADR-002 requires
  the exemption be *revisited rather than inherited* when that happens.
- **`marlowe-provider/src/http.rs` is unchanged and stays loopback-only.** Its header's deferral of
  the TLS question is now answered elsewhere, and the file is edited only to say so.
- **No credential handling.** ADR-028's "build the provider adapter; do NOT build the credential
  broker" still holds. `web` sends no `Authorization` header and reads no key, which is what makes
  keyed search a separate decision rather than a follow-on.

## 4. What this does not decide

- **Search.** Not built. `web` ships fetch-only and its description says fetch. The candidates and
  what each needs are recorded in STATE so the next session starts from a choice; a scrape-based
  search was rejected on the grounds that it breaks weekly.
- **HTTP/2, keep-alive, compression, cookies.** None. Each is a real feature and each is a real
  surface; they arrive individually with a reason.
- **The content store.** `web` declares `inline_threshold_bytes: 0` — the loop gets a reference —
  and nothing can dereference one yet. That is M2 D, and until then `web` is subject to the same
  head/tail preview stopgap as `read`.
