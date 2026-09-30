from jarvis.config import DEFAULT_GEMINI_REALTIME_MODEL
from jarvis.setup import _migrate_legacy_gemini_realtime_setting


def test_setup_migrates_legacy_gemini_realtime_model() -> None:
    settings = {
        "JARVIS_GEMINI_REALTIME_MODEL": "gemini-3.1-flash-live-preview",
    }

    _migrate_legacy_gemini_realtime_setting(settings)

    assert settings["JARVIS_GEMINI_REALTIME_MODEL"] == DEFAULT_GEMINI_REALTIME_MODEL


def test_setup_preserves_explicit_nonlegacy_gemini_realtime_model() -> None:
    settings = {
        "JARVIS_GEMINI_REALTIME_MODEL": "custom-live-model",
    }

    _migrate_legacy_gemini_realtime_setting(settings)

    assert settings["JARVIS_GEMINI_REALTIME_MODEL"] == "custom-live-model"
