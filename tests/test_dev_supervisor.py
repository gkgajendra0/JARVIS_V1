from __future__ import annotations

from pathlib import Path

import pytest

import jarvis.dev_supervisor as supervisor
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
    with pytest.raises(ValueError):
        DevSupervisorConfig(startup_timeout_seconds=0)


def test_environment_config_defaults_to_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_DEV_BRANCH", raising=False)

    assert _config_from_environment().branch == "main"


def test_environment_config_allows_explicit_development_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_DEV_BRANCH", " feature/jarvis-dev-supervisor ")

    assert _config_from_environment().branch == "feature/jarvis-dev-supervisor"


class FakeRepo:
    def __init__(self, *, updated_sha: str = "b" * 40) -> None:
        self.updated_sha = updated_sha
        self.pull_count = 0
        self.reset_to: str | None = None

    def pull_fast_forward(self) -> None:
        self.pull_count += 1

    def local_sha(self) -> str:
        return self.updated_sha

    def reset_hard(self, sha: str) -> None:
        self.reset_to = sha


class FakeControl:
    def __init__(self, readiness_outcomes: list[Exception | None]) -> None:
        self.readiness_outcomes = list(readiness_outcomes)
        self.readiness_calls = 0

    def wait_for_child_ready(self, *, timeout_seconds: float) -> None:
        assert timeout_seconds > 0
        self.readiness_calls += 1
        outcome = self.readiness_outcomes.pop(0)
        if outcome is not None:
            raise outcome


def test_approved_update_keeps_new_revision_after_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakeRepo()
    control = FakeControl([None])
    stopped: list[object] = []
    started = iter(["new-process"])
    monkeypatch.setattr(
        supervisor,
        "_stop_jarvis",
        lambda process, **_: stopped.append(process),
    )
    monkeypatch.setattr(
        supervisor,
        "_start_jarvis",
        lambda *_: next(started),
    )

    process, healthy = supervisor._apply_approved_update(
        repo,  # type: ignore[arg-type]
        Path("."),
        "old-process",  # type: ignore[arg-type]
        control,  # type: ignore[arg-type]
        DevSupervisorConfig(),
        previous_sha="a" * 40,
        remote_sha="b" * 40,
    )

    assert healthy is True
    assert process == "new-process"
    assert stopped == ["old-process"]
    assert repo.pull_count == 1
    assert repo.reset_to is None
    assert control.readiness_calls == 1


def test_approved_update_rolls_back_when_new_revision_never_becomes_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_sha = "a" * 40
    repo = FakeRepo()
    control = FakeControl([RuntimeError("new child failed"), None])
    stopped: list[object] = []
    started = iter(["new-process", "rollback-process"])
    monkeypatch.setattr(
        supervisor,
        "_stop_jarvis",
        lambda process, **_: stopped.append(process),
    )
    monkeypatch.setattr(
        supervisor,
        "_start_jarvis",
        lambda *_: next(started),
    )

    process, healthy = supervisor._apply_approved_update(
        repo,  # type: ignore[arg-type]
        Path("."),
        "old-process",  # type: ignore[arg-type]
        control,  # type: ignore[arg-type]
        DevSupervisorConfig(),
        previous_sha=previous_sha,
        remote_sha="b" * 40,
    )

    assert healthy is False
    assert process == "rollback-process"
    assert stopped == ["old-process", "new-process"]
    assert repo.pull_count == 1
    assert repo.reset_to == previous_sha
    assert control.readiness_calls == 2
