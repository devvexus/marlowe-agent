//! CONTRACTS.md section 4 as Rust types — and nothing else.
//!
//! This crate is the M0a↔M0b boundary. It depends on no other Marlowe crate, and nothing
//! here knows what a retriever is. **The JSON is normative; these types are its binding**
//! (section 4.2b), because the scorer is Python and the implementation is Rust.
//!
//! Three interfaces, and there is no fourth. Section 4: *"M0b may expose no other surface
//! to M0a. If the harness needs a fourth, the split is leaking and the fix belongs in
//! CONTRACTS.md, not in the harness."*
//!
//! # Determinism
//!
//! Section 4.0.8 and the `repro` acceptance criterion together mean a run at a fixed seed
//! and clock must reproduce **bit-identically**. Two hazards live in this crate's
//! neighbourhood and are called out here because they pass locally and fail in `repro`:
//!
//! 1. **`HashMap` iteration order is randomised per process** in Rust. Any map whose
//!    iteration order can reach the wire must be a `BTreeMap`, or be collected and sorted
//!    explicitly. A workspace test greps for the type to keep this honest.
//! 2. **No identifier may derive from anything time-adjacent.** The clock probe shifts every
//!    supplied timestamp by ten years and compares injected `memory_id`s for equality, so an
//!    id built from a timestamp fails translation invariance — and a run that reads the
//!    system clock for an id fails `repro` on the second run.

#![forbid(unsafe_code)]

pub mod common;
pub mod frame;
pub mod wire;

pub use common::{
    AbstentionReason, Channel, Clock, Fidelity, PayloadKind, Speaker, TrustClass,
};
pub use frame::{ErrorKind, FrameError, Op, RequestFrame, ResponseFrame};
pub use wire::{
    AnswerCost, AnswerLatency, AnswerRequest, AnswerResponse, ContractVersion,
    ExclusivityError, GateStamp, IngestCost, IngestLatency, IngestRequest, IngestResponse,
    InjectedMemory, Origin, RejectedWrite, RetrievalBudget, RetrievalCost, RetrievalLatency,
    RetrievalRequest, RetrievalResponse, Turn, Written, CONTRACT_VERSION,
};
