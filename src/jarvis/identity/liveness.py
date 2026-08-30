from __future__ import annotations

import secrets
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from jarvis.authority import EvidenceModality, EvidenceVerdict, IdentityEvidence


class LivenessAction(str, Enum):
    BLINK = "blink"
    OPEN_MOUTH = "open_mouth"
    SMILE = "smile"


class LivenessPhase(str, Enum):
    WAIT_NEUTRAL = "wait_neutral"
    WAIT_ACTION = "wait_action"
    WAIT_RELEASE = "wait_release"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class LivenessThresholds:
    blink_neutral_max: float = 0.30
    blink_action_min: float = 0.60
    mouth_neutral_max: float = 0.25
    mouth_action_min: float = 0.55
    smile_neutral_max: float = 0.30
    smile_action_min: float = 0.50
    consecutive_observations: int = 2

    def __post_init__(self) -> None:
        numeric = (
            self.blink_neutral_max,
            self.blink_action_min,
            self.mouth_neutral_max,
            self.mouth_action_min,
            self.smile_neutral_max,
            self.smile_action_min,
        )
        if any(not 0.0 <= value <= 1.0 for value in numeric):
            raise ValueError("liveness thresholds must be in [0, 1]")
        if self.blink_neutral_max >= self.blink_action_min:
            raise ValueError("blink neutral threshold must be below action threshold")
        if self.mouth_neutral_max >= self.mouth_action_min:
            raise ValueError("mouth neutral threshold must be below action threshold")
        if self.smile_neutral_max >= self.smile_action_min:
            raise ValueError("smile neutral threshold must be below action threshold")
        if self.consecutive_observations < 1:
            raise ValueError("consecutive_observations must be positive")


@dataclass(frozen=True, slots=True)
class LivenessChallenge:
    challenge_id: str
    session_id: str
    visual_track_id: int
    actions: tuple[LivenessAction, ...]
    issued_at_monotonic: float
    expires_at_monotonic: float


@dataclass(frozen=True, slots=True)
class LivenessObservation:
    session_id: str
    visual_track_id: int
    observed_at_monotonic: float
    blendshapes: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class LivenessProgress:
    challenge_id: str
    phase: LivenessPhase
    action_index: int
    action: LivenessAction | None
    completed_actions: tuple[LivenessAction, ...]
    reason_codes: tuple[str, ...] = ()

    @property
    def terminal(self) -> bool:
        return self.phase in {LivenessPhase.PASSED, LivenessPhase.FAILED}


class ActiveLivenessChallenge:
    """Fail-closed randomized facial-action challenge bound to one visual track."""

    provider_id = "mediapipe-face-landmarker-active-challenge-v1"

    def __init__(
        self,
        challenge: LivenessChallenge,
        *,
        thresholds: LivenessThresholds | None = None,
    ) -> None:
        if not challenge.actions:
            raise ValueError("liveness challenge requires at least one action")
        if len(set(challenge.actions)) != len(challenge.actions):
            raise ValueError("liveness challenge actions must not repeat")
        if challenge.expires_at_monotonic <= challenge.issued_at_monotonic:
            raise ValueError("liveness challenge expiry must follow issuance")
        self.challenge = challenge
        self.thresholds = thresholds or LivenessThresholds()
        self._phase = LivenessPhase.WAIT_NEUTRAL
        self._action_index = 0
        self._consecutive = 0
        self._completed: list[LivenessAction] = []
        self._reason_codes: tuple[str, ...] = ()
        self._passed_at: float | None = None

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        visual_track_id: int,
        now_monotonic: float | None = None,
        ttl_seconds: float = 24.0,
        actions: Sequence[LivenessAction] | None = None,
    ) -> ActiveLivenessChallenge:
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = time.monotonic() if now_monotonic is None else now_monotonic
        if actions is None:
            action_list = list(LivenessAction)
            secrets.SystemRandom().shuffle(action_list)
            selected = tuple(action_list)
        else:
            selected = tuple(actions)
        challenge = LivenessChallenge(
            challenge_id=str(uuid.uuid4()),
            session_id=session_id,
            visual_track_id=visual_track_id,
            actions=selected,
            issued_at_monotonic=now,
            expires_at_monotonic=now + ttl_seconds,
        )
        return cls(challenge)

    @property
    def progress(self) -> LivenessProgress:
        action = (
            self.challenge.actions[self._action_index]
            if self._action_index < len(self.challenge.actions)
            and self._phase not in {LivenessPhase.PASSED, LivenessPhase.FAILED}
            else None
        )
        return LivenessProgress(
            challenge_id=self.challenge.challenge_id,
            phase=self._phase,
            action_index=self._action_index,
            action=action,
            completed_actions=tuple(self._completed),
            reason_codes=self._reason_codes,
        )

    def observe(self, observation: LivenessObservation) -> LivenessProgress:
        if self.progress.terminal:
            return self.progress
        if observation.session_id != self.challenge.session_id:
            return self.fail("session_mismatch")
        if observation.visual_track_id != self.challenge.visual_track_id:
            return self.fail("visual_track_mismatch")
        if observation.observed_at_monotonic > self.challenge.expires_at_monotonic:
            return self.fail("challenge_expired")
        if observation.observed_at_monotonic < self.challenge.issued_at_monotonic:
            return self.fail("observation_predates_challenge")

        action = self.challenge.actions[self._action_index]
        values = _canonical_blendshapes(observation.blendshapes)
        predicate = (
            self._is_neutral(action, values)
            if self._phase in {LivenessPhase.WAIT_NEUTRAL, LivenessPhase.WAIT_RELEASE}
            else self._is_action(action, values)
        )
        self._consecutive = self._consecutive + 1 if predicate else 0
        if self._consecutive < self.thresholds.consecutive_observations:
            return self.progress

        self._consecutive = 0
        if self._phase is LivenessPhase.WAIT_NEUTRAL:
            self._phase = LivenessPhase.WAIT_ACTION
            return self.progress
        if self._phase is LivenessPhase.WAIT_ACTION:
            self._phase = LivenessPhase.WAIT_RELEASE
            return self.progress

        self._completed.append(action)
        self._action_index += 1
        if self._action_index >= len(self.challenge.actions):
            self._phase = LivenessPhase.PASSED
            self._passed_at = observation.observed_at_monotonic
            return self.progress
        self._phase = LivenessPhase.WAIT_NEUTRAL
        return self.progress

    def check_timeout(self, now_monotonic: float) -> LivenessProgress:
        if not self.progress.terminal and now_monotonic > self.challenge.expires_at_monotonic:
            return self.fail("challenge_expired")
        return self.progress

    def fail(self, reason: str) -> LivenessProgress:
        if self._phase is LivenessPhase.PASSED:
            return self.progress
        if not reason.strip():
            raise ValueError("liveness failure reason must not be empty")
        self._phase = LivenessPhase.FAILED
        self._reason_codes = (reason,)
        self._consecutive = 0
        return self.progress

    def to_identity_evidence(
        self,
        *,
        evidence_ttl_seconds: float = 10.0,
    ) -> IdentityEvidence:
        if self._phase is not LivenessPhase.PASSED or self._passed_at is None:
            raise RuntimeError("only a passed liveness challenge can create evidence")
        if evidence_ttl_seconds <= 0:
            raise ValueError("evidence_ttl_seconds must be positive")
        return IdentityEvidence(
            evidence_id=str(uuid.uuid4()),
            session_id=self.challenge.session_id,
            modality=EvidenceModality.FACE_LIVENESS,
            observed_at_monotonic=self._passed_at,
            expires_at_monotonic=self._passed_at + evidence_ttl_seconds,
            source_id=self.challenge.challenge_id,
            provider_id=self.provider_id,
            verdict=EvidenceVerdict.PASSED,
            visual_track_id=self.challenge.visual_track_id,
            reason_codes=("randomized_active_challenge_passed",),
        )

    def _is_neutral(self, action: LivenessAction, values: Mapping[str, float]) -> bool:
        if action is LivenessAction.BLINK:
            return (
                values.get("eyeblinkleft", 1.0) <= self.thresholds.blink_neutral_max
                and values.get("eyeblinkright", 1.0)
                <= self.thresholds.blink_neutral_max
            )
        if action is LivenessAction.OPEN_MOUTH:
            return values.get("jawopen", 1.0) <= self.thresholds.mouth_neutral_max
        return (
            values.get("mouthsmileleft", 1.0) <= self.thresholds.smile_neutral_max
            and values.get("mouthsmileright", 1.0)
            <= self.thresholds.smile_neutral_max
        )

    def _is_action(self, action: LivenessAction, values: Mapping[str, float]) -> bool:
        if action is LivenessAction.BLINK:
            return (
                values.get("eyeblinkleft", 0.0) >= self.thresholds.blink_action_min
                and values.get("eyeblinkright", 0.0)
                >= self.thresholds.blink_action_min
            )
        if action is LivenessAction.OPEN_MOUTH:
            return values.get("jawopen", 0.0) >= self.thresholds.mouth_action_min
        return (
            values.get("mouthsmileleft", 0.0) >= self.thresholds.smile_action_min
            and values.get("mouthsmileright", 0.0)
            >= self.thresholds.smile_action_min
        )


def _canonical_blendshapes(values: Mapping[str, float]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for name, value in values.items():
        key = "".join(character for character in name.lower() if character.isalnum())
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            continue
        normalized[key] = numeric
    return normalized
