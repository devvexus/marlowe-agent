"""M0c Session M, W1 — register this arm's graphs in the ONE loader, at runtime.

`tools/session_i_rerankers.py` is not edited. Its `FINETUNES` dict is the registry the single
loader consults, and this module adds W1's entries to it from
`runs/session-m0c-m/capacity-manifest.json` — the manifest `finetune_capacity.py` writes and pins.

**Why runtime registration rather than a source edit.** Session I's manifest is a record and
`session_i_rerankers.FINETUNES` has accumulated three sessions' worth of entries; adding a fourth
in source would put this arm's pins in a file two other sessions read. The load-time guarantees are
unaffected — `load` still hashes `model.onnx` and refuses on a mismatch, still asserts the provider,
still validates the pair encoding and the head — because the entry supplies only the digest to
check against, and the checking is the loader's.

Importing this module is the whole interface:

    import capacity_register  # noqa: F401
    import session_i_rerankers as R
    ce = R.load("ms-marco-MiniLM-L-12-v2-ft-w1")

A name whose graph is missing from disk, or whose digest has drifted, still fails at `load`. What
this module CANNOT do is make an unpinned model loadable, and that is deliberate.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import session_i_rerankers as R

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "runs" / "session-m0c-m" / "capacity-manifest.json"

REGISTERED: list[str] = []


def register() -> list[str]:
    if not MANIFEST.exists():
        return []
    data = json.loads(io.open(MANIFEST, encoding="utf-8").read())
    added = []
    for m in data["models"]:
        name = m["name"]
        if name == R.SHIPPED_FINETUNE:
            raise R.ModelRefused(
                f"{name} is the shipped control. W1 must not shadow it in the registry."
            )
        R.FINETUNES[name] = {
            "digest": m["digests"]["model.onnx"],
            "params_m": m["params_m"],
            "arch": "BERT",
            "max_seq": m["max_seq"],
        }
        added.append(name)
    return added


REGISTERED = register()
