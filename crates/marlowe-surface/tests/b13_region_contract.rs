//! §B13: **every bordered region has a label and a hotkey — 100%, asserted by test.**
//!
//! This is one of the three rows most likely to be skipped, and it is the one the whole design
//! rests on. It is asserted in two independent ways, because either alone would pass while the
//! property was gone:
//!
//! 1. **The tree.** Every region in the tree has a non-empty label and a typeable hotkey, and no
//!    two claim the same key. `Region` cannot be constructed otherwise, so this half is really a
//!    check that the tree is the thing being drawn.
//! 2. **The grep.** No `Block::bordered` or `Borders::` outside `region.rs` and `overlay.rs`.
//!    Without this, someone draws a decorative box directly and half 1 goes green anyway — which
//!    is exactly the failure mode "asserted by test, not by inspection" was written against.

mod common;

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use marlowe_stub::{Session, Tab};
use marlowe_surface::region::RegionTree;

#[test]
fn every_region_in_the_tree_has_a_label_and_a_hotkey() {
    let mut session = Session::new();
    let mut checked = 0;
    // Every pane, not only the visible one — the inspector's items are regions too (§B7).
    for tab in Tab::ALL {
        session.tab = tab;
        let tree = RegionTree::build(&session);
        for r in tree.regions() {
            assert!(
                !r.label().trim().is_empty(),
                "{:?} has no label. §B2: the label says what the region holds",
                r.id()
            );
            assert!(
                !r.hotkey().is_control() && !r.hotkey().is_whitespace(),
                "{:?} has no reachable hotkey. §B2: a region with no hotkey has no border",
                r.id()
            );
            assert_eq!(r.hotkey_label(), format!("({})", r.hotkey()));
            checked += 1;
        }
    }
    println!("bordered regions with a label and a hotkey: {checked}/{checked} (100%)");
}

#[test]
fn no_two_regions_visible_together_claim_the_same_key() {
    let mut session = Session::new();
    for tab in Tab::ALL {
        session.tab = tab;
        let tree = RegionTree::build(&session);
        let mut seen: BTreeMap<char, String> = BTreeMap::new();
        for r in tree.regions() {
            if let Some(prev) = seen.insert(r.hotkey(), r.label().to_string()) {
                panic!(
                    "on the {} tab, '{}' is claimed by both {prev:?} and {:?}. One of those \
                     borders is lying about how to reach it",
                    tab.title(),
                    r.hotkey(),
                    r.label()
                );
            }
        }
    }
}

/// The grep. Crude and enforced, per HP10: *a crude enforced mechanism beats an elegant unenforced
/// one.*
#[test]
fn no_border_is_drawn_outside_the_region_contract() {
    /// `region.rs` defines the contract, so it names the constructor in order to own it.
    ///
    /// `overlay.rs` is §B9's approval overlay — bordered, modal, and deliberately without a bottom-
    /// border hotkey because there is nothing to jump focus *to*. It lives in its own file
    /// precisely so this allowlist can name **it** rather than `render.rs`: exempting the drawing
    /// module would blind the grep to the one place a decorative border would actually appear.
    const ALLOWED: &[&str] = &["region.rs", "overlay.rs", "b13_region_contract.rs"];

    let mut offenders = Vec::new();
    for path in sources() {
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        if ALLOWED.contains(&name.as_str()) {
            continue;
        }
        let src = fs::read_to_string(&path).unwrap_or_default();
        for (n, line) in src.lines().enumerate() {
            let t = line.trim_start();
            if t.starts_with("//") || t.starts_with('*') {
                continue;
            }
            if line.contains("Block::bordered") || line.contains("Borders::") {
                offenders.push(format!("{}:{}: {}", path.display(), n + 1, line.trim()));
            }
        }
    }
    assert!(
        offenders.is_empty(),
        "a border is drawn outside the region contract. §B2: a border delineates an INTERACTIVE \
         region and every one carries a label and a hotkey. Route it through Region::block, or if \
         it is genuinely modal chrome, put it beside the approval overlay and defend the \
         allowlist entry:\n  {}",
        offenders.join("\n  ")
    );
}

fn sources() -> Vec<PathBuf> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let mut out = Vec::new();
    collect(&root.join("src"), &mut out);
    collect(&root.join("tests"), &mut out);
    out.sort();
    out
}

fn collect(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    let mut paths: Vec<_> = entries.filter_map(Result::ok).map(|e| e.path()).collect();
    paths.sort();
    for p in paths {
        if p.is_dir() {
            collect(&p, out);
        } else if p.extension().is_some_and(|e| e == "rs") {
            out.push(p);
        }
    }
}

/// §B3: *"the conversation holds no less than 55% of the horizontal split. The inspector is the
/// aside, never the peer."*
#[test]
fn the_conversation_never_drops_below_55_percent_of_the_split() {
    for (w, h) in common::SIZES {
        let c = marlowe_surface::render::layout(ratatui::layout::Rect::new(0, 0, w, h));
        let split = c.conversation.width + c.inspector.width;
        let pct = c.conversation.width as f64 * 100.0 / split as f64;
        println!("{w}x{h}: conversation {pct:.1}% of the split");
        assert!(
            pct >= 55.0,
            "at {w}x{h} the conversation is {pct:.1}% of the split; §B3 sets the floor at 55% and \
             the inspector is the aside, never the peer"
        );
    }
}
