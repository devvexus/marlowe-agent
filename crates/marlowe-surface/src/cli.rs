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

use marlowe_stub::{Clock, Entry, Session, Tab, ToolLineState};

use crate::commands::{self, Outcome};

/// Run the REPL over any reader/writer, so a test can drive it without a terminal.
pub fn run(input: impl BufRead, mut out: impl Write, clock: &Clock) -> std::io::Result<()> {
    let mut session = Session::new();
    let mut shown = 0usize;

    writeln!(
        out,
        "marlowe — classic. No grid, same commands. /help for the list."
    )?;
    drain(&mut session, &mut out, &mut shown, clock)?;

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
            match commands::dispatch(&mut session, name, &args, clock.now_ms()) {
                Outcome::Quit => return Ok(()),
                Outcome::Lines(lines) => {
                    for l in lines {
                        writeln!(out, "{l}")?;
                    }
                }
                Outcome::Tab(tab, said) => {
                    // The same rule as the TUI (§B7): the region carries the data, the transcript
                    // carries the judgment. Without a grid they arrive one after the other rather
                    // than side by side — that is the layout half of "parity, not layout parity".
                    writeln!(out, "{said}")?;
                    for l in commands::render_pane_linear(&session, tab) {
                        writeln!(out, "{l}")?;
                    }
                }
                Outcome::Rejected(why) => writeln!(out, "{why}")?,
                Outcome::Unknown(name) => {
                    let near = commands::complete(&name);
                    match near.first() {
                        Some(c) => writeln!(out, "No /{name}. Closest is /{}.", c.name)?,
                        None => writeln!(out, "No /{name}. /help lists what there is.")?,
                    }
                }
            }
            shown = session.transcript.len();
            // A command can raise an approval too — `/state waiting` does. Surfacing it only on the
            // message path would let the classic CLI sit in `waiting` with nothing on screen to
            // answer, which is a capability gap, and §B14 forbids TUI-only capabilities.
            print_approval(&session, &mut out)?;
            continue;
        }

        if let Some(cmd) = text.strip_prefix('!') {
            writeln!(
                out,
                "Shell runs through the approval path, and that path lands in M2. {cmd:?} was not run."
            )?;
            continue;
        }

        session.submit(text, clock.now_ms());
        drain(&mut session, &mut out, &mut shown, clock)?;

        print_approval(&session, &mut out)?;
    }
    Ok(())
}

/// §B9 reaches the classic CLI too — approvals are a **capability**, and §B14 forbids TUI-only
/// capabilities. Linearly it is a prompt rather than an overlay, which is layout, not capability.
///
/// **States blast radius, not the command.** `BlastRadius` has no field for the command string, so
/// this cannot print one even by accident.
fn print_approval(session: &Session, out: &mut impl Write) -> std::io::Result<()> {
    let Some(radius) = &session.approval else {
        return Ok(());
    };
    writeln!(out, "\n  approval — {}", radius.headline)?;
    writeln!(out, "  {}", radius.consequence)?;
    writeln!(out, "  {}", radius.why)?;
    let keys: Vec<String> = radius
        .options
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
    session: &mut Session,
    out: &mut impl Write,
    shown: &mut usize,
    clock: &Clock,
) -> std::io::Result<()> {
    let start = clock.now_ms();
    let mut t = start;
    loop {
        session.tick(t);
        print_new(session, out, shown)?;
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
    print_new(session, out, shown)
}

fn print_new(session: &Session, out: &mut impl Write, shown: &mut usize) -> std::io::Result<()> {
    while *shown < session.transcript.len() {
        match &session.transcript[*shown] {
            Entry::User(t) => writeln!(out, "> {t}")?,
            Entry::Said(t) => writeln!(out, "{t}")?,
            Entry::Compacted { turns } => writeln!(out, "-- compacted · {turns} turns → summary")?,
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
pub fn print_pane(session: &Session, tab: Tab, mut out: impl Write) -> std::io::Result<()> {
    for l in commands::render_pane_linear(session, tab) {
        writeln!(out, "{l}")?;
    }
    Ok(())
}
