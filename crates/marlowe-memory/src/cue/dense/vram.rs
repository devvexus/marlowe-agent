//! **How much device memory is free, right now, on the card this process would use.**
//!
//! This exists for one reason: the embedder wants GPU sessions, sessions are **one per worker**,
//! and the card is shared. On this machine `llama-server` holds ~11.5 GB of a 16.4 GB card, which
//! leaves ~4.8 GB — and that number is not a property of the hardware, it is a property of *what
//! the user happens to be running*. A worker count derived from the core count would open eight
//! sessions against whatever is left and take the model server down with it.
//!
//! # Why `nvidia-smi` rather than a CUDA binding
//!
//! `ort` 2.0.0-rc.10 exposes no device-memory query, and this crate has no CUDA FFI dependency.
//! `nvidia-smi` ships **with the driver**, so its absence is very close to "there is no NVIDIA
//! driver here" — which is exactly the case that should not get a GPU session anyway. The cost is
//! a process spawn (~40 ms measured on this machine), paid a handful of times at load and never on
//! the scored path.
//!
//! # This is a MEASUREMENT AT AN INSTANT, and the loader must treat it as one
//!
//! Between two reads, another process can allocate. Nothing here can prevent that, so the caller's
//! job is to keep real slack rather than to fill the card exactly — see
//! [`crate::cue::dense::embedder::Embedder::load_with_provider`], which requires a whole spare
//! session's worth of headroom before it opens another. A budget computed once at startup and
//! spent down without re-reading would be a *stale* artifact of the same family this project has
//! paid for repeatedly.
//!
//! # What it deliberately does NOT do
//!
//! It does not report which device ORT will choose, and it does not report node placement. The
//! first is a real gap on a multi-GPU host: [`free_bytes`] returns the **minimum** free across the
//! reported devices, which is the conservative reading rather than the correct one. The second is
//! not knowable from here at all — M0c Session L measured 13.6% of nodes still running on CPU
//! under a successfully registered CUDA session.

use std::process::Command;

/// Where a free-memory reading comes from.
///
/// **`Fixed` is not a configuration knob and nothing in the product constructs one.** It exists so
/// the exhaustion path can be driven deliberately: a test that waits for a real card to fill up is
/// a test that never runs. `Embedder::load_with_provider` reads this on every decision, so the
/// budget path a test exercises is the same code the product takes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Probe {
    /// Ask the driver.
    Device,
    /// Pretend this many bytes are free, and keep pretending. Measurement and tests only.
    Fixed(u64),
}

impl Probe {
    /// Free device memory in bytes, or `None` when there is no readable device.
    ///
    /// `None` and `Some(0)` are different answers and the caller must not collapse them: the first
    /// is "there is no GPU to measure", the second is "there is one and it is full".
    pub fn free_bytes(self) -> Option<u64> {
        match self {
            Probe::Device => free_bytes(),
            Probe::Fixed(n) => Some(n),
        }
    }
}

/// Free device memory in bytes, read from `nvidia-smi`, or `None`.
///
/// Returns the **minimum** across reported devices. On a single-GPU host that is the only reading;
/// on a multi-GPU host it is deliberately pessimistic, because nothing here knows which device ORT
/// will bind to and guessing wrong is the failure this module exists to prevent.
pub fn free_bytes() -> Option<u64> {
    let out = Command::new("nvidia-smi")
        .args(["--query-gpu=memory.free", "--format=csv,noheader,nounits"])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let text = String::from_utf8(out.stdout).ok()?;
    // MiB, one line per device. Parsed strictly: a line that does not parse makes the whole
    // reading `None` rather than silently shrinking the device list, because a partial reading
    // would look like a small card and quietly disable the GPU.
    let mut min: Option<u64> = None;
    for line in text.lines().map(str::trim).filter(|l| !l.is_empty()) {
        let mib: u64 = line.parse().ok()?;
        let bytes = mib * 1024 * 1024;
        min = Some(min.map_or(bytes, |m: u64| m.min(bytes)));
    }
    min
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_fixed_probe_reports_exactly_what_it_was_given() {
        // The property the exhaustion test rests on: `Fixed` must not consult the device, or a
        // machine with a big idle card would silently pass a test about a full one.
        assert_eq!(Probe::Fixed(0).free_bytes(), Some(0));
        assert_eq!(Probe::Fixed(1234).free_bytes(), Some(1234));
    }

    #[test]
    fn zero_free_and_no_device_are_different_answers() {
        // Stated as a test because collapsing them is the obvious simplification and it is wrong:
        // `None` must mean CPU-because-there-is-no-card, `Some(0)` CPU-because-the-card-is-full,
        // and the loader reports which.
        assert_ne!(Probe::Fixed(0).free_bytes(), None);
    }

    #[test]
    fn the_device_reading_is_either_absent_or_plausible() {
        // Cannot assert a value -- the card is shared and the number moves. What it CAN assert is
        // that a successful read is not nonsense, which is what catches a units error: this
        // returns bytes, and an unconverted MiB reading would land under a megabyte.
        match free_bytes() {
            None => eprintln!("SKIP: no readable NVIDIA device on this machine"),
            Some(n) => assert!(
                n == 0 || n >= 1024 * 1024,
                "{n} bytes free is neither zero nor at least a megabyte -- units are wrong"
            ),
        }
    }
}
