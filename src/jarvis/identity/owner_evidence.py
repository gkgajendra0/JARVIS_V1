from __future__ import annotations

import statistics
import uuid
from collections import deque
from dataclasses import dataclass
from enum import Enum

import numpy as np

from jarvis.authority import EvidenceModality, EvidenceVerdict, IdentityEvidence
from jarvis.identity.passive_liveness import (
    PassiveLivenessAssessment,
    PassiveLivenessState,
)


class OwnerIdentityState(str, Enum):
    INSUFFICIENT = "insufficient"
    OWNER_CANDIDATE = "owner_candidate"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class OwnerIdentityThresholds:
    """Provisional 3B.8 evidence-only bands; these do not grant T2."""

    window_size: int = 15
    owner_candidate_min: float = 0.65
    unknown_max: float = 0.35
    max_inter_observation_gap_seconds: float = 0.50

    def __post_init__(self) -> None:
        if self.window_size < 3:
            raise ValueError("OWNER identity window_size must be at least 3")
        if not 0.0 <= self.unknown_max < self.owner_candidate_min <= 1.0:
            raise ValueError(
                "OWNER identity thresholds must satisfy 0 <= unknown < owner <= 1"
            )
        if self.max_inter_observation_gap_seconds <= 0:
            raise ValueError("OWNER identity max observation gap must be positive")


@dataclass(frozen=True, slots=True)
class OwnerIdentityObservation:
    session_id: str
    visual_track_id: int
    provider_id: str
    observed_at_monotonic: float
    max_prototype_cosine: float

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        if not self.provider_id.strip():
            raise ValueError("provider_id must not be empty")
        if self.observed_at_monotonic < 0:
            raise ValueError("observed_at_monotonic must be non-negative")
        if not -1.0 <= self.max_prototype_cosine <= 1.0:
            raise ValueError("max_prototype_cosine must be in [-1, 1]")


@dataclass(frozen=True, slots=True)
class OwnerIdentityAssessment:
    session_id: str
    visual_track_id: int
    provider_id: str
    observed_at_monotonic: float
    state: OwnerIdentityState
    sample_count: int
    window_size: int
    temporal_similarity: float | None
    reason_codes: tuple[str, ...]


class TemporalOwnerIdentity:
    """Temporal SFace OWNER-candidate evidence bound to one session and track."""

    provider_id = "jarvis-sface-temporal-owner-candidate-v1"

    def __init__(
        self,
        *,
        session_id: str,
        visual_track_id: int,
        face_provider_id: str,
        thresholds: OwnerIdentityThresholds | None = None,
    ) -> None:
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        if not face_provider_id.strip():
            raise ValueError("face_provider_id must not be empty")
        self.session_id = session_id
        self.visual_track_id = visual_track_id
        self.face_provider_id = face_provider_id
        self.thresholds = thresholds or OwnerIdentityThresholds()
        self._observations: deque[OwnerIdentityObservation] = deque(
            maxlen=self.thresholds.window_size
        )
        self._last_observed_at: float | None = None

    def clear(self) -> None:
        self._observations.clear()
        self._last_observed_at = None

    def observe(self, observation: OwnerIdentityObservation) -> OwnerIdentityAssessment:
        self._validate_binding(observation)
        if (
            self._last_observed_at is not None
            and observation.observed_at_monotonic < self._last_observed_at
        ):
            raise ValueError("OWNER identity observations must be monotonic")
        if (
            self._last_observed_at is not None
            and observation.observed_at_monotonic - self._last_observed_at
            > self.thresholds.max_inter_observation_gap_seconds
        ):
            self.clear()

        self._observations.append(observation)
        self._last_observed_at = observation.observed_at_monotonic
        return self.assessment

    @property
    def assessment(self) -> OwnerIdentityAssessment:
        count = len(self._observations)
        observed_at = self._last_observed_at or 0.0
        if count < self.thresholds.window_size:
            return OwnerIdentityAssessment(
                session_id=self.session_id,
                visual_track_id=self.visual_track_id,
                provider_id=self.provider_id,
                observed_at_monotonic=observed_at,
                state=OwnerIdentityState.INSUFFICIENT,
                sample_count=count,
                window_size=self.thresholds.window_size,
                temporal_similarity=None,
                reason_codes=("owner_temporal_window_incomplete",),
            )

        similarity = float(
            statistics.median(
                observation.max_prototype_cosine for observation in self._observations
            )
        )
        if similarity >= self.thresholds.owner_candidate_min:
            state = OwnerIdentityState.OWNER_CANDIDATE
            reasons = ("provisional_temporal_owner_candidate_t2_disabled",)
        elif similarity <= self.thresholds.unknown_max:
            state = OwnerIdentityState.UNKNOWN
            reasons = ("temporal_owner_similarity_very_low",)
        else:
            state = OwnerIdentityState.AMBIGUOUS
            reasons = ("owner_identity_ambiguous_non_owner_calibration_missing",)

        return OwnerIdentityAssessment(
            session_id=self.session_id,
            visual_track_id=self.visual_track_id,
            provider_id=self.provider_id,
            observed_at_monotonic=observed_at,
            state=state,
            sample_count=count,
            window_size=self.thresholds.window_size,
            temporal_similarity=similarity,
            reason_codes=reasons,
        )

    def to_identity_evidence(
        self,
        assessment: OwnerIdentityAssessment | None = None,
        *,
        evidence_ttl_seconds: float = 2.0,
    ) -> IdentityEvidence:
        if evidence_ttl_seconds <= 0:
            raise ValueError("evidence_ttl_seconds must be positive")
        current = assessment or self.assessment
        if current.session_id != self.session_id:
            raise ValueError("assessment session does not match OWNER identity binding")
        if current.visual_track_id != self.visual_track_id:
            raise ValueError("assessment track does not match OWNER identity binding")

        verdict = {
            OwnerIdentityState.OWNER_CANDIDATE: EvidenceVerdict.MATCH,
            OwnerIdentityState.UNKNOWN: EvidenceVerdict.NO_MATCH,
            OwnerIdentityState.AMBIGUOUS: EvidenceVerdict.INSUFFICIENT,
            OwnerIdentityState.INSUFFICIENT: EvidenceVerdict.INSUFFICIENT,
        }[current.state]
        return IdentityEvidence(
            evidence_id=str(uuid.uuid4()),
            session_id=self.session_id,
            modality=EvidenceModality.FACE_MATCH,
            observed_at_monotonic=current.observed_at_monotonic,
            expires_at_monotonic=current.observed_at_monotonic + evidence_ttl_seconds,
            source_id=f"owner-face-track:{self.visual_track_id}",
            provider_id=self.provider_id,
            verdict=verdict,
            visual_track_id=self.visual_track_id,
            reason_codes=current.reason_codes,
        )

    def _validate_binding(self, observation: OwnerIdentityObservation) -> None:
        if observation.session_id != self.session_id:
            raise ValueError("OWNER identity session mismatch")
        if observation.visual_track_id != self.visual_track_id:
            raise ValueError("OWNER identity visual track mismatch")
        if observation.provider_id != self.face_provider_id:
            raise ValueError("OWNER identity face provider mismatch")


class OwnerLivenessBindingState(str, Enum):
    INSUFFICIENT = "insufficient"
    LIVE_OWNER_CANDIDATE = "live_owner_candidate"
    ACTIVE_CHALLENGE_ELIGIBLE = "active_challenge_eligible"
    SPOOFED_OWNER_PRESENTATION = "spoofed_owner_presentation"
    UNKNOWN_SUBJECT = "unknown_subject"
    AMBIGUOUS_SUBJECT = "ambiguous_subject"


@dataclass(frozen=True, slots=True)
class OwnerLivenessBindingAssessment:
    session_id: str
    visual_track_id: int
    state: OwnerLivenessBindingState
    identity_state: OwnerIdentityState
    liveness_state: PassiveLivenessState
    observed_at_monotonic: float
    reason_codes: tuple[str, ...]

    @property
    def face_evidence_grants_t2(self) -> bool:
        return False

    @property
    def requires_active_challenge(self) -> bool:
        return self.state is OwnerLivenessBindingState.ACTIVE_CHALLENGE_ELIGIBLE


def bind_owner_liveness(
    identity: OwnerIdentityAssessment,
    liveness: PassiveLivenessAssessment,
    *,
    max_observation_skew_seconds: float = 0.50,
) -> OwnerLivenessBindingAssessment:
    if max_observation_skew_seconds <= 0:
        raise ValueError("max_observation_skew_seconds must be positive")
    if identity.session_id != liveness.session_id:
        raise ValueError("OWNER/liveness session mismatch")
    if identity.visual_track_id != liveness.visual_track_id:
        raise ValueError("OWNER/liveness visual track mismatch")

    observed_at = min(identity.observed_at_monotonic, liveness.observed_at_monotonic)
    skew = abs(identity.observed_at_monotonic - liveness.observed_at_monotonic)
    if skew > max_observation_skew_seconds:
        return OwnerLivenessBindingAssessment(
            session_id=identity.session_id,
            visual_track_id=identity.visual_track_id,
            state=OwnerLivenessBindingState.INSUFFICIENT,
            identity_state=identity.state,
            liveness_state=liveness.state,
            observed_at_monotonic=observed_at,
            reason_codes=("owner_liveness_not_cofresh",),
        )

    if identity.state is OwnerIdentityState.INSUFFICIENT:
        state = OwnerLivenessBindingState.INSUFFICIENT
        reasons = ("owner_identity_insufficient",)
    elif identity.state is OwnerIdentityState.UNKNOWN:
        state = OwnerLivenessBindingState.UNKNOWN_SUBJECT
        reasons = ("owner_identity_unknown",)
    elif identity.state is OwnerIdentityState.AMBIGUOUS:
        state = OwnerLivenessBindingState.AMBIGUOUS_SUBJECT
        reasons = ("owner_identity_ambiguous",)
    elif liveness.state is PassiveLivenessState.INSUFFICIENT:
        state = OwnerLivenessBindingState.INSUFFICIENT
        reasons = ("owner_liveness_insufficient",)
    elif liveness.state is PassiveLivenessState.LIVE:
        state = OwnerLivenessBindingState.LIVE_OWNER_CANDIDATE
        reasons = ("live_owner_candidate_t2_disabled",)
    elif liveness.state is PassiveLivenessState.UNCERTAIN:
        state = OwnerLivenessBindingState.ACTIVE_CHALLENGE_ELIGIBLE
        reasons = ("owner_candidate_passive_liveness_uncertain",)
    else:
        state = OwnerLivenessBindingState.SPOOFED_OWNER_PRESENTATION
        reasons = ("owner_candidate_passive_liveness_spoof",)

    return OwnerLivenessBindingAssessment(
        session_id=identity.session_id,
        visual_track_id=identity.visual_track_id,
        state=state,
        identity_state=identity.state,
        liveness_state=liveness.state,
        observed_at_monotonic=observed_at,
        reason_codes=reasons,
    )


def max_prototype_cosine(prototypes: np.ndarray, feature: np.ndarray) -> float:
    matrix = np.asarray(prototypes, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] < 1:
        raise ValueError("OWNER prototypes must be a non-empty 2-D matrix")
    if not np.isfinite(matrix).all():
        raise ValueError("OWNER prototypes must be finite")
    prototype_norms = np.linalg.norm(matrix, axis=1)
    if not np.allclose(prototype_norms, 1.0, atol=1e-4):
        raise ValueError("OWNER prototypes must be L2-normalized")

    vector = np.asarray(feature, dtype=np.float32).reshape(-1)
    if vector.size != matrix.shape[1] or not np.isfinite(vector).all():
        raise ValueError("SFace feature is invalid or dimensionally incompatible")
    norm = float(np.linalg.norm(vector))
    if norm <= 0:
        raise ValueError("SFace feature norm must be positive")
    normalized = vector / norm
    return float(np.max(matrix @ normalized))
