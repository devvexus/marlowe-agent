# ADR-059 · `find` becomes `grep`, the engine becomes a real regex, and the walk stops disappearing into `target/`

**Status:** Accepted, 2026-08-27. Supersedes the `find` registration in ADR-006's set.

---

## 1 · The rename is a bug fix, and the evidence is in one string

`SHELL_DESCRIPTION` told the model both of these, in one paragraph, in one request body:

> "So `ls`, `grep`, `find`, `head`, `sed`, `awk` … all work as you expect."
>
> "**Reach for a real tool first** — `glob` lists files, `find` searches inside them"

Sentence one asserts unix semantics, where `find` matches NAMES and `grep` matches CONTENTS.
Sentence two asserts the inverse. **Two contradictory definitions of one word in one tool schema**
is stronger evidence than any appeal to a model's priors, and it is why the fix also deleted `grep`
and `find` from the unix-command list rather than only renaming the tool — otherwise `grep` would
appear twice in one description meaning two different things.

Corroboration in the repo's own instrument: `tool_call_probe.rs` elicited a *contents* search with
the prompt *"Find every occurrence of TODO."* — the English word that means filenames. That trial
was measuring a coin flip. It now reads *"Find every occurrence of TODO inside the files."*

## 2 · `regex`, not `fancy-regex`, and catastrophic backtracking is structurally impossible

`regex` 1.13.1 was already in `Cargo.lock` and **not in the product**: `cargo tree -p marlowe -i
regex` printed *"nothing to print"*. The existing entries come from `marlowe-embed-spike` (marked
TEMPORARY, deleted when ADR-004 closes) and an unbuilt ratatui backend, so this is **zero new
registry sources but not zero new compiled code**, and it is stated that way rather than claimed
away.

`fancy-regex` is also in the lockfile and is **refused**. It is a backtracking engine — that is
why it has lookaround — and using it would import exactly the ReDoS class this decision is asked
about. `regex` is finite-automata based with a documented worst case linear in the haystack, so
`(a+)+$` over 100k `a`s runs in linear time. **The DoS class is closed by the choice of crate, not
by a guard we would have to write and test.**

What can still be spent, and what bounds it:

| Vector | Bound |
|---|---|
| Compile-time state explosion | `size_limit` + `dfa_size_limit`, both `REGEX_SIZE_LIMIT` = 1 MiB, below the crate's 10 MB default. Over-limit is a compile **error** the model reads and fixes |
| Bytes scanned | `WALK_FILE_CAP` × `MAX_READ_BYTES`, now *reduced* by `WALK_SKIP` and by the `glob` filter |
| Hit accumulation | `MAX_MATCH_LINES` (200) and `READ_WINDOW_BYTES`; past either, the result degrades to per-file counts and says so |
| One pathological line | `MAX_MATCH_LINE_BYTES` (512), with the truncation marked in the line |

The regex is compiled **once**, outside the file loop. `Regex::new` per file × 2000 is the only way
to make a linear engine expensive.

**A note on the test for the size limit, because it is the ADR's own instance of the standing
failure family.** The obvious fixture is `a{1000}{1000}{1000}`, and it does **not** discriminate:
it is refused at the crate's 10 MB default too, so a control built on it is green on a build where
`REGEX_SIZE_LIMIT` is never read. Measured:

```text
a{1000}{1000}{1000}   default=Some("… exceeds size limit of 10485760 bytes.")
                      limited=Some("… exceeds size limit of 1048576 bytes.")
a{300}{300}           default=None
                      limited=Some("… exceeds size limit of 1048576 bytes.")
```

Both are asserted. The second is the only evidence the constant is read at all.

## 3 · The measured defect, which is larger than the rename

`collect` is a LIFO walk with a hard cap and **had no skip list**. `target/` on this checkout holds
~162,000 files, so `grep(pattern, path=".")` filled all 2,000 slots with build artifacts and never
reached `crates/`. Reproduced by disabling `WALK_SKIP` on the finished implementation and running
the shipped executor against this repository:

```text
--- WALK_SKIP emptied:  grep "WALK_SKIP" "."  =>  0 results · 927 files
--- WALK_SKIP live:     grep "WALK_SKIP" "."  =>  12 results · 1955 files
```

And `find` — unlike `glob` — **never checked whether the cap had bitten**, so the zero was reported
as a fact about the workspace. That is the session-B1.5 family verbatim: the harness knew and did
not say.

**The harness already owned the list and did not share it.** `marlowe_daemon::workspace_map`
carried a private `SKIP` with exactly the six right names. It is now `marlowe_exec::WALK_SKIP`, one
definition, read by the map builder and by the walk both tools search with.

`FIND_FILE_CAP` is renamed `WALK_FILE_CAP`. It has always bounded `glob` as well, so a name saying
it belonged to one tool sent every reader of `glob`'s cost model to the wrong constant.

## 4 · Four parameters, six rejections, and one refusal

**`pattern`, `path`, `glob`, `context`.** Every one required-or-obvious; none a mode switch.

| Rejected | Why |
|---|---|
| `-i` as a Boolean | `ollama.rs` maps a real JSON `Bool` to `Boolean` and the string `"true"` to `Text("true")`, so a Boolean from a 9B model is a coin flip on the wire. `(?i)` is standard regex, costs no schema, and the undeclared-argument refusal names it. **The measurement that would overturn this is in `tool_call_probe.rs`**, as two case-insensitive trials: decide on the number, not on this paragraph |
| `type` (`js`/`py`/`rust`) | `glob` subsumes it. A type table is a second vocabulary to learn and maintain for zero capability |
| `output_mode` | The shape ADR-058 deleted from `edit`: a model holding a request and a schema having to infer which tool it is in. The capability is taken **adaptively** — the result degrades to counts past `MAX_MATCH_LINES` and says so. The budget lever fires when it is needed, not when a model guessed |
| `multiline` | The whole result grammar is `path:line:text`. Multiline breaks it |
| `head_limit` / `offset` | Pagination invites paging instead of narrowing. The truncation notice names `glob` — the cheap fix, not the expensive one |
| line numbers as a switch | Always on. Free |

**`grep` refuses any argument it does not declare, naming the four it does and naming `(?i)`.** The
precedent is `recall`'s removed `payload_kind`: accepted, ignored, never reported, so a model that
passed it believed it had filtered and got an unfiltered answer. Scoped to `grep`; generalising it
to every executor is right and is a separate change.

## 5 · The `glob` filter runs INSIDE the walk, and outside it would have been decorative

The design this ADR was written from specified `glob` as a filter over the walk's output. **That
cannot fix the defect it exists for.** The cap bounds *enumeration*, so 2,000 build artifacts still
consume every slot before the first `.rs` file is reached and `glob: "*.rs"` narrows a set that
already stopped short of the code. Filtering inside the walk is what makes the cap count files that
could actually match. `a_glob_filter_reaches_source_that_the_cap_would_otherwise_hide` fails if it
moves back out, and its control applies both halves of that move.

The same change applies to the `glob` tool's own `pattern`, which had the identical defect.

## 6 · What the result now states that used to be inferable

Four things, each with the constant `format!`ed in so the sentence cannot drift from the bound:

1. the walk stopped at `WALK_FILE_CAP`, and `glob` is the way to narrow it;
2. which `WALK_SKIP` directories were declined, and that naming one as `path` searches it;
3. matches truncated, with per-file counts for the heaviest files;
4. files read only in part, and files that were not text — the latter of which `find` discarded, so
   a binary file incremented `scanned` and the denominator in `N results · M files` was wrong.

**A notice is not exempt from the caps the result is under.** Run against this checkout, the
partial-read notice listed 250 `.rlib` and `.pdb` paths on one line — a context flood inside the
sentence that exists to prevent one. `NAMES_IN_A_NOTICE` = 10 plus a count.

Three further inherited defects are fixed:

* **`body_for` → `body_for_window`.** `find` handed anything over `MAX_INLINE_BYTES` to `body_for`,
  which returns a `ContentRef` whose hash **cannot be dereferenced** — `read`'s `ref` takes ids
  `web` issued — with a preview reading *"the tool read the whole file"*, which is not even true of
  a search. Exactly the defect fixed for `read` at `fab045d`. `glob` had it too and has it fixed.
* **Indentation is preserved.** `find` emitted `line.trim()`, and `edit` REQUIRES `replacing`
  *"copied verbatim from a `read` including indentation"*. A model that grepped a line and edited
  with what it got back was told *"`replacing` was not found in the file"* with nothing on screen
  explaining why. The test asserts the two tools COMPOSE, which is where the defect bites.
* **Results are sorted by `(path, line)`.** `glob` sorted; `find` returned `read_dir` order.

Format: `path:line:text` for a match and `path-line-text` for a context line — ripgrep's
convention, and dropping the space after the colon is what makes *"indentation is preserved"*
unambiguous.

## 7 · Two dead things found on the way, and neither is asserted on

**`SummarySpec::verb` has ZERO readers.** A grep for uses outside its own module returns
constructors and one test. The proof it is dead: `glob`'s registration passed the literal `"find"`
as its verb and nothing ever noticed. The §B6 verb a user sees comes from `tool.to_string()` on the
wire. The value is corrected to `"glob"`; **it is deliberately not asserted on**, because asserting
a dead field's value is the sixteenth-instance family, which is how the wrong value got there.

**Both §B6 verb tables were already broken, in a way the brief predicted.** `watch_client.rs` was
missing **`write` and `glob`** — both live builtins whose calls reach the wire as
`tool.to_string()`, so every one of them in a `/watch` window rendered as the generic `tool`. Those
are the fourth and fifth instances of the gap `project.rs` already records for `use`. Nothing bound
either table to `BUILTIN_TOOLS`: a grep for that constant returns 29 sites and not one is in
`marlowe-daemon`. `every_builtin_is_in_the_section_b6_verb_vocabulary` now drives both from the
constant, and it **failed on the tree as it stood**, which is its control.

## 8 · Durability

Nothing reconstructs a call from the journal by tool name — `journal_records_why.rs` selects by
`EventKind`, and signatures are over payload bytes as written. Two consequences are real and both
are handled:

* **Historical §B6 rendering.** The daemon seeds runs from the journal on restart. Both verb tables
  keep `"find" => "find"` as a **labelled legacy arm**, so an old journal stays readable instead of
  rendering as a wall of `tool`. `an_old_journals_find_still_renders_as_a_verb` stops it being
  tidied away.
* **Memory.** `recall` can return a belief from an earlier session saying "use `find`". A retired
  name in live prose is worse than an invented one, because it reads as correct to everyone who
  remembers it — so `no_live_prose_names_a_retired_tool` sweeps the governance prompt, the
  `<workspace>` map, and **every registered tool and parameter description** for `done` and `find`.
  It is narrower than `unknown_tools_named_in` on purpose: descriptions are full of backticked
  lowercase words that are not tools and never were (`ls`, `head`, `sed`, `cwd`, `path`), and a
  guard that flagged those would be switched off within a week.

A half-done rename cannot ship: `daemon.rs` calls `verify_every_exposed_tool_is_runnable`, so a
profile saying `grep` against an executor saying `find` **refuses to boot**. No fallback was added
that would take that away.
