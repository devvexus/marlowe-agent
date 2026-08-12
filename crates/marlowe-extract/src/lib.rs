//! Document extraction: **bytes and a content type in, readable text out.**
//!
//! This is the module `marlowe-net`'s header promised and never got written:
//!
//! > *"Extraction is a separate module operating on [`Fetched`]"*
//!
//! Until now the `web` tool did `String::from_utf8_lossy` on the raw response and handed the
//! result to the model — `<script>` bodies, CSS, nav chrome and all. For a page over the inline
//! threshold that produced a head-and-tail preview consisting almost entirely of `<head>`
//! boilerplate and closing script tags, which is a result nobody can act on.
//!
//! # The design constraint that shapes everything here
//!
//! Marlowe reads **hundreds** of documents per research task, and reads them **without a model in
//! the loop**. So this crate is a throughput component, not a convenience wrapper:
//!
//! - **No DOM.** [`html`] is a single streaming pass that skips `<script>`/`<style>`/`<svg>`
//!   bodies wholesale and never materialises a tree it would only throw away. `memchr` does the
//!   `<` scan, so the hot loop runs at memory bandwidth.
//! - **Parallel by default.** [`extract_many`] is a `rayon` fan-out. Extraction is pure CPU over
//!   independent inputs — the single most parallelisable thing in the whole system.
//! - **No allocation per element.** Text accumulates into one buffer that is reserved once from
//!   the input length.
//!
//! # Failures are reported, never disguised
//!
//! The governing rule of this codebase is that a measurement must read differently when the thing
//! it describes is broken. Applied to a parser, that means **an extractor that cannot do the job
//! says so**, because the alternative — returning empty or partial text that looks like a
//! successful extraction — is indistinguishable from a document that genuinely had little to say.
//!
//! A scanned PDF with no text layer is the case that matters most in practice: it is a large
//! fraction of PDFs on the internet, and it extracts to `""` without erroring. That returns
//! [`Warning::NoTextLayer`], and a caller that ignores warnings still sees `text.is_empty()`.
//!
//! # What this crate deliberately cannot do
//!
//! No network — it takes bytes it did not fetch. No OCR, so an image-only document is *detected
//! and reported*, not read. No JavaScript execution, so a page that renders entirely client-side
//! yields its server HTML and [`Warning::LikelyClientRendered`].

#![forbid(unsafe_code)]

pub mod charset;
pub mod html;
pub mod office;
pub mod pdf;
pub mod plain;
pub mod sniff;
pub mod store;
pub mod zip;

use rayon::prelude::*;

/// Hard ceiling on decoded text kept for one document.
///
/// A cap, not a target: research documents are frequently long and truncating one is a real loss,
/// so this sits well above any normal page. What it bounds is the pathological case — a 400 MB
/// generated XML dump — where the alternative is the process dying.
pub const MAX_TEXT_CHARS: usize = 8 * 1024 * 1024;

/// Hard ceiling on input bytes any extractor will walk.
pub const MAX_INPUT_BYTES: usize = 64 * 1024 * 1024;

/// What a document turned out to be. Decided by [`sniff::detect`], never by the caller alone.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Format {
    Html,
    Xml,
    Pdf,
    PlainText,
    Markdown,
    Json,
    Csv,
    Docx,
    Xlsx,
    Pptx,
    Epub,
    /// Recognised as a container or binary this build does not extract. Carries no text.
    Unsupported,
}

impl Format {
    pub fn as_str(self) -> &'static str {
        match self {
            Format::Html => "html",
            Format::Xml => "xml",
            Format::Pdf => "pdf",
            Format::PlainText => "text",
            Format::Markdown => "markdown",
            Format::Json => "json",
            Format::Csv => "csv",
            Format::Docx => "docx",
            Format::Xlsx => "xlsx",
            Format::Pptx => "pptx",
            Format::Epub => "epub",
            Format::Unsupported => "unsupported",
        }
    }
}

/// A link found in the document, with its anchor text.
///
/// **Resolved against the document URL when one was supplied**, because a relative href is
/// useless to a caller that has to decide where to go next. Resolution is textual and does not
/// imply permission to fetch anything: this crate has no network and no opinion about egress.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Link {
    pub url: String,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Heading {
    pub level: u8,
    pub text: String,
}

/// **Everything this extraction could not do, stated.**
///
/// Warnings are not errors: the document still extracted, and `text` is still the best available
/// reading. They exist so a caller can tell "this document says little" from "this extractor
/// could not read it", which are the two cases an empty string conflates.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Warning {
    /// A PDF (or container) whose pages carry images and no extractable text layer. **The
    /// scanned-document case.** Reading it needs OCR, which this build does not have.
    NoTextLayer { pages: usize },
    /// The document declared an encryption or DRM scheme that blocked extraction.
    Encrypted { detail: String },
    /// The declared charset was not one `encoding_rs` knows; the fallback used is named.
    UnknownCharset { declared: String, used: &'static str },
    /// Bytes were not valid in the chosen encoding and were replaced.
    LossyDecode { replacements: usize },
    /// Output hit [`MAX_TEXT_CHARS`].
    Truncated { kept: usize, limit: usize },
    /// Markup was malformed in a way the extractor recovered from. Text is still returned.
    Recovered { detail: String },
    /// Server HTML carries almost no text but many scripts — the page is probably assembled in
    /// the browser, so what was extracted is not what a reader would see.
    LikelyClientRendered { text_chars: usize, script_chars: usize },
    /// A container part was skipped.
    PartSkipped { name: String, detail: String },
}

impl std::fmt::Display for Warning {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Warning::NoTextLayer { pages } => write!(
                f,
                "no extractable text layer across {pages} page(s) — this looks like a scanned \
                 document and reading it needs OCR, which this build does not have"
            ),
            Warning::Encrypted { detail } => write!(f, "encrypted or DRM-protected: {detail}"),
            Warning::UnknownCharset { declared, used } => {
                write!(f, "declared charset {declared:?} is not known; decoded as {used}")
            }
            Warning::LossyDecode { replacements } => {
                write!(f, "{replacements} byte sequence(s) were invalid and were replaced")
            }
            Warning::Truncated { kept, limit } => {
                write!(f, "output truncated to {kept} of a {limit} character limit")
            }
            Warning::Recovered { detail } => write!(f, "malformed markup recovered: {detail}"),
            Warning::LikelyClientRendered { text_chars, script_chars } => write!(
                f,
                "only {text_chars} characters of text against {script_chars} of script — the page \
                 is probably rendered client-side, so this is not what a reader would see"
            ),
            Warning::PartSkipped { name, detail } => write!(f, "skipped {name}: {detail}"),
        }
    }
}

/// One extracted document.
#[derive(Debug, Clone)]
pub struct Document {
    pub format: Format,
    pub title: Option<String>,
    /// The readable text, normalised: no runs of blank lines, no leading or trailing space on a
    /// line, block elements separated by newlines.
    pub text: String,
    pub links: Vec<Link>,
    pub headings: Vec<Heading>,
    /// From `<html lang>` or an equivalent, when stated. Never guessed.
    pub lang: Option<String>,
    pub description: Option<String>,
    /// Bytes handed in.
    pub bytes_in: usize,
    /// The encoding actually used to decode, for the record.
    pub encoding: &'static str,
    /// **Everything the extraction could not do.** See [`Warning`].
    pub warnings: Vec<Warning>,
}

impl Document {
    fn empty(format: Format, bytes_in: usize) -> Self {
        Self {
            format,
            title: None,
            text: String::new(),
            links: Vec::new(),
            headings: Vec::new(),
            lang: None,
            description: None,
            bytes_in,
            encoding: "none",
            warnings: Vec::new(),
        }
    }

    /// Did this produce anything a reader could use?
    ///
    /// Separate from `warnings.is_empty()` on purpose: a truncated 2 MB extraction is warned about
    /// and thoroughly usable, while a clean extraction of an image-only PDF is neither.
    pub fn has_text(&self) -> bool {
        !self.text.trim().is_empty()
    }

    /// Compression achieved against the input, as a ratio. Diagnostic — this is the number that
    /// says how much of a page was boilerplate.
    pub fn reduction(&self) -> f32 {
        if self.bytes_in == 0 {
            return 0.0;
        }
        1.0 - (self.text.len() as f32 / self.bytes_in as f32)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ExtractError {
    #[error("input is {bytes} bytes, above the {MAX_INPUT_BYTES} byte ceiling")]
    TooLarge { bytes: usize },
    #[error("{format} is recognised but this build does not extract it: {detail}")]
    Unsupported { format: &'static str, detail: String },
    #[error("the document is malformed beyond recovery: {detail}")]
    Malformed { detail: String },
    #[error("extracting {format}: {detail}")]
    Backend { format: &'static str, detail: String },
}

/// One document to extract, with whatever the caller knows about it.
///
/// **All three hints are optional and none is trusted over the bytes.** A server that says
/// `text/html` while serving a PDF is common enough that content type is an input to
/// [`sniff::detect`], not a decision.
#[derive(Debug, Clone, Default)]
pub struct Input<'a> {
    pub bytes: &'a [u8],
    /// Verbatim `Content-Type` header, if there was one.
    pub content_type: Option<&'a str>,
    /// The URL these bytes came from. Used to resolve relative links and as a weak format hint.
    pub url: Option<&'a str>,
}

impl<'a> Input<'a> {
    pub fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, content_type: None, url: None }
    }

    pub fn content_type(mut self, ct: Option<&'a str>) -> Self {
        self.content_type = ct;
        self
    }

    pub fn url(mut self, url: Option<&'a str>) -> Self {
        self.url = url;
        self
    }
}

/// Extract one document.
pub fn extract(input: &Input<'_>) -> Result<Document, ExtractError> {
    if input.bytes.len() > MAX_INPUT_BYTES {
        return Err(ExtractError::TooLarge { bytes: input.bytes.len() });
    }
    if input.bytes.is_empty() {
        return Ok(Document::empty(Format::PlainText, 0));
    }

    let format = sniff::detect(input.bytes, input.content_type, input.url);

    // **EVERY extractor runs under a panic guard, not just the PDF one.**
    //
    // `pdf.rs` has caught its own panics since it was written, with the right reason stated: a
    // parser panic in a `rayon` fan-out over three hundred documents propagates and takes the whole
    // batch with it. That reason is not specific to PDF. The hand-rolled HTML tokenizer, the ZIP
    // reader and `quick-xml` are all parsers over hostile input, and any one of them panicking cost
    // the other 299 documents — a denial of service costing an attacker one malformed `.docx`.
    //
    // Applying a guard to the one format whose library was known to panic, and not to the four
    // written in-house, is the shape this project keeps logging: a control placed where the danger
    // was noticed rather than where it lives.
    let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        extract_by_format(input, format)
    }));
    match outcome {
        Ok(result) => result,
        Err(panic) => {
            let detail = panic
                .downcast_ref::<&str>()
                .map(|s| (*s).to_string())
                .or_else(|| panic.downcast_ref::<String>().cloned())
                .unwrap_or_else(|| "the extractor panicked".to_string());
            Err(ExtractError::Backend {
                format: format.as_str(),
                detail: format!("{detail} (recovered; the rest of the batch is unaffected)"),
            })
        }
    }
}

fn extract_by_format(input: &Input<'_>, format: Format) -> Result<Document, ExtractError> {
    match format {
        Format::Html => html::extract(input.bytes, input.content_type, input.url),
        Format::Xml => office::extract_xml(input.bytes, input.content_type),
        Format::Pdf => pdf::extract(input.bytes),
        Format::PlainText | Format::Markdown | Format::Json | Format::Csv => {
            plain::extract(input.bytes, format, input.content_type)
        }
        Format::Docx | Format::Xlsx | Format::Pptx | Format::Epub => {
            office::extract(input.bytes, format)
        }
        Format::Unsupported => Err(ExtractError::Unsupported {
            format: "binary",
            detail: "the bytes match no format this build extracts".to_string(),
        }),
    }
}

/// **Extract a whole corpus in parallel.** The reason this crate exists in Rust.
///
/// Extraction is pure CPU over inputs that cannot affect one another, which makes it the single
/// most parallelisable stage in the system. Results come back in input order — `rayon`'s indexed
/// parallel iterator preserves it, so ordering is a property of the collect rather than something
/// callers have to reassemble.
///
/// Per-document failure is isolated: one malformed PDF in three hundred returns its own `Err` and
/// costs the other 299 nothing.
pub fn extract_many(inputs: &[Input<'_>]) -> Vec<Result<Document, ExtractError>> {
    inputs.par_iter().map(extract).collect()
}

/// [`extract_many`] with a caller-chosen thread count.
///
/// Exists because the default `rayon` pool is global and a caller running extraction *inside*
/// another parallel stage wants to bound it rather than oversubscribe the machine.
pub fn extract_many_with(
    inputs: &[Input<'_>],
    threads: usize,
) -> Result<Vec<Result<Document, ExtractError>>, ExtractError> {
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(threads.max(1))
        .build()
        .map_err(|e| ExtractError::Backend { format: "pool", detail: e.to_string() })?;
    Ok(pool.install(|| extract_many(inputs)))
}

/// Shared by every extractor: collapse whitespace into readable blocks, and cap.
///
/// One pass, no regex, no intermediate `Vec<String>`. Blocks are separated by `\n\n`, lines are
/// trimmed, and runs of blank lines collapse to one.
pub(crate) fn normalize(raw: &str, warnings: &mut Vec<Warning>) -> String {
    let mut out = String::with_capacity(raw.len().min(MAX_TEXT_CHARS) + 16);
    let mut pending_blank = false;
    let mut wrote_any = false;

    for line in raw.lines() {
        let trimmed = trim_collapsing(line);
        if trimmed.is_empty() {
            pending_blank = wrote_any;
            continue;
        }
        if pending_blank {
            out.push('\n');
            pending_blank = false;
        }
        if wrote_any {
            out.push('\n');
        }
        if out.len() + trimmed.len() > MAX_TEXT_CHARS {
            let room = MAX_TEXT_CHARS.saturating_sub(out.len());
            out.push_str(&trimmed[..floor_char_boundary(&trimmed, room)]);
            warnings.push(Warning::Truncated { kept: out.len(), limit: MAX_TEXT_CHARS });
            return out;
        }
        out.push_str(&trimmed);
        wrote_any = true;
    }
    out
}

/// Trim a line and collapse internal whitespace runs to a single space.
fn trim_collapsing(line: &str) -> String {
    let mut out = String::with_capacity(line.len());
    let mut in_space = true; // leading whitespace is skipped
    for ch in line.chars() {
        if ch.is_whitespace() {
            if !in_space {
                out.push(' ');
                in_space = true;
            }
        } else {
            out.push(ch);
            in_space = false;
        }
    }
    while out.ends_with(' ') {
        out.pop();
    }
    out
}

pub(crate) fn floor_char_boundary(s: &str, mut i: usize) -> usize {
    if i >= s.len() {
        return s.len();
    }
    while i > 0 && !s.is_char_boundary(i) {
        i -= 1;
    }
    i
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_collapses_blank_runs_and_trims() {
        let mut w = Vec::new();
        let got = normalize("  a  b  \n\n\n\n  c \n", &mut w);
        assert_eq!(got, "a b\n\nc");
        assert!(w.is_empty());
    }

    #[test]
    fn normalize_reports_truncation_rather_than_silently_cutting() {
        let mut w = Vec::new();
        let huge = "x".repeat(MAX_TEXT_CHARS + 1_000);
        let got = normalize(&huge, &mut w);
        assert!(got.len() <= MAX_TEXT_CHARS);
        assert!(
            matches!(w.first(), Some(Warning::Truncated { .. })),
            "a truncated extraction that does not say so is indistinguishable from a short document"
        );
    }

    #[test]
    fn an_empty_input_is_a_document_not_an_error() {
        let d = extract(&Input::new(b"")).expect("empty is not a failure");
        assert!(!d.has_text());
    }

    #[test]
    fn oversized_input_is_refused_by_size_not_walked() {
        let big = vec![b'x'; MAX_INPUT_BYTES + 1];
        assert!(matches!(
            extract(&Input::new(&big)),
            Err(ExtractError::TooLarge { .. })
        ));
    }
}
