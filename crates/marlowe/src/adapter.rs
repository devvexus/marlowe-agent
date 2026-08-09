//! `marlowe --eval-adapter` — CONTRACTS.md section 4.0.
//!
//! Reads request frames on stdin, writes response frames on stdout, one JSON value per line.
//! The harness owns the process lifetime and ends the run by closing stdin.
//!
//! Section 4.0.1 describes this as a thin forwarding mode over the daemon. There is no daemon
//! yet, so Session A hosts the journal and belief store in-process. The wire is identical
//! either way, which is the point of pinning the wire rather than the plumbing.

use std::io::{BufRead, Write};
use std::path::Path;

use marlowe_contract::{
    AbstentionReason, AnswerCost, AnswerLatency, AnswerRequest, AnswerResponse, ContractVersion,
    ErrorKind, GateStamp, IngestCost, IngestLatency, IngestRequest, IngestResponse, Op,
    RequestFrame, ResponseFrame, RetrievalCost, RetrievalLatency, RetrievalRequest,
    RetrievalResponse, CONTRACT_VERSION,
};
use marlowe_journal::{Journal, Profile};
use marlowe_memory::consolidate::{self, Policy};
use marlowe_memory::gate::{FrozenGate, FIT_ONLY_VERSION, GATE_VERSION};
use marlowe_memory::cue::dense::embedder::Embedder;
use marlowe_memory::cue::dense::vectors::VectorStore;
use marlowe_memory::rerank::CrossEncoder;
use marlowe_memory::retrieve::{
    debug_assert_injection_valid, select_for_injection_probed, Rerank, Scoring, RERANK_BUDGET,
};
use marlowe_memory::{ingest, BeliefStore};

use crate::dump::{ConsolidationDump, FeatureDump};
use crate::elapsed::{StageTimer, Stopwatch};
use crate::profile::RetrievalProfile;

/// How this process scores.
///
/// Two variants, and there is deliberately no third that would let a run gate with default
/// weights. `Gated` can only be constructed from a validated artifact.
///
/// Both may carry a dump. The dump is a diagnostic side channel and never changes what goes on
/// the wire; the mode is what decides whether a gate exists.
enum Mode {
    Gated(FrozenGate, Option<FeatureDump>),
    FitDump(FeatureDump),
}

/// Which consolidation policy a run uses, and where its dump goes.
///
/// A struct rather than two loose arguments so a call site cannot silently pass the dry run's
/// path to a frozen run, or the reverse.
pub struct Consolidation<'a> {
    pub policy: Consolidate,
    pub dump_path: Option<&'a Path>,
}

/// How the rerank stage is configured for this run.
///
/// **Both fields are experiment knobs whose shipped values are the measured ones**, and both are
/// recorded on every retrieval-profile row rather than only in the command line. A sweep cell that
/// forgot a flag would otherwise measure one configuration under another's label — the failure this
/// project has now paid for four times — and here the artifact itself carries the answer.
#[derive(Debug, Clone, Copy)]
pub struct RerankSettings {
    /// Score the slate in one forward pass. Shipped value `false`; see `retrieve::Rerank`.
    pub batched: bool,
    /// ONNX intra-op threads. Shipped value `rerank::SHIPPED_THREADS` = 1, per ADR-003's 1-vCPU
    /// target — which M0c Session L is measuring rather than assuming.
    pub threads: usize,
    /// Which execution provider scored the slate. Stamped on every profile row: a provider is the
    /// single most consequential thing a cell can be wrong about, and this project has already
    /// produced one "GPU" figure that was CPU.
    pub provider: marlowe_memory::rerank::RerankProvider,
}

/// Where the two diagnostic side channels write, if anywhere.
///
/// Bundled for the same reason `Consolidation` is: two bare `Option<&Path>` arguments of the same
/// type, adjacent in a call, is one transposition away from writing the retrieval profile into the
/// gate-feature dump. Both would still be created, both would still be written, and the fit would
/// silently read a file of latency rows.
pub struct Diagnostics<'a> {
    /// §4.2's per-candidate feature dump. `tools/fit_gate.py` and the scoring drivers read it.
    pub gate_features: Option<&'a Path>,
    /// The per-query retrieval stage profile. Read by `tools/profile_retrieval.py`.
    pub retrieval_profile: Option<&'a Path>,
}

/// The CLI's request, before the artifact is read.
///
/// Distinct from `Policy` because `Policy::Frozen` carries a threshold that only exists once the
/// artifact has loaded. Collapsing the two would need a placeholder threshold at the call site,
/// and a placeholder that reaches clustering is a merge at a number nobody chose.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Consolidate {
    Frozen,
    DryRun,
}

pub struct Adapter {
    journal: Journal,
    beliefs: BeliefStore,
    /// The dense cue's embedder and the vectors it has produced.
    ///
    /// Both live here rather than in `BeliefStore` because vectors are a **derived view** that
    /// is never journaled — see `cue::dense::vectors`, which reuses ADR-009's reasoning: a
    /// derived plaintext key stored beside the record survives crypto-shredding and does not
    /// demote when the entry's fidelity does.
    embedder: Embedder,
    vectors: VectorStore,
    mode: Mode,
    /// §5.3 consolidation. **Not optional, and there is no "off".**
    ///
    /// `Policy::load` refuses an unregistered artifact outright, so a build either merges at a
    /// threshold somebody registered or does not start. A boolean `--consolidate` flag was the
    /// obvious alternative and is the one CLAUDE.md warns about: forget it in the harness target
    /// string and the run measures the unconsolidated system under a consolidated label, with
    /// every number still produced and nothing observing the mismatch.
    policy: Policy,
    consolidation_dump: Option<ConsolidationDump>,
    /// Session H's rerank stage. `None` is an EXPLICIT choice made at the command line
    /// (`--reranking off`), never a default -- see `main.rs`'s USAGE.
    cross_encoder: Option<CrossEncoder>,
    /// How the rerank stage is configured. See [`RerankSettings`].
    rerank: RerankSettings,
    /// The retrieval stage profile, when `--profile-retrieval` named a path.
    ///
    /// `None` is the shipped configuration, and it is what makes an unprofiled run a **true
    /// baseline**: the probe is `Option<&mut StageTimer>`, so with no profile installed the only
    /// per-query cost is one `Instant::now()` and nine null checks. The profiled and unprofiled
    /// runs go through one call site, so they cannot be two different pipelines.
    profile: Option<RetrievalProfile>,
}

impl Adapter {
    /// Start against a **fresh** profile root.
    ///
    /// `Profile::init` refuses a non-empty directory, which is what keeps state from leaking
    /// between the harness's spawns. The clock probe alone spawns four processes and compares
    /// their outputs; a shared root would make it compare contaminated runs while reporting a
    /// clean verdict.
    ///
    /// **The gate is loaded here, and a bad artifact stops the process.** Deferring the load
    /// to the first retrieval would turn a build-time mistake into a per-query error the
    /// harness would score as a class B failure — a wrong number instead of no number.
    /// `dump_path` is optional and orthogonal to gating: with a gate loaded, the dump carries
    /// this build's own verdict for every scored candidate, which is what the scoring driver
    /// reads when the gate abstains and the wire therefore carries nothing.
    pub fn start(
        profile_root: &Path,
        embedder: Embedder,
        diagnostics: Diagnostics<'_>,
        consolidation: Consolidation<'_>,
        cross_encoder: Option<CrossEncoder>,
        rerank: RerankSettings,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let gate = FrozenGate::load()?;
        let dump = diagnostics.gate_features.map(FeatureDump::create).transpose()?;
        Self::start_with(
            profile_root,
            embedder,
            Mode::Gated(gate, dump),
            consolidation,
            cross_encoder,
            rerank,
            diagnostics.retrieval_profile,
        )
    }

    /// Start in feature-dump mode. Used only by `tools/fit_gate.py`; loads no gate.
    ///
    /// **Consolidation still applies here.** The gate is fit over whatever pool retrieval will
    /// actually see, so a fit run that skipped consolidation would calibrate against a candidate
    /// set that no scoring run ever has.
    pub fn start_for_fit(
        profile_root: &Path,
        embedder: Embedder,
        dump_path: &Path,
        consolidation: Consolidation<'_>,
        cross_encoder: Option<CrossEncoder>,
        rerank: RerankSettings,
        retrieval_profile: Option<&Path>,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        Self::start_with(
            profile_root,
            embedder,
            Mode::FitDump(FeatureDump::create(dump_path)?),
            consolidation,
            cross_encoder,
            rerank,
            retrieval_profile,
        )
    }

    fn start_with(
        profile_root: &Path,
        embedder: Embedder,
        mode: Mode,
        consolidation: Consolidation<'_>,
        cross_encoder: Option<CrossEncoder>,
        rerank: RerankSettings,
        retrieval_profile: Option<&Path>,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let profile = Profile::init(profile_root)?;
        let journal = Journal::open(&profile)?;
        let beliefs = BeliefStore::derive(&journal, profile.manifest().derivation_version)?;
        // Loaded here, not at the first ingest. Same rule the gate follows: a build-time mistake
        // must stop the process, not become a per-call error the harness scores as a class B
        // failure — a wrong number instead of no number.
        let policy = match consolidation.policy {
            Consolidate::DryRun => Policy::DryRun,
            Consolidate::Frozen => Policy::load()?,
        };
        Ok(Self {
            journal,
            beliefs,
            embedder,
            vectors: VectorStore::default(),
            mode,
            policy,
            consolidation_dump: consolidation
                .dump_path
                .map(ConsolidationDump::create)
                .transpose()?,
            cross_encoder,
            rerank,
            profile: retrieval_profile.map(RetrievalProfile::create).transpose()?,
        })
    }

    /// The serial request/response loop (section 4.0.5).
    pub fn run(
        &mut self,
        input: impl BufRead,
        mut output: impl Write,
    ) -> Result<(), Box<dyn std::error::Error>> {
        for line in input.lines() {
            let line = line?;
            if line.trim().is_empty() {
                continue;
            }
            let frame = self.handle_line(&line);
            // Section 4.0.2: one `\n`, never `\r\n`, and flush after every frame. A response
            // sitting in a buffer is indistinguishable from a hang.
            output.write_all(frame.to_line().as_bytes())?;
            output.write_all(b"\n")?;
            output.flush()?;
        }
        Ok(())
    }

    fn handle_line(&mut self, line: &str) -> ResponseFrame {
        // A frame we cannot even parse has no `op` to echo. Section 4.0.3 requires `op` to
        // echo the request's, so there is genuinely nothing correct to send -- `ingest` is
        // used as a placeholder and the harness aborts on the class A kind regardless.
        let frame: RequestFrame = match serde_json::from_str(line) {
            Ok(f) => f,
            Err(e) => {
                return ResponseFrame::error(
                    Op::Ingest,
                    ErrorKind::MalformedFrame,
                    format!("could not parse request frame: {e}"),
                )
            }
        };

        match frame.op {
            Op::Ingest => self.handle_ingest(frame.body),
            Op::Retrieve => self.handle_retrieve(frame.body),
            Op::Answer => self.handle_answer(frame.body),
        }
    }

    fn handle_ingest(&mut self, body: serde_json::Value) -> ResponseFrame {
        let request: IngestRequest = match serde_json::from_value(body) {
            Ok(r) => r,
            Err(e) => return malformed_body(Op::Ingest, e),
        };
        if let Some(frame) = check_version(Op::Ingest, &request.contract_version) {
            return frame;
        }

        let stopwatch = Stopwatch::start();
        let outcome = match ingest(&mut self.journal, &mut self.beliefs, &request) {
            Ok(o) => o,
            // Class B: we failed on a well-formed request. A RESULT -- the harness scores the
            // unit and continues. Dying here would make a recoverable bug indistinguishable
            // from a crash and throw away the rest of the run.
            Err(e) => {
                return ResponseFrame::error(Op::Ingest, ErrorKind::InternalError, e.to_string())
            }
        };

        // Embed the newly written memories. **Batched deliberately**: one LongMemEval ingest is
        // ~493 turns, and embedding them one at a time would serialize the run's dominant cost.
        // Failure is a class B result rather than a panic -- the write already happened and the
        // journal is the source of truth; a missing vector degrades the dense cue to 0.0 for
        // that entry, which `retrieve::dense_for` reports honestly rather than hiding.
        if let Err(e) = self.vectors.embed_missing(&self.beliefs, &mut self.embedder) {
            return ResponseFrame::error(
                Op::Ingest,
                ErrorKind::InternalError,
                format!("embedding the ingested memories failed: {e}"),
            );
        }

        // §5.3's consolidation pass, at **session close** — which for a benchmark that ingests a
        // whole synthetic session in one call is the end of that call. It runs after embedding
        // because the merge rule reads the dense vectors, and before any retrieval, so nothing
        // here touches the §4.1 path or its 300 ms budget.
        //
        // It reads `request.clock`, never a system clock: §4.5 is binding on every path reachable
        // from §4.6, and this is one.
        let consolidation_watch = Stopwatch::start();
        let report = match self.policy {
            // Sweeps every threshold and applies nothing. `apply` refuses the report it produces.
            Policy::DryRun => Ok(consolidate::dry_run(
                &self.beliefs,
                &request.session_id,
                &self.vectors,
            )),
            Policy::Frozen { .. } => consolidate::consolidate(
                &mut self.journal,
                &mut self.beliefs,
                &request.session_id,
                request.clock,
                &self.vectors,
                self.policy,
            ),
        };
        let report = match report {
            Ok(r) => r,
            // Class B, like the ingest failure above: the writes already happened and the journal
            // is the source of truth. Dying here would make a recoverable bug indistinguishable
            // from a crash and throw away the rest of the run.
            Err(e) => {
                return ResponseFrame::error(
                    Op::Ingest,
                    ErrorKind::InternalError,
                    format!("consolidating {} failed: {e}", request.session_id),
                )
            }
        };
        let consolidation_ms = consolidation_watch.stop().as_cost_ms();

        if let Some(dump) = self.consolidation_dump.as_mut() {
            if let Err(e) = dump.write(&report, consolidation_ms) {
                // Loud, for the same reason a truncated feature dump is: a partial sweep would
                // have a threshold chosen from it and nothing downstream could tell.
                eprintln!("marlowe: consolidation dump failed: {e}");
                std::process::exit(1);
            }
        }

        let latency = stopwatch.stop().as_cost_ms();

        let response = IngestResponse {
            contract_version: ContractVersion,
            session_id: request.session_id.clone(),
            written: outcome.written,
            rejected: outcome.rejected,
            cost: IngestCost {
                // No model call happens on ingest in Session A: writes on the hot path are
                // "cheap and dumb" per brief §5.3, and intelligence happens offline. Zero is
                // the true count, not a placeholder.
                ingest_tokens: 0,
                latency_ms: IngestLatency { total: latency },
            },
        };
        body_frame(Op::Ingest, &response)
    }

    fn handle_retrieve(&mut self, body: serde_json::Value) -> ResponseFrame {
        let request: RetrievalRequest = match serde_json::from_value(body) {
            Ok(r) => r,
            Err(e) => return malformed_body(Op::Retrieve, e),
        };
        if let Some(frame) = check_version(Op::Retrieve, &request.contract_version) {
            return frame;
        }

        let stopwatch = Stopwatch::start();
        let response = self.retrieve(&request, stopwatch);
        if let Err(e) = response.check_exclusivity() {
            // Our own outbound check. The harness enforces these too; catching it here means
            // a bug reports as a bug rather than as an aborted run of somebody's benchmark.
            return ResponseFrame::error(
                Op::Retrieve,
                ErrorKind::InternalError,
                format!("outbound section 4.2 violation: {e}"),
            );
        }
        body_frame(Op::Retrieve, &response)
    }

    fn retrieve(&mut self, request: &RetrievalRequest, stopwatch: Stopwatch) -> RetrievalResponse {
        // The cue and the gate run inside `select_for_injection`, so the two stages are timed
        // as one span rather than reported separately. §4.2's breakdown fields are optional
        // and absent stages are omitted; splitting one measured span into two invented halves
        // would be worse than reporting the span honestly under the stage that dominates it.
        let cue_watch = Stopwatch::start();

        // The query's own embedding -- one forward pass, and the whole per-query cost of the
        // dense cue. On failure the cue degrades to 0.0 for every candidate rather than the
        // request failing: retrieval that returns nothing is a worse answer than retrieval that
        // returns what the lexical cue found, and `dense_for` scores a missing query vector as
        // no evidence rather than skipping candidates.
        //
        // **Timed separately from every other stage, deliberately.** This is the one stage a warm
        // embedding cache deletes from the run, so folding it into the pipeline's span would make
        // a cold profile and a warm profile the same shape with different totals -- the trap
        // STATE.md records by name. `hits_before` is what tells the two apart afterwards.
        let embed_watch = Stopwatch::start();
        let hits_before = self.embedder.cache_stats().map(|(hits, _)| hits);
        let query_vector = match self.embedder.embed(&request.query_text) {
            Ok(v) => Some(v),
            Err(e) => {
                eprintln!("marlowe: query embedding failed, dense cue degraded to zero: {e}");
                None
            }
        };
        let embed_us = embed_watch.elapsed_us();
        let embed_was_cached = match (hits_before, self.embedder.cache_stats()) {
            (Some(before), Some((after, _))) => after > before,
            // No cache is configured, so nothing was served from one. Distinct from "the cache
            // missed", which is why the profile carries the flag rather than inferring it from a
            // small `embed_us`.
            _ => false,
        };

        let scoring = match &self.mode {
            Mode::Gated(gate, _) => Scoring::Gated(gate),
            Mode::FitDump(_) => Scoring::FitDump,
        };
        // One call site for both configurations. See `Adapter::profile` and
        // `marlowe_memory::probe`: the timer is installed only when a profile path was given, and
        // the probe is `Option<&mut _>` so there is no second copy of this call to drift from.
        let mut timer = StageTimer::start();
        let mut probe = self.profile.as_ref().map(|_| &mut timer);
        let selection = select_for_injection_probed(
            &self.beliefs,
            &request.session_id,
            &request.query_text,
            request.clock.now_ms,
            request.budget.max_tokens,
            &scoring,
            &self.vectors,
            query_vector.as_deref(),
            &mut match self.cross_encoder.as_mut() {
                Some(encoder) => {
                    Rerank::CrossEncoder { encoder, budget: RERANK_BUDGET, batched: self.rerank.batched }
                }
                None => Rerank::Off,
            },
            &mut probe,
        );
        // Captured HERE, the instant the pipeline returns. Reading it later — inside the profile
        // write, which is where the first draft read it — folds the gate-feature dump's ~1.5 ms
        // into the span and reports it as retrieval residual. See `RetrievalProfile::write`.
        let span_us = timer.span();
        let cues_ms = cue_watch.stop().as_cost_ms();
        debug_assert_injection_valid(&selection.injected);

        let (version, threshold) = match &self.mode {
            Mode::Gated(gate, _) => (GATE_VERSION.to_string(), gate.threshold()),
            // A mode that computed features but calibrated nothing must not be stampable as
            // one that gated. Same rule as Session A's `ungated-v0`.
            Mode::FitDump(_) => (FIT_ONLY_VERSION.to_string(), 0.0),
        };

        // Section 4.2: abstention and injection are mutually exclusive **in both
        // directions**. Injecting nothing IS the abstention outcome, so an empty set must
        // carry a reason rather than be reported as a non-abstention.
        let abstained = selection.injected.is_empty();
        let abstention_reason = if !abstained {
            None
        } else if selection.budget_exhausted {
            Some(AbstentionReason::BudgetExhausted)
        } else if selection.scoped > 0 && selection.above_threshold == 0 {
            // The gate's own abstention, and the first run in which this value is truthful:
            // candidates existed and every one of them scored below the operating point.
            // Session A could not report it, because there was no threshold to fall below.
            Some(AbstentionReason::NoCandidateAboveThreshold)
        } else {
            // Nothing was eligible at all: the store is empty for this session, or every
            // candidate is still maturing.
            Some(AbstentionReason::NoCandidates)
        };

        let dumped = match &mut self.mode {
            Mode::FitDump(dump) => Some((dump, false)),
            Mode::Gated(_, Some(dump)) => Some((dump, true)),
            Mode::Gated(_, None) => None,
        };
        if let Some((dump, gated)) = dumped {
            if let Err(e) = dump
                .write(&request.query_id, &selection.scored, gated)
                .and_then(|_| dump.flush())
            {
                // Loud. A truncated dump would produce a calibration fit on a silently partial
                // sample, and nothing downstream could tell.
                eprintln!("marlowe: gate-feature dump failed: {e}");
                std::process::exit(1);
            }
        }

        // **The wire's latency is read HERE, before the profile is written.**
        //
        // The gate-feature dump above is inside the span and stays inside it — every published
        // latency in this project was measured with it there, and moving it now would change the
        // baseline as a side effect of adding an instrument. The profile write is deliberately
        // outside, so `--profile-retrieval` cannot inflate the number it exists to explain. That
        // asymmetry is the point, not an oversight.
        //
        // `total_us` is the same span at microsecond resolution, read a few nanoseconds earlier
        // off the same `Instant`. It is what the profile reconciles its stages against: the wire
        // reports whole milliseconds, and a 200 ms span rounded to milliseconds cannot tell a
        // complete breakdown from one missing 400 us.
        let total_us = stopwatch.elapsed_us();
        let total_ms = stopwatch.stop().as_cost_ms();

        if let Some(profile) = self.profile.as_mut() {
            if let Err(e) = profile.write(
                &request.query_id,
                embed_us,
                embed_was_cached,
                &timer,
                span_us,
                total_us,
                self.rerank,
                &selection,
            ) {
                // Loud, for the same reason a truncated feature dump is: a profile missing rows
                // is a P95 over a population nobody chose, and nothing downstream could tell.
                eprintln!("marlowe: retrieval profile write failed: {e}");
                std::process::exit(1);
            }
        }

        RetrievalResponse {
            contract_version: ContractVersion,
            query_id: request.query_id.clone(),
            abstained,
            abstention_reason,
            injected: selection.injected,
            considered: selection.considered,
            gate: GateStamp {
                version,
                threshold,
                // False for M0. Only M10 may set this true, and only after beating the
                // frozen baseline at equal or lower cost.
                adaptive: false,
            },
            cost: RetrievalCost {
                retrieval_tokens: selection.retrieval_tokens,
                latency_ms: RetrievalLatency {
                    total: total_ms,
                    cues: Some(cues_ms),
                    // Still absent, and still omitted rather than zeroed: there is no embedder
                    // (ADR-004 is unwired) and nothing to fuse with one cue. A zero would read
                    // as a measurement of a stage that does not exist.
                    ..Default::default()
                },
            },
        }
    }

    fn handle_answer(&mut self, body: serde_json::Value) -> ResponseFrame {
        let request: AnswerRequest = match serde_json::from_value(body) {
            Ok(r) => r,
            Err(e) => return malformed_body(Op::Answer, e),
        };
        if let Some(frame) = check_version(Op::Answer, &request.contract_version) {
            return frame;
        }

        let stopwatch = Stopwatch::start();
        let retrieval_request = RetrievalRequest {
            contract_version: CONTRACT_VERSION.to_string(),
            clock: request.clock,
            query_id: request.query_id.clone(),
            session_id: request.session_id.clone(),
            turn_index: 0,
            query_text: request.question.clone(),
            budget: marlowe_contract::RetrievalBudget {
                max_tokens: 7000,
                max_latency_ms: 300,
            },
        };
        let retrieval_watch = Stopwatch::start();
        let retrieval = self.retrieve(&retrieval_request, retrieval_watch);
        let retrieval_tokens = retrieval.cost.retrieval_tokens;
        let retrieval_latency = retrieval.cost.latency_ms.total;

        // Session A has no generator wired, so **every answer is an honest abstention**.
        //
        // `degraded_path` is the accurate reason and is true in every case here, including
        // when retrieval found plenty: the answer path itself is what is degraded. Reusing
        // retrieval's `no_candidates` would be a lie whenever memories were injected, and
        // section 4.7 exists to stop exactly that kind of blur -- "a schema that lets two
        // outcomes blur is a schema that will let a confabulation score as an abstention."
        let response = AnswerResponse {
            contract_version: ContractVersion,
            query_id: request.query_id.clone(),
            answered: false,
            answer: None,
            abstained: true,
            abstention_reason: Some(AbstentionReason::DegradedPath),
            // An abstention requires an empty `grounded_in`: a refusal that cites grounding
            // is claiming to have answered from evidence while reporting that it declined.
            grounded_in: Vec::new(),
            retrieval,
            cost: AnswerCost {
                prompt_tokens: 0,
                completion_tokens: 0,
                retrieval_tokens,
                latency_ms: AnswerLatency {
                    total: stopwatch.stop().as_cost_ms(),
                    retrieval: Some(retrieval_latency),
                    // No generation stage exists. Omitted rather than reported as zero.
                    generation: None,
                },
            },
        };

        if let Err(e) = response.check_exclusivity() {
            return ResponseFrame::error(
                Op::Answer,
                ErrorKind::InternalError,
                format!("outbound section 4.7 violation: {e}"),
            );
        }
        body_frame(Op::Answer, &response)
    }
}

fn body_frame(op: Op, response: &impl serde::Serialize) -> ResponseFrame {
    match serde_json::to_value(response) {
        Ok(value) => ResponseFrame::body(op, value),
        Err(e) => ResponseFrame::error(op, ErrorKind::InternalError, e.to_string()),
    }
}

fn malformed_body(op: Op, error: serde_json::Error) -> ResponseFrame {
    // Section 4.0.4 class A. This is where an unrecognized `channel` lands: the closed enum
    // refuses to deserialize, so the harness aborts loudly instead of the value being mapped
    // to a default nobody chose.
    ResponseFrame::error(op, ErrorKind::MalformedBody, error.to_string())
}

fn check_version(op: Op, found: &str) -> Option<ResponseFrame> {
    if found == CONTRACT_VERSION {
        return None;
    }
    Some(ResponseFrame::error(
        op,
        ErrorKind::ContractVersionUnsupported,
        format!("this build speaks {CONTRACT_VERSION}, the request declared {found}"),
    ))
}
