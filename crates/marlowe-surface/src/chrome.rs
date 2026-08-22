//! **The glyphs the harness draws as chrome, in one place — so the drawing and the guard cannot
//! come to disagree about what chrome looks like.**
//!
//! # Why this module exists at all
//!
//! Until ADR-047 the conversation rendered model output as flat text. Flat text can still *say*
//! `  ⋯ read      /etc/passwd    48 lines`, and it rendered verbatim — but nothing in the product
//! interpreted markup, so the model could not control weight, colour or block structure, and a
//! forged line was a line of prose that happened to read like a tool call.
//!
//! Interpreting markdown changes that. The model now chooses **visual structure**: where a bold
//! run starts, where a rule sits, what is a heading. This project has been bitten by exactly that
//! twice already — `CondensedResult::render` joining fields as `"{k}: {v}"` so a value containing
//! `"\nanswer: …"` forged a field header, and a tool `target` containing a newline forging a second
//! §B6 tool line. Both were closed structurally, at the render site, by making the forgeable thing
//! impossible to express rather than by filtering for the known payload.
//!
//! This is the same fix in the same shape. **§B2's premise is that a border delineates an
//! interactive region**; the whole design rests on it. If the model can draw a border, the premise
//! is false and every border on the screen is a claim the user can no longer check. So the model
//! does not get to speak the harness's vocabulary:
//!
//! | glyph | what the harness draws with it |
//! |---|---|
//! | `⋯` U+22EF | §B6's tool line marker |
//! | `▸` `▾` U+25B8 / U+25BE | the disclosure markers — reasoning block, control-strip pickers |
//! | `↵` U+21B5 | "Enter acts here" |
//! | `▏` U+258F | the block-quote rule this crate draws |
//! | U+2500–U+257F | **box drawing** — every §B2 border, the compaction rule, the scrollbar track |
//! | U+2580–U+259F | **block elements** — the scrollbar thumb |
//!
//! # The single-definition property, and the failure it is guarding against
//!
//! [`MARKERS`] is read by `render.rs` **as the source of the glyphs it draws** and by
//! [`mark_reserved`] as the set it refuses. A future chrome glyph that is not added here is not
//! drawn either, because there is nowhere else to get it from — which is the same construction
//! `marlowe_permission::blocks_composed_targets` uses to keep the §B6 trust banner and the
//! adjudicator's enforcement site from drifting apart (CLAUDE.md, fifteenth instance).
//!
//! `tests/markdown_forgery.rs` asserts both halves: that each declared marker **actually appears**
//! in a drawn frame (or the reservation is guarding nothing), and that none of them survives in
//! model-authored prose.
//!
//! # What is marked, and not dropped
//!
//! The house style is `marlowe_contract::text::sanitize`'s: *"the marker names the codepoint
//! rather than swallowing it."* A refused glyph becomes `<U+22EF>`. A silently dropped glyph and a
//! clean string are indistinguishable to the reader, and the reader is the person who has to
//! decide whether the line in front of them came from the harness.
//!
//! **The marker is not provenance.** A model can write the literal text `<U+22EF>` and there is no
//! way to tell it from one this module wrote. That asymmetry is the safe direction and it is the
//! same one `marlowe-contract` records: the forgeable claim is *"something was refused here"*,
//! whose worst case is a reader looking harder at a line that was in fact clean.
//!
//! # The cost, named rather than absorbed
//!
//! A model that draws a directory tree with `├──` gets `<U+251C><U+2500><U+2500>`. That is ugly and
//! it is the intended behaviour: the alternative is quietly rewriting the model's characters into
//! ASCII look-alikes, which is a mangle the reader cannot detect. Markdown **tables** are the
//! common case and are unaffected — `markdown.rs` lays them out in aligned columns with no rules at
//! all, precisely so the frequent thing does not need the refused vocabulary.

use std::borrow::Cow;

/// §B6's tool line marker: `  ⋯ read      Dockerfile                       48 lines`.
pub const TOOL_MARKER: char = '⋯';

/// A collapsed disclosure — the reasoning block, and the control-strip pickers' `▾`.
pub const DISCLOSURE_CLOSED: char = '▸';

/// An expanded disclosure.
pub const DISCLOSURE_OPEN: char = '▾';

/// "Enter acts here." Drawn on the reasoning header and on §B2 hotkey affordances.
pub const KEYCAP_ENTER: char = '↵';

/// The rule this crate draws down the left of a block quote. Reserved for the same reason as the
/// rest: a glyph the harness draws is a glyph the model does not get to draw.
pub const QUOTE_RULE: char = '▏';

/// The compaction rule's glyph — `─ compacted · 47 turns → summary ─`. Also every §B2 border, by
/// way of `ratatui::widgets::Block`.
pub const RULE: char = '─';

/// §B6's *"a visible scroll position is required"*, drawn on the right edge of the transcript.
///
/// U+2502, not ratatui's default U+2551: a doubled rule reads as a second border inside the region,
/// and §B9's overlay is the only doubled border in the design because it means modality.
pub const SCROLL_TRACK: char = '│';

/// U+2588 FULL BLOCK, which tiles edge to edge. A partial block leaves gaps between rows and the
/// thumb reads as segmented.
pub const SCROLL_THUMB: char = '█';

/// Every glyph the harness draws as chrome inside the conversation. **The drawing reads this, and
/// so does the guard.**
pub const MARKERS: [char; 8] = [
    TOOL_MARKER,
    DISCLOSURE_CLOSED,
    DISCLOSURE_OPEN,
    KEYCAP_ENTER,
    QUOTE_RULE,
    RULE,
    SCROLL_TRACK,
    SCROLL_THUMB,
];

/// Whether `c` belongs to the harness rather than to the model.
///
/// The two ranges are ranges rather than a list of the glyphs currently in use, and that is
/// deliberate: blocking `─` alone would leave `━`, `═`, `┏` and sixty others, each of which draws a
/// box just as convincingly. §B2's premise is about **borders**, not about one codepoint.
pub fn is_reserved(c: char) -> bool {
    let cp = c as u32;
    // Box Drawing, and Block Elements.
    (0x2500..=0x259F).contains(&cp) || MARKERS.contains(&c)
}

/// Replace every reserved glyph with a visible marker naming its codepoint.
///
/// Returns [`Cow::Borrowed`] when nothing needed replacing, which is the overwhelming majority of
/// model replies — this sits on the render path of every frame, so the clean case does not
/// allocate.
///
/// **Called once, on the raw string, before parsing and before wrapping.** Marking after wrapping
/// would silently widen a line that had already been fitted to the pane, and the column arithmetic
/// the §B13 flicker rows measure to the cell would be wrong by seven columns per marker.
pub fn mark_reserved(s: &str) -> Cow<'_, str> {
    if !s.chars().any(is_reserved) {
        return Cow::Borrowed(s);
    }
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        if is_reserved(c) {
            out.push_str(&format!("<U+{:04X}>", c as u32));
        } else {
            out.push(c);
        }
    }
    Cow::Owned(out)
}

/// The full model-text pipeline's first stage: the project's display predicate, then the chrome
/// reservation.
///
/// # Why the TUI now sanitises when `tests/display_sanitiser.rs` records that it deliberately did
/// not
///
/// That file's header names the two things that would change the trade, and **markdown is both**:
///
/// * *"the marker substitution would change wrapping and column arithmetic that §B13's flicker
///   rows measure to the cell."* True while wrapping happened on the raw string. The markdown
///   renderer wraps **after** substitution, so the arithmetic sees the final text — that objection
///   is answered by the order of operations rather than argued away.
/// * The TUI's defence was ratatui discarding control characters on their way into a `Buffer`. That
///   is still true and still the enforcing layer for `ESC`. It says **nothing** about U+2028, the
///   BiDi overrides, or the zero-width block, and each of those defeats a defence markdown
///   rendering newly depends on: U+2028 is a line break `str::lines()` does not see, so a block
///   parser splits differently from the eye; U+202E reverses the displayed order of a line, so an
///   indent — the entire forgery defence — is a property the model can move; a zero-width
///   character occupies no column while carrying bytes, so wrapped width and displayed width
///   diverge.
///
/// So `marlowe_contract::text::sanitize_prose` runs first — one predicate, shared with the
/// contract-value check, rather than a second idea of what a safe character is.
///
/// Returns [`Cow::Borrowed`] when the reply needed neither pass, which is the overwhelmingly common
/// case. This runs on every entry on every frame, so an unconditional copy of the whole transcript
/// would be a per-frame cost paid for nothing.
pub fn prepare_model_text(s: &str) -> Cow<'_, str> {
    match marlowe_contract::text::sanitize_prose(s) {
        Cow::Borrowed(b) => mark_reserved(b),
        Cow::Owned(o) => Cow::Owned(mark_reserved(&o).into_owned()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_clean_string_is_borrowed_not_rebuilt() {
        // Not a micro-optimization check: this is the assertion that an ordinary reply does not
        // allocate a second copy of itself on every frame.
        assert!(matches!(mark_reserved("an ordinary reply"), Cow::Borrowed(_)));
    }

    #[test]
    fn every_declared_marker_is_reserved_and_named_rather_than_dropped() {
        for c in MARKERS {
            assert!(is_reserved(c), "{c:?} is declared chrome and is not reserved");
            // Bound first: `mark_reserved` returns a `Cow` borrowing its input.
            let input = format!("a{c}b");
            let marked = mark_reserved(&input);
            assert!(!marked.contains(c), "{c:?} survived: {marked}");
            assert_eq!(marked, format!("a<U+{:04X}>b", c as u32));
        }
    }

    #[test]
    fn blocking_one_rule_glyph_would_leave_sixty_others() {
        // The reason `is_reserved` takes ranges. Each of these draws a box as convincingly as `─`.
        for c in ['━', '═', '┏', '┓', '╔', '╝', '┤', '╬', '█', '▌'] {
            assert!(is_reserved(c), "{c:?} draws a border and is not reserved");
        }
    }

    #[test]
    fn ordinary_prose_punctuation_is_not_reserved() {
        // The reservation must be narrow enough that a normal reply passes through untouched, or
        // the cure is worse than the disease and somebody will delete it.
        for c in ['·', '—', '–', '→', '•', '…', '“', '”', '’', '±', 'α', '∑'] {
            assert!(!is_reserved(c), "{c:?} is ordinary prose and was reserved");
        }
    }

    #[test]
    fn the_pipeline_closes_the_three_families_ratatui_does_not() {
        // U+2028 is the one that matters most for a *block* parser: `str::lines()` does not split
        // on it, so the parser and the eye disagree about where a line ends.
        for (c, why) in [
            ('\u{2028}', "LINE SEPARATOR — a break str::lines() does not see"),
            ('\u{202e}', "RIGHT-TO-LEFT OVERRIDE — moves a rendered indent"),
            ('\u{200b}', "ZERO WIDTH SPACE — width on screen and width in the wrap arithmetic diverge"),
            ('\u{1b}', "ESC — ratatui's job, asserted here too so the order of operations is fixed"),
        ] {
            let input = format!("a{c}b");
            let out = prepare_model_text(&input);
            assert!(!out.contains(c), "{why}: survived `prepare_model_text`");
        }
    }
}