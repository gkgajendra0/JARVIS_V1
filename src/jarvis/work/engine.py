"""Stepwise JARVIS-controlled work engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.work.brain import (
    BrainAction,
    BrainCoordinator,
    BrainPreempted,
    BrainRequest,
)
from jarvis.work.models import (
    WorkDeliveryKind,
    WorkItem,
    WorkState,
    WorkStep,
    WorkType,
)
from jarvis.work.resources import ResourceLeaseManager, ResourcePressure
from jarvis.work.store import SQLiteWorkStore

_MAX_CONSECUTIVE_FAILURES = 3


class WorkOwnerInputRequired(RuntimeError):
    """An executor cannot continue safely without a new owner decision/input."""

    def __init__(self, question: str) -> None:
        normalized = question.strip()
        if not normalized:
            raise ValueError("owner-input question must not be empty")
        super().__init__(normalized)
        self.question = normalized


class WorkActionExecutor(Protocol):
    descriptor: BrainAction
    work_types: frozenset[WorkType]

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]: ...


class WorkActionRegistry:
    def __init__(self, executors: tuple[WorkActionExecutor, ...]) -> None:
        by_name: dict[str, WorkActionExecutor] = {}
        for executor in executors:
            name = executor.descriptor.name
            if name in by_name:
                raise ValueError(f"duplicate work action: {name}")
            by_name[name] = executor
        self._by_name = by_name

    @property
    def supported_work_types(self) -> frozenset[WorkType]:
        return frozenset(
            work_type
            for executor in self._by_name.values()
            for work_type in executor.work_types
        )

    def actions_for(self, work_type: WorkType) -> tuple[BrainAction, ...]:
        return tuple(
            executor.descriptor
            for executor in self._by_name.values()
            if work_type in executor.work_types
        )

    def require(self, action: str, work_type: WorkType) -> WorkActionExecutor:
        executor = self._by_name.get(action)
        if executor is None or work_type not in executor.work_types:
            raise ValueError(
                f"work action is unavailable for {work_type.value}: {action}"
            )
        return executor


@dataclass(frozen=True, slots=True)
class WorkAdvanceResult:
    work_id: str
    state: WorkState
    progressed: bool
    owner_question: str | None = None


class WorkEngine:
    """Advance one WorkItem by one JARVIS-controlled reasoning/execution cycle."""

    def __init__(
        self,
        *,
        store: SQLiteWorkStore,
        brain: BrainCoordinator,
        actions: WorkActionRegistry,
        resources: ResourceLeaseManager | None = None,
        base_resource_keys: tuple[str, ...] = (),
    ) -> None:
        self._store = store
        self._brain = brain
        self._actions = actions
        self._resources = resources or ResourceLeaseManager()
        self._base_resource_keys = self._resources.normalize(base_resource_keys)

    def _make_running(self, work: WorkItem) -> WorkItem:
        if work.state in {
            WorkState.QUEUED,
            WorkState.RETRYING,
            WorkState.WAITING_RESOURCE,
        }:
            running = work.transition(WorkState.RUNNING, status_detail="reasoning")
            return self._store.save(running, expected_version=work.version)
        return work

    @staticmethod
    def _development_evidence_indices(
        steps: tuple[WorkStep, ...],
    ) -> tuple[int, int, int, int]:
        last_write = max(
            (
                index
                for index, step in enumerate(steps)
                if step.kind == "dev_write_file" and step.state.value == "completed"
            ),
            default=-1,
        )
        last_passing_test = max(
            (
                index
                for index, step in enumerate(steps)
                if step.kind == "dev_run_tests"
                and step.state.value == "completed"
                and step.observation.get("passed") is True
            ),
            default=-1,
        )
        last_diff = max(
            (
                index
                for index, step in enumerate(steps)
                if step.kind == "dev_diff" and step.state.value == "completed"
            ),
            default=-1,
        )
        last_clean_commit = max(
            (
                index
                for index, step in enumerate(steps)
                if step.kind == "dev_commit"
                and step.state.value == "completed"
                and step.observation.get("committed") is True
                and step.observation.get("clean") is True
            ),
            default=-1,
        )
        return last_write, last_passing_test, last_diff, last_clean_commit

    @staticmethod
    def _completion_guard(
        work: WorkItem,
        steps: tuple[WorkStep, ...],
    ) -> tuple[bool, str | None]:
        if work.work_type is WorkType.RESEARCH:
            successful = any(
                step.kind == "research_web"
                and step.state.value == "completed"
                and bool(step.observation.get("ok"))
                for step in steps
            )
            return (
                (True, None)
                if successful
                else (
                    False,
                    "fresh research evidence has not been successfully retrieved",
                )
            )
        if work.work_type is WorkType.DEVELOPMENT:
            (
                last_write,
                last_passing_test,
                last_diff,
                last_clean_commit,
            ) = WorkEngine._development_evidence_indices(steps)
            if last_write < 0:
                return False, "development work requires a staged source change"
            if last_passing_test <= last_write:
                return (
                    False,
                    "development work requires passing sandboxed tests after the latest edit",
                )
            if last_diff <= last_passing_test:
                return (
                    False,
                    "development work requires final diff inspection after passing tests",
                )
            if last_clean_commit <= last_diff:
                return (
                    False,
                    "development work must be committed after final diff inspection with a clean worktree",
                )
            return True, None
        return True, None

    def _record_completion_guard(
        self,
        work: WorkItem,
        reason: str,
    ) -> WorkAdvanceResult:
        step = WorkStep(
            work_id=work.work_id,
            kind="completion_guard",
            summary="JARVIS rejected premature completion",
            input_data={},
        )
        self._store.add_step(step)
        completed = step.start().complete({"allowed": False, "reason": reason})
        self._store.save_step(completed)
        latest = self._store.require(work.work_id)
        progressed = latest.with_progress(
            current_step_id=None,
            status_detail=f"completion deferred: {reason}",
        )
        self._store.save(progressed, expected_version=latest.version)
        return WorkAdvanceResult(
            work.work_id,
            progressed.state,
            progressed=True,
        )

    def _retry_or_fail(
        self,
        work: WorkItem,
        *,
        reason: str,
        current_step_id: str | None = None,
    ) -> WorkAdvanceResult:
        steps = self._store.list_steps(work.work_id)
        consecutive_failures = 0
        for step in reversed(steps):
            if step.state.value != "failed":
                break
            consecutive_failures += 1

        if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            failed = work.transition(
                WorkState.FAILED,
                status_detail=reason,
                current_step_id=current_step_id,
            )
            saved = self._store.save(failed, expected_version=work.version)
            self._store.enqueue_delivery(
                work=saved,
                kind=WorkDeliveryKind.FAILURE,
                message=reason,
                event_key=f"failure:{saved.version}",
            )
            return WorkAdvanceResult(saved.work_id, saved.state, progressed=True)

        retrying = work.transition(
            WorkState.RETRYING,
            status_detail=reason,
            current_step_id=current_step_id,
        )
        saved = self._store.save(retrying, expected_version=work.version)
        return WorkAdvanceResult(saved.work_id, saved.state, progressed=True)

    def _record_reasoning_failure(
        self,
        work: WorkItem,
        exc: Exception,
    ) -> WorkAdvanceResult:
        step = WorkStep(
            work_id=work.work_id,
            kind="brain_reasoning",
            summary="JARVIS brain reasoning failed",
            input_data={},
        )
        self._store.add_step(step)
        failed_step = step.start().fail(f"{type(exc).__name__}: {exc}")
        self._store.save_step(failed_step)
        latest = self._store.require(work.work_id)
        return self._retry_or_fail(
            latest,
            reason=f"brain reasoning failed: {type(exc).__name__}",
            current_step_id=step.step_id,
        )

    def _check_dependencies(self, work: WorkItem) -> WorkAdvanceResult | None:
        if not work.dependencies:
            if work.state is WorkState.WAITING_DEPENDENCY:
                resumed = work.transition(
                    WorkState.RUNNING,
                    status_detail="dependencies satisfied",
                )
                self._store.save(resumed, expected_version=work.version)
            return None

        dependencies: list[WorkItem] = []
        for dependency_id in work.dependencies:
            dependency = self._store.get(dependency_id)
            if dependency is None:
                failed = work.transition(
                    WorkState.FAILED,
                    status_detail=f"dependency is missing: {dependency_id}",
                )
                saved = self._store.save(failed, expected_version=work.version)
                self._store.enqueue_delivery(
                    work=saved,
                    kind=WorkDeliveryKind.FAILURE,
                    message=saved.status_detail or "Background work dependency failed.",
                    event_key=f"failure:{saved.version}",
                )
                return WorkAdvanceResult(saved.work_id, saved.state, progressed=True)
            dependencies.append(dependency)

        failed_dependencies = [
            item
            for item in dependencies
            if item.state in {WorkState.FAILED, WorkState.CANCELLED}
        ]
        if failed_dependencies:
            names = ", ".join(item.work_id for item in failed_dependencies)
            failed = work.transition(
                WorkState.FAILED,
                status_detail=f"dependency did not complete successfully: {names}",
            )
            saved = self._store.save(failed, expected_version=work.version)
            self._store.enqueue_delivery(
                work=saved,
                kind=WorkDeliveryKind.FAILURE,
                message=saved.status_detail or "Background work dependency failed.",
                event_key=f"failure:{saved.version}",
            )
            return WorkAdvanceResult(saved.work_id, saved.state, progressed=True)

        pending = [
            item for item in dependencies if item.state is not WorkState.COMPLETED
        ]
        if pending:
            if work.state is WorkState.WAITING_DEPENDENCY:
                return WorkAdvanceResult(work.work_id, work.state, progressed=False)
            waiting = work.transition(
                WorkState.WAITING_DEPENDENCY,
                status_detail="waiting for dependencies: "
                + ", ".join(item.work_id for item in pending),
            )
            saved = self._store.save(waiting, expected_version=work.version)
            return WorkAdvanceResult(saved.work_id, saved.state, progressed=True)

        if work.state is WorkState.WAITING_DEPENDENCY:
            resumed = work.transition(
                WorkState.RUNNING,
                status_detail="dependencies satisfied",
            )
            self._store.save(resumed, expected_version=work.version)
        return None

    def _ensure_state_delivery(self, work: WorkItem) -> None:
        if work.state is WorkState.COMPLETED:
            self._store.enqueue_delivery(
                work=work,
                kind=WorkDeliveryKind.COMPLETION,
                message=work.status_detail or "Background work completed.",
                event_key="completion",
            )
        elif work.state is WorkState.FAILED:
            self._store.enqueue_delivery(
                work=work,
                kind=WorkDeliveryKind.FAILURE,
                message=work.status_detail or "Background work failed.",
                event_key=f"failure:{work.version}",
            )
        elif work.state is WorkState.WAITING_FOR_OWNER:
            self._store.enqueue_delivery(
                work=work,
                kind=WorkDeliveryKind.OWNER_INPUT,
                message=work.status_detail or "This work needs your input.",
                event_key=f"owner:{work.version}",
            )

    def reconcile_interrupted_steps(self) -> tuple[str, ...]:
        """Fail closed on executor steps whose outcome was not durably recorded."""

        reconciled: list[str] = []
        active = self._store.list(
            states=(
                WorkState.QUEUED,
                WorkState.RUNNING,
                WorkState.WAITING_RESOURCE,
                WorkState.WAITING_DEPENDENCY,
                WorkState.WAITING_UNTIL,
                WorkState.WAITING_FOR_OWNER,
                WorkState.PAUSED,
                WorkState.RETRYING,
            ),
            limit=10_000,
        )
        for work in active:
            running_steps = [
                step
                for step in self._store.list_steps(work.work_id)
                if step.state.value == "running"
            ]
            if not running_steps:
                continue

            for step in running_steps:
                self._store.save_step(
                    step.interrupt(
                        "process interrupted before executor outcome was durably recorded"
                    )
                )

            latest = self._store.require(work.work_id)
            last_step = running_steps[-1]
            detail = (
                "A background step was interrupted by process restart and its outcome "
                "is unverified. Review the task before retrying."
            )
            if latest.state is WorkState.PAUSED:
                updated = latest.with_progress(
                    current_step_id=last_step.step_id,
                    status_detail=detail,
                )
                self._store.save(updated, expected_version=latest.version)
            elif not latest.state.terminal:
                waiting = latest.transition(
                    WorkState.WAITING_FOR_OWNER,
                    status_detail=detail,
                    current_step_id=last_step.step_id,
                )
                saved = self._store.save(waiting, expected_version=latest.version)
                self._ensure_state_delivery(saved)
            reconciled.append(work.work_id)

        return tuple(reconciled)

    async def advance(self, work_id: str) -> WorkAdvanceResult:
        work = self._store.require(work_id)
        if work.state.terminal:
            self._ensure_state_delivery(work)
            return WorkAdvanceResult(work.work_id, work.state, progressed=False)
        if work.state is WorkState.PAUSED:
            return WorkAdvanceResult(work.work_id, work.state, progressed=False)

        dependency_result = self._check_dependencies(work)
        if dependency_result is not None:
            return dependency_result
        work = self._store.require(work_id)

        if work.state.terminal or work.state is WorkState.PAUSED:
            return WorkAdvanceResult(work.work_id, work.state, progressed=False)
        if work.state is WorkState.WAITING_FOR_OWNER:
            self._ensure_state_delivery(work)
            return WorkAdvanceResult(
                work.work_id,
                work.state,
                progressed=False,
                owner_question=work.status_detail,
            )

        work = self._make_running(work)
        actions = self._actions.actions_for(work.work_type)
        if not actions:
            failed = work.transition(
                WorkState.FAILED,
                status_detail=f"no registered executor for {work.work_type.value}",
            )
            self._store.save(failed, expected_version=work.version)
            self._store.enqueue_delivery(
                work=failed,
                kind=WorkDeliveryKind.FAILURE,
                message=failed.status_detail or "Background work failed.",
                event_key=f"failure:{failed.version}",
            )
            return WorkAdvanceResult(work.work_id, failed.state, progressed=True)

        steps = self._store.list_steps(work.work_id)
        try:
            decision = await self._brain.decide(
                BrainRequest(
                    work=work,
                    recent_steps=steps[-12:],
                    purpose="choose the next bounded step for this JARVIS-owned work item",
                    allowed_actions=actions,
                )
            )
        except BrainPreempted:
            latest = self._store.require(work.work_id)
            if latest.state.terminal or latest.state is WorkState.PAUSED:
                return WorkAdvanceResult(
                    latest.work_id,
                    latest.state,
                    progressed=False,
                )
            waiting = latest.transition(
                WorkState.WAITING_RESOURCE,
                status_detail="waiting for interactive brain",
                current_step_id=latest.current_step_id,
            )
            saved = self._store.save(waiting, expected_version=latest.version)
            return WorkAdvanceResult(saved.work_id, saved.state, progressed=True)
        except Exception as exc:  # noqa: BLE001 - provider boundary must fail closed
            latest = self._store.require(work.work_id)
            if latest.state.terminal or latest.state is WorkState.PAUSED:
                return WorkAdvanceResult(
                    latest.work_id,
                    latest.state,
                    progressed=False,
                )
            return self._record_reasoning_failure(latest, exc)

        latest = self._store.require(work.work_id)
        if latest.state.terminal or latest.state is WorkState.PAUSED:
            return WorkAdvanceResult(latest.work_id, latest.state, progressed=False)
        if latest.version != work.version:
            work = latest

        if decision.goal_complete:
            allowed, guard_reason = self._completion_guard(work, steps)
            if not allowed:
                assert guard_reason is not None
                return self._record_completion_guard(work, guard_reason)
            result_payload: dict[str, Any] = {"summary": decision.summary}
            if work.work_type is WorkType.DEVELOPMENT:
                commit_step = next(
                    (
                        step
                        for step in reversed(steps)
                        if step.kind == "dev_commit" and step.state.value == "completed"
                    ),
                    None,
                )
                test_step = next(
                    (
                        step
                        for step in reversed(steps)
                        if step.kind == "dev_run_tests"
                        and step.state.value == "completed"
                        and step.observation.get("passed") is True
                    ),
                    None,
                )
                if commit_step is not None:
                    result_payload["branch"] = commit_step.observation.get("branch")
                    result_payload["commit"] = commit_step.observation.get("commit")
                if test_step is not None:
                    result_payload["verification"] = {
                        "passed": True,
                        "sandbox": test_step.observation.get("sandbox"),
                    }
            completed = work.transition(
                WorkState.COMPLETED,
                status_detail=decision.summary,
                result=result_payload,
            )
            self._store.save(completed, expected_version=work.version)
            self._store.enqueue_delivery(
                work=completed,
                kind=WorkDeliveryKind.COMPLETION,
                message=decision.summary,
                event_key="completion",
            )
            return WorkAdvanceResult(work.work_id, completed.state, progressed=True)

        if decision.needs_owner:
            waiting = work.transition(
                WorkState.WAITING_FOR_OWNER,
                status_detail=decision.owner_question,
            )
            self._store.save(waiting, expected_version=work.version)
            self._store.enqueue_delivery(
                work=waiting,
                kind=WorkDeliveryKind.OWNER_INPUT,
                message=decision.owner_question or "This work needs your input.",
                event_key=f"owner:{waiting.version}",
            )
            return WorkAdvanceResult(
                work.work_id,
                waiting.state,
                progressed=True,
                owner_question=decision.owner_question,
            )

        assert decision.action is not None
        if decision.action == "dev_commit":
            (
                last_write,
                last_passing_test,
                last_diff,
                _,
            ) = self._development_evidence_indices(steps)
            if last_write < 0:
                return self._record_completion_guard(
                    work,
                    "local development commit requires a staged source change",
                )
            if last_passing_test <= last_write:
                return self._record_completion_guard(
                    work,
                    "local development commit requires passing sandboxed tests after the latest edit",
                )
            if last_diff <= last_passing_test:
                return self._record_completion_guard(
                    work,
                    "local development commit requires final diff inspection after passing tests",
                )
        executor = self._actions.require(decision.action, work.work_type)
        resource_provider = getattr(executor, "resource_keys", None)
        resource_keys = (
            tuple(resource_provider(work, dict(decision.parameters)))
            if callable(resource_provider)
            else ()
        )
        resource_keys = self._resources.normalize(
            (*self._base_resource_keys, *resource_keys)
        )

        if resource_keys:
            waiting = work.transition(
                WorkState.WAITING_RESOURCE,
                status_detail="waiting for resources: " + ", ".join(resource_keys),
            )
            self._store.save(waiting, expected_version=work.version)
            try:
                async with self._resources.lease(resource_keys):
                    latest = self._store.require(work.work_id)
                    if latest.state.terminal or latest.state is WorkState.PAUSED:
                        return WorkAdvanceResult(
                            latest.work_id,
                            latest.state,
                            progressed=False,
                        )
                    running = latest.transition(
                        WorkState.RUNNING,
                        status_detail=decision.summary,
                    )
                    work = self._store.save(running, expected_version=latest.version)
                    return await self._execute_action(
                        work=work,
                        executor=executor,
                        decision_action=decision.action,
                        decision_summary=decision.summary,
                        decision_parameters=dict(decision.parameters),
                    )
            except ResourcePressure as exc:
                latest = self._store.require(work.work_id)
                if latest.state.terminal or latest.state is WorkState.PAUSED:
                    return WorkAdvanceResult(
                        latest.work_id,
                        latest.state,
                        progressed=False,
                    )
                if latest.state is WorkState.WAITING_RESOURCE:
                    updated = latest.with_progress(
                        current_step_id=latest.current_step_id,
                        status_detail=f"waiting for resource pressure: {exc}",
                    )
                    self._store.save(updated, expected_version=latest.version)
                    latest = updated
                return WorkAdvanceResult(
                    latest.work_id,
                    latest.state,
                    progressed=False,
                )

        return await self._execute_action(
            work=work,
            executor=executor,
            decision_action=decision.action,
            decision_summary=decision.summary,
            decision_parameters=dict(decision.parameters),
        )

    async def _execute_action(
        self,
        *,
        work: WorkItem,
        executor: WorkActionExecutor,
        decision_action: str,
        decision_summary: str,
        decision_parameters: dict[str, Any],
    ) -> WorkAdvanceResult:
        persistence_provider = getattr(executor, "persisted_input", None)
        persisted_input = (
            dict(persistence_provider(dict(decision_parameters)))
            if callable(persistence_provider)
            else dict(decision_parameters)
        )
        step = WorkStep(
            work_id=work.work_id,
            kind=decision_action,
            summary=decision_summary,
            input_data=persisted_input,
        )
        self._store.add_step(step)
        running_step = step.start()
        self._store.save_step(running_step)
        with_step = work.with_progress(
            current_step_id=step.step_id,
            status_detail=decision_summary,
        )
        self._store.save(with_step, expected_version=work.version)

        try:
            observation = await executor.execute(
                work=with_step,
                parameters=dict(decision_parameters),
            )
        except WorkOwnerInputRequired as exc:
            waiting_step = running_step.complete(
                {"needs_owner": True, "question": exc.question}
            )
            self._store.save_step(waiting_step)
            latest = self._store.require(work.work_id)
            if latest.state.terminal or latest.state is WorkState.PAUSED:
                return WorkAdvanceResult(
                    latest.work_id,
                    latest.state,
                    progressed=False,
                )
            waiting = latest.transition(
                WorkState.WAITING_FOR_OWNER,
                status_detail=exc.question,
                current_step_id=step.step_id,
            )
            saved = self._store.save(waiting, expected_version=latest.version)
            self._store.enqueue_delivery(
                work=saved,
                kind=WorkDeliveryKind.OWNER_INPUT,
                message=exc.question,
                event_key=f"owner:{saved.version}",
            )
            return WorkAdvanceResult(
                saved.work_id,
                saved.state,
                progressed=True,
                owner_question=exc.question,
            )
        except Exception as exc:  # noqa: BLE001 - executor boundary must contain faults
            failed_step = running_step.fail(type(exc).__name__ + ": " + str(exc))
            self._store.save_step(failed_step)
            latest = self._store.require(work.work_id)
            if latest.state.terminal or latest.state is WorkState.PAUSED:
                return WorkAdvanceResult(
                    latest.work_id,
                    latest.state,
                    progressed=False,
                )
            return self._retry_or_fail(
                latest,
                reason=f"step failed: {decision_action}",
                current_step_id=step.step_id,
            )

        completed_step = running_step.complete(observation)
        self._store.save_step(completed_step)
        latest = self._store.require(work.work_id)
        if latest.state.terminal:
            return WorkAdvanceResult(
                latest.work_id,
                latest.state,
                progressed=False,
            )
        progressed = latest.with_progress(
            current_step_id=None,
            status_detail=f"completed step: {decision_action}",
        )
        self._store.save(progressed, expected_version=latest.version)
        return WorkAdvanceResult(work.work_id, progressed.state, progressed=True)

    def fail(self, work_id: str, reason: str) -> WorkItem:
        work = self._store.require(work_id)
        if work.state.terminal:
            return work
        normalized = reason.strip()
        if not normalized:
            raise ValueError("work failure reason must not be empty")
        failed = work.transition(
            WorkState.FAILED,
            status_detail=normalized,
            current_step_id=work.current_step_id,
        )
        saved = self._store.save(failed, expected_version=work.version)
        self._store.enqueue_delivery(
            work=saved,
            kind=WorkDeliveryKind.FAILURE,
            message=normalized,
            event_key=f"failure:{saved.version}",
        )
        return saved

    def apply_owner_input(self, work_id: str, response: str) -> WorkItem:
        normalized = response.strip()
        if not normalized:
            raise ValueError("owner response must not be empty")
        work = self._store.require(work_id)
        if work.state is not WorkState.WAITING_FOR_OWNER:
            already_applied = any(
                step.kind == "owner_input"
                and step.state.value == "completed"
                and step.observation.get("response") == normalized
                for step in reversed(self._store.list_steps(work_id))
            )
            if already_applied:
                return work
            raise ValueError("work is not waiting for owner input")
        step = WorkStep(
            work_id=work.work_id,
            kind="owner_input",
            summary="Owner supplied requested input",
            input_data={},
        )
        self._store.add_step(step)
        completed = step.start().complete({"response": normalized})
        self._store.save_step(completed)
        resumed = work.transition(
            WorkState.RUNNING,
            status_detail="owner input received",
        )
        return self._store.save(resumed, expected_version=work.version)
