from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from jarvis.capability_acquisition.workflow import AcquisitionResolveExecutor
from jarvis.engineering_change.gates import GateChallenge, GateKind, GateService
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)


@pytest.mark.asyncio
async def test_phase9_candidate_resolution_does_not_block_event_loop() -> None:
    executor = object.__new__(AcquisitionResolveExecutor)
    started = threading.Event()
    release = threading.Event()

    def blocking_resolve(work_id: str):
        assert work_id == "work_phase9"
        started.set()
        assert release.wait(timeout=2.0)
        artifact = SimpleNamespace(
            artifact_id="artifact_resolution",
            digest="digest_resolution",
        )
        resolution = SimpleNamespace(
            candidates=(),
            evaluations=(),
            selected_candidate_id=None,
        )
        return artifact, resolution

    executor._resolve_and_persist = blocking_resolve  # type: ignore[method-assign]

    task = asyncio.create_task(
        executor.execute(
            work=SimpleNamespace(work_id="work_phase9"),  # type: ignore[arg-type]
            parameters={},
        )
    )

    assert await asyncio.to_thread(started.wait, 1.0)

    heartbeat = asyncio.Event()
    asyncio.get_running_loop().call_soon(heartbeat.set)
    await asyncio.wait_for(heartbeat.wait(), timeout=0.1)
    assert task.done() is False

    release.set()
    result = await asyncio.wait_for(task, timeout=1.0)

    assert result["resolved"] is True
    assert result["resolution_artifact_id"] == "artifact_resolution"
    assert result["selected_candidate_id"] is None


def test_bound_gate_spoken_question_is_short_and_hides_internal_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    challenge = GateChallenge(
        gate_id="gate_deadbeef",
        change_id="change_deadbeef",
        kind=GateKind.ARCHITECTURE,
        artifact_id="artifact_architecture",
        artifact_digest="digest_architecture",
        created_at="now",
    )

    class Store:
        def latest_artifact(self, change_id: str, kind: str):
            assert change_id == challenge.change_id
            assert kind == "architecture"
            return SimpleNamespace(
                payload={"proposed_capability_id": "media_catalog.search"}
            )

    runtime = object.__new__(CanonicalActiveSpeakerRuntimeController)
    runtime._work_runtime = SimpleNamespace(  # type: ignore[attr-defined]
        changes=SimpleNamespace(store=Store())
    )

    monkeypatch.setattr(
        GateService,
        "get",
        lambda self, gate_id: challenge if gate_id == challenge.gate_id else None,
    )

    question = runtime._change_gate_spoken_question(challenge.gate_id)

    assert question == (
        "The architecture for media catalog search is ready. "
        "Do you approve or reject it?"
    )
    assert "gate_" not in question
    assert "change_" not in question
    assert "digest" not in question.casefold()
