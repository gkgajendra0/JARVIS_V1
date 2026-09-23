from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
    with pytest.raises(ValueError):
        DevSupervisorConfig(crash_restart_max_attempts=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(crash_restart_max_attempts=True)
    with pytest.raises(ValueError):
        DevSupervisorConfig(crash_restart_window_seconds=0)
    with pytest.raises(ValueError):
        DevSupervisorConfig(crash_restart_cooldown_seconds=-1)
    with pytest.raises(ValueError):
        DevSupervisorConfig(crash_restart_backoff_multiplier=0.5)


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
        self.child_stopped_calls = 0

    def child_stopped(self) -> None:
        self.child_stopped_calls += 1

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


def test_transient_voice_approval_failure_is_not_an_owner_decline() -> None:
    source = Path(supervisor.__file__).read_text(encoding="utf-8")

    assert "the update will be offered again" in source
    assert "declined_sha = None" in source


def test_dev_control_client_is_expected_to_reconnect_after_transient_failure() -> None:
    from jarvis import dev_control

    source = Path(dev_control.__file__).read_text(encoding="utf-8")

    assert "while True:" in source
    assert "await asyncio.sleep(1.0)" in source



def test_unexpected_exit_restarts_same_revision_and_persists_inconclusive(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.incidents import IncidentService, SqliteIncidentStore
    from jarvis.self_repair import RepairVerdict
    from jarvis.self_repair.supervisor import (
        SupervisorRepairController,
        build_runtime_child_exit_policy,
    )

    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    incidents = IncidentService(store)
    repair = SupervisorRepairController(
        incidents,
        policy=build_runtime_child_exit_policy(
            max_attempts=2,
            cooldown_seconds=0,
        ),
    )
    repo = FakeRepo(updated_sha="a" * 40)
    control = FakeControl([None])
    process = SimpleNamespace(returncode=9)
    monkeypatch.setattr(
        supervisor,
        "_start_jarvis",
        lambda *_: "restarted-process",
    )
    now = iter([100.0, 100.0, 101.0])

    restarted = supervisor._recover_unexpected_exit(
        repo,  # type: ignore[arg-type]
        Path("."),
        process,  # type: ignore[arg-type]
        control,  # type: ignore[arg-type]
        DevSupervisorConfig(
            crash_restart_max_attempts=2,
            crash_restart_cooldown_seconds=0,
        ),
        repair,
        sleep_fn=lambda _: None,
        now_fn=lambda: next(now),
    )

    assert restarted == "restarted-process"
    incident = incidents.list_recent(limit=1)[0]
    attempts = incidents.list_repair_attempts(incident.incident_id)
    assert len(attempts) == 1
    assert attempts[0].verdict is RepairVerdict.INCONCLUSIVE
    assert attempts[0].action.component_id == "voice_runtime"
    assert control.child_stopped_calls == 1
    store.close()


def test_readiness_failures_exhaust_restart_budget(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.incidents import IncidentService, SqliteIncidentStore
    from jarvis.self_repair import RepairVerdict
    from jarvis.self_repair.supervisor import (
        SupervisorRepairController,
        build_runtime_child_exit_policy,
    )

    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    incidents = IncidentService(store)
    repair = SupervisorRepairController(
        incidents,
        policy=build_runtime_child_exit_policy(
            max_attempts=2,
            rolling_window_seconds=300,
            cooldown_seconds=0,
        ),
    )
    repo = FakeRepo(updated_sha="a" * 40)
    control = FakeControl(
        [RuntimeError("not ready"), RuntimeError("still not ready")]
    )
    process = SimpleNamespace(returncode=9)
    started = iter(["restart-1", "restart-2"])
    stopped: list[object] = []
    monkeypatch.setattr(
        supervisor,
        "_start_jarvis",
        lambda *_: next(started),
    )
    monkeypatch.setattr(
        supervisor,
        "_stop_jarvis",
        lambda candidate, **_: stopped.append(candidate),
    )
    now = iter(
        [100.0, 100.0, 101.0, 102.0, 102.0, 103.0, 104.0]
    )

    restarted = supervisor._recover_unexpected_exit(
        repo,  # type: ignore[arg-type]
        Path("."),
        process,  # type: ignore[arg-type]
        control,  # type: ignore[arg-type]
        DevSupervisorConfig(
            crash_restart_max_attempts=2,
            crash_restart_cooldown_seconds=0,
        ),
        repair,
        sleep_fn=lambda _: None,
        now_fn=lambda: next(now),
    )

    assert restarted is None
    incident = incidents.list_recent(limit=1)[0]
    attempts = incidents.list_repair_attempts(incident.incident_id)
    assert len(attempts) == 2
    assert all(
        attempt.verdict is RepairVerdict.NOT_RECOVERED
        for attempt in attempts
    )
    assert stopped == ["restart-1", "restart-2"]
    assert any(
        evidence.kind == "repair_budget_exhausted"
        for evidence in incident.evidence
    ) is False
    refreshed = incidents.list_recent(limit=1)[0]
    assert any(
        evidence.kind == "repair_budget_exhausted"
        for evidence in refreshed.evidence
    )
    store.close()
