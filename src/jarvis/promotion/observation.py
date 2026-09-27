"""Durable production observation and deterministic failure attribution."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum

from jarvis.engineering_change.models import ChangeArtifact, ChangeConflict, ChangeState
from jarvis.engineering_change.store import ChangeStore

from .models import PromotionAttempt, PromotionAttemptState
from .release import DeploymentMetadataStore
from .store import PromotionStore


class FailureAttribution(str, Enum):
    CANDIDATE_LOCAL = "candidate_local"
    EXTERNAL_PROVIDER = "external_provider"
    EXTERNAL_HARDWARE = "external_hardware"
    UNKNOWN = "unknown"


class ObservationDisposition(str, Enum):
    CONTINUE = "continue"
    READY_TO_CLOSE = "ready_to_close"
    ROLLBACK_REQUIRED = "rollback_required"
    BLOCKED_UNKNOWN = "blocked_unknown"


@dataclass(frozen=True, slots=True)
class ObservationAssessment:
    disposition: ObservationDisposition
    healthy_samples: int
    external_failures: int
    unknown_failures: int
    candidate_failures: int


class ObservationController:
    """Persist observations and close only after bounded independent healthy evidence."""

    _ARTIFACT_KIND = "production_observation"

    def __init__(
        self,
        changes: ChangeStore,
        promotions: PromotionStore,
        metadata: DeploymentMetadataStore,
        *,
        required_healthy_samples: int = 3,
    ) -> None:
        if promotions.changes is not changes:
            raise ValueError("promotion store must share the canonical ChangeStore")
        if type(required_healthy_samples) is not int or required_healthy_samples < 1:
            raise ValueError("required_healthy_samples must be positive")
        self._changes = changes
        self._promotions = promotions
        self._metadata = metadata
        self._required_healthy_samples = required_healthy_samples

    def _record(
        self,
        attempt: PromotionAttempt,
        *,
        healthy: bool,
        attribution: FailureAttribution | None,
        reason_code: str,
        evidence: tuple[str, ...],
        now_epoch: float | None,
    ) -> ChangeArtifact:
        current = self._promotions.require(attempt.attempt_id)
        if current.state is not PromotionAttemptState.OBSERVING:
            raise ChangeConflict("promotion attempt is not observing")
        if healthy and attribution is not None:
            raise ValueError("healthy observation cannot carry failure attribution")
        if not healthy and not isinstance(attribution, FailureAttribution):
            raise ValueError("failed observation requires typed attribution")
        reason = str(reason_code).strip()
        if not reason:
            raise ValueError("observation reason_code must not be empty")
        normalized_evidence = tuple(
            dict.fromkeys(str(item).strip() for item in evidence if str(item).strip())
        )
        timestamp = time.time() if now_epoch is None else float(now_epoch)
        if not math.isfinite(timestamp) or timestamp <= 0:
            raise ValueError("observation timestamp must be finite and positive")
        artifacts = self._observations(attempt.change_id, attempt.attempt_id)
        return self._changes.add_artifact(
            attempt.change_id,
            kind=self._ARTIFACT_KIND,
            payload={
                "attempt_id": attempt.attempt_id,
                "ordinal": len(artifacts) + 1,
                "healthy": healthy,
                "attribution": None if attribution is None else attribution.value,
                "reason_code": reason,
                "evidence": list(normalized_evidence),
                "observed_at_epoch": timestamp,
            },
        )

    def record_healthy(
        self,
        attempt: PromotionAttempt,
        *,
        reason_code: str = "runtime_healthy",
        evidence: tuple[str, ...] = (),
        now_epoch: float | None = None,
    ) -> ChangeArtifact:
        return self._record(
            attempt,
            healthy=True,
            attribution=None,
            reason_code=reason_code,
            evidence=evidence,
            now_epoch=now_epoch,
        )

    def record_failure(
        self,
        attempt: PromotionAttempt,
        *,
        attribution: FailureAttribution,
        reason_code: str,
        evidence: tuple[str, ...] = (),
        now_epoch: float | None = None,
    ) -> ChangeArtifact:
        return self._record(
            attempt,
            healthy=False,
            attribution=attribution,
            reason_code=reason_code,
            evidence=evidence,
            now_epoch=now_epoch,
        )

    def _observations(
        self,
        change_id: str,
        attempt_id: str,
    ) -> tuple[ChangeArtifact, ...]:
        return tuple(
            artifact
            for artifact in self._changes.list_artifacts(
                change_id,
                kind=self._ARTIFACT_KIND,
            )
            if artifact.payload.get("attempt_id") == attempt_id
        )

    def assess(self, attempt: PromotionAttempt) -> ObservationAssessment:
        current = self._promotions.require(attempt.attempt_id)
        if current.state is not PromotionAttemptState.OBSERVING:
            raise ChangeConflict("promotion attempt is not observing")
        artifacts = self._observations(current.change_id, current.attempt_id)
        candidate = 0
        external = 0
        unknown = 0
        healthy_after_blocker = 0
        for artifact in artifacts:
            payload = artifact.payload
            if payload.get("healthy") is True:
                healthy_after_blocker += 1
                continue
            attribution = FailureAttribution(str(payload.get("attribution", "")))
            if attribution is FailureAttribution.CANDIDATE_LOCAL:
                candidate += 1
                healthy_after_blocker = 0
            elif attribution in {
                FailureAttribution.EXTERNAL_PROVIDER,
                FailureAttribution.EXTERNAL_HARDWARE,
            }:
                external += 1
            else:
                unknown += 1
                healthy_after_blocker = 0

        if candidate:
            disposition = ObservationDisposition.ROLLBACK_REQUIRED
        elif unknown:
            disposition = ObservationDisposition.BLOCKED_UNKNOWN
        elif healthy_after_blocker >= self._required_healthy_samples:
            disposition = ObservationDisposition.READY_TO_CLOSE
        else:
            disposition = ObservationDisposition.CONTINUE
        return ObservationAssessment(
            disposition=disposition,
            healthy_samples=healthy_after_blocker,
            external_failures=external,
            unknown_failures=unknown,
            candidate_failures=candidate,
        )

    def close_success(self, attempt: PromotionAttempt) -> PromotionAttempt:
        assessment = self.assess(attempt)
        if assessment.disposition is not ObservationDisposition.READY_TO_CLOSE:
            raise ChangeConflict("production observation is not ready to close")
        current = self._promotions.require(attempt.attempt_id)
        active = self._metadata.active()
        recovery = self._metadata.recovery()
        if active is None or active.promotion_attempt_id != current.attempt_id:
            raise ChangeConflict("active release does not match promotion attempt")
        if recovery is None or recovery.attempt_id != current.attempt_id:
            raise ChangeConflict("deployment recovery evidence is missing")
        self._metadata.set_lkg(active)
        self._metadata.clear_recovery()
        completed = self._promotions.transition(
            current.attempt_id,
            PromotionAttemptState.COMPLETED,
            expected_version=current.version,
        )
        change = self._changes.require(current.change_id)
        if change.state is not ChangeState.OBSERVING:
            raise ChangeConflict("EngineeringChange is not observing")
        self._changes.transition(
            change.change_id,
            ChangeState.CLOSED,
            expected_version=change.version,
        )
        return completed
