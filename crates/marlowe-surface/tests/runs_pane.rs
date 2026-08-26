//! **`/runs` asks the daemon, and says how many there are only once it has answered.**
//!
//! The Runs tab had never shown a live run to anyone. `/runs` was an `Outcome::Tab`: it switched
//! tab and re-summarised the client's cached view, which was last filled from `Event::Run` at
//! daemon boot. The daemon side was correct throughout — `turn()` registers every run — and the
//! surface simply never asked.
//!
//! The second half is why `Outcome::TabLive` carries no `Notice`. A summary is a **count of what
//! the pane holds**, and one composed at dispatch time counts the stale view: the pane would fill
//! correctly and the sentence beside it would describe the moment before.

mod common;

use marlowe_surface::commands::{self, Outcome};
use marlowe_view::{Intent, Tab};

#[test]
fn slash_runs_asks_the_daemon_rather_than_re_reading_the_cache() {
    let app = common::app();
    match commands::dispatch(app.view(), "runs", &[]) {
        Outcome::TabLive(Tab::Runs, Intent::Runs) => {}
        other => panic!("/runs did not ask for the runs: {other:?}"),
    }
}

/// The control, and the reason the variant exists. If `/runs` still carried a `Notice`, that
/// notice would have been composed from the view as it stood *before* the answer.
#[test]
fn the_request_carries_no_summary_because_there_is_nothing_to_summarise_yet() {
    let app = common::app();
    let outcome = commands::dispatch(app.view(), "runs", &[]);
    assert!(
        !matches!(outcome, Outcome::Tab(..)),
        "/runs is an Outcome::Tab again, which is the stale-summary shape it was moved out of"
    );
}

#[test]
fn pressing_slash_runs_switches_the_tab_at_once_and_queues_the_request() {
    // The tab is the user's keystroke and is instant; the count waits for the daemon.
    let mut app = common::app();
    app.tab = Tab::Schedule;
    app.run_command("runs", &[]);
    assert_eq!(app.tab, Tab::Runs, "the tab did not switch");
    assert!(
        app.drain_intents().contains(&Intent::Runs),
        "nothing was asked of the producer"
    );
}

/// **The summary lands after the answer, not with the request.**
#[test]
fn the_pane_summary_is_said_once_the_producer_has_answered() {
    let mut app = common::app();
    let before = app.view().transcript.len() + app.client_lines.len();
    app.run_command("runs", &[]);
    assert_eq!(
        app.client_lines.len() + app.view().transcript.len(),
        before,
        "a summary was said before the daemon answered — that is the stale count"
    );

    // `advance` applies the intent and republishes in one crank; `update` is that republish.
    let view = app.view().clone();
    app.update(view);
    assert!(
        app.client_lines.len() + app.view().transcript.len() > before,
        "no summary was ever said, so /runs is silent about what it found"
    );
}

// ─── the pane's own keyboard ───────────────────────────────────────────────────────────────────

use marlowe_surface::app::{Action, Key};
use marlowe_view::Item;

/// A view holding runs the boot-time one had never heard of — which is what a live `/runs` produces
/// and what `App::new` could never have seen.
fn view_with_runs(app: &marlowe_surface::app::App, n: usize) -> marlowe_view::SessionView {
    let mut view = app.view().clone();
    let keys = ['b', 'd', 'e', 'f', 'g'];
    view.runs = (0..n)
        .map(|i| {
            Item::new(
                &format!("run-{i}"),
                keys[i],
                marlowe_view::Tone::Normal,
                &[("running", marlowe_view::Tone::Normal)],
            )
            .identified(format!("0000000{i}-0000-4000-8000-000000000000"))
        })
        .collect();
    view
}

/// **The defect: the key registry was built once, in `App::new`, and never again.**
///
/// That was correct while the pane held whatever the connect-time snapshot produced — the registry
/// and the view came from one view and could not disagree. Making `/runs` live broke it: the pane
/// filled with runs the registry had never seen, every one drew a hotkey on its border, and
/// `resolve` missed all of them. §B10's words for exactly this: *"the borders are then lying."*
#[test]
fn a_run_that_arrived_after_startup_answers_to_the_key_on_its_border() {
    let mut app = common::app();
    app.tab = Tab::Runs;
    let view = view_with_runs(&app, 3);
    app.update(view);

    app.on_key(Key::Char('b'));
    assert!(
        matches!(app.focus, marlowe_surface::region::RegionId::Item(_, 0)),
        "the key printed on the first run's border did nothing: focus is {:?}",
        app.focus
    );

    // ...and it is the row the key belongs to, not merely *a* row.
    app.on_key(Key::Char('e'));
    assert!(matches!(app.focus, marlowe_surface::region::RegionId::Item(_, 2)), "{:?}", app.focus);
}

/// The control for the test above: with no runs in the view the same key must do nothing, so the
/// assertion is about the registry tracking the pane rather than about `b` being bound to anything.
#[test]
fn the_same_key_does_nothing_when_the_pane_is_empty() {
    let mut app = common::app();
    app.tab = Tab::Runs;
    let mut view = app.view().clone();
    view.runs.clear();
    app.update(view);
    let before = app.focus;
    app.on_key(Key::Char('b'));
    assert_eq!(app.focus, before, "an empty pane answered a run key");
}

/// **A run listed with no way to act on it is a listing, not a pane.** The only route to a window
/// was typing `/watch <name>` from memory — the affordance the pane exists to replace.
#[test]
fn enter_on_a_focused_run_opens_its_window() {
    let mut app = common::app();
    app.tab = Tab::Runs;
    app.update(view_with_runs(&app, 2));
    app.on_key(Key::Char('d'));
    assert_eq!(app.on_key(Key::Enter), Action::Redraw);

    // Both halves of Session F's split: the spawn is the driver's, the pane refresh the producer's.
    let asks = app.drain_window_asks();
    assert!(
        asks.iter().any(|o| matches!(o, Outcome::Watch(r) if r.ends_with("-0000-4000-8000-000000000000"))),
        "the driver was not asked to open a window: {asks:?}"
    );
    assert!(
        app.drain_intents().iter().any(|i| matches!(i, Intent::Watch { .. })),
        "the producer was not asked to refresh the run"
    );
}

/// Enter opens the run the user is looking at, and the id it carries — not the label, which is a
/// mnemonic and can be shared by two runs.
#[test]
fn enter_opens_the_run_the_row_names_rather_than_the_first_one() {
    let mut app = common::app();
    app.tab = Tab::Runs;
    app.update(view_with_runs(&app, 3));
    app.on_key(Key::Char('e'));
    app.on_key(Key::Enter);
    let asks = app.drain_window_asks();
    assert!(
        asks.iter().any(|o| matches!(o, Outcome::Watch(r) if r.starts_with("00000002"))),
        "the wrong run was opened: {asks:?}"
    );
}

/// The affordance has to be visible, or it is folklore. §B2 puts the enter keycap where Enter acts.
#[test]
fn the_focused_run_shows_that_enter_opens_it() {
    let mut app = common::app();
    app.tab = Tab::Runs;
    app.update(view_with_runs(&app, 2));
    app.on_key(Key::Char('b'));
    let text = common::buffer_text(&common::frame(&app, 140, 40));
    assert!(text.contains("watch"), "the focused run does not say what Enter does:\n{text}");

    // The control: it is on the FOCUSED row only, not on every row.
    assert_eq!(text.matches("↵ watch").count(), 1, "every row is carrying the keycap:\n{text}");
}
