//! The daemon's memory, wired to `marlowe-memory`. M2 Session D.
//!
//! **Beliefs become durable here, and conversations do not.** The daemon already opens a `Profile`
//! and a `Journal`, and `BeliefStore::derive` rebuilds the store from that log — so a memory
//! written today is present after a restart with no new persistence machinery at all. The session
//! store is still a `BTreeMap` on `Daemon` and still dies with the process. That split is
//! deliberate: durable *conversations* overlap M3's WAL and checkpoint-resume work, and STATE.md is
//! explicit that they must not be built twice.
//!
//! The honest one-line statement, which belongs anywhere this is described: **memory survives a
//! restart, the conversation does not.**
//!
//! # Why the journal is shared rather than owned
//!
//! A memory write is a *signed* append — invariant 2 says there is no unsigned path — and the loop
//! already holds the journal for the whole turn through its recorder. Two mutable borrows of one
//! `Journal` is the honest shape of one append-only log with two writers, and
//! `SharedJournalRecorder` is the resolution. The borrows are per-append and never nest: the engine
//! computes a `remember` outcome and *then* records the event.

use std::sync::{Arc, Mutex};

use marlowe_contract::{Clock, PayloadKind, TrustClass};
use marlowe_journal::Journal;
use marlowe_loop::driver::{ClaimRequest, MemoryHost};
use marlowe_loop::run::{RunId, SessionId};
use marlowe_memory::cue::dense::vectors::VectorStore;
use marlowe_memory::cue::dense::vram::{Probe, Reserve};
use marlowe_memory::rerank::{CrossEncoder, RerankChoice, SHIPPED_THREADS};
use marlowe_memory::retrieve::{
    debug_assert_injection_valid, select_for_injection, Rerank, Scoring, RERANK_BUDGET,
};
use marlowe_memory::{
    remember_claim, Abstention, BeliefStore, ClaimWrite, FrozenGate, OperatingPoint,
};

/// What one turn's retrieval produced.
///
/// **The trust floor travels with the text.** A caller that took `text` alone would build a context
/// block at whatever class it chose, and injecting an untrusted memory at a higher class is exactly
/// the laundering path §3.3 exists to close.
#[derive(Debug, Clone)]
pub struct Retrieved {
    pub text: String,
    pub count: usize,
    /// `min` over the injected memories' `effective_trust`. §3.3's worst case.
    pub floor: TrustClass,
    /// The rank-1/rank-2 cross-encoder margin, when defined. Diagnostic; `--dev` only.
    pub margin: Option<f32>,
    /// Why nothing was injected, when nothing was.
    pub abstention: Option<Abstention>,
}

impl Retrieved {
    pub fn is_empty(&self) -> bool {
        self.count == 0
    }

    /// Nothing retrieved, because nothing was asked. **Not the same as an abstention**, which is a
    /// retrieval that ran and declined; `abstention: None` here says the question was never put.
    /// A resumed run has no new message to retrieve against.
    pub fn nothing_was_asked() -> Self {
        Self {
            text: String::new(),
            count: 0,
            floor: TrustClass::UserAsserted,
            margin: None,
            abstention: None,
        }
    }
}

/// What the retrieval half of memory is doing, in words the status surface can print.
///
/// **Announced, never inferred** — ADR-029's rule applied to memory rather than to the rerank
/// provider. A daemon that silently had no retrieval would behave exactly like one whose store is
/// empty, and the two are very different facts. `--status` prints this.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RetrievalState {
    /// The cross-encoder loaded. Auto-injection is live at the declared operating point.
    Live { model_dir: String },
    /// **Write-only.** Claims are still written, signed and durable; nothing is read back
    /// automatically. Explicit `recall` is unaffected — it needs no margin.
    WriteOnly { why: String },
}

impl RetrievalState {
    pub fn headline(&self) -> String {
        match self {
            Self::Live { model_dir } => format!("live · {model_dir}"),
            Self::WriteOnly { why } => format!("WRITE-ONLY · {why}"),
        }
    }
}

/// The daemon's belief store and its handle on the one log.
pub struct DaemonMemory {
    journal: Arc<Mutex<Journal>>,
    /// **Shared with the `recall` tool host.** One store, two readers: the loop's injection path
    /// and the model's explicit search. A second store would be a second answer to *"what does
    /// Marlowe know"*, which is the two-sides-silently-disagree shape this project logs.
    beliefs: Arc<Mutex<BeliefStore>>,
    /// The scoring half. `None` means write-only, and [`RetrievalState`] says why.
    gate: FrozenGate,
    operating_point: OperatingPoint,
    cross_encoder: Option<CrossEncoder>,
    /// **Empty, and that is a stated limitation rather than an oversight.** The dense cue scores
    /// 0.0 for every candidate without vectors, so retrieval here is lexical + rerank. Embedding at
    /// write time is the next increment; `dense_for` already treats a missing vector as 0.0 — the
    /// honest value — rather than skipping the candidate, so the degradation is uniform and
    /// visible rather than a silently shrinking candidate set.
    vectors: VectorStore,
    state: RetrievalState,
}

impl DaemonMemory {
    /// Rebuild the store from the log.
    ///
    /// **A derivation failure is returned, never swallowed.** `BeliefStore::derive` refuses a
    /// profile written by a different derivation version, and it refuses a log it cannot fold. A
    /// daemon that started with an empty store after either would be a daemon that had silently
    /// forgotten everything while reporting itself healthy — which is indistinguishable, from the
    /// outside, from a first run.
    ///
    /// `reranking` names the cross-encoder directory. **`None` is write-only, announced.** It is not
    /// an error: a first run with no models present should still be able to talk and to remember,
    /// and refusing to start would make memory an install-time dependency of the whole product.
    /// What must never happen is retrieval quietly not running, which is what [`RetrievalState`] is
    /// for.
    pub fn open(
        journal: Arc<Mutex<Journal>>,
        derivation_version: u32,
        reranking: Option<&std::path::Path>,
        tier1_model: &str,
        // Which process holds tier 1. **A required parameter**, so a caller cannot mean "Ollama"
        // by omission -- see `marlowe_memory::cue::dense::vram::Tier1Runtime`.
        tier1_runtime: marlowe_memory::cue::dense::vram::Tier1Runtime,
    ) -> Result<Self, marlowe_memory::MemoryError> {
        let beliefs = {
            let j = journal.lock().expect("the journal lock was poisoned");
            BeliefStore::derive(&j, derivation_version)?
        };
        // Both artifacts load at startup, before a port is bound. Same rule the eval adapter
        // follows: a build-time mistake must stop the process rather than become a per-query error.
        let gate = FrozenGate::load().map_err(|e| {
            marlowe_memory::MemoryError::UndecodablePayload {
                seq: 0,
                source: serde_json::Error::io(std::io::Error::other(e.to_string())),
            }
        })?;
        let operating_point = OperatingPoint::load().map_err(|e| {
            marlowe_memory::MemoryError::UndecodablePayload {
                seq: 0,
                source: serde_json::Error::io(std::io::Error::other(e.to_string())),
            }
        })?;

        let (cross_encoder, state) = match reranking {
            None => (
                None,
                RetrievalState::WriteOnly {
                    why: "no --reranking directory; the rank-1/rank-2 margin the declared \
                          operating point reads does not exist without a cross-encoder"
                        .to_string(),
                },
            ),
            // **`load_auto`, not `load` -- ADR-045, and this call site is the reason the ADR is
            // not merely a CLI change.** Until now the daemon -- the SHIPPED interactive product --
            // called `CrossEncoder::load`, which is CPU by construction, so `--rerank-provider`
            // reached the eval adapter and nothing else. Flipping only the CLI default would have
            // been a control declared where nothing reads it: every `auto` line this project
            // published would have described a path the user never takes. The daemon now resolves
            // the same way the adapter does, yields the same reserve to tier 1, and reports what
            // it got.
            Some(dir) => match CrossEncoder::load_auto(
                dir,
                SHIPPED_THREADS,
                RerankChoice::Auto,
                Probe::Device,
                Reserve::ForTier1 { model: tier1_model, runtime: tier1_runtime },
            ) {
                Ok(e) => (
                    Some(e),
                    RetrievalState::Live { model_dir: dir.display().to_string() },
                ),
                // **Loudly write-only rather than silently ungated.** The digest pin refused this
                // graph, or the files are missing. Either way the reason travels to `--status`
                // instead of the daemon pretending retrieval is running.
                Err(e) => (
                    None,
                    RetrievalState::WriteOnly { why: format!("cross-encoder refused: {e}") },
                ),
            },
        };

        Ok(Self {
            journal,
            beliefs: Arc::new(Mutex::new(beliefs)),
            gate,
            operating_point,
            cross_encoder,
            vectors: VectorStore::default(),
            state,
        })
    }

    pub fn state(&self) -> &RetrievalState {
        &self.state
    }

    /// The rerank provider this daemon RESOLVED to, formatted for `--status`.
    ///
    /// **ADR-029 §"the provider is ANNOUNCED", discharged for the first time in the daemon.**
    /// `DaemonConfig::rerank_provider` has read the literal `"not-wired"` since it was written,
    /// with a comment saying that inventing a value would be the second source ADR-029 forbids.
    /// That comment was right and the field is now readable, because there is finally a resolution
    /// to read: this is the ONE place it is derived, and `daemon.rs` copies it rather than
    /// computing its own.
    ///
    /// The batching is on the string because it is derived from the provider and the two measured
    /// opposite — a status line naming a provider without its shape describes two configurations
    /// whose latencies differ by 50x.
    pub fn rerank_provider_label(&self) -> String {
        match self.cross_encoder.as_ref() {
            None => "not-loaded".to_string(),
            Some(e) => {
                let p = e.provider();
                format!(
                    "{} · {} · asked {}",
                    p.name(),
                    if p.default_batching() { "batched" } else { "sequential" },
                    e.plan().requested.asked()
                )
            }
        }
    }

    /// A handle on the same store, for the `recall` tool host.
    pub fn beliefs(&self) -> Arc<Mutex<BeliefStore>> {
        Arc::clone(&self.beliefs)
    }

    /// §4.2 retrieval for one turn: what, if anything, should be injected before the model speaks.
    ///
    /// **Returns the memories AND the trust floor they carry**, because a caller that took the text
    /// without the class would put untrusted content into the context view at whatever class it
    /// happened to construct the block with. §3.3's worst case is `min` over what was injected.
    pub fn retrieve(
        &mut self,
        session_id: &str,
        query_text: &str,
        now_ms: i64,
        max_tokens: u32,
    ) -> Retrieved {
        let mut rerank = match self.cross_encoder.as_mut() {
            Some(encoder) => {
                // **Derived from the RESOLVED provider, never a constant -- ADR-029, ADR-045.**
                // This read `batched: false` unconditionally, which was correct while the daemon
                // was CPU-only by construction and is wrong the moment it can resolve to CUDA: the
                // two providers measured OPPOSITE (CPU sequential 185.8 ms vs batched 195.6; CUDA
                // batched 3.4 vs sequential 15.2), so a hardcoded `false` would run the GPU in its
                // slower shape and nothing would say so.
                let batched = encoder.provider().default_batching();
                Rerank::CrossEncoder { encoder, budget: RERANK_BUDGET, batched }
            }
            None => Rerank::Off,
        };
        // The lock is held across the selection because `Selection` borrows entries out of the
        // store. It is released at the end of this function, before the turn runs — the `recall`
        // host takes the same lock and the two never overlap, because a tool call happens strictly
        // after injection.
        let beliefs = self.beliefs.lock().expect("the belief store lock was poisoned");
        let selection = select_for_injection(
            &beliefs,
            session_id,
            query_text,
            now_ms,
            max_tokens,
            // **The product is always the declared arm.** `Coverage::Full` is the un-gated control
            // for one offline comparison; there is no path that reaches it from the daemon, and
            // there must not be — K1 condition 3 fails a configuration that injects at low
            // precision to raise coverage, so shipping the control arm would fail the criterion by
            // construction.
            &Scoring::Gated {
                gate: &self.gate,
                operating_point: &self.operating_point,
                coverage: marlowe_memory::Coverage::Declared,
            },
            &self.vectors,
            None,
            &mut rerank,
            // **Profile-wide, and this is the product diverging from the measured configuration.**
            //
            // A session here is a *client name* — the TUI connects as `tui`, `--ask` as `cli` — so
            // under `ThisSession` a memory written at the CLI is invisible to auto-injection in the
            // TUI, and the eleven-week callback cannot cross surfaces. `recall` has always been
            // profile-wide, so this also ends an asymmetry where explicit search saw what injection
            // could not.
            //
            // **The declared operating point was calibrated on session-scoped pools.** Widening the
            // pool changes the rank-1/rank-2 margin distribution, so `PRECISION-COVERAGE.md`'s
            // coverage and precision describe `ThisSession` and not this. The cut point is still
            // the best available threshold in the graph's own units; what it is not is a measured
            // description of what happens here. See `RetrievalScope`.
            marlowe_memory::retrieve::RetrievalScope::Profile,
        );
        debug_assert_injection_valid(&selection.injected);

        // `min` over what is actually being injected. With nothing injected the floor is the top of
        // the lattice, which is correct: an empty block lowers nothing.
        let floor = selection
            .injected
            .iter()
            .map(|m| m.effective_trust)
            .min()
            .unwrap_or(TrustClass::UserAsserted);

        Retrieved {
            text: selection
                .injected
                .iter()
                .map(|m| m.content.clone())
                .collect::<Vec<_>>()
                .join("\n"),
            count: selection.injected.len(),
            floor,
            margin: selection.rerank_margin,
            abstention: selection.abstention,
        }
    }

    /// How many beliefs the store holds. For the status surface and for tests; **not** a retrieval
    /// path.
    pub fn len(&self) -> usize {
        self.beliefs.lock().expect("the belief store lock was poisoned").recall_candidates().len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

/// A model-supplied `payload_kind` string, mapped to the closed set.
///
/// **An unrecognised value is refused, never defaulted.** §4.6's rule for `channel` applies for the
/// same reason: a default arm would let the model write a belief under a kind nobody chose, and
/// `PayloadKind` is what a later filter reads. `None` here becomes a refusal the model can act on
/// rather than a silent reclassification.
fn payload_kind_from(raw: &str) -> Option<PayloadKind> {
    // Serde owns the wire spelling, so this cannot drift from the enum's own snake_case naming.
    serde_json::from_value(serde_json::Value::String(raw.to_string())).ok()
}

impl MemoryHost for DaemonMemory {
    fn remember(
        &mut self,
        run: RunId,
        session: SessionId,
        claim: &ClaimRequest,
        run_floor: TrustClass,
        now_ms: i64,
    ) -> Result<String, String> {
        // An empty `payload_kind` means the model did not supply the optional argument. That is a
        // legitimate call and `Episode` is the shape of "something that happened in a session" —
        // the same kind `ingest` gives every turn. A *wrong* value is a different situation and is
        // refused below.
        let kind = if claim.payload_kind.trim().is_empty() {
            PayloadKind::Episode
        } else {
            match payload_kind_from(&claim.payload_kind) {
                Some(k) => k,
                None => {
                    return Err(format!(
                        "payload_kind {:?} is not one of the kinds this build knows. Omit it, or \
                         pass one of: episode, fact, entity, edge, procedure, commitment, person, \
                         relationship, voice_params, noticing.",
                        claim.payload_kind
                    ))
                }
            }
        };

        let write = ClaimWrite {
            session_id: &session.to_string(),
            run_id: &run.to_string(),
            text: &claim.text,
            payload_kind: kind,
            derived_from: &claim.derived_from,
            run_floor,
        };

        // Held only for the append. The engine computes this outcome and *then* records its own
        // event through `SharedJournalRecorder`, so the two never nest on the same lock.
        let mut journal = self.journal.lock().expect("the journal lock was poisoned");
        let mut beliefs = self.beliefs.lock().expect("the belief store lock was poisoned");
        match remember_claim(&mut journal, &mut beliefs, Clock::new(now_ms), &write) {
            // The receipt names the trust class the harness DERIVED, not the one anybody asked
            // for. A model that reads "remembered at untrusted_content" has been told something
            // true about what it just did; a bare id tells it nothing.
            Ok(Ok(receipt)) => Ok(format!(
                "{} · {:?} · injectable after {}",
                receipt.id, receipt.effective_trust, receipt.silent_until
            )),
            Ok(Err(rejected)) => Err(rejected.as_wire_string()),
            // A journal failure is not survivable in silence — invariant 7. It reaches the model as
            // a refusal rather than being reported as a successful write.
            Err(e) => Err(format!("the write could not be journalled: {e}")),
        }
    }
}
