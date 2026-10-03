"""Deterministic Phase-9 acquisition-plan -> architecture handoff."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.capability_acquisition.artifacts import (
    candidate_from_payload,
    evaluation_from_payload,
    goal_from_payload,
    plan_from_payload,
)
from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
    external_interaction_contract_descriptor,
)
from jarvis.capability_acquisition.models import OwnerCapabilityGoalV1
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.engineering_change.models import (
    ChangeArtifact,
    ChangeConflict,
    ChangeStage,
    ChangeState,
    EngineeringChange,
)
from jarvis.engineering_change.store import ChangeStore
from jarvis.work.models import WorkItem, WorkState


class CapabilityAcquisitionArchitectureError(ChangeConflict):
    """Acquisition plan/architecture provenance is missing, stale or non-buildable."""


@dataclass(frozen=True, slots=True)
class SemanticCapabilityBuildContractV1:
    semantic_capability_family: str
    target_entity_type: str
    target_entity_id: str | None
    required_operations: tuple[str, ...]
    monitor_event_contract: str | None = None

    def __post_init__(self) -> None:
        family = str(self.semantic_capability_family).strip().casefold()
        target_type = str(self.target_entity_type).strip().casefold()
        operations = tuple(
            sorted(
                {
                    str(item).strip().casefold()
                    for item in self.required_operations
                    if str(item).strip()
                }
            )
        )
        target_id = (
            None
            if self.target_entity_id is None
            else str(self.target_entity_id).strip().casefold() or None
        )
        monitor_contract = (
            None
            if self.monitor_event_contract is None
            else str(self.monitor_event_contract).strip().casefold() or None
        )
        if not family or not target_type or not operations:
            raise CapabilityAcquisitionArchitectureError(
                "semantic capability build contract is incomplete"
            )
        object.__setattr__(self, "semantic_capability_family", family)
        object.__setattr__(self, "target_entity_type", target_type)
        object.__setattr__(self, "target_entity_id", target_id)
        object.__setattr__(self, "required_operations", operations)
        object.__setattr__(self, "monitor_event_contract", monitor_contract)

    def to_payload(self) -> dict[str, object]:
        descriptor_requirements: dict[str, object] = {
            "semantic_capability_family": self.semantic_capability_family,
            "target_entity_types": [self.target_entity_type],
        }
        if self.monitor_event_contract is not None:
            descriptor_requirements.update(
                {
                    "observation_operations": list(self.required_operations),
                    "monitor_event_contract": self.monitor_event_contract,
                }
            )
        return {
            "schema": "semantic_capability_build_contract.v1",
            "semantic_capability_family": self.semantic_capability_family,
            "target_entity_type": self.target_entity_type,
            "target_entity_id": self.target_entity_id,
            "required_operations": list(self.required_operations),
            "descriptor_requirements": descriptor_requirements,
        }


def _gicc_semantic_contract(
    store: ChangeStore,
    *,
    change_id: str,
    goal: OwnerCapabilityGoalV1,
) -> SemanticCapabilityBuildContractV1 | None:
    link = store.latest_artifact(change_id, "gicc_capability_gap_link")
    if link is None:
        return None
    payload = link.payload
    if payload.get("schema") not in {
        "gicc_phase9_gap_link.v1",
        "gicc_phase9_gap_link.v2",
    }:
        raise CapabilityAcquisitionArchitectureError(
            "GICC capability-gap link uses an unsupported contract"
        )
    if (
        payload.get("monitor_event_contract_required") is True
        and not str(payload.get("monitor_event_contract") or "").strip()
    ):
        raise CapabilityAcquisitionArchitectureError(
            "GICC monitoring gap requires an explicit monitor event contract"
        )
    contract = SemanticCapabilityBuildContractV1(
        semantic_capability_family=str(payload.get("reusable_capability_family") or ""),
        target_entity_type=str(payload.get("target_entity_type") or ""),
        target_entity_id=(
            None
            if payload.get("target_entity_id") is None
            else str(payload.get("target_entity_id"))
        ),
        required_operations=tuple(payload.get("minimum_required_operations") or ()),
        monitor_event_contract=(
            None
            if not payload.get("monitor_event_contract_required")
            else str(payload.get("monitor_event_contract") or "")
        ),
    )
    if contract.semantic_capability_family != goal.requested_capability.casefold():
        raise CapabilityAcquisitionArchitectureError(
            "GICC semantic family differs from the admitted Phase-9 goal"
        )
    if contract.required_operations != goal.required_operations:
        raise CapabilityAcquisitionArchitectureError(
            "GICC semantic operations differ from the admitted Phase-9 goal"
        )
    hints = {
        " ".join(str(item).split()).casefold()
        for item in goal.target_hints
        if str(item).strip()
    }
    if f"entity_type:{contract.target_entity_type}" not in hints:
        raise CapabilityAcquisitionArchitectureError(
            "GICC target type is not bound to the admitted Phase-9 goal"
        )
    if (
        contract.target_entity_id is not None
        and f"entity_id:{contract.target_entity_id}" not in hints
    ):
        raise CapabilityAcquisitionArchitectureError(
            "GICC target entity is not bound to the admitted Phase-9 goal"
        )
    if (
        contract.monitor_event_contract is not None
        and f"monitor_event_contract:{contract.monitor_event_contract}" not in hints
    ):
        raise CapabilityAcquisitionArchitectureError(
            "GICC monitor event contract is not bound to the admitted Phase-9 goal"
        )
    return contract


@dataclass(frozen=True, slots=True)
class CapabilityAcquisitionArchitecturePlan:
    goal_artifact_id: str
    goal_artifact_digest: str
    goal_id: str
    goal_digest: str
    plan_artifact_id: str
    plan_artifact_digest: str
    plan_id: str
    plan_digest: str
    selected_candidate_id: str
    selected_candidate_digest: str
    selected_evaluation_digest: str
    source_revision: str
    strategy: str
    requested_operations: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    allowed_components: tuple[str, ...]
    dependency_refs: tuple[str, ...]
    secret_scopes: tuple[str, ...]
    sandbox_profile_ids: tuple[str, ...]
    discovery_scopes: tuple[str, ...]
    network_scopes: tuple[str, ...]
    device_scopes: tuple[str, ...]
    verification_contract_ids: tuple[str, ...]
    verification_targets: tuple[str, ...]
    owner_acceptance_contract_ids: tuple[str, ...]
    proposed_capability_id: str
    proposed_package_id: str
    proposed_package_version: str
    rollback_strategy: str
    semantic_capability_contract: SemanticCapabilityBuildContractV1 | None = None
    build_permitted: bool = True
    protected_surface_review_required: bool = True
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.allowed_paths and not self.allowed_components:
            raise CapabilityAcquisitionArchitectureError(
                "capability acquisition architecture requires bounded build scope"
            )
        if not self.verification_targets:
            raise CapabilityAcquisitionArchitectureError(
                "capability acquisition architecture requires verification targets"
            )
        if not self.sandbox_profile_ids:
            raise CapabilityAcquisitionArchitectureError(
                "capability acquisition architecture requires sandbox profile"
            )
        if self.schema_version != 1:
            raise CapabilityAcquisitionArchitectureError(
                "unsupported capability acquisition architecture version"
            )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": "capability_acquisition_architecture.v1",
            "schema_version": self.schema_version,
            "process_key": OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
            "process_version": OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
            "goal_artifact_id": self.goal_artifact_id,
            "goal_artifact_digest": self.goal_artifact_digest,
            "goal_id": self.goal_id,
            "goal_digest": self.goal_digest,
            "plan_artifact_id": self.plan_artifact_id,
            "plan_artifact_digest": self.plan_artifact_digest,
            "plan_id": self.plan_id,
            "plan_digest": self.plan_digest,
            "selected_candidate_id": self.selected_candidate_id,
            "selected_candidate_digest": self.selected_candidate_digest,
            "selected_evaluation_digest": self.selected_evaluation_digest,
            "source_revision": self.source_revision,
            "strategy": self.strategy,
            "requested_operations": list(self.requested_operations),
            "allowed_paths": list(self.allowed_paths),
            "allowed_components": list(self.allowed_components),
            "dependency_refs": list(self.dependency_refs),
            "secret_scopes": list(self.secret_scopes),
            "sandbox_profile_ids": list(self.sandbox_profile_ids),
            "discovery_scopes": list(self.discovery_scopes),
            "network_scopes": list(self.network_scopes),
            "device_scopes": list(self.device_scopes),
            "verification_contract_ids": list(self.verification_contract_ids),
            "verification_targets": list(self.verification_targets),
            "owner_acceptance_contract_ids": list(self.owner_acceptance_contract_ids),
            "proposed_capability_id": self.proposed_capability_id,
            "proposed_package_id": self.proposed_package_id,
            "proposed_package_version": self.proposed_package_version,
            "rollback_strategy": self.rollback_strategy,
            "build_permitted": self.build_permitted,
            "protected_surface_review_required": self.protected_surface_review_required,
        }
        if self.semantic_capability_contract is not None:
            payload["semantic_capability_contract"] = (
                self.semantic_capability_contract.to_payload()
            )
        if PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT in set(
            self.owner_acceptance_contract_ids
        ):
            payload["external_runtime_contract"] = (
                external_interaction_contract_descriptor()
            )
        return payload


def _validate_completed_acquisition(
    store: ChangeStore,
    *,
    change: EngineeringChange,
    stage: ChangeStage,
    work: WorkItem,
) -> tuple[
    ChangeArtifact,
    ChangeArtifact,
    ChangeArtifact,
]:
    if work.state is not WorkState.COMPLETED:
        raise CapabilityAcquisitionArchitectureError(
            "acquisition architecture requires completed acquisition research"
        )
    if stage.work_id != work.work_id or stage.change_id != change.change_id:
        raise CapabilityAcquisitionArchitectureError(
            "acquisition WorkItem identity does not match change stage"
        )
    goal_artifact = store.latest_artifact(change.change_id, "capability_goal")
    admission = store.latest_artifact(
        change.change_id,
        "capability_acquisition_admission",
    )
    plan_artifact = store.latest_artifact(change.change_id, "acquisition_plan")
    if goal_artifact is None or admission is None or plan_artifact is None:
        raise CapabilityAcquisitionArchitectureError(
            "completed acquisition research lacks canonical goal/admission/plan"
        )
    goal = goal_from_payload(goal_artifact.payload)
    if (
        admission.payload.get("goal_artifact_id") != goal_artifact.artifact_id
        or admission.payload.get("goal_artifact_digest") != goal_artifact.digest
        or admission.payload.get("goal_id") != goal.goal_id
        or admission.payload.get("goal_digest") != goal.digest
    ):
        raise CapabilityAcquisitionArchitectureError(
            "acquisition admission is not bound to current goal"
        )

    finalize_step = next(
        (
            item
            for item in reversed(store.work.list_steps(work.work_id))
            if item.kind == "acq_finalize"
            and item.state.value == "completed"
            and item.observation.get("finalized") is True
        ),
        None,
    )
    if finalize_step is None:
        raise CapabilityAcquisitionArchitectureError(
            "completed acquisition WorkItem lacks canonical acq_finalize"
        )
    if (
        finalize_step.observation.get("plan_artifact_id") != plan_artifact.artifact_id
        or finalize_step.observation.get("plan_artifact_digest") != plan_artifact.digest
    ):
        raise CapabilityAcquisitionArchitectureError(
            "acquisition plan artifact differs from final WorkStep"
        )
    return goal_artifact, admission, plan_artifact


def derive_capability_acquisition_architecture(
    store: ChangeStore,
    *,
    change: EngineeringChange,
    stage: ChangeStage,
    work: WorkItem,
) -> ChangeArtifact:
    if (
        change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
        or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
    ):
        raise CapabilityAcquisitionArchitectureError(
            "capability acquisition handler received wrong process"
        )
    goal_artifact, admission, plan_artifact = _validate_completed_acquisition(
        store,
        change=change,
        stage=stage,
        work=work,
    )
    goal = goal_from_payload(goal_artifact.payload)
    selected_candidate = candidate_from_payload(
        plan_artifact.payload.get("selected_candidate")
    )
    selected_evaluation = evaluation_from_payload(
        plan_artifact.payload.get("selected_evaluation")
    )
    plan = plan_from_payload(
        plan_artifact.payload,
        goal=goal,
        candidate=selected_candidate,
        evaluation=selected_evaluation,
    )
    source_revision = str(admission.payload.get("source_revision") or "").strip()
    semantic_contract = _gicc_semantic_contract(
        store,
        change_id=change.change_id,
        goal=goal,
    )
    architecture = CapabilityAcquisitionArchitecturePlan(
        goal_artifact_id=goal_artifact.artifact_id,
        goal_artifact_digest=goal_artifact.digest,
        goal_id=goal.goal_id,
        goal_digest=goal.digest,
        plan_artifact_id=plan_artifact.artifact_id,
        plan_artifact_digest=plan_artifact.digest,
        plan_id=plan.plan_id,
        plan_digest=plan.digest,
        selected_candidate_id=selected_candidate.candidate_id,
        selected_candidate_digest=selected_candidate.digest,
        selected_evaluation_digest=selected_evaluation.digest,
        source_revision=source_revision,
        strategy=plan.strategy.value,
        requested_operations=plan.requested_operations,
        allowed_paths=plan.changed_paths,
        allowed_components=plan.changed_components,
        dependency_refs=plan.dependency_refs,
        secret_scopes=plan.secret_scopes,
        sandbox_profile_ids=plan.sandbox_profile_ids,
        discovery_scopes=plan.discovery_scopes,
        network_scopes=plan.network_scopes,
        device_scopes=plan.device_scopes,
        verification_contract_ids=plan.verification_contract_ids,
        verification_targets=plan.development_test_targets,
        owner_acceptance_contract_ids=plan.owner_acceptance_contract_ids,
        proposed_capability_id=plan.proposed_capability_id,
        proposed_package_id=plan.proposed_package_id,
        proposed_package_version=plan.proposed_package_version,
        rollback_strategy=plan.rollback_summary,
        semantic_capability_contract=semantic_contract,
    )
    payload = architecture.to_payload()
    current = store.latest_artifact(change.change_id, "architecture")
    if current is not None and current.payload == payload:
        return current
    return store.add_artifact(change.change_id, kind="architecture", payload=payload)


def ensure_capability_acquisition_architecture_current(
    store: ChangeStore,
    change_id: str,
    *,
    artifact_id: str | None = None,
) -> ChangeArtifact:
    change = store.require(change_id)
    if (
        change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
        or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
    ):
        raise CapabilityAcquisitionArchitectureError(
            "change is not Phase-9 capability acquisition"
        )
    architecture = store.latest_artifact(change_id, "architecture")
    if architecture is None:
        raise CapabilityAcquisitionArchitectureError(
            "capability acquisition architecture is missing"
        )
    if artifact_id is not None and architecture.artifact_id != artifact_id:
        raise CapabilityAcquisitionArchitectureError(
            "capability acquisition architecture was superseded"
        )
    payload = architecture.payload
    if (
        payload.get("schema") != "capability_acquisition_architecture.v1"
        or payload.get("schema_version") != 1
        or payload.get("process_key") != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
        or payload.get("process_version")
        != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
        or payload.get("build_permitted") is not True
        or payload.get("protected_surface_review_required") is not True
    ):
        raise CapabilityAcquisitionArchitectureError(
            "capability acquisition architecture contract is invalid"
        )
    goal_artifact = store.latest_artifact(change_id, "capability_goal")
    plan_artifact = store.latest_artifact(change_id, "acquisition_plan")
    admission = store.latest_artifact(
        change_id,
        "capability_acquisition_admission",
    )
    if goal_artifact is None or plan_artifact is None or admission is None:
        raise CapabilityAcquisitionArchitectureError(
            "capability acquisition architecture provenance is incomplete"
        )
    if (
        payload.get("goal_artifact_id") != goal_artifact.artifact_id
        or payload.get("goal_artifact_digest") != goal_artifact.digest
        or payload.get("plan_artifact_id") != plan_artifact.artifact_id
        or payload.get("plan_artifact_digest") != plan_artifact.digest
        or payload.get("source_revision") != admission.payload.get("source_revision")
    ):
        raise CapabilityAcquisitionArchitectureError(
            "capability acquisition architecture provenance drifted"
        )
    source_stage_key = (
        OWNER_CAPABILITY_ACQUISITION_PROCESS.architecture_source_stage.stage_key
    )
    stage = None
    work = None
    for candidate_stage in reversed(store.list_stages(change_id)):
        if candidate_stage.stage_key != source_stage_key:
            continue
        candidate_work = store.work.require(candidate_stage.work_id)
        if candidate_work.state is not WorkState.COMPLETED:
            continue
        finalize_step = next(
            (
                item
                for item in reversed(store.work.list_steps(candidate_work.work_id))
                if item.kind == "acq_finalize"
                and item.state.value == "completed"
                and item.observation.get("finalized") is True
                and item.observation.get("plan_artifact_id")
                == plan_artifact.artifact_id
                and item.observation.get("plan_artifact_digest")
                == plan_artifact.digest
            ),
            None,
        )
        if finalize_step is not None:
            stage = candidate_stage
            work = candidate_work
            break
    if stage is None or work is None:
        raise CapabilityAcquisitionArchitectureError(
            "capability acquisition architecture has no matching completed source stage"
        )
    _validate_completed_acquisition(
        store,
        change=change,
        stage=stage,
        work=work,
    )
    return architecture


class CapabilityAcquisitionDevelopmentRevisionResolver:
    """Bind Phase-9 DEVELOPMENT to the exact revision approved at acquisition."""

    def __init__(self, store: ChangeStore) -> None:
        if not isinstance(store, ChangeStore):
            raise TypeError("store must be ChangeStore")
        self._store = store

    def revision_for(self, work_id: str) -> str | None:
        stage = self._store.stage_for_work(str(work_id).strip())
        if stage is None:
            return None
        change = self._store.require(stage.change_id)
        if (
            change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
            or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
            or stage.stage_key
            != OWNER_CAPABILITY_ACQUISITION_PROCESS.development_stage.stage_key
        ):
            return None
        architecture = ensure_capability_acquisition_architecture_current(
            self._store,
            change.change_id,
            artifact_id=stage.plan_artifact_id,
        )
        revision = str(architecture.payload.get("source_revision") or "").strip()
        if not revision:
            raise CapabilityAcquisitionArchitectureError(
                "approved capability architecture has no source revision"
            )
        return revision


class CapabilityAcquisitionSourceCompletionHandler:
    process_key = OWNER_CAPABILITY_ACQUISITION_PROCESS.key
    process_version = OWNER_CAPABILITY_ACQUISITION_PROCESS.version

    def __init__(self, store: ChangeStore) -> None:
        if not isinstance(store, ChangeStore):
            raise TypeError("store must be ChangeStore")
        self._store = store

    def complete(
        self,
        *,
        change: EngineeringChange,
        stage: ChangeStage,
        work: WorkItem,
    ) -> ChangeState | None:
        artifact = derive_capability_acquisition_architecture(
            self._store,
            change=change,
            stage=stage,
            work=work,
        )
        revision_request = self._store.latest_artifact(
            change.change_id,
            "architecture_revision_request",
        )
        if (
            revision_request is not None
            and revision_request.payload.get("source_attempt") == stage.attempt
            and revision_request.payload.get("previous_architecture_artifact_id")
            == artifact.artifact_id
        ):
            no_progress_payload: dict[str, object] = {
                "schema": "capability_acquisition_revision_no_progress.v1",
                "source_attempt": stage.attempt,
                "source_work_id": work.work_id,
                "revision_request_artifact_id": revision_request.artifact_id,
                "revision_request_digest": revision_request.digest,
                "unchanged_architecture_artifact_id": artifact.artifact_id,
                "unchanged_architecture_digest": artifact.digest,
            }
            current = self._store.latest_artifact(
                change.change_id,
                "architecture_revision_no_progress",
            )
            if current is None or current.payload != no_progress_payload:
                self._store.add_artifact(
                    change.change_id,
                    kind="architecture_revision_no_progress",
                    payload=no_progress_payload,
                )
            return ChangeState.FAILED

        ensure_capability_acquisition_architecture_current(
            self._store,
            change.change_id,
            artifact_id=artifact.artifact_id,
        )
        return None
