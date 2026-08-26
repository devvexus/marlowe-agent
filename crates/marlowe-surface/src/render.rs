//! The frame. Six regions, top to bottom, all always present (§B3).
//!
//! # Chrome that scrolls is a bug
//!
//! > Every region's label, hotkey and footer are pinned outside its scroll area. Only content
//! > moves.
//!
//! This is the bug the design is most likely to ship with, so the scroll areas are returned by
//! [`Chrome`] as explicit rects and `tests/pinned_chrome.rs` asserts that no label, hotkey, pager
//! or tab-bar cell falls inside one. The rects exist for the test as much as for the drawing.
//!
//! # Every draw is a pure function of `(state, now_ms)`
//!
//! Nothing here reads a clock — the stub owns the time base (`frame_clock.rs`). That is what lets
//! the acceptance suite render frame N and frame N+1 at chosen times and diff the two buffers cell
//! by cell, turning §B13's "zero flicker" from an opinion into a count.

use marlowe_view::{Ambient, Entry, Tab, Tone};
use ratatui::buffer::Buffer;
use ratatui::layout::{Alignment, Constraint, Direction, Layout, Rect};
use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{
    Clear, Paragraph, Scrollbar, ScrollbarOrientation, ScrollbarState, StatefulWidget, Widget,
};

use crate::app::{App, FOOTER_KEYS, MIN_COLS, MIN_ROWS};
use crate::region::{FocusLevel, Region, RegionId, RegionTree};
use crate::chrome::Ink;
use crate::theme::Theme;

/// Where everything sits, including the scroll areas the pinned-chrome test needs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Chrome {
    pub titlebar: Rect,
    pub control: [Rect; 5],
    pub status: Rect,
    pub conversation: Rect,
    /// Inside the conversation's border, above the pager. **The only part that moves.**
    pub conversation_scroll: Rect,
    /// Pinned inside the border and outside the scroll area (§B6).
    pub pager: Rect,
    pub inspector: Rect,
    /// Pinned. Tabs do not scroll with their content (§B7).
    pub tab_bar: Rect,
    pub inspector_scroll: Rect,
    pub message: Rect,
    pub footer: Rect,
}

/// §B3's vertical budget. Twelve rows of fixed chrome, everything else to the split.
const TITLEBAR_H: u16 = 1;
const CONTROL_H: u16 = 3;
const STATUS_H: u16 = 4;
const MESSAGE_H: u16 = 3;
const FOOTER_H: u16 = 1;

/// §B3: *"the conversation holds no less than 55% of the horizontal split. The inspector is the
/// aside, never the peer."* The mockup's 1.3fr/1fr is 56.5%; this is 58/42 and the acceptance
/// suite asserts the floor rather than the value, so a later tweak cannot cross it unnoticed.
const CONVERSATION_PCT: u16 = 58;

pub fn layout(area: Rect) -> Chrome {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(TITLEBAR_H),
            Constraint::Length(CONTROL_H),
            Constraint::Length(STATUS_H),
            Constraint::Min(3),
            Constraint::Length(MESSAGE_H),
            Constraint::Length(FOOTER_H),
        ])
        .split(area);

    let control = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(17),
            Constraint::Percentage(14),
            Constraint::Percentage(23),
            Constraint::Percentage(29),
            Constraint::Percentage(17),
        ])
        .split(rows[1]);

    let main = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(CONVERSATION_PCT),
            Constraint::Percentage(100 - CONVERSATION_PCT),
        ])
        .spacing(1)
        .split(rows[3]);

    let convo = main[0];
    let convo_inner = inner(convo);
    // The pager is the last row inside the border, and the scroll area stops above it.
    let pager = Rect {
        y: convo_inner.bottom().saturating_sub(1),
        height: 1.min(convo_inner.height),
        ..convo_inner
    };
    let convo_scroll = Rect {
        height: convo_inner.height.saturating_sub(1),
        ..convo_inner
    };

    let inspector = main[1];
    // Two rows, because six tabs with their digits do not fit on one at 42% of 120 columns and a
    // tab bar that truncated would hide a reachable pane.
    let tab_h = 2.min(inspector.height);
    let tab_bar = Rect {
        height: tab_h,
        ..inspector
    };
    let inspector_scroll = Rect {
        y: inspector.y + tab_h,
        height: inspector.height.saturating_sub(tab_h),
        ..inspector
    };

    Chrome {
        titlebar: rows[0],
        control: [control[0], control[1], control[2], control[3], control[4]],
        status: rows[2],
        conversation: convo,
        conversation_scroll: convo_scroll,
        pager,
        inspector,
        tab_bar,
        inspector_scroll,
        message: rows[4],
        footer: rows[5],
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

/// Draw everything. The one entry point.
pub fn draw(app: &App, theme: &Theme, area: Rect, buf: &mut Buffer) {
    if area.width < MIN_COLS || area.height < MIN_ROWS {
        draw_refusal(area, buf, theme);
        return;
    }
    let c = layout(area);
    let tree = app.tree();

    draw_titlebar(app, theme, c.titlebar, buf);
    draw_control(app, theme, &tree, &c, buf);
    draw_status(app, theme, &tree, c.status, buf);
    draw_conversation(app, theme, &tree, &c, buf);
    draw_inspector(app, theme, &tree, &c, buf);
    draw_message(app, theme, &tree, c.message, buf);
    draw_footer(theme, c.footer, buf);

    // Overlays draw LAST, in z-order. An open dropdown extends past the control strip into the
    // status band and the conversation, and drawing it inside draw_control meant the regions below
    // painted straight over it — a menu that was there, then wasn't, with no error anywhere.
    draw_open_dropdown(app, theme, &tree, &c, buf);

    // The live window takes precedence: something is blocked waiting on it.
    if app.view().pending_approval.is_some() {
        crate::overlay::draw_pending_approval(app, theme, area, buf);
    } else if app.view().approval.is_some() {
        crate::overlay::draw_approval(app, theme, area, buf);
    }
}

/// The one open dropdown, if any. §B4: each control-strip region opens a selection list in place —
/// drawn by Marlowe, never an OS widget.
fn draw_open_dropdown(app: &App, theme: &Theme, tree: &RegionTree, c: &Chrome, buf: &mut Buffer) {
    let strip = &app.view().control;
    let cells: [(RegionId, &marlowe_view::Picker); 5] = [
        (RegionId::Model, &strip.model),
        (RegionId::Profile, &strip.profile),
        (RegionId::Session, &strip.session),
        (RegionId::Workspace, &strip.workspace),
        (RegionId::Autonomy, &strip.autonomy),
    ];
    for (i, (id, picker)) in cells.iter().enumerate() {
        if App::control_of(*id) != app.picker_open {
            continue;
        }
        if let Some(region) = tree.get(*id) {
            draw_dropdown(theme, region, picker, c.control[i], app.hover_option, buf);
        }
    }
}

/// §B11: *"Below the minimum, the TUI does not render a degraded layout. It prints one line naming
/// the current and required size, and offers the classic CLI. **A broken grid is worse than an
/// honest refusal.**"*
fn draw_refusal(area: Rect, buf: &mut Buffer, theme: &Theme) {
    let msg = format!(
        "marlowe needs {MIN_COLS}x{MIN_ROWS}; this terminal is {}x{}. Resize, or run `marlowe \
         --classic` for the same commands without the grid.",
        area.width, area.height
    );
    Paragraph::new(msg)
        .style(theme.normal())
        .wrap(ratatui::widgets::Wrap { trim: true })
        .render(area, buf);
}

/// The titlebar has no hotkey, so under §B2 it has no border.
fn draw_titlebar(app: &App, theme: &Theme, area: Rect, buf: &mut Buffer) {
    let session = app.view().control.session.value();
    let left = Line::from(vec![
        Span::styled("* ", Ink::Accent.style(theme)),
        Span::styled(format!("marlowe — {session}"), theme.normal()),
    ]);
    // One definition, shared with the OS window title — see `App::run_counts`.
    let (running, due) = app.run_counts();
    Paragraph::new(left).render(area, buf);

    // Under --diagnostic the titlebar carries ground truth instead of the ambient counts: raw
    // mode, colour tier, and a live keystroke counter. A session that renders and animates while
    // ignoring every key is indistinguishable from a working one until this line exists.
    let right = match &app.diagnostic {
        Some(d) => Line::from(Span::styled(
            format!(
                "{d} keys={} mouse={} last={} focus={:?} state={}",
                app.keys_seen,
                app.mouse_seen,
                app.last_key,
                app.focus,
                app.view().status.state.name(),
            ),
            Ink::Accent.style(theme),
        )),
        None => Line::from(Span::styled(
            format!("{running} runs · {due} due today"),
            Ink::Dim.style(theme),
        )),
    };
    Paragraph::new(right)
        .alignment(Alignment::Right)
        .render(area, buf);
}

fn focus_of(app: &App, id: RegionId) -> FocusLevel {
    if app.focus == id {
        FocusLevel::Focused
    } else if app.hover == Some(id) {
        // Below focus, never instead of it: the focused region keeps the full accent even while
        // the pointer is somewhere else, so moving the mouse never reads as focus moving.
        FocusLevel::Hovered
    } else {
        FocusLevel::Unfocused
    }
}

fn draw_control(app: &App, theme: &Theme, tree: &RegionTree, c: &Chrome, buf: &mut Buffer) {
    let strip = &app.view().control;
    let cells: [(RegionId, &marlowe_view::Picker); 5] = [
        (RegionId::Model, &strip.model),
        (RegionId::Profile, &strip.profile),
        (RegionId::Session, &strip.session),
        (RegionId::Workspace, &strip.workspace),
        (RegionId::Autonomy, &strip.autonomy),
    ];
    for (i, (id, picker)) in cells.iter().enumerate() {
        let Some(region) = tree.get(*id) else { continue };
        let area = c.control[i];
        let focus = focus_of(app, *id);
        // Autonomy is the one that carries state colour (§B4) — it is the single control that
        // changes what Marlowe may do without asking.
        let block = if *id == RegionId::Autonomy {
            region.block_toned(theme, focus, picker.autonomy_tone())
        } else {
            region.block(theme, focus)
        };
        let text = inner(area);
        block.render(area, buf);
        let value = Line::from(vec![
            Span::styled(
                picker.value(),
                if focus == FocusLevel::Focused {
                    theme.bright()
                } else {
                    theme.normal()
                },
            ),
        ]);
        Paragraph::new(value).render(text, buf);
        Paragraph::new(Line::from(Span::styled(
            crate::chrome::DISCLOSURE_OPEN.to_string(),
            Ink::Dim.style(theme),
        )))
            .alignment(Alignment::Right)
            .render(text, buf);
    }
}

/// A selection list drawn in place — by Marlowe, never an OS widget (§B4).
/// Where an open dropdown's popup sits, given the control cell it hangs from.
///
/// **Public because the mouse hit-test needs the same answer.** Geometry computed in two places is
/// geometry that can disagree, and the failure mode is a click that selects the row above the one
/// it is visibly over — which reads as flakiness rather than as a bug. One function, both callers.
///
/// Option `i` occupies row `rect.y + 1 + i`: the popup carries a border, so its first option is one
/// row inside its own top edge.
pub fn dropdown_rect(anchor: Rect, options: usize, screen_h: u16) -> Rect {
    let h = options as u16 + 2;
    Rect {
        x: anchor.x,
        y: anchor.bottom(),
        width: anchor.width,
        height: h.min(screen_h.saturating_sub(anchor.bottom())),
    }
}

fn draw_dropdown(
    theme: &Theme,
    region: &Region,
    picker: &marlowe_view::Picker,
    anchor: Rect,
    hovered: Option<usize>,
    buf: &mut Buffer,
) {
    let area = dropdown_rect(anchor, picker.options.len(), buf.area.height);
    Clear.render(area, buf);
    let block = region.block(theme, FocusLevel::Focused);
    let list = inner(area);
    block.render(area, buf);
    for (i, opt) in picker.options.iter().enumerate() {
        let y = list.y + i as u16;
        if y >= list.bottom() {
            break;
        }
        // §B2 and §B14: **no background fill to signal selection.** The marker and the accent
        // foreground carry it, which is also what keeps it legible on a light terminal.
        // Selection and hover are different facts and read differently: selection keeps the
        // marker and the full accent, hover only lifts the text. **Still no background fill** —
        // §B2, and a fill would repaint the row on every pixel of mouse travel.
        let (marker, style) = if i == picker.selected {
            ("›", Ink::Accent.style(theme))
        } else if hovered == Some(i) {
            (" ", Ink::Hover.style(theme))
        } else {
            (" ", Ink::Dim.style(theme))
        };
        buf.set_stringn(
            list.x,
            y,
            format!("{marker} {opt}"),
            list.width as usize,
            style,
        );
    }
}

fn draw_status(app: &App, theme: &Theme, tree: &RegionTree, area: Rect, buf: &mut Buffer) {
    let Some(region) = tree.get(RegionId::Status) else {
        return;
    };
    let band = &app.view().status;
    let focus = focus_of(app, RegionId::Status);
    let block = region.block_toned(theme, focus, band.state.tone());
    let text = inner(area);
    block.render(area, buf);

    // ADR-021's meter: 6 cells wide, 2 rows tall, at the left of the band.
    let meter_area = Rect {
        width: crate::meter::CELLS_WIDE,
        height: crate::meter::CELLS_TALL.min(text.height),
        ..text
    };
    crate::meter::render(
        &app.meter_frame(),
        meter_area,
        buf,
        Style::default().fg(Ink::of_tone(band.state.tone()).color(theme)),
    );

    // One column of padding on the right, so a right-aligned figure never runs flush into the
    // border and read as truncated.
    let body = Rect {
        x: text.x + crate::meter::CELLS_WIDE + 2,
        width: text
            .width
            .saturating_sub(crate::meter::CELLS_WIDE + 3),
        ..text
    };

    // Degradation lives here, not in the corner of the input line (§B5).
    let (detail, detail_style) = match band.degraded {
        Some(path) => (path.headline().to_string(), Ink::Amber.style(theme)),
        None => (band.detail.clone(), Ink::Dim.style(theme)),
    };
    let left = vec![
        Line::from(Span::styled(
            band.state.name(),
            Style::default()
                .fg(Ink::of_tone(band.state.tone()).color(theme))
                .add_modifier(Modifier::BOLD),
        )),
        Line::from(Span::styled(detail, detail_style)),
    ];
    Paragraph::new(left).render(body, buf);

    let figures: Vec<Line> = band
        .figures
        .iter()
        .map(|f| Line::from(Span::styled(f.clone(), Ink::Dim.style(theme))))
        .collect();
    Paragraph::new(figures)
        .alignment(Alignment::Right)
        .render(body, buf);
}

fn draw_conversation(app: &App, theme: &Theme, tree: &RegionTree, c: &Chrome, buf: &mut Buffer) {
    let Some(region) = tree.get(RegionId::Conversation) else {
        return;
    };
    let focus = focus_of(app, RegionId::Conversation);
    region.block(theme, focus).render(c.conversation, buf);

    // A visible scroll position is required (§B6) — a thin scrollbar on the right edge of the
    // transcript, not an overlay hint. It takes a column, and a second column is left as a gutter:
    // prose that runs flush into the bar reads as truncated even when it is not.
    let text_area = Rect {
        width: c.conversation_scroll.width.saturating_sub(2),
        ..c.conversation_scroll
    };
    let lines = transcript_lines(app, theme, text_area.width);
    let total = lines.len();
    let view = text_area.height as usize;
    let max_off = total.saturating_sub(view);
    // Hand the clamp back to the app. Only the renderer knows how many wrapped lines the transcript
    // occupies at this width, and without that number `move_within` was scrolling to `u16::MAX - 1`
    // and being clamped straight back to the bottom — so the first notch up moved nothing and the
    // next 65,533 moved nothing either. Scrolling looked dead while every unit test passed, because
    // the tests asserted that `scroll` *changed*, not that the view *moved*.
    app.scroll_max.set(max_off.min(u16::MAX as usize) as u16);
    let offset = match app.scroll {
        None => max_off,
        Some(o) => (o as usize).min(max_off),
    };
    let visible: Vec<Line> = lines
        .into_iter()
        .skip(offset)
        .take(view)
        .collect();
    Paragraph::new(visible).render(text_area, buf);

    if total > view {
        // The glyphs come from `crate::chrome`, which is also the set model prose may not contain —
        // so the model cannot draw a second scrollbar down the middle of its own reply.
        let track = crate::chrome::SCROLL_TRACK.to_string();
        let thumb = crate::chrome::SCROLL_THUMB.to_string();
        let mut state = ScrollbarState::new(max_off).position(offset);
        StatefulWidget::render(
            Scrollbar::new(ScrollbarOrientation::VerticalRight)
                .begin_symbol(None)
                .end_symbol(None)
                // ratatui's default vertical track is `║` U+2551 — a doubled box-drawing rule,
                // which reads as a second border inside the region. §B9's overlay is the only
                // doubled border in the design, and it means modality.
                .track_symbol(Some(&track))
                // U+2588 FULL BLOCK, which tiles edge to edge. A partial block or a box-drawing
                // glyph leaves gaps between rows and the thumb reads as segmented.
                .thumb_symbol(&thumb)
                .track_style(Ink::Structure.style(theme))
                // The scroll position is not a state, so it is not amber. It is structure, and
                // structure is the accent's role (§B2).
                .thumb_style(Ink::Accent.style(theme)),
            c.conversation_scroll,
            buf,
            &mut state,
        );
    }

    // Pinned, and carrying what no other region has (§B6).
    let p = app.view().pager;
    Paragraph::new(Line::from(Span::styled(
        format!(
            "turn {} · {} compacted · lineage {} deep",
            p.turn, p.compacted, p.lineage
        ),
        Ink::Dim.style(theme),
    )))
    .alignment(Alignment::Right)
    .render(c.pager, buf);
}

/// The transcript, wrapped to `width`.
///
/// Wrapping happens here rather than in `Paragraph` because the scrollbar needs the true line
/// count. A scrollbar sized from unwrapped lines lies by exactly the amount of prose on screen.
pub fn transcript_lines<'a>(app: &App, theme: &Theme, width: u16) -> Vec<Line<'a>> {
    entry_lines(
        &app.view().transcript,
        theme,
        width,
        app.reasoning_expanded,
        &|call| app.is_expanded(call),
        &|n| crate::commands::render_notice(app.view(), n),
    )
}

/// **The one definition of what a transcript looks like**, over the entries alone.
///
/// The conversation pane and a run window (`M3-DESIGN.md` §6) both draw the same
/// [`marlowe_view::Entry`] vocabulary, and §6.4 is explicit that the window must not reimplement the
/// look: *"Two definitions of a border is the two-sides-silently-disagree shape applied to pixels."*
/// So the three pieces of **looking-at** state this needs arrive as parameters rather than as an
/// `App`, and there is exactly one body.
///
/// `notice` is a closure because rendering a harness [`marlowe_view::Notice`] needs the command and
/// key registries, which a run window does not have — it has no command palette, and saying it has
/// one would be the surface inventing a capability. Each caller supplies the context it actually
/// holds.
///
/// **This does not sanitise `Entry::User`, deliberately.** That path is the main pane's
/// characterisation of what ratatui filters — see `tests/display_sanitiser.rs`, whose header records
/// that a probe has to use a path where the dependency is the only thing in the way. The run window
/// meets ADR-055's condition by preparing its entries *before* they arrive here; putting a sanitiser
/// in this arm would make that file vacuous about its own subject a second time.
#[allow(clippy::too_many_arguments)]
pub fn entry_lines<'a>(
    entries: &[marlowe_view::Entry],
    theme: &Theme,
    width: u16,
    reasoning_expanded: bool,
    is_expanded: &dyn Fn(&marlowe_view::ToolCall) -> bool,
    notice: &dyn Fn(&marlowe_view::Notice) -> Vec<String>,
) -> Vec<Line<'a>> {
    let mut out: Vec<Line> = Vec::new();
    let w = width.max(20) as usize;
    for entry in entries {
        match entry {
            // **Weight 1 — the terminal's own foreground.** What the user typed is not chrome and
            // not the machine's own noise; it is the other half of the conversation.
            //
            // This rendered at `Ink::Dim.style(theme)`, weight 2, which is the same weight the reasoning
            // block uses — so a question the user asked and a chain of thought they did not write
            // were the same colour. Reported live as *"user messages are indistinguishable from
            // thinking"*, and the theme had already said otherwise: `speech`'s own doc comment
            // reads *"the user's words stay in the terminal's foreground (weight 1) and Marlowe's
            // take this"*. The renderer was contradicting the scheme it was built on.
            //
            // The three weights now say three different things: the user is weight 1, the model's
            // reasoning is weight 2, and Marlowe's voice is the accent tint.
            Entry::User(text) => {
                for l in wrap(text, w) {
                    out.push(Line::from(Span::styled(l, Style::default())));
                }
                out.push(Line::from(""));
            }
            Entry::Said(speech) => {
                // Both halves render in the same colour — the user must not see a seam between the
                // model talking and the harness talking. The TYPE records who composed it; the
                // frame does not, because that is not the user's problem.
                //
                // The one place colour marks WHO is speaking rather than state. White prose read
                // as terminal output rather than as somebody talking.
                let base = Ink::Speech.style(theme);
                match speech {
                    // **Model prose is markdown (ADR-047).** It always was; until ADR-047 it was
                    // drawn flat, so a reply built out of headings, lists and code arrived as one
                    // paragraph with punctuation in it.
                    marlowe_view::Speech::Model(t) => {
                        out.extend(crate::markdown::render_prose(t, w, theme, base));
                    }
                    // **Harness notices are NOT markdown, and that is deliberate.** They are a
                    // closed vocabulary (ADR-030) rendered from typed data — a `/help` listing, a
                    // refusal, a copy confirmation. None of them contains markup, so interpreting
                    // it buys nothing, and interpreting it would mean an `*` in a path or a `_` in
                    // a flag name silently becoming emphasis in the one text the harness itself
                    // authored. They also skip the chrome reservation, because the harness is
                    // allowed to draw chrome and the model is not.
                    marlowe_view::Speech::Harness(n) => {
                        for raw in notice(n) {
                            for l in wrap(&raw, w) {
                                out.push(Line::from(Span::styled(l, base)));
                            }
                        }
                    }
                }
                out.push(Line::from(""));
            }
            // **The thinking block.** Collapsed by default, one line, expandable with `t`.
            //
            // It appears the instant the first reasoning chunk lands, which is the point: a
            // reasoning model spends most of a turn here, and without this the screen is static
            // while the machine is working. §B5's rule is that motion means Marlowe is working —
            // this is the part of the work that was invisible.
            Entry::Reasoning { text, done } => {
                let expanded = reasoning_expanded;
                // The glyphs come from `crate::chrome`, which is also the set model prose may not
                // contain. One definition: a marker that is drawn is a marker that is reserved,
                // and there is nowhere else to get one from.
                let marker = if expanded {
                    crate::chrome::DISCLOSURE_OPEN
                } else {
                    crate::chrome::DISCLOSURE_CLOSED
                };
                let key = crate::chrome::KEYCAP_ENTER;
                let head = if *done {
                    format!("{marker} thought for {} characters   {key}", text.len())
                } else {
                    // Live: the count moves, so the line itself reports progress.
                    format!("{marker} thinking… {} characters   {key}", text.len())
                };
                out.push(Line::from(Span::styled(head, Ink::Dim.style(theme))));
                if expanded {
                    // **Markdown here too, and only when EXPANDED.**
                    //
                    // Reasoning is where a model puts its working, and its working is where the
                    // equations are. Rendering it flat meant the one place a derivation actually
                    // lives was the one place it stayed raw.
                    //
                    // Collapsed, this costs nothing: the head line is a character COUNT, so the
                    // parser never runs on the path that draws 99% of frames. That matters because
                    // reasoning is the highest-volume text in the product -- a reasoning model can
                    // spend most of a turn here -- and K4 budgets 150 ms to first frame.
                    //
                    // The base stays `dim`. A reasoning block is not what Marlowe said (ADR-030):
                    // it does not carry the persona and it must not read as a conclusion, so
                    // markdown gives it structure without promoting it to speech.
                    for line in crate::markdown::render_prose(
                        text,
                        w.saturating_sub(2),
                        theme,
                        Ink::Dim.style(theme),
                    ) {
                        let mut spans = vec![Span::styled("  ".to_string(), Ink::Dim.style(theme))];
                        spans.extend(line.spans);
                        out.push(Line::from(spans));
                    }
                }
                out.push(Line::from(""));
            }
            Entry::Compacted { turns } => {
                let r = crate::chrome::RULE;
                let text = format!("{r} compacted · {turns} turns → summary {r}");
                let pad = w.saturating_sub(text.chars().count()) / 2;
                out.push(Line::from(Span::styled(
                    format!("{}{}", " ".repeat(pad), text),
                    Ink::Accent.style(theme).add_modifier(Modifier::DIM),
                )));
                out.push(Line::from(""));
            }
            Entry::Tools(calls) => {
                for call in calls {
                    out.push(tool_line(call, theme, w));
                    if is_expanded(call) {
                        out.extend(expansion(call, theme, w));
                    }
                }
                out.push(Line::from(""));
            }
        }
    }
    out
}

/// §B6's one line: `⋯ verb  target ............ summary`.
///
/// # The target is model-composed, and it is sanitised
///
/// CLAUDE.md's own example: *a tool `target` containing a newline forged a second §B6 tool line —
/// a call the model never made.* The classic CLI closed that at its site; the TUI was covered
/// **incidentally**, by ratatui discarding control characters on their way into a `Buffer`.
///
/// ADR-047 measured what ratatui does and does not discard, and the tag block U+E0000–U+E007F
/// **reaches the grid** — a full invisible ASCII alphabet, inside the line that tells the user what
/// the agent just did. `marlowe_contract::text::is_renderable` refuses it, so the target goes
/// through the same predicate the approval prompt uses.
///
/// `Shape::Line`, not `Shape::Prose`: this is one line, and a `\n` in a target is the attack rather
/// than a formatting nuisance. That is the same distinction `marlowe-contract` draws, drawn here
/// for the same reason.
fn tool_line<'a>(call: &marlowe_view::ToolCall, theme: &Theme, w: usize) -> Line<'a> {
    use marlowe_view::ToolLineState;
    // Consecutive same-verb calls collapse: six reads become `⋯ read  6 files`.
    let target = if call.collapsed.is_empty() {
        marlowe_contract::text::sanitize_line(&call.target).into_owned()
    } else {
        format!("{} files", call.collapsed.len() + 1)
    };
    let left = format!(
        "  {} {:<9} {}",
        crate::chrome::TOOL_MARKER,
        call.verb,
        target
    );
    let (right, right_style) = match &call.state {
        // Live lines animate in place with elapsed time. Never scrolled in and then cleared.
        ToolLineState::Running { elapsed_ms } => (
            format!("{}.{}s", elapsed_ms / 1000, (elapsed_ms % 1000) / 100),
            Style::default().fg(Ink::Amber.color(theme)),
        ),
        ToolLineState::Ok(s) => (s.render(), Ink::Dim.style(theme)),
        ToolLineState::Failed(s) => (s.render(), Style::default().fg(Ink::Red.color(theme))),
    };
    let gap = w
        .saturating_sub(left.chars().count())
        .saturating_sub(right.chars().count());
    Line::from(vec![
        Span::styled(left, Ink::Dim.style(theme)),
        Span::raw(" ".repeat(gap)),
        Span::styled(right, right_style),
    ])
}

fn expansion<'a>(call: &marlowe_view::ToolCall, theme: &Theme, w: usize) -> Vec<Line<'a>> {
    use marlowe_view::ToolLineState;
    let detail = match &call.state {
        ToolLineState::Ok(s) | ToolLineState::Failed(s) => s.detail.clone(),
        ToolLineState::Running { .. } => None,
    };
    let mut out = Vec::new();
    for t in &call.collapsed {
        // Same reason as `tool_line`: these are the targets it collapsed away.
        let t = marlowe_contract::text::sanitize_line(t);
        out.push(Line::from(Span::styled(format!("      {t}"), Ink::Dim.style(theme))));
    }
    if let Some(d) = detail {
        // A failure detail is genuinely multi-line — it is a stack trace or a compiler error — so
        // `Shape::Prose` here and `Shape::Line` above. Two destinations, two correct answers.
        let d = marlowe_contract::text::sanitize_prose(&d);
        for raw in d.lines() {
            for l in wrap(raw, w.saturating_sub(6)) {
                out.push(Line::from(Span::styled(
                    format!("      {l}"),
                    Ink::Red.style(theme),
                )));
            }
        }
    }
    out
}

fn wrap(text: &str, w: usize) -> Vec<String> {
    let mut out = Vec::new();
    for para in text.split('\n') {
        let mut line = String::new();
        for word in para.split_whitespace() {
            let extra = if line.is_empty() { 0 } else { 1 };
            if line.chars().count() + extra + word.chars().count() > w && !line.is_empty() {
                out.push(std::mem::take(&mut line));
            }
            if !line.is_empty() {
                line.push(' ');
            }
            line.push_str(word);
        }
        out.push(line);
    }
    out
}

/// Where each inspector tab's label sits, so it can be clicked and hovered.
///
/// **Shared with the mouse hit-test, and locked to the drawing by a test.** The tab bar is not a
/// region — it has no border, because each tab carries its own hotkey rather than the bar carrying
/// one (§B2) — so it is not in the region tree and `region_at` cannot find it. This is the whole
/// geometry, in one place, rather than a second copy that agrees today.
///
/// Three tabs per row, because six with their digits do not fit across 42% of 120 columns. Each
/// occupies `"{digit} "` plus `"{title}  "`, and the returned rect covers the digit and the title
/// but not the trailing gap — clicking the space between two tabs should do nothing rather than
/// pick whichever one is nearer.
pub fn tab_rects(tab_bar: Rect) -> Vec<(Tab, Rect)> {
    let mut out = Vec::new();
    let mut x = [tab_bar.x, tab_bar.x];
    for (i, tab) in Tab::ALL.iter().enumerate() {
        let row = if i < 3 { 0usize } else { 1 };
        let w = 2 + tab.title().chars().count() as u16;
        out.push((
            *tab,
            Rect {
                x: x[row],
                y: tab_bar.y + row as u16,
                width: w,
                height: 1,
            },
        ));
        x[row] += w + 2; // the two trailing spaces
    }
    out
}

fn draw_inspector(app: &App, theme: &Theme, tree: &RegionTree, c: &Chrome, buf: &mut Buffer) {
    // The inspector has no single hotkey — each tab has one — so under §B2 it has no border.
    let mut spans: Vec<Span> = Vec::new();
    let mut line1: Vec<Span> = Vec::new();
    for (i, tab) in Tab::ALL.iter().enumerate() {
        let active = *tab == app.tab;
        let target = if i < 3 { &mut spans } else { &mut line1 };
        target.push(Span::styled(
            format!("{} ", tab.digit()),
            Ink::Accent.style(theme),
        ));
        target.push(Span::styled(
            format!("{}  ", tab.title()),
            if active {
                theme.bright()
            } else if app.hover_tab == Some(*tab) {
                // Hover sits below selection here exactly as it does on regions: the active tab
                // keeps its brightened label, and the pointer only lifts the others.
                Ink::Hover.style(theme)
            } else {
                Ink::Dim.style(theme)
            },
        ));
    }
    Paragraph::new(vec![Line::from(spans), Line::from(line1)]).render(c.tab_bar, buf);

    let items = crate::inspector::items(app.view(), app.tab);
    // **The pane scrolls, by whole items.** Without this, a window shorter than the pane's content
    // simply stopped drawing at the fold: the Runs tab's later items existed, were focusable, were
    // reachable by their own hotkeys, and were invisible. An item you can select and cannot see is
    // worse than one that is not there.
    //
    // Whole items rather than rows, because an item is a bordered region (§B2) and half a border
    // with its label scrolled off is not a region any more — it is a rendering fault.
    let view = c.inspector_scroll.height;
    let max_off = {
        // How many items fit if the LAST one is flush with the bottom; everything before that is
        // how far it can scroll.
        let (mut acc, mut fit) = (0u16, 0usize);
        for item in items.iter().rev() {
            let h = item.lines.len() as u16 + 2;
            if acc + h > view {
                break;
            }
            acc += h;
            fit += 1;
        }
        items.len().saturating_sub(fit)
    };
    app.inspector_scroll_max.set(max_off as u16);
    let off = (app.inspector_scroll as usize).min(max_off);

    let mut y = c.inspector_scroll.y;
    let mut last_drawn = off;
    for (i, item) in items.iter().enumerate().skip(off) {
        let id = RegionId::Item(app.tab(), i);
        let Some(region) = tree.get(id) else { continue };
        let h = item.lines.len() as u16 + 2;
        if y + h > c.inspector_scroll.bottom() {
            break;
        }
        last_drawn = i;
        let area = Rect {
            x: c.inspector_scroll.x,
            y,
            width: c.inspector_scroll.width,
            height: h,
        };
        let focus = if app.focus == id {
            FocusLevel::Focused
        } else if app.hover == Some(id) {
            // Hover outranks Inactive: a dimmed item the pointer is over must acknowledge the
            // pointer, or the user concludes it is not clickable.
            FocusLevel::Hovered
        } else if item.tone == Tone::Dim {
            // Dimming is load-bearing: an event needing nothing is dimmed to near-invisible so the
            // eye goes to the ones that do (§B2, §B7).
            FocusLevel::Inactive
        } else {
            FocusLevel::Unfocused
        };
        let block = region.block_toned(theme, focus, item.tone);
        let text = inner(area);
        block.render(area, buf);
        let body: Vec<Line> = if item.editable {
            let shown = if app.steer.is_empty() {
                item.lines
                    .first()
                    .map(|(l, _)| l.clone())
                    .unwrap_or_default()
            } else {
                app.steer.clone()
            };
            let style = if app.steer.is_empty() {
                Ink::Dim.style(theme)
            } else {
                theme.normal()
            };
            vec![Line::from(Span::styled(shown, style))]
        } else {
            item.lines
                .iter()
                .map(|(l, tone)| {
                    // An item the user needs nothing from is dimmed to near-invisible with the
                    // THIRD weight, not the second (§B2, §B7). Using one dim for both is how a
                    // dense screen stops telling the eye where to look.
                    let style = if focus == FocusLevel::Inactive && *tone == Tone::Dim {
                        Ink::Dimmer.style(theme)
                    } else {
                        Ink::of_tone(*tone).style(theme)
                    };
                    Line::from(Span::styled(l.clone(), style))
                })
                .collect()
        };
        Paragraph::new(body).render(text, buf);
        y += h + 1;
    }
    app.inspector_last_visible.set(last_drawn as u16);
}

fn draw_message(app: &App, theme: &Theme, tree: &RegionTree, area: Rect, buf: &mut Buffer) {
    let Some(region) = tree.get(RegionId::Message) else {
        return;
    };
    let focus = focus_of(app, RegionId::Message);
    let block = region.block(theme, focus);
    let text = inner(area);
    block.render(area, buf);

    // The placeholder tracks the status band (§B8) — that is how barge-in is made visible without
    // a second indicator.
    let (body, style) = if app.input.is_empty() {
        (
            app.view().status.state.placeholder().to_string(),
            Ink::Dim.style(theme),
        )
    } else {
        (app.input.replace('\n', " ⏎ "), theme.normal())
    };
    Paragraph::new(Line::from(vec![
        Span::styled("› ", Ink::Accent.style(theme)),
        Span::styled(body, style),
    ]))
    .render(text, buf);

    // A copy confirmation takes the ambient slot until the next keystroke. OSC 52 cannot be
    // acknowledged, so this line is the only evidence the user gets that anything happened; it
    // outranks the spend counters for the second or two it is up.
    let a: Ambient = app.view().ambient;
    let ambient = if let Some(notice) = &app.notice {
        Line::from(Span::styled(
            notice.clone(),
            Ink::Accent.style(theme),
        ))
    } else {
        Line::from(vec![
            // Context pressure is a colour, not a bar (§B8).
            Span::styled(
                format!("{}%  ", a.fill_pct),
                Ink::of_tone(a.context_tone()).style(theme),
            ),
            Span::styled(
                format!("${}.{:02}  ", a.spend_cents / 100, a.spend_cents % 100),
                Ink::Dim.style(theme),
            ),
            Span::styled(format!("{}m", a.elapsed_min), Ink::Dim.style(theme)),
        ])
    };
    Paragraph::new(ambient)
        .alignment(Alignment::Right)
        .render(text, buf);

    // Slash autocomplete, inline, with descriptions (§B10).
    if let Some(prefix) = app.input.strip_prefix('/') {
        if !prefix.contains(' ') {
            draw_autocomplete(theme, prefix, app.completion, area, buf);
        }
    }
}

fn draw_autocomplete(theme: &Theme, prefix: &str, selected: usize, anchor: Rect, buf: &mut Buffer) {
    let hits = crate::commands::complete(prefix);
    if hits.is_empty() {
        return;
    }
    let h = (hits.len() as u16).min(6);
    let area = Rect {
        x: anchor.x + 2,
        y: anchor.y.saturating_sub(h),
        width: anchor.width.saturating_sub(4),
        height: h,
    };
    Clear.render(area, buf);
    for (i, cmd) in hits.iter().take(h as usize).enumerate() {
        let line = format!("/{:<10} {}", cmd.name, cmd.description);
        buf.set_stringn(
            area.x,
            area.y + i as u16,
            line,
            area.width as usize,
            if i == selected {
                Ink::Accent.style(theme)
            } else {
                Ink::Dim.style(theme)
            },
        );
    }
}

/// One line of global keys, always the same, never context-dependent (§B8). No hotkey of its own,
/// so no border.
fn draw_footer(theme: &Theme, area: Rect, buf: &mut Buffer) {
    let mut spans = Vec::new();
    for (key, what) in FOOTER_KEYS.iter().take(FOOTER_KEYS.len() - 1) {
        spans.push(Span::styled(
            format!("{key} "),
            Ink::Accent.style(theme),
        ));
        spans.push(Span::styled(format!("{what}   "), Ink::Dim.style(theme)));
    }
    Paragraph::new(Line::from(spans)).render(area, buf);
    let (key, what) = FOOTER_KEYS[FOOTER_KEYS.len() - 1];
    Paragraph::new(Line::from(vec![
        Span::styled(format!("{key} "), Ink::Accent.style(theme)),
        Span::styled(what, Ink::Dim.style(theme)),
    ]))
    .alignment(Alignment::Right)
    .render(area, buf);
}
