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
//! script, with no TUI running anywhere — and that is exactly why [`crate::launcher`]'s spawn is
//! allowed to be best-effort: the fallback is a command line, and a command line always works.
//!
//! # The loop
//!
//! Poll, render, read a key, repeat. [`POLL_MS`] is the pacing and it is deliberately short: this
//! is a window on a live run, and §B5's rule is that motion means Marlowe is working.
//!
//! **The clock enters here and nowhere below.** `marlowe-surface` reads no clock — that is what
//! makes a headless frame at a chosen `now_ms` possible, and what the flicker rows rest on — so
//! `now_ms` is stamped in this loop and handed down. `window_flicker.rs` then asserts purity
//! against the same function this calls.

use std::io::{self, Write};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crossterm::event::{self, Event as TermEvent, KeyCode, KeyEventKind, KeyModifiers};
use crossterm::{execute, terminal};
use ratatui::backend::CrosstermBackend;
use ratatui::Terminal;

use marlowe_daemon::watch_client::{ControlClient, RunProjection, WatchError};
use marlowe_surface::app::Key;
use marlowe_surface::window::{self, Action, WindowApp, WindowRequest};
use marlowe_surface::Theme;

/// How often the window re-asks the control plane what is true.
///
/// **A poll, not a subscription** — see `marlowe_daemon::watch`. 120 ms is under the threshold at
/// which streamed prose reads as arriving rather than appearing, and it is a loopback round trip
/// against an in-memory map, which the M0c profile measured at microseconds. The cost is one
/// connection per poll on a socket that is doing nothing else.
pub const POLL_MS: u64 = 120;

/// How long a key press waits before the loop goes back to polling.
const KEY_WAIT_MS: u64 = 30;

pub struct Options {
    pub run: String,
    pub profile_root: std::path::PathBuf,
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

    // **Connect before entering the alternate screen.** A refusal printed inside a raw-mode
    // alternate buffer that is then torn down is a refusal nobody reads; this is the same reason
    // `tui.rs` checks the terminal size before `enable_raw_mode`.
    let client = match ControlClient::connect(&opts.profile_root) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("marlowe: {e}");
            std::process::exit(1);
        }
    };

    // **The id is resolved once, against what the daemon holds.** A window opened on a prefix must
    // either name one run or say which ones it could have meant — silently taking the first is how
    // somebody steers the wrong run.
    let run_id = match resolve(&client, &opts.run) {
        Ok(id) => id,
        Err(e) => {
            eprintln!("marlowe: {e}");
            std::process::exit(1);
        }
    };

    let (cols, rows) = terminal::size()?;
    if cols < window::MIN_COLS || rows < window::MIN_ROWS {
        eprintln!(
            "a run window needs {}x{}; this terminal is {cols}x{rows}.\nResize it, or run \
             `marlowe --runs` for the same facts without the grid.",
            window::MIN_COLS,
            window::MIN_ROWS
        );
        std::process::exit(1);
    }

    let mut projection = RunProjection::new(&run_id);
    let first = client
        .watch(&run_id, 0)
        .map_err(|e| io::Error::other(e.to_string()))?;
    projection.apply(&first);
    let Some(view) = projection.view() else {
        eprintln!("marlowe: the control plane holds no run {run_id}");
        std::process::exit(1);
    };
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
    let result = event_loop(&mut term, &mut app, &client, &run_id, &theme);

    terminal::disable_raw_mode()?;
    execute!(io::stdout(), terminal::LeaveAlternateScreen)?;
    result
}

fn event_loop(
    term: &mut Terminal<CrosstermBackend<io::Stdout>>,
    app: &mut WindowApp,
    client: &ControlClient,
    run_id: &str,
    theme: &Theme,
) -> io::Result<()> {
    let mut projection = RunProjection::new(run_id);
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
                        if let marlowe_daemon::Event::Degraded { what, remedy } = e {
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

        app.now_ms = now_ms();
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
                // **The control plane's own words**, verbatim: `SteerRefused::TooLong` names the
                // length and the limit, and both are what the user needs in order to act.
                Err(e) => app.refused(e),
            }
        }
        if action == Action::Close {
            return Ok(());
        }
    }
}

/// Send one request the window made. `Ok(Some(_))` is a note worth showing.
fn apply(
    client: &ControlClient,
    run_id: &str,
    request: WindowRequest,
) -> Result<Option<String>, WatchError> {
    match request {
        // **The same call `/steer` makes**, ADR-054. The text crosses unvalidated; the daemon's
        // `admit` is the one door, and a cap here would be a second cap.
        WindowRequest::Steer(text) => {
            client.steer(run_id, &text)?;
            Ok(Some("steer sent — it applies at the next step".into()))
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

/// Resolve a run id or a unique prefix.
///
/// **An ambiguous prefix is an error naming the candidates**, never the first match. Taking the
/// first would be a window that steers a run the user did not mean, and every control in it would
/// work perfectly while doing it.
fn resolve(client: &ControlClient, given: &str) -> Result<String, String> {
    let events = client.runs().map_err(|e| e.to_string())?;
    let ids: Vec<String> = events
        .iter()
        .filter_map(|e| match e {
            marlowe_daemon::Event::RunDetail { id, .. } => Some(id.clone()),
            _ => None,
        })
        .collect();

    if ids.iter().any(|id| id == given) {
        return Ok(given.to_string());
    }
    let matches: Vec<&String> = ids.iter().filter(|id| id.starts_with(given)).collect();
    match matches.len() {
        1 => Ok(matches[0].clone()),
        0 if ids.is_empty() => Err(
            "this daemon holds no runs. Ask Marlowe something first, then watch the run it starts"
                .into(),
        ),
        0 => Err(format!(
            "no run starts with {given}. This daemon holds: {}",
            ids.iter()
                .map(|i| marlowe_daemon::watch_client::short_id(i))
                .collect::<Vec<_>>()
                .join(", ")
        )),
        _ => Err(format!(
            "{given} could be {} different runs: {}. Give more of the id",
            matches.len(),
            matches
                .iter()
                .map(|i| marlowe_daemon::watch_client::short_id(i))
                .collect::<Vec<_>>()
                .join(", ")
        )),
    }
}

/// Print every run the daemon holds. `marlowe --runs`, and §6.6's *"`/runs` and `/steer` survive"*.
///
/// **This is the fallback that makes the spawn allowed to be best-effort** (§6.7): a terminal
/// Marlowe cannot open is a command the user can paste, and the command is printed beside each run.
pub fn list(profile_root: &std::path::Path) -> io::Result<()> {
    let client = match ControlClient::connect(profile_root) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("marlowe: {e}");
            std::process::exit(1);
        }
    };
    let events = client.runs().map_err(|e| io::Error::other(e.to_string()))?;
    let mut any = false;
    for e in &events {
        let marlowe_daemon::Event::RunDetail {
            id, status, spend_micros_usd, ceiling_micros_usd, last_checkpoint, ..
        } = e
        else {
            continue;
        };
        any = true;
        let checkpoint = match last_checkpoint {
            Some(seq) => format!("seq {seq}"),
            None => "none".into(),
        };
        println!(
            "{}  {:<10}  {} of {}  checkpoint {checkpoint}",
            marlowe_daemon::watch_client::short_id(id),
            status,
            marlowe_view::run::micros_usd(*spend_micros_usd),
            marlowe_view::run::micros_usd(*ceiling_micros_usd),
        );
        println!("          marlowe --watch {}", marlowe_daemon::watch_client::short_id(id));
    }
    if !any {
        println!("Nothing running.");
    }
    Ok(())
}

/// `marlowe --steer <run> <text>`. §6.6: *"steering from outside — another terminal, no TUI, a
/// script. If steering only works in the window, closing one removes a capability."*
pub fn steer(profile_root: &std::path::Path, run: &str, text: &str) -> io::Result<()> {
    let client = match ControlClient::connect(profile_root) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("marlowe: {e}");
            std::process::exit(1);
        }
    };
    let id = match resolve(&client, run) {
        Ok(id) => id,
        Err(e) => {
            eprintln!("marlowe: {e}");
            std::process::exit(1);
        }
    };
    match client.steer(&id, text) {
        Ok(()) => {
            println!("steer sent to {} — it applies at the next step", marlowe_daemon::watch_client::short_id(&id));
            Ok(())
        }
        Err(e) => {
            eprintln!("marlowe: {e}");
            std::process::exit(1);
        }
    }
}

/// Milliseconds since the epoch. **The only clock in the window path**, and it is here rather than
/// in `marlowe-surface` so a frame stays a pure function of `(state, now_ms)`.
fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
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
    use super::*;

    /// The clock is here and nowhere below it. If this ever moves into `marlowe-surface`, the
    /// flicker rows stop being able to render a frame at a chosen instant.
    #[test]
    fn the_window_path_has_exactly_one_clock_and_it_is_in_this_file() {
        let surface = include_str!("../../marlowe-surface/src/window.rs");
        for forbidden in ["SystemTime", "Instant::now", "std::time::SystemTime"] {
            assert!(
                !surface.contains(forbidden),
                "`{forbidden}` appeared in marlowe-surface/src/window.rs — a surface that reads a \
                 clock cannot be rendered at a chosen instant, and §6.4's flicker rows rest on \
                 exactly that"
            );
        }
        // The control: this file does read one, so the assertion above is about a boundary and not
        // about a workspace with no clocks in it.
        assert!(now_ms() > 0);
    }
}
