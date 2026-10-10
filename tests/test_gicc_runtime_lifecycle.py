from __future__ import annotations

from typing import Any

import pytest

from jarvis.config import JarvisConfig
from jarvis.voice import canonical_active_speaker_runtime as active_runtime


class _FakeManagedRuntime:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def start(self) -> None:
        self._events.append("gicc-start")

    async def close(self) -> None:
        self._events.append("gicc-close")


@pytest.mark.asyncio
async def test_gicc_continuation_runtime_matches_voice_runtime_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    managed_runtime = _FakeManagedRuntime(events)
    controller = active_runtime.CanonicalActiveSpeakerRuntimeController(
        JarvisConfig(),
        object(),  # type: ignore[arg-type]
        gicc_runtime=managed_runtime,
    )

    assert controller._gicc_runtime is managed_runtime

    async def fake_base_run(self: Any) -> None:
        del self
        events.append("voice-run")

    monkeypatch.setattr(
        active_runtime.VoiceRuntimeController,
        "run",
        fake_base_run,
    )

    await controller.run()

    assert events == ["gicc-start", "voice-run", "gicc-close"]
