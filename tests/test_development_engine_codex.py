from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from jarvis.development_engine import (
    DevelopmentDisposition,
    DevelopmentSessionStore,
    DevelopmentTicketV1,
    DevelopmentToolSpecV1,
    DevelopmentUsageV1,
)
from jarvis.development_engine.codex import (
    CodexPlanDevelopmentEngine,
    CodexTurnResponse,
)
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.store import SQLiteWorkStore


class FakePlan:
    def __init__(self) -> None:
        self.calls = 0

    def access_token(self) -> str:
        self.calls += 1
        return "test-access-token"


@dataclass
class FakeThread:
    id: str
    responses: list[CodexTurnResponse]

    def __post_init__(self) -> None:
        self.user_messages: list[str] = []
        self.external_messages: list[str] = []

    async def run_user(
        self,
        message: str,
        *,
        output_schema: dict[str, Any],
    ) -> CodexTurnResponse:
        assert output_schema["type"] == "object"
        self.user_messages.append(message)
        return self.responses.pop(0)

    async def run_external(
        self,
        content: str,
        *,
        output_schema: dict[str, Any],
    ) -> CodexTurnResponse:
        assert output_schema["type"] == "object"
        self.external_messages.append(content)
        return self.responses.pop(0)


class FakeRuntime:
    def __init__(
        self,
        thread: FakeThread,
        *,
        fail_resume: bool = False,
        fail_start: BaseException | None = None,
    ) -> None:
        self.thread = thread
        self.fail_resume = fail_resume
        self.fail_start = fail_start
        self.started = 0
        self.resumed: list[str] = []
        self.closed = False

    @property
    def version(self) -> str:
        return "0.160.0"

    async def start_thread(self, *, model: str) -> FakeThread:
        assert model == "gpt-test"
        self.started += 1
        if self.fail_start is not None:
            raise self.fail_start
        return self.thread

    async def resume_thread(self, thread_id: str, *, model: str) -> FakeThread:
        assert model == "gpt-test"
        self.resumed.append(thread_id)
        if self.fail_resume:
            raise RuntimeError("stale provider thread")
        return self.thread

    async def close(self) -> None:
        self.closed = True


class FakeRuntimeFactory:
    def __init__(self, runtime: FakeRuntime) -> None:
        self.runtime = runtime
        self.access_token: str | None = None
        self.codex_home = None
        self.cwd = None

    def create(self, *, access_token, codex_home, cwd):
        self.access_token = access_token
        self.codex_home = codex_home
        self.cwd = cwd
        return self.runtime


class FakeTools:
    def __init__(self, names: tuple[str, ...]) -> None:
        self._names = tuple(sorted(names))
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._sequence = 0

    @property
    def tool_names(self) -> tuple[str, ...]:
        return self._names

    @property
    def tool_specs(self) -> tuple[DevelopmentToolSpecV1, ...]:
        return tuple(
            DevelopmentToolSpecV1(
                name=name,
                description=f"Synthetic {name}.",
                parameter_schema={
                    "type": "object",
                    "additionalProperties": True,
                },
            )
            for name in self._names
        )

    async def invoke(self, tool_name: str, parameters):
        self._sequence += 1
        values = dict(parameters)
        self.calls.append((tool_name, values))
        metadata = {
            "tool": tool_name,
            "action": f"dev_{tool_name}",
            "step_id": f"step_{self._sequence}",
            "evidence_ref": f"workstep:step_{self._sequence}",
        }
        if tool_name == "write_file":
            return {
                "path": values["path"],
                "sha256": "a" * 64,
                "_jarvis": metadata,
            }
        if tool_name == "run_tests":
            return {
                "passed": True,
                "_jarvis": metadata,
            }
        if tool_name == "inspect_diff":
            return {
                "diff": "synthetic diff",
                "_jarvis": metadata,
            }
        if tool_name == "commit_candidate":
            return {
                "committed": True,
                "commit": "d" * 40,
                "_jarvis": metadata,
            }
        return {"ok": True, "_jarvis": metadata}


def _ticket(*, work_id: str = "work_demo") -> DevelopmentTicketV1:
    return DevelopmentTicketV1.create(
        request="Develop the approved capability.",
        work_id=work_id,
        engineering_change_id="change_demo",
        goal_id="goal_demo",
        goal_digest="a" * 64,
        architecture_artifact_id="architecture_demo",
        architecture_digest="b" * 64,
        base_revision="c" * 40,
        workspace_id="workspace_demo",
        required_operations=("operation.demo",),
        research_evidence_refs=("research:approved",),
        acceptance_criteria=("candidate tests pass",),
        allowed_tools=(
            "commit_candidate",
            "inspect_diff",
            "run_tests",
            "write_file",
        ),
    )


def _sessions(tmp_path, ticket: DevelopmentTicketV1) -> DevelopmentSessionStore:
    store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store.create(
        WorkItem(
            request="develop capability",
            work_type=WorkType.DEVELOPMENT,
            source_session_id="session",
            source_turn_id="turn",
            work_id=ticket.work_id,
        )
    )
    sessions = DevelopmentSessionStore(store)
    sessions.begin(
        ticket=ticket,
        engine_id="codex_plan",
        engine_version="0.160.0",
        reasoning_fingerprint="e" * 64,
    )
    return sessions


def _response(payload: dict[str, Any], total: int) -> CodexTurnResponse:
    return CodexTurnResponse(
        final_response=json.dumps(payload),
        usage=(
            None
            if total == 0
            else DevelopmentUsageV1(
                input_tokens=total - 10,
                output_tokens=10,
                total_tokens=total,
            )
        ),
    )


@pytest.mark.asyncio
async def test_codex_engine_runs_coherent_tool_batches_and_derives_completion(
    tmp_path,
) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    thread = FakeThread(
        "thr_demo",
        [
            _response(
                {
                    "kind": "tool_batch",
                    "summary": "Create the implementation.",
                    "tool_calls": [
                        {
                            "call_id": "write",
                            "tool_name": "write_file",
                            "parameters_json": json.dumps(
                                {"path": "src/jarvis/demo.py", "text": "VALUE = 1\n"}
                            ),
                        }
                    ],
                    "disposition": None,
                    "reason": None,
                    "requested_dependencies": [],
                    "evidence_refs": [],
                    "blocker_code": None,
                },
                100,
            ),
            _response(
                {
                    "kind": "tool_batch",
                    "summary": "Verify and commit the implementation.",
                    "tool_calls": [
                        {
                            "call_id": "test",
                            "tool_name": "run_tests",
                            "parameters_json": "{}",
                        },
                        {
                            "call_id": "diff",
                            "tool_name": "inspect_diff",
                            "parameters_json": "{}",
                        },
                        {
                            "call_id": "commit",
                            "tool_name": "commit_candidate",
                            "parameters_json": json.dumps({"message": "test change"}),
                        },
                    ],
                    "disposition": None,
                    "reason": None,
                    "requested_dependencies": [],
                    "evidence_refs": [],
                    "blocker_code": None,
                },
                200,
            ),
            _response(
                {
                    "kind": "result",
                    "summary": "Implementation is complete and verified.",
                    "tool_calls": [],
                    "disposition": "completed",
                    "reason": None,
                    "requested_dependencies": [],
                    "evidence_refs": ["workstep:step_2", "workstep:step_3"],
                    "blocker_code": None,
                },
                300,
            ),
        ],
    )
    runtime = FakeRuntime(thread)
    factory = FakeRuntimeFactory(runtime)
    tools = FakeTools(ticket.allowed_tools)
    plan = FakePlan()
    engine = CodexPlanDevelopmentEngine(
        chatgpt_plan=plan,
        model="gpt-test",
        sessions=sessions,
        runtime_factory=factory,
        state_dir=tmp_path / "codex",
    )

    result = await engine.execute(ticket, tools=tools)

    assert result.disposition is DevelopmentDisposition.COMPLETED
    assert result.candidate_revision == "d" * 40
    assert result.changed_files == ("src/jarvis/demo.py",)
    assert result.test_evidence_refs == ("workstep:step_2",)
    assert result.usage is not None
    assert result.usage.total_tokens == 300
    assert sessions.get(ticket.digest).thread_id == "thr_demo"
    assert plan.calls == 1
    assert factory.access_token == "test-access-token"
    assert [name for name, _ in tools.calls] == [
        "write_file",
        "run_tests",
        "inspect_diff",
        "commit_candidate",
    ]
    assert len(thread.user_messages) == 1
    assert len(thread.external_messages) == 2
    assert runtime.closed is True


@pytest.mark.asyncio
async def test_codex_engine_reconstructs_when_saved_thread_is_stale(tmp_path) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    sessions.bind_thread(ticket_digest=ticket.digest, thread_id="thr_stale")
    thread = FakeThread(
        "thr_replacement",
        [
            _response(
                {
                    "kind": "result",
                    "summary": "Fresh research is required.",
                    "tool_calls": [],
                    "disposition": "needs_research",
                    "reason": "The protocol evidence is insufficient.",
                    "requested_dependencies": [],
                    "evidence_refs": ["research:approved"],
                    "blocker_code": None,
                },
                50,
            )
        ],
    )
    runtime = FakeRuntime(thread, fail_resume=True)
    engine = CodexPlanDevelopmentEngine(
        chatgpt_plan=FakePlan(),
        model="gpt-test",
        sessions=sessions,
        runtime_factory=FakeRuntimeFactory(runtime),
        state_dir=tmp_path / "codex",
    )

    result = await engine.execute(ticket, tools=FakeTools(ticket.allowed_tools))

    assert result.disposition is DevelopmentDisposition.NEEDS_RESEARCH
    assert runtime.resumed == ["thr_stale"]
    assert runtime.started == 1
    assert sessions.get(ticket.digest).thread_id == "thr_replacement"


@pytest.mark.asyncio
async def test_codex_engine_maps_plan_capacity_to_resource_blocker(tmp_path) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    runtime = FakeRuntime(
        FakeThread("thr_never", []),
        fail_start=RuntimeError("subscription_sharing_usage_limit_exceeded"),
    )
    engine = CodexPlanDevelopmentEngine(
        chatgpt_plan=FakePlan(),
        model="gpt-test",
        sessions=sessions,
        runtime_factory=FakeRuntimeFactory(runtime),
        state_dir=tmp_path / "codex",
    )

    result = await engine.execute(ticket, tools=FakeTools(ticket.allowed_tools))

    assert result.disposition is DevelopmentDisposition.BLOCKED_RESOURCE
    assert result.blocker_code == "rate_limited"
    assert runtime.closed is True


@pytest.mark.asyncio
async def test_codex_completion_without_durable_commit_is_rejected(tmp_path) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    thread = FakeThread(
        "thr_demo",
        [
            _response(
                {
                    "kind": "result",
                    "summary": "Done.",
                    "tool_calls": [],
                    "disposition": "completed",
                    "reason": None,
                    "requested_dependencies": [],
                    "evidence_refs": [],
                    "blocker_code": None,
                },
                25,
            )
        ],
    )
    engine = CodexPlanDevelopmentEngine(
        chatgpt_plan=FakePlan(),
        model="gpt-test",
        sessions=sessions,
        runtime_factory=FakeRuntimeFactory(FakeRuntime(thread)),
        state_dir=tmp_path / "codex",
    )

    result = await engine.execute(ticket, tools=FakeTools(ticket.allowed_tools))

    assert result.disposition is DevelopmentDisposition.FAILED
    assert "evidence validation" in result.summary.casefold()
