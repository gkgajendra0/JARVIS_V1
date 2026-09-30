from __future__ import annotations

import asyncio

import pytest

from jarvis.config import JarvisConfig
from jarvis.provider_model_lifecycle import GeminiLiveLifecycleResult
from jarvis.voice import production_runtime


class FakeRuntime:
    def __init__(self) -> None:
        self.shutdown_calls = 0

    def request_shutdown(self) -> None:
        self.shutdown_calls += 1


@pytest.mark.asyncio
async def test_lifecycle_trigger_reconciles_immediately_and_recycles_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def reconcile(config: JarvisConfig):
        nonlocal calls
        calls += 1
        assert config.gemini_realtime_model == "gemini-old-live"
        return GeminiLiveLifecycleResult(
            current_model="gemini-old-live",
            status="migrated",
            replacement_model="gemini-new-live",
        )

    monkeypatch.setattr(
        production_runtime,
        "_reconcile_provider_model_lifecycle",
        reconcile,
    )
    runtime = FakeRuntime()
    migrated = asyncio.Event()
    trigger = asyncio.Event()
    trigger.set()

    await asyncio.wait_for(
        production_runtime._run_provider_model_lifecycle_watch(
            JarvisConfig(
                ai_provider="gemini",
                gemini_realtime_model="gemini-old-live",
            ),
            runtime,
            migrated,
            trigger,
            asyncio.Event(),
            poll_seconds=3600,
        ),
        timeout=1,
    )

    assert calls == 1
    assert migrated.is_set()
    assert runtime.shutdown_calls == 1


@pytest.mark.asyncio
async def test_pending_migration_rollback_recycles_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def rollback(config: JarvisConfig):
        assert config.gemini_realtime_model == "gemini-new-live"
        return GeminiLiveLifecycleResult(
            current_model="gemini-new-live",
            status="rolled_back",
            replacement_model="gemini-old-live",
        )

    async def forbidden_reconcile(config: JarvisConfig):
        del config
        raise AssertionError("reconcile should not run after successful rollback")

    monkeypatch.setattr(
        production_runtime,
        "_rollback_provider_model_lifecycle",
        rollback,
    )
    monkeypatch.setattr(
        production_runtime,
        "_reconcile_provider_model_lifecycle",
        forbidden_reconcile,
    )
    runtime = FakeRuntime()
    migrated = asyncio.Event()
    lifecycle_trigger = asyncio.Event()
    rollback_trigger = asyncio.Event()
    lifecycle_trigger.set()
    rollback_trigger.set()

    await asyncio.wait_for(
        production_runtime._run_provider_model_lifecycle_watch(
            JarvisConfig(
                ai_provider="gemini",
                gemini_realtime_model="gemini-new-live",
            ),
            runtime,
            migrated,
            lifecycle_trigger,
            rollback_trigger,
            poll_seconds=3600,
        ),
        timeout=1,
    )

    assert migrated.is_set()
    assert runtime.shutdown_calls == 1


@pytest.mark.asyncio
async def test_pending_migration_failure_runs_validated_rollback_and_recycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def rollback(config: JarvisConfig):
        assert config.gemini_realtime_model == "gemini-new-live"
        return GeminiLiveLifecycleResult(
            current_model="gemini-new-live",
            status="rolled_back",
            replacement_model="gemini-old-live",
        )

    async def reconcile(config: JarvisConfig):
        raise AssertionError("reconcile should not run after successful rollback")

    monkeypatch.setattr(
        production_runtime,
        "_rollback_provider_model_lifecycle",
        rollback,
    )
    monkeypatch.setattr(
        production_runtime,
        "_reconcile_provider_model_lifecycle",
        reconcile,
    )

    runtime = FakeRuntime()
    migrated = asyncio.Event()
    lifecycle_trigger = asyncio.Event()
    rollback_trigger = asyncio.Event()
    lifecycle_trigger.set()
    rollback_trigger.set()

    await asyncio.wait_for(
        production_runtime._run_provider_model_lifecycle_watch(
            JarvisConfig(
                ai_provider="gemini",
                gemini_realtime_model="gemini-new-live",
            ),
            runtime,
            migrated,
            lifecycle_trigger,
            rollback_trigger,
            poll_seconds=3600,
        ),
        timeout=1,
    )

    assert migrated.is_set()
    assert runtime.shutdown_calls == 1


@pytest.mark.asyncio
async def test_periodic_lifecycle_check_keeps_runtime_when_model_is_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def reconcile(config: JarvisConfig):
        nonlocal calls
        calls += 1
        if calls == 1:
            return GeminiLiveLifecycleResult(
                current_model=config.gemini_realtime_model,
                status="current",
            )
        return GeminiLiveLifecycleResult(
            current_model=config.gemini_realtime_model,
            status="migrated",
            replacement_model="gemini-new-live",
        )

    monkeypatch.setattr(
        production_runtime,
        "_reconcile_provider_model_lifecycle",
        reconcile,
    )
    runtime = FakeRuntime()
    migrated = asyncio.Event()
    trigger = asyncio.Event()

    await asyncio.wait_for(
        production_runtime._run_provider_model_lifecycle_watch(
            JarvisConfig(
                ai_provider="gemini",
                gemini_realtime_model="gemini-old-live",
            ),
            runtime,
            migrated,
            trigger,
            asyncio.Event(),
            poll_seconds=0.01,
        ),
        timeout=1,
    )

    assert calls == 2
    assert migrated.is_set()
    assert runtime.shutdown_calls == 1
