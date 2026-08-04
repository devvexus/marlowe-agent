//! The Marlowe binary.
//!
//! ADR-002: one binary, two roles — `marlowe` (thin client) and `marlowe --serve` (daemon).
//! Neither exists yet. M0b ships one mode: the eval adapter, which is how the M0a harness
//! reaches an implementation over the section 4.0 transport.

mod adapter;
mod dump;
mod elapsed;

use std::io::{self, BufReader};
use std::path::PathBuf;

const USAGE: &str = "\
marlowe --eval-adapter --profile-root <DIR> [--dump-gate-features <FILE>] [--fit-mode]

  Speak CONTRACTS.md section 4 over NDJSON on stdin/stdout.

  --profile-root <DIR>          A fresh, empty directory for this run's journal. Required, and
                                required to be empty: the harness spawns one process per corpus
                                and four more for the clock probe, and each must start from
                                empty state.

  --dump-gate-features <FILE>   Write one NDJSON row per SCORED CANDIDATE to FILE. A diagnostic
                                side channel: it never changes what goes on the wire. With a
                                gate loaded each row also carries this build's own `score`,
                                `calibrated_precision` and `passes` -- which is what a scoring
                                run reads when the gate abstains and the response therefore
                                carries no injected memories at all.

  --fit-mode                    Load NO gate. Used only by `tools/fit_gate.py`, to produce the
                                features the gate is fit from before any gate exists. The gate
                                stamp reads `uncalibrated-fit-only`, never `frozen-v1`: this
                                mode calibrates nothing and must not be mistakable for a run
                                that did. Requires --dump-gate-features.
";

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();

    if !args.iter().any(|a| a == "--eval-adapter") {
        eprintln!("{USAGE}");
        eprintln!("error: no mode selected. M0b ships only --eval-adapter.");
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

    // Present-but-empty is a typo, not a request for a default path. Named explicitly because
    // the alternative -- silently dumping to some default file -- would let a fit run against
    // a stale dump from an earlier session and produce an artifact nobody could reproduce.
    if args.iter().any(|a| a == "--dump-gate-features")
        && flag_value(&args, "--dump-gate-features").is_none()
    {
        eprintln!("{USAGE}");
        eprintln!("error: --dump-gate-features requires a path and has no default.");
        std::process::exit(2);
    }

    let dump_path = flag_value(&args, "--dump-gate-features").map(std::path::Path::new);
    let fit_mode = args.iter().any(|a| a == "--fit-mode");

    let started = match (fit_mode, dump_path) {
        (true, Some(path)) => adapter::Adapter::start_for_fit(&profile_root, path),
        (true, None) => {
            eprintln!("{USAGE}");
            // Refused rather than defaulted to a path. Fit mode with nowhere to write is a run
            // that loads no gate and produces nothing -- silently useless.
            eprintln!("error: --fit-mode requires --dump-gate-features.");
            std::process::exit(2);
        }
        (false, path) => adapter::Adapter::start(&profile_root, path),
    };

    let mut adapter = match started {
        Ok(a) => a,
        Err(e) => {
            // stderr is diagnostic only and is never parsed by the harness (section 4.0.1).
            // An unfitted gate artifact lands here, and the error names the command that
            // regenerates it -- see `marlowe_memory::gate::GateError`.
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
    args.get(index + 1)
        .map(String::as_str)
        // A following token that is itself a flag means the value was omitted.
        .filter(|v| !v.starts_with("--"))
}
