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
/// `FrozenGate::load` asserts this array against the artifact's declared `feature_names`. That
/// check is the most valuable test in this module: weights and features living in two places
/// with only one of them checked is the exact shape of every unobservable mismatch this
/// project has paid for. A reordered array with no name check would silently apply the trust
/// weight to the BM25 value and every test would stay green.
pub const FEATURE_NAMES: [&str; 4] = [
    "lexical_bm25",
    "effective_trust",
    "fidelity",
    "cue_agreement",
];

pub const FEATURE_COUNT: usize = FEATURE_NAMES.len();

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
/// `raw_bm25` comes from [`lexical::score_all`] over the same candidate set, so the caller
/// scores the set once rather than per-entry.
pub fn extract(entry: &MemoryEntry, raw_bm25: f32) -> FeatureVector {
    let lexical_bm25 = lexical::saturate(raw_bm25);

    // Cue agreement: how many cues gave this candidate a positive score. With one cue this is
    // 0 or 1 and is very nearly constant — every candidate a query matches at all scores 1.
    // The fitter detects that as zero variance and pins the weight to zero; see `gate/mod.rs`.
    let cue_agreement = if raw_bm25 > 0.0 { 1.0 } else { 0.0 };

    FeatureVector([
        lexical_bm25,
        trust_ordinal(entry.effective_trust),
        fidelity_ordinal(entry.fidelity),
        cue_agreement,
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
        let f = extract(&e, 5.0);
        assert_eq!(f.0[1], 0.0, "untrusted_content is the bottom of the scale");

        let e = entry(TrustClass::UserAsserted, Fidelity::Record);
        assert_eq!(extract(&e, 5.0).0[1], 1.0);
    }

    #[test]
    fn ordinals_span_zero_to_one() {
        let e = entry(TrustClass::AgentObserved, Fidelity::Summary);
        let f = extract(&e, 5.0);
        assert!((f.0[1] - 2.0 / 3.0).abs() < 1e-6, "{:?}", f.0);
        assert!((f.0[2] - 2.0 / 3.0).abs() < 1e-6, "{:?}", f.0);
    }

    #[test]
    fn cue_agreement_is_one_when_the_single_cue_fired() {
        let e = entry(TrustClass::UserAsserted, Fidelity::Record);
        assert_eq!(extract(&e, 0.0).0[3], 0.0);
        assert_eq!(extract(&e, 0.1).0[3], 1.0);
    }

    #[test]
    fn names_and_values_stay_aligned() {
        let e = entry(TrustClass::UntrustedContent, Fidelity::Record);
        let f = extract(&e, 30.0);
        let named = f.named();
        assert_eq!(named[0].0, "lexical_bm25");
        assert!(named[0].1 > 0.7);
        assert_eq!(named[1].0, "effective_trust");
        assert_eq!(named[1].1, 0.0);
        assert_eq!(FEATURE_COUNT, 4);
    }
}
