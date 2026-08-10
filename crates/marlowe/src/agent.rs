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
    thinking: bool,
) -> Result<(), String> {
    let mut config = DaemonConfig::new(profile_root, workspace);
    if let Some(p) = port {
        config.port = p;
    }
    config.dev = dev;
    config.thinking = thinking;
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
    thinking: bool,
) -> Result<(), String> {
    let client = Client::new("cli");

    if !client.daemon_is_up() {
        // Announced, never silent.
        eprintln!("marlowe: no daemon running — starting one in this process for this question.");
        eprintln!("marlowe: run `marlowe --serve` for a daemon that outlives the command.");
        let mut config = DaemonConfig::new(profile_root, workspace);
        config.dev = dev;
        config.thinking = thinking;
        if let Some(n) = context {
            config.context_tokens = n;
        }
        let mut daemon = Daemon::open(config).map_err(|e| e.to_string())?;
        // **The in-process path prompts too.**
        //
        // `Daemon::ask` uses the deny-by-default gate, which is correct for a daemon nobody is
        // attached to — and wrong here, because somebody *is* attached: this is a terminal. Left
        // as it was, the most natural command (`marlowe --ask`, no daemon running) would decline
        // every approval and read as a broken gate rather than an absent surface.
        let mut events = Vec::new();
        let mut gate = TerminalApprovals;
        daemon.ask_streaming_with("cli", message, &mut gate, |e| events.push(e));
        render(&events);
        return Ok(());
    }

    // **Collected, then rendered — but the approval is answered inline.**
    //
    // `render` resolves retractions across the whole list, which streaming cannot do (stdout
    // cannot be un-written), so the events are still gathered before printing. What changed is
    // that the gathering loop now answers §B9 prompts as they arrive: the daemon is blocked
    // reading the reply, so this cannot be deferred to the end.
    let mut events = Vec::new();
    client
        .ask_streaming_approving(
            message,
            &mut |event| (approve_at_the_terminal(event), None),
            &mut |event| events.push(event),
        )
        .map_err(|e| e.to_string())?;
    render(&events);
    Ok(())
}

/// The in-process gate, for `--ask` with no daemon running. Same prompt, no socket in between.
struct TerminalApprovals;

impl marlowe_loop::ApprovalGate for TerminalApprovals {
    fn await_approval(&mut self, radius: &marlowe_permission::BlastRadius) -> bool {
        approve_at_the_terminal(&Event::Approval {
            decision: 0,
            verb: radius.verb.clone(),
            scope: radius.scope.clone(),
            reversible: radius.reversible,
            novelty: radius.novelty.as_ref().map(|n| format!("{n:?}")),
        })
    }
}

/// §B9 at the command line: **state the blast radius, take one answer, default to no.**
///
/// It reads stdin. When stdin is not a terminal — a pipe, a script, `< /dev/null` — `read_line`
/// returns EOF and this returns `false`. That is the correct outcome and not a degradation: an
/// unattended `--ask` has nobody to approve anything, and approving because nothing objected is
/// the failure §8.2 puts enforcement in the harness to prevent.
///
/// Everything goes to **stderr**, so a piped `--ask` still produces clean output.
fn approve_at_the_terminal(event: &Event) -> bool {
    let Event::Approval { verb, scope, reversible, novelty, .. } = event else {
        return false;
    };
    eprintln!();
    eprintln!("  approval needed: {verb}");
    eprintln!("  on:              {scope}");
    eprintln!(
        "  reversible:      {}",
        if *reversible { "yes" } else { "NO — this cannot be undone" }
    );
    match novelty {
        Some(n) => eprintln!("  novelty:         {n}"),
        // §B9 wants a novelty reason and a ceiling. Neither is fabricated when absent: a
        // defaulted "routine" would be a claim about promotion logic nobody has written.
        None => eprintln!("  novelty:         not assessed (the trust ledger is M6)"),
    }
    eprint!("  approve? [y/N] ");
    let _ = std::io::Write::flush(&mut std::io::stderr());

    let mut line = String::new();
    match std::io::stdin().read_line(&mut line) {
        Ok(0) | Err(_) => {
            eprintln!("no answer available — declined");
            false
        }
        Ok(_) => {
            let yes = matches!(line.trim().to_ascii_lowercase().as_str(), "y" | "yes");
            eprintln!("{}", if yes { "approved" } else { "declined" });
            yes
        }
    }
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

/// Drop every `Text` event that a later `SpeechRetracted` proved was reasoning.
///
/// A retraction applies to the speech emitted **so far in the turn**, so it clears the run of
/// `Text` events back to the previous retraction or the start of the list — the same span the
/// TUI moves into its thinking block.
fn resolve_retractions(events: &[Event]) -> Vec<Event> {
    let mut out: Vec<Event> = Vec::with_capacity(events.len());
    for event in events {
        match event {
            Event::SpeechRetracted => out.retain(|e| !matches!(e, Event::Text { .. })),
            other => out.push(other.clone()),
        }
    }
    out
}

/// Render events as §B6 asks: one line per tool call, prose as prose, failures visible.
///
/// **Retractions are resolved before anything prints.** `stdout` cannot be un-written, so the TUI's
/// approach — move the text into the thinking block — has no equivalent here. The classic path
/// gets the whole event list at once, so the retraction is applied to the list instead: text the
/// model later proved was reasoning never reaches the pipe in the first place.
fn render(events: &[Event]) {
    let events = resolve_retractions(events);
    for event in &events {
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
            // Only ever produced by `Replay`, which the classic path does not use.
            Event::User { text } => println!("> {text}"),
            // The classic path has no collapsible element, so reasoning is counted rather than
            // printed: it is progress, not an answer, and dumping a chain of thought into a
            // piped stdout would make `--ask` unusable in a script.
            Event::Reasoning { .. } => {}
            // Already applied by `resolve_retractions`, above.
            Event::SpeechRetracted => {}
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
