from __future__ import annotations

from jarvis.development_engine import (
    DevelopmentDisposition,
    DevelopmentEngineCoordinator,
    DevelopmentResultV1,
    DevelopmentSessionStore,
    DevelopmentTicketV1,
    DevelopmentToolSpecV1,
)
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.resources import ResourceLeaseManager
from jarvis.work.store import SQLiteWorkStore


class FakeTools:
    @property
    def tool_names(self):
        return ("read_file",)

    @property
    def tool_specs(self):
        return (
            DevelopmentToolSpecV1(
                name="read_file",
                description="read",
                parameter_schema={"type": "object"},
            ),
        )

    async def invoke(self, tool_name, parameters):
        raise AssertionError("fake engine should not execute tools")


class FakeEngine:
    engine_id = "fake_engine"
    engine_version = "1"

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, ticket, *, tools):
        self.calls += 1
        return DevelopmentResultV1.create(
            ticket=ticket,
            disposition=DevelopmentDisposition.NEEDS_RESEARCH,
            engine_id=self.engine_id,
            engine_version=self.engine_version,
            summary="More evidence required.",
            reason="The current evidence is insufficient.",
        )


def _ticket() -> DevelopmentTicketV1:
    return DevelopmentTicketV1.create(
        work_id="work_demo",
        engineering_change_id="change_demo",
        goal_id="goal_demo",
        goal_digest="a" * 64,
        architecture_artifact_id="architecture_demo",
        architecture_digest="b" * 64,
        base_revision="c" * 40,
        workspace_id="workspace_demo",
        required_operations=("operation.demo",),
        acceptance_criteria=("tests pass",),
        allowed_tools=("read_file",),
    )


def _sessions(tmp_path) -> DevelopmentSessionStore:
    store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store.create(
        WorkItem(
            request="develop",
            work_type=WorkType.DEVELOPMENT,
            source_session_id="session",
            source_turn_id="turn",
            work_id="work_demo",
        )
    )
    return DevelopmentSessionStore(store)


@pytest.mark.asyncio\nasync def test_coordinator_reuses_identical_reasoning_result(tmp_path) -> None:
    ticket = _ticket()
    engine = FakeEngine()
    coordinator = DevelopmentEngineCoordinator(
        engine=engine,
        sessions=_sessions(tmp_path),
    )

    first = await coordinator.execute(
        ticket,
        tools=FakeTools(),
        evidence_refs=("evidence:1",),
    )
    second = await coordinator.execute(
        ticket,
        tools=FakeTools(),
        evidence_refs=("evidence:1",),
    )

    assert first.reused is False
    assert second.reused is True
    assert first.result == second.result
    assert engine.calls == 1


@pytest.mark.asyncio\nasync def test_changed_evidence_admits_new_engine_turn(tmp_path) -> None:
    ticket = _ticket()
    engine = FakeEngine()
    coordinator = DevelopmentEngineCoordinator(
        engine=engine,
        sessions=_sessions(tmp_path),
    )

    first = await coordinator.execute(
        ticket,
        tools=FakeTools(),
        evidence_refs=("evidence:1",),
    )
    second = await coordinator.execute(
        ticket,
        tools=FakeTools(),
        evidence_refs=("evidence:1", "evidence:2"),
    )

    assert first.reasoning_fingerprint != second.reasoning_fingerprint
    assert second.reused is False
    assert engine.calls == 2


@pytest.mark.asyncio\nasync def test_coordinator_can_serialize_expensive_engine_capacity(tmp_path) -> None:
    ticket = _ticket()
    engine = FakeEngine()
    coordinator = DevelopmentEngineCoordinator(
        engine=engine,
        sessions=_sessions(tmp_path),
        resources=ResourceLeaseManager({"development_intelligence": 1}),
        resource_keys=("development_intelligence",),
    )

    result = await coordinator.execute(ticket, tools=FakeTools())

    assert result.result.disposition is DevelopmentDisposition.NEEDS_RESEARCH
    assert engine.calls == 1
