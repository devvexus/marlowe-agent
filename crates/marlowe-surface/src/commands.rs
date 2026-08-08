//! **One command registry, dispatched by both surfaces.**
//!
//! §B11: the classic CLI has *command parity, not layout parity* — every slash command, every
//! session, every piece of data is reachable, rendered linearly. §B13 asks for 100%.
//!
//! A checklist would rot on the first command somebody added to the TUI. So parity is not checked,
//! it is **structural**: this is the only dispatcher, both surfaces call it, and
//! `tests/command_parity.rs` asserts that every entry in [`REGISTRY`] resolves in both. A TUI-only
//! command would have to be built by bypassing this module, which the parity test names.
//!
//! *(v1 said "no TUI-only features". v2 §B11 amends that to no TUI-only **capabilities** — layout
//! is allowed to differ, because layout is what a grid buys.)*

use marlowe_stub::{Entry, Session, StatusState, Tab, Tone};

/// One command, and enough about it to autocomplete inline with a description (§B10).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Command {
    pub name: &'static str,
    pub args: &'static str,
    pub description: &'static str,
}

/// Every command M1 defines.
///
/// **Parity is measured against this list**, not against a claim about a command set that does not
/// exist yet. M2 adds commands; both surfaces get them at once because both read this array.
pub const REGISTRY: &[Command] = &[
    Command { name: "runs",     args: "",         description: "active background work — status, elapsed, spend, depth" },
    Command { name: "schedule", args: "",         description: "today's events, what Marlowe noticed, commitments due" },
    Command { name: "sessions", args: "",         description: "history, searchable by content" },
    Command { name: "skills",   args: "",         description: "installed skills by domain, and the exposed-tool budget" },
    Command { name: "trust",    args: "",         description: "the trust ledger — classes, tiers, agreement, ceilings" },
    Command { name: "status",   args: "",         description: "model, context, spend, connections, degradation" },
    Command { name: "state",    args: "<name>",   description: "drive the status band to a state (listening…idle)" },
    Command { name: "model",    args: "[name]",   description: "show or switch the routed model" },
    Command { name: "profile",  args: "[name]",   description: "show or switch profile — work / personal" },
    Command { name: "session",  args: "[name]",   description: "show or switch session" },
    Command { name: "workspace", args: "[path]",  description: "show or switch the working directory" },
    Command { name: "autonomy", args: "[tier]",   description: "observe / suggest / draft / confirm / act" },
    Command { name: "undo",     args: "[n]",      description: "soft-delete the last n turns" },
    Command { name: "compact",  args: "",         description: "compact the session — announces inline, does not interrupt" },
    Command { name: "keys",     args: "",         description: "every key binding, and the region each one reaches" },
    Command { name: "doctor",   args: "",         description: "terminal capability check, including the braille glyph row" },
    Command { name: "help",     args: "",         description: "this list" },
    Command { name: "quit",     args: "",         description: "leave. Runs are daemon-owned and survive (invariant 6)" },
];

/// What a command did. The TUI and the CLI render these differently — that is the layout half of
/// "command parity, not layout parity".
#[derive(Debug, Clone, PartialEq)]
pub enum Outcome {
    /// Lines to show. In the TUI they land in the transcript; in the CLI they print.
    Lines(Vec<String>),
    /// The inspector switched tab, and the transcript says only what a colleague would say out
    /// loud (§B7). Both strings travel together so neither surface can drop the other half.
    Tab(Tab, String),
    Quit,
    /// The command exists but the argument did not. Never a silent no-op.
    Rejected(String),
    Unknown(String),
}

/// Resolve a name to its registry entry.
pub fn lookup(name: &str) -> Option<&'static Command> {
    REGISTRY.iter().find(|c| c.name == name)
}

/// Inline autocomplete (§B10): every command whose name starts with the prefix, with its
/// description.
pub fn complete(prefix: &str) -> Vec<&'static Command> {
    REGISTRY
        .iter()
        .filter(|c| c.name.starts_with(prefix))
        .collect()
}

/// **The only dispatcher.** Both surfaces call this and neither has a second path.
pub fn dispatch(session: &mut Session, name: &str, args: &[&str], now_ms: u64) -> Outcome {
    if lookup(name).is_none() {
        return Outcome::Unknown(name.to_string());
    }
    match name {
        "runs" => Outcome::Tab(
            Tab::Runs,
            "Two running. The deep dive is at $1.20 of its $3 ceiling.".into(),
        ),
        "schedule" => Outcome::Tab(
            Tab::Schedule,
            "Three things need you — the vendor call at eleven is the one to look at.".into(),
        ),
        "sessions" => Outcome::Tab(Tab::Sessions, deferred_line("Sessions")),
        "skills" => Outcome::Tab(Tab::Skills, deferred_line("Skills")),
        "trust" => Outcome::Tab(Tab::Trust, deferred_line("Trust")),
        "status" => Outcome::Tab(Tab::Status, deferred_line("Status")),

        "state" => match args.first().map(|s| parse_state(s)) {
            Some(Some(state)) => {
                session.force_state(state, now_ms);
                Outcome::Lines(vec![format!("status: {}", state.name())])
            }
            _ => Outcome::Rejected(
                "usage: /state listening|thinking|speaking|writing|running|waiting|idle".into(),
            ),
        },

        "model" => picker(session, name, args),
        "profile" => picker(session, name, args),
        "session" => picker(session, name, args),
        "workspace" => picker(session, name, args),
        "autonomy" => picker(session, name, args),

        "undo" => {
            let n: usize = args.first().and_then(|s| s.parse().ok()).unwrap_or(1);
            let removed = undo(session, n);
            Outcome::Lines(vec![format!(
                "undone: {removed} turn{}",
                if removed == 1 { "" } else { "s" }
            )])
        }

        "compact" => {
            let turns = session.pager.turn.max(1);
            session.transcript.push(Entry::Compacted { turns });
            session.pager.compacted += turns;
            session.pager.lineage += 1;
            session.ambient.fill_pct = 12;
            Outcome::Lines(Vec::new())
        }

        "keys" => Outcome::Lines(key_help(session)),
        "doctor" => Outcome::Lines(crate::doctor::report(session)),
        "help" => Outcome::Lines(help()),
        "quit" => Outcome::Quit,

        _ => Outcome::Unknown(name.to_string()),
    }
}

/// A tab that M1 does not fill still answers its command — and says so rather than printing an
/// empty section. Silence would read as "you have no skills", which is a claim, and a false one.
fn deferred_line(tab: &str) -> String {
    format!("{tab} isn't built yet — M2, against real data. The tab is there so the bar isn't lying.")
}

fn picker(session: &mut Session, which: &str, args: &[&str]) -> Outcome {
    let p = match which {
        "model" => &mut session.control.model,
        "profile" => &mut session.control.profile,
        "session" => &mut session.control.session,
        "workspace" => &mut session.control.workspace,
        "autonomy" => &mut session.control.autonomy,
        _ => unreachable!("picker() is only called for the five control-strip regions"),
    };
    match args.first() {
        None => Outcome::Lines(vec![format!(
            "{which}: {}   ({})",
            p.value(),
            p.options.join(" · ")
        )]),
        Some(want) => match p.options.iter().position(|o| o == want) {
            Some(i) => {
                p.selected = i;
                Outcome::Lines(vec![format!("{which}: {}", p.value())])
            }
            None => Outcome::Rejected(format!(
                "{which} has no option {want:?}. One of: {}",
                p.options.join(", ")
            )),
        },
    }
}

/// §B10: `/undo N` soft-deletes the last N turns, **identically across TUI, CLI and messaging** —
/// which is exactly why it lives here and not in either surface.
fn undo(session: &mut Session, n: usize) -> usize {
    let mut removed = 0;
    while removed < n {
        let Some(start) = session
            .transcript
            .iter()
            .rposition(|e| matches!(e, Entry::User(_)))
        else {
            break;
        };
        session.transcript.truncate(start);
        removed += 1;
    }
    session.pager.turn = session.pager.turn.saturating_sub(removed as u32);
    removed
}

fn parse_state(s: &str) -> Option<StatusState> {
    Some(match s {
        "listening" => StatusState::Listening,
        "thinking" => StatusState::Thinking,
        "speaking" => StatusState::Speaking,
        "writing" => StatusState::Writing,
        "running" => StatusState::Running,
        "waiting" => StatusState::Waiting,
        "idle" => StatusState::Idle,
        _ => return None,
    })
}

fn help() -> Vec<String> {
    let width = REGISTRY
        .iter()
        .map(|c| c.name.len() + c.args.len() + 2)
        .max()
        .unwrap_or(12);
    REGISTRY
        .iter()
        .map(|c| {
            let left = if c.args.is_empty() {
                format!("/{}", c.name)
            } else {
                format!("/{} {}", c.name, c.args)
            };
            format!("{left:width$}  {}", c.description)
        })
        .collect()
}

fn key_help(session: &Session) -> Vec<String> {
    let tree = crate::region::RegionTree::build(session);
    let mut out = vec!["region keys — jump focus directly".to_string()];
    for r in tree.regions() {
        out.push(format!("  {}  {}", r.hotkey_label(), r.label()));
    }
    out.push("inspector tabs".to_string());
    for tab in Tab::ALL {
        out.push(format!("  ({})  {}", tab.digit(), tab.title()));
    }
    out.push("global".to_string());
    for (k, what) in crate::app::FOOTER_KEYS {
        out.push(format!("  {k}  {what}"));
    }
    // §B10's copy keys, and the escape hatch. **The escape hatch is listed because an escape hatch
    // nobody knows about is not an escape hatch** — mouse capture removes the terminal's ordinary
    // selection, and a user who does not know about Shift-drag concludes copying is gone.
    out.push("copy".to_string());
    out.push("  (y)  copy the focused turn, or a tool call's full expanded output".to_string());
    out.push("  (Y)  copy the whole transcript as markdown".to_string());
    out.push(
        "  shift-drag  the terminal's own selection, which still works while Marlowe holds \
         the mouse"
            .to_string(),
    );
    out
}

/// Render an inspector pane linearly, for the classic CLI. Same data, no grid.
pub fn render_pane_linear(session: &Session, tab: Tab) -> Vec<String> {
    let mut out = Vec::new();
    for item in crate::inspector::items_for(session, tab) {
        out.push(format!("  {} ({})", item.label, item.key));
        for (line, tone) in &item.lines {
            let mark = match tone {
                Tone::Red => "!",
                Tone::Amber => "*",
                _ => " ",
            };
            out.push(format!("    {mark} {line}"));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_registered_command_dispatches_to_something_other_than_unknown() {
        for c in REGISTRY {
            let mut s = Session::new();
            let out = dispatch(&mut s, c.name, &[], 0);
            assert!(
                !matches!(out, Outcome::Unknown(_)),
                "/{} is in the registry but the dispatcher does not know it, so it would \
                 autocomplete and then do nothing",
                c.name
            );
        }
    }

    #[test]
    fn a_bad_argument_is_rejected_out_loud_and_changes_nothing() {
        let mut s = Session::new();
        let before = s.control.autonomy.value().to_string();
        let out = dispatch(&mut s, "autonomy", &["god-mode"], 0);
        assert!(matches!(out, Outcome::Rejected(_)));
        assert_eq!(s.control.autonomy.value(), before);
    }

    #[test]
    fn undo_removes_whole_turns() {
        let mut s = Session::new();
        let turns = s
            .transcript
            .iter()
            .filter(|e| matches!(e, Entry::User(_)))
            .count();
        dispatch(&mut s, "undo", &["2"], 0);
        let after = s
            .transcript
            .iter()
            .filter(|e| matches!(e, Entry::User(_)))
            .count();
        assert_eq!(after, turns - 2);
    }

    #[test]
    fn autocomplete_carries_descriptions() {
        let hits = complete("s");
        assert!(hits.iter().any(|c| c.name == "schedule"));
        assert!(hits.iter().all(|c| !c.description.is_empty()));
    }
}
