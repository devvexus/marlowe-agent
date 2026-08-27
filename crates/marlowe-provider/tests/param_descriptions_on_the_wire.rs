//! **What the model is actually told about each parameter, read off the outbound body.**
//!
//! `builtin.rs`'s own guard asserts that every parameter carries a `description`. That is a check
//! on the DECLARATION, and this project has a standing count of properties asserted where they are
//! declared rather than where they are enforced — `web`'s `inline_threshold_bytes: 0` with no
//! reader, `persona/v1.md` loaded but never in a request body. A description that is stored and
//! never serialised would satisfy the declaration guard exactly.
//!
//! So this reads `request_body`'s `tools` array: the bytes `/api/chat` receives.
//!
//! The failure it exists for was live. Journal seq 4677–4679, 2026-08-26: the model called `read`
//! with neither `path` nor `ref`. Both are optional, and `param_description` generated the same
//! sentence for both — **"Optional. text."** — which reads as documentation and carries none.

use marlowe_loop::{Assembler, Block, CallLimits, SessionId, SessionState, SourceKind};
use marlowe_provider::{OllamaDriver, Routing};
use marlowe_tools::{builtin_registry, ExposedSet, ToolId, BUILTIN_TOOLS};

/// The generated fallback, verbatim from `param_description`. If this string is what a parameter
/// gets, nothing was written for it.
const GENERATED: [&str; 2] = ["REQUIRED. text.", "Optional. text."];

fn body() -> serde_json::Value {
    let driver = OllamaDriver::new(
        marlowe_provider::LocalEndpoint::default_ollama(),
        Routing::uniform(marlowe_provider::DEFAULT_MODEL).expect("a uniform route"),
        builtin_registry().expect("the builtin manifests load"),
    );
    // Every builtin at once, so no tool can be missed by an exposure this test chose.
    let tools = ExposedSet::new(BUILTIN_TOOLS.iter().map(|t| ToolId::new(*t)).collect())
        .expect("the builtins fit one exposed set");
    let mut state = SessionState::new(SessionId::new(), "Marlowe.");
    state.push(Block::new(
        SourceKind::History,
        "do something".to_string(),
        marlowe_contract::TrustClass::UserAsserted,
    ));
    let view = Assembler::new(100_000, 10_000).assemble(&state);
    driver.request_body(&view, &tools, CallLimits { max_output_tokens: 512 })
}

#[test]
fn every_parameter_the_model_is_offered_carries_a_written_description() {
    let body = body();
    let tools = body["tools"].as_array().expect("the request offers tools");
    assert_eq!(
        tools.len(),
        BUILTIN_TOOLS.len(),
        "not every builtin reached the wire, so this test cannot have checked them all"
    );

    let mut bare = Vec::new();
    let mut checked = 0usize;
    for t in tools {
        let name = t["function"]["name"].as_str().unwrap_or("?");
        let props = t["function"]["parameters"]["properties"]
            .as_object()
            .unwrap_or_else(|| panic!("`{name}` has no properties object on the wire"));
        for (param, spec) in props {
            checked += 1;
            let d = spec["description"].as_str().unwrap_or("");
            if d.trim().is_empty() || GENERATED.contains(&d.trim()) {
                bare.push(format!("{name}::{param} = {d:?}"));
            }
        }
    }

    // **The control on the loop itself.** Zero parameters checked would satisfy the assertion
    // below, and a `properties` shape that stopped serialising would produce exactly that.
    assert!(
        checked >= 15,
        "only {checked} parameters were found on the wire, so the check below is nearly vacuous"
    );
    assert!(
        bare.is_empty(),
        "these reach the model as a sentence generated from type and arity, which reads as \
         documentation and is not. Live, that is why `read` was called with no subject at all: \
         {bare:?}"
    );
}

/// The three facts a model most needs and could not previously have known, asserted individually
/// so a rewrite that keeps the descriptions non-empty but drops their content still fails.
///
/// Each is read off an executor: `edit` truncates when `replacing` is absent (`executors.rs`),
/// `slice_lines` is 1-based inclusive, and `find` matches with `line.contains` — no regex.
#[test]
fn the_three_facts_that_cost_a_call_are_the_ones_actually_stated() {
    let body = body();
    let tools = body["tools"].as_array().expect("tools");
    let find_desc = |tool: &str, param: &str| -> String {
        tools
            .iter()
            .find(|t| t["function"]["name"].as_str() == Some(tool))
            .and_then(|t| t["function"]["parameters"]["properties"][param]["description"].as_str())
            .unwrap_or_else(|| panic!("`{tool}::{param}` is not on the wire"))
            .to_string()
    };

    let replacing = find_desc("edit", "replacing");
    assert!(
        replacing.to_lowercase().contains("whole file"),
        "`edit::replacing` does not warn that omitting it overwrites everything, which is the \
         most destructive default in the builtins: {replacing:?}"
    );
    let range = find_desc("read", "range");
    assert!(
        range.contains("1-based") && range.to_lowercase().contains("inclusive"),
        "`read::range`'s format is unstated, so the model has to guess whether it is 0- or \
         1-based and whether the end is included: {range:?}"
    );
    let pattern = find_desc("find", "pattern");
    assert!(
        pattern.to_lowercase().contains("not a regular expression"),
        "`find::pattern` does not say it is a literal substring, so a model that writes a regex \
         gets silence rather than an error: {pattern:?}"
    );
}
