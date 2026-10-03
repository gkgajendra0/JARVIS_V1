from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.development_engine.contracts import DevelopmentTicketV1
from jarvis.development_engine.phase9 import (
    PHASE9_DEVELOPMENT_ENGINE_ACTION,
    Phase9DevelopmentControlPlaneDecider,
    Phase9ResearchEvidenceExecutor,
    phase9_development_completion_guard,
)
from jarvis.engineering_change.models import ChangeConflict
from jarvis.work.brain import BrainAction
from jarvis.work.models import WorkItem, WorkStep, WorkType


def _ticket(work_id: str = "work_development") -> DevelopmentTicketV1:
    return DevelopmentTicketV1.create(
        request="Develop the approved capability.",
        work_id=work_id,
        engineering_change_id="change_demo",
        goal_id="goal_demo",
        goal_digest="a" * 64,
        architecture_artifact_id="architecture_demo",
        architecture_digest="b" * 64,
        base_revision="c" * 40,
        workspace_id=work_id,
        required_operations=("operation.demo",),
        research_evidence_refs=(
            "source:https://example.com/docs",
            "sdk:example-client",
        ),
        acceptance_criteria=("tests pass",),
        allowed_tools=(
            "get_research_evidence",
            "read_file",
            "write_file",
        ),
    )


class FakeBuilder:
    def __init__(self, ticket: DevelopmentTicketV1) -> None:
        self.ticket = ticket

    def is_phase9_development_work(self, work: WorkItem) -> bool:
        return work.work_id == self.ticket.work_id

    def build(self, work: WorkItem) -> DevelopmentTicketV1:
        assert self.is_phase9_development_work(work)
        return self.ticket


class FakeWorkStore:
    def __init__(self, steps: tuple[WorkStep, ...]) -> None:
        self._steps = steps

    def require(self, work_id: str):
        assert work_id == "work_research"
        return SimpleNamespace(work_id=work_id)

    def list_steps(self, work_id: str) -> tuple[WorkStep, ...]:
        assert work_id == "work_research"
        return self._steps


class FakeChangeStore:
    def __init__(self, steps: tuple[WorkStep, ...]) -> None:
        self.work = FakeWorkStore(steps)

    def stage_for_work(self, work_id: str):
        assert work_id == "work_development"
        return SimpleNamespace(
            change_id="change_demo",
            stage_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.development_stage.stage_key,
        )

    def list_stages(self, change_id: str):
        assert change_id == "change_demo"
        return (
            SimpleNamespace(
                stage_key=(
                    OWNER_CAPABILITY_ACQUISITION_PROCESS.architecture_source_stage.stage_key
                ),
                attempt=1,
                work_id="work_research",
            ),
        )

    def require(self, change_id: str):
        assert change_id == "change_demo"
        return SimpleNamespace(
            process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
            process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
        )


def _development_work() -> WorkItem:
    return WorkItem(
        request="develop capability",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="session",
        source_turn_id="turn",
        work_id="work_development",
    )


def _completed_step(
    work_id: str,
    kind: str,
    observation: dict[str, object],
) -> WorkStep:
    step = WorkStep(work_id=work_id, kind=kind, summary=kind)
    return step.start().complete(observation)


def test_control_plane_bypasses_micro_step_reasoner_for_phase9() -> None:
    work = _development_work()
    decider = Phase9DevelopmentControlPlaneDecider(FakeBuilder(_ticket()))
    actions = (
        BrainAction(
            name=PHASE9_DEVELOPMENT_ENGINE_ACTION,
            description="run engineering specialist",
        ),
    )

    decision = decider(work, actions, ())

    assert decision is not None
    assert decision.action == PHASE9_DEVELOPMENT_ENGINE_ACTION
    assert decision.goal_complete is False


def test_control_plane_completes_after_typed_engine_result() -> None:
    work = _development_work()
    decider = Phase9DevelopmentControlPlaneDecider(FakeBuilder(_ticket()))
    actions = (
        BrainAction(
            name=PHASE9_DEVELOPMENT_ENGINE_ACTION,
            description="run engineering specialist",
        ),
    )
    engine_step = _completed_step(
        work.work_id,
        PHASE9_DEVELOPMENT_ENGINE_ACTION,
        {
            "development_result": {
                "disposition": "needs_research",
                "summary": "Fresh protocol evidence is required.",
            }
        },
    )

    decision = decider(work, actions, (engine_step,))

    assert decision is not None
    assert decision.action is None
    assert decision.goal_complete is True
    assert decision.summary == "Fresh protocol evidence is required."


@pytest.mark.asyncio
async def test_research_evidence_tool_is_ticket_bounded() -> None:
    work = _development_work()
    research_step = _completed_step(
        "work_research",
        "research_web",
        {
            "ok": True,
            "query": "example sdk documentation",
            "sources": [
                {
                    "source_id": "source:https://example.com/docs",
                    "url": "https://example.com/docs",
                    "excerpt": "Example client exposes the required operation.",
                }
            ],
        },
    )
    store = FakeChangeStore((research_step,))
    executor = Phase9ResearchEvidenceExecutor(
        store,  # type: ignore[arg-type]
        FakeBuilder(_ticket()),  # type: ignore[arg-type]
    )

    result = await executor.execute(
        work=work,
        parameters={"evidence_refs": ["source:https://example.com/docs"]},
    )

    assert result["schema"] == "phase9_development_research_evidence.v1"
    assert result["ticket_id"] == _ticket().ticket_id
    assert result["evidence"][0]["kind"] == "research_web"
    assert result["evidence"][0]["step_id"] == research_step.step_id

    with pytest.raises(ChangeConflict, match="outside the immutable ticket"):
        await executor.execute(
            work=work,
            parameters={"evidence_refs": ["source:unapproved"]},
        )


def test_phase9_completion_guard_allows_typed_revision_without_fake_commit() -> None:
    work = _development_work()
    store = FakeChangeStore(())
    revision = _completed_step(
        work.work_id,
        PHASE9_DEVELOPMENT_ENGINE_ACTION,
        {
            "development_result": {
                "disposition": "needs_architecture_revision",
                "summary": "Approved transport cannot satisfy the operation.",
            }
        },
    )

    assert phase9_development_completion_guard(
        store,  # type: ignore[arg-type]
        work,
        (revision,),
    ) == (True, None)


def test_phase9_completion_guard_keeps_resource_blocker_open() -> None:
    work = _development_work()
    store = FakeChangeStore(())
    blocked = _completed_step(
        work.work_id,
        PHASE9_DEVELOPMENT_ENGINE_ACTION,
        {
            "resource_blocked": False,
            "development_result": {
                "disposition": "blocked_resource",
                "summary": "Shared allowance unavailable.",
            },
        },
    )

    assert phase9_development_completion_guard(
        store,  # type: ignore[arg-type]
        work,
        (blocked,),
    ) == (False, "DevelopmentEngine is still resource-blocked")
