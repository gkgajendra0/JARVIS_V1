from __future__ import annotations

from typing import Any

import pytest

from jarvis.config import JarvisConfig
from jarvis.voice.livekit_session import _create_realtime_model


def test_openai_realtime_uses_bounded_retention_ratio_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    sentinel = object()

    def fake_model(**kwargs: Any) -> object:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(
        "jarvis.voice.livekit_session.openai.realtime.RealtimeModel",
        fake_model,
    )

    model = _create_realtime_model(JarvisConfig(ai_provider="openai"))

    assert model is sentinel
    truncation = captured["truncation"]
    assert truncation.type == "retention_ratio"
    assert truncation.retention_ratio == 0.75
    assert truncation.token_limits is not None
    assert truncation.token_limits.post_instructions == 12_000
