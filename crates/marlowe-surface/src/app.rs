//! Focus, input, and key dispatch. **Built before any content, per §B10.**
//!
//! > Keyboard first. The mockup is mouse-driven; the implementation must not be. Build every path
//! > by key and add mouse as a bonus. Mouse-first retrofitted with keys produces a bad TUI.
//!
//! Nothing in this module draws. That is deliberate: every navigation property §B13 asks for is
//! testable here without a terminal, and a key path that only works when something is on screen is
//! a key path that breaks the first time the screen changes.
//!
//! # `Esc` backs out one level, and interrupt is the outermost level
//!
//! §B10 says both *"`Esc` backs out one level"* and *"`Esc` interrupts"*. They are the same rule
//! applied at different depths, and the precedence is fixed here rather than left to whichever
//! branch runs first:
//!
//! 1. approval overlay up → **deny** (§B9)
//! 2. a control-strip dropdown open → close it
//! 3. focus is in a text field → blur to the conversation
//! 4. otherwise → **interrupt**, keeping partial output (§B10)
//!
//! # The one place region hotkeys are suspended
//!
//! While a text field has focus — the Message field, or the Runs pane's Steer field — a plain
//! character is text. It has to be: a message you cannot type the letter `m` into is not a message
//! field.
//!
//! Every region is still reachable by keyboard alone from there, three ways: `Tab`/`Shift-Tab`
//! cycle, `Esc` blurs to the conversation where every hotkey is live, and the Ctrl-modified footer
//! keys never suspend. `tests/keyboard_reachability.rs` proves it from the default focus rather
//! than from a convenient one.

use marlowe_stub::{Session, StatusState, Tab};

use crate::commands::{self, Outcome};
use crate::keys::{Binding, KeyRegistry};
use crate::region::{RegionId, RegionTree, TabId};

/// §B8's footer: **one line of global keys, always the same, never context-dependent.** Region
/// hotkeys live on their own borders; the footer is for actions.
pub const FOOTER_KEYS: &[(&str, &str)] = &[
    ("^v", "Voice"),
    ("^n", "New"),
    ("^r", "Runs"),
    ("^l", "Lineage"),
    ("^t", "Trust"),
    ("^u", "Undo"),
    ("esc", "Interrupt"),
    ("^k", "palette"),
];

/// A key, decoupled from crossterm so the whole dispatch table is testable without a terminal.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Key {
    Char(char),
    Ctrl(char),
    Enter,
    ShiftEnter,
    Tab,
    BackTab,
    Backspace,
    Up,
    Down,
    Left,
    Right,
    Esc,
}

/// What the caller should do after a key. The app never exits or draws on its own.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Action {
    None,
    Redraw,
    Quit,
}

/// The surface's own state — and **only** the surface's own state.
///
/// Focus, scroll offsets, what the user has typed, which lines are expanded. Every one of those is
/// a property of *looking at* the session, not of the session. ARCHITECTURE.md §2.14: a surface
/// holds no state the daemon does not have, and closing it does not affect a run.
#[derive(Debug)]
pub struct App {
    pub session: Session,
    pub focus: RegionId,
    pub input: String,
    pub steer: String,
    /// Transcript scroll offset in lines from the top. `None` means pinned to the bottom, which is
    /// what a live conversation wants and is not the same as "offset happens to be the maximum".
    pub scroll: Option<u16>,
    pub inspector_scroll: u16,
    /// Command output and notices, appended to the transcript as Marlowe's own lines.
    pub keys: KeyRegistry,
    /// Set when the terminal is too small. §B11: an honest refusal, never a degraded grid.
    pub too_small: Option<(u16, u16)>,

    /// **On-screen ground truth for a live session.**
    ///
    /// Everything about a running TUI that matters — is raw mode on, is the colour tier what the
    /// probe claimed, are keystrokes arriving — is invisible from outside the process. Inferring
    /// it from a separate `--timing-probe` run measures a *different* process, and inferring it
    /// from a screenshot measures a guess.
    ///
    /// So the program says it, in the frame, under `--diagnostic`. One picture then answers all
    /// three questions at once. This exists because a session that renders, animates, and ignores
    /// every key looks exactly like a session that works.
    pub diagnostic: Option<String>,
    /// Keystrokes that reached [`App::on_key`]. Rendered by `--diagnostic`.
    pub keys_seen: u32,
    /// The last key that arrived, as the app saw it.
    pub last_key: String,
    /// The largest scroll offset the last drawn frame allowed, written by `render::draw`.
    ///
    /// A `Cell` because it is a *measurement of the last frame*, not state the user changed —
    /// `draw` takes `&App` precisely so that rendering cannot mutate the session, and that
    /// restriction is worth keeping for everything except this. The alternative was for `App` to
    /// re-wrap the transcript itself to count lines, which means knowing the pane width, which
    /// means the layout leaking into the key dispatch.
    ///
    /// Zero until the first frame is drawn: scrolling before anything has been rendered is not a
    /// meaningful request, and treating it as "nothing to scroll" is correct rather than defensive.
    pub scroll_max: std::cell::Cell<u16>,
    /// The furthest the inspector pane can scroll, and the last item actually drawn — both written
    /// by `render::draw` for the same reason as `scroll_max`: only the renderer knows how many
    /// items fit in the pane at this window height.
    pub inspector_scroll_max: std::cell::Cell<u16>,
    pub inspector_last_visible: std::cell::Cell<u16>,
    /// Text waiting to be written to the clipboard, drained by the event loop.
    ///
    /// The app cannot write to the clipboard itself — that needs stdout, which is the terminal's,
    /// not the surface's. So `y` builds the payload here and the loop performs the OSC 52 write.
    /// Keeping the payload construction on this side is what lets `clipboard.rs` be tested without
    /// a terminal, which matters because the payloads are the part with the logic in them.
    pub pending_copy: Option<String>,
    /// A one-line confirmation shown until the next keystroke.
    ///
    /// **OSC 52 is write-only and unacknowledged**, so nothing downstream can tell the user whether
    /// the clipboard actually took it. The app therefore states what it sent and how much. An
    /// honest "copied 412 characters" beside an empty clipboard is a reportable bug; a silent
    /// no-op is a mystery, and this project has spent enough rounds on those.
    ///
    /// Cleared on the next key rather than on a timer: no clock is read, the surface stays a pure
    /// function of `(state, now_ms)`, and the confirmation lasts exactly as long as the user is
    /// still looking at the thing they just did.
    pub notice: Option<String>,
    /// Which slash-command suggestion is selected while typing one.
    ///
    /// §B10: *"slash commands autocomplete inline with descriptions."* A list you can see but not
    /// choose from is a hint, not a completion — so the arrows move this and `Tab` accepts it,
    /// which is what every shell and editor has trained the hands to expect.
    ///
    /// Reset to 0 on every edit of the input: after typing another character the old index points
    /// into a different list, and silently keeping it is how `/q` + `Down` + `Tab` completes to
    /// something the user never saw highlighted.
    pub completion: usize,
    /// The inspector tab the pointer is over, if any.
    ///
    /// A third hover slot rather than a variant of `hover`, for the same reason as `hover_option`:
    /// tabs are not regions. Each tab carries its own hotkey, so under §B2 the *bar* has no border
    /// and no `RegionId` — which is correct for the region contract and means the mouse needs its
    /// own hit-test here.
    pub hover_tab: Option<marlowe_stub::Tab>,
    /// The option index the pointer is over inside an OPEN dropdown, if any.
    ///
    /// Separate from `hover` because a dropdown's options are not regions — they have no border,
    /// no label and no hotkey of their own (§B2), so they cannot be `RegionId`s. Cleared by the
    /// same rules as `hover`, and additionally whenever no dropdown is open.
    pub hover_option: Option<usize>,
    /// The region the pointer is currently over, if any.
    ///
    /// **Deliberately not the conversation.** Hovering a transcript means nothing, and the pointer
    /// crossing it would repaint its border on every motion event — a flicker source with no
    /// information in it. `hoverable` is the whole rule and it lives in one place.
    ///
    /// A stuck hover is worse than no hover, so this clears on two events and not one: a motion
    /// that lands outside every hoverable region, **and** the terminal losing focus. Only the
    /// second covers the pointer leaving the window entirely, because no motion event is delivered
    /// once it does — the app would otherwise keep a highlight lit under a pointer that is now in
    /// another application.
    pub hover: Option<RegionId>,
    /// Mouse events that reached the loop, counted separately from keys.
    ///
    /// **Separate because a shared counter made an observation ambiguous exactly where it needed to
    /// be sharp.** The wheel is dispatched as `Key::Up`/`Key::Down` — deliberately, so the mouse
    /// adds no second scroll path — which means every wheel notch also ticks `keys_seen`. A frame
    /// reading `keys=2 last=Down` on a session where nothing had been typed was then equally
    /// consistent with "two phantom keystrokes" and "the mouse moved", and those call for opposite
    /// investigations. Two counters make the frame say which.
    pub mouse_seen: u32,
}

/// §B11's minimum. A narrow variant was designed and rejected: it cost the borders, which cost the
/// region contract, which is the entire design.
pub const MIN_COLS: u16 = 120;
pub const MIN_ROWS: u16 = 30;

impl App {
    /// Build, validating the key registry. **A conflict is a refusal to start** — see `keys.rs`.
    pub fn new(session: Session) -> Result<Self, crate::keys::KeyConflict> {
        let keys = KeyRegistry::build(&session)?;
        Ok(Self {
            session,
            // **The conversation, not the message field.**
            //
            // The first version started in the Message field, on the reasoning that the user came
            // here to type. It made §B10's first sentence false on arrival: *"Region hotkeys jump
            // focus directly — `m` to Model, `2` to Schedule, `c` to the conversation."* From a
            // focused text field `m` is the letter m, so every hotkey printed on every border did
            // nothing until the user guessed `Esc` first. The borders were advertising a contract
            // the default state broke.
            //
            // Starting on the conversation makes every hotkey live immediately, and `i` — already
            // printed on the message field's own bottom border — is how you begin typing. That is
            // the same shape as the rest of the design rather than an exception to it.
            focus: RegionId::Conversation,
            input: String::new(),
            steer: String::new(),
            scroll: None,
            inspector_scroll: 0,
            keys,
            too_small: None,
            diagnostic: None,
            keys_seen: 0,
            last_key: String::from("none"),
            mouse_seen: 0,
            scroll_max: std::cell::Cell::new(0),
            inspector_scroll_max: std::cell::Cell::new(0),
            inspector_last_visible: std::cell::Cell::new(0),
            completion: 0,
            hover: None,
            hover_tab: None,
            hover_option: None,
            pending_copy: None,
            notice: None,
        })
    }

    pub fn tab(&self) -> TabId {
        self.session.tab.into()
    }

    pub fn tree(&self) -> RegionTree {
        RegionTree::build(&self.session)
    }

    /// True when the focused region takes typed characters as text.
    pub fn focus_is_text(&self) -> bool {
        match self.focus {
            RegionId::Message => true,
            RegionId::Item(tab, i) => crate::inspector::items_for(&self.session, self.session.tab)
                .get(i)
                .is_some_and(|item| item.editable && TabId::from(self.session.tab) == tab),
            _ => false,
        }
    }

    fn picker_open(&self) -> bool {
        let c = &self.session.control;
        c.model.open || c.profile.open || c.session.open || c.workspace.open || c.autonomy.open
    }

    fn close_pickers(&mut self) {
        let c = &mut self.session.control;
        for p in [
            &mut c.model,
            &mut c.profile,
            &mut c.session,
            &mut c.workspace,
            &mut c.autonomy,
        ] {
            p.open = false;
        }
    }

    fn picker_mut(&mut self, id: RegionId) -> Option<&mut marlowe_stub::Picker> {
        let c = &mut self.session.control;
        Some(match id {
            RegionId::Model => &mut c.model,
            RegionId::Profile => &mut c.profile,
            RegionId::Session => &mut c.session,
            RegionId::Workspace => &mut c.workspace,
            RegionId::Autonomy => &mut c.autonomy,
            _ => return None,
        })
    }

    /// The five control-strip regions, in the order they are laid out. One list, so the mouse
    /// hit-test cannot drift out of step with the render order.
    pub const STRIP: [RegionId; 5] = [
        RegionId::Model,
        RegionId::Profile,
        RegionId::Session,
        RegionId::Workspace,
        RegionId::Autonomy,
    ];

    /// `(running, due today)` — the ambient counts. **One definition, two readers.**
    ///
    /// The titlebar row and the OS window title say the same thing, so they compute it in the same
    /// place. Two copies of "how many runs are running" is precisely the kind of duplication that
    /// disagrees six months later, with no test able to see it because each is individually right.
    pub fn run_counts(&self) -> (usize, usize) {
        let running = self
            .session
            .runs
            .iter()
            .filter(|i| i.lines.iter().any(|(l, _)| l.contains("running")))
            .count();
        let due = self
            .session
            .schedule
            .iter()
            .find(|i| i.label == "Due today")
            .map(|i| i.lines.len())
            .unwrap_or(0);
        (running, due)
    }

    /// The window title, as a function of session state. Written by the loop via OSC 0.
    ///
    /// **The title bar is a row of screen Marlowe is paying for either way.** Left alone it holds a
    /// static label — the profile's name, or worse, a shell's idea of the working directory. Driven
    /// from state it becomes the same readout the titlebar row carries inside the frame, which is
    /// what makes the window legible when it is not the focused one: a taskbar entry reading
    /// `marlowe — thursday · running` is the one piece of Marlowe visible from another application.
    ///
    /// This is the same argument for putting state in a native title bar on a platform that has
    /// one, so the string is built here rather than in the terminal-specific code.
    pub fn window_title(&self) -> String {
        let s = &self.session;
        let mut t = format!("marlowe — {}", s.control.session.value());
        // The state is worth the characters only when it is not the resting one; a title that
        // always says `idle` has spent a row to say nothing.
        if s.status.state != StatusState::Idle {
            t.push_str(&format!(" · {}", s.status.state.name()));
        }
        let (running, _due) = self.run_counts();
        if running > 0 {
            t.push_str(&format!(" · {running} runs"));
        }
        t
    }

    /// The slash-command suggestions for what is currently typed, or empty.
    ///
    /// One definition, read by both the renderer and the key dispatch — otherwise `Tab` completes
    /// from one list while the user is looking at another.
    pub fn completions(&self) -> Vec<&'static crate::commands::Command> {
        if self.focus != RegionId::Message {
            return Vec::new();
        }
        match self.input.strip_prefix('/') {
            Some(rest) if !rest.contains(' ') => crate::commands::complete(rest),
            _ => Vec::new(),
        }
    }

    /// Accept the highlighted suggestion. `Tab`, and the reason `Tab` is safe to take here: with a
    /// slash command open the region cycle is not what the hands are reaching for.
    pub fn accept_completion(&mut self) -> Action {
        let hits = self.completions();
        let Some(cmd) = hits.get(self.completion.min(hits.len().saturating_sub(1))) else {
            return Action::None;
        };
        self.input = format!("/{} ", cmd.name);
        self.completion = 0;
        Action::Redraw
    }

    /// `y` — copy the focused thing. §B10.
    ///
    /// What "focused" means depends on where focus is, and in M1 the conversation has no per-line
    /// cursor (§B6 cursoring is M2, with real scrollback), so from the conversation this copies the
    /// **last turn**. The notice says which, rather than leaving the user to infer it — a copy that
    /// silently took something other than what was wanted is worse than one that refused.
    pub fn copy_focused(&mut self) -> Action {
        let (text, what) = match self.focus {
            RegionId::Item(_, _) => {
                let items = crate::inspector::items_for(&self.session, self.session.tab);
                let RegionId::Item(_, i) = self.focus else {
                    unreachable!()
                };
                match items.get(i) {
                    Some(item) => (
                        item.lines
                            .iter()
                            .map(|(l, _)| l.clone())
                            .collect::<Vec<_>>()
                            .join("\n"),
                        "this item",
                    ),
                    None => return Action::None,
                }
            }
            _ => match self
                .session
                .transcript
                .iter()
                .rev()
                .find_map(crate::clipboard::entry_text)
            {
                Some(t) => (t, "the last turn"),
                None => {
                    self.notice = Some("nothing to copy yet".into());
                    return Action::Redraw;
                }
            },
        };
        self.notice = Some(format!("copied {what} — {} characters", text.chars().count()));
        self.pending_copy = Some(text);
        Action::Redraw
    }

    /// `Y` — copy the whole transcript as markdown. §B10.
    pub fn copy_transcript(&mut self) -> Action {
        let text = crate::clipboard::transcript_markdown(&self.session);
        self.notice = Some(format!(
            "copied the transcript as markdown — {} characters",
            text.chars().count()
        ));
        self.pending_copy = Some(text);
        Action::Redraw
    }

    /// Whether a region takes a hover highlight at all.
    ///
    /// The conversation does not: hovering a transcript conveys nothing, and the pointer crossing
    /// it would repaint a border on every motion event. Everything else the mouse can act on does.
    pub fn hoverable(id: RegionId) -> bool {
        !matches!(id, RegionId::Conversation)
    }

    /// Record the pointer's region, ignoring anything not hoverable. Returns whether it changed —
    /// the loop only needs to redraw when it did, which is what keeps motion cheap.
    pub fn set_hover(&mut self, id: Option<RegionId>) -> bool {
        let next = id.filter(|i| Self::hoverable(*i));
        let changed = self.hover != next;
        self.hover = next;
        changed
    }

    /// `(region, index in the strip, number of options)` for the open dropdown, if one is open.
    pub fn open_picker(&self) -> Option<(RegionId, usize, usize)> {
        let c = &self.session.control;
        for (i, (id, p)) in Self::STRIP
            .iter()
            .zip([&c.model, &c.profile, &c.session, &c.workspace, &c.autonomy])
            .enumerate()
        {
            if p.open {
                return Some((*id, i, p.options.len()));
            }
        }
        None
    }

    /// Open the focused region's dropdown, if it has one. What a click on a control cell does.
    pub fn open_focused_picker(&mut self) -> Action {
        let id = self.focus;
        match self.picker_mut(id) {
            Some(p) => {
                p.open = true;
                Action::Redraw
            }
            None => Action::None,
        }
    }

    /// Choose an option by index and commit — what `Enter` does, addressed directly.
    ///
    /// Lives here rather than in the event loop so that clicking an option is the *same* state
    /// transition as arrowing to it and pressing `Enter`, and so it can be tested without a
    /// terminal. An out-of-range index is ignored rather than clamped: a click that lands on the
    /// popup's border is not a request to pick the nearest option.
    pub fn choose_option(&mut self, index: usize) -> Action {
        let id = self.focus;
        let Some(p) = self.picker_mut(id) else {
            return Action::None;
        };
        if index >= p.options.len() {
            return Action::None;
        }
        p.selected = index;
        p.open = false;
        Action::Redraw
    }

    /// The single key entry point.
    pub fn on_key(&mut self, key: Key, now_ms: u64) -> Action {
        // Counted before any dispatch, so `--diagnostic` distinguishes "the key never arrived"
        // from "the key arrived and did nothing". Those have completely different causes and look
        // identical from outside the process.
        self.keys_seen += 1;
        self.last_key = format!("{key:?}");
        // A confirmation lasts until the user does something else. Taken before dispatch so that a
        // copy can set a fresh one on the way through.
        self.notice = None;

        // 1. §B9's overlay is modal. It is the only element permitted to dim the frame, and while
        //    it is up it is the only thing that answers a key.
        if self.session.approval.is_some() {
            return self.on_approval_key(key, now_ms);
        }

        // 2. Ctrl-modified footer keys never suspend, in any focus. That is what makes "reachable
        //    by keyboard alone" true even from inside a text field.
        if let Key::Ctrl(c) = key {
            return self.on_global_ctrl(c, now_ms);
        }

        // 3. An open dropdown owns the arrows and Enter.
        if self.picker_open() {
            return self.on_picker_key(key);
        }

        match key {
            // A slash command being typed owns Tab. Completing is what the hands expect there,
            // and the region cycle is still one Esc away.
            Key::Tab if !self.completions().is_empty() => self.accept_completion(),
            Key::Tab => {
                self.focus = self.tree().next(self.focus);
                Action::Redraw
            }
            Key::BackTab => {
                self.focus = self.tree().prev(self.focus);
                Action::Redraw
            }
            Key::Esc => self.on_escape(now_ms),
            _ if self.focus_is_text() => self.on_text_key(key, now_ms),
            _ => self.on_region_key(key, now_ms),
        }
    }

    fn on_escape(&mut self, now_ms: u64) -> Action {
        if self.picker_open() {
            self.close_pickers();
            return Action::Redraw;
        }
        if self.focus_is_text() {
            self.focus = RegionId::Conversation;
            return Action::Redraw;
        }
        // The outermost level. Partial output is kept (§B10).
        self.session.interrupt(now_ms);
        Action::Redraw
    }

    fn on_global_ctrl(&mut self, c: char, now_ms: u64) -> Action {
        match c {
            'v' => {
                // §B5's seven states, on demand. Required by M1's scope: every state must be
                // reachable without waiting for a script to arrive at it.
                self.session.cycle_state(now_ms);
                Action::Redraw
            }
            'n' => {
                self.session = Session::new();
                self.input.clear();
                self.scroll = None;
                Action::Redraw
            }
            'r' => self.switch_tab(Tab::Runs),
            't' => self.switch_tab(Tab::Trust),
            'l' => {
                self.say(format!(
                    "lineage {} deep · {} turns compacted. Walking it is M2 — the generations \
                     exist, the walk needs sessions behind it.",
                    self.session.pager.lineage, self.session.pager.compacted
                ));
                Action::Redraw
            }
            'u' => {
                self.run_command("undo", &["1"], now_ms);
                Action::Redraw
            }
            'k' => {
                // §B10's palette indexes sessions, models, skills, recent files and memory search.
                // None exist. Saying so is the honest surface; a palette over a stub index would
                // look like a feature and measure nothing.
                self.say(
                    "The palette lands in M2 — it indexes sessions, skills and models, and none \
                     of those exist yet. /help lists what does."
                        .to_string(),
                );
                Action::Redraw
            }
            'c' => Action::Quit,
            _ => Action::None,
        }
    }

    fn switch_tab(&mut self, tab: Tab) -> Action {
        self.session.tab = tab;
        self.inspector_scroll = 0;
        // Focus follows the tab only if it was already inside the inspector; otherwise a `^r`
        // while typing would steal the cursor out of a half-written message.
        if matches!(self.focus, RegionId::Item(_, _)) {
            self.focus = RegionId::Item(tab.into(), 0);
        }
        Action::Redraw
    }

    fn on_region_key(&mut self, key: Key, now_ms: u64) -> Action {
        match key {
            // §B10's copy keys. Checked before the region registry, and `keys.rs` refuses to build
            // a registry that binds either of them — so this cannot be shadowed by a pane whose
            // items happen to start with the letter y.
            Key::Char('y') => self.copy_focused(),
            Key::Char('Y') => self.copy_transcript(),
            Key::Char(c) => match self.keys.resolve(c, self.tab()) {
                Some(Binding::Focus(id)) => {
                    self.focus = id;
                    Action::Redraw
                }
                Some(Binding::Tab(t)) => self.switch_tab(match t {
                    TabId::Runs => Tab::Runs,
                    TabId::Schedule => Tab::Schedule,
                    TabId::Sessions => Tab::Sessions,
                    TabId::Skills => Tab::Skills,
                    TabId::Trust => Tab::Trust,
                    TabId::Status => Tab::Status,
                }),
                None => Action::None,
            },
            Key::Enter => self.act(now_ms),
            Key::Up => self.move_within(-1),
            Key::Down => self.move_within(1),
            Key::Left | Key::Right => Action::None,
            _ => Action::None,
        }
    }

    /// `Enter` acts on the focused region.
    fn act(&mut self, now_ms: u64) -> Action {
        match self.focus {
            RegionId::Model
            | RegionId::Profile
            | RegionId::Session
            | RegionId::Workspace
            | RegionId::Autonomy => {
                let id = self.focus;
                if let Some(p) = self.picker_mut(id) {
                    p.open = true;
                }
                Action::Redraw
            }
            RegionId::Status => {
                self.session.cycle_state(now_ms);
                Action::Redraw
            }
            RegionId::Conversation => {
                // §B6: cursor to a line, Enter for full output in place. M1 expands the last tool
                // group; per-line cursoring inside the transcript is M2 with real scrollback.
                if let Some(marlowe_stub::Entry::Tools(calls)) = self
                    .session
                    .transcript
                    .iter_mut()
                    .rev()
                    .find(|e| matches!(e, marlowe_stub::Entry::Tools(_)))
                {
                    for call in calls {
                        call.expanded = !call.expanded;
                    }
                }
                Action::Redraw
            }
            RegionId::Item(_, _) => Action::Redraw,
            RegionId::Message => Action::None,
        }
    }

    fn move_within(&mut self, delta: i32) -> Action {
        match self.focus {
            RegionId::Conversation => {
                // `None` is pinned to the bottom and stays pinned as the transcript grows — which
                // is what a live conversation wants, and is not the same as an offset that happens
                // to equal the maximum.
                let max = self.scroll_max.get();
                if max == 0 {
                    // The transcript fits. Nothing to scroll, and inventing an offset here is how
                    // the previous version ended up 65,534 lines above a 20-line conversation.
                    return Action::None;
                }
                self.scroll = match (self.scroll, delta < 0) {
                    (None, true) => Some(max.saturating_sub(1)),
                    (Some(o), true) => Some(o.saturating_sub(1)),
                    // Already at the bottom, and scrolling down re-pins rather than drifting.
                    (None, false) => None,
                    (Some(o), false) if o + 1 >= max => None,
                    (Some(o), false) => Some(o + 1),
                };
                Action::Redraw
            }
            RegionId::Item(tab, i) => {
                let n = crate::inspector::items_for(&self.session, self.session.tab).len();
                let next = (i as i32 + delta).clamp(0, n.saturating_sub(1) as i32) as usize;
                self.focus = RegionId::Item(tab, next);
                // Follow the selection rather than leaving it behind the fold. Only when it has
                // actually gone off an edge — scrolling on every keypress would move the whole
                // pane under a user who is just stepping down one row.
                let next = next as u16;
                if next < self.inspector_scroll {
                    self.inspector_scroll = next;
                } else if next > self.inspector_last_visible.get() {
                    self.inspector_scroll = self
                        .inspector_scroll
                        .saturating_add(next - self.inspector_last_visible.get())
                        .min(self.inspector_scroll_max.get());
                }
                Action::Redraw
            }
            _ => Action::None,
        }
    }

    fn on_picker_key(&mut self, key: Key) -> Action {
        let id = self.focus;
        let Some(p) = self.picker_mut(id) else {
            self.close_pickers();
            return Action::Redraw;
        };
        match key {
            Key::Up => {
                p.selected = p.selected.saturating_sub(1);
                Action::Redraw
            }
            Key::Down => {
                p.selected = (p.selected + 1).min(p.options.len() - 1);
                Action::Redraw
            }
            Key::Enter | Key::Esc => {
                p.open = false;
                Action::Redraw
            }
            _ => Action::None,
        }
    }

    fn on_text_key(&mut self, key: Key, now_ms: u64) -> Action {
        let steering = self.focus != RegionId::Message;
        match key {
            Key::Char(c) => {
                if steering {
                    self.steer.push(c);
                } else {
                    self.input.push(c);
                    // The list just changed underneath the index.
                    self.completion = 0;
                }
                Action::Redraw
            }
            Key::Backspace => {
                if steering {
                    self.steer.pop();
                } else {
                    self.input.pop();
                    self.completion = 0;
                }
                Action::Redraw
            }
            // Arrows walk the suggestions when there are any, and do nothing otherwise — a text
            // field with no completion open has no other use for Up and Down in M1.
            Key::Up | Key::Down if !self.completions().is_empty() => {
                let n = self.completions().len();
                self.completion = if key == Key::Up {
                    (self.completion + n - 1) % n
                } else {
                    (self.completion + 1) % n
                };
                Action::Redraw
            }
            // §B10: multiline by default — Shift-Enter for a newline, Enter to send.
            Key::ShiftEnter => {
                if steering {
                    self.steer.push('\n');
                } else {
                    self.input.push('\n');
                }
                Action::Redraw
            }
            Key::Enter => {
                if steering {
                    let text = std::mem::take(&mut self.steer);
                    if !text.trim().is_empty() {
                        // v1.0 §10.1: injected into a RUNNING child without killing it.
                        self.say(format!("Steered. The run has it: {}", text.trim()));
                    }
                    return Action::Redraw;
                }
                self.submit(now_ms)
            }
            _ => Action::None,
        }
    }

    /// Send the message field. Handles `/command`, `!shell`, and plain prose.
    pub fn submit(&mut self, now_ms: u64) -> Action {
        let text = std::mem::take(&mut self.input);
        let text = text.trim().to_string();
        if text.is_empty() {
            return Action::None;
        }
        self.scroll = None;

        if let Some(rest) = text.strip_prefix('/') {
            let mut parts = rest.split_whitespace();
            let name = parts.next().unwrap_or("");
            let args: Vec<&str> = parts.collect();
            return match self.run_command(name, &args, now_ms) {
                Outcome::Quit => Action::Quit,
                _ => Action::Redraw,
            };
        }

        if let Some(cmd) = text.strip_prefix('!') {
            // §B10: `!cmd` runs a shell command in the agent's working directory, **through the
            // same approval path**. M1 has no execution and no permission layer, so it reports
            // that rather than pretending — a stub that echoed fake output would be teaching the
            // user something false about what the approval path does.
            self.session.transcript.push(marlowe_stub::Entry::User(text.clone()));
            self.say(format!(
                "Shell runs through the approval path, and that path lands in M2. {cmd:?} was not \
                 run."
            ));
            return Action::Redraw;
        }

        self.session.submit(&text, now_ms);
        Action::Redraw
    }

    /// Dispatch through the **one** command registry (§B11), and render the outcome the TUI way.
    pub fn run_command(&mut self, name: &str, args: &[&str], now_ms: u64) -> Outcome {
        let outcome = commands::dispatch(&mut self.session, name, args, now_ms);
        match &outcome {
            Outcome::Lines(lines) => {
                for line in lines {
                    self.say(line.clone());
                }
            }
            Outcome::Tab(tab, said) => {
                // §B7's rule, and the whole argument for a TUI over a chat log: the inspector
                // renders it and the conversation says only what a colleague would say out loud.
                self.session.tab = *tab;
                self.inspector_scroll = 0;
                self.say(said.clone());
            }
            Outcome::Rejected(why) => self.say(why.clone()),
            Outcome::Unknown(name) => {
                let near = commands::complete(name);
                let msg = match near.first() {
                    Some(c) => format!("No /{name}. Closest is /{}.", c.name),
                    None => format!("No /{name}. /help lists what there is."),
                };
                self.say(msg);
            }
            Outcome::Quit => {}
        }
        outcome
    }

    fn say(&mut self, text: String) {
        self.session.transcript.push(marlowe_stub::Entry::Said(text));
    }

    fn on_approval_key(&mut self, key: Key, now_ms: u64) -> Action {
        match key {
            Key::Enter => {
                self.session.resolve_approval(true, now_ms);
                Action::Redraw
            }
            Key::Esc => {
                self.session.resolve_approval(false, now_ms);
                Action::Redraw
            }
            Key::Char('e') => {
                self.session.approval = None;
                self.session.force_state(StatusState::Idle, now_ms);
                self.say("Opened for editing. Nothing sent.".into());
                Action::Redraw
            }
            Key::Char('s') => {
                // Addendum A §A3: sending *as Marlowe* is the path that avoids impersonation
                // entirely, and §B9 requires the overlay to offer it.
                self.session.approval = None;
                self.session.force_state(StatusState::Idle, now_ms);
                self.say("Sent as Marlowe, with your name on the request and not on the sender.".into());
                Action::Redraw
            }
            // Everything else is swallowed. §B9's whole subject is a user who has stopped reading;
            // an overlay that let an unrelated keystroke fall through to the frame behind it would
            // be the rubber-stamping failure with extra steps.
            _ => Action::None,
        }
    }
}
