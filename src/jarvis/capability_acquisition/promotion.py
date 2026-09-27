"""Phase-9 bridge from Phase-7 active release to Phase-8 package truth."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.verification import (
    ensure_capability_candidate_acceptance_current,
)
from jarvis.capability_registry.admission import (
    CapabilityPackageAdmissionResult,
    CapabilityPackageAdmissionService,
)
from jarvis.capability_registry.compatibility import CompatibilityVerdict
from jarvis.capability_registry.models import (
    CapabilityRegistryState,
    DesiredActivationState,
    PackageDisposition,
)
from jarvis.capability_registry.reconciliation import (
    CapabilityLifecycleReconciler,
    ReconciliationTrigger,
)
from jarvis.engineering_change.models import ChangeArtifact, ChangeConflict, ChangeState
from jarvis.engineering_change.store import ChangeStore
from jarvis.promotion.models import PromotionAttempt, PromotionAttemptState
from jarvis.promotion.release import DeploymentMetadataStore
from jarvis.promotion.store import PromotionStore
from jarvis.work.models import WorkDeliveryKind


class CapabilityAcquisitionReleaseBridgeError(ChangeConflict):
    """Promoted Phase-9 source cannot safely become Phase-8 package truth."""

    def __init__(self, reason_code: str, message: str) -> None:
        code = str(reason_code).strip().casefold()
        text = str(message).strip()
        if not code or not text:
            raise ValueError("release bridge failure requires code and message")
        super().__init__(text)
        self.reason_code = code


@dataclass(frozen=True, slots=True)
class CapabilityLifecycleProposalV1:
    capability_id: str
    package_id: str
    package_version: str
    package_digest: str
    compatibility_digest: str
    expected_generation: int
    proposed_actions: tuple[str, ...]
    authority_required: bool = True

    def payload(self) -> dict[str, object]:
        return {
            "schema": "capability_lifecycle_proposal.v1",
            "capability_id": self.capability_id,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "package_digest": self.package_digest,
            "compatibility_digest": self.compatibility_digest,
            "expected_generation": self.expected_generation,
            "proposed_actions": list(self.proposed_actions),
            "authority_required": self.authority_required,
        }


@dataclass(frozen=True, slots=True)
class CapabilityAcquisitionReleaseBridgeResult:
    admission: CapabilityPackageAdmissionResult
    admission_artifact: ChangeArtifact
    lifecycle_proposal: CapabilityLifecycleProposalV1
    lifecycle_artifact: ChangeArtifact


def _registry_payload(
    state: CapabilityRegistryState | None,
) -> dict[str, object] | None:
    if state is None:
        return None
    return {
        "capability_id": state.capability_id,
        "selected_package_id": state.selected_package_id,
        "selected_package_version": state.selected_package_version,
        "selected_package_digest": state.selected_package_digest,
        "desired_state": state.desired_state.value,
        "generation": state.generation,
        "updated_at": state.updated_at,
    }


class CapabilityAcquisitionReleaseBridge:
    """Admit exact promoted package, prove no auto-activation, propose lifecycle only."""

    def __init__(
        self,
        changes: ChangeStore,
        promotions: PromotionStore,
        deployment: DeploymentMetadataStore,
        *,
        admission: CapabilityPackageAdmissionService,
        reconciler: CapabilityLifecycleReconciler,
    ) -> None:
        if promotions.changes is not changes:
            raise ValueError("promotion store must share canonical ChangeStore")
        if admission.store is not reconciler.store:
            raise ValueError("admission and reconciler must share registry store")
        if admission.evaluator is not reconciler.evaluator:
            raise ValueError(
                "admission and reconciler must share compatibility evaluator"
            )
        if admission.package_source is not reconciler.evaluator.package_source:
            raise ValueError("admission and reconciler must share package source")
        self._changes = changes
        self._promotions = promotions
        self._deployment = deployment
        self._admission = admission
        self._reconciler = reconciler

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

    def _attempt(
        self,
        change_id: str,
        attempt_id: str,
    ) -> PromotionAttempt:
        attempt = self._promotions.require(str(attempt_id).strip())
        if attempt.change_id != change_id:
            raise CapabilityAcquisitionReleaseBridgeError(
                "promotion_change_mismatch",
                "promotion attempt belongs to another EngineeringChange",
            )
        if attempt.state not in {
            PromotionAttemptState.OBSERVING,
            PromotionAttemptState.COMPLETED,
        }:
            raise CapabilityAcquisitionReleaseBridgeError(
                "promotion_not_deployed",
                "Phase-9 package admission requires deployed/observing promotion",
            )
        if attempt.merge_sha is None:
            raise CapabilityAcquisitionReleaseBridgeError(
                "promotion_merge_missing",
                "deployed promotion has no exact merge SHA",
            )
        return attempt

    def reconcile(
        self,
        change_id: str,
        *,
        attempt_id: str,
    ) -> CapabilityAcquisitionReleaseBridgeResult:
        change = self._changes.require(change_id)
        if (
            change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
            or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
        ):
            raise CapabilityAcquisitionReleaseBridgeError(
                "wrong_process",
                "release bridge only accepts owner_capability_acquisition.v1",
            )
        if change.state not in {ChangeState.OBSERVING, ChangeState.CLOSED}:
            raise CapabilityAcquisitionReleaseBridgeError(
                "change_not_observing",
                "Phase-9 package bridge requires deployed EngineeringChange",
            )
        ensure_capability_candidate_acceptance_current(self._changes, change_id)
        candidate = self._changes.latest_artifact(change_id, "capability_candidate")
        if candidate is None:
            raise CapabilityAcquisitionReleaseBridgeError(
                "candidate_missing",
                "current Phase-9 capability candidate is missing",
            )

        attempt = self._attempt(change_id, attempt_id)
        if (
            attempt.candidate_artifact_id != candidate.artifact_id
            or attempt.candidate_artifact_digest != candidate.digest
        ):
            raise CapabilityAcquisitionReleaseBridgeError(
                "promotion_candidate_stale",
                "deployed promotion attempt is not bound to current Phase-9 candidate",
            )
        active = self._deployment.active()
        if (
            active is None
            or active.promotion_attempt_id != attempt.attempt_id
            or active.release_sha != attempt.merge_sha
        ):
            raise CapabilityAcquisitionReleaseBridgeError(
                "active_release_mismatch",
                "Phase-7 active release does not match deployed promotion attempt",
            )
        if self._admission.package_source.release_sha != active.release_sha:
            raise CapabilityAcquisitionReleaseBridgeError(
                "package_source_release_mismatch",
                "Phase-8 package source is not bound to active Phase-7 release",
            )

        package_id = str(candidate.payload.get("package_id") or "").strip().casefold()
        package_version = str(candidate.payload.get("package_version") or "").strip()
        package_digest = str(candidate.payload.get("package_digest") or "").strip()
        capability_id = (
            str(candidate.payload.get("capability_id") or "").strip().casefold()
        )
        package_path = str(candidate.payload.get("package_path") or "").strip()
        if not all(
            (package_id, package_version, package_digest, capability_id, package_path)
        ):
            raise CapabilityAcquisitionReleaseBridgeError(
                "candidate_package_binding_missing",
                "Phase-9 candidate lacks exact package identity evidence",
            )

        sourced = next(
            (
                item
                for item in self._admission.package_source.packages()
                if item.package.package_id == package_id
                and item.package.package_version == package_version
            ),
            None,
        )
        if sourced is None:
            raise CapabilityAcquisitionReleaseBridgeError(
                "package_not_in_active_release",
                "approved capability package is absent from exact active release",
            )
        if (
            sourced.relative_path != package_path
            or sourced.package_digest != package_digest
            or sourced.package.capability_id != capability_id
        ):
            raise CapabilityAcquisitionReleaseBridgeError(
                "promoted_package_mismatch",
                "active-release package differs from verified Phase-9 candidate",
            )

        registry_store = self._admission.store
        before = registry_store.get_registry(capability_id)
        result = self._admission.admit(sourced)
        after = registry_store.require_registry(capability_id)

        if (
            result.admitted.disposition is not PackageDisposition.AVAILABLE
            or result.compatibility.verdict is not CompatibilityVerdict.READY
        ):
            raise CapabilityAcquisitionReleaseBridgeError(
                "package_not_ready",
                "promoted capability package did not pass Phase-8 compatibility",
            )

        if before is None:
            if (
                after.desired_state is not DesiredActivationState.DISABLED
                or after.has_selection
            ):
                raise CapabilityAcquisitionReleaseBridgeError(
                    "admission_auto_activated",
                    "new capability admission changed lifecycle state unexpectedly",
                )
        elif (
            before.selected_package_id != after.selected_package_id
            or before.selected_package_version != after.selected_package_version
            or before.selected_package_digest != after.selected_package_digest
            or before.desired_state is not after.desired_state
            or before.generation != after.generation
        ):
            raise CapabilityAcquisitionReleaseBridgeError(
                "admission_mutated_lifecycle",
                "package admission changed existing lifecycle state",
            )

        snapshot = self._reconciler.reconcile(ReconciliationTrigger.ADMISSION)
        effective = snapshot.state(capability_id)
        if before is None and (effective is None or effective.effective_enabled):
            raise CapabilityAcquisitionReleaseBridgeError(
                "admission_effectively_enabled",
                "new package became executable without lifecycle Authority",
            )

        proposed_actions: list[str] = []
        if not (
            after.selected_package_id == package_id
            and after.selected_package_version == package_version
            and after.selected_package_digest == package_digest
        ):
            proposed_actions.append("select_version")
        if after.desired_state is not DesiredActivationState.ENABLED:
            proposed_actions.append("enable")

        proposal = CapabilityLifecycleProposalV1(
            capability_id=capability_id,
            package_id=package_id,
            package_version=package_version,
            package_digest=package_digest,
            compatibility_digest=result.compatibility.digest,
            expected_generation=after.generation,
            proposed_actions=tuple(proposed_actions),
        )
        admission_payload = {
            "schema": "capability_acquisition_release_admission.v1",
            "attempt_id": attempt.attempt_id,
            "active_release_sha": active.release_sha,
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "candidate_id": candidate.payload.get("candidate_id"),
            "candidate_digest": candidate.payload.get("digest"),
            "package_path": sourced.relative_path,
            "package_id": package_id,
            "package_version": package_version,
            "package_digest": package_digest,
            "capability_id": capability_id,
            "compatibility_verdict": result.compatibility.verdict.value,
            "compatibility_digest": result.compatibility.digest,
            "compatibility_reason_codes": list(result.compatibility.reason_codes),
            "registry_before": _registry_payload(before),
            "registry_after": _registry_payload(after),
            "snapshot_digest": snapshot.digest,
            "effective_enabled_after_admission": (
                False if effective is None else effective.effective_enabled
            ),
            "auto_activated": False,
        }
        admission_artifact = self._persist_if_changed(
            self._changes,
            change_id=change_id,
            kind="capability_package_admission",
            payload=admission_payload,
        )
        lifecycle_artifact = self._persist_if_changed(
            self._changes,
            change_id=change_id,
            kind="capability_lifecycle_proposal",
            payload={
                **proposal.payload(),
                "admission_artifact_id": admission_artifact.artifact_id,
                "admission_artifact_digest": admission_artifact.digest,
            },
        )

        development_work_id = str(
            candidate.payload.get("development_work_id") or ""
        ).strip()
        if not development_work_id:
            raise CapabilityAcquisitionReleaseBridgeError(
                "development_work_missing",
                "Phase-9 candidate has no canonical development WorkItem",
            )
        development_work = self._changes.work.require(development_work_id)
        self._changes.work.enqueue_delivery(
            work=development_work,
            kind=WorkDeliveryKind.OWNER_INPUT,
            message=(
                f"Capability acquisition {change_id} is deployed and package "
                f"{package_id}@{package_version} passed Phase-8 admission. It remains "
                f"disabled by design. Lifecycle proposal SHA-256: "
                f"{lifecycle_artifact.digest}. Explicit owner activation is required. "
                f"Say 'activate acquired capability {change_id}' to continue, or leave "
                f"it disabled."
            ),
            event_key=(f"phase9-lifecycle:{change_id}:{lifecycle_artifact.digest}"),
        )
        return CapabilityAcquisitionReleaseBridgeResult(
            admission=result,
            admission_artifact=admission_artifact,
            lifecycle_proposal=proposal,
            lifecycle_artifact=lifecycle_artifact,
        )


def ensure_capability_release_bridge_current(
    changes: ChangeStore,
    deployment: DeploymentMetadataStore,
    change_id: str,
    *,
    attempt_id: str,
) -> ChangeArtifact:
    """Require exact active-release Phase-8 admission before Phase-7 close."""

    change = changes.require(change_id)
    if (
        change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
        or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
    ):
        raise CapabilityAcquisitionReleaseBridgeError(
            "wrong_process",
            "change is not Phase-9 capability acquisition",
        )
    candidate = changes.latest_artifact(change_id, "capability_candidate")
    admission = changes.latest_artifact(change_id, "capability_package_admission")
    lifecycle = changes.latest_artifact(change_id, "capability_lifecycle_proposal")
    if candidate is None or admission is None or lifecycle is None:
        raise CapabilityAcquisitionReleaseBridgeError(
            "release_bridge_evidence_missing",
            "Phase-9 close requires package admission and lifecycle proposal evidence",
        )
    active = deployment.active()
    if active is None or active.promotion_attempt_id != str(attempt_id).strip():
        raise CapabilityAcquisitionReleaseBridgeError(
            "active_release_mismatch",
            "current active release does not match Phase-9 promotion attempt",
        )
    if (
        admission.payload.get("attempt_id") != active.promotion_attempt_id
        or admission.payload.get("active_release_sha") != active.release_sha
        or admission.payload.get("candidate_artifact_id") != candidate.artifact_id
        or admission.payload.get("candidate_artifact_digest") != candidate.digest
        or admission.payload.get("auto_activated") is not False
    ):
        raise CapabilityAcquisitionReleaseBridgeError(
            "release_bridge_evidence_stale",
            "Phase-9 package admission evidence is stale or unsafe",
        )
    if (
        lifecycle.payload.get("admission_artifact_id") != admission.artifact_id
        or lifecycle.payload.get("admission_artifact_digest") != admission.digest
        or lifecycle.payload.get("authority_required") is not True
    ):
        raise CapabilityAcquisitionReleaseBridgeError(
            "lifecycle_proposal_stale",
            "Phase-9 lifecycle proposal is stale or bypasses Authority",
        )
    return admission
