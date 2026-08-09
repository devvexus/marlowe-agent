//! The terminal event loop. Owns raw mode, the alternate screen, and nothing else.
//!
//! Every decision that could be made without a terminal was made without one — focus, dispatch,
//! layout and drawing all live in `marlowe-surface` and are exercised headless. What is left here
//! is the part that genuinely needs a TTY, which is also the part that cannot be unit-tested and
//! therefore has to be small.
//!
//! # No real clock is read in this file
//!
//! Time comes from `marlowe_stub::Clock`, which is the fence `determinism_guard.rs` names. That is
//! not ceremony: it is what keeps every render a pure function of `(state, now_ms)`, which is what
//! makes §B13's flicker rows diffable.

use std::io::{self, Write};

use crossterm::event::{
    self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyEventKind, KeyModifiers,
    MouseButton, MouseEventKind,
};
use crossterm::{execute, terminal};
use marlowe_stub::Clock;
use marlowe_view::Produce;
use marlowe_surface::app::{Action, App, Key};
use marlowe_surface::{render, Theme, MIN_COLS, MIN_ROWS};
use ratatui::backend::CrosstermBackend;
use ratatui::Terminal;

/// How often to repaint while the status indicator is sampling.
///
/// 20 fps. The meter is 12 cells; ratatui's differential renderer writes only the cells that
/// changed, so a tick that moves nothing else costs twelve cell writes. §B12's *"streaming does
/// not repaint the screen"* is a property of the diff, not of the tick rate — but the tick rate is
/// what decides how often the diff is even asked, and 50 ms is under the threshold where a level
/// meter reads as stepping rather than moving.
const ANIMATION_TICK_MS: u64 = 50;

/// Poll timeout when nothing is animating and nothing is scheduled. The loop blocks here; a
/// terminal doing nothing should cost nothing.
const IDLE_TICK_MS: u64 = 1_000;

pub struct Options {
    /// Print startup timings and the resolved capability tiers, then leave.
    pub timing_probe: bool,
    /// Render raw-mode state, colour tier and a live keystroke counter in the titlebar.
    ///
    /// A running TUI's most important properties are invisible from outside the process, and a
    /// separate probe run measures a *different* process. This makes the session itself answer.
    pub diagnostic: bool,
    /// Explicit colour-depth override. §B2's fallback chain is a probe, and a silent probe is the
    /// mismatch-hiding default this project has shipped four bugs behind — so its answer is
    /// printed, and this is how it is overridden.
    pub color_depth: Option<String>,
    /// **Experimental.** Ask the terminal to adopt the mockup's ground via OSC 10/11.
    ///
    /// §B2 says *never hardcode a background fill*, and this does not: there is no per-cell `bg`
    /// anywhere, `no_background_fill.rs` still passes, and focus is still signalled by border and
    /// label colour alone. OSC 11 changes **the terminal's own default background** — so the rule
    /// *"the terminal's background is the background"* stays literally true; the terminal is simply
    /// being asked to use the one the design was drawn against (`#0f0e14`), with `#cdc9d6` as the
    /// default foreground that §B2's weight-1 `Color::Reset` then resolves to.
    ///
    /// It is off by default and reverted on exit (OSC 110/111), because changing a user's terminal
    /// colours is exactly the kind of thing a program should ask for rather than assume. Whether it
    /// becomes the default, stays a flag, or is replaced by a shipped colour scheme is a decision
    /// this does not pre-empt — it exists so the choice can be made by looking at it.
    pub ground: bool,
    /// Drive M1's scripted stub instead of the real engine.
    ///
    /// **`--tui` is live by default and this is the opt-out, not the other way round.** The
    /// producer in use is printed at startup and named in the status band: ADR-029's rule
    /// generalised — the active producer is announced, never silently chosen, because an
    /// unannounced fallback is indistinguishable from the failure mode it resembles.
    pub scripted: bool,
    /// Point the client at a non-default daemon port.
    ///
    /// **Isolation, not configuration.** Two sessions on one machine share `DEFAULT_DAEMON_PORT`,
    /// and the reflex when one is in the way — stopping it — takes the other session's daemon with
    /// it. A scratch port is how a clean daemon is obtained without touching anyone else's.
    pub daemon_port: Option<u16>,
    /// Enter raw mode and the alternate screen, draw one frame, then **panic on purpose**.
    ///
    /// The panic hook is the one piece of teardown that cannot be exercised by quitting normally,
    /// and it is also the one whose failure is most expensive: a panic inside the alternate screen
    /// with raw mode on and the mouse captured leaves a terminal that echoes nothing, selects
    /// nothing, and is still showing the alternate buffer — with the panic message invisible.
    ///
    /// This is a flag rather than a key so that nothing on the interactive surface can crash the
    /// application. It exists to be run, once, and to have its aftermath looked at.
    pub panic_probe: bool,
}

pub fn run(opts: Options) -> io::Result<()> {
    let clock = Clock::real();

    let theme = match Theme::resolve(|k| std::env::var(k).ok(), opts.color_depth.as_deref()) {
        Ok(t) => t,
        Err(e) => {
            // A load-time refusal, not a fall-back to the default accent. See theme.rs.
            eprintln!("error: {e}");
            std::process::exit(2);
        }
    };

    // **M2 C2d's deliverable: the TUI drives the real engine.** `--scripted` keeps M1's stub for
    // the interaction demo. Whichever is live is announced rather than inferred.
    if opts.scripted {
        let mut session = marlowe_stub::Session::new();
        return run_with(&mut session, opts, theme, clock);
    }
    let port = opts.daemon_port.unwrap_or(marlowe_daemon::DEFAULT_DAEMON_PORT);
    ensure_daemon(port);
    let mut session = marlowe_daemon::LiveSession::connect_on("tui", port);
    if !session.is_connected() {
        // Not fatal. Invariant 4: degrade visibly and name the remedy. The band says the same
        // thing, so this line is for the case where the frame never appears at all.
        eprintln!("marlowe: no daemon answered; the band will say so. Start one with `marlowe --serve`.");
    }
    run_with(&mut session, opts, theme, clock)
}

/// Start a daemon if none is listening. **§5's zero-config first run**: the user types `marlowe`
/// (or clicks the shortcut) and it works.
///
/// **Announced, never silent** — a process appearing on a machine without the user being told is
/// exactly what a well-behaved tool does not do. It is spawned DETACHED rather than run in-process
/// because invariant 6 is the whole reason for the split: a daemon inside the TUI would die with
/// the terminal, which is the thing §6 exists to prevent.
fn ensure_daemon(port: u16) {
    let client = marlowe_daemon::Client::new("tui").with_port(port);
    if client.daemon_is_up() {
        return;
    }
    let Ok(exe) = std::env::current_exe() else { return };
    let cwd = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
    eprintln!("marlowe: no daemon running — starting one. It outlives this window (invariant 6).");
    let mut cmd = std::process::Command::new(exe);
    cmd.arg("--serve").arg("--workspace").arg(&cwd);
    if port != marlowe_daemon::DEFAULT_DAEMON_PORT {
        cmd.arg("--daemon-port").arg(port.to_string());
    }
    cmd.stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());

    // **The daemon must not inherit this console, and nulling stdio is not enough.**
    //
    // Found by running it: `--timing-probe` returned in 56 ms and the shell hung anyway. A child
    // process on Windows inherits the parent's console handle, so a daemon that runs forever holds
    // the console open forever — the pipeline never sees end-of-output, and a terminal, a shell
    // pipeline or a double-clicked shortcut all appear to hang. Nothing on the Marlowe side is
    // wrong at that point; the process that finished simply cannot say so.
    //
    // DETACHED_PROCESS (0x8) gives the daemon no console at all, which is what a daemon should
    // have. CREATE_NEW_PROCESS_GROUP (0x200) keeps a Ctrl-C in the launching terminal from
    // reaching it — invariant 6 says the run outlives the client, and it would not survive
    // inheriting the client's interrupt.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const DETACHED_PROCESS: u32 = 0x0000_0008;
        const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
        cmd.creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP);
    }

    let spawned = cmd.spawn();
    if spawned.is_err() {
        eprintln!("marlowe: could not start one; the band will say so.");
        return;
    }
    // Wait for the socket rather than sleeping a fixed amount. §B13 budgets 150 ms to first frame
    // and a fixed sleep would spend it whether or not it was needed.
    for _ in 0..40 {
        // LOOP-EXEMPT: waiting on a socket to come up, not a driving loop.
        if client.daemon_is_up() {
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(25));
    }
    eprintln!("marlowe: the daemon did not answer in time; the band will say so.");
}

fn run_with(
    session: &mut impl Produce,
    opts: Options,
    theme: Theme,
    clock: Clock,
) -> io::Result<()> {
    let mut app = match App::new(session.view().clone()) {
        Ok(a) => a,
        Err(conflict) => {
            // §B2's contract, enforced before the first frame. A duplicate hotkey means one
            // region's bottom border is lying about how to reach it.
            eprintln!("error: {conflict}");
            std::process::exit(2);
        }
    };

    // §B11: request the minimum on start. Terminals that honour CSI 8 comply; those that do not
    // are handled by the refusal below, which is the same path a user who declines a resize takes.
    let mut out = io::stdout();
    write!(out, "\x1b[8;{MIN_ROWS};{MIN_COLS}t")?;
    out.flush()?;

    let (cols, rows) = terminal::size()?;
    if cols < MIN_COLS || rows < MIN_ROWS {
        // **Never a degraded grid.** One line naming current and required size, and the offer.
        // A narrow variant was designed and rejected: it cost the borders, which cost the region
        // contract, which is the entire design.
        eprintln!(
            "marlowe needs {MIN_COLS}x{MIN_ROWS}; this terminal is {cols}x{rows}.\n\
             Resize it, or run `marlowe --classic` — same commands, no grid."
        );
        std::process::exit(1);
    }

    // **The panic hook is installed BEFORE raw mode is entered, and it is not optional.**
    //
    // A panic inside the alternate screen with raw mode on leaves the user with a terminal that
    // echoes nothing, has no line discipline, and is still showing the alternate buffer — and the
    // panic message itself is invisible or mangled. `reset` is then the only way out.
    //
    // The hook restores the terminal FIRST and prints SECOND, so the message lands on a working
    // terminal. It chains to the previous hook rather than replacing it, so the backtrace survives.
    install_panic_hook();

    // An explicit `--color-depth` is an explicit request, and it outranks `NO_COLOR`.
    //
    // Honouring `NO_COLOR` by default is correct — it is a real convention and a user who set it
    // meant it. But a user who *also* passes `--color-depth truecolor` has asked twice, and
    // silently handing them a white screen would be the mismatch-hiding default again. So: the flag
    // forces colour on, and either way the startup record below says which happened.
    if theme.no_color().is_some() && opts.color_depth.is_some() {
        crossterm::style::force_color_output(true);
    }

    terminal::enable_raw_mode()?;
    execute!(
        io::stdout(),
        terminal::EnterAlternateScreen,
        // §B10 amended (2026-08-08): the mouse is captured. Keyboard remains the primary and
        // complete path — every action is still reachable by key, and `b13_keyboard.rs` proves it
        // from the default focus. What capture buys is that drag-select stops belonging to the
        // terminal, which is the single thing that made a running application read as a printout.
        EnableMouseCapture,
        // Focus reporting is what lets hover clear when the pointer leaves the terminal entirely.
        event::EnableFocusChange,
        crossterm::cursor::Hide
    )?;

    if opts.ground {
        // OSC 11 = default background, OSC 10 = default foreground. The mockup's `--bg` and
        // `--text`. BEL-terminated, which every emulator accepts; ST-terminated is stricter but
        // less widely handled.
        let mut o = io::stdout();
        write!(o, "\x1b]11;#0f0e14\x07\x1b]10;#cdc9d6\x07")?;
        o.flush()?;
    }

    // Read back rather than assume. `enable_raw_mode` returning `Ok` means the call succeeded, not
    // that the mode is in force — under a redirected stdout or a console host that does not
    // support it, those are different things, and the difference is invisible until a keystroke
    // fails to arrive.
    let raw_mode = terminal::is_raw_mode_enabled().unwrap_or(false);

    if opts.diagnostic {
        app.diagnostic = Some(format!(
            "raw={} alt=on mouse=captured tier={} {}",
            if raw_mode { "ON" } else { "OFF" },
            theme.depth().as_str(),
            // NOT `depth_reason` alone. A tier printed next to a screen with no colour on it is a
            // record that agrees with the code and disagrees with the user.
            match theme.no_color() {
                Some(v) if opts.color_depth.is_some() => format!("NO_COLOR={v} OVERRIDDEN"),
                Some(v) => format!("NO_COLOR={v} SUPPRESSES ALL COLOUR"),
                None => theme.depth_reason().to_string(),
            },
        ));
    }

    let mut term = Terminal::new(CrosstermBackend::new(io::stdout()))?;
    let result = event_loop(&mut term, session, &mut app, &theme, &clock, &opts);

    if opts.ground {
        // OSC 110/111 reset fore/background to the terminal's configured defaults. A program that
        // changes a user's terminal colours and does not change them back is a program they will
        // not run twice.
        let mut o = io::stdout();
        write!(o, "\x1b]111\x07\x1b]110\x07")?;
        o.flush()?;
    }

    execute!(
        io::stdout(),
        crossterm::cursor::Show,
        DisableMouseCapture,
        event::DisableFocusChange,
        terminal::LeaveAlternateScreen
    )?;
    terminal::disable_raw_mode()?;

    if let Some((first_frame_ms, interactive_ms)) = result? {
        println!("raw_mode                {}", on_off(raw_mode));
        println!("alternate_screen        on");
        // §B10: *keyboard first; mouse is a bonus.* Not capturing the mouse is a decision, not an
        // omission: with mouse reporting off, the terminal's own selection and copy keep working,
        // which is what a user expects of a program they may want to copy a line out of. The cost
        // is that click-to-focus does not exist, and every path is therefore reachable by key.
        // §B10 amended 2026-08-08: captured. Keyboard is still the primary and complete path —
        // every action remains reachable by key — but selection no longer belongs to the terminal.
        println!("mouse_capture           on (§B10 as amended; keyboard remains complete)");
        println!("color_depth             {}", theme.depth().as_str());
        println!("color_depth_reason      {}", theme.depth_reason());
        println!("color_emitted           {}", theme.emission_report());
        println!("accent                  {}", theme.accent_source());
        println!("terminal                {cols}x{rows}");
        println!("time_to_first_frame_ms  {first_frame_ms}");
        println!("time_to_interactive_ms  {interactive_ms}");
        println!("target_first_frame_ms   150   (K4)");
        println!("target_interactive_ms   300");
    }
    Ok(())
}

fn on_off(b: bool) -> &'static str {
    if b {
        "on"
    } else {
        "OFF — keystrokes will not reach the event loop"
    }
}

/// Restore the terminal on the way out of a panic, then let the default hook print.
fn install_panic_hook() {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        // Mouse capture is released here too. A panic that leaves capture on hands the user a
        // terminal whose mouse no longer selects text and no longer scrolls — with no application
        // running to explain why. It is the same class of damage as leaving raw mode on.
        let _ = execute!(
            io::stdout(),
            crossterm::cursor::Show,
            DisableMouseCapture,
            event::DisableFocusChange,
            terminal::LeaveAlternateScreen
        );
        let _ = terminal::disable_raw_mode();
        previous(info);
    }));
}

/// Returns `Some((first_frame_ms, interactive_ms))` under `--timing-probe`.
fn event_loop(
    term: &mut Terminal<CrosstermBackend<io::Stdout>>,
    session: &mut impl Produce,
    app: &mut App,
    theme: &Theme,
    clock: &Clock,
    opts: &Options,
) -> io::Result<Option<(u64, u64)>> {
    advance(session, app, clock.now_ms());
    term.draw(|f| render::draw(app, theme, f.area(), f.buffer_mut()))?;
    let first_frame_ms = clock.now_ms();

    // The window title, kept current with session state via OSC 0. Tracked rather than re-emitted
    // every frame: at the animation tick that would be twenty title writes a second, and some
    // terminals flash the taskbar entry on each one.
    let mut title = String::new();

    // "Interactive" is the first moment a keystroke would be accepted, which is the first
    // completed poll — not the moment the loop is entered. Measuring the latter would report a
    // number that is true of the code and false of the user.
    event::poll(std::time::Duration::from_millis(0))?;
    let interactive_ms = clock.now_ms();

    if opts.timing_probe {
        return Ok(Some((first_frame_ms, interactive_ms)));
    }

    if opts.panic_probe {
        // Deliberate. The hook installed before raw mode must restore the terminal and then print,
        // in that order, or the message lands on a terminal that cannot show it.
        panic!("--panic-probe: this panic is intentional; the terminal should be usable below");
    }

    loop {
        let now = clock.now_ms();
        advance(session, app, now);

        let timeout = if app.view().status.state.samples_amplitude() {
            ANIMATION_TICK_MS
        } else {
            session
                .next_beat_in(now)
                .unwrap_or(IDLE_TICK_MS)
                .clamp(1, IDLE_TICK_MS)
        };

        if event::poll(std::time::Duration::from_millis(timeout))? {
            match event::read()? {
                Event::Key(k) if k.kind == KeyEventKind::Press => {
                    if let Some(key) = translate(k.code, k.modifiers) {
                        if app.on_key(key) == Action::Quit {
                            return Ok(None);
                        }
                    }
                }
                // §B10 as amended: the mouse is captured, so these events arrive here instead of
                // being handled by the terminal. Every one of them routes through the same
                // dispatch the keyboard uses — the mouse adds no state and no second code path,
                // which is what keeps "reachable by keyboard alone" true rather than merely
                // asserted.
                Event::Mouse(m) => {
                    app.mouse_seen += 1;
                    let chrome = render::layout(term.size()?.into());
                    let hit = region_at(&chrome, m.column, m.row);
                    // Every motion event updates hover, including the ones that leave a region for
                    // dead chrome — that is the half that makes a hover clear rather than stick.
                    app.set_hover(hit);
                    // And the option under the pointer inside an open dropdown, which is not a
                    // region and so cannot ride on `hover`.
                    app.hover_option = app
                        .open_picker()
                        .and_then(|(_, i, n)| option_at(&chrome, i, n, term.size().ok()?, m));
                    // And the inspector tab, which is not a region either.
                    app.hover_tab = tab_at(&chrome, m.column, m.row);
                    match m.kind {
                        MouseEventKind::Down(MouseButton::Left) => {
                            // An open dropdown takes the click first, exactly as it takes the
                            // arrows and Enter from the keyboard (§B10, dispatch step 3).
                            if let Some((id, i, n)) = app.open_picker() {
                                let size = term.size()?;
                                app.focus = id;
                                if let Some(opt) = option_at(&chrome, i, n, size, m) {
                                    app.choose_option(opt);
                                } else {
                                    // Outside the popup: dismiss without choosing.
                                    app.on_key(Key::Esc);
                                    // **And if the click landed on ANOTHER control cell, open that
                                    // one in the same click.** Requiring a first click to dismiss
                                    // and a second to open is the behaviour of a modal nobody
                                    // asked for; every real menu bar switches on one click.
                                    if let Some(other) = hit {
                                        if other != id && App::STRIP.contains(&other) {
                                            app.focus = other;
                                            app.open_focused_picker();
                                        }
                                    }
                                }
                            } else if let Some(tab) = tab_at(&chrome, m.column, m.row) {
                                // Tabs are selectable by pointer as well as by digit. Routed
                                // through the same key the tab bar advertises, so there is one
                                // switch path rather than two.
                                app.on_key(Key::Char(tab.digit()));
                            } else if let Some(id) = hit {
                                app.focus = id;
                                // Clicking a control cell opens it. Focusing without opening is
                                // the state a user reads as "the click did nothing".
                                app.open_focused_picker();
                            }
                        }
                        MouseEventKind::ScrollUp | MouseEventKind::ScrollDown => {
                            // Focus follows the wheel, then the ordinary arrow-key path does the
                            // work. Scrolling a region you are not focused on would put the
                            // scrollbar and the focus ring in disagreement.
                            // The inspector is not a region — it has no border of its own (§B2) —
                            // so the wheel over it moves the pane directly rather than through a
                            // focus change.
                            let over_inspector = m.column >= chrome.inspector.x
                                && m.column < chrome.inspector.x + chrome.inspector.width
                                && m.row >= chrome.inspector.y
                                && m.row < chrome.inspector.y + chrome.inspector.height;
                            if over_inspector && hit.is_none() {
                                let max = app.inspector_scroll_max.get();
                                app.inspector_scroll = if m.kind == MouseEventKind::ScrollUp {
                                    app.inspector_scroll.saturating_sub(1)
                                } else {
                                    (app.inspector_scroll + 1).min(max)
                                };
                                advance(session, app, clock.now_ms());
                                term.draw(|f| {
                                    render::draw(app, theme, f.area(), f.buffer_mut())
                                })?;
                                continue;
                            }
                            if let Some(id) = hit {
                                app.focus = id;
                            }
                            let key = if m.kind == MouseEventKind::ScrollUp {
                                Key::Up
                            } else {
                                Key::Down
                            };
                            app.on_key(key);
                        }
                        _ => {}
                    }
                }
                // The pointer leaving the window delivers no motion event, so without this the
                // highlight would stay lit under a pointer that is now in another application.
                // A stuck hover is worse than no hover.
                Event::FocusLost => {
                    app.set_hover(None);
                }
                Event::Resize(_, _) => {
                    // ratatui reflows on the next draw. Nothing to recompute here, which is the
                    // point of layout being a pure function of the area.
                }
                _ => {}
            }
        }

        // §B10's copy. The payload was built by the surface; writing it needs stdout, which is
        // this file's job. OSC 52 goes straight out rather than through ratatui's buffer — it is
        // not a cell, and queueing it would tie a clipboard write to a repaint.
        if let Some(text) = app.pending_copy.take() {
            let mut out = io::stdout();
            write!(out, "{}", marlowe_surface::clipboard::osc52(&text))?;
            out.flush()?;
        }

        let next_title = app.window_title();
        if next_title != title {
            title = next_title;
            let mut out = io::stdout();
            write!(out, "\x1b]0;{title}\x07")?;
            out.flush()?;
        }

        advance(session, app, clock.now_ms());
        term.draw(|f| render::draw(app, theme, f.area(), f.buffer_mut()))?;
    }
}

/// One turn of the crank: hand the surface's requests to the producer, advance it, republish.
///
/// **This function is the client/daemon boundary, in miniature.** Every change the user causes
/// goes out as an `Intent` and comes back as a whole new view; nothing on the surface's side is
/// edited in place. A refusal is printed rather than dropped -- a producer that silently ignored
/// an intent would make a working build and a broken one look identical.
fn advance(session: &mut impl Produce, app: &mut App, now_ms: u64) {
    for intent in app.drain_intents() {
        if let Err(e) = session.apply(intent) {
            // Shown in the conversation and kept there. A refusal that vanished on the next
            // keystroke would leave a blocked action with no explanation.
            app.refused(&e);
        }
    }
    session.tick(now_ms);
    app.update(session.view().clone());
}

/// Which inspector tab a pointer is over. Geometry from `render::tab_rects`, never recomputed.
fn tab_at(chrome: &render::Chrome, col: u16, row: u16) -> Option<marlowe_view::Tab> {
    render::tab_rects(chrome.tab_bar)
        .into_iter()
        .find(|(_, r)| col >= r.x && col < r.x + r.width && row == r.y)
        .map(|(t, _)| t)
}

/// Which dropdown option a pointer is over, or `None` if it is not inside the popup's option rows.
///
/// Shared by hover and click so the highlighted row and the chosen row can never be different ones
/// — the failure that reads as flakiness rather than as a bug. The popup carries a border, so the
/// first option is one row inside its own top edge.
fn option_at(
    chrome: &render::Chrome,
    strip_index: usize,
    options: usize,
    size: ratatui::layout::Size,
    m: crossterm::event::MouseEvent,
) -> Option<usize> {
    let popup = render::dropdown_rect(chrome.control[strip_index], options, size.height);
    let inside = m.column >= popup.x
        && m.column < popup.x + popup.width
        && m.row > popup.y
        && m.row < popup.y + popup.height.saturating_sub(1);
    inside.then(|| (m.row - popup.y - 1) as usize)
}

/// Which region contains a screen cell, or `None` for the chrome between them.
///
/// Deliberately does **not** resolve inspector items: a click lands on the inspector, and the item
/// within it is chosen by key. Hit-testing individual items would be the first place the mouse grew
/// a capability the keyboard did not have, and §B10 keeps them at parity.
fn region_at(chrome: &render::Chrome, col: u16, row: u16) -> Option<marlowe_surface::region::RegionId> {
    use marlowe_surface::region::RegionId;
    let hit = |r: ratatui::layout::Rect| {
        col >= r.x && col < r.x + r.width && row >= r.y && row < r.y + r.height
    };
    for (i, id) in [
        RegionId::Model,
        RegionId::Profile,
        RegionId::Session,
        RegionId::Workspace,
        RegionId::Autonomy,
    ]
    .into_iter()
    .enumerate()
    {
        if hit(chrome.control[i]) {
            return Some(id);
        }
    }
    if hit(chrome.status) {
        return Some(RegionId::Status);
    }
    if hit(chrome.conversation) {
        return Some(RegionId::Conversation);
    }
    if hit(chrome.message) {
        return Some(RegionId::Message);
    }
    None
}

/// crossterm → the surface's key vocabulary.
///
/// The translation lives here so `marlowe-surface::app` never imports crossterm, and every
/// keyboard property §B13 asks for is testable without a terminal.
fn translate(code: KeyCode, mods: KeyModifiers) -> Option<Key> {
    let ctrl = mods.contains(KeyModifiers::CONTROL);
    let shift = mods.contains(KeyModifiers::SHIFT);
    Some(match code {
        KeyCode::Char(c) if ctrl => Key::Ctrl(c),
        KeyCode::Char(c) => Key::Char(c),
        // §B10: multiline by default — Shift-Enter is a newline, Enter sends. Terminals that do
        // not distinguish them send plain Enter, which sends; that is a terminal limitation and
        // is not worked around by making Enter ambiguous.
        KeyCode::Enter if shift => Key::ShiftEnter,
        KeyCode::Enter => Key::Enter,
        KeyCode::Tab => Key::Tab,
        KeyCode::BackTab => Key::BackTab,
        KeyCode::Backspace => Key::Backspace,
        KeyCode::Up => Key::Up,
        KeyCode::Down => Key::Down,
        KeyCode::Left => Key::Left,
        KeyCode::Right => Key::Right,
        KeyCode::Esc => Key::Esc,
        _ => return None,
    })
}
