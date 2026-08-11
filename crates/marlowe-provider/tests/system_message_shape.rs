//! **Exactly one `system` message, at position 0.** A chat-template constraint, found in the wild.
//!
//! Reported live against a **qwen3-next** architecture model: Ollama answered HTTP 400 with
//!
//! ```text
//! Unable to generate parser for this template. Automatic parser generation failed:
//! ... raise_exception('System message must be at the beginnin ...
//! Error: Jinja Exception: System message must be at the beginning
//! ```
//!
//! The driver emitted **one `system` message per stable block and per context block** — a dozen of
//! them — plus a further one *after the user's turn* for injected memory. `/api/chat` accepts that
//! shape and `qwen3.5:9b`'s template accepts it, which is exactly why it survived: the wire was
//! being validated against the one model anybody ran.
//!
//! **This is the measurement-transfer family in a new place.** "The request body is well-formed"
//! was a reading taken on one template and treated as a property of the endpoint. The template is
//! the model's, it varies per model, and a wire format that varies with it makes every model swap a
//! debugging session. So the driver builds to the strictest common shape and this test pins it.
//!
//! The guard is written against the **assembled view**, not against a hand-built message list: a
//! test that constructed its own messages would assert about a shape the driver never produces.

use marlowe_contract::TrustClass;
use marlowe_loop::{
    Assembler, Block, CallLimits, ContextView, GovernanceConstraint, SessionId, SessionState,
    SourceKind,
};
use marlowe_provider::{OllamaDriver, Routing};
use marlowe_tools::{builtin_registry, ExposedSet, ToolId};

fn driver() -> OllamaDriver {
    OllamaDriver::new(
        marlowe_provider::LocalEndpoint::default_ollama(),
        Routing::uniform(marlowe_provider::DEFAULT_MODEL).expect("a uniform route"),
        builtin_registry().expect("the builtins are compiled in"),
    )
}

/// A view shaped like a real mid-conversation turn: identity and governance in the stable tier,
/// a user turn, an assistant turn, **and an injected memory** — which is the block that used to
/// emit a `system` message after the conversation had started.
fn realistic_view() -> ContextView {
    let mut state = SessionState::new(SessionId::new(), "Marlowe.");
    state.assert_governance(GovernanceConstraint::asserted("the workspace is scoped"));
    state.assert_governance(GovernanceConstraint::asserted("finish by replying"));
    state.push(Block::new(
        SourceKind::History,
        "what did I say my favourite colour was?".to_string(),
        TrustClass::UserAsserted,
    ));
    state.push(Block::new(
        SourceKind::InjectedMemory,
        "the user's favourite colour is green".to_string(),
        TrustClass::AgentInferred,
    ));
    state.push(Block::new(
        SourceKind::History,
        "Green.".to_string(),
        TrustClass::AgentInferred,
    ));
    Assembler::new(8_192, 1_024).assemble(&state)
}

fn roles(body: &serde_json::Value) -> Vec<String> {
    body.get("messages")
        .and_then(|m| m.as_array())
        .expect("the request carries messages")
        .iter()
        .filter_map(|m| m.get("role").and_then(|r| r.as_str()))
        .map(str::to_string)
        .collect()
}

#[test]
fn there_is_exactly_one_system_message_and_it_is_first() {
    let tools = ExposedSet::new(vec![ToolId::new("read")]).expect("one tool fits");
    let body = driver().request_body(&realistic_view(), &tools, CallLimits { max_output_tokens: 512 });
    let roles = roles(&body);

    let system_count = roles.iter().filter(|r| *r == "system").count();
    assert_eq!(
        system_count, 1,
        "a template that accepts exactly one system message rejects the whole request otherwise. \
         Roles were: {roles:?}"
    );
    assert_eq!(
        roles.first().map(String::as_str),
        Some("system"),
        "`System message must be at the beginning` is a real Jinja exception from a real model. \
         Roles were: {roles:?}"
    );
}

/// The regression, stated as the thing that actually broke rather than as a count.
///
/// **This is the assertion with teeth**: the count test above would still pass if injected memory
/// were dropped entirely, and dropping it is a much worse bug than mis-roling it.
#[test]
fn an_injected_memory_reaches_the_model_without_starting_a_second_system_message() {
    let tools = ExposedSet::new(vec![ToolId::new("read")]).expect("one tool fits");
    let body = driver().request_body(&realistic_view(), &tools, CallLimits { max_output_tokens: 512 });

    let messages = body.get("messages").and_then(|m| m.as_array()).expect("messages");
    let carrying: Vec<&str> = messages
        .iter()
        .filter(|m| {
            m.get("content")
                .and_then(|c| c.as_str())
                .is_some_and(|c| c.contains("favourite colour is green"))
        })
        .filter_map(|m| m.get("role").and_then(|r| r.as_str()))
        .collect();

    assert_eq!(
        carrying,
        vec!["system"],
        "the memory must still reach the model, in the ONE system message. Dropping it would make \
         retrieval silently useless while every shape test stayed green"
    );

    // And it must not have been attributed to the person. §B1 keeps memory out of the interface,
    // which starts with not pretending it was spoken; a recalled fact arriving as a `user` turn is
    // indistinguishable from something they just said.
    let roles = roles(&body);
    assert_eq!(roles.iter().filter(|r| *r == "system").count(), 1, "{roles:?}");
}

/// The stable tier still leads, so the prefix stays cache-friendly and the persona still comes
/// first inside the one system message.
#[test]
fn the_identity_still_leads_the_system_message() {
    let tools = ExposedSet::new(vec![ToolId::new("read")]).expect("one tool fits");
    let body = driver().request_body(&realistic_view(), &tools, CallLimits { max_output_tokens: 512 });
    let messages = body.get("messages").and_then(|m| m.as_array()).expect("messages");
    let system = messages[0].get("content").and_then(|c| c.as_str()).expect("system content");

    assert!(
        system.starts_with("Marlowe."),
        "identity leads the stable tier and therefore the system message: {:?}",
        &system[..system.len().min(80)]
    );
    assert!(
        system.contains("the workspace is scoped"),
        "governance must survive the concatenation"
    );
}
