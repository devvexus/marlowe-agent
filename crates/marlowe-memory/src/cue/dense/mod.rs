//! The dense cue — ADR-004's local ONNX embedder.
//!
//! Session C's addition, and the second of brief §5's five cues. What it buys over the lexical
//! cue is the case `cue/lexical.rs` asserts it cannot do: *a query sharing no vocabulary with
//! the memory that answers it*. What it does **not** buy is the other three cues, so a number
//! produced here is still a statement about an incomplete cue set.
//!
//! Frozen parameters, all declared before the fit in `runs/session-c/PREREGISTRATION.json` and
//! `runs/session-c/PREREGISTRATION-model.json`:
//!
//! | Parameter | Value | Chosen on |
//! |---|---|---|
//! | model | jina-embeddings-v2-small-en, ONNX, pinned by sha256 | measurement — see below |
//! | dimensions | 512 | the model's `config.json` |
//! | `MAX_SEQ_LEN` | 8192 | the model's ALiBi capacity; truncates 4 turns of 246,750 |
//! | pooling | mean over the attention mask, then L2 normalize | the model's own recipe |
//! | engine | ort 2.0.0-rc.10, threads pinned to 1 | `docs/design/spike-2026-08-04-embedder.md` |
//!
//! **The model is not ADR-004's original all-MiniLM-L6-v2, and the reason is a measurement.**
//! On 42 fit-split cases, gold-turn recall@1 under pure cosine is **0.452 against MiniLM's
//! 0.345**, and recall@20 is 0.968 against 0.913. See `runs/session-c/embedder-comparison.json`
//! and ADR-004's amendment. The cost is 0.37× the per-core throughput, which is why the
//! embedding cache is load-bearing rather than an optimization.
//!
//! **Two things a later session must not misread, both of them corrections to what we believed
//! before measuring:**
//!
//! 1. **Truncation was not the binding constraint.** `runs/session-c/truncation.json` found
//!    38.64% of the corpus's word pieces never reached the embedder at 256 tokens, and we
//!    reasoned that the dense number would substantially measure truncation. It does not.
//!    Within a *fixed* model, turns truncated at 46% / 34% / 0% (MiniLM at 128, at 256, and
//!    chunk-and-pooled) give recall@1 of 0.314 / 0.345 / 0.309 — flat, and not monotone in how
//!    much text reached the encoder. The first 256 word pieces carry essentially all the
//!    retrievable signal despite being 61% of the tokens. That was a wrong call, caught by
//!    measurement.
//! 2. **jina's win is model quality, not window length.** Because the comparison above is flat,
//!    the 8192-token context is *not* what bought the improvement. Do not read "longer context
//!    helped" from this file.
//!
//! **Chunk-and-pool was measured and rejected**, not skipped: max-over-windows scored recall@1
//! 0.309 against 0.345 truncated, at 23.9 texts/s/core against a 25 gate. A long turn gets more
//! windows and so more chances for one to look relevant in isolation, which crowds the gold
//! turn out of the top ranks — the precision risk, predicted in advance and then observed.

pub mod cache;
pub mod embedder;
pub mod vectors;
pub mod tokenizer;

/// Maximum sequence length, including `[CLS]` and `[SEP]`.
///
/// **Frozen under HP1.** 8192 is the model's own ALiBi capacity — there are no learned position
/// embeddings to run past. At this length **4 turns of 246,750 truncate** (0.002%), against
/// 34.33% at the 256 this replaced.
///
/// It is also the length the throughput measurement was taken at, so lowering it to buy speed
/// would invalidate the number the model decision rests on. Changing it invalidates the fitted
/// gate outright: the embeddings move, so the features move.
pub const MAX_SEQ_LEN: usize = 8192;

/// The embedding dimension, from the model's own `config.json`.
///
/// 512, not ADR-004's original 384. Under the int8 hot array ADR-004 already mandates this holds
/// ~1.95M entries per GB against 384's ~2.6M, so it does not bind. What does get tighter is the
/// **exact-search f32 path** ROADMAP keeps permanently as ANN validation ground truth: 0.75× as
/// dense per GB, ~488k entries against ~651k. The ANN session inherits that budget.
pub const DIMENSIONS: usize = 512;

/// Cosine similarity between two **already L2-normalized** vectors, floored at zero.
///
/// **Absolute, deliberately — not min-max over the query's candidate set.** Identical reasoning
/// to `lexical::saturate`, and the hazard is the same one: min-max forces the best candidate of
/// *every* query to 1.0, including queries where nothing is relevant, and a gate whose top
/// feature is 1.0 by construction cannot abstain. §4.2 makes abstention a first-class outcome,
/// so the mapping has to preserve "everything here is bad".
///
/// The floor at zero matters for a second reason the lexical cue does not have: cosine runs to
/// −1, and a *negative* similarity is no evidence, not anti-evidence. Letting it go negative
/// would let an unrelated memory push a candidate's fused score below one that matched nothing
/// at all.
///
/// Both inputs are asserted to be unit-length in debug builds rather than re-normalized here.
/// Re-normalizing would paper over a caller that forgot to normalize at write time, and that
/// caller's stored vectors would still be wrong everywhere else.
pub fn cosine(a: &[f32], b: &[f32]) -> f32 {
    debug_assert_eq!(a.len(), DIMENSIONS);
    debug_assert_eq!(b.len(), DIMENSIONS);

    // f64 accumulation over a fixed-length, fixed-order loop. The order is the vector's own
    // index order and cannot vary, which is what `repro` needs.
    let mut dot = 0.0f64;
    for i in 0..DIMENSIONS {
        dot += a[i] as f64 * b[i] as f64;
    }
    if dot <= 0.0 {
        return 0.0;
    }
    (dot as f32).min(1.0)
}

/// Mean-pool a `[tokens, DIMENSIONS]` hidden state over its attention mask, then L2 normalize.
///
/// This is the arithmetic that turns a model output into an embedding, and it is the most
/// likely place for a silent error: a wrong pooling still produces a 512-dim unit vector that
/// scores, ranks, and looks entirely reasonable. `tests/embedding_reference.rs` is what makes
/// that observable, by checking against vectors sentence-transformers produced.
pub fn mean_pool_and_normalize(hidden: &[f32], tokens: usize) -> Vec<f32> {
    debug_assert_eq!(hidden.len(), tokens * DIMENSIONS);

    let mut pooled = vec![0.0f64; DIMENSIONS];
    for t in 0..tokens {
        for d in 0..DIMENSIONS {
            pooled[d] += hidden[t * DIMENSIONS + d] as f64;
        }
    }
    // Every token is attended: `tokenizer::encode` emits an all-ones mask and never pads, so
    // the mask sum is the token count. Dividing by a mask sum that is structurally the length
    // would invite a caller to pad and then silently average in the padding.
    let denominator = tokens.max(1) as f64;
    for value in pooled.iter_mut() {
        *value /= denominator;
    }

    let norm = pooled.iter().map(|v| v * v).sum::<f64>().sqrt();
    if norm == 0.0 {
        return vec![0.0f32; DIMENSIONS];
    }
    pooled.iter().map(|v| (v / norm) as f32).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn unit(mut v: Vec<f32>) -> Vec<f32> {
        let norm = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        for x in v.iter_mut() {
            *x /= norm;
        }
        v
    }

    #[test]
    fn cosine_of_a_vector_with_itself_is_one() {
        let a = unit((0..DIMENSIONS).map(|i| (i as f32).sin()).collect());
        assert!((cosine(&a, &a) - 1.0).abs() < 1e-6);
    }

    #[test]
    fn an_opposed_vector_scores_zero_rather_than_negative() {
        // A negative similarity is no evidence, not anti-evidence. If it were allowed through,
        // an unrelated memory could push a candidate below one that matched nothing at all.
        let a = unit((0..DIMENSIONS).map(|i| (i as f32).sin()).collect());
        let b: Vec<f32> = a.iter().map(|x| -x).collect();
        assert_eq!(cosine(&a, &b), 0.0);
    }

    #[test]
    fn similarity_is_absolute_not_relative_to_the_candidate_set() {
        // The property the gate depends on, restated for the dense cue: a query where nothing
        // is relevant must produce LOW values, not 1.0 for whichever candidate was least bad.
        let query = unit((0..DIMENSIONS).map(|i| (i as f32 * 0.7).sin()).collect());
        let poor: Vec<Vec<f32>> = (0..4)
            .map(|k| unit((0..DIMENSIONS).map(|i| ((i + k * 97) as f32 * 3.1).cos()).collect()))
            .collect();
        let best = poor
            .iter()
            .map(|c| cosine(&query, c))
            .fold(0.0f32, f32::max);
        assert!(best < 0.5, "nothing was relevant, so nothing should score high: {best}");
    }

    #[test]
    fn pooling_averages_over_tokens_then_normalizes_to_unit_length() {
        let mut hidden = vec![0.0f32; 3 * DIMENSIONS];
        for t in 0..3 {
            for d in 0..DIMENSIONS {
                hidden[t * DIMENSIONS + d] = (t + 1) as f32 * (d as f32 + 1.0);
            }
        }
        let pooled = mean_pool_and_normalize(&hidden, 3);
        assert_eq!(pooled.len(), DIMENSIONS);
        let norm = pooled.iter().map(|x| x * x).sum::<f32>().sqrt();
        assert!((norm - 1.0).abs() < 1e-5, "must be unit length, got {norm}");
        // Averaging 1x, 2x, 3x gives 2x, which normalizes to the same direction as x.
        let expected = unit((0..DIMENSIONS).map(|d| d as f32 + 1.0).collect());
        for (a, b) in pooled.iter().zip(expected.iter()) {
            assert!((a - b).abs() < 1e-5);
        }
    }

    #[test]
    fn an_all_zero_hidden_state_does_not_divide_by_zero() {
        let pooled = mean_pool_and_normalize(&vec![0.0f32; DIMENSIONS], 1);
        assert!(pooled.iter().all(|x| *x == 0.0));
    }

    #[test]
    fn pooling_and_cosine_are_deterministic() {
        let hidden: Vec<f32> = (0..2 * DIMENSIONS).map(|i| (i as f32 * 0.37).sin()).collect();
        assert_eq!(mean_pool_and_normalize(&hidden, 2), mean_pool_and_normalize(&hidden, 2));
    }
}
