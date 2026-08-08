//! Not an acceptance row — a way to look at the screen.
//!
//! Run with `cargo test -p marlowe-surface --test snapshot -- --nocapture` to print the frame as
//! text. Tests can pass while the screen looks wrong, and this is the cheapest defence against
//! that. It asserts only the handful of things that would mean the layout collapsed.

mod common;

use marlowe_stub::{Session, StatusState, Tab};
use marlowe_surface::app::{App, Key};

fn show(name: &str, app: &App) {
    println!("\n=== {name} ===");
    println!("{}", common::buffer_text(&common::frame(app, 120, 30)));
}

#[test]
fn the_frame_renders_and_can_be_read() {
    let mut app = common::app();
    app.session.tick(300);
    show("default — schedule tab, listening", &app);

    let mut runs = App::new(Session::new()).unwrap();
    runs.session.tab = Tab::Runs;
    runs.focus = marlowe_surface::region::RegionId::Item(Tab::Runs.into(), 4);
    runs.session.force_state(StatusState::Running, 41_000);
    runs.session.tick(41_000);
    show("runs tab, steer focused, running", &runs);

    let mut waiting = App::new(Session::new()).unwrap();
    waiting.session.force_state(StatusState::Waiting, 0);
    waiting.session.tick(0);
    show("approval overlay — the only element that dims the frame", &waiting);

    let mut trust = App::new(Session::new()).unwrap();
    trust.session.tab = Tab::Trust;
    show("trust tab — present, reachable, and honest about M2", &trust);

    let mut typing = App::new(Session::new()).unwrap();
    typing.input = "/s".into();
    show("slash autocomplete", &typing);

    let mut small = common::app();
    small.session.tick(0);
    println!("\n=== 100x24 — honest refusal, never a degraded grid ===");
    println!("{}", common::buffer_text(&common::frame(&small, 100, 24)));

    // The things that would mean it collapsed.
    let text = common::buffer_text(&common::frame(&common::app(), 120, 30));
    for want in [
        "Model", "Profile", "Session", "Workspace", "Autonomy", "Status", "Conversation",
        "Message", "(m)", "(v)", "(c)", "(i)", "^v", "turn 12", "Schedule",
    ] {
        assert!(text.contains(want), "the frame is missing {want:?}");
    }
}

#[test]
fn a_dropdown_draws_over_the_frame_without_a_fill() {
    let mut app = common::app();
    app.on_key(Key::Esc, 0);
    app.on_key(Key::Char('a'), 0);
    app.on_key(Key::Enter, 0);
    show("autonomy dropdown open", &app);
    let text = common::buffer_text(&common::frame(&app, 120, 30));
    assert!(text.contains("observe") && text.contains("act"));
    // §B14: no background fill to signal selection. The marker carries it.
    assert!(text.contains('›'));
}
