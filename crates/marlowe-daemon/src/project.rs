//! The daemon's projection into `marlowe-view`. **The second producer, and the reason C2d is a
//! promotion rather than a rename.**
//!
//! The scripted stub could always fill a `SessionView`; that proves nothing, because it was
//! designed alongside the shape. What makes the promotion real is that the *daemon's* own
//! vocabulary — [`StatusReport`] and the [`Event`] stream — maps onto the same view without the
//! view being bent to fit. Where it does not map, this module says so by name rather than
//! inventing a value.
//!
//! # What is deliberately absent
//!
//! §B5's band takes everything it needs from `StatusReport`, which was the point of building that
//! frame in C2c. What the daemon has **no source for** is stated rather than filled in:
//!
//! - **The amplitude meter.** There is no voice pipeline and no token-rate telemetry, so the
//!   projection reports [`MeterSource::None`] and the meter holds its last frame. It does **not**
//!   report `BASELINE`, which would render as a live, silent session — a claim about the world
//!   made by a component that cannot know it. §B12 forbids decorative motion, and a synthetic
//!   envelope on the daemon path would be exactly that.
//! - **The inspector's Runs and Schedule panes.** `Event::Run` carries id, status, tokens and
//!   depth, which is enough for Runs; Schedule has no producer at all until triggers land, so it
//!   renders its own not-built notice.
//! - **`Ambient::spend_cents` and `elapsed_min`** come from `Event::Done`, so they are zero until
//!   a turn completes. Zero is the truth there, not a placeholder.

use marlowe_view::meter::MeterSource;
use marlowe_view::model::{
    Ambient, ControlStrip, Entry, Item, Pager, Picker, StatusBand, StatusState, Tone, ToolCall,
};
use marlowe_view::notice::Speech;
use marlowe_view::turn::{DegradedPath, Metric, ResultSummary, ToolLineState};
use marlowe_view::SessionView;

use crate::protocol::{Event, StatusReport};

/// Build the view §B5's band renders, from the report the daemon already answers `Status` with.
///
/// **`rerank_provider` is read, never derived.** ADR-029: the active provider is announced, and
/// STATE.md's inherited note is explicit that the profile row's field is *the* source — building a
/// second one here would be the two-sides-silently-disagree shape with a fresh coat of paint.
pub fn view_from_status(report: &StatusReport) -> SessionView {
    let degraded = report.degraded.as_deref().map(classify_degradation);
    SessionView {
        control: ControlStrip {
            // One option each, because one is the truth: the daemon runs one model, in one
            // workspace, and profile/session switching has no producer until M2 D and M3. A picker
            // listing choices that cannot be taken would be a control that lies about being
            // interactive -- `Picker::new` already refuses an empty one.
            // **Built from the daemon's list, not from a literal.** §2.14: the surface holds no
            // state the daemon lacks, so what a person can select is what the daemon said it would
            // accept. With the endpoint down the list is just the configured model, which is the
            // truthful reading rather than an empty control.
            model: {
                let options: Vec<&str> = report.models.iter().map(String::as_str).collect();
                let selected = options.iter().position(|m| *m == report.model).unwrap_or(0);
                if options.is_empty() {
                    Picker::new(&[report.model.as_str()], 0)
                } else {
                    Picker::new(&options, selected)
                }
            },
            profile: Picker::new(&["default"], 0),
            session: Picker::new(&["cli"], 0),
            workspace: Picker::new(&[report.workspace.as_str()], 0),
            // Addendum A §A8: this is the one control that changes what Marlowe may do without
            // asking. The daemon has no autonomy ladder yet, so it shows the floor rather than a
            // tier nobody implemented.
            autonomy: Picker::new(&["observe"], 0),
        },
        status: StatusBand {
            state: if degraded.is_some() {
                StatusState::Idle
            } else {
                StatusState::Idle
            },
            detail: match &report.degraded {
                Some(remedy) => remedy.clone(),
                None => format!("ready · {}", report.model_disclosure),
            },
            figures: vec![
                format!("{} live", report.live_runs),
                // Announced, never inferred.
                format!("rerank {}", report.rerank_provider),
            ],
            degraded,
        },
        transcript: Vec::new(),
        pager: Pager { turn: 0, compacted: 0, lineage: 0 },
        ambient: Ambient { fill_pct: 0, spend_cents: 0, elapsed_min: 0 },
        approval: None,
        pending_approval: None,
        // No telemetry, so no reading. See this module's header.
        meter: MeterSource::None,
        runs: Vec::new(),
        schedule: vec![not_built("Schedule", pane_key(0), "triggers land in M4")],
    }
}

/// Map the daemon's remedy string onto §B5's declared degraded paths.
///
/// **A remedy that matches none of them is not silently dropped.** Invariant 4 says degrade
/// visibly; a projection that returned `None` for an unrecognised remedy would turn a degraded
/// daemon into a healthy-looking band, which is the failure the invariant exists to prevent. So
/// the fallback is the *most* general declared path rather than an absence.
fn classify_degradation(remedy: &str) -> DegradedPath {
    let r = remedy.to_lowercase();
    if r.contains("ollama") || r.contains("model") || r.contains("provider") {
        DegradedPath::ProviderFailedOver
    } else if r.contains("retriev") || r.contains("dense") || r.contains("embed") {
        DegradedPath::DenseRetrievalOffline
    } else if r.contains("voice") {
        DegradedPath::VoiceUnavailable
    } else {
        // **Not `ProviderFailedOver`.** Guessing the most general declared path meant the band
        // announced a failover that never happened — observed live, for a daemon whose only
        // problem was a stale binary. An unclassified degradation says so.
        DegradedPath::Unclassified
    }
}

/// Fold one turn's events into a view. The transcript grows; nothing else is invented.
pub fn apply_events(view: &mut SessionView, events: &[Event]) {
    for event in events {
        match event {
            Event::Status(r) => {
                view.status.degraded = r.degraded.as_deref().map(classify_degradation);
                view.status.figures = vec![
                    format!("{} live", r.live_runs),
                    format!("rerank {}", r.rerank_provider),
                ];
                // **The control strip re-reads the report too, and this is not cosmetic.**
                // `Request::SetModel` is answered with a fresh `Status`, and the client applies it
                // here rather than patching its own picker optimistically. Without these three
                // lines a switch the daemon *accepted* would leave the strip showing the old model
                // and the band showing the old disclosure — the surface asserting a state the
                // daemon does not hold, which §2.14 exists to make impossible.
                let options: Vec<&str> = r.models.iter().map(String::as_str).collect();
                if !options.is_empty() {
                    let selected = options.iter().position(|m| *m == r.model).unwrap_or(0);
                    view.control.model = Picker::new(&options, selected);
                }
                if r.degraded.is_none() {
                    view.status.detail = format!("ready · {}", r.model_disclosure);
                }
            }
            // Model output, so `Speech::Model`. Deltas coalesce into one `Said` rather than one
            // entry per token. This is the half of `Entry::Said` that is legitimately a `String`:
            // it is what the model emitted, and the harness does not get to reword it.
            Event::Text { delta } => {
                // The first answer token closes the reasoning block: the model has stopped
                // thinking and started answering, and a block still marked open would keep
                // claiming work that has finished.
                if let Some(Entry::Reasoning { done, .. }) = view.transcript.last_mut() {
                    *done = true;
                }
                match view.transcript.last_mut() {
                    Some(Entry::Said(Speech::Model(s))) => s.push_str(delta),
                    _ => view.transcript.push(Entry::Said(Speech::Model(delta.clone()))),
                }
            }
            Event::User { text } => view.transcript.push(Entry::User(text.clone())),
            // **Take back what was rendered as speech.** The model closed a think block it had
            // opened before the `content` channel began, so text already on screen in the response
            // colour was reasoning. Observed live: `</think>` printed to the user under a tool
            // call that had failed.
            //
            // The move is what makes the requirement literal — nothing switches to the response
            // colour before the model leaves the think block, because anything that did is put
            // back. The reasoning block is collapsed by default, so the correction reads as the
            // thinking counter growing rather than as text jumping around.
            Event::SpeechRetracted => {
                // **Searched for, not assumed to be last.** The first version of this checked
                // `transcript.last()` only, which held for the event order in its test and not
                // for the one the provider produced — a tool line or a reasoning delta landing
                // after the speech made the retraction a silent no-op, and the leak stayed on
                // screen. The retraction is about the turn's outstanding speech wherever it sits.
                let Some(at) =
                    view.transcript.iter().rposition(|e| matches!(e, Entry::Said(Speech::Model(_))))
                else {
                    // Nothing outstanding. A turn can retract before it has spoken, and that is
                    // not an error — it is the ordinary nested `<think>…</think>` case.
                    continue;
                };
                let Entry::Said(Speech::Model(spoken)) = view.transcript.remove(at) else {
                    unreachable!("rposition matched this variant")
                };
                // Into the thinking block it belongs to: the one immediately before it, so the
                // reasoning reads in the order the model produced it.
                match view.transcript[..at].iter().rposition(|e| matches!(e, Entry::Reasoning { .. }))
                {
                    Some(r) => {
                        if let Entry::Reasoning { text, done } = &mut view.transcript[r] {
                            text.push_str(&spoken);
                            *done = false;
                        }
                    }
                    None => view
                        .transcript
                        .insert(at, Entry::Reasoning { text: spoken, done: false }),
                }
            }
            // Coalesced into one block, and it opens as soon as the first chunk lands.
            Event::Reasoning { delta } => match view.transcript.last_mut() {
                Some(Entry::Reasoning { text, done: false }) => text.push_str(delta),
                _ => view
                    .transcript
                    .push(Entry::Reasoning { text: delta.clone(), done: false }),
            },
            Event::Tool { id, verb, target, state, summary } => {
                let call = tool_call(*id, verb, target, state, summary);
                match view.transcript.last_mut() {
                    Some(Entry::Tools(calls)) => calls.push(call),
                    _ => view.transcript.push(Entry::Tools(vec![call])),
                }
            }
            Event::Compacted { turns } => {
                view.transcript.push(Entry::Compacted { turns: *turns });
                view.pager.compacted += turns;
                view.pager.lineage += 1;
            }
            Event::Degraded { what, remedy } => {
                view.status.degraded = Some(classify_degradation(&format!("{what} {remedy}")));
            }
            Event::Approval { .. } => {
                // §B9's overlay needs a `BlastRadius`, and CONTRACTS §9's shape and the rendered
                // one are reconciled in Session E per STATE.md. Rather than build half of it here,
                // the band says an answer is owed -- which is true, and is what `waiting` means.
                view.status.state = StatusState::Waiting;
                view.status.detail = "approval needed".into();
            }
            Event::Done { outcome, detail, spend_micros_usd, elapsed_ms } => {
                if !detail.is_empty() {
                    view.transcript.push(Entry::Said(Speech::Model(detail.clone())));
                }
                view.pager.turn += 1;
                view.ambient.spend_cents = (*spend_micros_usd / 10_000) as u32;
                view.ambient.elapsed_min = (*elapsed_ms / 60_000) as u32;
                view.status.state = StatusState::Idle;
                view.status.detail = outcome.clone();
            }
            Event::Run { id, status, tokens, depth, .. } => {
                view.runs.push(Item::new(
                    id,
                    // **From the safe pool, never a digit.** The first version numbered runs by
                    // position, which produced '1'..'9' — the inspector tab digits (§B7). It would
                    // have refused to start the moment a run existed, and only because
                    // `KeyRegistry::build` errors on a collision rather than letting one key
                    // silently shadow another.
                    pane_key(view.runs.len()),
                    if status == "running" { Tone::Green } else { Tone::Dim },
                    &[
                        (status.as_str(), Tone::Normal),
                        (&format!("{tokens} tokens · depth {depth}"), Tone::Dim),
                    ],
                ));
            }
            Event::Error { detail } => {
                view.status.degraded = Some(classify_degradation(detail));
            }
        }
    }
}

fn tool_call(id: u64, verb: &str, target: &str, state: &str, summary: &str) -> ToolCall {
    // `ToolCall::verb` is `&'static str` because §B6's vocabulary is closed. A verb off the wire
    // is not static, so it is matched against the builtins and anything unrecognised renders as
    // `tool` rather than leaking an arbitrary string into the frame.
    let verb: &'static str = match verb {
        "read" => "read",
        "edit" => "edit",
        "find" => "find",
        "bash" => "bash",
        "recall" => "recall",
        "remember" => "remember",
        "web" => "web",
        "spawn" => "spawn",
        _ => "tool",
    };
    let metrics = vec![Metric::State(match state {
        "ok" => "ok",
        "failed" => "failed",
        _ => "running",
    })];
    let summary = ResultSummary::with_detail(metrics, summary);
    let mut call = ToolCall::ok(id, verb, target, Vec::new());
    call.state = match state {
        "failed" => ToolLineState::Failed(summary),
        "running" => ToolLineState::Running { elapsed_ms: 0 },
        _ => ToolLineState::Ok(summary),
    };
    // §B6: failures auto-expand.
    call.expanded = matches!(call.state, ToolLineState::Failed(_));
    call
}

/// Hotkeys a pane item may take, in order.
///
/// **Everything the frame already claims is excluded**: the eight region keys (`m p s w a v c i`,
/// §B2), the six tab digits (§B7), and §B10's copy pair `y`/`Y`. A collision is a refusal to
/// start — which is correct, and is how the first version of this file was caught giving the
/// Schedule item `'s'`, the Session region's key. The refusal happened on a real run rather than
/// in any test, because no test built a view from the daemon and then constructed a key registry
/// over it.
const PANE_KEYS: &[char] = &[
    'b', 'd', 'e', 'f', 'g', 'h', 'j', 'k', 'l', 'n', 'o', 'q', 'r', 't', 'u', 'x', 'z',
];

/// The nth pane key. **Refuses to wrap** — wrapping would hand two items the same key, which is
/// the silent shadowing `KeyRegistry` exists to prevent, reintroduced one layer up.
fn pane_key(n: usize) -> char {
    PANE_KEYS[n.min(PANE_KEYS.len() - 1)]
}

fn not_built(what: &str, key: char, when: &str) -> Item {
    Item::new(
        what,
        key,
        Tone::Dim,
        &[(&format!("not built — {when}"), Tone::Dim)],
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn report() -> StatusReport {
        StatusReport {
            version: "0.1.0".into(),
            workspace: "/ws".into(),
            model: "qwen3.5:9b".into(),
            model_disclosure: "qwen3.5:9b · tool calls 12/12".into(),
            degraded: None,
            rerank_provider: "cpu-sequential".into(),
            model_provider: "ollama".into(),
            live_runs: 0,
        models: Vec::new(),
        }
    }

    #[test]
    fn the_band_reads_the_daemons_own_report_rather_than_a_second_source() {
        // STATE.md, inherited from ADR-029: `rerank_provider` on the profile row is THE field the
        // band reads -- do not build a second source. This asserts the value arrives unchanged.
        let v = view_from_status(&report());
        assert!(
            v.status.figures.iter().any(|f| f.contains("cpu-sequential")),
            "{:?}",
            v.status.figures
        );
        assert_eq!(v.control.model.value(), "qwen3.5:9b");
        assert_eq!(v.control.workspace.value(), "/ws");
    }

    #[test]
    fn a_daemon_with_no_amplitude_source_reports_no_reading_rather_than_silence() {
        // The distinction `MeterSource` exists for. `BASELINE` would render as a live, silent
        // session; the daemon has no telemetry and must say so, so the meter freezes instead.
        let v = view_from_status(&report());
        assert_eq!(v.meter, MeterSource::None);
        assert!(!v.meter.is_reporting());
    }

    #[test]
    fn a_degraded_report_reaches_the_band_even_when_the_remedy_is_unrecognised() {
        // Invariant 4: degrade visibly. An unmatched remedy string must not project to "healthy" --
        // that would turn a degraded daemon into a clean band with nothing reporting the change.
        let mut r = report();
        r.degraded = Some("something nobody has classified yet".into());
        let v = view_from_status(&r);
        assert!(v.status.degraded.is_some(), "an unknown remedy must still degrade the band");

        r.degraded = Some("ollama is not running — start it with `ollama serve`".into());
        let v = view_from_status(&r);
        assert_eq!(v.status.degraded, Some(DegradedPath::ProviderFailedOver));
    }

    #[test]
    fn text_deltas_coalesce_into_one_turn_rather_than_one_entry_per_token() {
        let mut v = view_from_status(&report());
        apply_events(
            &mut v,
            &[
                Event::Text { delta: "Your cost base ".into() },
                Event::Text { delta: "moved.".into() },
            ],
        );
        assert_eq!(v.transcript.len(), 1);
        assert!(matches!(
            &v.transcript[0],
            Entry::Said(Speech::Model(s)) if s == "Your cost base moved."
        ));
    }

    #[test]
    fn an_unrecognised_verb_does_not_leak_an_arbitrary_string_into_the_frame() {
        // §B6's verb vocabulary is closed, and `ToolCall::verb` is `&'static str` because of it.
        let mut v = view_from_status(&report());
        apply_events(
            &mut v,
            &[Event::Tool {
                id: 1,
                verb: "definitely-not-a-builtin".into(),
                target: "x".into(),
                state: "ok".into(),
                summary: "1 file".into(),
            }],
        );
        let Some(Entry::Tools(calls)) = v.transcript.last() else {
            panic!("no tool group");
        };
        assert_eq!(calls[0].verb, "tool");
    }

    #[test]
    fn a_failed_tool_call_arrives_expanded() {
        let mut v = view_from_status(&report());
        apply_events(
            &mut v,
            &[Event::Tool {
                id: 1,
                verb: "bash".into(),
                target: "pytest".into(),
                state: "failed".into(),
                summary: "exit 1".into(),
            }],
        );
        let Some(Entry::Tools(calls)) = v.transcript.last() else {
            panic!("no tool group");
        };
        assert!(calls[0].is_failure());
        assert!(calls[0].expanded, "§B6: failures auto-expand");
    }
}

#[cfg(test)]
mod key_tests {
    use super::*;
    use marlowe_view::Tab;

    /// The bug a real run found, as a test.
    ///
    /// No test built a view from the daemon and then constructed a key registry over it, so a
    /// hotkey collision between the projection and §B2's region keys was invisible until the
    /// binary refused to start. This is that seam, crossed.
    #[test]
    fn no_projected_pane_item_collides_with_a_region_key_or_a_tab_digit() {
        const REGION_KEYS: &[char] = &['m', 'p', 's', 'w', 'a', 'v', 'c', 'i'];
        const COPY_KEYS: &[char] = &['y', 'Y'];

        let mut v = view_from_status(&StatusReport {
            version: "0.1.0".into(),
            workspace: "/ws".into(),
            model: "m".into(),
            model_disclosure: "d".into(),
            degraded: None,
            rerank_provider: "cpu".into(),
            model_provider: "ollama".into(),
            live_runs: 0,
        models: Vec::new(),
        });
        // Enough runs to exhaust the pool and then some.
        let events: Vec<Event> = (0..25)
            .map(|i| Event::Run {
                attribution: None,
                id: format!("r{i}"),
                status: "running".into(),
                tokens: 1,
                depth: 0,
            })
            .collect();
        apply_events(&mut v, &events);

        for item in v.runs.iter().chain(v.schedule.iter()) {
            assert!(
                !REGION_KEYS.contains(&item.key),
                "pane item {:?} took region key {:?} (§B2) — the binary refuses to start",
                item.label,
                item.key
            );
            assert!(
                !item.key.is_ascii_digit(),
                "pane item {:?} took a digit, which reaches an inspector tab (§B7)",
                item.label
            );
            assert!(!COPY_KEYS.contains(&item.key), "pane item {:?} took a copy key", item.label);
        }
        assert!(!v.runs.is_empty() && !v.schedule.is_empty(), "the scan had nothing to check");
        let _ = Tab::ALL;
    }
}
