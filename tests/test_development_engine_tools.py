from __future__ import annotations

from typing import Any

import pytest

from jarvis.development_engine import (
    DevelopmentTicketV1,
    DevelopmentToolDenied,
    DevelopmentToolOwnerInputRequired,
    WorkExecutorDevelopmentToolPort,
)
from jarvis.work.brain import BrainAction
from jarvis.work.engine import (
    WorkActionRegistry,
    WorkOwnerInputRequired,
)
from jarvis.work.models import WorkItem, WorkState, WorkStep, WorkType
from jarvis.work.resources import ResourceLeaseManager
from jarvis.work.store import SQLiteWorkStore


class FakeExecutor:
    descriptor = BrainAction(
        name="dev_read_file",
        description="Read a fake file.",
        parameter_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ("cpu",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "work_id": work.work_id,
            "path": parameters["path"],
            "ok": True,
        }


class WriteExecutor:
    descriptor = BrainAction(
        name="dev_write_file",
        description="Write a synthetic file.",
        parameter_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["path", "text"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del work
        return {
            "path": parameters["path"],
            "sha256": "f" * 64,
            "written": True,
        }


class OwnerExecutor:
    descriptor = BrainAction(
        name="dev_run_tests",
        description="Synthetic owner boundary.",
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del work, parameters
        raise WorkOwnerInputRequired(
            "A protected value is required.",
            sensitive=True,
            input_key="demo_secret",
            resume_context={"kind": "secret"},
        )


class CommitExecutor:
    descriptor = BrainAction(
        name="dev_commit",
        description="Synthetic commit.",
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del work, parameters
        return {"committed": True}


def _ticket(
    *,
    tools: tuple[str, ...],
    writable_paths: tuple[str, ...] = (),
) -> DevelopmentTicketV1:
    return DevelopmentTicketV1.create(
        request="Develop the approved capability.",
        work_id="work_demo",
        engineering_change_id="change_demo",
        goal_id="goal_demo",
        goal_digest="a" * 64,
        architecture_artifact_id="artifact_demo",
        architecture_digest="b" * 64,
        base_revision="c" * 40,
        workspace_id="workspace_demo",
        required_operations=("operation.demo",),
        acceptance_criteria=("pytest:tests/test_demo.py",),
        allowed_tools=tools,
        writable_paths=writable_paths,
    )


def _running_store(tmp_path) -> SQLiteWorkStore:
    store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    item = WorkItem(
        request="develop capability",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="session",
        source_turn_id="turn",
        work_id="work_demo",
    )
    store.create(item)
    store.save(
        item.transition(WorkState.RUNNING, status_detail="engineering"),
        expected_version=item.version,
    )
    return store


@pytest.mark.asyncio
async def test_tool_port_reuses_executor_and_persists_work_step(tmp_path) -> None:
    store = _running_store(tmp_path)
    actions = WorkActionRegistry((FakeExecutor(),))
    port = WorkExecutorDevelopmentToolPort(
        ticket=_ticket(tools=("read_file",)),
        store=store,
        actions=actions,
        resources=ResourceLeaseManager({"cpu": 1}),
    )

    result = await port.invoke("read_file", {"path": "src/demo.py"})

    assert result["ok"] is True
    assert result["_jarvis"]["tool"] == "read_file"
    assert result["_jarvis"]["action"] == "dev_read_file"
    steps = store.list_steps("work_demo")
    assert result["_jarvis"]["step_id"] == steps[0].step_id
    assert result["_jarvis"]["evidence_ref"] == f"workstep:{steps[0].step_id}"
    assert len(steps) == 1
    assert steps[0].kind == "dev_read_file"
    assert steps[0].state.value == "completed"
    assert steps[0].observation["path"] == "src/demo.py"
    assert port.tool_names == ("read_file",)
    assert port.tool_specs[0].name == "read_file"


@pytest.mark.asyncio
async def test_tool_port_rejects_tool_not_on_ticket(tmp_path) -> None:
    store = _running_store(tmp_path)
    port = WorkExecutorDevelopmentToolPort(
        ticket=_ticket(tools=("read_file",)),
        store=store,
        actions=WorkActionRegistry((FakeExecutor(),)),
        resources=ResourceLeaseManager({"cpu": 1}),
    )

    with pytest.raises(DevelopmentToolDenied, match="not authorized"):
        await port.invoke("write_file", {"path": "src/demo.py"})


@pytest.mark.asyncio
async def test_tool_port_enforces_exact_ticket_writable_paths(tmp_path) -> None:
    store = _running_store(tmp_path)
    port = WorkExecutorDevelopmentToolPort(
        ticket=_ticket(
            tools=("write_file",),
            writable_paths=("src/approved.py",),
        ),
        store=store,
        actions=WorkActionRegistry((WriteExecutor(),)),
        resources=ResourceLeaseManager({"git": 1}),
    )

    written = await port.invoke(
        "write_file",
        {"path": "src\\approved.py", "text": "VALUE = 1\n"},
    )
    assert written["path"] == "src/approved.py"

    with pytest.raises(DevelopmentToolDenied, match="outside DevelopmentTicket"):
        await port.invoke(
            "write_file",
            {"path": "src/unapproved.py", "text": "VALUE = 2\n"},
        )

    with pytest.raises(DevelopmentToolDenied, match="safe repository-relative"):
        await port.invoke(
            "write_file",
            {"path": "../escape.py", "text": "VALUE = 3\n"},
        )


@pytest.mark.asyncio
async def test_tool_port_denies_writes_when_ticket_has_no_writable_paths(
    tmp_path,
) -> None:
    store = _running_store(tmp_path)
    port = WorkExecutorDevelopmentToolPort(
        ticket=_ticket(tools=("write_file",)),
        store=store,
        actions=WorkActionRegistry((WriteExecutor(),)),
        resources=ResourceLeaseManager({"git": 1}),
    )

    with pytest.raises(DevelopmentToolDenied, match="outside DevelopmentTicket"):
        await port.invoke(
            "write_file",
            {"path": "src/demo.py", "text": "VALUE = 1\n"},
        )


@pytest.mark.asyncio
async def test_tool_port_defaults_to_and_enforces_approved_test_targets(
    tmp_path,
) -> None:
    store = _running_store(tmp_path)
    port = WorkExecutorDevelopmentToolPort(
        ticket=_ticket(tools=("run_tests",)),
        store=store,
        actions=WorkActionRegistry((OwnerExecutor(),)),
        resources=ResourceLeaseManager({"cpu": 1}),
    )

    with pytest.raises(DevelopmentToolOwnerInputRequired):
        await port.invoke("run_tests", {})
    step = store.list_steps("work_demo")[-1]
    assert step.input_data["targets"] == ["tests/test_demo.py"]

    with pytest.raises(DevelopmentToolDenied, match="acceptance targets"):
        await port.invoke(
            "run_tests",
            {"targets": ["tests/test_unapproved.py"]},
        )


@pytest.mark.asyncio
async def test_tool_port_requires_running_admitted_work(tmp_path) -> None:
    store = _running_store(tmp_path)
    running = store.require("work_demo")
    paused = running.transition(WorkState.PAUSED, status_detail="gate")
    store.save(paused, expected_version=running.version)

    port = WorkExecutorDevelopmentToolPort(
        ticket=_ticket(tools=("read_file",)),
        store=store,
        actions=WorkActionRegistry((FakeExecutor(),)),
        resources=ResourceLeaseManager({"cpu": 1}),
    )

    with pytest.raises(DevelopmentToolDenied, match="not executable"):
        await port.invoke("read_file", {"path": "src/demo.py"})


@pytest.mark.asyncio
async def test_tool_port_preserves_owner_boundary_without_changing_work_state(
    tmp_path,
) -> None:
    store = _running_store(tmp_path)
    port = WorkExecutorDevelopmentToolPort(
        ticket=_ticket(tools=("run_tests",)),
        store=store,
        actions=WorkActionRegistry((OwnerExecutor(),)),
        resources=ResourceLeaseManager({"cpu": 1}),
    )

    with pytest.raises(DevelopmentToolOwnerInputRequired) as captured:
        await port.invoke("run_tests", {})

    assert captured.value.sensitive is True
    assert captured.value.input_key == "demo_secret"
    assert store.require("work_demo").state is WorkState.RUNNING
    step = store.list_steps("work_demo")[0]
    assert step.observation["needs_owner"] is True
    assert "response" not in step.observation


@pytest.mark.asyncio
async def test_commit_candidate_is_guarded_by_durable_evidence(tmp_path) -> None:
    store = _running_store(tmp_path)
    port = WorkExecutorDevelopmentToolPort(
        ticket=_ticket(tools=("commit_candidate",)),
        store=store,
        actions=WorkActionRegistry((CommitExecutor(),)),
        resources=ResourceLeaseManager({"git": 1}),
    )

    with pytest.raises(DevelopmentToolDenied, match="staged source change"):
        await port.invoke("commit_candidate", {})


def test_tool_port_reconstructs_progress_from_canonical_work_steps(tmp_path) -> None:
    store = _running_store(tmp_path)
    work_id = "work_demo"

    def add(kind: str, observation: dict[str, Any]) -> None:
        step = WorkStep(work_id=work_id, kind=kind, summary=kind)
        store.add_step(step)
        store.save_step(step.start().complete(observation))

    add("dev_write_file", {"path": "src/jarvis/demo.py", "sha256": "a" * 64})
    add("dev_run_tests", {"passed": True, "sandbox": "docker"})
    add("dev_diff", {"diff": "bounded"})
    add(
        "dev_commit",
        {
            "committed": True,
            "commit": "d" * 40,
            "branch": "work/demo",
            "clean": True,
        },
    )

    port = WorkExecutorDevelopmentToolPort(
        ticket=_ticket(tools=("read_file",)),
        store=store,
        actions=WorkActionRegistry((FakeExecutor(),)),
        resources=ResourceLeaseManager({"cpu": 1}),
    )

    snapshot = port.snapshot()

    assert snapshot["schema"] == "jarvis.development_progress.v1"
    assert snapshot["changed_files"] == ["src/jarvis/demo.py"]
    assert snapshot["candidate_revision"] == "d" * 40
    assert snapshot["candidate_branch"] == "work/demo"
    assert len(snapshot["passing_test_evidence_refs"]) == 1
    assert snapshot["completed_tool_step_count"] == 4
