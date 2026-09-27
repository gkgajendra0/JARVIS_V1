"""Canonical artifact serialization for Phase-9 acquisition contracts."""

from __future__ import annotations

from typing import Any

from jarvis.capability_acquisition.models import (
    AcquisitionCandidateEvaluationV1,
    AcquisitionCandidateV1,
    AcquisitionDisposition,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    CapabilityAcquisitionPlanV1,
    OwnerCapabilityGoalV1,
)


class AcquisitionArtifactError(ValueError):
    """Persisted Phase-9 typed artifact failed canonical validation."""


def goal_payload(goal: OwnerCapabilityGoalV1) -> dict[str, object]:
    return {
        "schema": "owner_capability_goal.v1",
        "goal_id": goal.goal_id,
        **goal.canonical_payload(),
        "digest": goal.digest,
    }


def goal_from_payload(payload: object) -> OwnerCapabilityGoalV1:
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "owner_capability_goal.v1"
    ):
        raise AcquisitionArtifactError("invalid owner capability goal artifact")
    try:
        goal = OwnerCapabilityGoalV1.create(
            request=str(payload["request"]),
            requested_capability=str(payload["requested_capability"]),
            required_operations=tuple(payload["required_operations"]),
            target_hints=tuple(payload.get("target_hints") or ()),
            source_session_id=str(payload["source_session_id"]),
            source_turn_id=str(payload["source_turn_id"]),
            now_epoch=float(payload["created_at_epoch"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AcquisitionArtifactError(
            "owner capability goal artifact is malformed"
        ) from exc
    if goal.goal_id != payload.get("goal_id") or goal.digest != payload.get("digest"):
        raise AcquisitionArtifactError("owner capability goal artifact digest mismatch")
    return goal


def candidate_payload(candidate: AcquisitionCandidateV1) -> dict[str, object]:
    return {
        "schema": "acquisition_candidate.v1",
        "candidate_id": candidate.candidate_id,
        **candidate.canonical_payload(),
        "digest": candidate.digest,
    }


def candidate_from_payload(payload: object) -> AcquisitionCandidateV1:
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "acquisition_candidate.v1"
    ):
        raise AcquisitionArtifactError("invalid acquisition candidate artifact")
    try:
        candidate = AcquisitionCandidateV1.create(
            source_kind=AcquisitionSourceKind(str(payload["source_kind"])),
            source_identity=str(payload["source_identity"]),
            source_version=payload.get("source_version"),
            source_digest=payload.get("source_digest"),
            trust_class=AcquisitionTrustClass(str(payload["trust_class"])),
            supported_operations=tuple(payload["supported_operations"]),
            dependency_refs=tuple(payload.get("dependency_refs") or ()),
            secret_scopes=tuple(payload.get("secret_scopes") or ()),
            network_scopes=tuple(payload.get("network_scopes") or ()),
            device_scopes=tuple(payload.get("device_scopes") or ()),
            discovery_scopes=tuple(payload.get("discovery_scopes") or ()),
            evidence_refs=tuple(payload["evidence_refs"]),
            license_id=payload.get("license_id"),
            provenance_refs=tuple(payload.get("provenance_refs") or ()),
            strategy=AcquisitionStrategy(str(payload["strategy"])),
            verification_requirements=tuple(payload["verification_requirements"]),
            external_acceptance_requirements=tuple(
                payload.get("external_acceptance_requirements") or ()
            ),
            reason_codes=tuple(payload.get("reason_codes") or ()),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AcquisitionArtifactError(
            "acquisition candidate artifact is malformed"
        ) from exc
    if candidate.candidate_id != payload.get(
        "candidate_id"
    ) or candidate.digest != payload.get("digest"):
        raise AcquisitionArtifactError("acquisition candidate artifact digest mismatch")
    return candidate


def evaluation_payload(
    evaluation: AcquisitionCandidateEvaluationV1,
) -> dict[str, object]:
    return {
        "schema": "acquisition_candidate_evaluation.v1",
        "evaluation_id": evaluation.evaluation_id,
        **evaluation.canonical_payload(),
        "digest": evaluation.digest,
    }


def evaluation_from_payload(payload: object) -> AcquisitionCandidateEvaluationV1:
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "acquisition_candidate_evaluation.v1"
    ):
        raise AcquisitionArtifactError("invalid acquisition evaluation artifact")
    # Evaluation is reconstructed by validating the persisted canonical payload itself.
    try:
        evaluation = AcquisitionCandidateEvaluationV1(
            evaluation_id=str(payload["evaluation_id"]),
            candidate_id=str(payload["candidate_id"]),
            candidate_digest=str(payload["candidate_digest"]),
            requested_operations=tuple(payload["requested_operations"]),
            covered_operations=tuple(payload["covered_operations"]),
            missing_operations=tuple(payload["missing_operations"]),
            evidence_complete=payload["evidence_complete"],
            trust_allowed=payload["trust_allowed"],
            requirements_compatible=payload["requirements_compatible"],
            disposition=AcquisitionDisposition(str(payload["disposition"])),
            reason_codes=tuple(payload["reason_codes"]),
            evaluator_id=str(payload["evaluator_id"]),
            evaluator_version=int(payload["evaluator_version"]),
            digest=str(payload["digest"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AcquisitionArtifactError(
            "acquisition evaluation artifact is malformed"
        ) from exc
    return evaluation


def plan_payload(plan: CapabilityAcquisitionPlanV1) -> dict[str, object]:
    return {
        "schema": "capability_acquisition_plan.v1",
        "plan_id": plan.plan_id,
        **plan.canonical_payload(),
        "digest": plan.digest,
    }


def plan_from_payload(
    payload: object,
    *,
    goal: OwnerCapabilityGoalV1,
    candidate: AcquisitionCandidateV1,
    evaluation: AcquisitionCandidateEvaluationV1,
) -> CapabilityAcquisitionPlanV1:
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "capability_acquisition_plan.v1"
    ):
        raise AcquisitionArtifactError("invalid capability acquisition plan artifact")
    try:
        plan = CapabilityAcquisitionPlanV1.create(
            goal,
            candidate,
            evaluation,
            proposed_capability_id=str(payload["proposed_capability_id"]),
            proposed_package_id=str(payload["proposed_package_id"]),
            proposed_package_version=str(payload["proposed_package_version"]),
            rollback_summary=str(payload["rollback_summary"]),
            changed_components=tuple(payload.get("changed_components") or ()),
            changed_paths=tuple(payload.get("changed_paths") or ()),
            dependency_refs=tuple(payload.get("dependency_refs") or ()),
            secret_scopes=tuple(payload.get("secret_scopes") or ()),
            sandbox_profile_ids=tuple(payload.get("sandbox_profile_ids") or ()),
            discovery_scopes=tuple(payload.get("discovery_scopes") or ()),
            network_scopes=tuple(payload.get("network_scopes") or ()),
            verification_contract_ids=tuple(
                payload.get("verification_contract_ids") or ()
            ),
            owner_acceptance_contract_ids=tuple(
                payload.get("owner_acceptance_contract_ids") or ()
            ),
            evidence_refs=tuple(payload.get("evidence_refs") or ()),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AcquisitionArtifactError(
            "capability acquisition plan artifact is malformed"
        ) from exc
    if plan.plan_id != payload.get("plan_id") or plan.digest != payload.get("digest"):
        raise AcquisitionArtifactError(
            "capability acquisition plan artifact digest mismatch"
        )
    return plan


def resolution_payload(
    *,
    candidates: tuple[AcquisitionCandidateV1, ...],
    evaluations: tuple[AcquisitionCandidateEvaluationV1, ...],
    selected_candidate_id: str | None,
) -> dict[str, object]:
    return {
        "schema": "capability_acquisition_resolution.v1",
        "candidates": [candidate_payload(item) for item in candidates],
        "evaluations": [evaluation_payload(item) for item in evaluations],
        "selected_candidate_id": selected_candidate_id,
    }


def typed_resolution_from_payload(
    payload: object,
) -> tuple[
    tuple[AcquisitionCandidateV1, ...],
    tuple[AcquisitionCandidateEvaluationV1, ...],
    str | None,
]:
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "capability_acquisition_resolution.v1"
    ):
        raise AcquisitionArtifactError(
            "invalid capability acquisition resolution artifact"
        )
    raw_candidates = payload.get("candidates")
    raw_evaluations = payload.get("evaluations")
    if not isinstance(raw_candidates, list) or not isinstance(raw_evaluations, list):
        raise AcquisitionArtifactError(
            "resolution candidate/evaluation lists are missing"
        )
    candidates = tuple(candidate_from_payload(item) for item in raw_candidates)
    evaluations = tuple(evaluation_from_payload(item) for item in raw_evaluations)
    selected = payload.get("selected_candidate_id")
    selected_id = None if selected is None else str(selected).strip() or None
    candidate_ids = {item.candidate_id for item in candidates}
    if len(candidate_ids) != len(candidates):
        raise AcquisitionArtifactError("resolution candidate identities are duplicated")
    if {item.candidate_id for item in evaluations} != candidate_ids:
        raise AcquisitionArtifactError("resolution evaluations do not match candidates")
    if selected_id is not None and selected_id not in candidate_ids:
        raise AcquisitionArtifactError("resolution selected candidate is missing")
    return candidates, evaluations, selected_id
