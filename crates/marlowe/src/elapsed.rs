//! **The only place in the system that reads a real clock.**
//!
//! CONTRACTS.md section 4.5 is binding: *"on any path reachable from sections 4.1, 4.6, or
//! 4.7, the implementation MUST NOT read a system clock. Every timestamp is derived from the
//! `clock` supplied by the caller."* Staleness half-life is unmeasurable and every
//! decay-dependent result irreproducible if that is violated.
//!
//! And yet section 4.2 requires `cost.latency_ms`, self-reported by the implementation. So
//! exactly one real-clock read is legitimate, and the two rules coexist only if that read
//! cannot influence anything else.
//!
//! The reconciliation, stated precisely: **a monotonic elapsed duration is not a timestamp.**
//! It cannot be converted into one, it names no point in time, and nothing in memory can key
//! off it. Decay, activation, `silent_until` maturation and supersession recency all read the
//! supplied clock and are structurally unable to reach this module, because the only thing it
//! hands out is an `ElapsedMs` that goes straight into a cost block.
//!
//! Two mechanisms hold that:
//!
//! 1. [`ElapsedMs`] has no arithmetic with timestamps, no `From<ElapsedMs> for i64` that
//!    reads as a time, and one accessor whose name says where it belongs.
//! 2. A workspace test (`determinism_guard.rs`) bans `Instant`, `SystemTime` and `UNIX_EPOCH`
//!    everywhere except this file, by name. A second real-clock read cannot appear without
//!    appearing in that allowlist.
//!
//! The harness agrees this is the boundary: `canonical.py` excludes `latency_ms` from the
//! reproduction hash by a one-key allowlist, precisely because it is self-reported and varies
//! by nature. Everything else must match byte for byte.

use std::time::Instant;

/// A duration, in milliseconds, that may only be reported as cost.
///
/// Deliberately not `i64` and deliberately not convertible to one except through
/// [`ElapsedMs::as_cost_ms`], whose name is the documentation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ElapsedMs(u128);

impl ElapsedMs {
    /// The only way out. Named for its single legitimate destination.
    pub fn as_cost_ms(self) -> i64 {
        // Saturating rather than wrapping: a nonsense latency should read as implausibly
        // large, never as a small plausible one.
        i64::try_from(self.0).unwrap_or(i64::MAX)
    }
}

/// Times an operation, and hands back only a duration.
///
/// ```ignore
/// let stopwatch = Stopwatch::start();
/// let result = do_the_work(clock);          // `clock` is the caller's, not ours
/// let cost = stopwatch.stop().as_cost_ms(); // the one real-clock read
/// ```
pub struct Stopwatch(Instant);

impl Stopwatch {
    pub fn start() -> Self {
        Self(Instant::now())
    }

    pub fn stop(self) -> ElapsedMs {
        ElapsedMs(self.0.elapsed().as_millis())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn elapsed_is_reportable_as_cost() {
        let sw = Stopwatch::start();
        let ms = sw.stop().as_cost_ms();
        assert!(ms >= 0, "a duration is never negative");
    }

    #[test]
    fn elapsed_cannot_masquerade_as_a_timestamp() {
        // Structural, and asserted so it is a stated property rather than an accident: a
        // freshly measured elapsed duration is small, where any real epoch-millis timestamp
        // is enormous. If ElapsedMs ever gained a conversion that produced wall-clock time,
        // this is the assertion that would start failing.
        let ms = Stopwatch::start().stop().as_cost_ms();
        assert!(
            ms < 1_000_000,
            "an elapsed duration must not be a point in time; got {ms}"
        );
    }
}
