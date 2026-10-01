from __future__ import annotations

from typing import Any

import pytest

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
    controller = object.__new__(active_runtime.CanonicalActiveSpeakerRuntimeController)
    controller._memory_runtime = None
    controller._memory_query_coordinator = None
    controller._research_service = None
    controller._capability_runtime = None
    controller._work_runtime = None
    controller._gicc_runtime = _FakeManagedRuntime(events)
    controller._session_ready_for_inactivity = False
    controller._user_is_speaking = False
    controller._session_conversation = None
    controller._agent_state = "unavailable"
    controller._live_session = None

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
