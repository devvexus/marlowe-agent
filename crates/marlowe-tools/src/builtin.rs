//! ADR-006 — the eleven model-visible tools, with their manifests.
//!
//! `bash · read · edit · find · web · recall · remember · use · run · ask · done`
//!
//! Eleven against a budget of twelve. **The spare slot is for a situational tool a profile
//! adds, not for a twelfth permanent one.**
//!
//! # The consequence column, and why each is what it is
//!
//! | Tool | Consequence | Reason |
//! |---|---|---|
//! | `read` `find` `recall` `ask` `done` | `Inert` | Pure reads and escalations. §9 exempts `Inert` from *target-provenance* checking on the stated grounds that following a link found on a page is how research works. **Path scoping still applies** — that is a different check, and it applies at every level. |
//! | `web` | `Inert` | Deliberate, and it is §9's own example. Containment is three non-kernel mechanisms: the result returns `UntrustedContent`, it returns by reference, and egress allowlisting closes the exfiltration leg. ADR-002 records that if any one weakens, this exemption is revisited rather than inherited. |
//! | `edit` `use` | `Reversible` | §9 checks `Reversible` targets, and both are here for that reason. A workspace write is a durable channel into a later run's context (§8.3's sandbox-boundary-redefinition class); a skill load chosen by untrusted content is supply-chain steering. |
//! | `remember` `run` | `Consequential` | A memory write is the highest-privilege operation in the system (§8.2). A spawn commits budget and acts through a child. |
//! | `bash` | `Irreversible` | The declared level is the **ceiling a tool can reach**, and an arbitrary shell command can reach anything. Refining it per-command means parsing the command to decide whether it is safe, which is the Cursor CVE exactly — an allowlist that auto-approved the commands the attacker needed. Any such refinement is a separate argued change with its own ADR, never a convenience. |
//!
//! # `hosts` in a manifest is a declared maximum, not a grant
//!
//! The manifest says what a tool may *ever* reach; `EgressPolicy` on the run's
//! `CapabilityProfile` says what this run *does* grant, deny-by-default. The effective set is
//! the intersection. `web` therefore declares `*` — it is the general-purpose fetch tool and
//! its audit surface is honestly "anywhere" — and the run's policy is where the real
//! allowlist lives. A connector declares its provider's hosts and nothing else.

use crate::manifest::{
    load, CapabilityManifest, ConsequenceLevel, LoadError, ManifestProvenance, ParamType,
    RawManifest, RawParamSpec, ToolId,
};
use crate::registry::{Description, ToolRegistration, ToolRegistry, Transport};
use crate::summary::SummarySpec;
use crate::ArgumentRole;

/// The eleven ids, in ADR-006's order. Used by the HP10 budget test and by profile
/// construction, so the list exists once.
pub const BUILTIN_TOOLS: [&str; 10] = [
    "bash", "read", "edit", "find", "web", "recall", "remember", "use", "run", "ask",
];

/// The workspace-relative glob every filesystem tool declares.
///
/// `.` is resolved against the run's workspace root by path scoping, which is the only
/// component that may turn a declaration into a decision. A manifest holding an absolute path
/// would be a manifest that means something different on another machine.
const WORKSPACE: &str = "./**";

fn param(name: &str, role: ArgumentRole, ty: ParamType, required: bool) -> RawParamSpec {
    RawParamSpec { name: name.to_string(), role: Some(role), ty, required }
}

/// **Four constructors, because there are two independent questions.**
///
/// `target`/`payload` answers *may untrusted content shape this* (§9). `req`/`opt` answers *does
/// the executor need it*. They were the same switch until this session, and the eleven mismatches
/// that produced are in [`marlowe_tools::ParamSpec::required`].
fn target_req(name: &str, ty: ParamType) -> RawParamSpec {
    param(name, ArgumentRole::Target, ty, true)
}

fn target_opt(name: &str, ty: ParamType) -> RawParamSpec {
    param(name, ArgumentRole::Target, ty, false)
}

fn payload_req(name: &str, ty: ParamType) -> RawParamSpec {
    param(name, ArgumentRole::Payload, ty, true)
}

fn payload_opt(name: &str, ty: ParamType) -> RawParamSpec {
    param(name, ArgumentRole::Payload, ty, false)
}

fn manifest(
    tool: &str,
    consequence: ConsequenceLevel,
    paths: &[&str],
    hosts: &[&str],
    params: Vec<RawParamSpec>,
) -> Result<CapabilityManifest, LoadError> {
    load(
        RawManifest {
            tool: ToolId::new(tool),
            paths: paths.iter().map(|s| (*s).to_string()).collect(),
            hosts: hosts.iter().map(|s| (*s).to_string()).collect(),
            creds: vec![],
            consequence: Some(consequence),
            params,
        },
        // First-party, because these are built here in code. Everything arriving as bytes
        // loads as `ThirdParty` — see `manifest`'s header.
        ManifestProvenance::FirstParty,
    )
}

/// One builtin's registration: manifest, description, and its §8 one-line summary spec.
fn registration(
    tool: &'static str,
    description: &'static str,
    verb: &'static str,
    inline_threshold_bytes: u64,
    consequence: ConsequenceLevel,
    paths: &[&str],
    hosts: &[&str],
    params: Vec<RawParamSpec>,
) -> Result<ToolRegistration, LoadError> {
    let transport = Transport::Builtin;
    Ok(ToolRegistration {
        id: ToolId::new(tool),
        manifest: manifest(tool, consequence, paths, hosts, params)?,
        description: Description::new(description, &transport),
        summary: SummarySpec::new(verb, inline_threshold_bytes),
        transport,
    })
}

/// Every builtin, registered. **Registration, not exposure** — a profile still selects ≤12.
pub fn builtin_registry() -> Result<ToolRegistry, LoadError> {
    use ConsequenceLevel::*;
    use ParamType::*;

    let mut r = ToolRegistry::new();
    let regs = [
        registration(
            "bash",
            "Run a shell command in the workspace. Each call is a fresh shell: nothing persists between calls.",
            "bash",
            2_048,
            Irreversible,
            &[WORKSPACE],
            &[],
            // `command` is a Target and not a Payload. It is not body content that a tool
            // happens to carry — it *is* the action, and untrusted content choosing it is the
            // whole attack.
            vec![target_req("command", Text), target_opt("cwd", ParamType::Path)],
        ),
        registration(
            "read",
            "Read a file in the workspace, by workspace-relative path.",
            "read",
            8_192,
            Inert,
            &[WORKSPACE],
            &[],
            vec![target_req("path", ParamType::Path), payload_opt("range", Text)],
        ),
        registration(
            "edit",
            "Replace a file's contents, or write a new file.",
            "edit",
            2_048,
            Reversible,
            &[WORKSPACE],
            &[],
            vec![
                // WritePath, not Path: `edit` is the one builtin that may create its target.
                target_req("path", ParamType::WritePath),
                // Content is Payload by design: §9 is explicit that untrusted prose may fill
                // an inert body freely. The danger is the pair, not the text.
                payload_req("content", Text),
                payload_opt("replacing", Text),
            ],
        ),
        registration(
            "find",
            "Search the workspace for a literal substring, line by line.",
            "find",
            8_192,
            Inert,
            &[WORKSPACE],
            &[],
            vec![payload_req("pattern", Text), target_opt("path", ParamType::Path)],
        ),
        registration(
            "web",
            "Search and fetch. Always returns a reference, always untrusted content.",
            "web",
            0, // Never inlined. §8.2: raw untrusted bytes do not reach attention.
            Inert,
            &[],
            &["*"],
            vec![target_opt("url", Url), payload_opt("query", Text)],
        ),
        registration(
            "recall",
            "Search memory explicitly, including things that were forgotten.",
            "recall",
            8_192,
            Inert,
            &[],
            &[],
            vec![payload_req("query", Text), target_opt("payload_kind", Text)],
        ),
        registration(
            "remember",
            "Ask the harness to record a claim. The harness adjudicates, stamps and signs it.",
            "remember",
            1_024,
            Consequential,
            &[],
            &[],
            vec![
                payload_req("text", Text),
                // Which memories a claim derives from is a Target: choosing the lineage is how
                // laundering would launder (§14.6, HP6).
                target_opt("derived_from", Identifier),
                target_opt("payload_kind", Text),
            ],
        ),
        registration(
            "use",
            "Find and load a skill or tool.",
            "use",
            4_096,
            // Reversible rather than Inert *so that the target check fires*. Loading a skill
            // chosen by untrusted content is supply-chain steering, and §9 checks Reversible.
            Reversible,
            &[],
            &[],
            vec![target_opt("name", Text), payload_opt("query", Text)],
        ),
        registration(
            "run",
            "Spawn, steer or await a child run.",
            "run",
            1_024,
            Consequential,
            &[],
            &[],
            vec![
                payload_req("task", Text),
                payload_opt("output_contract", Text),
                // The child's capability profile and budget are Targets. Untrusted content
                // choosing a child's tool set is the trifecta reassembling itself one level
                // down.
                target_opt("exposed_tools", Text),
                target_opt("budget_micros_usd", Amount),
                target_opt("orphan_policy", Text),
            ],
        ),
        registration(
            "ask",
            "Escalate to the user with a decision package.",
            "ask",
            2_048,
            Inert,
            &[],
            &[],
            vec![payload_req("question", Text), payload_opt("options", Text)],
        ),
    ];

    for reg in regs {
        let reg = reg?;
        r.register(reg).expect("builtin ids are distinct and each manifest names its own tool");
    }
    Ok(r)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::exposure::MAX_EXPOSED_TOOLS;

    #[test]
    fn ten_tools_against_a_budget_of_twelve() {
        let r = builtin_registry().expect("the builtin manifests load");
        assert_eq!(r.len(), BUILTIN_TOOLS.len());
        // **Ten since M2 C2e removed `done`.** ADR-006 named eleven; the eleventh was a tool
        // whose only job was ending a run, and a run now ends when the model replies without
        // calling a tool. Two spare slots rather than one — spending either still needs an ADR.
        assert_eq!(BUILTIN_TOOLS.len(), 10, "ADR-006's eleven, less `done` (M2 C2e)");
        assert!(
            BUILTIN_TOOLS.len() < MAX_EXPOSED_TOOLS,
            "the spare slot is the design; spending it here needs an ADR"
        );

        let ids: Vec<ToolId> = BUILTIN_TOOLS.iter().map(|t| ToolId::new(*t)).collect();
        assert!(r.expose(&ids).is_ok(), "all ten fit in one exposed set");
    }

    #[test]
    fn every_builtin_parameter_has_a_role() {
        // Not a restatement of the load-time check: this asserts that the eleven shipped
        // manifests actually pass it, which is what "startup fails on an unannotated
        // manifest" means for the tools that are always present.
        let r = builtin_registry().unwrap();
        for reg in r.iter() {
            for p in reg.manifest.params() {
                assert!(
                    matches!(p.role, ArgumentRole::Target | ArgumentRole::Payload),
                    "{}::{} has no role",
                    reg.id,
                    p.name
                );
            }
        }
    }

    #[test]
    fn the_shell_command_is_a_target() {
        // The single most consequential role assignment in the file. If `command` were a
        // Payload, untrusted content could compose a shell line and the provenance check
        // would pass it, because Payload fields are unchecked by design.
        let r = builtin_registry().unwrap();
        let bash = r.manifest(&ToolId::new("bash")).unwrap();
        assert_eq!(bash.role_of("command"), Some(ArgumentRole::Target));
        assert_eq!(bash.consequence(), ConsequenceLevel::Irreversible);
    }

    #[test]
    fn web_is_inert_and_never_inlines() {
        let r = builtin_registry().unwrap();
        let web = r.get(&ToolId::new("web")).unwrap();
        assert_eq!(web.manifest.consequence(), ConsequenceLevel::Inert);
        assert_eq!(
            web.summary.inline_threshold_bytes, 0,
            "fetched bytes never reach attention; the loop gets a reference"
        );
    }

    #[test]
    fn the_child_capability_arguments_are_targets() {
        let r = builtin_registry().unwrap();
        let run = r.manifest(&ToolId::new("run")).unwrap();
        assert_eq!(run.role_of("exposed_tools"), Some(ArgumentRole::Target));
        assert_eq!(run.role_of("budget_micros_usd"), Some(ArgumentRole::Target));
        assert_eq!(run.role_of("task"), Some(ArgumentRole::Payload));
    }
}
