"""Read-only exact lineage verification for Phase-9 capability acquisition.

This module owns no lifecycle state. It projects and validates canonical evidence
already persisted by GICC, EngineeringChange, Phase 7/8, activation, and external
acceptance so every caller uses one completion rule.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.capability_acquisition.external_acceptance import (
    EXTERNAL_ACCEPTANCE_RESULT_KIND,
)
from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.engineering_change import ChangeStore
from jarvis.engineering_substrate.contracts import HardwareAcceptanceVerdict


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
    external_id = None
    if external_required:
        external = store.latest_artifact(
            change_key,
            EXTERNAL_ACCEPTANCE_RESULT_KIND,
        )
        if external is None:
            return None
        if (
            external.payload.get("candidate_artifact_id") != candidate.artifact_id
            or external.payload.get("candidate_artifact_digest") != candidate.digest
            or external.payload.get("activation_artifact_id") != activation.artifact_id
            or external.payload.get("activation_artifact_digest") != activation.digest
        ):
            raise CapabilityAcquisitionLineageError(
                "external acceptance is not bound to the current activation"
            )
        if external.payload.get("verdict") != HardwareAcceptanceVerdict.PASS.value:
            return None
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
        external_acceptance_artifact_id=external_id,
    )
