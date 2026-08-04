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
use marlowe_memory::gate::{FrozenGate, FIT_ONLY_VERSION, GATE_VERSION};
use marlowe_memory::retrieve::{debug_assert_injection_valid, select_for_injection, Scoring};
use marlowe_memory::{ingest, BeliefStore};

use crate::dump::FeatureDump;
use crate::elapsed::Stopwatch;

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

pub struct Adapter {
    journal: Journal,
    beliefs: BeliefStore,
    mode: Mode,
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
        dump_path: Option<&Path>,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let gate = FrozenGate::load()?;
        let dump = dump_path.map(FeatureDump::create).transpose()?;
        Self::start_with(profile_root, Mode::Gated(gate, dump))
    }

    /// Start in feature-dump mode. Used only by `tools/fit_gate.py`; loads no gate.
    pub fn start_for_fit(
        profile_root: &Path,
        dump_path: &Path,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        Self::start_with(profile_root, Mode::FitDump(FeatureDump::create(dump_path)?))
    }

    fn start_with(profile_root: &Path, mode: Mode) -> Result<Self, Box<dyn std::error::Error>> {
        let profile = Profile::init(profile_root)?;
        let journal = Journal::open(&profile)?;
        let beliefs = BeliefStore::derive(&journal, profile.manifest().derivation_version)?;
        Ok(Self {
            journal,
            beliefs,
            mode,
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
        let scoring = match &self.mode {
            Mode::Gated(gate, _) => Scoring::Gated(gate),
            Mode::FitDump(_) => Scoring::FitDump,
        };
        let selection = select_for_injection(
            &self.beliefs,
            &request.session_id,
            &request.query_text,
            request.clock.now_ms,
            request.budget.max_tokens,
            &scoring,
        );
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
                    total: stopwatch.stop().as_cost_ms(),
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
