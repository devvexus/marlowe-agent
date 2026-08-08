//! The cross-encoder rerank stage — Session H, re-pinned to the fine-tuned graph in Session K.
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
//! ## The shipped graph is the Session J fine-tune, and it is f32 — ADR-018, ADR-020
//!
//! Sessions B–I shipped `Xenova/ms-marco-MiniLM-L-2-v2` `onnx/model_int8.onnx`. What ships now is
//! that same architecture **domain-adapted on same-session hard negatives mined from the fit
//! split**, exported to f32: held-out R@1 `0.6026 → 0.6725`, `+0.0699`, discordant 38 (27 gained,
//! 11 lost), exact McNemar `p = 0.0139` with α attainable. It is the first change this project has
//! made to the scored path that is significant on held-out with the power to have detected an
//! effect.
//!
//! **The precision change from int8 to f32 removes a live hazard rather than adding one.** ADR-015
//! measured the shipped int8 graph as **shape-bound in every dimension**: bit-identical token ids
//! re-padded to a longer tensor moved the logit by a median 0.0109 and **padding alone flipped
//! top-1 in 15% of cases**, while all eight f32 graphs were invariant to `0.000000`. The shipped
//! f32 graph is re-verified — not inherited — at batch invariance `0.000000` and padding invariance
//! `0.000000`; see `runs/session-k/export-verification-*.json`.
//!
//! ## Batch is 1, and it stays structural even though the reason changed
//!
//! Session G's original reason was that **int8 batch invariance FAILED** at 0.037 logits for L-2.
//! **That reason no longer applies to the shipped graph** — f32 is batch-invariant at exactly
//! `0.000000` — and leaving the old rationale in place would be a stale comment defending a
//! constant nobody had re-examined. Two reasons replace it:
//!
//! 1. **Invariance is a per-graph measurement and is never inherited.** ADR-013's rule. A future
//!    re-pin — a re-quantization, a new fine-tune, a different export — arrives with no invariance
//!    result until one is taken, and a batch parameter sitting in the code is a way for that
//!    re-pin to silently score candidates against whoever shares their batch.
//! 2. **Batching buys nothing here.** 21.4 ms/pair × 10 candidates = 214 ms/query against a 300 ms
//!    P95 budget, on ADR-003's 1-vCPU target.
//!
//! So [`CrossEncoder::score`] still takes **one** pair, builds a `[1, MAX_SEQ_LEN]` tensor, and
//! asserts the leading dimension. There is no batch parameter to raise and no slice-of-pairs entry
//! point: reintroducing batching means deleting an assertion and changing a signature.
//!
//! ## `MAX_SEQ_LEN` is 256 and the 7.86% gold truncation is a PRICED DEFECT
//!
//! Not an unexamined constant. ADR-015 measured raising it to 512 as a **−0.0917 R@1 regression**
//! (`p = 0.0002`, α attainable): the cap is doing two opposing jobs, costing the 7.86% of gold
//! turns that do not fit and earning more back by capping how much score a long distractor can
//! accumulate. ADR-017 tested the only named route to raising it — explicit length normalization —
//! and that route is a **held-out null with power** on every cell. **Do not raise this without a
//! normalization term fitted against relevance rather than against the score.**
//!
//! ## Everything is pinned and nothing is defaulted
//!
//! Same rule as [`crate::cue::dense::embedder`], for the same reason: a wrong model, a wrong
//! vocabulary or a wrong sequence length all produce a plausible number rather than a crash. There
//! is deliberately **no table of accepted graphs** — a loader that accepts two graphs is a way for
//! a target string to name one scorer and measure another, which is the failure this project has
//! now recorded nine instances of.

use std::path::{Path, PathBuf};

use ort::execution_providers::CPUExecutionProvider;
use ort::session::builder::GraphOptimizationLevel;
use ort::session::Session;
use ort::value::Value;
use sha2::{Digest, Sha256};

use crate::cue::dense::tokenizer::{encode_pair, EncodedPair, Vocab};

/// `ms-marco-MiniLM-L-2-v2-ft-session-j`, `model.onnx` — the Session J fine-tune, f32.
///
/// Pinned here so a file swapped after export is caught at *load*, not merely at training time.
/// The same digest appears in `runs/session-j/finetuned-manifest.json` and in
/// `runs/session-k/export-verification-ms-marco-MiniLM-L-2-v2-ft-session-j.json`, which is where
/// the five determinism checks were re-taken on the shipped graph — so this constant is what ties
/// the running binary to the published `0.6725`.
///
/// **The export gap is bounded, not closed.** There is no external authority for a model this
/// project trained, because this project is the publisher. What stands behind the graph is digest
/// pinning, torch-vs-ORT fixture agreement at 1e-6, and per-graph determinism / batch / padding
/// invariance. See ADR-018 and STATE.md's open-gaps section.
pub const MODEL_SHA256: &str = "9c222dac4315cfd2f33f2e865bb651a7a16bf532c11e55b7fb1a43bb041880c0";

/// The fine-tune's `tokenizer.json`, carried out of `cross-encoder/ms-marco-MiniLM-L-2-v2`.
///
/// **A different file than the Xenova export's, and the difference was measured rather than
/// waved through.** `vocab` (30522 entries), `normalizer`, `pre_tokenizer`, `post_processor`,
/// `decoder` and `added_tokens` are byte-identical between the two; they differ only in the
/// embedded `padding` and `truncation` blocks, which this crate implements itself in
/// [`encode_pair`] and never reads from the file. Confirmed empirically: token ids, attention
/// mask, token type ids and the truncation flag agree on all 8 reference cases across both
/// tokenizers. See `tests/fixtures/cross-encoder-reference-ft-session-j.json`.
pub const TOKENIZER_SHA256: &str =
    "0d3aef594edd5f9b53e7f814277a9171dc70ff93eb66bda6e01f7aa53997d963";

pub const MODEL_FILE: &str = "model.onnx";
pub const TOKENIZER_FILE: &str = "tokenizer.json";

/// The graph file the pre-Session-K builds loaded, named here **only** so a stale `--reranking`
/// path gets an error that says what happened instead of a bare "file not found".
const SUPERSEDED_INT8_FILE: &str = "model_int8.onnx";

/// Sequence length, fixed. See the module docs — this is a priced defect, not a free constant.
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

    #[error(
        "{dir} holds `{superseded}` but no `{expected}`. This is the pre-Session-K int8 graph, and \
         the shipped reranker moved to the Session J fine-tune (f32) -- held-out R@1 0.6026 -> \
         0.6725, ADR-018. Point --reranking at models/ms-marco-MiniLM-L-2-v2-ft-session-j. The \
         int8 graph is NOT loadable here on purpose: a loader that accepts two graphs lets a \
         target string name one scorer and measure another. It stays reachable through the offline \
         tools (tools/session_i_rerankers.py), which is where ablations belong"
    )]
    SupersededGraph { dir: PathBuf, superseded: &'static str, expected: &'static str },

    #[error("reading {path}: {source}")]
    Io { path: PathBuf, source: std::io::Error },

    #[error(
        "{path} hashes to {found}, the pinned digest is {expected}. This is a different file than \
         the one runs/session-k/ took the five determinism checks on and measured held-out R@1 \
         0.6725 with. A different graph still scores and still ranks -- it only moves the number, \
         which is why this is a refusal"
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
    /// Load from a directory holding the pinned `model.onnx` and `tokenizer.json`.
    ///
    /// Both digests are checked before the graph is constructed, and the execution provider is
    /// required to register rather than being allowed to fall back. See the builder below.
    pub fn load(dir: &Path) -> Result<Self, RerankError> {
        let model_path = dir.join(MODEL_FILE);
        let tokenizer_path = dir.join(TOKENIZER_FILE);

        // Named before the generic `Missing`, so pointing at the pre-Session-K int8 directory
        // says what actually happened. A stale path in a target string is the most likely way
        // this stage gets loaded wrong, and "model.onnx does not exist" would send the reader to
        // the fetch script rather than to ADR-018.
        if !model_path.exists() && dir.join(SUPERSEDED_INT8_FILE).exists() {
            return Err(RerankError::SupersededGraph {
                dir: dir.to_path_buf(),
                superseded: SUPERSEDED_INT8_FILE,
                expected: MODEL_FILE,
            });
        }

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
            //
            // **And there could not be one here, which is worth stating rather than implying.**
            // Session K checked: `ort` 2.0.0-rc.10 exposes no way to enumerate a CONSTRUCTED
            // session's active providers -- no `get_providers`, no `available_providers`, nothing
            // on `Session`. The Python side asserts `sess.get_providers()` explicitly because it
            // can (`tools/session_j_models.py`, `session_j_verify_export.py`); Rust states the
            // requirement at build time instead, which refuses earlier rather than reporting
            // later. Do not add a comment claiming a post-construction assertion exists here.
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
