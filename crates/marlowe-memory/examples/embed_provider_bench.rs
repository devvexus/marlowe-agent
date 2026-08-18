//! **CPU against CUDA, on the same texts, with the cache OFF.**
//!
//! ADR-015's rule is that a different execution provider is a different scorer, so a CUDA number
//! and a CPU number are two baselines rather than one comparison. This produces both, in one
//! process, on one fixed text set, at three sequence lengths.
//!
//! # The cache is disabled and that is the whole validity of the second column
//!
//! `Embedder::load_with_provider(..., cache_dir = None, marlowe_memory::cue::dense::vram::Reserve::None)`. With a cache, whichever provider runs
//! second reads back the first one's vectors and reports a "speedup" that is a disk read — a
//! fabricated number of exactly the kind this project keeps a ledger of. The line
//! `embedding cache: OFF` is printed with every table so a pasted result carries its own control.
//!
//! # What is measured, and what each number is NOT
//!
//! - **Per-embedding overhead** is wall clock over a fixed text set divided by the count. It
//!   includes tokenisation, which is CPU on both arms, so the CUDA column is not a kernel time and
//!   must not be read as one.
//! - **Peak host RAM** is the process's peak working set, read from the OS. On the CUDA arm it
//!   includes the driver's host-side allocations, which are large and are not the embedder's.
//! - **VRAM is read DEVICE-LEVEL, and which instrument produced it is printed with the table.**
//!   The per-process query -- `nvidia-smi --query-compute-apps=pid,used_memory` -- returns `[N/A]`
//!   for every process under WDDM on this machine, and the column printed `-1.0` for a whole
//!   session's worth of tables. `-1.0 MB` is not `0 MB`, but a sentinel in a numeric column is one
//!   careless reading away from being taken for one. So the shipped column is
//!   `memory.free` for the whole card, differenced against a baseline captured before the first
//!   session opens, and the per-process figure is printed beside it as `[N/A]` when the driver
//!   declines. The device-level reading includes anything ELSE that allocated during the window --
//!   which is the honest cost of the only instrument that works here, and is why the baseline is
//!   printed too.
//! - A CUDA session having constructed says nothing about node placement: M0c Session L measured
//!   13.6% of nodes still on CPU under a registered CUDA session.
//!
//! ```text
//! cargo run -p marlowe-memory --release --example embed_provider_bench
//! ```

use std::time::Instant;

use marlowe_memory::cue::dense::embedder::{Embedder, EmbedProvider, ProviderChoice};
use marlowe_memory::cue::dense::tokenizer::{encode, Vocab};
use marlowe_memory::cue::dense::vram::{self, Probe};
use marlowe_memory::cue::dense::MAX_SEQ_LEN;

fn peak_host_bytes() -> u64 {
    #[cfg(windows)]
    {
        let out = std::process::Command::new("powershell")
            .args([
                "-NoProfile",
                "-Command",
                &format!("(Get-Process -Id {}).PeakWorkingSet64", std::process::id()),
            ])
            .output();
        if let Ok(o) = out {
            if let Ok(s) = String::from_utf8(o.stdout) {
                if let Ok(v) = s.trim().parse::<u64>() {
                    return v;
                }
            }
        }
        0
    }
    #[cfg(not(windows))]
    {
        std::fs::read_to_string("/proc/self/status")
            .ok()
            .and_then(|s| {
                s.lines().find(|l| l.starts_with("VmHWM:")).and_then(|l| {
                    l.split_whitespace().nth(1).and_then(|v| v.parse::<u64>().ok())
                })
            })
            .map(|kb| kb * 1024)
            .unwrap_or(0)
    }
}

/// This process's own device memory, in bytes, or `None` where the driver will not say.
///
/// **`None` is the normal answer on this machine and it must never be rendered as a number.**
/// WDDM does not report per-process device memory, so `used_memory` comes back as the literal
/// `[N/A]` for every row -- including this process's. The parse therefore fails, which is correct:
/// a reading that does not exist is `None`, and the caller prints `[N/A]`.
///
/// Kept rather than deleted because it is the *right* instrument where it works: the card is
/// shared, and on a driver that answers, this attributes bytes to a process where a card-wide
/// delta cannot.
fn own_vram_bytes() -> Option<u64> {
    let out = std::process::Command::new("nvidia-smi")
        .args(["--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"])
        .output()
        .ok()?;
    let text = String::from_utf8(out.stdout).ok()?;
    let me = std::process::id().to_string();
    for line in text.lines() {
        let mut parts = line.split(',').map(str::trim);
        if parts.next() == Some(me.as_str()) {
            // `[N/A]` fails to parse and yields None -- deliberately, see above.
            return parts.next().and_then(|m| m.parse::<u64>().ok()).map(|m| m * 1024 * 1024);
        }
    }
    None
}

/// Device memory held since `baseline`, card-wide, or `None` where the card is unreadable.
///
/// Signed: another process freeing memory mid-run makes this negative, and a saturating
/// subtraction would render that as a confident `0.0 MB` -- a wrong number that looks like a
/// measurement.
fn device_held_since(baseline: Option<u64>) -> Option<i64> {
    let (b, now) = (baseline?, vram::free_bytes()?);
    Some(b as i64 - now as i64)
}

fn mb(b: u64) -> f64 {
    b as f64 / 1024.0 / 1024.0
}

/// A text of roughly `words` word-pieces. The actual token count is measured, never assumed.
fn text_of(words: usize, salt: usize) -> String {
    // A rotating handful of ordinary single-piece words, so the text is not one token repeated --
    // a degenerate input could be optimised differently by either provider.
    const BANK: [&str; 8] =
        ["equation", "morning", "report", "engine", "signal", "harbour", "letter", "number"];
    let mut s = String::with_capacity(words * 8);
    for i in 0..words {
        s.push_str(BANK[(i + salt) % BANK.len()]);
        s.push(' ');
    }
    s
}

struct Row {
    provider: &'static str,
    workers: usize,
    tokens: usize,
    texts: usize,
    ms_total: f64,
    peak_host: u64,
    /// Card-wide, differenced against the baseline taken before any session opened.
    device_held: Option<i64>,
    /// Per-process, `None` where the driver returns `[N/A]`.
    own_vram: Option<u64>,
}

fn run_case(
    dir: &std::path::Path,
    choice: ProviderChoice,
    workers: usize,
    texts: &[String],
    tokens: usize,
    device_baseline: Option<u64>,
) -> Option<Row> {
    // cache_dir = None. See the module header: with a cache this whole table is a disk benchmark.
    let mut embedder =
        match Embedder::load_with_provider(dir, workers, None, choice, Probe::Device, marlowe_memory::cue::dense::vram::Reserve::None) {
            Ok(e) => e,
            Err(e) => {
                println!("  {choice:?} x{workers}: did not load: {e}");
                return None;
            }
        };
    let plan = embedder.plan().clone();

    // One untimed pass so the arena and any lazy kernel selection are paid for outside the clock.
    let _ = embedder.embed_batch(&texts[..texts.len().min(2)]);

    let start = Instant::now();
    let out = embedder.embed_batch(texts);
    let elapsed = start.elapsed();
    if let Err(e) = out {
        println!("  {} x{}: FAILED: {e}", plan.provider.name(), plan.workers);
        return None;
    }

    let row = Row {
        provider: plan.provider.name(),
        workers: plan.workers,
        tokens,
        texts: texts.len(),
        ms_total: elapsed.as_secs_f64() * 1000.0,
        peak_host: peak_host_bytes(),
        // Both sampled while the sessions are still alive -- after the drop the driver has
        // released the memory and every reading would be zero.
        device_held: device_held_since(device_baseline),
        own_vram: own_vram_bytes(),
    };
    Some(row)
}

fn main() {
    let dir = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "models/jina-embeddings-v2-small-en".to_string());
    let dir = std::path::Path::new(&dir);

    println!("== embedder provider benchmark ==");
    println!("embedding cache: OFF (cache_dir = None on every case)");
    println!("MAX_SEQ_LEN = {MAX_SEQ_LEN}");
    // Captured ONCE, before any session opens, and every `device held` column below is a
    // difference against it. A per-case baseline would silently absorb whatever the previous case
    // failed to release.
    let device_baseline = vram::free_bytes();
    println!(
        "free device memory at start: {}",
        device_baseline.map_or("no readable device".to_string(), |b| format!("{:.0} MB", mb(b)))
    );
    println!(
        "VRAM instrument: device-level `nvidia-smi --query-gpu=memory.free`, differenced against          that baseline. Per-process `--query-compute-apps` reports {} here.",
        match own_vram_bytes() {
            Some(b) => format!("{:.1} MB", mb(b)),
            None => "[N/A] -- WDDM does not attribute device memory per process".to_string(),
        }
    );
    println!(
        "co-resident processes on the card at start: {}",
        std::process::Command::new("nvidia-smi")
            .args(["--query-compute-apps=process_name", "--format=csv,noheader"])
            .output()
            .ok()
            .and_then(|o| String::from_utf8(o.stdout).ok())
            .map(|t| {
                let names: Vec<String> = t
                    .lines()
                    .map(str::trim)
                    .filter(|l| !l.is_empty())
                    .filter(|l| l.contains("llama") || l.contains("ollama"))
                    .map(str::to_string)
                    .collect();
                if names.is_empty() { "no llama/ollama process".to_string() } else { names.join(", ") }
            })
            .unwrap_or_else(|| "unreadable".to_string())
    );
    println!("CUDA session constructs on the shipped graph: {}", Embedder::cuda_available(dir));

    let vocab = match std::fs::read_to_string(dir.join("vocab.txt"))
        .ok()
        .and_then(|t| Vocab::parse(&t, "vocab.txt").ok())
    {
        Some(v) => v,
        None => {
            println!("no vocab.txt under {}; run `python tools/fetch_model.py`", dir.display());
            return;
        }
    };

    // The derived width -- the same expression the product uses, never a literal.
    let derived = std::thread::available_parallelism().map_or(1, |n| n.get().min(8));
    println!("derived worker count (available_parallelism().min(8)): {derived}\n");

    const TEXTS_PER_CASE: usize = 32;
    let mut rows: Vec<Row> = Vec::new();

    for target in [100usize, 500, MAX_SEQ_LEN] {
        let texts: Vec<String> =
            (0..TEXTS_PER_CASE).map(|i| text_of(target, i)).collect();
        let measured = encode(&vocab, &texts[0], MAX_SEQ_LEN).input_ids.len();
        println!("-- target {target} word-pieces, measured {measured} tokens/text, {TEXTS_PER_CASE} texts");

        // **The GPU arm goes through `Auto`, not `Cuda`, and that is a safety decision.**
        // `ProviderChoice::Cuda` deliberately applies NO device-memory budget -- it is the refusal
        // arm for measurement cells. Opening eight unbudgeted sessions on a card that is already
        // holding an 11.5 GB model server is how a benchmark takes the user's model down. `Auto`
        // runs the same CUDA builder behind the budget, and reports what it actually got, so a row
        // that reads `workers 3` where 8 were asked for is the budget speaking.
        for choice in [ProviderChoice::Cpu, ProviderChoice::Auto] {
            for workers in [1usize, derived] {
                if let Some(row) = run_case(dir, choice, workers, &texts, measured, device_baseline) {
                    println!(
                        "   {:<22} workers {:<2}  {:>8.2} ms total  {:>7.2} ms/embedding  host peak {:>7.1} MB  device held {:>9}  per-process {:>9}",
                        row.provider,
                        row.workers,
                        row.ms_total,
                        row.ms_total / row.texts as f64,
                        mb(row.peak_host),
                        row.device_held
                            .map_or("[unreadable]".to_string(), |d| format!("{:.1} MB", d as f64 / 1048576.0)),
                        row.own_vram.map_or("[N/A]".to_string(), |v| format!("{:.1} MB", mb(v))),
                    );
                    rows.push(row);
                }
                if derived == 1 {
                    break;
                }
            }
        }
        println!();
    }

    // The comparison, stated as two baselines rather than one ratio -- and the ratio printed only
    // where both arms exist, because a missing CUDA arm must read as absent, not as 1.0x.
    println!("== summary: ms per embedding ==");
    println!("{:<8} {:<10} {:>8} {:>12}", "tokens", "workers", "cpu", "cuda");
    let mut widths: Vec<usize> = rows.iter().map(|r| r.workers).collect();
    widths.sort_unstable();
    widths.dedup();
    let mut lens: Vec<usize> = rows.iter().map(|r| r.tokens).collect();
    lens.sort_unstable();
    lens.dedup();
    for tokens in &lens {
        for workers in &widths {
            let find = |name: &str| {
                rows.iter()
                    .find(|r| r.tokens == *tokens && r.workers == *workers && r.provider == name)
                    .map(|r| r.ms_total / r.texts as f64)
            };
            let cpu = find(EmbedProvider::Cpu.name());
            let cuda = find(EmbedProvider::Cuda.name());
            if cpu.is_none() && cuda.is_none() {
                continue;
            }
            println!(
                "{:<8} {:<10} {:>8} {:>12}{}",
                tokens,
                workers,
                cpu.map_or("-".to_string(), |v| format!("{v:.2}")),
                cuda.map_or("-".to_string(), |v| format!("{v:.2}")),
                match (cpu, cuda) {
                    (Some(c), Some(g)) if g > 0.0 => format!("   {:.2}x", c / g),
                    _ => String::new(),
                }
            );
        }
    }
    println!("\nembedding cache was OFF for every row above.");
}
