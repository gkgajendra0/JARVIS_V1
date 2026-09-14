from __future__ import annotations

import json

from jarvis.incidents import IncidentService, IncidentStatus, SqliteIncidentStore
from jarvis.observability.context import (
    CorrelationContext,
    current_correlation,
    reset_correlation,
    set_correlation,
)
from jarvis.observability.events import OperationalEvent
from jarvis.observability.redaction import redact_data
from jarvis.self_model import (
    ComponentDescriptor,
    DependencyCriticality,
    DependencyDescriptor,
    HealthObservation,
    HealthRegistry,
    HealthSnapshot,
    HealthState,
    SelfModelRegistry,
)


def _registry() -> SelfModelRegistry:
    return SelfModelRegistry(
        components=(
            ComponentDescriptor("a", "A", ("a.py",)),
            ComponentDescriptor("b", "B", ("b.py",)),
            ComponentDescriptor("c", "C", ("c.py",)),
        ),
        dependencies=(
            DependencyDescriptor(
                "a",
                "b",
                criticality=DependencyCriticality.BLOCKING,
            ),
            DependencyDescriptor(
                "c",
                "a",
                criticality=DependencyCriticality.DEGRADING,
            ),
        ),
    )


def test_health_registry_expires_stale_evidence() -> None:
    health = HealthRegistry()
    health.record(
        HealthObservation.create(
            component_id="a",
            source="probe",
            state=HealthState.HEALTHY,
            reason_code="ok",
            summary="healthy",
            ttl_seconds=5,
            observed_at_epoch=100,
        )
    )
    assert health.snapshot("a", now_epoch=104).state is HealthState.HEALTHY
    assert health.snapshot("a", now_epoch=106).state is HealthState.UNKNOWN


def test_dependency_rollup_and_blast_radius_are_deterministic() -> None:
    model = _registry()
    health = HealthRegistry()
    health.record(
        HealthObservation.create(
            component_id="a",
            source="probe",
            state=HealthState.HEALTHY,
            reason_code="ok",
            summary="a ok",
            ttl_seconds=30,
            observed_at_epoch=100,
        )
    )
    health.record(
        HealthObservation.create(
            component_id="b",
            source="probe",
            state=HealthState.FAILED,
            reason_code="boom",
            summary="b failed",
            ttl_seconds=30,
            observed_at_epoch=100,
        )
    )
    snapshot = model.snapshot("a", health, now_epoch=101)
    assert snapshot.health.state is HealthState.FAILED
    assert "dependency_b_failed" in snapshot.health.reason_codes
    assert model.affected_components("b") == ("a", "c")


def test_correlation_context_is_explicitly_restored() -> None:
    assert current_correlation().session_id is None
    token = set_correlation(
        CorrelationContext(session_id="s1", component_id="hands")
    )
    try:
        assert current_correlation().session_id == "s1"
        assert current_correlation().component_id == "hands"
    finally:
        reset_correlation(token)
    assert current_correlation().session_id is None


def test_redaction_blocks_sensitive_keys_and_token_shapes() -> None:
    payload = redact_data(
        {
            "api_key": "sk-secret-value-that-should-never-land",
            "nested": {"authorization": "Bearer abcdefghijklmnop"},
            "message": "request used sk-abcdefghijklmnop and failed",
            "safe": "visible",
        }
    )
    assert payload["api_key"] == "[REDACTED]"
    assert payload["nested"]["authorization"] == "[REDACTED]"
    assert "sk-abcdefghijklmnop" not in payload["message"]
    assert payload["safe"] == "visible"


def test_operational_event_carries_context_and_redacts_attributes() -> None:
    token = set_correlation(
        CorrelationContext(session_id="s1", component_id="hands")
    )
    try:
        event = OperationalEvent.create(
            event_name="capability.failed",
            component_id="hands",
            reason_code="timeout",
            result_state="failed",
            attributes={"password": "secret", "operation": "focus_window"},
            occurred_at_epoch=10,
        )
    finally:
        reset_correlation(token)
    correlation = json.loads(event.correlation_json)
    attributes = json.loads(event.attributes_json)
    assert correlation["session_id"] == "s1"
    assert attributes["password"] == "[REDACTED]"
    assert attributes["operation"] == "focus_window"


def test_incident_groups_health_failure_and_persists_resolution(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    service = IncidentService(store, grouping_window_seconds=60)
    health = HealthRegistry()
    before = health.snapshot("hands", now_epoch=100)
    health.record(
        HealthObservation.create(
            component_id="hands",
            source="postcondition",
            state=HealthState.FAILED,
            reason_code="postcondition_failed",
            summary="window state did not match expected result",
            ttl_seconds=30,
            observed_at_epoch=101,
        )
    )
    failed = health.snapshot("hands", now_epoch=101)
    incident = service.record_health_transition(before, failed)
    assert incident is not None
    degraded = HealthSnapshot(
        component_id="hands",
        state=HealthState.DEGRADED,
        evaluated_at_epoch=102,
        reason_codes=("fallback_available",),
        summaries=("visual fallback remains available",),
        sources=("postcondition",),
    )
    repeated = service.record_health_transition(failed, degraded)
    assert repeated is not None
    assert repeated.incident_id == incident.incident_id
    resolved = service.resolve(
        incident.incident_id,
        root_cause="UI Automation regression",
        accepted_fix="restore supported selector path",
        regression_tests=("tests/test_windows_structured_control.py",),
        commit_sha="abc123",
        pr_number=99,
        now_epoch=103,
    )
    assert resolved.status is IncidentStatus.RESOLVED
    loaded = store.get(incident.incident_id)
    assert loaded is not None
    assert loaded.root_cause == "UI Automation regression"
    assert len(loaded.evidence) == 2
    assert service.similar_resolved("hands") == (loaded,)
    store.close()
