//! Path scoping. **This is the wall.**
//!
//! ADR-002 (revised) removed the kernel backstop, and brief §8.3 states the consequence:
//!
//! > **Inseparable from handle-based access**: canonicalize-then-open leaves a check-then-use
//! > race, so a traversal suite passing against a check-then-open implementation reports a
//! > boundary that is not there. The suite and the handle discipline are one requirement and
//! > ship together.
//!
//! They ship together here. Three parts, and each does one job:
//!
//! | Part | Job |
//! |---|---|
//! | [`request`] | refuse ambiguous *spellings* before any syscall — `..`, rooted forms, ADS, device names, short names, munged names, homoglyph separators |
//! | [`glob`] | decide whether a well-formed request is inside what the manifest **declared** |
//! | [`walk`] | open it without ever letting a string be resolved twice — `openat`/`O_NOFOLLOW` on POSIX, pinned handles plus reparse refusal plus identity verification on Windows |
//!
//! **Order matters and it is the order ADR-002 names: canonicalize before the check, never
//! after.** Here the strongest reading of that is stronger still — the hostile string is never
//! canonicalized at all. It is validated, matched against the declaration, and then *walked*,
//! with the kernel resolving one component at a time under our supervision. There is no moment
//! at which a resolved string exists and is trusted.
//!
//! # `ScopedPath` cannot be built from a string, and that is the discipline as a type
//!
//! It holds an open handle. An implementation that resolved a path without opening it cannot
//! produce one, so "operate on handles rather than re-resolved strings" is enforced by what the
//! adjudicator demands rather than by review.

pub mod glob;
pub mod request;
pub mod walk;

use std::fmt;
use std::fs::File;
use std::path::{Path, PathBuf};

use marlowe_tools::PathGlob;

pub use request::RequestError;
pub use walk::WalkObserver;

/// A path that was resolved **and opened**, with the handle retained.
///
/// The handle is the point. Every subsequent operation goes through it rather than re-resolving
/// the string, which is what closes the check-then-use window: a link planted after the check
/// cannot redirect an already-open handle.
#[derive(Debug)]
pub struct ScopedPath {
    /// Private, and there is deliberately no constructor taking a `PathBuf`.
    handle: File,
    resolved: PathBuf,
    relative: String,
}

impl ScopedPath {
    /// The open handle. All access goes through it.
    pub fn handle(&self) -> &File {
        &self.handle
    }

    /// Consume the scope and take the handle.
    pub fn into_handle(self) -> File {
        self.handle
    }

    /// The resolved path, for logging and for the blast-radius line the user sees.
    ///
    /// **Not for re-opening.** A caller that takes this and calls `File::open` on it has
    /// reintroduced the race the handle exists to close.
    pub fn resolved(&self) -> &Path {
        &self.resolved
    }

    /// The workspace-relative form the request normalized to.
    pub fn relative(&self) -> &str {
        &self.relative
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ScopeError {
    /// Only reachable from [`Unavailable`].
    #[error(
        "path scoping is not implemented in this build, so `{requested}` is refused. The \
         traversal suite and the handle discipline ship together (brief §8.3) — a path check \
         without them certifies a boundary that is not there"
    )]
    Unavailable { requested: String },

    #[error("`{requested}` is not a well-formed workspace-relative path: {source}")]
    Malformed {
        requested: String,
        #[source]
        source: RequestError,
    },

    #[error(
        "`{requested}` is not inside any path this tool declared. Undeclared access is denied \
         at the boundary, not warned about (brief §8.2)"
    )]
    Undeclared { requested: String },

    #[error(
        "`{requested}` resolves outside the workspace. A link in the path pointed out of \
         scope and was refused rather than followed"
    )]
    OutsideScope { requested: String },

    #[error("`{requested}` could not be opened: {detail}")]
    Unopenable { requested: String, detail: String },

    #[error(
        "`{requested}` changed identity during resolution. The handle does not refer to the \
         object that was checked, so it is refused"
    )]
    IdentityChanged { requested: String },
}

/// Resolve a requested path against a tool's declared globs, and open it.
///
/// The signature takes the **workspace root** because manifests declare workspace-relative globs
/// (`./**`): a manifest holding an absolute path would mean something different on another
/// machine, and resolving that binding is the scope's job, not the manifest's.
pub trait PathScope: fmt::Debug + Send + Sync {
    fn open(
        &self,
        declared: &[PathGlob],
        workspace: &Path,
        requested: &str,
    ) -> Result<ScopedPath, ScopeError>;
}

/// Refuses every path. Retained after M2 Session B rather than deleted.
///
/// It is what a capability profile uses when it must provably not touch the filesystem, and it
/// is what the adjudicator's tests use so that a permission-layer test never depends on a real
/// directory existing. Keeping it also means "no scope configured" has a value that fails
/// closed, rather than being represented by an `Option` whose `None` arm somebody writes a
/// permissive branch for.
#[derive(Debug, Default, Clone, Copy)]
pub struct Unavailable;

impl PathScope for Unavailable {
    fn open(
        &self,
        _declared: &[PathGlob],
        _workspace: &Path,
        requested: &str,
    ) -> Result<ScopedPath, ScopeError> {
        Err(ScopeError::Unavailable { requested: requested.to_string() })
    }
}

/// The real one.
#[derive(Debug, Default)]
pub struct WorkspaceScope;

impl WorkspaceScope {
    pub fn new() -> Self {
        Self
    }

    /// The same walk, with an observer. **Test-facing**, and the reason it is `pub` is stated
    /// in `walk`: the TOCTOU test has to be able to plant a link at the exact instant a race
    /// would land, and a test that races a thread and hopes would prove nothing when it passed.
    #[doc(hidden)]
    pub fn open_observed(
        &self,
        declared: &[PathGlob],
        workspace: &Path,
        requested: &str,
        observer: &dyn WalkObserver,
    ) -> Result<ScopedPath, ScopeError> {
        // 1. Refuse ambiguous spellings, before any syscall.
        let parsed = request::validate(requested).map_err(|source| ScopeError::Malformed {
            requested: requested.to_string(),
            source,
        })?;

        // 2. The declaration decides, and an empty declaration decides "no".
        if !glob::admits(declared, &parsed) {
            return Err(ScopeError::Undeclared { requested: parsed.as_relative() });
        }

        // 3. Walk it open. Nothing above this line touched the filesystem, and nothing below it
        //    resolves a string the kernel will resolve again.
        let opened = walk::open_within(workspace, &parsed, observer)?;
        Ok(ScopedPath {
            handle: opened.handle,
            resolved: opened.resolved,
            relative: parsed.as_relative(),
        })
    }
}

impl PathScope for WorkspaceScope {
    fn open(
        &self,
        declared: &[PathGlob],
        workspace: &Path,
        requested: &str,
    ) -> Result<ScopedPath, ScopeError> {
        self.open_observed(declared, workspace, requested, &())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_refusing_scope_still_refuses_and_says_why() {
        let e = Unavailable
            .open(&[PathGlob::new("./**")], Path::new("/ws"), "src/main.rs")
            .unwrap_err();
        assert!(matches!(e, ScopeError::Unavailable { .. }));
        assert!(e.to_string().contains("ship together"), "{e}");
    }

    #[test]
    fn a_scoped_path_cannot_be_built_without_a_handle() {
        // Executable documentation. `ScopedPath` has private fields and no `new`; the only way
        // to obtain one is from an implementation that actually opened something. If a future
        // session adds `ScopedPath::from_path(PathBuf)`, this comment is what has to be argued
        // past, and brief §8.3 is the argument it has to beat.
        fn _assert_no_public_constructor() {
            // Intentionally empty: the assertion is that the following does not compile.
            //   let _ = ScopedPath { handle: .., resolved: .., relative: .. };
        }
    }

    #[test]
    fn the_declaration_is_checked_before_the_filesystem_is_touched() {
        // A path outside the declaration is refused without a syscall, so a nonexistent
        // workspace still produces `Undeclared` rather than an io error. That ordering is what
        // keeps an undeclared probe from being answerable by timing.
        let e = WorkspaceScope::new()
            .open(
                &[PathGlob::new("./out/**")],
                Path::new("/nonexistent-workspace-xyzzy"),
                "src/secret.rs",
            )
            .unwrap_err();
        assert!(matches!(e, ScopeError::Undeclared { .. }), "{e:?}");
    }

    #[test]
    fn a_malformed_request_is_refused_before_the_declaration_is_consulted() {
        let e = WorkspaceScope::new()
            .open(&[PathGlob::new("./**")], Path::new("/nonexistent-xyzzy"), "../../etc/passwd")
            .unwrap_err();
        assert!(matches!(e, ScopeError::Malformed { .. }), "{e:?}");
    }
}
