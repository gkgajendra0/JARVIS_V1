from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from jarvis.development_engine import (
    DevelopmentDisposition,
    DevelopmentSessionStore,
    DevelopmentTicketV1,
    DevelopmentToolOwnerInputRequired,
    DevelopmentToolSpecV1,
    DevelopmentUsageV1,
)
from jarvis.development_engine.codex import (
    CodexPlanDevelopmentEngine,
    CodexTurnResponse,
    _DevelopmentResponseContractError,
    _OfficialCodexThread,
)
from jarvis.provider_circuit import BackgroundProviderCircuit
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.store import SQLiteWorkStore


class InvalidRequestError(RuntimeError):
    pass


class ServerBusyError(RuntimeError):
    pass


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
        resume_error: BaseException | None = None,
        fail_start: BaseException | None = None,
        version: str = "0.160.0",
    ) -> None:
        self.thread = thread
        self.fail_resume = fail_resume
        self.resume_error = resume_error
        self.fail_start = fail_start
        self.runtime_version = version
        self.started = 0
        self.resumed: list[str] = []
        self.closed = False

    @property
    def version(self) -> str:
        return self.runtime_version

    async def start_thread(self, *, model: str) -> FakeThread:
        assert model == "gpt-test"
        self.started += 1
        if self.fail_start is not None:
            raise self.fail_start
        return self.thread

    async def resume_thread(self, thread_id: str, *, model: str) -> FakeThread:
        assert model == "gpt-test"
        self.resumed.append(thread_id)
        if self.resume_error is not None:
            raise self.resume_error
        if self.fail_resume:
            raise InvalidRequestError("thread not found")
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
    def __init__(
        self,
        names: tuple[str, ...],
        *,
        snapshot_data: dict[str, Any] | None = None,
    ) -> None:
        self._names = tuple(sorted(names))
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._sequence = 0
        self._snapshot_data = snapshot_data

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

    def snapshot(self) -> dict[str, Any]:
        if self._snapshot_data is not None:
            return dict(self._snapshot_data)
        return {
            "schema": "jarvis.development_progress.v1",
            "ticket_id": "fake",
            "ticket_digest": "fake",
            "completed_tool_step_count": 0,
            "changed_files": [],
            "passing_test_evidence_refs": [],
            "candidate_revision": None,
            "candidate_branch": None,
            "recent_tool_evidence": [],
        }

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
                model_turns=1,
            )
        ),
    )


@pytest.mark.asyncio
async def test_codex_engine_rejects_unreviewed_runtime_generation(tmp_path) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    runtime = FakeRuntime(
        FakeThread("thr_unreviewed", []),
        version="0.161.0",
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
    assert result.blocker_code == "development_engine_unclassified"
    assert result.engine_version == "0.160.0"
    assert runtime.started == 0
    assert runtime.resumed == []
    record = sessions.get(ticket.digest)
    assert record is not None
    assert record.thread_id is None


@pytest.mark.asyncio
async def test_codex_engine_preserves_unclassified_runtime_failure_for_retry(
    tmp_path,
) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    runtime = FakeRuntime(
        FakeThread("thr_unused", []),
        fail_start=RuntimeError("synthetic runtime boundary"),
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
    assert result.blocker_code == "development_engine_unclassified"
    assert result.retry_after_seconds is None
    assert "RuntimeError" in (result.reason or "")


@pytest.mark.asyncio
async def test_codex_engine_repairs_one_malformed_directive_in_same_thread(
    tmp_path,
) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    thread = FakeThread(
        "thr_repair",
        [
            CodexTurnResponse(
                final_response="not-json",
                usage=DevelopmentUsageV1(total_tokens=10, model_turns=1),
            ),
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
                20,
            ),
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

    assert result.disposition is DevelopmentDisposition.NEEDS_RESEARCH
    assert len(thread.user_messages) == 1
    assert len(thread.external_messages) == 1
    repair = json.loads(thread.external_messages[0])
    assert repair["contract"] == "jarvis.development_response_repair.v1"
    assert repair["status"] == "previous_response_rejected"


@pytest.mark.asyncio
async def test_codex_engine_parks_after_bounded_contract_repairs_are_exhausted(
    tmp_path,
) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    thread = FakeThread(
        "thr_contract_cooldown",
        [
            CodexTurnResponse(final_response="not-json-1", usage=None),
            CodexTurnResponse(final_response="not-json-2", usage=None),
            CodexTurnResponse(final_response="not-json-3", usage=None),
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

    assert result.disposition is DevelopmentDisposition.BLOCKED_RESOURCE
    assert result.blocker_code == "response_contract_invalid"
    assert result.retry_after_seconds is None
    assert "durable cooldown" in (result.reason or "")
    assert "non-retryable" not in (result.reason or "")
    assert len(thread.user_messages) == 1
    assert len(thread.external_messages) == 2


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
    assert result.usage.total_tokens == 600
    assert result.usage.model_turns == 3
    assert result.usage.tool_calls == 4
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
    assert result.blocker_code == "quota_exhausted"
    assert runtime.closed is True


@pytest.mark.asyncio
async def test_codex_app_server_overload_parks_development(tmp_path) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    runtime = FakeRuntime(
        FakeThread("thr_never", []),
        fail_start=ServerBusyError("server overloaded"),
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
    assert result.blocker_code == "service_unavailable"
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


@pytest.mark.asyncio
async def test_codex_engine_does_not_replace_thread_on_transient_resume_pressure(
    tmp_path,
) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    sessions.bind_thread(ticket_digest=ticket.digest, thread_id="thr_saved")
    runtime = FakeRuntime(
        FakeThread("thr_unused", []),
        resume_error=RuntimeError("subscription_sharing_usage_limit_exceeded"),
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
    assert runtime.resumed == ["thr_saved"]
    assert runtime.started == 0
    assert sessions.get(ticket.digest).thread_id == "thr_saved"


@pytest.mark.asyncio
async def test_codex_engine_reconstructs_completion_from_canonical_progress(
    tmp_path,
) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    sessions.bind_thread(ticket_digest=ticket.digest, thread_id="thr_missing")
    thread = FakeThread(
        "thr_rebuilt",
        [
            _response(
                {
                    "kind": "result",
                    "summary": "Canonical candidate is already complete.",
                    "tool_calls": [],
                    "disposition": "completed",
                    "reason": None,
                    "requested_dependencies": [],
                    "evidence_refs": [
                        "workstep:test_prior",
                        "workstep:commit_prior",
                    ],
                    "blocker_code": None,
                },
                40,
            )
        ],
    )
    runtime = FakeRuntime(thread, fail_resume=True)
    tools = FakeTools(
        ticket.allowed_tools,
        snapshot_data={
            "schema": "jarvis.development_progress.v1",
            "ticket_id": ticket.ticket_id,
            "ticket_digest": ticket.digest,
            "completed_tool_step_count": 4,
            "changed_files": ["src/jarvis/demo.py"],
            "passing_test_evidence_refs": ["workstep:test_prior"],
            "candidate_revision": "d" * 40,
            "candidate_branch": "work/demo",
            "recent_tool_evidence": [
                {
                    "tool": "run_tests",
                    "step_id": "test_prior",
                    "evidence_ref": "workstep:test_prior",
                    "summary": "tests",
                    "observation": {"passed": True},
                },
                {
                    "tool": "commit_candidate",
                    "step_id": "commit_prior",
                    "evidence_ref": "workstep:commit_prior",
                    "summary": "commit",
                    "observation": {"commit": "d" * 40, "clean": True},
                },
            ],
        },
    )
    engine = CodexPlanDevelopmentEngine(
        chatgpt_plan=FakePlan(),
        model="gpt-test",
        sessions=sessions,
        runtime_factory=FakeRuntimeFactory(runtime),
        state_dir=tmp_path / "codex",
    )

    result = await engine.execute(ticket, tools=tools)

    assert result.disposition is DevelopmentDisposition.COMPLETED
    assert result.candidate_revision == "d" * 40
    assert result.changed_files == ("src/jarvis/demo.py",)
    assert result.test_evidence_refs == ("workstep:test_prior",)
    assert tools.calls == []
    assert runtime.resumed == ["thr_missing"]
    assert runtime.started == 1


@pytest.mark.asyncio
async def test_codex_engine_open_provider_circuit_suppresses_cloud_request(
    tmp_path,
) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    clock = lambda: 1000.0
    circuit = BackgroundProviderCircuit(clock=clock)
    trip = circuit.record_failure(
        RuntimeError(
            "subscription_sharing_usage_limit_exceeded: "
            "Subscription Sharing usage limit reached"
        )
    )
    assert trip is not None
    plan = FakePlan()
    runtime = FakeRuntime(FakeThread("thr_never", []))
    factory = FakeRuntimeFactory(runtime)
    engine = CodexPlanDevelopmentEngine(
        chatgpt_plan=plan,
        model="gpt-test",
        sessions=sessions,
        runtime_factory=factory,
        state_dir=tmp_path / "codex",
        provider_circuit=circuit,
    )

    result = await engine.execute(ticket, tools=FakeTools(ticket.allowed_tools))

    assert result.disposition is DevelopmentDisposition.BLOCKED_RESOURCE
    assert result.blocker_code == "provider_circuit_open"
    assert result.retry_after_seconds == trip.delay_seconds
    assert plan.calls == 0
    assert factory.access_token is None
    assert runtime.started == 0
    assert runtime.resumed == []


@pytest.mark.asyncio
async def test_codex_engine_subscription_limit_opens_shared_circuit_and_suppresses_retry(
    tmp_path,
) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    circuit = BackgroundProviderCircuit(clock=lambda: 1000.0)
    plan = FakePlan()
    runtime = FakeRuntime(
        FakeThread("thr_never", []),
        fail_start=RuntimeError(
            "subscription_sharing_usage_limit_exceeded: "
            "Subscription Sharing usage limit reached"
        ),
    )
    factory = FakeRuntimeFactory(runtime)
    engine = CodexPlanDevelopmentEngine(
        chatgpt_plan=plan,
        model="gpt-test",
        sessions=sessions,
        runtime_factory=factory,
        state_dir=tmp_path / "codex",
        provider_circuit=circuit,
    )

    first = await engine.execute(ticket, tools=FakeTools(ticket.allowed_tools))
    second = await engine.execute(ticket, tools=FakeTools(ticket.allowed_tools))

    assert first.disposition is DevelopmentDisposition.BLOCKED_RESOURCE
    assert first.blocker_code == "quota_exhausted"
    assert first.retry_after_seconds == 1800.0
    assert second.disposition is DevelopmentDisposition.BLOCKED_RESOURCE
    assert second.blocker_code == "provider_circuit_open"
    assert second.retry_after_seconds == 1800.0
    assert circuit.allow_request() is False
    assert circuit.failed_attempts == 1
    assert plan.calls == 1
    assert runtime.started == 1


@pytest.mark.asyncio
async def test_codex_tool_batch_cannot_smuggle_terminal_disposition(tmp_path) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    thread = FakeThread(
        "thr_invalid_batch",
        [
            *[
                _response(
                    {
                        "kind": "tool_batch",
                        "summary": "Invalid mixed directive.",
                        "tool_calls": [
                            {
                                "call_id": "write",
                                "tool_name": "write_file",
                                "parameters_json": json.dumps(
                                    {
                                        "path": "src/jarvis/demo.py",
                                        "text": "VALUE = 1\n",
                                    }
                                ),
                            }
                        ],
                        "disposition": "completed",
                        "reason": None,
                        "requested_dependencies": [],
                        "evidence_refs": [],
                        "blocker_code": None,
                    },
                    25,
                )
                for _ in range(3)
            ]
        ],
    )
    tools = FakeTools(ticket.allowed_tools)
    engine = CodexPlanDevelopmentEngine(
        chatgpt_plan=FakePlan(),
        model="gpt-test",
        sessions=sessions,
        runtime_factory=FakeRuntimeFactory(FakeRuntime(thread)),
        state_dir=tmp_path / "codex",
    )

    result = await engine.execute(ticket, tools=tools)

    assert result.disposition is DevelopmentDisposition.FAILED
    assert tools.calls == []


@pytest.mark.asyncio
async def test_codex_terminal_result_cannot_request_more_tools(tmp_path) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    thread = FakeThread(
        "thr_invalid_result",
        [
            *[
                _response(
                    {
                        "kind": "result",
                        "summary": "Invalid terminal directive.",
                        "tool_calls": [
                            {
                                "call_id": "write",
                                "tool_name": "write_file",
                                "parameters_json": json.dumps(
                                    {
                                        "path": "src/jarvis/demo.py",
                                        "text": "VALUE = 2\n",
                                    }
                                ),
                            }
                        ],
                        "disposition": "failed",
                        "reason": "synthetic",
                        "requested_dependencies": [],
                        "evidence_refs": [],
                        "blocker_code": None,
                    },
                    25,
                )
                for _ in range(3)
            ]
        ],
    )
    tools = FakeTools(ticket.allowed_tools)
    engine = CodexPlanDevelopmentEngine(
        chatgpt_plan=FakePlan(),
        model="gpt-test",
        sessions=sessions,
        runtime_factory=FakeRuntimeFactory(FakeRuntime(thread)),
        state_dir=tmp_path / "codex",
    )

    result = await engine.execute(ticket, tools=tools)

    assert result.disposition is DevelopmentDisposition.FAILED
    assert tools.calls == []


@pytest.mark.asyncio
async def test_codex_engine_propagates_governed_owner_input_boundary(tmp_path) -> None:
    ticket = _ticket()
    sessions = _sessions(tmp_path, ticket)
    thread = FakeThread(
        "thr_owner_boundary",
        [
            _response(
                {
                    "kind": "tool_batch",
                    "summary": "Use the governed tool that requires owner input.",
                    "tool_calls": [
                        {
                            "call_id": "write",
                            "tool_name": "write_file",
                            "parameters_json": json.dumps(
                                {
                                    "path": "src/jarvis/demo.py",
                                    "text": "VALUE = 1\n",
                                }
                            ),
                        }
                    ],
                    "disposition": None,
                    "reason": None,
                    "requested_dependencies": [],
                    "evidence_refs": [],
                    "blocker_code": None,
                },
                25,
            )
        ],
    )

    class OwnerBoundaryTools(FakeTools):
        async def invoke(self, tool_name: str, parameters):
            del tool_name, parameters
            raise DevelopmentToolOwnerInputRequired(
                "Provide the protected pairing value.",
                sensitive=True,
                input_key="pairing_pin",
                resume_context={"kind": "pin"},
            )

    engine = CodexPlanDevelopmentEngine(
        chatgpt_plan=FakePlan(),
        model="gpt-test",
        sessions=sessions,
        runtime_factory=FakeRuntimeFactory(FakeRuntime(thread)),
        state_dir=tmp_path / "codex",
    )

    with pytest.raises(DevelopmentToolOwnerInputRequired) as captured:
        await engine.execute(ticket, tools=OwnerBoundaryTools(ticket.allowed_tools))

    assert captured.value.sensitive is True
    assert captured.value.input_key == "pairing_pin"


def test_official_codex_thread_recovers_commentary_agent_message() -> None:
    payload = '{"kind":"tool_batch","summary":"Inspect source","tool_calls":[]}'
    result = SimpleNamespace(
        final_response=None,
        items=[
            SimpleNamespace(
                root=SimpleNamespace(
                    type="agentMessage",
                    text=payload,
                    phase=SimpleNamespace(value="commentary"),
                )
            )
        ],
    )

    assert _OfficialCodexThread._structured_response_text(result) == payload


def test_official_codex_thread_rejects_completed_turn_without_agent_message() -> None:
    result = SimpleNamespace(
        final_response=None,
        items=[SimpleNamespace(root=SimpleNamespace(type="reasoning", text="hidden"))],
    )

    with pytest.raises(
        _DevelopmentResponseContractError,
        match="without a structured agent response",
    ):
        _OfficialCodexThread._structured_response_text(result)


def test_official_codex_usage_uses_last_turn_not_cumulative_thread_total() -> None:
    usage = SimpleNamespace(
        last=SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
        ),
        total=SimpleNamespace(
            input_tokens=900,
            output_tokens=100,
            total_tokens=1000,
        ),
    )
    result = SimpleNamespace(usage=usage)

    projected = _OfficialCodexThread._usage(result)

    assert projected == DevelopmentUsageV1(
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
        model_turns=1,
    )
