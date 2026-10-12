"""The Phase-9 research lane must really call its research tool before resolving.

This is an isolated WorkEngine/CurrentResearchService boundary acceptance, not
a claim that production model reasoning, GitHub promotion or device control was
exercised. The provider is a deterministic no-network fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.development_engine.phase9 import Phase9ResearchControlPlaneDecider
from jarvis.knowledge.research import (
    CurrentResearchService,
    EvidenceSource,
    ProviderResearchEvidence,
    ResearchMode,
)
from jarvis.work.actions import ResearchWorkExecutor
from jarvis.work.brain import BrainAction, BrainCoordinator, BrainDecision, BrainRequest
from jarvis.work.engine import WorkActionRegistry, WorkEngine
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.store import SQLiteWorkStore


class _ReviewedOfflineProvider:
    provider_name = "offline-research-fixture"
    model_name = "offline"

    def __init__(self, *, source_available: bool) -> None:
        self.source_available = source_available
        self.calls: list[tuple[str, ResearchMode]] = []

    def research(self, query: str, mode: ResearchMode) -> ProviderResearchEvidence:
        self.calls.append((query, mode))
        sources = (
            (
                EvidenceSource(
                    source_id="fixture-reference",
                    url="https://example.org/device-reference",
                    title="Controlled reference material",
                    domain="example.org",
                    retrieved_at=datetime.now(UTC),
                    excerpt="Documentation for a fictional integration.",
                ),
            )
            if self.source_available
            else ()
        )
        return ProviderResearchEvidence(sources=sources)

    def close(self) -> None:
        pass


class _GoalInspectExecutor:
    descriptor = BrainAction(
        name="acq_inspect_goal", description="Inspect the typed owner requirement."
    )
    work_types = frozenset({WorkType.RESEARCH})

    async def execute(self, *, work: WorkItem, parameters: dict) -> dict:
        del parameters
        return {"goal": work.request, "source_revision": "fixture-only"}


class _ResolveExecutor:
    descriptor = BrainAction(
        name="acq_resolve", description="Re-evaluate sources after research."
    )
    work_types = frozenset({WorkType.RESEARCH})

    async def execute(self, *, work: WorkItem, parameters: dict) -> dict:
        del work, parameters
        return {"resolved": True}


class _Phase9FixtureBuilder:
    def is_phase9_research_work(self, work: WorkItem) -> bool:
        return (
            work.work_type is WorkType.RESEARCH
            and work.source_session_id == "change:fixture-phase9"
        )


class _GoalDrivenResearchReasoner:
    """Controlled model port; the test cannot pre-inject successful research."""

    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, request: BrainRequest) -> BrainDecision:
        self.calls += 1
        steps = request.full_history_steps
        inspected = next(
            (step for step in steps if step.kind == "acq_inspect_goal"),
            None,
        )
        assert inspected is not None
        assert inspected.observation["goal"] == request.work.request
        if not any(step.kind == "research_web" for step in steps):
            return BrainDecision(
                action="research_web",
                summary="Research the requested device capability.",
                parameters={
                    "query": (
                        request.work.request
                        + " official developer protocol and security documentation"
                    ),
                    "mode": "current",
                },
            )
        return BrainDecision(
            action=None,
            summary="Research and source resolution completed.",
            goal_complete=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target_type", ("air_conditioner", "smart_light", "robot_vacuum")
)
@pytest.mark.parametrize("source_available", (True, False))
async def test_unseen_device_research_is_executed_before_resolution_and_survives_restart(
    tmp_path: Path,
    target_type: str,
    source_available: bool,
) -> None:
    store = SQLiteWorkStore(tmp_path / "research.sqlite3")
    request = f"Research how to control a new {target_type} device"
    work = store.create(
        WorkItem(
            request=request,
            work_type=WorkType.RESEARCH,
            source_session_id="change:fixture-phase9",
            source_turn_id="original-owner-goal",
        )
    )
    provider = _ReviewedOfflineProvider(source_available=source_available)
    model = _GoalDrivenResearchReasoner()
    actions = WorkActionRegistry(
        (
            _GoalInspectExecutor(),
            ResearchWorkExecutor(CurrentResearchService(provider)),
            _ResolveExecutor(),
        )
    )

    def restart_engine() -> WorkEngine:
        return WorkEngine(
            store=store,
            brain=BrainCoordinator(model),
            actions=actions,
            control_plane_decider=Phase9ResearchControlPlaneDecider(
                _Phase9FixtureBuilder()
            ),
        )

    engine = restart_engine()
    await engine.advance(work.work_id)  # deterministic canonical goal inspection
    await engine.advance(work.work_id)  # model chooses the real research executor
    research_steps = [
        step for step in store.list_steps(work.work_id) if step.kind == "research_web"
    ]
    assert len(research_steps) == 1
    assert research_steps[0].observation["ok"] is source_available
    assert research_steps[0].observation["provider"] == provider.provider_name
    assert provider.calls == [
        (
            request + " official developer protocol and security documentation",
            ResearchMode.CURRENT,
        )
    ]

    engine = restart_engine()  # model/worker restart must not redo web research
    await engine.advance(work.work_id)  # deterministic re-resolution
    await engine.advance(work.work_id)  # completion is gated on good research
    steps = store.list_steps(work.work_id)
    evidence_steps = [
        step for step in steps if step.kind != "completion_guard"
    ]
    assert [step.kind for step in evidence_steps] == [
        "acq_inspect_goal",
        "research_web",
        "acq_resolve",
    ]
    assert model.calls == 2
    assert len(provider.calls) == 1

    finished = store.require(work.work_id)
    if source_available:
        assert all(step.kind != "completion_guard" for step in steps)
        assert finished.state is WorkState.COMPLETED
        assert research_steps[0].observation["sources"][0]["url"] == (
            "https://example.org/device-reference"
        )
    else:
        assert finished.state is not WorkState.COMPLETED
        assert research_steps[0].observation["sources"] == []
        # The WorkEngine must persist an explicit completion guard; absence
        # of research sources is never silently treated as successful work.
        guard_steps = [
            step for step in steps if step.kind == "completion_guard"
        ]
        assert len(guard_steps) == 1
