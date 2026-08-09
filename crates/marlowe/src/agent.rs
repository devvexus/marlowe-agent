//! `--serve` and `--ask`: the two roles of ARCHITECTURE §6, at the command line.
//!
//! This is the first path in the product where a real model answers a real question through the
//! real loop. Everything before it ran against M1's scripted stub.
//!
//! # `--ask` is a thin client and nothing else
//!
//! It connects, sends one message, renders the events, and exits. It holds no run state — the
//! daemon owns the run, which is why closing this process does not end it (§6, invariant 6).
//! **It auto-spawns a daemon if none is listening, and says so**, because a process appearing on
//! a machine without the user being told is what a well-behaved tool does not do.

use std::path::PathBuf;

use marlowe_daemon::protocol::Event;
use marlowe_daemon::{Client, Daemon, DaemonConfig};

/// Where the profile lives when nobody says otherwise.
///
/// Under the user's data directory rather than the workspace: a journal inside the workspace
/// would be reachable by `read`, and ARCHITECTURE invariant 8 requires the journal to sit
/// **outside the model's filesystem scope** so that forgetting is not cosmetic.
pub fn default_profile_root() -> PathBuf {
    let base = std::env::var_os("LOCALAPPDATA")
        .or_else(|| std::env::var_os("XDG_DATA_HOME"))
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    base.join("marlowe").join("default-profile")
}

pub fn serve(
    workspace: PathBuf,
    profile_root: PathBuf,
    port: Option<u16>,
    dev: bool,
    context: Option<u32>,
) -> Result<(), String> {
    let mut config = DaemonConfig::new(profile_root, workspace);
    if let Some(p) = port {
        config.port = p;
    }
    config.dev = dev;
    if let Some(n) = context {
        config.context_tokens = n;
    }
    eprintln!(
        "marlowe: context window {} tokens (model ceiling {})",
        config.context_tokens,
        marlowe_provider::MODEL_CONTEXT_CEILING
    );
    let port = config.port;
    let daemon = Daemon::open(config).map_err(|e| e.to_string())?;
    eprintln!("marlowe: daemon listening on 127.0.0.1:{port}");
    eprintln!("marlowe: runs are owned here and survive the client that started them");
    daemon.serve().map_err(|e| e.to_string())
}

/// One question, one answer. Auto-spawns a daemon if none is up.
pub fn ask(
    message: &str,
    workspace: PathBuf,
    profile_root: PathBuf,
    dev: bool,
    context: Option<u32>,
) -> Result<(), String> {
    let client = Client::new("cli");

    if !client.daemon_is_up() {
        // Announced, never silent.
        eprintln!("marlowe: no daemon running — starting one in this process for this question.");
        eprintln!("marlowe: run `marlowe --serve` for a daemon that outlives the command.");
        let mut config = DaemonConfig::new(profile_root, workspace);
        config.dev = dev;
        if let Some(n) = context {
            config.context_tokens = n;
        }
        let mut daemon = Daemon::open(config).map_err(|e| e.to_string())?;
        render(&daemon.ask("cli", message));
        return Ok(());
    }

    let events = client.ask(message).map_err(|e| e.to_string())?;
    render(&events);
    Ok(())
}

pub fn status(workspace: PathBuf, profile_root: PathBuf) -> Result<(), String> {
    let client = Client::new("cli");
    let events = if client.daemon_is_up() {
        client.status().map_err(|e| e.to_string())?
    } else {
        let config = DaemonConfig::new(profile_root, workspace);
        let daemon = Daemon::open(config).map_err(|e| e.to_string())?;
        vec![Event::Status(daemon.status())]
    };
    render(&events);
    Ok(())
}

/// Render events as §B6 asks: one line per tool call, prose as prose, failures visible.
fn render(events: &[Event]) {
    for event in events {
        match event {
            Event::Status(r) => {
                println!("marlowe {}", r.version);
                println!("  workspace   {}", r.workspace);
                println!("  model       {}", r.model_disclosure);
                // ADR-029: announced, never inferred.
                println!("  rerank      {}", r.rerank_provider);
                println!("  runs        {} live", r.live_runs);
                match &r.degraded {
                    Some(d) => println!("  DEGRADED    {d}"),
                    None => println!("  ready"),
                }
            }
            Event::Text { delta } => print!("{delta}"),
            Event::Tool { verb, target, state, summary, .. } => {
                println!("  ⋯ {verb}  {target}  {summary}  [{state}]");
            }
            Event::Compacted { turns } => println!("  ─ compacted · {turns} turns ─"),
            Event::Degraded { what, remedy } => {
                println!("  ! {what}");
                println!("    {remedy}");
            }
            Event::Approval { verb, scope, reversible, .. } => {
                println!(
                    "  ? approval needed: {verb} {scope}{}",
                    if *reversible { "" } else { " · not recoverable" }
                );
                println!("    (no interactive surface attached; the harness declined)");
            }
            Event::Done { outcome, detail, elapsed_ms, .. } => {
                if !detail.is_empty() {
                    println!("{detail}");
                }
                println!("  [{outcome} · {elapsed_ms} ms]");
            }
            Event::Run { id, status, tokens, .. } => {
                println!("  run {id}  {status}  {tokens} tokens");
            }
            Event::Error { detail } => println!("  error: {detail}"),
        }
    }
}
