//! §B13: **regions reachable by keyboard alone — 100%.** Plus zero dropped keystrokes.
//!
//! Reachability is proved **from the default focus**, and the default focus changed because of
//! this test's original shape.
//!
//! It used to start in the Message field and press `Esc` before every hotkey — and it passed,
//! because "reachable after one extra key that no border mentions" is still reachable. What it
//! could not see is that §B10's first sentence was false on arrival: *"Region hotkeys jump focus
//! directly."* In a focused text field `m` is the letter m, so every hotkey printed on every
//! border did nothing until the user guessed `Esc` first.
//!
//! The default is now the Conversation, `i` enters the Message field, and this test presses **the
//! hotkey and nothing else**. A test that helps the implementation past the user's real starting
//! state is measuring the wrong thing.

mod common;

use marlowe_stub::{Session, Tab};
use marlowe_surface::app::{App, Key};
use marlowe_surface::region::{RegionId, RegionTree};

#[test]
fn every_region_is_reachable_from_the_default_focus() {
    let mut reached = 0;
    let mut total = 0;

    for tab in Tab::ALL {
        let mut session = Session::new();
        session.tab = tab;
        let tree = RegionTree::build(&session);

        for target in tree.regions() {
            total += 1;
            let mut app = App::new({
                let mut s = Session::new();
                s.tab = tab;
                s
            })
            .unwrap();
            assert_eq!(
                app.focus,
                RegionId::Conversation,
                "the default focus moved; §B10 requires region hotkeys to work on arrival"
            );

            // The hotkey the border advertises, and nothing else. No Esc, no Tab, no warm-up.
            app.on_key(Key::Char(target.hotkey()), 0);

            if app.focus == target.id() {
                reached += 1;
            } else {
                panic!(
                    "{:?} ('{}' on the {} tab) was not reached by Esc then its own hotkey. §B13 \
                     asks for 100% reachable by keyboard alone, and the border says '{}'",
                    target.id(),
                    target.label(),
                    tab.title(),
                    target.hotkey_label()
                );
            }
        }
    }
    println!("regions reachable by keyboard alone: {reached}/{total} (100%)");
}

#[test]
fn tab_and_shift_tab_cycle_every_region_in_reading_order() {
    let mut app = common::app();
    let tree = app.tree();
    let n = tree.regions().len();

    app.on_key(Key::Esc, 0);
    let start = app.focus;
    let mut seen = vec![app.focus];
    for _ in 0..n - 1 {
        app.on_key(Key::Tab, 0);
        seen.push(app.focus);
    }
    app.on_key(Key::Tab, 0);
    assert_eq!(app.focus, start, "Tab must wrap, not stop at the end");

    for r in tree.regions() {
        assert!(
            seen.contains(&r.id()),
            "{:?} is not in the Tab cycle, so a user who never learns its hotkey cannot reach it",
            r.id()
        );
    }

    // Shift-Tab walks it back.
    for _ in 0..n {
        app.on_key(Key::BackTab, 0);
    }
    assert_eq!(app.focus, start);
    println!("Tab cycle covers {n}/{n} regions and wraps in both directions");
}

#[test]
fn every_inspector_tab_is_reachable_by_its_digit() {
    let mut app = common::app();
    app.on_key(Key::Esc, 0);
    for tab in Tab::ALL {
        app.on_key(Key::Char(tab.digit()), 0);
        assert_eq!(
            app.session.tab,
            tab,
            "'{}' did not reach the {} tab",
            tab.digit(),
            tab.title()
        );
    }
}

/// §B13: **dropped keystrokes during streaming — zero.**
///
/// The stub streams a scripted reply while the keys arrive. Input is never blocked (§B10), so
/// every character typed during the stream must land in the message field in order.
#[test]
fn no_keystroke_is_dropped_while_the_stub_is_streaming() {
    let mut app = common::app();
    app.input = "run the tests".into();
    app.submit(0);
    assert!(app.session.is_busy(), "the rig must actually be streaming");
    // `i` enters the message field — the same key the border advertises.
    app.on_key(Key::Char('i'), 0);
    assert_eq!(app.focus, RegionId::Message);

    let typed = "the quick brown fox jumps over the lazy dog 0123456789";
    let mut now = 0u64;
    for c in typed.chars() {
        now += 7;
        // Ticking between keys is what a real loop does; a key that arrives mid-tick must not be
        // swallowed by the redraw.
        app.session.tick(now);
        app.on_key(Key::Char(c), now);
    }
    app.session.tick(now + 3_000);

    assert_eq!(
        app.input, typed,
        "keystrokes were lost or reordered during a stream. Typed {} chars, kept {}",
        typed.len(),
        app.input.len()
    );
    println!(
        "dropped keystrokes during streaming: 0 of {} delivered",
        typed.chars().count()
    );
}

#[test]
fn esc_backs_out_one_level_and_interrupt_is_the_outermost() {
    let mut app = common::app();

    // 3. focus is in a text field -> blur. Reached by `i`, the key the message field's own bottom
    //    border advertises — not assumed, because the default focus is the conversation.
    app.on_key(Key::Char('i'), 0);
    assert_eq!(app.focus, RegionId::Message);
    app.on_key(Key::Esc, 0);
    assert_eq!(app.focus, RegionId::Conversation);

    // 2. a dropdown is open -> close it.
    app.on_key(Key::Char('m'), 0);
    app.on_key(Key::Enter, 0);
    assert!(app.session.control.model.open);
    app.on_key(Key::Esc, 0);
    assert!(!app.session.control.model.open);
    assert_eq!(app.focus, RegionId::Model, "closing a dropdown must not also move focus");

    // 4. otherwise -> interrupt, keeping partial output.
    app.on_key(Key::Char('c'), 0);
    app.input = "run the tests".into();
    app.submit(0);
    app.session.tick(200);
    let kept = app.session.transcript.len();
    app.on_key(Key::Esc, 300);
    assert!(!app.session.is_busy());
    assert!(app.session.transcript.len() >= kept, "§B10: partial output is kept");

    // 1. the approval overlay outranks all of it.
    app.session.force_state(marlowe_stub::StatusState::Waiting, 400);
    assert!(app.session.approval.is_some());
    app.on_key(Key::Esc, 500);
    assert!(app.session.approval.is_none(), "Esc on the overlay denies");
}

#[test]
fn the_overlay_swallows_unrelated_keys_rather_than_letting_them_through() {
    // §B9's whole subject is a user who has stopped reading. An overlay that let a stray keystroke
    // fall through to the frame behind it would be the rubber-stamping failure with extra steps.
    let mut app = common::app();
    app.session.force_state(marlowe_stub::StatusState::Waiting, 0);
    let before = app.session.tab;
    app.on_key(Key::Char('3'), 0);
    app.on_key(Key::Char('c'), 0);
    app.on_key(Key::Tab, 0);
    assert_eq!(app.session.tab, before);
    assert!(app.session.approval.is_some(), "only ↵ e s esc resolve it");
}

#[test]
fn ctrl_keys_work_even_from_inside_a_text_field() {
    // This is what makes reachability true from the default focus without any Esc at all.
    let mut app = common::app();
    app.on_key(Key::Char('i'), 0);
    assert_eq!(
        app.focus,
        RegionId::Message,
        "the premise of this test is that focus IS in a text field; if `i` no longer gets there \
         the test below proves nothing"
    );
    app.on_key(Key::Ctrl('r'), 0);
    assert_eq!(app.session.tab, Tab::Runs);
    app.on_key(Key::Ctrl('t'), 0);
    assert_eq!(app.session.tab, Tab::Trust);

    // ^v drives the status band through all seven states without waiting for a script — with one
    // stop, and the stop is correct. `waiting` raises §B9's overlay, and the overlay is modal: it
    // swallows every key but ↵ e s esc. So reaching `idle` means answering the approval first,
    // which is exactly what `waiting` means. A ^v that walked past a pending approval would be the
    // rubber-stamping failure with a keyboard shortcut attached.
    let mut seen = Vec::new();
    let mut now = 0u64;
    for _ in 0..8 {
        now += 10;
        seen.push(app.session.status.state);
        if app.session.approval.is_some() {
            app.on_key(Key::Esc, now); // deny, and back out of the modal level
        } else {
            app.on_key(Key::Ctrl('v'), now);
        }
    }
    let mut distinct: Vec<&str> = seen.iter().map(|s| s.name()).collect();
    distinct.sort_unstable();
    distinct.dedup();
    assert_eq!(
        distinct.len(),
        7,
        "^v must reach every state, not cycle a subset; saw {distinct:?}"
    );
    println!("status states reachable on demand: 7/7 (waiting via its overlay, as it should be)");
}

#[test]
fn ctrl_v_does_not_walk_past_a_pending_approval() {
    // The other half of the test above, stated on its own so it cannot be lost in a refactor.
    let mut app = common::app();
    app.session.force_state(marlowe_stub::StatusState::Waiting, 0);
    for i in 0..5 {
        app.on_key(Key::Ctrl('v'), i * 10);
    }
    assert_eq!(
        app.session.status.state,
        marlowe_stub::StatusState::Waiting,
        "a global shortcut escaped §B9's overlay; the overlay is the one modal element and \
         answering it is the only way out"
    );
}
