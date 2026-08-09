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

use marlowe_view::{ControlId, Intent, SessionView, StatusState, Tab, Tone};

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
///
/// # C2d: a command that changes the session returns an [`Intent`] instead of having changed it
///
/// `dispatch` used to take `&mut Session` and mutate a producer in place, which made the command
/// registry — a *surface* module — one of the places the surface authored session state. It now
/// takes `&SessionView` and is **pure**: the only way a command changes anything is by returning
/// [`Outcome::Ask`], which the driver hands to whatever is producing the view.
///
/// The practical tell that this was the right cut: `dispatch` can no longer make `/undo` remove a
/// turn from a transcript the daemon still has.
#[derive(Debug, Clone, PartialEq)]
pub enum Outcome {
    /// Lines to show. **Client output, not Marlowe's prose** — in the TUI they render as
    /// `ClientLine`s, in the CLI they print.
    Lines(Vec<String>),
    /// The inspector switched tab, and the transcript says only what a colleague would say out
    /// loud (§B7). Both strings travel together so neither surface can drop the other half.
    Tab(Tab, String),
    Quit,
    /// The command exists but the argument did not. Never a silent no-op.
    Rejected(String),
    Unknown(String),
    /// The command asks the producer to do something, and says what it asked for.
    ///
    /// The lines travel with the intent so a surface cannot report success before the producer has
    /// acted — they describe the *request*, and anything describing the result has to come back
    /// through the view.
    Ask(Intent, Vec<String>),
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
///
/// Read-only in the view, and `now_ms` is gone with the mutation it used to serve — a pure
/// dispatcher has no use for a clock.
pub fn dispatch(view: &SessionView, name: &str, args: &[&str]) -> Outcome {
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
            Some(Some(state)) => Outcome::Ask(
                Intent::ForceState(state),
                vec![format!("status: {}", state.name())],
            ),
            _ => Outcome::Rejected(
                "usage: /state listening|thinking|speaking|writing|running|waiting|idle".into(),
            ),
        },

        "model" => picker(view, ControlId::Model, args),
        "profile" => picker(view, ControlId::Profile, args),
        "session" => picker(view, ControlId::Session, args),
        "workspace" => picker(view, ControlId::Workspace, args),
        "autonomy" => picker(view, ControlId::Autonomy, args),

        "undo" => {
            let n: usize = args.first().and_then(|s| s.parse().ok()).unwrap_or(1);
            // **No count is reported here, and that is the correction.** The old version returned
            // "undone: N turns" from a number it produced by mutating the transcript itself. A
            // surface cannot know how many turns a producer will actually drop — it can only say
            // what it asked for.
            Outcome::Ask(
                Intent::Undo(n),
                vec![format!("undo {n} turn{}", if n == 1 { "" } else { "s" })],
            )
        }

        "compact" => Outcome::Ask(Intent::Compact, Vec::new()),

        "keys" => Outcome::Lines(key_help(view)),
        "doctor" => Outcome::Lines(crate::doctor::report(view)),
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

/// Show or request a control-strip value. **Reads the view; never writes it.**
///
/// The `Some(want)` arm returns the *request*, not a confirmation. `"{which}: {value}"` after a
/// successful assignment was a surface reporting a change it had made to a producer's state; the
/// same sentence now has to wait for the view to come back saying so.
fn picker(view: &SessionView, control: ControlId, args: &[&str]) -> Outcome {
    let p = view.picker(control);
    let which = control.name();
    match args.first() {
        None => Outcome::Lines(vec![format!(
            "{which}: {}   ({})",
            p.value(),
            p.options.join(" · ")
        )]),
        Some(want) => match p.options.iter().position(|o| o == want) {
            Some(i) => Outcome::Ask(
                Intent::Select { control, option: i },
                vec![format!("{which} → {want}")],
            ),
            None => Outcome::Rejected(format!(
                "{which} has no option {want:?}. One of: {}",
                p.options.join(", ")
            )),
        },
    }
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

fn key_help(view: &SessionView) -> Vec<String> {
    let tree = crate::region::RegionTree::build(view, Tab::Runs);
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
pub fn render_pane_linear(view: &SessionView, tab: Tab) -> Vec<String> {
    let mut out = Vec::new();
    for item in crate::inspector::items_for(view, tab) {
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
        let s = marlowe_stub::Session::new();
        for c in REGISTRY {
            let out = dispatch(s.view(), c.name, &[]);
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
        let s = marlowe_stub::Session::new();
        let before = s.view().control.autonomy.value().to_string();
        let out = dispatch(s.view(), "autonomy", &["god-mode"]);
        assert!(matches!(out, Outcome::Rejected(_)));
        assert_eq!(s.view().control.autonomy.value(), before);
    }

    #[test]
    fn a_command_that_changes_the_session_asks_rather_than_acts() {
        // C2d's shape change, asserted directly. `dispatch` takes `&SessionView`, so there is no
        // way for it to mutate; what this pins is that the mutating commands still *do* something
        // — returning `Outcome::Lines` for `/undo` would be a command that silently stopped
        // working, which is precisely the failure a compile-checked refactor can leave behind.
        let s = marlowe_stub::Session::new();
        for (name, args, want) in [
            ("undo", vec!["2"], Intent::Undo(2)),
            ("compact", vec![], Intent::Compact),
            (
                "autonomy",
                vec!["act"],
                Intent::Select { control: ControlId::Autonomy, option: 4 },
            ),
            ("state", vec!["idle"], Intent::ForceState(StatusState::Idle)),
        ] {
            match dispatch(s.view(), name, &args) {
                Outcome::Ask(got, _) => assert_eq!(got, want, "/{name}"),
                other => panic!("/{name} returned {other:?}, not a request"),
            }
        }
    }

    #[test]
    fn undo_reports_what_it_asked_for_and_not_what_happened() {
        // The old version returned "undone: 2 turns" from a count it produced by mutating the
        // transcript itself. A surface cannot know how many turns a producer will drop.
        let s = marlowe_stub::Session::new();
        let Outcome::Ask(_, lines) = dispatch(s.view(), "undo", &["2"]) else {
            panic!("expected a request");
        };
        assert_eq!(lines, vec!["undo 2 turns"]);
        assert!(
            !lines.iter().any(|l| l.contains("undone")),
            "a past-tense report of a change the producer has not made yet: {lines:?}"
        );
    }

    #[test]
    fn autocomplete_carries_descriptions() {
        let hits = complete("s");
        assert!(hits.iter().any(|c| c.name == "schedule"));
        assert!(hits.iter().all(|c| !c.description.is_empty()));
    }
}
