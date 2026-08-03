"""`verify-corpus` -- structural validation of a real download.

This exists because of a specific hole. The fixtures in this repo were authored from the
published schema descriptions by the same hand that wrote the adapters, so they cannot catch
a misreading: a green fixture suite proves self-consistency and nothing more. The first
contact with real data is where a misread schema surfaces, and without this command that
contact is a debugging session rather than a check.

It scores nothing. It answers one question: is this file the shape the adapter believes?
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from . import locomo, longmemeval
from .errors import CorpusFormatError
from .fetch import MANIFEST, IntegrityError, sha256_of
from .model import Corpus

LOADERS = {
    "longmemeval-s": lambda p: longmemeval.load(p, dataset="longmemeval-s"),
    "longmemeval-m": lambda p: longmemeval.load(p, dataset="longmemeval-m"),
    "locomo": locomo.load,
}

EXPECTED_CATEGORIES = {
    "longmemeval-s": longmemeval.CATEGORIES,
    "longmemeval-m": longmemeval.CATEGORIES,
    "locomo": locomo.CATEGORIES,
}


class VerificationFailed(Exception):
    """Raised with every finding, not just the first -- one read, not one bisect."""

    def __init__(self, dataset: str, findings: list[str]) -> None:
        self.dataset = dataset
        self.findings = findings
        body = "\n".join(f"  - {f}" for f in findings)
        super().__init__(f"{dataset}: {len(findings)} finding(s)\n{body}")


def verify(dataset: str, path: Path, *, strict_counts: bool = True) -> dict[str, Any]:
    if dataset not in LOADERS:
        raise KeyError(f"unknown dataset {dataset!r}; known: {sorted(LOADERS)}")

    path = Path(path)
    findings: list[str] = []
    spec = MANIFEST.get(dataset)

    digest = sha256_of(path) if path.exists() else None
    if spec is not None and spec.sha256 is not None and digest != spec.sha256:
        raise IntegrityError(
            f"{dataset}: digest mismatch; expected {spec.sha256}, got {digest}"
        )

    try:
        corpus: Corpus = LOADERS[dataset](path)
    except CorpusFormatError as exc:
        raise VerificationFailed(dataset, [str(exc)]) from None

    # -- counts -----------------------------------------------------------------
    expected = spec.expected_cases if spec else None
    n_cases = len(corpus.cases)
    if expected is not None and n_cases != expected:
        msg = f"expected {expected} questions, found {n_cases}"
        if strict_counts:
            findings.append(msg)

    # -- category coverage ------------------------------------------------------
    by_category = Counter(c.category for c in corpus.cases)
    declared = EXPECTED_CATEGORIES[dataset]
    for category in declared:
        if by_category.get(category, 0) == 0:
            findings.append(f"category {category!r} has no questions")
    for category in sorted(by_category):
        if category not in declared:
            findings.append(
                f"category {category!r} appears in the data but not in the adapter's "
                "declared set -- the release has drifted"
            )

    # -- the answer key ---------------------------------------------------------
    known_turns = set(corpus.turn_text())
    missing_gold = [
        c.query_id
        for c in corpus.cases
        if not c.is_abstention and not c.gold_turn_ids
    ]
    if missing_gold:
        findings.append(
            f"{len(missing_gold)} answerable questions carry no gold evidence "
            f"(e.g. {missing_gold[:3]}); evidence precision would be uncomputable"
        )
    dangling = [
        (c.query_id, t)
        for c in corpus.cases
        for t in c.gold_turn_ids
        if t not in known_turns
    ]
    if dangling:
        findings.append(
            f"{len(dangling)} gold evidence ids do not match any turn "
            f"(e.g. {dangling[:3]}); the evidence key and the turn ids disagree"
        )

    # -- abstention subset ------------------------------------------------------
    n_abstention = sum(1 for c in corpus.cases if c.is_abstention)
    if n_abstention == 0:
        findings.append(
            "no abstention questions found; K2 puts a floor on the abstention subset and "
            "it cannot be scored"
        )

    if findings:
        raise VerificationFailed(dataset, findings)

    return {
        "dataset": dataset,
        "path": str(path),
        "sha256": digest,
        "manifest_sha256": spec.sha256 if spec else None,
        "questions": n_cases,
        "expected_questions": expected,
        "sessions": len(corpus.sessions),
        "turns": sum(len(s.turns) for s in corpus.sessions),
        "abstention_questions": n_abstention,
        "by_category": dict(sorted(by_category.items())),
        "verdict": "ok",
    }
