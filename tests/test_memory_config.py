from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.config import JarvisConfig
from jarvis.machine_config import load_machine_settings, save_machine_settings


@pytest.fixture(autouse=True)
def _isolate_machine_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(tmp_path / "machine.json"))
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)


def test_memory_rollout_is_disabled_by_default() -> None:
    assert JarvisConfig.from_environment().memory_enabled is False


def test_memory_rollout_reads_explicit_environment_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_MEMORY_ENABLED", "true")
    assert JarvisConfig.from_environment().memory_enabled is True


def test_invalid_memory_rollout_value_fails_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_MEMORY_ENABLED", "sometimes")
    with pytest.raises(ValueError, match="JARVIS_MEMORY_ENABLED"):
        JarvisConfig.from_environment()


def test_memory_rollout_setting_may_be_persisted_without_secrets(
    tmp_path: Path,
) -> None:
    path = tmp_path / "persisted-machine.json"
    save_machine_settings({"JARVIS_MEMORY_ENABLED": "true"}, path)
    assert load_machine_settings(path) == {"JARVIS_MEMORY_ENABLED": "true"}
