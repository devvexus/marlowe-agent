//! The frozen gate — HP1.
//!
//! Three properties, all of them load-bearing:
//!
//! 1. **Weights are a build-time artifact**, fit offline on LongMemEval gold evidence. Nothing
//!    here learns at runtime and there is no code path that could.
//! 2. **Features are user-specific even though weights are not** — see [`features`].
//! 3. **The threshold is expressed in calibrated-precision units, not raw score.** An isotonic
//!    curve maps score → predicted precision, so [`THRESHOLD`] = 0.95 means *predicted
//!    precision ≥ 0.95*, which is what makes the operating point portable across profiles.
//!
//! **There is no default gate.** Every failure below is a load-time error naming the file and
//! the command that regenerates it. CLAUDE.md: *"Prefer a load-time error to a sensible
//! default."* A permissive fallback here would be the worst instance of that pattern in the
//! project — a run would report `frozen-v1` while scoring with weights nobody fit.

pub mod features;

use std::collections::BTreeMap;

use serde::Deserialize;

pub use features::{FeatureVector, FEATURE_COUNT, FEATURE_NAMES};

/// The stamp a **calibrated** gate puts on `§4.2 gate.version`.
///
/// Never produced without a loaded, validated artifact. Asserted by test.
pub const GATE_VERSION: &str = "frozen-v1";

/// The stamp the feature-dump mode puts on `§4.2 gate.version`.
///
/// Same discipline as Session A's `ungated-v0`: a mode that computed features but calibrated
/// nothing must not be stampable as one that gated. A report reading `gate.version` has to be
/// able to tell which of the three states produced it.
pub const FIT_ONLY_VERSION: &str = "uncalibrated-fit-only";

/// K1's operating point, in calibrated-precision units.
///
/// **Frozen.** ROADMAP M10 is the only milestone that may move an operating point, and only by
/// beating this baseline. Lowering it because a run injected nothing is the tuning HP1 exists
/// to forbid — a low number at 0.95 is a result about the cue set.
pub const THRESHOLD: f32 = 0.95;

/// The artifact, embedded at compile time.
///
/// `include_str!` means a missing file is a **compile** error rather than a runtime one, and a
/// released binary can never be separated from the weights it was measured with.
const ARTIFACT_JSON: &str = include_str!("../../artifacts/gate-frozen-v1.json");

const ARTIFACT_PATH: &str = "crates/marlowe-memory/artifacts/gate-frozen-v1.json";

#[derive(Debug, thiserror::Error)]
pub enum GateError {
    #[error(
        "{ARTIFACT_PATH} does not parse: {0}. The gate has no default weights; fix or \
         regenerate the artifact with `python tools/fit_gate.py`"
    )]
    Unparseable(#[from] serde_json::Error),

    #[error(
        "{ARTIFACT_PATH} is in state {found:?} and carries no fitted weights. This is the \
         committed placeholder, not a gate. Run `python tools/preregister_split.py` then \
         `python tools/fit_gate.py` and rebuild. Refusing to run rather than inventing weights"
    )]
    Unfitted { found: String },

    #[error(
        "{ARTIFACT_PATH} is fitted but omits {field:?}. A fitted artifact missing a field is \
         corrupt, not partial"
    )]
    MissingField { field: &'static str },

    #[error(
        "{ARTIFACT_PATH} declares features {found:?}; this build extracts {expected:?}. The \
         weights were fit against a different feature vector and applying them would score \
         each value with the wrong coefficient"
    )]
    FeatureNamesDisagree {
        found: Vec<String>,
        expected: Vec<String>,
    },

    #[error(
        "{ARTIFACT_PATH} carries {found} weights for {expected} features. Silently zipping \
         the shorter of the two is how a feature ends up unweighted with nothing observing it"
    )]
    WeightCountDisagrees { found: usize, expected: usize },

    #[error(
        "{ARTIFACT_PATH} pins {feature:?} to zero but gives it weight {weight}. A pinned \
         weight that is not zero is a coefficient someone intended to be inert and is not"
    )]
    PinnedWeightNotZero { feature: String, weight: f32 },

    #[error(
        "{ARTIFACT_PATH} pins unknown feature {feature:?} to zero. It matches no name in this \
         build's feature vector, so the pin protects nothing"
    )]
    PinnedFeatureUnknown { feature: String },

    #[error(
        "{ARTIFACT_PATH}'s isotonic curve is not monotone at breakpoint {index}: precision \
         goes {previous} -> {current}. An isotonic curve that decreases is a corrupt fit, and \
         reading a threshold off it would give a precision the fit never predicted"
    )]
    CurveNotMonotone {
        index: usize,
        previous: f32,
        current: f32,
    },

    #[error(
        "{ARTIFACT_PATH}'s isotonic breakpoints are not sorted by score at index {index}: \
         {previous} -> {current}. The lookup is a binary search and would return the wrong bin"
    )]
    CurveNotSorted {
        index: usize,
        previous: f32,
        current: f32,
    },

    #[error("{ARTIFACT_PATH}'s isotonic curve is empty; there is nothing to calibrate against")]
    CurveEmpty,

    #[error(
        "{ARTIFACT_PATH} declares threshold {found}, this build's operating point is \
         {THRESHOLD}. The threshold is frozen under HP1 and M10 is the only milestone that may \
         move it"
    )]
    ThresholdDisagrees { found: f32 },
}

/// The artifact as it sits on disk.
///
/// Fit-specific fields are `Option` **only** so the committed placeholder parses. Every one of
/// them is required by [`FrozenGate::load`] when `state` is `fitted`, and the error names the
/// missing field. The provenance fields are carried so a gate and the split it was fit under
/// travel together — an artifact whose `split_digest` disagrees with `tools/split.json` is a
/// visible mismatch instead of a number nobody can reproduce.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GateArtifact {
    pub state: String,
    pub note: String,
    pub version: Option<String>,
    pub threshold: Option<f32>,
    pub feature_names: Option<Vec<String>>,
    pub weights: Option<Vec<f32>>,
    pub bias: Option<f32>,
    /// feature name -> why its weight is pinned to zero. See [`FrozenGate::load`].
    pub pinned_zero_weights: Option<BTreeMap<String, String>>,
    /// Ascending `[score_upper, precision]` pairs.
    pub isotonic_breakpoints: Option<Vec<[f32; 2]>>,
    pub corpus: Option<String>,
    pub corpus_variant: Option<String>,
    pub corpus_sha256: Option<String>,
    pub split_rule: Option<String>,
    pub split_digest: Option<String>,
    pub fit_cases: Option<u32>,
    pub heldout_cases: Option<u32>,
    pub fit_rows: Option<u32>,
    pub fit_positives: Option<u32>,
    pub fitted_at_clock_ms: Option<i64>,
}

/// A validated, frozen gate.
#[derive(Debug, Clone)]
pub struct FrozenGate {
    weights: [f32; FEATURE_COUNT],
    bias: f32,
    curve: Vec<[f32; 2]>,
    threshold: f32,
    provenance: Provenance,
}

/// What the gate was fit on. Reported by `--dev` diagnostics and by the scoring driver, so a
/// number and the artifact that produced it can always be joined.
#[derive(Debug, Clone)]
pub struct Provenance {
    pub corpus: String,
    pub corpus_variant: String,
    pub corpus_sha256: String,
    pub split_rule: String,
    pub split_digest: String,
    pub fit_cases: u32,
    pub heldout_cases: u32,
    pub pinned_zero_weights: BTreeMap<String, String>,
}

/// One candidate's gate verdict.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Verdict {
    /// The squashed linear score, in `[0, 1]`. On the wire as `injected[].score`.
    pub score: f32,
    /// The isotonic curve's prediction. On the wire as `injected[].calibrated_precision`.
    pub calibrated_precision: f32,
    pub passes: bool,
}

impl FrozenGate {
    /// Load and validate the embedded artifact. **The only constructor.**
    pub fn load() -> Result<Self, GateError> {
        Self::from_json(ARTIFACT_JSON)
    }

    pub fn from_json(json: &str) -> Result<Self, GateError> {
        let artifact: GateArtifact = serde_json::from_str(json)?;
        Self::from_artifact(artifact)
    }

    pub fn from_artifact(artifact: GateArtifact) -> Result<Self, GateError> {
        if artifact.state != "fitted" {
            return Err(GateError::Unfitted {
                found: artifact.state,
            });
        }

        fn required<T>(value: Option<T>, field: &'static str) -> Result<T, GateError> {
            value.ok_or(GateError::MissingField { field })
        }

        let threshold = required(artifact.threshold, "threshold")?;
        if (threshold - THRESHOLD).abs() > f32::EPSILON {
            return Err(GateError::ThresholdDisagrees { found: threshold });
        }

        // The check this module exists for. Names, in order, against the array that produced
        // the values -- not a count, which would pass a transposition.
        let names = required(artifact.feature_names, "feature_names")?;
        if names.len() != FEATURE_COUNT || names.iter().zip(FEATURE_NAMES).any(|(a, b)| a != b) {
            return Err(GateError::FeatureNamesDisagree {
                found: names,
                expected: FEATURE_NAMES.iter().map(|s| s.to_string()).collect(),
            });
        }

        let raw_weights = required(artifact.weights, "weights")?;
        if raw_weights.len() != FEATURE_COUNT {
            return Err(GateError::WeightCountDisagrees {
                found: raw_weights.len(),
                expected: FEATURE_COUNT,
            });
        }
        let mut weights = [0.0f32; FEATURE_COUNT];
        weights.copy_from_slice(&raw_weights);

        // Pinned-zero features. A feature with no variance in the fit split gets a coefficient
        // fit on noise -- inert today, and live the moment the feature starts varying, which
        // for `cue_agreement` is the day cue 2 lands. Pinning it is recorded here rather than
        // left as a comment so the inertness is enforced, not intended.
        let pinned = required(artifact.pinned_zero_weights, "pinned_zero_weights")?;
        for (feature, _why) in &pinned {
            let index = FEATURE_NAMES
                .iter()
                .position(|n| n == feature)
                .ok_or_else(|| GateError::PinnedFeatureUnknown {
                    feature: feature.clone(),
                })?;
            if weights[index] != 0.0 {
                return Err(GateError::PinnedWeightNotZero {
                    feature: feature.clone(),
                    weight: weights[index],
                });
            }
        }

        let curve = required(artifact.isotonic_breakpoints, "isotonic_breakpoints")?;
        if curve.is_empty() {
            return Err(GateError::CurveEmpty);
        }
        for i in 1..curve.len() {
            if curve[i][0] < curve[i - 1][0] {
                return Err(GateError::CurveNotSorted {
                    index: i,
                    previous: curve[i - 1][0],
                    current: curve[i][0],
                });
            }
            if curve[i][1] < curve[i - 1][1] {
                return Err(GateError::CurveNotMonotone {
                    index: i,
                    previous: curve[i - 1][1],
                    current: curve[i][1],
                });
            }
        }

        Ok(Self {
            weights,
            bias: required(artifact.bias, "bias")?,
            curve,
            threshold,
            provenance: Provenance {
                corpus: required(artifact.corpus, "corpus")?,
                corpus_variant: required(artifact.corpus_variant, "corpus_variant")?,
                corpus_sha256: required(artifact.corpus_sha256, "corpus_sha256")?,
                split_rule: required(artifact.split_rule, "split_rule")?,
                split_digest: required(artifact.split_digest, "split_digest")?,
                fit_cases: required(artifact.fit_cases, "fit_cases")?,
                heldout_cases: required(artifact.heldout_cases, "heldout_cases")?,
                pinned_zero_weights: pinned,
            },
        })
    }

    pub fn threshold(&self) -> f32 {
        self.threshold
    }

    pub fn provenance(&self) -> &Provenance {
        &self.provenance
    }

    /// The frozen linear combination, squashed into `[0, 1]`.
    ///
    /// The logistic is not there for probability semantics — the isotonic curve supplies those.
    /// It is there because the harness stratifies its human-label sample by **gate-score
    /// decile** (`decile_of` is `int(score * 10)`), so a raw logit on the wire would collapse
    /// the stratification into two buckets and the label set would lose support across its
    /// range. See ROADMAP's sampling rule.
    pub fn score(&self, f: &FeatureVector) -> f32 {
        let mut z = self.bias as f64;
        for (i, value) in f.as_slice().iter().enumerate() {
            z += self.weights[i] as f64 * *value as f64;
        }
        (1.0 / (1.0 + (-z).exp())) as f32
    }

    /// Isotonic lookup: score → predicted precision.
    ///
    /// Below the first breakpoint returns the first block's precision; above the last returns
    /// the last block's. Both are the fit's own predictions at the extremes rather than
    /// extrapolations — isotonic regression is a step function and does not extrapolate.
    pub fn calibrate(&self, score: f32) -> f32 {
        let index = self.curve.partition_point(|bp| bp[0] < score);
        let index = index.min(self.curve.len() - 1);
        self.curve[index][1]
    }

    pub fn judge(&self, f: &FeatureVector) -> Verdict {
        let score = self.score(f);
        let calibrated_precision = self.calibrate(score);
        Verdict {
            score,
            calibrated_precision,
            passes: calibrated_precision >= self.threshold,
        }
    }

    /// The highest precision this curve predicts anywhere.
    ///
    /// Reported when the gate abstains everywhere, which is the anticipated single-cue
    /// outcome: it distinguishes *"nothing scored well today"* from *"this cue set cannot
    /// reach the operating point at all"*, and only the second is a statement about the design.
    pub fn max_calibrated_precision(&self) -> f32 {
        self.curve.last().map_or(0.0, |bp| bp[1])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fitted_json(extra: &str) -> String {
        format!(
            r#"{{
  "state": "fitted",
  "note": "test fixture",
  "version": "frozen-v1",
  "threshold": 0.95,
  "feature_names": ["lexical_bm25", "effective_trust", "fidelity", "cue_agreement"],
  "weights": [4.0, 0.0, 0.0, 0.0],
  "bias": -3.0,
  "pinned_zero_weights": {{"cue_agreement": "constant until cue 2"}},
  "isotonic_breakpoints": [[0.2, 0.1], [0.5, 0.4], [0.8, 0.97]],
  "corpus": "longmemeval-s",
  "corpus_variant": "cleaned",
  "corpus_sha256": "abc",
  "split_rule": "test",
  "split_digest": "def",
  "fit_cases": 250,
  "heldout_cases": 250,
  "fit_rows": 1000,
  "fit_positives": 10,
  "fitted_at_clock_ms": 1780000000000{extra}
}}"#
        )
    }

    #[test]
    fn the_committed_artifact_is_whatever_it_says_it_is() {
        // Not an assertion about fitted-ness: this test passes before and after the fit, and
        // what it proves is that the embedded file parses and that `load` agrees with its own
        // declared state. A parse failure here is a compile-adjacent breakage worth catching.
        let artifact: GateArtifact = serde_json::from_str(ARTIFACT_JSON).expect("artifact parses");
        match artifact.state.as_str() {
            "fitted" => {
                let gate = FrozenGate::load().expect("a fitted artifact must load");
                assert_eq!(gate.threshold(), THRESHOLD);
            }
            "unfitted" => {
                assert!(matches!(FrozenGate::load(), Err(GateError::Unfitted { .. })));
            }
            other => panic!("unknown artifact state {other:?}"),
        }
    }

    #[test]
    fn an_unfitted_artifact_is_refused_rather_than_defaulted() {
        let json = r#"{"state": "unfitted", "note": "placeholder"}"#;
        let err = FrozenGate::from_json(json).unwrap_err();
        assert!(matches!(err, GateError::Unfitted { .. }));
        // The message has to say how to fix it: this is the error a fresh clone hits.
        assert!(err.to_string().contains("tools/fit_gate.py"), "{err}");
    }

    #[test]
    fn reordered_feature_names_are_refused() {
        let json = fitted_json("").replace(
            r#"["lexical_bm25", "effective_trust", "fidelity", "cue_agreement"]"#,
            r#"["effective_trust", "lexical_bm25", "fidelity", "cue_agreement"]"#,
        );
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::FeatureNamesDisagree { .. })
        ));
    }

    #[test]
    fn a_wrong_weight_count_is_refused_rather_than_zipped_short() {
        let json = fitted_json("").replace("[4.0, 0.0, 0.0, 0.0]", "[4.0, 0.0, 0.0]");
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::WeightCountDisagrees { found: 3, expected: 4 })
        ));
    }

    #[test]
    fn a_pinned_weight_that_is_not_zero_is_refused() {
        // The hazard the pin exists for: a coefficient fit on a constant feature is noise, and
        // it becomes load-bearing the moment the feature starts varying.
        let json = fitted_json("").replace("[4.0, 0.0, 0.0, 0.0]", "[4.0, 0.0, 0.0, 0.7]");
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::PinnedWeightNotZero { .. })
        ));
    }

    #[test]
    fn pinning_a_feature_this_build_does_not_have_is_refused() {
        let json = fitted_json("").replace(
            r#"{"cue_agreement": "constant until cue 2"}"#,
            r#"{"recency": "not a feature here"}"#,
        );
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::PinnedFeatureUnknown { .. })
        ));
    }

    #[test]
    fn a_non_monotone_curve_is_refused() {
        let json = fitted_json("").replace("[0.5, 0.4]", "[0.5, 0.05]");
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::CurveNotMonotone { .. })
        ));
    }

    #[test]
    fn an_unsorted_curve_is_refused() {
        let json = fitted_json("").replace("[[0.2, 0.1], [0.5, 0.4]", "[[0.6, 0.1], [0.5, 0.4]");
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::CurveNotSorted { .. })
        ));
    }

    #[test]
    fn a_moved_threshold_is_refused() {
        // HP1's freeze, enforced. Lowering the operating point to make a run inject something
        // is the exact tuning the freeze exists to forbid, and it cannot be done by editing
        // the artifact alone.
        let json = fitted_json("").replace("\"threshold\": 0.95", "\"threshold\": 0.6");
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::ThresholdDisagrees { .. })
        ));
    }

    #[test]
    fn a_missing_field_names_itself() {
        let json = fitted_json("").replace("\"bias\": -3.0,", "");
        let err = FrozenGate::from_json(&json).unwrap_err();
        assert!(matches!(err, GateError::MissingField { field: "bias" }), "{err}");
    }

    #[test]
    fn isotonic_lookup_hits_the_right_block() {
        let gate = FrozenGate::from_json(&fitted_json("")).unwrap();
        assert_eq!(gate.calibrate(0.0), 0.1, "below the first breakpoint");
        assert_eq!(gate.calibrate(0.2), 0.1, "at a breakpoint, inclusive");
        assert_eq!(gate.calibrate(0.35), 0.4, "between breakpoints");
        assert_eq!(gate.calibrate(0.8), 0.97);
        assert_eq!(gate.calibrate(1.0), 0.97, "above the last breakpoint");
        assert_eq!(gate.max_calibrated_precision(), 0.97);
    }

    #[test]
    fn the_threshold_is_read_in_calibrated_units_not_score_units() {
        // The property HP1 property 3 turns on. A candidate with a high raw score but a
        // calibrated precision under 0.95 must NOT pass -- if the comparison were against
        // `score` the operating point would stop being portable across profiles.
        let gate = FrozenGate::from_json(&fitted_json("")).unwrap();

        let low = FeatureVector([0.05, 1.0, 1.0, 1.0]);
        let high = FeatureVector([0.99, 1.0, 1.0, 1.0]);

        let low_v = gate.judge(&low);
        assert!(!low_v.passes);
        assert!(low_v.calibrated_precision < THRESHOLD);

        let high_v = gate.judge(&high);
        assert!(high_v.score > low_v.score, "the score moved with the feature");
        assert!(high_v.passes, "{high_v:?}");
        assert!(high_v.calibrated_precision >= THRESHOLD);
    }

    #[test]
    fn a_pinned_feature_cannot_move_the_score() {
        let gate = FrozenGate::from_json(&fitted_json("")).unwrap();
        let with = FeatureVector([0.5, 1.0, 1.0, 1.0]);
        let without = FeatureVector([0.5, 1.0, 1.0, 0.0]);
        assert_eq!(gate.score(&with), gate.score(&without));
    }

    #[test]
    fn scoring_is_deterministic() {
        let gate = FrozenGate::from_json(&fitted_json("")).unwrap();
        let f = FeatureVector([0.37, 1.0, 1.0, 1.0]);
        assert_eq!(gate.judge(&f), gate.judge(&f));
    }

    #[test]
    fn the_two_stamps_are_distinguishable() {
        // A report reading `gate.version` must be able to tell a calibrated run from a
        // feature-dump run from Session A's ungated run. Three states, three strings.
        assert_ne!(GATE_VERSION, FIT_ONLY_VERSION);
        assert_ne!(GATE_VERSION, crate::retrieve::UNGATED_VERSION);
        assert_ne!(FIT_ONLY_VERSION, crate::retrieve::UNGATED_VERSION);
    }
}
