//! The fetch primitive. ADR-031.
//!
//! # What this crate is for, and the boundary that is the point of it
//!
//! It performs one HTTPS request and returns **bytes and a content type**. It does not parse, it
//! does not strip HTML, it does not guess a charset beyond what the header states, and it has no
//! opinion about what a page means.
//!
//! **Extraction is a separate module operating on [`Fetched`]**, and that boundary is structural
//! rather than stylistic. Extraction is where the interesting parsing bugs live, and parsing is
//! the thing you least want entangled with the code that decides whether a request may happen at
//! all: an extractor that panics must not take the egress path with it, and an egress rule must
//! never be expressible as a parser option.
//!
//! # What it deliberately cannot do
//!
//! No HTTP/2, no keep-alive, no compression, no cookies, no authentication. Each is a real feature
//! and each is a real surface; they arrive individually, with a reason, as
//! `marlowe-provider/src/http.rs` learned to say about itself.
//!
//! **No credentials are sent, ever.** ADR-028's *"build the provider adapter; do NOT build the
//! credential broker"* still holds, and it is what keeps keyed search a separate decision rather
//! than a follow-on from this crate existing.
//!
//! # Redirects are the security-relevant part
//!
//! [`fetch`] does **not** follow redirects itself. It returns [`Fetched::redirect_to`] and lets the
//! caller decide, because **a redirect is a second egress destination** — following one without
//! re-checking the allowlist means the host being fetched chose where the request goes, which is
//! untrusted content selecting a target through a channel that never touches the taint layer.
//!
//! The re-check cannot live here: this crate does not know the run's `EgressPolicy` and must not,
//! or the permission layer would have a second implementation inside a networking crate. See
//! `marlowe-exec`'s `web` executor for the loop that consumes this.

#![forbid(unsafe_code)]

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::sync::Arc;
use std::time::Duration;

#[derive(Debug, thiserror::Error)]
pub enum FetchError {
    #[error("{url} is not a URL this tool will fetch: {detail}")]
    Unsupported { url: String, detail: String },
    #[error("could not reach {host}: {detail}")]
    Unreachable { host: String, detail: String },
    #[error("TLS to {host} failed: {detail}")]
    Tls { host: String, detail: String },
    #[error("malformed response from {host}: {detail}")]
    Malformed { host: String, detail: String },
    #[error("{host} returned a body larger than the {limit} byte cap")]
    TooLarge { host: String, limit: usize },
}

/// One response. **Bytes and a content type — nothing interpreted.**
#[derive(Debug, Clone)]
pub struct Fetched {
    pub status: u16,
    /// Verbatim from the `Content-Type` header, `None` when absent. Not defaulted to
    /// `text/html`: a guess here would be indistinguishable from a server that said so.
    pub content_type: Option<String>,
    pub bytes: Vec<u8>,
    /// The URL this response came from — the one requested, since this crate does not follow
    /// redirects. The caller updates it as it walks a chain.
    pub final_url: String,
    /// `Some` when the status is a redirect and a `Location` header was present. **The caller must
    /// re-adjudicate this host before fetching it.**
    pub redirect_to: Option<String>,
}

/// Bodies above this are truncated rather than buffered. `web` returns by reference anyway
/// (`inline_threshold_bytes: 0`), so this bounds memory, not usefulness.
pub const MAX_BODY_BYTES: usize = 4 * 1024 * 1024;

const TIMEOUT: Duration = Duration::from_secs(20);

/// A parsed destination. Construction is the validation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Target {
    pub host: String,
    pub port: u16,
    pub path: String,
    pub tls: bool,
}

impl Target {
    /// **`https` only, and `http` is refused rather than upgraded.**
    ///
    /// Silently upgrading would make the scheme the caller asked for and the scheme actually used
    /// two different things with nothing observing the difference — and a downgrade in a redirect
    /// chain is exactly what §2.5 refuses, so accepting plaintext here would open by the front door
    /// what that closes at the back.
    pub fn parse(url: &str) -> Result<Self, FetchError> {
        let url = url.trim();
        let unsupported = |detail: &str| FetchError::Unsupported {
            url: url.to_string(),
            detail: detail.to_string(),
        };
        let rest = url.strip_prefix("https://").ok_or_else(|| {
            if url.starts_with("http://") {
                unsupported("only https is supported; plaintext http is refused, not upgraded")
            } else {
                unsupported("the URL must begin with https://")
            }
        })?;

        let (authority, path) = match rest.find('/') {
            Some(i) => (&rest[..i], &rest[i..]),
            None => (rest, "/"),
        };
        if authority.contains('@') {
            return Err(unsupported("userinfo in the authority is not accepted"));
        }
        let (host, port) = match authority.rsplit_once(':') {
            Some((h, p)) => (
                h,
                p.parse::<u16>().map_err(|_| unsupported("the port is not a number"))?,
            ),
            None => (authority, 443),
        };
        if host.is_empty() || host.contains(char::is_whitespace) {
            return Err(unsupported("the host is empty or contains whitespace"));
        }
        Ok(Self {
            host: host.to_ascii_lowercase(),
            port,
            path: path.to_string(),
            tls: true,
        })
    }
}

fn root_store() -> rustls::RootCertStore {
    // ADR-031 §2.2: the vendored Mozilla set. A corporate MITM root will not verify, and that
    // refusal is deliberate — an escape hatch accepting an unknown root would be a hole in the one
    // component whose entire job is fetching content nobody trusts.
    rustls::RootCertStore {
        roots: webpki_roots::TLS_SERVER_ROOTS.to_vec(),
    }
}

/// One request. No redirect following — see the module header.
pub fn fetch(target: &Target) -> Result<Fetched, FetchError> {
    let config = rustls::ClientConfig::builder()
        .with_root_certificates(root_store())
        .with_no_client_auth();

    let server_name = target
        .host
        .clone()
        .try_into()
        .map_err(|_| FetchError::Tls { host: target.host.clone(), detail: "not a valid DNS name".into() })?;

    let conn = rustls::ClientConnection::new(Arc::new(config), server_name).map_err(|e| {
        FetchError::Tls { host: target.host.clone(), detail: e.to_string() }
    })?;

    let sock = TcpStream::connect((target.host.as_str(), target.port)).map_err(|e| {
        FetchError::Unreachable { host: target.host.clone(), detail: e.to_string() }
    })?;
    sock.set_read_timeout(Some(TIMEOUT)).ok();
    sock.set_write_timeout(Some(TIMEOUT)).ok();

    let mut tls = rustls::StreamOwned::new(conn, sock);

    // `Connection: close` because there is no keep-alive here and a server holding the socket open
    // would turn "read to EOF" into a hang rather than an answer.
    let request = format!(
        "GET {} HTTP/1.1\r\nHost: {}\r\nUser-Agent: marlowe\r\nAccept: */*\r\n\
         Accept-Encoding: identity\r\nConnection: close\r\n\r\n",
        target.path, target.host
    );
    tls.write_all(request.as_bytes())
        .and_then(|()| tls.flush())
        .map_err(|e| FetchError::Unreachable { host: target.host.clone(), detail: e.to_string() })?;

    let mut reader = BufReader::new(tls);
    let mut status_line = String::new();
    reader.read_line(&mut status_line).map_err(|e| FetchError::Malformed {
        host: target.host.clone(),
        detail: e.to_string(),
    })?;
    let status: u16 = status_line
        .split_whitespace()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .ok_or_else(|| FetchError::Malformed {
            host: target.host.clone(),
            detail: format!("no status code in {status_line:?}"),
        })?;

    let mut content_type = None;
    let mut location = None;
    let mut chunked = false;
    let mut content_length: Option<usize> = None;
    loop {
        let mut line = String::new();
        let n = reader.read_line(&mut line).map_err(|e| FetchError::Malformed {
            host: target.host.clone(),
            detail: e.to_string(),
        })?;
        if n == 0 || line.trim().is_empty() {
            break;
        }
        let Some((name, value)) = line.split_once(':') else { continue };
        let value = value.trim().to_string();
        match name.trim().to_ascii_lowercase().as_str() {
            "content-type" => content_type = Some(value),
            "location" => location = Some(value),
            "transfer-encoding" if value.eq_ignore_ascii_case("chunked") => chunked = true,
            "content-length" => content_length = value.parse().ok(),
            _ => {}
        }
    }

    let bytes = if chunked {
        read_chunked(&mut reader, &target.host)?
    } else {
        let cap = content_length.unwrap_or(MAX_BODY_BYTES).min(MAX_BODY_BYTES);
        let mut buf = Vec::with_capacity(cap.min(64 * 1024));
        // `by_ref` because `Read::take` consumes self and the reader is still needed after.
        Read::by_ref(&mut reader)
            .take(MAX_BODY_BYTES as u64)
            .read_to_end(&mut buf)
            .map_err(|e| FetchError::Malformed { host: target.host.clone(), detail: e.to_string() })?;
        buf
    };

    let redirect_to = match status {
        301 | 302 | 303 | 307 | 308 => location,
        _ => None,
    };

    Ok(Fetched {
        status,
        content_type,
        bytes,
        final_url: format!("https://{}:{}{}", target.host, target.port, target.path),
        redirect_to,
    })
}

fn read_chunked<R: BufRead>(reader: &mut R, host: &str) -> Result<Vec<u8>, FetchError> {
    let mut out = Vec::new();
    loop {
        let mut size_line = String::new();
        reader.read_line(&mut size_line).map_err(|e| FetchError::Malformed {
            host: host.to_string(),
            detail: e.to_string(),
        })?;
        let size = usize::from_str_radix(size_line.trim().split(';').next().unwrap_or("").trim(), 16)
            .map_err(|_| FetchError::Malformed {
                host: host.to_string(),
                detail: format!("bad chunk size {size_line:?}"),
            })?;
        if size == 0 {
            break;
        }
        if out.len() + size > MAX_BODY_BYTES {
            return Err(FetchError::TooLarge { host: host.to_string(), limit: MAX_BODY_BYTES });
        }
        let mut chunk = vec![0u8; size];
        reader.read_exact(&mut chunk).map_err(|e| FetchError::Malformed {
            host: host.to_string(),
            detail: e.to_string(),
        })?;
        out.extend_from_slice(&chunk);
        let mut crlf = String::new();
        reader.read_line(&mut crlf).ok();
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plaintext_http_is_refused_and_not_upgraded() {
        let err = Target::parse("http://example.com/x").unwrap_err();
        let msg = err.to_string();
        assert!(
            msg.contains("refused, not upgraded"),
            "a silent upgrade makes the requested scheme and the used scheme two different \
             things with nothing observing the difference: {msg}"
        );
    }

    #[test]
    fn a_url_with_no_scheme_is_refused() {
        assert!(Target::parse("example.com").is_err());
        assert!(Target::parse("ftp://example.com").is_err());
    }

    #[test]
    fn userinfo_is_refused_because_it_hides_the_real_host() {
        // `https://trusted.example@evil.example/` fetches evil.example. An allowlist check on a
        // naively-parsed host would pass on the wrong string entirely.
        let err = Target::parse("https://trusted.example@evil.example/").unwrap_err();
        assert!(err.to_string().contains("userinfo"));
    }

    #[test]
    fn the_host_is_lowercased_so_an_allowlist_compares_one_spelling() {
        let t = Target::parse("https://Docs.Example.COM/a").expect("valid");
        assert_eq!(t.host, "docs.example.com");
        assert_eq!(t.port, 443);
        assert_eq!(t.path, "/a");
    }

    #[test]
    fn a_missing_path_becomes_root() {
        assert_eq!(Target::parse("https://example.com").expect("valid").path, "/");
    }

    #[test]
    fn an_explicit_port_is_kept() {
        let t = Target::parse("https://example.com:8443/x").expect("valid");
        assert_eq!(t.port, 8443);
    }
}
