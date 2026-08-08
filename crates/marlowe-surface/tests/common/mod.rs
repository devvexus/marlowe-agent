//! Shared rig for the §B13 suite.
//!
//! Every test here renders into a `TestBackend` buffer at a chosen size and a chosen `now_ms`.
//! That is possible only because the surface reads no clock — see `frame_clock.rs`. It is what
//! turns "zero flicker" from an opinion into a cell count.

// Each test binary compiles this module and uses a different subset of it.
#![allow(dead_code)]

use marlowe_stub::Session;
use marlowe_surface::app::App;
use marlowe_surface::render;
use marlowe_surface::Theme;
use ratatui::backend::TestBackend;
use ratatui::buffer::Buffer;
use ratatui::Terminal;

/// §B13 verifies flicker across this range. The low end is §B11's minimum; the high end is a
/// 4K-ish terminal at a small font.
pub const SIZES: [(u16, u16); 5] = [(120, 30), (140, 40), (160, 45), (200, 50), (240, 60)];

pub fn app() -> App {
    App::new(Session::new()).expect("the shipped key set has no conflicts")
}

pub fn theme() -> Theme {
    Theme::default_truecolor()
}

/// Render one frame and hand back the buffer.
pub fn frame(app: &App, w: u16, h: u16) -> Buffer {
    let mut term = Terminal::new(TestBackend::new(w, h)).unwrap();
    term.draw(|f| render::draw(app, &theme(), f.area(), f.buffer_mut()))
        .unwrap();
    term.backend().buffer().clone()
}

/// Render into a persistent terminal so the *next* draw is a real differential update.
pub fn terminal(w: u16, h: u16) -> Terminal<TestBackend> {
    Terminal::new(TestBackend::new(w, h)).unwrap()
}

pub fn draw_into(term: &mut Terminal<TestBackend>, app: &App) -> Buffer {
    term.draw(|f| render::draw(app, &theme(), f.area(), f.buffer_mut()))
        .unwrap();
    term.backend().buffer().clone()
}

/// Cells that differ between two buffers of the same size.
pub fn diff_cells(a: &Buffer, b: &Buffer) -> Vec<(u16, u16)> {
    let mut out = Vec::new();
    for y in 0..a.area.height {
        for x in 0..a.area.width {
            let (pa, pb) = (a.cell((x, y)), b.cell((x, y)));
            if pa != pb {
                out.push((x, y));
            }
        }
    }
    out
}

/// Every non-blank string in a buffer row, for tests that assert on what is drawn where.
pub fn row_text(buf: &Buffer, y: u16) -> String {
    (0..buf.area.width)
        .map(|x| {
            buf.cell((x, y))
                .map(|c| c.symbol())
                .unwrap_or(" ")
                .to_string()
        })
        .collect()
}

pub fn buffer_text(buf: &Buffer) -> String {
    (0..buf.area.height)
        .map(|y| row_text(buf, y))
        .collect::<Vec<_>>()
        .join("\n")
}
