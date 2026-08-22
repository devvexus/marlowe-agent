//! **The two shapes an OpenAI-dialect endpoint refuses, in one place because two adapters build
//! the same request.**
//!
//! Neither of these is a style preference. Each is a hard `400` from a strict endpoint, and each
//! was produced by code that is *correct everywhere else in the system* — which is why they were
//! invisible until a hosted provider was pointed at the quarantined reader.
//!
//! # 1. `tools: []`
//!
//! The dialect says `tools` may be absent, or an array with **at least one** element. An empty
//! array is a schema violation, not "no tools".
//!
//! Two live producers, and neither looks like a bug at its own site:
//!
//! * `CapabilityProfile::quarantined_reader` is `ExposedSet::empty()`. That is **layer 1** — the
//!   load-time invariant that a component which reads untrusted content cannot hold a tool. The
//!   security property is exactly right, and rendering it onto the wire ended every quarantined
//!   read on the hosted path.
//! * `FARMING_HARD_STOP` withholds tools for one call, on purpose, from the **parent**: *"a nudge
//!   asks; an empty tool set removes the option."* Same wire shape, no quarantine involved.
//!
//! Omitting the field removes the option just as an empty array was meant to, and is what the
//! dialect actually defines.
//!
//! # 2. A `tool` message that answers no call
//!
//! `role: "tool"` is a **reply**. The dialect pairs it to an assistant `tool_calls` entry by id,
//! and a `tool` message whose `tool_call_id` is missing — or names a call that is not in the
//! request — is refused.
//!
//! The producer here is `Engine::condense_batch`, which pushes each fetched page into the child's
//! window as `SourceKind::ToolResults`. In the *parent's* conversation those blocks are genuine
//! replies to genuine calls. In the **child's** they are not: the child never called anything and
//! structurally never can, so the block carries no `wire` metadata and there is no assistant turn
//! in front of it. The child's whole request was `system, assistant, tool` — a reply to a call
//! that does not exist, and no user message at all.
//!
//! A block that is a tool result *somewhere* is therefore not automatically a `tool` message
//! *here*, and the same orphaning is reachable any time trimming drops an assistant turn while
//! keeping its results. [`unorphan_tool_messages`] decides it from the request being built rather
//! than from the block's provenance, so it holds for a producer nobody has written yet.

use serde_json::Value;
use std::collections::BTreeSet;

/// The role an unlinkable tool result is demoted to.
///
/// `user` because it is the only role in the dialect that carries content and is not a claim
/// about who acted. **The content is not rewritten** — no prefix, no wrapper, no interpolation:
/// the harness already writes the label immediately before the bytes it names, and adding a
/// second frame here would be a second place for that framing to drift.
const DEMOTED_ROLE: &str = "user";

/// `tools`, or nothing at all.
///
/// Returns `None` for an empty tool set, so the caller omits the key rather than sending `[]`.
/// Takes the built array so there is one definition of "empty" and it is the one the wire sees —
/// asking the `ExposedSet` instead would be a different question, and the two can disagree: a
/// tool that is exposed but absent from the registry is filtered out while building the array,
/// leaving a non-empty set and an empty array.
pub fn tools_field(schema: Value) -> Option<Value> {
    match schema.as_array() {
        Some(a) if a.is_empty() => None,
        _ => Some(schema),
    }
}

/// Rewrite any `tool` message that answers no call in this request into a plain user message.
///
/// A `tool` message keeps its role only when it carries a `tool_call_id` that some **earlier**
/// assistant message in this same list announced. Order matters: a reply cannot precede its call.
/// Everything else is demoted to [`DEMOTED_ROLE`] with the pairing fields removed, because a
/// `tool_call_id` on a non-`tool` message is itself malformed.
pub fn unorphan_tool_messages(messages: &mut [Value]) {
    let mut announced: BTreeSet<String> = BTreeSet::new();
    for msg in messages.iter_mut() {
        let role = msg.get("role").and_then(Value::as_str).unwrap_or("").to_string();

        if role == "tool" {
            let linked = msg
                .get("tool_call_id")
                .and_then(Value::as_str)
                .is_some_and(|id| announced.contains(id));
            if !linked {
                if let Some(obj) = msg.as_object_mut() {
                    obj.insert("role".into(), Value::String(DEMOTED_ROLE.into()));
                    obj.remove("tool_call_id");
                    obj.remove("tool_name");
                }
            }
            continue;
        }

        // Collected AFTER the `tool` branch and only from assistant turns, so a demoted message
        // cannot announce anything and a result can never license itself.
        if role == "assistant" {
            if let Some(calls) = msg.get("tool_calls").and_then(Value::as_array) {
                for c in calls {
                    if let Some(id) = c.get("id").and_then(Value::as_str) {
                        announced.insert(id.to_string());
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn roles(m: &[Value]) -> Vec<String> {
        m.iter().map(|x| x["role"].as_str().unwrap_or("?").to_string()).collect()
    }

    #[test]
    fn an_empty_tool_array_is_omitted_and_a_populated_one_is_kept() {
        assert!(tools_field(json!([])).is_none());
        assert!(tools_field(json!([{ "type": "function" }])).is_some());
    }

    #[test]
    fn a_tool_message_with_no_preceding_call_becomes_a_user_message() {
        // The quarantined reader's request, exactly: a brief and a page, no call anywhere.
        let mut m = vec![
            json!({ "role": "system", "content": "Marlowe." }),
            json!({ "role": "assistant", "content": "Below are 1 fetched sources." }),
            json!({ "role": "tool", "content": "=== source_1 (web) ===\nbytes" }),
        ];
        unorphan_tool_messages(&mut m);
        assert_eq!(roles(&m), vec!["system", "assistant", "user"]);
        assert_eq!(m[2]["content"], "=== source_1 (web) ===\nbytes", "content is not rewritten");
    }

    #[test]
    fn a_tool_message_that_answers_a_real_call_keeps_its_role() {
        // The control. Without it the function above could return "demote everything" and pass.
        let mut m = vec![
            json!({ "role": "assistant", "tool_calls": [{ "id": "call_1" }] }),
            json!({ "role": "tool", "tool_call_id": "call_1", "content": "ok" }),
        ];
        unorphan_tool_messages(&mut m);
        assert_eq!(roles(&m), vec!["assistant", "tool"]);
        assert_eq!(m[1]["tool_call_id"], "call_1");
    }

    #[test]
    fn a_result_whose_call_was_trimmed_away_is_demoted_and_loses_its_pairing() {
        // Compaction dropping an assistant turn while keeping its results reaches the same shape
        // the child does, by a route that has nothing to do with the quarantine.
        let mut m = vec![json!({
            "role": "tool", "tool_call_id": "call_9", "tool_name": "read", "content": "ok"
        })];
        unorphan_tool_messages(&mut m);
        assert_eq!(roles(&m), vec!["user"]);
        assert!(m[0].get("tool_call_id").is_none(), "a stale pairing is malformed on a user turn");
        assert!(m[0].get("tool_name").is_none());
    }

    #[test]
    fn a_reply_that_precedes_its_call_is_not_linked() {
        let mut m = vec![
            json!({ "role": "tool", "tool_call_id": "call_1", "content": "ok" }),
            json!({ "role": "assistant", "tool_calls": [{ "id": "call_1" }] }),
        ];
        unorphan_tool_messages(&mut m);
        assert_eq!(roles(&m), vec!["user", "assistant"]);
    }
}
