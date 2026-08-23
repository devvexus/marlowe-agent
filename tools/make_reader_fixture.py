"""Generate the answerability reference fixture for the mobilebert reader.

Same discipline as make_cross_encoder_fixtures.py: HuggingFace `tokenizers` + ONNX Runtime are
the authority; `crates/marlowe-memory` must reproduce their answerability score or the test
fails. NEVER regenerated to make a test pass. Generated on CPUExecutionProvider for
determinism, at the shipped MAX_SEQ 256.

    python tools/make_reader_fixture.py \\
        --model-dir models/mobilebert-uncased-squad-v2 \\
        --out crates/marlowe-memory/tests/fixtures/answerability-reference-mobilebert.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
MAX_SEQ = 256

CASES = [
    ("short notation fragment", "what was the move after 27. Kg2 Bd5+?",
     "28. Kg3 would be my move."),
    ("verbatim value", "What breed is my dog?",
     "I'm thinking of getting Max a new collar. It should suit a Golden Retriever like Max."),
    ("ratio in prose", "what is the recommended dilution ratio for tea tree oil?",
     "It's essential to dilute tea tree oil with a carrier oil such as coconut oil in a 1:10 "
     "ratio to prevent skin irritation."),
    ("no answer here", "What breed is my dog?",
     "I've been pretty happy with my external hard drive, a 2TB Western Digital, bought recently."),
    ("question echo only", "What breed is my dog?",
     "Why do you want to know what breed of dog I have?"),
    ("long turn", "what did I plant recently?",
     "Garden update. " + ("The tomato bed needs mulch and the peppers need staking. " * 12)
     + " By the way, I planted 12 new tomato saplings today."),
    ("numeric answer", "how many museums did I visit in February?",
     "I took my niece to the Natural History Museum on 2/8 and she loved the dinosaur exhibit!"),
    ("unicode accents", "what café did I recommend?",
     "You should try Café Anglais — the pastry chef is excellent."),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(str(args.model_dir / "tokenizer.json"))
    sess_options = None
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    sess = ort.InferenceSession(str(args.model_dir / "model.onnx"), sess_options=options,
                                providers=["CPUExecutionProvider"])
    input_names = {i.name for i in sess.get_inputs()}
    print("graph inputs:", sorted(input_names))

    out_cases = []
    for name, query, document in CASES:
        enc = tok.encode(query, document)
        ids = enc.ids[:MAX_SEQ]
        mask = enc.attention_mask[:MAX_SEQ]
        type_ids = enc.type_ids[:MAX_SEQ]
        feed = {"input_ids": np.array([ids], dtype=np.int64),
                "attention_mask": np.array([mask], dtype=np.int64)}
        if "token_type_ids" in input_names:
            feed["token_type_ids"] = np.array([type_ids], dtype=np.int64)
        out = sess.run(None, feed)
        start = np.asarray(out[0]).reshape(-1).astype(np.float64)
        end = np.asarray(out[1]).reshape(-1).astype(np.float64)
        null = float(start[0] + end[0])
        seq = enc.sequence_ids[:MAX_SEQ] if enc.sequence_ids else [1 if t else 0 for t in type_ids]
        idx = [i for i in range(len(ids)) if (seq[i] == 1 if i < len(seq) else False) and mask[i] == 1]
        if not idx:
            score = 0.0
        else:
            lo, hi = idx[0], idx[-1]
            s_win, e_win = start[lo:hi + 1], end[lo:hi + 1]
            best = np.maximum.accumulate(s_win)
            span = float(np.max(best + e_win))
            score = span - null
        out_cases.append({"name": name, "query": query, "document": document,
                          "score": round(score, 6)})
        print(f"  {name:26} score {score:+.4f}")

    art = {"_what": "answerability reference fixture (HuggingFace tokenizers + ONNX Runtime CPU)",
           "max_seq_len": MAX_SEQ, "cases": out_cases}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(art, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
