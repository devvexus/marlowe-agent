//! **§B13's rows, re-run against markdown-rich replies, plus §B10's `Y`.**
//!
//! `b13_rendering.rs` proves those rows over the stub's scripted transcript, which is plain prose.
//! ADR-047 put a parser between the model's bytes and the grid, so every one of them has to be
//! re-asked with the parser in the path. **A measurement is scoped to the system it was taken on**
//! — CLAUDE.md's rule about carrying a number across a boundary — and a renderer is a boundary.
//!
//! | row | asserted here |
//! |---|---|
//! | background fills | zero cells with a `bg`, **and zero with `REVERSED`** |
//! | distinct colours | every emitted foreground is in `Theme::declared_colours` |
//! | chrome inside a scroll area | markdown writes nothing outside `conversation_scroll` |
//! | repaint flicker, 120×30 → 240×60 | frame N+1 is a cell-for-cell re-render of frame N |
//! | resize reflows cleanly | away and back returns the identical buffer |
//!
//! Everything is asserted on a drawn `ratatui::Buffer`. An assertion on the `Vec<Span>` the
//! renderer built would be a statement about its own bookkeeping.

mod common;

use marlowe_surface::app::App;
use marlowe_surface::render;
use marlowe_view::notice::Speech;
use marlowe_view::Entry;
use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier};

/// A reply exercising every construct the renderer knows, so the sweeps below are not walking a
/// screen of plain prose and reporting that nothing went wrong.
const RICH: &str = "\
# Retrieval, end to end

The gate is a **build-time artifact**: the binary *refuses* to start without one, and there is
no ~~default~~ fallback weight vector.

## What runs where

1. `fit_gate.py` writes the artifact
2. `cargo build --release` embeds it via `include_str!`
   - the digest is pinned
   - a stale path errors by name
3. the binary reproduces the number

> Filtering does not work. Containment works.

| stage | P95 | share |
|---|---|---|
| lexical | 3.83 ms | 1.78% |
| dense | 41 ms | 19% |

```rust
let gate = include_str!(\"../artifacts/gate.json\");
assert!(gate.len() > 0);
```

Precision is $\\alpha \\times \\beta^2$ over the held-out split, and the integral form
$\\int_0^\\infty e^{-x}dx$ is left as written. See [the note](https://example.invalid/precision).

---

That is the whole mechanism.
";

fn app_saying(text: &str) -> App {
    let producer = marlowe_stub::Session::new();
    let mut view = producer.view().clone();
    view.transcript
        .push(Entry::Said(Speech::Model(text.to_string())));
    App::new(view).expect("the shipped key set has no conflicts")
}

fn rich() -> App {
    app_saying(RICH)
}

/// §B2: *"Never hardcode a background fill."* §B13: zero background fills.
///
/// **And `REVERSED`, which the `bg` check cannot see.** Reverse video is a modifier, so a cell
/// carrying it reports `bg == Color::Reset` while the terminal paints a solid slab — the obvious
/// way to render a code fence, and a §B13 violation that the existing row would have passed. This
/// is the project's own failure family (a property asserted where it is declared rather than where
/// it is seen) and it is why this assertion is two assertions.
#[test]
fn not_one_cell_carries_a_background_or_reverse_video() {
    let app = rich();
    let mut cells = 0usize;
    for (w, h) in common::SIZES {
        let buf = common::frame(&app, w, h);
        for y in 0..h {
            for x in 0..w {
                let cell = buf.cell((x, y)).unwrap();
                cells += 1;
                assert_eq!(
                    cell.bg,
                    Color::Reset,
                    "{w}x{h}: cell ({x},{y}) has background {:?}",
                    cell.bg
                );
                assert!(
                    !cell.modifier.contains(Modifier::REVERSED),
                    "{w}x{h}: cell ({x},{y}) is reverse video, which is a background fill by \
                     another name — it renders as a solid block and reports bg = Reset"
                );
            }
        }
    }
    println!("markdown: 0 fills and 0 reversed cells of {cells} walked");
}

/// §B13: *≤ 1 accent + 3 state + 3 foreground weights*, asserted **by value** against the theme's
/// own declaration — the same construction `b13_rendering.rs` uses, and for the same reason: a
/// count passes happily while every colour on screen is wrong.
///
/// This is where syntax highlighting would fail. Green-for-strings and blue-for-keywords are
/// outside the declared set by construction, and §B2 forbids them for a stronger reason than the
/// count: state colours encode state, so a green token would make the screen say *healthy* about
/// a piece of syntax.
#[test]
fn markdown_emits_no_colour_outside_the_declared_palette() {
    let theme = common::theme();
    let mut allowed: Vec<Color> = theme.declared_colours();
    allowed.push(Color::DarkGray); // the approval overlay's dimming, as in b13_rendering.rs
    let app = rich();
    let mut used: Vec<Color> = Vec::new();
    for (w, h) in common::SIZES {
        let buf = common::frame(&app, w, h);
        for y in 0..h {
            for x in 0..w {
                let fg = buf.cell((x, y)).unwrap().fg;
                if !used.contains(&fg) {
                    used.push(fg);
                }
                assert!(
                    allowed.contains(&fg),
                    "{w}x{h}: cell ({x},{y}) uses {fg:?}, outside one accent, three state colours \
                     and three foreground weights. Markdown gets attributes — bold, italic, \
                     underline — and never a new colour"
                );
            }
        }
    }
    println!("markdown: {} distinct foregrounds, all declared", used.len());
    for c in &used {
        println!("    in use: {c:?}");
    }
}

/// The attributes are the palette, so they have to actually reach the grid. Without this the
/// colour row above passes on a frame where markdown rendered nothing at all.
#[test]
fn the_attributes_reach_the_grid_and_the_source_markers_do_not() {
    let buf = common::frame(&rich(), 160, 45);
    let screen = common::buffer_text(&buf);

    assert!(screen.contains("Retrieval, end to end"), "the reply never rendered:\n{screen}");
    assert!(!screen.contains("**"), "the strong markers survived:\n{screen}");
    assert!(!screen.contains("~~"), "the strikethrough markers survived:\n{screen}");
    assert!(!screen.contains("# "), "a heading kept its hashes:\n{screen}");

    let mut bold = 0;
    let mut italic = 0;
    let mut underlined = 0;
    let mut crossed = 0;
    let mut accent = 0;
    for y in 0..buf.area.height {
        for x in 0..buf.area.width {
            let cell = buf.cell((x, y)).unwrap();
            if cell.symbol() == " " {
                continue;
            }
            if cell.modifier.contains(Modifier::BOLD) {
                bold += 1;
            }
            if cell.modifier.contains(Modifier::ITALIC) {
                italic += 1;
            }
            if cell.modifier.contains(Modifier::UNDERLINED) {
                underlined += 1;
            }
            if cell.modifier.contains(Modifier::CROSSED_OUT) {
                crossed += 1;
            }
            if cell.fg == common::theme().accent() {
                accent += 1;
            }
        }
    }
    assert!(bold > 0, "nothing is bold");
    assert!(italic > 0, "nothing is italic");
    assert!(underlined > 0, "no link text is underlined");
    assert!(crossed > 0, "nothing is struck through");
    assert!(accent > 0, "no heading or bullet took the accent");
    println!(
        "markdown attributes on the grid: {bold} bold, {italic} italic, {underlined} underlined, \
         {crossed} struck, {accent} accent"
    );
}

/// K4: *zero repaint flicker across 120×30 → 240×60*. The property that makes it checkable is that
/// every render is a pure function of `(state, now_ms)`; a parser with a cache keyed on anything
/// that moves would take it away, and would do it silently.
#[test]
fn a_second_render_of_the_same_state_changes_not_one_cell() {
    let app = rich();
    for (w, h) in common::SIZES {
        let mut term = common::terminal(w, h);
        let first = common::draw_into(&mut term, &app);
        let second = common::draw_into(&mut term, &app);
        let changed = common::diff_cells(&first, &second);
        assert!(
            changed.is_empty(),
            "{w}x{h}: re-rendering identical state repainted {} cells, first at {:?}. The markdown \
             renderer is not a pure function of its arguments",
            changed.len(),
            changed.first()
        );
    }
    println!("markdown re-render: 0 cells differ, 120x30 through 240x60");
}

/// §B12: *"This is why focus is a border and not a fill"* — re-asked with markdown in the pane.
///
/// `b13_rendering.rs` proves this over the stub's plain transcript. A renderer that styled by
/// region rather than by content — a code fence filling its rows, a heading painting a bar — would
/// pass that version and fail this one, because the cells it repaints are the ones markdown put
/// there.
#[test]
fn a_focus_change_repaints_no_markdown_cell() {
    for (w, h) in common::SIZES {
        // Only the reply, so the vacuity control below is a statement about markdown rather than
        // about whatever the stub's own transcript happened to scroll into view.
        let producer = marlowe_stub::Session::new();
        let mut view = producer.view().clone();
        view.transcript.clear();
        view.transcript
            .push(Entry::Said(Speech::Model(RICH.to_string())));
        let mut app = App::new(view).expect("the shipped key set has no conflicts");
        app.scroll = Some(0);
        app.on_key(marlowe_surface::app::Key::Esc);
        let mut term = common::terminal(w, h);
        let before = common::draw_into(&mut term, &app);

        app.on_key(marlowe_surface::app::Key::Char('m')); // conversation -> Model
        let after = common::draw_into(&mut term, &app);

        let c = render::layout(Rect::new(0, 0, w, h));
        let r = c.conversation_scroll;
        let hits: Vec<_> = common::diff_cells(&before, &after)
            .into_iter()
            .filter(|(x, y)| *x >= r.x && *x < r.right() && *y >= r.y && *y < r.bottom())
            .collect();
        assert!(
            hits.is_empty(),
            "{w}x{h}: moving focus to Model repainted {} cells inside the markdown transcript, \
             first at {:?}. Focus is a border and a title, not a fill — and rendered markdown is \
             not part of the focus signal",
            hits.len(),
            hits.first()
        );
        // Non-vacuity: the pane must have had markdown in it, and the focus change must have
        // repainted *something* — otherwise this passes on a frame where nothing happened.
        assert!(
            common::buffer_text(&before).contains("Retrieval, end to end"),
            "{w}x{h}: no markdown was on screen"
        );
        assert!(
            !common::diff_cells(&before, &after).is_empty(),
            "{w}x{h}: the focus change repainted nothing at all"
        );
    }
    println!("focus change with markdown on screen: 0 transcript cells repainted, 5 sizes");
}

/// §B12: *"Resize reflows cleanly."* Away and back must return the identical buffer — a parser
/// holding state across widths would not.
#[test]
fn a_resize_round_trip_with_markdown_returns_the_identical_frame() {
    let app = rich();
    let before = common::frame(&app, 140, 40);
    let _ = common::frame(&app, 240, 60);
    let _ = common::frame(&app, 120, 30);
    let after = common::frame(&app, 140, 40);
    assert!(
        common::diff_cells(&before, &after).is_empty(),
        "markdown layout is holding state across resizes"
    );
    println!("markdown resize round trip 140x40 -> 240x60 -> 120x30 -> 140x40: 0 cells differ");
}

/// §B3: *"Chrome that scrolls is a bug."* The renderer wraps, so the renderer decides how many
/// lines a reply occupies; if it wrote past the scroll area it would paint over the pager, which
/// carries the turn count, the compaction count and the lineage depth and lives nowhere else.
#[test]
fn markdown_never_paints_over_the_pager_or_the_border() {
    for (w, h) in common::SIZES {
        let app = app_saying(&format!("{RICH}\n\n{RICH}"));
        let buf = common::frame(&app, w, h);
        let c = render::layout(Rect::new(0, 0, w, h));
        let pager = common::row_text(&buf, c.pager.y);
        assert!(
            pager.contains("turn ") && pager.contains("compacted") && pager.contains("lineage"),
            "{w}x{h}: the pager row reads {pager:?} — a long reply painted over it"
        );
        // And the region's own bottom border is intact.
        let border = common::row_text(&buf, c.conversation.bottom() - 1);
        assert!(border.contains("(c)"), "{w}x{h}: the conversation's hotkey is gone: {border:?}");
    }
    println!("pager and hotkey survive a two-screen markdown reply at 5 sizes");
}

/// The scrollbar is sized from the renderer's own line count, so the count has to be the one that
/// was drawn. A markdown reply produces a different number of lines than its source has, and
/// `App::scroll_max` is the only place those two answers could diverge.
#[test]
fn the_scroll_extent_agrees_with_what_markdown_actually_drew() {
    let app = app_saying(&RICH.repeat(3));
    let theme = common::theme();
    for (w, h) in common::SIZES {
        let buf = common::frame(&app, w, h);
        let c = render::layout(Rect::new(0, 0, w, h));
        let text_w = c.conversation_scroll.width - 2;
        let lines = render::transcript_lines(&app, &theme, text_w);
        let expected = lines
            .len()
            .saturating_sub(c.conversation_scroll.height as usize);
        assert_eq!(
            app.scroll_max.get() as usize,
            expected,
            "{w}x{h}: the scrollbar was sized from {} lines and the renderer drew {}",
            app.scroll_max.get() as usize + c.conversation_scroll.height as usize,
            lines.len()
        );
        // Non-vacuity: the reply must actually overflow, or `expected` is 0 and the assertion holds
        // for a transcript that never needed a scrollbar.
        assert!(expected > 0, "{w}x{h}: the transcript fits, so this proves nothing");
        assert!(!common::buffer_text(&buf).is_empty());
    }
    println!("scroll extent matches the drawn line count at 5 sizes");
}

/// §B10: **`Y` copies the whole transcript as markdown**, and markdown is already the interchange
/// format. Rendering it must not change what comes out.
///
/// The two halves are a control for each other: the pane showing no `**` proves the renderer ran,
/// and the clipboard showing `**` proves it did not reach the copy. Either assertion alone passes
/// on a build where the feature does nothing.
#[test]
fn y_still_copies_the_source_markdown_and_not_the_rendered_form() {
    let mut app = rich();
    let screen = common::buffer_text(&common::frame(&app, 160, 45));
    assert!(
        !screen.contains("**build-time artifact**"),
        "the pane is showing source markers, so the copy assertion below proves nothing:\n{screen}"
    );
    assert!(screen.contains("build-time artifact"), "the reply never rendered:\n{screen}");

    app.copy_transcript();
    let copied = app.pending_copy.clone().expect("Y puts a payload on the clipboard");

    for fragment in [
        "**build-time artifact**",
        "# Retrieval, end to end",
        "1. `fit_gate.py` writes the artifact",
        "> Filtering does not work. Containment works.",
        "| stage | P95 | share |",
        "[the note](https://example.invalid/precision)",
        r"$\int_0^\infty e^{-x}dx$",
    ] {
        assert!(
            copied.contains(fragment),
            "`Y` must yield what the model WROTE, not a re-serialisation of the parse. Missing \
             {fragment:?} from:\n{copied}"
        );
    }
    // And nothing from the rendered form leaked in. `·` alone is not on this list: the stub's own
    // tool-call text uses it as a separator, so it is in the payload for a legitimate reason — the
    // rendered horizontal RULE is a run of them, and that is what would signal a leak.
    for fragment in ["•", "▏", "····"] {
        assert!(
            !copied.contains(fragment),
            "{fragment:?} is a rendering decision and reached the clipboard"
        );
    }
    println!("Y: {} characters of source markdown, unchanged", copied.chars().count());
}

/// The commonest reply in the product has no markup in it at all, and the renderer must be
/// undetectable in that case. Without this, every assertion above is compatible with a renderer
/// that rewrites ordinary prose.
#[test]
fn plain_prose_reaches_the_grid_exactly_as_written() {
    let text = "I read the Dockerfile. The pinned version got dropped when it was rebuilt.";
    let app = app_saying(text);
    let screen = common::buffer_text(&common::frame(&app, 160, 45));
    assert!(screen.contains(text), "plain prose was reflowed or rewritten:\n{screen}");
}
