# ADR-072 — A thought is measured in tokens, a frame is not one, and the engine is the only witness

**Status:** PROPOSED — **built, and the human has chosen the shape.** The choice recorded in §5 was
put to the human on 2026-08-31 with §2's measurements in hand; the answer was *"do whatever you
recommend. No tokenizer. Has to work for all models."* `DECISIONS.md` is untouched.

This amends nothing. It **corrects** two sentences: `daemon.rs`'s *"one delta is one token on both
local engines"* and `protocol.rs`'s *"one per token on both local engines"*, both of which were
assumptions about a server that nothing had measured — `STATE.md` said so, under *"Still
unmeasured, and it is the next thing to pull on if the number still looks wrong."*

---

## 1 · What was on screen

```
▸ thinking… 1688 characters   ↵
▸ thought for 1688 characters   ↵
```

`text.len()`, in `render.rs`, and the same quantity in the classic CLI's `{} chars`. Characters are
what a renderer can count for itself, and that is the whole objection: **the number a person wants
here is what the model spent, and a renderer has no tokenizer.** Dividing by four would have been
worse — it replaces a number that is honestly the wrong quantity with one that looks like the right
quantity and is an estimate.

**A smaller thing, noted because it is the same shape one size down:** `String::len()` is **bytes**,
so the line said *characters* and reported bytes. A thought containing an em dash or a `×` counted
three and two. Nobody would have found that from the screen, because a number that is 3% off a
quantity nobody wanted is indistinguishable from the quantity nobody wanted.

## 2 · The measurement, and it overturns a documented assumption

Taken 2026-08-31 on this machine. Ground truth is `llama-server`'s `/tokenize` on the **same GGUF
blob Ollama was serving**, so both sides are the same vocabulary.

**First, the control that makes the rest meaningful.** For three greedy runs,

```
eval_count == tokenize(thinking_text) + tokenize(content_text)     residual 0, 0, 0
```

So retokenizing the streamed text reproduces the engine's own count exactly. There are no hidden
tokens to argue about, and `eval_count` is a trustworthy total.

**Then the finding.** Counting NDJSON frames does *not* reproduce it:

| prompt | thinking frames | exact tokens | frames are |
|---|---|---|---|
| `Say hi.` | 116 | 120 | −3.3% |
| `What is 2+2?` | 179 | 200 | −10.5% |
| `Name one primary colour.` | 236 | 250 | −5.6% |

Identical across three repetitions of one prompt at `temperature: 0`, so it is **not** a slow
client losing frames — it is deterministic. A raw frame dump shows why: Ollama's own thinking
parser buffers a whitespace-leading token and flushes it joined to the next one (`"\n\n1"`,
`"  **"` arriving as single frames). `/v1/chat/completions` merges identically, so there is no
endpoint to move to.

**The content channel is exactly one token per frame** — 60 frames against an `eval_count` of 61,
the extra being the stop token — and that asymmetry is what makes §4's arithmetic possible.

`llama-server`, asked with `timings_per_token: true`, puts `timings.predicted_n` on **every**
streamed chunk: 41 of 43 chunks carried it, finishing on exactly the `completion_tokens` the usage
chunk reported.

## 3 · Why this is instance #20 rather than a bug

Nothing was broken. `daemon.rs` counted deltas for the **cadence band**, which reports a *rate*,
and a rate is a ratio over an interval whose numerator has to be what this process saw arrive while
the clock ran. As a throughput figure that count is correct. The sentence beside it —
*"one delta is one token"* — answered an **adjacent** question, and the moment a second consumer
needed *spend* rather than *throughput* the adjacency became a 10% error.

The tell is the one this project keeps writing down: **the number arrived with a citation instead
of a command.** `STATE.md` had already flagged it as an assumption about a server with nothing
measuring it, and it survived anyway, because a frame count and a token count read identically.

## 4 · The rule, and it is one sentence

> **Every token the engine reports as generated belongs to the channel that was open when it was
> produced.**

Tokens the engine counts but never streams — think delimiters, the stop token, whitespace merged
into a later frame — go to the channel that was open. The count travels **with the chunk**, as a
delta the receiver adds; nothing downstream re-derives it.

Per engine:

| engine | live | at end of call | exact? |
|---|---|---|---|
| **llama.cpp** | `timings.predicted_n` increment per chunk | remainder to the open channel | **yes, throughout** |
| **Ollama** | one per frame — a rising lower bound | `eval_count − answer tokens` | **yes at end of call** |
| **OpenRouter** | one per chunk — a lower bound | `usage.completion_tokens` remainder | as exact as the provider is |

`0` is an ordinary value on that delta: a buffer released after the frames that filled it were
already counted. An **empty chunk with a non-zero count** is the settlement, and it must join the
block it settles rather than open one — a call that produced no reasoning still generates a stop
token, and without that rule every answer in the product would grow a thinking line under it
reading `thought 1 token`.

## 5 · The three ways this could have gone, and why the middle one

**A — count frames, document the bound.** Simplest. Ships a number knowingly 3–10% low on the
Ollama path, which is precisely the shape this repo's ledger exists to catch. Rejected.

**B — the engine's own count, settled at end of call.** What is built. No per-model constant is
subtracted anywhere: `</think>` costs a different number of tokens in a different vocabulary, and a
constant measured on one model is not a fact about another — that is this project's own rule about
carrying a measurement across a boundary, applied to a template. The cost is that the Ollama figure
is a *definition* at the margin: the ≤2 tokens of closing delimiter and stop sequence land in the
thought rather than nowhere. That is stated rather than hidden, and it is bounded, unlike A's 10%.

**C — tokenize the text with the model's own vocab.** Exact everywhere, and it is *available*:
`/tokenize` reproduced `eval_count` with residual 0, which is how §2 was measured at all. It was
rejected by the human on two grounds — **no tokenizer**, and **it has to work for all models**. A
GGUF vocab reader plus a BPE implementation is a second copy of the engine's tokenizer that can
drift from it, and drift in a scored path is a failure this project has already had (ADR-015, where
two graph optimization levels gave logits 0.0699 apart).

## 6 · What renders when the count is unknown

`0` renders as **no number** — `▸ thought   ↵`, not `▸ thought 0 tokens`. A replayed turn has the
reasoning text and never had the count, because `WireTurn` carries what the endpoint documents and
a token count is not part of that shape. `0 tokens` would be a claim about a model that plainly did
think. **A missing field renders as missing**, which is the rule `Event::Approval`'s `novelty`
already follows.

Recording the count in `WireTurn` would fix replay and is deliberately **not** done here: that
struct is serialized into the outbound request body, so a field added for the transcript's benefit
becomes a field sent to the model.

## 6b · Live-verified, on the running process

Not a test process. One turn read off the **daemon's own socket** — the same instrument this repo
adopted after `persona_emission.rs` went green against a stale deployment:

```
reasoning chunks on the wire : 111
reasoning tokens reported    : 133
settlement chunks (empty)    : [23]
text chunks                  : 21
```

110 text-carrying frames at one token each, plus one empty settlement of 23. The frame count would
have read **110** against the engine's **133** — 17% low on this turn, wider than any cell in §2.

## 6c · What the first live read found, and it was not the count

`▸ thinking… 226 tokens` **on a turn that had answered**. The number was right; the block was never
closed. `Event::Text` was the only writer of `done` and it checked `transcript.last_mut()`, so it
closed a block only while that block was still the last entry — and every turn with a tool in it has
a second one:

```
R×58  R0  TOOL(running) TOOL(ok)  R×297  T×9  R0  DONE
```

**Older than this ADR** — the same turn read `thinking… 1688 characters` before — and unrelated to
the count. Changing the unit is what made it worth reporting: a stale character count is one more
slightly-wrong number; a stale `thinking…` under a finished answer is a claim about work in
progress.

`watch_client::entries()` has carried the correct rule since ADR-055. The conversation pane never
got it, exactly as it never got `control_plane::push`'s tool-line rule. Now one definition,
`close_finished_reasoning`, and the seam is covered by a test in `marlowe` — the only crate that can
see the daemon's fold and the surface's renderer at once, which is why three green crates and a
broken product were consistent.

## 7 · What is NOT settled

1. **`Cadence::tokens` remains a count of deltas** and is now documented as such. It is throughput
   as this process observed it; `Entry::Reasoning::tokens` is spend as the engine counted it. Two
   quantities, deliberately not unified — but a reader who sees both on one screen may reasonably
   ask why they disagree, and nothing on the screen answers that.
2. **`Usage` gains no `reasoning_tokens` field**, so the split does not reach the journal or the
   run record. Only the surface sees it.
3. **The Ollama live figure jumps at end of call** — from the frame count up to the engine's — and
   nothing measures how visible that is on a long thought. It is an upward correction on a line
   that is already moving, which is why it was judged acceptable without a live read.
4. **`crates/marlowe-loop/src/driver.rs` is a §13-guarded file and it was edited.** The guarded
   subject is *the memory and approval ports*; what changed is the **provider** port's streaming
   callbacks, which share the file. The hook fired on the path, as designed. This ADR is the
   record CLAUDE.md asks for.
