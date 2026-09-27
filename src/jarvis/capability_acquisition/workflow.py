"""Typed acquisition-stage actions for Phase-9 RESEARCH WorkItems."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.capability_acquisition.artifacts import (
    candidate_from_payload,
    candidate_payload,
    evaluation_payload,
    goal_from_payload,
    plan_payload,
    resolution_payload,
    typed_resolution_from_payload,
)
from jarvis.capability_acquisition.models import (
    AcquisitionCandidateV1,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    CapabilityAcquisitionPlanV1,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.resolver import CapabilityAcquisitionResolver
from jarvis.capability_acquisition.runtime_context import AcquisitionContextProvider
from jarvis.capability_acquisition.source import CapabilitySourceRegistry
from jarvis.engineering_change import ChangeArtifact, ChangeStore
from jarvis.work.brain import BrainAction
from jarvis.work.models import WorkItem, WorkStep, WorkType


class AcquisitionProtocolError(RuntimeError):
    """Phase-9 acquisition evidence/finalization failed deterministic validation."""


@dataclass(frozen=True, slots=True)
class AcquisitionWorkContext:
    change_id: str
    work_id: str
    goal: OwnerCapabilityGoalV1
    goal_artifact: ChangeArtifact
    admission_artifact: ChangeArtifact
    source_revision: str


class AcquisitionWorkContextResolver:
    def __init__(self, store: ChangeStore) -> None:
        if not isinstance(store, ChangeStore):
            raise TypeError("store must be ChangeStore")
        self._store = store

    @property
    def store(self) -> ChangeStore:
        return self._store

    def context_for(self, work_id: str) -> AcquisitionWorkContext:
        normalized = str(work_id).strip()
        stage = self._store.stage_for_work(normalized)
        if stage is None:
            raise AcquisitionProtocolError(
                "acquisition WorkItem is not linked to an EngineeringChange"
            )
        change = self._store.require(stage.change_id)
        if (
            change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
            or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
            or stage.stage_key
            != OWNER_CAPABILITY_ACQUISITION_PROCESS.architecture_source_stage.stage_key
        ):
            raise AcquisitionProtocolError(
                "acquisition action is unavailable outside Phase-9 acquisition stage"
            )
        goal_artifact = self._store.latest_artifact(change.change_id, "capability_goal")
        admission = self._store.latest_artifact(
            change.change_id,
            "capability_acquisition_admission",
        )
        if goal_artifact is None or admission is None:
            raise AcquisitionProtocolError("Phase-9 admission artifacts are incomplete")
        goal = goal_from_payload(goal_artifact.payload)
        if (
            admission.payload.get("goal_artifact_id") != goal_artifact.artifact_id
            or admission.payload.get("goal_artifact_digest") != goal_artifact.digest
            or admission.payload.get("goal_id") != goal.goal_id
            or admission.payload.get("goal_digest") != goal.digest
        ):
            raise AcquisitionProtocolError("Phase-9 admission/goal binding is stale")
        source_revision = str(admission.payload.get("source_revision") or "").strip()
        if not source_revision:
            raise AcquisitionProtocolError("Phase-9 source revision is missing")
        return AcquisitionWorkContext(
            change_id=change.change_id,
            work_id=normalized,
            goal=goal,
            goal_artifact=goal_artifact,
            admission_artifact=admission,
            source_revision=source_revision,
        )

    def completed_steps(self, work_id: str) -> tuple[WorkStep, ...]:
        return tuple(
            step
            for step in self._store.work.list_steps(str(work_id).strip())
            if step.state.value == "completed"
        )


def recorded_unverified_candidates(
    steps: tuple[WorkStep, ...],
) -> tuple[AcquisitionCandidateV1, ...]:
    output: dict[str, AcquisitionCandidateV1] = {}
    for step in steps:
        if step.kind != "acq_record_candidate" or step.state.value != "completed":
            continue
        candidate = candidate_from_payload(step.observation.get("candidate"))
        if candidate.trust_class is not AcquisitionTrustClass.UNVERIFIED_CANDIDATE:
            raise AcquisitionProtocolError(
                "research-recorded candidates must remain unverified"
            )
        output[candidate.candidate_id] = candidate
    return tuple(sorted(output.values(), key=lambda item: item.candidate_id))


class AcquisitionInspectGoalExecutor:
    descriptor = BrainAction(
        name="acq_inspect_goal",
        description=(
            "Read the exact owner capability goal and immutable source revision for this "
            "Phase-9 acquisition WorkItem. This action is read-only."
        ),
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.RESEARCH})

    def __init__(self, resolver: AcquisitionWorkContextResolver) -> None:
        self._resolver = resolver

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ()

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del parameters
        context = self._resolver.context_for(work.work_id)
        return {
            "goal": context.goal_artifact.payload,
            "goal_artifact_id": context.goal_artifact.artifact_id,
            "goal_artifact_digest": context.goal_artifact.digest,
            "source_revision": context.source_revision,
        }


class AcquisitionRecordCandidateExecutor:
    """Record research-discovered source metadata without assigning trust."""

    descriptor = BrainAction(
        name="acq_record_candidate",
        description=(
            "Record one research-discovered capability source candidate. This action "
            "always stores the source as UNVERIFIED; model text cannot grant trust."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "source_kind": {
                    "type": "string",
                    "enum": ["mcp", "openapi", "asyncapi", "sdk_library"],
                },
                "source_identity": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1000,
                },
                "source_version": {
                    "type": ["string", "null"],
                    "maxLength": 240,
                },
                "source_digest": {
                    "type": ["string", "null"],
                    "maxLength": 64,
                },
                "supported_operations": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 120},
                    "minItems": 1,
                    "maxItems": 256,
                },
                "evidence_refs": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "minItems": 1,
                    "maxItems": 50,
                },
                "verification_requirements": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 500},
                    "minItems": 1,
                    "maxItems": 30,
                },
            },
            "required": [
                "source_kind",
                "source_identity",
                "supported_operations",
                "evidence_refs",
                "verification_requirements",
            ],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.RESEARCH})

    def __init__(self, resolver: AcquisitionWorkContextResolver) -> None:
        self._resolver = resolver

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ()

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        self._resolver.context_for(work.work_id)
        try:
            source_kind = AcquisitionSourceKind(str(parameters.get("source_kind")))
        except ValueError as exc:
            raise AcquisitionProtocolError(
                "unsupported acquisition source kind"
            ) from exc
        strategy = {
            AcquisitionSourceKind.MCP: AcquisitionStrategy.WRAP,
            AcquisitionSourceKind.OPENAPI: AcquisitionStrategy.GENERATE_CONTRACT_CLIENT,
            AcquisitionSourceKind.ASYNCAPI: AcquisitionStrategy.GENERATE_CONTRACT_CLIENT,
            AcquisitionSourceKind.SDK_LIBRARY: AcquisitionStrategy.ADAPT_SDK,
        }[source_kind]
        candidate = AcquisitionCandidateV1.create(
            source_kind=source_kind,
            source_identity=str(parameters.get("source_identity") or ""),
            source_version=parameters.get("source_version"),
            source_digest=parameters.get("source_digest"),
            trust_class=AcquisitionTrustClass.UNVERIFIED_CANDIDATE,
            supported_operations=tuple(parameters.get("supported_operations") or ()),
            strategy=strategy,
            evidence_refs=tuple(parameters.get("evidence_refs") or ()),
            verification_requirements=tuple(
                parameters.get("verification_requirements") or ()
            ),
            reason_codes=("research_discovered_unverified",),
        )
        return {
            "candidate": candidate_payload(candidate),
            "trust_assignment": "unverified_candidate",
            "execution_authorized": False,
        }


class AcquisitionResolveExecutor:
    descriptor = BrainAction(
        name="acq_resolve",
        description=(
            "Resolve trusted registered capability sources against the exact owner goal. "
            "Research-recorded unverified candidates remain visible but blocked."
        ),
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.RESEARCH})

    def __init__(
        self,
        resolver: AcquisitionWorkContextResolver,
        *,
        context_provider: AcquisitionContextProvider,
        sources: CapabilitySourceRegistry,
    ) -> None:
        self._resolver = resolver
        self._context_provider = context_provider
        self._acquisition = CapabilityAcquisitionResolver(sources)

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ()

    @staticmethod
    def _persist_if_changed(
        store: ChangeStore,
        *,
        change_id: str,
        payload: dict[str, object],
    ) -> ChangeArtifact:
        latest = store.latest_artifact(change_id, "acquisition_resolution")
        if latest is not None and latest.payload == payload:
            return latest
        return store.add_artifact(
            change_id,
            kind="acquisition_resolution",
            payload=payload,
        )

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del parameters
        context = self._resolver.context_for(work.work_id)
        resolution = self._acquisition.resolve(
            context.goal,
            self._context_provider.current(),
        )
        candidates = list(resolution.candidates)
        evaluations = list(resolution.evaluations)
        known = {item.candidate_id for item in candidates}
        for candidate in recorded_unverified_candidates(
            self._resolver.completed_steps(work.work_id)
        ):
            if candidate.candidate_id in known:
                continue
            candidates.append(candidate)
            evaluations.append(
                self._acquisition.evaluate(
                    context.goal,
                    candidate,
                    self._context_provider.current(),
                )
            )
        candidates.sort(key=lambda item: item.candidate_id)
        evaluations.sort(key=lambda item: item.candidate_id)
        payload = resolution_payload(
            candidates=tuple(candidates),
            evaluations=tuple(evaluations),
            selected_candidate_id=resolution.selected_candidate_id,
        )
        artifact = self._persist_if_changed(
            self._resolver.store,
            change_id=context.change_id,
            payload=payload,
        )
        return {
            "resolved": True,
            "resolution_artifact_id": artifact.artifact_id,
            "resolution_artifact_digest": artifact.digest,
            "selected_candidate_id": resolution.selected_candidate_id,
            "candidate_count": len(candidates),
            "blocked_candidate_count": sum(
                item.disposition.value == "blocked" for item in evaluations
            ),
        }


class AcquisitionFinalizeExecutor:
    descriptor = BrainAction(
        name="acq_finalize",
        description=(
            "Create the exact digest-bound capability acquisition plan from the latest "
            "deterministically selected candidate. This does not approve or build it."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "proposed_capability_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 180,
                },
                "proposed_package_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 180,
                },
                "proposed_package_version": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 80,
                },
                "rollback_summary": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 2000,
                },
                "changed_components": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 180},
                    "maxItems": 50,
                },
                "changed_paths": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "maxItems": 100,
                },
                "dependency_refs": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "maxItems": 100,
                },
                "secret_scopes": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 180},
                    "maxItems": 50,
                },
                "network_scopes": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "maxItems": 50,
                },
                "device_scopes": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "maxItems": 50,
                },
                "discovery_scopes": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 180},
                    "maxItems": 50,
                },
                "sandbox_profile_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 180},
                    "minItems": 1,
                    "maxItems": 20,
                },
                "verification_contract_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 180},
                    "minItems": 1,
                    "maxItems": 30,
                },
                "owner_acceptance_contract_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 180},
                    "maxItems": 30,
                },
                "evidence_refs": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "maxItems": 100,
                },
            },
            "required": [
                "proposed_capability_id",
                "proposed_package_id",
                "proposed_package_version",
                "rollback_summary",
                "sandbox_profile_ids",
                "verification_contract_ids",
            ],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.RESEARCH})

    def __init__(self, resolver: AcquisitionWorkContextResolver) -> None:
        self._resolver = resolver

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ()

    @staticmethod
    def _persist_if_changed(
        store: ChangeStore,
        *,
        change_id: str,
        payload: dict[str, object],
    ) -> ChangeArtifact:
        latest = store.latest_artifact(change_id, "acquisition_plan")
        if latest is not None and latest.payload == payload:
            return latest
        return store.add_artifact(change_id, kind="acquisition_plan", payload=payload)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._resolver.context_for(work.work_id)
        resolution_artifact = self._resolver.store.latest_artifact(
            context.change_id,
            "acquisition_resolution",
        )
        if resolution_artifact is None:
            raise AcquisitionProtocolError("acq_finalize requires acq_resolve evidence")
        candidates, evaluations, selected_id = typed_resolution_from_payload(
            resolution_artifact.payload
        )
        if selected_id is None:
            raise AcquisitionProtocolError(
                "no safe acquisition candidate is selectable"
            )
        candidate = next(
            item for item in candidates if item.candidate_id == selected_id
        )
        evaluation = next(
            item for item in evaluations if item.candidate_id == selected_id
        )
        if candidate.strategy is AcquisitionStrategy.REUSE:
            raise AcquisitionProtocolError(
                "an existing reusable capability became available; engineering build is unnecessary"
            )
        changed_components = tuple(parameters.get("changed_components") or ())
        changed_paths = tuple(parameters.get("changed_paths") or ())
        if not changed_components and not changed_paths:
            raise AcquisitionProtocolError(
                "build acquisition plan requires bounded changed component/path scope"
            )
        plan = CapabilityAcquisitionPlanV1.create(
            context.goal,
            candidate,
            evaluation,
            proposed_capability_id=str(parameters.get("proposed_capability_id") or ""),
            proposed_package_id=str(parameters.get("proposed_package_id") or ""),
            proposed_package_version=str(
                parameters.get("proposed_package_version") or ""
            ),
            rollback_summary=str(parameters.get("rollback_summary") or ""),
            changed_components=changed_components,
            changed_paths=changed_paths,
            dependency_refs=tuple(
                {
                    *candidate.dependency_refs,
                    *(parameters.get("dependency_refs") or ()),
                }
            ),
            secret_scopes=tuple(
                {
                    *candidate.secret_scopes,
                    *(parameters.get("secret_scopes") or ()),
                }
            ),
            sandbox_profile_ids=tuple(parameters.get("sandbox_profile_ids") or ()),
            discovery_scopes=tuple(
                {
                    *candidate.discovery_scopes,
                    *(parameters.get("discovery_scopes") or ()),
                }
            ),
            network_scopes=tuple(
                {
                    *candidate.network_scopes,
                    *(parameters.get("network_scopes") or ()),
                }
            ),
            device_scopes=tuple(
                {
                    *candidate.device_scopes,
                    *(parameters.get("device_scopes") or ()),
                }
            ),
            verification_contract_ids=tuple(
                {
                    *candidate.verification_requirements,
                    *(parameters.get("verification_contract_ids") or ()),
                }
            ),
            owner_acceptance_contract_ids=tuple(
                {
                    *candidate.external_acceptance_requirements,
                    *(parameters.get("owner_acceptance_contract_ids") or ()),
                }
            ),
            evidence_refs=tuple(
                {
                    *candidate.evidence_refs,
                    *(parameters.get("evidence_refs") or ()),
                    f"resolution-artifact:{resolution_artifact.artifact_id}",
                }
            ),
        )
        artifact = self._persist_if_changed(
            self._resolver.store,
            change_id=context.change_id,
            payload={
                **plan_payload(plan),
                "resolution_artifact_id": resolution_artifact.artifact_id,
                "resolution_artifact_digest": resolution_artifact.digest,
                "selected_candidate": candidate_payload(candidate),
                "selected_evaluation": evaluation_payload(evaluation),
            },
        )
        return {
            "finalized": True,
            "plan_id": plan.plan_id,
            "plan_digest": plan.digest,
            "plan_artifact_id": artifact.artifact_id,
            "plan_artifact_digest": artifact.digest,
            "selected_candidate_id": candidate.candidate_id,
            "selected_candidate_digest": candidate.digest,
        }


def acquisition_completion_guard(
    steps: tuple[WorkStep, ...],
) -> tuple[bool, str | None]:
    inspected = any(
        step.kind == "acq_inspect_goal"
        and step.state.value == "completed"
        and isinstance(step.observation.get("goal"), dict)
        for step in steps
    )
    if not inspected:
        return False, "capability acquisition must inspect the exact owner goal"

    resolved = [
        (index, step)
        for index, step in enumerate(steps)
        if step.kind == "acq_resolve"
        and step.state.value == "completed"
        and step.observation.get("resolved") is True
    ]
    if not resolved:
        return False, "capability acquisition requires deterministic source resolution"

    finalized = [
        (index, step)
        for index, step in enumerate(steps)
        if step.kind == "acq_finalize"
        and step.state.value == "completed"
        and step.observation.get("finalized") is True
    ]
    if not finalized:
        return False, "capability acquisition requires a canonical acq_finalize plan"

    finalize_index, _ = finalized[-1]
    relevant = {
        "research_web",
        "acq_record_candidate",
        "acq_resolve",
    }
    latest_relevant = max(
        (
            index
            for index, step in enumerate(steps)
            if step.state.value == "completed" and step.kind in relevant
        ),
        default=-1,
    )
    if finalize_index <= latest_relevant:
        return False, "capability acquisition must re-finalize after latest evidence"
    return True, None


def build_acquisition_protocol_executors(
    resolver: AcquisitionWorkContextResolver,
    *,
    context_provider: AcquisitionContextProvider,
    sources: CapabilitySourceRegistry,
) -> tuple[object, ...]:
    return (
        AcquisitionInspectGoalExecutor(resolver),
        AcquisitionRecordCandidateExecutor(resolver),
        AcquisitionResolveExecutor(
            resolver,
            context_provider=context_provider,
            sources=sources,
        ),
        AcquisitionFinalizeExecutor(resolver),
    )
