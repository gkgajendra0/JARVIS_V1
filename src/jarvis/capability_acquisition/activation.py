"""Owner-turn Phase-9 activation/disable coordinator over Phase-8 lifecycle Authority."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.capability_acquisition.promotion import (
    ensure_capability_release_bridge_current,
)
from jarvis.capability_registry.authority import CapabilityLifecycleAuthoritySource
from jarvis.capability_registry.lifecycle import (
    CapabilityLifecycleMutationResult,
    CapabilityLifecycleService,
)
from jarvis.engineering_change.models import ChangeArtifact, ChangeConflict
from jarvis.engineering_change.store import ChangeStore
from jarvis.promotion.release import DeploymentMetadataStore


class CapabilityAcquisitionLifecycleError(ChangeConflict):
    pass


@dataclass(frozen=True, slots=True)
class CapabilityAcquisitionLifecycleResult:
    capability_id: str
    package_id: str
    package_version: str
    package_digest: str
    selected: CapabilityLifecycleMutationResult | None
    enabled: CapabilityLifecycleMutationResult | None
    disabled: CapabilityLifecycleMutationResult | None
    artifact: ChangeArtifact


class CapabilityAcquisitionLifecycleCoordinator:
    """Apply only the exact admitted Phase-9 package through Phase-8 Authority."""

    def __init__(
        self,
        changes: ChangeStore,
        deployment: DeploymentMetadataStore,
        lifecycle: CapabilityLifecycleService,
    ) -> None:
        if not isinstance(changes, ChangeStore):
            raise TypeError("changes must be ChangeStore")
        if not isinstance(deployment, DeploymentMetadataStore):
            raise TypeError("deployment must be DeploymentMetadataStore")
        if not isinstance(lifecycle, CapabilityLifecycleService):
            raise TypeError("lifecycle must be CapabilityLifecycleService")
        self._changes = changes
        self._deployment = deployment
        self._lifecycle = lifecycle

    @staticmethod
    def _persist_if_changed(
        store: ChangeStore,
        *,
        change_id: str,
        kind: str,
        payload: dict[str, object],
    ) -> ChangeArtifact:
        latest = store.latest_artifact(change_id, kind)
        if latest is not None and latest.payload == payload:
            return latest
        return store.add_artifact(change_id, kind=kind, payload=payload)

    def _binding(self, change_id: str) -> tuple[ChangeArtifact, ChangeArtifact]:
        candidate = self._changes.latest_artifact(change_id, "capability_candidate")
        admission = self._changes.latest_artifact(
            change_id,
            "capability_package_admission",
        )
        if candidate is None or admission is None:
            raise CapabilityAcquisitionLifecycleError(
                "Phase-9 lifecycle requires candidate and package admission evidence"
            )
        architecture = self._changes.latest_artifact(change_id, "architecture")
        if (
            architecture is None
            or candidate.payload.get("architecture_artifact_id")
            != architecture.artifact_id
            or candidate.payload.get("architecture_digest") != architecture.digest
        ):
            raise CapabilityAcquisitionLifecycleError(
                "Phase-9 candidate is not bound to the current acquisition architecture"
            )
        attempt_id = str(admission.payload.get("attempt_id") or "").strip()
        ensure_capability_release_bridge_current(
            self._changes,
            self._deployment,
            change_id,
            attempt_id=attempt_id,
        )
        return candidate, admission

    @staticmethod
    def _identity(candidate: ChangeArtifact) -> tuple[str, str, str, str]:
        capability_id = (
            str(candidate.payload.get("capability_id") or "").strip().casefold()
        )
        package_id = str(candidate.payload.get("package_id") or "").strip().casefold()
        package_version = str(candidate.payload.get("package_version") or "").strip()
        package_digest = (
            str(candidate.payload.get("package_digest") or "").strip().casefold()
        )
        if not all((capability_id, package_id, package_version, package_digest)):
            raise CapabilityAcquisitionLifecycleError(
                "Phase-9 candidate package identity is incomplete"
            )
        return capability_id, package_id, package_version, package_digest

    @staticmethod
    def _source(
        *,
        authority_session_id: str,
        source_turn_id: str,
    ) -> CapabilityLifecycleAuthoritySource:
        return CapabilityLifecycleAuthoritySource.owner_turn(
            session_id=str(authority_session_id).strip(),
            turn_id=str(source_turn_id).strip(),
        )

    def activate(
        self,
        change_id: str,
        *,
        authority_session_id: str,
        source_turn_id: str,
    ) -> CapabilityAcquisitionLifecycleResult:
        candidate, admission = self._binding(change_id)
        capability_id, package_id, package_version, package_digest = self._identity(
            candidate
        )
        source = self._source(
            authority_session_id=authority_session_id,
            source_turn_id=source_turn_id,
        )
        current = self._lifecycle.store.require_registry(capability_id)
        selected_result: CapabilityLifecycleMutationResult | None = None
        if (
            current.selected_package_id != package_id
            or current.selected_package_version != package_version
            or current.selected_package_digest != package_digest
        ):
            selected_result = self._lifecycle.select_version(
                capability_id,
                package_id=package_id,
                package_version=package_version,
                expected_generation=current.generation,
                authority_session_id=authority_session_id,
                source=source,
            )
            current = selected_result.current_state

        enabled_result = self._lifecycle.enable(
            capability_id,
            expected_generation=current.generation,
            authority_session_id=authority_session_id,
            source=source,
        )
        effective = enabled_result.snapshot.state(capability_id)
        if effective is None or not effective.effective_enabled:
            raise CapabilityAcquisitionLifecycleError(
                "Phase-8 lifecycle did not make acquired capability effective"
            )
        payload = {
            "schema": "capability_acquisition_activation.v1",
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "admission_artifact_id": admission.artifact_id,
            "admission_artifact_digest": admission.digest,
            "capability_id": capability_id,
            "package_id": package_id,
            "package_version": package_version,
            "package_digest": package_digest,
            "registry_generation": enabled_result.current_state.generation,
            "snapshot_digest": enabled_result.snapshot.digest,
            "effective_enabled": True,
            "authority_session_id": str(authority_session_id).strip(),
            "source_turn_id": str(source_turn_id).strip(),
        }
        artifact = self._persist_if_changed(
            self._changes,
            change_id=change_id,
            kind="capability_lifecycle_activation",
            payload=payload,
        )
        return CapabilityAcquisitionLifecycleResult(
            capability_id=capability_id,
            package_id=package_id,
            package_version=package_version,
            package_digest=package_digest,
            selected=selected_result,
            enabled=enabled_result,
            disabled=None,
            artifact=artifact,
        )

    def disable(
        self,
        change_id: str,
        *,
        authority_session_id: str,
        source_turn_id: str,
    ) -> CapabilityAcquisitionLifecycleResult:
        candidate, admission = self._binding(change_id)
        capability_id, package_id, package_version, package_digest = self._identity(
            candidate
        )
        source = self._source(
            authority_session_id=authority_session_id,
            source_turn_id=source_turn_id,
        )
        current = self._lifecycle.store.require_registry(capability_id)
        disabled_result = self._lifecycle.disable(
            capability_id,
            expected_generation=current.generation,
            authority_session_id=authority_session_id,
            source=source,
        )
        effective = disabled_result.snapshot.state(capability_id)
        if effective is not None and effective.effective_enabled:
            raise CapabilityAcquisitionLifecycleError(
                "Phase-8 lifecycle disable remained effectively enabled"
            )
        payload = {
            "schema": "capability_acquisition_disable.v1",
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "admission_artifact_id": admission.artifact_id,
            "admission_artifact_digest": admission.digest,
            "capability_id": capability_id,
            "package_id": package_id,
            "package_version": package_version,
            "package_digest": package_digest,
            "registry_generation": disabled_result.current_state.generation,
            "snapshot_digest": disabled_result.snapshot.digest,
            "effective_enabled": False,
            "authority_session_id": str(authority_session_id).strip(),
            "source_turn_id": str(source_turn_id).strip(),
        }
        artifact = self._persist_if_changed(
            self._changes,
            change_id=change_id,
            kind="capability_lifecycle_disable",
            payload=payload,
        )
        return CapabilityAcquisitionLifecycleResult(
            capability_id=capability_id,
            package_id=package_id,
            package_version=package_version,
            package_digest=package_digest,
            selected=None,
            enabled=None,
            disabled=disabled_result,
            artifact=artifact,
        )
