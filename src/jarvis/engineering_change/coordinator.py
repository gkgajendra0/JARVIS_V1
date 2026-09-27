"""Reconcile change stages through the accepted WorkItem/DBOS substrate."""

from __future__ import annotations

from typing import Protocol

from jarvis.work.models import WorkItem, WorkPriority, WorkState

from .models import (
    ChangeArtifact,
    ChangeConflict,
    ChangeState,
    EngineeringChange,
    ProcessStageRole,
    UnsupportedProcess,
)
from .store import ChangeStore


class WorkBackend(Protocol):
    def submit(self, work_id: str, *, priority: WorkPriority) -> str: ...


class ChangeProcessAdapter(Protocol):
    """Optional process-specific derivation while lifecycle/gates remain generic."""

    process_key: str
    process_version: int

    def derive_architecture(
        self,
        *,
        store: ChangeStore,
        change: EngineeringChange,
        source_work: WorkItem,
    ) -> ChangeArtifact | None: ...

    def build_development_request(
        self,
        *,
        store: ChangeStore,
        change: EngineeringChange,
        architecture: ChangeArtifact,
        source_work_ids: tuple[str, ...],
    ) -> str: ...


class ChangeCoordinator:
    def __init__(
        self,
        store: ChangeStore,
        backend: WorkBackend,
        *,
        process_adapters: tuple[ChangeProcessAdapter, ...] = (),
    ) -> None:
        self.store = store
        self.backend = backend
        self._process_adapters: dict[
            tuple[str, int],
            ChangeProcessAdapter,
        ] = {}
        for adapter in process_adapters:
            identity = (
                str(adapter.process_key).strip().lower(),
                int(adapter.process_version),
            )
            if not identity[0] or identity[1] < 1:
                raise ValueError("process adapter identity must be normalized")
            if identity in self._process_adapters:
                raise ValueError("duplicate change process adapter")
            self._process_adapters[identity] = adapter

    def _process_adapter(
        self,
        change: EngineeringChange,
    ) -> ChangeProcessAdapter | None:
        return self._process_adapters.get(
            (change.process_key, change.process_version)
        )

    def start(
        self,
        request: str,
        source_session_id: str,
        source_turn_id: str,
        *,
        process_key: str = "engineering.change",
        process_version: int = 1,
    ) -> EngineeringChange:
        change = self.store.create(
            request=request,
            process_key=process_key,
            process_version=process_version,
            source_session_id=source_session_id,
            source_turn_id=source_turn_id,
        )
        return self.reconcile(change.change_id)

    def submit_stage(self, change_id: str, stage_key: str, attempt: int):
        change = self.store.require(change_id)
        process = self.store.process_contract(
            change.process_key,
            change.process_version,
        )
        stage_contract = process.stage_for_key(stage_key)
        stages = self.store.list_stages(change_id)
        existing = next(
            (s for s in stages if s.stage_key == stage_key and s.attempt == attempt),
            None,
        )

        architecture = None
        if stage_contract.role is ProcessStageRole.ARCHITECTURE_SOURCE:
            request = change.request
            dependencies: tuple[str, ...] = ()
        elif stage_contract.role is ProcessStageRole.DEVELOPMENT:
            architecture = self.store.latest_artifact(change_id, "architecture")
            if architecture is None:
                raise ChangeConflict("approved architecture is missing")
            source_stage = process.architecture_source_stage
            source_work = [
                s.work_id for s in stages if s.stage_key == source_stage.stage_key
            ]
            if not source_work:
                raise ChangeConflict(
                    "development requires completed architecture-source work"
                )
            dependencies = tuple(source_work)
            adapter = self._process_adapter(change)
            if adapter is None:
                request = (
                    f"{change.request}\nApproved architecture revision "
                    f"{architecture.revision}: {architecture.payload}"
                )
            else:
                request = adapter.build_development_request(
                    store=self.store,
                    change=change,
                    architecture=architecture,
                    source_work_ids=dependencies,
                )
        else:  # pragma: no cover - ProcessContract validation owns known roles
            raise ChangeConflict("unregistered change stage role")

        if existing is None:
            item = WorkItem(
                request=request,
                work_type=stage_contract.work_type,
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
            if stage_contract.role is ProcessStageRole.DEVELOPMENT and (
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
            try:
                self.reconcile(change_id)
            except UnsupportedProcess:
                # A removed process handler must not stop unrelated WorkItems.
                # The per-action admission check refuses all affected stages.
                continue

    def reconcile(self, change_id: str) -> EngineeringChange:
        change = self.store.require(change_id)
        process = self.store.process_contract(
            change.process_key,
            change.process_version,
        )
        source_stage = process.architecture_source_stage
        development_stage = process.development_stage

        if change.state is ChangeState.PROPOSED:
            change = self.store.transition(
                change_id, ChangeState.RESEARCHING, expected_version=change.version
            )

        if change.state is ChangeState.RESEARCHING:
            stage = self.submit_stage(change_id, source_stage.stage_key, 1)
            source_work = self.store.work.require(stage.work_id)
            if source_work.state in {WorkState.FAILED, WorkState.CANCELLED}:
                return self.store.transition(
                    change_id, ChangeState.FAILED, expected_version=change.version
                )
            if source_work.state is WorkState.COMPLETED:
                architecture = self.store.latest_artifact(
                    change_id,
                    "architecture",
                )
                adapter = self._process_adapter(change)
                if architecture is None and adapter is not None:
                    architecture = adapter.derive_architecture(
                        store=self.store,
                        change=change,
                        source_work=source_work,
                    )
                if architecture is not None:
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
                if s.stage_key == development_stage.stage_key
            ]
            matching = next(
                (s for s in attempts if s.plan_artifact_id == architecture.artifact_id),
                None,
            )
            self.submit_stage(
                change_id,
                development_stage.stage_key,
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
                    if s.stage_key == development_stage.stage_key
                    and architecture is not None
                    and s.plan_artifact_id == architecture.artifact_id
                ),
                None,
            )
            if stage is None:
                raise ChangeConflict("developing change has no WorkItem")
            item = self.store.work.require(stage.work_id)
            if item.state in {WorkState.FAILED, WorkState.CANCELLED}:
                return self.store.transition(
                    change_id, ChangeState.FAILED, expected_version=change.version
                )
            if item.state is WorkState.COMPLETED:
                with self.store.work._lock, self.store.work._connect() as db:
                    self.store._admit_stage(
                        db,
                        change,
                        development_stage.stage_key,
                    )
                return self.store.transition(
                    change_id,
                    ChangeState.VERIFYING,
                    expected_version=change.version,
                )
            if not item.state.terminal:
                self.submit_stage(
                    change_id,
                    development_stage.stage_key,
                    stage.attempt,
                )
        return self.store.require(change_id)
