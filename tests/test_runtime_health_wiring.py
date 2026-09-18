from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.local_reads import ApprovedRootPolicy, LocalProjectReadExecutor
from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.health_adapters import (
    CapabilityExecutionHealthObserver,
    record_foundation_health,
    require_startup_preflight_with_health,
)
from jarvis.preflight import PreflightCheck, StartupPreflightError
from jarvis.self_awareness import SelfAwarenessRuntime
from jarvis.self_model.health import HealthState


class FakeAuthority:
    def authorize(self, prepared):
        del prepared
        return object()

    def consume(self, authorized) -> None:
        del authorized

    def audit_result(self, *, session_id, authorized, result) -> None:
        del session_id, authorized, result

    def close(self) -> None:
        pass


class BrokenAwareness:
    incident_persistence_available = True

    def observe(self, **kwargs) -> None:
        del kwargs
        raise RuntimeError("diagnostics unavailable")


def test_capability_runtime_notifies_result_observer(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")
    executor = LocalProjectReadExecutor(ApprovedRootPolicy(project_root=tmp_path))
    observed: list[CapabilityResult] = []
    runtime = CapabilityRuntime(
        executors=(executor,),
        resolver=CapabilityResolver((), builtins=(executor.descriptor,)),
        authority=FakeAuthority(),
        result_observer=observed.append,
    )

    result = runtime.execute_operation(
        session_id="session-1",
        operation="read_file",
        parameters={"root": "project", "path": "note.txt"},
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert observed == [result]


def test_capability_health_observer_ignores_policy_outcomes(tmp_path: Path) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    observer = CapabilityExecutionHealthObserver(awareness)
    observer(
        CapabilityResult(
            status=CapabilityStatus.DENIED,
            capability_key="windows:desktop.control",
            operation="click",
            data={},
            reason="owner approval required",
        )
    )

    snapshot = awareness.component_snapshot("capability_runtime")
    assert snapshot.health.state is HealthState.UNKNOWN
    assert snapshot.health.dependency_states == (("authority", HealthState.UNKNOWN),)
    awareness.close()


def test_capability_health_observer_tracks_success_then_failure(tmp_path: Path) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    observer = CapabilityExecutionHealthObserver(awareness)
    observer(
        CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key="windows:desktop.control",
            operation="focus_window",
            data={},
            elapsed_ms=12.5,
        )
    )
    assert (
        awareness.component_snapshot("capability_runtime").health.state
        is HealthState.HEALTHY
    )

    observer(
        CapabilityResult(
            status=CapabilityStatus.FAILED,
            capability_key="windows:desktop.control",
            operation="focus_window",
            data={},
            reason="postcondition failed",
            elapsed_ms=25.0,
        )
    )
    assert (
        awareness.component_snapshot("capability_runtime").health.state
        is HealthState.DEGRADED
    )
    awareness.close()


def test_foundation_health_reports_incident_store(tmp_path: Path) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    record_foundation_health(awareness)

    assert (
        awareness.component_snapshot("observability").health.state
        is HealthState.HEALTHY
    )
    assert awareness.component_snapshot("incidents").health.state is HealthState.HEALTHY
    awareness.close()


def test_health_adapters_fail_open_when_diagnostics_break() -> None:
    broken = BrokenAwareness()
    record_foundation_health(broken)  # type: ignore[arg-type]
    CapabilityExecutionHealthObserver(broken)(  # type: ignore[arg-type]
        CapabilityResult(
            status=CapabilityStatus.FAILED,
            capability_key="browser:playwright",
            operation="navigate",
            data={},
        )
    )


def test_preflight_health_is_recorded_before_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    checks = [
        PreflightCheck("Conversation microphone", True, "available"),
        PreflightCheck("Cloud AI provider", False, "unavailable"),
    ]
    monkeypatch.setattr(
        "jarvis.health_adapters.run_startup_preflight", lambda config: checks
    )
    monkeypatch.setattr("jarvis.health_adapters.print_preflight", lambda checks: None)

    with pytest.raises(StartupPreflightError):
        require_startup_preflight_with_health(object(), awareness)  # type: ignore[arg-type]

    voice = awareness.component_snapshot("runtime.voice")
    assert voice.health.state is HealthState.FAILED
    assert "startup_check_passed" in voice.health.reason_codes
    assert "preflight:conversation_microphone" in voice.health.sources
    assert (
        awareness.component_snapshot("runtime.provider").health.state
        is HealthState.FAILED
    )
    awareness.close()
