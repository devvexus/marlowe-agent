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

/// How many files `find` will open in one call. A search is bounded structurally rather than by
/// hoping the pattern is selective.
pub const FIND_FILE_CAP: usize = 2_000;

/// How long `bash` may run before it is killed.
pub const BASH_TIMEOUT_MS: u64 = 120_000;

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
}

impl<S: PathScope> FileSystemTools<S> {
    pub fn new(scope: S, workspace: impl Into<PathBuf>) -> Self {
        Self {
            scope,
            workspace: workspace.into(),
            store: marlowe_extract::store::DocumentStore::new(),
        }
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

fn failed(verb: &'static str, detail: impl Into<String>) -> ToolOutcome {
    ToolOutcome {
        summary: ResultSummary::with_detail(vec![Metric::State(verb)], detail),
        body: ToolBody::Inline(String::new()),
        // The harness computed this refusal, so it is agent-observed. Inheriting the call's own
        // taint would make a blocked-call notice unreadable by the very next step.
        trust: TrustClass::AgentObserved,
        failed: true,
        wall_ms: 0,
        preview: None,
    }
}

/// Inline if small, reference if not. §2.8's first axis — **size**, independent of trust.
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
        if let Err(e) = clone_and_read(scoped, &mut text) {
            return failed("read", e.to_string());
        }
        // `range` is a Payload: untrusted prose may shape it freely, because it selects nothing
        // outside a file the target check already approved.
        if let Some(range) = text_arg(args, "range") {
            text = slice_lines(&text, range);
        }
        let lines = text.lines().count() as u64;
        let (body, bytes, preview) = body_for(text);
        ToolOutcome {
            summary: ResultSummary::new(vec![
                Metric::Count { n: lines, unit: "lines" },
                Metric::Bytes { n: bytes },
            ]),
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

    fn edit(&self, args: &Args, a: &Adjudication) -> ToolOutcome {
        let Some(scoped) = handle_for(a, "path") else {
            return failed("edit", "no adjudicated handle for `path`");
        };
        let Some(content) = text_arg(args, "content") else {
            return failed("edit", "`content` is required");
        };

        let mut file = match scoped.handle().try_clone() {
            Ok(f) => f,
            Err(e) => return failed("edit", e.to_string()),
        };

        let (next, added, removed) = if let Some(replacing) = text_arg(args, "replacing") {
            let mut existing = String::new();
            if let Err(e) = file.read_to_string(&mut existing) {
                return failed("edit", e.to_string());
            }
            let Some(at) = existing.find(replacing) else {
                return failed("edit", "`replacing` was not found in the file");
            };
            let mut next = String::with_capacity(existing.len());
            next.push_str(&existing[..at]);
            next.push_str(content);
            next.push_str(&existing[at + replacing.len()..]);
            (next, count_lines(content), count_lines(replacing))
        } else {
            let mut existing = String::new();
            let _ = file.read_to_string(&mut existing);
            (content.to_string(), count_lines(content), count_lines(&existing))
        };

        // Truncate through the handle, not by reopening with `create(true)`.
        if let Err(e) = file
            .set_len(0)
            .and_then(|()| file.seek(SeekFrom::Start(0)).map(|_| ()))
            .and_then(|()| file.write_all(next.as_bytes()))
            .and_then(|()| file.flush())
        {
            return failed("edit", e.to_string());
        }

        ToolOutcome {
            summary: ResultSummary::new(vec![Metric::Diff { added, removed }]),
            body: ToolBody::Inline(scoped.relative().to_string()),
            trust: TrustClass::AgentObserved,
            failed: false,
            wall_ms: 0,
            // `edit` reports a diff, not a body; there is nothing to preview.
            preview: None,
        }
    }

    fn find(&self, args: &Args, a: &Adjudication, declared: &[PathGlob]) -> ToolOutcome {
        let Some(pattern) = text_arg(args, "pattern") else {
            return failed("find", "`pattern` is required");
        };
        let Some(root) = handle_for(a, "path") else {
            return failed("find", "no adjudicated handle for `path`");
        };

        // Enumeration produces candidate NAMES. Every one is then opened through the scope, so
        // nothing this loop reads bypassed the wall.
        let base = root.resolved().to_path_buf();
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
            Ok((code, text)) => {
                let (body, _, preview) = body_for(text);
                let lines = text_lines(&body);
                let mut metrics = vec![Metric::Count { n: lines, unit: "lines" }];
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
        if let Some(range) = text_arg(args, "range") {
            text = slice_lines(&text, range);
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

        match crate::corpus::read(url, fetched) {
            crate::corpus::Outcome::Redirect { status, location, .. } => ToolOutcome {
                summary: ResultSummary::with_detail(
                    vec![Metric::State("redirect")],
                    format!("{status} -> {location}"),
                ),
                body: ToolBody::Inline(format!(
                    "{url} redirected to {location}. It was NOT followed: a redirect target \
                     is chosen by the site, so it is checked like any other target. Call \
                     `web` again with that URL if it is what you want."
                )),
                // The harness observed the status and the header. The BODY is what would
                // be untrusted, and none of it is being returned here.
                trust: TrustClass::AgentObserved,
                failed: false,
                wall_ms: 0,
                preview: None,
            },

            // **Extraction failed, so nothing readable exists — and the raw bytes are NOT a
            // fallback.** Handing over undecodable input would put the exact material this
            // change exists to remove back into the window, on the one path nobody tests.
            crate::corpus::Outcome::Unreadable { detail, .. } => ToolOutcome {
                summary: ResultSummary::with_detail(
                    vec![Metric::State("unreadable"), Metric::Bytes { n: raw_bytes as u64 }],
                    format!("{status} {}", content_type.as_deref().unwrap_or("no content-type")),
                ),
                body: ToolBody::Inline(format!(
                    "{url} returned {raw_bytes} bytes that could not be turned into text: \
                     {detail}. Nothing was read."
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
                let text = reference.render();
                let chars = reference.chars as u64;
                let (body, _, preview) = body_for(text);
                ToolOutcome {
                    summary: ResultSummary::with_detail(
                        vec![
                            Metric::State(if status < 400 { "ok" } else { "http" }),
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
        ["read", "edit", "find", "bash", "web"]
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
            "edit" => self.edit(args, adjudication),
            "find" => self.find(args, adjudication, &declared),
            "bash" => self.bash(args, adjudication),
            "web" => self.web(args),
            other => failed("tool", format!("`{other}` has no executor in this build")),
        }
    }
}

fn clone_and_read(scoped: &ScopedPath, into: &mut String) -> std::io::Result<()> {
    let mut f = scoped.handle().try_clone()?;
    f.seek(SeekFrom::Start(0))?;
    f.read_to_string(into)?;
    Ok(())
}

fn count_lines(s: &str) -> u32 {
    if s.is_empty() {
        0
    } else {
        s.lines().count() as u32
    }
}

fn slice_lines(text: &str, range: &str) -> String {
    let Some((a, b)) = range.split_once('-') else { return text.to_string() };
    let (Ok(a), Ok(b)) = (a.trim().parse::<usize>(), b.trim().parse::<usize>()) else {
        return text.to_string();
    };
    text.lines().skip(a.saturating_sub(1)).take(b.saturating_sub(a) + 1).collect::<Vec<_>>().join("\n")
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

#[cfg(windows)]
fn spawn_shell(
    command: &str,
    dir: &Path,
    _cwd_handle: Option<&ScopedPath>,
) -> std::io::Result<(i32, String)> {
    // The cwd crosses as a STRING because Win32 has no handle-relative spawn. What makes it safe
    // is that `_cwd_handle` is still alive: the walk opened it without FILE_SHARE_DELETE, so the
    // directory cannot be renamed or deleted, and the string still names the verified object.
    let out = std::process::Command::new("cmd").arg("/C").arg(command).current_dir(dir).output()?;
    Ok((out.status.code().unwrap_or(-1), combine(&out.stdout, &out.stderr)))
}

#[cfg(unix)]
#[allow(unsafe_code)]
fn spawn_shell(
    command: &str,
    _dir: &Path,
    cwd_handle: Option<&ScopedPath>,
) -> std::io::Result<(i32, String)> {
    use std::os::unix::io::AsRawFd;
    use std::os::unix::process::CommandExt;

    let mut cmd = std::process::Command::new("sh");
    cmd.arg("-c").arg(command);
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
    let out = cmd.output()?;
    Ok((out.status.code().unwrap_or(-1), combine(&out.stdout, &out.stderr)))
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
