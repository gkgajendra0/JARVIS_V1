"""Crash-safe single-active Phase-7 deployment coordinator."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from jarvis.dev_control import RuntimeReleaseIdentity
from jarvis.engineering_change.models import ChangeConflict, ChangeState
from jarvis.engineering_change.store import ChangeStore

from jarvis.engineering_substrate.canonical import canonical_digest

from .models import PromotionAttempt, PromotionAttemptState, PromotionEvidenceV1
from .release import (
    DeploymentMetadataStore,
    GitReleaseStager,
    RecoveryPhase,
    RecoveryRecord,
    ReleaseRecord,
    deployment_id,
)
from .store import PromotionStore


class DeploymentError(ChangeConflict):
    pass


class RuntimeDeploymentDriver(Protocol):
    """Supervisor-owned runtime switch boundary; never implemented by the model."""

    def stop_active(self, *, timeout_seconds: float) -> None: ...

    def start_release(self, identity: RuntimeReleaseIdentity) -> None: ...

    def wait_ready(
        self,
        identity: RuntimeReleaseIdentity,
        *,
        timeout_seconds: float,
    ) -> None: ...

    def stop_candidate(self, *, timeout_seconds: float) -> None: ...


@dataclass(frozen=True, slots=True)
class DeploymentResult:
    deployment_id: str
    release: ReleaseRecord
    lkg: ReleaseRecord


class DeploymentCoordinator:
    """Stage exact merged source then switch one runtime under durable recovery state."""

    def __init__(
        self,
        changes: ChangeStore,
        promotions: PromotionStore,
        *,
        stager: GitReleaseStager,
        metadata: DeploymentMetadataStore,
        runtime: RuntimeDeploymentDriver,
        shutdown_timeout_seconds: float = 15.0,
        startup_timeout_seconds: float = 60.0,
    ) -> None:
        if promotions.changes is not changes:
            raise ValueError("promotion store must share the canonical ChangeStore")
        if shutdown_timeout_seconds <= 0 or startup_timeout_seconds <= 0:
            raise ValueError("deployment timeouts must be positive")
        self._changes = changes
        self._promotions = promotions
        self._stager = stager
        self._metadata = metadata
        self._runtime = runtime
        self._shutdown_timeout = float(shutdown_timeout_seconds)
        self._startup_timeout = float(startup_timeout_seconds)

    def bootstrap_lkg(
        self,
        *,
        release_sha: str,
        config_digest: str,
        schema_versions: tuple[tuple[str, int], ...] = (),
        verified: bool,
        now_epoch: float | None = None,
    ) -> ReleaseRecord:
        """Adopt one already-accepted production revision as initial Phase-7 LKG."""
        if verified is not True:
            raise DeploymentError(
                "initial LKG requires independent runtime verification"
            )
        existing = self._metadata.lkg()
        if existing is not None:
            if existing.release_sha != release_sha:
                raise DeploymentError(
                    "Last Known Good is already initialized differently"
                )
            return existing
        release_root = self._stager.stage(release_sha)
        accepted_at = time.time() if now_epoch is None else float(now_epoch)
        bootstrap_digest = canonical_digest(
            {
                "kind": "phase7_lkg_bootstrap",
                "release_sha": release_sha,
                "config_digest": config_digest,
                "schema_versions": {
                    name: version for name, version in sorted(schema_versions)
                },
            }
        )
        record = ReleaseRecord(
            release_sha=release_sha,
            release_root=str(release_root),
            promotion_attempt_id=f"promotion_bootstrap_{release_sha[:16]}",
            promotion_evidence_digest=bootstrap_digest,
            config_digest=config_digest,
            schema_versions=normalized_schema_versions,
            accepted_at_epoch=accepted_at,
        )
        self._metadata.set_lkg(record)
        self._metadata.set_active(record)
        return record

    def deploy(
        self,
        *,
        evidence: PromotionEvidenceV1,
        attempt: PromotionAttempt,
        schema_versions: tuple[tuple[str, int], ...] = (),
        now_epoch: float | None = None,
    ) -> DeploymentResult:
        if attempt.change_id != evidence.change_id:
            raise DeploymentError("deployment evidence belongs to another change")
        if attempt.state is not PromotionAttemptState.MERGED:
            raise DeploymentError("promotion attempt must be merged before deployment")
        if attempt.merge_sha is None:
            raise DeploymentError("merged promotion attempt has no merge SHA")
        if not evidence.compatibility.ordinary_path_safe:
            raise DeploymentError(
                "ordinary deployment requires SAFE compatibility evidence"
            )

        lkg = self._metadata.lkg()
        if lkg is None:
            raise DeploymentError(
                "deployment requires a verified Last Known Good release"
            )
        if lkg.release_sha != evidence.lkg_release_sha:
            raise DeploymentError(
                "approved promotion evidence no longer matches Last Known Good"
            )

        normalized_schema_versions = tuple(sorted(schema_versions))
        if normalized_schema_versions != lkg.schema_versions:
            raise DeploymentError(
                "ordinary deployment cannot change durable schema versions"
            )
        release_root = self._stager.stage(attempt.merge_sha)
        accepted_at = time.time() if now_epoch is None else float(now_epoch)
        candidate = ReleaseRecord(
            release_sha=attempt.merge_sha,
            release_root=str(release_root),
            promotion_attempt_id=attempt.attempt_id,
            promotion_evidence_digest=evidence.digest,
            config_digest=evidence.config_digest,
            schema_versions=tuple(sorted(schema_versions)),
            accepted_at_epoch=accepted_at,
        )
        identifier = deployment_id(
            attempt_id=attempt.attempt_id,
            merge_sha=attempt.merge_sha,
            evidence_digest=evidence.digest,
        )
        recovery = RecoveryRecord(
            deployment_id=identifier,
            attempt_id=attempt.attempt_id,
            phase=RecoveryPhase.STAGED,
            candidate=candidate,
            lkg=lkg,
        )
        self._metadata.set_recovery(recovery)
        attempt = self._promotions.transition(
            attempt.attempt_id,
            PromotionAttemptState.DEPLOYING,
            expected_version=attempt.version,
            deployment_id=identifier,
            lkg_sha=lkg.release_sha,
        )

        self._runtime.stop_active(timeout_seconds=self._shutdown_timeout)
        recovery = RecoveryRecord(
            identifier,
            attempt.attempt_id,
            RecoveryPhase.OLD_RUNTIME_STOPPED,
            candidate,
            lkg,
        )
        self._metadata.set_recovery(recovery)

        try:
            self._runtime.start_release(candidate.runtime_identity())
            recovery = RecoveryRecord(
                identifier,
                attempt.attempt_id,
                RecoveryPhase.NEW_RUNTIME_STARTED,
                candidate,
                lkg,
            )
            self._metadata.set_recovery(recovery)
            self._runtime.wait_ready(
                candidate.runtime_identity(),
                timeout_seconds=self._startup_timeout,
            )
        except Exception:
            recovery = RecoveryRecord(
                identifier,
                attempt.attempt_id,
                RecoveryPhase.STARTUP_FAILED,
                candidate,
                lkg,
            )
            self._metadata.set_recovery(recovery)
            raise

        self._metadata.set_active(candidate)
        recovery = RecoveryRecord(
            identifier,
            attempt.attempt_id,
            RecoveryPhase.NEW_RUNTIME_VERIFIED,
            candidate,
            lkg,
        )
        self._metadata.set_recovery(recovery)
        self._promotions.transition(
            attempt.attempt_id,
            PromotionAttemptState.OBSERVING,
            expected_version=attempt.version,
        )
        change = self._changes.require(attempt.change_id)
        if change.state is not ChangeState.PROMOTED:
            raise DeploymentError(
                "EngineeringChange is not PROMOTED at deployment verification"
            )
        self._changes.transition(
            change.change_id,
            ChangeState.OBSERVING,
            expected_version=change.version,
        )
        return DeploymentResult(identifier, candidate, lkg)
