from dataclasses import replace

import pytest

from jarvis import ai_provider


def targets():
    from jarvis.model_routing.gemini import (
        GeminiFallbackConfig,
        build_gemini_role_targets,
    )

    return build_gemini_role_targets(
        role="work",
        model="gemini-test",
        adapter_id="gemini",
        config=GeminiFallbackConfig(enabled=True),
    )


def test_independent_keys(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "free-canary-do-not-log")
    monkeypatch.setenv("JARVIS_GEMINI_PAID_API_KEY", "paid-canary-do-not-log")
    free, paid = targets()
    assert ai_provider.resolve_target_api_key(free) == "free-canary-do-not-log"
    assert ai_provider.resolve_target_api_key(paid) == "paid-canary-do-not-log"
    assert ai_provider.provider_api_key("gemini") == "free-canary-do-not-log"
    assert ai_provider.gemini_credential_ref("free") == "GOOGLE_API_KEY"
    assert ai_provider.gemini_credential_ref("paid") == "JARVIS_GEMINI_PAID_API_KEY"


def test_tts_not_paid_fallback(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "free-canary")
    monkeypatch.setenv("JARVIS_GEMINI_PAID_API_KEY", "paid-canary")
    monkeypatch.setenv("JARVIS_TTS_GOOGLE_API_KEY", "tts-canary")
    assert ai_provider.require_tts_api_key("gemini") == "tts-canary"
    _, paid = targets()
    assert ai_provider.resolve_target_api_key(paid) == "paid-canary"
    monkeypatch.delenv("JARVIS_TTS_GOOGLE_API_KEY")
    assert ai_provider.require_tts_api_key("gemini") == "free-canary"


def test_missing_paid_key_never_uses_free_as_paid(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "free-canary")
    _, paid = targets()
    with pytest.raises(RuntimeError, match="JARVIS_GEMINI_PAID_API_KEY") as exc:
        ai_provider.resolve_target_api_key(paid)
    assert "free-canary" not in str(exc.value)


def test_secrets_absent_from_diagnostics(monkeypatch, caplog):
    monkeypatch.setenv("GOOGLE_API_KEY", "free-canary-do-not-log")
    monkeypatch.setenv("JARVIS_GEMINI_PAID_API_KEY", "paid-canary-do-not-log")
    free, paid = targets()
    assert ai_provider.resolve_target_api_key(paid) == "paid-canary-do-not-log"
    bad = replace(free, credential_ref="PATH")
    with pytest.raises(ValueError):
        ai_provider.resolve_target_api_key(bad)
    visible = caplog.text + repr((free, paid))
    assert "free-canary-do-not-log" not in visible
    assert "paid-canary-do-not-log" not in visible


def test_wrong_provider_cannot_read_paid_gemini_credential(monkeypatch):
    monkeypatch.setenv("JARVIS_GEMINI_PAID_API_KEY", "paid-canary")
    _, paid = targets()
    with pytest.raises(ValueError):
        ai_provider.resolve_target_api_key(replace(paid, provider_id="openai"))
