//! CONTRACTS.md sections 4.1–4.4 — retrieval.
//!
//! Session B adds the first relevance judgment: one lexical cue ([`crate::cue::lexical`]) and
//! the frozen gate ([`crate::gate`]). What that is **not** is the five-cue system K1 measures —
//! dense, entity-graph, temporal and causal are all missing, and a number produced here is a
//! statement about an incomplete cue set rather than about the design.
//!
//! The pipeline, in order, matching §4.2's latency breakdown:
//!
//! 1. **candidates** — §4.3's three exclusions, then session scope
//! 2. **cues** — BM25 over that set
//! 3. **gate** — frozen weights → score → isotonic curve → calibrated precision → threshold
//! 4. **budget** — §5.7's ≤7,000 tokens, applied to what survived the gate
//!
//! Order matters at step 4. Gating **before** budgeting means the budget cuts the least
//! confident of the memories worth injecting; budgeting first would cut on recency and hand
//! the gate a set that was already truncated for an unrelated reason.

use marlowe_contract::{Fidelity, InjectedMemory};

use crate::cue::lexical;
use crate::entry::MemoryEntry;
use crate::gate::{features, FrozenGate};
use crate::store::BeliefStore;

/// The gate stamp for a build with no gate — Session A's state, retained for the feature-dump
/// path's sibling and as the thing `gate::GATE_VERSION` is asserted to differ from.
///
/// It is deliberately not `frozen-v1`. A report reading `gate.version` must be able to tell
/// that nothing was scored — a plausible version string next to zero scores would read as a
/// gate that ran and found nothing interesting, which is a different and much better-looking
/// claim than the true one.
pub const UNGATED_VERSION: &str = "ungated-v0";

/// Characters per token, used **pessimistically on purpose**.
///
/// There is no tokenizer here: ADR-004's model is not wired yet, and inventing a precise
/// count would be reporting a measurement that was not taken. So this is an estimate, and
/// the direction it errs in is the whole point.
///
/// Three characters per token *over*-estimates for ordinary English (four is the usual rule
/// of thumb). Over-estimating can only make the reported `retrieval_tokens` look worse than
/// reality, so it can never hide a miss against section 5.7's ≤7,000 budget. An estimator
/// that erred the other way would let a real budget overrun report as compliant, which is the
/// failure mode that matters.
pub const CHARS_PER_TOKEN_PESSIMISTIC: usize = 3;

pub fn estimate_tokens(text: &str) -> u32 {
    // div_ceil so a non-empty string never estimates zero tokens.
    (text.len().div_ceil(CHARS_PER_TOKEN_PESSIMISTIC)) as u32
}

/// How a run scores its candidates.
///
/// Two modes and no third. The absence of a "gate is optional" variant is the point: there is
/// no path where a calibrated stamp can be produced without a calibrated gate.
pub enum Scoring<'a> {
    /// The shipping path.
    Gated(&'a FrozenGate),
    /// Feature-dump mode, used only by `tools/fit_gate.py`. Computes features so they can be
    /// written to a side file, calibrates nothing, and gates nothing — so it selects exactly
    /// as Session A did (recency, then the budget) and stamps `uncalibrated-fit-only`.
    FitDump,
}

/// One candidate after scoring. The dump writes these; the selection ranks them.
pub struct ScoredCandidate<'a> {
    pub entry: &'a MemoryEntry,
    pub features: features::FeatureVector,
    pub score: f32,
    pub calibrated_precision: f32,
    pub passes: bool,
}

pub struct Selection<'a> {
    pub injected: Vec<InjectedMemory>,
    /// The true size of the set that passed section 4.3's three exclusions, across the whole
    /// store, before session scoping and the budget cut.
    ///
    /// Reported as what was actually enumerated. Setting it to `injected.len()` or to a
    /// constant would be a fabricated measurement in a field the report treats as real.
    pub considered: u32,
    pub retrieval_tokens: u32,
    /// Every candidate in scope, scored. Retained so the feature dump can write the negatives
    /// too — a calibration fit only on what was injected would be fit on its own output.
    pub scored: Vec<ScoredCandidate<'a>>,
    /// How many candidates were in the session's scope at all.
    pub scoped: u32,
    /// How many cleared the gate's threshold, before the budget.
    pub above_threshold: u32,
    pub budget_exhausted: bool,
}

/// Select what to inject.
///
/// Ranking under [`Scoring::Gated`] is `(calibrated_precision desc, score desc, id asc)`; under
/// [`Scoring::FitDump`] it is Session A's `(created_at desc, id asc)`. Both are **totally
/// deterministic**, and that is not a nicety: `marlowe-eval repro` compares two runs byte for
/// byte and the injected set is in the hash. The final tiebreak is always `id` because two
/// entries with equal scores would otherwise be ordered by whatever the collection did.
pub fn select_for_injection<'a>(
    beliefs: &'a BeliefStore,
    session_id: &str,
    query_text: &str,
    now_ms: i64,
    max_tokens: u32,
    scoring: &Scoring<'_>,
) -> Selection<'a> {
    let candidates = beliefs.injection_candidates(now_ms);
    let considered = candidates.len() as u32;

    // Session scoping. Note what this is not: a relevance judgment. It is the scope the
    // request names, and the cue is what judges relevance inside it.
    let scoped: Vec<&MemoryEntry> = candidates
        .into_iter()
        .filter(|e| e.source_session_id == session_id)
        .collect();

    let raw_scores = lexical::score_all(&scoped, query_text);

    let mut scored: Vec<ScoredCandidate<'a>> = scoped
        .iter()
        .zip(raw_scores.iter())
        .map(|(entry, raw)| {
            let f = features::extract(entry, *raw);
            match scoring {
                Scoring::Gated(gate) => {
                    let v = gate.judge(&f);
                    ScoredCandidate {
                        entry,
                        features: f,
                        score: v.score,
                        calibrated_precision: v.calibrated_precision,
                        passes: v.passes,
                    }
                }
                // No gate ran. Zero is the honest report of "nothing scored this", and
                // `gate.version` names the absence so the zero cannot be read as a low score.
                Scoring::FitDump => ScoredCandidate {
                    entry,
                    features: f,
                    score: 0.0,
                    calibrated_precision: 0.0,
                    passes: true,
                },
            }
        })
        .collect();

    let mut order: Vec<usize> = (0..scored.len()).collect();
    match scoring {
        Scoring::Gated(_) => {
            order.retain(|i| scored[*i].passes);
            order.sort_by(|a, b| {
                let (x, y) = (&scored[*a], &scored[*b]);
                y.calibrated_precision
                    .total_cmp(&x.calibrated_precision)
                    .then_with(|| y.score.total_cmp(&x.score))
                    .then_with(|| x.entry.id.cmp(&y.entry.id))
            });
        }
        Scoring::FitDump => {
            order.sort_by(|a, b| {
                let (x, y) = (&scored[*a], &scored[*b]);
                y.entry
                    .created_at
                    .cmp(&x.entry.created_at)
                    .then_with(|| x.entry.id.cmp(&y.entry.id))
            });
        }
    }
    let above_threshold = order.len() as u32;

    let mut injected = Vec::new();
    let mut tokens = 0u32;
    let mut budget_exhausted = false;

    for index in order {
        let candidate = &scored[index];
        let cost = estimate_tokens(&candidate.entry.text);
        if tokens + cost > max_tokens {
            // Section 4.2's `budget_exhausted` describes having nothing further to inject
            // within budget. Recorded rather than silently truncated.
            budget_exhausted = true;
            break;
        }
        tokens += cost;
        injected.push(InjectedMemory {
            memory_id: candidate.entry.id.clone(),
            content: candidate.entry.text.clone(),
            score: candidate.score,
            calibrated_precision: candidate.calibrated_precision,
            fidelity: candidate.entry.fidelity,
            effective_trust: candidate.entry.effective_trust,
            payload_kind: candidate.entry.payload_kind,
        });
    }

    // Dump order is by id so two runs write byte-identical files.
    scored.sort_by(|a, b| a.entry.id.cmp(&b.entry.id));

    Selection {
        injected,
        considered,
        retrieval_tokens: tokens,
        scoped: scored.len() as u32,
        above_threshold,
        scored,
        budget_exhausted,
    }
}

/// Assert the invariants section 4.3 states about what may appear in `injected`.
///
/// Called on the way out. The harness checks these too; doing it here as well means a
/// violation is a panic with a stack trace in our own process rather than a protocol error
/// that aborts someone's run and reports only what the bytes looked like.
pub fn debug_assert_injection_valid(injected: &[InjectedMemory]) {
    for item in injected {
        debug_assert_ne!(
            item.fidelity,
            Fidelity::Tombstone,
            "a tombstone reached the injected set; section 4.3 says it may never compete for \
             injection precision, because it is the ABSENCE of a memory"
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::entry::MATURATION_WINDOW_MS;
    use marlowe_contract::{PayloadKind, TrustClass};

    fn entry(id: &str, session: &str, text: &str, created: i64) -> MemoryEntry {
        MemoryEntry {
            id: id.into(),
            text: text.into(),
            payload_kind: PayloadKind::Episode,
            embedding_ref: None,
            source_turn_id: format!("t-{id}"),
            source_session_id: session.into(),
            trust_class: TrustClass::UserAsserted,
            effective_trust: TrustClass::UserAsserted,
            derivation: Vec::new(),
            origin_event: 1,
            created_at: created,
            last_accessed: created,
            access_count: 0,
            confidence: 1.0,
            activation: 1.0,
            fidelity: Fidelity::Record,
            silent_until: Some(created + MATURATION_WINDOW_MS),
            supersedes: Vec::new(),
            superseded_by: None,
        }
    }

    fn store() -> BeliefStore {
        let mut s = BeliefStore::default();
        s.insert(entry("m-a", "s-1", "the ingest job times out nightly", 1_000));
        s.insert(entry("m-b", "s-1", "we had pasta for dinner", 2_000));
        s.insert(entry("m-c", "s-2", "gamma", 3_000));
        s
    }

    /// A gate whose curve makes the threshold reachable, so the gated path can be exercised
    /// without depending on whatever the real fit produced.
    fn test_gate() -> FrozenGate {
        FrozenGate::from_json(
            r#"{
              "state": "fitted", "note": "test", "version": "frozen-v1", "threshold": 0.95,
              "feature_names": ["lexical_bm25","effective_trust","fidelity","cue_agreement"],
              "weights": [8.0, 0.0, 0.0, 0.0], "bias": -1.0,
              "pinned_zero_weights": {"cue_agreement": "constant until cue 2"},
              "isotonic_breakpoints": [[0.4, 0.10], [0.7, 0.99]],
              "corpus": "test", "corpus_variant": "cleaned", "corpus_sha256": "x",
              "split_rule": "test", "split_digest": "y",
              "fit_cases": 1, "heldout_cases": 1, "fit_rows": 1, "fit_positives": 1,
              "fitted_at_clock_ms": 0
            }"#,
        )
        .unwrap()
    }

    fn dump() -> Scoring<'static> {
        Scoring::FitDump
    }

    #[test]
    fn nothing_is_injected_before_maturation() {
        let beliefs = store();
        let sel = select_for_injection(&beliefs, "s-1", "ingest", 2_000, 7000, &dump());
        assert!(sel.injected.is_empty());
        assert_eq!(sel.considered, 0, "and nothing was even a candidate");
    }

    #[test]
    fn only_the_requested_session_is_scoped() {
        let now = 3_000 + MATURATION_WINDOW_MS;
        let beliefs = store();
        let sel = select_for_injection(&beliefs, "s-1", "ingest", now, 7000, &dump());
        assert_eq!(sel.injected.len(), 2);
        assert!(sel.injected.iter().all(|i| i.memory_id != "m-c"));
        assert_eq!(sel.considered, 3, "considered counts the whole candidate set");
        assert_eq!(sel.scoped, 2);
    }

    #[test]
    fn the_gate_drops_what_it_does_not_believe_in() {
        let now = 3_000 + MATURATION_WINDOW_MS;
        let gate = test_gate();
        let beliefs = store();
        let sel = select_for_injection(
            &beliefs,
            "s-1",
            "why is the ingest job timing out",
            now,
            7000,
            &Scoring::Gated(&gate),
        );
        assert_eq!(sel.scoped, 2, "both were scored");
        assert_eq!(sel.above_threshold, 1, "only one cleared the threshold");
        assert_eq!(sel.injected.len(), 1);
        assert_eq!(sel.injected[0].memory_id, "m-a");
        assert!(sel.injected[0].calibrated_precision >= crate::gate::THRESHOLD);
        assert!(sel.injected[0].score > 0.0, "a real score, not Session A's zero");
    }

    #[test]
    fn a_query_matching_nothing_clears_no_candidate() {
        // The abstention path that matters: candidates existed, none was good enough. This is
        // what makes `no_candidate_above_threshold` distinguishable from `no_candidates`.
        let now = 3_000 + MATURATION_WINDOW_MS;
        let gate = test_gate();
        let beliefs = store();
        let sel = select_for_injection(
            &beliefs,
            "s-1",
            "quarterly headcount forecast",
            now,
            7000,
            &Scoring::Gated(&gate),
        );
        assert_eq!(sel.scoped, 2);
        assert_eq!(sel.above_threshold, 0);
        assert!(sel.injected.is_empty());
        assert!(!sel.budget_exhausted, "nothing was cut for cost");
    }

    #[test]
    fn every_scored_candidate_is_retained_including_the_rejects() {
        // The fit needs negatives. A calibration fit only on what was injected would be fit on
        // its own output.
        let now = 3_000 + MATURATION_WINDOW_MS;
        let gate = test_gate();
        let beliefs = store();
        let sel = select_for_injection(
            &beliefs,
            "s-1",
            "why is the ingest job timing out",
            now,
            7000,
            &Scoring::Gated(&gate),
        );
        assert_eq!(sel.scored.len(), 2, "both, not just the one that passed");
        assert!(sel.scored.iter().any(|c| !c.passes));
    }

    #[test]
    fn the_dump_order_is_stable() {
        let now = 3_000 + MATURATION_WINDOW_MS;
        let beliefs = store();
        let sel = select_for_injection(&beliefs, "s-1", "ingest", now, 7000, &dump());
        let ids: Vec<&str> = sel.scored.iter().map(|c| c.entry.id.as_str()).collect();
        assert_eq!(ids, vec!["m-a", "m-b"], "sorted by id, so two runs write the same bytes");
    }

    #[test]
    fn ranking_is_deterministic() {
        let now = 3_000 + MATURATION_WINDOW_MS;
        let gate = test_gate();
        let beliefs = store();
        let ids = |s: &Selection| s.injected.iter().map(|i| i.memory_id.clone()).collect::<Vec<_>>();
        let a = select_for_injection(&beliefs, "s-1", "ingest job", now, 7000, &Scoring::Gated(&gate));
        let b = select_for_injection(&beliefs, "s-1", "ingest job", now, 7000, &Scoring::Gated(&gate));
        assert_eq!(ids(&a), ids(&b));
    }

    #[test]
    fn the_token_estimate_is_pessimistic() {
        // Erring high is the safe direction: it can never hide a budget miss.
        assert_eq!(estimate_tokens("abc"), 1);
        assert_eq!(estimate_tokens("abcd"), 2, "4 chars -> 2 tokens, not 1");
        assert_eq!(estimate_tokens(""), 0);
    }

    #[test]
    fn the_budget_cuts_after_the_gate_and_says_so() {
        let now = 3_000 + MATURATION_WINDOW_MS;
        let gate = test_gate();
        let beliefs = store();
        let sel = select_for_injection(
            &beliefs,
            "s-1",
            "why is the ingest job timing out",
            now,
            1,
            &Scoring::Gated(&gate),
        );
        assert_eq!(sel.above_threshold, 1, "the gate still passed it");
        assert!(sel.budget_exhausted, "and the budget is what cut it");
        assert!(sel.injected.is_empty());
        assert!(sel.retrieval_tokens <= 1);
    }
}
