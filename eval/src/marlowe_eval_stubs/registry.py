"""Resolve a `--target` spec to a MemorySystem.

Only `stub://` is implemented. `exec://` -- spawning a real implementation over the NDJSON
transport -- is deliberately absent until CONTRACTS.md section 4.0 is pinned; see
docs/design/proposed-4.0-transport.md.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from marlowe_eval.adapter.base import MemorySystem
from marlowe_eval.datasets.model import Corpus

from .broken import MUTATIONS, MutatingStub
from .oracle import OracleStub

_FLOAT_KNOBS = {"precision", "abstention_rate", "answer_accuracy", "gate_threshold"}
_INT_KNOBS = {"seed", "maturation_ms", "k"}


def _knobs(query: str) -> dict[str, float | int]:
    out: dict[str, float | int] = {}
    for key, values in parse_qs(query).items():
        value = values[-1]
        if key in _FLOAT_KNOBS:
            out[key] = float(value)
        elif key in _INT_KNOBS:
            out[key] = int(value)
        else:
            raise ValueError(f"unknown stub knob: {key!r}")
    return out


def build_target(spec: str, corpus: Corpus, **overrides: float | int) -> MemorySystem:
    parsed = urlparse(spec)
    if parsed.scheme != "stub":
        raise ValueError(
            f"unsupported target scheme {parsed.scheme!r}. Only stub:// exists; the "
            "subprocess transport awaits the pin of CONTRACTS.md section 4.0."
        )

    kind = parsed.netloc or parsed.path.lstrip("/")
    knobs = {**_knobs(parsed.query), **overrides}

    if kind == "oracle":
        return OracleStub(corpus, **knobs)  # type: ignore[arg-type]

    if kind == "broken.clock_reader":
        # Not a response mutation: a stub that reads the system clock, which is exactly what
        # section 4.5 forbids and what the clock probe must catch.
        return OracleStub(corpus, read_system_clock=True, **knobs)  # type: ignore[arg-type]

    if kind.startswith("broken."):
        name = kind.split(".", 1)[1]
        if name not in MUTATIONS:
            raise ValueError(f"unknown conformance fixture: {name!r}")
        mutation, _ = MUTATIONS[name]
        return MutatingStub(OracleStub(corpus, **knobs), mutation, kind)  # type: ignore[arg-type]

    raise ValueError(f"unknown stub target: {kind!r}")


def describe_targets() -> dict[str, str]:
    out = {
        "stub://oracle": "reference implementation; reads the answer key, does not search",
        "stub://broken.clock_reader": "reads a system clock; must fail the clock probe",
    }
    for name, (_, what) in MUTATIONS.items():
        out[f"stub://broken.{name}"] = what
    return out
