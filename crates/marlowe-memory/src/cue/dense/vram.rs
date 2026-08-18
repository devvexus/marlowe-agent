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

/// **What tier 3 must LEAVE ALONE, in bytes — the VRAM priority order, ADR-045 §4.**
///
/// The card is shared, and the sharing has an order that is not negotiable:
///
/// | tier | component | footprint here | fallback |
/// |---|---|---|---|
/// | **0** | **every other process on this machine** — a game, a browser decoding video, the compositor | **unmeasurable in advance** | not ours to schedule |
/// | **1** | the language model (Ollama) — **`marlowe-red:9b` is the working model on this box** | **6.6 GB resident**, 100% GPU at 32k context | **none.** VRAM or nothing |
/// | **2** | the voice model | — | **none.** VRAM or nothing — **NOT BUILT, M7** |
/// | **3** | the embedder, the reranker, anything later | 0.8 GB per embedder session; see ADR-045's table | **CPU**, slower but correct |
///
/// **ONLY 9B MODELS ARE LOADED ON THIS MACHINE. 20B AND LARGER ARE OFF LIMITS** — a 20B is
/// ~12–13 GB and either evicts whatever is resident or fails to load, and either way it perturbs
/// every device reading taken around it. `marlowe-red:9b` is the constant every coexistence figure
/// in this project is measured against; keep it that way so the numbers stay comparable.
///
/// Tiers 1 and 2 have no fallback, so they have **first claim**. Tier 3 yields. *"Everything GPU
/// if it has space for it"* means space that is genuinely spare **after** the tiers above are
/// satisfied — not merely free at the instant a tier-3 component happened to load.
///
/// **TIER 0 IS THE ONE THAT CANNOT BE DERIVED, AND IT IS NOT HYPOTHETICAL.** On 2026-08-17, within
/// an hour of the reserve being specified, a game was launched by accident on this machine: it
/// crashed, it took a running `marlowe` process with it, and Ollama evicted its own model. Nobody
/// constructed that; it happened. **A development machine is a shared card by definition.** Tier 0
/// does not negotiate, does not yield, gives no warning, and cannot be measured before it
/// allocates — the only thing that can be done about it is to leave room. That is why the
/// one-spare-session rule exists on top of the reserve rather than instead of it: the reserve
/// covers the claims that can be named, and the spare covers the ones that cannot.
///
/// # Why this type exists at all, and it is a defect report
///
/// Before ADR-045, `auto` read `memory.free` and took what was there. **On an idle card the
/// embedder opened 8 sessions and held 4,647 MB.** Nothing was wrong locally — and if the language
/// model then needed to load, tier 3 had squatted on memory belonging to a higher priority. The
/// symptom would not have been an error from this process: **Ollama evicts its own models rather
/// than failing**, so it would have surfaced as the model reloading, in a log that cannot see us.
///
/// # The reserve is DERIVED, never a constant, and every branch says which one it took
///
/// `marlowe_net::io_concurrency()` is this project's pattern — one definition, every caller routed
/// through it, nothing keeping a second copy that would drift. This is that shape for device
/// memory. The authority for *how big tier 1 is* is Ollama itself, because Ollama is what runs it.
///
/// **NOTHING is reserved for tier 2.** Voice is M7 and does not exist, and reserving device memory
/// for a component nobody has built is a declared control with no reader — which `STATE.md`
/// already records twice. It is named in the table above so that whoever builds M7 finds the tier
/// list rather than discovering the contention.
///
/// # The known bound on this number, stated rather than hidden
///
/// `ollama list` reports the model's **on-disk** size. The resident footprint is larger by the KV
/// cache — `marlowe-red:9b` reads 5.8 GB on disk and 6.6 GB resident at 32k context, roughly
/// +14%. **So this reserve UNDERSTATES tier 1's claim**, and it understates it in the direction
/// that matters. Closing that needs `/api/show`'s `num_ctx` or a reading taken from `ollama ps`
/// after a warm load; neither is done here, and the gap is recorded rather than papered over with
/// a multiplier nobody measured.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Reserve<'a> {
    /// Yield to the tier-1 language model this build routes to, named rather than guessed. The
    /// caller supplies the name because `marlowe-memory` does not depend on `marlowe-provider`
    /// and inventing a second source of the routed model's identity is how two sides silently
    /// disagree. It borrows rather than owning a `&'static str` because the daemon's model is
    /// **switchable at runtime** (`--status` reports it, `switch_model` changes it), so a reserve
    /// pinned to a compile-time default would protect the wrong model the moment a user switched.
    ForTier1(&'a str),
    /// Reserve nothing. **Measurement only** — this is the pre-ADR-045 behaviour and it is kept
    /// so the defect above can be reproduced deliberately rather than described.
    None,
}

/// A reserve, with the branch that produced it. **Reported, never parsed.**
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReserveReading {
    pub bytes: u64,
    pub reason: String,
}

impl Reserve<'_> {
    /// Read the reserve. One process spawn at load, never on the scored path — the same cost
    /// `free_bytes` already accepts for `nvidia-smi`, and for the same reason: the tool that
    /// ships with the thing is the authority on the thing.
    pub fn read(self) -> ReserveReading {
        let name = match self {
            Reserve::None => {
                return ReserveReading {
                    bytes: 0,
                    reason: "no reserve was requested (measurement arm)".to_string(),
                }
            }
            Reserve::ForTier1(name) => name,
        };

        // Resident already? Then its bytes are ALREADY OUT of `memory.free` and reserving them a
        // second time would double-count -- which would read as a smaller card and quietly push
        // tier 3 onto CPU for a reason that does not exist.
        match ollama_lines(&["ps"]) {
            None => {
                return ReserveReading {
                    bytes: 0,
                    reason: "no `ollama` on this machine, so there is no tier 1 to yield to"
                        .to_string(),
                }
            }
            Some(lines) => {
                if lines.iter().any(|l| first_field(l) == Some(name)) {
                    return ReserveReading {
                        bytes: 0,
                        reason: format!(
                            "{name} is already resident; free device memory is already net of it"
                        ),
                    };
                }
            }
        }

        let Some(lines) = ollama_lines(&["list"]) else {
            return ReserveReading {
                bytes: 0,
                reason: "`ollama list` did not answer; tier 1's size is unknown".to_string(),
            };
        };
        for line in &lines {
            if first_field(line) != Some(name) {
                continue;
            }
            match parse_size(line) {
                Some(bytes) => {
                    return ReserveReading {
                        bytes,
                        reason: format!(
                            "reserving {} MB for tier 1 ({name}), which is not resident and has no \
                             CPU fallback",
                            bytes / (1024 * 1024)
                        ),
                    }
                }
                // Strict: an unparseable size is NOT silently zero. It is reported, and it is the
                // one branch where this returns a reserve it cannot justify -- so it says so.
                None => {
                    return ReserveReading {
                        bytes: 0,
                        reason: format!(
                            "`ollama list` names {name} but its size did not parse; NO RESERVE WAS \
                             APPLIED and tier 1 is unprotected"
                        ),
                    }
                }
            }
        }
        ReserveReading {
            bytes: 0,
            reason: format!("{name} is not installed, so tier 1 cannot run here either"),
        }
    }
}

/// `ollama <args>` split into non-header, non-empty lines, or `None` if it could not run.
fn ollama_lines(args: &[&str]) -> Option<Vec<String>> {
    let out = Command::new("ollama").args(args).output().ok()?;
    if !out.status.success() {
        return None;
    }
    Some(
        String::from_utf8(out.stdout)
            .ok()?
            .lines()
            .map(str::trim)
            .filter(|l| !l.is_empty() && !l.starts_with("NAME"))
            .map(str::to_string)
            .collect(),
    )
}

fn first_field(line: &str) -> Option<&str> {
    line.split_whitespace().next()
}

/// `NAME  ID  <n> <unit>  MODIFIED` -> bytes, or `None`.
///
/// Deliberately strict and deliberately positional-with-a-check: the unit must be one this
/// understands, or the whole reading fails. A permissive parser that fell through to bytes would
/// turn `18 GB` into 18 and reserve nothing while looking like it had.
fn parse_size(line: &str) -> Option<u64> {
    let parts: Vec<&str> = line.split_whitespace().collect();
    let value: f64 = parts.get(2)?.parse().ok()?;
    if !value.is_finite() || value < 0.0 {
        return None;
    }
    let unit = match *parts.get(3)? {
        "KB" => 1024f64,
        "MB" => 1024f64 * 1024.0,
        "GB" => 1024f64 * 1024.0 * 1024.0,
        "TB" => 1024f64 * 1024.0 * 1024.0 * 1024.0,
        _ => return None,
    };
    // Rounded UP. The number is already an understatement (no KV cache); rounding it down as well
    // would compound the error in the direction that hurts tier 1.
    Some((value * unit).ceil() as u64)
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
