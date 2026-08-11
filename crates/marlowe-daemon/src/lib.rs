//! ARCHITECTURE §6 — one binary, two roles.
//!
//! > **`marlowe`** — thin client. Holds no run state. Renders. Auto-spawns the daemon if absent.
//! > **`marlowe --serve`** — the daemon. Owns the journal, belief store, indexes, runs.
//!
//! # Why the split exists, and what it does and does not buy at M2
//!
//! §6 is explicit: *"The client/daemon split is forced by invariant 6: if the client owned the
//! run, closing the terminal would kill it."* So the daemon owns the `Engine`, the `Journal` and
//! the run table, and [`protocol`] has no frame that hands a client a `Run`, a `Checkpoint` or a
//! transcript — asserted in that module rather than left to discipline.
//!
//! **What this buys at M2:** a run outlives the *client*. Close the terminal, reconnect, and the
//! daemon still owns it and still reports it.
//!
//! **What it does not buy, stated so it is not read as more:** a run does not yet outlive the
//! *daemon*. There is no WAL and no checkpoint resume, so a daemon restart loses in-flight runs.
//! That is **M3 and K5**, and `RunControl::resume` already refuses by name rather than pretending
//! otherwise. Calling this "durable runs" would be exactly the adjacent-measurement failure this
//! project has logged fifteen times.
//!
//! # The first frame does not come from here
//!
//! §B13 budgets 150 ms to first frame and §6 names the split as what buys it: *"the client has
//! almost nothing to initialize, and the header paints before the daemon connection resolves."*
//! Nothing in this crate is on the path to the first frame, and `tests/first_frame.rs` asserts
//! that a client can render before a daemon exists at all.

#![forbid(unsafe_code)]

pub mod client;
pub mod clock;
pub mod daemon;
pub mod live;
pub mod memory;
pub mod recall;
pub mod project;
mod staleness;
pub mod protocol;

pub use client::{Client, ClientError};
pub use daemon::{Daemon, DaemonConfig, DaemonError, governance_prompt};
pub use live::LiveSession;
pub use project::{apply_events, view_from_status};
pub use protocol::{Event, Request, StatusReport};

/// The loopback port the daemon listens on.
///
/// Loopback only, and that is not a placeholder for "configurable later": a daemon that owned a
/// user's filesystem and answered from a routable address would be a remote code execution
/// service. If a remote client is ever wanted, it is a separate decision with authentication in
/// it, argued in `DECISIONS.md`.
pub const DEFAULT_DAEMON_PORT: u16 = 11435;
