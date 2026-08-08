//! CONTRACTS.md §5's `RunControl`.
//!
//! **M2 is ephemeral: the parent blocks, the child returns, the child dies with the parent.**
//! The trait is stated in full now so M3 extends it rather than replaces it, and the two
//! methods M2 cannot honour say so **by name** instead of succeeding quietly.
//!
//! A no-op `resume` would be the worst available shape: a durable-run control plane whose
//! resume path returns `Ok(())` and does nothing is a K5 failure that reports as a pass.

use std::collections::VecDeque;

use crate::driver::{Control, SteerMessage};
use crate::run::RunId;

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ResumeError {
    #[error(
        "run {run} cannot be resumed: this build spawns ephemerally, so there is no durable \
         checkpoint to resume from. Durable runs are M3 (K5)"
    )]
    NotDurable { run: RunId },
}

/// The control plane. `spawn` is absent on purpose: at M2 a spawn is the loop re-entering
/// itself (see `engine::Engine::spawn`), and a `spawn` method here would be a second entry
/// point into run creation that M3's scheduler would then have to unify.
pub trait RunControl {
    fn steer(&mut self, run: RunId, guidance: SteerMessage);
    fn cancel(&mut self, run: RunId);
    fn resume(&mut self, run: RunId) -> Result<(), ResumeError>;
}

/// The M2 implementation: steering and cancellation for the run the user is watching.
#[derive(Debug, Default)]
pub struct EphemeralControl {
    steers: VecDeque<SteerMessage>,
    interrupts: VecDeque<String>,
    cancelled: bool,
}

impl EphemeralControl {
    pub fn new() -> Self {
        Self::default()
    }

    /// Queue guidance for the next iteration boundary. Ordered, and never applied mid-tool-call.
    pub fn push_steer(&mut self, steer: SteerMessage) {
        self.steers.push_back(steer);
    }

    pub fn push_interrupt(&mut self, text: impl Into<String>) {
        self.interrupts.push_back(text.into());
    }
}

impl Control for EphemeralControl {
    fn cancelled(&self) -> bool {
        self.cancelled
    }

    fn take_steer(&mut self) -> Option<SteerMessage> {
        self.steers.pop_front()
    }

    fn take_interrupt(&mut self) -> Option<String> {
        self.interrupts.pop_front()
    }
}

impl RunControl for EphemeralControl {
    fn steer(&mut self, _run: RunId, guidance: SteerMessage) {
        self.push_steer(guidance);
    }

    fn cancel(&mut self, _run: RunId) {
        self.cancelled = true;
    }

    fn resume(&mut self, run: RunId) -> Result<(), ResumeError> {
        Err(ResumeError::NotDurable { run })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::driver::Urgency;

    #[test]
    fn resume_refuses_by_name_rather_than_succeeding_quietly() {
        let mut c = EphemeralControl::new();
        let run = RunId::from_name("r");
        let e = c.resume(run).unwrap_err();
        assert_eq!(e, ResumeError::NotDurable { run });
        assert!(e.to_string().contains("M3"), "the refusal must name where it lands: {e}");
    }

    #[test]
    fn steering_is_ordered() {
        let mut c = EphemeralControl::new();
        let run = RunId::from_name("r");
        c.steer(run, SteerMessage { text: "first".into(), urgency: Urgency::Advisory });
        c.steer(run, SteerMessage { text: "second".into(), urgency: Urgency::Advisory });
        assert_eq!(c.take_steer().unwrap().text, "first");
        assert_eq!(c.take_steer().unwrap().text, "second");
        assert!(c.take_steer().is_none());
    }
}
