//! A minimal blocking HTTP/1.1 client for a **loopback** endpoint.
//!
//! # Why this is not `reqwest`
//!
//! ADR-028 makes the default provider a local Ollama endpoint: `127.0.0.1`, no TLS, no auth, no
//! redirects, no proxies, no connection reuse worth the complexity. A general HTTP client would
//! bring an async runtime and a TLS stack onto the critical path of the one component that is
//! supposed to prove Marlowe needs no network.
//!
//! **The TLS question is deferred to the session that adds a hosted provider**, which is when it
//! is a real question with a real requirement behind it. Adding the dependency now would be
//! paying for a capability nothing uses, in the crate where the supply chain matters most.
//!
//! # What it deliberately cannot do
//!
//! No `https`, no redirect following, no keep-alive, no compression. It decodes a response body
//! with `Content-Length`, with `Transfer-Encoding: chunked`, or by reading to EOF — **chunked is
//! not optional**, because Ollama's `/api/tags` uses it and the first probe run failed on exactly
//! that. If anything beyond this becomes limiting, that is the signal to argue for a real client
//! rather than to grow this one: a hand-rolled HTTP client that has started following redirects
//! is a hand-rolled HTTP client with a security surface.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::time::Duration;

#[derive(Debug, thiserror::Error)]
pub enum HttpError {
    #[error("could not reach {endpoint}: {detail}")]
    Unreachable { endpoint: String, detail: String },
    #[error("{endpoint} returned HTTP {status}: {body}")]
    Status { endpoint: String, status: u16, body: String },
    #[error("malformed response from {endpoint}: {detail}")]
    Malformed { endpoint: String, detail: String },
}

/// A loopback endpoint. **Refuses anything that is not a local address**, because the whole
/// premise of ADR-028 is that the default path reaches no network.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LocalEndpoint {
    host: String,
    port: u16,
}

impl LocalEndpoint {
    pub const DEFAULT_PORT: u16 = 11434;

    /// `None` for a host that is not loopback.
    pub fn new(host: &str, port: u16) -> Option<Self> {
        let host = host.trim().to_ascii_lowercase();
        let loopback = host == "localhost" || host == "127.0.0.1" || host == "::1";
        loopback.then(|| Self { host, port })
    }

    pub fn default_ollama() -> Self {
        Self { host: "127.0.0.1".into(), port: Self::DEFAULT_PORT }
    }

    pub fn authority(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}

impl std::fmt::Display for LocalEndpoint {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "http://{}", self.authority())
    }
}

/// POST a JSON body and read a JSON response.
pub fn post_json(
    endpoint: &LocalEndpoint,
    path: &str,
    body: &serde_json::Value,
    timeout: Duration,
) -> Result<serde_json::Value, HttpError> {
    let raw = request(endpoint, "POST", path, Some(body), timeout)?;
    serde_json::from_str(&raw).map_err(|e| HttpError::Malformed {
        endpoint: endpoint.to_string(),
        detail: format!("{e}; body began: {}", raw.chars().take(200).collect::<String>()),
    })
}

pub fn get_json(
    endpoint: &LocalEndpoint,
    path: &str,
    timeout: Duration,
) -> Result<serde_json::Value, HttpError> {
    let raw = request(endpoint, "GET", path, None, timeout)?;
    serde_json::from_str(&raw).map_err(|e| HttpError::Malformed {
        endpoint: endpoint.to_string(),
        detail: e.to_string(),
    })
}

fn request(
    endpoint: &LocalEndpoint,
    method: &str,
    path: &str,
    body: Option<&serde_json::Value>,
    timeout: Duration,
) -> Result<String, HttpError> {
    let unreachable = |detail: String| HttpError::Unreachable {
        endpoint: endpoint.to_string(),
        detail,
    };

    let mut stream = TcpStream::connect(endpoint.authority()).map_err(|e| unreachable(e.to_string()))?;
    stream.set_read_timeout(Some(timeout)).map_err(|e| unreachable(e.to_string()))?;
    stream.set_write_timeout(Some(timeout)).map_err(|e| unreachable(e.to_string()))?;

    let serialized = body.map(|b| b.to_string()).unwrap_or_default();
    let mut head = format!(
        "{method} {path} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\nAccept: application/json\r\n",
        endpoint.authority()
    );
    if body.is_some() {
        head.push_str("Content-Type: application/json\r\n");
        head.push_str(&format!("Content-Length: {}\r\n", serialized.len()));
    }
    head.push_str("\r\n");

    stream.write_all(head.as_bytes()).map_err(|e| unreachable(e.to_string()))?;
    if body.is_some() {
        stream.write_all(serialized.as_bytes()).map_err(|e| unreachable(e.to_string()))?;
    }
    stream.flush().map_err(|e| unreachable(e.to_string()))?;

    let mut reader = BufReader::new(stream);
    let mut status_line = String::new();
    reader.read_line(&mut status_line).map_err(|e| unreachable(e.to_string()))?;
    let status: u16 = status_line
        .split_whitespace()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .ok_or_else(|| HttpError::Malformed {
            endpoint: endpoint.to_string(),
            detail: format!("no status in {status_line:?}"),
        })?;

    let mut content_length: Option<usize> = None;
    let mut chunked = false;
    loop {
        // LOOP-EXEMPT: header parsing, not a driving loop.
        let mut line = String::new();
        reader.read_line(&mut line).map_err(|e| unreachable(e.to_string()))?;
        if line.trim().is_empty() {
            break;
        }
        if let Some((name, value)) = line.split_once(':') {
            if name.trim().eq_ignore_ascii_case("content-length") {
                content_length = value.trim().parse().ok();
            }
            if name.trim().eq_ignore_ascii_case("transfer-encoding")
                && value.trim().eq_ignore_ascii_case("chunked")
            {
                chunked = true;
            }
        }
    }

    let mut out = String::new();
    if chunked {
        // Minimal chunked decoding: a hex length line, that many bytes, CRLF, until a zero
        // length. Ollama's /api/tags uses this and the first probe run failed on it.
        let mut body = Vec::new();
        loop {
            // LOOP-EXEMPT: chunk framing, not a driving loop.
            let mut size_line = String::new();
            reader.read_line(&mut size_line).map_err(|e| unreachable(e.to_string()))?;
            let size = usize::from_str_radix(
                size_line.trim().split(';').next().unwrap_or("").trim(),
                16,
            )
            .map_err(|e| HttpError::Malformed {
                endpoint: endpoint.to_string(),
                detail: format!("bad chunk size {size_line:?}: {e}"),
            })?;
            if size == 0 {
                break;
            }
            let mut chunk = vec![0u8; size];
            reader.read_exact(&mut chunk).map_err(|e| unreachable(e.to_string()))?;
            body.extend_from_slice(&chunk);
            let mut crlf = [0u8; 2];
            reader.read_exact(&mut crlf).map_err(|e| unreachable(e.to_string()))?;
        }
        out = String::from_utf8_lossy(&body).into_owned();
    } else {
        match content_length {
            Some(n) => {
                let mut buf = vec![0u8; n];
                reader.read_exact(&mut buf).map_err(|e| unreachable(e.to_string()))?;
                out = String::from_utf8_lossy(&buf).into_owned();
            }
            None => {
                reader.read_to_string(&mut out).map_err(|e| unreachable(e.to_string()))?;
            }
        }
    }

    if !(200..300).contains(&status) {
        return Err(HttpError::Status {
            endpoint: endpoint.to_string(),
            status,
            body: out.chars().take(300).collect(),
        });
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_loopback_endpoints_can_be_constructed() {
        // ADR-028's premise is that the default path reaches no network. An endpoint type that
        // accepted any host would let a config line turn the local-first design into a remote
        // one with nothing observing the change.
        assert!(LocalEndpoint::new("127.0.0.1", 11434).is_some());
        assert!(LocalEndpoint::new("localhost", 11434).is_some());
        assert!(LocalEndpoint::new("::1", 11434).is_some());

        assert!(LocalEndpoint::new("example.com", 11434).is_none());
        assert!(LocalEndpoint::new("10.0.0.5", 11434).is_none());
        assert!(LocalEndpoint::new("127.0.0.1.evil.com", 11434).is_none());
    }

    #[test]
    fn an_absent_endpoint_is_unreachable_rather_than_a_panic() {
        // Port 1 is reserved and nothing listens on it. The failure must be a typed error the
        // degradation path can read, not a crash — invariant 4.
        let e = get_json(
            &LocalEndpoint::new("127.0.0.1", 1).unwrap(),
            "/api/tags",
            Duration::from_millis(500),
        )
        .unwrap_err();
        assert!(matches!(e, HttpError::Unreachable { .. }), "{e}");
    }
}
