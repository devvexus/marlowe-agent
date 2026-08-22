"""Revert one item-2 bound by exact string replacement, then restore.

Same discipline as mutate.py: one bound at a time, and the question is which named test
notices. A bound whose reversion fails nothing is a bound nobody is checking.

Usage: python mutate2.py <file> <marker-name>
       python mutate2.py --restore <file>
"""
import sys
import shutil
import pathlib

BAK = ".item2-mutation-backup"

# name -> (file-relative-path, find, replace)
MUTATIONS = {
    # The title/description cap at the extract() chokepoint.
    "title_cap": (
        "crates/marlowe-extract/src/lib.rs",
        "Ok((_, result)) => result.map(enforce_metadata_caps),",
        "Ok((_, result)) => result,",
    ),
    # CSV row retention: put back the unbounded push.
    "csv_rows": (
        "crates/marlowe-extract/src/plain.rs",
        "            if rows.len() < keep {\n                rows.push(std::mem::take(&mut row));\n            } else {\n                row.clear();\n            }",
        "            rows.push(std::mem::take(&mut row));",
    ),
    # CSV column cap on the newline branch.
    "csv_cols": (
        "crates/marlowe-extract/src/plain.rs",
        "            c if c == delim => {\n                if row.len() < MAX_CSV_COLS {\n                    row.push(std::mem::take(&mut field));\n                } else {\n                    field.clear();\n                }\n            }",
        "            c if c == delim => row.push(std::mem::take(&mut field)),",
    ),
    # CSV single-field cap.
    "csv_field": (
        "crates/marlowe-extract/src/plain.rs",
        "    if field.len() < MAX_CSV_FIELD_BYTES {\n        field.push(c);\n    }",
        "    field.push(c);",
    ),
    # xlsx: the row cap, which is the multiplying term in the amplification.
    "xlsx_row": (
        "crates/marlowe-extract/src/office.rs",
        "if s.is_empty() || row.len() >= MAX_SHEET_COLS {",
        "if s.is_empty() {",
    ),
    # xlsx: the shared-string byte budget.
    "xlsx_shared": (
        "crates/marlowe-extract/src/office.rs",
        "                    if retained_bytes + entry.len() > MAX_SHARED_BYTES {\n                        out.push(String::new());\n                    } else {\n                        retained_bytes += entry.len();\n                        out.push(entry);\n                    }",
        "                    out.push(entry);",
    ),
    # ── ADR-047: markdown and LaTeX in the conversation pane ─────────────────────────────────
    # The render site itself: put the flat wrap back.
    "md_render": (
        "crates/marlowe-surface/src/render.rs",
        "                        out.extend(crate::markdown::render_prose(t, w, theme, base));",
        "                        for l in wrap(t, w) {\n                            out.push(Line::from(Span::styled(l, base)));\n                        }",
    ),
    # The chrome reservation: let model prose speak the harness's vocabulary again.
    "md_chrome": (
        "crates/marlowe-surface/src/chrome.rs",
        "    match marlowe_contract::text::sanitize_prose(s) {\n        Cow::Borrowed(b) => mark_reserved(b),\n        Cow::Owned(o) => Cow::Owned(mark_reserved(&o).into_owned()),\n    }",
        "    Cow::Borrowed(s)",
    ),
    # Reserve only the listed glyphs, not the box-drawing and block-element ranges.
    "md_ranges": (
        "crates/marlowe-surface/src/chrome.rs",
        "    (0x2500..=0x259F).contains(&cp) || MARKERS.contains(&c)",
        "    let _ = cp;\n    MARKERS.contains(&c)",
    ),
    # Draw the markdown horizontal rule with the compaction marker's own glyph.
    "md_rule": (
        "crates/marlowe-surface/src/markdown.rs",
        '            "·".repeat(width),',
        '            crate::chrome::RULE.to_string().repeat(width),',
    ),
    # Render a code span as reverse video -- a background fill that reports bg = Reset.
    "md_reversed": (
        "crates/marlowe-surface/src/markdown.rs",
        "    fn code(&self) -> Style {\n        Style::default().fg(Color::Reset)\n    }",
        "    fn code(&self) -> Style {\n        Style::default().fg(Color::Reset).add_modifier(Modifier::REVERSED)\n    }",
    ),
    # Remove the look-ahead bound that closed the quadratic.
    "md_budget": (
        "crates/marlowe-surface/src/markdown.rs",
        "    len.saturating_mul(16).saturating_add(4_096)",
        "    let _ = len;\n    usize::MAX",
    ),
    # Make the LaTeX sub/superscript mapping best-effort instead of all-or-nothing.
    "md_latex_partial": (
        "crates/marlowe-surface/src/latex.rs",
        "        out.push(table.iter().find(|(k, _)| *k == c).map(|(_, v)| *v)?);",
        "        if let Some((_, v)) = table.iter().find(|(k, _)| *k == c) {\n            out.push(*v);\n        }",
    ),
    # Remove the OUTPUT-side chrome check in the maths renderer.
    "md_latex_output": (
        "crates/marlowe-surface/src/latex.rs",
        "    if spaced.chars().any(crate::chrome::is_reserved) {\n        return None;\n    }",
        "",
    ),
    # Remove the currency guard, so `$5 and $10` is treated as an equation.
    "md_currency": (
        "crates/marlowe-surface/src/markdown.rs",
        "    if open[0] == '$' && !crate::latex::looks_like_inline_maths(&content) {\n        return None;\n    }",
        "",
    ),
    # The §B6 tool line's model-composed target: put the raw clone back.
    "md_toolline": (
        "crates/marlowe-surface/src/render.rs",
        "        marlowe_contract::text::sanitize_line(&call.target).into_owned()",
        "        call.target.clone()",
    ),
    # Make `Y` hand back a re-serialisation of the parse rather than the source.
    "md_copy_source": (
        "crates/marlowe-surface/src/clipboard.rs",
        '                out.push_str(&format!("**Marlowe:** {t}\\n\\n"));',
        '                out.push_str(&format!("**Marlowe:** {}\\n\\n", t.replace("**", "").replace("# ", "")));',
    ),
    # -- ADR-049: the quarantined reader's request shape --------------------------------
    # Send `tools: []` again on the hosted path. Layer 1's empty ExposedSet renders to exactly
    # that, and it is what returned HTTP 400 on every quarantined read.
    "wire_tools_hosted": (
        "crates/marlowe-openrouter/src/driver.rs",
        """if let Some(tools) = marlowe_provider::wire::tools_field(self.tool_schema(tools)) {
            body["tools"] = tools;
        }""",
        """body["tools"] = self.tool_schema(tools);""",
    ),
    # The same on the local path.
    "wire_tools_local": (
        "crates/marlowe-provider/src/ollama.rs",
        """if let Some(tools) = crate::wire::tools_field(self.tool_schema(tools)) {
            body["tools"] = tools;
        }""",
        """body["tools"] = self.tool_schema(tools);""",
    ),
    # Put the orphaned `tool` message back on the hosted path: a reply to a call that does not
    # exist, which is the second half of the 400.
    "wire_orphan_hosted": (
        "crates/marlowe-openrouter/src/driver.rs",
        """        marlowe_provider::wire::unorphan_tool_messages(&mut messages);
""",
        """""",
    ),
    # And on the local path, where the same shape left the chat template's think block open.
    "wire_orphan_local": (
        "crates/marlowe-provider/src/ollama.rs",
        """        crate::wire::unorphan_tool_messages(&mut messages);
""",
        """""",
    ),
    # Collapse the five refusal categories back to the one sentence that reported all of them.
    "refusal_one_string": (
        "crates/marlowe-loop/src/engine.rs",
        """format!("{} · {}", p.summary, refusal.note())""",
        """format!("{} · the content could not be condensed within the contract. It was NOT placed in this window.", p.summary)""",
    ),
    # Drop the contract-exhaustion arm, so a reader that answered badly is reported as one
    # that never ran -- 'do not retry' where narrowing the document is what works.
    "refusal_contract_arm": (
        "crates/marlowe-loop/src/engine.rs",
        """                    LoopOutcome::Failed { error } if error.starts_with(CONTRACT_UNMET) => {
                        QuarantineRefusal::ContractUnmet
                    }
""",
        "",
    ),
    # html: the block buffer bound -- the HTML memory peak.
    "html_blocks": (
        "crates/marlowe-extract/src/html.rs",
        "        if self.block_chars >= crate::MAX_TEXT_CHARS {\n            return;\n        }\n        self.block_chars += text.len();",
        "",
    ),
}


def main():
    if sys.argv[1] == "--restore":
        for p in pathlib.Path(".").rglob("*" + BAK):
            shutil.copy(p, str(p)[: -len(BAK)])
            p.unlink()
            print(f"restored {str(p)[:-len(BAK)]}")
        return

    name = sys.argv[1]
    rel, find, repl = MUTATIONS[name]
    p = pathlib.Path(rel)
    text = p.read_text(encoding="utf-8")
    if text.count(find) != 1:
        raise SystemExit(
            f"MUTATION {name} DID NOT APPLY: found {text.count(find)} matches, expected 1. "
            "The code moved -- fix the pattern rather than reporting a clean mutation."
        )
    # **A SECOND MUTATION OF THE SAME FILE USED TO EAT ITS OWN BACKUP.** `shutil.copy` over an
    # existing `.bak` replaced the pristine copy with the already-mutated one, so `--restore`
    # handed back a file that still carried the first mutation -- silently, and reporting
    # "restored". Two of this session's five bounds live in one file each with another, and the
    # leak was caught by grepping the source afterwards rather than by anything the tool said.
    #
    # Refused rather than made smarter: stacking mutations is not a thing to support. The
    # question is always "which named test notices THIS bound", and two at once cannot answer it.
    if pathlib.Path(str(p) + BAK).exists():
        raise SystemExit(
            f"{p} IS ALREADY MUTATED: a backup exists at {p}{BAK}. Run --restore first. "
            "Mutating twice would overwrite the pristine backup with a mutated one, and the "
            "restore would report success while leaving the first mutation in place."
        )
    shutil.copy(p, str(p) + BAK)
    p.write_text(text.replace(find, repl), encoding="utf-8")
    print(f"reverted bound: {name} ({p.name})")


main()
