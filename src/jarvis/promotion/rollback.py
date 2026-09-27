"""Bounded compatibility-safe rollback to exact Last Known Good."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.engineering_change.models import ChangeConflict, ChangeState
from jarvis.engineering_change.store import ChangeStore

from .deployment import RuntimeDeploymentDriver
from .models import PromotionAttempt, PromotionAttemptState, PromotionEvidenceV1
from .observation import FailureAttribution
from .release import (
    DeploymentMetadataStore,
    RecoveryPhase,
    RecoveryRecord,
    ReleaseRecord,
)
from .store import PromotionStore


class RollbackError(ChangeConflict):
    pass


@dataclass(frozen=True, slots=True)
class RollbackResult:
    restored: ReleaseRecord
    already_reconciled: bool


class RollbackCoordinator:
    """Allow at most one deterministic rollback encoded by the recovery record."""

    def __init__(
        self,
        changes: ChangeStore,
        promotions: PromotionStore,
        *,
        metadata: DeploymentMetadataStore,
        runtime: RuntimeDeploymentDriver,
        shutdown_timeout_seconds: float = 15.0,
        startup_timeout_seconds: float = 60.0,
    ) -> None:
        if promotions.changes is not changes:
            raise ValueError("promotion store must share the canonical ChangeStore")
        self._changes = changes
        self._promotions = promotions
        self._metadata = metadata
        self._runtime = runtime
        self._shutdown_timeout = float(shutdown_timeout_seconds)
        self._startup_timeout = float(startup_timeout_seconds)

    @staticmethod
    def _rollback_compatible(
        candidate: ReleaseRecord,
        lkg: ReleaseRecord,
        evidence: PromotionEvidenceV1,
    ) -> bool:
        return (
            evidence.compatibility.ordinary_path_safe
            and candidate.schema_versions == lkg.schema_versions
        )

    def rollback(
        self,
        *,
        evidence: PromotionEvidenceV1,
        attempt: PromotionAttempt,
        attribution: FailureAttribution,
    ) -> RollbackResult:
        if attribution is not FailureAttribution.CANDIDATE_LOCAL:
            raise RollbackError(
                "automatic rollback requires deterministic candidate-local failure"
            )
        current = self._promotions.require(attempt.attempt_id)
        if current.state is PromotionAttemptState.ROLLED_BACK:
            active = self._metadata.active()
            if active is None or active.release_sha != current.lkg_sha:
                raise RollbackError("rolled-back state does not match active LKG")
            return RollbackResult(active, True)
        if current.state not in {
            PromotionAttemptState.DEPLOYING,
            PromotionAttemptState.OBSERVING,
        }:
            raise RollbackError("promotion attempt is not rollback eligible")

        recovery = self._metadata.recovery()
        if recovery is None or recovery.attempt_id != current.attempt_id:
            raise RollbackError("deployment recovery record is missing or stale")
        if recovery.phase in {
            RecoveryPhase.ROLLBACK_STARTED,
            RecoveryPhase.ROLLBACK_VERIFIED,
        }:
            if recovery.phase is RecoveryPhase.ROLLBACK_VERIFIED:
                active = self._metadata.active()
                if active != recovery.lkg:
                    raise RollbackError(
                        "rollback metadata disagrees with active release"
                    )
                return RollbackResult(recovery.lkg, True)
            raise RollbackError(
                "rollback already started; restart reconciliation is required"
            )
        if current.lkg_sha != recovery.lkg.release_sha:
            raise RollbackError("promotion attempt Last Known Good identity changed")
        if evidence.lkg_release_sha != recovery.lkg.release_sha:
            raise RollbackError("approved evidence Last Known Good identity changed")
        if not self._rollback_compatible(
            recovery.candidate,
            recovery.lkg,
            evidence,
        ):
            raise RollbackError("automatic rollback is not data/schema compatible")

        started = RecoveryRecord(
            recovery.deployment_id,
            recovery.attempt_id,
            RecoveryPhase.ROLLBACK_STARTED,
            recovery.candidate,
            recovery.lkg,
        )
        self._metadata.set_recovery(started)
        self._runtime.stop_candidate(timeout_seconds=self._shutdown_timeout)
        self._runtime.start_release(recovery.lkg.runtime_identity())
        self._runtime.wait_ready(
            recovery.lkg.runtime_identity(),
            timeout_seconds=self._startup_timeout,
        )
        self._metadata.set_active(recovery.lkg)
        verified = RecoveryRecord(
            recovery.deployment_id,
            recovery.attempt_id,
            RecoveryPhase.ROLLBACK_VERIFIED,
            recovery.candidate,
            recovery.lkg,
        )
        self._metadata.set_recovery(verified)

        self._promotions.transition(
            current.attempt_id,
            PromotionAttemptState.ROLLED_BACK,
            expected_version=current.version,
            reason="deterministic candidate-local production regression",
        )
        change = self._changes.require(current.change_id)
        if change.state not in {ChangeState.PROMOTED, ChangeState.OBSERVING}:
            raise RollbackError("EngineeringChange is not rollback eligible")
        self._changes.transition(
            change.change_id,
            ChangeState.ROLLED_BACK,
            expected_version=change.version,
        )
        return RollbackResult(recovery.lkg, False)
