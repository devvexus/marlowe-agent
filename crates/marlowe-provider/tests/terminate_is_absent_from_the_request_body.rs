//! **M3-DESIGN §11's amended rows 1 and 2, over every profile and both local adapters.**
//!
//! # The row this replaces was RED on a correct build, and the cheap repair is the defect
//!
//! §11 used to ask for *"TERMINATE present in an agent's `request_body`: 0 occurrences."* The
//! string `terminate` ships to every model holding `run` from two production sources that have
//! nothing whatever to do with the escape hatch:
//!
//! ```text
//! crates/marlowe-tools/src/builtin.rs   the `run` tool's `orphan_policy` parameter description
//! crates/marlowe-loop/src/engine.rs     OrphanPolicy::Terminate => "terminate", in the receipt
//! ```
//!
//! **The repair that must not be made is narrowing the search until the zero comes back** —
//! matching case-sensitively, excluding the manifest, grepping a longer label. Each restores a
//! green cell over a property nobody checked, which is instance #15 committed against the
//! acceptance table.
//!
//! The row was measuring a **spelling**; §3.4 is about an **object**. `OrphanPolicy::Terminate` is
//! a declared, model-nameable, harmless lifecycle value and is *supposed* to be in the schema. So
//! this file asserts on [`marlowe_view::TERMINATE_CANARY`] — a token that exists in the view crate,
//! in the surface that draws the row, and **in no type any `ModelDriver` can reach** — and on
//! [`marlowe_view::TERMINATE_LABEL`], the wording a human reads.
//!
//! [`the_word_terminate_is_in_these_bodies_and_that_is_correct`] states the red cell out loud
//! rather than hiding it, so a future session reading a green run here cannot conclude the old row
//! was satisfied.
//!
//! # This file is NOT §11 row 2
//!
//! Every body here is built **inside the test process**. That is the `persona_emission.rs` failure
//! aimed at a security measurement: those assertions were green while the deployed daemon served a
//! binary from before the persona commit. This is a **breadth** check — six profiles by two
//! adapters — and the acceptance measurement is the `--dev` outbound dump of the running process,
//! which is recorded as not taken in this session's report.

use marlowe_contract::TrustClass;
use marlowe_loop::profile::AgentLevel;
use marlowe_loop::{
    Assembler, Block, CallLimits, CapabilityProfile, ContextView, InterruptPolicy, ModelRoute,
    SessionId, SessionState, SourceKind,
};
use marlowe_permission::EgressPolicy;
use marlowe_provider::llamacpp::{LlamaCppDriver, SamplingPlan, ScriptedTransport};
use marlowe_provider::{LocalEndpoint, OllamaDriver, Routing};
use marlowe_tools::{builtin_registry, ExposedSet, ToolId};
use marlowe_view::{TERMINATE_CANARY, TERMINATE_LABEL};

/// A phrase from `persona/v2.md`, the same marker `persona_emission.rs` uses. **The positive
/// control**: a body that failed to build, or that carried no messages, would report a clean zero
/// for the canary and prove nothing.
const PERSONA_MARKER: &str = "You are not impressed";

fn view() -> ContextView {
    let persona = include_str!("../../../persona/v2.md");
    let mut state = SessionState::new(SessionId::from_name("terminate"), persona);
    state.push(Block::new(
        SourceKind::History,
        // A spawn receipt, verbatim in shape: this is one of the two production sources of the
        // word `terminate`, and it is deliberately IN the view so the old row's redness is
        // reproduced rather than avoided.
        "[spawned child brave-storm] orphan_policy: terminate".to_string(),
        TrustClass::AgentObserved,
    ));
    Assembler::new(8_192, 1_024).assemble(&state)
}

fn profiles() -> Vec<(&'static str, CapabilityProfile)> {
    let leaf = |level: AgentLevel, tools: &[&str]| {
        CapabilityProfile::new(
            ExposedSet::new(tools.iter().map(|t| ToolId::new(*t)).collect()).expect("a small set"),
            EgressPolicy::DenyAll,
            InterruptPolicy::Unattended,
            ModelRoute::Worker,
            level,
            false,
            false,
        )
        .expect("a profile the constructor admits")
    };
    vec![
        ("secretary", CapabilityProfile::interactive()),
        ("top-agent-manages", leaf(AgentLevel::TopAgent { manages: true }, &["run", "ask"])),
        ("top-agent-works", leaf(AgentLevel::TopAgent { manages: false }, &["read", "bash"])),
        ("master", leaf(AgentLevel::Master, &["run", "ask"])),
        ("worker", leaf(AgentLevel::Worker, &["read", "edit"])),
        ("quarantined-reader", CapabilityProfile::quarantined_reader()),
    ]
}

fn bodies() -> Vec<(String, serde_json::Value)> {
    let mut out = Vec::new();
    for (name, p) in profiles() {
        let limits = CallLimits { max_output_tokens: 512, route: p.model_route() };
        let ollama = OllamaDriver::new(
            LocalEndpoint::default_ollama(),
            Routing::uniform(marlowe_provider::DEFAULT_MODEL).expect("a uniform route"),
            builtin_registry().expect("the builtins are compiled in"),
        )
        .request_body(&view(), p.exposed_tools(), limits);
        out.push((format!("ollama/{name}"), ollama));

        let llama = LlamaCppDriver::with_transport(
            Box::new(ScriptedTransport::new(Vec::new())),
            "qwen3.5:9b",
            builtin_registry().expect("the builtins are compiled in"),
            SamplingPlan::ServerDefaults,
        )
        .with_context_tokens(32_768)
        .request_body(&view(), p.exposed_tools(), limits);
        out.push((format!("llamacpp/{name}"), llama));
    }
    out
}

/// **Row 1 and row 2's breadth check.** The canary and the label reach no model, at any level, on
/// either local adapter.
///
/// *Mutation:* put `TERMINATE_CANARY` into any harness-authored prompt text → red on every row.
#[test]
fn the_escape_hatch_reaches_no_model() {
    let bodies = bodies();
    assert_eq!(bodies.len(), 12, "6 profiles x 2 adapters");

    for (name, body) in &bodies {
        let json = serde_json::to_string(body).expect("a body serialises");

        // **The positive control, first.** A body that failed to build carries no canary either,
        // and a zero read off an empty string is not evidence.
        let messages = body
            .get("messages")
            .and_then(|m| m.as_array())
            .unwrap_or_else(|| panic!("{name}: the body carries no messages array: {body}"));
        assert!(!messages.is_empty(), "{name}: the body carries no messages");
        assert!(
            json.contains(PERSONA_MARKER),
            "{name}: the persona is not in this body, so its silence about the canary is not \
             evidence about anything"
        );

        assert!(
            !json.contains(TERMINATE_CANARY),
            "{name}: the escape hatch's wire identity reached a model"
        );
        assert!(
            !json.to_lowercase().contains(&TERMINATE_LABEL.to_lowercase()),
            "{name}: the escape hatch's human-readable label reached a model"
        );
    }
}

/// **The leak control: the search itself is proven.**
///
/// Without this, a zero above could mean *"the substring scan is broken"* rather than *"the canary
/// is absent"*, and the two read identically. Here a body is built deliberately carrying the
/// canary, and the same scan is asserted to **find** it.
#[test]
fn the_scan_finds_the_canary_when_it_is_actually_there() {
    let mut state = SessionState::new(SessionId::from_name("leak"), "Marlowe.");
    state.push(Block::new(
        SourceKind::History,
        format!("a leaked overlay: {TERMINATE_CANARY} / {TERMINATE_LABEL}"),
        TrustClass::AgentObserved,
    ));
    let leaked = Assembler::new(8_192, 1_024).assemble(&state);
    let body = OllamaDriver::new(
        LocalEndpoint::default_ollama(),
        Routing::uniform(marlowe_provider::DEFAULT_MODEL).expect("a uniform route"),
        builtin_registry().expect("the builtins are compiled in"),
    )
    .request_body(&leaked, &ExposedSet::empty(), CallLimits {
        max_output_tokens: 256,
        route: ModelRoute::Worker,
    });
    let json = serde_json::to_string(&body).expect("a body serialises");
    assert!(json.contains(TERMINATE_CANARY), "the scan cannot see a canary that IS there: {json}");
    assert!(json.to_lowercase().contains(&TERMINATE_LABEL.to_lowercase()));
}

/// **Row 1, at the exposed set rather than at the bytes.** There is no escape-hatch tool, at any
/// level, and this design adds none.
///
/// **Green on an empty implementation and it always will be** — `builtin_registry()` has no such
/// entry and never had one. It is a regression guard, not evidence, and saying so is the point:
/// §11's amendment records that the first two of its three rows are satisfiable by a build that
/// draws nothing.
#[test]
fn no_profile_exposes_an_escape_hatch_tool() {
    for (name, p) in profiles() {
        for t in p.exposed_tools().iter() {
            assert!(
                !t.as_str().contains("terminat") && t.as_str() != "escape",
                "{name} exposes {t:?}, which reads like the escape hatch as a tool"
            );
        }
    }
    let registry = builtin_registry().expect("the builtins are compiled in");
    assert!(
        !format!("{registry:?}").contains(TERMINATE_CANARY),
        "the canary is in the tool registry, which is the one thing that ships to every model"
    );
}

/// **The red cell, stated out loud so nobody restores it.**
///
/// `terminate` IS in these bodies, from `orphan_policy`'s description and from the spawn receipt.
/// This test asserts that it is — so a session that "fixed" the old row by making this word absent
/// would break the `run` tool's documentation and find out here, and a session reading a green run
/// of this file cannot conclude the old zero was earned.
#[test]
fn the_word_terminate_is_in_these_bodies_and_that_is_correct() {
    let mut found_in_schema = 0;
    let mut found_in_history = 0;
    for (name, body) in bodies() {
        let json = serde_json::to_string(&body).expect("a body serialises");
        if json.to_lowercase().contains("terminate") {
            if name.contains("secretary") || name.contains("manages") || name.contains("master") {
                found_in_schema += 1;
            }
            found_in_history += 1;
        }
    }
    assert!(
        found_in_schema > 0,
        "no body carried the word `terminate` at all. Either `orphan_policy`'s description was \
         renamed to protect a test -- the scoreboard reshaping the product -- or the receipt \
         changed. Neither is a reason to relax the canary assertions in this file"
    );
    assert!(found_in_history > 0);
    println!(
        "bodies carrying the word `terminate`: {found_in_history} of 12 -- RED under §11's \
         original row, correct under the amendment"
    );
}
