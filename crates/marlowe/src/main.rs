//! The Marlowe binary.
//!
//! ADR-002: one binary, two roles — `marlowe` (thin client) and `marlowe --serve` (daemon).
//! Neither exists yet. M0b Session A ships one mode: the eval adapter, which is how the M0a
//! harness reaches an implementation over the section 4.0 transport.

mod adapter;
mod elapsed;

use std::io::{self, BufReader};
use std::path::PathBuf;

const USAGE: &str = "\
marlowe --eval-adapter --profile-root <DIR>

  Speak CONTRACTS.md section 4 over NDJSON on stdin/stdout.

  --profile-root <DIR>   A fresh, empty directory for this run's journal. Required, and
                         required to be empty: the harness spawns one process per corpus and
                         four more for the clock probe, and each must start from empty state.
";

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();

    if !args.iter().any(|a| a == "--eval-adapter") {
        eprintln!("{USAGE}");
        eprintln!("error: no mode selected. Session A ships only --eval-adapter.");
        std::process::exit(2);
    }

    let profile_root = match flag_value(&args, "--profile-root") {
        Some(v) => PathBuf::from(v),
        None => {
            eprintln!("{USAGE}");
            // Required rather than defaulted to a temp directory. A default would let two
            // spawns share one root, and the clock probe would compare contaminated runs
            // while reporting a clean verdict.
            eprintln!("error: --profile-root is required and has no default.");
            std::process::exit(2);
        }
    };

    let mut adapter = match adapter::Adapter::start(&profile_root) {
        Ok(a) => a,
        Err(e) => {
            // stderr is diagnostic only and is never parsed by the harness (section 4.0.1).
            eprintln!("marlowe: could not start against {}: {e}", profile_root.display());
            std::process::exit(1);
        }
    };

    let stdin = BufReader::new(io::stdin());
    // Locked once for the whole run rather than re-acquired per frame.
    let stdout = io::stdout();
    let stdout = stdout.lock();

    if let Err(e) = adapter.run(stdin, stdout) {
        eprintln!("marlowe: transport failure: {e}");
        std::process::exit(1);
    }

    // Section 4.0.6: the harness closes stdin, the implementation flushes and exits 0.
}

fn flag_value<'a>(args: &'a [String], flag: &str) -> Option<&'a str> {
    let index = args.iter().position(|a| a == flag)?;
    args.get(index + 1).map(String::as_str)
}
