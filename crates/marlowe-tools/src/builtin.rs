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

/// What `bash` actually is, per platform, in the words the model reads.
///
/// Split by `cfg` on the same condition `marlowe_exec::spawn_shell` splits on, so the two cannot
/// disagree about which interpreter runs. **Naming the network is deliberate**: the absence of any
/// statement was read by a live session as evidence that there was none, and it reported a
/// non-existent egress boundary rather than a quoting problem.
#[cfg(windows)]
const SHELL_DESCRIPTION: &str = "Run a command through the Windows shell, `cmd /C` — NOT bash, despite the name. Quote with double quotes, not single. No `grep`/`sed`/`awk`, no `&&`, no `2>/dev/null`. It reaches the network normally. Each call is a fresh shell and asks the user to approve it first. For something the user already told Marlowe, try `recall` first.";

#[cfg(not(windows))]
const SHELL_DESCRIPTION: &str = "Run a command through `sh -c`. It reaches the network normally. Each call is a fresh shell: nothing persists between calls, and every call asks the user to approve it first. For something the user already told Marlowe, try `recall` before the filesystem.";

/// Every builtin, registered. **Registration, not exposure** — a profile still selects ≤12.
pub fn builtin_registry() -> Result<ToolRegistry, LoadError> {
    use ConsequenceLevel::*;
    use ParamType::*;

    let mut r = ToolRegistry::new();
    let regs = [
        registration(
            "bash",
            // Every clause is checkable: `spawn_shell` runs one `cmd /C` (or `sh -c`) per call, so
            // nothing carries over; `adjudicate` returns `NeedsApproval` for `Irreversible`
            // unconditionally, before any tier comparison, so the approval is not tier-dependent.
            // The last sentence is routing advice, not a capability claim — a shell CAN read files,
            // which is exactly why a model reaches for it when the answer is in memory instead.
            //
            // **THE TOOL IS CALLED `bash` AND ON WINDOWS IT IS NOT BASH.** `spawn_shell` is
            // `cfg`-split: `cmd /C` on Windows, `sh -c` elsewhere. The name was the whole of what
            // the model had to go on, and the name is wrong on this platform — so a model writes
            // `'single quotes'`, `grep`, `&&`, `2>/dev/null`, and gets failures that look like
            // anything but a different interpreter. A real session read a string of them as *"the
            // harness has no network egress"* and reported a security boundary that does not
            // exist: `bash` reaches the network exactly as any other process on this machine does
            // — measured, `curl` to arxiv.org returns 200 — and no `EgressPolicy` is consulted on
            // this path at all. ADR-049 §4.
            //
            // The interpreter is therefore **named**, per platform, in the text the model reads.
            // [`SHELL_DESCRIPTION`] is `cfg`-selected rather than one string mentioning both,
            // because a description listing two shells makes the model guess which one it has.
            SHELL_DESCRIPTION,
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
            // `range`'s format was undocumented anywhere the model could see it: the generated
            // parameter description for a `Text` payload is "Optional. text." `slice_lines` splits
            // on `-`, parses both sides, and takes `skip(a-1).take(b-a+1)` — 1-based and inclusive.
            "Read a file in the workspace by workspace-relative `path`, OR a fetched document by `ref` (the id `web` returns). `range` selects lines by 1-based inclusive number, e.g. \"20-60\".",
            "read",
            8_192,
            Inert,
            &[WORKSPACE],
            &[],
            // **`path` became optional when `ref` arrived, and ADR-034's rule is preserved rather
            // than broken.** That rule is *a parameter the executor cannot run without is
            // required*; `read` now has two ways to name its subject, so neither one alone is
            // structurally mandatory. A call supplying neither is refused by the executor with a
            // message naming both — the one case ADR-034 exists to prevent is a call that is
            // schema-valid and can NEVER succeed, and that is not this.
            //
            // `ref` is a **Target**, not a payload: it selects which document is read, and §9's
            // whole point is that untrusted content may not choose a target.
            //
            // **AND THE CHECK DOES NOT FIRE ON IT. Audit finding A6.** An earlier version of this
            // comment ended *"a ref composed out of a fetched page's own text would carry that
            // page's class and be blocked by the same check as any other target"*. That is false in
            // this build. The target-provenance loop in `adjudicate` is guarded by
            // `if manifest.consequence() > ConsequenceLevel::Inert`, and `read` is `Inert` — the
            // loop never runs, so `role_of("ref")` has no reader on any enforcing path. A test
            // asserting the role would be green on a build where the check cannot execute, which is
            // the sixteenth-instance family exactly.
            //
            // What actually holds today: `read_ref` returns `UntrustedContent`, so layer 1 fires on
            // the content, and the store's ids are BLAKE3 and unguessable. What is NOT covered is
            // **steering** — text surviving into a condensed summary can name which of N refs the
            // parent dereferences next, and no provenance check sees that choice. The `Inert`
            // branch names its own revisit condition ("egress allowlisting closes the exfiltration
            // leg"), and layer 4 is approved-but-not-shipped, so that condition is already unmet.
            //
            // Left as a documented gap rather than silently widened: changing it is a §13 boundary
            // change and needs a `DECISIONS.md` entry.
            vec![
                target_opt("path", ParamType::Path),
                target_opt("ref", Text),
                payload_opt("range", Text),
            ],
        ),
        registration(
            "edit",
            // Three claims, each from the executor: `existing.find(replacing)` takes the FIRST
            // occurrence; a miss returns `failed("edit", "`replacing` was not found in the file")`;
            // with no `replacing` the handle is truncated and rewritten with `content`. The parent
            // directory is the walk's rule, not this tool's — only the LAST component is opened
            // `CreateOrOpen`, so a missing parent is `Unopenable`, which
            // `executors.rs::edit_writes_through_the_handle_and_can_create` shows happening.
            "Replace a file's contents, or write a new file. With `replacing`, the first exact occurrence of that text is replaced, and the call fails if it is not found; without it the whole file is overwritten. The parent directory must already exist.",
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
            // `line.contains(pattern)` — a literal substring, and the result line is built as
            // `{relative}:{n+1}: {line}`. `collect` enumerates with `read_dir`, so `path` names a
            // directory, and it stops at `FIND_FILE_CAP` (2000). `.` is the spelling the scope
            // accepts for the workspace root — `request::validate` drops `.` components, and
            // `executors.rs::find_reports_matches_and_how_many_files_it_actually_read` passes it.
            "Search files under a directory for a literal substring, line by line. Not a regex and not a symbol index. `path` is the directory to search: pass \".\" for the whole workspace. Matches come back as `path:line: text`, over at most 2000 files.",
            "find",
            8_192,
            Inert,
            &[WORKSPACE],
            &[],
            // **`path` is REQUIRED, and that is the executor's demand rather than the role's.**
            // `find` opens `handle_for(a, "path")` and returns "no adjudicated handle for `path`"
            // when it is absent — and the adjudicator only opens a handle for an argument that was
            // supplied. So a call omitting `path` was schema-valid and could never succeed, which
            // is the mismatch ADR-034 separated the two fields to make visible.
            vec![payload_req("pattern", Text), target_req("path", ParamType::Path)],
        ),
        registration(
            "web",
            "Fetch one URL over https and return the page. It does not search: supply a full URL. Always returns untrusted content.",
            "web",
            0, // Never inlined. §8.2: raw untrusted bytes do not reach attention.
            Inert,
            &[],
            &["*"],
            // **`url` is REQUIRED and `query` is gone.** Both were optional when `web` was
            // "search and fetch": a search had no url, a fetch had no query, so neither could be
            // mandatory. This build only fetches, so `url` is exactly what the executor cannot
            // run without — and a `query` parameter for an operation that does not exist invites
            // a call that always fails. It returns when search does (ADR-035).
            vec![target_req("url", Url)],
        ),
        registration(
            "recall",
            // **The description now says WHEN to reach for it, because that is what was missing.**
            // Observed live: asked when a deploy script runs — an answer that was in memory, with
            // `recall` exposed and executable — the model called `bash` (`ls -la`), was refused, and
            // then answered from a directory listing that never happened. "Search memory
            // explicitly" describes the mechanism and never told it this was the moment.
            //
            // Every clause is `daemon::recall`: it reads `recall_candidates()` (§4.3 hot ∪ cold,
            // tombstones and unmatured included, which auto-injection withholds), scores with
            // `cue::lexical` (BM25 over tokens, no stemming and no stop list — so the user's own
            // words are the ones that match), drops zero scores, and truncates at `RECALL_LIMIT`.
            // The withholding half is not taken on trust either:
            // `retrieve.rs::nothing_is_injected_before_maturation` is the injection path refusing
            // an entry that `recall_candidates()` returns unconditionally.
            "Search Marlowe's own memory: what the user said in earlier sessions, and what Marlowe has learned. Reach for this FIRST when a question touches anything from before — ahead of guessing, and ahead of reading the filesystem. It also returns entries nothing else surfaces: ones not yet matured, and ones forgotten. Matching is by word, so reuse the user's. Up to 5 results.",
            "recall",
            8_192,
            Inert,
            &[],
            &[],
            // **`payload_kind` is gone.** `RecallTools::recall` reads `query` and nothing else, so
            // the argument was accepted, ignored, and never reported — a model that passed
            // `payload_kind: "commitment"` believed it had filtered and got an unfiltered answer.
            // That is worse than `web`'s removed `query`, which at least failed loudly. It comes
            // back when the executor filters on it.
            vec![payload_req("query", Text)],
        ),
        registration(
            "remember",
            // CONTRACTS §3.5's naming hazard: the tool is a REQUEST, not a write the model performs.
            // `DaemonMemory::remember` adjudicates the claim, maps `payload_kind` through a closed
            // set (an unknown value is refused by name), appends through the signed journal, and
            // returns `"{id} · {trust:?} · injectable after {ms}"` — so the receipt's three fields
            // are named here rather than left for the model to parse blind.
            "Ask the harness to record something worth keeping. A request, not a write: the harness adjudicates it, stamps and signs it, and can refuse. What comes back is a receipt — the entry's id, the trust class the harness derived for it, and when it becomes injectable.",
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
            // **"Spawn, steer or await" named three operations, and the model can reach none.**
            // `ollama::control_step` routes a model's `run` call to an ordinary `ToolCall`, no host
            // declares a `run` executor, and `ModelStep::Spawn` — the only thing that reaches
            // `Engine::spawn` — is constructed nowhere outside `spawn_and_budget.rs`. There is also
            // no steer and no await: the parameters are a task and a child's capability profile,
            // with no run id among them. Saying so is the `web`-does-not-search precedent; it comes
            // back when M2 D decides who declares the spawn contract (§5: never inferred).
            "Delegate a sub-task to a child run. This build cannot spawn one yet, so the call is refused — do the work in this run instead.",
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
            // What actually happens: `control_step` builds `ModelStep::Ask(question)`, the engine
            // records `ApprovalRequested`, sets `RunStatus::Paused { AwaitingAnswer }` and returns
            // `LoopOutcome::Escalated`. So the run stops until the user answers — which is the part
            // worth knowing before calling it. "A decision package" named a shape nothing builds.
            "Put a question to the user and wait. The run pauses until they answer. For a choice that is theirs to make — not for confirming work you could simply do.",
            "ask",
            2_048,
            Inert,
            &[],
            &[],
            // **`options` is gone, for `web`'s `query` reason.** `control_step` reads `question`
            // (falling back to the message body) and nothing else, and `ModelStep::Ask` carries a
            // single `String` — so a model that listed options had them silently dropped on the way
            // to a user who never saw them.
            vec![payload_req("question", Text)],
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

    /// **A description that hit the cap was cut mid-sentence and nothing said so.**
    ///
    /// `Description::new` truncates at [`MAX_DESCRIPTION_CHARS`] silently — correctly, because the
    /// budget must hold for third-party prose that arrives as bytes. But for the builtins the cap
    /// is a drafting error rather than an attack, and the failure is invisible: the tool list still
    /// renders, the model still gets a description, and the half of the sentence that said *"the
    /// call fails if it is not found"* is simply gone.
    ///
    /// Strictly less than the cap, not `<=`: a truncated description is exactly `MAX` characters,
    /// so `<=` would pass on the one case this exists to catch.
    #[test]
    fn no_builtin_description_is_silently_truncated() {
        use crate::registry::MAX_DESCRIPTION_CHARS;
        let r = builtin_registry().unwrap();
        for reg in r.iter() {
            let n = reg.description.text().chars().count();
            assert!(
                n < MAX_DESCRIPTION_CHARS,
                "`{}`'s description is {n} chars and the cap is {MAX_DESCRIPTION_CHARS}, so it \
                 reached the model cut off mid-sentence: {:?}",
                reg.id,
                reg.description.text()
            );
        }
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
