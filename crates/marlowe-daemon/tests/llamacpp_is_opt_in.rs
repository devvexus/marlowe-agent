//! **ADR-060's hybrid is opt-in, and the sites that would have made it silent.**
//!
//! Three tests here assert the INVERSE of what they asserted a day ago, and each says so at
//! its own doc comment. That is not churn: ADR-060 was accepted as the hybrid rather than as
//! the third provider these were written against, and a refusal that became a fallback is a
//! behavioural decision, not a bug fix. `hybrid_engine.rs` holds the tests for the fallback
//! itself.
//!
//! # What was actually dangerous about adding a provider here
//!
//! Three of the matches over `ModelProviderChoice` are exhaustive, so the compiler carries them.
//! **Four were `if let ModelProviderChoice::OpenRouter { .. }`**, which compile clean against a new
//! variant and take the *Ollama* branch:
//!
//! | site | what it would have done |
//! |---|---|
//! | `Daemon::status` | probe `127.0.0.1:11434`, list Ollama's `/api/tags` as the picker, and report `capability_for(&config.model)` — the 12/12 measured **through Ollama's renderer and parser** |
//! | `Daemon::set_model` | accept or refuse models on the authority of what **Ollama** has pulled |
//! | `marlowe::tui::spawn_args` | spawn a daemon with no `--provider` flag: a local Ollama daemon while the client believes otherwise |
//! | `marlowe::agent::serve` | print a startup announcement identical to an Ollama one |
//!
//! All four are `match` now. The two reachable from this crate are asserted below on **behaviour**,
//! not on the shape of the code: what the daemon reports and what it refuses. `spawn_args` is
//! asserted in `marlowe::tui`'s own `spawn_argv` module, next to the OpenRouter case it repeats.
//!
//! # And the property that must not move
//!
//! Ollama is the default. `zero_config_is_unchanged.rs` asserts that no environment variable moves
//! it; what is added here is that adding a third option did not move it either.

use marlowe_daemon::{Daemon, DaemonConfig, ModelProviderChoice};

fn daemon(case: &str) -> Daemon {
    let root = std::env::temp_dir().join(format!("marlowe-llamacpp-optin-{case}"));
    let _ = std::fs::remove_dir_all(&root);
    std::fs::create_dir_all(&root).expect("a scratch profile");
    let mut config = DaemonConfig::new(root, std::env::temp_dir());
    // A scratch port: this daemon never binds, but a shared one would make two cases collide.
    config.port = 0;
    Daemon::open(config).expect("a daemon on an empty profile")
}

fn llamacpp() -> ModelProviderChoice {
    ModelProviderChoice::LlamaCpp {
        // Port 1 is reserved and nothing listens on it, so the probe reaches `EndpointDown`
        // deterministically rather than depending on whether a server happens to be running.
        endpoint: marlowe_provider::LocalEndpoint::new("127.0.0.1", 1).expect("loopback"),
        sampling: marlowe_provider::llamacpp::SamplingSource::ServerDefaults,
    }
}

#[test]
fn the_default_provider_is_still_ollama_after_a_third_option_exists() {
    // Asserted on `model_provider()` — the ONE function the run path calls to choose a driver and
    // `status()` calls to announce one — rather than on the struct field, which is a value a build
    // can hold while the run path reads something else entirely.
    let config = DaemonConfig::new(std::env::temp_dir(), std::env::temp_dir());
    assert_eq!(config.model_provider(), ModelProviderChoice::Ollama);
}

#[test]
fn every_provider_the_picker_offers_has_a_name_the_enum_can_produce() {
    // `project::PROVIDERS` is the single definition of the set, and `name()` is what `status()`
    // reports. `project.rs`'s picker finds the active one with `position()` and falls back to
    // `unwrap_or(0)`, so a `name()` that did not match its `PROVIDERS` entry EXACTLY would render a
    // llamacpp daemon as `ollama` — a wrong answer in the one place a person reads which provider
    // is live, with nothing failing.
    let produced: Vec<&str> = vec![
        ModelProviderChoice::Ollama.name(),
        ModelProviderChoice::OpenRouter { model: "vendor/model".into() }.name(),
        llamacpp().name(),
    ];
    for name in &produced {
        assert!(
            marlowe_daemon::PROVIDERS.contains(name),
            "`{name}` is a name the enum produces and the picker does not offer"
        );
    }
    assert_eq!(
        produced.len(),
        marlowe_daemon::PROVIDERS.len(),
        "PROVIDERS and this list disagree: {:?} vs {produced:?}. A `PROVIDERS` entry with no \
         variant is refused at runtime by `set_provider`'s named `other` arm; a variant with no \
         entry is worse, because the picker silently reports the wrong provider.",
        marlowe_daemon::PROVIDERS
    );
}

/// **`Daemon::status` did not fall through to the Ollama tail**, asserted on what it reports.
#[test]
fn a_llamacpp_daemon_does_not_disclose_ollamas_measured_tool_call_reliability() {
    let mut d = daemon("status");
    d.config_mut().model_provider = llamacpp();
    let report = d.status();

    assert_eq!(report.model_provider, "ollama/llama.cpp");
    // **The measurement-transfer family, at the one place it would have happened.** The recorded
    // 12/12 for `qwen3.5:9b` was measured through Ollama's `renderer: qwen3.5` and
    // `parser: qwen3.5`; llama.cpp uses neither. Falling through to the Ollama tail would have
    // disclosed one runtime's number under another's name, correctly formatted and about a
    // different system.
    assert!(
        !report.model_disclosure.contains("12/12"),
        "a figure measured through Ollama was disclosed for a runtime that is not Ollama: {}",
        report.model_disclosure
    );
    assert!(
        report.model_disclosure.contains("NOT MEASURED"),
        "{}",
        report.model_disclosure
    );
    assert!(
        report.model_disclosure.contains("llama.cpp"),
        "the disclosure must name the runtime, or a reader cannot tell which system it is about: {}",
        report.model_disclosure
    );

    // The control. Without it the assertions above pass on a build that reports NOT MEASURED for
    // everything — including the default, where the figure is real and disclosing it is the point.
    let mut ollama = daemon("status-control");
    ollama.config_mut().model = marlowe_provider::DEFAULT_MODEL.to_string();
    assert!(
        ollama.status().model_disclosure.contains("12/12"),
        "the Ollama path stopped disclosing its own measurement: {}",
        ollama.status().model_disclosure
    );
}

/// **The picker holds OLLAMA'S inventory, and that is the hybrid's whole first half.**
///
/// # This assertion is the inverse of the one it replaces, and the inversion is the decision
///
/// It read `assert_eq!(report.models, vec![report.model])` — one entry — and that was right for
/// the third-provider design, where the user launched `llama-server` against one blob and Marlowe
/// could not change it. ADR-060 accepted the hybrid instead: **Ollama stores, downloads and lists;
/// llama.cpp serves.** So every model Ollama has pulled is selectable, `/model` restarts the
/// engine against the new blob, and a one-entry picker would now be hiding the inventory the user
/// is entitled to.
///
/// **What this reads on a build without the change:** `models` would be `vec![config.model]`, of
/// length 1, and the assertion that the configured model is *present* would still pass — so the
/// length check is what does the work, and only on a machine where Ollama has more than one model.
/// That is stated rather than hidden: on a machine with exactly one model pulled, this test cannot
/// distinguish the two designs and says so instead of asserting something it has not shown.
#[test]
fn the_hybrids_picker_offers_what_ollama_has_pulled_because_ollama_is_the_store() {
    let mut d = daemon("models");
    d.config_mut().model_provider = llamacpp();
    let report = d.status();
    assert!(
        report.models.iter().any(|m| *m == report.model),
        "the picker must always contain the value it is reporting: {:?}",
        report.models
    );
    let ollama_has = {
        let mut c = daemon("models-control");
        c.config_mut().model = marlowe_provider::DEFAULT_MODEL.to_string();
        c.status().models.len()
    };
    if ollama_has <= 1 {
        eprintln!(
            "SKIP: Ollama reports {ollama_has} model(s) on this machine, so a one-entry picker \
             and the full inventory are indistinguishable here. The assertion below would pass \
             under either design and is therefore not run."
        );
        return;
    }
    assert_eq!(
        report.models.len(),
        ollama_has,
        "the hybrid must offer Ollama's inventory -- Ollama is the store. Got {:?}",
        report.models
    );
}

/// **`/model` on the hybrid RESTARTS the engine. It does not refuse, and it does not lie about
/// having switched.**
///
/// # The inversion, and why the old assertion was right for the old design
///
/// This test used to assert a refusal naming the restart, because Marlowe did not own the server:
/// the model was the argv someone else typed, and there was genuinely nothing a config write could
/// change. ADR-060's hybrid makes Marlowe the thing that started it, so refusing would be
/// declining to do something it can do — and would leave `/model` meaning two different things
/// depending on a provider setting.
///
/// # What is asserted is the ABSENCE OF A WINDOW, which is the property that could lie
///
/// The dangerous shape is an acknowledged switch with the old model still loaded: the picker
/// updates, the band updates, and the next reply comes from the previous weights. So the switch is
/// synchronous — `set_model` does not return until a server on our port is serving the new blob
/// and has been measured on the GPU, or until the engine has fallen back to Ollama, which has the
/// model too. Either way, **when this call returns, `status().model` names something that is
/// actually loaded.**
///
/// **What this reads on a build without the change:** `set_model` returns `Err`, and
/// `expect("...")` fails by name. It cannot pass accidentally.
#[test]
fn switching_models_on_the_hybrid_restarts_the_engine_and_is_not_acknowledged_before_it_is_true() {
    let mut d = daemon("set-model");
    d.config_mut().model_provider = llamacpp();

    // Port 1: nothing can listen there, so the engine cannot start and the fallback is certain.
    // That is the case being asserted -- a model switch must still WORK when the engine cannot,
    // because Ollama has the model and Ollama is the other half of the hybrid.
    let asked = "some-other-model:9b";
    d.set_model(asked).expect(
        "the hybrid switches models by restarting its own engine; a refusal here is the \
         third-provider behaviour ADR-060 replaced",
    );
    assert_eq!(
        d.status().model,
        asked,
        "the switch was acknowledged, so the reported model must be the one asked for"
    );
    // And the reason the engine is not serving it is on the screen rather than implied.
    let degraded = d.status().degraded.unwrap_or_default();
    assert!(
        degraded.contains(marlowe_provider::FELL_BACK_MARKER),
        "a switch whose engine could not restart must SAY so, persistently: {degraded:?}"
    );

    // Selecting the model it is already serving is a no-op rather than a restart -- otherwise
    // `/model <the current one>` would tear down a working server to reach the state it is in.
    let current = d.status().model;
    d.set_model(&current).expect("the model it is already serving");
    assert_eq!(d.status().model, current);
}

/// **THE SWITCH IS ACCEPTED AND THE ENGINE FALLS BACK, AND THE REASON IS ON THE SCREEN.**
///
/// # The single most important behavioural change in ADR-060, asserted on the words
///
/// This test used to assert a **refusal**: the user picks the provider, the server is not up, and
/// Marlowe says no. That was the third-provider design, and Matthew's decision replaces it —
/// *"llama fails fall back to ollama but surface to user why"*. A refusal leaves the user with
/// nothing; a silent fallback leaves them with a screen naming an engine that is not serving. The
/// answer is both: it works, and it says.
///
/// # Asserted where it is enforced, not where it is declared
///
/// The subject is `StatusReport::degraded` — the string §B5 renders in amber in the status band on
/// **every** frame — and the assertions are on the **words a person reads**, not on which enum
/// variant was constructed. A test asserting `matches!(engine, FellBack { .. })` would be green on
/// a build whose message said nothing.
///
/// **What this reads on a build without the change:** `set_provider` returns `Err` and
/// `expect(...)` fails by name; before that, `degraded` carried a launch command with no statement
/// about which engine was serving, so every assertion below fails.
#[test]
fn a_hybrid_switch_whose_engine_cannot_start_falls_back_to_ollama_and_says_exactly_why() {
    let mut d = daemon("switch");
    // **The failure is forced at the STORE, not at the port, and the first attempt at this test is
    // why.** It used port 1 on the theory that nothing can listen there — and on Windows
    // `llama-server` bound it, came up healthy, and measured **97 tok/s on the GPU**. The test
    // failed, correctly, because the premise was wrong rather than the code.
    //
    // Two things follow. A test must not spawn a real 6.7 GB server to assert a string: it takes
    // 2.6 s, it takes the card, and it contends with any measurement running beside it. And the
    // failure has to be one that CANNOT succeed on any machine — so it is a model name that is not
    // in Ollama's store, which fails in `ollama_store::resolve` **before** anything is spawned and
    // before any resident Ollama model is unloaded.
    d.config_mut().model_provider = llamacpp();
    d.config_mut().model = "definitely-not-a-model:0b".to_string();
    d.set_provider("ollama/llama.cpp").expect(
        "the hybrid must be selectable even when its engine cannot start -- that is the fallback",
    );
    // **The switch and the start are two steps now, and the test mirrors the handler.** The engine
    // takes seconds to come up and `set_provider` runs on the thread that answers the control
    // port, so acknowledging first is what stops the surface freezing from the moment the slash
    // command is sent. A test that called only the first half would assert on a daemon that had
    // not tried to start anything.
    d.start_pending_engine();

    let report = d.status();
    assert_eq!(
        report.model_provider, "ollama/llama.cpp",
        "the picker keeps showing what the user CHOSE; the band is what says the engine differs"
    );
    let degraded = report.degraded.expect("a fallen-back engine must degrade visibly");

    // The four clauses the requirement actually asks for.
    assert!(
        degraded.contains("llama.cpp is NOT serving"),
        "it must name the engine that is not serving: {degraded}"
    );
    assert!(
        degraded.contains("Ollama is"),
        "it must name the engine that IS serving, or the user cannot tell if anything is: \
         {degraded}"
    );
    assert!(
        degraded.contains("225 ms"),
        "it must say what was lost, measured rather than adjectival: {degraded}"
    );
    assert!(
        degraded.contains("/provider ollama/llama.cpp"),
        "a degraded state a user cannot act on is a crash with better manners: {degraded}"
    );
    // And the cause is SPECIFIC rather than a category: it names the model that could not be
    // resolved and the store it was looked for in.
    assert!(
        degraded.contains("definitely-not-a-model:0b"),
        "the cause must name what could not be resolved: {degraded}"
    );
    assert!(
        degraded.contains("Ollama's model store"),
        "the cause must name where it looked -- on a layout that changed under us, that is the          whole cost of the change: {degraded}"
    );
}

/// **THE NEGATIVE CONTROL. Without it, a build that shows the fallback line unconditionally passes
/// every assertion above.**
///
/// The plain `ollama` provider is the one state where the fallback sentence must be **absent** —
/// nothing fell back, because nothing was asked to start. Ask what the test above would read if
/// `degraded` were hardcoded to the fallback line: it would pass, and this fails.
#[test]
fn the_fallback_sentence_is_absent_when_no_engine_was_asked_to_start() {
    let mut d = daemon("no-fallback");
    d.config_mut().model_provider = marlowe_daemon::ModelProviderChoice::Ollama;
    let degraded = d.status().degraded.unwrap_or_default();
    assert!(
        !degraded.contains(marlowe_provider::FELL_BACK_MARKER),
        "a plain-Ollama daemon reported an engine fallback that never happened: {degraded}"
    );
    // The second half of the control: `openrouter` is also not the hybrid, and it degrades for its
    // own reasons (no key). Those must not be dressed as an engine fallback either.
    d.config_mut().model_provider =
        marlowe_daemon::ModelProviderChoice::OpenRouter { model: "vendor/model".into() };
    let degraded = d.status().degraded.unwrap_or_default();
    assert!(
        !degraded.contains(marlowe_provider::FELL_BACK_MARKER),
        "an OpenRouter degradation was reported as a llama.cpp fallback: {degraded}"
    );
}

/// **The collision a live run found, and the guard that closes the class rather than the instance.**
///
/// `LLAMACPP_DEFAULT_PORT` was 11435 — which is `DEFAULT_DAEMON_PORT`. Every unit test passed,
/// because no single process knows both constants; what caught it was `marlowe --status --provider
/// llamacpp` reporting *"something is listening on http://127.0.0.1:11435 but it is not
/// llama-server"* about **Marlowe's own daemon**. Moving the constant fixes today. This asserts on
/// the configured ports, which is what can still collide once both are settable by hand.
#[test]
fn a_llamacpp_port_equal_to_the_daemons_own_is_refused_by_name() {
    // Half one: the two compiled defaults. Nothing in a single process compares them but this.
    assert_ne!(
        marlowe_provider::LLAMACPP_DEFAULT_PORT,
        marlowe_daemon::DEFAULT_DAEMON_PORT,
        "the two defaults collided again"
    );
    assert_ne!(
        marlowe_provider::LLAMACPP_DEFAULT_PORT,
        marlowe_provider::LocalEndpoint::DEFAULT_PORT,
        "the llamacpp default landed on Ollama's port, which this provider must run beside"
    );

    // Half two, and it is the one that survives both constants changing: a hand-set collision
    // is refused. `--daemon-port` and `--llamacpp-port` are both settable, so equal defaults
    // were never the only way to reach this state.
    let mut d = daemon("port-collision");
    d.config_mut().port = marlowe_provider::LLAMACPP_DEFAULT_PORT;
    let e = d
        .set_provider("llamacpp")
        .expect_err("a llama-server cannot be on the daemon's own control port");
    assert!(
        e.contains("own control port"),
        "the refusal must say WHICH conflict this is, or it reads as the server being down: {e}"
    );
}

/// The name is accepted by `set_provider` — i.e. the arm exists at all. Without it,
/// `set_provider`'s named `other` arm answers *"`llamacpp` is listed as a provider and has no
/// implementation"*, which is the correct failure and still a failure.
#[test]
fn llamacpp_is_not_rejected_by_name() {
    let mut d = daemon("by-name");
    // **A model that is not in Ollama's store, so the engine cannot start and this test cannot
    // spawn a 6.7 GB server.** It was spawning one: `set_provider` starts the engine, and on this
    // machine that meant a real `llama-server` on the card for ~2 s per test. CLAUDE.md's sixth
    // parallel-session hazard is a build stealing CPU from a timed measurement; a test suite
    // taking the GPU is the same hazard with a different resource, and it would be invisible in
    // the measurement it corrupted. The subject here is the NAME being accepted, not the engine.
    d.config_mut().model = "definitely-not-a-model:0b".to_string();
    if let Err(e) = d.set_provider("llamacpp") {
        assert!(
            !e.contains("is not a provider this build has"),
            "the picker offers it and the daemon does not know it: {e}"
        );
        assert!(
            !e.contains("has no implementation"),
            "`PROVIDERS` gained an entry that `set_provider` has no arm for: {e}"
        );
    }
}
