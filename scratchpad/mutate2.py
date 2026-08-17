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
    shutil.copy(p, str(p) + BAK)
    p.write_text(text.replace(find, repl), encoding="utf-8")
    print(f"reverted bound: {name} ({p.name})")


main()
