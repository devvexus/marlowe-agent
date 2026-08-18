//! **Peak resident memory while embedding at `MAX_SEQ_LEN`.**
//!
//! The number under test is the ALiBi relative-distance matrix, `8 x N x N` int64, allocated per
//! session. It is not visible in any unit test because a test that merely embeds a short string
//! never reaches the maximum — the two reference tests that DO reach it fail with `bad allocation`
//! rather than reporting a size.
//!
//! Peak working set is read from the OS rather than instrumented in-process, because the
//! allocation happens inside ONNX Runtime's arena and a Rust allocator hook would not see it.

use marlowe_memory::cue::dense::{embedder::Embedder, MAX_SEQ_LEN};

fn peak_bytes() -> u64 {
    #[cfg(windows)]
    {
        // `GetProcessMemoryInfo` via wmic-free path: read it from the OS through a tiny
        // PowerShell call, so this example needs no new dependency.
        let out = std::process::Command::new("powershell")
            .args([
                "-NoProfile",
                "-Command",
                &format!(
                    "(Get-Process -Id {}).PeakWorkingSet64",
                    std::process::id()
                ),
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
                s.lines()
                    .find(|l| l.starts_with("VmHWM:"))
                    .and_then(|l| l.split_whitespace().nth(1).and_then(|v| v.parse::<u64>().ok()))
            })
            .map(|kb| kb * 1024)
            .unwrap_or(0)
    }
}

fn mb(b: u64) -> f64 {
    b as f64 / 1024.0 / 1024.0
}

fn main() {
    let dir = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "models/jina-embeddings-v2-small-en".to_string());
    let workers: usize = std::env::args().nth(2).and_then(|s| s.parse().ok()).unwrap_or(1);

    println!("MAX_SEQ_LEN = {MAX_SEQ_LEN}");
    println!(
        "predicted ALiBi matrix (8 x N x N int64, per session): {:.1} MB",
        mb(8 * MAX_SEQ_LEN as u64 * MAX_SEQ_LEN as u64 * 8)
    );
    println!("baseline peak before load: {:.1} MB\n", mb(peak_bytes()));

    let mut embedder = match Embedder::load(std::path::Path::new(&dir), workers, None) {
        Ok(e) => e,
        Err(e) => {
            println!("embedder did not open: {e}");
            return;
        }
    };
    println!("after loading {workers} session(s): {:.1} MB", mb(peak_bytes()));

    // A short text first — this is the common case and it must stay cheap.
    let short = "a niche equation appears in the middle of a long document";
    match embedder.embed(short) {
        Ok(v) => println!("short text ({} dims): peak {:.1} MB", v.len(), mb(peak_bytes())),
        Err(e) => println!("short text FAILED: {e}"),
    }

    // **Then a text that reaches MAX_SEQ_LEN**, which is the case that allocates the matrix and
    // the case the failing reference tests exercise. One token per word keeps it simple; the
    // tokenizer truncates at the cap regardless.
    let long = "equation ".repeat(MAX_SEQ_LEN * 2);
    match embedder.embed(&long) {
        Ok(v) => println!("at MAX_SEQ_LEN ({} dims): peak {:.1} MB", v.len(), mb(peak_bytes())),
        Err(e) => println!("at MAX_SEQ_LEN FAILED: {e}"),
    }

    println!("\nFINAL PEAK: {:.1} MB", mb(peak_bytes()));
}
