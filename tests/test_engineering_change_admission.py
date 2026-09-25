from __future__ import annotations

import pytest

from jarvis.engineering_change import ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.work.brain import BrainAction, BrainDecision
from jarvis.work.engine import WorkActionRegistry, WorkEngine
from jarvis.work.models import WorkState, WorkType
from jarvis.work.store import SQLiteWorkStore


class Backend:
    def submit(self, work_id, *, priority):
        del priority
        return work_id


class Reasoner:
    async def decide(self, request):
        del request
        return BrainDecision(action="safe_step", summary="execute safe step")


class Executor:
    descriptor = BrainAction(
        name="safe_step", description="Test action", parameter_schema={"type": "object"}
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(self):
        self.calls = 0

    async def execute(self, *, work, parameters):
        del work, parameters
        self.calls += 1
        return {"verified": True}


@pytest.mark.asyncio
async def test_superseded_approval_pauses_existing_development_before_action(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    coordinator = ChangeCoordinator(changes, Backend())
    change = coordinator.start("New camera adapter", "owner", "goal")
    research = changes.list_stages(change.change_id)[0]
    running = work.save(
        work.require(research.work_id).transition(WorkState.RUNNING), expected_version=1
    )
    work.save(running.transition(WorkState.COMPLETED), expected_version=running.version)
    architecture = changes.add_artifact(
        change.change_id, kind="architecture", payload={"api": "v1"}
    )
    coordinator.reconcile(change.change_id)
    gates = GateService(changes, verify_owner=lambda *_: True)
    gate = gates.present(
        change.change_id, GateKind.ARCHITECTURE, architecture.artifact_id
    )
    gates.decide(
        gate.gate_id,
        approved=True,
        artifact_digest=architecture.digest,
        actor_id="owner",
        source_session_id="owner",
        source_turn_id="yes",
        request_key="owner:yes",
    )
    coordinator.reconcile(change.change_id)
    dev = changes.list_stages(change.change_id)[1]
    changes.add_artifact(change.change_id, kind="architecture", payload={"api": "v2"})
    executor = Executor()
    engine = WorkEngine(
        store=work,
        brain=Reasoner(),
        actions=WorkActionRegistry((executor,)),
        action_admission=changes.work_admitted,
    )
    result = await engine.advance(dev.work_id)
    assert result.state is WorkState.PAUSED
    assert executor.calls == 0
