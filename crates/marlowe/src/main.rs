//! The Marlowe binary.
//!
//! ADR-002: one binary, two roles — `marlowe` (thin client) and `marlowe --serve` (daemon).
//! The daemon does not exist yet. M1 adds the client's two surfaces, driven by a scripted stub:
//! `--tui` (Addendum B v2) and `--classic` (§B11). M0b's eval adapter is unchanged.

mod adapter;
mod agent;
mod dump;
mod elapsed;
mod launcher;
mod profile;
mod tui;

use std::io::{self, BufReader};
use std::path::PathBuf;

const USAGE: &str = "\
marlowe --ask <question> [--workspace <DIR>] [--dev] [--context <TOKENS>]
marlowe --serve [--workspace <DIR>] [--daemon-port <N>] [--dev] [--context <TOKENS>]
marlowe --status
marlowe --launch
marlowe --tui [--scripted] [--daemon-port <N>] [--timing-probe] [--color-depth <truecolor|256|16>]
        [--ground]
marlowe --classic
marlowe --doctor
marlowe --eval-adapter --profile-root <DIR> --embedder-model <DIR> --reranking <off|DIR>
        [--embedding-cache <DIR>] [--embedder-workers <N>]
        [--dump-gate-features <FILE>] [--fit-mode]
        [--dump-consolidation <FILE>] [--consolidation-dry-run]
        [--profile-retrieval <FILE>]
        [--rerank-threads <N>] [--rerank-batch <on|off>] [--rerank-provider <cpu|cuda>]

  --ask <question>              Ask one question and print the answer. The thin client of
                                ARCHITECTURE §6: it holds no run state, so the run belongs to the
                                daemon and outlives this process. Auto-spawns a daemon if none is
                                listening, and says so.

  --serve                       Run the daemon. It owns the journal, the engine and the runs.
                                Runs survive the client that started them (invariant 6); they do
                                NOT yet survive the daemon itself — that is M3 and K5.

  --status                      What the daemon is, what model it routes to with that model's
                                MEASURED tool-call reliability, which rerank provider is active
                                (announced, never inferred — ADR-029), and whether anything is
                                degraded with the command that fixes it.

  --workspace <DIR>             The directory tools are scoped to. Defaults to the current
                                directory. Every path the model names is resolved relative to it
                                and refused if it escapes.

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

  --profile-retrieval <FILE>    Write one NDJSON row per §4.2 call with the per-stage breakdown:
                                query embedding, the full-store candidate scan, session scoping,
                                lexical, dense, features, gate, pruning, rerank and assembly, in
                                MICROSECONDS, plus the span they were taken inside and the
                                RESIDUAL between the two. Diagnostic only: the §4.2 response is
                                byte-identical with or without it, and the write happens AFTER
                                `cost.latency_ms` is read, so profiling cannot inflate the number
                                it exists to explain. Read it with `tools/profile_retrieval.py`.

  --rerank-threads <N>          ONNX intra-op threads for the CROSS-ENCODER only. Default 1, the
                                value every published number was measured at, per ADR-003's 1-vCPU
                                target. MEASUREMENT KNOB: raising it may change reduction order
                                inside a matmul, which changes logits, which changes the ranking.
                                A value is adopted only if scored-candidates.ndjson stays
                                byte-identical -- determinism gates this regardless of speed. The
                                value is recorded on every --profile-retrieval row, so a sweep
                                cell cannot claim one thread count and run another.

  --rerank-batch <on|off>       Score the whole depth-10 slate in ONE forward pass. Explicit value,
                                no bare boolean, default `off`. Batch invariance is measured at
                                0.000000000 across sizes 1..10 on the shipped graph, so this is
                                bit-identical by construction -- it is a COST switch, not a quality
                                one. Off by default because M0c Session L measured it as a 12%
                                REGRESSION at one thread (rerank p50 187.6 -> 210.2 ms): batching
                                pays through parallelism across the batch dimension and there is
                                none at one thread. Recorded per profile row.

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
    let modes: Vec<&str> = ["--tui", "--classic", "--doctor", "--eval-adapter", "--launch",
                            "--serve", "--ask", "--status"]
        .into_iter()
        .filter(|m| args.iter().any(|a| a == m))
        .collect();
    match modes.len() {
        1 => {}
        0 => {
            eprintln!("{USAGE}");
            eprintln!(
                "error: no mode selected. One of --serve, --ask, --status, --launch, --tui, --classic, --doctor, --eval-adapter."
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

    // ── ARCHITECTURE §6: the two roles ────────────────────────────────────────────────────
    // **`--context` refuses rather than falling back.** A value that cannot be resolved must be a
    // load-time error: Ollama silently applies 2048 to a 262,144-token model when `num_ctx` is
    // omitted, and that permissive default was live for the whole of M2. A typo must not reach it.
    let context: Option<u32> = match flag_value(&args, "--context") {
        None if args.iter().any(|a| a == "--context") => {
            eprintln!("error: --context requires a value in tokens, e.g. `--context 32768`.");
            std::process::exit(2);
        }
        None => None,
        Some(v) => match v.parse::<u32>() {
            Ok(n) if (1_024..=marlowe_provider::MODEL_CONTEXT_CEILING).contains(&n) => Some(n),
            Ok(n) => {
                eprintln!(
                    "error: --context {n} is outside 1024..={}. The upper bound is what the                      pinned model reports it supports; a larger window is a KV-cache commitment                      the model cannot honour.",
                    marlowe_provider::MODEL_CONTEXT_CEILING
                );
                std::process::exit(2);
            }
            Err(_) => {
                eprintln!("error: --context {v:?} is not a number of tokens.");
                std::process::exit(2);
            }
        },
    };

    if matches!(modes[0], "--serve" | "--ask" | "--status") {
        let workspace = flag_value(&args, "--workspace")
            .map(PathBuf::from)
            .or_else(|| std::env::current_dir().ok())
            .unwrap_or_else(|| PathBuf::from("."));
        let profile_root = flag_value(&args, "--profile-root")
            .map(PathBuf::from)
            .unwrap_or_else(agent::default_profile_root);

        let result = match modes[0] {
            "--serve" => agent::serve(
                workspace,
                profile_root,
                flag_value(&args, "--daemon-port").and_then(|v| v.parse().ok()),
                args.iter().any(|a| a == "--dev"),
                context,
            ),
            "--status" => agent::status(workspace, profile_root),
            _ => match flag_value(&args, "--ask") {
                Some(message) => agent::ask(
                    message,
                    workspace,
                    profile_root,
                    args.iter().any(|a| a == "--dev"),
                    context,
                ),
                None => Err("--ask requires a question, e.g. `marlowe --ask \"read notes.md\"`"
                    .to_string()),
            },
        };
        if let Err(e) = result {
            eprintln!("marlowe: {e}");
            std::process::exit(1);
        }
        return;
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
                        scripted: args.iter().any(|a| a == "--scripted"),
                        daemon_port: None,
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
            scripted: args.iter().any(|a| a == "--scripted"),
            daemon_port: flag_value(&args, "--daemon-port").and_then(|v| v.parse().ok()),
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
        let mut session = marlowe_stub::Session::new();
        if let Err(e) =
            marlowe_surface::cli::run(&mut session, stdin.lock(), io::stdout(), &clock)
        {
            eprintln!("error: {e}");
            std::process::exit(1);
        }
        return;
    }

    if modes[0] == "--doctor" {
        // `--doctor` reports on a scripted view deliberately: it is a TERMINAL capability
        // check, and giving it a `SessionView::default()` would have been the permissive default
        // this project keeps deleting. There is no `Default` on `SessionView` to reach for.
        let doctor_session = marlowe_stub::Session::new();
        for line in marlowe_surface::doctor::report(doctor_session.view()) {
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

    // Same rule again: present-but-empty is a typo, not a request for a default path. A default
    // here would let a profile land in a file from an earlier run and produce a P95 that mixes
    // two configurations -- which is the one thing a latency comparison must never do.
    if args.iter().any(|a| a == "--profile-retrieval")
        && flag_value(&args, "--profile-retrieval").is_none()
    {
        eprintln!("{USAGE}");
        eprintln!("error: --profile-retrieval requires a path and has no default.");
        std::process::exit(2);
    }

    // Explicit value, never a bare boolean -- the `--reranking` rule. A default-on/off switch
    // forgotten in a sweep string measures one configuration under another's label.
    let rerank_provider = match flag_value(&args, "--rerank-provider") {
        Some("cpu") | None => marlowe_memory::rerank::RerankProvider::Cpu,
        Some("cuda") => marlowe_memory::rerank::RerankProvider::Cuda,
        Some(other) => {
            eprintln!("{USAGE}");
            eprintln!("error: --rerank-provider takes `cpu` or `cuda`, got {other:?}.");
            std::process::exit(2);
        }
    };
    let rerank_batched = match flag_value(&args, "--rerank-batch") {
        Some("on") => true,
        Some("off") => false,
        // **Derived from the provider, not a constant.** CPU is faster sequential, CUDA is faster
        // batched, both measured; see `RerankProvider::default_batching`. A single default would be
        // wrong for one of them whichever value it took. The resolved value is stamped on every
        // profile row, so this default cannot hide a mismatch.
        None => rerank_provider.default_batching(),
        Some(other) => {
            eprintln!("{USAGE}");
            eprintln!("error: --rerank-batch takes `on` or `off`, got {other:?}.");
            std::process::exit(2);
        }
    };
    let rerank_threads = match flag_value(&args, "--rerank-threads") {
        Some(v) => match v.parse::<usize>() {
            Ok(n) if n >= 1 => n,
            _ => {
                eprintln!("{USAGE}");
                eprintln!("error: --rerank-threads must be a positive integer, got {v:?}.");
                std::process::exit(2);
            }
        },
        None => marlowe_memory::rerank::SHIPPED_THREADS,
    };
    // Explicit value, no bare boolean, default `cpu` -- the shipped provider. A run that means to
    // measure CUDA and forgets the flag measures CPU and says CUDA in its filename; the value is
    // stamped on every profile row so the artifact settles it rather than the label.
    let rerank_settings = adapter::RerankSettings {
        batched: rerank_batched,
        threads: rerank_threads,
        provider: rerank_provider,
    };

    let dump_path = flag_value(&args, "--dump-gate-features").map(std::path::Path::new);
    let profile_path = flag_value(&args, "--profile-retrieval").map(std::path::Path::new);
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
        Some(dir) => match marlowe_memory::rerank::CrossEncoder::load_with(&dir, rerank_threads, rerank_provider) {
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
        (true, Some(path)) => adapter::Adapter::start_for_fit(
            &profile_root,
            embedder,
            path,
            consolidation,
            cross_encoder,
            rerank_settings,
            profile_path,
        ),
        (true, None) => {
            eprintln!("{USAGE}");
            // Refused rather than defaulted to a path. Fit mode with nowhere to write is a run
            // that loads no gate and produces nothing -- silently useless.
            eprintln!("error: --fit-mode requires --dump-gate-features.");
            std::process::exit(2);
        }
        (false, path) => adapter::Adapter::start(
            &profile_root,
            embedder,
            adapter::Diagnostics { gate_features: path, retrieval_profile: profile_path },
            consolidation,
            cross_encoder,
            rerank_settings,
        ),
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
