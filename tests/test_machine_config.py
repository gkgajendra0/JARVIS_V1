from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.config import JarvisConfig
from jarvis.machine_config import (
    configured_alias_text,
    load_machine_settings,
    save_machine_settings,
)


def test_machine_config_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "machine.json"
    saved = save_machine_settings(
        {
            "JARVIS_AI_PROVIDER": "gemini",
            "JARVIS_AUDIO_INPUT_DEVICE": "name:Osmo|hostapi:Windows WASAPI",
        },
        path,
    )

    assert saved == path
    assert load_machine_settings(path) == {
        "JARVIS_AI_PROVIDER": "gemini",
        "JARVIS_AUDIO_INPUT_DEVICE": "name:Osmo|hostapi:Windows WASAPI",
    }


def test_machine_config_persists_tts_provider_but_never_tts_secret(
    tmp_path: Path,
) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings(
        {
            "JARVIS_AI_PROVIDER": "openai",
            "JARVIS_TTS_PROVIDER": "gemini",
            "JARVIS_GEMINI_TTS_MODEL": "gemini-3.8-flash-tts",
            "JARVIS_TTS_PROJECT_BILLING_ISOLATION_VERIFIED": "true",
        },
        path,
    )

    settings = load_machine_settings(path)
    assert settings["JARVIS_AI_PROVIDER"] == "openai"
    assert settings["JARVIS_TTS_PROVIDER"] == "gemini"
    assert settings["JARVIS_GEMINI_TTS_MODEL"] == "gemini-3.8-flash-tts"
    assert settings["JARVIS_TTS_PROJECT_BILLING_ISOLATION_VERIFIED"] == "true"

    with pytest.raises(ValueError, match="may not be persisted"):
        save_machine_settings(
            {"JARVIS_TTS_GOOGLE_API_KEY": "secret"},
            tmp_path / "secret-machine.json",
        )


def test_machine_config_refuses_unapproved_secret(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="may not be persisted"):
        save_machine_settings(
            {"OPENAI_API_KEY": "secret"},
            tmp_path / "machine.json",
        )


def test_jarvis_config_uses_machine_profile_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings(
        {
            "JARVIS_AI_PROVIDER": "gemini",
            "JARVIS_WAKE_MODEL_PATH": "C:\\models\\jarvis.onnx",
            "JARVIS_AUDIO_INPUT_DEVICE": "name:Osmo|hostapi:Windows WASAPI",
            "JARVIS_AUDIO_OUTPUT_DEVICE": "name:TV|hostapi:Windows WASAPI",
            "JARVIS_VISION_ENABLED": "true",
        },
        path,
    )
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)
    monkeypatch.setenv("JARVIS_AI_PROVIDER", "openai")
    monkeypatch.setenv(
        "JARVIS_AUDIO_OUTPUT_DEVICE",
        "name:Stale Bluetooth|hostapi:Windows WASAPI",
    )

    config = JarvisConfig.from_environment()
    assert config.ai_provider == "gemini"
    assert config.wake_model_path == "C:\\models\\jarvis.onnx"
    assert config.audio_input_device == "name:Osmo|hostapi:Windows WASAPI"
    assert config.audio_output_device == "name:TV|hostapi:Windows WASAPI"
    assert config.vision_enabled is True


def test_legacy_realtime_provider_machine_setting_migrates_without_breaking_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings({"JARVIS_REALTIME_PROVIDER": "gemini"}, path)
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))
    monkeypatch.delenv("JARVIS_AI_PROVIDER", raising=False)
    monkeypatch.delenv("JARVIS_REALTIME_PROVIDER", raising=False)
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)

    assert JarvisConfig.from_environment().ai_provider == "gemini"


def test_explicit_diagnostic_mode_allows_environment_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings(
        {"JARVIS_AI_PROVIDER": "gemini"},
        path,
    )
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))
    monkeypatch.setenv("JARVIS_RUNTIME_ENV_OVERRIDES", "true")
    monkeypatch.setenv("JARVIS_AI_PROVIDER", "openai")

    assert JarvisConfig.from_environment().ai_provider == "openai"


def test_environment_is_used_when_machine_setting_is_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings({}, path)
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)
    monkeypatch.setenv("JARVIS_AI_PROVIDER", "gemini")

    assert JarvisConfig.from_environment().ai_provider == "gemini"


def test_alias_resolution_preserves_machine_first_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = (
        "JARVIS_DEVELOPMENT_TEST_DOCKER_IMAGE",
        "JARVIS_DEV_TEST_DOCKER_IMAGE",
    )
    settings = {
        "JARVIS_DEV_TEST_DOCKER_IMAGE": "persisted-legacy:local",
    }
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)
    monkeypatch.setenv(
        "JARVIS_DEVELOPMENT_TEST_DOCKER_IMAGE",
        "stale-shell:local",
    )

    assert configured_alias_text(names, settings) == "persisted-legacy:local"

    monkeypatch.setenv("JARVIS_RUNTIME_ENV_OVERRIDES", "true")
    assert configured_alias_text(names, settings) == "stale-shell:local"


def test_jarvis_config_preserves_machine_precedence_across_image_aliases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings(
        {
            "JARVIS_DEV_TEST_DOCKER_IMAGE": "persisted-legacy:local",
        },
        path,
    )
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(path))
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)
    monkeypatch.setenv(
        "JARVIS_DEVELOPMENT_TEST_DOCKER_IMAGE",
        "stale-shell:local",
    )

    config = JarvisConfig.from_environment()

    assert config.development_test_docker_image == "persisted-legacy:local"


def test_work_runtime_non_secret_settings_can_be_persisted(tmp_path: Path) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings(
        {
            "JARVIS_WORK_ORCHESTRATION_ENABLED": "true",
            "JARVIS_WORK_ORCHESTRATION_MODEL": "model-x",
            "JARVIS_GLOBAL_BRAIN_ROUTER_MODE": "shadow",
            "JARVIS_WORK_GLOBAL_CONCURRENCY": "4",
            "JARVIS_DEV_TEST_DOCKER_IMAGE": "jarvis-dev-tests:local",
        },
        path,
    )
    settings = load_machine_settings(path)
    assert settings["JARVIS_WORK_ORCHESTRATION_ENABLED"] == "true"
    assert settings["JARVIS_WORK_ORCHESTRATION_MODEL"] == "model-x"
    assert settings["JARVIS_GLOBAL_BRAIN_ROUTER_MODE"] == "shadow"
    assert settings["JARVIS_WORK_GLOBAL_CONCURRENCY"] == "4"
    assert settings["JARVIS_DEV_TEST_DOCKER_IMAGE"] == "jarvis-dev-tests:local"


def test_development_test_image_alias_can_be_persisted(tmp_path: Path) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings(
        {
            "JARVIS_DEVELOPMENT_TEST_DOCKER_IMAGE": "jarvis-dev-tests:local",
        },
        path,
    )

    settings = load_machine_settings(path)
    assert settings["JARVIS_DEVELOPMENT_TEST_DOCKER_IMAGE"] == "jarvis-dev-tests:local"


def test_work_database_url_cannot_be_persisted(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="may not be persisted"):
        save_machine_settings(
            {
                "JARVIS_WORK_DBOS_DATABASE_URL": (
                    "postgresql://jarvis:secret@localhost/jarvis_work"
                )
            },
            tmp_path / "machine.json",
        )


def test_github_promotion_non_secret_settings_can_be_persisted(tmp_path: Path) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings(
        {
            "JARVIS_GITHUB_PROMOTION_ENABLED": "true",
            "JARVIS_GITHUB_APP_CLIENT_ID": "Iv1.phase9",
            "JARVIS_GITHUB_APP_INSTALLATION_ID": "12345",
            "JARVIS_GITHUB_REPOSITORY": "gkgajendra0/JARVIS_V1",
            "JARVIS_GITHUB_APP_SECRET_ID": "github-promotion-private-key",
            "JARVIS_GITHUB_BASE_BRANCH": "main",
            "JARVIS_GITHUB_WORKFLOW_FILE": "code-quality.yml",
            "JARVIS_GITHUB_EXPECTED_CI_APP_ID": "15368",
        },
        path,
    )
    settings = load_machine_settings(path)
    assert settings["JARVIS_GITHUB_PROMOTION_ENABLED"] == "true"
    assert settings["JARVIS_GITHUB_APP_SECRET_ID"] == "github-promotion-private-key"
    assert "PRIVATE_KEY" not in settings


def test_github_private_key_plaintext_cannot_be_persisted(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="may not be persisted"):
        save_machine_settings(
            {"JARVIS_GITHUB_APP_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----"},
            tmp_path / "machine.json",
        )


def test_default_media_target_is_persistable_non_secret_setting(tmp_path: Path) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings(
        {"JARVIS_DEFAULT_MEDIA_TARGET": "Hisense TV"},
        path,
    )

    settings = load_machine_settings(path)
    assert settings["JARVIS_DEFAULT_MEDIA_TARGET"] == "Hisense TV"


def test_jev_admission_settings_are_persistable_but_key_is_not(tmp_path: Path) -> None:
    path = tmp_path / "machine.json"
    save_machine_settings(
        {
            "JARVIS_JEV_BOUNDED_DECISIONS_ENABLED": "true",
            "JARVIS_JEV_BENCHMARK_ADMITTED": "true",
            "JARVIS_JEV_BENCHMARK_REPORT_PATH": "C:\\JARVIS\\acceptance\\jev.json",
            "JARVIS_JEV_MODEL": "jev-latest",
            "JARVIS_JEV_ENDPOINT": "https://api.typesafe.ai/v1/systemone",
            "JARVIS_JEV_MIN_CONFIDENCE": "0.95",
        },
        path,
    )

    settings = load_machine_settings(path)
    assert settings["JARVIS_JEV_BOUNDED_DECISIONS_ENABLED"] == "true"
    assert settings["JARVIS_JEV_BENCHMARK_ADMITTED"] == "true"
    assert settings["JARVIS_JEV_MIN_CONFIDENCE"] == "0.95"
    assert settings["JARVIS_JEV_MODEL"] == "jev-latest"

    with pytest.raises(ValueError, match="may not be persisted"):
        save_machine_settings(
            {"JEV_API_KEY": "secret"},
            tmp_path / "jev-secret.json",
        )
