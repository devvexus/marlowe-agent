//! The driver. Speaks Ollama's `/api/chat`, returns a [`ModelStep`].
//!
//! # Degrading honestly (ADR-028 requirement 1, invariant 4)
//!
//! An absent endpoint is **not** a crash and **not** a silent fallback. [`Availability::probe`]
//! answers three distinguishable questions — is anything listening, does it speak Ollama, is the
//! routed model present — because the remedies differ and a user cannot act on "unavailable".
//! Each answer carries the command that fixes it.

use std::time::Duration;

use marlowe_loop::{
    CallLimits, ClaimRequest, CondensedResult, ContextView, DegradedPath, ModelCall, ModelDriver,
    ModelStep, ProviderError, Usage,
};
use marlowe_permission::{ArgValue, Args};
use marlowe_tools::{ExposedSet, ToolId, ToolRegistry};

use crate::capability::ModelCapability;
use crate::http::{self, HttpError, LocalEndpoint};
use crate::routing::Routing;

/// The pinned default, chosen on **measured tool-call reliability** (ADR-028 requirement 2).
///
/// **Measured 2026-08-08, `tests/tool_call_probe.rs`, 12 trials: 12/12 well-formed, 12/12 with
/// the correct target, median 1666 ms.**
///
/// **And the honest qualification, because a point estimate is not an interval.** 12/12 is a
/// perfect score on twelve trials; the 95% Clopper-Pearson lower bound is ≈0.74, which is *below*
/// [`crate::capability::MIN_RATE`]. So this clears the bar **on the point estimate and not with
/// its interval** — the same distinction K1's amendment turns on, and it is stated here rather
/// than rounded away. Twelve trials is thin; the number to raise is
/// [`crate::capability::MIN_TRIALS`], and raising it costs only probe time.
///
/// It is a constant so the choice is one line to change and one line to review.
pub const DEFAULT_MODEL: &str = "qwen3.5:9b";

/// What [`DEFAULT_MODEL`] was measured to do, so a run can disclose it without re-measuring.
///
/// A build that changes `DEFAULT_MODEL` and not this is a build that discloses one model's
/// number under another model's name — so the pair is asserted in `tests`.
pub fn default_capability() -> ModelCapability {
    ModelCapability {
        model: DEFAULT_MODEL.to_string(),
        parameters: Some("9B".into()),
        tool_calls: Some(crate::capability::ToolCallReport {
            trials: 12,
            well_formed: 12,
            correct_target: 12,
            measured_on: "2026-08-08".into(),
            median_ms: 1666,
        }),
    }
}

pub const DEFAULT_TIMEOUT: Duration = Duration::from_secs(180);

/// What is wrong, specifically enough to fix.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Availability {
    Ready { models: Vec<String> },
    /// Nothing is listening.
    EndpointDown { endpoint: String },
    /// Something answered but it is not Ollama.
    NotOllama { endpoint: String, detail: String },
    /// Ollama is up; the routed model is not pulled.
    ModelMissing { model: String, available: Vec<String> },
}

impl Availability {
    pub fn is_ready(&self) -> bool {
        matches!(self, Availability::Ready { .. })
    }

    /// The line the user sees. **Names the remedy**, because a degraded state a user cannot act
    /// on is a crash with better manners.
    pub fn remedy(&self) -> String {
        match self {
            Availability::Ready { .. } => "ready".into(),
            Availability::EndpointDown { endpoint } => format!(
                "no model available — nothing is listening on {endpoint}. Start it with \
                 `ollama serve`"
            ),
            Availability::NotOllama { endpoint, detail } => format!(
                "no model available — something is listening on {endpoint} but it is not Ollama \
                 ({detail})"
            ),
            Availability::ModelMissing { model, available } => {
                let have = if available.is_empty() {
                    "none are pulled".to_string()
                } else {
                    format!("available: {}", available.join(", "))
                };
                format!("no model available — `{model}` is not pulled. Run `ollama pull {model}` ({have})")
            }
        }
    }

    /// §B5's status band carries this, in amber. Invariant 4: the flag is on the run, so silent
    /// degradation is not representable.
    pub fn degraded_path(&self) -> Option<DegradedPath> {
        (!self.is_ready()).then_some(DegradedPath::ModelUnavailable)
    }

    pub fn probe(endpoint: &LocalEndpoint, routing: &Routing) -> Self {
        let tags = match http::get_json(endpoint, "/api/tags", Duration::from_secs(5)) {
            Ok(v) => v,
            Err(HttpError::Unreachable { .. }) => {
                return Availability::EndpointDown { endpoint: endpoint.to_string() }
            }
            Err(e) => {
                return Availability::NotOllama {
                    endpoint: endpoint.to_string(),
                    detail: e.to_string(),
                }
            }
        };
        let Some(models) = tags.get("models").and_then(|m| m.as_array()) else {
            return Availability::NotOllama {
                endpoint: endpoint.to_string(),
                detail: "no `models` array in /api/tags".into(),
            };
        };
        let names: Vec<String> = models
            .iter()
            .filter_map(|m| m.get("name").and_then(|n| n.as_str()).map(str::to_string))
            .collect();

        for wanted in routing.models() {
            if !names.iter().any(|n| n == wanted || n == &format!("{wanted}:latest")) {
                return Availability::ModelMissing {
                    model: wanted.to_string(),
                    available: names,
                };
            }
        }
        Availability::Ready { models: names }
    }
}

/// The context window used when none is given, in tokens.
///
/// **Declared and always sent, never inferred.** Ollama's own default is 2048 whatever the model
/// supports; a request that omits `num_ctx` gets it silently. Measured on this machine before
/// pinning — see STATE.md.
pub const DEFAULT_CONTEXT_TOKENS: u32 = 32_768;

/// What `qwen3.5:9b` reports it supports, recorded so a model swap has something to compare to.
///
/// **Not the default**: the whole window is a KV-cache commitment and 262k on a 9B model is far
/// more memory than a terminal session should take. Recorded, not used.
pub const MODEL_CONTEXT_CEILING: u32 = 262_144;

/// A sink for raw provider frames, before any interpretation.
///
/// **`--dev` only.** A slow turn and a hung one are indistinguishable from the outside, and the
/// pre-parse frames are the only view that separates *the model is emitting slowly* from *nothing
/// is arriving*. That is a diagnostic, not conversation, so it does not go near the transcript.
pub type RawFrameSink = Box<dyn FnMut(&serde_json::Value) + Send>;

/// A sink for the **outbound request body**, as it goes over the wire.
///
/// # This closes a blind spot a source-level test cannot see
///
/// `persona_emission.rs` asserts that `request_body` places the persona in the system role. It
/// passes whether the deployed binary is current or six commits stale — and in M2 C2e it did
/// exactly that: the persona was correctly wired, the test was green, and the daemon had been
/// serving pre-persona code for an hour because the release binary was never rebuilt.
///
/// **Source-verified is weaker than deployment-verified.** The only reading that settles "is the
/// persona reaching the model" is the bytes the running process sent, so this exists to produce
/// them. Fourth instance of one shape; see CLAUDE.md's table.
pub type RequestSink = Box<dyn FnMut(&serde_json::Value) + Send>;

pub struct OllamaDriver {
    endpoint: LocalEndpoint,
    routing: Routing,
    registry: ToolRegistry,
    capability: ModelCapability,
    timeout: Duration,
    raw_frames: Option<RawFrameSink>,
    request_dump: Option<RequestSink>,
    /// The context window, in tokens, carried on **every** request as `num_ctx`.
    ///
    /// **Ollama defaults this to 2048 regardless of what the model supports**, and until M2 C2e
    /// nothing set it — so a 262,144-token model ran in a 2,048-token window and silently
    /// truncated history, injected memory and tool results. Worse, the assembler was packing to
    /// 32,000: two numbers, disagreeing, with §6's compaction trigger computed from the wrong one.
    ///
    /// **This is the single source.** `Engine`'s assembler window is derived from the same value;
    /// see `marlowe-daemon`'s `Daemon::ask` and `tests/context_window.rs`.
    context_tokens: u32,
}

impl OllamaDriver {
    pub fn new(endpoint: LocalEndpoint, routing: Routing, registry: ToolRegistry) -> Self {
        let capability = ModelCapability::unmeasured(routing.model_for(
            marlowe_loop::ModelRoute::Orchestrator,
        ));
        Self {
            endpoint,
            routing,
            registry,
            capability,
            timeout: DEFAULT_TIMEOUT,
            raw_frames: None,
            request_dump: None,
            context_tokens: DEFAULT_CONTEXT_TOKENS,
        }
    }

    pub fn with_capability(mut self, capability: ModelCapability) -> Self {
        self.capability = capability;
        self
    }

    pub fn capability(&self) -> &ModelCapability {
        &self.capability
    }

    pub fn availability(&self) -> Availability {
        Availability::probe(&self.endpoint, &self.routing)
    }

    /// The exposed tools, in Ollama's function schema. Only exposed tools are described —
    /// registration is unlimited, exposure is what the model sees (§7.2).
    fn tool_schema(&self, exposed: &ExposedSet) -> serde_json::Value {
        let tools: Vec<serde_json::Value> = exposed
            .iter()
            .filter_map(|id| self.registry.get(id))
            .map(|reg| {
                let properties: serde_json::Map<String, serde_json::Value> = reg
                    .manifest
                    .params()
                    .iter()
                    .map(|p| {
                        (
                            p.name.clone(),
                            serde_json::json!({
                                "type": "string",
                                "description": format!("{:?} · {:?}", p.role, p.ty),
                            }),
                        )
                    })
                    .collect();
                serde_json::json!({
                    "type": "function",
                    "function": {
                        "name": reg.id.as_str(),
                        // A third-party description is untrusted input (§7.2). It is passed
                        // through verbatim rather than filtered — containment is the trust class
                        // and the assembler's tier, not a sanitizer — but it is bounded, which
                        // `Description::new` already did at registration.
                        "description": reg.description.text(),
                        "parameters": { "type": "object", "properties": properties },
                    }
                })
            })
            .collect();
        serde_json::Value::Array(tools)
    }
}

impl OllamaDriver {
    /// The outbound request, built and returned rather than sent.
    ///
    /// **Extracted so the persona can be asserted where it actually matters.** Addendum C §C6 puts
    /// the persona in the stable tier of the system prompt, and the only check worth having is
    /// that it reaches *this* value — the bytes that go to the provider. A test that loaded
    /// `persona/v1.md` and asserted it was non-empty would prove the file loaded and nothing else.
    ///
    /// That is the same distinction as `get_providers()` reporting *registered* execution
    /// providers versus where nodes actually ran (M0c Session L), and as a pipe-tested hook
    /// matcher versus an observed permission prompt. Three subsystems, one shape.
    pub fn request_body(
        &self,
        view: &ContextView,
        tools: &ExposedSet,
        limits: CallLimits,
    ) -> serde_json::Value {
        let model = self.routing.model_for(marlowe_loop::ModelRoute::Orchestrator).to_string();

        // The three tiers become three messages in order, so the stable prefix stays stable and
        // cache-friendly (§6). Governance is in `stable` and therefore always first.
        let mut messages = Vec::new();
        for block in view.stable.iter() {
            messages.push(serde_json::json!({ "role": "system", "content": block.text }));
        }
        for block in view.context.iter().chain(view.volatile.iter()) {
            messages.push(serde_json::json!({ "role": "user", "content": block.text }));
        }

        serde_json::json!({
            "model": model,
            "messages": messages,
            "tools": self.tool_schema(tools),
            "stream": true,
            "options": {
                // The budget's hard cap, handed to the provider. `budget` is explicit that this
                // is the mechanism and the top-of-loop check is only the backstop.
                "num_predict": limits.max_output_tokens.min(i32::MAX as u64) as i64,
                // **Never omitted.** Omitting it is Ollama's 2048, which is the permissive
                // default this project keeps deleting — and it was live the whole time.
                "num_ctx": self.context_tokens,
            }
        })
    }
}

impl OllamaDriver {
    /// Attach a raw-frame sink. `--dev` wires this; nothing else does.
    pub fn with_raw_frames(mut self, sink: RawFrameSink) -> Self {
        self.raw_frames = Some(sink);
        self
    }

    /// Attach an outbound-request sink. `--dev` wires this; nothing else does.
    pub fn with_request_dump(mut self, sink: RequestSink) -> Self {
        self.request_dump = Some(sink);
        self
    }

    /// Set the context window. **The same number must reach the assembler** — see
    /// [`DEFAULT_CONTEXT_TOKENS`].
    pub fn with_context_tokens(mut self, tokens: u32) -> Self {
        self.context_tokens = tokens;
        self
    }

    pub fn context_tokens(&self) -> u32 {
        self.context_tokens
    }
}

impl ModelDriver for OllamaDriver {
    fn call(
        &mut self,
        view: &ContextView,
        tools: &ExposedSet,
        limits: CallLimits,
    ) -> Result<ModelCall, ProviderError> {
        self.call_streaming(view, tools, limits, &mut |_| {})
    }

    /// This driver streams, so the engine must not re-emit the assembled reply.
    fn streams(&self) -> bool {
        true
    }

    fn call_streaming(
        &mut self,
        view: &ContextView,
        tools: &ExposedSet,
        limits: CallLimits,
        on_delta: &mut dyn FnMut(&str),
    ) -> Result<ModelCall, ProviderError> {
        let body = self.request_body(view, tools, limits);

        // **The bytes that actually go out**, dumped before they are sent. Not the same claim as
        // a test asserting on a body built in a test process — see `RequestSink`.
        if let Some(sink) = self.request_dump.as_mut() {
            sink(&body);
        }

        // **Streamed, and the frames are folded as they land.** Layer 2 of the loop still emits
        // one `TextDelta` per `Say`, so this alone does not put tokens on screen — what it does
        // is make them exist incrementally at all, and feed `--dev`'s raw view.
        let mut stream = http::post_ndjson(&self.endpoint, "/api/chat", &body, self.timeout)
            .map_err(|e| ProviderError {
                detail: format!("{e}"),
                // Unreachable is worth a failover attempt; a malformed body is not — it will be
                // malformed on the next provider too.
                retriable: matches!(e, HttpError::Unreachable { .. }),
            })?;

        let mut text = String::new();
        let mut tool_calls: Vec<serde_json::Value> = Vec::new();
        let mut usage = Usage { prompt_tokens: 0, completion_tokens: 0, micros_usd: 0, wall_ms: 0 };

        while let Some(frame) = stream.next_value() {
            // LOOP-EXEMPT: consuming a response stream, not a driving loop.
            let frame = frame.map_err(|e| ProviderError {
                detail: format!("{e}"),
                retriable: matches!(e, HttpError::Unreachable { .. }),
            })?;

            // **The raw frame, before any interpretation.** §B1 keeps memory out of the
            // interface; this is not memory, it is the provider's own wire, and it is the only
            // view that separates "the model is emitting slowly" from "nothing is arriving".
            // Behind `--dev` because it is diagnostic, not conversation.
            if let Some(sink) = self.raw_frames.as_mut() {
                sink(&frame);
            }

            if let Some(msg) = frame.get("message") {
                if let Some(c) = msg.get("content").and_then(|c| c.as_str()) {
                    if !c.is_empty() {
                        // Out to the surface immediately, and kept for the assembled `Say`.
                        on_delta(c);
                    }
                    text.push_str(c);
                }
                if let Some(calls) = msg.get("tool_calls").and_then(|t| t.as_array()) {
                    tool_calls.extend(calls.iter().cloned());
                }
            }
            // Ollama sends the counters on the final frame only.
            if frame.get("done").and_then(|d| d.as_bool()) == Some(true) {
                usage.prompt_tokens =
                    frame.get("prompt_eval_count").and_then(|v| v.as_u64()).unwrap_or(0);
                usage.completion_tokens =
                    frame.get("eval_count").and_then(|v| v.as_u64()).unwrap_or(0);
                usage.wall_ms = frame
                    .get("total_duration")
                    .and_then(|v| v.as_u64())
                    .map(|ns| ns / 1_000_000)
                    .unwrap_or(0);
            }
        }

        // Reassembled into the same shape the non-streaming path produced, so `parse_step` is
        // unchanged and the four loop-control tools keep their routing.
        let mut message = serde_json::json!({ "content": text });
        if !tool_calls.is_empty() {
            message["tool_calls"] = serde_json::Value::Array(tool_calls);
        }
        let step = parse_step(&message);
        Ok(ModelCall { usage, step })
    }
}

/// Four of the eleven tools are LOOP CONTROL, not tool-host executions.
///
/// `done`, `ask`, `remember` and `run` are `ModelStep` variants in ARCHITECTURE §3's match —
/// they end a run, escalate, request a memory write, and spawn a child. A provider that mapped
/// them to `ModelStep::ToolCall` would send them to the tool host, which has no executor for
/// any of them.
///
/// **This was found by running it, not by a test.** The first real end-to-end question was
/// answered correctly in two steps and then looped for 155 seconds: the model called `done`, the
/// tool host reported "no executor", the model saw a failure it could not interpret, and tried
/// again. The budget paused it — the backstop worked — but the loop should have ended at `done`.
/// Every unit test passed throughout, because each half was correct in isolation.
const CONTROL_TOOLS: [&str; 4] = ["done", "ask", "remember", "run"];

/// Turn one Ollama message into a [`ModelStep`].
///
/// **No taint is produced here and there is nowhere for it to go** — `ModelStep::ToolCall`
/// carries no provenance field (ADR-023). What the model says about where its arguments came
/// from is not evidence, and the harness computes taint from the context view instead.
pub fn parse_step(message: &serde_json::Value) -> ModelStep {
    if let Some(calls) = message.get("tool_calls").and_then(|c| c.as_array()) {
        if let Some(first) = calls.first() {
            let function = first.get("function");
            let name = function
                .and_then(|f| f.get("name"))
                .and_then(|n| n.as_str())
                .unwrap_or_default();
            if !name.is_empty() {
                let mut args = Args::new();
                if let Some(obj) = function.and_then(|f| f.get("arguments")).and_then(|a| a.as_object())
                {
                    for (k, v) in obj {
                        let value = match v {
                            serde_json::Value::String(s) => ArgValue::Text(s.clone()),
                            serde_json::Value::Number(n) if n.is_i64() => {
                                ArgValue::Integer(n.as_i64().unwrap_or(0))
                            }
                            serde_json::Value::Bool(b) => ArgValue::Boolean(*b),
                            other => ArgValue::Text(other.to_string()),
                        };
                        args = args.with(k.clone(), value);
                    }
                }
                if CONTROL_TOOLS.contains(&name) {
                    return control_step(name, &args, message);
                }
                return ModelStep::ToolCall { tool: ToolId::new(name), args };
            }
        }
    }
    ModelStep::Say(
        message.get("content").and_then(|c| c.as_str()).unwrap_or_default().to_string(),
    )
}

/// Map a control tool onto its `ModelStep`. §12: the adapter normalizes what the model speaks.
fn control_step(name: &str, args: &Args, message: &serde_json::Value) -> ModelStep {
    let text = |key: &str| args.get(key).and_then(ArgValue::as_text).map(str::to_string);
    // A model may name the field `result`, `answer`, `content` or nothing at all. Falling back to
    // the message's own prose is what stops a well-formed `done` with an unexpected field name
    // from becoming a contract violation the model then has to guess its way out of.
    let body = text("result")
        .or_else(|| text("answer"))
        .or_else(|| text("content"))
        .or_else(|| text("text"))
        .or_else(|| {
            message
                .get("content")
                .and_then(|c| c.as_str())
                .filter(|s| !s.trim().is_empty())
                .map(str::to_string)
        })
        .unwrap_or_default();

    match name {
        "done" => ModelStep::Done(CondensedResult::new().with("answer", body)),
        "ask" => ModelStep::Ask(text("question").unwrap_or(body)),
        "remember" => ModelStep::MemoryWrite(ClaimRequest {
            text: text("text").unwrap_or(body),
            payload_kind: text("payload_kind").unwrap_or_else(|| "fact".into()),
            derived_from: text("derived_from").into_iter().collect(),
        }),
        // `run` needs a full SpawnRequest and the model supplies only a task. Rather than
        // synthesise a capability profile and a budget the model never declared — which §5 says
        // must be declared at spawn, never inferred — this reports the gap as prose the model can
        // act on. Wiring `run` from a provider is M2 D work.
        _ => ModelStep::Say(format!(
            "[run is not yet reachable from a model call; the spawn contract must be declared              explicitly] {body}"
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_recorded_capability_describes_the_model_that_is_actually_default() {
        // A build that changed DEFAULT_MODEL and not `default_capability` would disclose one
        // model's measured rate under another model's name — a number quoted about the wrong
        // subject, which is the family this project has logged fourteen times.
        let c = default_capability();
        assert_eq!(c.model, DEFAULT_MODEL);
        assert!(c.fit_for_default(), "the pinned default must clear its own bar: {}", c.disclosure());
        assert!(c.disclosure().contains("12/12"), "{}", c.disclosure());
    }

    #[test]
    fn an_absent_endpoint_degrades_with_a_remedy_rather_than_crashing() {
        // Invariant 4, exercised against a port nothing listens on. The assertion is not that it
        // fails — it is that it fails into a DECLARED state carrying the command that fixes it.
        let endpoint = LocalEndpoint::new("127.0.0.1", 1).unwrap();
        let routing = Routing::uniform(DEFAULT_MODEL).unwrap();
        let a = Availability::probe(&endpoint, &routing);

        assert!(matches!(a, Availability::EndpointDown { .. }), "{a:?}");
        assert_eq!(a.degraded_path(), Some(DegradedPath::ModelUnavailable));
        assert!(a.remedy().contains("ollama serve"), "the remedy must be actionable: {}", a.remedy());
    }

    #[test]
    fn each_unavailability_names_a_different_remedy() {
        // Three distinguishable failures, because the fixes differ. Collapsing them into
        // "unavailable" would be a message the user cannot act on.
        let down = Availability::EndpointDown { endpoint: "http://127.0.0.1:11434".into() };
        let missing = Availability::ModelMissing {
            model: "qwen3.5:9b".into(),
            available: vec!["gemma3:12b".into()],
        };
        let wrong = Availability::NotOllama {
            endpoint: "http://127.0.0.1:11434".into(),
            detail: "HTTP 404".into(),
        };
        assert!(down.remedy().contains("ollama serve"));
        assert!(missing.remedy().contains("ollama pull qwen3.5:9b"));
        assert!(missing.remedy().contains("gemma3:12b"), "say what IS available");
        assert!(wrong.remedy().contains("not Ollama"));
        for a in [&down, &missing, &wrong] {
            assert_eq!(a.degraded_path(), Some(DegradedPath::ModelUnavailable));
        }
    }

    #[test]
    fn a_tool_call_parses_into_a_step_with_no_taint_field_to_fill() {
        let msg = serde_json::json!({
            "content": "",
            "tool_calls": [{
                "function": { "name": "read", "arguments": { "path": "src/main.rs" } }
            }]
        });
        match parse_step(&msg) {
            ModelStep::ToolCall { tool, args } => {
                assert_eq!(tool.as_str(), "read");
                assert_eq!(args.get("path"), Some(&ArgValue::Text("src/main.rs".into())));
            }
            other => panic!("expected a tool call, got {other:?}"),
        }
    }

    #[test]
    fn prose_parses_as_say() {
        let msg = serde_json::json!({ "content": "Marlowe here." });
        assert_eq!(parse_step(&msg), ModelStep::Say("Marlowe here.".into()));
    }

    #[test]
    fn the_four_control_tools_become_loop_steps_not_tool_calls() {
        // The defect the first real end-to-end run exposed. `done` routed to the tool host,
        // which has no executor for it, so the run never ended and burned its whole budget.
        let done = serde_json::json!({
            "content": "",
            "tool_calls": [{ "function": { "name": "done", "arguments": { "result": "42" } } }]
        });
        match parse_step(&done) {
            ModelStep::Done(r) => assert_eq!(r.get("answer"), Some("42")),
            other => panic!("`done` must end the run, got {other:?}"),
        }

        let ask = serde_json::json!({
            "content": "",
            "tool_calls": [{ "function": { "name": "ask", "arguments": { "question": "which?" } } }]
        });
        assert_eq!(parse_step(&ask), ModelStep::Ask("which?".into()));

        let remember = serde_json::json!({
            "content": "",
            "tool_calls": [{ "function": { "name": "remember", "arguments": { "text": "x" } } }]
        });
        assert!(matches!(parse_step(&remember), ModelStep::MemoryWrite(_)));

        // ...and a real tool still routes to the tool host.
        let read = serde_json::json!({
            "content": "",
            "tool_calls": [{ "function": { "name": "read", "arguments": { "path": "a" } } }]
        });
        assert!(matches!(parse_step(&read), ModelStep::ToolCall { .. }));
    }

    #[test]
    fn done_with_an_unexpected_field_name_still_ends_the_run() {
        // A model that says `content` instead of `result` has still finished. Turning that into
        // a contract violation would make it guess its way out, which is the loop this defect
        // produced in the first place.
        let done = serde_json::json!({
            "content": "the answer",
            "tool_calls": [{ "function": { "name": "done", "arguments": {} } }]
        });
        match parse_step(&done) {
            ModelStep::Done(r) => assert_eq!(r.get("answer"), Some("the answer")),
            other => panic!("expected Done, got {other:?}"),
        }
    }

    #[test]
    fn a_malformed_tool_call_falls_back_to_prose_rather_than_inventing_a_call() {
        // A model that emits `tool_calls: [{}]` has failed to call a tool. Synthesising a call
        // from the fragments would turn a model failure into a harness action.
        let msg = serde_json::json!({ "content": "hm", "tool_calls": [{ "function": {} }] });
        assert_eq!(parse_step(&msg), ModelStep::Say("hm".into()));
    }
}
