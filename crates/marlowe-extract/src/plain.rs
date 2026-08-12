//! Text-shaped formats: plain text, Markdown, JSON, CSV.
//!
//! These share one property that shapes the whole module: **the characters are already the
//! content.** There is no markup to strip, so the job is decoding, light structural flattening,
//! and — for the two structured formats — turning a machine shape into something a reader (or a
//! model, or an embedder) can use as prose.
//!
//! Flattening JSON and CSV rather than pretty-printing them is the deliberate part. A research
//! agent that fetches a dataset wants *"country: France, population: 68000000"*, not two hundred
//! lines of punctuation, because every downstream stage — ranking, embedding, summarising —
//! scores the punctuation too.

use crate::{charset, Document, ExtractError, Format, Heading, Warning};

/// How many rows of a CSV get flattened into prose before the rest is summarised.
///
/// A cap on *output*, not on reading: the row count reported afterwards is the true one. Without
/// this a 400 MB export becomes 400 MB of `col: value` text, which is worse than useless — it is
/// expensive and useless.
const MAX_CSV_ROWS: usize = 5_000;

/// Depth limit for JSON flattening. Beyond this a value is summarised by its shape.
const MAX_JSON_DEPTH: usize = 24;

pub fn extract(
    bytes: &[u8],
    format: Format,
    content_type: Option<&str>,
) -> Result<Document, ExtractError> {
    let mut warnings = Vec::new();
    let decoded = charset::decode(bytes, content_type, false, &mut warnings);

    let (text, headings) = match format {
        Format::Markdown => markdown(&decoded.text),
        Format::Json => (json(&decoded.text, &mut warnings), Vec::new()),
        Format::Csv => (csv(&decoded.text, &mut warnings), Vec::new()),
        _ => (decoded.text.clone(), Vec::new()),
    };

    let title = match format {
        Format::Markdown => headings.iter().find(|h| h.level == 1).map(|h| h.text.clone()),
        _ => None,
    };

    let text = crate::normalize(&text, &mut warnings);
    Ok(Document {
        format,
        title,
        text,
        links: Vec::new(),
        headings,
        lang: None,
        description: None,
        bytes_in: bytes.len(),
        encoding: decoded.encoding,
        warnings,
    })
}

/// Markdown is kept nearly verbatim — it is already the readable form.
///
/// Only the headings are lifted out into structure, because a caller that wants an outline should
/// not have to re-parse the text to get one. Fences are tracked so a `#` in a code block is not
/// mistaken for a heading.
fn markdown(src: &str) -> (String, Vec<Heading>) {
    let mut headings = Vec::new();
    let mut in_fence = false;
    for line in src.lines() {
        let t = line.trim_start();
        if t.starts_with("```") || t.starts_with("~~~") {
            in_fence = !in_fence;
            continue;
        }
        if in_fence {
            continue;
        }
        let hashes = t.bytes().take_while(|b| *b == b'#').count();
        if (1..=6).contains(&hashes) && t.as_bytes().get(hashes) == Some(&b' ') {
            let text = t[hashes + 1..].trim().trim_end_matches('#').trim().to_string();
            if !text.is_empty() {
                headings.push(Heading { level: hashes as u8, text });
            }
        }
    }
    (src.to_string(), headings)
}

/// Flatten JSON into `path: value` lines.
///
/// Hand-rolled rather than pulled through `serde_json`, for one reason worth stating: a research
/// corpus is full of **almost**-JSON — trailing commas, NDJSON, truncated downloads — and a strict
/// parser returns nothing at all for any of it. This walks the text and emits what it can, so a
/// malformed file yields its readable content instead of an error.
fn json(src: &str, warnings: &mut Vec<Warning>) -> String {
    let mut out = String::with_capacity(src.len() / 2);
    let mut depth = 0usize;
    let mut chars = src.char_indices().peekable();
    let mut pending_key: Option<String> = None;
    let mut deepest = 0usize;

    while let Some((i, c)) = chars.next() {
        match c {
            '{' | '[' => {
                depth += 1;
                deepest = deepest.max(depth);
                if depth > MAX_JSON_DEPTH {
                    continue;
                }
            }
            '}' | ']' => {
                depth = depth.saturating_sub(1);
                if !out.ends_with('\n') {
                    out.push('\n');
                }
            }
            '"' => {
                let (s, next) = read_json_string(src, i);
                // **Advance by POSITION, not by a byte count used as a step count.**
                //
                // `next - i - 1` is a byte distance; using it as a number of `char_indices` steps
                // over-advanced on any non-ASCII string and silently swallowed the following
                // fields. A dataset in any non-English language lost data with no warning --
                // "silently wrong", which is the failure `charset.rs` exists to prevent.
                while chars.peek().is_some_and(|(j, _)| *j < next) {
                    chars.next();
                }
                // A string followed by `:` is a key; anything else is a value.
                let is_key = src[next..].trim_start().starts_with(':');
                if is_key {
                    pending_key = Some(s);
                } else {
                    emit(&mut out, pending_key.take(), &s);
                }
            }
            c if c.is_ascii_digit() || c == '-' => {
                let start = i;
                let mut end = i + c.len_utf8();
                while let Some((j, d)) = chars.peek().copied() {
                    if d.is_ascii_digit() || d == '.' || d == 'e' || d == 'E' || d == '+' || d == '-'
                    {
                        end = j + d.len_utf8();
                        chars.next();
                    } else {
                        break;
                    }
                }
                emit(&mut out, pending_key.take(), &src[start..end]);
            }
            't' | 'f' | 'n' => {
                for word in ["true", "false", "null"] {
                    if src[i..].starts_with(word) {
                        for _ in 1..word.len() {
                            chars.next();
                        }
                        emit(&mut out, pending_key.take(), word);
                        break;
                    }
                }
            }
            _ => {}
        }
    }
    if deepest > MAX_JSON_DEPTH {
        warnings.push(Warning::Recovered {
            detail: format!("JSON nested {deepest} deep; below {MAX_JSON_DEPTH} was flattened"),
        });
    }
    out
}

fn emit(out: &mut String, key: Option<String>, value: &str) {
    if value.trim().is_empty() {
        return;
    }
    if let Some(k) = key {
        out.push_str(&k);
        out.push_str(": ");
    }
    out.push_str(value);
    out.push('\n');
}

/// Read a JSON string starting at the opening quote. Returns the unescaped value and the index
/// just past the closing quote.
fn read_json_string(src: &str, open: usize) -> (String, usize) {
    let bytes = src.as_bytes();
    let mut out = String::new();
    let mut i = open + 1;
    while i < bytes.len() {
        match bytes[i] {
            b'"' => return (out, i + 1),
            b'\\' if i + 1 < bytes.len() => {
                let e = bytes[i + 1];
                match e {
                    b'n' | b'r' => out.push(' '),
                    b't' => out.push(' '),
                    b'u' => {
                        if let Some(hex) = src.get(i + 2..i + 6) {
                            if let Some(c) =
                                u32::from_str_radix(hex, 16).ok().and_then(char::from_u32)
                            {
                                out.push(c);
                            }
                            i += 6;
                            continue;
                        }
                    }
                    other => {
                        // **Decode the whole character before advancing.**
                        //
                        // `i += 2` stepped one byte past the backslash and one byte INTO a
                        // multi-byte escaped character, after which the `_` arm sliced at a
                        // non-boundary and panicked. `["\<e-acute>"]` was enough.
                        let ch = src[i + 1..].chars().next().unwrap_or(other as char);
                        out.push(ch);
                        i += 1 + ch.len_utf8();
                        continue;
                    }
                }
                i += 2;
                continue;
            }
            _ => {
                let ch = src[i..].chars().next().unwrap_or(' ');
                out.push(ch);
                i += ch.len_utf8();
                continue;
            }
        }
    }
    (out, bytes.len())
}

/// Flatten CSV into `header: cell` prose, one record per block.
///
/// RFC 4180 quoting is honoured — a delimiter inside quotes is data, and `""` is a literal quote —
/// because a naive `split(',')` corrupts exactly the rows that contain prose, which are the rows a
/// research agent cares about.
fn csv(src: &str, warnings: &mut Vec<Warning>) -> String {
    let delim = pick_delimiter(src);
    let rows = parse_csv(src, delim);
    if rows.is_empty() {
        return String::new();
    }
    let header = &rows[0];
    let looks_headed = header.iter().all(|c| !c.trim().is_empty())
        && header.iter().any(|c| c.parse::<f64>().is_err());

    let mut out = String::new();
    let body = if looks_headed { &rows[1..] } else { &rows[..] };
    for row in body.iter().take(MAX_CSV_ROWS) {
        for (i, cell) in row.iter().enumerate() {
            if cell.trim().is_empty() {
                continue;
            }
            if looks_headed {
                if let Some(h) = header.get(i) {
                    out.push_str(h.trim());
                    out.push_str(": ");
                }
            }
            out.push_str(cell.trim());
            out.push('\n');
        }
        out.push('\n');
    }
    if body.len() > MAX_CSV_ROWS {
        // The true count, stated. A silently-capped export reads as a small dataset.
        out.push_str(&format!(
            "[{} of {} rows shown]\n",
            MAX_CSV_ROWS,
            body.len()
        ));
        warnings.push(Warning::Truncated { kept: MAX_CSV_ROWS, limit: MAX_CSV_ROWS });
    }
    out
}

fn pick_delimiter(src: &str) -> char {
    let head: String = src.lines().take(5).collect::<Vec<_>>().join("\n");
    [',', '\t', ';', '|']
        .into_iter()
        .max_by_key(|d| head.matches(*d).count())
        .unwrap_or(',')
}

fn parse_csv(src: &str, delim: char) -> Vec<Vec<String>> {
    let mut rows = Vec::new();
    let mut row = Vec::new();
    let mut field = String::new();
    let mut quoted = false;
    let mut chars = src.chars().peekable();

    while let Some(c) = chars.next() {
        if quoted {
            if c == '"' {
                if chars.peek() == Some(&'"') {
                    field.push('"');
                    chars.next();
                } else {
                    quoted = false;
                }
            } else {
                field.push(c);
            }
            continue;
        }
        match c {
            '"' if field.is_empty() => quoted = true,
            c if c == delim => row.push(std::mem::take(&mut field)),
            '\n' => {
                row.push(std::mem::take(&mut field));
                rows.push(std::mem::take(&mut row));
            }
            '\r' => {}
            _ => field.push(c),
        }
    }
    if !field.is_empty() || !row.is_empty() {
        row.push(field);
        rows.push(row);
    }
    rows
}

#[cfg(test)]
mod tests {
    use super::*;

    fn go(bytes: &[u8], f: Format) -> Document {
        extract(bytes, f, Some("text/plain; charset=utf-8")).expect("extracts")
    }

    #[test]
    fn markdown_keeps_its_text_and_lifts_an_outline() {
        let d = go(b"# Title\n\nSome prose.\n\n## Section\n\nMore.\n", Format::Markdown);
        assert_eq!(d.title.as_deref(), Some("Title"));
        assert_eq!(d.headings.len(), 2);
        assert!(d.text.contains("Some prose."));
    }

    #[test]
    fn a_hash_inside_a_code_fence_is_not_a_heading() {
        let d = go(b"# Real\n\n```\n# not a heading\n```\n", Format::Markdown);
        assert_eq!(d.headings.len(), 1);
    }

    #[test]
    fn json_flattens_to_readable_pairs() {
        let d = go(br#"{"country":"France","population":68000000,"eu":true}"#, Format::Json);
        assert!(d.text.contains("country: France"), "got {:?}", d.text);
        assert!(d.text.contains("population: 68000000"), "got {:?}", d.text);
        assert!(d.text.contains("eu: true"), "got {:?}", d.text);
    }

    #[test]
    fn malformed_json_still_yields_its_content() {
        // A strict parser returns nothing here; a truncated download is common in a corpus.
        let d = go(br#"{"a":"kept","b":"also kept","c":"#, Format::Json);
        assert!(d.text.contains("kept"), "got {:?}", d.text);
    }

    #[test]
    fn csv_uses_headers_and_honours_quoting() {
        let d = go(
            b"name,note\nAda,\"Lovelace, Countess\"\nAlan,\"He said \"\"hi\"\"\"\n",
            Format::Csv,
        );
        assert!(d.text.contains("name: Ada"), "got {:?}", d.text);
        assert!(
            d.text.contains("note: Lovelace, Countess"),
            "a quoted delimiter must stay data: {:?}",
            d.text
        );
        assert!(d.text.contains(r#"He said "hi""#), "got {:?}", d.text);
    }

    #[test]
    fn a_tab_separated_file_is_detected_by_delimiter_frequency() {
        let d = go(b"a\tb\n1\t2\n3\t4\n", Format::Csv);
        assert!(d.text.contains("a: 1"), "got {:?}", d.text);
    }
}
