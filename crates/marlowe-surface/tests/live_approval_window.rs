//! **The live approval window: yes, no, and no-with-a-reason.**
//!
//! The daemon blocks on this answer, which makes the window the one piece of UI with a process
//! waiting on the other end of it. Two properties follow and both are asserted here:
//!
//! 1. every key that leaves the window **sends an answer**, and
//! 2. there is **no key that leaves it without one** — a dismissed question is a hung turn.

use marlowe_surface::app::{App, Key};
use marlowe_view::approval::PendingApproval;
use marlowe_view::view::Intent;

fn app_awaiting_approval() -> App {
    let producer = marlowe_stub::Session::new();
    let mut view = producer.view().clone();
    view.pending_approval = Some(PendingApproval {
        decision: 3,
        verb: "web".into(),
        scope: "https://example.com/".into(),
        reversible: true,
        novelty: None,
    });
    App::new(view).unwrap()
}

fn answer(key: Key) -> Option<Intent> {
    let mut app = app_awaiting_approval();
    app.on_key(key);
    app.drain_intents().into_iter().next()
}

#[test]
fn y_approves_and_n_declines() {
    assert_eq!(answer(Key::Char('y')), Some(Intent::Approve { granted: true, reason: None }));
    assert_eq!(answer(Key::Char('n')), Some(Intent::Approve { granted: false, reason: None }));
    // Esc is a decline rather than a dismissal. It is the key a user reaches for to make a modal
    // go away, and the only safe meaning for it here is "no".
    assert_eq!(answer(Key::Esc), Some(Intent::Approve { granted: false, reason: None }));
}

#[test]
fn o_collects_a_reason_and_sends_it_with_the_decline() {
    let mut app = app_awaiting_approval();
    app.on_key(Key::Char('o'));
    assert!(app.drain_intents().is_empty(), "opening the editor must not answer yet");

    for c in "wrong host".chars() {
        app.on_key(Key::Char(c));
    }
    app.on_key(Key::Backspace);
    app.on_key(Key::Enter);

    assert_eq!(
        app.drain_intents(),
        vec![Intent::Approve {
            granted: false,
            reason: Some(marlowe_view::notice::Echo("wrong hos".into())),
        }],
        "other is a decline that carries the user's words, quoted and not reworded"
    );
}

/// **Esc inside the editor goes back to the question, not out of it.**
///
/// The tempting behaviour is to treat it as a cancel that closes the window. That would leave the
/// daemon blocked on a read with nothing on screen, which is the worst outcome available here.
#[test]
fn escaping_the_reason_editor_returns_to_the_question_without_answering() {
    let mut app = app_awaiting_approval();
    app.on_key(Key::Char('o'));
    app.on_key(Key::Char('x'));
    app.on_key(Key::Esc);
    assert!(app.drain_intents().is_empty(), "esc in the editor must not answer");

    // ...and the question is still live, so the keys still work.
    app.on_key(Key::Char('y'));
    assert_eq!(
        app.drain_intents(),
        vec![Intent::Approve { granted: true, reason: None }],
        "the window is still up and still answerable"
    );
}

/// **The negative control.** A key that is not an answer must not close the window.
#[test]
fn an_unrelated_key_neither_answers_nor_dismisses() {
    let mut app = app_awaiting_approval();
    for key in [Key::Tab, Key::Up, Key::Char('q'), Key::Char('1'), Key::Enter] {
        app.on_key(key);
        assert!(
            app.drain_intents().is_empty(),
            "{key:?} produced an answer, and it is not one of the three"
        );
    }
    assert!(
        app.view().pending_approval.is_some(),
        "the window must still be up: nothing has answered the daemon"
    );
}
