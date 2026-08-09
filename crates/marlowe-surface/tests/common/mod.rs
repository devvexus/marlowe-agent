//! Shared rig for the §B13 suite.
//!
//! Every test here renders into a `TestBackend` buffer at a chosen size and a chosen `now_ms`.
//! That is possible only because the surface reads no clock — see `frame_clock.rs`. It is what
//! turns "zero flicker" from an opinion into a cell count.

// Each test binary compiles this module and uses a different subset of it.
#![allow(dead_code)]

use marlowe_stub::Session;
use marlowe_surface::app::{Action, App, Key};
use marlowe_surface::render;
use marlowe_surface::Theme;
use marlowe_view::Produce;
use ratatui::backend::TestBackend;
use ratatui::buffer::Buffer;
use ratatui::Terminal;

/// §B13 verifies flicker across this range. The low end is §B11's minimum; the high end is a
/// 4K-ish terminal at a small font.
pub const SIZES: [(u16, u16); 5] = [(120, 30), (140, 40), (160, 45), (200, 50), (240, 60)];

/// A producer and a surface, wired the way a real driver wires them.
///
/// **C2d made this necessary and that is the point.** M1's tests held one object: `App` owned a
/// `Session` and a keystroke mutated it in place, so a test could assert on `app.session` straight
/// after a key. There is now a boundary in between — the surface emits an [`marlowe_view::Intent`],
/// the producer applies it, and a new view comes back — and a test that wants to observe the
/// result has to cross the same boundary the product does.
///
/// A test that could still reach through would be a test that proved nothing about the split.
pub struct Rig {
    pub producer: Session,
    pub app: App,
}

impl Rig {
    pub fn new() -> Self {
        let producer = Session::new();
        let app = App::new(producer.view().clone()).expect("the shipped key set has no conflicts");
        Self { producer, app }
    }

    /// Publish the producer's current view to the surface.
    pub fn sync(&mut self) {
        self.app.update(self.producer.view().clone());
    }

    /// Advance the producer and republish.
    pub fn tick(&mut self, now_ms: u64) {
        self.producer.tick(now_ms);
        self.sync();
    }

    /// One keystroke, through the whole loop: dispatch, drain the requests, apply them, republish.
    pub fn key(&mut self, key: Key, now_ms: u64) -> Action {
        let action = self.app.on_key(key);
        self.settle(now_ms);
        action
    }

    /// Apply whatever the surface asked for, then republish. Refusals are surfaced, never dropped
    /// — a rig that swallowed an `IntentError` would hide the one failure mode `Produce::apply`
    /// exists to make visible.
    pub fn settle(&mut self, now_ms: u64) {
        for intent in self.app.drain_intents() {
            self.producer
                .apply(intent.clone())
                .unwrap_or_else(|e| panic!("the producer refused {intent:?}: {e}"));
        }
        self.producer.tick(now_ms);
        self.sync();
    }

    /// Drive the band to a state, the way `/state` does.
    pub fn force_state(&mut self, state: marlowe_view::StatusState, now_ms: u64) {
        self.producer.force_state(state, now_ms);
        self.producer.tick(now_ms);
        self.sync();
    }

    pub fn tab(&mut self, tab: marlowe_view::Tab) {
        self.app.tab = tab;
    }
}

/// A surface over a fresh scripted view, for tests that only render.
pub fn app() -> App {
    App::new(Session::new().view().clone()).expect("the shipped key set has no conflicts")
}

pub fn rig() -> Rig {
    Rig::new()
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
