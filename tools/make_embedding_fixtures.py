"""Generate the committed reference fixtures the Rust embedder is checked against.

**These are generated once, from Python, and are never regenerated to make Rust pass.** That
direction is the whole value: a fixture rewritten to match the implementation it validates is a
test that asserts the code does what it does. If Rust disagrees with these files, Rust is wrong
until proven otherwise — the same rule `eval/` lives under.

Two files, written to `crates/marlowe-memory/tests/fixtures/`:

  wordpiece-reference.json   token ids from HuggingFace's own BertTokenizer, built from the
                             PINNED vocab.txt and tokenizer_config.json in `models/`.
  embedding-reference.json   512-dim vectors from the sentence-transformers pipeline, which is
                             the authority on what an all-MiniLM-L6-v2 embedding *is*.

**Why the reference is sentence-transformers and not onnxruntime.** The question the fixture has
to answer is "does our implementation produce all-MiniLM-L6-v2 embeddings", not "does it agree
with one particular ONNX engine". Generating the reference with a candidate engine would make
that engine trivially correct by construction and leave the other measured against it — an
asymmetry with no justification.

So the reference is the published pipeline, and this script *separately* records how closely
onnxruntime-on-the-pinned-file reproduces it. That second number is doing real work: it validates
that the ONNX export in `models/` is faithful to the published model, and it establishes the
realistic floor for the Rust-vs-reference tolerance. A tolerance tighter than the gap between two
faithful implementations of the same graph would be a test that fails for being correct.

The text set is chosen for tokenizer hazards, not for coverage of English: accents (stripped
under do_lower_case), CJK (spaced by tokenize_chinese_chars), subword continuations, [UNK],
digits and versions, an empty string, whitespace only, and one text long enough to truncate.

    python tools/make_embedding_fixtures.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO / "models" / "jina-embeddings-v2-small-en"
FIXTURES = REPO / "crates" / "marlowe-memory" / "tests" / "fixtures"

# Must match `marlowe_memory::cue::dense::MAX_SEQ_LEN`.
#
# 256, NOT the 128 originally frozen. runs/session-c/truncation.json measured 46.18% of
# turns truncated at 128, which falsifies the principle 128 was chosen on, and
# runs/session-c/PREREGISTRATION.json's single pre-committed adjustment selects 256 --
# the model's own configured maximum, reached because neither 192 nor 256 gets under 10%.
# Measured before the fit and before any quality number existed.
MAX_SEQ_LEN = 8192

HF_MODEL = "jinaai/jina-embeddings-v2-small-en"

# Tokenizer hazards, each present deliberately. The comment is the reason it is here.
TEXTS: list[str] = [
    "the ingest job times out on the nightly run",           # plain, the lexical cue's fixture
    "we had pasta for dinner",                               # plain, unrelated
    "why is the ingest job timing out",                      # a query, different vocabulary
    "quarterly headcount forecast",                          # shares no vocabulary with the above
    "",                                                      # empty: [CLS] [SEP] and nothing else
    "   ",                                                   # whitespace only
    "\t\n  \r\n ",                                           # other whitespace forms
    "Hello, World!",                                         # punctuation splitting
    "café naïve Zürich",                                     # accents -> stripped under do_lower_case
    "CAFÉ NAÏVE ZÜRICH",                                     # and the casefold path to the same ids
    "Ångström Þorn ﬁligree",                                 # NFD decomposables and a ligature
    "v1.2.3 released 2023-04-17",                            # digits, dots, dates
    "moved off Postgres in April 2023",                      # the temporal-reasoning shape
    "supercalifragilisticexpialidocious",                    # long -> many ## continuations
    "antidisestablishmentarianism tokenization",             # more continuations
    "zzzqqqxx",                                              # unknown-ish -> continuations or [UNK]
    "\U0001f600 \U0001f680 emoji then words",                # astral-plane, likely [UNK]
    "你好世界",                              # CJK: tokenize_chinese_chars spaces each
    "日本語のテキスト",      # Japanese, mixed scripts
    "русский текст",  # Cyrillic
    "é vs é",                                     # combining acute vs precomposed
    "https://example.com/path?q=1&r=2",                      # URL punctuation storm
    "snake_case camelCase kebab-case",                       # identifier shapes
    "def f(x): return x ** 2  # comment",                    # code-ish
    "[CLS] [SEP] [PAD] [MASK] [UNK]",                        # the special tokens AS TEXT
    "100% sure, 3.14159, -42, 1e9",                          # numeric forms
    "a" * 300,                                               # single long word -> continuations
    "the " * 400,                                            # long, but inside 8192 now
    "the migration ran overnight. " * 2200,                  # exceeds MAX_SEQ_LEN 8192 -> truncation
    "I'll send the pricing sheet Thursday",                  # apostrophe, HP15's example
    "don't can't won't it's",                                # contractions
    "  leading and trailing spaces  ",                       # boundary whitespace
    "multiple     internal      spaces",                     # repeated separators
    "MiXeD CaSe WoRdS",                                      # casefold
    "user: hey\nassistant: hello there",                     # a chat turn, newline separated
    # The separator/control split, which looks uniform and behaves oppositely. Zl/Zp
    # survive cleaning and are split on by Python's str.split(); Cc/Cf are DROPPED and weld
    # the word together. LongMemEval transcripts contain U+2028/U+2029 --
    # score_longmemeval.py records exactly that, which is why these are here.
    "ab cd",                                            # Zl -> ["ab", "cd"]
    "ab cd",                                            # Zp -> ["ab", "cd"]
    "ab cd",                                            # Zs -> folded to a space
    "abcd",                                            # Cc -> dropped, welds to "abcd"
    "ab​cd",                                            # Cf -> dropped, welds to "abcd"
    "the migration ran overnight and finished",          # the same, in a realistic turn
]


def build_tokenizer():
    """HuggingFace's BertTokenizer, built from the PINNED files in models/.

    `from_pretrained` on a local directory reads that directory's `vocab.txt` and
    `tokenizer_config.json` — the two files `fetch_model.py` pinned by digest. It does not
    reach the network and cannot pick up a different revision.
    """
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(str(MODEL_DIR), local_files_only=True)


def wordpiece_fixture(tokenizer) -> dict:
    cases = []
    for text in TEXTS:
        encoded = tokenizer(
            text,
            add_special_tokens=True,
            truncation=True,
            max_length=MAX_SEQ_LEN,
            padding=False,
        )
        ids = list(encoded["input_ids"])
        cases.append(
            {
                "text": text,
                "input_ids": ids,
                "tokens": tokenizer.convert_ids_to_tokens(ids),
                "attention_mask": list(encoded["attention_mask"]),
                "truncated": len(ids) == MAX_SEQ_LEN,
            }
        )
    return {
        "_what": (
            "Reference WordPiece tokenization from HuggingFace BertTokenizer, built from the "
            "pinned vocab.txt and tokenizer_config.json. The Rust tokenizer must reproduce "
            "input_ids EXACTLY -- there is no tolerance on an integer."
        ),
        "_generated_by": "tools/make_embedding_fixtures.py",
        "_never_regenerate_to_make_rust_pass": True,
        "model": HF_MODEL,
        "max_seq_len": MAX_SEQ_LEN,
        "settings": {
            "do_lower_case": True,
            "strip_accents": None,
            "tokenize_chinese_chars": True,
            "_strip_accents_note": (
                "null means BertTokenizer derives it from do_lower_case, so accents ARE "
                "stripped. Recorded because 'null' reads like 'off' and is not."
            ),
        },
        "cases": cases,
    }


def reference_embeddings(tokenizer, texts: list[str]) -> np.ndarray:
    """The reference: the pinned ONNX graph, pooled and normalized in numpy.

    **This is not the authority sentence-transformers was.** jina-v2 ships a custom BERT whose
    remote code imports `transformers.onnx`, removed in transformers 5.x, so the published
    PyTorch pipeline cannot be loaded here at all. Recorded as a real loss: what it bought was a
    check that the ONNX export in `models/` is faithful to the published weights, and nothing
    below replaces that.

    What this still does, which is most of the value: it is an independent implementation of
    everything OUR code does around the graph — tokenization, masking, mean pooling, L2
    normalization — in a different language with different arithmetic. A Rust bug in any of
    those fails against this. A bug in the exported weights would not, and that gap is stated
    rather than papered over.
    """
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(
        str(MODEL_DIR / "model.onnx"), options, providers=["CPUExecutionProvider"]
    )
    wanted = {i.name for i in session.get_inputs()}

    out = np.zeros((len(texts), 512), dtype=np.float32)
    for row, text in enumerate(texts):
        encoded = tokenizer(
            text, add_special_tokens=True, truncation=True, max_length=MAX_SEQ_LEN, padding=False
        )
        ids = np.asarray([encoded["input_ids"]], dtype=np.int64)
        mask = np.asarray([encoded["attention_mask"]], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in wanted:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = session.run(None, {k: v for k, v in feed.items() if k in wanted})[0]

        m = mask[0].astype(np.float32)[:, None]
        pooled = (hidden[0] * m).sum(axis=0) / np.clip(m.sum(axis=0), 1e-9, None)
        norm = np.linalg.norm(pooled)
        out[row] = pooled / norm if norm > 0 else pooled
    return out


def maintainer_pooled_embeddings(tokenizer, texts: list[str]) -> np.ndarray | None:
    """The maintainer's OWN pooled graph — an independent check on the pooling recipe.

    `model-w-mean-pooling.onnx` is the same weights with mean pooling compiled into the graph by
    the model's authors. Comparing our hand-written pooling against it answers the question that
    matters most here: *is this the pooling the model expects?* A wrong mask convention or a
    CLS-pooling mistake still yields a unit vector that scores and ranks, and this is what makes
    that observable.

    It substitutes for the faithfulness check lost with sentence-transformers, and on the
    highest-risk component it is a better instrument: it tests the pooling directly rather than
    inferring it from an end-to-end agreement.
    """
    import onnxruntime as ort

    path = MODEL_DIR / "model-w-mean-pooling.onnx"
    if not path.exists():
        return None

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
    wanted = {i.name for i in session.get_inputs()}

    out = np.zeros((len(texts), 512), dtype=np.float32)
    for row, text in enumerate(texts):
        encoded = tokenizer(
            text, add_special_tokens=True, truncation=True, max_length=MAX_SEQ_LEN, padding=False
        )
        ids = np.asarray([encoded["input_ids"]], dtype=np.int64)
        mask = np.asarray([encoded["attention_mask"]], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in wanted:
            feed["token_type_ids"] = np.zeros_like(ids)
        pooled = np.asarray(session.run(None, {k: v for k, v in feed.items() if k in wanted})[0])[0]
        # The graph pools but does not normalize; we compare directions.
        norm = np.linalg.norm(pooled)
        out[row] = pooled / norm if norm > 0 else pooled
    return out


def agreement(a: np.ndarray, b: np.ndarray) -> dict:
    diff = np.abs(a - b)
    cosines = (a * b).sum(axis=1) / np.clip(
        np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1), 1e-12, None
    )
    return {
        "max_abs_diff": float(diff.max()),
        "mean_abs_diff": float(diff.mean()),
        "min_cosine": float(cosines.min()),
        "mean_cosine": float(cosines.mean()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing fixtures. Refused by default: silently regenerating a "
        "reference to match the implementation it validates is the failure these files exist "
        "to prevent.",
    )
    args = parser.parse_args()

    if not MODEL_DIR.exists():
        raise SystemExit(f"{MODEL_DIR} not found. Run `python tools/fetch_model.py` first.")

    FIXTURES.mkdir(parents=True, exist_ok=True)
    wp_path = FIXTURES / "wordpiece-reference.json"
    emb_path = FIXTURES / "embedding-reference.json"
    existing = [p for p in (wp_path, emb_path) if p.exists()]
    if existing and not args.force:
        print(
            f"{', '.join(str(p) for p in existing)} already exist. Refusing to regenerate; "
            "pass --force only if you intend to invalidate every check made against them.",
            file=sys.stderr,
        )
        return 1

    print("building the pinned tokenizer ...")
    tokenizer = build_tokenizer()

    print("writing the wordpiece reference ...")
    wp = wordpiece_fixture(tokenizer)
    wp_path.write_text(json.dumps(wp, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    truncated = sum(1 for c in wp["cases"] if c["truncated"])
    print(f"  {len(wp['cases'])} cases, {truncated} truncated at {MAX_SEQ_LEN}")

    print("embedding with onnxruntime on the pinned model.onnx ...")
    reference = reference_embeddings(tokenizer, TEXTS)

    print("cross-checking the pooling against the maintainer's own pooled graph ...")
    pooled_graph = maintainer_pooled_embeddings(tokenizer, TEXTS)
    export_faithfulness = (
        agreement(reference, pooled_graph)
        if pooled_graph is not None
        else {"unavailable": "model-w-mean-pooling.onnx not fetched"}
    )
    print(
        f"  our pooling vs the maintainer's pooled graph: max abs diff "
        f"{export_faithfulness['max_abs_diff']:.2e}, min cosine "
        f"{export_faithfulness['min_cosine']:.8f}"
    )

    emb = {
        "_what": (
            "Reference embeddings: the pinned ONNX graph, pooled and normalized in numpy. An "
            "independent implementation of everything our code does AROUND the graph. NOT a "
            "check that the exported weights match the published PyTorch model -- jina-v2's "
            "remote code cannot load under transformers 5.x, and that check is genuinely lost."
        ),
        "_generated_by": "tools/make_embedding_fixtures.py",
        "_never_regenerate_to_make_rust_pass": True,
        "_tolerance_floor": (
            "pooling_cross_check_vs_maintainer_graph below is the gap between our hand-written "
            "pooling and the same pooling compiled into the graph by the model's authors. A "
            "Rust-vs-reference tolerance tighter than that would fail an implementation for "
            "being correct."
        ),
        "model": HF_MODEL,
        "revision": "44e7d1d6caec8c883c2d4b207588504d519788d0",
        "dimensions": 512,
        "max_seq_len": MAX_SEQ_LEN,
        "pooling": "mean over the attention mask, then L2 normalize",
        "pooling_cross_check_vs_maintainer_graph": export_faithfulness,
        "cases": [
            {"text": text, "embedding": [float(x) for x in vector]}
            for text, vector in zip(TEXTS, reference)
        ],
    }
    emb_path.write_text(json.dumps(emb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nwrote {wp_path.relative_to(REPO)}")
    print(f"wrote {emb_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
