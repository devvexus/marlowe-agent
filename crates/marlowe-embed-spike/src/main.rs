//! The engine spike — **measurement, not argument**.
//!
//! ADR-004 says "local ONNX" and names no runtime. `runs/session-c/PREREGISTRATION.json` wrote
//! the gates down before this ran:
//!
//! | Gate | Condition |
//! |---|---|
//! | throughput | >= 25 texts/s per core, single-threaded, at `MAX_SEQ_LEN` |
//! | latency | retrieval P95 <= 120 ms (40% of the 300 ms budget; the rest is for cues 3-5) |
//! | op coverage | loads the pinned file and reproduces the committed reference embeddings |
//! | determinism | byte-identical across calls, spawns, and worker counts 1 / 2 / 8 |
//!
//! Decision rule, also pre-committed: tract if it clears all four, otherwise ort with threads
//! pinned to 1 and its version recorded in the gate artifact.
//!
//! **Parallelism is at the text level, never inside the model.** Each forward pass runs
//! single-threaded on one worker and results are collected by index, so worker count cannot
//! change any output. That is what makes it the one performance knob that is provably not a
//! quality knob — and this binary asserts it rather than assuming it.
//!
//! Run:
//! ```text
//! cargo run --release -p marlowe-embed-spike -- --report
//! cargo run --release -p marlowe-embed-spike -- --hash tract   # for the cross-spawn check
//! ```

use std::path::{Path, PathBuf};
use std::time::Instant;

use marlowe_memory::cue::dense::tokenizer::{encode, Encoded, Vocab};
use marlowe_memory::cue::dense::{mean_pool_and_normalize, DIMENSIONS, MAX_SEQ_LEN};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("crates/marlowe-embed-spike -> repo root")
        .to_path_buf()
}

/// One candidate engine, reduced to the only operation the cue needs.
trait Engine {
    fn name(&self) -> &'static str;
    /// Run the graph and return the `[tokens, DIMENSIONS]` last hidden state, flattened.
    fn forward(&mut self, encoded: &Encoded) -> Vec<f32>;
}

fn embed(engine: &mut dyn Engine, vocab: &Vocab, text: &str) -> Vec<f32> {
    let encoded = encode(vocab, text, MAX_SEQ_LEN);
    let tokens = encoded.input_ids.len();
    let hidden = engine.forward(&encoded);
    mean_pool_and_normalize(&hidden, tokens)
}

// ------------------------------------------------------------------------------- tract

struct Tract {
    plan: std::sync::Arc<tract_onnx::prelude::TypedRunnableModel>,
}

impl Tract {
    fn load(model: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        use tract_onnx::prelude::*;

        // Symbolic sequence length. Padding every text to MAX_SEQ_LEN would be simpler and
        // would trade roughly 3x the compute for it -- the median turn is 96 word pieces
        // against a 256 limit -- so the symbolic dimension is what makes the throughput gate
        // a fair test rather than a self-inflicted failure.
        let mut model = tract_onnx::onnx().model_for_path(model)?;

        // The symbol MUST come from the model's own scope: tract keeps symbols scoped to a
        // model and a foreign one resolves to a dead scope at run time, not at build time.
        let s = model.symbols.new_with_prefix("S");
        for index in 0..model.inputs.len() {
            model.set_input_fact(
                index,
                InferenceFact::dt_shape(i64::datum_type(), tvec!(1.to_dim(), s.to_dim())),
            )?;
        }
        let plan = model.into_optimized()?.into_runnable()?;
        Ok(Self { plan })
    }
}

impl Engine for Tract {
    fn name(&self) -> &'static str {
        "tract"
    }

    fn forward(&mut self, encoded: &Encoded) -> Vec<f32> {
        use tract_onnx::prelude::*;

        let len = encoded.input_ids.len();
        let ids: Vec<i64> = encoded.input_ids.iter().map(|v| *v as i64).collect();
        let mask: Vec<i64> = encoded.attention_mask.iter().map(|v| *v as i64).collect();
        let zeros = vec![0i64; len];

        let shape = [1, len];
        let mut inputs: TVec<TValue> = tvec!();
        for index in 0..self.plan.model().inputs.len() {
            let name = self.plan.model().node(self.plan.model().inputs[index].node).name.clone();
            let data = if name.contains("attention") {
                &mask
            } else if name.contains("token_type") {
                &zeros
            } else {
                &ids
            };
            inputs.push(
                Tensor::from_shape(&shape, data)
                    .expect("shape matches")
                    .into(),
            );
        }

        let outputs = self.plan.run(inputs).expect("tract runs");
        outputs[0]
            .to_plain_array_view::<f32>()
            .expect("f32 hidden state")
            .iter()
            .copied()
            .collect()
    }
}

// --------------------------------------------------------------------------------- ort

struct Ort {
    session: ort::session::Session,
    input_names: Vec<String>,
}

impl Ort {
    fn load(model: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        use ort::session::builder::GraphOptimizationLevel;

        let session = ort::session::Session::builder()?
            // Threads pinned to 1 and execution forced sequential. Anything else makes the
            // numerics a property of the machine's core count.
            .with_intra_threads(1)?
            .with_inter_threads(1)?
            // Pinned explicitly rather than left at the default: the default is a property of
            // the ORT version, and a bump could re-fuse the graph and move a published number.
            .with_optimization_level(GraphOptimizationLevel::Level1)?
            .commit_from_file(model)?;
        let input_names = session.inputs.iter().map(|i| i.name.clone()).collect();
        Ok(Self { session, input_names })
    }
}

impl Engine for Ort {
    fn name(&self) -> &'static str {
        "ort"
    }

    fn forward(&mut self, encoded: &Encoded) -> Vec<f32> {
        use ort::value::Value;

        let len = encoded.input_ids.len();
        let ids: Vec<i64> = encoded.input_ids.iter().map(|v| *v as i64).collect();
        let mask: Vec<i64> = encoded.attention_mask.iter().map(|v| *v as i64).collect();
        let zeros = vec![0i64; len];

        let mut inputs: Vec<(String, Value)> = Vec::new();
        for name in &self.input_names {
            let data = if name.contains("attention") {
                ids_tensor(&mask, len)
            } else if name.contains("token_type") {
                ids_tensor(&zeros, len)
            } else {
                ids_tensor(&ids, len)
            };
            inputs.push((name.clone(), data));
        }

        let outputs = self.session.run(inputs).expect("ort runs");
        let (_, data) = outputs[0].try_extract_tensor::<f32>().expect("f32 hidden state");
        data.to_vec()
    }
}

fn ids_tensor(data: &[i64], len: usize) -> ort::value::Value {
    ort::value::Value::from_array(([1usize, len], data.to_vec()))
        .expect("tensor builds")
        .into_dyn()
}

// ------------------------------------------------------------------------------ checks

struct Sample {
    turns: Vec<String>,
    queries: Vec<String>,
}

fn load_sample(root: &Path) -> Sample {
    let path = root.join("runs/session-c/spike-sample.json");
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("{} missing ({e}); run tools/make_spike_sample.py", path.display()));
    let value: serde_json::Value = serde_json::from_str(&text).expect("sample parses");
    let strings = |key: &str| {
        value[key]
            .as_array()
            .expect(key)
            .iter()
            .map(|v| v.as_str().expect("string").to_string())
            .collect::<Vec<_>>()
    };
    Sample { turns: strings("turns"), queries: strings("queries") }
}

struct Reference {
    texts: Vec<String>,
    vectors: Vec<Vec<f32>>,
}

fn load_reference(root: &Path) -> Reference {
    let path = root.join("crates/marlowe-memory/tests/fixtures/embedding-reference.json");
    let text = std::fs::read_to_string(&path).expect("reference fixture reads");
    let value: serde_json::Value = serde_json::from_str(&text).expect("reference parses");
    let mut texts = Vec::new();
    let mut vectors = Vec::new();
    for case in value["cases"].as_array().expect("cases") {
        texts.push(case["text"].as_str().expect("text").to_string());
        vectors.push(
            case["embedding"]
                .as_array()
                .expect("embedding")
                .iter()
                .map(|v| v.as_f64().expect("f64") as f32)
                .collect(),
        );
    }
    Reference { texts, vectors }
}

/// Max absolute per-dimension difference and minimum cosine against the reference.
fn agreement(engine: &mut dyn Engine, vocab: &Vocab, reference: &Reference) -> (f32, f32) {
    let mut max_abs = 0.0f32;
    let mut min_cos = 1.0f32;
    for (text, expected) in reference.texts.iter().zip(&reference.vectors) {
        let actual = embed(engine, vocab, text);
        let mut dot = 0.0f64;
        for i in 0..DIMENSIONS {
            max_abs = max_abs.max((actual[i] - expected[i]).abs());
            dot += actual[i] as f64 * expected[i] as f64;
        }
        min_cos = min_cos.min(dot as f32);
    }
    (max_abs, min_cos)
}

fn percentile(sorted: &[f64], p: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let index = ((sorted.len() as f64 - 1.0) * p).round() as usize;
    sorted[index]
}

/// Hash every embedding, order included. Two runs agreeing on this is what `repro` needs.
fn digest(vectors: &[Vec<f32>]) -> String {
    let mut hasher = blake3_like();
    for vector in vectors {
        for value in vector {
            hasher.update(&value.to_le_bytes());
        }
    }
    hasher.finish()
}

/// A tiny FNV-1a, deliberately not a dependency: this hash never leaves the spike.
struct Fnv(u64);
fn blake3_like() -> Fnv {
    Fnv(0xcbf2_9ce4_8422_2325)
}
impl Fnv {
    fn update(&mut self, bytes: &[u8]) {
        for byte in bytes {
            self.0 ^= *byte as u64;
            self.0 = self.0.wrapping_mul(0x1000_0000_01b3);
        }
    }
    fn finish(&self) -> String {
        format!("{:016x}", self.0)
    }
}

struct Row {
    engine: &'static str,
    loaded: bool,
    load_ms: u128,
    max_abs_diff: f32,
    min_cosine: f32,
    texts_per_sec: f64,
    query_p50_ms: f64,
    query_p95_ms: f64,
    identical_across_calls: bool,
    digest: String,
}

fn measure(
    name: &'static str,
    engine: &mut dyn Engine,
    vocab: &Vocab,
    sample: &Sample,
    reference: &Reference,
    load_ms: u128,
) -> Row {
    let (max_abs_diff, min_cosine) = agreement(engine, vocab, reference);

    // Throughput over the corpus sample, single-threaded, warm.
    let started = Instant::now();
    let mut vectors = Vec::with_capacity(sample.turns.len());
    for text in &sample.turns {
        vectors.push(embed(engine, vocab, text));
    }
    let elapsed = started.elapsed().as_secs_f64();
    let texts_per_sec = sample.turns.len() as f64 / elapsed;

    // Query latency: the per-retrieval cost, on query-length text.
    let mut timings: Vec<f64> = Vec::with_capacity(sample.queries.len());
    for query in &sample.queries {
        let started = Instant::now();
        let _ = embed(engine, vocab, query);
        timings.push(started.elapsed().as_secs_f64() * 1000.0);
    }
    timings.sort_by(f64::total_cmp);

    // Same input twice, same process.
    let repeat: Vec<Vec<f32>> = sample.turns[..50]
        .iter()
        .map(|t| embed(engine, vocab, t))
        .collect();
    let identical_across_calls = repeat == vectors[..50].to_vec();

    Row {
        engine: name,
        loaded: true,
        load_ms,
        max_abs_diff,
        min_cosine,
        texts_per_sec,
        query_p50_ms: percentile(&timings, 0.50),
        query_p95_ms: percentile(&timings, 0.95),
        identical_across_calls,
        digest: digest(&vectors),
    }
}

fn main() {
    let root = repo_root();
    let model_dir = root.join("models/jina-embeddings-v2-small-en");
    let model = model_dir.join("model.onnx");
    let vocab_text = std::fs::read_to_string(model_dir.join("vocab.txt"))
        .expect("vocab.txt; run tools/fetch_model.py");
    let vocab = Vocab::parse(&vocab_text, "vocab.txt").expect("pinned vocab parses");

    let args: Vec<String> = std::env::args().skip(1).collect();

    // --hash <engine>: print only the digest, so the caller can spawn twice and compare.
    if let Some(position) = args.iter().position(|a| a == "--hash") {
        let which = args.get(position + 1).map(String::as_str).unwrap_or("tract");
        let sample = load_sample(&root);
        let mut engine: Box<dyn Engine> = match which {
            "ort" => Box::new(Ort::load(&model).expect("ort loads")),
            _ => Box::new(Tract::load(&model).expect("tract loads")),
        };
        let vectors: Vec<Vec<f32>> = sample.turns[..200]
            .iter()
            .map(|t| embed(engine.as_mut(), &vocab, t))
            .collect();
        println!("{}", digest(&vectors));
        return;
    }

    // --workers N <engine>: the worker-count invariance measurement.
    //
    // One engine instance per thread and a static split of the text list by index, so each
    // text's forward pass happens entirely inside one worker and results are reassembled in
    // input order. If the digest moves with the worker count, text-level parallelism is not
    // actually text-level and the claim that worker count is not a quality knob is false.
    if let Some(position) = args.iter().position(|a| a == "--workers") {
        let workers: usize = args[position + 1].parse().expect("worker count");
        let which = args.get(position + 2).map(String::as_str).unwrap_or("tract").to_string();
        let sample = load_sample(&root);
        let texts: Vec<String> = sample.turns[..200].to_vec();

        let mut handles = Vec::new();
        for worker in 0..workers {
            let texts = texts.clone();
            let which = which.clone();
            let model = model.clone();
            let vocab = vocab.clone();
            handles.push(std::thread::spawn(move || {
                let mut engine: Box<dyn Engine> = match which.as_str() {
                    "ort" => Box::new(Ort::load(&model).expect("ort loads")),
                    _ => Box::new(Tract::load(&model).expect("tract loads")),
                };
                texts
                    .iter()
                    .enumerate()
                    .filter(|(index, _)| index % workers == worker)
                    .map(|(index, text)| (index, embed(engine.as_mut(), &vocab, text)))
                    .collect::<Vec<_>>()
            }));
        }

        let mut collected: Vec<(usize, Vec<f32>)> = Vec::new();
        for handle in handles {
            collected.extend(handle.join().expect("worker finished"));
        }
        collected.sort_by_key(|(index, _)| *index);
        let vectors: Vec<Vec<f32>> = collected.into_iter().map(|(_, v)| v).collect();
        println!("{}", digest(&vectors));
        return;
    }

    let sample = load_sample(&root);
    let reference = load_reference(&root);
    println!(
        "sample: {} turns, {} queries | reference: {} texts | MAX_SEQ_LEN {}",
        sample.turns.len(),
        sample.queries.len(),
        reference.texts.len(),
        MAX_SEQ_LEN
    );

    let mut rows = Vec::new();

    print!("tract: loading ... ");
    let started = Instant::now();
    match Tract::load(&model) {
        Ok(mut engine) => {
            let load_ms = started.elapsed().as_millis();
            println!("ok ({load_ms} ms)");
            rows.push(measure("tract", &mut engine, &vocab, &sample, &reference, load_ms));
        }
        Err(e) => {
            println!("FAILED: {e}");
            rows.push(failed_row("tract"));
        }
    }

    print!("ort:   loading ... ");
    let started = Instant::now();
    match Ort::load(&model) {
        Ok(mut engine) => {
            let load_ms = started.elapsed().as_millis();
            println!("ok ({load_ms} ms)");
            rows.push(measure("ort", &mut engine, &vocab, &sample, &reference, load_ms));
        }
        Err(e) => {
            println!("FAILED: {e}");
            rows.push(failed_row("ort"));
        }
    }

    println!();
    println!("| engine | loads | load ms | max abs diff | min cosine | texts/s/core | query P50 | query P95 | same across calls | digest |");
    println!("|---|---|---|---|---|---|---|---|---|---|");
    for row in &rows {
        if !row.loaded {
            println!("| {} | NO | - | - | - | - | - | - | - | - |", row.engine);
            continue;
        }
        println!(
            "| {} | yes | {} | {:.2e} | {:.8} | {:.1} | {:.1} ms | {:.1} ms | {} | {} |",
            row.engine,
            row.load_ms,
            row.max_abs_diff,
            row.min_cosine,
            row.texts_per_sec,
            row.query_p50_ms,
            row.query_p95_ms,
            if row.identical_across_calls { "yes" } else { "NO" },
            row.digest,
        );
    }

    println!();
    println!("pre-committed gates: >= 25 texts/s/core, query P95 within a 120 ms retrieval budget,");
    println!("loads the pinned file, reproduces the reference, identical across calls/spawns/workers.");
    for row in rows.iter().filter(|r| r.loaded) {
        let throughput = row.texts_per_sec >= 25.0;
        println!(
            "  {:6} throughput {} ({:.1}/s)   reference {} ({:.2e})   calls {}",
            row.engine,
            if throughput { "PASS" } else { "FAIL" },
            row.texts_per_sec,
            if row.max_abs_diff <= 1e-4 { "PASS" } else { "FAIL" },
            row.max_abs_diff,
            if row.identical_across_calls { "PASS" } else { "FAIL" },
        );
    }
}

fn failed_row(engine: &'static str) -> Row {
    Row {
        engine,
        loaded: false,
        load_ms: 0,
        max_abs_diff: f32::NAN,
        min_cosine: f32::NAN,
        texts_per_sec: 0.0,
        query_p50_ms: 0.0,
        query_p95_ms: 0.0,
        identical_across_calls: false,
        digest: String::new(),
    }
}
