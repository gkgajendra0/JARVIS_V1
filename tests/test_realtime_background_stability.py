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
from jarvis.work.models import WorkDeliveryKind
from jarvis.work.runtime import WorkRuntime


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


@pytest.mark.asyncio
async def test_bound_gate_spoken_question_is_short_and_hides_internal_ids(
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

    question = await runtime._change_gate_spoken_question(challenge.gate_id)

    assert question == (
        "The architecture for media catalog search is ready. "
        "Do you approve or reject it?"
    )
    assert "gate_" not in question
    assert "change_" not in question
    assert "digest" not in question.casefold()


@pytest.mark.asyncio
async def test_work_status_scheduler_persistence_does_not_block_event_loop() -> None:
    runtime = object.__new__(WorkRuntime)
    runtime._closed = False
    started = threading.Event()
    release = threading.Event()

    def blocking_status_tick() -> None:
        started.set()
        assert release.wait(timeout=2.0)

    runtime._process_due_status_updates = blocking_status_tick  # type: ignore[method-assign]

    task = asyncio.create_task(runtime._status_update_loop())

    assert await asyncio.to_thread(started.wait, 1.0)
    heartbeat = asyncio.Event()
    asyncio.get_running_loop().call_soon(heartbeat.set)
    await asyncio.wait_for(heartbeat.wait(), timeout=0.1)
    assert task.done() is False

    runtime._closed = True
    release.set()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_background_delivery_store_poll_does_not_block_event_loop() -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingStore:
        def list_due_deliveries(self, *, limit: int):
            assert limit == 5
            started.set()
            assert release.wait(timeout=2.0)
            return ()

    controller = object.__new__(CanonicalActiveSpeakerRuntimeController)
    controller._shutdown = asyncio.Event()
    controller._work_runtime = SimpleNamespace(store=BlockingStore())
    controller.audio = SimpleNamespace(output=object())
    controller._state = SimpleNamespace(value="idle")
    controller._live_session = None

    task = asyncio.create_task(controller._deliver_pending_work())

    assert await asyncio.to_thread(started.wait, 1.0)
    heartbeat = asyncio.Event()
    asyncio.get_running_loop().call_soon(heartbeat.set)
    await asyncio.wait_for(heartbeat.wait(), timeout=0.1)
    assert task.done() is False

    controller._shutdown.set()
    release.set()
    await asyncio.wait_for(task, timeout=1.0)


def test_routing_resource_notifications_coalesce_across_work_items() -> None:
    first = SimpleNamespace(
        delivery_id="delivery_a",
        kind=WorkDeliveryKind.RESOURCE_BLOCKER,
        event_key="routing-resource:aaa",
    )
    second = SimpleNamespace(
        delivery_id="delivery_b",
        kind=WorkDeliveryKind.RESOURCE_BLOCKER,
        event_key="routing-resource:bbb",
    )
    unrelated = SimpleNamespace(
        delivery_id="delivery_c",
        kind=WorkDeliveryKind.RESOURCE_BLOCKER,
        event_key="memory-resource:ccc",
    )

    assert CanonicalActiveSpeakerRuntimeController._coalesced_delivery_ids(
        (first, second, unrelated),
        first,
    ) == ("delivery_a", "delivery_b")
    assert CanonicalActiveSpeakerRuntimeController._coalesced_delivery_ids(
        (first, second, unrelated),
        unrelated,
    ) == ("delivery_c",)
