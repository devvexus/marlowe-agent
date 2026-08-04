"""Write the deterministic text sample the engine spike measures throughput on.

**Drawn from the real corpus, not synthesized.** Throughput on a synthetic short string would
measure the wrong thing entirely: the cost of a transformer forward pass is driven by sequence
length, and this corpus's length distribution is bimodal (median 96 word pieces, 75th percentile
380). A sample that missed the long tail would report a throughput the real run never sees.

Selection is a deterministic stride over turns sorted by turn_id, so the same corpus always
yields the same sample and the spike's numbers are comparable across runs and across engines.

    python tools/make_spike_sample.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval" / "src"))

from marlowe_eval.datasets import longmemeval  # noqa: E402

SPLIT_PATH = REPO / "tools" / "split.json"
OUT_PATH = REPO / "runs" / "session-c" / "spike-sample.json"
SAMPLE_SIZE = 1000


def main() -> int:
    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    corpus = longmemeval.load(REPO / split["corpus_path"])

    turns = sorted(
        ((t.turn_id, t.text) for s in corpus.sessions for t in s.turns), key=lambda p: p[0]
    )
    stride = max(1, len(turns) // SAMPLE_SIZE)
    sample = [text for _, text in turns[::stride]][:SAMPLE_SIZE]

    queries = sorted(c.question for c in corpus.cases)[:100]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(
            {
                "_what": (
                    "Deterministic sample of the real corpus for the engine spike. Stride over "
                    "turns sorted by turn_id; the length distribution is the corpus's own."
                ),
                "corpus_sha256": split["corpus_sha256"],
                "stride": stride,
                "turns": sample,
                "queries": queries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    lengths = [len(t) for t in sample]
    print(f"wrote {OUT_PATH.relative_to(REPO)}")
    print(f"  {len(sample)} turns (stride {stride}), {len(queries)} queries")
    print(f"  chars: mean {sum(lengths)//len(lengths)}, max {max(lengths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
