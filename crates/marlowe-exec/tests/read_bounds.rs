//! **`read` cannot be made to panic or to exhaust memory by its arguments.** Findings A7 and A8.
//!
//! A7 is the one that matters most, and it is worth stating why a line-range arithmetic bug is a
//! security finding rather than a tidiness one.
//!
//! `range` is a declared **Payload**. §9 says untrusted content may shape a payload freely, so
//! injected prose can choose this value *directly*, with no permission check anywhere in the way —
//! it is the one argument on `read` that is designed to be attacker-choosable. The old expression
//! `take(b.saturating_sub(a) + 1)` overflowed: a panic in debug and test, a silent wrap to
//! `take(0)` in release.
//!
//! **The audit named `"1-18446744073709551615"` and that particular literal does not overflow.**
//! With `a = 1` the subtraction saturates to `usize::MAX - 1` and the `+ 1` fits. It needs
//! `a = 0` — `"0-18446744073709551615"` — for `b - a` to be `usize::MAX` exactly. The finding is
//! real and the exploit value was off by one, which is only visible by running the mutation:
//! reverting the fix leaves `the_range_that_overflowed_returns_a_result` GREEN and fails
//! `no_range_argument_can_unwind_the_executor`, because only the second one contains `0-`.
//! A single-value regression test taken from the report would have looked like a passing fix.
//!
//! And a panic here does not stay here. `dispatch` runs inside a `scope.spawn` closure, and
//! `std::thread::scope` re-raises on join — so **one bad `range` aborted the entire batch** and
//! unwound out through `run_group`, with no `catch_unwind` between here and the daemon. Thirty
//! fetched documents lost to one integer.

use std::io::Write;

use marlowe_contract::TrustClass;
use marlowe_exec::{FileSystemTools, MAX_READ_BYTES};
use marlowe_loop::{ToolBody, ToolHost};
use marlowe_permission::scope::WorkspaceScope;
use marlowe_permission::{Adjudicator, Args, EgressPolicy, Request, TaintSet, Tier};
use marlowe_tools::{builtin_registry, ExposedSet, ToolId, BUILTIN_TOOLS};

static SEQ: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

struct Workspace {
    dir: std::path::PathBuf,
}

impl Workspace {
    fn new(name: &str) -> Self {
        let n = SEQ.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let dir = std::env::temp_dir()
            .join(format!("marlowe-readbounds-{name}-{}-{n}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        Self { dir }
    }

    fn write(&self, name: &str, contents: &[u8]) -> String {
        let mut f = std::fs::File::create(self.dir.join(name)).unwrap();
        f.write_all(contents).unwrap();
        name.to_string()
    }
}

impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

/// Adjudicate and execute one `read`, exactly as the loop does — so the handle comes from the
/// permission layer rather than from the test.
fn read_with(ws: &Workspace, args: Vec<(&str, &str)>) -> marlowe_loop::ToolOutcome {
    let registry = builtin_registry().expect("the builtin registry loads");
    let tool = ToolId::new("read");
    let mut a = Args::new();
    for (k, v) in args {
        a = a.text(k, v);
    }
    let exposed =
        ExposedSet::new(BUILTIN_TOOLS.iter().map(|t| ToolId::new(*t)).collect()).unwrap();
    let mut taint = TaintSet::new();
    for (name, _) in a.iter() {
        taint.insert(name.clone(), TrustClass::UserAsserted);
    }
    let mut adjudicator = Adjudicator::new(WorkspaceScope::new().expect("scope"));
    let adjudication = adjudicator.adjudicate(Request {
        manifest: registry.manifest(&tool).expect("read is registered"),
        args: &a,
        taint: &taint,
        exposed: &exposed,
        egress: &EgressPolicy::DenyAll,
        workspace: &ws.dir,
        tier: Tier::Silent,
        novelty: None,
    });
    let mut host = FileSystemTools::new(WorkspaceScope::new().expect("scope"), ws.dir.clone());
    host.execute(&tool, &a, &adjudication)
}

fn body(o: &marlowe_loop::ToolOutcome) -> String {
    match &o.body {
        ToolBody::Inline(s) => s.clone(),
        ToolBody::Reference { hash, bytes } => format!("ref {hash} {bytes}"),
    }
}

/// **A7.** The value that actually overflows. It must produce an answer, not a panic.
#[test]
fn the_range_that_overflowed_returns_a_result() {
    let ws = Workspace::new("overflow");
    let path = ws.write("f.txt", b"one\ntwo\nthree\n");

    let out = read_with(&ws, vec![("path", &path), ("range", "0-18446744073709551615")]);

    assert!(!out.failed, "an absurd range is not a failure, it is a wide range");
    assert!(body(&out).contains("one"), "a range from line 1 must still start at line 1");
}

/// Every neighbouring shape of the same argument, because an off-by-one fix that clears exactly one
/// value is not a fix. None of these may panic.
#[test]
fn no_range_argument_can_unwind_the_executor() {
    let ws = Workspace::new("ranges");
    let path = ws.write("f.txt", b"a\nb\nc\nd\ne\n");

    let hostile = [
        "1-18446744073709551615",
        "18446744073709551615-18446744073709551615",
        "18446744073709551615-1",
        "0-0",
        "0-18446744073709551615",
        "5-1",
        "-",
        "-5",
        "5-",
        "",
        "1-2-3",
        "٣-٤",
        "1e10-2e10",
        " 1 - 2 ",
    ];
    for range in hostile {
        // The assertion is that this call RETURNS. A panic propagates out of `scope.spawn` and
        // takes the whole batch with it, so "did not panic" is the property, and `catch_unwind`
        // is how a test can tell the difference between that and a failed call.
        let r = std::panic::catch_unwind(|| {
            let out = read_with(&ws, vec![("path", &path), ("range", range)]);
            body(&out)
        });
        assert!(r.is_ok(), "range {range:?} unwound the executor");
    }
}

/// An inverted range selects nothing rather than one arbitrary line.
#[test]
fn an_inverted_range_selects_nothing() {
    let ws = Workspace::new("inverted");
    let path = ws.write("f.txt", b"a\nb\nc\nd\ne\n");
    let out = read_with(&ws, vec![("path", &path), ("range", "4-2")]);
    assert!(body(&out).trim().is_empty(), "got {:?}", body(&out));
}

/// The negative control: ordinary ranges still work. Without this, a `slice_lines` that returned
/// `""` for everything would pass both tests above.
#[test]
fn an_ordinary_range_still_selects_the_lines_it_names() {
    let ws = Workspace::new("ordinary");
    let path = ws.write("f.txt", b"a\nb\nc\nd\ne\n");
    let out = read_with(&ws, vec![("path", &path), ("range", "2-4")]);
    assert_eq!(body(&out).trim(), "b\nc\nd");
}

/// **A8.** A file larger than the cap is truncated, and the model is told so in words.
#[test]
fn an_oversized_file_is_capped_and_the_truncation_is_stated() {
    let ws = Workspace::new("huge");
    // One byte over, so the boundary itself is under test rather than a comfortable margin.
    let size = MAX_READ_BYTES as usize + 1;
    let path = ws.write("huge.txt", &b"A".repeat(size));

    let out = read_with(&ws, vec![("path", &path)]);
    let text = body(&out);

    assert!(!out.failed, "a large file is readable, just not wholly");
    // A reference body carries only a hash, so the size assertion goes through the summary.
    let rendered = out.summary.render();
    assert!(
        rendered.contains("truncated"),
        "the truncation must be reported: {rendered}"
    );
    assert!(
        text.len() < size,
        "the whole file came back despite the cap: {} bytes",
        text.len()
    );
}

/// The negative control for the cap. A file at exactly the cap is **not** truncated — otherwise a
/// `read` that always reported truncation would pass the test above.
#[test]
fn a_file_at_exactly_the_cap_is_not_reported_as_truncated() {
    let ws = Workspace::new("exact");
    let path = ws.write("exact.txt", &b"A".repeat(MAX_READ_BYTES as usize));
    let out = read_with(&ws, vec![("path", &path)]);
    assert!(
        !out.summary.render().contains("truncated"),
        "a file exactly at the cap is whole: {}",
        out.summary.render()
    );
}

/// A binary file is **reported**, not decoded.
///
/// `read_to_string` used to fail outright, so `read` could say nothing at all about a non-UTF-8
/// file; decoding lossily would be worse, filling the window with replacement characters that look
/// like content.
#[test]
fn a_binary_file_is_named_rather_than_decoded_or_refused() {
    let ws = Workspace::new("binary");
    let mut bytes = vec![0u8; 4096];
    for (i, b) in bytes.iter_mut().enumerate() {
        *b = (i % 256) as u8;
    }
    let path = ws.write("blob.bin", &bytes);

    let out = read_with(&ws, vec![("path", &path)]);
    let rendered = out.summary.render();
    assert!(!out.failed, "a binary file is not an error, it is a fact about the file");
    assert!(rendered.contains("binary"), "it must say what it found: {rendered}");
    assert!(body(&out).is_empty(), "and it must not hand over the bytes");
}

/// The negative control for that: an ordinary text file is still returned whole.
#[test]
fn a_text_file_is_still_returned_whole() {
    let ws = Workspace::new("text");
    let path = ws.write("f.txt", "hello\nworld\n".as_bytes());
    let out = read_with(&ws, vec![("path", &path)]);
    assert!(body(&out).contains("hello"), "{:?}", body(&out));
    assert!(!out.summary.render().contains("binary"));
    assert!(!out.summary.render().contains("truncated"));
}
