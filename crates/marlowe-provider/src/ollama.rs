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
    CallLimits, ContextView, DegradedPath, ModelCall, ModelDriver, ModelStep, ProviderError, Usage,
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

pub struct OllamaDriver {
    endpoint: LocalEndpoint,
    routing: Routing,
    registry: ToolRegistry,
    capability: ModelCapability,
    timeout: Duration,
}

impl OllamaDriver {
    pub fn new(endpoint: LocalEndpoint, routing: Routing, registry: ToolRegistry) -> Self {
        let capability = ModelCapability::unmeasured(routing.model_for(
            marlowe_loop::ModelRoute::Orchestrator,
        ));
        Self { endpoint, routing, registry, capability, timeout: DEFAULT_TIMEOUT }
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

impl ModelDriver for OllamaDriver {
    fn call(
        &mut self,
        view: &ContextView,
        tools: &ExposedSet,
        limits: CallLimits,
    ) -> Result<ModelCall, ProviderError> {
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

        let body = serde_json::json!({
            "model": model,
            "messages": messages,
            "tools": self.tool_schema(tools),
            "stream": false,
            "options": {
                // The budget's hard cap, handed to the provider. `budget` is explicit that this
                // is the mechanism and the top-of-loop check is only the backstop.
                "num_predict": limits.max_output_tokens.min(i32::MAX as u64) as i64,
            }
        });

        let response = http::post_json(&self.endpoint, "/api/chat", &body, self.timeout).map_err(
            |e| ProviderError {
                detail: format!("{e}"),
                // Unreachable is worth a failover attempt; a malformed body is not — it will be
                // malformed on the next provider too.
                retriable: matches!(e, HttpError::Unreachable { .. }),
            },
        )?;

        let usage = Usage {
            prompt_tokens: response.get("prompt_eval_count").and_then(|v| v.as_u64()).unwrap_or(0),
            completion_tokens: response.get("eval_count").and_then(|v| v.as_u64()).unwrap_or(0),
            // A local model costs no money. Recorded as zero rather than omitted, so the budget
            // dimension still exists and still fires when a hosted provider arrives.
            micros_usd: 0,
            wall_ms: response
                .get("total_duration")
                .and_then(|v| v.as_u64())
                .map(|ns| ns / 1_000_000)
                .unwrap_or(0),
        };

        let message = response.get("message").cloned().unwrap_or(serde_json::Value::Null);
        let step = parse_step(&message);
        Ok(ModelCall { usage, step })
    }
}

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
                return ModelStep::ToolCall { tool: ToolId::new(name), args };
            }
        }
    }
    ModelStep::Say(
        message.get("content").and_then(|c| c.as_str()).unwrap_or_default().to_string(),
    )
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
    fn a_malformed_tool_call_falls_back_to_prose_rather_than_inventing_a_call() {
        // A model that emits `tool_calls: [{}]` has failed to call a tool. Synthesising a call
        // from the fragments would turn a model failure into a harness action.
        let msg = serde_json::json!({ "content": "hm", "tool_calls": [{ "function": {} }] });
        assert_eq!(parse_step(&msg), ModelStep::Say("hm".into()));
    }
}
