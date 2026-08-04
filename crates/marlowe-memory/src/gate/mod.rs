//! The frozen gate — HP1.
//!
//! Three properties, all of them load-bearing:
//!
//! 1. **The calibration is a build-time artifact**, fit offline on LongMemEval gold evidence.
//!    Nothing here learns at runtime and there is no code path that could.
//! 2. **Features are user-specific even though the calibration is not** — see [`features`].
//! 3. **The threshold is expressed in calibrated-precision units, not raw score.** [`THRESHOLD`]
//!    = 0.95 means *predicted precision ≥ 0.95*, which is what makes the operating point
//!    portable across profiles.
//!
//! # The fusion, and why it changed in Session D
//!
//! Through `frozen-v2` the gate was **one logistic over the whole feature vector**, calibrated by
//! a single isotonic curve. Session C measured that combiner against its own inputs and it lost:
//! at top-1 on the held-out split it reached 0.4957 against **lexical alone at 0.5478**, while the
//! either-cue oracle reached 0.6522. It won at k=5 and k=10 and lost only at k=1 — which is where
//! the operating point reads.
//!
//! The mechanism is not mysterious. The fitted weights were `lexical 4.539 / dense 26.468` at bias
//! `-26.314`, because IRLS minimises log-loss over all 119,340 rows and dense is the better cue in
//! aggregate (R@5 0.830 vs 0.787) while lexical is the better cue *at rank 1* (0.548 vs 0.444).
//! **One global weight vector cannot be dense-shaped in the middle and lexical-shaped at the top.**
//!
//! `frozen-v3` therefore calibrates **each cue separately** and fuses by taking the **max**. There
//! is no weight vector left to trade, and calibration is the only thing that makes two cues
//! comparable: a BM25 score whose empirical gold rate is 0.6 outranks a cosine whose empirical
//! gold rate is 0.3, which raw-score linear fusion cannot express at any weighting.
//!
//! Two properties of this shape, and the second is the one people assume wrongly:
//!
//! * `max_i max(a_i, b_i) = max(max_i a_i, max_i b_i)`, so at top-1 the fused ranking always
//!   selects one of the two cues' **own** top-1 candidates. The oracle is its exact ceiling.
//! * **It is not structurally floor-safe.** Per candidate `max(p_lex, p_dense) ≥ p_lex`, so
//!   *coverage* at a fixed threshold is monotone — but ranking is relative and `max` reorders. On
//!   a query where lexical's top-1 is gold, dense's is not, and dense is the more confident of the
//!   two, this loses a hit lexical alone would have had. The floor is an empirical test, not a
//!   guarantee. See `runs/session-d/PREREGISTRATION.json`.
//!
//! **There is no default gate.** Every failure below is a load-time error naming the file and the
//! command that regenerates it. CLAUDE.md: *"Prefer a load-time error to a sensible default."* A
//! permissive fallback here would be the worst instance of that pattern in the project — a run
//! would report `frozen-v3` while scoring with a calibration nobody fit.

pub mod features;

use std::collections::BTreeMap;

use serde::Deserialize;

pub use features::{
    FeatureVector, CUE_COUNT, CUE_FEATURES, FEATURE_COUNT, FEATURE_NAMES,
};

/// The stamp a **calibrated** gate puts on `§4.2 gate.version`.
///
/// Never produced without a loaded, validated artifact. Asserted by test.
///
/// **`frozen-v3`, bumped in Session D.** The *combination function* changed, not the feature
/// vector: same five features, fused by max over per-cue calibrated precisions instead of by one
/// logistic. A run stamped `frozen-v2` was scored by a different function, and a report joining
/// numbers across the two without noticing would be comparing different systems. The v1 and v2
/// artifacts stay on disk as the provenance of Sessions B and C; neither is embedded.
pub const GATE_VERSION: &str = "frozen-v3";

/// The fusion this build implements, asserted against the artifact's own declaration.
///
/// The feature *names* are unchanged from v2, so `FeatureNamesDisagree` cannot catch a v2
/// calibration applied under v3 semantics. This constant is what does — and it is a separate
/// check rather than a comment because the failure it prevents is silent: a max-fusion binary
/// reading a logistic's weights would produce numbers for every query.
pub const FUSION: &str = "max-per-cue-calibrated-precision";

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
/// released binary can never be separated from the calibration it was measured with.
const ARTIFACT_JSON: &str = include_str!("../../artifacts/gate-frozen-v3.json");

const ARTIFACT_PATH: &str = "crates/marlowe-memory/artifacts/gate-frozen-v3.json";

#[derive(Debug, thiserror::Error)]
pub enum GateError {
    #[error(
        "{ARTIFACT_PATH} does not parse: {0}. The gate has no default calibration; fix or \
         regenerate the artifact with `python tools/fit_gate.py`"
    )]
    Unparseable(#[from] serde_json::Error),

    #[error(
        "{ARTIFACT_PATH} is in state {found:?} and carries no fitted calibration. This is the \
         committed placeholder, not a gate. Run `python tools/preregister_session_d.py` then \
         `python tools/fit_gate.py` and rebuild. Refusing to run rather than inventing a curve"
    )]
    Unfitted { found: String },

    #[error(
        "{ARTIFACT_PATH} is fitted but omits {field:?}. A fitted artifact missing a field is \
         corrupt, not partial"
    )]
    MissingField { field: &'static str },

    #[error(
        "{ARTIFACT_PATH} declares version {found:?}; this build is {GATE_VERSION}. The artifact \
         and the binary disagree about which gate this is"
    )]
    VersionDisagrees { found: String },

    #[error(
        "{ARTIFACT_PATH} declares fusion {found:?}; this build implements {FUSION}. The feature \
         NAMES are identical across v2 and v3, so this is the only check that catches a \
         calibration fit under a different combination function — and applying one under the \
         other would produce a number for every query with nothing observing the mismatch"
    )]
    FusionDisagrees { found: String },

    #[error(
        "{ARTIFACT_PATH} declares features {found:?}; this build extracts {expected:?}. The \
         calibration was fit against a different feature vector"
    )]
    FeatureNamesDisagree {
        found: Vec<String>,
        expected: Vec<String>,
    },

    #[error(
        "{ARTIFACT_PATH} declares cue features {found:?}; this build fuses {expected:?}. An \
         artifact naming fewer cues would produce a gate that silently stopped reading one, and \
         every downstream number would still be produced"
    )]
    CueFeaturesDisagree {
        found: Vec<String>,
        expected: Vec<String>,
    },

    #[error(
        "{ARTIFACT_PATH} declares cue {feature:?} but carries no curve for it. A cue with no \
         calibration cannot be fused and must not be silently dropped"
    )]
    CueCurveMissing { feature: String },

    #[error(
        "{ARTIFACT_PATH} carries a curve for {feature:?}, which is not one of this build's cue \
         features. It would never be read, so the fit it represents is not the fit that runs"
    )]
    CueCurveExtra { feature: String },

    #[error(
        "{ARTIFACT_PATH} does not declare {feature:?} inert, and it is not a cue either. Every \
         feature outside the fusion must carry a stated reason for being inert, so that a \
         feature dropping out of the gate is a decision on the record rather than an omission"
    )]
    NonCueFeatureNotInert { feature: String },

    #[error(
        "{ARTIFACT_PATH} declares {feature:?} inert, but it is one of this build's cue features. \
         A cue cannot be both fused and inert"
    )]
    InertFeatureIsACue { feature: String },

    #[error(
        "{ARTIFACT_PATH} declares unknown feature {feature:?} inert. It matches no name in this \
         build's feature vector, so the declaration protects nothing"
    )]
    InertFeatureUnknown { feature: String },

    #[error(
        "{ARTIFACT_PATH}'s curve for {cue:?} is not monotone at breakpoint {index}: precision \
         goes {previous} -> {current}. An isotonic curve that decreases is a corrupt fit, and \
         reading a threshold off it would give a precision the fit never predicted"
    )]
    CurveNotMonotone {
        cue: String,
        index: usize,
        previous: f32,
        current: f32,
    },

    #[error(
        "{ARTIFACT_PATH}'s curve for {cue:?} is not sorted by score at index {index}: \
         {previous} -> {current}. The lookup is a binary search and would return the wrong bin"
    )]
    CurveNotSorted {
        cue: String,
        index: usize,
        previous: f32,
        current: f32,
    },

    #[error(
        "{ARTIFACT_PATH}'s curve for {cue:?} has two blocks at the same score {value} (index \
         {index}). `partition_point` cannot resolve which block owns that score, so the lookup \
         would be ambiguous. Both cue scores have a large atom at 0 — candidates with no term \
         overlap for BM25, and the cosine floor for dense — so quantile bucketing produces this \
         unless the fitter pools buckets that share a score bound"
    )]
    CurveDuplicateBreakpoint {
        cue: String,
        index: usize,
        value: f32,
    },

    #[error(
        "{ARTIFACT_PATH}'s curve for {cue:?} predicts precision {value} at index {index}, which \
         is outside [0, 1]. Precision is a probability; a curve exceeding 1.0 would clear the \
         frozen threshold on arithmetic rather than on evidence"
    )]
    CurvePrecisionOutOfRange {
        cue: String,
        index: usize,
        value: f32,
    },

    #[error("{ARTIFACT_PATH}'s curve for {cue:?} is empty; there is nothing to calibrate against")]
    CurveEmpty { cue: String },

    #[error(
        "{ARTIFACT_PATH} declares threshold {found}, this build's operating point is \
         {THRESHOLD}. The threshold is frozen under HP1 and M10 is the only milestone that may \
         move it"
    )]
    ThresholdDisagrees { found: f32 },

    #[error(
        "{ARTIFACT_PATH} records floor_verdict {verdict:?}, and its calibration reaches \
         {reachable} against the frozen threshold of {THRESHOLD} — so this gate WOULD INJECT. A \
         fusion measured below its own best single cue must not decide what reaches the model. \
         Fit a shape that passes the floor, or re-measure this one and record the verdict with \
         `python tools/analyze_cue_overlap.py --run <RUN> --record-verdict`"
    )]
    FailedFloorWouldInject { verdict: String, reachable: f32 },

    #[error(
        "{ARTIFACT_PATH} records floor_verdict {found:?}, which is not one of \
         \"pass\" | \"fail\" | \"unmeasured\". An unrecognised verdict cannot be checked, and a \
         gate whose floor status is unreadable is a gate with no floor"
    )]
    FloorVerdictUnrecognised { found: String },
}

/// The artifact as it sits on disk.
///
/// Fit-specific fields are `Option` **only** so the committed placeholder parses. Every one of
/// them is required by [`FrozenGate::from_artifact`] when `state` is `fitted`, and the error names
/// the missing field.
///
/// `deny_unknown_fields` is what makes the v2/v3 boundary refuse in **both** directions: a v2
/// artifact hits unknown `weights` here, and a v3 artifact hits unknown `cue_curves` under a v2
/// binary. Neither can be loaded by the wrong build.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GateArtifact {
    pub state: String,
    pub note: String,
    pub version: Option<String>,
    pub fusion: Option<String>,
    pub threshold: Option<f32>,
    pub feature_names: Option<Vec<String>>,
    /// The subset of `feature_names` the fusion reads, in order.
    pub cue_features: Option<Vec<String>>,
    /// cue name -> ascending `[score_upper, precision]` pairs.
    pub cue_curves: Option<BTreeMap<String, Vec<[f32; 2]>>>,
    /// feature name -> why it takes no part in the fusion.
    pub inert_features: Option<BTreeMap<String, String>>,
    /// `"pass" | "fail" | "unmeasured"` — the pre-registered floor condition's verdict for the
    /// shape this artifact implements. See [`FrozenGate::from_artifact`].
    pub floor_verdict: Option<String>,
    /// What the floor required, what was measured, and where it was read. Carried so the verdict
    /// travels with its evidence instead of being a bare word.
    pub floor_required: Option<f32>,
    pub floor_measured: Option<f32>,
    pub floor_read_from: Option<String>,
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

/// One cue's calibration.
#[derive(Debug, Clone)]
pub struct CueCurve {
    pub name: String,
    /// Position within [`FEATURE_NAMES`] — resolved once at load, never by name at score time.
    pub feature_index: usize,
    /// Ascending `[score_upper, precision]`, strictly increasing in score.
    pub curve: Vec<[f32; 2]>,
}

/// A validated, frozen gate.
#[derive(Debug, Clone)]
pub struct FrozenGate {
    cues: Vec<CueCurve>,
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
    pub inert_features: BTreeMap<String, String>,
    /// `"pass" | "fail" | "unmeasured"`, with the evidence it was read from. Reported by `--dev`
    /// so a run and its floor status travel together.
    pub floor_verdict: String,
    pub floor_required: Option<f32>,
    pub floor_measured: Option<f32>,
    pub floor_read_from: Option<String>,
}

/// One candidate's gate verdict.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Verdict {
    /// The winning cue's **percentile within its own curve**, in `[0, 1]`. On the wire as
    /// `injected[].score`.
    ///
    /// **This changed meaning in Session D and the field name did not move**, which is exactly
    /// what a later reader would take for "unchanged". Through v2 it was a squashed linear
    /// logistic. It is now a percentile.
    ///
    /// The v2 doc comment justified the logistic by saying the harness stratifies its human-label
    /// sample by gate-*score* decile. **That was never true.** Both stratification call sites pass
    /// `calibrated_precision`, not `score`:
    /// `eval/src/marlowe_eval/metrics/precision.py:96` and
    /// `eval/src/marlowe_eval/labels/sampler.py:73`. `sampler.py:80` carries `score` onto
    /// `SampleDraw` and nothing reads it. The harness's *parameter* is named `score`
    /// (`precision.py:67`), which is how the claim survived — the name matched this field, so the
    /// dependency was inferred rather than checked.
    ///
    /// The reason it exists now is different and verifiable: it is the **third key of the ranking
    /// tiebreak**, and it has to be on the wire so a driver-side reader can reproduce the gate's
    /// ordering without re-implementing the curves in Python.
    pub score: f32,
    /// **max** over the per-cue calibrated precisions. On the wire as
    /// `injected[].calibrated_precision`, and the value the threshold is compared against.
    pub calibrated_precision: f32,
    /// **min** over the per-cue calibrated precisions. Never on the wire; the ranking key's
    /// second level.
    ///
    /// This is the agreement signal done correctly: among candidates the winning cue rates
    /// equally, prefer the one the *other* cue also rates highly. It is continuous, calibrated,
    /// and needs **no firing predicate** — which is precisely what keeps `cue_agreement_2cue`
    /// pinned. The tiebreak is a different mechanism, not that missing predicate, so the unpin
    /// condition is unchanged: cue 3, predicate pre-registered first.
    pub min_calibrated_precision: f32,
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

        let version = required(artifact.version, "version")?;
        if version != GATE_VERSION {
            return Err(GateError::VersionDisagrees { found: version });
        }

        // The check the v2/v3 boundary turns on. Feature names are IDENTICAL across the two, so
        // `FeatureNamesDisagree` cannot see this one.
        let fusion = required(artifact.fusion, "fusion")?;
        if fusion != FUSION {
            return Err(GateError::FusionDisagrees { found: fusion });
        }

        let threshold = required(artifact.threshold, "threshold")?;
        if (threshold - THRESHOLD).abs() > f32::EPSILON {
            return Err(GateError::ThresholdDisagrees { found: threshold });
        }

        // Names, in order, against the array that produced the values -- not a count, which
        // would pass a transposition.
        let names = required(artifact.feature_names, "feature_names")?;
        if names.len() != FEATURE_COUNT || names.iter().zip(FEATURE_NAMES).any(|(a, b)| a != b) {
            return Err(GateError::FeatureNamesDisagree {
                found: names,
                expected: FEATURE_NAMES.iter().map(|s| s.to_string()).collect(),
            });
        }

        // Same treatment for the cue subset, and for the same reason: an artifact naming one cue
        // would produce a gate that quietly stopped fusing the other.
        let cue_names = required(artifact.cue_features, "cue_features")?;
        if cue_names.len() != CUE_COUNT || cue_names.iter().zip(CUE_FEATURES).any(|(a, b)| a != b) {
            return Err(GateError::CueFeaturesDisagree {
                found: cue_names,
                expected: CUE_FEATURES.iter().map(|s| s.to_string()).collect(),
            });
        }

        let mut curves = required(artifact.cue_curves, "cue_curves")?;

        // Every cue needs a curve...
        let mut cues: Vec<CueCurve> = Vec::with_capacity(CUE_COUNT);
        for name in &cue_names {
            let curve = curves
                .remove(name)
                .ok_or_else(|| GateError::CueCurveMissing {
                    feature: name.clone(),
                })?;
            let feature_index =
                features::feature_index(name).ok_or_else(|| GateError::CueCurveExtra {
                    feature: name.clone(),
                })?;
            validate_curve(name, &curve)?;
            cues.push(CueCurve {
                name: name.clone(),
                feature_index,
                curve,
            });
        }
        // ...and nothing may carry a curve that is never read.
        if let Some(extra) = curves.keys().next() {
            return Err(GateError::CueCurveExtra {
                feature: extra.clone(),
            });
        }

        // Every feature outside the fusion must carry a stated reason. This replaces v2's
        // `PinnedWeightNotZero`: with no weight vector there is no coefficient to check, so the
        // property to enforce is COVERAGE -- a feature cannot leave the gate silently.
        let inert = required(artifact.inert_features, "inert_features")?;
        for feature in inert.keys() {
            if features::feature_index(feature).is_none() {
                return Err(GateError::InertFeatureUnknown {
                    feature: feature.clone(),
                });
            }
            if CUE_FEATURES.contains(&feature.as_str()) {
                return Err(GateError::InertFeatureIsACue {
                    feature: feature.clone(),
                });
            }
        }
        for name in FEATURE_NAMES {
            if !CUE_FEATURES.contains(&name) && !inert.contains_key(name) {
                return Err(GateError::NonCueFeatureNotInert {
                    feature: name.to_string(),
                });
            }
        }

        // ---------------------------------------------------------------- the floor interlock
        //
        // Session D's fusion FAILED its pre-registered floor: 0.4783 at top-1 against a required
        // 0.5478, worse than its own best single cue. It stays embedded only because its
        // calibration tops out at 0.3090 against a frozen 0.95, so it injects nothing and the
        // ranking never reaches the wire.
        //
        // **That argument expires exactly when the next session succeeds.** The whole goal of the
        // cascade is to make the gate inject, and the moment it does, a shape measured worse than
        // its own best input would start deciding what reaches the model. Leaving that to a
        // session remembering to swap the artifact is the failure mode this project keeps paying
        // for, so it is an interlock instead: a failed floor and a calibration that would inject
        // cannot coexist.
        //
        // The check is on `"fail"` only, not on `"unmeasured"`. Refusing "unmeasured" would
        // deadlock: the floor is read from a scoring run's feature dump, which requires this
        // gate to load in order to produce it. "unmeasured" is therefore permitted to load and is
        // visible in the artifact for a reader to act on.
        let verdict = required(artifact.floor_verdict, "floor_verdict")?;
        if !matches!(verdict.as_str(), "pass" | "fail" | "unmeasured") {
            return Err(GateError::FloorVerdictUnrecognised { found: verdict });
        }
        let reachable = cues
            .iter()
            .filter_map(|c| c.curve.last().map(|bp| bp[1]))
            .fold(0.0f32, f32::max);
        if verdict == "fail" && reachable >= threshold {
            return Err(GateError::FailedFloorWouldInject { verdict, reachable });
        }

        Ok(Self {
            cues,
            threshold,
            provenance: Provenance {
                corpus: required(artifact.corpus, "corpus")?,
                corpus_variant: required(artifact.corpus_variant, "corpus_variant")?,
                corpus_sha256: required(artifact.corpus_sha256, "corpus_sha256")?,
                split_rule: required(artifact.split_rule, "split_rule")?,
                split_digest: required(artifact.split_digest, "split_digest")?,
                fit_cases: required(artifact.fit_cases, "fit_cases")?,
                heldout_cases: required(artifact.heldout_cases, "heldout_cases")?,
                inert_features: inert,
                floor_verdict: verdict,
                floor_required: artifact.floor_required,
                floor_measured: artifact.floor_measured,
                floor_read_from: artifact.floor_read_from,
            },
        })
    }

    pub fn threshold(&self) -> f32 {
        self.threshold
    }

    pub fn provenance(&self) -> &Provenance {
        &self.provenance
    }

    pub fn cues(&self) -> &[CueCurve] {
        &self.cues
    }

    /// One cue's calibration lookup: cue score → `(predicted precision, percentile)`.
    ///
    /// Below the first breakpoint returns the first block; above the last returns the last. Both
    /// are the fit's own predictions at the extremes rather than extrapolations — isotonic
    /// regression is a step function and does not extrapolate.
    ///
    /// The percentile is `block index / (blocks - 1)`. Blocks are equal-count by construction
    /// (the fitter buckets by quantile, not by width), so this is a genuine percentile of the fit
    /// population rather than a position on an arbitrary grid.
    pub fn calibrate_cue(curve: &[[f32; 2]], value: f32) -> (f32, f32) {
        let index = curve.partition_point(|bp| bp[0] < value);
        let index = index.min(curve.len() - 1);
        let percentile = if curve.len() > 1 {
            index as f32 / (curve.len() - 1) as f32
        } else {
            0.0
        };
        (curve[index][1], percentile)
    }

    /// The fusion: **max over per-cue calibrated precisions**.
    ///
    /// Cue order is `CUE_FEATURES` order, and ties on both precision and percentile resolve to
    /// the first cue listed — so the verdict is a pure function of the features, with no
    /// dependence on map iteration order.
    pub fn judge(&self, f: &FeatureVector) -> Verdict {
        let values = f.as_slice();
        let mut max_p = f32::NEG_INFINITY;
        let mut min_p = f32::INFINITY;
        let mut winning_percentile = 0.0f32;

        for cue in &self.cues {
            let (p, percentile) = Self::calibrate_cue(&cue.curve, values[cue.feature_index]);
            if p > max_p || (p == max_p && percentile > winning_percentile) {
                max_p = p;
                winning_percentile = percentile;
            }
            if p < min_p {
                min_p = p;
            }
        }

        Verdict {
            score: winning_percentile,
            calibrated_precision: max_p,
            min_calibrated_precision: min_p,
            passes: max_p >= self.threshold,
        }
    }

    /// The highest precision this gate predicts anywhere — the max over the cues' top blocks.
    ///
    /// Reported when the gate abstains everywhere, which has been the outcome since Session B: it
    /// distinguishes *"nothing scored well today"* from *"this cue set cannot reach the operating
    /// point at all"*, and only the second is a statement about the design.
    ///
    /// **Under v3 the fusion does not enter this number.** It is a per-cue quantity, which is what
    /// makes it a clean read on how precise the best cue's most confident region is, undiluted by
    /// a joint logistic. That is the headline of Session D.
    pub fn max_calibrated_precision(&self) -> f32 {
        self.cues
            .iter()
            .filter_map(|c| c.curve.last().map(|bp| bp[1]))
            .fold(0.0f32, f32::max)
    }

    /// Per-cue top-block precision, for the calibration generalization pair.
    ///
    /// The standing check compares each cue's fit-split prediction against the held-out
    /// measurement, and it only exists if someone looks: a memorized calibration is invisible in
    /// precision, coverage, ASR and latency alike.
    pub fn max_calibrated_precision_per_cue(&self) -> Vec<(String, f32)> {
        self.cues
            .iter()
            .map(|c| (c.name.clone(), c.curve.last().map_or(0.0, |bp| bp[1])))
            .collect()
    }
}

/// Curve invariants, checked per cue so the error names which one.
fn validate_curve(cue: &str, curve: &[[f32; 2]]) -> Result<(), GateError> {
    if curve.is_empty() {
        return Err(GateError::CurveEmpty {
            cue: cue.to_string(),
        });
    }
    for (index, bp) in curve.iter().enumerate() {
        if !(0.0..=1.0).contains(&bp[1]) {
            return Err(GateError::CurvePrecisionOutOfRange {
                cue: cue.to_string(),
                index,
                value: bp[1],
            });
        }
    }
    for i in 1..curve.len() {
        if curve[i][0] < curve[i - 1][0] {
            return Err(GateError::CurveNotSorted {
                cue: cue.to_string(),
                index: i,
                previous: curve[i - 1][0],
                current: curve[i][0],
            });
        }
        // Strictly increasing, not merely non-decreasing. Two blocks at the same score make
        // `partition_point` ambiguous, and both cue scores have a large atom at 0.
        if curve[i][0] == curve[i - 1][0] {
            return Err(GateError::CurveDuplicateBreakpoint {
                cue: cue.to_string(),
                index: i,
                value: curve[i][0],
            });
        }
        if curve[i][1] < curve[i - 1][1] {
            return Err(GateError::CurveNotMonotone {
                cue: cue.to_string(),
                index: i,
                previous: curve[i - 1][1],
                current: curve[i][1],
            });
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fitted_json() -> String {
        r#"{
  "state": "fitted",
  "note": "test fixture",
  "version": "frozen-v3",
  "fusion": "max-per-cue-calibrated-precision",
  "threshold": 0.95,
  "feature_names": ["lexical_bm25", "dense_cosine", "effective_trust", "fidelity", "cue_agreement_2cue"],
  "cue_features": ["lexical_bm25", "dense_cosine"],
  "cue_curves": {
    "lexical_bm25": [[0.2, 0.1], [0.5, 0.4], [0.8, 0.97]],
    "dense_cosine": [[0.3, 0.05], [0.6, 0.2], [0.9, 0.5]]
  },
  "inert_features": {
    "effective_trust": "zero variance across the fit split",
    "fidelity": "zero variance across the fit split",
    "cue_agreement_2cue": "declared: needs a firing predicate for the dense cue"
  },
  "floor_verdict": "pass",
  "floor_required": 0.5478,
  "floor_measured": 0.6,
  "floor_read_from": "test fixture",
  "corpus": "longmemeval-s",
  "corpus_variant": "cleaned",
  "corpus_sha256": "abc",
  "split_rule": "test",
  "split_digest": "def",
  "fit_cases": 250,
  "heldout_cases": 250,
  "fit_rows": 1000,
  "fit_positives": 10,
  "fitted_at_clock_ms": 1780000000000
}"#
        .to_string()
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
                assert_eq!(gate.cues().len(), CUE_COUNT);
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

    // ------------------------------------------------------------------ the v2/v3 boundary

    #[test]
    fn a_v2_artifact_is_refused_by_its_own_extra_fields() {
        // The direction that matters most: v2 is a *fitted* artifact with plausible provenance,
        // and its feature names are IDENTICAL to v3's. Nothing but the schema catches it.
        let v2 = r#"{
  "state": "fitted", "note": "v2", "version": "frozen-v2", "threshold": 0.95,
  "feature_names": ["lexical_bm25", "dense_cosine", "effective_trust", "fidelity", "cue_agreement_2cue"],
  "weights": [4.53, 26.46, 0.0, 0.0, 0.0], "bias": -26.31,
  "pinned_zero_weights": {"fidelity": "constant"},
  "isotonic_breakpoints": [[0.5, 0.1], [1.0, 0.3176]],
  "corpus": "longmemeval-s", "corpus_variant": "cleaned", "corpus_sha256": "abc",
  "split_rule": "r", "split_digest": "d", "fit_cases": 251, "heldout_cases": 249,
  "fit_rows": 119340, "fit_positives": 452, "fitted_at_clock_ms": 0
}"#;
        let err = FrozenGate::from_json(v2).unwrap_err();
        assert!(matches!(err, GateError::Unparseable(_)), "{err}");
        assert!(err.to_string().contains("weights"), "{err}");
    }

    #[test]
    fn a_v2_fusion_declared_on_a_v3_schema_is_refused_by_name() {
        // Belt and braces for the same hazard: if someone hand-edited a v2 calibration into the
        // v3 schema, the feature names would still match and only `fusion` would catch it.
        let json = fitted_json().replace(
            r#""fusion": "max-per-cue-calibrated-precision""#,
            r#""fusion": "logistic-over-raw-scores""#,
        );
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::FusionDisagrees { .. })
        ));
    }

    #[test]
    fn a_wrong_version_is_refused() {
        let json = fitted_json().replace(r#""version": "frozen-v3""#, r#""version": "frozen-v2""#);
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::VersionDisagrees { .. })
        ));
    }

    // ------------------------------------------------------------------ feature / cue identity

    #[test]
    fn reordered_feature_names_are_refused() {
        let json = fitted_json().replace(
            r#"["lexical_bm25", "dense_cosine", "effective_trust", "fidelity", "cue_agreement_2cue"]"#,
            r#"["dense_cosine", "lexical_bm25", "effective_trust", "fidelity", "cue_agreement_2cue"]"#,
        );
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::FeatureNamesDisagree { .. })
        ));
    }

    #[test]
    fn dropping_a_cue_is_refused_rather_than_silently_fusing_one() {
        // The v3-specific hazard. A gate that fused only lexical would still produce a number
        // for every query, and every downstream metric would still be computed.
        let json = fitted_json()
            .replace(
                r#""cue_features": ["lexical_bm25", "dense_cosine"]"#,
                r#""cue_features": ["lexical_bm25"]"#,
            )
            .replace(r#",
    "dense_cosine": [[0.3, 0.05], [0.6, 0.2], [0.9, 0.5]]"#, "");
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::CueFeaturesDisagree { .. })
        ));
    }

    #[test]
    fn reordered_cue_features_are_refused() {
        let json = fitted_json().replace(
            r#""cue_features": ["lexical_bm25", "dense_cosine"]"#,
            r#""cue_features": ["dense_cosine", "lexical_bm25"]"#,
        );
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::CueFeaturesDisagree { .. })
        ));
    }

    #[test]
    fn a_cue_without_a_curve_is_refused() {
        let json = fitted_json().replace(
            r#""dense_cosine": [[0.3, 0.05], [0.6, 0.2], [0.9, 0.5]]"#,
            r#""fidelity": [[0.3, 0.05], [0.6, 0.2], [0.9, 0.5]]"#,
        );
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::CueCurveMissing { .. })
        ));
    }

    #[test]
    fn a_curve_that_is_never_read_is_refused() {
        let json = fitted_json().replace(
            r#""dense_cosine": [[0.3, 0.05], [0.6, 0.2], [0.9, 0.5]]"#,
            r#""dense_cosine": [[0.3, 0.05], [0.6, 0.2], [0.9, 0.5]],
    "effective_trust": [[0.5, 0.1]]"#,
        );
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::CueCurveExtra { .. })
        ));
    }

    // ------------------------------------------------------------------ inert-feature coverage

    #[test]
    fn a_non_cue_feature_with_no_stated_reason_is_refused() {
        // v2 checked that a pinned weight was zero. With no weight vector the property to
        // enforce is coverage: a feature cannot drop out of the gate without a reason on record.
        let json = fitted_json().replace(
            r#""fidelity": "zero variance across the fit split",
"#,
            "",
        );
        let err = FrozenGate::from_json(&json).unwrap_err();
        assert!(
            matches!(err, GateError::NonCueFeatureNotInert { ref feature } if feature == "fidelity"),
            "{err}"
        );
    }

    #[test]
    fn declaring_a_cue_inert_is_refused() {
        let json = fitted_json().replace(
            r#""effective_trust": "zero variance across the fit split","#,
            r#""lexical_bm25": "oops","#,
        );
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::InertFeatureIsACue { .. })
        ));
    }

    #[test]
    fn declaring_an_unknown_feature_inert_is_refused() {
        let json = fitted_json().replace(
            r#""effective_trust": "zero variance across the fit split","#,
            r#""recency": "not a feature here","#,
        );
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::InertFeatureUnknown { .. })
        ));
    }

    // ------------------------------------------------------------------ curve invariants

    #[test]
    fn a_non_monotone_curve_is_refused_and_names_its_cue() {
        let json = fitted_json().replace("[0.5, 0.4]", "[0.5, 0.05]");
        let err = FrozenGate::from_json(&json).unwrap_err();
        assert!(
            matches!(err, GateError::CurveNotMonotone { ref cue, .. } if cue == "lexical_bm25"),
            "{err}"
        );
    }

    #[test]
    fn an_unsorted_curve_is_refused() {
        let json = fitted_json().replace("[[0.2, 0.1], [0.5, 0.4]", "[[0.6, 0.1], [0.5, 0.4]");
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::CurveNotSorted { .. })
        ));
    }

    #[test]
    fn a_duplicate_breakpoint_is_refused() {
        // The hazard identified before the fit: both cue scores have a large atom at 0 -- BM25
        // for candidates with no term overlap, dense at the cosine floor -- so quantile bucketing
        // produces blocks sharing a score bound unless the fitter pools them. `partition_point`
        // cannot say which block owns that score, and a NOT-SORTED check using `<` would pass it.
        let json = fitted_json().replace("[[0.2, 0.1], [0.5, 0.4]", "[[0.2, 0.1], [0.2, 0.4]");
        let err = FrozenGate::from_json(&json).unwrap_err();
        assert!(
            matches!(err, GateError::CurveDuplicateBreakpoint { ref cue, .. } if cue == "lexical_bm25"),
            "{err}"
        );
    }

    #[test]
    fn a_precision_above_one_is_refused() {
        let json = fitted_json().replace("[0.8, 0.97]", "[0.8, 1.4]");
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::CurvePrecisionOutOfRange { .. })
        ));
    }

    #[test]
    fn an_empty_curve_is_refused() {
        let json = fitted_json().replace("[[0.3, 0.05], [0.6, 0.2], [0.9, 0.5]]", "[]");
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::CurveEmpty { .. })
        ));
    }

    #[test]
    fn a_moved_threshold_is_refused() {
        // HP1's freeze, enforced. Lowering the operating point to make a run inject something
        // is the exact tuning the freeze exists to forbid, and it cannot be done by editing
        // the artifact alone.
        let json = fitted_json().replace("\"threshold\": 0.95", "\"threshold\": 0.6");
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::ThresholdDisagrees { .. })
        ));
    }

    #[test]
    fn a_missing_field_names_itself() {
        let json = fitted_json().replace("\"corpus\": \"longmemeval-s\",", "");
        let err = FrozenGate::from_json(&json).unwrap_err();
        assert!(matches!(err, GateError::MissingField { field: "corpus" }), "{err}");
    }

    // ------------------------------------------------------------------ the fusion itself

    #[test]
    fn per_cue_lookup_hits_the_right_block() {
        let gate = FrozenGate::from_json(&fitted_json()).unwrap();
        let lex = &gate.cues()[0].curve;
        assert_eq!(FrozenGate::calibrate_cue(lex, 0.0).0, 0.1, "below the first breakpoint");
        assert_eq!(FrozenGate::calibrate_cue(lex, 0.2).0, 0.1, "at a breakpoint, inclusive");
        assert_eq!(FrozenGate::calibrate_cue(lex, 0.35).0, 0.4, "between breakpoints");
        assert_eq!(FrozenGate::calibrate_cue(lex, 0.8).0, 0.97);
        assert_eq!(FrozenGate::calibrate_cue(lex, 1.0).0, 0.97, "above the last breakpoint");
    }

    #[test]
    fn the_percentile_spans_the_unit_interval() {
        // It is the ranking key's third level, so it has to order candidates inside a tied block.
        let gate = FrozenGate::from_json(&fitted_json()).unwrap();
        let lex = &gate.cues()[0].curve;
        assert_eq!(FrozenGate::calibrate_cue(lex, 0.0).1, 0.0);
        assert_eq!(FrozenGate::calibrate_cue(lex, 0.35).1, 0.5);
        assert_eq!(FrozenGate::calibrate_cue(lex, 1.0).1, 1.0);
    }

    #[test]
    fn the_fusion_takes_the_max_and_reports_the_min() {
        let gate = FrozenGate::from_json(&fitted_json()).unwrap();
        // lexical 0.8 -> 0.97 ; dense 0.3 -> 0.05
        let f = FeatureVector([0.8, 0.3, 1.0, 1.0, 1.0]);
        let v = gate.judge(&f);
        assert_eq!(v.calibrated_precision, 0.97, "max over cues");
        assert_eq!(v.min_calibrated_precision, 0.05, "min over cues");
        assert!(v.passes);
    }

    #[test]
    fn the_weaker_cue_cannot_drag_the_verdict_down() {
        // The v2 defect, stated as a test. A strong lexical match must not be diluted by a weak
        // dense score -- which is exactly what a single weight vector did, and what cost the
        // combiner 0.052 at top-1 against lexical alone.
        let gate = FrozenGate::from_json(&fitted_json()).unwrap();
        let alone = gate.judge(&FeatureVector([0.8, 0.0, 1.0, 1.0, 1.0]));
        let with_weak_dense = gate.judge(&FeatureVector([0.8, 0.3, 1.0, 1.0, 1.0]));
        assert_eq!(
            alone.calibrated_precision, with_weak_dense.calibrated_precision,
            "a weak second cue must not lower the fused precision"
        );
    }

    #[test]
    fn either_cue_alone_can_carry_a_candidate() {
        // The complementarity the fusion exists to exploit: Session C measured lexical finding
        // gold dense misses in 20.9% of cases and dense finding gold lexical misses in 10.4%.
        let gate = FrozenGate::from_json(&fitted_json()).unwrap();
        let lexical_only = gate.judge(&FeatureVector([0.8, 0.0, 1.0, 1.0, 1.0]));
        assert_eq!(lexical_only.calibrated_precision, 0.97);
        // dense's curve tops out at 0.5 in this fixture, so it carries but does not pass
        let dense_only = gate.judge(&FeatureVector([0.0, 0.95, 1.0, 1.0, 1.0]));
        assert_eq!(dense_only.calibrated_precision, 0.5);
        assert!(!dense_only.passes);
    }

    #[test]
    fn the_threshold_is_read_in_calibrated_units_not_score_units() {
        // The property HP1 property 3 turns on. `score` is now a percentile, and a candidate at
        // the TOP percentile of a cue whose calibration never reaches 0.95 must still not pass.
        let gate = FrozenGate::from_json(&fitted_json()).unwrap();
        let top_of_dense = gate.judge(&FeatureVector([0.0, 1.0, 1.0, 1.0, 1.0]));
        assert_eq!(top_of_dense.score, 1.0, "the highest percentile its cue has");
        assert!(
            !top_of_dense.passes,
            "a perfect percentile on a cue that tops out at 0.5 predicted precision must not pass"
        );
    }

    #[test]
    fn an_inert_feature_cannot_move_the_verdict() {
        let gate = FrozenGate::from_json(&fitted_json()).unwrap();
        let with = FeatureVector([0.5, 0.4, 1.0, 1.0, 1.0]);
        let without = FeatureVector([0.5, 0.4, 0.0, 0.0, 0.0]);
        assert_eq!(gate.judge(&with), gate.judge(&without));
    }

    #[test]
    fn scoring_is_deterministic() {
        let gate = FrozenGate::from_json(&fitted_json()).unwrap();
        let f = FeatureVector([0.37, 0.62, 1.0, 1.0, 1.0]);
        assert_eq!(gate.judge(&f), gate.judge(&f));
    }

    #[test]
    fn max_calibrated_precision_is_the_best_cues_top_block() {
        let gate = FrozenGate::from_json(&fitted_json()).unwrap();
        assert_eq!(gate.max_calibrated_precision(), 0.97);
        let per_cue = gate.max_calibrated_precision_per_cue();
        assert_eq!(per_cue.len(), 2);
        assert_eq!(per_cue[0], ("lexical_bm25".to_string(), 0.97));
        assert_eq!(per_cue[1], ("dense_cosine".to_string(), 0.5));
    }

    // ------------------------------------------------------------------ the floor interlock

    #[test]
    fn a_failed_floor_loads_while_it_cannot_inject() {
        // Session D's actual situation, and the reason v3 ships at all: the shape failed its
        // floor, but its calibration tops out far below the frozen threshold, so it decides
        // nothing that reaches the model. The fixture's cues top out at 0.97 and 0.5, so drop
        // both under 0.95 to reproduce it.
        // 0.45, not something lower: the block below it predicts 0.4, and a curve that decreases
        // is refused by `CurveNotMonotone` before the floor interlock is ever reached.
        let json = fitted_json()
            .replace(r#""floor_verdict": "pass""#, r#""floor_verdict": "fail""#)
            .replace("[0.8, 0.97]", "[0.8, 0.45]");
        let gate = FrozenGate::from_json(&json).expect("a failed floor that cannot inject loads");
        assert!(gate.max_calibrated_precision() < THRESHOLD);
        assert_eq!(gate.provenance().floor_verdict, "fail");
    }

    #[test]
    fn a_failed_floor_that_would_inject_is_refused() {
        // **The interlock.** The fixture's lexical curve reaches 0.97, above the frozen 0.95, so
        // this gate would inject -- and its floor verdict says the shape ranks worse than its own
        // best single cue. Those two facts must not coexist in a loadable artifact.
        //
        // This is the check that stops Session D's scaffolding from surviving into the run that
        // makes the gate inject, without depending on anyone remembering to swap it.
        let json = fitted_json().replace(r#""floor_verdict": "pass""#, r#""floor_verdict": "fail""#);
        let err = FrozenGate::from_json(&json).unwrap_err();
        assert!(
            matches!(err, GateError::FailedFloorWouldInject { .. }),
            "{err}"
        );
        // The message must name the way out, like every other refusal here.
        assert!(err.to_string().contains("--record-verdict"), "{err}");
    }

    #[test]
    fn a_passing_floor_that_would_inject_loads() {
        // The interlock must not be a blanket ban on injecting gates -- that would make it fire
        // on the very shape it exists to let through.
        let gate = FrozenGate::from_json(&fitted_json()).unwrap();
        assert!(gate.max_calibrated_precision() >= THRESHOLD);
        assert_eq!(gate.provenance().floor_verdict, "pass");
    }

    #[test]
    fn an_unmeasured_floor_loads_because_refusing_it_would_deadlock() {
        // The floor is read from a scoring run's feature dump, which requires this gate to load
        // in order to produce it. Refusing "unmeasured" would make the measurement unreachable.
        let json = fitted_json().replace(r#""floor_verdict": "pass""#, r#""floor_verdict": "unmeasured""#);
        let gate = FrozenGate::from_json(&json).expect("unmeasured must load");
        assert_eq!(gate.provenance().floor_verdict, "unmeasured");
    }

    #[test]
    fn an_unrecognised_floor_verdict_is_refused() {
        let json = fitted_json().replace(r#""floor_verdict": "pass""#, r#""floor_verdict": "probably fine""#);
        assert!(matches!(
            FrozenGate::from_json(&json),
            Err(GateError::FloorVerdictUnrecognised { .. })
        ));
    }

    #[test]
    fn a_missing_floor_verdict_is_refused() {
        let json = fitted_json().replace(r#""floor_verdict": "pass",
"#, "");
        let err = FrozenGate::from_json(&json).unwrap_err();
        assert!(
            matches!(err, GateError::MissingField { field: "floor_verdict" }),
            "{err}"
        );
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
