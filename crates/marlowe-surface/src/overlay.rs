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
    let Some(radius) = &app.session.approval else {
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
        Line::from(Span::styled(radius.headline.clone(), theme.bright())),
        Line::from(""),
        Line::from(Span::styled(
            radius.consequence.clone(),
            theme.style(radius.tier.tone()),
        )),
        Line::from(""),
        Line::from(Span::styled(radius.why.clone(), theme.dim())),
        Line::from(""),
        Line::from(
            radius
                .options
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
