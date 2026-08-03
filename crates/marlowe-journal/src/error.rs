//! Journal errors. Every one of these is loud; none has a fallback path.

use std::path::PathBuf;

use crate::event::{EventKind, Seq};

#[derive(Debug, thiserror::Error)]
pub enum JournalError {
    #[error(
        "profile root {root} already contains {entries} entr(ies); refusing to reuse state. \
         Each eval spawn must start empty, or the clock probe compares contaminated runs \
         while reporting a clean verdict"
    )]
    ProfileRootNotEmpty { root: PathBuf, entries: usize },

    #[error(
        "profile at {root} is incomplete: {missing} is absent. This is a startup error and \
         not a reason to start fresh -- a wiped journal must never be indistinguishable from \
         a new profile"
    )]
    ProfileIncomplete { root: PathBuf, missing: PathBuf },

    #[error("signing key at {path} is not 32 bytes of hex")]
    MalformedKey { path: PathBuf },

    #[error("profile was written for contract {found}, this build speaks {expected}")]
    ContractVersionMismatch { found: String, expected: String },

    #[error(
        "profile was derived by version {found}, this build derives version {expected}. The \
         belief store is a materialized view, so the fix is a rebuild, never a migration"
    )]
    DerivationVersionMismatch { found: u32, expected: u32 },

    #[error(
        "event kind {kind:?} may only be appended by Actor::Permission, but the actor was \
         {actor}. Section 1.1: self-granted promotions are structurally impossible, not \
         merely forbidden"
    )]
    ActorMayNotEmit { kind: EventKind, actor: String },

    #[error(
        "signature chain broken at seq {seq}: this event does not verify. The log is the \
         audit trail (invariant 7), so a break is tampering or corruption and never \
         something to skip past"
    )]
    ChainBroken { seq: Seq },

    #[error("sequence gap: expected seq {expected}, found {found}. Gaps are impossible by construction")]
    SequenceGap { expected: Seq, found: Seq },

    #[error("could not generate a signing key: {0}")]
    KeyGeneration(String),

    #[error(transparent)]
    Io(#[from] std::io::Error),

    #[error(transparent)]
    Sqlite(#[from] rusqlite::Error),

    #[error(transparent)]
    Json(#[from] serde_json::Error),
}
