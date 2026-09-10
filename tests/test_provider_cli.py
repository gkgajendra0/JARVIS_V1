from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis import provider_cli
from jarvis.ai_provider import AI_PROVIDER_SETTING
from jarvis.machine_config import save_machine_settings


def _machine_path(tmp_path: Path) -> Path:
    return tmp_path / "machine.json"


def test_switch_provider_requires_selected_credential_and_preserves_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _machine_path(tmp_path)
    save_machine_settings(
        {
            AI_PROVIDER_SETTING: "gemini",
            "JARVIS_LOG_LEVEL": "DEBUG",
        },
        path,
    )
    monkeypatch.setattr(provider_cli, "default_machine_config_path", lambda: path)
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-openai-key")

    assert provider_cli.switch_provider("openai") == 0

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["settings"][AI_PROVIDER_SETTING] == "openai"
    assert payload["settings"]["JARVIS_LOG_LEVEL"] == "DEBUG"
    output = capsys.readouterr().out
    assert "super-secret-openai-key" not in output
    assert "gemini -> openai" in output


def test_switch_provider_does_not_change_profile_when_key_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _machine_path(tmp_path)
    save_machine_settings({AI_PROVIDER_SETTING: "gemini"}, path)
    monkeypatch.setattr(provider_cli, "default_machine_config_path", lambda: path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert provider_cli.switch_provider("openai") == 2

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["settings"][AI_PROVIDER_SETTING] == "gemini"


def test_show_provider_reports_key_presence_without_printing_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _machine_path(tmp_path)
    save_machine_settings({AI_PROVIDER_SETTING: "openai"}, path)
    monkeypatch.setattr(provider_cli, "default_machine_config_path", lambda: path)
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-print-me")

    assert provider_cli.show_provider() == 0

    output = capsys.readouterr().out
    assert "JARVIS active AI provider: openai" in output
    assert "Credential variable: OPENAI_API_KEY" in output
    assert "Credential available: yes" in output
    assert "do-not-print-me" not in output
