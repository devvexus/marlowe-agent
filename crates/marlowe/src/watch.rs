//! **`marlowe --watch <run>` — a real terminal window on one run.** `M3-DESIGN.md` §6.
//!
//! # Why this is a second process and not a tab
//!
//! §6's first sentence: *"Multiple real TUI windows, not tabs."* A tab would put a run's output in
//! the same frame as the conversation, which is what §6.6's first interface rule exists to stop:
//! *"Filling the main pane with agent output halts the conversation visually, which is what this
//! milestone exists to stop."*
//!
//! A second process also makes §10.1's *"addressable from outside"* literal rather than aspirational.
//! This is an ordinary command. It works in a terminal Marlowe did not open, over SSH, from a
//! script — and that is exactly why [`crate::launcher::open_window`] is allowed to be best-effort:
//! the fallback is a command line, and a command line always works.
//!
//! # What this file does NOT own
//!
//! **The connection.** Session A's [`marlowe_daemon::Client`] finds the control plane, authenticates
//! and falls back to the main port when no control listener is running. A second client here would
//! be two answers to "where is the daemon", and the one that survives is the one that already
//! handles the fall-back.
//!
//! **The projection.** [`RunProjection`] folds `RunDetail` and `RunOutput` into the view.
//!
//! # The loop
//!
//! Poll, render, read a key, repeat. [`POLL_MS`] is the pacing and it is deliberately short: this is
//! a window on a live run, and §B5's rule is that motion means Marlowe is working.
//!
//! **There is no clock in the surface, and after this session there is none in the window at all.**
//! Elapsed is resolved on the daemon — see `ControlPlane::detail` — so a frame is a pure function of
//! the state this loop last fetched. The only time this file reads is the poll interval.

use std::io::{self, Write};
use std::time::{Duration, Instant};

use crossterm::event::{self, Event as TermEvent, KeyCode, KeyEventKind, KeyModifiers};
use crossterm::{execute, terminal};
use ratatui::backend::CrosstermBackend;
use ratatui::Terminal;

use marlowe_daemon::watch_client::RunProjection;
use marlowe_daemon::{Client, Event};
use marlowe_surface::app::Key;
use marlowe_surface::window::{self, Action, WindowApp, WindowRequest};
use marlowe_surface::Theme;

/// How often the window re-asks the control plane what is true.
///
/// **A poll, not a subscription.** 120 ms is under the threshold at which streamed prose reads as
/// arriving rather than appearing, and it is a loopback round trip against an in-memory map. The
/// cost is one connection per poll on a socket doing nothing else.
pub const POLL_MS: u64 = 120;

/// How long a key press waits before the loop goes back to polling.
const KEY_WAIT_MS: u64 = 30;

pub struct Options {
    pub run: String,
    pub profile_root: std::path::PathBuf,
    pub port: Option<u16>,
    pub color_depth: Option<String>,
}

/// Open a window on a run. Returns when the user detaches.
///
/// **Detaching, never cancelling** (§6.5). There is no path out of this function that stops a run
/// except the one the user confirmed at the overlay.
pub fn run(opts: Options) -> io::Result<()> {
    let theme = match Theme::resolve(|k| std::env::var(k).ok(), opts.color_depth.as_deref()) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("error: {e}");
            std::process::exit(2);
        }
    };

    // **Everything that can refuse, refuses before the alternate screen.** A message printed inside
    // a raw-mode alternate buffer that is then torn down is a message nobody reads — the same
    // reason `tui.rs` checks the terminal size before `enable_raw_mode`.
    let mut client = Client::new("watch").with_profile_root(&opts.profile_root);
    if let Some(port) = opts.port {
        client = client.with_port(port);
    }

    let mut projection = RunProjection::new(&opts.run);
    match client.watch(&opts.run, 0) {
        Ok(events) => projection.apply(&events),
        Err(e) => {
            eprintln!("marlowe: {e}");
            std::process::exit(1);
        }
    }
    let Some(view) = projection.view() else {
        eprintln!(
            "marlowe: this daemon holds no run {}. `marlowe --runs` lists them",
            opts.run
        );
        std::process::exit(1);
    };

    let (cols, rows) = terminal::size()?;
    if cols < window::MIN_COLS || rows < window::MIN_ROWS {
        eprintln!(
            "a run window needs {}x{}; this terminal is {cols}x{rows}.\nResize it, or run \
             `marlowe --runs {}` for the same facts without the grid.",
            window::MIN_COLS,
            window::MIN_ROWS,
            opts.run
        );
        std::process::exit(1);
    }

    let mut app = WindowApp::new(view);

    // The panic hook first, for `tui.rs`'s reason: a panic inside raw mode leaves a terminal that
    // echoes nothing and is still on the alternate buffer, with the message invisible.
    install_panic_hook();
    terminal::enable_raw_mode()?;
    execute!(io::stdout(), terminal::EnterAlternateScreen)?;
    // The terminal's own title bar, which no sanitiser in this workspace covers — so every
    // character of it is the harness's own. See `window::title`.
    let mut out = io::stdout();
    let _ = write!(out, "\x1b]0;{}\x07", window::title(app.view()));
    let _ = out.flush();

    let mut term = Terminal::new(CrosstermBackend::new(io::stdout()))?;
    let result = event_loop(&mut term, &mut app, &client, &opts.run, &theme, projection);

    terminal::disable_raw_mode()?;
    execute!(io::stdout(), terminal::LeaveAlternateScreen)?;
    result
}

fn event_loop(
    term: &mut Terminal<CrosstermBackend<io::Stdout>>,
    app: &mut WindowApp,
    client: &Client,
    run_id: &str,
    theme: &Theme,
    mut projection: RunProjection,
) -> io::Result<()> {
    let mut last_poll = Instant::now() - Duration::from_millis(POLL_MS);

    loop {
        // LOOP-EXEMPT: a surface's event loop, not an agent loop.
        if last_poll.elapsed() >= Duration::from_millis(POLL_MS) {
            last_poll = Instant::now();
            match client.watch(run_id, projection.since()) {
                Ok(events) => {
                    // **A degraded frame is shown, not swallowed.** The plane sends one when a
                    // window has fallen off the end of the frame ring; a gap the reader cannot see
                    // is worse than a shorter history.
                    for e in &events {
                        if let Event::Degraded { what, remedy } = e {
                            app.notice = Some(format!("{what} — {remedy}"));
                        }
                    }
                    projection.apply(&events);
                    if let Some(v) = projection.view() {
                        app.update(v);
                    }
                }
                // **The daemon going away does not close the window**, it says so. A window that
                // vanished when a daemon restarted would take the user's steer draft with it.
                Err(e) => app.notice = Some(format!("the control plane is unreachable: {e}")),
            }
        }

        let area = term.size().map(|s| ratatui::layout::Rect::new(0, 0, s.width, s.height))?;
        app.set_scroll_max(window::scroll_max(app, theme, area));
        term.draw(|f| window::draw(app, theme, f.area(), f.buffer_mut()))?;

        if !event::poll(Duration::from_millis(KEY_WAIT_MS))? {
            continue;
        }
        let TermEvent::Key(k) = event::read()? else { continue };
        if k.kind != KeyEventKind::Press {
            continue;
        }
        let Some(key) = translate(k.code, k.modifiers) else { continue };

        let action = app.on_key(key);
        for request in app.drain_requests() {
            match apply(client, run_id, request) {
                Ok(Some(note)) => app.notice = Some(note),
                Ok(None) => {}
                // **The control plane's own words**, verbatim: a refusal reworded here would lose
                // whatever the daemon said about why.
                Err(e) => app.refused(e),
            }
        }
        // A write is answered with a fresh `RunDetail`, so re-project immediately rather than
        // waiting up to 120 ms — `pending_steers` moving is the confirmation that a steer landed.
        if let Ok(events) = client.watch(run_id, projection.since()) {
            projection.apply(&events);
            if let Some(v) = projection.view() {
                app.update(v);
            }
        }
        if action == Action::Close {
            return Ok(());
        }
    }
}

/// Send one request the window made. `Ok(Some(_))` is a note worth showing.
fn apply(
    client: &Client,
    run_id: &str,
    request: WindowRequest,
) -> Result<Option<String>, marlowe_daemon::ClientError> {
    match request {
        // **The same request `/steer` and `marlowe --steer` send** (ADR-054). The text crosses
        // unvalidated; the daemon's admission is the one door, and a cap here would be a second cap.
        WindowRequest::Steer(text) => {
            client.steer(run_id, &text)?;
            Ok(Some("steer sent — it applies at the run's next step".into()))
        }
        WindowRequest::Cancel => {
            client.cancel(run_id)?;
            Ok(Some("cancelling at the next step".into()))
        }
        WindowRequest::Resume => {
            client.resume(run_id)?;
            Ok(Some("resume requested".into()))
        }
        // Nothing crosses the wire. §6.5: closing a window is a fact about the window.
        WindowRequest::Detach => Ok(None),
    }
}

fn translate(code: KeyCode, mods: KeyModifiers) -> Option<Key> {
    let ctrl = mods.contains(KeyModifiers::CONTROL);
    let shift = mods.contains(KeyModifiers::SHIFT);
    Some(match code {
        KeyCode::Char(c) if ctrl => Key::Ctrl(c),
        KeyCode::Char(c) => Key::Char(c),
        KeyCode::Enter if shift => Key::ShiftEnter,
        KeyCode::Enter => Key::Enter,
        KeyCode::Tab => Key::Tab,
        KeyCode::BackTab => Key::BackTab,
        KeyCode::Backspace => Key::Backspace,
        KeyCode::Up => Key::Up,
        KeyCode::Down => Key::Down,
        KeyCode::Esc => Key::Esc,
        _ => return None,
    })
}

fn install_panic_hook() {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let _ = terminal::disable_raw_mode();
        let _ = execute!(io::stdout(), terminal::LeaveAlternateScreen);
        previous(info);
    }));
}

#[cfg(test)]
mod tests {
    /// **There is no clock in the window's surface**, asserted at the crate boundary where it would
    /// show. §6.4's flicker rows rest on a frame being renderable at will; a surface that read a
    /// clock could not be.
    ///
    /// This began as *"the window path has exactly one clock and it is in this file"*. The merge
    /// with Session A removed the last reason for one anywhere: elapsed is resolved on the daemon,
    /// so the window has no `now_ms` at all and this file's only remaining time source is the poll
    /// interval.
    #[test]
    fn the_window_surface_reads_no_clock() {
        let surface = include_str!("../../marlowe-surface/src/window.rs");
        for forbidden in ["SystemTime", "Instant::now", "now_ms"] {
            assert!(
                !surface.contains(forbidden),
                "`{forbidden}` appeared in marlowe-surface/src/window.rs — a surface that reads a \
                 clock, or holds a caller-supplied instant, cannot be rendered at will, and §6.4's \
                 flicker rows rest on exactly that"
            );
        }
        // The control: this file DOES measure time, so the assertion above is about a boundary
        // rather than about a workspace with no clocks in it.
        assert!(include_str!("watch.rs").contains("Instant::now"));
    }
}
