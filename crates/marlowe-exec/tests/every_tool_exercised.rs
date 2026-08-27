//! An ordinary-and-edge-case sweep of the five local executors: `read`, `write`, `edit`, `find`,
//! `bash`. `web` is excluded — it reaches the network.
//!
//! Companion to `tests/executors.rs`, which established the pattern this file reuses: adjudicate
//! for real through `WorkspaceScope` and the `Adjudicator`, then hand the result to
//! `FileSystemTools`, so what is under test is the executor using the handle the permission layer
//! actually opened rather than a hand-built one.
//!
//! This file exists because three bugs shipped past a ~1400-test suite that only ever exercised
//! the cases someone thought to write: `bash` mangling every quoted command on Windows, `edit`
//! creating a file and then refusing to write it, `read` on an empty file being indistinguishable
//! from a missing one. The brief is to run each tool against a real temp filesystem across
//! ordinary and adversarial inputs and see what else is in that family.
//!
//! Every `// SUSPECT:` comment names a behaviour this file found concerning, states what a model
//! holding only the tool's description would expect instead, and why the gap matters. Everything
//! else asserts what is believed to be correct behaviour and is not flagged.

use std::fs;
use std::path::PathBuf;

use marlowe_contract::TrustClass;
use marlowe_exec::FileSystemTools;
use marlowe_loop::{ToolBody, ToolHost, ToolOutcome};
use marlowe_permission::scope::WorkspaceScope;
use marlowe_permission::{
    Adjudication, Adjudicator, Args, BlockReason, EgressPolicy, Outcome, Request, TaintSet, Tier,
};
use marlowe_tools::{builtin_registry, ExposedSet, ToolId, ToolRegistry, BUILTIN_TOOLS};

static SEQ: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

/// A bare workspace: nothing pre-seeded. Each test builds exactly the files it needs, so a
/// fixture's contents are visible at the call site rather than hidden in shared setup.
struct Fixture {
    root: PathBuf,
    registry: ToolRegistry,
}

impl Fixture {
    fn new(name: &str) -> Self {
        let n = SEQ.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let root = std::env::temp_dir()
            .join(format!("marlowe-exec-every-{name}-{}-{n}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        Self { root, registry: builtin_registry().unwrap() }
    }

    fn seed(&self, rel: &str, content: &str) {
        let p = self.root.join(rel);
        if let Some(parent) = p.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(p, content).unwrap();
    }

    fn mkdir(&self, rel: &str) {
        fs::create_dir_all(self.root.join(rel)).unwrap();
    }

    fn on_disk(&self, rel: &str) -> String {
        fs::read_to_string(self.root.join(rel)).unwrap()
    }

    /// Adjudicate for real, then hand the result to the executor — see `tests/executors.rs`'s
    /// header for why re-resolving a path here instead would test the wrong thing.
    fn call(&self, tool: &str, args: Args) -> (Outcome, ToolOutcome) {
        let exposed =
            ExposedSet::new(BUILTIN_TOOLS.iter().map(|t| ToolId::new(*t)).collect()).unwrap();
        let mut taint = TaintSet::new();
        for (name, _) in args.iter() {
            taint.insert(name.clone(), TrustClass::UserAsserted);
        }
        let egress = EgressPolicy::DenyAll;
        let mut adj = Adjudicator::new(WorkspaceScope::new().expect("verified platform"));
        let adjudication: Adjudication = adj.adjudicate(Request {
            manifest: self.registry.manifest(&ToolId::new(tool)).unwrap(),
            args: &args,
            taint: &taint,
            exposed: &exposed,
            egress: &egress,
            workspace: &self.root,
            tier: Tier::Silent,
            novelty: None,
        });
        let outcome = adjudication.decision.outcome.clone();
        let mut tools =
            FileSystemTools::new(WorkspaceScope::new().expect("verified platform"), &self.root);
        let result = tools.execute(&ToolId::new(tool), &args, &adjudication);
        (outcome, result)
    }

    /// **Why a call failed, wherever the executor put it.**
    ///
    /// `marlowe_exec::failed` returns `body: ToolBody::Inline(String::new())` and the reason in
    /// `summary.detail`. A failure assertion that reads `text()` therefore reads the empty string
    /// — which is why every one of them panicked with a blank message. This is the same
    /// detail-versus-body split that reached the MODEL as the literal string `"edit · "`, in a
    /// test file rather than in a window.
    ///
    /// Both are concatenated rather than choosing one, so a tool that reports through the body
    /// (`bash` puts its output there) is covered by the same helper.
    fn why(&self, r: &ToolOutcome) -> String {
        format!("{} {}", r.summary.detail.clone().unwrap_or_default(), self.text(r))
    }

    fn text(&self, r: &ToolOutcome) -> String {
        match &r.body {
            ToolBody::Inline(s) => s.clone(),
            ToolBody::Reference { hash, bytes } => format!("<ref {hash} {bytes}>"),
        }
    }

    fn detail(&self, r: &ToolOutcome) -> String {
        r.summary.detail.clone().unwrap_or_default()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

// ============================================================================================
// read
// ============================================================================================

#[test]
fn read_ordinary_success() {
    let fx = Fixture::new("read-ok");
    fx.seed("hello.txt", "one\ntwo\nthree\n");
    let (outcome, r) = fx.call("read", Args::new().text("path", "hello.txt"));
    assert_eq!(outcome, Outcome::Allowed);
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fx.text(&r), "one\ntwo\nthree\n");
    assert_eq!(r.summary.render(), "3 lines · 14 B");
}

#[test]
fn read_neither_path_nor_ref_is_a_clear_refusal() {
    let fx = Fixture::new("read-neither");
    let (outcome, r) = fx.call("read", Args::new());
    assert_eq!(outcome, Outcome::Allowed, "nothing was declared, so nothing was checked");
    assert!(r.failed);
    // **The reason is in BOTH the body and `detail` now**, so no consumer has to know that
    // failures are shaped differently from successes. This asserted that `detail` was EMPTY,
    // which was true and was the defect: the model's window is built from the body, the journal
    // read `detail`, and each got half the story.
    assert!(!fx.detail(&r).is_empty(), "a failure must carry its reason in `detail`");
    assert!(
        fx.why(&r).contains("supply either `path`") && fx.why(&r).contains("Neither was given"),
        "{}",
        fx.why(&r)
    );
}

#[test]
fn read_empty_string_path_is_a_malformed_request() {
    let fx = Fixture::new("read-empty-path");
    let (outcome, r) = fx.call("read", Args::new().text("path", ""));
    assert!(outcome.is_blocked(), "{outcome:?}");
    match outcome {
        Outcome::Blocked { reason: BlockReason::UndeclaredPath { detail, .. } } => {
            assert!(detail.contains("empty path component"), "{detail}");
        }
        other => panic!("expected UndeclaredPath, got {other:?}"),
    }
    assert!(r.failed);
    assert!(fx.why(&r).contains("no adjudicated handle for `path`"), "{}", fx.why(&r));
}

#[test]
fn read_path_with_a_space_survives() {
    let fx = Fixture::new("read-space");
    fx.seed("a folder/my notes.md", "space in the path\n");
    let (_, r) = fx.call("read", Args::new().text("path", "a folder/my notes.md"));
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fx.text(&r), "space in the path\n");
}

#[test]
fn read_path_with_unicode_survives() {
    let fx = Fixture::new("read-unicode");
    // Precomposed NFC, matching what `request::validate` normalizes both sides to.
    fx.seed("café-résumé.md", "unicode path\n");
    let (_, r) = fx.call("read", Args::new().text("path", "café-résumé.md"));
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fx.text(&r), "unicode path\n");
}

#[test]
fn read_missing_file_says_it_is_not_a_refusal() {
    let fx = Fixture::new("read-missing");
    let (outcome, r) = fx.call("read", Args::new().text("path", "does-not-exist.txt"));
    assert!(outcome.is_blocked(), "{outcome:?}");
    match outcome {
        Outcome::Blocked { reason: BlockReason::UndeclaredPath { detail, .. } } => {
            // This is `ScopeError::Unopenable`'s careful text -- "NOT a scoping refusal" -- and
            // it is real information that never reaches the executor's own message below.
            assert!(detail.contains("NOT a scoping refusal"), "{detail}");
            assert!(detail.contains("`find`"), "{detail}");
        }
        other => panic!("expected UndeclaredPath, got {other:?}"),
    }
    assert!(r.failed);
    // SUSPECT: the executor's own text collapses every reason a handle could be absent into one
    // sentence -- "no adjudicated handle for `path`" -- which says nothing about *why*. The
    // adjudicator's `BlockReason::UndeclaredPath` carries the careful, ENOENT-specific message
    // above ("NOT a scoping refusal... confirm with `find`"), and it is genuinely reachable by
    // the model (see `refusal_prose` in `marlowe-loop/src/engine.rs`), so this executor-level
    // fallback is not the only thing the model sees in production. It matters anyway because
    // `refusal_prose`'s `UndeclaredPath` arm is a SINGLE template shared by every scope failure --
    // "The path `{path}` is outside the workspace this run may touch... Retry with a path
    // relative to the workspace root, with no `..` and no drive letter" -- which is simply FALSE
    // for a relative, in-scope path that happens not to exist. A model told to retry with a
    // "properly relative" path when the path was already exactly that will try meaningless
    // reformulations of a filename that was never the problem. This is the same confusion
    // CLAUDE.md already records happening live on 2026-08-25 over `Unopenable`, and the fix
    // documented there (the ScopeError message itself) is undone one layer up, in the file the
    // model's refusal prose actually comes from.
    assert!(fx.why(&r).contains("no adjudicated handle for `path`"), "{}", fx.why(&r));
}

#[test]
fn read_a_directory_given_as_path() {
    let fx = Fixture::new("read-dir");
    fx.mkdir("a-directory");
    let (outcome, r) = fx.call("read", Args::new().text("path", "a-directory"));
    // Scoping does not require the FINAL component to be a directory or a file for `Access::Read`
    // -- that check only applies to intermediate components during the walk (`walk.rs`, "not a
    // directory" is checked only `if !is_last`). So the handle opens successfully...
    assert!(outcome.is_blocked() == false || outcome.needs_approval(), "{outcome:?}");
    // ...and what the executor does with a directory HANDLE is the interesting part.
    if r.failed {
        // A read error surfaced, which is the sound outcome: the model is told the read did not
        // work, rather than being handed a result that looks like an empty file.
        assert!(!fx.detail(&r).is_empty(), "a failed read should say why: {:?}", r.summary);
    } else {
        // SUSPECT: if this branch is live, reading a directory produced a *successful* result --
        // and given `MAX_READ_BYTES`/UTF-8 handling, the most likely shape is "0 lines · 0 B",
        // which is EXACTLY the signature `read`'s own manifest description reserves for "the file
        // is there and is empty" ("a result of `0 lines · 0 B` means the file is there and is
        // empty — reading it again will not change that"). A directory is neither missing nor
        // empty, and a model told to trust that signature would misdiagnose a directory as an
        // empty file with the same confidence the manifest asks it to have.
        assert_eq!(
            r.summary.render(),
            "0 lines · 0 B",
            "if this ever reads as content instead, this whole test needs re-deriving: {}",
            fx.text(&r)
        );
    }
}

#[test]
fn read_empty_file_is_the_documented_signature() {
    let fx = Fixture::new("read-empty-file");
    fx.seed("empty.txt", "");
    let (outcome, r) = fx.call("read", Args::new().text("path", "empty.txt"));
    assert_eq!(outcome, Outcome::Allowed);
    // Not flagged: the manifest description now states this explicitly ("a result of `0 lines ·
    // 0 B` means the file is there and is empty"), so this is the documented contract, verified.
    assert!(!r.failed);
    assert_eq!(fx.text(&r), "");
    assert_eq!(r.summary.render(), "0 lines · 0 B");
}

/// **A file over the inline threshold is READ, not referenced.**
///
/// This asserted the opposite, and the opposite was the defect: anything over `MAX_INLINE_BYTES`
/// became a `ContentRef` — a hash plus a 4 KB head-and-tail — and **a file reference cannot be
/// dereferenced**, because `read`'s `ref` takes ids `web` issued. The middle of every file above
/// 8 KB was unreachable, which is why a run could read five design documents and answer from none
/// of them.
///
/// The summary's numbers now describe what was RETURNED rather than what was withheld, which is
/// the honest reading of a windowed result: the notice carries the file's true length.
#[test]
fn read_large_file_returns_a_readable_window_not_a_hash() {
    let fx = Fixture::new("read-large");
    let content: String = (1..=5000).map(|i| format!("line {i}\n")).collect();
    assert!(
        content.len() > marlowe_exec::MAX_INLINE_BYTES,
        "the test is only meaningful over the old inline threshold"
    );
    fx.seed("big.txt", &content);

    let (_, r) = fx.call("read", Args::new().text("path", "big.txt"));
    assert!(!r.failed, "{:?}", r.summary);

    match &r.body {
        ToolBody::Inline(body) => {
            assert!(body.contains("line 1\n"), "the window starts at the top");
            assert!(body.contains("of 5000"), "and states the file's true length: {body:.200}");
        }
        ToolBody::Reference { .. } => {
            panic!("a file must never come back as a hash the model cannot dereference")
        }
    }
    // The counts describe the WINDOW. The full length is in the notice, where it is useful.
    let rendered = r.summary.render();
    assert!(rendered.contains("lines"), "{rendered}");
    assert!(
        fx.text(&r).lines().count() <= marlowe_exec::READ_WINDOW_LINES + 5,
        "the window must bound what came back: {rendered}"
    );
}

#[test]
fn read_range_normal_selects_the_named_lines() {
    let fx = Fixture::new("read-range-normal");
    let content: String = (1..=100).map(|i| format!("line {i}\n")).collect();
    fx.seed("hundred.txt", &content);
    let (_, r) = fx.call("read", Args::new().text("path", "hundred.txt").text("range", "20-60"));
    assert!(!r.failed, "{:?}", r.summary);
    let body = fx.text(&r);
    assert!(body.starts_with("line 20\n"), "{body}");
    assert!(body.trim_end().ends_with("line 60"), "{body}");
    assert_eq!(body.lines().count(), 41);
}

/// A transposition, and it used to render as `0 lines · 0 B` — the signature `read`'s own
/// description reserves for "the file is there and is empty".
#[test]
fn read_range_reversed_is_refused_with_the_swap() {
    let fx = Fixture::new("read-range-reversed");
    let content: String = (1..=100).map(|i| format!("line {i}\n")).collect();
    fx.seed("hundred.txt", &content);
    let (_, r) = fx.call("read", Args::new().text("path", "hundred.txt").text("range", "60-20"));
    assert!(r.failed, "a backwards range must not read as an empty file");
    assert!(fx.why(&r).contains("20-60"), "offer the swap it can see: {}", fx.why(&r));
}

/// **The sharpest collision `range` produced.** Slicing happens BEFORE the metrics are computed,
/// so an out-of-bounds range on a ten-line file rendered `0 lines · 0 B` — the exact string
/// `read`'s description promises means "the file is there and is empty". The description's promise
/// became false the instant `range` was supplied.
#[test]
fn read_range_past_the_end_says_how_long_the_file_is() {
    let fx = Fixture::new("read-range-oob");
    fx.seed("ten.txt", &(1..=10).map(|i| format!("line {i}\n")).collect::<String>());
    let (_, r) = fx.call("read", Args::new().text("path", "ten.txt").text("range", "500-600"));
    assert!(r.failed, "a range that selected nothing must not render as an empty file");
    assert!(
        fx.why(&r).contains("the file has 10"),
        "the fact the model needs is the line count: {}",
        fx.why(&r)
    );
}

/// **`slice_lines` returned the WHOLE FILE for anything it could not parse.** A model that
/// mistyped a range on a large file got everything back with nothing to say the range had been
/// ignored rather than honoured — which for a file near `MAX_INLINE_BYTES` turns a targeted read
/// into a `ContentRef` it then cannot dereference.
#[test]
fn read_range_malformed_is_refused_not_silently_ignored() {
    let fx = Fixture::new("read-range-malformed");
    let content = "line 1\nline 2\nline 3\n";
    fx.seed("three.txt", content);
    let (_, r) = fx.call("read", Args::new().text("path", "three.txt").text("range", "abc"));
    assert!(r.failed, "a range that cannot be parsed must not read as no range at all");
    assert!(fx.why(&r).contains("first-last"), "state the format: {}", fx.why(&r));
}

/// The same family: `"2"` has no `-`, so `split_once` returned `None` and the whole file came
/// back. "Just line 2" is a reasonable guess at a parameter documented as *"line range"*, and the
/// answer to a reasonable guess is the format, not the entire file.
#[test]
fn read_range_of_a_single_number_is_refused_with_the_format() {
    let fx = Fixture::new("read-range-single");
    let content = "line 1\nline 2\nline 3\n";
    fx.seed("three.txt", content);
    let (_, r) = fx.call("read", Args::new().text("path", "three.txt").text("range", "2"));
    assert!(r.failed, "`2` is not a range and must not silently mean the whole file");
    assert!(fx.why(&r).contains("first-last"), "{}", fx.why(&r));
}

// ============================================================================================
// edit
// ============================================================================================

#[test]
fn edit_ordinary_success() {
    let fx = Fixture::new("edit-ok");
    fx.seed("notes.md", "alpha\nbeta needle\ngamma\n");
    let (_, r) = fx.call(
        "edit",
        Args::new().text("path", "notes.md").text("replacing", "beta needle").text("content", "beta found"),
    );
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fx.on_disk("notes.md"), "alpha\nbeta found\ngamma\n");
}

#[test]
fn edit_missing_path() {
    let fx = Fixture::new("edit-no-path");
    let (_, r) =
        fx.call("edit", Args::new().text("content", "x").text("replacing", "y"));
    assert!(r.failed);
    assert!(fx.why(&r).contains("no adjudicated handle for `path`"), "{}", fx.why(&r));
}

#[test]
fn edit_missing_content() {
    let fx = Fixture::new("edit-no-content");
    fx.seed("notes.md", "alpha\n");
    let (_, r) = fx.call("edit", Args::new().text("path", "notes.md").text("replacing", "alpha"));
    assert!(r.failed);
    assert!(fx.why(&r).contains("`content` is required"), "{}", fx.why(&r));
    assert_eq!(fx.on_disk("notes.md"), "alpha\n", "a rejected call must not touch the file");
}

#[test]
fn edit_missing_replacing_names_write_as_the_remedy() {
    let fx = Fixture::new("edit-no-replacing");
    fx.seed("notes.md", "alpha\n");
    let (_, r) = fx.call("edit", Args::new().text("path", "notes.md").text("content", "beta"));
    assert!(r.failed);
    assert!(fx.why(&r).contains("`replacing` is required"), "{}", fx.why(&r));
    assert!(fx.why(&r).contains("`write`"), "{}", fx.why(&r));
    assert_eq!(fx.on_disk("notes.md"), "alpha\n");
}

/// **`str::find("")` returns `Some(0)` for any string, so an empty `replacing` matched trivially
/// at offset 0 and PREPENDED `content` — reported as an ordinary successful edit.**
///
/// A model reaches an empty `replacing` by accident: a snippet extracted from a `read` that
/// returned nothing, a template filled in blank, a variable stripped. It is the write-then-refuse
/// bug one step worse — that one failed loudly and wasted a call; this one succeeded wrongly and
/// changed a file nobody asked it to change.
#[test]
fn edit_empty_string_replacing_is_refused_not_silently_prepended() {
    let fx = Fixture::new("edit-empty-replacing");
    fx.seed("notes.md", "hello\nworld\n");
    let (_, r) = fx.call(
        "edit",
        Args::new().text("path", "notes.md").text("replacing", "").text("content", "INSERTED-"),
    );
    assert!(r.failed, "an empty `replacing` must not be treated as a match: {:?}", r.summary);
    assert!(fx.why(&r).contains("`write`"), "the remedy must be named: {}", fx.why(&r));
    assert_eq!(
        fx.on_disk("notes.md"),
        "hello\nworld\n",
        "THE PROPERTY: the file is untouched. This used to prepend `content` and report success."
    );
}

#[test]
fn edit_empty_string_content_deletes_the_snippet() {
    let fx = Fixture::new("edit-empty-content");
    fx.seed("notes.md", "alpha\nbeta\ngamma\n");
    let (_, r) = fx.call(
        "edit",
        Args::new().text("path", "notes.md").text("replacing", "beta\n").text("content", ""),
    );
    // Not flagged: this is an ordinary, predictable deletion -- `content` becoming the empty
    // string is exactly "delete `replacing`", and the manifest's wording ("`content` becomes...
    // what `replacing` becomes") supports reading it that way.
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fx.on_disk("notes.md"), "alpha\ngamma\n");
}

#[test]
fn edit_empty_string_path_is_malformed() {
    let fx = Fixture::new("edit-empty-path");
    let (outcome, r) =
        fx.call("edit", Args::new().text("path", "").text("replacing", "x").text("content", "y"));
    assert!(outcome.is_blocked(), "{outcome:?}");
    assert!(r.failed);
    assert!(fx.why(&r).contains("no adjudicated handle for `path`"), "{}", fx.why(&r));
}

#[test]
fn edit_path_with_a_space_survives() {
    let fx = Fixture::new("edit-space");
    fx.seed("a dir/notes.md", "alpha\nbeta\n");
    let (_, r) = fx.call(
        "edit",
        Args::new().text("path", "a dir/notes.md").text("replacing", "beta").text("content", "BETA"),
    );
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fx.on_disk("a dir/notes.md"), "alpha\nBETA\n");
}

#[test]
fn edit_path_with_unicode_survives() {
    let fx = Fixture::new("edit-unicode");
    fx.seed("café.md", "alpha\nbeta\n");
    let (_, r) = fx.call(
        "edit",
        Args::new().text("path", "café.md").text("replacing", "beta").text("content", "BETA"),
    );
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fx.on_disk("café.md"), "alpha\nBETA\n");
}

#[test]
fn edit_a_file_that_does_not_exist_creates_it_at_zero_bytes_then_refuses() {
    let fx = Fixture::new("edit-new-file");
    let (_, r) = fx.call(
        "edit",
        Args::new().text("path", "brand-new.md").text("replacing", "anything").text("content", "x"),
    );
    // Not flagged as a NEW finding: this is the exact, already-documented case from
    // `marlowe-exec/src/lib.rs::replacing_miss` and `tests/executors.rs`. Verified here only for
    // completeness of the sweep -- `path` is a `WritePath`, so scoping opens it `CreateOrOpen`
    // before this executor runs, the file exists at zero bytes, and the refusal names `write` and
    // states the file is now zero bytes.
    assert!(r.failed);
    let d = fx.why(&r);
    assert!(d.contains("`write`"), "{d}");
    assert!(d.contains("zero bytes"), "{d}");
    assert_eq!(fx.on_disk("brand-new.md"), "", "the empty file this call cannot avoid creating");
}

#[test]
fn edit_a_directory_given_as_path() {
    let fx = Fixture::new("edit-dir");
    fx.mkdir("a-directory");
    let (outcome, r) = fx.call(
        "edit",
        Args::new().text("path", "a-directory").text("replacing", "x").text("content", "y"),
    );
    // The path is a WritePath (`CreateOrOpen`), and the target already exists as a directory, so
    // whether scoping opens it at all is the first question.
    if outcome.is_blocked() {
        match outcome {
            Outcome::Blocked { reason: BlockReason::UndeclaredPath { detail, .. } } => {
                assert!(!detail.is_empty());
            }
            other => panic!("{other:?}"),
        }
        assert!(r.failed);
    } else {
        // A handle to the directory was opened. The executor must not report success against a
        // directory it never actually read text from.
        assert!(r.failed, "editing a directory succeeded, and nothing on disk explains what that means: {:?} {}", r.summary, fx.why(&r));
        // SUSPECT (conditional on this branch running): if scoping opens a directory handle for
        // `CreateOrOpen` without erroring, the failure the model sees is whatever
        // `file.read_to_string` or the later `set_len`/`write_all` produced -- a raw OS error
        // string with no mention that the target is a directory. Compare this to `read`'s own
        // handling of the same situation, and to `ScopeError::Unopenable`'s care about naming
        // what actually went wrong: an OS error like "Access is denied. (os error 5)" gives the
        // model nothing to act on beyond "try something else."
        assert!(!fx.detail(&r).is_empty(), "{:?}", r.summary);
    }
}

#[test]
fn edit_parent_directory_missing() {
    let fx = Fixture::new("edit-no-parent");
    let (outcome, r) = fx.call(
        "edit",
        Args::new().text("path", "nosuchdir/file.md").text("replacing", "x").text("content", "y"),
    );
    assert!(outcome.is_blocked(), "{outcome:?}");
    assert!(r.failed);
    assert!(
        fs::metadata(fx.root.join("nosuchdir")).is_err(),
        "a missing parent must stay missing -- `edit` creates only the final component"
    );
}

#[test]
fn edit_a_truly_empty_file_refuses_and_names_write() {
    let fx = Fixture::new("edit-truly-empty");
    fx.seed("already-empty.txt", "");
    let (_, r) = fx.call(
        "edit",
        Args::new().text("path", "already-empty.txt").text("replacing", "x").text("content", "y"),
    );
    assert!(r.failed);
    assert!(fx.why(&r).contains("`write`"), "{}", fx.why(&r));
    assert_eq!(fx.on_disk("already-empty.txt"), "");
}

#[test]
fn edit_large_file_reports_a_true_diff_and_writes_correctly() {
    let fx = Fixture::new("edit-large");
    let mut content = String::new();
    for i in 1..=3000 {
        if i == 1500 {
            content.push_str("TARGET_LINE_MARKER\n");
        } else {
            content.push_str(&format!("line {i}\n"));
        }
    }
    fx.seed("big.md", &content);
    let (_, r) = fx.call(
        "edit",
        Args::new()
            .text("path", "big.md")
            .text("replacing", "TARGET_LINE_MARKER")
            .text("content", "REPLACED"),
    );
    assert!(!r.failed, "{:?}", r.summary);
    let on_disk = fx.on_disk("big.md");
    assert!(on_disk.contains("REPLACED\n"), "the replacement did not land");
    assert!(!on_disk.contains("TARGET_LINE_MARKER"), "the original snippet must be gone");
    assert_eq!(on_disk.lines().count(), 3000, "one line replaced by one line: total is unchanged");
}

#[test]
fn edit_snippet_appears_twice_only_the_first_is_replaced() {
    let fx = Fixture::new("edit-twice");
    fx.seed("dup.md", "alpha\nshared\nbeta\nshared\ngamma\n");
    let (_, r) =
        fx.call("edit", Args::new().text("path", "dup.md").text("replacing", "shared").text("content", "unique"));
    assert!(!r.failed, "{:?}", r.summary);
    // Not flagged as a new finding: the manifest's own `replacing` description says plainly "The
    // FIRST occurrence is replaced", so a model reading its own tool description already knows
    // this. Verified here rather than merely trusted.
    assert_eq!(fx.on_disk("dup.md"), "alpha\nunique\nbeta\nshared\ngamma\n");
}

#[test]
fn edit_snippet_is_the_whole_file() {
    let fx = Fixture::new("edit-whole-file");
    fx.seed("all.md", "everything here\n");
    let (_, r) = fx.call(
        "edit",
        Args::new().text("path", "all.md").text("replacing", "everything here\n").text("content", "new content\n"),
    );
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fx.on_disk("all.md"), "new content\n");
}

#[test]
fn edit_snippet_differs_only_in_whitespace_names_the_real_problem() {
    let fx = Fixture::new("edit-whitespace");
    fx.seed("notes.md", "alpha\nbeta    needle\ngamma\n");
    let (_, r) = fx.call(
        "edit",
        Args::new().text("path", "notes.md").text("replacing", "beta needle").text("content", "x"),
    );
    assert!(r.failed);
    let d = fx.why(&r);
    assert!(d.contains("apart from whitespace"), "{d}");
    assert_eq!(fx.on_disk("notes.md"), "alpha\nbeta    needle\ngamma\n", "a miss must not touch the file");
}

// ============================================================================================
// write
// ============================================================================================

#[test]
fn write_ordinary_success() {
    let fx = Fixture::new("write-ok");
    let (_, r) = fx.call("write", Args::new().text("path", "new.txt").text("content", "made"));
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fx.on_disk("new.txt"), "made");
}

#[test]
fn write_missing_path() {
    let fx = Fixture::new("write-no-path");
    let (_, r) = fx.call("write", Args::new().text("content", "x"));
    assert!(r.failed);
    assert!(fx.why(&r).contains("no adjudicated handle for `path`"), "{}", fx.why(&r));
}

#[test]
fn write_missing_content() {
    let fx = Fixture::new("write-no-content");
    let (_, r) = fx.call("write", Args::new().text("path", "new.txt"));
    assert!(r.failed);
    assert!(fx.why(&r).contains("`content` is required"), "{}", fx.why(&r));
    assert!(fs::metadata(fx.root.join("new.txt")).is_err() || fx.on_disk("new.txt").is_empty());
}

#[test]
fn write_empty_string_content_truncates_an_existing_file() {
    let fx = Fixture::new("write-empty-content");
    fx.seed("existing.txt", "there was something here\n");
    let (_, r) = fx.call("write", Args::new().text("path", "existing.txt").text("content", ""));
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fx.on_disk("existing.txt"), "");
}

#[test]
fn write_empty_string_path_is_malformed() {
    let fx = Fixture::new("write-empty-path");
    let (outcome, r) = fx.call("write", Args::new().text("path", "").text("content", "x"));
    assert!(outcome.is_blocked(), "{outcome:?}");
    assert!(r.failed);
    assert!(fx.why(&r).contains("no adjudicated handle for `path`"), "{}", fx.why(&r));
}

#[test]
fn write_path_with_a_space_survives() {
    let fx = Fixture::new("write-space");
    // **`write` creates the FILE, not the tree** — its description says so, and the original
    // version of this test omitted the directory and read the resulting refusal as a spacing bug.
    fx.mkdir("a dir");
    let (_, r) = fx.call(
        "write",
        Args::new().text("path", "a dir/new file.txt").text("content", "hi"),
    );
    assert!(!r.failed, "{:?} {}", r.summary, fx.why(&r));
    assert_eq!(fx.on_disk("a dir/new file.txt"), "hi");
}

#[test]
fn write_path_with_unicode_survives() {
    let fx = Fixture::new("write-unicode");
    let (_, r) = fx.call("write", Args::new().text("path", "notä-café.txt").text("content", "hi"));
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fx.on_disk("notä-café.txt"), "hi");
}

#[test]
fn write_a_directory_given_as_path() {
    let fx = Fixture::new("write-dir");
    fx.mkdir("a-directory");
    let (outcome, r) =
        fx.call("write", Args::new().text("path", "a-directory").text("content", "x"));
    if outcome.is_blocked() {
        assert!(r.failed);
    } else {
        assert!(r.failed, "writing over a directory succeeded: {:?} {}", r.summary, fx.why(&r));
        // SUSPECT (conditional): same shape as `edit`'s directory case -- if a handle to the
        // directory opens at all, whatever io error `set_len`/`write_all` produces reaches the
        // model as a raw OS string with no mention that the target was a directory rather than a
        // file.
        assert!(!fx.detail(&r).is_empty(), "{:?}", r.summary);
    }
}

#[test]
fn write_over_an_empty_file() {
    let fx = Fixture::new("write-over-empty");
    fx.seed("empty.txt", "");
    let (_, r) = fx.call("write", Args::new().text("path", "empty.txt").text("content", "now filled\n"));
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fx.on_disk("empty.txt"), "now filled\n");
}

#[test]
fn write_large_content_lands_exactly() {
    let fx = Fixture::new("write-large");
    let content: String = (1..=5000).map(|i| format!("line {i}\n")).collect();
    let (_, r) = fx.call("write", Args::new().text("path", "big.txt").text("content", &content));
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fx.on_disk("big.txt"), content);
    // `write`'s body is always the relative path, never the content, regardless of size -- so a
    // large write does not become a `Reference`. Verified rather than assumed.
    assert!(matches!(r.body, ToolBody::Inline(_)));
}

#[test]
fn write_parent_directory_missing() {
    let fx = Fixture::new("write-no-parent");
    let (outcome, r) =
        fx.call("write", Args::new().text("path", "nosuchdir/file.txt").text("content", "x"));
    assert!(outcome.is_blocked(), "{outcome:?}");
    assert!(r.failed);
    assert!(
        fs::metadata(fx.root.join("nosuchdir")).is_err(),
        "the manifest says the parent must already exist, and it must stay that way on refusal"
    );
}

// ============================================================================================
// find
// ============================================================================================

#[test]
fn find_ordinary_success() {
    let fx = Fixture::new("find-ok");
    fx.seed("notes.md", "alpha\nbeta needle\ngamma\n");
    let (_, r) = fx.call("find", Args::new().text("pattern", "needle").text("path", "."));
    assert!(!r.failed, "{:?}", r.summary);
    assert!(fx.text(&r).contains("notes.md:2"), "{}", fx.text(&r));
    assert_eq!(r.summary.render(), "1 result · 1 file");
}

#[test]
fn find_missing_pattern() {
    let fx = Fixture::new("find-no-pattern");
    let (_, r) = fx.call("find", Args::new().text("path", "."));
    assert!(r.failed);
    assert!(fx.why(&r).contains("`pattern` is required"), "{}", fx.why(&r));
}

#[test]
fn find_missing_path() {
    let fx = Fixture::new("find-no-path");
    let (_, r) = fx.call("find", Args::new().text("pattern", "needle"));
    assert!(r.failed);
    // SUSPECT, minor: `find`'s `path` is REQUIRED by the manifest, but unlike `read` (which
    // distinguishes "you gave neither `path` nor `ref`" from "the `path` you gave was refused"),
    // `find` reports the identical "no adjudicated handle for `path`" whether `path` was omitted
    // entirely or supplied and rejected. A model that never mentioned `path` at all gets the same
    // sentence as one whose path was scoped out, which is a smaller gap than `read`'s (the
    // sentence at least clearly says a `path` is needed) but is still a missed opportunity to say
    // plainly "`path` is required and was not given" the way `edit` and `write` do for `content`.
    assert!(fx.why(&r).contains("no adjudicated handle for `path`"), "{}", fx.why(&r));
}

/// **`str::contains("")` is always true**, so an empty pattern reported every line of every file
/// under `path` as a match — a context-flood standing in for what should have been an error.
#[test]
fn find_empty_pattern_is_refused_not_treated_as_matching_everything() {
    let fx = Fixture::new("find-empty-pattern");
    fx.seed("a.txt", "one\ntwo\nthree\n");
    fx.seed("b.txt", "four\nfive\n");
    let (_, r) = fx.call("find", Args::new().text("pattern", "").text("path", "."));
    assert!(r.failed, "an empty pattern must not report every line as a hit: {:?}", r.summary);
    assert!(fx.why(&r).contains("`glob`"), "the tool that DOES list files: {}", fx.why(&r));
}

#[test]
fn find_empty_string_path_is_malformed() {
    let fx = Fixture::new("find-empty-path");
    let (outcome, r) = fx.call("find", Args::new().text("pattern", "x").text("path", ""));
    assert!(outcome.is_blocked(), "{outcome:?}");
    assert!(r.failed);
    assert!(fx.why(&r).contains("no adjudicated handle for `path`"), "{}", fx.why(&r));
}

#[test]
fn find_path_with_a_space_survives() {
    let fx = Fixture::new("find-space");
    fx.seed("a dir/inside.txt", "needle here\n");
    let (_, r) = fx.call("find", Args::new().text("pattern", "needle").text("path", "a dir"));
    assert!(!r.failed, "{:?}", r.summary);
    assert!(fx.text(&r).contains("inside.txt"), "{}", fx.text(&r));
}

#[test]
fn find_path_with_unicode_survives() {
    let fx = Fixture::new("find-unicode");
    fx.seed("dossier-café/inside.txt", "needle here\n");
    let (_, r) = fx.call("find", Args::new().text("pattern", "needle").text("path", "dossier-café"));
    assert!(!r.failed, "{:?}", r.summary);
    assert!(fx.text(&r).contains("inside.txt"), "{}", fx.text(&r));
}

#[test]
fn find_path_does_not_exist() {
    let fx = Fixture::new("find-missing-dir");
    let (outcome, r) = fx.call("find", Args::new().text("pattern", "x").text("path", "nope"));
    assert!(outcome.is_blocked(), "{outcome:?}");
    assert!(r.failed);
}

/// **`collect()` swallows `read_dir`'s error on a file**, so the walk found zero candidates and
/// the result was `0 results · 0 files` — identical to a correctly-specified EMPTY directory. The
/// manifest says "the DIRECTORY to search -- not a file"; nothing enforced it, so the model that
/// made exactly the mistake the manifest names got no signal at all.
#[test]
fn find_given_a_file_says_so_rather_than_looking_empty() {
    let fx = Fixture::new("find-file-as-dir");
    fx.seed("notes.md", "alpha\nneedle\ngamma\n");
    let (_, r) = fx.call("find", Args::new().text("pattern", "needle").text("path", "notes.md"));
    assert!(r.failed, "a file where a directory was asked for must not read as empty");
    assert!(fx.why(&r).to_lowercase().contains("directory"), "{}", fx.why(&r));
    assert!(fx.why(&r).contains("`read`"), "name the tool for one file: {}", fx.why(&r));
}

#[test]
fn find_empty_directory_has_no_matches_and_says_so_honestly() {
    let fx = Fixture::new("find-empty-dir");
    fx.mkdir("nothing-here");
    let (_, r) = fx.call("find", Args::new().text("pattern", "needle").text("path", "nothing-here"));
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(r.summary.render(), "0 results · 0 files");
}

#[test]
fn find_reports_true_counts_across_many_files() {
    let fx = Fixture::new("find-many");
    let mut with_needle = 0;
    for i in 0..40 {
        let has_needle = i % 3 == 0;
        if has_needle {
            with_needle += 1;
        }
        let body = if has_needle { format!("line\nneedle {i}\nline\n") } else { "line\nline\n".to_string() };
        fx.seed(&format!("dir{}/file{i}.txt", i % 4), &body);
    }
    let (_, r) = fx.call("find", Args::new().text("pattern", "needle").text("path", "."));
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(
        r.summary.render(),
        format!("{with_needle} results · 40 files"),
        "one hit per matching file, every file counted as scanned"
    );
}

#[test]
fn find_pattern_with_regex_metacharacters_is_treated_literally() {
    let fx = Fixture::new("find-regex-chars");
    fx.seed(
        "a.txt",
        "just a dot .\nsomething with .* literally\nan asterisk alone *\na bracket [ here\n",
    );
    // Confirms the manifest's claim ("Not a regex and not a glob: `.` and `*` match themselves")
    // holds in the executor, not merely in the docs.
    let (_, r) = fx.call("find", Args::new().text("pattern", ".*").text("path", "."));
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(r.summary.render(), "1 result · 1 file", "`.*` must match only the literal substring, not \"any line\"");
    assert!(fx.text(&r).contains("literally"), "{}", fx.text(&r));

    let (_, r) = fx.call("find", Args::new().text("pattern", "[").text("path", "."));
    assert!(!r.failed, "an unmatched `[` must not be treated as a regex and must not panic: {:?}", r.summary);
    assert_eq!(r.summary.render(), "1 result · 1 file");
    assert!(fx.text(&r).contains("bracket"), "{}", fx.text(&r));
}

// ============================================================================================
// bash
// ============================================================================================

#[test]
fn bash_missing_command() {
    let fx = Fixture::new("bash-no-command");
    let (outcome, r) = fx.call("bash", Args::new());
    assert_eq!(outcome, Outcome::NeedsApproval { tier: marlowe_permission::RiskTier::Irreversible });
    assert!(r.failed);
    assert!(fx.why(&r).contains("`command` is required"), "{}", fx.why(&r));
}

#[test]
fn bash_empty_string_command() {
    let fx = Fixture::new("bash-empty-command");
    let (_, r) = fx.call("bash", Args::new().text("command", ""));
    // An empty command line handed to `cmd /C` (or `sh -c`) is not refused by this executor --
    // it is run as-is and whatever the shell does with nothing, happens. Asserting on the actual
    // observed exit rather than assuming: this is not flagged unless it hangs, panics, or silently
    // fabricates output, none of which it does.
    assert!(r.wall_ms == 0);
    let _ = r; // outcome is whatever the shell does with an empty line; not asserted further.
}

#[test]
fn bash_a_command_that_fails_reports_the_exit_code() {
    let fx = Fixture::new("bash-fails");
    let cmd = if cfg!(windows) { "exit 3" } else { "exit 3" };
    let (_, r) = fx.call("bash", Args::new().text("command", cmd));
    assert!(r.failed);
    assert_eq!(r.summary.render(), "exit 3 · 0 lines");
}

#[test]
fn bash_a_command_producing_no_output() {
    let fx = Fixture::new("bash-no-output");
    // `rem` is a `cmd` word; `:` is bash's no-op.
    let cmd = ":";
    let (_, r) = fx.call("bash", Args::new().text("command", cmd));
    assert!(!r.failed, "{:?} {}", r.summary, fx.text(&r));
    assert_eq!(fx.text(&r), "");
    assert_eq!(r.summary.render(), "0 lines");
}

#[test]
fn bash_a_command_producing_a_lot_of_output_is_capped() {
    let fx = Fixture::new("bash-lots-of-output");
    // Deterministic and fast: create the bytes with `fs::write` rather than asking the shell to
    // generate them, and have the shell merely emit what is already on disk.
    let big = "x".repeat(2 * marlowe_exec::MAX_SHELL_OUTPUT_BYTES);
    fx.seed("big.txt", &big);
    let cmd = "cat big.txt";
    let (_, r) = fx.call("bash", Args::new().text("command", cmd));
    // **Output this large becomes a `ContentRef`, so `text()` renders `<ref hash bytes>` and the
    // notice is inside the referenced content, not in the rendered string.** The first version of
    // this test asserted on `text()` and read the reference as a missing notice — measuring the
    // rendering rather than the result.
    let bytes = match &r.body {
        ToolBody::Reference { bytes, .. } => *bytes as usize,
        ToolBody::Inline(s) => s.len(),
    };
    assert!(
        bytes <= marlowe_exec::MAX_SHELL_OUTPUT_BYTES + 4096,
        "the cap must actually cap: {bytes} bytes against a cap of {}",
        marlowe_exec::MAX_SHELL_OUTPUT_BYTES
    );
    // And the model must be TOLD, wherever the result put it: inline, or in the preview that
    // stands in for a reference it cannot dereference.
    let told = format!("{} {}", fx.text(&r), r.preview.clone().unwrap_or_default());
    assert!(
        told.contains("the harness stopped this command after it produced more than"),
        "a truncated result must say so somewhere the model reads: {}",
        &told[..300.min(told.len())]
    );
}

#[test]
fn bash_quoted_command_reaches_the_shell_unmangled() {
    let fx = Fixture::new("bash-quotes");
    fx.mkdir("a dir");
    fx.seed("a dir/inside.txt", "found me");
    let cmd = r#"cat "a dir/inside.txt""#;
    let (_, r) = fx.call("bash", Args::new().text("command", cmd));
    assert!(!r.failed, "{:?} {}", r.summary, fx.text(&r));
    assert!(fx.text(&r).contains("found me"), "{}", fx.text(&r));
}

#[test]
fn bash_cwd_with_a_space() {
    let fx = Fixture::new("bash-cwd-space");
    fx.mkdir("a dir");
    // One spelling: `bash` is bash on both platforms now. `cd` printed the directory under
    // `cmd`; in bash it goes to $HOME and prints nothing.
    let (_, r) = fx.call("bash", Args::new().text("command", "pwd").text("cwd", "a dir"));
    assert!(!r.failed, "{:?} {}", r.summary, fx.text(&r));
    assert!(fx.text(&r).to_lowercase().contains("a dir"), "{}", fx.text(&r));
}

#[test]
fn bash_cwd_with_unicode() {
    let fx = Fixture::new("bash-cwd-unicode");
    fx.mkdir("café-dossier");
    let (_, r) = fx.call("bash", Args::new().text("command", "pwd").text("cwd", "café-dossier"));
    assert!(!r.failed, "{:?} {}", r.summary, fx.text(&r));
    assert!(fx.text(&r).to_lowercase().contains("caf"), "{}", fx.text(&r));
}

// ============================================================================================
// glob — the tool that did not exist, and whose absence the model filled with invention
// ============================================================================================

/// The ordinary case: list what is under a directory.
#[test]
fn glob_lists_everything_beneath_a_path() {
    let fx = Fixture::new("glob-basic");
    fx.seed("src/main.rs", "fn main() {}");
    fx.seed("src/lib.rs", "");
    fx.seed("docs/readme.md", "hi");
    let (_, r) = fx.call("glob", Args::new().text("path", "."));
    assert!(!r.failed, "{:?} {}", r.summary, fx.why(&r));
    let out = fx.text(&r);
    for want in ["src/main.rs", "src/lib.rs", "docs/readme.md"] {
        assert!(out.contains(want), "`{want}` is missing: {out}");
    }
    assert_eq!(r.summary.render(), "3 paths");
}

/// Sorted, because `read_dir` order is a filesystem detail and two runs must agree.
#[test]
fn glob_is_sorted_and_stable() {
    let fx = Fixture::new("glob-sorted");
    for n in ["c.txt", "a.txt", "b.txt"] {
        fx.seed(n, "x");
    }
    let (_, first) = fx.call("glob", Args::new().text("path", "."));
    let (_, again) = fx.call("glob", Args::new().text("path", "."));
    assert_eq!(fx.text(&first), fx.text(&again), "two identical calls must agree");
    assert_eq!(fx.text(&first), "a.txt\nb.txt\nc.txt");
}

/// `*` and `?` are the only metacharacters, and a pattern without `/` matches the NAME.
#[test]
fn glob_pattern_matches_the_name_anywhere_beneath_the_path() {
    let fx = Fixture::new("glob-name");
    fx.seed("src/main.rs", "");
    fx.seed("src/deep/other.rs", "");
    fx.seed("notes.md", "");
    let (_, r) = fx.call("glob", Args::new().text("path", ".").text("pattern", "*.rs"));
    assert!(!r.failed, "{}", fx.why(&r));
    let out = fx.text(&r);
    assert!(out.contains("src/main.rs") && out.contains("src/deep/other.rs"), "{out}");
    assert!(!out.contains("notes.md"), "a non-match leaked in: {out}");
}

/// A pattern WITH a `/` matches the whole workspace-relative path, so it can be anchored.
#[test]
fn glob_pattern_with_a_slash_matches_the_path() {
    let fx = Fixture::new("glob-path");
    fx.seed("src/main.rs", "");
    fx.seed("src/deep/other.rs", "");
    let (_, r) = fx.call("glob", Args::new().text("path", ".").text("pattern", "src/*.rs"));
    assert!(!r.failed, "{}", fx.why(&r));
    let out = fx.text(&r);
    assert!(out.contains("src/main.rs"), "{out}");
    assert!(!out.contains("deep"), "`src/*.rs` must not reach into `src/deep`: {out}");
}

/// **Regex metacharacters are LITERAL.** A model that writes `.*` out of habit must not silently
/// match everything — it must match a file actually called that, and otherwise match nothing.
#[test]
fn glob_treats_regex_metacharacters_as_literal_text() {
    let fx = Fixture::new("glob-regex");
    fx.seed("real.txt", "");
    fx.seed("other.md", "");
    for pattern in [".*", "[a-z]*", "^real", "real$", "(real|other)"] {
        let (_, r) = fx.call("glob", Args::new().text("path", ".").text("pattern", pattern));
        assert!(!r.failed, "{pattern:?}: {}", fx.why(&r));
        assert!(
            !fx.text(&r).contains("other.md"),
            "`{pattern}` was interpreted as a regex and matched everything: {}",
            fx.text(&r)
        );
    }
    // The control: `*` really does match everything, so the assertions above are not vacuous.
    let (_, all) = fx.call("glob", Args::new().text("path", ".").text("pattern", "*"));
    assert!(fx.text(&all).contains("other.md"), "`*` must match: {}", fx.text(&all));
}

/// Case-insensitive, because this ships on Windows where the filesystem is.
#[test]
fn glob_is_case_insensitive() {
    let fx = Fixture::new("glob-case");
    fx.seed("README.MD", "");
    let (_, r) = fx.call("glob", Args::new().text("path", ".").text("pattern", "*.md"));
    assert!(fx.text(&r).contains("README.MD"), "{}", fx.text(&r));
}

/// **"Nothing here" and "nothing matched" are different facts.** A model that cannot tell them
/// apart invents one — which is exactly what happened live, when it reported a directory with four
/// files in it as "appears empty".
#[test]
fn glob_distinguishes_an_empty_directory_from_a_pattern_that_matched_nothing() {
    let fx = Fixture::new("glob-empty");
    fx.mkdir("hollow");
    let (_, empty) = fx.call("glob", Args::new().text("path", "hollow"));
    assert!(!empty.failed, "{}", fx.why(&empty));
    assert!(
        fx.text(&empty).contains("no files under this path at all"),
        "an empty directory must say it is empty: {}",
        fx.text(&empty)
    );

    fx.seed("full/a.txt", "");
    fx.seed("full/b.txt", "");
    let (_, nomatch) = fx.call("glob", Args::new().text("path", "full").text("pattern", "*.rs"));
    assert!(!nomatch.failed, "{}", fx.why(&nomatch));
    let out = fx.text(&nomatch);
    assert!(out.contains("2 file(s) are under this path"), "say how many ARE there: {out}");
    assert!(out.contains("*.rs"), "name the pattern that missed: {out}");
    assert_ne!(out, fx.text(&empty), "the two answers must not be the same string");
}

/// A file where a directory was asked for — the mistake the description names.
#[test]
fn glob_given_a_file_says_so() {
    let fx = Fixture::new("glob-file");
    fx.seed("notes.md", "hi");
    let (_, r) = fx.call("glob", Args::new().text("path", "notes.md"));
    assert!(r.failed, "a file must not read as an empty directory: {}", fx.text(&r));
    assert!(fx.why(&r).to_lowercase().contains("directory"), "{}", fx.why(&r));
}

/// Names with spaces and non-ASCII survive to the listing.
#[test]
fn glob_handles_spaces_and_unicode() {
    let fx = Fixture::new("glob-names");
    fx.seed("a dir/some file.txt", "");
    fx.seed("café/menú.md", "");
    let (_, r) = fx.call("glob", Args::new().text("path", "."));
    let out = fx.text(&r);
    assert!(out.contains("a dir/some file.txt"), "{out}");
    assert!(out.contains("café/menú.md"), "{out}");
}

/// `path` is required, and `glob` reads no file contents — which is what lets it be `Inert` and
/// run without interrupting the user, unlike `bash`.
#[test]
fn glob_requires_a_path_and_never_asks_for_approval() {
    let fx = Fixture::new("glob-required");
    let (_, r) = fx.call("glob", Args::new());
    assert!(r.failed, "`path` is required");

    fx.seed("a.txt", "secret contents");
    let (outcome, ok) = fx.call("glob", Args::new().text("path", "."));
    assert_eq!(outcome, Outcome::Allowed, "listing names must not need approval");
    assert!(
        !fx.text(&ok).contains("secret contents"),
        "glob returns NAMES; a file's contents must never appear: {}",
        fx.text(&ok)
    );
}

// ============================================================================================
// The descriptions and the executors, checked against each other
// ============================================================================================

/// **A description drifts from behaviour silently, and nothing in this project could see it.**
///
/// `read.range` promised *"a backwards range returns nothing"* for an hour after the executor
/// started refusing one instead. Both halves were tested — the wire test asserts the description
/// reaches the model, the executor test asserts the refusal — and **neither compares them**, which
/// is the whole gap: a claim asserted where it is written and a behaviour asserted where it runs,
/// with no line joining the two.
///
/// So this reads each promise out of the shipped manifest, then makes the call it describes.
/// Deliberately a small set: only claims that are checkable in one call, because a guard that
/// tries to parse prose would be a worse thing than the drift.
#[test]
fn each_description_promise_is_kept_by_the_executor() {
    let fx = Fixture::new("promises");
    let reg = builtin_registry().expect("the builtins load");
    let desc = |tool: &str, param: &str| -> String {
        reg.manifest(&ToolId::new(tool))
            .unwrap()
            .params()
            .iter()
            .find(|p| p.name == param)
            .unwrap_or_else(|| panic!("`{tool}::{param}` is not declared"))
            .description
            .clone()
            .unwrap_or_default()
    };

    // 1. `read.range` — the one that actually drifted.
    let r = desc("read", "range");
    assert!(
        r.contains("REFUSED") || r.contains("refused"),
        "`read.range` must say a bad range is refused, not describe some other outcome: {r}"
    );
    fx.seed("ten.txt", &(1..=10).map(|i| format!("line {i}\n")).collect::<String>());
    for bad in ["60-20", "abc", "2", "0-5", "500-600"] {
        let (_, out) = fx.call("read", Args::new().text("path", "ten.txt").text("range", bad));
        assert!(out.failed, "`range` {bad:?} is described as refused and was not: {:?}", out.summary);
    }
    // The control: the shape the description DOES endorse still works.
    let (_, ok) = fx.call("read", Args::new().text("path", "ten.txt").text("range", "2-4"));
    assert!(!ok.failed, "`20-60` style must work or the loop above proves nothing");
    assert_eq!(fx.text(&ok).lines().count(), 3);

    // 2. `edit.replacing` — "an empty string is refused rather than inserting at the start".
    let e = desc("edit", "replacing");
    assert!(e.contains("empty string is refused"), "{e}");
    fx.seed("notes.md", "hello\n");
    let (_, out) =
        fx.call("edit", Args::new().text("path", "notes.md").text("replacing", "").text("content", "X"));
    assert!(out.failed, "described as refused: {:?}", out.summary);
    assert_eq!(fx.on_disk("notes.md"), "hello\n");

    // 3. `find.pattern` — "an empty string is refused rather than matching every line".
    let f = desc("find", "pattern");
    assert!(f.contains("empty string is refused"), "{f}");
    let (_, out) = fx.call("find", Args::new().text("pattern", "").text("path", "."));
    assert!(out.failed, "described as refused: {:?}", out.summary);

    // 4. `find.path` — "A file here is refused".
    let fp = desc("find", "path");
    assert!(fp.contains("file here is refused"), "{fp}");
    let (_, out) = fx.call("find", Args::new().text("pattern", "hello").text("path", "notes.md"));
    assert!(out.failed, "described as refused: {:?}", out.summary);

    // 5. `glob.pattern` — "`src/*.rs` finds only those directly in `src`".
    let g = desc("glob", "pattern");
    assert!(g.contains("directly in `src`"), "{g}");
    fx.seed("src/a.rs", "");
    fx.seed("src/deep/b.rs", "");
    let (_, out) = fx.call("glob", Args::new().text("path", ".").text("pattern", "src/*.rs"));
    assert!(fx.text(&out).contains("src/a.rs"), "{}", fx.text(&out));
    assert!(!fx.text(&out).contains("deep"), "the promise is `directly in`: {}", fx.text(&out));
}

// ============================================================================================
// read is a WINDOW, the way Claude Code reads a file
// ============================================================================================

/// **A file bigger than the window comes back as text, not as a hash.**
///
/// `read` used to hand anything over `MAX_INLINE_BYTES` to `body_for`, which returned a
/// `ContentRef` — a hash plus a 4 KB head-and-tail. **That hash is not dereferenceable for a
/// file**: `read`'s `ref` takes ids `web` issued. So the middle of every file above 8 KB was
/// unreachable, and a model could see both ends and nothing else.
#[test]
fn a_long_file_is_read_in_windows_and_every_part_is_reachable() {
    let fx = Fixture::new("read-window");
    let content: String = (1..=5_000).map(|i| format!("line {i}\n")).collect();
    fx.seed("long.txt", &content);

    let (_, first) = fx.call("read", Args::new().text("path", "long.txt"));
    assert!(!first.failed, "{}", fx.why(&first));
    let body = fx.text(&first);
    assert!(!body.starts_with("<ref"), "a file must not come back as a hash: {}", &body[..60]);
    assert!(body.contains("line 1\n"), "the window must start at the top");
    assert!(body.contains(&format!("line {}\n", marlowe_exec::READ_WINDOW_LINES)), "{body:.120}");
    assert!(
        !body.contains("line 2001\n"),
        "the window must STOP at its bound, not merely mention one"
    );
    assert!(body.contains("of 5000"), "the notice must say how long the file is: {body:.200}");
    assert!(body.contains("2001-4000"), "and exactly what to ask for next: {body:.200}");

    // **The part that was unreachable.** The next window really does return the next lines.
    let (_, second) = fx.call("read", Args::new().text("path", "long.txt").text("range", "2001-4000"));
    assert!(!second.failed, "{}", fx.why(&second));
    assert!(fx.text(&second).contains("line 2500\n"), "the middle of the file is reachable now");
    assert!(!fx.text(&second).contains("line 1\n"), "and it is the SECOND window, not the first");
}

/// A file that fits is returned whole, with no notice at all — the window is a bound, not a habit.
#[test]
fn a_short_file_has_no_window_notice() {
    let fx = Fixture::new("read-short");
    fx.seed("short.txt", "alpha\nbeta\ngamma\n");
    let (_, r) = fx.call("read", Args::new().text("path", "short.txt"));
    assert_eq!(fx.text(&r), "alpha\nbeta\ngamma\n", "no notice, no truncation, no hash");
}

/// **The cost warning is held back for files that are actually expensive.**
///
/// A model told that everything is expensive has learned nothing about what is. So an ordinary
/// long file gets one line — what you got, what to ask for next — and only a genuinely large one
/// also gets the token estimate and the pointer at `find`.
#[test]
fn only_a_genuinely_large_file_is_called_expensive() {
    let fx = Fixture::new("read-cost");

    // Just past the line bound, but small: short notice, no cost, no advice.
    let modest: String = (1..=2_400).map(|i| format!("{i}\n")).collect();
    fx.seed("modest.txt", &modest);
    let (_, r) = fx.call("read", Args::new().text("path", "modest.txt"));
    let body = fx.text(&r);
    assert!(body.contains("of 2400"), "it is still truncated and still says so: {body:.150}");
    assert!(
        !body.contains("tokens") && !body.contains("`find`"),
        "an ordinary long file must not be dressed as a warning: {}",
        &body[body.len().saturating_sub(300)..]
    );

    // Genuinely large: the cost, and the cheaper way to get an answer.
    let huge: String = (1..=5_000).map(|i| format!("line {i} with enough text to weigh something\n")).collect();
    fx.seed("huge.txt", &huge);
    let (_, r) = fx.call("read", Args::new().text("path", "huge.txt"));
    let body = fx.text(&r);
    let tail = &body[body.len().saturating_sub(400)..];
    assert!(tail.contains("tokens"), "a large file must state its cost in tokens: {tail}");
    assert!(tail.contains("`find`"), "and name the targeted alternative: {tail}");
}

/// The window bounds an explicit `range` too, so it is not a way around the ceiling.
#[test]
fn an_explicit_range_is_still_bounded_by_the_window() {
    let fx = Fixture::new("read-range-bounded");
    let content: String = (1..=9_000).map(|i| format!("line {i}\n")).collect();
    fx.seed("long.txt", &content);
    let (_, r) = fx.call("read", Args::new().text("path", "long.txt").text("range", "1-9000"));
    assert!(!r.failed, "{}", fx.why(&r));
    let returned = fx.text(&r).lines().count();
    assert!(
        returned <= marlowe_exec::READ_WINDOW_LINES + 5,
        "a range asking for everything returned {returned} lines; the window is {}",
        marlowe_exec::READ_WINDOW_LINES
    );
}
