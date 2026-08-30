from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .types import AttentionState, EvidenceModality


class EvidenceVerdict(str, Enum):
    MATCH = "match"
    NO_MATCH = "no_match"
    PASSED = "passed"
    FAILED = "failed"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    evidence_id: str
    session_id: str
    modality: EvidenceModality
    observed_at_monotonic: float
    expires_at_monotonic: float
    source_id: str
    provider_id: str
    verdict: EvidenceVerdict
    visual_track_id: int | None = None
    audio_turn_id: str | None = None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AttentionObservation:
    session_id: str
    visual_track_id: int
    state: AttentionState
    observed_at_monotonic: float
    expires_at_monotonic: float
    reason_codes: tuple[str, ...] = ()


class AttentionEvidenceProvider(Protocol):
    def observe_attention(
        self,
        *,
        session_id: str,
        visual_track_id: int,
    ) -> AttentionObservation: ...
