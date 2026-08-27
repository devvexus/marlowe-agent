//! The four executors, driven through a **real adjudication** rather than a hand-built handle.
//!
//! That matters: the thing under test is not "can this code read a file" but "does the executor
//! use the handle the permission layer opened, and only that handle". A test that constructed a
//! `ScopedPath` itself would be testing the reading and not the wall — and it could not, because
//! `ScopedPath` has no constructor from a string.

use std::fs;
use std::path::PathBuf;

use marlowe_contract::TrustClass;
use marlowe_exec::FileSystemTools;
use marlowe_loop::{ToolBody, ToolHost};
use marlowe_permission::scope::WorkspaceScope;
use marlowe_permission::{
    Adjudication, Adjudicator, Args, EgressPolicy, Outcome, Request, TaintSet, Tier,
};
use marlowe_tools::{builtin_registry, ExposedSet, ToolId, ToolRegistry, BUILTIN_TOOLS};

static SEQ: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

struct Fixture {
    root: PathBuf,
    registry: ToolRegistry,
}

impl Fixture {
    fn new(name: &str) -> Self {
        let n = SEQ.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!("marlowe-exec-{name}-{}-{n}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("src")).unwrap();
        fs::write(root.join("src").join("main.rs"), "fn main() {\n    println!(\"hi\");\n}\n").unwrap();
        fs::write(root.join("notes.md"), "alpha\nbeta needle\ngamma\n").unwrap();
        Self { root, registry: builtin_registry().unwrap() }
    }

    /// Adjudicate for real, then hand the result to the executor. Everything a tool touches
    /// therefore came through the wall.
    fn call(&self, tool: &str, args: Args) -> (Outcome, marlowe_loop::ToolOutcome) {
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

    fn text(&self, r: &marlowe_loop::ToolOutcome) -> String {
        match &r.body {
            ToolBody::Inline(s) => s.clone(),
            ToolBody::Reference { hash, bytes } => format!("<ref {hash} {bytes}>"),
        }
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn read_returns_the_file_through_the_adjudicated_handle() {
    let fx = Fixture::new("read");
    let (_, r) = fx.call("read", Args::new().text("path", "src/main.rs"));
    assert!(!r.failed, "{:?}", r.summary);
    assert!(fx.text(&r).contains("println!"));
    assert_eq!(r.summary.render(), "3 lines · 34 B");
}

#[test]
fn edit_writes_through_the_handle_and_can_create() {
    let fx = Fixture::new("edit");

    // Replace inside an existing file.
    let (_, r) = fx.call(
        "edit",
        Args::new().text("path", "notes.md").text("replacing", "beta needle").text("content", "beta found"),
    );
    assert!(!r.failed, "{:?}", r.summary);
    assert_eq!(fs::read_to_string(fx.root.join("notes.md")).unwrap(), "alpha\nbeta found\ngamma\n");

    // Create a file that did not exist — the WritePath half.
    let (_, r) = fx.call("edit", Args::new().text("path", "out/new.txt").text("content", "made"));
    // The parent must exist; `edit` creates the file, not the tree.
    if r.failed {
        fs::create_dir_all(fx.root.join("out")).unwrap();
        let (_, r) = fx.call("edit", Args::new().text("path", "out/new.txt").text("content", "made"));
        assert!(!r.failed, "{:?}", r.summary);
    }
    assert_eq!(fs::read_to_string(fx.root.join("out").join("new.txt")).unwrap(), "made");
}

#[test]
fn find_reports_matches_and_how_many_files_it_actually_read() {
    let fx = Fixture::new("find");
    let (_, r) = fx.call("find", Args::new().text("pattern", "needle").text("path", "."));
    assert!(!r.failed, "{:?}", r.summary);
    assert!(fx.text(&r).contains("notes.md:2"), "{}", fx.text(&r));
    // The second metric is the honest one: how many files were opened THROUGH THE SCOPE. A
    // search that reported matches without reporting its denominator would hide a wall that
    // silently refused everything.
    assert!(r.summary.render().contains("files"), "{}", r.summary.render());
}

#[test]
fn bash_runs_in_the_verified_directory() {
    let fx = Fixture::new("bash");
    let cmd = if cfg!(windows) { "cd" } else { "pwd" };
    let (outcome, r) = fx.call("bash", Args::new().text("command", cmd).text("cwd", "src"));

    // ADR-026: `bash` escalates unconditionally, at EVERY tier including Silent. Asserted here
    // rather than assumed — this test drives the executor as though the approval had been
    // granted, and without this line it would look like `bash` runs unattended.
    assert_eq!(
        outcome,
        Outcome::NeedsApproval { tier: marlowe_permission::RiskTier::Irreversible },
        "bash must ask at every tier"
    );
    assert!(!r.failed, "{:?} {}", r.summary, fx.text(&r));
    assert!(
        fx.text(&r).to_lowercase().contains("src"),
        "the child did not start in the verified directory: {}",
        fx.text(&r)
    );
}

#[test]
fn an_escape_never_reaches_an_executor_at_all() {
    // The integration assertion: a refused call produces no handle, so the executor has nothing
    // to work with and says so. The refusal happens in the permission layer, not in the tool.
    let fx = Fixture::new("escape");
    let (outcome, r) = fx.call("read", Args::new().text("path", "../../../etc/passwd"));
    assert!(outcome.is_blocked(), "{outcome:?}");
    assert!(r.failed);
    assert!(
        r.summary.detail.as_deref().unwrap_or("").contains("no adjudicated handle"),
        "{:?}",
        r.summary
    );
}

/// **The loop a model could not escape: `edit` creates the file, then refuses to write it.**
///
/// `path` is a `WritePath`, so path scoping opens it `CreateOrOpen` before the executor runs. A
/// model writing a NEW file and supplying `replacing` therefore searched an empty string and was
/// told *"`replacing` was not found in the file"* — a true sentence about a situation that did not
/// exist, since the file it named had been created by that same call.
///
/// Watched live 2026-08-26, journal seq 4813-4859: `edit`, refusal, `read` (`0 lines · 0 B`, which
/// an empty file and a missing one both produce), `edit` again, `read`, `read`, then `bash` to run
/// `dir`. **Six calls, three minutes, and a zero-byte file left on disk.**
///
/// Each branch is asserted separately, because one message covering all three is what the old one
/// was.
#[test]
fn a_failed_replace_says_which_of_the_three_things_went_wrong() {
    let fx = Fixture::new("edit-miss");

    // 1. A NEW file. This is the live case.
    let (_, r) = fx.call(
        "edit",
        Args::new()
            .text("path", "brand-new.md")
            .text("replacing", "anything at all")
            .text("content", "hello"),
    );
    assert!(r.failed);
    let d = r.summary.detail.clone().unwrap_or_default();
    assert!(
        d.contains("empty") && d.contains("CREATES"),
        "a model writing a new file must be told the file is empty BECAUSE `edit` made it, and \
         that omitting `replacing` is the fix: {d:?}"
    );
    assert!(
        d.contains("NO `replacing`"),
        "the remedy has to be named, not implied: {d:?}"
    );
    // The side effect, which nothing can undo and which the next `read` will otherwise present
    // as a second unrelated mystery.
    assert!(
        d.contains("ZERO BYTES"),
        "the call left a zero-byte file on disk and did not say so, so `0 lines` from a later          `read` looks like a new problem: {d:?}"
    );

    // 2. A whitespace-only mismatch — the commonest miss in a real file, and the one where a
    //    generic message sends the model round the same loop.
    let (_, r) = fx.call(
        "edit",
        Args::new()
            .text("path", "src/main.rs")
            .text("replacing", "println!(\"hi\");")
            .text("content", "println!(\"bye\");"),
    );
    assert!(!r.failed, "that snippet IS in the file verbatim, so this must succeed: {:?}", r.summary);

    let (_, r) = fx.call(
        "edit",
        Args::new()
            .text("path", "notes.md")
            // `notes.md` is "alpha\nbeta needle\ngamma\n" — same words, wrong spacing.
            .text("replacing", "beta    needle")
            .text("content", "x"),
    );
    assert!(r.failed);
    let d = r.summary.detail.clone().unwrap_or_default();
    assert!(
        d.contains("apart from whitespace"),
        "the file contains that text apart from spacing, and saying so turns an unbounded retry \
         into one corrected call: {d:?}"
    );

    // 3. Genuinely absent, in a file with content. The message must carry the file's size, or
    //    the model cannot tell "wrong file" from "wrong snippet".
    let (_, r) = fx.call(
        "edit",
        Args::new().text("path", "notes.md").text("replacing", "no such text").text("content", "x"),
    );
    assert!(r.failed);
    let d = r.summary.detail.clone().unwrap_or_default();
    assert!(
        d.contains("bytes") && d.contains("lines"),
        "a miss in a non-empty file must state what the file actually is: {d:?}"
    );
    assert!(
        !d.contains("apart from whitespace"),
        "**THE CONTROL.** If the whitespace branch fired here it fires on everything, and \
         branch 2 proves nothing: {d:?}"
    );
}
