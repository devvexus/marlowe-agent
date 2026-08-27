# ADR-061 · `read` returns line numbers, `edit` refuses the prefix it printed, and one snippet means one site

**Status:** Accepted, 2026-08-27. Extends ADR-058 (`write` is its own tool) and ADR-059 (`find`
becomes `grep`). ADR-060 was taken by the local-model runtime; the design proposed 059 and both
numbers were already spent.

---

## 1 · The gap, stated as two tools that could not talk to each other

ADR-059 made `grep` report `path:line:text`. `read` reported neither a line number nor any way to
compute one. So a model holding `crates/marlowe-loop/src/engine.rs:1888` had **no bounded way to
turn it into a window** — `range` is 1-based and absolute, and nothing in a `read` result said what
line anything was on. It could read the file from the top and count.

That is the whole motivation. Numbering is not a display preference; it is the missing half of a
correspondence between two tools that already speak in line numbers on one side.

## 2 · The format, and why each part of it is load-bearing

**`{:>6}` + TAB + the line verbatim, with ABSOLUTE file line numbers.**

* **`cat -n` is the most-seen form.** It is in every shell transcript, it neighbours `grep -n`, and
  it is what the reference implementation emits. The skill being asked of the model is not
  *emitting* the prefix — it never emits one — it is **recognising and stripping** it, and
  recognition is strongest for the most-seen shape.
* **The tab is what makes §3's detection tight.** Source lines legitimately begin with spaces; they
  essentially never begin with `spaces + digits + TAB`. A `: ` or `| ` separator would put
  `42: foo` — ordinary log text — and every markdown table inside the grammar.
* **Right-alignment to a fixed width keeps the content column constant.** Not cosmetic. The most
  common `edit` failure in this executor is a whitespace mismatch — `replacing_miss` carries a
  dedicated branch for it — and a left-aligned number shifts the content column between line 99 and
  line 100. That is the harness corrupting the model's view of indentation *inside one window*.
* **Absolute, not window-relative.** `read(range: "500-600")` returns `   500\t…`. Window-relative
  numbering would look authoritative and be wrong, which is strictly worse than no numbering,
  because the number could no longer be handed back as a range. It has its own negative control
  (`a_read_returns_the_file_line_numbers_and_not_the_windows`) and its own mutation run.

Rejected: `→` as a separator (non-ASCII, an extra token per line, and it passes through
`text::sanitize` on other paths — a separator any sanitiser might touch is the wrong separator);
and `path:N: text`, `grep`'s shape (`grep` repeats the path because each hit is a different file;
`read` is one file, named once in the call).

### 2.1 · Three ordering rules, and one of them is a constant that had stopped meaning anything

1. **Number after windowing, before the trailer.** `READ_WINDOW_LINES` truncation runs first; then
   numbering; then the `[showing lines …]` block is appended **unnumbered, at column 0**.
2. **`READ_WINDOW_BYTES` measures what is RETURNED, so it is applied AFTER numbering.** A prefix
   costs 7 bytes a line; a full 2,000-line window gains ~14 KB. Capping the raw text and then
   adding 14 KB would leave the declared 32 KB ceiling describing a quantity that never reaches the
   model — the proxy failure this repo has logged seventeen times. **Measured on the mutated
   build: 41,979 bytes returned against a declared 32,768.** The visible consequence is that a
   numbered window is often fewer than 2,000 lines; nothing becomes unreachable, because the notice
   names the next range either way. `READ_WINDOW_BYTES` was deliberately **not** raised to
   compensate — that is a separate decision about context spend and needs its own argument.
3. **The `MAX_READ_BYTES` cap note moved out of `text`.** It used to be pushed into the text before
   `range` ran, so it was a range-selectable line that counted toward the file's length — and under
   numbering it would have acquired a line number, which stops the numbering being a faithful map
   of the file. It is now in the same unnumbered trailer as the window notice.

### 2.2 · A pre-existing defect this would otherwise have made universal

`str::lines()` **strips a trailing `\r`**, and `read`'s window path did
`text.lines().take(N).collect::<Vec<_>>().join("\n")`. **A windowed or ranged read of a CRLF file
silently returned LF**, so a `replacing` copied out of it could never match — and the message the
model got named the wrong cause. Whole-file reads under both ceilings escaped it, which is why
nobody had hit it.

Numbering routes *every* read through a line decomposition, so this would have gone from rare to
universal and been blamed on this change. `number_lines`, `slice_lines` and the line window now all
walk `split_inclusive('\n')` and re-emit terminators verbatim, and `replacing_miss` gained a CRLF
branch. There was no CRLF handling anywhere in `marlowe-exec` before this.

## 3 · Detection, and why the named refusal's false-positive rate is zero by construction

The harness now manufactures a way for `edit` to miss: it prints a prefix, tells the model to copy
`replacing` out of a `read`, and matches the file byte for byte. A feature that creates a failure
mode owes that failure mode a diagnosis.

`strip_line_numbers(text) -> Option<String>` returns `Some` iff **every** line matches
`^( *)(\d+)\t` with `spaces + digits == LINE_NUMBER_WIDTH` (or no padding above a million lines)
**and** the numbers are strictly consecutive.

The grammar alone has false positives — a terminal transcript, a fixed-width report, a fixture in
this crate. **The bound is structural, and only the first of its three conjuncts is a heuristic:**

1. `replacing` parses as numbered — heuristic.
2. **`existing.find(replacing)` has already MISSED.** The detector lives in `replacing_miss`, which
   runs only on that path. A file that genuinely contains `      42\tfoo`, edited with exactly that
   snippet, **matches and is edited normally** — the detector is never reached. Asserted directly
   (`a_file_that_really_contains_numbered_text_is_edited_normally`).
3. Stripping the prefixes makes it match: `existing.find(&stripped)` succeeds, and its line is
   reported.

(3) is what turns a guess into a checked diagnosis. The message does not say "this looks numbered";
it says *"stripped, your text IS in the file, starting at line 42"* — verified against the file the
executor is holding. The residual case is enumerable and empty: a file containing both
`      42\tfoo` and bare `foo` fails (2), so the edit proceeds and the detector never fires.

A second tier — grammar matched, stripped form still absent — states both facts and guesses
neither. That is where the residual uncertainty is put, inside a message that was already a refusal
for a real miss.

### 3.1 · `content` is the worse half, and the two tools answer differently

A prefixed `replacing` fails loudly. A prefixed **`content`** *succeeds* and writes `   42\t` into
the source, reporting `+n −m`. That is the empty-`replacing` prepend one step worse, at the same
call site.

| parameter | fires at | why the threshold differs |
|---|---|---|
| `edit.replacing` | **1 line** | cross-checked against the file, so the named refusal cannot be wrong; and one line is the modal case, because the description tells the model to keep it short |
| `edit.content` | **`NUMBERED_CONTENT_LINES` = 2** | no file to check against, so the grammar carries the whole burden; one numbered-looking line is plausibly genuine |

**`edit` REFUSES and names `write`. `write` WARNS and proceeds** — `Metric::State("line-numbered")`
plus a `detail` sentence. Splicing prefixes into existing code is never intended; writing a whole
file that legitimately contains `cat -n` output (a transcript, a fixture, this ADR's own tests) has
to stay possible through the tool surface, and `write` is where that happens. The asymmetry mirrors
the `edit`→`write` referral ADR-058 already uses twice, so no capability is lost.

## 4 · `replacing` must be unique, and that is only useful because of §2

`edit` replaced the **first** occurrence and reported `+1 −1`. A rename whose old name appears
twelve times was edited once, and **the summary is indistinguishable from the summary of the edit
the model meant to make**, so the run moves on. The old test asserted this behaviour as correct;
it now asserts the refusal.

Refusing is only worth doing if the message can say **where**:

> `` `replacing` occurs 4 times, at lines 12, 40, 88 and 91. `edit` changes ONE snippet, so it must
> appear exactly once — add a neighbouring line to make it unique, or edit each site in a separate
> call. ``

That sentence is possible only because `read` numbers now. The two changes compound; neither is
worth much alone. The enumeration is bounded by `MAX_EDIT_SITES_NAMED` = 8 with an exact count —
ADR-059 had to fix the same shape in `grep`'s truncation notice, which listed 250 paths on one line.

## 5 · No line-anchored edit

Rejected, for four reasons in descending weight.

1. **A line number is stale the moment anything writes, and this executor batches concurrently.**
   Exact-string matching is self-validating: if the file moved under you, the match fails and you
   are told. A line anchor addresses whatever is now at line 42 and writes either way.
2. **It reinstates the ambiguity ADR-058 deleted.** `edit` was two tools wearing one name, told
   apart by an optional parameter. An optional `at_line` as an alternative to `replacing` is that
   shape, in that tool.
3. **The failure it would prevent is better prevented by a message.** A correct diagnosis costs one
   call; a line-anchored edit landing in the wrong place costs a file, and the summary reads `+3 −3`
   either way.
4. Claude Code has no line-anchored edit, and coding parity with Claude Code is the stated goal.

The variant worth naming and still deferring: `at_line` as **advisory only**, to disambiguate a
non-unique `replacing`. §4 solves that without a parameter.

## 6 · The `edit`/`edit` race in one batch — fixed here, because §4 made it likely

`execute_batch` runs a turn's calls concurrently and each `edit`/`write` does its own
read-modify-write through its own cloned handle. **Two edits to one file both read the original,
and the second's `set_len(0)` + `write_all` overwrote the first. Both reported success.**

It has been reachable since batching landed. What made it urgent is §4: the remedy that refusal
names is *"edit each site in a separate call"*, and separate calls in one turn are exactly one
batch. Closing one hazard by routing the model into another is not a fix.

`FileSystemTools` now holds one `Mutex<()>` held across the whole read-modify-write in both `write`
and `edit`. **One lock for all mutations, not one per path**: a batch is a turn's worth of calls, a
file rewrite is microseconds, and the batch's real cost is `web` fetches, which do not take it.

**The unguarded build is worse than the description above.** Running the control, the failure that
appeared first was not a lost write but a **spurious refusal**: a concurrent `edit` observed the
file mid-truncation and reported *"the file is empty, so there is no snippet to replace"*.

## 7 · What this does NOT do

* **`read(ref)` is not numbered.** It returns `UntrustedContent`, so `Engine::condense_batch` routes
  it to a quarantined reader. Numbering it costs fidelity (the summariser's input becomes a
  harness-mangled document) and, worse, forges the harness's own voice: `condense_chunk` rests on
  source labels being *"assigned here, never taken from the content"*, and a harness-authored prefix
  on every line of attacker-controlled text is exactly a harness marker inside attacker-controlled
  text. There is nothing to edit in a fetched page, so the numbers buy nothing.
  Asserted as a **conjunction** in one test, using `marlowe_permission::blocks_composed_targets` —
  the same predicate `engine.rs:1888` routes on — because either half alone can drift green.
* **No new tools.** 12 builtins + 2 MCP slots = 14 = `MAX_EXPOSED_TOOLS`, and that cap carries no
  spare by design.
* **`READ_WINDOW_BYTES` is not raised.** See §2.1.

## 8 · Constants introduced

| Constant | Value | What moving it would change |
|---|---|---|
| `LINE_NUMBER_WIDTH` | 6 | the column width, the grammar's padding rule, and `read`'s description — the description's number is parsed and compared in `each_description_promise_is_kept_by_the_executor` |
| `NUMBERED_CONTENT_LINES` | 2 | when `edit` refuses numbered `content` and `write` flags it; also parsed out of `edit.content`'s prose |
| `MAX_EDIT_SITES_NAMED` | 8 | how many sites a non-unique refusal enumerates before "and N more" |
