//! `marlowe --eval-adapter` — CONTRACTS.md section 4.0.
//!
//! Reads request frames on stdin, writes response frames on stdout, one JSON value per line.
//! The harness owns the process lifetime and ends the run by closing stdin.
//!
//! Section 4.0.1 describes this as a thin forwarding mode over the daemon. There is no daemon
//! yet, so Session A hosts the journal and belief store in-process. The wire is identical
//! either way, which is the point of pinning the wire rather than the plumbing.

use std::io::{BufRead, Write};

use marlowe_contract::{
    AbstentionReason, AnswerCost, AnswerLatency, AnswerRequest, AnswerResponse, ContractVersion,
    ErrorKind, GateStamp, IngestCost, IngestLatency, IngestRequest, IngestResponse, Op,
    RequestFrame, ResponseFrame, RetrievalCost, RetrievalLatency, RetrievalRequest,
    RetrievalResponse, CONTRACT_VERSION,
};
use marlowe_journal::{Journal, Profile};
use marlowe_memory::retrieve::{debug_assert_injection_valid, select_for_injection, UNGATED_VERSION};
use marlowe_memory::{ingest, BeliefStore};

use crate::elapsed::Stopwatch;

pub struct Adapter {
    journal: Journal,
    beliefs: BeliefStore,
}

impl Adapter {
    /// Start against a **fresh** profile root.
    ///
    /// `Profile::init` refuses a non-empty directory, which is what keeps state from leaking
    /// between the harness's spawns. The clock probe alone spawns four processes and compares
    /// their outputs; a shared root would make it compare contaminated runs while reporting a
    /// clean verdict.
    pub fn start(profile_root: &std::path::Path) -> Result<Self, Box<dyn std::error::Error>> {
        let profile = Profile::init(profile_root)?;
        let journal = Journal::open(&profile)?;
        let beliefs = BeliefStore::derive(&journal, profile.manifest().derivation_version)?;
        Ok(Self { journal, beliefs })
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

    fn retrieve(&self, request: &RetrievalRequest, stopwatch: Stopwatch) -> RetrievalResponse {
        let selection = select_for_injection(
            &self.beliefs,
            &request.session_id,
            request.clock.now_ms,
            request.budget.max_tokens,
        );
        debug_assert_injection_valid(&selection.injected);

        // Section 4.2: abstention and injection are mutually exclusive **in both
        // directions**. Injecting nothing IS the abstention outcome, so an empty set must
        // carry a reason rather than be reported as a non-abstention.
        let abstained = selection.injected.is_empty();
        let abstention_reason = if !abstained {
            None
        } else if selection.budget_exhausted {
            Some(AbstentionReason::BudgetExhausted)
        } else {
            // Everything else in Session A is "there was nothing eligible": either the store
            // is empty for this session, or every candidate is still maturing. Both are
            // `no_candidates` -- there is no threshold yet for anything to fall below, so
            // `no_candidate_above_threshold` would name a mechanism that does not exist.
            Some(AbstentionReason::NoCandidates)
        };

        RetrievalResponse {
            contract_version: ContractVersion,
            query_id: request.query_id.clone(),
            abstained,
            abstention_reason,
            injected: selection.injected,
            considered: selection.considered,
            gate: GateStamp {
                version: UNGATED_VERSION.to_string(),
                threshold: 0.0,
                // False for M0. Only M10 may set this true, and only after beating the
                // frozen baseline at equal or lower cost.
                adaptive: false,
            },
            cost: RetrievalCost {
                retrieval_tokens: selection.retrieval_tokens,
                latency_ms: RetrievalLatency {
                    total: stopwatch.stop().as_cost_ms(),
                    // Absent stages are omitted, never zeroed: there is no embed, cue, fuse
                    // or gate stage to time, and a zero would read as a measurement.
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
