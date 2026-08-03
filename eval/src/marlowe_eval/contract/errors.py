"""Protocol errors.

A protocol error is NOT a warning and NOT a score. It means the implementation returned
something CONTRACTS.md section 4 does not permit, so there is no result to record. The
distinction is load-bearing:

  * protocol error  -> the response is unscoreable; the run fails loudly
  * scored failure  -> the response was valid and the implementation did badly

Missing a latency budget is the second kind. Missing `cost` is the first.
"""

from __future__ import annotations

import enum


class Interface(str, enum.Enum):
    """The three interfaces of the section 4 boundary. There is no fourth."""

    INGEST = "ingest"
    RETRIEVE = "retrieve"
    ANSWER = "answer"


class ProtocolErrorKind(str, enum.Enum):
    # -- section 4.2b / 4.6 / 4.7: cost is not optional on any interface -------------
    MISSING_COST = "missing_cost"

    # -- section 4.7: the honest "no" and a hedged answer are distinct outcomes ------
    HEDGED_ABSTENTION = "hedged_abstention"

    # -- section 4.2: abstention and injection are mutually exclusive, both ways -----
    ABSTAINED_WITH_INJECTED = "abstained_with_injected"
    REASON_WITHOUT_ABSTENTION = "reason_without_abstention"
    EMPTY_INJECTION_WITHOUT_ABSTENTION = "empty_injection_without_abstention"

    # -- section 4.7: the same exclusivity on the answer interface ------------------
    GROUNDED_WHILE_ABSTAINED = "grounded_while_abstained"
    UNANSWERED_WITHOUT_ABSTENTION = "unanswered_without_abstention"

    # -- section 4.3: a tombstone can never appear in `injected` ---------------------
    TOMBSTONE_INJECTED = "tombstone_injected"

    # -- section 4.5: clock required on all three interfaces ------------------------
    MISSING_CLOCK = "missing_clock"

    # -- section 4.6: M0a declares origin, never trust ------------------------------
    HARNESS_DECLARED_TRUST = "harness_declared_trust"

    # -- shape ----------------------------------------------------------------------
    MISSING_FIELD = "missing_field"
    UNKNOWN_FIELD = "unknown_field"
    BAD_TYPE = "bad_type"
    BAD_ENUM = "bad_enum"
    MALFORMED_JSON = "malformed_json"
    CONTRACT_VERSION_MISMATCH = "contract_version_mismatch"
    CORRELATION_MISMATCH = "correlation_mismatch"


class ProtocolError(Exception):
    """Raised when a payload violates section 4. Carries enough to report per interface."""

    def __init__(
        self,
        kind: ProtocolErrorKind,
        interface: Interface,
        detail: str,
        *,
        location: str | None = None,
    ) -> None:
        self.kind = kind
        self.interface = interface
        self.detail = detail
        self.location = location
        where = f" at {location}" if location else ""
        super().__init__(f"[{interface.value}] {kind.value}{where}: {detail}")

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "interface": self.interface.value,
            "detail": self.detail,
            "location": self.location or "",
        }
