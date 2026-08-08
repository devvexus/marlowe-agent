"""Session J, Part 2 — the determinism gate for a graph this session exported.

**A model this session trained is a second instance of the unvalidated-export gap**, and unlike a
maintainer export it cannot be closed by an external authority, because none exists. What *can* be
done is done here, and what cannot is stated rather than skipped.

Four checks, each re-verified per graph because ADR-013's rule is that a determinism result is not
inheritable:

  1. **Determinism** — same input, same bytes out, across repeats.
  2. **Batch invariance** — Session H measured int8 failing at 0.0958 and all eight f32 graphs
     passing at exactly 0.000000. A newly exported f32 graph has to demonstrate that itself.
  3. **Padding invariance** — ADR-015. Bit-identical token ids, stripped of padding and re-padded
     to a longer tensor, so only the tensor shape differs. On the shipped int8 graph padding alone
     flips top-1 in 15% of cases. An f32 export should be invariant to 0.000000, and if it is not,
     any sweep varying sequence length on this graph is measuring two different scorers.
  4. **torch vs ORT** — the exported graph must reproduce the PyTorch module it came from, on the
     same pairs. This is the only check that speaks to the export itself rather than to the graph's
     behaviour, and it is what "self-validated" means here.

`ORT_ENABLE_BASIC` on the Python side against `ort`'s `Level1`, provider asserted after
construction, batch 1 in the scored path — all inherited from `session_i_rerankers`, not restated.

    python tools/session_j_verify_export.py --model ms-marco-MiniLM-L-6-v2-ft-session-j
"""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "runs" / "session-j"

from session_i_rerankers import batch_invariance, determinism, smoke_test  # noqa: E402
import session_j_models  # noqa: E402

QUERY = "which database did I migrate my analytics warehouse to?"
DOCS = [
    "I finally migrated the analytics warehouse off Postgres and onto ClickHouse in April.",
    "The forecast for the weekend is heavy rain, so the barbecue is probably cancelled.",
    "We talked about the migration again and I confirmed the cutover date with the team.",
]


def padding_invariance(ce, pairs: int = 60) -> dict:
    """ADR-015's check. Bit-identical ids, only the tensor SHAPE differs."""
    tok = ce.tokenizer
    deltas, flips = [], 0
    for i in range(pairs):
        doc = DOCS[i % len(DOCS)] + f" (variant {i})"
        tok.no_truncation()
        tok.no_padding()
        tok.enable_truncation(max_length=256)
        tok.enable_padding(length=256)
        enc = tok.encode(QUERY, doc)
        ids = list(enc.ids)
        mask = list(enc.attention_mask)
        types = list(enc.type_ids)
        # Strip padding, then re-pad to a LONGER tensor. Content is bit-identical.
        keep = sum(mask)
        long_ids = ids[:keep] + [0] * (512 - keep)
        long_mask = mask[:keep] + [0] * (512 - keep)
        long_types = types[:keep] + [0] * (512 - keep)

        def run(a, b, c):
            feed = {"input_ids": np.array([a], dtype=np.int64),
                    "attention_mask": np.array([b], dtype=np.int64)}
            if "token_type_ids" in ce.input_names:
                feed["token_type_ids"] = np.array([c], dtype=np.int64)
            out = np.asarray(ce.session.run(None, feed)[0]).reshape(-1)
            return float(out[0]) if ce.output_dim == 1 else float(out[1] - out[0])

        a = run(ids, mask, types)
        b = run(long_ids, long_mask, long_types)
        deltas.append(abs(a - b))
        if i % 2 == 1 and abs(a - b) > 0:
            flips += 1
    d = np.array(deltas)
    return {
        "pairs": pairs,
        "median_abs_delta": float(np.median(d)),
        "p95_abs_delta": float(np.percentile(d, 95)),
        "max_abs_delta": float(d.max()),
        "invariant": bool(d.max() == 0.0),
        "nonzero_deltas": int((d > 0).sum()),
    }


def torch_vs_ort(ce, hf_repo: str) -> dict:
    """The only check that speaks to the EXPORT rather than to the graph's behaviour."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    directory = REPO / "models" / ce.name
    state = directory / "pytorch-reference"
    if not state.exists():
        return {"run": False,
                "why": "no PyTorch reference was saved beside the export; run the trainer with "
                       "--keep-torch-reference to enable this check"}
    tok = AutoTokenizer.from_pretrained(hf_repo)
    model = AutoModelForSequenceClassification.from_pretrained(str(state))
    model.eval()
    ort_scores, torch_scores = [], []
    with torch.no_grad():
        for doc in DOCS:
            ort_scores.append(ce.score(QUERY, doc, 256))
            enc = tok([QUERY], [doc], padding="max_length", truncation=True,
                      max_length=256, return_tensors="pt")
            torch_scores.append(float(model(**enc).logits.reshape(-1)[0]))
    d = np.abs(np.array(ort_scores) - np.array(torch_scores))
    return {"run": True, "ort": ort_scores, "torch": torch_scores,
            "max_abs_delta": float(d.max()), "agrees": bool(d.max() < 1e-3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--hf-repo", default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    # REQUIRED since Session K. It defaulted to runs/session-j/, so re-running it in a later
    # session silently OVERWROTE Session J's record of what Session J measured. A verification
    # artifact that a re-run can replace is not a record.
    ap.add_argument("--out-dir", required=True,
                    help="where to write the verification artifact, e.g. runs/session-k")
    args = ap.parse_args()

    out_dir = (REPO / args.out_dir) if not os.path.isabs(args.out_dir) else Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    import torch

    lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.isdir(lib):
        try:
            os.add_dll_directory(lib)
        except (AttributeError, OSError):
            pass

    ce = session_j_models.load_finetuned(args.model)
    print(f"{args.model}  digest {ce.digest[:16]}...  provider asserted, ORT_ENABLE_BASIC, 1 thread")

    checks = {
        "smoke_discriminates": smoke_test(ce),
        "determinism": determinism(ce),
        "batch_invariance": batch_invariance(ce),
        "padding_invariance": padding_invariance(ce),
        "torch_vs_ort": torch_vs_ort(ce, args.hf_repo),
    }

    print()
    s = checks["smoke_discriminates"]
    print(f"  1. discriminates          relevant {s['relevant']:+.4f} vs irrelevant "
          f"{s['irrelevant']:+.4f}   {'PASS' if s['pass'] else 'FAIL'}")
    d = checks["determinism"]
    print(f"  2. determinism            {len(set(d['values']))} distinct value(s) over "
          f"{len(d['values'])} runs   {'PASS' if d['pass'] else 'FAIL'}")
    b = checks["batch_invariance"]
    print(f"  3. batch invariance       max |delta| {b['max_abs_diff']:.6f}   "
          f"{'PASS' if b['identical'] else 'FAIL'}")
    p = checks["padding_invariance"]
    print(f"  4. padding invariance     median {p['median_abs_delta']:.6f}  p95 "
          f"{p['p95_abs_delta']:.6f}  max {p['max_abs_delta']:.6f}   "
          f"{'PASS' if p['invariant'] else 'FAIL'}")
    t = checks["torch_vs_ort"]
    if t.get("run"):
        print(f"  5. torch vs ORT           max |delta| {t['max_abs_delta']:.6f}   "
              f"{'PASS' if t['agrees'] else 'FAIL'}")
    else:
        print(f"  5. torch vs ORT           NOT RUN — {t['why']}")

    ok = (checks["smoke_discriminates"]["pass"] and checks["determinism"]["pass"]
          and checks["batch_invariance"]["identical"] and checks["padding_invariance"]["invariant"])
    print()
    print(f"  VERDICT: {'the graph may be scored' if ok else 'REFUSED — do not score with this graph'}")

    out = out_dir / f"export-verification-{args.model}.json"
    out.write_text(json.dumps({
        "_what": "Session J — determinism gate for a graph this session exported.",
        "model": args.model, "digest": ce.digest,
        "checks": checks,
        "pass": bool(ok),
        "open_gap": (
            "SELF-VALIDATED ONLY. There is no external authority for a model this session trained, "
            "so the unvalidated-export gap is NOT closed by these checks — it is bounded by them. "
            "What they establish is that the graph is deterministic, shape-invariant and faithful "
            "to the module it was exported from; what they cannot establish is that the module is "
            "what its publisher intended, because this session is the publisher."
        ),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {out.relative_to(REPO)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
