//! §B11's classic CLI. **The narrow, SSH, piped-stdin and no-TTY path.**
//!
//! > It is a readline REPL with **command parity, not layout parity** — every slash command, every
//! > session, every piece of data is reachable, rendered linearly. **It is not a lesser product;
//! > it is the same product without a grid.**
//!
//! Parity is structural, not a checklist: this dispatches through `crate::commands`, the same and
//! only dispatcher the TUI uses. A TUI-only command would have to be built by bypassing that
//! module, and `tests/command_parity.rs` names it if one is.
//!
//! *(v1 said "no TUI-only features". v2 amends that to no TUI-only **capabilities** — layout is
//! allowed to differ, because layout is what a grid buys.)*

use std::io::{BufRead, Write};

use marlowe_view::{ClockRead, Entry, Intent, Produce, SessionView, Tab, ToolLineState};

use crate::commands::{self, Outcome};

/// Run the REPL over any reader/writer, so a test can drive it without a terminal.
/// **The REPL is a driver, so it is handed a producer rather than making one.**
///
/// C2d: it used to call `Session::new()`, which put a concrete producer inside the render crate.
/// It now takes `&mut impl Produce`, so `marlowe-surface` can drive a producer without being able
/// to construct one -- the same property that keeps `App` honest, applied to the surface that has
/// no grid.
pub fn run(
    session: &mut impl Produce,
    input: impl BufRead,
    mut out: impl Write,
    clock: &impl ClockRead,
) -> std::io::Result<()> {
    let mut shown = 0usize;

    writeln!(
        out,
        "marlowe — classic. No grid, same commands. /help for the list."
    )?;
    drain(session, &mut out, &mut shown, clock)?;

    for line in input.lines() {
        let line = line?;
        let text = line.trim();
        if text.is_empty() {
            continue;
        }

        if let Some(rest) = text.strip_prefix('/') {
            let mut parts = rest.split_whitespace();
            let name = parts.next().unwrap_or("");
            let args: Vec<&str> = parts.collect();
            let outcome = commands::dispatch(session.view(), name, &args);
            // One renderer, both surfaces. §B11 is command parity, and parity of the WORDS is the
            // half a checklist would miss.
            let say = |out: &mut dyn Write, v: &SessionView, n: &marlowe_view::Notice| {
                for l in commands::render_notice(v, n) {
                    let _ = writeln!(out, "{l}");
                }
            };
            match outcome {
                Outcome::Quit => return Ok(()),
                Outcome::Say(n) => say(&mut out, session.view(), &n),
                Outcome::Diagnostic(lines) => {
                    for l in lines {
                        writeln!(out, "{l}")?;
                    }
                }
                // Same request path as the TUI. The producer acts; a refusal is printed by name
                // rather than swallowed, so the CLI cannot look like it worked.
                Outcome::Ask(intent) => {
                    if let Err(e) = session.apply(intent) {
                        say(&mut out, session.view(), &e.as_notice());
                    }
                    drain(session, &mut out, &mut shown, clock)?;
                }
                Outcome::Tab(tab, said) => {
                    // The same rule as the TUI (§B7): the region carries the data, the transcript
                    // carries the judgment. Without a grid they arrive one after the other rather
                    // than side by side — that is the layout half of "parity, not layout parity".
                    say(&mut out, session.view(), &said);
                    for l in commands::render_pane_linear(session.view(), tab) {
                        writeln!(out, "{l}")?;
                    }
                }
                Outcome::Rejected(r) => {
                    say(&mut out, session.view(), &marlowe_view::Notice::Refused(r))
                }
                Outcome::Unknown(name) => {
                    let nearest = commands::complete(&name).first().map(|c| c.name);
                    say(
                        &mut out,
                        session.view(),
                        &marlowe_view::Notice::Refused(marlowe_view::Refusal::UnknownCommand {
                            name: marlowe_view::Echo::new(name),
                            nearest,
                        }),
                    );
                }
            }
            shown = session.view().transcript.len();
            // A command can raise an approval too — `/state waiting` does. Surfacing it only on the
            // message path would let the classic CLI sit in `waiting` with nothing on screen to
            // answer, which is a capability gap, and §B14 forbids TUI-only capabilities.
            print_approval(session.view(), &mut out)?;
            continue;
        }

        if let Some(cmd) = text.strip_prefix('!') {
            writeln!(
                out,
                "Shell runs through the approval path, and that path lands in M2. {cmd:?} was not run."
            )?;
            continue;
        }

        // Asked, not assigned -- exactly as the TUI does it.
        if let Err(e) = session.apply(Intent::Send(text.to_string())) {
            let n = e.as_notice();
            for l in commands::render_notice(session.view(), &n) {
                writeln!(out, "{l}")?;
            }
        }
        drain(session, &mut out, &mut shown, clock)?;

        print_approval(session.view(), &mut out)?;
    }
    Ok(())
}

/// §B9 reaches the classic CLI too — approvals are a **capability**, and §B14 forbids TUI-only
/// capabilities. Linearly it is a prompt rather than an overlay, which is layout, not capability.
///
/// **States blast radius, not the command.** `BlastRadius` has no field for the command string, so
/// this cannot print one even by accident.
fn print_approval(view: &SessionView, out: &mut impl Write) -> std::io::Result<()> {
    let Some(radius) = &view.approval else {
        return Ok(());
    };
    writeln!(out, "\n  approval — {}", radius.headline())?;
    writeln!(out, "  {}", radius.consequence())?;
    writeln!(out, "  {}", radius.why())?;
    let keys: Vec<String> = radius
        .keys()
        .iter()
        .map(|(k, what)| {
            let key = match k {
                '\n' => "enter".to_string(),
                '\u{1b}' => "esc".to_string(),
                c => c.to_string(),
            };
            format!("{key} {what}")
        })
        .collect();
    writeln!(out, "  {}\n", keys.join(" · "))
}

/// Play out every pending beat and print what appeared.
///
/// The TUI animates live tool lines in place; without a grid there is nowhere to animate, so the
/// linear surface prints each line once it has settled. Same data, same order, no cursor tricks.
fn drain(
    session: &mut impl Produce,
    out: &mut impl Write,
    shown: &mut usize,
    clock: &impl ClockRead,
) -> std::io::Result<()> {
    let start = clock.now_ms();
    let mut t = start;
    loop {
        session.tick(t);
        print_new(session.view(), out, shown)?;
        match session.next_beat_in(t) {
            Some(dt) => t += dt.max(1),
            None => break,
        }
        // The scripted beats are bounded; this only guards against a future script that is not.
        if t - start > 60_000 {
            break;
        }
    }
    session.tick(t);
    print_new(session.view(), out, shown)
}

fn print_new(view: &SessionView, out: &mut impl Write, shown: &mut usize) -> std::io::Result<()> {
    while *shown < view.transcript.len() {
        match &view.transcript[*shown] {
            Entry::User(t) => writeln!(out, "> {t}")?,
            Entry::Said(t) => match t {
                // The classic surface renders both halves identically -- a user must not see a
                // seam between the model talking and the harness talking.
                marlowe_view::Speech::Model(text) => writeln!(out, "{text}")?,
                marlowe_view::Speech::Harness(n) => {
                    for line in crate::commands::render_notice(view, n) {
                        writeln!(out, "{line}")?;
                    }
                }
            },
            Entry::Compacted { turns } => writeln!(out, "-- compacted · {turns} turns → summary")?,
            // Linear surfaces have nowhere to collapse to, so the classic CLI reports the shape
            // rather than the content: it is progress, not an answer.
            Entry::Reasoning { text, done } => writeln!(
                out,
                "  ⋯ thinking   {} chars{}",
                text.len(),
                if *done { "" } else { " …" }
            )?,
            Entry::Tools(calls) => {
                for c in calls {
                    let target = if c.collapsed.is_empty() {
                        c.target.clone()
                    } else {
                        format!("{} files", c.collapsed.len() + 1)
                    };
                    let right = match &c.state {
                        ToolLineState::Running { elapsed_ms } => format!("{elapsed_ms} ms"),
                        ToolLineState::Ok(s) | ToolLineState::Failed(s) => s.render(),
                    };
                    writeln!(out, "  ... {:<9} {:<40} {}", c.verb, target, right)?;
                    if c.expanded {
                        for t in &c.collapsed {
                            writeln!(out, "        {t}")?;
                        }
                        if let ToolLineState::Ok(s) | ToolLineState::Failed(s) = &c.state {
                            if let Some(d) = &s.detail {
                                for l in d.lines() {
                                    writeln!(out, "        {l}")?;
                                }
                            }
                        }
                    }
                }
            }
        }
        *shown += 1;
    }
    out.flush()
}

/// Print one pane linearly. Used by `--classic --print <tab>` for a piped, no-TTY read.
pub fn print_pane(view: &SessionView, tab: Tab, mut out: impl Write) -> std::io::Result<()> {
    for l in commands::render_pane_linear(view, tab) {
        writeln!(out, "{l}")?;
    }
    Ok(())
}
