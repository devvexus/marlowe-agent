//! **A CHARACTERISATION TEST OF A DEPENDENCY, NOT A GUARD. Read this before trusting it.**
//!
//! The TUI does not sanitise. It is safe from terminal-escape forgery because **ratatui** discards
//! control characters on their way into a `Buffer` — a cell holds a grapheme, and `ESC` is not one.
//! That is the enforcing layer, it lives in someone else's crate, and this repository has never
//! asserted it, named it, or arranged to notice it changing.
//!
//! So this file does not prove the TUI is defended. It records **which component is doing the
//! defending**, so that the day a ratatui upgrade changes that behaviour, something fails with a
//! name attached instead of an escape sequence quietly reaching a terminal.
//!
//! # Why the TUI is not sanitised at its own render sites, and when that should change
//!
//! Sanitising in `render::draw` as well would be belt-and-braces, and the argument against it is
//! honest rather than principled: `draw` is a hot path that runs per frame per cell, the marker
//! substitution would change wrapping and column arithmetic that §B13's flicker rows measure to
//! the cell, and the classic CLI — which has *nothing* underneath it — was the surface actually
//! carrying the defect. This is a recorded trade, not an oversight.
//!
//! **What would change it:** this test failing, or the TUI gaining a render path that writes bytes
//! to the terminal without going through a ratatui `Buffer`. Either one moves the enforcing layer,
//! and the sanitiser then belongs at the TUI's sites too.
//!
//! The classic CLI's own guards are unit tests at their enforcement sites — `cli.rs`'s
//! `display_sanitiser` module and `marlowe/src/agent.rs`'s. Those are guards. This is not.

mod common;

use marlowe_view::notice::Speech;
use marlowe_view::Entry;
use marlowe_surface::app::App;

/// One of each family the predicate refuses, chosen because each defeats a *different* defence.
const HOSTILE: [(char, &str); 3] = [
    ('\u{1b}', "ESC — the escape that starts every ANSI sequence"),
    ('\u{202e}', "RIGHT-TO-LEFT OVERRIDE — Trojan Source, reverses displayed order"),
    ('\u{200b}', "ZERO WIDTH SPACE — occupies no columns while carrying bytes"),
];

fn app_saying(text: String) -> App {
    let producer = marlowe_stub::Session::new();
    let mut view = producer.view().clone();
    view.transcript.push(Entry::Said(Speech::Model(text)));
    App::new(view).unwrap()
}

#[test]
fn ratatui_is_the_layer_that_stops_an_escape_reaching_the_grid() {
    for (c, why) in HOSTILE {
        // Wrapped in ordinary words so the vacuity control below can prove the text arrived.
        let app = app_saying(format!("BEFORE{c}AFTER"));
        let buf = common::frame(&app, 140, 40);
        let screen = common::buffer_text(&buf);

        assert!(
            !screen.contains(c),
            "{why}: it reached the ratatui Buffer.\n\
             THIS IS THE ENFORCING LAYER MOVING, not a test being wrong — the TUI does not \
             sanitise, so if ratatui stops filtering this character the TUI is undefended. Add \
             the sanitiser to render::draw; see this file's header.\n{screen}"
        );
    }
}

#[test]
fn the_hostile_text_actually_reached_the_screen() {
    // **The vacuity control, and it is the whole reason the test above means anything.**
    //
    // Every assertion up there passes if the model's speech never rendered at all — a transcript
    // that did not append, a pane too small, a stub whose view was replaced. This asserts the
    // surrounding characters DID land on the grid, so "the escape is absent" is a statement about
    // the escape rather than about an empty buffer.
    let app = app_saying("BEFORE\u{1b}AFTER".to_string());
    let screen = common::buffer_text(&common::frame(&app, 140, 40));
    assert!(screen.contains("BEFORE"), "the speech never rendered:\n{screen}");
    assert!(screen.contains("AFTER"), "the speech never rendered:\n{screen}");
}
