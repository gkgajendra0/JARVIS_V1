"""Reconcile change stages through the accepted WorkItem/DBOS substrate."""

from __future__ import annotations

from typing import Protocol

from jarvis.work.models import WorkItem, WorkPriority, WorkState, WorkType

from .models import ChangeConflict, ChangeState, EngineeringChange
from .store import ChangeStore


class WorkBackend(Protocol):
    def submit(self, work_id: str, *, priority: WorkPriority) -> str: ...


class ChangeCoordinator:
    def __init__(self, store: ChangeStore, backend: WorkBackend) -> None:
        self.store = store
        self.backend = backend

    def start(
        self, request: str, source_session_id: str, source_turn_id: str
    ) -> EngineeringChange:
        change = self.store.create(
            request=request,
            process_key="engineering.change",
            process_version=1,
            source_session_id=source_session_id,
            source_turn_id=source_turn_id,
        )
        return self.reconcile(change.change_id)

    def submit_stage(self, change_id: str, stage_key: str, attempt: int):
        change = self.store.require(change_id)
        stages = self.store.list_stages(change_id)
        existing = next(
            (s for s in stages if s.stage_key == stage_key and s.attempt == attempt),
            None,
        )
        if stage_key == "research":
            work_type = WorkType.RESEARCH
            request = change.request
            dependencies: tuple[str, ...] = ()
        elif stage_key == "development":
            work_type = WorkType.DEVELOPMENT
            architecture = self.store.latest_artifact(change_id, "architecture")
            if architecture is None:
                raise ChangeConflict("approved architecture is missing")
            request = (
                f"{change.request}\nApproved architecture revision "
                f"{architecture.revision}: {architecture.payload}"
            )
            research = [s.work_id for s in stages if s.stage_key == "research"]
            if not research:
                raise ChangeConflict("development requires completed research")
            dependencies = tuple(research)
        else:
            raise ChangeConflict("unregistered change stage")
        if existing is None:
            item = WorkItem(
                request=request,
                work_type=work_type,
                source_session_id=f"change:{change_id}",
                source_turn_id=f"{stage_key}:{attempt}",
                priority=WorkPriority.NORMAL,
                dependencies=dependencies,
            )
            stage = self.store.link_work(change_id, stage_key, attempt, item)
        else:
            stage = existing
            item = self.store.work.require(stage.work_id)
            # The gate is checked again before re-submitting after a restart.
            with self.store.work._lock, self.store.work._connect() as db:
                self.store._admit_stage(db, change, stage_key)
            if stage_key == "development" and (
                architecture is None
                or stage.plan_artifact_id != architecture.artifact_id
            ):
                raise ChangeConflict(
                    "development attempt belongs to an older architecture"
                )
        if not item.state.terminal:
            execution_id = self.backend.submit(item.work_id, priority=item.priority)
            if execution_id != item.work_id:
                raise ChangeConflict(
                    "durable backend returned mismatched work identity"
                )
        return stage

    def reconcile_for_work(self, work_id: str) -> EngineeringChange | None:
        stage = self.store.stage_for_work(work_id)
        return None if stage is None else self.reconcile(stage.change_id)

    def reconcile_active(self) -> None:
        for change_id in self.store.active_ids():
            self.reconcile(change_id)

    def reconcile(self, change_id: str) -> EngineeringChange:
        change = self.store.require(change_id)
        if change.state is ChangeState.PROPOSED:
            change = self.store.transition(
                change_id, ChangeState.RESEARCHING, expected_version=change.version
            )
        if change.state is ChangeState.RESEARCHING:
            stage = self.submit_stage(change_id, "research", 1)
            research = self.store.work.require(stage.work_id)
            if (
                research.state is WorkState.COMPLETED
                and self.store.latest_artifact(change_id, "architecture") is not None
            ):
                return self.store.transition(
                    change_id,
                    ChangeState.ARCHITECTURE_READY,
                    expected_version=change.version,
                )
        elif change.state is ChangeState.APPROVED_FOR_BUILD:
            architecture = self.store.latest_artifact(change_id, "architecture")
            if architecture is None:
                raise ChangeConflict("approved architecture is missing")
            attempts = [
                s
                for s in self.store.list_stages(change_id)
                if s.stage_key == "development"
            ]
            matching = next(
                (s for s in attempts if s.plan_artifact_id == architecture.artifact_id),
                None,
            )
            self.submit_stage(
                change_id,
                "development",
                matching.attempt
                if matching is not None
                else max((s.attempt for s in attempts), default=0) + 1,
            )
            return self.store.transition(
                change_id, ChangeState.DEVELOPING, expected_version=change.version
            )
        elif change.state is ChangeState.DEVELOPING:
            architecture = self.store.latest_artifact(change_id, "architecture")
            stage = next(
                (
                    s
                    for s in reversed(self.store.list_stages(change_id))
                    if s.stage_key == "development"
                    and architecture is not None
                    and s.plan_artifact_id == architecture.artifact_id
                ),
                None,
            )
            if stage is None:
                raise ChangeConflict("developing change has no WorkItem")
            item = self.store.work.require(stage.work_id)
            if item.state is WorkState.COMPLETED:
                with self.store.work._lock, self.store.work._connect() as db:
                    self.store._admit_stage(db, change, "development")
                return self.store.transition(
                    change_id,
                    ChangeState.VERIFYING,
                    expected_version=change.version,
                )
            if not item.state.terminal:
                self.submit_stage(change_id, "development", stage.attempt)
        return self.store.require(change_id)
