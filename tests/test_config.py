from pathlib import Path

import pytest

from jarvis.config import JarvisConfig


@pytest.fixture(autouse=True)
def _isolate_machine_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep config unit tests independent from the real PC machine profile."""
    monkeypatch.setenv(
        "JARVIS_MACHINE_CONFIG",
        str(tmp_path / "machine.json"),
    )
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)


def test_voice_configuration_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_AI_PROVIDER", " GEMINI ")
    monkeypatch.setenv("JARVIS_TTS_PROVIDER", " OPENAI ")
    monkeypatch.setenv("JARVIS_REALTIME_MODEL", " model-x ")
    monkeypatch.setenv("JARVIS_REALTIME_VOICE", " voice-y ")
    monkeypatch.setenv("JARVIS_GEMINI_REALTIME_MODEL", " gemini-x ")
    monkeypatch.setenv("JARVIS_GEMINI_REALTIME_VOICE", " Charon ")
    monkeypatch.setenv("JARVIS_GEMINI_TTS_MODEL", " gemini-3.8-flash-lite-tts ")
    monkeypatch.setenv("JARVIS_TTS_PROJECT_BILLING_ISOLATION_VERIFIED", "true")
    monkeypatch.setenv("JARVIS_SHOW_TRANSCRIPT", "off")
    monkeypatch.setenv("JARVIS_STARTUP_GREETING", "off")
    monkeypatch.setenv("JARVIS_WAKE_MODEL_PATH", " C:\\models\\jarvis.onnx ")
    monkeypatch.setenv("JARVIS_WAKE_THRESHOLD", "0.72")
    monkeypatch.setenv("JARVIS_AUDIO_PRE_ROLL_SECONDS", "0.8")
    monkeypatch.setenv("JARVIS_LIVE_CONTEXT_RECENT_TURNS", "7")
    monkeypatch.setenv(
        "JARVIS_AUDIO_OUTPUT_WASAPI_DEVICE",
        " {0.0.0.00000000}.{render-endpoint} ",
    )
    monkeypatch.setenv("JARVIS_MEMORY_ENABLED", "true")
    monkeypatch.setenv("JARVIS_MEMORY_CANDIDATE_EXTRACTION_ENABLED", "true")
    monkeypatch.setenv("JARVIS_MEMORY_CANDIDATE_EXTRACTION_MODEL", " extractor-x ")
    monkeypatch.setenv("JARVIS_VISION_ENABLED", "true")
    monkeypatch.setenv("JARVIS_BLAZEFACE_MODEL_PATH", " C:\\models\\blazeface.tflite ")
    monkeypatch.setenv("JARVIS_VISION_DEFAULT_CAMERA", " POCKET3 ")
    monkeypatch.setenv("JARVIS_VISION_LENOVO_DEVICE_INDEX", "2")
    monkeypatch.setenv("JARVIS_VISION_POCKET3_DEVICE_INDEX", "4")
    monkeypatch.setenv("JARVIS_SPEAKER_SHADOW_ENABLED", "true")

    config = JarvisConfig.from_environment()

    assert config.ai_provider == "gemini"
    assert config.tts_provider == "openai"
    assert config.realtime_provider == "gemini"
    assert config.realtime_model == "model-x"
    assert config.realtime_voice == "voice-y"
    assert config.gemini_realtime_model == "gemini-x"
    assert config.gemini_realtime_voice == "Charon"
    assert config.gemini_tts_model == "gemini-3.8-flash-lite-tts"
    assert config.tts_project_billing_isolation_verified is True
    assert config.show_transcript is False
    assert config.startup_greeting_enabled is False
    assert config.wake_model_path == "C:\\models\\jarvis.onnx"
    assert config.wake_threshold == 0.72
    assert config.audio_pre_roll_seconds == 0.8
    assert config.live_context_recent_turns == 7
    assert config.audio_output_wasapi_device == "{0.0.0.00000000}.{render-endpoint}"
    assert config.memory_enabled is True
    assert config.memory_candidate_extraction_enabled is True
    assert config.memory_candidate_extraction_model == "extractor-x"
    assert config.vision_enabled is True
    assert config.vision_head_model_path == "C:\\models\\blazeface.tflite"
    assert config.vision_default_camera == "pocket3"
    assert config.vision_lenovo_device_index == 2
    assert config.vision_pocket3_device_index == 4
    assert config.speaker_shadow_enabled is True


def test_tts_defaults_to_current_quality_first_model() -> None:
    config = JarvisConfig()
    assert config.gemini_tts_model == "gemini-3.8-flash-tts"
    assert config.gemini_realtime_voice == "Charon"
    assert config.tts_project_billing_isolation_verified is False


def test_tts_provider_defaults_to_gemini_independent_of_brain() -> None:
    assert JarvisConfig(ai_provider="openai").tts_provider == "gemini"
    assert JarvisConfig(ai_provider="gemini").tts_provider == "gemini"


def test_invalid_tts_provider_fails_truthfully() -> None:
    with pytest.raises(ValueError, match="JARVIS_TTS_PROVIDER"):
        JarvisConfig(tts_provider="unknown")


def test_memory_candidate_extraction_is_default_off() -> None:
    config = JarvisConfig()

    assert config.memory_candidate_extraction_enabled is False
    assert config.memory_candidate_extraction_model is None
    assert not hasattr(config, "memory_candidate_extraction_provider")


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "memory_enabled": False,
            "memory_candidate_extraction_enabled": True,
            "memory_candidate_extraction_model": "model-x",
        },
        {
            "memory_enabled": True,
            "memory_candidate_extraction_enabled": True,
            "memory_candidate_extraction_model": None,
        },
    ],
)
def test_memory_candidate_extraction_requires_explicit_configuration(
    kwargs: dict,
) -> None:
    with pytest.raises(ValueError, match="CANDIDATE_EXTRACTION"):
        JarvisConfig(**kwargs)


def test_invalid_ai_provider_fails_truthfully() -> None:
    with pytest.raises(ValueError, match="JARVIS_AI_PROVIDER"):
        JarvisConfig(ai_provider="unknown")


def test_invalid_boolean_setting_fails_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_SHOW_TRANSCRIPT", "sometimes")

    with pytest.raises(ValueError, match="JARVIS_SHOW_TRANSCRIPT"):
        JarvisConfig.from_environment()


def test_invalid_startup_greeting_boolean_setting_fails_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_STARTUP_GREETING", "sometimes")

    with pytest.raises(ValueError, match="JARVIS_STARTUP_GREETING"):
        JarvisConfig.from_environment()


def test_invalid_vision_boolean_setting_fails_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_VISION_ENABLED", "sometimes")

    with pytest.raises(ValueError, match="JARVIS_VISION_ENABLED"):
        JarvisConfig.from_environment()


def test_invalid_speaker_shadow_boolean_setting_fails_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_SPEAKER_SHADOW_ENABLED", "sometimes")

    with pytest.raises(ValueError, match="JARVIS_SPEAKER_SHADOW_ENABLED"):
        JarvisConfig.from_environment()


def test_invalid_wake_buffer_and_live_context_settings_fail_truthfully() -> None:
    with pytest.raises(ValueError, match="wake_threshold"):
        JarvisConfig(wake_threshold=0)
    with pytest.raises(ValueError, match="pre-roll"):
        JarvisConfig(audio_ring_buffer_seconds=1, audio_pre_roll_seconds=2)
    with pytest.raises(ValueError, match="live_context_recent_turns"):
        JarvisConfig(live_context_recent_turns=0)
    with pytest.raises(TypeError, match="live_context_recent_turns"):
        JarvisConfig(live_context_recent_turns=True)


def test_invalid_live_context_environment_value_fails_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_LIVE_CONTEXT_RECENT_TURNS", "many")

    with pytest.raises(ValueError, match="JARVIS_LIVE_CONTEXT_RECENT_TURNS"):
        JarvisConfig.from_environment()


def test_work_orchestration_requires_production_postgres() -> None:
    with pytest.raises(ValueError, match="WORK_DBOS_DATABASE_URL"):
        JarvisConfig(work_orchestration_enabled=True)

    with pytest.raises(ValueError, match="must use Postgres"):
        JarvisConfig(
            work_orchestration_enabled=True,
            work_dbos_database_url="sqlite:///work.sqlite3",
        )

    config = JarvisConfig(
        work_orchestration_enabled=True,
        work_dbos_database_url="postgresql://localhost/jarvis_work",
    )
    assert config.work_orchestration_enabled is True
    assert config.work_dbos_database_url == "postgresql://localhost/jarvis_work"


def test_github_promotion_requires_non_secret_identifiers() -> None:
    with pytest.raises(ValueError, match="CLIENT_ID"):
        JarvisConfig(github_promotion_enabled=True)

    config = JarvisConfig(
        github_promotion_enabled=True,
        github_app_client_id="Iv1.phase9",
        github_app_installation_id=12345,
        github_repository_full_name="gkgajendra0/JARVIS_V1",
        github_app_secret_id="github-promotion-private-key",
    )
    assert config.github_promotion_enabled is True
    assert config.github_app_installation_id == 12345
    assert config.github_repository_full_name == "gkgajendra0/JARVIS_V1"
    assert config.github_app_secret_id == "github-promotion-private-key"


def test_invalid_github_promotion_identifiers_fail_closed() -> None:
    with pytest.raises(ValueError, match="INSTALLATION_ID"):
        JarvisConfig(
            github_promotion_enabled=True,
            github_app_client_id="Iv1.phase9",
            github_app_installation_id=0,
            github_repository_full_name="gkgajendra0/JARVIS_V1",
            github_app_secret_id="github-promotion-private-key",
        )
    with pytest.raises(ValueError, match="github_expected_ci_app_id"):
        JarvisConfig(github_expected_ci_app_id=0)


def test_vision_camera_defaults_to_lenovo_primary() -> None:
    config = JarvisConfig()

    assert config.vision_default_camera == "lenovo"
    assert config.vision_lenovo_device_index == 0
    assert config.vision_pocket3_device_index == 1


def test_invalid_vision_camera_configuration_fails_truthfully() -> None:
    with pytest.raises(ValueError, match="vision_default_camera"):
        JarvisConfig(vision_default_camera="unknown")
    with pytest.raises(ValueError, match="vision_lenovo_device_index"):
        JarvisConfig(vision_lenovo_device_index=-1)
    with pytest.raises(TypeError, match="vision_pocket3_device_index"):
        JarvisConfig(vision_pocket3_device_index=True)
