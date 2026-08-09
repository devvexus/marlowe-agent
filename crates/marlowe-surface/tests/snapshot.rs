//! Not an acceptance row — a way to look at the screen.
//!
//! Run with `cargo test -p marlowe-surface --test snapshot -- --nocapture` to print the frame as
//! text. Tests can pass while the screen looks wrong, and this is the cheapest defence against
//! that. It asserts only the handful of things that would mean the layout collapsed.

mod common;

use marlowe_surface::app::{App, Key};
use marlowe_view::{StatusState, Tab};

fn show(name: &str, app: &App) {
    println!("\n=== {name} ===");
    println!("{}", common::buffer_text(&common::frame(app, 120, 30)));
}

#[test]
fn the_frame_renders_and_can_be_read() {
    let mut r = common::rig();
    r.tick(300);
    show("default — schedule tab, listening", &r.app);

    let mut runs = common::rig();
    runs.app.tab = Tab::Runs;
    runs.app.focus = marlowe_surface::region::RegionId::Item(Tab::Runs.into(), 4);
    runs.force_state(StatusState::Running, 41_000);
    show("runs tab, steer focused, running", &runs.app);

    let mut waiting = common::rig();
    waiting.force_state(StatusState::Waiting, 0);
    show("approval overlay — the only element that dims the frame", &waiting.app);

    let mut trust = common::rig();
    trust.app.tab = Tab::Trust;
    show("trust tab — present, reachable, and honest about M2", &trust.app);

    let mut typing = common::rig();
    typing.app.input = "/s".into();
    show("slash autocomplete", &typing.app);

    let mut small = common::rig();
    small.tick(0);
    println!("\n=== 100x24 — honest refusal, never a degraded grid ===");
    println!("{}", common::buffer_text(&common::frame(&small.app, 100, 24)));

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
    let mut r = common::rig();
    r.key(Key::Esc, 0);
    r.key(Key::Char('a'), 0);
    r.key(Key::Enter, 0);
    show("autonomy dropdown open", &r.app);
    let text = common::buffer_text(&common::frame(&r.app, 120, 30));
    assert!(text.contains("observe") && text.contains("act"));
    // §B14: no background fill to signal selection. The marker carries it.
    assert!(text.contains('›'));
}
