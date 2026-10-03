"""Governed development-tool adapter over the existing JARVIS Work executors."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import pathlib
from typing import Any

from jarvis.work.engine import (
    WorkActionRegistry,
    WorkOwnerInputRequired,
)
from jarvis.work.models import WorkItem, WorkState, WorkStep, WorkType
from jarvis.work.resources import ResourceLeaseManager, ResourcePressure
from jarvis.work.store import SQLiteWorkStore

from .contracts import DevelopmentTicketV1
from .protocol import DevelopmentToolSpecV1

_TOOL_TO_ACTION: dict[str, str] = {
    "prepare_workspace": "dev_prepare_workspace",
    "list_files": "dev_list_files",
    "read_file": "dev_read_file",
    "search_source": "dev_search",
    "write_file": "dev_write_file",
    "run_tests": "dev_run_tests",
    "inspect_diff": "dev_diff",
    "commit_candidate": "dev_commit",
    "status": "dev_status",
    "resolve_python_dependency": "dev_resolve_python_dependency",
    "bind_capability_manifest": "dev_bind_capability_manifest",
    "record_substrate_verification": "dev_verify_capability_substrate",
    "get_research_evidence": "dev_get_research_evidence",
}
_ACTION_TO_TOOL = {action: tool for tool, action in _TOOL_TO_ACTION.items()}


class DevelopmentToolPortError(RuntimeError):
    """Base error for the governed development-tool boundary."""


class DevelopmentToolDenied(DevelopmentToolPortError):
    """The ticket or canonical Work state does not authorize this tool call."""


class DevelopmentToolExecutionError(DevelopmentToolPortError):
    """A governed executor failed while processing a development tool call."""


class DevelopmentToolResourceBlocked(DevelopmentToolPortError):
    """A deterministic resource lease could not be admitted."""


class DevelopmentToolOwnerInputRequired(DevelopmentToolPortError):
    """A governed executor reached a genuinely owner-only boundary."""

    def __init__(
        self,
        question: str,
        *,
        sensitive: bool,
        input_key: str | None,
        resume_context: Mapping[str, Any],
    ) -> None:
        super().__init__(question)
        self.question = question
        self.sensitive = bool(sensitive)
        self.input_key = input_key
        self.resume_context = dict(resume_context)


def _path_within_writable_scope(path: str, scope: str) -> bool:
    """Match the same file/directory semantics as Phase-9 candidate verification."""

    if path == scope:
        return True
    normalized_scope = scope.rstrip("/")
    if not normalized_scope:
        return False
    if pathlib.PurePosixPath(normalized_scope).suffix == "":
        return path.startswith(normalized_scope + "/")
    return False


def _canonical_repository_path(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/")
    posix = pathlib.PurePosixPath(text)
    windows = pathlib.PureWindowsPath(text)
    if (
        not text
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or bool(windows.root)
        or ".." in posix.parts
        or text.startswith("-")
        or posix.as_posix() == "."
    ):
        raise DevelopmentToolDenied(
            "development write path must be a safe repository-relative path"
        )
    return posix.as_posix()


class WorkExecutorDevelopmentToolPort:
    """Expose existing DEVELOPMENT executors through a ticket-bounded tool surface.

    The adapter deliberately reuses the same source-owned executors as WorkEngine.
    Each invocation is persisted as a normal WorkStep so provider thread memory never
    becomes canonical execution truth.
    """

    def __init__(
        self,
        *,
        ticket: DevelopmentTicketV1,
        store: SQLiteWorkStore,
        actions: WorkActionRegistry,
        resources: ResourceLeaseManager | None = None,
        base_resource_keys: tuple[str, ...] = (),
        action_admission: Callable[[str], bool] | None = None,
    ) -> None:
        if not isinstance(ticket, DevelopmentTicketV1):
            raise TypeError("ticket must be DevelopmentTicketV1")
        if not isinstance(store, SQLiteWorkStore):
            raise TypeError("store must be SQLiteWorkStore")
        if not isinstance(actions, WorkActionRegistry):
            raise TypeError("actions must be WorkActionRegistry")
        self._ticket = ticket
        self._store = store
        self._actions = actions
        self._resources = resources or ResourceLeaseManager()
        self._base_resource_keys = self._resources.normalize(base_resource_keys)
        self._action_admission = action_admission

        unknown = [name for name in ticket.allowed_tools if name not in _TOOL_TO_ACTION]
        if unknown:
            raise ValueError(
                "development ticket contains unregistered tools: "
                + ", ".join(sorted(unknown))
            )
        for name in ticket.allowed_tools:
            self._actions.require(_TOOL_TO_ACTION[name], WorkType.DEVELOPMENT)

    @property
    def tool_names(self) -> tuple[str, ...]:
        return self._ticket.allowed_tools

    @property
    def tool_specs(self) -> tuple[DevelopmentToolSpecV1, ...]:
        specs: list[DevelopmentToolSpecV1] = []
        for name in self._ticket.allowed_tools:
            executor = self._actions.require(
                _TOOL_TO_ACTION[name],
                WorkType.DEVELOPMENT,
            )
            specs.append(
                DevelopmentToolSpecV1(
                    name=name,
                    description=executor.descriptor.description,
                    parameter_schema=dict(executor.descriptor.parameter_schema),
                )
            )
        return tuple(specs)

    def snapshot(self) -> Mapping[str, Any]:
        """Project durable development progress without depending on provider memory."""

        steps = self._store.list_steps(self._ticket.work_id)
        relevant: list[tuple[int, WorkStep, str]] = []
        for index, step in enumerate(steps):
            alias = _ACTION_TO_TOOL.get(step.kind)
            if alias is None or step.state.value != "completed":
                continue
            relevant.append((index, step, alias))

        last_write = max(
            (index for index, step, _ in relevant if step.kind == "dev_write_file"),
            default=-1,
        )
        last_passing_test = max(
            (
                index
                for index, step, _ in relevant
                if step.kind == "dev_run_tests"
                and step.observation.get("passed") is True
            ),
            default=-1,
        )
        last_diff = max(
            (index for index, step, _ in relevant if step.kind == "dev_diff"),
            default=-1,
        )
        last_commit = max(
            (
                index
                for index, step, _ in relevant
                if step.kind == "dev_commit"
                and step.observation.get("committed") is True
                and step.observation.get("clean") is True
            ),
            default=-1,
        )

        changed_files = tuple(
            sorted(
                {
                    str(step.observation.get("path") or "").strip()
                    for _, step, _ in relevant
                    if step.kind == "dev_write_file"
                    and str(step.observation.get("path") or "").strip()
                }
            )
        )
        passing_test_refs = tuple(
            f"workstep:{step.step_id}"
            for index, step, _ in relevant
            if step.kind == "dev_run_tests"
            and step.observation.get("passed") is True
            and index > last_write
        )
        candidate_revision = None
        candidate_branch = None
        if last_commit > last_diff > last_passing_test > last_write >= 0:
            commit_step = steps[last_commit]
            raw_commit = (
                str(commit_step.observation.get("commit") or "").strip().casefold()
            )
            if len(raw_commit) == 40 and all(
                char in "0123456789abcdef" for char in raw_commit
            ):
                candidate_revision = raw_commit
                candidate_branch = (
                    str(commit_step.observation.get("branch") or "").strip() or None
                )

        recent = [
            {
                "tool": alias,
                "step_id": step.step_id,
                "evidence_ref": f"workstep:{step.step_id}",
                "summary": step.summary,
                "observation": {
                    key: value
                    for key, value in step.observation.items()
                    if key
                    in {
                        "path",
                        "sha256",
                        "passed",
                        "timed_out",
                        "sandbox",
                        "committed",
                        "commit",
                        "branch",
                        "clean",
                        "manifest_id",
                        "manifest_digest",
                        "verification_artifact_id",
                        "verification_artifact_digest",
                    }
                },
            }
            for _, step, alias in relevant[-12:]
        ]
        return {
            "schema": "jarvis.development_progress.v1",
            "ticket_id": self._ticket.ticket_id,
            "ticket_digest": self._ticket.digest,
            "completed_tool_step_count": len(relevant),
            "changed_files": list(changed_files),
            "passing_test_evidence_refs": list(passing_test_refs),
            "candidate_revision": candidate_revision,
            "candidate_branch": candidate_branch,
            "recent_tool_evidence": recent,
        }

    def _require_active_work(self) -> WorkItem:
        work = self._store.require(self._ticket.work_id)
        if work.work_type is not WorkType.DEVELOPMENT:
            raise DevelopmentToolDenied(
                "development ticket is not bound to DEVELOPMENT work"
            )
        if work.state.terminal or work.state is WorkState.PAUSED:
            raise DevelopmentToolDenied(
                f"development work is not executable in state {work.state.value}"
            )
        if work.state is not WorkState.RUNNING:
            raise DevelopmentToolDenied(
                "development tools require an admitted RUNNING WorkItem"
            )
        admission = self._action_admission
        if admission is not None and not admission(work.work_id):
            raise DevelopmentToolDenied(
                "engineering change requires renewed owner review"
            )
        return work

    def _approved_test_targets(self) -> tuple[str, ...]:
        return tuple(
            item.removeprefix("pytest:").strip()
            for item in self._ticket.acceptance_criteria
            if item.startswith("pytest:") and item.removeprefix("pytest:").strip()
        )

    def _guard_test_targets(
        self,
        parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        approved = self._approved_test_targets()
        if not approved:
            raise DevelopmentToolDenied(
                "development ticket has no approved pytest targets"
            )
        requested = parameters.get("targets")
        if requested is None:
            return {**dict(parameters), "targets": list(approved)}
        if not isinstance(requested, list):
            raise DevelopmentToolDenied("development test targets must be an array")
        normalized = tuple(str(item).strip() for item in requested if str(item).strip())
        if not normalized or any(item not in set(approved) for item in normalized):
            raise DevelopmentToolDenied(
                "development tests must stay inside DevelopmentTicket acceptance targets"
            )
        return {**dict(parameters), "targets": list(normalized)}

    def _guard_commit(self) -> None:
        steps = self._store.list_steps(self._ticket.work_id)
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
        if last_write < 0:
            raise DevelopmentToolDenied(
                "candidate commit requires a staged source change"
            )
        if last_passing_test <= last_write:
            raise DevelopmentToolDenied(
                "candidate commit requires passing sandboxed tests after the latest edit"
            )
        if last_diff <= last_passing_test:
            raise DevelopmentToolDenied(
                "candidate commit requires final diff inspection after passing tests"
            )

    async def invoke(
        self,
        tool_name: str,
        parameters: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        name = str(tool_name).strip().casefold()
        if name not in self._ticket.allowed_tools:
            raise DevelopmentToolDenied(
                f"development tool is not authorized by this ticket: {name}"
            )
        if not isinstance(parameters, Mapping):
            raise TypeError("development tool parameters must be a mapping")

        work = self._require_active_work()
        action = _TOOL_TO_ACTION[name]
        if action == "dev_commit":
            self._guard_commit()

        executor = self._actions.require(action, WorkType.DEVELOPMENT)
        request_parameters = dict(parameters)
        if name == "run_tests":
            request_parameters = self._guard_test_targets(request_parameters)
        if name == "write_file":
            path = _canonical_repository_path(request_parameters.get("path"))
            if not any(
                _path_within_writable_scope(path, scope)
                for scope in self._ticket.writable_paths
            ):
                raise DevelopmentToolDenied(
                    "development write path is outside DevelopmentTicket authority"
                )
            request_parameters["path"] = path
        resource_provider = getattr(executor, "resource_keys", None)
        resource_keys = (
            tuple(resource_provider(work, dict(request_parameters)))
            if callable(resource_provider)
            else ()
        )
        lease_keys = self._resources.normalize(
            (*self._base_resource_keys, *resource_keys)
        )
        try:
            if lease_keys:
                async with self._resources.lease(lease_keys):
                    return await self._execute(
                        work=work,
                        executor=executor,
                        action=action,
                        alias=name,
                        parameters=request_parameters,
                    )
            return await self._execute(
                work=work,
                executor=executor,
                action=action,
                alias=name,
                parameters=request_parameters,
            )
        except ResourcePressure as exc:
            raise DevelopmentToolResourceBlocked(str(exc)) from exc

    async def _execute(
        self,
        *,
        work: WorkItem,
        executor: object,
        action: str,
        alias: str,
        parameters: dict[str, Any],
    ) -> Mapping[str, Any]:
        persisted_input_provider = getattr(executor, "persisted_input", None)
        persisted_input = (
            dict(persisted_input_provider(dict(parameters)))
            if callable(persisted_input_provider)
            else dict(parameters)
        )
        step = WorkStep(
            work_id=work.work_id,
            kind=action,
            summary=f"DevelopmentEngine tool: {alias}",
            input_data=persisted_input,
        )
        self._store.add_step(step)
        running = step.start()
        self._store.save_step(running)

        execute = getattr(executor, "execute", None)
        if not callable(execute):
            failed = running.fail("TypeError: development executor is not callable")
            self._store.save_step(failed)
            raise DevelopmentToolExecutionError("development executor is not callable")

        try:
            observation = await execute(
                work=work,
                parameters=dict(parameters),
            )
        except WorkOwnerInputRequired as exc:
            self._store.save_step(
                running.complete(
                    {
                        "needs_owner": True,
                        "question": exc.question,
                        "sensitive": exc.sensitive,
                        "input_key": exc.input_key,
                        "resume_context": dict(exc.resume_context),
                    }
                )
            )
            raise DevelopmentToolOwnerInputRequired(
                exc.question,
                sensitive=exc.sensitive,
                input_key=exc.input_key,
                resume_context=exc.resume_context,
            ) from exc
        except Exception as exc:
            self._store.save_step(running.fail(f"{type(exc).__name__}: {exc}"))
            raise DevelopmentToolExecutionError(
                f"{action} failed: {type(exc).__name__}: {exc}"
            ) from exc

        if not isinstance(observation, Mapping):
            self._store.save_step(
                running.fail(
                    "TypeError: development executor observation is not a mapping"
                )
            )
            raise DevelopmentToolExecutionError(
                "development executor returned an invalid observation"
            )
        result = dict(observation)
        if "_jarvis" in result:
            self._store.save_step(
                running.fail(
                    "ValueError: development executor used reserved _jarvis metadata key"
                )
            )
            raise DevelopmentToolExecutionError(
                "development executor used reserved _jarvis metadata key"
            )
        completed = running.complete(result)
        self._store.save_step(completed)
        return {
            **result,
            "_jarvis": {
                "tool": alias,
                "action": action,
                "step_id": step.step_id,
                "evidence_ref": f"workstep:{step.step_id}",
            },
        }
