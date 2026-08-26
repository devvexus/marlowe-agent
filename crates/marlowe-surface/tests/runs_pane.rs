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
