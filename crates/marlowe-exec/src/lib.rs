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

use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

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
}

impl<S: PathScope> FileSystemTools<S> {
    pub fn new(scope: S, workspace: impl Into<PathBuf>) -> Self {
        Self { scope, workspace: workspace.into() }
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
    }
}

/// Inline if small, reference if not. §2.8's first axis — **size**, independent of trust.
fn body_for(text: String) -> (ToolBody, u64) {
    let bytes = text.len() as u64;
    if text.len() <= MAX_INLINE_BYTES {
        (ToolBody::Inline(text), bytes)
    } else {
        // Content-addressed by the store at M2 D; until then the hash names the bytes so the
        // summary is honest about what it is standing in for.
        let hash = format!("{:016x}", fnv1a(text.as_bytes()));
        (ToolBody::Reference { hash, bytes }, bytes)
    }
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
        let Some(scoped) = handle_for(a, "path") else {
            return failed("read", "no adjudicated handle for `path`");
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
        let (body, bytes) = body_for(text);
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
        let (body, _) = body_for(hits.join("\n"));
        ToolOutcome {
            summary: ResultSummary::new(vec![
                Metric::Count { n: found, unit: "results" },
                Metric::Count { n: scanned, unit: "files" },
            ]),
            body,
            trust: TrustClass::AgentObserved,
            failed: false,
            wall_ms: 0,
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
                let (body, _) = body_for(text);
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
                }
            }
        }
    }
}

impl<S: PathScope> ToolHost for FileSystemTools<S> {
    fn execute(&mut self, tool: &ToolId, args: &Args, adjudication: &Adjudication) -> ToolOutcome {
        // The declared globs are the manifest's; the adjudicator already matched the model's
        // argument against them. `find` needs them again for its own opens.
        let declared = [PathGlob::new("./**")];
        match tool.as_str() {
            "read" => self.read(args, adjudication),
            "edit" => self.edit(args, adjudication),
            "find" => self.find(args, adjudication, &declared),
            "bash" => self.bash(args, adjudication),
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
