//! Brief §8.2 — egress allowlisting, deny-by-default per run.
//!
//! This is the third leg of the lethal trifecta (§8.1) and one of the three mechanisms that
//! ADR-002 names as the reason `Inert` reads stay unchecked on targets. If it weakens, that
//! exemption is revisited rather than inherited.
//!
//! # The URL parser is deliberately strict, and refuses rather than guesses
//!
//! A permissive URL parser is the wrong instrument here. Host confusion — userinfo before an
//! `@`, an IPv6 literal, a trailing dot, a percent-encoded separator — is how an allowlist
//! gets walked past while still matching a pattern. Every one of those forms is **refused**
//! rather than normalized, because a normalizer has to be right about every encoding and a
//! refusal only has to be right about one thing.
//!
//! The cost is real and is accepted: Marlowe cannot fetch `http://user:pw@host/` or
//! `http://[::1]/`. Both are recoverable by the user restating the URL in a plain form, and
//! neither is worth a parser whose failure mode is a silently wrong host.

use marlowe_tools::HostPattern;
use serde::{Deserialize, Serialize};

/// A validated destination host: lowercase, ASCII, no port, no userinfo.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(transparent)]
pub struct Host(String);

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum HostError {
    #[error("`{url}` has no http/https scheme; egress is only adjudicated for schemes it can parse")]
    UnsupportedScheme { url: String },
    #[error(
        "`{url}` carries userinfo before `@`. The form is refused rather than parsed: it is the \
         classic way to make a URL read as one host and resolve as another"
    )]
    Userinfo { url: String },
    #[error("`{url}` uses an address literal or an unsupported authority form")]
    UnsupportedAuthority { url: String },
    #[error("`{url}` has an empty or malformed host")]
    MalformedHost { url: String },
}

impl Host {
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Extract the host from an absolute http/https URL, or refuse.
    pub fn from_url(url: &str) -> Result<Self, HostError> {
        let lower = url.trim().to_ascii_lowercase();
        let rest = lower
            .strip_prefix("https://")
            .or_else(|| lower.strip_prefix("http://"))
            .ok_or_else(|| HostError::UnsupportedScheme { url: url.to_string() })?;

        let authority = rest.split(['/', '?', '#']).next().unwrap_or("");

        if authority.contains('@') {
            return Err(HostError::Userinfo { url: url.to_string() });
        }
        if authority.contains('[') || authority.contains(']') {
            return Err(HostError::UnsupportedAuthority { url: url.to_string() });
        }

        // A port is permitted and dropped: the allowlist is about *where the bytes go*, and a
        // pattern set that had to enumerate ports would be one people write `*` into.
        let host = authority.split(':').next().unwrap_or("");
        Self::parse(host).ok_or_else(|| HostError::MalformedHost { url: url.to_string() })
    }

    /// A bare host name, validated. `None` for anything that is not plainly a DNS name.
    pub fn parse(host: &str) -> Option<Self> {
        let host = host.to_ascii_lowercase();
        if host.is_empty() || host.len() > 253 {
            return None;
        }
        // A trailing dot is DNS-equivalent and string-distinct. Refused rather than trimmed:
        // "equivalent under one comparison and not another" is exactly the seam an allowlist
        // gets walked past through.
        if host.starts_with('.') || host.ends_with('.') {
            return None;
        }
        for label in host.split('.') {
            if label.is_empty() || label.len() > 63 {
                return None;
            }
            if label.starts_with('-') || label.ends_with('-') {
                return None;
            }
            if !label.chars().all(|c| c.is_ascii_alphanumeric() || c == '-') {
                return None;
            }
        }
        Some(Self(host))
    }
}

/// Whether a pattern admits a host. Exact, or a `*.` suffix.
///
/// `*.example.com` matches `a.example.com` and **not** `example.com`. A wildcard that also
/// matched the apex would silently widen every pattern by one host, and the apex is usually
/// the one worth naming explicitly.
fn pattern_admits(pattern: &str, host: &Host) -> bool {
    let pattern = pattern.trim().to_ascii_lowercase();
    if pattern == "*" {
        return true;
    }
    match pattern.strip_prefix("*.") {
        Some(suffix) => {
            let Some(rest) = host.as_str().strip_suffix(suffix) else { return false };
            rest.ends_with('.') && rest.len() > 1
        }
        None => host.as_str() == pattern,
    }
}

/// A run's outbound network grant. **Deny-by-default** — that is the `Default` impl, and it is
/// the one a forgotten field gets.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EgressPolicy {
    /// No outbound network at all.
    DenyAll,
    /// Exactly these patterns.
    Allow { hosts: Vec<HostPattern> },
    /// Anywhere. **Spelled out so it is greppable**: this variant exists so that "the run may
    /// reach the open web" is a decision somebody made and a reviewer can find, rather than a
    /// `*` that appeared in a pattern list.
    AllowAnyHost,
}

impl Default for EgressPolicy {
    fn default() -> Self {
        Self::DenyAll
    }
}

impl EgressPolicy {
    pub fn allow(hosts: &[&str]) -> Self {
        Self::Allow { hosts: hosts.iter().map(|h| HostPattern::new(*h)).collect() }
    }

    /// Whether **this run** grants the destination. Half the decision; see [`Self::permits`].
    pub fn grants(&self, host: &Host) -> bool {
        match self {
            EgressPolicy::DenyAll => false,
            EgressPolicy::AllowAnyHost => true,
            EgressPolicy::Allow { hosts } => hosts.iter().any(|p| pattern_admits(p.as_str(), host)),
        }
    }

    /// The full decision: the run grants it **and** the tool declared it.
    ///
    /// Two sets, intersected, and neither one alone is the answer. The manifest is the tool's
    /// declared maximum — its audit surface — and the policy is this run's grant. A tool that
    /// declared `*` still reaches only what the run allows; a run that allows everything still
    /// cannot make a connector reach a host it never declared.
    pub fn permits(&self, host: &Host, declared: &[HostPattern]) -> bool {
        self.grants(host) && declared.iter().any(|p| pattern_admits(p.as_str(), host))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn h(s: &str) -> Host {
        Host::parse(s).unwrap()
    }

    #[test]
    fn the_default_is_deny_all() {
        assert_eq!(EgressPolicy::default(), EgressPolicy::DenyAll);
        assert!(!EgressPolicy::default().grants(&h("example.com")));
    }

    #[test]
    fn confusing_url_forms_are_refused_not_normalized() {
        // Each of these is a form where a permissive parser and a strict one disagree about
        // the host. Disagreement is the vulnerability, so both sides refuse.
        assert!(matches!(
            Host::from_url("https://evil.example@good.example/"),
            Err(HostError::Userinfo { .. })
        ));
        assert!(matches!(
            Host::from_url("https://[::1]/x"),
            Err(HostError::UnsupportedAuthority { .. })
        ));
        assert!(matches!(
            Host::from_url("ftp://good.example/"),
            Err(HostError::UnsupportedScheme { .. })
        ));
        assert!(matches!(
            Host::from_url("https://good.example./"),
            Err(HostError::MalformedHost { .. })
        ));
        assert!(matches!(
            Host::from_url("https://goo%64.example/"),
            Err(HostError::MalformedHost { .. })
        ));
    }

    #[test]
    fn ordinary_urls_parse_to_their_host() {
        assert_eq!(Host::from_url("https://Example.COM/a?b#c").unwrap(), h("example.com"));
        assert_eq!(Host::from_url("http://a.b.example.com:8443/x").unwrap(), h("a.b.example.com"));
    }

    #[test]
    fn a_wildcard_does_not_match_the_apex() {
        let p = EgressPolicy::allow(&["*.example.com"]);
        assert!(p.grants(&h("api.example.com")));
        assert!(p.grants(&h("a.b.example.com")));
        assert!(!p.grants(&h("example.com")), "the apex needs naming explicitly");
        assert!(!p.grants(&h("notexample.com")));
        // The suffix-match trap: `evilexample.com` ends with `example.com` textually.
        assert!(!p.grants(&h("evilexample.com")));
    }

    #[test]
    fn the_decision_is_the_intersection_of_grant_and_declaration() {
        let policy = EgressPolicy::allow(&["api.example.com"]);
        let declared_anything = [HostPattern::new("*")];
        let declared_elsewhere = [HostPattern::new("other.example.com")];

        assert!(policy.permits(&h("api.example.com"), &declared_anything));
        assert!(
            !policy.permits(&h("api.example.com"), &declared_elsewhere),
            "a run's grant cannot widen a tool past what it declared"
        );
        assert!(
            !policy.permits(&h("other.example.com"), &declared_elsewhere),
            "a tool's declaration cannot widen a run past what it granted"
        );
    }

    #[test]
    fn allow_any_host_is_a_named_variant_not_a_pattern() {
        assert!(EgressPolicy::AllowAnyHost.grants(&h("anything.example")));
        // ...and it still does not bypass the tool's declaration.
        assert!(!EgressPolicy::AllowAnyHost
            .permits(&h("anything.example"), &[HostPattern::new("only.example")]));
    }
}
