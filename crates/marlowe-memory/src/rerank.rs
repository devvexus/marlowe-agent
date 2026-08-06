//! The cross-encoder rerank stage — Session H.
//!
//! A **rerank stage, not a cue.** The distinction is ADR-010's and it decides what this is capable
//! of. A cue produces a score that the gate arbitrates between; a fusion that only arbitrates
//! cannot beat the either-cue oracle, because it can only ever pick a candidate one of the cues
//! already ranked first — which is the cap Sessions D and E both shipped into. This stage computes
//! a **new** score over `(query, candidate text)` and can promote a candidate neither cue ranked
//! anywhere near the top, so its ceiling is *gold is in the slate handed to it*. That was
//! confirmed by measurement before this file was written, not assumed:
//! `runs/session-h/rerank-fit.json → adr_010_reach_check`.
//!
//! ## Batch is 1, and it is structural
//!
//! Session G re-verified determinism per graph rather than inheriting the spike's result, and
//! **int8 batch invariance FAILED** — 0.037 logits for L-2, 0.050 for L-6, where the spike's fp32
//! L-6 passed at exactly `0.000e+00`. Quantization changes the reduction order inside the graph, so
//! a candidate's score depends on which other candidates share its batch. That breaks
//! `repro --runs 2`, which is a standing check.
//!
//! This module removes the failure mode instead of tolerating it: [`CrossEncoder::score`] takes
//! **one** pair, builds a `[1, MAX_SEQ_LEN]` tensor, and asserts the leading dimension. There is no
//! batch parameter to raise and no slice-of-pairs entry point, so a later optimization cannot
//! reintroduce batching without deleting an assertion and changing a signature. With ~9 ms per pair
//! against a 300 ms budget at the shipped candidate count, batching buys nothing.
//!
//! ## Everything is pinned and nothing is defaulted
//!
//! Same rule as [`crate::cue::dense::embedder`], for the same reason: a wrong model, a wrong
//! vocabulary or a wrong sequence length all produce a plausible number rather than a crash.

use std::path::{Path, PathBuf};

use ort::execution_providers::CPUExecutionProvider;
use ort::session::builder::GraphOptimizationLevel;
use ort::session::Session;
use ort::value::Value;
use sha2::{Digest, Sha256};

use crate::cue::dense::tokenizer::{encode_pair, EncodedPair, Vocab};

/// `Xenova/ms-marco-MiniLM-L-2-v2`, `onnx/model_int8.onnx`.
///
/// Pinned here so a file swapped after download is caught at *load*, not merely at fetch. The same
/// digest appears in `runs/session-g/cross-encoder-recost.json`, which is where the 92.41 ms
/// latency figure was measured — so this constant is what ties the shipped graph to the published
/// number.
pub const MODEL_SHA256: &str = "1857c1a59b01c1641a46a47fd85b01d98c6e15e1e48588eac1f6a97ff83479c7";

/// The same release's `tokenizer.json`.
pub const TOKENIZER_SHA256: &str =
    "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66";

pub const MODEL_FILE: &str = "model_int8.onnx";
pub const TOKENIZER_FILE: &str = "tokenizer.json";

/// Sequence length, fixed. The same 256 Session G re-costed at.
pub const MAX_SEQ_LEN: usize = 256;

/// The batch size, and it is not a tuning parameter. See the module docs.
pub const BATCH: usize = 1;

/// The execution provider this stage is measured and adopted on.
///
/// CPU, deliberately. ADR-013 records that GPU is not adopted for the retrieval path: determinism
/// across execution providers and ADR-003's 1-vCPU VPS target each need their own ADR, and CPU
/// already clears the budget.
pub const PROVIDER: &str = "CPUExecutionProvider";

#[derive(Debug, thiserror::Error)]
pub enum RerankError {
    #[error(
        "{path} does not exist. The cross-encoder is never vendored ({dir} is gitignored); fetch \
         it with `python tools/fetch_model.py --cross-encoder`. There is no fallback model and no \
         default path"
    )]
    Missing { path: PathBuf, dir: String },

    #[error("reading {path}: {source}")]
    Io { path: PathBuf, source: std::io::Error },

    #[error(
        "{path} hashes to {found}, the pinned digest is {expected}. This is a different file than \
         the one runs/session-g/cross-encoder-recost.json measured 92.41 ms on. A different graph \
         still scores and still ranks -- it only moves the number, which is why this is a refusal"
    )]
    DigestMismatch { path: PathBuf, found: String, expected: &'static str },

    #[error("{path}: {source}")]
    Vocab { path: PathBuf, source: crate::cue::dense::tokenizer::VocabError },

    #[error("loading the ONNX session from {path}: {source}")]
    Session { path: PathBuf, source: Box<ort::Error> },

    #[error("running the cross-encoder graph: {source}")]
    Run { source: Box<ort::Error> },

    // There is deliberately NO `ProviderFellBack` variant. ADR-013's finding is discharged at
    // construction by `error_on_failure()` (see `load`), which makes a registration failure a
    // `Session` error rather than something this stage has to detect afterwards. An unreachable
    // variant would suggest a check that does not exist.
    #[error(
        "the graph returned {found} values for one pair; a sequence-classification head returns \
         exactly 1 logit. This is not the model this stage was built against"
    )]
    ShapeDisagrees { found: usize },
}

fn sha256_file(path: &Path) -> Result<String, RerankError> {
    let bytes = std::fs::read(path).map_err(|source| RerankError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    Ok(format!("{:x}", hasher.finalize()))
}

fn pinned(path: &Path, expected: &'static str, dir: &Path) -> Result<(), RerankError> {
    if !path.exists() {
        return Err(RerankError::Missing {
            path: path.to_path_buf(),
            dir: dir.display().to_string(),
        });
    }
    let found = sha256_file(path)?;
    if found != expected {
        return Err(RerankError::DigestMismatch {
            path: path.to_path_buf(),
            found,
            expected,
        });
    }
    Ok(())
}

/// The loaded cross-encoder. One graph, one vocabulary, one pair at a time.
pub struct CrossEncoder {
    session: Session,
    vocab: Vocab,
}

impl CrossEncoder {
    /// Load from a directory holding the pinned `model_int8.onnx` and `tokenizer.json`.
    ///
    /// Both digests are checked before the graph is constructed, and the execution provider is
    /// required to register rather than being allowed to fall back. See the builder below.
    pub fn load(dir: &Path) -> Result<Self, RerankError> {
        let model_path = dir.join(MODEL_FILE);
        let tokenizer_path = dir.join(TOKENIZER_FILE);
        pinned(&model_path, MODEL_SHA256, dir)?;
        pinned(&tokenizer_path, TOKENIZER_SHA256, dir)?;

        let text = std::fs::read_to_string(&tokenizer_path).map_err(|source| RerankError::Io {
            path: tokenizer_path.clone(),
            source,
        })?;
        let vocab = Vocab::from_tokenizer_json(&text, &tokenizer_path.display().to_string())
            .map_err(|source| RerankError::Vocab { path: tokenizer_path, source })?;

        let session = Session::builder()
            // **ADR-013's provider finding, discharged at construction.** The Python re-costing
            // requested CUDA, ORT failed to load it on missing cuBLAS/cuDNN and fell back to CPU
            // *without raising*, producing a "GPU" figure within 1% of the 1-thread CPU one. That
            // was caught after the fact by comparing `get_providers()` against the request.
            //
            // `ort` lets the same requirement be stated up front: `error_on_failure()` turns a
            // registration failure into a hard error instead of a silent fallback to the next
            // provider. So the provider cannot silently differ from the one this stage was
            // measured on -- there is no after-the-fact check to forget to write.
            .and_then(|b| {
                b.with_execution_providers([CPUExecutionProvider::default()
                    .build()
                    .error_on_failure()])
            })
            .and_then(|b| b.with_optimization_level(GraphOptimizationLevel::Level1))
            // One thread inside the graph. ADR-003 sizes against a 1-vCPU VPS, and the verdict in
            // runs/session-g/cross-encoder-recost.json is read at 1 thread for that reason.
            .and_then(|b| b.with_intra_threads(1))
            .and_then(|b| b.with_inter_threads(1))
            .and_then(|b| b.commit_from_file(&model_path))
            .map_err(|e| RerankError::Session { path: model_path, source: Box::new(e) })?;

        Ok(Self { session, vocab })
    }

    /// Score one `(query, document)` pair. Higher is more relevant.
    ///
    /// **One pair. Not a slice, not a batch.** See the module docs: int8 batch invariance failed
    /// at 0.037 logits, and a fixed batch of 1 removes the failure mode rather than tolerating it.
    pub fn score(&mut self, query: &str, document: &str) -> Result<f32, RerankError> {
        let encoded = encode_pair(&self.vocab, query, document, MAX_SEQ_LEN);
        self.run(&encoded)
    }

    fn run(&mut self, encoded: &EncodedPair) -> Result<f32, RerankError> {
        let ids: Vec<i64> = encoded.input_ids.iter().map(|&v| v as i64).collect();
        let mask: Vec<i64> = encoded.attention_mask.iter().map(|&v| v as i64).collect();
        let types: Vec<i64> = encoded.token_type_ids.iter().map(|&v| v as i64).collect();

        let shape = [BATCH as i64, MAX_SEQ_LEN as i64];
        // The structural assertion. `BATCH` is a constant and this is what stops a later change
        // from making it anything else without the failure being loud and immediate.
        assert_eq!(shape[0], 1, "cross-encoder batch is fixed at 1; see rerank.rs module docs");
        assert_eq!(ids.len(), BATCH * MAX_SEQ_LEN, "fixed [1, {MAX_SEQ_LEN}] shape");

        let make = |data: Vec<i64>| -> Result<Value, RerankError> {
            Value::from_array((shape, data))
                .map(|v| v.into_dyn())
                .map_err(|e| RerankError::Run { source: Box::new(e) })
        };
        // BY NAME, never by position. `token_type_ids` is what carries the query/candidate
        // boundary, and binding positionally would transpose it on any graph that orders its
        // inputs differently -- the model would still return a plausible score.
        let inputs: Vec<(String, Value)> = vec![
            ("input_ids".to_string(), make(ids)?),
            ("attention_mask".to_string(), make(mask)?),
            ("token_type_ids".to_string(), make(types)?),
        ];

        let outputs = self
            .session
            .run(inputs)
            .map_err(|e| RerankError::Run { source: Box::new(e) })?;
        let (_, logits) = outputs[0]
            .try_extract_tensor::<f32>()
            .map_err(|e| RerankError::Run { source: Box::new(e) })?;

        if logits.len() != 1 {
            return Err(RerankError::ShapeDisagrees { found: logits.len() });
        }
        Ok(logits[0])
    }
}
