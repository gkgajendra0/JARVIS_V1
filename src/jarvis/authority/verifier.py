from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .proposal import ActionProposal


class StrongVerificationStatus(str, Enum):
    VERIFIED = "verified"
    CANCELED = "canceled"
    FAILED = "failed"
    RETRIES_EXHAUSTED = "retries_exhausted"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class StrongVerificationResult:
    status: StrongVerificationStatus
    verifier_id: str
    reason_codes: tuple[str, ...] = ()

    @property
    def verified(self) -> bool:
        return self.status is StrongVerificationStatus.VERIFIED


class StrongVerifier(Protocol):
    def verify(
        self,
        *,
        proposal: ActionProposal,
        session_id: str,
    ) -> StrongVerificationResult: ...
