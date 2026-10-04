from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.capability_acquisition.artifacts import candidate_payload
from jarvis.capability_acquisition.models import (
    AcquisitionCandidateV1,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.development_engine.contracts import DevelopmentTicketV1
from jarvis.development_engine.phase9 import (
    PHASE9_DEVELOPMENT_ENGINE_ACTION,
    Phase9DevelopmentControlPlaneDecider,
    Phase9ResearchControlPlaneDecider,
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
        return (
            work.work_type is WorkType.DEVELOPMENT
            and work.work_id == self.ticket.work_id
        )

    def is_phase9_research_work(self, work: WorkItem) -> bool:
        return work.work_type is WorkType.RESEARCH

    def build(self, work: WorkItem) -> DevelopmentTicketV1:
        assert self.is_phase9_development_work(work)
        return self.ticket


class FakeWorkStore:
    def __init__(
        self,
        steps: tuple[WorkStep, ...],
        *,
        prior_steps: tuple[WorkStep, ...] = (),
    ) -> None:
        self._steps = {
            "work_research": steps,
            "work_research_old": prior_steps,
        }

    def require(self, work_id: str):
        assert work_id in self._steps
        return SimpleNamespace(work_id=work_id)

    def list_steps(self, work_id: str) -> tuple[WorkStep, ...]:
        assert work_id in self._steps
        return self._steps[work_id]


class FakeChangeStore:
    def __init__(
        self,
        steps: tuple[WorkStep, ...],
        *,
        prior_steps: tuple[WorkStep, ...] = (),
    ) -> None:
        self.work = FakeWorkStore(steps, prior_steps=prior_steps)
        self._has_prior = bool(prior_steps)

    def stage_for_work(self, work_id: str):
        assert work_id == "work_development"
        return SimpleNamespace(
            change_id="change_demo",
            stage_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.development_stage.stage_key,
        )

    def list_stages(self, change_id: str):
        assert change_id == "change_demo"
        stages = []
        if self._has_prior:
            stages.append(
                SimpleNamespace(
                    stage_key=(
                        OWNER_CAPABILITY_ACQUISITION_PROCESS.architecture_source_stage.stage_key
                    ),
                    attempt=1,
                    work_id="work_research_old",
                )
            )
        stages.append(
            SimpleNamespace(
                stage_key=(
                    OWNER_CAPABILITY_ACQUISITION_PROCESS.architecture_source_stage.stage_key
                ),
                attempt=2 if self._has_prior else 1,
                work_id="work_research",
            )
        )
        return tuple(stages)

    def get_artifact(self, artifact_id: str):
        assert artifact_id == "architecture_demo"
        return SimpleNamespace(
            artifact_id=artifact_id,
            digest="b" * 64,
            payload={
                "plan_artifact_id": "plan_current",
                "plan_artifact_digest": "d" * 64,
            },
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


def _unverified_sdk_payload(version: str = "2.4.1") -> dict[str, object]:
    candidate = AcquisitionCandidateV1.create(
        source_kind=AcquisitionSourceKind.SDK_LIBRARY,
        source_identity="example-device-sdk",
        source_version=version,
        trust_class=AcquisitionTrustClass.UNVERIFIED_CANDIDATE,
        supported_operations=("pair", "launch", "key_input"),
        strategy=AcquisitionStrategy.ADAPT_SDK,
        evidence_refs=("evidence-2", "evidence-4"),
        verification_requirements=("sdk-adapter-contract-test",),
        reason_codes=("research_discovered_unverified",),
    )
    return candidate_payload(candidate)


def test_research_control_plane_inspects_goal_without_model_reasoning() -> None:
    work = WorkItem(
        request="research capability",
        work_type=WorkType.RESEARCH,
        source_session_id="session",
        source_turn_id="turn",
        work_id="work_research_control",
    )
    decider = Phase9ResearchControlPlaneDecider(FakeBuilder(_ticket()))
    actions = (
        BrainAction(name="acq_inspect_goal", description="inspect goal"),
        BrainAction(name="research_web", description="research"),
        BrainAction(name="acq_resolve", description="resolve"),
    )

    decision = decider(work, actions, ())

    assert decision is not None
    assert decision.action == "acq_inspect_goal"


def test_research_control_plane_resolves_only_after_new_evidence() -> None:
    work = WorkItem(
        request="research capability",
        work_type=WorkType.RESEARCH,
        source_session_id="session",
        source_turn_id="turn",
        work_id="work_research_control",
    )
    decider = Phase9ResearchControlPlaneDecider(FakeBuilder(_ticket()))
    actions = (
        BrainAction(name="acq_inspect_goal", description="inspect goal"),
        BrainAction(name="research_web", description="research"),
        BrainAction(name="acq_resolve", description="resolve"),
    )
    inspect = _completed_step(work.work_id, "acq_inspect_goal", {"goal": {}})
    evidence = _completed_step(
        work.work_id,
        "research_web",
        {"ok": True, "sources": [{"url": "https://example.com"}]},
    )

    decision = decider(work, actions, (inspect, evidence))

    assert decision is not None
    assert decision.action == "acq_resolve"

    resolved = _completed_step(work.work_id, "acq_resolve", {"resolved": True})
    assert decider(work, actions, (inspect, evidence, resolved)) is None


def test_research_control_plane_verifies_exact_sdk_before_resolve() -> None:
    work = WorkItem(
        request="research capability",
        work_type=WorkType.RESEARCH,
        source_session_id="session",
        source_turn_id="turn",
        work_id="work_research_control",
    )
    decider = Phase9ResearchControlPlaneDecider(FakeBuilder(_ticket()))
    actions = (
        BrainAction(name="acq_inspect_goal", description="inspect goal"),
        BrainAction(name="acq_verify_pypi_sdk", description="verify sdk"),
        BrainAction(name="acq_resolve", description="resolve"),
    )
    inspect = _completed_step(work.work_id, "acq_inspect_goal", {"goal": {}})
    payload = _unverified_sdk_payload()
    record = _completed_step(
        work.work_id,
        "acq_record_candidate",
        {"recorded": True, "candidate": payload},
    )

    decision = decider(work, actions, (inspect, record))

    assert decision is not None
    assert decision.action == "acq_verify_pypi_sdk"
    assert decision.parameters == {"candidate_id": payload["candidate_id"]}

    verified = _completed_step(
        work.work_id,
        "acq_verify_pypi_sdk",
        {
            "verified": True,
            "source_candidate_id": payload["candidate_id"],
        },
    )
    decision = decider(work, actions, (inspect, record, verified))

    assert decision is not None
    assert decision.action == "acq_resolve"
    assert decision.parameters == {}


def test_research_control_plane_does_not_force_nonexact_sdk_verification() -> None:
    work = WorkItem(
        request="research capability",
        work_type=WorkType.RESEARCH,
        source_session_id="session",
        source_turn_id="turn",
        work_id="work_research_control",
    )
    decider = Phase9ResearchControlPlaneDecider(FakeBuilder(_ticket()))
    actions = (
        BrainAction(name="acq_inspect_goal", description="inspect goal"),
        BrainAction(name="acq_verify_pypi_sdk", description="verify sdk"),
        BrainAction(name="acq_resolve", description="resolve"),
    )
    inspect = _completed_step(work.work_id, "acq_inspect_goal", {"goal": {}})
    record = _completed_step(
        work.work_id,
        "acq_record_candidate",
        {
            "recorded": True,
            "candidate": _unverified_sdk_payload(">=2.4"),
        },
    )

    decision = decider(work, actions, (inspect, record))

    assert decision is not None
    assert decision.action == "acq_resolve"
    assert decision.parameters == {}


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
    finalize = _completed_step(
        "work_research",
        "acq_finalize",
        {
            "finalized": True,
            "plan_artifact_id": "plan_current",
            "plan_artifact_digest": "d" * 64,
        },
    )
    store = FakeChangeStore((research_step, finalize))
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
    assert result["source_attempt"] == 1
    assert result["source_work_id"] == "work_research"
    assert result["plan_artifact_id"] == "plan_current"
    assert result["evidence"][0]["kind"] == "research_web"
    assert result["evidence"][0]["step_id"] == research_step.step_id

    with pytest.raises(ChangeConflict, match="outside the immutable ticket"):
        await executor.execute(
            work=work,
            parameters={"evidence_refs": ["source:unapproved"]},
        )


@pytest.mark.asyncio
async def test_research_evidence_excludes_superseded_source_attempt() -> None:
    work = _development_work()
    stale_research = _completed_step(
        "work_research_old",
        "research_web",
        {
            "ok": True,
            "query": "obsolete transport",
            "sources": [
                {
                    "source_id": "source:https://example.com/docs",
                    "excerpt": "obsolete attempt evidence",
                }
            ],
        },
    )
    stale_finalize = _completed_step(
        "work_research_old",
        "acq_finalize",
        {
            "finalized": True,
            "plan_artifact_id": "plan_old",
            "plan_artifact_digest": "e" * 64,
        },
    )
    current_research = _completed_step(
        "work_research",
        "research_web",
        {
            "ok": True,
            "query": "replacement transport",
            "sources": [
                {
                    "source_id": "source:https://example.com/docs",
                    "excerpt": "current attempt evidence",
                }
            ],
        },
    )
    current_finalize = _completed_step(
        "work_research",
        "acq_finalize",
        {
            "finalized": True,
            "plan_artifact_id": "plan_current",
            "plan_artifact_digest": "d" * 64,
        },
    )
    store = FakeChangeStore(
        (current_research, current_finalize),
        prior_steps=(stale_research, stale_finalize),
    )
    executor = Phase9ResearchEvidenceExecutor(
        store,  # type: ignore[arg-type]
        FakeBuilder(_ticket()),  # type: ignore[arg-type]
    )

    result = await executor.execute(
        work=work,
        parameters={"evidence_refs": ["source:https://example.com/docs"]},
    )

    assert result["source_attempt"] == 2
    assert result["source_work_id"] == "work_research"
    evidence_step_ids = {item["step_id"] for item in result["evidence"]}
    assert current_research.step_id in evidence_step_ids
    assert current_finalize.step_id in evidence_step_ids
    assert stale_research.step_id not in evidence_step_ids
    assert stale_finalize.step_id not in evidence_step_ids


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
