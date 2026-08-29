from __future__ import annotations

import pytest

from jarvis.dev_supervisor import DevSupervisorConfig, _config_from_environment


def test_supervisor_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        DevSupervisorConfig(remote=" ")
    with pytest.raises(ValueError):
        DevSupervisorConfig(branch=" ")
    with pytest.raises(ValueError):
        DevSupervisorConfig(poll_seconds=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(shutdown_timeout_seconds=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(approval_timeout_seconds=0)


def test_environment_config_defaults_to_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_DEV_BRANCH", raising=False)

    assert _config_from_environment().branch == "main"


def test_environment_config_allows_explicit_development_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_DEV_BRANCH", " feature/jarvis-dev-supervisor ")

    assert _config_from_environment().branch == "feature/jarvis-dev-supervisor"
