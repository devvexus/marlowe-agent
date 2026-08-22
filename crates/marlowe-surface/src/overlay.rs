//! §B9's approval overlay. **The one place a border is drawn outside the region contract.**
//!
//! §B2 says every bordered region carries a hotkey on its bottom border, and `region.rs` makes
//! that unconstructable otherwise. This overlay is bordered and does not: its keys are stated in
//! its body, because it is modal and there is nothing to *jump focus to*.
//!
//! It lives in its own file so `tests/b13_region_contract.rs` can allowlist **this file** rather
//! than `render.rs`. Exempting the whole drawing module would blind the grep to the one place a
//! stray decorative border would actually appear — the same argument `determinism_guard.rs` makes
//! for refusing directory-level exemptions.

use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, BorderType, Clear, Paragraph, Widget};

use crate::app::App;
use crate::theme::Theme;

fn inner(r: Rect) -> Rect {
    Rect {
        x: r.x + 1,
        y: r.y + 1,
        width: r.width.saturating_sub(2),
        height: r.height.saturating_sub(2),
    }
}

/// §B9. **In a design where every region is bordered, a border no longer signals modality.**
///
/// So the overlay dims the entire frame behind it, uses a doubled border in its risk tier's
/// colour, and centres itself. It is the only element permitted to dim the rest of the screen.
///
/// **The dim is a foreground rewrite, never a fill.** That is not a stylistic choice — §B13 asks
/// for zero background fills and `tests/no_background_fill.rs` walks every cell with the overlay
/// up. A `bg`-based scrim would fail it, and would also be the full-cell repaint §B12 forbids.
pub fn draw_approval(app: &App, theme: &Theme, area: Rect, buf: &mut Buffer) {
    let Some(radius) = &app.view().approval else {
        return;
    };

    for y in area.top()..area.bottom() {
        for x in area.left()..area.right() {
            if let Some(cell) = buf.cell_mut((x, y)) {
                let s = cell.style();
                cell.set_style(
                    s.remove_modifier(Modifier::BOLD)
                        .add_modifier(Modifier::DIM)
                        .fg(ratatui::style::Color::DarkGray),
                );
            }
        }
    }

    let w = 64.min(area.width.saturating_sub(4));
    let lines: Vec<Line> = vec![
        Line::from(Span::styled(radius.headline(), theme.bright())),
        Line::from(""),
        Line::from(Span::styled(
            radius.consequence(),
            theme.style(radius.tier.tone()),
        )),
        Line::from(""),
        Line::from(Span::styled(radius.why(), theme.dim())),
        Line::from(""),
        Line::from(
            radius
                .keys()
                .iter()
                .flat_map(|(k, what)| {
                    let key = match k {
                        '\n' => "↵".to_string(),
                        '\u{1b}' => "esc".to_string(),
                        c => c.to_string(),
                    };
                    [
                        Span::styled(
                            format!("{key} "),
                            Style::default().fg(theme.tone(radius.tier.tone())),
                        ),
                        Span::styled(format!("{what}    "), theme.normal()),
                    ]
                })
                .collect::<Vec<_>>(),
        ),
    ];
    let h = lines.len() as u16 + 2;
    let overlay = Rect {
        x: area.x + (area.width.saturating_sub(w)) / 2,
        y: area.y + (area.height.saturating_sub(h)) / 2,
        width: w,
        height: h.min(area.height),
    };
    Clear.render(overlay, buf);
    let tier = Style::default().fg(theme.tone(radius.tier.tone()));
    let block = Block::bordered()
        .border_type(BorderType::Double)
        .border_style(tier)
        .title(Span::styled("approval", tier));
    let text = inner(overlay);
    block.render(overlay, buf);
    Paragraph::new(lines).render(text, buf);
}

/// The **live** approval window: yes, no, or no-with-a-reason.
///
/// # Why this is not `draw_approval`
///
/// That one renders §B9's [`marlowe_view::approval::BlastRadius`], which the live path cannot
/// build: `Effect` has no fetch variant and `Ceiling` has no producer until the trust ledger at
/// M6. See `PendingApproval`'s header. Rather than invent an effect and a ceiling to reuse the
/// richer overlay, this draws what the permission layer actually knows and **prints what it does
/// not** — `ceiling unknown` is on screen, not omitted.
///
/// **There is no dismiss key.** The daemon is blocked on the answer, so a window that could be
/// closed without sending one would hang the turn with nothing explaining why.
pub fn draw_pending_approval(app: &App, theme: &Theme, area: Rect, buf: &mut Buffer) {
    let Some(p) = &app.view().pending_approval else {
        return;
    };

    for y in area.top()..area.bottom() {
        for x in area.left()..area.right() {
            if let Some(cell) = buf.cell_mut((x, y)) {
                let s = cell.style();
                cell.set_style(
                    s.remove_modifier(Modifier::BOLD)
                        .add_modifier(Modifier::DIM)
                        .fg(ratatui::style::Color::DarkGray),
                );
            }
        }
    }

    // **Wider, and it WRAPS.** The first version was a fixed 64 with no wrap, so
    // `web · https://a-long-host.example.com/some/path` lost its tail off the right edge — and
    // the scope line is the one thing the user is actually deciding about. Silently truncating
    // it is the same defect as `blast_radius` dropping a target it could not stringify, one
    // layer up: an approval prompt that does not show the whole target is a prompt you cannot
    // trust, and it looks complete either way.
    let w = 76.min(area.width.saturating_sub(4));
    let mut lines: Vec<Line> = vec![
        Line::from(Span::styled(p.headline(), theme.bright())),
        Line::from(""),
        Line::from(Span::styled(p.detail(), theme.dim())),
        Line::from(""),
    ];

    match &app.decline_reason {
        // Typing a reason. The cursor is a block so it is obvious the window is taking input
        // rather than waiting on one of the three keys.
        Some(text) => {
            lines.push(Line::from(Span::styled("declining — why?", theme.normal())));
            lines.push(Line::from(Span::styled(format!("{text}\u{2588}"), theme.bright())));
            lines.push(Line::from(""));
            lines.push(Line::from(vec![
                Span::styled(format!("{} ", crate::chrome::KEYCAP_ENTER), theme.bright()),
                Span::styled("send    ", theme.normal()),
                Span::styled("esc ", theme.bright()),
                Span::styled("back to the question", theme.normal()),
            ]));
        }
        None => lines.push(Line::from(vec![
            Span::styled("y ", theme.bright()),
            Span::styled("yes    ", theme.normal()),
            Span::styled("n ", theme.bright()),
            Span::styled("no    ", theme.normal()),
            Span::styled("o ", theme.bright()),
            Span::styled("other — no, with a reason", theme.normal()),
        ])),
    }

    let h = lines.len() as u16 + 2;
    let overlay = Rect {
        x: area.x + (area.width.saturating_sub(w)) / 2,
        y: area.y + (area.height.saturating_sub(h)) / 2,
        width: w,
        height: h.min(area.height),
    };
    Clear.render(overlay, buf);
    // Amber, not red: this is a question, not a failure. Red is for a conflict or something
    // irreversible, and a fetch that has not happened yet is neither.
    let tone = if p.reversible { marlowe_view::Tone::Amber } else { marlowe_view::Tone::Red };
    let border = Style::default().fg(theme.tone(tone));
    let block = Block::bordered()
        .border_type(BorderType::Double)
        .border_style(border)
        .title(Span::styled("approval", border));
    let text = inner(overlay);
    block.render(overlay, buf);
    Paragraph::new(lines)
        .wrap(ratatui::widgets::Wrap { trim: false })
        .render(text, buf);
}
