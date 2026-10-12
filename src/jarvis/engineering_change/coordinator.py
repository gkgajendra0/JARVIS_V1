"""Reconcile change stages through the accepted WorkItem/DBOS substrate."""

from __future__ import annotations

import json
from typing import Protocol

from jarvis.work.execution import ensure_durable_execution
from jarvis.work.models import WorkItem, WorkPriority, WorkState

from .models import (
    ChangeConflict,
    ChangeState,
    EngineeringChange,
    ProcessStageRole,
    UnsupportedProcess,
)
from .outcomes import classify_work_system_outcome
from .store import ChangeStore


class WorkBackend(Protocol):
    def submit(self, work_id: str, *, priority: WorkPriority) -> str: ...


class ArchitectureSourceCompletionHandler(Protocol):
    process_key: str
    process_version: int

    def complete(
        self,
        *,
        change: EngineeringChange,
        stage,
        work: WorkItem,
    ) -> ChangeState | None: ...


class DevelopmentCompletionHandler(Protocol):
    process_key: str
    process_version: int

    def complete(
        self,
        *,
        change: EngineeringChange,
        stage,
        work: WorkItem,
    ) -> ChangeState | None: ...


class ChangeCoordinator:
    def __init__(
        self,
        store: ChangeStore,
        backend: WorkBackend,
        *,
        source_completion_handlers: tuple[
            ArchitectureSourceCompletionHandler, ...
        ] = (),
        development_completion_handlers: tuple[DevelopmentCompletionHandler, ...] = (),
    ) -> None:
        self.store = store
        self.backend = backend
        handlers: dict[tuple[str, int], ArchitectureSourceCompletionHandler] = {}
        for handler in source_completion_handlers:
            key = (handler.process_key, handler.process_version)
            if key in handlers:
                raise ValueError(
                    "duplicate architecture-source completion handler: "
                    f"{key[0]}/{key[1]}"
                )
            handlers[key] = handler
        self._source_completion_handlers = handlers

        development_handlers: dict[tuple[str, int], DevelopmentCompletionHandler] = {}
        for handler in development_completion_handlers:
            key = (handler.process_key, handler.process_version)
            if key in development_handlers:
                raise ValueError(
                    f"duplicate development completion handler: {key[0]}/{key[1]}"
                )
            development_handlers[key] = handler
        self._development_completion_handlers = development_handlers

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
            revision_request = self.store.latest_artifact(
                change_id,
                "architecture_revision_request",
            )
            if (
                revision_request is not None
                and int(revision_request.payload.get("source_attempt", 0)) == attempt
            ):
                reason = " ".join(
                    str(revision_request.payload.get("reason") or "").split()
                )
                if reason:
                    request += (
                        "\nThe previously approved architecture could not safely "
                        "continue during governed development. Re-research the capability "
                        "and derive a complete replacement architecture from current "
                        "evidence. Revision reason: " + reason
                    )
                previous_id = str(
                    revision_request.payload.get("previous_architecture_artifact_id")
                    or ""
                ).strip()
                previous = (
                    None if not previous_id else self.store.get_artifact(previous_id)
                )
                if previous is not None:
                    request += (
                        "\nCanonical previous approved architecture context: "
                        + json.dumps(
                            {
                                "artifact_id": previous.artifact_id,
                                "digest": previous.digest,
                                "payload": previous.payload,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            default=str,
                        )
                        + ". Preserve the owner target semantics while replacing only "
                        "the architecture elements that current evidence proves cannot "
                        "continue."
                    )
            dependencies: tuple[str, ...] = ()
        elif stage_contract.role is ProcessStageRole.DEVELOPMENT:
            architecture = self.store.latest_artifact(change_id, "architecture")
            if architecture is None:
                raise ChangeConflict("approved architecture is missing")
            request = (
                f"{change.request}\nApproved architecture artifact "
                f"{architecture.artifact_id} revision {architecture.revision} "
                f"digest {architecture.digest}: {architecture.payload}"
            )
            source_stage = process.architecture_source_stage
            authoritative_source = self.store.current_stage_attempt(
                change_id,
                source_stage.stage_key,
            )
            if authoritative_source is None:
                raise ChangeConflict(
                    "development requires authoritative architecture-source work"
                )
            source_item = self.store.work.require(authoritative_source.work_id)
            if source_item.state is not WorkState.COMPLETED:
                raise ChangeConflict(
                    "authoritative architecture-source work is not completed"
                )
            dependencies = (authoritative_source.work_id,)
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
            try:
                ensure_durable_execution(
                    store=self.store.work,
                    backend=self.backend,
                    item=item,
                )
            except RuntimeError as exc:
                if "durable backend must use work_id as execution_id" in str(exc):
                    raise ChangeConflict(
                        "durable backend returned mismatched work identity"
                    ) from exc
                raise
        return stage

    def prepare_failed_work_retry(
        self,
        work_id: str,
    ) -> EngineeringChange | None:
        """Reopen only the governing failed stage for an explicit Work retry."""

        return self.store.reopen_failed_stage_for_retry(work_id)

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
            source_attempt = 1
            revision_request = self.store.latest_artifact(
                change_id,
                "architecture_revision_request",
            )
            current_architecture = self.store.latest_artifact(
                change_id,
                "architecture",
            )
            if revision_request is not None:
                requested_attempt = revision_request.payload.get("source_attempt")
                matching_revision_stage = next(
                    (
                        item
                        for item in self.store.list_stages(change_id)
                        if item.stage_key == source_stage.stage_key
                        and item.attempt == requested_attempt
                    ),
                    None,
                )
                previous_architecture_id = revision_request.payload.get(
                    "previous_architecture_artifact_id"
                )
                revision_is_current = matching_revision_stage is not None or (
                    current_architecture is not None
                    and previous_architecture_id == current_architecture.artifact_id
                )
                if (
                    isinstance(requested_attempt, int)
                    and requested_attempt > 1
                    and revision_is_current
                ):
                    # Before the replacement architecture exists, the previous
                    # architecture proves this is the active revision request.
                    # After the handler has written a replacement but before the
                    # state transition commits, the already-linked source stage
                    # is the durable replay identity. Never fall back to attempt 1.
                    source_attempt = requested_attempt
            stage = self.submit_stage(
                change_id,
                source_stage.stage_key,
                source_attempt,
            )
            source_work = self.store.work.require(stage.work_id)
            if source_work.state in {WorkState.FAILED, WorkState.CANCELLED}:
                outcome = classify_work_system_outcome(
                    source_work,
                    steps=self.store.work.list_steps(source_work.work_id),
                )
                if outcome.terminal:
                    return self.store.transition(
                        change_id,
                        ChangeState.FAILED,
                        expected_version=change.version,
                    )
                return self.store.require(change_id)
            if source_work.state is WorkState.COMPLETED:
                handler = self._source_completion_handlers.get(
                    (change.process_key, change.process_version)
                )
                if handler is not None:
                    terminal_state = handler.complete(
                        change=change,
                        stage=stage,
                        work=source_work,
                    )
                    change = self.store.require(change_id)
                    if terminal_state is not None:
                        if change.state is not ChangeState.RESEARCHING:
                            return change
                        return self.store.transition(
                            change_id,
                            terminal_state,
                            expected_version=change.version,
                        )
                architecture = self.store.latest_artifact(
                    change_id,
                    "architecture",
                )
                if architecture is not None:
                    revision_request = self.store.latest_artifact(
                        change_id,
                        "architecture_revision_request",
                    )
                    produced_by_attempt = not (
                        revision_request is not None
                        and revision_request.payload.get("source_attempt")
                        == stage.attempt
                        and revision_request.payload.get(
                            "previous_architecture_artifact_id"
                        )
                        == architecture.artifact_id
                    )
                    if produced_by_attempt:
                        self.store.record_stage_outcome(
                            change_id,
                            stage.stage_key,
                            stage.attempt,
                            produced_artifact_id=architecture.artifact_id,
                            accepted=True,
                        )
                    change = self.store.require(change_id)
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
                (
                    stage
                    for stage in reversed(attempts)
                    if stage.plan_artifact_id == architecture.artifact_id
                    and not self.store.work.require(stage.work_id).state.terminal
                ),
                None,
            )
            self.submit_stage(
                change_id,
                development_stage.stage_key,
                matching.attempt
                if matching is not None
                else max((stage.attempt for stage in attempts), default=0) + 1,
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
                outcome = classify_work_system_outcome(
                    item,
                    steps=self.store.work.list_steps(item.work_id),
                )
                if outcome.terminal:
                    return self.store.transition(
                        change_id,
                        ChangeState.FAILED,
                        expected_version=change.version,
                    )
                return self.store.require(change_id)
            if item.state is WorkState.COMPLETED:
                with self.store.work._lock, self.store.work._connect() as db:
                    self.store._admit_stage(
                        db,
                        change,
                        development_stage.stage_key,
                    )
                handler = self._development_completion_handlers.get(
                    (change.process_key, change.process_version)
                )
                if handler is not None:
                    terminal_state = handler.complete(
                        change=change,
                        stage=stage,
                        work=item,
                    )
                    change = self.store.require(change_id)
                    if terminal_state is not None:
                        if change.state is not ChangeState.DEVELOPING:
                            if (
                                change.state is ChangeState.RESEARCHING
                                and terminal_state is ChangeState.RESEARCHING
                            ):
                                # A DEVELOPMENT completion handler may atomically
                                # reopen governed research (for example a typed
                                # DevelopmentEngine architecture revision). Complete
                                # that lifecycle escalation in the same reconciliation
                                # so the replacement source attempt is durably linked
                                # before returning to the caller.
                                return self.reconcile(change_id)
                            return change
                        return self.store.transition(
                            change_id,
                            terminal_state,
                            expected_version=change.version,
                        )
                change = self.store.require(change_id)
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
