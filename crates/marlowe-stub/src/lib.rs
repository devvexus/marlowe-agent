//! The scripted stub M1's surfaces are built against.
//!
//! **No model, no memory, no network.** M1 consumes none of M0b, deliberately: the interface must
//! not be shaped by whatever the memory system happens to do today.
//!
//! This crate stands in for the daemon (ARCHITECTURE.md §6). It owns the time base, the session
//! state, and every value that appears on screen. `marlowe-surface` depends on it and not the
//! reverse, which is how §2.14's *"surfaces hold no state the daemon does not have"* becomes a
//! property of the dependency graph rather than a discipline: a surface with no way to produce
//! these values cannot invent one.

#![forbid(unsafe_code)]

pub mod amplitude;
pub mod frame_clock;
pub mod model;
pub mod script;
pub mod turn;

pub use amplitude::{Frame, LEVELS, SAMPLES};
pub use frame_clock::Clock;
pub use model::{
    Ambient, BlastRadius, ControlStrip, Entry, Item, Pager, Picker, RiskTier, StatusBand,
    StatusState, Tab, Tone, ToolCall,
};
pub use script::Session;
pub use turn::{DegradedPath, Metric, ResultSummary, ToolLineState, TurnEvent};
