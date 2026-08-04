//! The gate-feature dump — the side channel `tools/fit_gate.py` reads.
//!
//! **A side file, never the wire.** The obvious alternative was to widen the §4.2 response
//! with the scores of everything considered; that would have been a fourth channel between
//! harness and implementation, which is precisely what the M0a/M0b split exists to prevent.
//! The dump is written under an explicit flag, read by one script, and the retrieval response
//! is byte-identical with or without it.
//!
//! One line per **scored candidate**, not per injected memory. The fit needs the negatives:
//! a calibration fit only on what was injected would be fit on its own output.
//!
//! Nothing derived from the answer key is written here. The join to gold happens in the
//! fitter, from §4.6's `written[].turn_id` mapping — the same join the harness itself uses.
//!
//! **In gated mode the dump also carries this build's own `score`, `calibrated_precision`,
//! `min_calibrated_precision` and `passes`.** That is not a convenience. When the frozen gate
//! abstains on every query — the outcome since Session B — the §4.2 response carries no
//! `injected` entries at all, so a precision/coverage curve read from the wire would be a curve
//! over an empty set. The alternative was to re-apply the artifact's curves in Python, which
//! would put a second implementation of the gate's arithmetic beside the real one with nothing
//! comparing them. Reading the implementation's own numbers has neither problem.
//!
//! `min_calibrated_precision` was added in Session D for exactly that reason: it is the ranking
//! key's second level, so without it the driver cannot reproduce the gate's own top-1 — which is
//! the number the session's floor condition is judged on.

use std::fs::{File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::Path;

use marlowe_memory::retrieve::ScoredCandidate;

pub struct FeatureDump {
    out: BufWriter<File>,
}

impl FeatureDump {
    pub fn create(path: &Path) -> std::io::Result<Self> {
        // Truncating, not appending. An append would silently merge two runs into one fit set,
        // and the resulting artifact would be reproducible from neither.
        let file = OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(path)?;
        Ok(Self {
            out: BufWriter::new(file),
        })
    }

    /// `gated` distinguishes the two modes. Under `--fit-mode` no gate is loaded, so the
    /// verdict fields are **omitted rather than written as zeros** — the same rule §4.2 applies
    /// to absent latency stages, and for the same reason: a zero reads as a measurement.
    pub fn write(
        &mut self,
        query_id: &str,
        candidates: &[ScoredCandidate<'_>],
        gated: bool,
    ) -> std::io::Result<()> {
        for candidate in candidates {
            let mut row = serde_json::Map::new();
            row.insert("query_id".into(), query_id.into());
            row.insert("memory_id".into(), candidate.entry.id.clone().into());
            // By name, not by position. A reorder of `FEATURE_NAMES` must not silently
            // transpose the fit -- the fitter reads these keys and asserts the set.
            for (name, value) in candidate.features.named() {
                row.insert(name.into(), serde_json::json!(value));
            }
            if gated {
                row.insert("score".into(), serde_json::json!(candidate.score));
                row.insert(
                    "calibrated_precision".into(),
                    serde_json::json!(candidate.calibrated_precision),
                );
                // The ranking key's second level. Emitted for the same reason
                // `calibrated_precision` is: without it the driver cannot reproduce the gate's
                // own ordering, and reproducing it in Python would put a second implementation
                // of the fusion beside the real one with nothing comparing them.
                row.insert(
                    "min_calibrated_precision".into(),
                    serde_json::json!(candidate.min_calibrated_precision),
                );
                row.insert("passes".into(), serde_json::json!(candidate.passes));
            }
            writeln!(self.out, "{}", serde_json::Value::Object(row))?;
        }
        Ok(())
    }

    pub fn flush(&mut self) -> std::io::Result<()> {
        self.out.flush()
    }
}
