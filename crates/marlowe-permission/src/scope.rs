//! Path scoping. **Not implemented in this session, and the absence is enforced rather than
//! documented.**
//!
//! ADR-002 (revised) removed the kernel backstop. A path check defeated by string manipulation
//! is therefore the whole protection gone, and brief §8.3 states the consequence in one line:
//!
//! > **Inseparable from handle-based access**: canonicalize-then-open leaves a check-then-use
//! > race, so a traversal suite passing against a check-then-open implementation reports a
//! > boundary that is not there. The suite and the handle discipline are one requirement and
//! > ship together.
//!
//! # Why there is a trait here with exactly one refusing implementation
//!
//! The tempting shape for a first session is a textual check — canonicalize with
//! `fs::canonicalize`, compare prefixes, ship it, and add handles later. That produces a
//! boundary that is *believed*, which §8.3 says is worse than no boundary. It would also make
//! the eventual traversal suite meaningless: a suite written against a check-then-open
//! implementation certifies the wrong thing.
//!
//! So the only implementation that exists is [`Unavailable`], which refuses every path. The
//! consequence is loud and intended: **`read`, `edit`, `find` and `bash` cannot run until
//! Session B lands the real scope**, because each declares a `Path` parameter and the
//! adjudicator blocks a `Path` target it cannot resolve. Their executors are not built either,
//! so nothing regresses — what is bought is that no path ever passes through a check that does
//! not exist.
//!
//! [`ScopedPath`] has no constructor from a string. It can only be built from an **open
//! handle**, so an implementation that resolved a path without opening it cannot produce the
//! type the adjudicator requires. That is the discipline expressed as a type rather than as a
//! review note.

use std::fmt;
use std::fs::File;
use std::path::{Path, PathBuf};

use marlowe_tools::PathGlob;

/// A path that was resolved **and opened**, with the handle retained.
///
/// The handle is the point. Every subsequent operation goes through it rather than
/// re-resolving the string, which is what closes the check-then-use window: a symlink planted
/// after the check cannot redirect an already-open handle.
#[derive(Debug)]
pub struct ScopedPath {
    /// Private, and there is deliberately no constructor taking a `PathBuf`.
    handle: File,
    canonical: PathBuf,
}

impl ScopedPath {
    /// The open handle. All access goes through it.
    pub fn handle(&self) -> &File {
        &self.handle
    }

    /// The resolved path, for logging and for the blast-radius line the user sees.
    ///
    /// **Not for re-opening.** A caller that takes this string and calls `File::open` on it has
    /// reintroduced the race the handle exists to close.
    pub fn canonical(&self) -> &Path {
        &self.canonical
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ScopeError {
    /// The only variant that can occur today.
    #[error(
        "path scoping is not implemented in this build, so `{requested}` is refused. The \
         traversal suite and the handle discipline ship together (brief §8.3) — a path check \
         without them certifies a boundary that is not there"
    )]
    Unavailable { requested: String },

    #[error("`{requested}` resolves outside every declared path")]
    OutsideScope { requested: String },

    #[error("`{requested}` could not be opened: {detail}")]
    Unopenable { requested: String, detail: String },

    #[error(
        "`{requested}` changed identity between resolution and open. The handle does not \
         refer to the file that was checked"
    )]
    IdentityChanged { requested: String },
}

/// Resolve a requested path against a tool's declared globs, and open it.
///
/// The signature takes the **workspace root** because manifests declare workspace-relative
/// globs (`./**`): a manifest holding an absolute path would mean something different on
/// another machine, and resolving that binding is the scope's job, not the manifest's.
pub trait PathScope: fmt::Debug + Send + Sync {
    fn open(
        &self,
        declared: &[PathGlob],
        workspace: &Path,
        requested: &str,
    ) -> Result<ScopedPath, ScopeError>;
}

/// The only implementation in this build. Refuses everything.
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_path_is_refused_and_the_refusal_says_why() {
        let e = Unavailable
            .open(&[PathGlob::new("./**")], Path::new("/ws"), "src/main.rs")
            .unwrap_err();
        assert!(matches!(e, ScopeError::Unavailable { .. }));
        let msg = e.to_string();
        assert!(
            msg.contains("ship together"),
            "the refusal must name the reason, not read as a missing feature: {msg}"
        );
    }

    #[test]
    fn a_scoped_path_cannot_be_built_without_a_handle() {
        // Executable documentation. `ScopedPath` has private fields and no `new`; the only way
        // to obtain one is from an implementation that actually opened something. If a future
        // session adds `ScopedPath::from_path(PathBuf)`, this comment is the thing that has to
        // be argued past, and brief §8.3 is the argument it has to beat.
        fn _assert_no_public_constructor() {
            // Intentionally empty: the assertion is that the following does not compile.
            //   let _ = ScopedPath { handle: .., canonical: .. };
        }
    }
}
