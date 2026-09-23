from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import jarvis.dev_supervisor as supervisor
from jarvis.dev_supervisor import DevSupervisorConfig
from jarvis.incidents import IncidentService, SqliteIncidentStore
from jarvis.self_model import HealthState
from jarvis.self_repair import RepairTrigger
from jarvis.self_repair.supervisor import (
    SupervisorRepairController,
    build_runtime_child_exit_policy,
)


class RevisionChangingRepo:
    def __init__(self) -> None:
        self._shas = iter(("a" * 40, "b" * 40))

    def local_sha(self) -> str:
        return next(self._shas)


class MinimalControl:
    def __init__(self) -> None:
        self.child_stopped_calls = 0

    def child_stopped(self) -> None:
        self.child_stopped_calls += 1


def test_phase5_revision_change_aborts_before_any_restart_attempt(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    incidents = IncidentService(store)
    repair = SupervisorRepairController(
        incidents,
        policy=build_runtime_child_exit_policy(
            max_attempts=1,
            cooldown_seconds=0,
        ),
    )
    repo = RevisionChangingRepo()
    control = MinimalControl()
    process = SimpleNamespace(returncode=17)

    monkeypatch.setattr(
        supervisor,
        "_start_jarvis",
        lambda *_: pytest.fail("changed revision must not restart"),
    )

    restarted = supervisor._recover_unexpected_exit(
        repo,  # type: ignore[arg-type]
        Path("."),
        process,  # type: ignore[arg-type]
        control,  # type: ignore[arg-type]
        DevSupervisorConfig(
            crash_restart_max_attempts=1,
            crash_restart_cooldown_seconds=0,
        ),
        repair,
        sleep_fn=lambda _: None,
        now_fn=lambda: 100.0,
    )

    assert restarted is None
    incident = incidents.list_recent(limit=1)[0]
    assert incidents.list_repair_attempts(incident.incident_id) == ()
    assert control.child_stopped_calls == 1
    store.close()


def test_phase5_provider_quota_has_no_registered_runtime_restart(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    controller = SupervisorRepairController(IncidentService(store))
    trigger = RepairTrigger.create(
        component_id="voice_runtime",
        reason_code="provider_quota_exhausted",
        source="dev_supervisor",
        health_state=HealthState.DEGRADED,
        observed_at_epoch=100.0,
    )

    assert controller.registry.match(trigger) is None
    assert controller.registry.action_for(trigger, now_epoch=100.0) is None
    store.close()


def test_phase5_incident_persistence_failure_disables_automatic_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_store(path):
        raise sqlite3.OperationalError("fault injected")

    monkeypatch.setattr(supervisor, "SqliteIncidentStore", unavailable_store)

    repair, store = supervisor._build_supervisor_repair_controller(
        DevSupervisorConfig()
    )

    assert repair is None
    assert store is None
