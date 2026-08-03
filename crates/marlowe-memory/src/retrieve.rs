//! CONTRACTS.md sections 4.1–4.4 — retrieval, as far as Session A goes.
//!
//! **This is not a retriever and must not be described as one.** There is no cue, no
//! embedding, no fusion, no scoring model and no gate. What it does is make the *candidate
//! set* observable: apply section 4.3's three exclusions, scope to the session, respect the
//! token budget, and report honestly what was considered.
//!
//! Session B adds the lexical cue and the frozen gate with a real isotonic calibration. Until
//! then, every number this module produces about relevance is zero, and the gate stamp says
//! so in words rather than leaving a plausible-looking score behind.

use marlowe_contract::{Fidelity, InjectedMemory};

use crate::entry::MemoryEntry;
use crate::store::BeliefStore;

/// The gate stamp version for a build with no gate.
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

pub struct Selection {
    pub injected: Vec<InjectedMemory>,
    /// The true size of the set that passed section 4.3's three exclusions, across the whole
    /// store, before session scoping and the budget cut.
    ///
    /// Reported as what was actually enumerated. Setting it to `injected.len()` or to a
    /// constant would be a fabricated measurement in a field the report treats as real.
    pub considered: u32,
    pub retrieval_tokens: u32,
    pub budget_exhausted: bool,
}

/// Select what to inject.
///
/// Ordering is `(created_at descending, id ascending)` — a mild recency preference, and
/// **totally deterministic**. Determinism is not a nicety here: `marlowe-eval repro` compares
/// two runs byte for byte, and the injected set is in the hash. The tiebreak on `id` exists
/// because two turns ingested at the same clock value would otherwise leave the order to the
/// underlying collection.
///
/// Note what the ordering does *not* use: `query_text`. This function never receives it.
/// That is the same structural guarantee the M0a reference stub carries in the other
/// direction — there is nowhere for a similarity search to live.
pub fn select_for_injection(
    beliefs: &BeliefStore,
    session_id: &str,
    now_ms: i64,
    max_tokens: u32,
) -> Selection {
    let candidates = beliefs.injection_candidates(now_ms);
    let considered = candidates.len() as u32;

    // Session scoping, not relevance. "Memories from this conversation" is a scope filter a
    // system with no cues can honestly apply; cross-session retrieval is what the cues are
    // for, and arrives with them.
    let mut scoped: Vec<&MemoryEntry> = candidates
        .into_iter()
        .filter(|e| e.source_session_id == session_id)
        .collect();

    scoped.sort_by(|a, b| {
        b.created_at
            .cmp(&a.created_at)
            .then_with(|| a.id.cmp(&b.id))
    });

    let mut injected = Vec::new();
    let mut tokens = 0u32;
    let mut budget_exhausted = false;

    for entry in scoped {
        let cost = estimate_tokens(&entry.text);
        if tokens + cost > max_tokens {
            // Section 4.2's `budget_exhausted` describes having nothing further to inject
            // within budget. Recorded rather than silently truncated.
            budget_exhausted = true;
            break;
        }
        tokens += cost;
        injected.push(InjectedMemory {
            memory_id: entry.id.clone(),
            content: entry.text.clone(),
            // No gate ran. Zero is the honest report of "nothing scored this", and
            // `gate.version` names the absence so the zero cannot be read as a low score.
            score: 0.0,
            calibrated_precision: 0.0,
            fidelity: entry.fidelity,
            effective_trust: entry.effective_trust,
            payload_kind: entry.payload_kind,
        });
    }

    Selection {
        injected,
        considered,
        retrieval_tokens: tokens,
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
        s.insert(entry("m-a", "s-1", "alpha", 1_000));
        s.insert(entry("m-b", "s-1", "beta", 2_000));
        s.insert(entry("m-c", "s-2", "gamma", 3_000));
        s
    }

    #[test]
    fn nothing_is_injected_before_maturation() {
        let sel = select_for_injection(&store(), "s-1", 2_000, 7000);
        assert!(sel.injected.is_empty());
        assert_eq!(sel.considered, 0, "and nothing was even a candidate");
    }

    #[test]
    fn only_the_requested_session_is_injected() {
        let now = 3_000 + MATURATION_WINDOW_MS;
        let sel = select_for_injection(&store(), "s-1", now, 7000);
        assert_eq!(sel.injected.len(), 2);
        assert!(sel.injected.iter().all(|i| i.memory_id != "m-c"));
        assert_eq!(sel.considered, 3, "considered counts the whole candidate set");
    }

    #[test]
    fn ordering_is_deterministic_and_recency_first() {
        let now = 3_000 + MATURATION_WINDOW_MS;
        let a = select_for_injection(&store(), "s-1", now, 7000);
        let b = select_for_injection(&store(), "s-1", now, 7000);
        let ids = |s: &Selection| s.injected.iter().map(|i| i.memory_id.clone()).collect::<Vec<_>>();
        assert_eq!(ids(&a), ids(&b));
        assert_eq!(ids(&a), vec!["m-b", "m-a"], "newer first");
    }

    #[test]
    fn the_token_estimate_is_pessimistic() {
        // Erring high is the safe direction: it can never hide a budget miss.
        assert!(estimate_tokens("abcd") >= 4 / 4, "at least the optimistic count");
        assert_eq!(estimate_tokens("abc"), 1);
        assert_eq!(estimate_tokens("abcd"), 2, "4 chars -> 2 tokens, not 1");
        assert_eq!(estimate_tokens(""), 0);
    }

    #[test]
    fn the_budget_cuts_and_says_so() {
        let now = 3_000 + MATURATION_WINDOW_MS;
        let sel = select_for_injection(&store(), "s-1", now, 1);
        assert!(sel.budget_exhausted);
        assert!(sel.retrieval_tokens <= 1);
    }
}
