"""Protect realtime speech scheduling from synchronous status and delivery I/O."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from jarvis.capability_acquisition.workflow import AcquisitionResolveExecutor
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.work.runtime import WorkRuntime


@pytest.mark.asyncio
async def test_acquisition_resolver_does_not_block_realtime_loop() -> None:
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
            selected_candidate=None,
        )
        return artifact, resolution

    executor._resolve_and_persist = blocking_resolve  # type: ignore[method-assign]
    task = asyncio.create_task(
        executor.execute(
            work=SimpleNamespace(work_id="work_phase9"),  # type: ignore[arg-type]
            parameters={},
        )
    )
    try:
        assert await asyncio.to_thread(started.wait, 1.0)
        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), timeout=0.1)
        assert task.done() is False
    finally:
        release.set()

    result = await asyncio.wait_for(task, timeout=1.0)
    assert result["resolved"] is True
    assert result["resolution_artifact_id"] == "artifact_resolution"
    assert result["selected_candidate_id"] is None
    assert result["selected_candidate_strategy"] is None
    assert result["selected_candidate_source_kind"] is None


@pytest.mark.asyncio
async def test_work_status_persistence_does_not_block_realtime_loop() -> None:
    runtime = object.__new__(WorkRuntime)
    runtime._closed = False
    started = threading.Event()
    release = threading.Event()

    def blocking_status_tick() -> None:
        started.set()
        assert release.wait(timeout=2.0)

    runtime._process_due_status_updates = (  # type: ignore[method-assign]
        blocking_status_tick
    )
    task = asyncio.create_task(runtime._status_update_loop())
    try:
        assert await asyncio.to_thread(started.wait, 1.0)
        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), timeout=0.1)
        assert task.done() is False
    finally:
        runtime._closed = True
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_background_delivery_poll_does_not_block_realtime_loop() -> None:
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
    try:
        assert await asyncio.to_thread(started.wait, 1.0)
        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), timeout=0.1)
        assert task.done() is False
    finally:
        controller._shutdown.set()
        release.set()
        await asyncio.wait_for(task, timeout=1.0)
