from __future__ import annotations

from jarvis.config import JarvisConfig
from jarvis.voice.context_sync import (
    ProviderContextSyncMode,
    provider_context_sync_capability,
)


def test_openai_realtime_allows_mid_session_context_update() -> None:
    capability = provider_context_sync_capability(
        JarvisConfig(realtime_provider="openai", realtime_model="gpt-realtime")
    )

    assert capability.provider == "openai"
    assert capability.model == "gpt-realtime"
    assert capability.mode is ProviderContextSyncMode.MID_SESSION_UPDATE
    assert capability.automatic_mid_session_sync_supported is True


def test_gemini_31_fails_closed_to_initial_history_only() -> None:
    capability = provider_context_sync_capability(
        JarvisConfig(
            realtime_provider="gemini",
            gemini_realtime_model="gemini-3.1-flash-live-preview",
        )
    )

    assert capability.provider == "gemini"
    assert capability.mode is ProviderContextSyncMode.INITIAL_HISTORY_ONLY
    assert capability.automatic_mid_session_sync_supported is False
    assert "ignores" in capability.reason


def test_older_gemini_realtime_model_keeps_generic_update_capability() -> None:
    capability = provider_context_sync_capability(
        JarvisConfig(
            realtime_provider="gemini",
            gemini_realtime_model="gemini-2.5-flash-native-audio-preview-12-2025",
        )
    )

    assert capability.mode is ProviderContextSyncMode.MID_SESSION_UPDATE
    assert capability.automatic_mid_session_sync_supported is True


def test_context_sync_capability_validates_config_type() -> None:
    try:
        provider_context_sync_capability(object())  # type: ignore[arg-type]
    except TypeError as exc:
        assert "JarvisConfig" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected TypeError")
