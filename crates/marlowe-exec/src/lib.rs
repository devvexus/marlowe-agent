//! The filesystem and shell executors: `read`, `edit`, `find`, `bash`.
//!
//! # The one rule this crate exists to obey
//!
//! **Every executor operates on the handle the adjudicator opened. None of them re-opens a
//! path.** `Adjudication::handles` carries the [`ScopedPath`]s the permission layer produced
//! while checking the call; a tool that took `scoped.resolved()` and called `File::open` on it
//! would reopen the check-then-use race **across the permission boundary** — the one place
//! `tests/traversal.rs` would never look, because that suite tests the checker and the race
//! would be in the caller.
//!
//! `tests/handles.rs` asserts it directly rather than trusting the comment.
//!
//! # Where a tool touches more than its declared targets
//!
//! `find` reads many files, only one of which the model named. Those extra opens are not
//! unchecked: each one is routed back through the same [`PathScope`], so every byte this crate
//! reads came through the wall. The model's argument is what the `(action, target)` check
//! adjudicated; the enumeration underneath it is a source of *candidate names*, not a source of
//! authority.
//!
//! # `bash` and the cwd string
//!
//! `CreateProcess` takes a working directory as a **string**, not a handle — there is no
//! handle-relative spawn on Windows. So `bash` holds the verified directory handle open across
//! the spawn and relies on the walk's pinning a **second time**: no `FILE_SHARE_DELETE` means
//! the directory cannot be renamed or deleted, so the string still names the verified object.
//!
//! That argument is load-bearing in a second place, so it earns its own assertion rather than
//! inheriting the walk's — see `tests/bash_cwd.rs`. On POSIX there is no such gap: the child
//! `fchdir`s to the descriptor before `exec`.

// `deny`, not `forbid`, and the exception is named. `Command::pre_exec` is unsafe by contract —
// the closure runs after `fork` and before `exec`, where only async-signal-safe calls are legal.
// `fchdir` is one. This is the only `unsafe` in the crate and it is what lets POSIX pass a
// DESCRIPTOR to the child instead of the path string Windows is forced to use.
#![deny(unsafe_code)]

pub mod corpus;

use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

use marlowe_contract::TrustClass;
use marlowe_loop::{ToolBody, ToolHost, ToolOutcome};
use marlowe_permission::scope::{Access, PathScope, ScopedPath};
use marlowe_permission::{Adjudication, ArgValue, Args};
use marlowe_tools::{Metric, PathGlob, ResultSummary, ToolId};

/// How much of a tool's output is kept. Above this the result is a reference and the loop sees
/// only the §8 summary — §6's *"the raw data should never touch attention"*.
pub const MAX_INLINE_BYTES: usize = 8_192;

/// How many lines one `read` returns when the caller does not say.
///
/// # A file is read through a WINDOW, the way Claude Code reads one
///
/// `read` used to return the whole file. Anything over [`MAX_INLINE_BYTES`] then became a
/// `ContentRef` — a hash plus a 4 KB head-and-tail — and **that hash is not dereferenceable for a
/// file**: `read`'s `ref` parameter takes ids that `web` issued, not file reads. So the middle of
/// any file above 8 KB was simply unreachable. The model could glimpse both ends and nothing else.
///
/// Watched live 2026-08-27: a run read `DECISIONS.md` (208 KB), `ROADMAP.md` (68 KB),
/// `CONTRACTS.md` (61 KB), `ARCHITECTURE.md` (33 KB) and `M3-DESIGN.md` (32 KB), got head and tail
/// of each, and could not answer from any of them.
///
/// 2,000 lines matches the reference implementation. It is a **default**, not a limit: `range`
/// reads any window of the file, and a truncated result says so and says how.
pub const READ_WINDOW_LINES: usize = 2_000;

/// The byte ceiling on one window, whatever its line count.
///
/// 2,000 lines of ordinary prose is far more than a 32,768-token context can hold, so lines alone
/// do not bound this — one call could still swallow the window. 32 KB is roughly 11k tokens
/// against `DEFAULT_CONTEXT_TOKENS`, which leaves room for the conversation that asked for it.
///
/// Both bounds are reported when either bites, because a result that stops without saying so is
/// indistinguishable from a file that ended.
pub const READ_WINDOW_BYTES: usize = 32 * 1024;

/// Above this, a truncated read also says what the whole file would cost and names `find`.
///
/// A quarter of `DEFAULT_CONTEXT_TOKENS`. Below it a file is several windows at worst and the
/// short notice is enough; above it, reading the whole thing is a decision worth making
/// deliberately rather than by repeating `read` until the budget runs out.
///
/// **Held back deliberately.** Warning on every truncated read would make the warning worthless —
/// a model told that everything is expensive has learned nothing about what actually is.
/// What fraction of the context window makes a file worth warning about.
///
/// A quarter. Below it, reading the file costs a share of the window a run can afford to spend on
/// one call; above it, reading the whole thing is a decision worth making deliberately rather than
/// by repeating `read` until the budget runs out.
///
/// **Held back deliberately.** Warning on every truncated read would make the warning worthless —
/// a model told that everything is expensive has learned nothing about what actually is.
pub const LARGE_FILE_SHARE_OF_CONTEXT: u32 = 4;

/// The window assumed when nobody says. Kept as a literal rather than importing
/// `marlowe_provider::DEFAULT_CONTEXT_TOKENS`, because this crate must not depend on a provider —
/// `with_context_tokens` is how the real number arrives, and the daemon always passes it.
fn marlowe_provider_context_default() -> u32 {
    32_768
}

/// How many files `find` will open in one call. A search is bounded structurally rather than by
/// hoping the pattern is selective.
pub const FIND_FILE_CAP: usize = 2_000;

/// How long `bash` may run before it is killed.
///
/// **This is now read.** Audit finding A1: it was declared here and a grep over the whole repo
/// returned exactly one hit — this definition. Both `spawn_shell` implementations called
/// `Command::output()`, which blocks until the child exits, so any approved non-terminating command
/// (`ping -t`, `tail -f`, a blocking read) hung the batch, the turn and the daemon forever. It is
/// the "declared control nothing reads" family in its purest form, and the test that pins it kills
/// a real sleeping child rather than asserting this number.
pub const BASH_TIMEOUT_MS: u64 = 120_000;

/// How often the wait loop looks at the child.
///
/// **The deadline is counted in sleeps, not measured with a clock**, because §4.5 forbids a real
/// clock on any path reachable from the section 4 interfaces and `marlowe/tests/determinism_guard.rs`
/// enforces it across the workspace — it has already caught an `Instant::now()` in `bash`. So the
/// bound is a *lower* bound on wall time: under load the child gets somewhat longer than
/// [`BASH_TIMEOUT_MS`]. The property that matters is that the wait terminates, and it does.
const POLL_MS: u64 = 10;

/// How much output `bash` will hold, **per stream**.
///
/// Audit finding A2: `Command::output()` buffered stdout and stderr with no ceiling, `combine` made
/// a second copy through `from_utf8_lossy(...).into_owned()`, and `body_for` hashed and previewed it
/// again — peak around 3x the child's output, for `yes`, `cat /dev/urandom` or `dir /s C:\`.
/// `MAX_INLINE_BYTES` bounds only what reaches the model, never what is allocated. CLAUDE.md
/// records a `0x139` bugcheck on this machine under memory exhaustion, so this is not theoretical.
///
/// A breach **kills the child** rather than draining and discarding: draining would leave a command
/// producing output at line rate running until the timeout, burning a core for two minutes to
/// produce nothing.
pub const MAX_SHELL_OUTPUT_BYTES: usize = 1_048_576;

/// How long the reader threads are given to hand back what they read, after the child is gone.
///
/// A grandchild that inherited the pipe keeps it open, so a `join` here could block forever — the
/// hang this whole section exists to remove, moved one level down. After the grace the readers are
/// abandoned with whatever they had; the tool reports rather than waits.
const READER_GRACE_MS: u64 = 250;

/// The production [`ToolHost`].
///
/// It holds a scope because `find` needs one (see the header). It does **not** hold a workspace
/// path it could use to bypass the scope: the workspace is passed to the scope, which is the only
/// thing that turns a path into a handle.
pub struct FileSystemTools<S: PathScope> {
    scope: S,
    workspace: PathBuf,
    /// ARCHITECTURE §2.2's content store, scoped to fetched documents.
    ///
    /// **Every fetched document lands here, whole**, and the run receives a `DocumentRef` — a
    /// hash and a set of counts with no bytes of the page in it. Today the extracted text ALSO
    /// still flows to the run through layer 1's quarantined reader, so nothing regresses; the
    /// store is what makes the next step possible, where the text stops flowing at all and is
    /// pulled only when something asks a question of it. See `docs/design/adr/ADR-042`.
    store: marlowe_extract::store::DocumentStore,
    /// The model's context window, in tokens — **the thing "large" is large COMPARED TO.**
    ///
    /// A fixed byte or token threshold answers the wrong question. A 10,000-token file is most of
    /// a 32k window and a rounding error in a 200k one, and warning about it in both teaches a
    /// model with room to spare that the warning means nothing. So the executor is told the window
    /// and compares against it.
    ///
    /// Defaults to `DEFAULT_CONTEXT_TOKENS` so a host built without one still behaves sensibly;
    /// the daemon passes the number it actually sends as `num_ctx`, which is the same field the
    /// assembler sizes its view from.
    context_tokens: u32,
}

impl<S: PathScope> FileSystemTools<S> {
    pub fn new(scope: S, workspace: impl Into<PathBuf>) -> Self {
        Self {
            scope,
            workspace: workspace.into(),
            store: marlowe_extract::store::DocumentStore::new(),
            context_tokens: marlowe_provider_context_default(),
        }
    }

    /// The model's context window, so "this file is large" is measured against something real.
    pub fn with_context_tokens(mut self, tokens: u32) -> Self {
        if tokens > 0 {
            self.context_tokens = tokens;
        }
        self
    }

    /// Share one store across hosts. The daemon builds a single host today, so this exists for the
    /// case where a corpus must outlive one of them.
    pub fn with_store(mut self, store: marlowe_extract::store::DocumentStore) -> Self {
        self.store = store;
        self
    }

    /// The documents fetched so far. The dereference path reads from here.
    pub fn store(&self) -> &marlowe_extract::store::DocumentStore {
        &self.store
    }
}

/// Why `replacing` did not match, told so the model can act on it.
///
/// # The loop this ends
///
/// `path` is a `WritePath`, so the scoping layer opens it `CreateOrOpen` — **the file exists,
/// empty, by the time this executor runs.** A model writing a NEW file and supplying `replacing`
/// therefore searched an empty string, and got back *"`replacing` was not found in the file"*: a
/// true sentence describing a situation that does not exist, since the file it names had been
/// created by that same call one line earlier.
///
/// Watched live 2026-08-26, journal seq 4813-4839. The model tried `edit`, was told that, `read`
/// the file, got **"0 lines · 0 B"** — which is what an empty file and a file that was never
/// there both look like — tried `edit` again, read again, read again, and finally fell back to
/// `bash` to run `dir`. **Six calls, two minutes, one zero-byte file, and no way to learn why.**
/// The user's summary was "he can't even write a file, and he doesn't even know why".
///
/// Nothing was broken. `existing.find` was correct, the refusal was honest, and the message was
/// about the wrong thing. So the three cases are separated and each says what to do next.
fn replacing_miss(existing: &str, replacing: &str) -> String {
    // **The empty-file case does not reach here any more** — `edit` writes it, because a
    // `replacing` that cannot match anything in a file with no content is vacuous rather than
    // wrong. See the note at that branch. Debug-asserted rather than handled, so a future change
    // that routes an empty file back here is caught in the suite instead of shipping a message
    // about a case that has a better answer.
    debug_assert!(!existing.is_empty(), "an empty file is written, not refused");

    // **The overwhelmingly common miss is whitespace**, and saying so turns an unbounded retry
    // into one corrected call. Checked by collapsing runs of whitespace on both sides: if the
    // snippet is there apart from spacing, the model copied the text and not the indentation.
    let squash = |t: &str| t.split_whitespace().collect::<Vec<_>>().join(" ");
    if !replacing.trim().is_empty() && squash(existing).contains(&squash(replacing)) {
        return format!(
            "`replacing` was not found. The file DOES contain that text apart from whitespace, so \
             the indentation or line breaks differ — `replacing` must match byte for byte. `read` \
             the file and copy the snippet exactly as it comes back. The file is {} bytes, {} \
             lines.",
            existing.len(),
            existing.lines().count(),
        );
    }

    format!(
        "`replacing` was not found in the file, which is {} bytes and {} lines. It must match byte \
         for byte, including indentation. `read` the file first and copy the snippet from what it \
         returns — or omit `replacing` entirely to overwrite the whole file with `content`.",
        existing.len(),
        existing.lines().count(),
    )
}

fn failed(verb: &'static str, detail: impl Into<String>) -> ToolOutcome {
    // ── THE REASON GOES IN THE BODY TOO, AND THAT IS THE WHOLE POINT ────────────────────
    //
    // This returned an EMPTY body with the reason in `summary.detail`, and `detail` is the §B6
    // expansion — a field every consumer had to know to look in. The ones that did not:
    //
    // * the model's own window, which is built from `summary.render()` and the BODY, so a failed
    //   `edit` arrived as the literal string `"edit · "`;
    // * the journal, which recorded `{"tool":"read","summary":"read"}` — the name, twice;
    // * the surface, which shows `render()` only;
    // * and every failure assertion in `every_tool_exercised.rs`, which read the body and got the
    //   empty string, panicking with a blank message.
    //
    // Four consumers, four separate patches, one cause. **A failure's reason is not an optional
    // detail — it is the result.** Putting it in the body means nothing downstream has to know
    // that failures are shaped differently from successes, and the places already patched keep
    // working (`Engine::finish` appends `detail` only when the text does not already contain it).
    let detail = detail.into();
    ToolOutcome {
        summary: ResultSummary::with_detail(vec![Metric::State(verb)], detail.clone()),
        body: ToolBody::Inline(detail),
        // The harness computed this refusal, so it is agent-observed. Inheriting the call's own
        // taint would make a blocked-call notice unreadable by the very next step.
        trust: TrustClass::AgentObserved,
        failed: true,
        wall_ms: 0,
        preview: None,
    }
}

/// Inline if small, reference if not. §2.8's first axis — **size**, independent of trust.
///
/// **`read` does not come through here any more** — see [`body_for_window`]. A file bounded by
/// [`READ_WINDOW_BYTES`] is meant to be READ, and turning it into a hash the model cannot
/// dereference was the whole defect. This still governs `bash` output and `find` results, where a
/// reference is the honest answer to "more than you asked for".
fn body_for(text: String) -> (ToolBody, u64, Option<String>) {
    let bytes = text.len() as u64;
    if text.len() <= MAX_INLINE_BYTES {
        (ToolBody::Inline(text), bytes, None)
    } else {
        // Content-addressed by the store at M2 D; until then the hash names the bytes so the
        // summary is honest about what it is standing in for.
        let hash = format!("{:016x}", fnv1a(text.as_bytes()));
        let preview = Some(head_and_tail(&text));
        (ToolBody::Reference { hash, bytes }, bytes, preview)
    }
}

/// A window that has already been bounded reaches the model as TEXT.
///
/// `body_for` would hand back a `ContentRef` for anything over 8 KB, and a file reference cannot
/// be dereferenced — `read`'s `ref` takes ids `web` issued. That is what made every file above
/// 8 KB unreadable past its first and last 4 KB. The window is bounded by
/// [`READ_WINDOW_BYTES`] before it gets here, so there is nothing left to protect against.
fn body_for_window(text: String) -> (ToolBody, u64, Option<String>) {
    let bytes = text.len() as u64;
    (ToolBody::Inline(text), bytes, None)
}

/// How much of an over-large body still reaches the model.
///
/// A hash it cannot dereference is not a result — measured live, `read` on a 69 KB file returned
/// only `ref 225bfe8df7bbc044` and the model called `read` five times chasing the same hash. Head
/// and tail with the omission **stated in words** is something it can act on.
const PREVIEW_BYTES: usize = 4_000;

fn head_and_tail(text: &str) -> String {
    if text.len() <= PREVIEW_BYTES {
        return text.to_string();
    }
    let head_len = floor_boundary(text, PREVIEW_BYTES / 2);
    let tail_len = floor_boundary(text, PREVIEW_BYTES / 4);
    let tail_start = ceil_boundary(text, text.len() - tail_len);
    let omitted = tail_start - head_len;
    format!(
        "{}
…[{omitted} characters omitted from the middle; the tool read the whole file]…
{}",
        &text[..head_len],
        &text[tail_start..]
    )
}

fn floor_boundary(s: &str, mut i: usize) -> usize {
    i = i.min(s.len());
    while i > 0 && !s.is_char_boundary(i) {
        // LOOP-EXEMPT: walking back at most three bytes to a UTF-8 boundary.
        i -= 1;
    }
    i
}

fn ceil_boundary(s: &str, mut i: usize) -> usize {
    i = i.min(s.len());
    while i < s.len() && !s.is_char_boundary(i) {
        // LOOP-EXEMPT: walking forward at most three bytes to a UTF-8 boundary.
        i += 1;
    }
    i
}

fn fnv1a(bytes: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in bytes {
        h ^= *b as u64;
        h = h.wrapping_mul(0x1000_0000_01b3);
    }
    h
}

fn text_arg<'a>(args: &'a Args, name: &str) -> Option<&'a str> {
    args.get(name).and_then(ArgValue::as_text)
}

fn handle_for<'a>(a: &'a Adjudication, param: &str) -> Option<&'a ScopedPath> {
    a.handles.get(param)
}

impl<S: PathScope> FileSystemTools<S> {
    fn read(&self, args: &Args, a: &Adjudication) -> ToolOutcome {
        // **The dereference path.** `engine.rs` has anticipated this since M2: *"The content store
        // lands at M2 D and the `read`-a-reference path with it."* Until it existed, a reference
        // was a hash the model could not turn back into anything, so `web` had to ship the page.
        if let Some(id) = text_arg(args, "ref") {
            return self.read_ref(id, args);
        }
        let Some(scoped) = handle_for(a, "path") else {
            // **Two different failures, two different messages.** A `path` that was supplied and
            // refused has no handle; so does a call that named no subject at all. Collapsing them
            // told a model whose traversal had just been blocked that it had "given neither",
            // which is false and points it at the wrong correction.
            return if args.get("path").is_some() {
                failed("read", "no adjudicated handle for `path`")
            } else {
                failed(
                    "read",
                    "supply either `path` (a workspace-relative file) or `ref` (the id a `web` result reported). Neither was given.",
                )
            };
        };
        let mut text = String::new();
        let capped = match clone_and_read(scoped, &mut text) {
            Ok(c) => c,
            Err(e) => return failed("read", e.to_string()),
        };
        let capped = match capped {
            ReadOutcome::Whole => false,
            ReadOutcome::Capped => true,
            // A binary is REPORTED, not decoded. `read_to_string` used to fail outright, so `read`
            // could say nothing at all about a non-UTF-8 file; decoding it lossily would be worse,
            // filling the window with replacement characters that look like content.
            ReadOutcome::NotText { bytes } => {
                return ToolOutcome {
                    summary: ResultSummary::with_detail(
                        vec![Metric::State("binary"), Metric::Bytes { n: bytes }],
                        "this file is not UTF-8 text, so its bytes were not returned",
                    ),
                    body: ToolBody::Inline(String::new()),
                    trust: TrustClass::AgentObserved,
                    failed: false,
                    wall_ms: 0,
                    preview: None,
                };
            }
        };
        if capped {
            text.push_str(&format!(
                "\n[the harness stopped reading at {MAX_READ_BYTES} bytes. The file is longer than \
                 this and the text above is a prefix.]"
            ));
        }
        // `range` is a Payload: untrusted prose may shape it freely, because it selects nothing
        // outside a file the target check already approved.
        if let Some(range) = text_arg(args, "range") {
            // **Both failure modes here were SILENT and both produced a result that means
            // something else.** See `slice_lines`.
            let of = text.lines().count();
            match slice_lines(&text, range) {
                Ok(sliced) if sliced.is_empty() && of > 0 => {
                    // `0 lines · 0 B` is the signature `read`'s own description reserves for "the
                    // file is there and is empty". A range that selected nothing rendered
                    // IDENTICALLY, so a model asking for lines 500-600 of a ten-line file was
                    // handed the exact string it had been told to read as "this file is empty".
                    return failed(
                        "read",
                        format!(
                            "`range` \"{range}\" selected no lines: the file has {of}. Ask for a \
                             range inside 1-{of}, or omit `range` for the whole file."
                        ),
                    );
                }
                Ok(sliced) => text = sliced,
                // `slice_lines` used to swallow this and return the WHOLE FILE. A model that
                // mistyped a range on a large file got everything back, with nothing to say the
                // range had been ignored rather than honoured.
                Err(why) => return failed("read", why),
            }
        }
        // ── THE WINDOW, AND WHAT IT COSTS ──────────────────────────────────────────────
        //
        // Applied AFTER `range`, so an explicit range is bounded by the same ceiling rather than
        // being a way around it, and BEFORE the metrics, so the numbers describe what was
        // actually returned.
        //
        // **Two notices, and the size decides which.** A 2,400-line file is ordinary and needs one
        // line: what you got, what to ask for next. A 208 KB file is a different decision, and the
        // unit that decision is made in is TOKENS -- bytes do not tell a model what it is
        // committing to. Watched live 2026-08-27: a run read five design documents totalling
        // ~400 KB, spent its whole 200k budget and answered from none of them.
        //
        // The long form is held back for genuinely large files ([`LARGE_FILE_TOKENS`]) so that
        // routine reads are not dressed as warnings. A model told everything is expensive learns
        // nothing about what actually is.
        let total_lines = text.lines().count();
        // The same pessimistic three-characters-per-token the assembler budgets with, so the two
        // numbers a run is judged by are computed the same way.
        let est_tokens = marlowe_loop::estimate_tokens(&text);
        // **Large COMPARED TO THIS MODEL'S WINDOW**, not against a constant. The same file is
        // most of a 32k context and a rounding error in a 200k one.
        let expensive = est_tokens > self.context_tokens / LARGE_FILE_SHARE_OF_CONTEXT;
        let mut clipped: Option<String> = None;

        let mut note = |kept: usize| {
            let next_end = (kept + READ_WINDOW_LINES).min(total_lines);
            let cost = if expensive {
                format!(
                    " The whole file is about {est_tokens} tokens; to find something specific, \
                     `find` searches inside files and returns `path:line: text`."
                )
            } else {
                String::new()
            };
            clipped = Some(format!(
                "\n\n[showing lines 1-{kept} of {total_lines}. Continue with range \
                 \"{}-{}\".{cost}]",
                kept + 1,
                next_end,
            ));
        };

        if total_lines > READ_WINDOW_LINES {
            let first: String =
                text.lines().take(READ_WINDOW_LINES).collect::<Vec<_>>().join("\n");
            note(READ_WINDOW_LINES);
            text = first;
        }
        if text.len() > READ_WINDOW_BYTES {
            let cut = floor_boundary(&text, READ_WINDOW_BYTES);
            let kept = text[..cut].lines().count();
            text.truncate(cut);
            note(kept);
        }
        // Appended after truncation so the notice is never itself cut off, and inside the body so
        // it survives whatever the body becomes.
        if let Some(n) = &clipped {
            text.push_str(n);
        }

        let lines = text.lines().count() as u64;
        let (body, bytes, preview) = body_for_window(text);
        let mut metrics =
            vec![Metric::Count { n: lines, unit: "lines" }, Metric::Bytes { n: bytes }];
        if capped {
            metrics.insert(0, Metric::State("truncated"));
        }
        ToolOutcome {
            summary: ResultSummary::new(metrics),
            body,
            // Workspace content is what the harness read from disk, not what a model asserted.
            // A file whose *origin* is untrusted (a fetched page written to disk) is a §2.8
            // problem the content store solves at M2 D; a workspace read is agent-observed.
            trust: TrustClass::AgentObserved,
            failed: false,
            wall_ms: 0,
            preview,
        }
    }

    /// **`write` exists because a tool's NAME is the first thing a model matches on.**
    ///
    /// Told to write a file, the model looked for a write verb, found none, and reached for the
    /// shell: `cat > session-handoff.md << 'EOF'` — journal seq 4806, 2026-08-26, which failed
    /// under `cmd /C` with a bare exit code. `edit` did not occur to it until the shell had
    /// failed, and then it picked `edit`'s wrong mode.
    ///
    /// That second part was the deeper fault. `edit` used to be **two tools wearing one name**,
    /// told apart by an OPTIONAL parameter: supply `replacing` and it patches, omit it and it
    /// overwrites. A model holding a request and a schema had to infer a mode, and the mode it
    /// inferred was wrong. No description fixes that — the ambiguity is in the shape.
    ///
    /// So the two modes are two tools and every parameter of each is required. `write` creates or
    /// overwrites; `edit` replaces a snippet and fails if it is absent. Neither has a mode.
    fn write(&self, args: &Args, a: &Adjudication) -> ToolOutcome {
        let Some(scoped) = handle_for(a, "path") else {
            return failed("write", "no adjudicated handle for `path`");
        };
        let Some(content) = text_arg(args, "content") else {
            return failed("write", "`content` is required");
        };
        let mut file = match scoped.handle().try_clone() {
            Ok(f) => f,
            Err(e) => return failed("write", e.to_string()),
        };
        let mut existing = String::new();
        let _ = file.read_to_string(&mut existing);
        // Truncate through the handle, not by reopening with `create(true)` — the handle is the
        // one the permission layer checked, and reopening by path is the TOCTOU this avoids.
        if let Err(e) = file
            .set_len(0)
            .and_then(|()| file.seek(SeekFrom::Start(0)).map(|_| ()))
            .and_then(|()| file.write_all(content.as_bytes()))
            .and_then(|()| file.flush())
        {
            return failed("write", e.to_string());
        }
        ToolOutcome {
            summary: ResultSummary::new(vec![Metric::Diff {
                added: count_lines(content),
                removed: count_lines(&existing),
            }]),
            body: ToolBody::Inline(scoped.relative().to_string()),
            trust: TrustClass::AgentObserved,
            failed: false,
            wall_ms: 0,
            preview: None,
        }
    }

    /// Replace one snippet. **`replacing` is required** — see [`FileSystemTools::write`] for why
    /// the two modes are two tools.
    fn edit(&self, args: &Args, a: &Adjudication) -> ToolOutcome {
        let Some(scoped) = handle_for(a, "path") else {
            return failed("edit", "no adjudicated handle for `path`");
        };
        let Some(content) = text_arg(args, "content") else {
            return failed("edit", "`content` is required");
        };
        // **AN EMPTY `replacing` IS A SILENT, UNREQUESTED WRITE, and this is the one place it
        // could be caught.** `str::find("")` returns `Some(0)` for ANY string, so an empty
        // `replacing` matches trivially at offset 0 and the splice PREPENDS `content` to the file
        // — reported back as an ordinary successful `edit`, with a `+n −0` line that looks right.
        //
        // A model reaches an empty `replacing` by accident, not on purpose: a snippet extracted
        // from a `read` that returned nothing, a template that filled in blank, a variable that
        // was stripped. Every other failure in this executor at least SAYS something; this one
        // mutated a file and said "done".
        //
        // It is the write-then-refuse bug one step worse — that one failed loudly and wasted a
        // call; this one succeeds wrongly and damages a file.
        if text_arg(args, "replacing").is_some_and(|r| r.is_empty()) {
            return failed(
                "edit",
                "`replacing` is empty, which would match at the very start of the file and insert \
                 `content` there rather than replace anything. Give the exact snippet to replace, \
                 or use `write` to replace the whole file.",
            );
        }
        let Some(replacing) = text_arg(args, "replacing") else {
            return failed(
                "edit",
                "`replacing` is required: `edit` replaces one exact snippet. To create a file or \
                 replace all of it, use `write` instead.",
            );
        };

        let mut file = match scoped.handle().try_clone() {
            Ok(f) => f,
            Err(e) => return failed("edit", e.to_string()),
        };
        let mut existing = String::new();
        if let Err(e) = file.read_to_string(&mut existing) {
            return failed("edit", e.to_string());
        }
        // **An empty file has nothing to patch, and `edit` no longer creates one to find out.**
        // `path` is a `WritePath`, so scoping has already opened it `CreateOrOpen` — the zero-byte
        // file exists by the time this runs and cannot be un-created here. What CAN be done is
        // refuse in a sentence that names the tool that would have worked.
        if existing.is_empty() {
            return failed(
                "edit",
                "the file is empty, so there is no snippet to replace. Use `write` with `path` \
                 and `content` to create it. (Naming a path here creates it at zero bytes before \
                 this tool runs, so it now exists and is empty.)",
            );
        }
        let Some(at) = existing.find(replacing) else {
            return failed("edit", replacing_miss(&existing, replacing));
        };
        let mut next = String::with_capacity(existing.len());
        next.push_str(&existing[..at]);
        next.push_str(content);
        next.push_str(&existing[at + replacing.len()..]);

        if let Err(e) = file
            .set_len(0)
            .and_then(|()| file.seek(SeekFrom::Start(0)).map(|_| ()))
            .and_then(|()| file.write_all(next.as_bytes()))
            .and_then(|()| file.flush())
        {
            return failed("edit", e.to_string());
        }
        ToolOutcome {
            summary: ResultSummary::new(vec![Metric::Diff {
                added: count_lines(content),
                removed: count_lines(replacing),
            }]),
            body: ToolBody::Inline(scoped.relative().to_string()),
            trust: TrustClass::AgentObserved,
            failed: false,
            wall_ms: 0,
            preview: None,
        }
    }

    /// **List what is in a directory. There was no way to do this at all.**
    ///
    /// `find` searches file CONTENTS and needs a pattern. `read` needs a path you already know.
    /// `bash` is `Irreversible`, so every attempt stops and asks the user. Asked what was inside
    /// `docs/requirements`, the model had exactly one option and it cost a prompt each time:
    /// journal seq 4884-4908 shows four `bash` calls — `dir "docs/requirements" /s`,
    /// `dir "docs\*" /b`, `list "docs"`, a GNU-`find` invocation — and 2026-08-27 shows three more
    /// (`ls -la docs/requirements/`, `ls docs/requirements`, `find ... | head -20`) declined for
    /// want of an approval surface. It then reported the directory **"appears empty"**. It has four
    /// files in it.
    ///
    /// That last part is the cost of the gap: with no way to look and no way to say "I could not
    /// look", a model fills the silence. The answer is not a better refusal, it is a tool.
    ///
    /// # Names only, and that is what makes it `Inert`
    ///
    /// This returns paths. It opens nothing and reads no bytes, so no file content — trusted or
    /// otherwise — passes through it, which is why it can be `Inert` and run without asking while
    /// `bash` cannot. Enumeration is bounded by [`FIND_FILE_CAP`] exactly as `find`'s is, and the
    /// cap being hit is **stated**, because a listing that silently stops makes absence
    /// indistinguishable from truncation.
    fn glob(&self, args: &Args, a: &Adjudication) -> ToolOutcome {
        let Some(root) = handle_for(a, "path") else {
            return failed("glob", "no adjudicated handle for `path`");
        };
        // Absent means "everything here", which is the common case: `glob` with a path and no
        // pattern is "list this directory".
        let pattern = text_arg(args, "pattern").unwrap_or("*");

        let base = root.resolved().to_path_buf();
        // Same as `find`: a file here is the mistake the description names, and it must not
        // look like an empty directory.
        if base.is_file() {
            return failed(
                "glob",
                "`path` is a file, and `glob` lists a DIRECTORY. Pass the directory that contains \
                 it — the file you named is already the answer.",
            );
        }
        let mut candidates = Vec::new();
        collect(&base, &mut candidates, FIND_FILE_CAP);
        let truncated = candidates.len() >= FIND_FILE_CAP;

        let mut hits: Vec<String> = Vec::new();
        for candidate in &candidates {
            let Ok(relative) = candidate.strip_prefix(&self.workspace) else { continue };
            let relative = relative.to_string_lossy().replace('\\', "/");
            let name = candidate
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_default();
            // The pattern matches the NAME when it has no slash, and the workspace-relative PATH
            // when it does — so `*.rs` means "any .rs anywhere under here" and `src/*.rs` means
            // what it looks like. Stated in the tool's description rather than left to be guessed.
            let subject = if pattern.contains('/') { relative.as_str() } else { name.as_str() };
            if glob_match(pattern, subject) {
                hits.push(relative);
            }
        }
        hits.sort();

        let found = hits.len() as u64;
        let mut listing = hits.join("\n");
        if truncated {
            listing.push_str(&format!(
                "\n[enumeration stopped at {FIND_FILE_CAP} files; there may be more under this \
                 path than are listed]"
            ));
        }
        if found == 0 {
            // **An empty result says which of the two things happened.** "No matches" and "that
            // directory has nothing in it" are different facts, and a model that cannot tell them
            // apart invents one — which is exactly what happened live.
            listing = if candidates.is_empty() {
                format!("no files under this path at all (`{pattern}` was not the reason)")
            } else {
                format!(
                    "{} file(s) are under this path and none matched `{pattern}`",
                    candidates.len()
                )
            };
        }
        let (body, _, preview) = body_for(listing);
        ToolOutcome {
            summary: ResultSummary::new(vec![Metric::Count { n: found, unit: "paths" }]),
            body,
            trust: TrustClass::AgentObserved,
            failed: false,
            wall_ms: 0,
            preview,
        }
    }

    fn find(&self, args: &Args, a: &Adjudication, declared: &[PathGlob]) -> ToolOutcome {
        let Some(pattern) = text_arg(args, "pattern") else {
            return failed("find", "`pattern` is required");
        };
        // **`str::contains("")` is always true**, so an empty pattern reported every line of every
        // file under `path` as a match — a context-flood standing in for what should have been an
        // error. A model arrives at an empty pattern the same way it arrives at an empty
        // `replacing`: a stripped variable, a bad split, never on purpose.
        if pattern.is_empty() {
            return failed(
                "find",
                "`pattern` is empty, which matches every line of every file. Give the text to \
                 search for, or use `glob` to list files without searching inside them.",
            );
        }
        let Some(root) = handle_for(a, "path") else {
            return failed("find", "no adjudicated handle for `path`");
        };

        // Enumeration produces candidate NAMES. Every one is then opened through the scope, so
        // nothing this loop reads bypassed the wall.
        let base = root.resolved().to_path_buf();
        // **A file where a directory was asked for produced `0 results · 0 files` — the same
        // answer an empty directory gives.** `collect` swallows `read_dir`'s error on a file
        // (`let Ok(entries) = read_dir(..) else { continue }`), so the walk simply found nothing.
        // The manifest says "the DIRECTORY to search -- not a file"; nothing enforced it, and the
        // model that made exactly the mistake the manifest names got no signal at all.
        if base.is_file() {
            return failed(
                "find",
                "`path` is a file, and `find` searches a DIRECTORY. Pass the directory that \
                 contains it, or use `read` to look at this one file.",
            );
        }
        let mut candidates = Vec::new();
        collect(&base, &mut candidates, FIND_FILE_CAP);

        let mut hits = Vec::new();
        let mut scanned = 0u64;
        for candidate in &candidates {
            let Ok(relative) = candidate.strip_prefix(&self.workspace) else { continue };
            let relative = relative.to_string_lossy().replace('\\', "/");
            let Ok(scoped) = self.scope.open(declared, &self.workspace, &relative, Access::Read)
            else {
                // Refused by the wall — a link, an undeclared subtree, an unreadable name. It is
                // skipped rather than reported as a match, and the count says how many were read.
                continue;
            };
            let mut text = String::new();
            if clone_and_read(&scoped, &mut text).is_err() {
                continue;
            }
            scanned += 1;
            for (n, line) in text.lines().enumerate() {
                if line.contains(pattern) {
                    hits.push(format!("{relative}:{}: {}", n + 1, line.trim()));
                }
            }
        }

        let found = hits.len() as u64;
        let (body, _, preview) = body_for(hits.join("\n"));
        ToolOutcome {
            summary: ResultSummary::new(vec![
                Metric::Count { n: found, unit: "results" },
                Metric::Count { n: scanned, unit: "files" },
            ]),
            body,
            trust: TrustClass::AgentObserved,
            failed: false,
            wall_ms: 0,
            preview,
        }
    }

    fn bash(&self, args: &Args, a: &Adjudication) -> ToolOutcome {
        let Some(command) = text_arg(args, "command") else {
            return failed("bash", "`command` is required");
        };
        // `cwd` is a declared Path parameter, so a handle exists whenever it was supplied. It is
        // held open for the whole spawn — see the crate header for why that is the mechanism on
        // Windows rather than a convenience.
        let cwd = handle_for(a, "cwd");
        let dir = cwd.map(|c| c.resolved().to_path_buf()).unwrap_or_else(|| self.workspace.clone());

        // No clock is read here, and that is not an oversight. Section 4.5 is binding on every
        // path reachable from the section 4 interfaces, and `marlowe/tests/determinism_guard.rs`
        // enforces it across the workspace — it caught an `Instant::now()` in this very function.
        // The LOOP measures the call with its injected `ClockSource`, which is the clock a test
        // can hold still; an executor reading the wall clock would make a decay-dependent result
        // irreproducible and would do it from a component nobody would think to look in.
        let out = spawn_shell(command, &dir, cwd);

        // The handle is dropped only now, after the child has been spawned and waited on.
        drop(cwd);

        match out {
            Err(e) => failed("bash", e.to_string()),
            Ok(ShellRun { code, text, stopped, flooded }) => {
                // **Told in the body, not only in a metric.** A metric is a summary line; the model
                // reads the body. A killed command whose output merely ends is indistinguishable
                // from one that finished, and acting on a truncated prefix as though it were the
                // whole answer is the failure worth preventing here.
                let text = match (stopped, flooded) {
                    (true, _) => format!(
                        "{text}\n[the harness stopped this command after {BASH_TIMEOUT_MS} ms. \
                         The output above is what it had produced by then, and the command did \
                         not finish.]"
                    ),
                    (_, true) => format!(
                        "{text}\n[the harness stopped this command after it produced more than \
                         {MAX_SHELL_OUTPUT_BYTES} bytes on one stream. The output above is a \
                         prefix, and the command did not finish.]"
                    ),
                    _ => text,
                };
                let (body, _, preview) = body_for(text);
                let lines = text_lines(&body);
                let mut metrics = vec![Metric::Count { n: lines, unit: "lines" }];
                if stopped {
                    metrics.insert(0, Metric::State("timed-out"));
                }
                if flooded {
                    metrics.insert(0, Metric::State("truncated"));
                }
                if code != 0 {
                    metrics.insert(0, Metric::Exit { code });
                }
                ToolOutcome {
                    summary: ResultSummary::new(metrics),
                    body,
                    // A shell's stdout is bytes from whatever it ran. The harness observed the
                    // exit code; it did not author the output.
                    trust: TrustClass::AgentObserved,
                    failed: code != 0,
                    // Filled in by the loop from its `ClockSource`. See above.
                    wall_ms: 0,
                    preview,
                }
            }
        }
    }
}

impl<S: PathScope> FileSystemTools<S> {
    /// Read a fetched document back out of the store. **This is where untrusted text re-enters.**
    ///
    /// `web` no longer returns page content, so this is the ONLY way a fetched document reaches a
    /// run — which is what makes the boundary auditable: one function, one trust class, one place
    /// layer 1 has to fire. The result is `UntrustedContent`, so the loop condenses it through a
    /// quarantined reader exactly as before.
    ///
    /// The consequence worth stating: a research pass that fetches thirty pages and reads three of
    /// them pays for **three**, not thirty.
    fn read_ref(&self, id: &str, args: &Args) -> ToolOutcome {
        let Some(document) = self.store.get(id) else {
            return failed(
                "read",
                format!(
                    "no fetched document has ref {id:?}. Refs are reported by `web` and last for this session; fetch the URL again if you need it."
                ),
            );
        };
        let mut text = crate::corpus::render(&document);
        // The `ref` path takes the same treatment as the `path` path: a malformed range is an
        // error rather than a silent whole-document read, and a range that selects nothing is
        // reported instead of rendering as an empty document.
        if let Some(range) = text_arg(args, "range") {
            let of = text.lines().count();
            match slice_lines(&text, range) {
                Ok(sliced) if sliced.is_empty() && of > 0 => {
                    return failed(
                        "read",
                        format!(
                            "`range` \"{range}\" selected no lines: the document has {of}. Ask                              for a range inside 1-{of}, or omit `range` for all of it."
                        ),
                    );
                }
                Ok(sliced) => text = sliced,
                Err(why) => return failed("read", why),
            }
        }
        let chars = text.len() as u64;
        let (body, _, preview) = body_for(text);
        ToolOutcome {
            summary: ResultSummary::with_detail(
                vec![
                    Metric::State("doc"),
                    Metric::Count { n: chars, unit: "chars" },
                ],
                format!("{} · {}", document.format.as_str(), id),
            ),
            body,
            // **Unchanged by the round trip through the store.** A document does not become
            // trustworthy by being written down and read back; storing it is not laundering.
            trust: TrustClass::UntrustedContent,
            failed: false,
            wall_ms: 0,
            preview,
        }
    }

    /// `web` — fetch. ADR-031.
    ///
    /// **Egress was already decided before this runs.** The adjudicator checked the URL's host
    /// against the run's `EgressPolicy` intersected with the manifest's declared hosts, and a
    /// refusal never reaches an executor. This function does not re-check and must not: a second
    /// egress implementation inside a networking call site is how the two sides come to disagree.
    ///
    /// **Redirects are NOT followed here, and that is the security design rather than a
    /// shortcut.** A redirect is a second egress destination chosen by the host being fetched —
    /// untrusted content selecting a target. Following it inside this function would mean
    /// re-implementing the allowlist check where the taint layer cannot see it. Instead the
    /// `Location` is returned as a *result*, and following it requires a fresh `web` call that
    /// goes through the real adjudicator, with the real taint, like any other target.
    ///
    /// The consequence is deliberate and worth naming: once this run has read a page, ADR-023's
    /// latch blocks model-composed targets, so **the model generally cannot follow the redirect**.
    /// That is the trifecta break working, not a defect. The path is a quarantined reader.
    ///
    /// **Nothing here parses the body.** Bytes and a content type go back; extraction is a
    /// separate module and a separate session.
    fn web(&self, a: &Args) -> ToolOutcome {
        let Some(url) = a.get("url").and_then(ArgValue::as_text) else {
            // `query` exists in the manifest for a search this build does not have. Saying so
            // plainly beats a refusal the model reads as "the URL was malformed".
            return failed(
                "web",
                "`url` is required. This build fetches a single URL and does not search, so \
                 `query` alone cannot be answered — supply a full https:// URL.",
            );
        };

        let target = match marlowe_net::Target::parse(url) {
            Ok(t) => t,
            Err(e) => return failed("web", e.to_string()),
        };

        let fetched = match marlowe_net::fetch(&target) {
            Ok(res) => res,
            Err(e) => return failed("web", e.to_string()),
        };
        let status = fetched.status;
        let content_type = fetched.content_type.clone();
        let wire = fetched.wire_bytes;
        let raw_bytes = fetched.bytes.len();
        let outcome = crate::corpus::read(url, fetched);
        self.web_outcome(url, status, content_type.as_deref(), raw_bytes, wire, outcome)
    }

    /// Turn one [`corpus::Outcome`](crate::corpus::Outcome) into the result the model sees.
    ///
    /// **Split out of `web` so it has a test.** Audit finding A3 asked for a hostile `Location`
    /// case *"asserting on the `ToolOutcome`, not on `DocumentRef`"* — and there was no way to
    /// reach a `ToolOutcome` without a live fetch, so every existing boundary test asserted one
    /// level below the thing that shipped. That is the shape this project keeps logging: the weaker
    /// claim is true, cheap and adjacent. `web` now does the network and this does the rest, so the
    /// bytes the model receives are directly assertable.
    pub fn web_outcome(
        &self,
        url: &str,
        status: u16,
        content_type: Option<&str>,
        raw_bytes: usize,
        wire: usize,
        outcome: crate::corpus::Outcome,
    ) -> ToolOutcome {
        match outcome {
            // **The `Location` header does not reach here verbatim.** Audit finding A3: this arm
            // used to interpolate the raw header at `AgentObserved`, straight into the parent's
            // window, with the trust floor unmoved — the one genuine layer-1 bypass in the round.
            // `RedirectTo` is the validated form and `render()` is the only way it becomes text.
            crate::corpus::Outcome::Redirect { status, location, .. } => ToolOutcome {
                summary: ResultSummary::with_detail(
                    vec![Metric::State("redirect")],
                    // The host only. A summary line is the most quotable thing a tool produces.
                    format!("{status} -> {}", location.host().unwrap_or("an unusable location")),
                ),
                body: ToolBody::Inline(format!(
                    "{url} redirected {}. It was NOT followed: a redirect target \
                     is chosen by the site, so it is checked like any other target. Call \
                     `web` again with that URL if it is what you want.",
                    location.render()
                )),
                // The harness observed the status and authored every character of this body
                // except a validated host and a path that cannot carry prose.
                trust: TrustClass::AgentObserved,
                failed: false,
                wall_ms: 0,
                preview: None,
            },

            // **Extraction failed, so nothing readable exists — and the raw bytes are NOT a
            // fallback.** Handing over undecodable input would put the exact material this
            // change exists to remove back into the window, on the one path nobody tests.
            //
            // **Nor is the parser's error message a fallback.** Audit finding A4: `detail` is built
            // from `pdf_extract`'s `Display` and from downcast panic payloads, both of which carry
            // document-derived text. `kind` is a harness constant; `detail` stays in the summary,
            // which is journalled.
            crate::corpus::Outcome::Unreadable { kind, .. } => ToolOutcome {
                summary: ResultSummary::with_detail(
                    vec![Metric::State("unreadable"), Metric::Bytes { n: raw_bytes as u64 }],
                    format!("{status} {}", normalize_content_type(content_type)),
                ),
                body: ToolBody::Inline(format!(
                    "{url} returned {raw_bytes} bytes that could not be turned into text \
                     ({kind}). Nothing was read."
                )),
                trust: TrustClass::AgentObserved,
                failed: true,
                wall_ms: 0,
                preview: None,
            },

            crate::corpus::Outcome::Unreachable { detail, .. } => failed("web", detail),

            crate::corpus::Outcome::Read { document, wire_bytes, .. } => {
                // **Stored whole, before anything is summarised.** The reference this produces
                // carries a hash and counts and no bytes of the page — see
                // `marlowe_extract::store`, where that property is asserted directly.
                let reference = self.store.put(url, wire_bytes, document);
                // ── ADR-042. THE PAGE DOES NOT COME BACK. ────────────────────────────────────
                //
                // What crosses is a `DocumentRef`: a hash and a set of counts, every one of them
                // measured by the harness. There is no substring of the page anywhere in it — no
                // title, no headings, no description, no snippet — which is why this result is
                // `AgentObserved` rather than `UntrustedContent`.
                //
                // **That reclassification is the whole win, and it is not a relaxation.** Layer 1
                // condenses untrusted results because attacker *prose* is crossing; a page can
                // influence these numbers but cannot author them, and a number cannot carry an
                // instruction. So a fetch now costs **no model call at all**, and the agent can
                // decide what to read while having read nothing.
                //
                // The content is still reachable, through exactly one door: `read(ref=…)`, which
                // returns it at `UntrustedContent` and goes through the quarantined reader.
                // ── THE STATUS HAS TO REACH THE MODEL, AND IT DID NOT ────────────────────
                //
                // ADR-049 §5. The exact code was formatted into `ResultSummary::detail` by every
                // arm of this function -- and **`detail` has no reader in the shipped product**.
                // It is §8's expansion payload, nothing expands it, and `render()` walks the
                // metrics only. So `web` computed the status, journalled it, and showed the model
                // the bare word `http`: 400, 403, 404 and 503 were one indistinguishable state,
                // and a malformed query looked like an outage.
                //
                // Same family as `inline_threshold_bytes: 0` -- a control that is declared, is
                // correct, and that no line of code reads. It was found by an assertion on what
                // the model receives failing, which is the only place it could have been found.
                //
                // Fixed in the two places the model actually looks: a harness-authored sentence
                // at the head of the body, and a class in the state metric. **Both are harness
                // constants and a number the harness measured** -- ADR-042's rule is unchanged,
                // and this stays `AgentObserved` because a status line is not the page.
                let text = reference.render();
                let text = match status {
                    s if s >= 500 => format!(
                        "The server returned HTTP {s}. What follows is what came back with that \
                         error, not the document you asked for.\n{text}"
                    ),
                    s if s >= 400 => format!(
                        "The server returned HTTP {s}: it refused this request. What follows is \
                         the error page, not the document you asked for.\n{text}"
                    ),
                    _ => text,
                };
                let chars = reference.chars as u64;
                let (body, _, preview) = body_for(text);
                ToolOutcome {
                    summary: ResultSummary::with_detail(
                        vec![
                            // `State` is `&'static str`, so the CLASS is what a metric can carry
                            // and the exact code goes in the body above. Three constants beat one
                            // formatted string here: no new `Metric` variant, and CONTRACTS.md
                            // §8's pinned enum is untouched.
                            Metric::State(match status {
                                s if s >= 500 => "http 5xx",
                                s if s >= 400 => "http 4xx",
                                _ => "ok",
                            }),
                            Metric::Count { n: chars, unit: "chars" },
                        ],
                        format!(
                            "{status} {} · {} · {} B wire · read it with ref {}",
                            reference.format.as_str(),
                            content_type.as_deref().unwrap_or("no content-type"),
                            wire,
                            reference.hash
                        ),
                    ),
                    body,
                    // **`AgentObserved`, and the justification is the absence of content, not a
                    // judgement about the site.** The harness fetched some bytes and measured
                    // them; what it is reporting is its own measurements. The moment any
                    // attacker-authored substring is added to this result, this must go back to
                    // `UntrustedContent` — `marlowe-extract`'s `store` tests assert the absence
                    // that licenses it, and `web_returns_no_page_content` asserts it here.
                    trust: TrustClass::AgentObserved,
                    failed: status >= 400,
                    wall_ms: 0,
                    preview,
                }
            }
        }
    }
}

impl<S: PathScope> ToolHost for FileSystemTools<S> {
    /// **The five this host actually has arms for.** Kept beside the match below so the two
    /// cannot drift; `every_declared_tool_has_a_match_arm` asserts they agree.
    fn executes(&self) -> Vec<marlowe_tools::ToolId> {
        ["read", "write", "edit", "glob", "find", "bash", "web"]
            .iter()
            .map(|t| marlowe_tools::ToolId::new(*t))
            .collect()
    }

    fn execute(&mut self, tool: &ToolId, args: &Args, adjudication: &Adjudication) -> ToolOutcome {
        self.dispatch(tool, args, adjudication)
    }

    /// **Run the batch concurrently.** This is what makes *"fetch these 30 sites"* one round of
    /// work instead of thirty.
    ///
    /// # What licenses the concurrency, stated precisely
    ///
    /// Not the fact that the model emitted the calls together — that argument is about data flow
    /// and says nothing about side effects. The loop only ever hands this method a group of calls
    /// whose manifests declare `ConsequenceLevel::Inert` — *"pure reads, no side effects"* — so
    /// `edit` and `bash` are never in a group of more than one and never overlap with anything.
    /// See `Engine::run_group`.
    ///
    /// Every item was adjudicated individually before arriving here, including the per-host egress
    /// check: thirty URLs is thirty separate allowlist decisions, and a refused one never reaches
    /// this method. **Nothing about permission is batched.**
    ///
    /// # Threads, not an executor
    ///
    /// These calls are network-bound, so the useful width is well above the core count and the
    /// threads spend their lives parked on sockets. `marlowe-net`'s `Client` is `Send + Sync` and
    /// holds the shared connection pool, DNS cache and TLS session cache, so concurrent fetches to
    /// one host reuse connections rather than racing to open thirty.
    fn execute_batch(&mut self, items: &[marlowe_loop::BatchItem<'_>]) -> Vec<ToolOutcome> {
        if items.is_empty() {
            return Vec::new();
        }

        // **STANDING RULE: extraction never runs on the caller's thread, not even for one call.**
        //
        // The obvious optimisation here is to run a single-item batch inline and skip the thread.
        // That is exactly what must not happen: a batch of one is the common case, and a single
        // `web` call on a 2 MB PDF is hundreds of milliseconds of parsing. Run inline, that lands
        // on the daemon's thread and the interface stops responding for the duration — the user
        // sees a frozen surface and no indication why.
        //
        // The caller still *blocks* here, because `ToolHost` is synchronous by design. What it no
        // longer does is *perform the parse*. On a machine with this many cores, spending one
        // thread-spawn (tens of microseconds) to keep heavy CPU work off the thread that draws the
        // screen is not a trade worth thinking about twice.
        let workers = items.len().min(batch_concurrency());
        let slots: Vec<Mutex<Option<ToolOutcome>>> =
            (0..items.len()).map(|_| Mutex::new(None)).collect();
        let next = AtomicUsize::new(0);
        // `&*self`, so every worker shares one host. `PathScope` is already `Send + Sync` and
        // every executor takes `&self`, which is what makes this a borrow rather than a redesign.
        let me: &Self = self;

        std::thread::scope(|scope| {
            for _ in 0..workers {
                scope.spawn(|| loop {
                    let i = next.fetch_add(1, Ordering::Relaxed);
                    if i >= items.len() {
                        break;
                    }
                    let item = &items[i];
                    let outcome = me.dispatch(item.tool, item.args, item.adjudication);
                    *slots[i].lock().expect("batch slot poisoned") = Some(outcome);
                });
            }
        });

        // **In input order.** The loop attributes results to calls positionally, so a reordering
        // here would hand the model one call's result under another call's id.
        slots
            .into_iter()
            .map(|s| {
                s.into_inner()
                    .expect("batch slot poisoned")
                    .expect("every slot is filled before the scope ends")
            })
            .collect()
    }
}

/// How wide to run a batch on **this** machine. **Derived, never hardcoded.**
///
/// Delegates to [`marlowe_net::io_concurrency`] rather than keeping a second constant: a batch
/// here is `Inert` calls, overwhelmingly `web` fetches, so it is the same I/O-bound question and
/// two answers to it would drift.
///
/// The CPU half needs no arithmetic at all: extraction runs on `rayon`'s global pool, already
/// sized to the core count, and each worker extracts its own document — so network waits and
/// parsing overlap without a second pool to tune.
pub fn batch_concurrency() -> usize {
    marlowe_net::io_concurrency()
}

impl<S: PathScope> FileSystemTools<S> {
    /// The one dispatch table. `execute` and `execute_batch` both route through it so the serial
    /// and concurrent paths cannot come to disagree about what a tool name means.
    fn dispatch(&self, tool: &ToolId, args: &Args, adjudication: &Adjudication) -> ToolOutcome {
        // The declared globs are the manifest's; the adjudicator already matched the model's
        // argument against them. `find` needs them again for its own opens.
        let declared = [PathGlob::new("./**")];
        match tool.as_str() {
            "read" => self.read(args, adjudication),
            "write" => self.write(args, adjudication),
            "edit" => self.edit(args, adjudication),
            "glob" => self.glob(args, adjudication),
            "find" => self.find(args, adjudication, &declared),
            "bash" => self.bash(args, adjudication),
            "web" => self.web(args),
            other => failed("tool", format!("`{other}` has no executor in this build")),
        }
    }
}

/// How much of a file `read` will hold in memory.
///
/// Audit finding A8: `read_to_string` had no cap, `find` did the same for up to
/// [`FIND_FILE_CAP`] files, and `MAX_INLINE_BYTES` gates only what reaches the model — the whole
/// file was already resident by then. Sized well above any source file and well below anything that
/// threatens the process.
pub const MAX_READ_BYTES: u64 = 4 * 1024 * 1024;

/// What a bounded read found. Not a `bool`, because "binary" is a third answer and collapsing it
/// into `Err` is what made `read` unable to say anything at all about a non-UTF-8 file.
enum ReadOutcome {
    Whole,
    Capped,
    NotText { bytes: u64 },
}

fn clone_and_read(scoped: &ScopedPath, into: &mut String) -> std::io::Result<ReadOutcome> {
    let mut f = scoped.handle().try_clone()?;
    f.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    // One byte past the cap, so "exactly at the cap" and "longer than the cap" are distinguishable
    // — otherwise a file of exactly MAX_READ_BYTES would be reported as truncated when it is not.
    let taken = (&mut f).take(MAX_READ_BYTES + 1).read_to_end(&mut bytes)?;
    let capped = taken as u64 > MAX_READ_BYTES;
    if capped {
        bytes.truncate(MAX_READ_BYTES as usize);
    }
    match String::from_utf8(bytes) {
        Ok(s) => {
            into.push_str(&s);
            Ok(if capped { ReadOutcome::Capped } else { ReadOutcome::Whole })
        }
        Err(e) => {
            // A cap can land mid-character, and that is not a binary file. Keep the valid prefix.
            let valid = e.utf8_error().valid_up_to();
            if capped && valid > 0 {
                let raw = e.into_bytes();
                into.push_str(std::str::from_utf8(&raw[..valid]).unwrap_or_default());
                Ok(ReadOutcome::Capped)
            } else {
                Ok(ReadOutcome::NotText { bytes: taken as u64 })
            }
        }
    }
}

fn count_lines(s: &str) -> u32 {
    if s.is_empty() {
        0
    } else {
        s.lines().count() as u32
    }
}

/// Select `range` (`"a-b"`, 1-based, inclusive) out of `text`.
///
/// **Audit finding A7, and the arithmetic is the whole finding.** `take(b.saturating_sub(a) + 1)`
/// had an unguarded `+ 1`: `range = "1-18446744073709551615"` makes the subtraction `usize::MAX` and
/// the addition overflows — a **panic** in debug and test, a silent wrap to `take(0)` in release,
/// where `[profile.release]` sets no `overflow-checks`.
///
/// The panic is the serious half. `dispatch` runs inside a `scope.spawn` closure and
/// `std::thread::scope` re-raises on join, so one bad `range` aborted the **entire batch** and
/// unwound out through `run_group`, with no `catch_unwind` anywhere between here and the daemon.
///
/// And it is reachable by design, not by accident: `range` is a declared **Payload**, so §9
/// explicitly permits untrusted content to choose this value with no permission check in the way.
/// Injected prose could pick the number directly.
/// `*` and `?` only, and deliberately no more.
///
/// `*` matches any run of characters including none; `?` matches exactly one. **No `**`, no `[a-z]`,
/// no `{a,b}`** — every one of those is a spelling some shells accept and others do not, and a
/// pattern language a model has to guess at is the thing this tool exists to stop. What it does is
/// stated in the tool's description in full, so there is nothing left to infer.
///
/// Case-insensitive, because this ships on Windows where the filesystem is, and a `*.MD` that
/// silently found nothing would be indistinguishable from an empty directory.
fn glob_match(pattern: &str, subject: &str) -> bool {
    fn go(p: &[char], s: &[char]) -> bool {
        match p.first() {
            None => s.is_empty(),
            Some('*') => {
                // Match zero characters, or one more and try again. Bounded by the subject's
                // length because each recursion consumes one.
                //
                // **`*` does not cross a `/`.** Without this it did, and `src/*.rs` matched
                // `src/deep/other.rs` — contradicting the tool's own description, which promises
                // that a pattern with a slash finds only what is directly in that directory. Found
                // by `glob_pattern_with_a_slash_matches_the_path`, which is why that test names
                // the directory it must NOT reach into rather than only what it must find.
                //
                // A name-only pattern is unaffected: a file name contains no separator, so the
                // guard never fires on `*.rs`, which is the spelling for "anywhere beneath".
                go(&p[1..], s) || (!s.is_empty() && s[0] != '/' && go(p, &s[1..]))
            }
            Some('?') => !s.is_empty() && go(&p[1..], &s[1..]),
            Some(c) => !s.is_empty() && s[0] == *c && go(&p[1..], &s[1..]),
        }
    }
    let p: Vec<char> = pattern.to_lowercase().chars().collect();
    let s: Vec<char> = subject.to_lowercase().chars().collect();
    go(&p, &s)
}

/// `first-last`, 1-based and inclusive — and **every way of getting it wrong is now an error**.
///
/// # It used to fall back to the whole file, silently, for anything it could not parse
///
/// `split_once('-')` failing, or either half failing `parse::<usize>()`, returned `text` unchanged.
/// So `range: "abc"` and `range: "2"` — the latter a perfectly reasonable guess at "just line 2"
/// from a parameter documented as *"line range"* — both returned the ENTIRE file with no signal
/// that `range` had been ignored. On a large file that turns a targeted read into an unexpectedly
/// huge one, or into a `ContentRef` the model then cannot dereference.
///
/// A caller that wants the whole file omits `range`. There is no reading of a malformed range
/// under which returning everything is what was asked for.
fn slice_lines(text: &str, range: &str) -> Result<String, String> {
    let malformed = |detail: &str| {
        Err(format!(
            "`range` must be `first-last`, 1-based and inclusive, e.g. \"20-60\" — {detail}. Omit \
             `range` to read the whole file."
        ))
    };
    let Some((a, b)) = range.split_once('-') else {
        return malformed(&format!("\"{range}\" has no `-`"));
    };
    let (Ok(a), Ok(b)) = (a.trim().parse::<usize>(), b.trim().parse::<usize>()) else {
        return malformed(&format!("\"{range}\" is not two whole numbers"));
    };
    if a == 0 {
        return malformed("lines are numbered from 1, not 0");
    }
    // An inverted range selects nothing. `b.saturating_sub(a)` would read 0 and `take(1)` would
    // return line `a` — an answer to a question nobody asked. It is refused rather than silently
    // emptied, because a caller that wrote `60-20` meant `20-60`.
    if b < a {
        return malformed(&format!("\"{range}\" runs backwards; did you mean \"{b}-{a}\"?"));
    }
    Ok(text
        .lines()
        .skip(a.saturating_sub(1))
        .take(b.saturating_sub(a).saturating_add(1))
        .collect::<Vec<_>>()
        .join("\n"))
}

/// Enumerate regular files under `base`, breadth-first, to a hard cap.
///
/// Symlinked directories are **not** descended — `read_dir` reports them, and following one here
/// would walk outside the workspace before the scope ever saw the path. The scope refuses them
/// anyway on the way back in; not descending is the cheaper half of the same refusal.
fn collect(base: &Path, out: &mut Vec<PathBuf>, cap: usize) {
    let mut queue = vec![base.to_path_buf()];
    while let Some(dir) = queue.pop() {
        // LOOP-EXEMPT: a breadth-first enumeration, not a driving loop. The crate has no agent
        // loop in it; HP10's check is scoped to `marlowe-loop`.
        let Ok(entries) = std::fs::read_dir(&dir) else { continue };
        for entry in entries.flatten() {
            if out.len() >= cap {
                return;
            }
            let Ok(meta) = entry.metadata() else { continue };
            let Ok(link_meta) = entry.path().symlink_metadata() else { continue };
            if link_meta.file_type().is_symlink() {
                continue;
            }
            if meta.is_dir() {
                queue.push(entry.path());
            } else if meta.is_file() {
                out.push(entry.path());
            }
        }
    }
}

/// The two bounds a shell run is held to.
///
/// **A parameter rather than two constants read inside the function, and that is the whole reason
/// this type exists.** A1's proposed test says the check must *"run a sleeping command with a
/// lowered constant and assert the call returns"* — and note the sentence that follows it:
/// *"asserting on the constant's value would be the sixteenth-instance family again."* With the
/// production numbers baked in, the only affordable test is `assert_eq!(BASH_TIMEOUT_MS, 120_000)`,
/// which is green on a build where nothing reads it — exactly the defect A1 reports. Injecting the
/// bounds is what buys a test that kills a real child in under a second.
#[derive(Debug, Clone, Copy)]
pub struct ShellLimits {
    pub timeout_ms: u64,
    pub max_output_bytes: usize,
}

impl ShellLimits {
    /// What `bash` actually runs with.
    pub fn production() -> Self {
        Self { timeout_ms: BASH_TIMEOUT_MS, max_output_bytes: MAX_SHELL_OUTPUT_BYTES }
    }
}

/// What a shell run produced, and how it ended.
///
/// `stopped` and `flooded` are carried out to the caller rather than folded into the text, because
/// the model has to be **told** it got a prefix. A silent truncation is a result that looks
/// complete and is not, which is the whole family this project keeps logging.
pub struct ShellRun {
    pub code: i32,
    pub text: String,
    /// The child hit [`BASH_TIMEOUT_MS`] and was killed.
    pub stopped: bool,
    /// The child breached [`MAX_SHELL_OUTPUT_BYTES`] on a stream and was killed.
    pub flooded: bool,
}

/// The shell every `bash` call runs, as a `Command` with its program and `-c` already set.
///
/// **Public because `shell_bounds.rs` had its own copy and the copy drifted.** That file built
/// `Command::new("cmd").arg("/C")` under a doc comment reading *"the way `spawn_shell` does on
/// this platform"* — true when it was written, false the moment the interpreter changed, and
/// nothing could have reported it. A test that constructs its own idea of the subject is testing
/// its own idea.
///
/// Fails rather than falling back: a shell that is silently a different shell is the defect being
/// removed here, not a graceful degradation.
pub fn shell_command() -> std::io::Result<std::process::Command> {
    #[cfg(windows)]
    {
        let Some(bash) = git_bash() else {
            return Err(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                "the `bash` tool needs Git Bash and it is not installed. Install Git for Windows \
                 (https://git-scm.com/download/win), or set MARLOWE_BASH to a bash.exe. The \
                 `read`, `write`, `edit`, `glob` and `find` tools do not need it.",
            ));
        };
        let mut c = std::process::Command::new(bash);
        c.arg("-c");
        Ok(c)
    }
    #[cfg(unix)]
    {
        let mut c = std::process::Command::new("bash");
        c.arg("-c");
        Ok(c)
    }
}

/// Where Git Bash is, resolved once and never taken from `PATH`.
///
/// # `PATH` holds a bash that is a different machine
///
/// `C:\Windows\System32\bash.exe` comes first on a default `PATH` and it is **WSL's launcher**,
/// not a shell — it runs inside a Linux VM with its own filesystem. Measured on this machine, the
/// same `pwd` through each:
///
/// ```text
///   Git Bash   ->  /c/Users/matth/Projects/Marlowe_Harness
///   PATH bash  ->  /mnt/c/Users/matth/Projects/Marlowe_Harness
/// ```
///
/// Both "work", which is what makes it dangerous: a path scoping decision made about a Windows
/// directory would be enforced against a handle in one filesystem and a command run in another,
/// and on a machine with no WSL distribution installed the same call fails outright. So the
/// candidates are explicit and `PATH` is not consulted.
///
/// `MARLOWE_BASH` overrides, for a machine that keeps Git somewhere else. It is read once.
#[cfg(windows)]
fn git_bash() -> Option<std::path::PathBuf> {
    use std::sync::OnceLock;
    static FOUND: OnceLock<Option<std::path::PathBuf>> = OnceLock::new();
    FOUND
        .get_or_init(|| {
            if let Some(explicit) = std::env::var_os("MARLOWE_BASH") {
                let p = std::path::PathBuf::from(explicit);
                return p.is_file().then_some(p);
            }
            let mut roots: Vec<std::path::PathBuf> = Vec::new();
            for var in ["ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"] {
                if let Some(v) = std::env::var_os(var) {
                    roots.push(std::path::PathBuf::from(&v).join("Git"));
                    roots.push(std::path::PathBuf::from(&v).join("Programs").join("Git"));
                }
            }
            roots.push(std::path::PathBuf::from(r"C:\Program Files\Git"));
            for root in roots {
                // `bin\bash.exe` is the launcher Git for Windows puts on a user's PATH;
                // `usr\bin\bash.exe` is the same shell one level down. Either is fine.
                for rel in [r"bin\bash.exe", r"usr\bin\bash.exe"] {
                    let candidate = root.join(rel);
                    if candidate.is_file() {
                        return Some(candidate);
                    }
                }
            }
            None
        })
        .clone()
}

/// **The `bash` tool runs bash.** On Windows that is Git Bash, which is what this project's own
/// tooling uses and what the model's shell vocabulary assumes.
///
/// # It ran `cmd /C` until 2026-08-27, and that is why every shell call failed
///
/// The tool has always been NAMED `bash`. It ran `cmd.exe`, so a model writing the shell it was
/// told it had -- `ls`, `find -type f`, `head`, `grep`, `2>/dev/null` -- got failures that looked
/// like a model unable to use a shell. Across two live sessions it made **seven** attempts to list
/// one directory and never succeeded once; each was `Irreversible`, so each stopped and asked the
/// user first. It then reported a directory with four files in it as *"appears empty"*.
///
/// Two separate faults, and fixing only the first left it broken:
///
/// 1. `Command::arg` applies **Rust's** escaping, turning `"` into `\"`, and `cmd.exe` reads that
///    literally -- so every QUOTED command arrived corrupted. `raw_arg` fixed that for `cmd`.
/// 2. The interpreter was still wrong. Teaching the model `cmd` was the other option and it is the
///    worse one: the tool's name, the model's priors and this project's own scripts are all bash.
///
/// **Rust's escaping is correct for this shell**, so `arg` is right here where `raw_arg` was right
/// for `cmd` -- MSYS2 parses the MSVC-style command line the way `Command` writes it. Measured:
/// `echo "hello world"` through `arg` prints `hello world`, where the same call to `cmd` printed
/// `\"hello world\"`.
///
/// **No fallback to `cmd`.** A shell that is silently a different shell is precisely the defect
/// being removed; if Git Bash is absent the call fails and says what to install.
#[cfg(windows)]
fn spawn_shell(
    command: &str,
    dir: &Path,
    _cwd_handle: Option<&ScopedPath>,
) -> std::io::Result<ShellRun> {
    // The cwd crosses as a STRING because Win32 has no handle-relative spawn. What makes it safe
    // is that `_cwd_handle` is still alive: the walk opened it without FILE_SHARE_DELETE, so the
    // directory cannot be renamed or deleted, and the string still names the verified object.
    let mut cmd = shell_command()?;
    cmd.arg(command).current_dir(dir);
    run_bounded(cmd, ShellLimits::production())
}

#[cfg(unix)]
#[allow(unsafe_code)]
fn spawn_shell(
    command: &str,
    _dir: &Path,
    cwd_handle: Option<&ScopedPath>,
) -> std::io::Result<ShellRun> {
    use std::os::unix::io::AsRawFd;
    use std::os::unix::process::CommandExt;

    // **`bash`, not `sh`.** The tool is named `bash` and the model writes bash; `sh` is a
    // different shell on several distributions and the difference shows up exactly where a model
    // reaches for a bashism.
    let mut cmd = shell_command()?;
    cmd.arg(command);
    match cwd_handle {
        Some(scoped) => {
            // No string crosses at all: the child changes directory to the descriptor the walk
            // verified, before `exec`. This is the gap Windows cannot close.
            let fd = scoped.handle().as_raw_fd();
            unsafe {
                cmd.pre_exec(move || {
                    rustix::process::fchdir(std::os::fd::BorrowedFd::borrow_raw(fd))
                        .map_err(|e| std::io::Error::from_raw_os_error(e.raw_os_error()))
                });
            }
        }
        None => {
            cmd.current_dir(_dir);
        }
    }
    run_bounded(cmd, ShellLimits::production())
}

/// Spawn, read both pipes under a cap, wait under a deadline, kill on breach of either.
///
/// # What this does NOT close, stated rather than implied
///
/// **The grandchild.** `child.kill()` kills the shell, not what the shell started. On Unix the
/// child is not put in its own process group and no group signal is sent; on Windows there is no
/// Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, which would need a `windows-sys`
/// dependency this crate does not have. So `bash("sh -c 'sleep 999 &'")` leaves the grandchild
/// running after this returns.
///
/// What *is* closed is the one the audit named: the **harness** no longer waits on it. The turn,
/// the batch and the daemon come back. A surviving grandchild is a resource leak; a hung daemon was
/// a denial of service, and they are not the same severity. The Job Object is worth doing and is
/// not being claimed here.
pub fn run_bounded(
    mut cmd: std::process::Command,
    limits: ShellLimits,
) -> std::io::Result<ShellRun> {
    use std::process::Stdio;
    use std::sync::atomic::AtomicBool;
    use std::sync::Arc;

    // **stdin is null, not inherited.** An inherited stdin lets an approved command read the
    // terminal the user is typing into, and a command that blocks on it would have been another
    // way to hang before the deadline existed.
    cmd.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = cmd.spawn()?;

    let over_cap = Arc::new(AtomicBool::new(false));
    let (tx, rx) = std::sync::mpsc::channel::<(bool, Vec<u8>)>();

    // `true` marks stdout so the two streams can be told apart on the way back; the channel is what
    // makes abandoning a blocked reader possible, which `join` would not be.
    for (is_stdout, pipe) in [
        (true, child.stdout.take().map(DynRead::Out),),
        (false, child.stderr.take().map(DynRead::Err)),
    ] {
        let Some(pipe) = pipe else { continue };
        let tx = tx.clone();
        let flag = Arc::clone(&over_cap);
        std::thread::spawn(move || {
            let buf = drain_capped(pipe, limits.max_output_bytes, &flag);
            let _ = tx.send((is_stdout, buf));
        });
    }
    drop(tx);

    let mut stopped = false;
    let mut flooded = false;
    let mut waited = 0u64;
    let status = loop {
        // LOOP-EXEMPT: waiting on a child process, not a driving loop.
        if over_cap.load(Ordering::Relaxed) {
            flooded = true;
            let _ = child.kill();
            break child.wait()?;
        }
        match child.try_wait()? {
            Some(s) => break s,
            None => {
                if waited >= limits.timeout_ms {
                    stopped = true;
                    let _ = child.kill();
                    break child.wait()?;
                }
                std::thread::sleep(std::time::Duration::from_millis(POLL_MS));
                waited += POLL_MS;
            }
        }
    };

    // Whatever the readers managed to hand back within the grace. Two streams, so two receives.
    let grace = std::time::Duration::from_millis(READER_GRACE_MS);
    let (mut out, mut err) = (Vec::new(), Vec::new());
    for _ in 0..2 {
        match rx.recv_timeout(grace) {
            Ok((true, b)) => out = b,
            Ok((false, b)) => err = b,
            Err(_) => break,
        }
    }

    Ok(ShellRun {
        code: status.code().unwrap_or(-1),
        text: combine(&out, &err),
        stopped,
        flooded: flooded || over_cap.load(Ordering::Relaxed),
    })
}

/// The two pipe types, so one reader function serves both without a trait object per read.
enum DynRead {
    Out(std::process::ChildStdout),
    Err(std::process::ChildStderr),
}

impl Read for DynRead {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        match self {
            DynRead::Out(r) => r.read(buf),
            DynRead::Err(r) => r.read(buf),
        }
    }
}

/// Read until EOF or the cap, setting `flag` the moment the cap is passed.
///
/// It keeps reading after the cap and discards, rather than returning immediately: returning would
/// close the pipe and hand the child a broken pipe mid-write, and the caller is about to kill it
/// anyway. The flag is what the wait loop watches.
fn drain_capped(mut r: impl Read, cap: usize, flag: &std::sync::atomic::AtomicBool) -> Vec<u8> {
    let mut buf = Vec::new();
    let mut chunk = [0u8; 16 * 1024];
    loop {
        // LOOP-EXEMPT: draining a pipe, not a driving loop.
        match r.read(&mut chunk) {
            Ok(0) | Err(_) => break,
            Ok(n) => {
                if buf.len() >= cap {
                    flag.store(true, Ordering::Relaxed);
                    continue;
                }
                let room = cap - buf.len();
                buf.extend_from_slice(&chunk[..n.min(room)]);
                if n > room {
                    flag.store(true, Ordering::Relaxed);
                }
            }
        }
    }
    buf
}

/// A `Content-Type` header, reduced to a media type or `"unknown"`.
///
/// Audit finding A4's second half. The raw header went into the summary detail, and a header is a
/// server-chosen string: parameters, quoted values and anything else the origin cares to write.
/// This keeps the part before the first `;` and only if it is a media-type **token**; everything
/// else is reported as unknown rather than quoted.
fn normalize_content_type(ct: Option<&str>) -> &'static str {
    // Returning `&'static str` is the enforcement, not a style choice: a `String` return could be
    // built from the header by a later edit and nothing would notice. This signature cannot.
    const KNOWN: &[&str] = &[
        "text/html",
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/xml",
        "application/xml",
        "application/json",
        "application/pdf",
        "application/zip",
        "application/epub+zip",
        "application/octet-stream",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ];
    let Some(ct) = ct else { return "no content-type" };
    let media = ct.split(';').next().unwrap_or("").trim().to_ascii_lowercase();
    KNOWN.iter().copied().find(|k| *k == media).unwrap_or("an unrecognised content-type")
}

fn text_lines(body: &ToolBody) -> u64 {
    match body {
        ToolBody::Inline(s) => s.lines().count() as u64,
        ToolBody::Reference { .. } => 0,
    }
}

fn combine(stdout: &[u8], stderr: &[u8]) -> String {
    let mut s = String::from_utf8_lossy(stdout).into_owned();
    if !stderr.is_empty() {
        if !s.is_empty() {
            s.push('\n');
        }
        s.push_str(&String::from_utf8_lossy(stderr));
    }
    s
}
