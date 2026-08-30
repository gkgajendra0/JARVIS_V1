from __future__ import annotations

import statistics
import uuid
from collections import deque
from dataclasses import dataclass
from enum import Enum

from jarvis.authority import EvidenceModality, EvidenceVerdict, IdentityEvidence


class PassiveLivenessState(str, Enum):
    INSUFFICIENT = "insufficient"
    LIVE = "live"
    UNCERTAIN = "uncertain"
    SPOOF = "spoof"


@dataclass(frozen=True, slots=True)
class PassiveLivenessThresholds:
    """Pocket-3/MiniFAS temporal bands accepted from Step 3B.7B evidence."""

    window_size: int = 15
    live_min: float = 0.95
    spoof_max: float = 0.50
    max_inter_observation_gap_seconds: float = 0.50

    def __post_init__(self) -> None:
        if self.window_size < 3:
            raise ValueError("passive liveness window_size must be at least 3")
        if not 0.0 <= self.spoof_max < self.live_min <= 1.0:
            raise ValueError("passive liveness thresholds must satisfy 0 <= spoof < live <= 1")
        if self.max_inter_observation_gap_seconds <= 0:
            raise ValueError("passive liveness max observation gap must be positive")


@dataclass(frozen=True, slots=True)
class PassiveLivenessObservation:
    session_id: str
    visual_track_id: int
    provider_id: str
    observed_at_monotonic: float
    real_probability: float

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        if not self.provider_id.strip():
            raise ValueError("provider_id must not be empty")
        if self.observed_at_monotonic < 0:
            raise ValueError("observed_at_monotonic must be non-negative")
        if not 0.0 <= self.real_probability <= 1.0:
            raise ValueError("real_probability must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class PassiveLivenessAssessment:
    session_id: str
    visual_track_id: int
    provider_id: str
    observed_at_monotonic: float
    state: PassiveLivenessState
    sample_count: int
    window_size: int
    temporal_real_probability: float | None
    reason_codes: tuple[str, ...]

    @property
    def requires_active_challenge(self) -> bool:
        return self.state is PassiveLivenessState.UNCERTAIN


class TemporalPassiveLiveness:
    """JARVIS-owned temporal fusion for the accepted MiniFAS RGB PAD provider.

    The object is deliberately bound to one Windows session, one visual track, and
    one PAD provider. Cross-session/track/provider observations are rejected rather
    than blended. A long observation gap clears the temporal window so stale frames
    cannot contribute to fresh liveness evidence.
    """

    provider_id = "jarvis-minifas-temporal-passive-liveness-v1"

    def __init__(
        self,
        *,
        session_id: str,
        visual_track_id: int,
        pad_provider_id: str,
        thresholds: PassiveLivenessThresholds | None = None,
    ) -> None:
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        if not pad_provider_id.strip():
            raise ValueError("pad_provider_id must not be empty")
        self.session_id = session_id
        self.visual_track_id = visual_track_id
        self.pad_provider_id = pad_provider_id
        self.thresholds = thresholds or PassiveLivenessThresholds()
        self._observations: deque[PassiveLivenessObservation] = deque(
            maxlen=self.thresholds.window_size
        )
        self._last_observed_at: float | None = None

    def clear(self) -> None:
        self._observations.clear()
        self._last_observed_at = None

    def observe(
        self, observation: PassiveLivenessObservation
    ) -> PassiveLivenessAssessment:
        self._validate_binding(observation)
        if (
            self._last_observed_at is not None
            and observation.observed_at_monotonic < self._last_observed_at
        ):
            raise ValueError("passive liveness observations must be monotonic")
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
    def assessment(self) -> PassiveLivenessAssessment:
        count = len(self._observations)
        observed_at = self._last_observed_at or 0.0
        if count < self.thresholds.window_size:
            return PassiveLivenessAssessment(
                session_id=self.session_id,
                visual_track_id=self.visual_track_id,
                provider_id=self.provider_id,
                observed_at_monotonic=observed_at,
                state=PassiveLivenessState.INSUFFICIENT,
                sample_count=count,
                window_size=self.thresholds.window_size,
                temporal_real_probability=None,
                reason_codes=("temporal_window_incomplete",),
            )

        temporal_probability = float(
            statistics.median(
                observation.real_probability for observation in self._observations
            )
        )
        if temporal_probability >= self.thresholds.live_min:
            state = PassiveLivenessState.LIVE
            reasons = ("temporal_pad_live",)
        elif temporal_probability <= self.thresholds.spoof_max:
            state = PassiveLivenessState.SPOOF
            reasons = ("temporal_pad_spoof",)
        else:
            state = PassiveLivenessState.UNCERTAIN
            reasons = ("temporal_pad_uncertain_active_challenge_required",)

        return PassiveLivenessAssessment(
            session_id=self.session_id,
            visual_track_id=self.visual_track_id,
            provider_id=self.provider_id,
            observed_at_monotonic=observed_at,
            state=state,
            sample_count=count,
            window_size=self.thresholds.window_size,
            temporal_real_probability=temporal_probability,
            reason_codes=reasons,
        )

    def to_identity_evidence(
        self,
        assessment: PassiveLivenessAssessment | None = None,
        *,
        evidence_ttl_seconds: float = 2.0,
    ) -> IdentityEvidence:
        if evidence_ttl_seconds <= 0:
            raise ValueError("evidence_ttl_seconds must be positive")
        current = assessment or self.assessment
        if current.session_id != self.session_id:
            raise ValueError("assessment session does not match passive liveness binding")
        if current.visual_track_id != self.visual_track_id:
            raise ValueError("assessment track does not match passive liveness binding")

        verdict = {
            PassiveLivenessState.LIVE: EvidenceVerdict.PASSED,
            PassiveLivenessState.SPOOF: EvidenceVerdict.FAILED,
            PassiveLivenessState.UNCERTAIN: EvidenceVerdict.INSUFFICIENT,
            PassiveLivenessState.INSUFFICIENT: EvidenceVerdict.INSUFFICIENT,
        }[current.state]
        return IdentityEvidence(
            evidence_id=str(uuid.uuid4()),
            session_id=self.session_id,
            modality=EvidenceModality.FACE_LIVENESS,
            observed_at_monotonic=current.observed_at_monotonic,
            expires_at_monotonic=current.observed_at_monotonic
            + evidence_ttl_seconds,
            source_id=f"passive-pad-track:{self.visual_track_id}",
            provider_id=self.provider_id,
            verdict=verdict,
            visual_track_id=self.visual_track_id,
            reason_codes=current.reason_codes,
        )

    def _validate_binding(self, observation: PassiveLivenessObservation) -> None:
        if observation.session_id != self.session_id:
            raise ValueError("passive liveness session mismatch")
        if observation.visual_track_id != self.visual_track_id:
            raise ValueError("passive liveness visual track mismatch")
        if observation.provider_id != self.pad_provider_id:
            raise ValueError("passive liveness PAD provider mismatch")
