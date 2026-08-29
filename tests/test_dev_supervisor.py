from __future__ import annotations

import builtins

import pytest

from jarvis.dev_supervisor import DevSupervisorConfig, _owner_approves_update


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


def test_supervisor_config_rejects_non_positive_timing() -> None:
    with pytest.raises(ValueError):
        DevSupervisorConfig(poll_seconds=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(shutdown_timeout_seconds=0)
