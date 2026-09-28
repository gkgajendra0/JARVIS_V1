"""Crash-safe single-active Phase-7 deployment coordinator."""

from __future__ import annotations

import time
from dataclasses import dataclass
from collections.abc import Callable\nfrom typing import Protocol

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

    def ensure_release(
        self,
        identity: RuntimeReleaseIdentity,
        *,
        timeout_seconds: float,
    ) -> None: ...


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
        runtime: RuntimeDeploymentDriver | None = None,
        prepare_release: Callable[[PromotionAttempt, ReleaseRecord], object] | None = None,
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
        self._prepare_release = prepare_release
        self._shutdown_timeout = float(shutdown_timeout_seconds)
        self._startup_timeout = float(startup_timeout_seconds)

    def _require_runtime(self) -> RuntimeDeploymentDriver:
        if self._runtime is None:
            raise DeploymentError(
                "deployment process control is owned by the supervisor"
            )
        return self._runtime

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
        normalized_schema_versions = tuple(sorted(schema_versions))
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

    def _finish_verified(
        self,
        *,
        attempt: PromotionAttempt,
        recovery: RecoveryRecord,
    ) -> DeploymentResult:
        self._metadata.set_active(recovery.candidate)
        verified = RecoveryRecord(
            recovery.deployment_id,
            recovery.attempt_id,
            RecoveryPhase.NEW_RUNTIME_VERIFIED,
            recovery.candidate,
            recovery.lkg,
        )
        self._metadata.set_recovery(verified)
        current = self._promotions.require(attempt.attempt_id)
        if current.state is PromotionAttemptState.DEPLOYING:
            current = self._promotions.transition(
                current.attempt_id,
                PromotionAttemptState.OBSERVING,
                expected_version=current.version,
            )
        elif current.state is not PromotionAttemptState.OBSERVING:
            raise DeploymentError("deployment attempt is not reconcilable")
        change = self._changes.require(current.change_id)
        if change.state is ChangeState.PROMOTED:
            self._changes.transition(
                change.change_id,
                ChangeState.OBSERVING,
                expected_version=change.version,
            )
        elif change.state is not ChangeState.OBSERVING:
            raise DeploymentError(
                "EngineeringChange is not reconcilable after deployment"
            )
        return DeploymentResult(
            recovery.deployment_id,
            recovery.candidate,
            recovery.lkg,
        )

    def resume(self, attempt: PromotionAttempt) -> DeploymentResult:
        """Resume one exact deployment from durable recovery metadata."""
        runtime = self._require_runtime()
        current = self._promotions.require(attempt.attempt_id)
        recovery = self._metadata.recovery()
        if recovery is None or recovery.attempt_id != current.attempt_id:
            raise DeploymentError("deployment recovery record is missing or stale")
        if current.state is PromotionAttemptState.OBSERVING:
            active = self._metadata.active()
            if (
                recovery.phase is not RecoveryPhase.NEW_RUNTIME_VERIFIED
                or active != recovery.candidate
            ):
                raise DeploymentError(
                    "observing deployment does not match durable active release"
                )
            return DeploymentResult(
                recovery.deployment_id,
                recovery.candidate,
                recovery.lkg,
            )
        if current.state is not PromotionAttemptState.DEPLOYING:
            raise DeploymentError("promotion attempt is not deployment-recoverable")

        if recovery.phase is RecoveryPhase.STAGED:
            if self._prepare_release is not None:
                try:
                    self._prepare_release(current, recovery.candidate)
                except DeploymentError:
                    raise
                except Exception as exc:
                    raise DeploymentError(
                        "candidate release preparation failed before runtime switch"
                    ) from exc
            runtime.stop_active(timeout_seconds=self._shutdown_timeout)
            recovery = RecoveryRecord(
                recovery.deployment_id,
                recovery.attempt_id,
                RecoveryPhase.OLD_RUNTIME_STOPPED,
                recovery.candidate,
                recovery.lkg,
            )
            self._metadata.set_recovery(recovery)

        if recovery.phase is RecoveryPhase.OLD_RUNTIME_STOPPED:
            runtime.start_release(recovery.candidate.runtime_identity())
            recovery = RecoveryRecord(
                recovery.deployment_id,
                recovery.attempt_id,
                RecoveryPhase.NEW_RUNTIME_STARTED,
                recovery.candidate,
                recovery.lkg,
            )
            self._metadata.set_recovery(recovery)

        if recovery.phase is RecoveryPhase.NEW_RUNTIME_STARTED:
            try:
                runtime.ensure_release(
                    recovery.candidate.runtime_identity(),
                    timeout_seconds=self._startup_timeout,
                )
            except Exception as exc:
                failed = RecoveryRecord(
                    recovery.deployment_id,
                    recovery.attempt_id,
                    RecoveryPhase.STARTUP_FAILED,
                    recovery.candidate,
                    recovery.lkg,
                )
                self._metadata.set_recovery(failed)
                try:
                    runtime.stop_candidate(timeout_seconds=self._shutdown_timeout)
                    runtime.start_release(recovery.lkg.runtime_identity())
                    runtime.wait_ready(
                        recovery.lkg.runtime_identity(),
                        timeout_seconds=self._startup_timeout,
                    )
                    self._metadata.set_active(recovery.lkg)
                except Exception as lkg_exc:
                    raise DeploymentError(
                        "candidate startup failed and Last Known Good could not recover"
                    ) from lkg_exc
                raise DeploymentError(
                    "candidate startup failed; Last Known Good restored pending attribution"
                ) from exc
            return self._finish_verified(attempt=current, recovery=recovery)

        if recovery.phase is RecoveryPhase.NEW_RUNTIME_VERIFIED:
            runtime.ensure_release(
                recovery.candidate.runtime_identity(),
                timeout_seconds=self._startup_timeout,
            )
            return self._finish_verified(attempt=current, recovery=recovery)

        if recovery.phase is RecoveryPhase.STARTUP_FAILED:
            raise DeploymentError(
                "candidate startup previously failed; rollback decision required"
            )
        raise DeploymentError(
            f"deployment phase {recovery.phase.value} belongs to rollback recovery"
        )

    def prepare(
        self,
        *,
        evidence: PromotionEvidenceV1,
        attempt: PromotionAttempt,
        schema_versions: tuple[tuple[str, int], ...] = (),
        now_epoch: float | None = None,
    ) -> PromotionAttempt:
        """Persist the exact deployment handoff without controlling the runtime."""
        current = self._promotions.require(attempt.attempt_id)
        if current.change_id != evidence.change_id:
            raise DeploymentError("deployment evidence belongs to another change")
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

        if current.state is PromotionAttemptState.DEPLOYING:
            recovery = self._metadata.recovery()
            if (
                recovery is None
                or recovery.attempt_id != current.attempt_id
                or recovery.candidate.release_sha != current.merge_sha
                or recovery.candidate.promotion_evidence_digest != evidence.digest
                or recovery.lkg.release_sha != lkg.release_sha
            ):
                raise DeploymentError(
                    "existing deployment handoff does not match current evidence"
                )
            return current

        if current.state is not PromotionAttemptState.MERGED:
            raise DeploymentError("promotion attempt must be merged before deployment")
        if current.merge_sha is None:
            raise DeploymentError("merged promotion attempt has no merge SHA")

        existing_recovery = self._metadata.recovery()
        if (
            existing_recovery is not None
            and existing_recovery.attempt_id != current.attempt_id
        ):
            raise DeploymentError("another deployment recovery is still active")

        release_root = self._stager.stage(current.merge_sha)
        accepted_at = time.time() if now_epoch is None else float(now_epoch)
        candidate = ReleaseRecord(
            release_sha=current.merge_sha,
            release_root=str(release_root),
            promotion_attempt_id=current.attempt_id,
            promotion_evidence_digest=evidence.digest,
            config_digest=evidence.config_digest,
            schema_versions=normalized_schema_versions,
            accepted_at_epoch=accepted_at,
        )
        identifier = deployment_id(
            attempt_id=current.attempt_id,
            merge_sha=current.merge_sha,
            evidence_digest=evidence.digest,
        )
        recovery = RecoveryRecord(
            deployment_id=identifier,
            attempt_id=current.attempt_id,
            phase=RecoveryPhase.STAGED,
            candidate=candidate,
            lkg=lkg,
        )
        self._metadata.set_recovery(recovery)
        return self._promotions.transition(
            current.attempt_id,
            PromotionAttemptState.DEPLOYING,
            expected_version=current.version,
            deployment_id=identifier,
            lkg_sha=lkg.release_sha,
        )

    def deploy(
        self,
        *,
        evidence: PromotionEvidenceV1,
        attempt: PromotionAttempt,
        schema_versions: tuple[tuple[str, int], ...] = (),
        now_epoch: float | None = None,
    ) -> DeploymentResult:
        prepared = self.prepare(
            evidence=evidence,
            attempt=attempt,
            schema_versions=schema_versions,
            now_epoch=now_epoch,
        )
        return self.resume(prepared)
