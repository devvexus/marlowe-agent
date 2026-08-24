//! The `use` tool — skill discovery and progressive disclosure. ADR-051.
//!
//! # This is `find_skill`, and it is not a new tool
//!
//! ROADMAP M2 C3 names *"`find_skill` semantic discovery"*. There is no `find_skill` tool and
//! there must not be: ADR-006 registered `use` — *"Find and load a skill or tool"* — in M2 Session
//! A with exactly the two parameters the job needs, and it has been **registered and unrunnable
//! ever since**. Adding a twelfth tool would spend ARCHITECTURE §5's one spare slot on something
//! that already had a slot.
//!
//! | Call | What it does |
//! |---|---|
//! | `use(query = "...")` | discovery — rank installed skills, return names and descriptions |
//! | `use(name = "...")` | disclosure — load that skill's instructions |
//!
//! # THE RANKING IS LEXICAL, NOT SEMANTIC, AND SAYING SO IS THE POINT
//!
//! §7.1 says trigger phrases and descriptions are *"embedded for semantic discovery"*, and the
//! ROADMAP row says "semantic". **This implementation is BM25.** The reason is not a shortcut and
//! it is not a preference:
//!
//! **The shipped interactive daemon holds no embedder.** `Embedder::load_with_provider` has one
//! caller in the workspace — `crates/marlowe/src/main.rs`, on the `--eval-adapter` path — and the
//! daemon's memory is a `BeliefStore::derive` with no dense cue behind it. `recall`, the tool this
//! one sits beside, ranks with `cue::lexical` for the same reason.
//!
//! So the choice was: rank lexically and say so, or wire an ONNX session into the daemon as a side
//! effect of a skills session. **Claiming "semantic discovery ships" over a BM25 would be this
//! repository's most-repeated defect** — a property asserted where it is declared rather than
//! where it is enforced. It is recorded as named debt in ADR-051 §5 and in `STATE.md`, and the
//! rename in `Metric` output says `lexical` so nothing downstream can read it as the other thing.
//!
//! `use` is nonetheless the right seam: when an embedder does reach the daemon, `rank` is the one
//! function that changes, and `Skill::discovery_text` already defines exactly what may be embedded.
//!
//! # There is no second ranker
//!
//! `cue::lexical::score_texts` is `score_all`'s own arithmetic with the belief projection lifted
//! out (ADR-051), pinned by `the_belief_path_and_the_text_path_are_the_same_arithmetic`. A second
//! BM25 beside the retrieval one would put the tokenizer — the part most likely to be wrong — in
//! two places that could disagree silently.
//!
//! # Why a wrapper, and why the trust class is what it is
//!
//! A wrapper for `recall`'s reason: `marlowe-exec` executes against the filesystem and the
//! network, and teaching it about skills would point the executor crate at another subsystem. The
//! daemon is the composition root and already owns both.
//!
//! **A loaded skill's instructions enter at `UserAsserted`.** That is a claim, so here is the
//! argument. Installing a skill into the profile is the user directing Marlowe to follow those
//! instructions — the same reasoning ADR-052 gives for an installed MCP server being trusted, and
//! the reason `skill::load_skill` records `ManifestProvenance::UserReviewed`. The agent cannot
//! install one on its own initiative.
//!
//! What keeps that safe is **not** the class: it is that `use` is declared `Reversible` rather
//! than `Inert` specifically so §9's target check fires on `name`. Untrusted content therefore
//! cannot *choose* which skill loads, which is the supply-chain-steering attack. `builtin.rs` has
//! carried that comment since Session A; this is the first code to depend on it.
//!
//! Note also what the class does **not** buy: `ContextView::trust_floor` is `min`, so a
//! `UserAsserted` block cannot raise a floor that untrusted content has already lowered. The
//! choice between `UserAsserted` and `AgentObserved` here is about labelling the origin honestly,
//! not about a privilege — both sit above `blocks_composed_targets`'s threshold.

use std::sync::{Arc, Mutex};

use marlowe_contract::TrustClass;
use marlowe_loop::driver::{ToolBody, ToolHost, ToolOutcome};
use marlowe_memory::cue::lexical;
use marlowe_permission::{Adjudication, Args};
use marlowe_tools::skill::{Skill, SkillRegistry};
use marlowe_tools::{Metric, ResultSummary, ToolId};

/// How many skills one `use(query = ...)` returns.
///
/// `recall`'s reasoning, unchanged: this competes for the same window the conversation needs, and
/// a discovery result listing forty skills has moved the choice into the model's attention rather
/// than making it.
const DISCOVERY_LIMIT: usize = 5;

/// The daemon's tool host: whatever it wraps, plus `use` over the installed skills.
pub struct SkillTools<H: ToolHost> {
    inner: H,
    skills: Arc<Mutex<SkillRegistry>>,
}

impl<H: ToolHost> SkillTools<H> {
    pub fn new(inner: H, skills: Arc<Mutex<SkillRegistry>>) -> Self {
        Self { inner, skills }
    }

    /// Rank installed skills against a query. **One function**, so the discovery path and any
    /// test of it cannot disagree about what is scored — and so replacing BM25 with an embedder
    /// later is one edit rather than a search.
    ///
    /// Scores exactly [`Skill::discovery_text`]: the description and the trigger phrases, never
    /// the body. §7.1.
    fn rank<'a>(skills: &'a [&'a Skill], query: &str) -> Vec<(&'a Skill, f32)> {
        let texts: Vec<String> = skills.iter().map(|s| s.discovery_text()).collect();
        let refs: Vec<&str> = texts.iter().map(String::as_str).collect();
        let scores = lexical::score_texts(&refs, query);

        let mut order: Vec<usize> = (0..skills.len()).collect();
        // Score descending, then id ascending. The tiebreak is not decoration: two equal scores
        // ordered by whatever the collection did would make one run's discovery differ from the
        // next, and `repro` compares runs byte for byte.
        order.sort_by(|a, b| {
            scores[*b].total_cmp(&scores[*a]).then_with(|| skills[*a].id().cmp(skills[*b].id()))
        });
        // A zero score means the query shares no vocabulary with the skill. Returning those would
        // pad the answer with skills the model then has to argue its way out of.
        order.retain(|i| scores[*i] > 0.0);
        order.truncate(DISCOVERY_LIMIT);
        order.into_iter().map(|i| (skills[i], scores[i])).collect()
    }

    fn discover(&self, query: &str) -> ToolOutcome {
        let skills = self.skills.lock().expect("the skill registry lock was poisoned");
        let all: Vec<&Skill> = skills.iter().collect();

        if all.is_empty() {
            return harness_says(
                "no skills are installed in this profile. A skill is a `SKILL.md` in its own \
                 directory under the profile's `skills/` folder.",
                vec![Metric::Count { n: 0, unit: "skills" }],
            );
        }

        let hits = Self::rank(&all, query);
        if hits.is_empty() {
            return harness_says(
                &format!(
                    "no installed skill matches {query:?}. {} were searched. Note that this \
                     search is lexical, so a skill whose description uses different words will \
                     not be found by meaning alone.",
                    all.len()
                ),
                vec![
                    Metric::Count { n: 0, unit: "skills" },
                    Metric::Count { n: all.len() as u64, unit: "searched" },
                ],
            );
        }

        let mut out = String::new();
        for (skill, _) in &hits {
            // The score is deliberately NOT printed. It is a BM25 magnitude with no calibrated
            // meaning, and a number beside a name invites the model to reason about the gap
            // between two of them as though it were a probability.
            out.push_str(&format!("- {}: {}\n", skill.id(), skill.description().text()));
        }
        out.push_str("\nLoad one with `use` and its name.");

        ToolOutcome {
            summary: ResultSummary::new(vec![
                Metric::Count { n: hits.len() as u64, unit: "skills" },
                Metric::Count { n: all.len() as u64, unit: "searched" },
                Metric::State("lexical"),
            ]),
            body: ToolBody::Inline(out),
            // Installed-skill prose. See the module header on why this class and what it does
            // not buy.
            trust: TrustClass::UserAsserted,
            failed: false,
            wall_ms: 0,
            preview: None,
        }
    }

    fn disclose(&self, name: &str) -> ToolOutcome {
        let skills = self.skills.lock().expect("the skill registry lock was poisoned");
        let Some(skill) = skills.get(name) else {
            // **Names what IS installed.** A bare "not found" invites the model to guess again,
            // and a second wrong guess costs another turn.
            let installed: Vec<&str> = skills.iter().map(|s| s.id().as_str()).collect();
            return failed(&if installed.is_empty() {
                format!("no skill named {name:?} is installed, and neither is any other.")
            } else {
                format!(
                    "no skill named {name:?} is installed. These are: {}.",
                    installed.join(", ")
                )
            });
        };

        match skill.body().read() {
            Err(e) => failed(&format!(
                "the skill `{}` is installed but its instructions could not be read: {e}",
                skill.id()
            )),
            Ok(body) => ToolOutcome {
                summary: ResultSummary::new(vec![
                    Metric::Count { n: 1, unit: "skills" },
                    Metric::Bytes { n: skill.body().bytes() },
                ]),
                body: ToolBody::Inline(body),
                trust: TrustClass::UserAsserted,
                failed: false,
                wall_ms: 0,
                preview: None,
            },
        }
    }

    fn use_tool(&self, args: &Args) -> ToolOutcome {
        let name = args.get("name").and_then(|v| v.as_text()).filter(|s| !s.trim().is_empty());
        let query = args.get("query").and_then(|v| v.as_text()).filter(|s| !s.trim().is_empty());

        match (name, query) {
            // **`name` wins when both are given.** Not arbitrary: `name` is the `Target` and
            // `query` is the `Payload` (`builtin.rs`), so resolving toward `name` means the
            // decision is made by the argument §9 actually checks the provenance of. Preferring
            // the payload would let the checked argument be present and ignored.
            (Some(name), _) => self.disclose(name),
            (None, Some(query)) => self.discover(query),
            (None, None) => failed(
                "`use` needs either `name` (load that skill) or `query` (search for one).",
            ),
        }
    }
}

fn harness_says(detail: &str, metrics: Vec<Metric>) -> ToolOutcome {
    ToolOutcome {
        summary: ResultSummary::new(metrics),
        body: ToolBody::Inline(detail.to_string()),
        // The HARNESS computed this: it enumerated the registry and counted. No skill's prose is
        // in the answer, so no skill's class is inherited. `recall`'s precedent, exactly.
        trust: TrustClass::AgentObserved,
        failed: false,
        wall_ms: 0,
        preview: None,
    }
}

fn failed(detail: &str) -> ToolOutcome {
    ToolOutcome {
        summary: ResultSummary::new(vec![Metric::Count { n: 0, unit: "skills" }]),
        body: ToolBody::Inline(detail.to_string()),
        trust: TrustClass::AgentObserved,
        failed: true,
        wall_ms: 0,
        preview: None,
    }
}

impl<H: ToolHost> ToolHost for SkillTools<H> {
    fn executes(&self) -> Vec<ToolId> {
        // The inner host's set plus `use`, never a hardcoded list — `RecallTools`' reasoning, and
        // `verify_every_exposed_tool_is_runnable` reads this.
        let mut tools = self.inner.executes();
        tools.push(ToolId::new("use"));
        tools
    }

    fn execute(&mut self, tool: &ToolId, args: &Args, adjudication: &Adjudication) -> ToolOutcome {
        if tool.as_str() == "use" {
            return self.use_tool(args);
        }
        self.inner.execute(tool, args, adjudication)
    }

    /// **Forward the batch, or this wrapper silently un-parallelises the product.**
    ///
    /// The default `execute_batch` loops serially. `SkillTools` wraps `RecallTools` which wraps
    /// `FileSystemTools`, and the innermost one is where the concurrent fetch lives — so without
    /// this override the parallel path would exist, be tested, be green, and never run. That is
    /// exactly the trap `RecallTools` documents at length, one layer further out.
    ///
    /// `use` is served here; everything else is delegated **as one batch** and reassembled into
    /// input order.
    fn execute_batch(&mut self, items: &[marlowe_loop::BatchItem<'_>]) -> Vec<ToolOutcome> {
        let mut delegated_slots: Vec<usize> = Vec::new();
        let mut delegated: Vec<marlowe_loop::BatchItem<'_>> = Vec::new();
        for (i, it) in items.iter().enumerate() {
            if it.tool.as_str() != "use" {
                delegated_slots.push(i);
                delegated.push(marlowe_loop::BatchItem {
                    tool: it.tool,
                    args: it.args,
                    adjudication: it.adjudication,
                });
            }
        }

        let inner_out = if delegated.is_empty() {
            Vec::new()
        } else {
            self.inner.execute_batch(&delegated)
        };

        let mut out: Vec<Option<ToolOutcome>> = (0..items.len()).map(|_| None).collect();
        let mut got = inner_out.into_iter();
        for slot in &delegated_slots {
            // Positional, and short-counting is a failure rather than a shift: a missing inner
            // result must never slide onto a later call's position.
            match got.next() {
                Some(o) => out[*slot] = Some(o),
                None => break,
            }
        }
        for (i, it) in items.iter().enumerate() {
            if it.tool.as_str() == "use" {
                out[i] = Some(self.use_tool(it.args));
            }
        }

        out.into_iter()
            .enumerate()
            .map(|(i, o)| {
                o.unwrap_or_else(|| {
                    failed(&format!(
                        "the inner tool host returned no outcome for call {i} (`{}`)",
                        items[i].tool.as_str()
                    ))
                })
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use marlowe_tools::skill::load_skill;
    use std::path::PathBuf;

    /// A host that answers nothing, so every assertion below is about `SkillTools` itself.
    struct Nothing;

    impl ToolHost for Nothing {
        fn executes(&self) -> Vec<ToolId> {
            vec![ToolId::new("read")]
        }
        fn execute(&mut self, _: &ToolId, _: &Args, _: &Adjudication) -> ToolOutcome {
            failed("the inner host was reached")
        }
    }

    fn skill_file(dir: &std::path::Path, name: &str, description: &str, body: &str) -> PathBuf {
        let d = dir.join(name);
        std::fs::create_dir_all(&d).unwrap();
        let f = d.join("SKILL.md");
        std::fs::write(
            &f,
            format!("---\nname: {name}\ndescription: {description}\n---\n{body}\n"),
        )
        .unwrap();
        f
    }

    /// An `Allowed` decision. `SkillTools` never inspects it — what is under test here is the
    /// wiring, and the permission layer has its own suite.
    fn allowed() -> Adjudication {
        let tool = ToolId::new("use");
        Adjudication {
            decision: marlowe_permission::PermissionDecision {
                id: marlowe_permission::DecisionId(1),
                tool: tool.clone(),
                action_class: marlowe_permission::ActionClass {
                    tool,
                    shape: 0,
                    label: "test".into(),
                },
                outcome: marlowe_permission::Outcome::Allowed,
                blast_radius: marlowe_permission::BlastRadius {
                    verb: "use".into(),
                    scope: "test".into(),
                    reversible: true,
                    novelty: None,
                },
                taint: marlowe_permission::TaintSet::new(),
                reasons: Vec::new(),
            },
            handles: Default::default(),
        }
    }

    fn tempdir(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("marlowe-usetool-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    fn host(root: &std::path::Path) -> SkillTools<Nothing> {
        let (registry, errors) = marlowe_tools::skill::scan(root, 0);
        assert!(errors.is_empty(), "the fixture skills must all load: {errors:?}");
        SkillTools::new(Nothing, Arc::new(Mutex::new(registry)))
    }

    #[test]
    fn discovery_returns_names_and_descriptions_and_not_one_word_of_a_body() {
        let root = tempdir("discover");
        skill_file(&root, "pdf-report", "Generate a cited PDF report.", "SECRETSTEP one.");
        skill_file(&root, "sql-tuning", "Diagnose a slow database query.", "SECRETSTEP two.");
        let mut h = host(&root);

        let out = h.execute(
            &ToolId::new("use"),
            &Args::new().text("query", "make me a pdf report"),
            &allowed(),
        );
        let ToolBody::Inline(text) = &out.body else { panic!("expected an inline body") };

        assert!(text.contains("pdf-report"), "the matching skill is missing: {text}");
        assert!(
            !text.contains("SECRETSTEP"),
            "a body reached the discovery result. §7.1: only description + trigger_phrases"
        );
        assert!(!out.failed);
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn disclosure_returns_the_body_and_only_when_asked_by_name() {
        let root = tempdir("disclose");
        skill_file(&root, "pdf-report", "Generate a cited PDF report.", "SECRETSTEP one.");
        let mut h = host(&root);

        let out = h.execute(
            &ToolId::new("use"),
            &Args::new().text("name", "pdf-report"),
            &allowed(),
        );
        let ToolBody::Inline(text) = &out.body else { panic!("expected an inline body") };
        assert!(text.contains("SECRETSTEP one."), "the body did not load: {text}");
        assert_eq!(out.trust, TrustClass::UserAsserted);
        assert!(!out.failed);
        let _ = std::fs::remove_dir_all(&root);
    }

    /// The two halves of progressive disclosure, in one assertion: the same registry, the same
    /// tool, and the body crosses on exactly one of the two calls.
    ///
    /// **This is the control for the test above.** Without it, a `discover` that returned nothing
    /// at all would satisfy "no body in the discovery result".
    #[test]
    fn the_body_crosses_on_disclosure_and_not_on_discovery() {
        let root = tempdir("both");
        skill_file(&root, "pdf-report", "Generate a cited PDF report.", "SECRETSTEP one.");
        let mut h = host(&root);
        let adj = allowed();

        let discovered = h.execute(
            &ToolId::new("use"),
            &Args::new().text("query", "pdf report"),
            &adj,
        );
        let disclosed =
            h.execute(&ToolId::new("use"), &Args::new().text("name", "pdf-report"), &adj);

        let body_of = |o: &ToolOutcome| match &o.body {
            ToolBody::Inline(s) => s.clone(),
            _ => panic!("expected inline"),
        };
        let d = body_of(&discovered);
        let l = body_of(&disclosed);

        assert!(d.contains("pdf-report"), "discovery found nothing, so it proves nothing");
        assert!(!d.contains("SECRETSTEP"));
        assert!(l.contains("SECRETSTEP"));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn a_name_that_is_not_installed_says_what_is() {
        let root = tempdir("missing");
        skill_file(&root, "pdf-report", "Generate a cited PDF report.", "body");
        let mut h = host(&root);
        let out = h.execute(
            &ToolId::new("use"),
            &Args::new().text("name", "no-such-skill"),
            &allowed(),
        );
        assert!(out.failed);
        let ToolBody::Inline(text) = &out.body else { panic!() };
        assert!(text.contains("pdf-report"), "the refusal must name what IS installed: {text}");
        let _ = std::fs::remove_dir_all(&root);
    }

    /// `name` is the `Target` and `query` is the `Payload`. Resolving toward `name` means the
    /// decision is made by the argument the permission layer actually provenance-checks.
    #[test]
    fn name_wins_over_query_when_both_are_supplied() {
        let root = tempdir("both-args");
        skill_file(&root, "alpha", "The first skill.", "ALPHABODY");
        skill_file(&root, "beta", "The second skill.", "BETABODY");
        let mut h = host(&root);

        let out = h.execute(
            &ToolId::new("use"),
            &Args::new().text("name", "alpha").text("query", "second skill"),
            &allowed(),
        );
        let ToolBody::Inline(text) = &out.body else { panic!() };
        assert!(text.contains("ALPHABODY"));
        assert!(!text.contains("BETABODY"));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn use_is_in_the_executed_set_alongside_whatever_is_wrapped() {
        let root = tempdir("executes");
        let h = host(&root);
        let ids: Vec<String> = h.executes().iter().map(|t| t.as_str().to_string()).collect();
        assert!(ids.contains(&"use".to_string()));
        assert!(ids.contains(&"read".to_string()), "the inner host's set must survive");
    }

    #[test]
    fn a_profile_with_no_skills_says_so_rather_than_failing() {
        let root = tempdir("empty");
        let mut h = host(&root);
        let out = h.execute(
            &ToolId::new("use"),
            &Args::new().text("query", "anything"),
            &allowed(),
        );
        assert!(!out.failed, "an empty skills directory is not an error");
        let ToolBody::Inline(text) = &out.body else { panic!() };
        assert!(text.contains("no skills are installed"));
        let _ = std::fs::remove_dir_all(&root);
    }
}
