//! Gate features — **deliberately artifact-free**.
//!
//! This module knows how to turn a candidate into numbers. It knows nothing about weights,
//! calibration, or a threshold. That separation is what makes the fit possible without a
//! bootstrap placeholder: `marlowe --dump-gate-features` runs *this* code and nothing in
//! `gate/mod.rs`, so there is never a moment where the binary needs a gate artifact in order
//! to produce the data the gate artifact is fit from.
//!
//! HP1 property 2: **features are user-specific even though weights are not.** Everything here
//! reads this profile's own data; the weights that combine them are a build-time constant.

use marlowe_contract::{Fidelity, TrustClass};

use crate::cue::lexical;
use crate::entry::MemoryEntry;

/// The feature vector's field order, and the **single source of that order**.
///
/// **v2, Session C.** `cue_agreement` was renamed to `cue_agreement_2cue` because its *meaning*
/// changed when the dense cue landed: a 0/1 indicator became a count over two cues. A weight fit
/// under one meaning and applied under the other is a live mismatch that nothing downstream
/// would observe, so the rename converts it into a load-time refusal by machinery that already
/// existed. The denominator is in the name on purpose — cue 3 forces another rename, another
/// refusal, and another deliberate re-fit.
///
/// `FrozenGate::load` asserts this array against the artifact's declared `feature_names`. That
/// check is the most valuable test in this module: weights and features living in two places
/// with only one of them checked is the exact shape of every unobservable mismatch this
/// project has paid for. A reordered array with no name check would silently apply the trust
/// weight to the BM25 value and every test would stay green.
pub const FEATURE_NAMES: [&str; 5] = [
    "lexical_bm25",
    "dense_cosine",
    "effective_trust",
    "fidelity",
    "cue_agreement_2cue",
];

pub const FEATURE_COUNT: usize = FEATURE_NAMES.len();

/// The features the **fusion** reads, in order — a subset of [`FEATURE_NAMES`].
///
/// **Session D.** The gate no longer combines the whole vector with one weight vector. It
/// calibrates each *cue* separately and fuses by taking the max, so the artifact carries one
/// isotonic curve per name here and nothing at all for the rest.
///
/// Pinned in Rust rather than left for the artifact to declare, for the reason that governs the
/// `feature_names` check one line up: an artifact that named only `lexical_bm25` here would
/// produce a gate that silently stopped reading the dense cue, and every downstream number would
/// still be produced. `FrozenGate::load` asserts the artifact's `cue_features` against this array
/// by name **and order**, so a cue can only leave the fusion by editing this file.
///
/// Cue 3 extends this array, which — together with the `cue_agreement_2cue` rename — makes
/// adding a cue a deliberate two-line change that forces a re-fit rather than a silent one.
pub const CUE_FEATURES: [&str; 2] = ["lexical_bm25", "dense_cosine"];

pub const CUE_COUNT: usize = CUE_FEATURES.len();

/// The position of a cue feature within [`FEATURE_NAMES`].
///
/// Returns `None` for a name this build does not extract, which `FrozenGate::load` turns into a
/// refusal rather than a skipped cue.
pub fn feature_index(name: &str) -> Option<usize> {
    FEATURE_NAMES.iter().position(|n| *n == name)
}

/// One candidate's features, in `FEATURE_NAMES` order.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FeatureVector(pub [f32; FEATURE_COUNT]);

impl FeatureVector {
    pub fn as_slice(&self) -> &[f32; FEATURE_COUNT] {
        &self.0
    }

    /// Pair each value with its name. Used by the feature dump, so the fitter reads names
    /// rather than positions and a reorder here cannot silently transpose the fit.
    pub fn named(&self) -> [(&'static str, f32); FEATURE_COUNT] {
        let mut out = [("", 0.0f32); FEATURE_COUNT];
        for (i, name) in FEATURE_NAMES.iter().enumerate() {
            out[i] = (name, self.0[i]);
        }
        out
    }
}

/// Trust as an ordinal in `[0, 1]`.
///
/// **`effective_trust` — the propagated value — never `trust_class`.** §3.3's worst-case
/// propagation is the whole point of the field, and a gate that scored the declared class
/// would hand a laundered memory its original trust back at the last step before injection.
fn trust_ordinal(trust: TrustClass) -> f32 {
    (trust as u8) as f32 / (TrustClass::UserAsserted as u8) as f32
}

/// Fidelity as an ordinal in `[0, 1]`.
///
/// `Tombstone` maps to 0.0 but can never appear: §4.3 excludes tombstones from the candidate
/// set before scoring, and `debug_assert_injection_valid` re-checks it on the way out.
fn fidelity_ordinal(fidelity: Fidelity) -> f32 {
    (fidelity as u8) as f32 / (Fidelity::Record as u8) as f32
}

/// Extract features for one candidate.
///
/// `raw_bm25` comes from [`lexical::score_all`] and `dense_cosine` from
/// [`crate::cue::dense::cosine`], both computed over the same candidate set, so the caller
/// scores the set once rather than per-entry.
pub fn extract(entry: &MemoryEntry, raw_bm25: f32, dense_cosine: f32) -> FeatureVector {
    let lexical_bm25 = lexical::saturate(raw_bm25);

    // How many of the two cues fired, as a fraction. **The denominator is in the feature's
    // name** — cue 3 changes this to /3, the rename forces `FrozenGate::load`'s
    // `FeatureNamesDisagree` refusal, and the refusal forces a deliberate re-fit.
    //
    // Still pinned to zero, and the reason changed with the cue count. It is no longer collinear
    // with the lexical feature the way the one-cue indicator was — but making it informative
    // needs a *firing predicate* for the dense cue, and unlike BM25's `raw > 0` any cosine floor
    // is an unmeasured constant entering the frozen path. A 2-bit coarsening of two continuous
    // features already in this vector does not earn that. Unpin at cue 3, where agreement stops
    // being a coarsening of the vector's own contents.
    let fired = u8::from(raw_bm25 > 0.0) + u8::from(dense_cosine > 0.0);
    let cue_agreement_2cue = f32::from(fired) / 2.0;

    FeatureVector([
        lexical_bm25,
        dense_cosine,
        trust_ordinal(entry.effective_trust),
        fidelity_ordinal(entry.fidelity),
        cue_agreement_2cue,
    ])
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::entry::MATURATION_WINDOW_MS;
    use marlowe_contract::PayloadKind;

    fn entry(trust: TrustClass, fidelity: Fidelity) -> MemoryEntry {
        MemoryEntry {
            id: "m-a".into(),
            text: "the ingest job times out".into(),
            payload_kind: PayloadKind::Episode,
            embedding_ref: None,
            source_turn_id: "t-1".into(),
            source_session_id: "s-1".into(),
            // Deliberately the OPPOSITE of `effective_trust` in this fixture, so a test that
            // reads the wrong field fails loudly instead of coincidentally agreeing.
            trust_class: TrustClass::UserAsserted,
            effective_trust: trust,
            derivation: Vec::new(),
            origin_event: 1,
            created_at: 1_000,
            last_accessed: 1_000,
            access_count: 0,
            confidence: 1.0,
            activation: 1.0,
            fidelity,
            silent_until: Some(1_000 + MATURATION_WINDOW_MS),
            supersedes: Vec::new(),
            superseded_by: None,
        }
    }

    #[test]
    fn the_gate_scores_effective_trust_not_declared_trust() {
        // The fixture declares `user_asserted` and propagates `untrusted_content`. A gate
        // reading the declared field would score 1.0 here and hand a laundered memory its
        // original trust back at the last step before injection.
        let e = entry(TrustClass::UntrustedContent, Fidelity::Record);
        let f = extract(&e, 5.0, 0.0);
        assert_eq!(f.0[2], 0.0, "untrusted_content is the bottom of the scale");

        let e = entry(TrustClass::UserAsserted, Fidelity::Record);
        assert_eq!(extract(&e, 5.0, 0.0).0[2], 1.0);
    }

    #[test]
    fn ordinals_span_zero_to_one() {
        let e = entry(TrustClass::AgentObserved, Fidelity::Summary);
        let f = extract(&e, 5.0, 0.0);
        assert!((f.0[2] - 2.0 / 3.0).abs() < 1e-6, "{:?}", f.0);
        assert!((f.0[3] - 2.0 / 3.0).abs() < 1e-6, "{:?}", f.0);
    }

    #[test]
    fn cue_agreement_counts_how_many_of_the_two_cues_fired() {
        // The semantics change the rename exists for: 0 / 0.5 / 1.0, not 0 / 1.
        let e = entry(TrustClass::UserAsserted, Fidelity::Record);
        assert_eq!(extract(&e, 0.0, 0.0).0[4], 0.0, "neither cue fired");
        assert_eq!(extract(&e, 0.1, 0.0).0[4], 0.5, "lexical only");
        assert_eq!(extract(&e, 0.0, 0.4).0[4], 0.5, "dense only");
        assert_eq!(extract(&e, 0.1, 0.4).0[4], 1.0, "both");
    }

    #[test]
    fn names_and_values_stay_aligned() {
        let e = entry(TrustClass::UntrustedContent, Fidelity::Record);
        let f = extract(&e, 30.0, 0.62);
        let named = f.named();
        assert_eq!(named[0].0, "lexical_bm25");
        assert!(named[0].1 > 0.7);
        assert_eq!(named[1].0, "dense_cosine");
        assert_eq!(named[1].1, 0.62);
        assert_eq!(named[2].0, "effective_trust");
        assert_eq!(named[2].1, 0.0);
        assert_eq!(named[4].0, "cue_agreement_2cue");
        assert_eq!(FEATURE_COUNT, 5);
    }
}
