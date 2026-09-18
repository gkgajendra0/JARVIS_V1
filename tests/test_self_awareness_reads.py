from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.models import CapabilityRequest, CapabilityStatus
from jarvis.capabilities.self_awareness_reads import (
    SelfAwarenessReadExecutor,
    SelfAwarenessReadValidationError,
)
from jarvis.self_awareness import SelfAwarenessRuntime
from jarvis.self_model.health import HealthState


def _request(operation: str, parameters: dict | None = None) -> CapabilityRequest:
    return CapabilityRequest(
        session_id="session-1",
        capability_key="local:self_awareness.read",
        operation=operation,
        parameters=parameters or {},
    )


def test_routine_health_is_low_risk_but_engineering_details_are_private(
    tmp_path: Path,
) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    executor = SelfAwarenessReadExecutor(awareness)

    routine = executor.prepare(_request("get_system_health"))
    component = executor.prepare(
        _request("get_component_health", {"component_id": "runtime.provider"})
    )
    details = executor.prepare(
        _request("get_component_details", {"component_id": "runtime.provider"})
    )
    incidents = executor.prepare(_request("list_recent_incidents", {"max_results": 5}))
    evidence = executor.prepare(
        _request(
            "query_operational_evidence",
            {"component_id": "runtime.provider", "max_results": 5},
        )
    )
    prior_fixes = executor.prepare(
        _request(
            "list_similar_resolved_incidents",
            {"component_id": "runtime.provider", "max_results": 5},
        )
    )

    assert routine.attributes == ActionAttributes()
    assert component.attributes == ActionAttributes()
    assert details.attributes == ActionAttributes(private_read=True)
    assert incidents.attributes == ActionAttributes(private_read=True)
    assert evidence.attributes == ActionAttributes(private_read=True)
    assert prior_fixes.attributes == ActionAttributes(private_read=True)
    assert routine.execution_payload == {}
    assert details.execution_payload == {}
    awareness.close()


def test_system_and_component_queries_use_deterministic_health(tmp_path: Path) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    awareness.observe(
        component_id="runtime.provider",
        source="test_probe",
        state=HealthState.FAILED,
        reason_code="provider_unavailable",
        summary="Provider is unavailable",
        ttl_seconds=60.0,
    )
    executor = SelfAwarenessReadExecutor(awareness)

    system = executor.execute(executor.prepare(_request("get_system_health")))
    component = executor.execute(
        executor.prepare(
            _request("get_component_health", {"component_id": "runtime.provider"})
        )
    )

    assert system.status is CapabilityStatus.SUCCEEDED
    assert system.data["component_count"] >= 1
    states = {item["component_id"]: item["state"] for item in system.data["components"]}
    assert states["runtime.provider"] == "failed"
    assert component.data["state"] == "failed"
    assert component.data["reason_codes"] == ["provider_unavailable"]
    awareness.close()


def test_component_details_include_code_dependencies_and_blast_radius(
    tmp_path: Path,
) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    executor = SelfAwarenessReadExecutor(awareness)

    result = executor.execute(
        executor.prepare(
            _request("get_component_details", {"component_id": "runtime.provider"})
        )
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert "src/jarvis/ai_provider.py" in result.data["source_paths"]
    assert "runtime.voice" in result.data["affected_components"]
    assert result.data["verification_passed"] is True
    awareness.close()


def test_recent_incidents_are_available_through_governed_read(tmp_path: Path) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    awareness.observe(
        component_id="capability_runtime",
        source="test_execution",
        state=HealthState.DEGRADED,
        reason_code="capability_failed",
        summary="Capability execution failed",
        ttl_seconds=60.0,
    )
    executor = SelfAwarenessReadExecutor(awareness)

    result = executor.execute(
        executor.prepare(_request("list_recent_incidents", {"max_results": 5}))
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["available"] is True
    assert len(result.data["incidents"]) == 1
    assert result.data["incidents"][0]["affected_components"] == ["capability_runtime"]
    awareness.close()


def test_unknown_component_is_rejected_before_execution(tmp_path: Path) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    executor = SelfAwarenessReadExecutor(awareness)

    with pytest.raises(SelfAwarenessReadValidationError, match="unknown component_id"):
        executor.prepare(
            _request("get_component_details", {"component_id": "missing.component"})
        )
    awareness.close()


def test_list_components_exposes_canonical_ids_and_purposes(tmp_path: Path) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    executor = SelfAwarenessReadExecutor(awareness)

    result = executor.execute(executor.prepare(_request("list_components")))

    assert result.status is CapabilityStatus.SUCCEEDED
    components = {
        item["component_id"]: item["purpose"] for item in result.data["components"]
    }
    assert components["runtime.provider"] == (
        "Cloud AI provider boundary and provider resilience."
    )
    assert components["vision.pocket3"] == (
        "Pocket 3 native tracking transport and evidence."
    )
    awareness.close()


def test_unknown_component_guides_canonical_component_discovery(tmp_path: Path) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    executor = SelfAwarenessReadExecutor(awareness)

    with pytest.raises(
        SelfAwarenessReadValidationError,
        match="use list_components",
    ):
        executor.prepare(
            _request("get_component_details", {"component_id": "provider"})
        )
    awareness.close()


def test_component_details_expose_hierarchy_and_logger_ownership(
    tmp_path: Path,
) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    executor = SelfAwarenessReadExecutor(awareness)

    result = executor.execute(
        executor.prepare(
            _request("get_component_details", {"component_id": "voice.wake"})
        )
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["parent_component_id"] == "runtime.voice"
    assert "runtime.voice" in result.data["ancestors"]
    assert "jarvis.voice.wakeword" in result.data["logger_prefixes"]
    awareness.close()


def test_similar_resolved_incidents_return_confirmed_fix_history(
    tmp_path: Path,
) -> None:
    awareness = SelfAwarenessRuntime(incident_store_path=tmp_path / "incidents.sqlite3")
    assert awareness.incidents is not None
    incident = awareness.incidents.create_manual(
        symptom="provider session stopped",
        affected_components=("runtime.provider",),
    )
    awareness.incidents.resolve(
        incident.incident_id,
        root_cause="provider quota exhausted",
        accepted_fix="switch project quota before restarting session",
        regression_tests=("tests/test_provider_resilience.py",),
        commit_sha="abc123",
        pr_number=77,
    )
    executor = SelfAwarenessReadExecutor(awareness)

    result = executor.execute(
        executor.prepare(
            _request(
                "list_similar_resolved_incidents",
                {"component_id": "runtime.provider", "max_results": 5},
            )
        )
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["incidents"][0]["root_cause"] == "provider quota exhausted"
    assert result.data["incidents"][0]["accepted_fix"].startswith("switch project")
    awareness.close()
