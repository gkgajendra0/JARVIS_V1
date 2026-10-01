from pathlib import Path

import pytest

from jarvis.config import JarvisConfig
from jarvis.dev_supervisor import (
    DevSupervisorConfig,
    VoiceControlServer,
    _runtime_supervisor_config_from_environment,
)
from jarvis.runtime_lane import (
    GICC_MODE_ENV,
    RUNTIME_LANE_ENV,
    GiccMode,
    RuntimeLane,
    configured_gicc_mode,
    configured_runtime_lane,
)


@pytest.fixture(autouse=True)
def _isolate_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("JARVIS_MACHINE_CONFIG", str(tmp_path / "machine.json"))
    monkeypatch.delenv("JARVIS_RUNTIME_ENV_OVERRIDES", raising=False)
    monkeypatch.delenv(RUNTIME_LANE_ENV, raising=False)
    monkeypatch.delenv(GICC_MODE_ENV, raising=False)


def test_direct_voice_defaults_fail_closed_to_production_off() -> None:
    assert configured_runtime_lane({}) is RuntimeLane.PRODUCTION
    assert (
        configured_gicc_mode(RuntimeLane.PRODUCTION, {})
        is GiccMode.OFF
    )

    config = JarvisConfig.from_environment()

    assert config.runtime_lane is RuntimeLane.PRODUCTION
    assert config.gicc_mode is GiccMode.OFF


def test_development_lane_defaults_to_shadow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RUNTIME_LANE_ENV, "development")

    config = JarvisConfig.from_environment()

    assert config.runtime_lane is RuntimeLane.DEVELOPMENT
    assert config.gicc_mode is GiccMode.SHADOW


def test_development_apply_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RUNTIME_LANE_ENV, "development")
    monkeypatch.setenv(GICC_MODE_ENV, "apply")

    config = JarvisConfig.from_environment()

    assert config.runtime_lane is RuntimeLane.DEVELOPMENT
    assert config.gicc_mode is GiccMode.APPLY


def test_production_apply_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RUNTIME_LANE_ENV, "production")
    monkeypatch.setenv(GICC_MODE_ENV, "apply")

    with pytest.raises(ValueError, match="GICC APPLY is disabled"):
        JarvisConfig.from_environment()


def test_invalid_runtime_lane_and_gicc_mode_fail_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RUNTIME_LANE_ENV, "maybe")
    with pytest.raises(ValueError, match=RUNTIME_LANE_ENV):
        JarvisConfig.from_environment()

    monkeypatch.setenv(RUNTIME_LANE_ENV, "development")
    monkeypatch.setenv(GICC_MODE_ENV, "automatic")
    with pytest.raises(ValueError, match=GICC_MODE_ENV):
        JarvisConfig.from_environment()


def test_dev_supervisor_child_receives_development_lane() -> None:
    control = VoiceControlServer(runtime_lane=RuntimeLane.DEVELOPMENT)
    try:
        assert control.child_environment()[RUNTIME_LANE_ENV] == "development"
    finally:
        control.close()


def test_production_supervisor_config_is_explicitly_production() -> None:
    config = _runtime_supervisor_config_from_environment()

    assert config.git_updates_enabled is False
    assert config.runtime_lane is RuntimeLane.PRODUCTION


def test_dev_supervisor_config_defaults_to_development() -> None:
    config = DevSupervisorConfig()

    assert config.runtime_lane is RuntimeLane.DEVELOPMENT
