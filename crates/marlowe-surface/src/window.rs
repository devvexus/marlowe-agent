//! **A real terminal window per run.** `M3-DESIGN.md` §6.
//!
//! Not a tab, and not a debug panel that grew. A window attaches to a **run** — a top-agent scope is
//! a run with children, so one surface serves both and this does not wait on the agent tree to
//! exist.
//!
//! # It is a debugging instrument before it is a feature
//!
//! §6's opening position, and it is what decides the layout: verifying durable resume means
//! *watching a run die and come back at the right step*. So [`RunView::checkpoint`] is not a
//! footnote in a status line — it is a panel of its own, above the output, with two separate facts
//! in it: what the run last finished, and what a resume would actually do. Those answer different
//! questions, and a window that showed only the first would invite the reader to infer the second.
//!
//! # What this file does NOT own
//!
//! **The look.** §6.4: *"Do not reimplement the look. Two definitions of a border is the
//! two-sides-silently-disagree shape applied to pixels."* So:
//!
//! | thing | where it comes from |
//! |---|---|
//! | every border | [`crate::region::Region::block`] — the only bordered `Block` in this crate |
//! | the region tree | [`RegionTree::for_window`] |
//! | every glyph | [`crate::chrome`] — the set model prose may not contain |
//! | the transcript | [`crate::render::entry_lines`] — one body, shared with the conversation pane |
//! | markdown and maths | ADR-047's renderer, by way of `entry_lines` |
//! | colour | [`crate::theme`], which has no eighth colour to reach for |
//!
//! **State.** §6.6: *"One state, two renderings."* [`WindowApp`] holds a [`RunView`] it was handed
//! and everything about **looking at** it — the steer draft, the scroll offset, whether a reasoning
//! block is open, what time it is. It computes no run fact, and there is no setter that could.
//!
//! # A frame is a pure function of state, and there is no clock here at all
//!
//! §6.4 borrows §B13's flicker rows and asks that anything moving be a pure function of
//! `(state, now_ms)`. **This ended up stronger than asked for: there is no `now_ms`.**
//!
//! It was `elapsed = now_ms - started_ms`, computed here, with `now_ms` a field the driver stamped.
//! Session A's `ControlPlane::detail` resolves elapsed on the daemon — the final wall time when a
//! run has one, the live figure otherwise — because the daemon is the thing that holds a clock. So
//! the last reason for a clock in this file went away, and the field went with it.
//!
//! **It went with it rather than being left harmless.** A `now_ms` nothing read would be a declared
//! control with no reader, and `pulse()` beside it was already exactly that: a helper with a green
//! test asserting it is a pure function of time, and no caller anywhere in the draw path. That is
//! family #16, found here by the merge that removed its last purpose.
//!
//! A second draw of one state therefore changes **not one cell**, which `window_flicker.rs` diffs
//! at five sizes — and two windows on one run are the same frame whenever the daemon last spoke.
//!
//! The scroll offset is computed inside [`draw`] from the line count and the viewport, rather than
//! cached in a `Cell` and read back on the next frame — a value written by frame N and read by frame
//! N+1 is a cross-frame dependency, and the flicker check would be measuring convergence rather than
//! purity.
//!
//! # ADR-055 is the reason there is an output panel at all
//!
//! Audit finding E4's generalised form — *"prose composed inside a window holding attacker-controlled
//! pages must not stream to a terminal"* — forbids this panel as written. ADR-055 crosses it
//! deliberately, **on the condition that E4's own unbuilt second clause is built**: the character
//! check at the boundary where bytes reach a screen. [`prepared`] is that clause, and
//! `tests/window_sanitiser.rs` asserts it on the rendered `Buffer` rather than on the function that
//! built it.

use std::collections::BTreeMap;

use ratatui::buffer::Buffer;
use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::style::Style;
use ratatui::text::{Line, Span};
use ratatui::widgets::{Paragraph, Widget};

use marlowe_view::run::{elapsed, micros_usd, RunView};
use marlowe_view::{Entry, Item, Tone};

use crate::region::{FocusLevel, RegionId, RegionTree};
use crate::theme::Theme;

/// §B11's honest refusal, at a run window's scale.
///
/// **Smaller than the main TUI's 120×30, and that is a decision rather than a relaxation.** The
/// main frame carries a conversation *and* a six-tab inspector side by side; a run window carries
/// one run. 80×24 is the classic terminal default, so a window Marlowe opens for the user fits
/// whatever they already have — and §6.7's fallback is a command they paste into a terminal that is
/// whatever size it is. Below this it prints one line naming both sizes, exactly as `render::draw`
/// does: a broken grid is worse than an honest refusal.
pub const MIN_COLS: u16 = 80;
pub const MIN_ROWS: u16 = 24;

/// The right-hand column's width. Fixed, so §6.3's placeholders occupy the space they will occupy
/// when they fill — the layout must not move on the day the roster lands.
const ASIDE_W: u16 = 30;

const TITLEBAR_H: u16 = 1;
const IDENTITY_H: u16 = 4;
const CHECKPOINT_H: u16 = 4;
const STEER_H: u16 = 3;
const FOOTER_H: u16 = 1;

/// What the window asks the control plane to do. **Drained by the driver; never applied here.**
///
/// ARCHITECTURE §2.14: surfaces own rendering and input and hold no policy. A window that could
/// steer a run directly would be holding the control plane, and §6.1's correction — *"a steer field
/// is a write"* — is precisely about not letting that happen quietly.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WindowRequest {
    /// The text the person typed, **unvalidated**. It becomes a `SteerMessage` only inside
    /// `marlowe_loop::steer::admit`, which is the one door (ADR-054). The surface deliberately does
    /// not pre-check it: a second copy of the cap and the sanitiser here is the drift that ADR
    /// exists to prevent.
    Steer(String),
    /// Confirmed at the overlay, which stated the orphan policy plainly first.
    Cancel,
    Resume,
    /// Close the window. **Detaches; never cancels** (§6.5).
    Detach,
}

/// A modal the window is holding up. Only one thing is modal here.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Confirm {
    /// §6.2: cancel *"with the orphan policy the run declared at spawn stated plainly"*. The policy
    /// is read off the [`RunView`] at draw, so this variant carries nothing — a copy of the policy
    /// taken when the key was pressed could disagree with the run by the time it is confirmed.
    Cancel,
}

/// What a key did, for a driver that has to decide whether to repaint.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Action {
    None,
    Redraw,
    /// The window should close. Detaching, not cancelling.
    Close,
}

/// A run window: one [`RunView`], and everything about looking at it.
#[derive(Debug, Clone)]
pub struct WindowApp {
    view: RunView,
    /// The steer draft. A `String` and not a `SteerMessage`: see [`WindowRequest::Steer`].
    pub steer: String,
    pub focus: RegionId,
    /// `None` is pinned to the bottom and **stays** pinned as output arrives, which is what a
    /// window on a live run wants. `Some(n)` is a position the user chose.
    pub scroll: Option<u16>,
    pub reasoning_expanded: bool,
    /// Per-tool-line overrides. Whether you opened a line is a property of looking at it, so the
    /// producer's own `expanded` stays the default an untouched line falls back to.
    pub expanded: BTreeMap<u64, bool>,
    pub confirm: Option<Confirm>,
    /// One line of harness-authored text, shown above the steer field. **Harness-authored** — a
    /// window never puts words in Marlowe's mouth (ADR-030), so this is only ever something the
    /// surface itself has to say, such as a refused steer.
    pub notice: Option<String>,
    /// The largest scroll offset the current viewport allows, as the **driver** last computed it
    /// with [`scroll_max`].
    ///
    /// # Why this is set from outside rather than cached during a draw
    ///
    /// Scrolling up from the pinned position needs to know where the bottom is, and that depends on
    /// the width — which only a draw knows. The main pane solves this with a `Cell` written during
    /// `draw` and read by the next keystroke. **A window must not**, because §6.4 makes the frame a
    /// pure function of `(state, now_ms)`, and a value written by frame N and read by frame N+1
    /// makes the flicker check measure convergence instead of purity.
    ///
    /// The driver holds the terminal size, so it is the honest owner: it calls [`scroll_max`] and
    /// sets this before dispatching a key. [`draw`] clamps independently against the size it is
    /// actually given, so a stale hint can move the offset but can never render out of range.
    ///
    /// **The defect this closes is not hypothetical.** With no maximum, `Up` from the pinned
    /// position computed `u16::MAX - 1`, which still clamped to the bottom — so scrolling up in a
    /// window did nothing at all, silently, on every run with more output than fits.
    scroll_max_hint: u16,
    requests: Vec<WindowRequest>,
}

impl WindowApp {
    pub fn new(view: RunView) -> Self {
        Self {
            view,
            steer: String::new(),
            // Opens on the output, because the first thing anyone does with a run window is read
            // it. Focus starts somewhere a keystroke is safe.
            focus: RegionId::RunOutput,
            scroll: None,
            reasoning_expanded: false,
            expanded: BTreeMap::new(),
            confirm: None,
            notice: None,
            scroll_max_hint: 0,
            requests: Vec::new(),
        }
    }

    pub fn view(&self) -> &RunView {
        &self.view
    }

    /// Publish a fresh projection of the run. **Replaces; never merges.**
    ///
    /// The window holds no run fact of its own, so there is nothing here to reconcile — which is
    /// what "one state, two renderings" means in practice.
    pub fn update(&mut self, view: RunView) {
        self.view = view;
    }

    pub fn tree(&self) -> RegionTree {
        RegionTree::for_window()
    }

    /// Take what the window has asked for. The driver applies these; the surface does not.
    pub fn drain_requests(&mut self) -> Vec<WindowRequest> {
        std::mem::take(&mut self.requests)
    }

    /// The control plane refused something. Shown verbatim.
    ///
    /// **Verbatim is the point.** `SteerRefused::TooLong` names the length and the limit; a window
    /// that reworded it into "too long" would delete the two numbers the user needs to act.
    pub fn refused(&mut self, why: impl std::fmt::Display) {
        self.notice = Some(why.to_string());
    }

    pub fn is_expanded(&self, call: &marlowe_view::ToolCall) -> bool {
        *self.expanded.get(&call.id).unwrap_or(&call.expanded)
    }

    fn ask(&mut self, r: WindowRequest) {
        self.requests.push(r);
    }

    /// Whether typed characters go into the steer field.
    fn focus_is_text(&self) -> bool {
        self.focus == RegionId::RunSteer
    }

    pub fn on_key(&mut self, key: crate::app::Key) -> Action {
        use crate::app::Key;

        // ── the modal first, and it consumes everything ──────────────────────────────────────
        //
        // §B9's shape: while something is up, the keys underneath do not fire. A cancel
        // confirmation that could be dismissed by a keystroke meant for the steer field is a
        // confirmation that did not happen.
        if let Some(Confirm::Cancel) = self.confirm {
            return match key {
                Key::Enter => {
                    self.confirm = None;
                    self.ask(WindowRequest::Cancel);
                    Action::Redraw
                }
                Key::Esc => {
                    self.confirm = None;
                    Action::Redraw
                }
                _ => Action::None,
            };
        }

        match key {
            // ── footer keys, always live ─────────────────────────────────────────────────────
            Key::Ctrl('x') => {
                self.confirm = Some(Confirm::Cancel);
                Action::Redraw
            }
            Key::Ctrl('r') => {
                self.ask(WindowRequest::Resume);
                Action::Redraw
            }
            Key::Ctrl('d') => {
                // §6.5: **closing detaches.** The request is `Detach`, not `Cancel`, and there is
                // no key in this window that closes it and stops the run at once.
                self.ask(WindowRequest::Detach);
                Action::Close
            }
            Key::Tab => {
                self.focus = self.tree().next(self.focus);
                Action::Redraw
            }
            Key::BackTab => {
                self.focus = self.tree().prev(self.focus);
                Action::Redraw
            }
            _ if self.focus_is_text() => self.on_text_key(key),
            // ── region hotkeys, §B10: a letter jumps focus ───────────────────────────────────
            Key::Char(c) => {
                if let Some(r) = self.tree().regions().iter().find(|r| r.hotkey() == c) {
                    self.focus = r.id();
                    return Action::Redraw;
                }
                Action::None
            }
            Key::Enter => self.act(),
            Key::Up => self.scroll_by(-1),
            Key::Down => self.scroll_by(1),
            Key::Esc => {
                self.notice = None;
                Action::Redraw
            }
            _ => Action::None,
        }
    }

    fn on_text_key(&mut self, key: crate::app::Key) -> Action {
        use crate::app::Key;
        match key {
            Key::Char(c) => {
                self.steer.push(c);
                Action::Redraw
            }
            Key::Backspace => {
                self.steer.pop();
                Action::Redraw
            }
            // §B10: multiline by default — Shift-Enter for a newline, Enter to send.
            Key::ShiftEnter => {
                self.steer.push('\n');
                Action::Redraw
            }
            Key::Enter => {
                let text = std::mem::take(&mut self.steer);
                if text.trim().is_empty() {
                    // Not a request. `admit` would refuse it, and a round trip to be told the
                    // obvious is worse than nothing happening.
                    return Action::Redraw;
                }
                self.notice = None;
                self.ask(WindowRequest::Steer(text));
                Action::Redraw
            }
            Key::Esc => {
                // Leaves the field without sending. The draft survives, because losing a
                // half-typed correction to a stray Esc is the kind of thing that stops people
                // using a field at all.
                self.focus = RegionId::RunOutput;
                Action::Redraw
            }
            _ => Action::None,
        }
    }

    fn act(&mut self) -> Action {
        match self.focus {
            RegionId::RunOutput => {
                self.reasoning_expanded = !self.reasoning_expanded;
                Action::Redraw
            }
            RegionId::RunSteer => Action::None,
            _ => Action::None,
        }
    }

    /// Tell the window how far it can scroll, from a driver that knows the terminal size.
    ///
    /// Called with [`scroll_max`] before dispatching a key. See [`WindowApp::scroll_max_hint`].
    pub fn set_scroll_max(&mut self, max: u16) {
        self.scroll_max_hint = max;
    }

    fn scroll_by(&mut self, delta: i32) -> Action {
        // **Pinned means "at the bottom", and the bottom is `scroll_max_hint`.** Resolving the
        // sentinel here rather than in `draw` is what makes `Up` from the pinned position move at
        // all; `u16::MAX - 1` clamps to the bottom just as `u16::MAX` does.
        let current = self.scroll.unwrap_or(self.scroll_max_hint).min(self.scroll_max_hint);
        let next = if delta < 0 {
            current.saturating_sub(delta.unsigned_abs() as u16)
        } else {
            // Scrolling past the end re-pins, so a window on a live run keeps following it.
            current.saturating_add(delta as u16).min(self.scroll_max_hint)
        };
        self.scroll = Some(next);
        Action::Redraw
    }
}

/// Where everything sits.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Chrome {
    pub titlebar: Rect,
    pub identity: Rect,
    pub checkpoint: Rect,
    pub output: Rect,
    /// Inside the output border. **The only part that scrolls.**
    pub output_scroll: Rect,
    pub steer: Rect,
    pub subagents: Rect,
    pub budget: Rect,
    pub scope_memory: Rect,
    pub meetings: Rect,
    pub footer: Rect,
}

pub fn layout(area: Rect) -> Chrome {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(TITLEBAR_H),
            Constraint::Min(3),
            Constraint::Length(FOOTER_H),
        ])
        .split(area);

    let body = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Min(20), Constraint::Length(ASIDE_W)])
        .spacing(1)
        .split(rows[1]);

    let left = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(IDENTITY_H),
            Constraint::Length(CHECKPOINT_H),
            Constraint::Min(3),
            Constraint::Length(STEER_H),
        ])
        .split(body[0]);

    // **Four equal shares, from the first frame.** §6.3: the panels are sized now so the layout
    // does not move when they fill. An aside that laid itself out from the panels that have content
    // would reflow the day the roster lands, which is the churn the rule exists to prevent.
    let aside = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Ratio(1, 4),
            Constraint::Ratio(1, 4),
            Constraint::Ratio(1, 4),
            Constraint::Ratio(1, 4),
        ])
        .split(body[1]);

    let output = left[2];
    Chrome {
        titlebar: rows[0],
        identity: left[0],
        checkpoint: left[1],
        output,
        output_scroll: inner(output),
        steer: left[3],
        subagents: aside[0],
        budget: aside[1],
        scope_memory: aside[2],
        meetings: aside[3],
        footer: rows[2],
    }
}

fn inner(r: Rect) -> Rect {
    Rect {
        x: r.x + 1,
        y: r.y + 1,
        width: r.width.saturating_sub(2),
        height: r.height.saturating_sub(2),
    }
}

/// **ADR-055's condition, and the only place it is applied.**
///
/// E4's second clause, which was filed as *"move the character check to the sink boundary"* and was
/// never built: every string a run's output carries goes through
/// [`crate::chrome::prepare_model_text`] — the display predicate, then the chrome reservation —
/// before anything renders it.
///
/// # Why it is here rather than inside `entry_lines`
///
/// `entry_lines` is shared with the conversation pane, and that pane's `Entry::User` arm is
/// deliberately *not* sanitised: it is `tests/display_sanitiser.rs`'s characterisation of what
/// ratatui filters, and a probe has to use a path where the dependency is the only thing in the way.
/// Sanitising there would make that file vacuous about its own subject for the second time in its
/// history. So the window meets the condition on its **own** boundary, which is also where the
/// condition was granted.
///
/// # What is left alone, and why that is not a gap
///
/// `ToolCall::verb` is `&'static str` and every [`marlowe_view::Metric`] is typed — a count, a diff,
/// an exit code, a `&'static str` state. There is no free-text escape hatch in a §B6 summary, by
/// construction (CONTRACTS §8), so the model-composed strings in a tool line are exactly `target`,
/// the collapsed targets, and the expansion `detail`. Those three are prepared; the rest cannot
/// carry a byte the model chose.
pub fn prepared(entries: &[Entry]) -> Vec<Entry> {
    use marlowe_view::notice::Speech;
    use marlowe_view::ToolLineState;

    let clean = |s: &str| crate::chrome::prepare_model_text(s).into_owned();
    let clean_state = |st: &ToolLineState| match st {
        ToolLineState::Running { elapsed_ms } => ToolLineState::Running { elapsed_ms: *elapsed_ms },
        ToolLineState::Ok(s) => {
            let mut s = s.clone();
            s.detail = s.detail.as_deref().map(clean);
            ToolLineState::Ok(s)
        }
        ToolLineState::Failed(s) => {
            let mut s = s.clone();
            s.detail = s.detail.as_deref().map(clean);
            ToolLineState::Failed(s)
        }
    };

    entries
        .iter()
        .map(|e| match e {
            Entry::User(t) => Entry::User(clean(t)),
            Entry::Said(Speech::Model(t)) => Entry::Said(Speech::Model(clean(t))),
            // A harness notice is a closed vocabulary rendered from typed data (ADR-030), and the
            // harness is allowed to draw chrome. Passing it through the reservation would turn the
            // `⋯` in a §B6 listing into `<U+22EF>` in the one text the harness itself authored.
            Entry::Said(other) => Entry::Said(other.clone()),
            Entry::Reasoning { text, done } => {
                Entry::Reasoning { text: clean(text), done: *done }
            }
            Entry::Compacted { turns } => Entry::Compacted { turns: *turns },
            Entry::Tools(calls) => Entry::Tools(
                calls
                    .iter()
                    .map(|c| {
                        let mut c = c.clone();
                        c.target = clean(&c.target);
                        c.collapsed = c.collapsed.iter().map(|t| clean(t)).collect();
                        c.state = clean_state(&c.state);
                        c
                    })
                    .collect(),
            ),
        })
        .collect()
}

/// Draw the window. The one entry point.
pub fn draw(app: &WindowApp, theme: &Theme, area: Rect, buf: &mut Buffer) {
    if area.width < MIN_COLS || area.height < MIN_ROWS {
        draw_refusal(area, buf, theme);
        return;
    }
    let c = layout(area);
    let tree = app.tree();

    draw_titlebar(app, theme, c.titlebar, buf);
    draw_identity(app, theme, &tree, c.identity, buf);
    draw_checkpoint(app, theme, &tree, c.checkpoint, buf);
    draw_output(app, theme, &tree, &c, buf);
    draw_aside(app, theme, &tree, &c, buf);
    draw_steer(app, theme, &tree, c.steer, buf);
    draw_footer(theme, c.footer, buf);

    if app.confirm.is_some() {
        crate::overlay::draw_window_cancel(app, theme, area, buf);
    }
}

fn draw_refusal(area: Rect, buf: &mut Buffer, theme: &Theme) {
    let msg = format!(
        "a run window needs {MIN_COLS}x{MIN_ROWS}; this terminal is {}x{}. Resize, or watch the \
         run with `marlowe --runs` for the same facts without the grid.",
        area.width, area.height
    );
    Paragraph::new(msg)
        .style(theme.normal())
        .wrap(ratatui::widgets::Wrap { trim: true })
        .render(area, buf);
}

/// The titlebar has no hotkey, so under §B2 it has no border.
fn draw_titlebar(app: &WindowApp, theme: &Theme, area: Rect, buf: &mut Buffer) {
    let v = app.view();
    let left = Line::from(vec![
        Span::styled("marlowe", Style::default().fg(theme.accent())),
        Span::styled("  run ", theme.dim()),
        Span::styled(v.id.clone(), theme.normal()),
    ]);
    Paragraph::new(left).render(area, buf);
}

fn focus_of(app: &WindowApp, id: RegionId) -> FocusLevel {
    if app.focus == id {
        FocusLevel::Focused
    } else {
        FocusLevel::Unfocused
    }
}

/// §6.2: id, status, elapsed, spend against ceiling — plus what cancelling would do.
fn draw_identity(
    app: &WindowApp,
    theme: &Theme,
    tree: &RegionTree,
    area: Rect,
    buf: &mut Buffer,
) {
    let v = app.view();
    let Some(region) = tree.get(RegionId::RunIdentity) else {
        return;
    };
    // The border carries the run's state, and **only** its state (§B2). A run needing the user
    // amber-borders its own panel; a healthy one carries no state colour at all.
    let block = region.block_toned(theme, focus_of(app, RegionId::RunIdentity), v.state.tone());
    let body = block.inner(area);
    block.render(area, buf);

    let spend = format!("{} of {}", micros_usd(v.spend_micros_usd), micros_usd(v.ceiling_micros_usd));
    let spend_style = if v.at_ceiling() {
        theme.style(Tone::Red)
    } else {
        theme.dim()
    };
    let status = Line::from(vec![
        Span::styled(v.state.name().to_string(), theme.style(v.state.tone())),
        Span::styled("   elapsed ", theme.dim()),
        Span::styled(elapsed(v.elapsed_ms), theme.normal()),
        Span::styled("   spend ", theme.dim()),
        Span::styled(spend, spend_style),
    ]);

    // §6.2's *"with the orphan policy the run declared at spawn stated plainly"*. It is on the
    // identity panel as well as in the confirmation, so it is not a surprise at the moment of
    // deciding.
    let policy = Line::from(Span::styled(
        format!("on cancel · {}", v.orphan_policy.plainly()),
        theme.dimmer(),
    ));

    let mut lines = vec![status, policy];
    // A failure's reason belongs where the failure is named, not two panels away.
    if let marlowe_view::RunState::Failed { error } = &v.state {
        lines.push(Line::from(Span::styled(
            marlowe_contract::text::sanitize_line(error).into_owned(),
            theme.style(Tone::Red),
        )));
    }
    Paragraph::new(lines).render(body, buf);
}

/// **The panel that makes this a debugging instrument** (§6.2).
fn draw_checkpoint(
    app: &WindowApp,
    theme: &Theme,
    tree: &RegionTree,
    area: Rect,
    buf: &mut Buffer,
) {
    let v = app.view();
    let Some(region) = tree.get(RegionId::RunCheckpoint) else {
        return;
    };
    let block = region.block(theme, focus_of(app, RegionId::RunCheckpoint));
    let body = block.inner(area);
    block.render(area, buf);

    // Two facts, two lines, never collapsed into one. "What did it finish" and "what would a
    // resume do" are different questions, and the second is the one being debugged.
    let last = match v.checkpoint.last_completed {
        Some(step) => Line::from(vec![
            Span::styled("last completed step · ", theme.dim()),
            Span::styled(format!("step {step}"), theme.normal()),
        ]),
        // **`None` means no checkpoint exists — not step zero.** Session A's words, and the
        // renderer says them rather than inventing a step the run never reached.
        None => Line::from(Span::styled("no checkpoint yet", theme.dim())),
    };
    // **What a resume would do, as the control plane answered it.**
    //
    // `resumable` is a fact `ControlPlane::detail` read off the checkpoint store, not a guess this
    // window made. When it is false the window says the run cannot be resumed **and invents no
    // reason**, because it has none: a run that completed, failed or was cancelled is not
    // resumable, and which of those it was is already on the identity panel above.
    let resume = match (v.checkpoint.resumable, v.checkpoint.last_completed) {
        (true, Some(step)) => Line::from(vec![
            Span::styled("resume · ", theme.dim()),
            Span::styled(format!("from step {step}"), theme.style(Tone::Green)),
        ]),
        // Resumable with no checkpoint yet is a real state — a run accepted and not yet stepped.
        (true, None) => Line::from(vec![
            Span::styled("resume · ", theme.dim()),
            Span::styled("from the beginning", theme.style(Tone::Green)),
        ]),
        (false, _) => Line::from(vec![
            Span::styled("resume · ", theme.dim()),
            Span::styled("not from here", theme.dim()),
        ]),
    };
    Paragraph::new(vec![last, resume]).render(body, buf);
}

/// How many lines the output currently occupies at this width. A pure function of the view.
fn output_lines<'a>(app: &WindowApp, theme: &Theme, width: u16) -> Vec<Line<'a>> {
    // ADR-055's condition, applied once, before anything can render a byte of it.
    let entries = prepared(&app.view().output);
    crate::render::entry_lines(
        &entries,
        theme,
        width,
        app.reasoning_expanded,
        &|call| app.is_expanded(call),
        // A run window has no command palette and no key registry of its own to list, and saying
        // it had one would be the surface inventing a capability. A harness notice that needs a
        // listing renders its own empty table rather than borrowing the main pane's.
        &|n| {
            n.render(&marlowe_view::notice::RenderContext {
                commands: &[],
                keys: &[],
                control: None,
            })
        },
    )
}

fn draw_output(
    app: &WindowApp,
    theme: &Theme,
    tree: &RegionTree,
    c: &Chrome,
    buf: &mut Buffer,
) {
    let Some(region) = tree.get(RegionId::RunOutput) else {
        return;
    };
    let block = region.block(theme, focus_of(app, RegionId::RunOutput));
    block.render(c.output, buf);

    let area = c.output_scroll;
    if area.height == 0 || area.width == 0 {
        return;
    }
    let lines = output_lines(app, theme, area.width);
    let max = (lines.len() as u16).saturating_sub(area.height);
    // **Computed here, not cached.** `scroll` carries `u16::MAX` for "pinned to the bottom", and
    // clamping it needs the width — which only the draw knows. A `Cell` written by frame N and read
    // by frame N+1 would make the flicker check measure convergence rather than purity.
    let offset = app.scroll.unwrap_or(u16::MAX).min(max);

    Paragraph::new(lines)
        .scroll((offset, 0))
        .render(area, buf);
}

/// §6.3's placeholders. **Present, sized, and honest.**
fn draw_aside(app: &WindowApp, theme: &Theme, tree: &RegionTree, c: &Chrome, buf: &mut Buffer) {
    let v = app.view();
    for (id, rect, items) in [
        (RegionId::RunSubagents, c.subagents, &v.subagents),
        (RegionId::RunBudget, c.budget, &v.budget),
        (RegionId::RunScopeMemory, c.scope_memory, &v.scope_memory),
        (RegionId::RunMeetings, c.meetings, &v.meetings),
    ] {
        let Some(region) = tree.get(id) else { continue };
        let block = region.block(theme, focus_of(app, id));
        let body = block.inner(rect);
        block.render(rect, buf);
        Paragraph::new(panel_lines(region.label(), items, theme)).render(body, buf);
    }
}

/// **A placeholder states a fact, never a roadmap** (§6.3).
///
/// `Subagents — none` is true now, stays true for a childless run once the tree exists, and the same
/// panel simply fills. *"Coming in Session C"* would leak the roadmap into the product and become a
/// lie the moment C ships — and it would have to be found and deleted by whoever ships it, which is
/// not a thing anyone remembers to do.
///
/// **Nothing is ever faked to preview the layout.** An empty panel that drew two greyed example rows
/// would be the same family as a green test over a mechanism that never ran.
fn panel_lines<'a>(label: &str, items: &[Item], theme: &Theme) -> Vec<Line<'a>> {
    if items.is_empty() {
        return vec![Line::from(Span::styled(
            format!("{} — none", label.to_lowercase()),
            theme.dimmer(),
        ))];
    }
    items
        .iter()
        .map(|i| Line::from(Span::styled(i.label.clone(), theme.normal())))
        .collect()
}

/// The steer field. **A write** (§6.1, ADR-054).
fn draw_steer(app: &WindowApp, theme: &Theme, tree: &RegionTree, area: Rect, buf: &mut Buffer) {
    let Some(region) = tree.get(RegionId::RunSteer) else {
        return;
    };
    let block = region.block(theme, focus_of(app, RegionId::RunSteer));
    let body = block.inner(area);
    block.render(area, buf);

    // A refusal displaces the draft line rather than sitting beside it: at one row there is no
    // beside, and the refusal is what the user needs to read before typing again.
    if let Some(notice) = &app.notice {
        Paragraph::new(Line::from(Span::styled(
            marlowe_contract::text::sanitize_line(notice).into_owned(),
            theme.style(Tone::Amber),
        )))
        .render(body, buf);
        return;
    }

    let line = if app.steer.is_empty() && app.focus != RegionId::RunSteer {
        // §B2's placeholder register: what the field is for, dim, never an instruction.
        Line::from(Span::styled("steer this run", theme.dimmer()))
    } else {
        let cursor = if app.focus == RegionId::RunSteer { "\u{2588}" } else { "" };
        Line::from(vec![
            Span::styled(app.steer.replace('\n', " "), theme.normal()),
            Span::styled(cursor.to_string(), Style::default().fg(theme.accent())),
        ])
    };
    Paragraph::new(line).render(body, buf);
}

/// The keys a run window answers to. §B8's namespace: Ctrl-modified keys are the footer's.
pub const FOOTER_KEYS: &[(&str, &str)] = &[
    ("^r", "resume"),
    ("^x", "cancel"),
    ("^d", "detach"),
    ("tab", "region"),
];

fn draw_footer(theme: &Theme, area: Rect, buf: &mut Buffer) {
    let mut spans = Vec::new();
    for (i, (key, what)) in FOOTER_KEYS.iter().enumerate() {
        if i > 0 {
            spans.push(Span::styled("   ", theme.dimmer()));
        }
        spans.push(Span::styled((*key).to_string(), Style::default().fg(theme.accent())));
        spans.push(Span::styled(format!(" {what}"), theme.dim()));
    }
    Paragraph::new(Line::from(spans)).render(area, buf);
}

/// The scrollback height a window would need to show everything, for a driver deciding whether a
/// scroll key does anything. Pure over `(view, width, height)`.
pub fn scroll_max(app: &WindowApp, theme: &Theme, area: Rect) -> u16 {
    let c = layout(area);
    let lines = output_lines(app, theme, c.output_scroll.width);
    (lines.len() as u16).saturating_sub(c.output_scroll.height)
}

/// Whether a modifier-free key would be swallowed by the steer field. The driver needs this to
/// decide whether a bare letter is a hotkey or a character.
pub fn typing(app: &WindowApp) -> bool {
    app.focus_is_text()
}

/// The window title, for the terminal's own chrome (OSC 0).
///
/// **Every character of it is the harness's own.** The id is a hex short form and the status word
/// comes from [`marlowe_view::RunState::name`], which is `&'static str` per variant — so a run
/// cannot write its own window title, which is a surface the sanitiser does not cover.
pub fn title(view: &RunView) -> String {
    format!("marlowe · run {} · {}", view.id, view.state.name())
}

/// **The one definition of the command that attaches to a run.** `M3-DESIGN.md` §6.7.
///
/// Two callers need it and they must not disagree: the launcher prints it when it cannot open a
/// window, and the classic CLI prints it because it never can. A second `format!` in the other file
/// is the two-sides-silently-disagree shape applied to the one string whose whole job is being
/// copied correctly — a stale flag name in one of them is a command that fails for the user with no
/// clue why.
///
/// **Quoted when the path has a space in it**, because a Windows install is under `Program Files`
/// more often than not, and an unquoted command the user pastes and watches fail is worse than
/// being told there is none.
pub fn attach_command(run: &str) -> String {
    format!("{} --watch {run}", quoted_exe())
}

/// The same, for steering from outside. §6.6: *"`/runs` and `/steer` survive."*
pub fn steer_command(run: &str) -> String {
    format!("{} --steer {run} <text>", quoted_exe())
}

fn quoted_exe() -> String {
    let exe = std::env::current_exe()
        .map(|p| p.display().to_string())
        .unwrap_or_else(|_| "marlowe".to_string());
    if exe.contains(' ') {
        format!("\"{exe}\"")
    } else {
        exe
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_placeholder_names_the_panel_and_says_none() {
        // §6.3. The two halves that matter: it is a FACT (`none`), and it carries no milestone.
        let l = panel_lines("Subagents", &[], &Theme::default_truecolor());
        let text: String = l[0].spans.iter().map(|s| s.content.to_string()).collect();
        assert_eq!(text, "subagents — none");
        for leak in ["Session", "coming", "soon", "M3", "not built", "TODO"] {
            assert!(!text.contains(leak), "a roadmap leaked into the product: {text}");
        }
    }

    #[test]
    fn the_window_title_cannot_carry_a_byte_the_run_chose_except_its_id() {
        // The terminal's own title bar is outside every sanitiser this crate owns — it is written
        // with OSC 0, which the emulator interprets. So the title is built from a short id and a
        // `&'static str` per state, and there is no arm that interpolates model text.
        let v = view();
        assert_eq!(title(&v), "marlowe · run a1b2c3d4 · running");
    }

    fn view() -> RunView {
        RunView {
            id: "a1b2c3d4".into(),
            state: marlowe_view::RunState::Running,
            parent: None,
            elapsed_ms: 0,
            spend_micros_usd: 0,
            ceiling_micros_usd: 3_000_000,
            spent_tokens: 0,
            granted_tokens: 50_000,
            depth: 0,
            checkpoint: marlowe_view::CheckpointView {
                last_completed: None,
                resumable: true,
            },
            orphan_policy: marlowe_view::OrphanPolicyLabel::Detach,
            pending_steers: 0,
            output: Vec::new(),
            subagents: Vec::new(),
            budget: Vec::new(),
            scope_memory: Vec::new(),
            meetings: Vec::new(),
        }
    }
}
