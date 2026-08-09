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
/// Exactly one reading of a real clock is legitimate **on a contract path**: `cost.latency_ms`,
/// which the contract requires the implementation to self-report and which the harness excludes
/// from its reproduction hash for that reason. That read is fenced into one module so this guard
/// can name it, and so a second one cannot appear without appearing here.
///
/// M1 adds a second fence, off every contract path. A terminal that animates needs a monotonic
/// time base, and K4 is stated in milliseconds to first frame, so `--timing-probe` has to read a
/// real clock to report one. It is fenced for the same reason the first one is: so that the
/// *third* read cannot appear silently.
///
/// **Both entries are exact file names, never directories.** The `HashMap` guard's argument
/// applies here too — allowlisting a directory would blind this guard to the files where the real
/// mistake would live. `marlowe-surface` gets no exemption at all: every render there is a pure
/// function of `(state, now_ms)`, which is what makes §B13's flicker rows diffable in the first
/// place, and a stray `Instant::now()` inside a widget would take that away.
#[test]
fn the_only_real_clock_read_is_the_latency_fence() {
    const FENCES: &[&str] = &[
        // Section 4.2's self-reported `cost.latency_ms`. The original fence.
        "elapsed.rs",
        // M1: the stub owns the time base because ARCHITECTURE.md §2.14 says a surface holds no
        // state the daemon lacks, and time is state. Not on any contract path.
        "frame_clock.rs",
        // M2 C2c: the PRODUCTION harness clock. §4.5 forbids a system clock on the contract
        // paths and names the legitimate case in the same paragraph — "in production the harness
        // supplies the real clock". The daemon is that harness, so real time enters the system
        // here, once. It is a whole file holding one struct so this fence stays narrow:
        // exempting `daemon.rs` would blind the guard to every future clock read in it, which is
        // the failure this test's own header warns about for directories. The eval adapter never
        // constructs a `Daemon` and still supplies M0a's synthetic clock.
        "clock.rs",
    ];

    /// The engine spike — a **temporary** measurement crate, exempt with an expiry.
    ///
    /// It times forward passes to decide ADR-004's runtime, so a real clock is the whole
    /// point. It implements no section 4 interface, is not a dependency of `marlowe`, and is
    /// deleted once ADR-004 names an engine. **Delete this entry with the crate** — an
    /// exemption that outlives what it exempts is how a guard quietly stops guarding.
    ///
    /// Note this is a directory exemption, which the `HashMap` guard deliberately refuses to
    /// grant. The difference: that guard's whole value is covering the files where the real
    /// mistake would live, whereas nothing on a contract path is inside this crate.
    const TEMPORARY_SPIKE: &str = "marlowe-embed-spike";

    // **A fence naming a file that no longer exists is a comment.**
    //
    // This list matches on file NAME, so a fenced file moving between crates keeps working and a
    // fenced file being *deleted* leaves a silent exemption behind — and the exemption would then
    // sit there ready to excuse a future file that happened to take the same name. That is the
    // fourteenth-instance shape (a guard whose subject moved) with the subject gone entirely.
    //
    // `protect-boundaries.py` grew `--self-check` for exactly this after M2 Session B; this guard
    // never did. M2 C2d moved `turn.rs` and `model.rs` between crates, which is what made the gap
    // worth closing rather than noting.
    let all: Vec<String> = crate_sources()
        .iter()
        .filter_map(|p| p.file_name().map(|n| n.to_string_lossy().to_string()))
        .collect();
    for fence in FENCES {
        assert!(
            all.iter().any(|n| n == fence),
            "the clock fence names `{fence}`, and no such file exists in crates/. Either it was \
             renamed — in which case point the fence at the new name — or it was deleted, in \
             which case delete the entry. An exemption that outlives what it exempts silently \
             excuses the next file to take that name."
        );
    }

    /// Files that **name** the forbidden spellings in order to ban them, and read no clock.
    ///
    /// Deliberately a separate list from [`FENCES`], not extra entries in it. A fence says *this
    /// file legitimately reads real time*; these say *this file mentions the words*. Collapsing
    /// them would let a genuine clock read appear in a test file under an exemption that was
    /// granted for a string literal — the two claims are different and the list that records them
    /// should be too.
    /// Files that compare **filesystem timestamps** and never read the current time.
    ///
    /// A third list, and the separation is the point. `FENCES` means *this file legitimately reads
    /// real time*; `NAMES_BUT_DOES_NOT_READ` means *this file spells the words in order to ban
    /// them*. Neither describes a file that compares two mtimes — and folding it into `FENCES`
    /// would grant it the right to call `SystemTime::now()`, which is exactly what it must not do.
    const COMPARES_MTIMES: &[&str] = &[
        // M2 C2e: the daemon staleness guard. Compares the executable's mtime against the newest
        // source file. Nothing here reaches a journal timestamp, a memory id or a repro hash.
        "staleness.rs",
    ];
    for named in COMPARES_MTIMES {
        assert!(
            all.iter().any(|n| n == named),
            "the clock guard exempts `{named}`, and no such file exists in crates/."
        );
    }

    const NAMES_BUT_DOES_NOT_READ: &[&str] = &[
        "determinism_guard.rs",
        // M2 C2d. Asserts locally that `marlowe-surface` reads no clock, which means spelling out
        // what it is looking for. See `marlowe-surface/tests/c2d_boundary.rs`.
        "c2d_boundary.rs",
    ];
    for named in NAMES_BUT_DOES_NOT_READ {
        assert!(
            all.iter().any(|n| n == named),
            "the clock guard exempts `{named}`, and no such file exists in crates/. Delete the \
             entry with the file — an exemption that outlives what it exempts is how a guard \
             quietly stops guarding."
        );
    }

    let mut offenders = Vec::new();
    for path in crate_sources() {
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        if FENCES.contains(&name.as_str())
            || NAMES_BUT_DOES_NOT_READ.contains(&name.as_str())
            || COMPARES_MTIMES.contains(&name.as_str())
        {
            continue;
        }
        if path.components().any(|c| c.as_os_str() == TEMPORARY_SPIKE) {
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
        "a real clock is read outside the fences {FENCES:?}. Section 4.5 is binding on every path \
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
