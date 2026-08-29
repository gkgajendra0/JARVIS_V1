from __future__ import annotations

import builtins

import pytest

from jarvis.dev_supervisor import (
    DevSupervisorConfig,
    _config_from_environment,
    _owner_approves_update,
)


@pytest.mark.parametrize("answer", ["y", "Y", "yes", "YES", "  yes  "])
def test_owner_approval_accepts_only_explicit_yes(
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    monkeypatch.setattr(builtins, "input", lambda _: answer)

    assert _owner_approves_update("a" * 40, "b" * 40) is True


@pytest.mark.parametrize("answer", ["", "n", "no", "maybe", "1", "true"])
def test_owner_approval_treats_everything_else_as_no(
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    monkeypatch.setattr(builtins, "input", lambda _: answer)

    assert _owner_approves_update("a" * 40, "b" * 40) is False


def test_supervisor_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        DevSupervisorConfig(remote=" ")
    with pytest.raises(ValueError):
        DevSupervisorConfig(branch=" ")
    with pytest.raises(ValueError):
        DevSupervisorConfig(poll_seconds=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(shutdown_timeout_seconds=0)


def test_environment_config_defaults_to_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_DEV_BRANCH", raising=False)

    assert _config_from_environment().branch == "main"


def test_environment_config_allows_explicit_development_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_DEV_BRANCH", " feature/jarvis-dev-supervisor ")

    assert _config_from_environment().branch == "feature/jarvis-dev-supervisor"
