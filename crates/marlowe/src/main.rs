//! The Marlowe binary.
//!
//! ADR-002: one binary, two roles — `marlowe` (thin client) and `marlowe --serve` (daemon).
//! The daemon does not exist yet. M1 adds the client's two surfaces, driven by a scripted stub:
//! `--tui` (Addendum B v2) and `--classic` (§B11). M0b's eval adapter is unchanged.

mod adapter;
mod dump;
mod elapsed;
mod launcher;
mod tui;

use std::io::{self, BufReader};
use std::path::PathBuf;

const USAGE: &str = "\
marlowe --launch
marlowe --tui [--timing-probe] [--color-depth <truecolor|256|16>] [--ground]
marlowe --classic
marlowe --doctor
marlowe --eval-adapter --profile-root <DIR> --embedder-model <DIR> --reranking <off|DIR>
        [--embedding-cache <DIR>] [--embedder-workers <N>]
        [--dump-gate-features <FILE>] [--fit-mode]
        [--dump-consolidation <FILE>] [--consolidation-dry-run]

  --tui                         The terminal interface. Requires at least 120x30; below that it
                                prints one line naming the current and required size and offers
                                --classic. It does NOT render a degraded grid -- a narrow variant
                                was designed and rejected because it cost the borders, which cost
                                the region contract, which is the entire design (Addendum B §B11).

  --diagnostic                  Render raw-mode state, the colour tier and a LIVE KEYSTROKE
                                COUNTER in the titlebar. A running TUI's most important properties
                                are invisible from outside the process, and a separate probe run
                                measures a different process. This makes the session answer for
                                itself: a terminal that renders and animates while ignoring every
                                key looks exactly like one that works.

  --timing-probe                Draw one frame, report time to first frame and time to
                                interactive in milliseconds, and leave. K4 is stated in these
                                numbers, so they are a command that prints them rather than a
                                target nobody measures.

  --color-depth <TIER>          Override the colour-depth probe. §B2 requires the 256- and
                                16-colour fallbacks, so a probe cannot be avoided -- but a silent
                                probe is the mismatch-hiding default this project has shipped four
                                bugs behind. The probe's answer is printed by --timing-probe and
                                --doctor, and this is how it is overridden.

  --classic                     The classic CLI: a readline REPL with COMMAND parity, not layout
                                parity. The narrow, SSH, piped-stdin and no-TTY path. Both
                                surfaces dispatch from one command registry, so parity is a
                                property of the design rather than a checklist that rots.

  --doctor                      Terminal capability report: size, colour depth and why it was
                                chosen, accent contrast against a dark and a light background, and
                                the braille glyph row for you to confirm BY EYE. Font coverage for
                                U+2800-U+28FF cannot be detected, and ADR-021 refuses to add a
                                silent fallback -- so the check is given to the only instrument
                                that can read it.

  Speak CONTRACTS.md section 4 over NDJSON on stdin/stdout.

  --profile-root <DIR>          A fresh, empty directory for this run's journal. Required, and
                                required to be empty: the harness spawns one process per corpus
                                and four more for the clock probe, and each must start from
                                empty state.

  --embedder-model <DIR>        ADR-004's embedding model. Required, no default. The files are
                                verified against digests pinned in the binary, so a swapped or
                                partial model is a refusal rather than a quietly different
                                number. Fetch with `python tools/fetch_model.py`.

  --reranking <off|DIR>         Session H's in-session cross-encoder rerank stage. REQUIRED, no
                                default, and it takes an EXPLICIT value -- either the literal
                                `off` or the directory holding the pinned graph and tokenizer.
                                The pinned graph is the SESSION J FINE-TUNE, f32:
                                models/ms-marco-MiniLM-L-2-v2-ft-session-j (ADR-018, held-out
                                R@1 0.6725 at 214 ms/query). The pre-Session-K int8 directory is
                                refused BY NAME rather than by a missing-file error.
                                Deliberately NOT a bare `--rerank` boolean. That is the mistake
                                the consolidation flag documents below: forget a default-off
                                switch in the harness target string and the run measures the
                                un-reranked system under a reranked label, producing every number
                                with nothing observing the mismatch. Spelling `off` is a choice
                                somebody made and the report records it; omitting the flag is a
                                refusal to start.

  --embedding-cache <DIR>       Content-addressed embedding cache, keyed on the model and
                                vocabulary digests, the embedder version and the sequence
                                length. Optional. NOT inside --profile-root, which is required
                                to be empty per spawn and would make the cache cold every time.

  --embedder-workers <N>        Forward passes to run concurrently. A throughput knob and
                                provably NOT a quality knob: each text is embedded entirely
                                within one worker, asserted bit-for-bit at 1/3/8 workers.
                                Default: available parallelism, capped at 8.

  --dump-gate-features <FILE>   Write one NDJSON row per SCORED CANDIDATE to FILE. A diagnostic
                                side channel: it never changes what goes on the wire. With a
                                gate loaded each row also carries this build's own `score`,
                                `calibrated_precision` and `passes` -- which is what a scoring
                                run reads when the gate abstains and the response therefore
                                carries no injected memories at all.

  --dump-consolidation <FILE>   Write one NDJSON row per INGESTED SESSION describing what §5.3
                                consolidation merged. A diagnostic side channel: the §4.6
                                response is byte-identical with or without it.

  --consolidation-dry-run       Cluster at every threshold in SWEEP_THRESHOLDS and APPLY NOTHING.
                                This is the pass the frozen merge threshold is chosen from, so it
                                must not itself assume one. Loads no consolidation artifact, and
                                requires --dump-consolidation: a dry run with nowhere to write
                                its sweep changes nothing and produces nothing.

                                WITHOUT this flag consolidation is ON and reads its threshold
                                from the frozen artifact. There is deliberately no flag that
                                turns it off -- a default-off switch is the permissive default
                                that lets a run measure the unconsolidated system under a
                                consolidated label.

  --fit-mode                    Load NO gate. Used only by `tools/fit_gate.py`, to produce the
                                features the gate is fit from before any gate exists. The gate
                                stamp reads `uncalibrated-fit-only`, never `frozen-v2`: this
                                mode calibrates nothing and must not be mistakable for a run
                                that did. Requires --dump-gate-features.
";

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();

    // Modes are mutually exclusive and named. There is deliberately no default mode: a bare
    // `marlowe` becomes the thin client at M2, and guessing one now would mean changing what an
    // existing command does later.
    let modes: Vec<&str> = ["--tui", "--classic", "--doctor", "--eval-adapter", "--launch"]
        .into_iter()
        .filter(|m| args.iter().any(|a| a == m))
        .collect();
    match modes.len() {
        1 => {}
        0 => {
            eprintln!("{USAGE}");
            eprintln!(
                "error: no mode selected. One of --launch, --tui, --classic, --doctor, --eval-adapter."
            );
            std::process::exit(2);
        }
        _ => {
            eprintln!("{USAGE}");
            eprintln!(
                "error: {} were all given. They are different surfaces over the same session, not \
                 layers; pick one.",
                modes.join(" and ")
            );
            std::process::exit(2);
        }
    }

    // §B17. Opens a terminal Marlowe controls, rather than assuming this one is suitable.
    if modes[0] == "--launch" {
        let extra: Vec<String> = args.iter().filter(|a| *a != "--launch").cloned().collect();
        match launcher::launch(&extra) {
            Ok(o) => {
                // Report what was chosen, always. A launcher that silently accepts a terminal it
                // could not configure is how "the font is wrong" becomes a bug against the frame.
                match &o.terminal {
                    Some(t) => println!("terminal   {t}{}", if o.profile_written {
                        " (Marlowe profile)"
                    } else {
                        " (no profile; direct launch)"
                    }),
                    None => println!("terminal   this one"),
                }
                // Global settings are named individually. Windows Terminal keeps window chrome
                // outside profiles, so theming it necessarily reaches past "adds one, modifies
                // none" — which is allowed, and is never silent.
                if !o.globals_changed.is_empty() {
                    println!("globals    {} (chrome is global in Windows Terminal; \
                              settings.json.marlowe-backup holds the previous file)",
                             o.globals_changed.join(", "));
                }
                for d in &o.degraded {
                    println!("degraded   {d}");
                }
                if o.terminal.is_none() {
                    // Nothing suitable was found. Run here rather than refuse, having said what
                    // is degraded — §B17 asks for the note, not for a dead end.
                    if let Err(e) = tui::run(tui::Options {
                        timing_probe: false,
                        diagnostic: false,
                        color_depth: None,
                        ground: true,
                        panic_probe: false,
                    }) {
                        eprintln!("error: {e}");
                        std::process::exit(1);
                    }
                }
            }
            Err(e) => {
                eprintln!("error: {e}");
                std::process::exit(1);
            }
        }
        return;
    }

    if modes[0] == "--tui" {
        let opts = tui::Options {
            timing_probe: args.iter().any(|a| a == "--timing-probe"),
            diagnostic: args.iter().any(|a| a == "--diagnostic"),
            color_depth: flag_value(&args, "--color-depth").map(str::to_string),
            ground: args.iter().any(|a| a == "--ground"),
            panic_probe: args.iter().any(|a| a == "--panic-probe"),
        };
        if args.iter().any(|a| a == "--color-depth") && opts.color_depth.is_none() {
            eprintln!("error: --color-depth requires a value: truecolor, 256 or 16.");
            std::process::exit(2);
        }
        if let Err(e) = tui::run(opts) {
            eprintln!("error: {e}");
            std::process::exit(1);
        }
        return;
    }

    if modes[0] == "--classic" {
        let stdin = io::stdin();
        let clock = marlowe_stub::Clock::real();
        if let Err(e) = marlowe_surface::cli::run(stdin.lock(), io::stdout(), &clock) {
            eprintln!("error: {e}");
            std::process::exit(1);
        }
        return;
    }

    if modes[0] == "--doctor" {
        for line in marlowe_surface::doctor::report(&marlowe_stub::Session::new()) {
            println!("{line}");
        }
        return;
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

    // Same rule as --dump-gate-features: present-but-empty is a typo, not a request for a
    // default path. A default here would let a sweep land in a stale file from an earlier run
    // and produce a threshold nobody could reproduce.
    if args.iter().any(|a| a == "--dump-consolidation")
        && flag_value(&args, "--dump-consolidation").is_none()
    {
        eprintln!("{USAGE}");
        eprintln!("error: --dump-consolidation requires a path and has no default.");
        std::process::exit(2);
    }

    let dump_path = flag_value(&args, "--dump-gate-features").map(std::path::Path::new);
    let fit_mode = args.iter().any(|a| a == "--fit-mode");
    let consolidation_dump = flag_value(&args, "--dump-consolidation").map(std::path::Path::new);
    let consolidation = if args.iter().any(|a| a == "--consolidation-dry-run") {
        if consolidation_dump.is_none() {
            eprintln!("{USAGE}");
            // Refused rather than defaulted. A dry run applies nothing, so a dry run with nowhere
            // to write its sweep is a run that changes nothing and records nothing -- silently
            // useless, and indistinguishable from a consolidated run that merged nothing.
            eprintln!("error: --consolidation-dry-run requires --dump-consolidation.");
            std::process::exit(2);
        }
        adapter::Consolidate::DryRun
    } else {
        adapter::Consolidate::Frozen
    };

    // Required, with no default, for the same reason --profile-root is: a default path here
    // would let a run silently pick up whatever model happened to be lying around, and a
    // different model still embeds, still scores, and still produces a number.
    let embedder_model = match flag_value(&args, "--embedder-model") {
        Some(v) => PathBuf::from(v),
        None => {
            eprintln!("{USAGE}");
            eprintln!(
                "error: --embedder-model is required and has no default. Fetch it with `python tools/fetch_model.py`."
            );
            std::process::exit(2);
        }
    };
    // Required, and it takes an explicit value. See USAGE: a bare boolean here is exactly the
    // failure mode the consolidation flag exists to avoid.
    let reranking = match flag_value(&args, "--reranking") {
        Some(v) if v == "off" => None,
        Some(v) => Some(PathBuf::from(v)),
        None => {
            eprintln!("{USAGE}");
            eprintln!(
                "error: --reranking is required and has no default. Pass `off` to disable the \
                 cross-encoder explicitly, or the directory holding its pinned files."
            );
            std::process::exit(2);
        }
    };

    let cache_dir = flag_value(&args, "--embedding-cache").map(PathBuf::from);
    let workers = match flag_value(&args, "--embedder-workers") {
        Some(v) => match v.parse::<usize>() {
            Ok(n) if n >= 1 => n,
            _ => {
                eprintln!("{USAGE}");
                eprintln!("error: --embedder-workers must be a positive integer, got {v:?}.");
                std::process::exit(2);
            }
        },
        None => std::thread::available_parallelism().map_or(1, |n| n.get().min(8)),
    };

    let embedder = match marlowe_memory::cue::dense::embedder::Embedder::load(
        &embedder_model,
        workers,
        cache_dir.as_deref(),
    ) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("marlowe: {e}");
            std::process::exit(1);
        }
    };

    // Loaded HERE rather than at first retrieval, for the same reason the gate is: a bad artifact
    // must stop the process, not become a per-query error the harness scores as a wrong number.
    let cross_encoder = match reranking {
        Some(dir) => match marlowe_memory::rerank::CrossEncoder::load(&dir) {
            Ok(e) => Some(e),
            Err(e) => {
                eprintln!("marlowe: {e}");
                std::process::exit(1);
            }
        },
        None => None,
    };

    let consolidation = adapter::Consolidation {
        policy: consolidation,
        dump_path: consolidation_dump,
    };
    let started = match (fit_mode, dump_path) {
        (true, Some(path)) => {
            adapter::Adapter::start_for_fit(&profile_root, embedder, path, consolidation, cross_encoder)
        }
        (true, None) => {
            eprintln!("{USAGE}");
            // Refused rather than defaulted to a path. Fit mode with nowhere to write is a run
            // that loads no gate and produces nothing -- silently useless.
            eprintln!("error: --fit-mode requires --dump-gate-features.");
            std::process::exit(2);
        }
        (false, path) => {
            adapter::Adapter::start(&profile_root, embedder, path, consolidation, cross_encoder)
        }
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
