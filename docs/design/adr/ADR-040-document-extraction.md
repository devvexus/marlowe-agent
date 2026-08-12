# ADR-040 · `marlowe-extract`: the extraction module ADR-031 promised, and a fetch path built for corpus scale

**Status:** Accepted, shipped, benchmarked live (M2, tools-only session)
**Supersedes nothing. Amends:** `marlowe-net`'s transport behaviour and the `web` executor's return value.
**Touches no §13 boundary.** No change to trust classes, taint, adjudication, egress policy, the
agent loop, or the permission layer. The `web` executor still returns `UntrustedContent`.

## Context

`marlowe-net`'s module header has said this since ADR-031:

> *"Extraction is a separate module operating on `Fetched`"*

**That module was never written.** Until this change the `web` executor did
`String::from_utf8_lossy(&res.bytes)` and handed the result on — script bodies, inline CSS, nav
chrome and all. For any page over `MAX_INLINE_BYTES` the loop then produced a head-and-tail
preview, which for HTML is `<head>` boilerplate at one end and closing `<script>` tags at the
other. Measured on a realistic article page: **93,064 characters, of which ~11,000 were the
article.**

Marlowe is a deep research agent (ADR-037). It reads hundreds of pages, PDFs and datasets per
task, **without a model in the loop**. The extraction path is therefore a throughput component,
and it did not exist.

The transport was built for a different workload too. Per request it constructed a fresh
`rustls::ClientConfig`, opened a new TCP connection, completed a full handshake, sent
`Connection: close` and `Accept-Encoding: identity`, and read to EOF.

## Decision

Two changes, kept on opposite sides of a hard boundary.

### 1. A new crate, `marlowe-extract`

Bytes and a content type in, readable text out. **It depends on nothing of Marlowe's**, exactly as
`marlowe-net` does not — the edge is absent in both directions, so a parser cannot reach the
egress path and an egress rule cannot be expressed as a parser option. `marlowe-exec` is the only
place the two meet.

| Format | Implementation |
|---|---|
| HTML | hand-rolled single-pass extractor, no DOM |
| PDF | `pdf-extract`, with scanned-document detection |
| docx / xlsx / pptx / epub | hand-rolled ZIP reader + `quick-xml` |
| XML, text, Markdown, JSON, CSV | hand-rolled |
| charset | `encoding_rs` |

`extract_many` is a `rayon` fan-out. Extraction is pure CPU over inputs that cannot affect one
another — the most parallelisable stage in the system.

### 2. `marlowe-net` rebuilt for repeat fetching

| Was | Now |
|---|---|
| `ClientConfig` per request | one shared `Arc` — it owns the **TLS session cache**, so resumption was structurally impossible before |
| new connection per request | keep-alive pool keyed by host, with a one-shot retry on a stale connection |
| `Accept-Encoding: identity` | `gzip, br`, with a separate decompressed-size ceiling against bombs |
| DNS per request | 60-second cache |
| one at a time | `Client::fetch_many`, `Send + Sync` |

## The dependency argument, decided by measurement

The workspace lockfile already holds 323 crates, so the question was marginal cost against what a
hand-roll actually buys. Measured, not estimated:

| Candidate | New crates | Taken? |
|---|---|---|
| `flate2`, `memchr`, `rayon` | **0** each | yes — already in the tree |
| `encoding_rs` | **1** | yes |
| `quick-xml` | 1 | yes |
| `brotli` | 4 | yes |
| `lopdf` | 0 beyond `pdf-extract` | yes |
| `pdf-extract` | 22 | **yes — coverage** |
| `zip` | 23 | **no — hand-rolled** |
| `scraper` / `html5ever` | 18 | **no — hand-rolled** |

**`encoding_rs` is the one taken for correctness rather than scale.** A mis-decoded document does
not crash; it produces plausible text — mojibake in the accented range, silently wrong in CJK —
that is then summarised, embedded and ranked. In English-language testing it looks perfect. This
is the one place where hand-rolling is *more* dangerous, not merely more work.

**`scraper` was refused because it is heavier *and* slower for this job.** It builds a
spec-compliant interned DOM that would be discarded to produce a string. The hand-rolled pass
skips `<script>`/`<style>`/`<svg>` bodies wholesale, parses attributes for four elements only, and
lets `memchr` find the next `<`. Measured at **498 MB/s** on a single document.

**`pdf-extract` was taken because the requirement is coverage.** *"Any document on the internet
must be readable."* Hand-rolling PDF is xref tables and xref streams, object streams, FlateDecode,
LZW, encryption, font CMaps, `ToUnicode` maps and text-positioning maths, against a relentlessly
non-conforming corpus. 22 crates is the price, including an AES stack and a timezone database.

**`zip` was refused** because Office and epub use exactly two storage methods, stored and deflate,
and `flate2` was already free. 23 crates for formats that never appear is a poor trade, and unlike
PDF there is no coverage argument on the other side.

## Failures are reported, never disguised

The governing rule of this codebase applied to a parser: **an extractor that cannot do the job says
so**, because empty text that looks like a successful extraction is indistinguishable from a
document that had little to say.

The case that matters most is the **scanned PDF** — a large fraction of PDFs on the internet, which
extract to `""` without erroring. `Warning::NoTextLayer { pages }` fires when recovered characters
fall below a per-page floor, and it names the page count. Reading those needs OCR, which this build
does not have. Also carried: `Encrypted`, `UnknownCharset`, `LossyDecode` (counted, not a boolean),
`Truncated`, `LikelyClientRendered`, `PartSkipped`.

**Warnings are rendered into the text**, not just the struct, because everything downstream handles
the text.

## Two bugs this produced, both of the standing family

**1. A guard whose subject was classified after it had already left scope.** `<nav>` was not in
`BLOCK`, so nav text stayed buffered until the next block element opened — by which point `</nav>`
had decremented `boiler_depth`, and the chrome was stamped as content and survived filtering.
**Any element that moves a depth counter is a block boundary by definition**, or two contexts share
one classification.

**2. A warning that fired on a page that was merely short.** `LikelyClientRendered` tripped on
`doc.rust-lang.org/book/ch01-00` — a complete server-rendered chapter index, 288 characters of real
content against 2,418 of ordinary page script. A warning that reads the same on a short page and on
an unreadable one is evidence about neither. Thresholds raised to require all three of: >10 KB
script, <500 characters of text, and a 20× ratio. **The negative control — a short-but-complete
page that must NOT warn — is now asserted alongside the positive case.**

**3. A probe that measured the wrong object.** `corpus::fetch_and_extract` built its own
`Client::new()`, so `connection_stats()` reported the *shared* client — which had never run. The
first live benchmark printed `handshakes 0, reused 0` beside ten completed fetches. That reads as
"pooling is broken" and meant "you measured a different client". Same family as
`get_providers()` reporting registered rather than where nodes ran. Fixed by using the shared
client, which is also what makes the pool outlive a batch.

## Measured

CPU, synthetic 90 KB article page, release build:

```
old path (from_utf8_lossy)   0.020 ms    93,064 chars to the model
new path (extract)           0.178 ms    10,990 chars to the model
reduction 88.2%  (8.5x fewer chars)   throughput 498 MB/s
```

Corpus, 300 documents / 25.3 MB, 16 cores:

```
serial          26.9 ms    939 MB/s
extract_many     4.7 ms   5,394 MB/s      5.74x
```

The speedup is memory-bandwidth-bound rather than core-bound at 5.4 GB/s; it is not 16×, and
claiming otherwise would be a proxy for a number nobody measured.

End to end, 10 real URLs including a 2.2 MB arXiv PDF:

```
serial (concurrency 1)   1016 ms
concurrent (16)           222 ms      4.57x
read 10/10   2609 KB wire -> 621 KB text
TLS handshakes 10, connections reused 10
```

**Pooling alone nearly halved the serial pass** — 1968 ms before the shared client, 1016 ms after —
so the concurrency multiplier is measured against an already-improved baseline rather than against
the old code.

## What this does NOT change, stated because the boundary was explicit

- **No trust-class change.** `web` returns `UntrustedContent` exactly as before. Extraction does not
  launder: a cleaner rendering of untrusted content is still untrusted content.
- **No egress change.** `corpus::fetch_and_extract` has no `EgressPolicy`, cannot obtain one, and
  must never grow one. Every URL reaching it has already been adjudicated.
- **Redirects are still not followed**, in either the single or the batch path.
- **The agent loop is untouched.** `Engine::tool_batch` still executes batched tool calls in a
  `for` loop, so 30 parallel `web` calls from the model still run serially. `Client` and the corpus
  API are `Send + Sync` and internally concurrent, so that remains a self-contained change to make
  when it is authorised — but it was **not** made here.

## Consequence to know

`web` no longer falls back to raw bytes when extraction fails. It returns `unreadable` with the
reason and reads nothing. Handing over undecodable input would put the exact material this ADR
removes back into the window, on the one path nobody tests.
