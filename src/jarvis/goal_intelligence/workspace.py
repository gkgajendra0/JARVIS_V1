"""Read-only governed ObjectiveWorkspace projection over canonical JARVIS state.

The workspace is a materialized view, never a second persistence authority. It reads
GICC, EngineeringChange and Work stores and exposes one goal-scoped system reality for
later Supervisor ledgers and bounded specialist context views.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.engineering_change import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.work.models import WorkState
from jarvis.work.store import SQLiteWorkStore

from .models import (
    CapabilityGapState,
    ContinuationState,
    InformationNeedState,
)
from .phase9 import Phase9AcquisitionRequestV2
from .store import GoalStore, GoalStoreError


@dataclass(frozen=True, slots=True)
class WorkspaceRecordV1:
    kind: str
    record_id: str
    digest: str
    payload: dict[str, object]

    def to_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "record_id": self.record_id,
            "digest": self.digest,
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceTargetV1:
    target_key: str
    entity_id: str | None
    entity_type: str
    canonical_name: str | None
    provenance_refs: tuple[str, ...]
    source_refs: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "target_key": self.target_key,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "canonical_name": self.canonical_name,
            "provenance_refs": list(self.provenance_refs),
            "source_refs": list(self.source_refs),
        }


@dataclass(frozen=True, slots=True)
class WorkspaceStepV1:
    step_id: str
    kind: str
    summary: str
    state: str
    input_data: dict[str, Any]
    observation: dict[str, Any]
    error: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None

    def to_payload(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "kind": self.kind,
            "summary": self.summary,
            "state": self.state,
            "input_data": self.input_data,
            "observation": self.observation,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceWorkV1:
    work_id: str
    work_type: str
    state: str
    source_session_id: str
    source_turn_id: str
    dependencies: tuple[str, ...]
    status_detail: str | None
    result: dict[str, Any]
    version: int
    created_at: str
    updated_at: str
    steps: tuple[WorkspaceStepV1, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "work_id": self.work_id,
            "work_type": self.work_type,
            "state": self.state,
            "source_session_id": self.source_session_id,
            "source_turn_id": self.source_turn_id,
            "dependencies": list(self.dependencies),
            "status_detail": self.status_detail,
            "result": self.result,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "steps": [item.to_payload() for item in self.steps],
        }


@dataclass(frozen=True, slots=True)
class WorkspaceArtifactV1:
    artifact_id: str
    kind: str
    revision: int
    digest: str
    payload: dict[str, Any]
    created_at: str

    def to_payload(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "revision": self.revision,
            "digest": self.digest,
            "payload": self.payload,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceStageV1:
    stage_key: str
    attempt: int
    work_id: str
    plan_artifact_id: str | None

    def to_payload(self) -> dict[str, object]:
        return {
            "stage_key": self.stage_key,
            "attempt": self.attempt,
            "work_id": self.work_id,
            "plan_artifact_id": self.plan_artifact_id,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceEventV1:
    event_key: str
    kind: str
    detail: dict[str, Any]
    created_at: str

    def to_payload(self) -> dict[str, object]:
        return {
            "event_key": self.event_key,
            "kind": self.kind,
            "detail": self.detail,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceChangeV1:
    change_id: str
    request: str
    process_key: str
    process_version: int
    state: str
    version: int
    source_session_id: str
    source_turn_id: str
    created_at: str
    updated_at: str
    current_architecture_artifact_id: str | None
    artifacts: tuple[WorkspaceArtifactV1, ...]
    stages: tuple[WorkspaceStageV1, ...]
    events: tuple[WorkspaceEventV1, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "change_id": self.change_id,
            "request": self.request,
            "process_key": self.process_key,
            "process_version": self.process_version,
            "state": self.state,
            "version": self.version,
            "source_session_id": self.source_session_id,
            "source_turn_id": self.source_turn_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "current_architecture_artifact_id": self.current_architecture_artifact_id,
            "artifacts": [item.to_payload() for item in self.artifacts],
            "stages": [item.to_payload() for item in self.stages],
            "events": [item.to_payload() for item in self.events],
        }


@dataclass(frozen=True, slots=True)
class ObjectiveWorkspaceV1:
    schema: str
    goal: WorkspaceRecordV1
    targets: tuple[WorkspaceTargetV1, ...]
    requirement_graph: WorkspaceRecordV1 | None
    plan: WorkspaceRecordV1 | None
    capability_gaps: tuple[WorkspaceRecordV1, ...]
    information_needs: tuple[WorkspaceRecordV1, ...]
    continuations: tuple[WorkspaceRecordV1, ...]
    changes: tuple[WorkspaceChangeV1, ...]
    work_items: tuple[WorkspaceWorkV1, ...]
    current_architecture_refs: tuple[str, ...]
    observed_blockers: tuple[str, ...]
    open_questions: tuple[str, ...]
    digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal": self.goal.to_payload(),
            "targets": [item.to_payload() for item in self.targets],
            "requirement_graph": (
                None
                if self.requirement_graph is None
                else self.requirement_graph.to_payload()
            ),
            "plan": None if self.plan is None else self.plan.to_payload(),
            "capability_gaps": [
                item.to_payload() for item in self.capability_gaps
            ],
            "information_needs": [
                item.to_payload() for item in self.information_needs
            ],
            "continuations": [item.to_payload() for item in self.continuations],
            "changes": [item.to_payload() for item in self.changes],
            "work_items": [item.to_payload() for item in self.work_items],
            "current_architecture_refs": list(self.current_architecture_refs),
            "observed_blockers": list(self.observed_blockers),
            "open_questions": list(self.open_questions),
        }

    def __post_init__(self) -> None:
        if self.schema != "objective_workspace.v1":
            raise ValueError("unsupported ObjectiveWorkspace schema")
        if self.digest != "pending":
            expected = canonical_digest(self.canonical_payload())
            if self.digest != expected:
                raise ValueError("ObjectiveWorkspace digest mismatch")


class ObjectiveWorkspaceProjector:
    """Build a deterministic goal-scoped read model without writing canonical state."""

    def __init__(
        self,
        *,
        goal_store: GoalStore,
        change_store: ChangeStore,
        work_store: SQLiteWorkStore | None = None,
    ) -> None:
        if not isinstance(goal_store, GoalStore):
            raise TypeError("goal_store must be GoalStore")
        if not isinstance(change_store, ChangeStore):
            raise TypeError("change_store must be ChangeStore")
        selected_work = work_store or goal_store.work
        if not isinstance(selected_work, SQLiteWorkStore):
            raise TypeError("work_store must be SQLiteWorkStore")
        if selected_work.path != goal_store.work.path:
            raise ValueError("ObjectiveWorkspace stores must share canonical Work storage")
        if change_store.work.path != selected_work.path:
            raise ValueError("EngineeringChange must share canonical Work storage")
        self._goals = goal_store
        self._changes = change_store
        self._work = selected_work

    @staticmethod
    def _record(
        *,
        kind: str,
        record_id: str,
        digest: str,
        payload: dict[str, object],
    ) -> WorkspaceRecordV1:
        return WorkspaceRecordV1(
            kind=kind,
            record_id=record_id,
            digest=digest,
            payload=payload,
        )

    def _targets(
        self,
        *,
        goal_id: str,
        referenced_entity_ids: tuple[str, ...],
        gaps: tuple[Any, ...],
    ) -> tuple[WorkspaceTargetV1, ...]:
        collected: dict[
            tuple[str | None, str],
            dict[str, object],
        ] = {}

        def add(
            *,
            entity_id: str | None,
            entity_type: str,
            canonical_name: str | None,
            provenance_refs: tuple[str, ...],
            source_ref: str,
        ) -> None:
            normalized_type = str(entity_type).strip().casefold()
            if not normalized_type:
                return
            key = (entity_id, normalized_type)
            current = collected.setdefault(
                key,
                {
                    "entity_id": entity_id,
                    "entity_type": normalized_type,
                    "canonical_name": canonical_name,
                    "provenance_refs": set(),
                    "source_refs": set(),
                },
            )
            if current["canonical_name"] is None and canonical_name is not None:
                current["canonical_name"] = canonical_name
            current["provenance_refs"].update(provenance_refs)
            current["source_refs"].add(source_ref)

        for entity_id in referenced_entity_ids:
            entity = self._goals.get_entity(entity_id)
            if entity is None:
                continue
            add(
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                canonical_name=entity.canonical_name,
                provenance_refs=entity.provenance_refs,
                source_ref=f"goal:{goal_id}",
            )

        for gap in gaps:
            entity = (
                None
                if gap.target_entity_id is None
                else self._goals.get_entity(gap.target_entity_id)
            )
            add(
                entity_id=gap.target_entity_id,
                entity_type=gap.target_entity_type,
                canonical_name=None if entity is None else entity.canonical_name,
                provenance_refs=() if entity is None else entity.provenance_refs,
                source_ref=f"capability_gap:{gap.gap_id}",
            )

        targets = []
        for (entity_id, entity_type), item in collected.items():
            target_key = (
                f"entity:{entity_id}"
                if entity_id is not None
                else f"type:{entity_type}"
            )
            targets.append(
                WorkspaceTargetV1(
                    target_key=target_key,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    canonical_name=item["canonical_name"],
                    provenance_refs=tuple(sorted(item["provenance_refs"])),
                    source_refs=tuple(sorted(item["source_refs"])),
                )
            )
        return tuple(sorted(targets, key=lambda item: item.target_key))

    def _linked_changes(self, *, goal: Any, gaps: tuple[Any, ...]) -> tuple[Any, ...]:
        by_id: dict[str, Any] = {}

        direct = self._changes.find_by_source(
            goal.source_session_id,
            goal.source_turn_id,
            self._changes.DEFAULT_PROCESS.key,
        )
        if direct is not None:
            by_id[direct.change_id] = direct

        for gap in gaps:
            if gap.motivating_goal_id != goal.goal_id:
                continue
            request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)
            change = self._changes.find_by_source(
                request.bridge_source_session_id,
                request.bridge_source_turn_id,
                OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
            )
            if change is not None:
                by_id[change.change_id] = change

        return tuple(sorted(by_id.values(), key=lambda item: item.change_id))

    def _change_snapshot(self, change: Any) -> WorkspaceChangeV1:
        artifacts = tuple(
            WorkspaceArtifactV1(
                artifact_id=item.artifact_id,
                kind=item.kind,
                revision=item.revision,
                digest=item.digest,
                payload=dict(item.payload),
                created_at=item.created_at,
            )
            for item in self._changes.list_artifacts(change.change_id)
        )
        stages = tuple(
            WorkspaceStageV1(
                stage_key=item.stage_key,
                attempt=item.attempt,
                work_id=item.work_id,
                plan_artifact_id=item.plan_artifact_id,
            )
            for item in self._changes.list_stages(change.change_id)
        )
        events = tuple(
            WorkspaceEventV1(
                event_key=str(item["event_key"]),
                kind=str(item["kind"]),
                detail=dict(item["detail"]),
                created_at=str(item["created_at"]),
            )
            for item in self._changes.list_events(change.change_id)
        )
        architecture = self._changes.latest_artifact(change.change_id, "architecture")
        return WorkspaceChangeV1(
            change_id=change.change_id,
            request=change.request,
            process_key=change.process_key,
            process_version=change.process_version,
            state=change.state.value,
            version=change.version,
            source_session_id=change.source_session_id,
            source_turn_id=change.source_turn_id,
            created_at=change.created_at,
            updated_at=change.updated_at,
            current_architecture_artifact_id=(
                None if architecture is None else architecture.artifact_id
            ),
            artifacts=artifacts,
            stages=stages,
            events=events,
        )

    def _work_snapshots(
        self,
        *,
        seed_work_ids: set[str],
    ) -> tuple[WorkspaceWorkV1, ...]:
        pending = list(sorted(seed_work_ids))
        loaded: dict[str, WorkspaceWorkV1] = {}

        while pending:
            work_id = pending.pop(0)
            if work_id in loaded:
                continue
            work = self._work.get(work_id)
            if work is None:
                continue
            for dependency_id in work.dependencies:
                if dependency_id not in loaded:
                    pending.append(dependency_id)
            steps = tuple(
                WorkspaceStepV1(
                    step_id=step.step_id,
                    kind=step.kind,
                    summary=step.summary,
                    state=step.state.value,
                    input_data=dict(step.input_data),
                    observation=dict(step.observation),
                    error=step.error,
                    created_at=step.created_at.isoformat(),
                    started_at=(
                        None
                        if step.started_at is None
                        else step.started_at.isoformat()
                    ),
                    completed_at=(
                        None
                        if step.completed_at is None
                        else step.completed_at.isoformat()
                    ),
                )
                for step in self._work.list_steps(work.work_id)
            )
            loaded[work.work_id] = WorkspaceWorkV1(
                work_id=work.work_id,
                work_type=work.work_type.value,
                state=work.state.value,
                source_session_id=work.source_session_id,
                source_turn_id=work.source_turn_id,
                dependencies=work.dependencies,
                status_detail=work.status_detail,
                result=dict(work.result),
                version=work.version,
                created_at=work.created_at.isoformat(),
                updated_at=work.updated_at.isoformat(),
                steps=steps,
            )

        return tuple(loaded[key] for key in sorted(loaded))

    def project(self, goal_id: str) -> ObjectiveWorkspaceV1:
        goal = self._goals.get_goal(str(goal_id).strip())
        if goal is None:
            raise GoalStoreError(f"unknown owner goal: {goal_id}")

        requirement_graph = self._goals.latest_requirement_graph(goal_id=goal.goal_id)
        plan = self._goals.latest_plan_for_goal(goal.goal_id)
        gaps = self._goals.list_gaps(goal_id=goal.goal_id)
        needs = self._goals.list_information_needs(goal_id=goal.goal_id)
        continuations = self._goals.list_continuations(goal_id=goal.goal_id)
        changes = self._linked_changes(goal=goal, gaps=gaps)
        change_snapshots = tuple(self._change_snapshot(item) for item in changes)

        seed_work_ids = {
            work_id
            for continuation in continuations
            for work_id in continuation.work_ids
        }
        for change in change_snapshots:
            seed_work_ids.update(stage.work_id for stage in change.stages)
            for artifact in change.artifacts:
                if artifact.kind != "gicc_capability_gap_link":
                    continue
                work_id = str(artifact.payload.get("acquisition_work_id") or "").strip()
                if work_id:
                    seed_work_ids.add(work_id)
        work_items = self._work_snapshots(seed_work_ids=seed_work_ids)

        blockers: set[str] = set()
        questions: set[str] = set()
        for gap in gaps:
            if gap.state is not CapabilityGapState.SATISFIED:
                blockers.add(f"capability_gap:{gap.gap_id}:{gap.state.value}")
        for need in needs:
            if need.state is not InformationNeedState.RESOLVED:
                blockers.add(
                    f"information_need:{need.information_need_id}:{need.state.value}"
                )
                questions.add(need.owner_question or need.required_fact)
        for continuation in continuations:
            if continuation.state is ContinuationState.BLOCKED:
                blockers.add(
                    "continuation:"
                    f"{continuation.continuation_id}:"
                    f"{continuation.blocked_by_type.value}:"
                    f"{continuation.blocked_by_id}"
                )
        for work in work_items:
            if work.state in {
                WorkState.WAITING_RESOURCE.value,
                WorkState.WAITING_DEPENDENCY.value,
                WorkState.WAITING_FOR_OWNER.value,
                WorkState.WAITING_UNTIL.value,
                WorkState.FAILED.value,
            }:
                blockers.add(f"work:{work.work_id}:{work.state}")

        current_architecture_refs = tuple(
            sorted(
                change.current_architecture_artifact_id
                for change in change_snapshots
                if change.current_architecture_artifact_id is not None
            )
        )
        workspace = ObjectiveWorkspaceV1(
            schema="objective_workspace.v1",
            goal=self._record(
                kind="owner_goal",
                record_id=goal.goal_id,
                digest=goal.digest,
                payload=goal.canonical_payload(),
            ),
            targets=self._targets(
                goal_id=goal.goal_id,
                referenced_entity_ids=goal.referenced_entity_ids,
                gaps=gaps,
            ),
            requirement_graph=(
                None
                if requirement_graph is None
                else self._record(
                    kind="capability_requirement_graph",
                    record_id=requirement_graph.graph_id,
                    digest=requirement_graph.digest,
                    payload=requirement_graph.canonical_payload(),
                )
            ),
            plan=(
                None
                if plan is None
                else self._record(
                    kind="plan",
                    record_id=plan.plan_id,
                    digest=plan.digest,
                    payload=plan.canonical_payload(),
                )
            ),
            capability_gaps=tuple(
                self._record(
                    kind="capability_gap",
                    record_id=gap.gap_id,
                    digest=gap.digest,
                    payload=gap.canonical_payload(),
                )
                for gap in gaps
            ),
            information_needs=tuple(
                self._record(
                    kind="information_need",
                    record_id=need.information_need_id,
                    digest=need.digest,
                    payload=need.canonical_payload(),
                )
                for need in needs
            ),
            continuations=tuple(
                self._record(
                    kind="goal_continuation",
                    record_id=continuation.continuation_id,
                    digest=continuation.digest,
                    payload=continuation.canonical_payload(),
                )
                for continuation in continuations
            ),
            changes=change_snapshots,
            work_items=work_items,
            current_architecture_refs=current_architecture_refs,
            observed_blockers=tuple(sorted(blockers)),
            open_questions=tuple(sorted(questions)),
            digest="pending",
        )
        return replace(
            workspace,
            digest=canonical_digest(workspace.canonical_payload()),
        )
