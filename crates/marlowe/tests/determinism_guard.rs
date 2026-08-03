//! Two crude, enforced guards against the failures that pass locally and fail `repro`.
//!
//! HP10's rule: *"a crude enforced mechanism beats an elegant unenforced one."* These are
//! source greps. They will produce the occasional false positive and need an allowlist that
//! itself needs maintenance, and that is the accepted cost.
//!
//! Both guards exist because the failure they catch is **invisible until the acceptance
//! test runs**, and by then it presents as an unexplained hash mismatch rather than as the
//! line of code that caused it.

use std::fs;
use std::path::{Path, PathBuf};

/// Lines a grep-based guard must not judge, with the reason each is exempt.
///
/// Only two exemptions, and neither one hides a line of real code:
///
/// * **Comments.** A guard that fires on the sentence explaining the rule makes the rule
///   undocumentable.
/// * **The `fn` line of a `#[test]`.** Tests asserting these properties are named after
///   them, so `fn memory_ids_do_not_contain_a_timestamp()` trips the very guard it supports.
///
/// The exemption is deliberately the *declaration line of an annotated test* and not the
/// file, the module, or anything named "test". Allowlisting `entry.rs` would have been one
/// character of diff and would have blinded the guard to the single file where the real
/// mistake would live — which is how a guard survives as a passing test while protecting
/// nothing.
fn judgeable_lines(src: &str) -> Vec<(usize, &str)> {
    let mut out = Vec::new();
    let mut prev_was_test_attr = false;
    for (n, line) in src.lines().enumerate() {
        let trimmed = line.trim_start();
        let is_comment = trimmed.starts_with("//") || trimmed.starts_with('*');
        let is_test_signature = prev_was_test_attr && trimmed.starts_with("fn ");
        if !is_comment && !is_test_signature {
            out.push((n + 1, line));
        }
        if !trimmed.is_empty() {
            prev_was_test_attr = trimmed == "#[test]";
        }
    }
    out
}

fn crate_sources() -> Vec<PathBuf> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("crates/")
        .to_path_buf();
    let mut out = Vec::new();
    collect(&root, &mut out);
    out.sort();
    out
}

fn collect(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    // Sorted, because even a test's own traversal order should not depend on the filesystem.
    let mut entries: Vec<_> = entries.filter_map(Result::ok).map(|e| e.path()).collect();
    entries.sort();
    for path in entries {
        if path.is_dir() {
            if path.file_name().is_some_and(|n| n == "target") {
                continue;
            }
            collect(&path, out);
        } else if path.extension().is_some_and(|e| e == "rs") {
            out.push(path);
        }
    }
}

/// `HashMap` iteration order is randomised per process in Rust. A map whose order can reach
/// the wire therefore produces a different `run.jsonl` on every run, and `marlowe-eval repro
/// --runs 2` fails with two different sha256 values and no indication of where they came
/// from.
///
/// The rule is blunt on purpose: use `BTreeMap`/`BTreeSet`. If a hash map is ever genuinely
/// needed for a hot path whose order provably cannot reach output, add it to the allowlist
/// **with the reason**, and expect to defend it.
#[test]
fn no_hash_map_in_crate_sources() {
    const ALLOWED: &[&str] = &[
        // This file names the types in order to ban them.
        "determinism_guard.rs",
    ];

    let mut offenders = Vec::new();
    for path in crate_sources() {
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        if ALLOWED.contains(&name.as_str()) {
            continue;
        }
        let src = fs::read_to_string(&path).unwrap_or_default();
        for (n, line) in judgeable_lines(&src) {
            if line.contains("HashMap") || line.contains("HashSet") {
                offenders.push(format!("{}:{}: {}", path.display(), n, line.trim()));
            }
        }
    }
    assert!(
        offenders.is_empty(),
        "hash-ordered collections found. Their iteration order is randomised per process, so \
         anything reaching the wire from one makes `marlowe-eval repro` fail with two \
         different hashes and no clue why. Use BTreeMap/BTreeSet:\n  {}",
        offenders.join("\n  ")
    );
}

/// Section 4.5, and the one legitimate exception to it.
///
/// *"On any path reachable from sections 4.1, 4.6, or 4.7, the implementation MUST NOT read
/// a system clock. Every timestamp is derived from the `clock` supplied by the caller."*
///
/// Exactly one reading of a real clock is legitimate: `cost.latency_ms`, which the contract
/// requires the implementation to self-report and which the harness excludes from its
/// reproduction hash for that reason. That read is fenced into one module so this guard can
/// name it, and so a second one cannot appear without appearing here.
#[test]
fn the_only_real_clock_read_is_the_latency_fence() {
    const FENCE: &str = "elapsed.rs";

    let mut offenders = Vec::new();
    for path in crate_sources() {
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        if name == FENCE || name == "determinism_guard.rs" {
            continue;
        }
        let src = fs::read_to_string(&path).unwrap_or_default();
        for (n, line) in judgeable_lines(&src) {
            if line.contains("SystemTime")
                || line.contains("Instant::now")
                || line.contains("UNIX_EPOCH")
            {
                offenders.push(format!("{}:{}: {}", path.display(), n, line.trim()));
            }
        }
    }
    assert!(
        offenders.is_empty(),
        "a real clock is read outside {FENCE}. Section 4.5 is binding on every path \
         reachable from sections 4.1/4.6/4.7, and a stray read makes staleness half-life \
         unmeasurable and every decay-dependent result irreproducible. If this is a latency \
         measurement, route it through the fence:\n  {}",
        offenders.join("\n  ")
    );
}

/// The clock probe shifts every supplied timestamp by ten years and compares the injected
/// `memory_id`s for equality, so an id built from a timestamp fails translation invariance.
/// This guard is weaker than the two above — it only catches the obvious spelling — so the
/// real defence is the probe itself. It is here to fail early and name the reason.
#[test]
fn memory_ids_are_not_built_from_timestamps() {
    let mut offenders = Vec::new();
    for path in crate_sources() {
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        if name == "determinism_guard.rs" {
            continue;
        }
        let src = fs::read_to_string(&path).unwrap_or_default();
        for (n, line) in judgeable_lines(&src) {
            let looks_like_id = line.contains("memory_id") || line.contains("MemoryId");
            let looks_like_time = line.contains("now_ms")
                || line.contains("occurred_at")
                || line.contains("timestamp");
            if looks_like_id && looks_like_time {
                offenders.push(format!("{}:{}: {}", path.display(), n, line.trim()));
            }
        }
    }
    assert!(
        offenders.is_empty(),
        "an identifier appears to be derived from a time value. Clock probe test A shifts \
         every supplied timestamp by ten years and asserts the injected ids are unchanged, \
         so this fails translation invariance:\n  {}",
        offenders.join("\n  ")
    );
}
