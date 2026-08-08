//! The brief §13 hook guards paths. This asserts the paths still exist.
//!
//! CLAUDE.md: *"a component with no entry is unguarded regardless of what this list says — the
//! entry is the enforcement, and the list is only a map of it."* The corollary is the failure
//! this test exists for: **a component whose file moved is unguarded too, and nothing says so.**
//!
//! It happened in M2 Session B. `crates/marlowe-permission/src/scope.rs` became
//! `scope/{mod,request,glob,walk}.rs`, the hook's entry named a file that no longer existed, and
//! path scoping — the wall, per ADR-002 — was silently unprotected. A pipe test caught it; a pipe
//! test that nobody runs would not have.
//!
//! This lives in `marlowe-permission` because that is where most guarded paths now are, and
//! because `marlowe-loop/tests/hp10_budgets.rs` already sets the precedent for a repo-scanning
//! test. It shells out to the hook rather than reimplementing the list: two copies of a
//! protected-path list is how they disagree.

use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..")
}

#[test]
fn every_guarded_path_in_the_boundary_hook_still_exists() {
    let root = repo_root();
    let hook = root.join(".claude").join("hooks").join("protect-boundaries.py");
    assert!(hook.exists(), "the boundary hook is missing: {}", hook.display());

    let out = Command::new("python")
        .arg(&hook)
        .arg("--self-check")
        .arg(&root)
        .output()
        .or_else(|_| {
            Command::new("python3").arg(&hook).arg("--self-check").arg(&root).output()
        })
        .expect("python is needed to run the boundary hook's self-check");

    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(
        out.status.success(),
        "the brief §13 hook names paths that no longer exist, so those components are \
         UNGUARDED and nothing else would report it:\n{stderr}"
    );
}

#[test]
fn the_hook_actually_fires_on_a_guarded_path() {
    // The self-check above proves the list is not stale. This proves the list does something —
    // together they are the pair, and either alone is a proxy.
    let root = repo_root();
    let hook = root.join(".claude").join("hooks").join("protect-boundaries.py");

    let guarded = "C:/anywhere/crates/marlowe-permission/src/scope/walk.rs";
    let payload = format!(r#"{{"tool_input":{{"file_path":"{guarded}"}}}}"#);

    let mut child = Command::new("python")
        .arg(&hook)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .or_else(|_| {
            Command::new("python3")
                .arg(&hook)
                .stdin(std::process::Stdio::piped())
                .stdout(std::process::Stdio::piped())
                .spawn()
        })
        .expect("python is needed to run the boundary hook");
    {
        use std::io::Write;
        child.stdin.as_mut().unwrap().write_all(payload.as_bytes()).unwrap();
    }
    let out = child.wait_with_output().unwrap();
    let stdout = String::from_utf8_lossy(&out.stdout);
    // `json.dumps` escapes non-ASCII by default, so the section sign arrives as `§`.
    // Asserting on the literal would have made this test fail for a reason that has nothing to
    // do with the boundary.
    assert!(
        stdout.contains("\"permissionDecision\": \"ask\"") && stdout.contains("BOUNDARY"),
        "the hook must ask for a decision on a guarded path, got: {stdout}"
    );
}
