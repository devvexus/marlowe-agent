//! M2's three report items, each asserted as the property rather than as a proxy.
//!
//! 1. A spawn declaring `reads_untrusted` with a tool set fails at load time.
//! 2. A budget ceiling pauses rather than overspending.
//! 3. A child's transcript never reaches the parent's context.

mod common;

use common::*;
use marlowe_contract::TrustClass;
use marlowe_journal::EventKind;
use marlowe_loop::{
    Budget, BudgetShare, CapabilityProfile, CondensedResult, Engine, LoopOutcome, MemoryRecorder,
    ModelStep, OrphanPolicy, OutputContract, PauseReason, Ports, Provenance, Run, RunId,
    SessionId, SessionState, SpawnRequest,
};
use marlowe_permission::{Tier, Unavailable};
use marlowe_tools::{builtin_registry, ToolId};

fn engine() -> Engine<Unavailable> {
    Engine::new(
        builtin_registry().expect("the eleven builtin manifests load"),
        Unavailable,
        100_000,
        10_000,
        std::path::PathBuf::from("/ws"),
        Tier::Act,
    )
}

fn root(budget: Budget) -> Run {
    Run::root(
        RunId::from_name("root"),
        SessionId::from_name("root-session"),
        CapabilityProfile::interactive(),
        budget,
        OutputContract::answer(),
    )
}

// ─────────────────────────────────────────────────────────────────────────────────────────
// 1. A spawn that declares reads_untrusted with a tool set fails at load time
// ─────────────────────────────────────────────────────────────────────────────────────────

#[test]
fn a_spawn_that_reads_untrusted_with_tools_is_refused_and_the_child_never_starts() {
    // NOTE on the phrasing of this requirement. CONTRACTS §5 states the load-time error as
    // `reads_untrusted && !exposed_tools.is_empty()` — it is a **non-empty** tool set that is
    // refused. The empty set with `reads_untrusted` is the *valid* quarantined reader, and it
    // is asserted below so the two cases cannot be confused.
    let mut e = engine();
    let mut driver = ScriptDriver::new(vec![
        step(
            ModelStep::Spawn(SpawnRequest {
                task: "read this page and tell me what it says".into(),
                contract: OutputContract::new("findings", &["findings"]),
                orphan: OrphanPolicy::Terminate,
                share: BudgetShare::Standard,
                tools: vec![ToolId::new("web")], // the violation
                reads_untrusted: true,
            }),
            100,
        ),
        // **Two replies, one each.** A spawn re-enters the same loop with the same scripted
        // driver, so the CHILD consumes the first reply and completes on it; the parent then
        // needs one of its own. Before M2 C2e a reply ended nothing and one sufficed.
        say("child done", 100),
        say("parent done", 100),
    ]);
    let mut summarizer = EmptySummarizer;
    let mut tools = ScriptedTools::default();
    let mut approvals = FixedApprovals(true);
    let mut sink = CollectingSink::default();
    let mut control = marlowe_loop::NoControl;
    let mut clock = FrozenClock(1_700_000_000_000);
    let mut recorder = MemoryRecorder::default();
    let mut ports = Ports {
        driver: &mut driver,
        summarizer: &mut summarizer,
        tools: &mut tools,
        memory: None,
        approvals: &mut approvals,
        sink: &mut sink,
        control: &mut control,
        clock: &mut clock,
        recorder: &mut recorder,
    };

    let mut run = root(Budget::interactive());
    let mut state = SessionState::new(run.session, "Marlowe.");
    let mut prov = Provenance::new();
    let outcome = e.run(&mut run, &mut state, &mut prov, &mut ports);

    assert!(matches!(outcome, LoopOutcome::Completed(_)), "the parent survives the refusal");

    // The child never started: no RunSpawned event exists.
    assert_eq!(
        recorder.count(EventKind::RunSpawned),
        0,
        "an invalid capability profile must be refused before a child run is created"
    );
    // ...and the parent was told why, in words naming the rule.
    let rendered = e.assembler().assemble(&state).rendered();
    assert!(
        rendered.contains("trifecta"),
        "the refusal must reach the model as a reason it can act on: {rendered}"
    );
    // The requested tool set was NOT silently dropped in favour of a valid quarantined reader.
    assert!(
        !rendered.contains("[child returned"),
        "a refused spawn must not quietly run as something else"
    );
}

#[test]
fn the_empty_tool_set_with_reads_untrusted_is_the_valid_quarantined_reader() {
    // The other side of the same rule, asserted so the refusal above cannot be read as
    // "reads_untrusted is never allowed" — the quarantined reader is the whole reason a
    // subagent may safely read untrusted content at all (§8.2).
    let q = CapabilityProfile::quarantined_reader();
    assert!(q.reads_untrusted());
    assert!(q.exposed_tools().is_empty());
    assert!(!q.may_write_memory());
}

#[test]
fn a_quarantined_child_runs_and_returns_findings() {
    let mut e = engine();
    let mut driver = ScriptDriver::new(vec![
        step(
            ModelStep::Spawn(SpawnRequest {
                task: "summarise the fetched page".into(),
                contract: OutputContract::new("findings", &["findings"]),
                orphan: OrphanPolicy::Terminate,
                share: BudgetShare::Small,
                tools: vec![], // empty: the quarantined shape
                reads_untrusted: true,
            }),
            100,
        ),
        // the child
        step(
            ModelStep::Say("the page recommends x".into()),
            100,
        ),
        // the parent finishes
        say("x", 100),
    ]);
    let mut summarizer = EmptySummarizer;
    let mut tools = ScriptedTools::default();
    let mut approvals = FixedApprovals(true);
    let mut sink = CollectingSink::default();
    let mut control = marlowe_loop::NoControl;
    let mut clock = FrozenClock(1_700_000_000_000);
    let mut recorder = MemoryRecorder::default();
    let mut ports = Ports {
        driver: &mut driver,
        summarizer: &mut summarizer,
        tools: &mut tools,
        memory: None,
        approvals: &mut approvals,
        sink: &mut sink,
        control: &mut control,
        clock: &mut clock,
        recorder: &mut recorder,
    };

    let mut run = root(Budget::interactive());
    let mut state = SessionState::new(run.session, "Marlowe.");
    let mut prov = Provenance::new();
    let outcome = e.run(&mut run, &mut state, &mut prov, &mut ports);

    assert!(matches!(outcome, LoopOutcome::Completed(_)));
    assert_eq!(recorder.count(EventKind::RunSpawned), 1);

    // The orphan policy is recorded at spawn even though M2 cannot orphan anything. That
    // record is what lets M3 be an extension rather than a migration.
    let spawned = recorder.payloads(EventKind::RunSpawned);
    assert_eq!(spawned[0]["orphan_policy"], serde_json::json!("terminate"));
    assert_eq!(spawned[0]["reads_untrusted"], serde_json::json!(true));

    assert!(e.assembler().assemble(&state).rendered().contains("the page recommends x"));
}

// ─────────────────────────────────────────────────────────────────────────────────────────
// 2. A budget ceiling pauses rather than overspending
// ─────────────────────────────────────────────────────────────────────────────────────────

#[test]
fn a_budget_ceiling_pauses_and_never_spends_past_the_line() {
    let mut e = engine();
    // Twenty steps offered; the budget allows far fewer.
    // **Tool calls, not replies.** M2 C2e made a reply-with-no-tool-call the end of a turn,
    // so a script of twenty `say`s now ends at the first one and the budget never bites. A long
    // turn in the real product is a run of tool calls, which is what this scripts.
    let script: Vec<_> = (0..20).map(|_| work(1_000)).collect();
    let mut driver = ScriptDriver::new(script);
    let mut summarizer = EmptySummarizer;
    let mut tools = ScriptedTools::default();
    let mut approvals = FixedApprovals(true);
    let mut sink = CollectingSink::default();
    let mut control = marlowe_loop::NoControl;
    let mut clock = FrozenClock(1_700_000_000_000);
    let mut recorder = MemoryRecorder::default();
    let mut ports = Ports {
        driver: &mut driver,
        summarizer: &mut summarizer,
        tools: &mut tools,
        memory: None,
        approvals: &mut approvals,
        sink: &mut sink,
        control: &mut control,
        clock: &mut clock,
        recorder: &mut recorder,
    };

    let budget = Budget { tokens: 3_000, ..Budget::interactive() };
    let mut run = root(budget);
    let mut state = SessionState::new(run.session, "Marlowe.");
    let mut prov = Provenance::new();
    let outcome = e.run(&mut run, &mut state, &mut prov, &mut ports);

    // It PAUSED. It did not fail, and it did not run to the end of the script.
    assert_eq!(
        outcome,
        LoopOutcome::Paused {
            reason: PauseReason::BudgetExhausted { dimension: "tokens".into() }
        }
    );
    assert_eq!(recorder.count(EventKind::RunPaused), 1, "a pause is never silent");

    // It did not spend past the line.
    assert!(
        run.spent.tokens <= budget.tokens,
        "spent {} against a ceiling of {}",
        run.spent.tokens,
        budget.tokens
    );

    // THE non-proxy assertion: the cap handed to the provider tracked what was left. A
    // constant here would also produce a pause, and the pause alone proves nothing about
    // whether the line could have been crossed.
    assert_eq!(
        driver.limits_seen,
        vec![3_000, 2_000, 1_000],
        "each call is capped at the remaining budget, and the fourth is never issued"
    );
    assert!(driver.steps.len() >= 17, "the script was not exhausted; the budget stopped it");
}

#[test]
fn every_budget_dimension_can_be_the_one_that_pauses() {
    // A budget test that only ever trips on tokens is a budget test for one dimension. Each
    // case below sets one ceiling to its minimum and leaves the others generous.
    for (dimension, budget) in [
        ("tokens", Budget { tokens: 600, ..Budget::interactive() }),
        ("tool_calls", Budget { tool_calls: 0, ..Budget::interactive() }),
        ("micros_usd", Budget { micros_usd: 0, ..Budget::interactive() }),
        ("wall_ms", Budget { wall_ms: 0, ..Budget::interactive() }),
        ("subagents", Budget { subagents: 0, ..Budget::interactive() }),
    ] {
        let mut e = engine();
        let script: Vec<_> = (0..5).map(|_| work(100)).collect();
        let mut driver = ScriptDriver::new(script);
        let mut summarizer = EmptySummarizer;
        let mut tools = ScriptedTools::default();
        let mut approvals = FixedApprovals(true);
        let mut sink = CollectingSink::default();
        let mut control = marlowe_loop::NoControl;
        let mut clock = FrozenClock(1_700_000_000_000);
        let mut recorder = MemoryRecorder::default();
        let mut ports = Ports {
            driver: &mut driver,
            summarizer: &mut summarizer,
            tools: &mut tools,
            memory: None,
            approvals: &mut approvals,
            sink: &mut sink,
            control: &mut control,
            clock: &mut clock,
            recorder: &mut recorder,
        };
        let mut run = root(budget);
        let mut state = SessionState::new(run.session, "Marlowe.");
        let mut prov = Provenance::new();
        let outcome = e.run(&mut run, &mut state, &mut prov, &mut ports);
        assert_eq!(
            outcome,
            LoopOutcome::Paused {
                reason: PauseReason::BudgetExhausted { dimension: dimension.into() }
            },
            "a zero {dimension} ceiling must pause on {dimension}"
        );
    }
}

#[test]
fn a_driver_that_ignores_its_cap_is_stopped_at_the_next_iteration() {
    // The honest limit of the mechanism, asserted rather than left implied. The harness hands
    // the provider a hard cap; a provider that returns more than it was allowed overshoots by
    // at most one call, and the top-of-loop check stops it there. Claiming "never past the
    // line" without this test would be claiming something about a provider we do not control.
    let mut e = engine();
    let mut driver = ScriptDriver::new(vec![
        // Tool calls, not replies: a reply ends the turn (M2 C2e), and this test needs a
        // SECOND iteration to exist so the top-of-loop check can stop it there.
        work(50_000), // ignores a 3,000 cap
        work(50_000),
    ]);
    let mut summarizer = EmptySummarizer;
    let mut tools = ScriptedTools::default();
    let mut approvals = FixedApprovals(true);
    let mut sink = CollectingSink::default();
    let mut control = marlowe_loop::NoControl;
    let mut clock = FrozenClock(1_700_000_000_000);
    let mut recorder = MemoryRecorder::default();
    let mut ports = Ports {
        driver: &mut driver,
        summarizer: &mut summarizer,
        tools: &mut tools,
        memory: None,
        approvals: &mut approvals,
        sink: &mut sink,
        control: &mut control,
        clock: &mut clock,
        recorder: &mut recorder,
    };
    let mut run = root(Budget { tokens: 3_000, ..Budget::interactive() });
    let mut state = SessionState::new(run.session, "Marlowe.");
    let mut prov = Provenance::new();
    let outcome = e.run(&mut run, &mut state, &mut prov, &mut ports);

    assert!(matches!(outcome, LoopOutcome::Paused { .. }));
    assert_eq!(driver.limits_seen, vec![3_000], "exactly one call was issued");
    assert_eq!(driver.steps.len(), 1, "the second scripted step was never reached");
    assert!(run.spent.tokens > 3_000, "the overshoot is real and is bounded to one call");
}

// ─────────────────────────────────────────────────────────────────────────────────────────
// 3. A child's transcript never reaches the parent's context
// ─────────────────────────────────────────────────────────────────────────────────────────

const CHILD_MARKER: &str = "CHILD-TRANSCRIPT-MARKER-9f2a";

#[test]
fn a_childs_transcript_never_reaches_the_parents_context() {
    let mut e = engine();
    let mut driver = ScriptDriver::new(vec![
        // the parent spawns
        step(
            ModelStep::Spawn(SpawnRequest {
                task: "investigate the thing".into(),
                contract: OutputContract::new("what you found", &["findings"]),
                orphan: OrphanPolicy::Detach,
                share: BudgetShare::Standard,
                // The child needs a tool in order to HAVE working to isolate.
                tools: vec![ToolId::new("read")],
                reads_untrusted: false,
            }),
            100,
        ),
        // The child works, then replies — which is what ends it (M2 C2e). It cannot "talk at
        // length" across several replies any more, because the first reply completes it.
        work(100),
        work(100),
        // **The marker is on the child's WORKING (its tool results), not on its answer.**
        //
        // M2 C2e made the reply the result, so a child's final reply legitimately crosses to
        // the parent — that is what a subagent is FOR. What must never cross is how it got
        // there. Marking the answer would test the opposite of the invariant.
        say("the answer is 42", 100),
        // the parent finishes
        say("42", 100),
    ]);
    let mut summarizer = EmptySummarizer;
    // The child's tool results carry the marker: that is its WORKING, which must not cross.
    let mut tools = ScriptedTools {
        body: Some(format!("{CHILD_MARKER} intermediate finding")),
        ..Default::default()
    };
    let mut approvals = FixedApprovals(true);
    let mut sink = CollectingSink::default();
    let mut control = marlowe_loop::NoControl;
    let mut clock = FrozenClock(1_700_000_000_000);
    let mut recorder = MemoryRecorder::default();
    let mut ports = Ports {
        driver: &mut driver,
        summarizer: &mut summarizer,
        tools: &mut tools,
        memory: None,
        approvals: &mut approvals,
        sink: &mut sink,
        control: &mut control,
        clock: &mut clock,
        recorder: &mut recorder,
    };

    let mut run = root(Budget::interactive());
    let mut state = SessionState::new(run.session, "Marlowe.");
    let mut prov = Provenance::new();
    let outcome = e.run(&mut run, &mut state, &mut prov, &mut ports);
    assert!(matches!(outcome, LoopOutcome::Completed(_)));

    // The anti-vacuity check FIRST. Without it, an absent marker in the parent would prove
    // nothing — it would also be absent if the child had never spoken.
    // **The anti-vacuity check, and it took three attempts to state correctly.**
    //
    // Not `sink.text()`: tool bodies never reach the sink, which carries §B6 tool *lines* — a
    // verb and a typed summary. Not `tools.calls`: this engine's scope is `Unavailable`, so
    // adjudication refuses the call before the tool host ever sees it.
    //
    // What is true regardless is that the child made several model calls. A child that ran one
    // step and stopped would leave an absent marker in the parent proving nothing.
    assert!(
        driver.views_seen.len() >= 4,
        "the child must actually have worked across several steps for this test to mean \
         anything; the driver saw {} calls",
        driver.views_seen.len()
    );

    // The property: none of it is in the parent's context, in any tier.
    let view = e.assembler().assemble(&state);
    assert!(
        !view.rendered().contains(CHILD_MARKER),
        "the parent's assembled view carries the child's transcript:\n{}",
        view.rendered()
    );
    for block in view.blocks() {
        assert!(!block.text.contains(CHILD_MARKER), "block {:?} carries it", block.source);
    }
    // ...and not in the raw session state either, which is what the view is built from.
    assert!(!state.volatile.iter().any(|b| b.text.contains(CHILD_MARKER)));

    // What did cross is the contract's field, and only that.
    assert!(view.rendered().contains("findings: the answer is 42"));

    // The parent's own driver only ever saw views without the marker. This is the assertion
    // that would catch a leak arriving through some path other than `SessionState`.
    assert!(
        driver.views_seen.iter().all(|v| !v.contains(CHILD_MARKER)
            || v.contains("investigate the thing")),
        "only the child's own views may contain the child's transcript"
    );
}

#[test]
fn a_child_that_returns_a_transcript_shaped_result_is_refused_by_its_contract() {
    // The second half: the child cannot smuggle its history through the return value either.
    let contract = OutputContract::new("what you found", &["findings"]);
    let smuggled = CondensedResult::new()
        .with("findings", "ok")
        .with("transcript", "...everything I read...");
    assert!(contract.validate(&smuggled).is_err());

    let fat = CondensedResult::new().with("findings", "x".repeat(marlowe_loop::DEFAULT_RESULT_MAX_CHARS + 1));
    assert!(contract.validate(&fat).is_err());
}

#[test]
fn a_child_does_not_inherit_its_parents_provenance_attributions() {
    // A string the user typed to the parent is not user-asserted inside a child that never saw
    // the user say it. Without this, a spawn would be a laundering step for provenance.
    let mut e = engine();
    let mut driver = ScriptDriver::new(vec![
        step(
            ModelStep::Spawn(SpawnRequest {
                task: "look into it".into(),
                contract: OutputContract::new("f", &["findings"]),
                orphan: OrphanPolicy::Terminate,
                share: BudgetShare::Small,
                tools: vec![ToolId::new("remember")],
                reads_untrusted: false,
            }),
            100,
        ),
        // The child names a memory id the *user* mentioned to the parent. In the child that is
        // a model-composed target, and the child's window floor is what decides it.
        step(
            ModelStep::ToolCall {
                tool: ToolId::new("remember"),
                args: marlowe_permission::Args::new()
                    .text("text", "a claim")
                    .text("derived_from", "m-secret")
                    .text("payload_kind", "fact"),
            },
            100,
        ),
        say("done", 100),
        say("ok", 100),
    ]);
    let mut summarizer = EmptySummarizer;
    let mut tools = ScriptedTools::default();
    let mut approvals = FixedApprovals(true);
    let mut sink = CollectingSink::default();
    let mut control = marlowe_loop::NoControl;
    let mut clock = FrozenClock(1_700_000_000_000);
    let mut recorder = MemoryRecorder::default();
    let mut ports = Ports {
        driver: &mut driver,
        summarizer: &mut summarizer,
        tools: &mut tools,
        memory: None,
        approvals: &mut approvals,
        sink: &mut sink,
        control: &mut control,
        clock: &mut clock,
        recorder: &mut recorder,
    };

    let mut run = root(Budget::interactive());
    let mut state = SessionState::new(run.session, "Marlowe.");
    let mut prov = Provenance::new();
    // The user said it — to the parent.
    prov.attribute_user_message("please remember m-secret");

    let _ = e.run(&mut run, &mut state, &mut prov, &mut ports);

    // The child's call went through on the child's own floor — which is `agent_inferred`,
    // because the child's window holds its task brief, and that brief is text the *parent's
    // model* composed. It is allowed, and it is allowed for a reason that has nothing to do
    // with the user having vouched for `m-secret` in a conversation the child never saw.
    let decisions = recorder.payloads(EventKind::PermissionDecided);
    let d = decisions.last().expect("the child adjudicated its remember call");
    assert_eq!(
        d["taint"]["derived_from"],
        serde_json::json!("agent_inferred"),
        "the child's window floor decided this, not the parent's attribution: {d}"
    );
    assert_ne!(
        d["taint"]["derived_from"],
        serde_json::json!("user_asserted"),
        "a spawn must not launder the parent's attributions into the child"
    );
}

#[test]
fn a_child_cannot_be_given_a_tool_its_parent_does_not_have() {
    let narrow = CapabilityProfile::new(
        marlowe_tools::ExposedSet::new(vec![ToolId::new("read"), ToolId::new("done")]).unwrap(),
        marlowe_permission::EgressPolicy::DenyAll,
        marlowe_loop::InterruptPolicy::Interruptible,
        marlowe_loop::ModelRoute::Orchestrator,
        false,
        false,
    )
    .unwrap();

    let mut e = engine();
    let mut driver = ScriptDriver::new(vec![
        step(
            ModelStep::Spawn(SpawnRequest {
                task: "do a thing".into(),
                contract: OutputContract::new("f", &["findings"]),
                orphan: OrphanPolicy::Terminate,
                share: BudgetShare::Small,
                tools: vec![ToolId::new("bash")], // the parent does not have it
                reads_untrusted: false,
            }),
            100,
        ),
        say("ok", 100),
    ]);
    let mut summarizer = EmptySummarizer;
    let mut tools = ScriptedTools::default();
    let mut approvals = FixedApprovals(true);
    let mut sink = CollectingSink::default();
    let mut control = marlowe_loop::NoControl;
    let mut clock = FrozenClock(1_700_000_000_000);
    let mut recorder = MemoryRecorder::default();
    let mut ports = Ports {
        driver: &mut driver,
        summarizer: &mut summarizer,
        tools: &mut tools,
        memory: None,
        approvals: &mut approvals,
        sink: &mut sink,
        control: &mut control,
        clock: &mut clock,
        recorder: &mut recorder,
    };

    let mut run = Run::root(
        RunId::from_name("root"),
        SessionId::from_name("s"),
        narrow,
        Budget::interactive(),
        OutputContract::answer(),
    );
    let mut state = SessionState::new(run.session, "Marlowe.");
    let mut prov = Provenance::new();
    let _ = e.run(&mut run, &mut state, &mut prov, &mut ports);

    assert_eq!(recorder.count(EventKind::RunSpawned), 0, "privilege must not grow with depth");
    assert!(e.assembler().assemble(&state).rendered().contains("not available to this run"));
}

#[test]
fn the_spawn_tree_is_bounded_by_depth() {
    // Anthropic's documented deep-research failures were excessive spawning and endless loops.
    // Depth is the structural bound, and it is checked before a child exists.
    let mut e = engine();
    let spawn = |task: &str| {
        step(
            ModelStep::Spawn(SpawnRequest {
                task: task.into(),
                contract: OutputContract::new("f", &["findings"]),
                orphan: OrphanPolicy::Terminate,
                share: BudgetShare::Standard,
                tools: vec![],
                reads_untrusted: false,
            }),
            10,
        )
    };
    let mut driver = ScriptDriver::new(vec![
        spawn("depth 1"),
        spawn("depth 2"),
        spawn("depth 3 — refused"),
        say("d2", 10),
        say("d1", 10),
        say("ok", 10),
    ]);
    let mut summarizer = EmptySummarizer;
    let mut tools = ScriptedTools::default();
    let mut approvals = FixedApprovals(true);
    let mut sink = CollectingSink::default();
    let mut control = marlowe_loop::NoControl;
    let mut clock = FrozenClock(1_700_000_000_000);
    let mut recorder = MemoryRecorder::default();
    let mut ports = Ports {
        driver: &mut driver,
        summarizer: &mut summarizer,
        tools: &mut tools,
        memory: None,
        approvals: &mut approvals,
        sink: &mut sink,
        control: &mut control,
        clock: &mut clock,
        recorder: &mut recorder,
    };

    let mut run = root(Budget { depth: 2, ..Budget::interactive() });
    let mut state = SessionState::new(run.session, "Marlowe.");
    let mut prov = Provenance::new();
    let outcome = e.run(&mut run, &mut state, &mut prov, &mut ports);

    assert!(matches!(outcome, LoopOutcome::Completed(_)));
    assert_eq!(recorder.count(EventKind::RunSpawned), 2, "two levels, then a refusal");
}

#[test]
fn a_childs_spend_counts_against_its_parent() {
    // A tree whose children spent from thin air would let a run cost arbitrarily more than the
    // root declared, and every per-run budget test would still pass.
    let mut e = engine();
    let mut driver = ScriptDriver::new(vec![
        step(
            ModelStep::Spawn(SpawnRequest {
                task: "t".into(),
                contract: OutputContract::new("f", &["findings"]),
                orphan: OrphanPolicy::Terminate,
                share: BudgetShare::Standard,
                tools: vec![],
                reads_untrusted: false,
            }),
            1_000,
        ),
        say("child thinking", 5_000),
        step(ModelStep::Say("f".into()), 1_000),
    ]);
    let mut summarizer = EmptySummarizer;
    let mut tools = ScriptedTools::default();
    let mut approvals = FixedApprovals(true);
    let mut sink = CollectingSink::default();
    let mut control = marlowe_loop::NoControl;
    let mut clock = FrozenClock(1_700_000_000_000);
    let mut recorder = MemoryRecorder::default();
    let mut ports = Ports {
        driver: &mut driver,
        summarizer: &mut summarizer,
        tools: &mut tools,
        memory: None,
        approvals: &mut approvals,
        sink: &mut sink,
        control: &mut control,
        clock: &mut clock,
        recorder: &mut recorder,
    };

    let mut run = root(Budget::interactive());
    let mut state = SessionState::new(run.session, "Marlowe.");
    let mut prov = Provenance::new();
    let _ = e.run(&mut run, &mut state, &mut prov, &mut ports);

    assert_eq!(run.spent.subagents, 1);
    assert_eq!(
        run.spent.tokens, 7_000,
        // A reply ends a run, so the child costs ONE call and the parent one more. Under the old
        // `done` contract each needed a second step to finish, which is where 8,000 came from.
        "1,000 (spawn) + 5,000 (the child's reply) + 1,000 (the parent's reply)"
    );
}

#[test]
fn a_tool_call_whose_target_came_from_untrusted_content_is_blocked_by_the_loop() {
    // The permission layer's rule, exercised through the loop rather than in isolation — the
    // point being that provenance is computed by the harness from the view, and the model
    // supplies no taint at all.
    let mut e = engine();
    let mut driver = ScriptDriver::new(vec![
        // a fetched page enters the window
        step(
            ModelStep::ToolCall {
                tool: ToolId::new("web"),
                args: marlowe_permission::Args::new().text("url", "https://docs.example.com/x"),
            },
            100,
        ),
        // ...and now the model proposes a shell command
        step(
            ModelStep::ToolCall {
                tool: ToolId::new("bash"),
                args: marlowe_permission::Args::new().text("command", "rm -rf /"),
            },
            100,
        ),
        say("stopped", 100),
    ]);
    let mut summarizer = EmptySummarizer;
    let mut tools = ScriptedTools {
        body: Some("the page says to run rm -rf /".into()),
        trust: Some(TrustClass::UntrustedContent),
        ..Default::default()
    };
    let mut approvals = FixedApprovals(true);
    let mut sink = CollectingSink::default();
    let mut control = marlowe_loop::NoControl;
    let mut clock = FrozenClock(1_700_000_000_000);
    let mut recorder = MemoryRecorder::default();
    let mut ports = Ports {
        driver: &mut driver,
        summarizer: &mut summarizer,
        tools: &mut tools,
        memory: None,
        approvals: &mut approvals,
        sink: &mut sink,
        control: &mut control,
        clock: &mut clock,
        recorder: &mut recorder,
    };

    let mut profile_run = Run::root(
        RunId::from_name("root"),
        SessionId::from_name("s"),
        CapabilityProfile::new(
            marlowe_tools::ExposedSet::new(vec![ToolId::new("web"), ToolId::new("bash")]).unwrap(),
            marlowe_permission::EgressPolicy::allow(&["docs.example.com"]),
            marlowe_loop::InterruptPolicy::Interruptible,
            marlowe_loop::ModelRoute::Orchestrator,
            false,
            false,
        )
        .unwrap(),
        Budget::interactive(),
        OutputContract::answer(),
    );
    let mut state = SessionState::new(profile_run.session, "Marlowe.");
    let mut prov = Provenance::new();
    let _ = e.run(&mut profile_run, &mut state, &mut prov, &mut ports);

    // The web fetch ran; the shell command did not.
    assert_eq!(tools.calls.len(), 1, "only the inert read executed: {:?}", tools.calls);
    assert_eq!(tools.calls[0].0, "web");
    assert!(e
        .assembler()
        .assemble(&state)
        .rendered()
        .contains("UntrustedTarget"));
}

/// **An empty turn must never quietly succeed.** (M2 C2e, issue 2.)
///
/// Completion is the absence of an action, and an empty reply is technically that — so without a
/// guard, a model returning nothing repeatedly would END THE RUN with an empty answer, reported as
/// success. That is the difference between "Marlowe answered" and "Marlowe said nothing and we
/// called it done".
#[test]
fn a_model_that_returns_nothing_fails_the_run_rather_than_completing_it() {
    let mut e = engine();
    // Four empty turns: three are nudged, the fourth exhausts the allowance.
    let mut driver = ScriptDriver::new((0..4).map(|_| say("", 10)).collect());
    let mut summarizer = EmptySummarizer;
    let mut tools = ScriptedTools::default();
    let mut approvals = FixedApprovals(true);
    let mut sink = CollectingSink::default();
    let mut control = marlowe_loop::NoControl;
    let mut clock = FrozenClock(1_700_000_000_000);
    let mut recorder = MemoryRecorder::default();
    let mut ports = Ports {
        driver: &mut driver,
        summarizer: &mut summarizer,
        tools: &mut tools,
        memory: None,
        approvals: &mut approvals,
        sink: &mut sink,
        control: &mut control,
        clock: &mut clock,
        recorder: &mut recorder,
    };

    let mut run = root(Budget::interactive());
    let mut state = SessionState::new(run.session, "Marlowe.");
    let mut prov = Provenance::new();
    let outcome = e.run(&mut run, &mut state, &mut prov, &mut ports);

    match outcome {
        LoopOutcome::Failed { error } => assert!(
            error.contains("no reply and no tool call"),
            "the failure must name what happened: {error}"
        ),
        other => panic!("an empty turn was reported as {other:?} rather than a failure"),
    }
}

/// The nudge is retried a bounded number of times before that failure.
#[test]
fn an_empty_turn_is_nudged_before_it_is_failed() {
    let mut e = engine();
    // Two empties then a real reply: the nudges recover the turn.
    let mut driver = ScriptDriver::new(vec![say("", 10), say("", 10), say("here it is", 10)]);
    let mut summarizer = EmptySummarizer;
    let mut tools = ScriptedTools::default();
    let mut approvals = FixedApprovals(true);
    let mut sink = CollectingSink::default();
    let mut control = marlowe_loop::NoControl;
    let mut clock = FrozenClock(1_700_000_000_000);
    let mut recorder = MemoryRecorder::default();
    let mut ports = Ports {
        driver: &mut driver,
        summarizer: &mut summarizer,
        tools: &mut tools,
        memory: None,
        approvals: &mut approvals,
        sink: &mut sink,
        control: &mut control,
        clock: &mut clock,
        recorder: &mut recorder,
    };

    let mut run = root(Budget::interactive());
    let mut state = SessionState::new(run.session, "Marlowe.");
    let mut prov = Provenance::new();
    let outcome = e.run(&mut run, &mut state, &mut prov, &mut ports);

    assert!(
        matches!(outcome, LoopOutcome::Completed(_)),
        "two empty turns should be recovered by the nudge, not fatal: {outcome:?}"
    );
}
