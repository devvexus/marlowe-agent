//! The corpus pipeline: **fetch and extract many documents at once.**
//!
//! This is the entry point for the non-LLM half of the work — the deep-research case where
//! Marlowe pulls hundreds of pages, PDFs and datasets and turns them into text with no model in
//! the loop. It is the only place `marlowe-net` and `marlowe-extract` meet, which is what keeps a
//! parser bug out of the egress path and an egress rule out of the parser.
//!
//! # Why this is threads and not an async runtime
//!
//! Fetching is I/O-bound and extraction is CPU-bound, so the obvious reach is for `tokio`. It
//! would be the wrong call here for a reason that has nothing to do with taste: **the entire call
//! chain around this is synchronous** — adjudication, tool execution, journalling — so adopting an
//! executor means colouring all of it `async` to solve a problem that OS threads already solve.
//! A few dozen threads parked on sockets costs a few dozen stacks, and the work here is measured
//! in network round trips, not in context switches.
//!
//! # The pipelining, stated precisely
//!
//! Each worker fetches **and then extracts its own document** before taking the next URL. That is
//! deliberate rather than lazy: it means CPU work on document *k* overlaps network waits on
//! documents *k+1..n* with no channel, no queue and no separate thread pool to size. Extraction
//! runs in single-digit milliseconds against network latency in the hundreds, so the workers stay
//! network-bound, which is the regime you want.
//!
//! # What this does NOT do
//!
//! It does not adjudicate. Every URL handed to [`fetch_and_extract`] must already have been
//! through the permission layer — this function has no `EgressPolicy`, cannot obtain one, and
//! must never grow one, or there would be two implementations of the allowlist and they would
//! come to disagree. It also does not follow redirects, for the same reason `marlowe-net` does
//! not: a redirect is a second destination chosen by the site.

use marlowe_extract::{Document, Input};
use marlowe_net::{Fetched, Target};

/// The fan-out for this machine. **Derived, never hardcoded** — see
/// [`marlowe_net::io_concurrency`]. Pass `0` to `fetch_and_extract` to get it.
pub fn default_concurrency() -> usize {
    marlowe_net::io_concurrency()
}

/// What happened to one URL.
#[derive(Debug)]
pub enum Outcome {
    /// Fetched and extracted.
    Read {
        url: String,
        status: u16,
        document: Document,
        /// Bytes off the socket before decompression.
        wire_bytes: usize,
        reused_connection: bool,
        /// Time on the network for this document.
        fetch_ms: u64,
        /// Time turning its bytes into text. **Reported separately from `fetch_ms` on purpose:**
        /// the two answer different questions, and a single total would hide which half a corpus
        /// is actually bound by.
        extract_ms: u64,
    },
    /// Fetched, but the server sent a redirect. **Not followed** — see the module header.
    Redirect { url: String, status: u16, location: String },
    /// The fetch failed.
    Unreachable { url: String, detail: String },
    /// The bytes arrived and could not be turned into text.
    Unreadable { url: String, status: u16, detail: String },
}

impl Outcome {
    pub fn url(&self) -> &str {
        match self {
            Outcome::Read { url, .. }
            | Outcome::Redirect { url, .. }
            | Outcome::Unreachable { url, .. }
            | Outcome::Unreadable { url, .. } => url,
        }
    }

    pub fn document(&self) -> Option<&Document> {
        match self {
            Outcome::Read { document, .. } => Some(document),
            _ => None,
        }
    }
}

/// Fetch and extract many URLs concurrently. **Results are in input order.**
///
/// A URL that fails to parse, fails to fetch or fails to extract yields its own [`Outcome`] and
/// costs the others nothing — which is the property that matters at corpus scale, where a handful
/// of dead links and malformed PDFs is the normal case rather than an exception.
pub fn fetch_and_extract(urls: &[String], concurrency: usize) -> Vec<Outcome> {
    let n = urls.len();
    if n == 0 {
        return Vec::new();
    }
    // `0` means "decide for me": the derived width for this machine. Never more workers than
    // there is work, so a two-document corpus does not spawn sixty-four threads.
    let requested = if concurrency == 0 { default_concurrency() } else { concurrency };
    let workers = requested.max(1).min(n);
    let slots: Vec<std::sync::Mutex<Option<Outcome>>> =
        (0..n).map(|_| std::sync::Mutex::new(None)).collect();
    let next = std::sync::atomic::AtomicUsize::new(0);
    // **The process-wide client, not a fresh one.**
    //
    // A `Client::new()` here looked harmless and quietly discarded the three things that make
    // repeat fetching fast — the connection pool, the DNS cache and the TLS session cache — at
    // the end of every batch. It also made `connection_stats()` report on a client that had never
    // run: the first live benchmark printed `handshakes 0, reused 0` for ten completed fetches,
    // which reads as "pooling is broken" and actually meant "you measured a different object".
    // Same family as every other instance in this project: the number was real and it was about
    // something else.
    let client = marlowe_net::shared();

    std::thread::scope(|scope| {
        for _ in 0..workers {
            scope.spawn(|| loop {
                let i = next.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                if i >= n {
                    break;
                }
                let outcome = one(&client, &urls[i]);
                *slots[i].lock().expect("corpus slot poisoned") = Some(outcome);
            });
        }
    });

    slots
        .into_iter()
        .map(|s| {
            s.into_inner()
                .expect("corpus slot poisoned")
                .expect("every slot is filled before the scope ends")
        })
        .collect()
}

fn one(client: &marlowe_net::Client, url: &str) -> Outcome {
    let target = match Target::parse(url) {
        Ok(t) => t,
        Err(e) => return Outcome::Unreachable { url: url.to_string(), detail: e.to_string() },
    };
    let t = std::time::Instant::now();
    let fetched = client.fetch(&target);
    let fetch_ms = t.elapsed().as_millis() as u64;
    match fetched {
        Err(e) => Outcome::Unreachable { url: url.to_string(), detail: e.to_string() },
        Ok(res) => {
            let mut o = read(url, res);
            if let Outcome::Read { fetch_ms: slot, .. } = &mut o {
                *slot = fetch_ms;
            }
            o
        }
    }
}

/// Turn one fetched response into an outcome. Shared with the single-URL `web` executor so the
/// two cannot drift — a batch and a single call must read a page identically.
pub fn read(url: &str, res: Fetched) -> Outcome {
    if let Some(location) = res.redirect_to {
        return Outcome::Redirect {
            url: url.to_string(),
            status: res.status,
            location,
        };
    }
    let input = Input::new(&res.bytes)
        .content_type(res.content_type.as_deref())
        .url(Some(url));
    let t = std::time::Instant::now();
    let extracted = marlowe_extract::extract(&input);
    let extract_ms = t.elapsed().as_millis() as u64;
    match extracted {
        Ok(document) => Outcome::Read {
            url: url.to_string(),
            status: res.status,
            document,
            wire_bytes: res.wire_bytes,
            reused_connection: res.reused_connection,
            // Filled in by `one`, which is the only caller that did the fetching.
            fetch_ms: 0,
            extract_ms,
        },
        Err(e) => Outcome::Unreadable {
            url: url.to_string(),
            status: res.status,
            detail: e.to_string(),
        },
    }
}

/// Render one extracted document for a reader.
///
/// **Warnings come first and are never dropped.** A scanned PDF, a client-rendered page or a
/// truncated dataset must announce itself where it will actually be read — attaching the caveat
/// to the text is the only place it cannot be lost, because everything downstream handles the
/// text and not the struct.
pub fn render(document: &Document) -> String {
    let mut out = String::with_capacity(document.text.len() + 256);
    if let Some(title) = &document.title {
        out.push_str(title);
        out.push('\n');
        out.push('\n');
    }
    for w in &document.warnings {
        // `Recovered` is bookkeeping about how the parse went, not something a reader must act
        // on. The rest change what the text means.
        if matches!(w, marlowe_extract::Warning::Recovered { .. }) {
            continue;
        }
        out.push_str("[note: ");
        out.push_str(&w.to_string());
        out.push_str("]\n");
    }
    if !out.is_empty() && !out.ends_with("\n\n") {
        out.push('\n');
    }
    out.push_str(&document.text);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_empty_corpus_is_empty_rather_than_a_panic() {
        assert!(fetch_and_extract(&[], 8).is_empty());
    }

    #[test]
    fn a_malformed_url_fails_alone_and_in_place() {
        // No network: every one of these fails at parse, which is enough to prove that failures
        // are per-URL and that ordering survives them.
        let urls: Vec<String> = vec![
            "http://plaintext.example".into(),
            "not-a-url".into(),
            "https://ok.example@evil".into(),
        ];
        let got = fetch_and_extract(&urls, 4);
        assert_eq!(got.len(), 3);
        for (i, o) in got.iter().enumerate() {
            assert_eq!(o.url(), urls[i], "results must stay in input order");
            assert!(matches!(o, Outcome::Unreachable { .. }));
        }
    }

    #[test]
    fn a_redirect_is_reported_and_never_followed() {
        let res = Fetched {
            status: 301,
            content_type: Some("text/html".into()),
            bytes: b"<html><body>ignored</body></html>".to_vec(),
            final_url: "https://a.example/".into(),
            redirect_to: Some("https://b.example/".into()),
            wire_bytes: 33,
            reused_connection: false,
        };
        match read("https://a.example/", res) {
            Outcome::Redirect { location, .. } => assert_eq!(location, "https://b.example/"),
            other => panic!("a redirect must not be read as a page: {other:?}"),
        }
    }

    #[test]
    fn a_fetched_page_is_extracted_not_handed_over_raw() {
        let html = b"<html><head><title>T</title><style>.a{}</style></head>\
                     <body><p>The content.</p><script>var x=1</script></body></html>";
        let res = Fetched {
            status: 200,
            content_type: Some("text/html; charset=utf-8".into()),
            bytes: html.to_vec(),
            final_url: "https://a.example/".into(),
            redirect_to: None,
            wire_bytes: html.len(),
            reused_connection: false,
        };
        let out = read("https://a.example/", res);
        let doc = out.document().expect("read");
        assert_eq!(doc.text, "The content.");
        assert_eq!(doc.title.as_deref(), Some("T"));
        assert!(render(doc).contains("The content."));
    }

    #[test]
    fn warnings_reach_the_rendered_text_where_they_cannot_be_dropped() {
        let doc = Document {
            format: marlowe_extract::Format::Pdf,
            title: None,
            text: String::new(),
            links: Vec::new(),
            headings: Vec::new(),
            lang: None,
            description: None,
            bytes_in: 10,
            encoding: "UTF-8",
            warnings: vec![marlowe_extract::Warning::NoTextLayer { pages: 12 }],
        };
        let rendered = render(&doc);
        assert!(rendered.contains("OCR"), "got {rendered:?}");
        assert!(rendered.contains("12"), "the page count is the evidence: {rendered:?}");
    }
}
