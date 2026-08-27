//! **The providers a build can be switched between — the single definition of that set.**
//!
//! # Why this lives in the view crate and not in the daemon
//!
//! It used to live in `marlowe_daemon::project::PROVIDERS`, and there was a second copy in
//! `marlowe_stub::script` — `["ollama", "openrouter"]`, two entries, out of date the moment a
//! third arrived. `marlowe-stub` **structurally cannot reach `marlowe-daemon`** (that is the C2d
//! acceptance and it is enforced by the dependency graph), so the two lists could never have been
//! made to agree from either end. The fix is not a rule about keeping them in step; it is putting
//! the list in the one crate both can see.
//!
//! `marlowe-view` depends on nothing, and the stub, the daemon and the surface all depend on it.
//! So: here.
//!
//! # `ollama/llama.cpp` is ONE entry naming TWO halves, and that is the decision
//!
//! ADR-060, accepted 2026-08-27. Ollama stores, downloads and lists the models; `llama-server`
//! serves them off the blob Ollama already holds. It is a single choice because the user makes a
//! single choice — *"simple on the user"* — and it names both halves because the user must be able
//! to see **which engine is answering**. A silent swap under the existing `ollama` entry would have
//! served 52 ms from a different runtime while the screen said `ollama`, with no way to find out.
//!
//! Plain `ollama` stays selectable, unchanged, for compatibility. `openrouter` is untouched.

/// The provider names, in the order a picker offers them.
///
/// **Every consumer reads this array**: the daemon's picker, the daemon's `set_provider`
/// validation, the stub's scripted control strip, and `marlowe-surface`'s `/provider` help text.
/// A name a user can see is therefore a name the daemon accepts, by construction rather than by
/// review.
pub const PROVIDERS: &[&str] = &[OLLAMA, HYBRID, OPENROUTER];

/// ADR-028's default. Ollama stores the models **and** runs them.
pub const OLLAMA: &str = "ollama";

/// ADR-060's hybrid. Ollama stores and lists; a supervised `llama-server` runs.
///
/// **The spelling is load-bearing in three places at once** — the picker's option, the string
/// `ModelProviderChoice::name()` returns, and the value `set_provider` accepts — so it is a
/// constant rather than three literals. `project.rs`'s picker locates the active provider with
/// `position()`, and a mismatch there does not error: it selects index 0 and renders a hybrid
/// daemon as plain `ollama`, which is a silent wrong answer in the one place a user reads which
/// engine is live.
pub const HYBRID: &str = "ollama/llama.cpp";

/// ADR-046. Hosted, opt-in, needs a key.
pub const OPENROUTER: &str = "openrouter";
