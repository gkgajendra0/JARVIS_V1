"""Read-only exact lineage verification for Phase-9 capability acquisition.

This module owns no lifecycle state. It projects and validates canonical evidence
already persisted by GICC, EngineeringChange, Phase 7/8, activation, and external
acceptance so every caller uses one completion rule.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.capability_acquisition.external_acceptance import (
    EXTERNAL_ACCEPTANCE_BINDING_KIND,
    EXTERNAL_ACCEPTANCE_RESULT_KIND,
    external_acceptance_completion_guard,
)
from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.engineering_change import ChangeStore
from jarvis.engineering_substrate.change_integration import MANIFEST_KIND
from jarvis.engineering_substrate.contracts import HardwareAcceptanceVerdict
from jarvis.work.models import WorkState, WorkType


@dataclass(frozen=True, slots=True)
class CapabilityAcquisitionLineage:
    change_id: str
    motivating_goal_id: str
    gap_id: str
    request_id: str
    request_digest: str
    acquisition_work_id: str
    candidate_artifact_id: str
    package_admission_artifact_id: str
    activation_artifact_id: str
    package_id: str
    package_version: str
    package_digest: str
    external_acceptance_required: bool
    external_acceptance_binding_artifact_id: str | None
    external_acceptance_work_id: str | None
    external_acceptance_artifact_id: str | None


class CapabilityAcquisitionLineageError(ValueError):
    """Persisted Phase-9 lineage is missing, stale, or contradictory."""


def _text(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise CapabilityAcquisitionLineageError(f"{field} is missing")
    return normalized


def verify_capability_acquisition_completion(
    store: ChangeStore,
    *,
    change_id: str,
    motivating_goal_id: str,
    gap_id: str,
    request_id: str | None = None,
    request_digest: str | None = None,
) -> CapabilityAcquisitionLineage | None:
    """Return exact completion lineage, or None when canonical evidence is incomplete.

    Contradictory/stale evidence raises because callers should fail closed rather than
    silently accepting a different capability generation.
    """

    change_key = _text(change_id, field="change_id")
    goal_key = _text(motivating_goal_id, field="motivating_goal_id")
    gap_key = _text(gap_id, field="gap_id")

    link = store.latest_artifact(change_key, "gicc_capability_gap_link")
    candidate = store.latest_artifact(change_key, "capability_candidate")
    admission = store.latest_artifact(change_key, "capability_package_admission")
    activation = store.latest_artifact(change_key, "capability_lifecycle_activation")
    architecture = store.latest_artifact(change_key, "architecture")
    if any(
        artifact is None
        for artifact in (link, candidate, admission, activation, architecture)
    ):
        return None

    assert link is not None
    assert candidate is not None
    assert admission is not None
    assert activation is not None
    assert architecture is not None

    if link.payload.get("schema") != "gicc_phase9_gap_link.v2":
        raise CapabilityAcquisitionLineageError("GICC Phase-9 link schema is stale")
    if (
        link.payload.get("motivating_goal_id") != goal_key
        or link.payload.get("gap_id") != gap_key
        or link.payload.get("engineering_change_id") != change_key
    ):
        raise CapabilityAcquisitionLineageError(
            "GICC Phase-9 link does not match the requested goal/gap/change"
        )

    linked_request_id = _text(link.payload.get("request_id"), field="request_id")
    linked_request_digest = _text(
        link.payload.get("request_digest"),
        field="request_digest",
    )
    if request_id is not None and linked_request_id != str(request_id).strip():
        raise CapabilityAcquisitionLineageError("Phase-9 request identity drift")
    if (
        request_digest is not None
        and linked_request_digest != str(request_digest).strip()
    ):
        raise CapabilityAcquisitionLineageError("Phase-9 request digest drift")

    acquisition_work_id = _text(
        link.payload.get("acquisition_work_id"),
        field="acquisition_work_id",
    )

    if (
        admission.payload.get("candidate_artifact_id") != candidate.artifact_id
        or admission.payload.get("candidate_artifact_digest") != candidate.digest
    ):
        raise CapabilityAcquisitionLineageError(
            "Phase-8 package admission is not bound to the current candidate"
        )
    if (
        activation.payload.get("candidate_artifact_id") != candidate.artifact_id
        or activation.payload.get("candidate_artifact_digest") != candidate.digest
        or activation.payload.get("admission_artifact_id") != admission.artifact_id
        or activation.payload.get("admission_artifact_digest") != admission.digest
    ):
        raise CapabilityAcquisitionLineageError(
            "activation is not bound to the current candidate/package admission"
        )
    if activation.payload.get("effective_enabled") is not True:
        return None

    disabled = store.latest_artifact(change_key, "capability_lifecycle_disable")
    if (
        disabled is not None
        and disabled.payload.get("candidate_artifact_id") == candidate.artifact_id
        and disabled.payload.get("candidate_artifact_digest") == candidate.digest
        and disabled.payload.get("effective_enabled") is False
        and disabled.created_at >= activation.created_at
    ):
        # A later explicit disable invalidates capability readiness even when an
        # older activation and external-acceptance artifact still exist.
        return None

    package_identity = (
        _text(candidate.payload.get("package_id"), field="package_id"),
        _text(candidate.payload.get("package_version"), field="package_version"),
        _text(candidate.payload.get("package_digest"), field="package_digest"),
    )
    if package_identity != (
        admission.payload.get("package_id"),
        admission.payload.get("package_version"),
        admission.payload.get("package_digest"),
    ):
        raise CapabilityAcquisitionLineageError(
            "candidate and Phase-8 admission package identities disagree"
        )
    if package_identity != (
        activation.payload.get("package_id"),
        activation.payload.get("package_version"),
        activation.payload.get("package_digest"),
    ):
        raise CapabilityAcquisitionLineageError(
            "activation package identity disagrees with the admitted package"
        )

    contracts = {
        str(item).strip()
        for item in architecture.payload.get("owner_acceptance_contract_ids", ())
        if str(item).strip()
    }
    external_required = PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT in contracts
    external_binding_id = None
    external_work_id = None
    external_id = None
    if external_required:
        binding = store.latest_artifact(
            change_key,
            EXTERNAL_ACCEPTANCE_BINDING_KIND,
        )
        external = store.latest_artifact(
            change_key,
            EXTERNAL_ACCEPTANCE_RESULT_KIND,
        )
        if binding is None or external is None:
            return None
        if binding.payload.get("schema") != "capability_external_acceptance_binding.v1":
            raise CapabilityAcquisitionLineageError(
                "external acceptance binding schema is stale"
            )

        goal_artifact = store.latest_artifact(change_key, "capability_goal")
        manifest = store.latest_artifact(change_key, MANIFEST_KIND)
        if goal_artifact is None or manifest is None:
            return None

        if (
            binding.payload.get("candidate_artifact_id") != candidate.artifact_id
            or binding.payload.get("candidate_artifact_digest") != candidate.digest
            or binding.payload.get("activation_artifact_id") != activation.artifact_id
            or binding.payload.get("activation_artifact_digest") != activation.digest
            or binding.payload.get("architecture_artifact_id")
            != architecture.artifact_id
            or binding.payload.get("architecture_artifact_digest")
            != architecture.digest
            or binding.payload.get("manifest_artifact_id") != manifest.artifact_id
            or binding.payload.get("manifest_artifact_digest") != manifest.digest
            or binding.payload.get("goal_artifact_id") != goal_artifact.artifact_id
            or binding.payload.get("goal_artifact_digest") != goal_artifact.digest
        ):
            raise CapabilityAcquisitionLineageError(
                "external acceptance binding is stale or cross-generation"
            )
        if (
            binding.payload.get("acceptance_contract_id")
            != PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT
        ):
            raise CapabilityAcquisitionLineageError(
                "external acceptance binding contract does not match architecture"
            )
        if (
            binding.payload.get("authority_session_id")
            != activation.payload.get("authority_session_id")
            or binding.payload.get("source_turn_id")
            != activation.payload.get("source_turn_id")
        ):
            raise CapabilityAcquisitionLineageError(
                "external acceptance authority differs from activation authority"
            )

        work_id = _text(
            binding.payload.get("work_id"),
            field="external_acceptance_work_id",
        )
        acceptance_work = store.work.get(work_id)
        if acceptance_work is None:
            return None
        if (
            acceptance_work.work_type is not WorkType.EXTERNAL_ACCEPTANCE
            or acceptance_work.source_session_id != f"phase9-external:{change_key}"
            or acceptance_work.source_turn_id != activation.artifact_id
        ):
            raise CapabilityAcquisitionLineageError(
                "external acceptance WorkItem identity does not match its binding"
            )
        development_work_id = _text(
            candidate.payload.get("development_work_id"),
            field="development_work_id",
        )
        if development_work_id not in set(acceptance_work.dependencies):
            raise CapabilityAcquisitionLineageError(
                "external acceptance WorkItem is not dependent on current development"
            )
        if acceptance_work.state is not WorkState.COMPLETED:
            return None
        allowed, _ = external_acceptance_completion_guard(
            store.work.list_steps(work_id)
        )
        if not allowed:
            return None

        if (
            external.payload.get("schema") != "capability_external_acceptance.v1"
            or external.payload.get("work_id") != work_id
            or external.payload.get("binding_artifact_id") != binding.artifact_id
            or external.payload.get("binding_artifact_digest") != binding.digest
            or external.payload.get("candidate_artifact_id") != candidate.artifact_id
            or external.payload.get("candidate_artifact_digest") != candidate.digest
            or external.payload.get("activation_artifact_id") != activation.artifact_id
            or external.payload.get("activation_artifact_digest") != activation.digest
        ):
            raise CapabilityAcquisitionLineageError(
                "external acceptance is not bound to the current acceptance mission"
            )
        if external.payload.get("verdict") != HardwareAcceptanceVerdict.PASS.value:
            return None
        external_binding_id = binding.artifact_id
        external_work_id = work_id
        external_id = external.artifact_id

    return CapabilityAcquisitionLineage(
        change_id=change_key,
        motivating_goal_id=goal_key,
        gap_id=gap_key,
        request_id=linked_request_id,
        request_digest=linked_request_digest,
        acquisition_work_id=acquisition_work_id,
        candidate_artifact_id=candidate.artifact_id,
        package_admission_artifact_id=admission.artifact_id,
        activation_artifact_id=activation.artifact_id,
        package_id=package_identity[0],
        package_version=package_identity[1],
        package_digest=package_identity[2],
        external_acceptance_required=external_required,
        external_acceptance_binding_artifact_id=external_binding_id,
        external_acceptance_work_id=external_work_id,
        external_acceptance_artifact_id=external_id,
    )
