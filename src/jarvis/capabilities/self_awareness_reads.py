"""Governed read-only access to JARVIS operational self-knowledge."""

from __future__ import annotations

import time
from typing import Any

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.incidents import IncidentStatus
from jarvis.self_awareness import SelfAwarenessRuntime
from jarvis.self_model.registry import ComponentSnapshot


class SelfAwarenessReadValidationError(ValueError):
    pass


class SelfAwarenessReadExecutor:
    capability_key = "local:self_awareness.read"
    operations = (
        "get_system_health",
        "get_component_health",
        "get_component_details",
        "list_recent_incidents",
    )

    def __init__(self, awareness: SelfAwarenessRuntime) -> None:
        self._awareness = awareness

    @property
    def descriptor(self) -> CapabilityDescriptor:
        return CapabilityDescriptor.create(
            capability_id="self_awareness.read",
            source_id="local",
            kind=CapabilityKind.LOCAL_READ,
            name="JARVIS operational self-awareness",
            description=(
                "Read-only access to deterministic component health, dependencies, "
                "implementation metadata, blast radius, and engineering incidents."
            ),
            operations=list(self.operations),
            execution_enabled=True,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation not in self.operations:
            raise SelfAwarenessReadValidationError(
                "unsupported self-awareness read operation"
            )
        params = dict(request.parameters)
        target: dict[str, Any] = {"scope": "jarvis_self_awareness"}

        if request.operation in {"get_component_health", "get_component_details"}:
            component_id = str(params.get("component_id") or "").strip().lower()
            if not component_id:
                raise SelfAwarenessReadValidationError("component_id is required")
            if self._awareness.self_model.component(component_id) is None:
                raise SelfAwarenessReadValidationError("unknown component_id")
            params = {"component_id": component_id}
            target["component_id"] = component_id
        elif request.operation == "list_recent_incidents":
            limit = int(params.get("max_results", 20))
            if limit < 1 or limit > 50:
                raise SelfAwarenessReadValidationError(
                    "max_results must be between 1 and 50"
                )
            status_raw = params.get("status")
            status = None
            if status_raw not in {None, ""}:
                try:
                    status = IncidentStatus(str(status_raw).strip().lower())
                except ValueError as exc:
                    raise SelfAwarenessReadValidationError(
                        "status is not a supported incident state"
                    ) from exc
            params = {
                "max_results": limit,
                "status": status.value if status is not None else None,
            }
        else:
            params = {}

        summaries = {
            "get_system_health": "Read current JARVIS component health summary",
            "get_component_health": "Read deterministic health for one JARVIS component",
            "get_component_details": (
                "Read implementation and dependency metadata for one JARVIS component"
            ),
            "list_recent_incidents": "Read bounded recent JARVIS engineering incidents",
        }
        routine_health = request.operation in {
            "get_system_health",
            "get_component_health",
        }
        return PreparedCapability(
            request=request,
            target=target,
            parameters=params,
            material_summary=summaries[request.operation],
            attributes=(
                ActionAttributes()
                if routine_health
                else ActionAttributes(private_read=True)
            ),
            execution_payload={},
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        try:
            operation = prepared.request.operation
            if operation == "get_system_health":
                data = self._system_health()
            elif operation == "get_component_health":
                data = self._component_health(str(prepared.parameters["component_id"]))
            elif operation == "get_component_details":
                data = self._component_details(str(prepared.parameters["component_id"]))
            else:
                data = self._recent_incidents(
                    limit=int(prepared.parameters["max_results"]),
                    status_value=prepared.parameters.get("status"),
                )
            return CapabilityResult(
                status=CapabilityStatus.SUCCEEDED,
                capability_key=self.capability_key,
                operation=operation,
                data={**data, "verification_passed": True},
                elapsed_ms=(time.monotonic() - started) * 1000.0,
                provenance=("JARVIS Self Model", "JARVIS Health Registry"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            return CapabilityResult(
                status=CapabilityStatus.FAILED,
                capability_key=self.capability_key,
                operation=prepared.request.operation,
                data={},
                reason=f"self-awareness read failed: {type(exc).__name__}",
                elapsed_ms=(time.monotonic() - started) * 1000.0,
            )

    def _system_health(self) -> dict[str, Any]:
        snapshots = self._awareness.system_snapshot()
        return {
            "components": [self._health_payload(item) for item in snapshots],
            "component_count": len(snapshots),
        }

    def _component_health(self, component_id: str) -> dict[str, Any]:
        snapshot = self._awareness.component_snapshot(component_id)
        return self._health_payload(snapshot)

    def _component_details(self, component_id: str) -> dict[str, Any]:
        snapshot = self._awareness.component_snapshot(component_id)
        descriptor = snapshot.descriptor
        dependencies = self._awareness.self_model.dependencies_for(component_id)
        dependents = self._awareness.self_model.dependents_of(component_id)
        return {
            **self._health_payload(snapshot),
            "purpose": descriptor.purpose,
            "source_paths": list(descriptor.source_paths),
            "product_capabilities": list(descriptor.product_capabilities),
            "capability_keys": list(descriptor.capability_keys),
            "code_symbols": list(descriptor.code_symbols),
            "tests": list(descriptor.tests),
            "config_keys": list(descriptor.config_keys),
            "docs": list(descriptor.docs),
            "resources": list(descriptor.resources),
            "health_probes": list(descriptor.health_probes),
            "dependencies": [self._dependency_payload(item) for item in dependencies],
            "dependents": [self._dependency_payload(item) for item in dependents],
            "affected_components": list(
                self._awareness.self_model.affected_components(component_id)
            ),
        }

    def _recent_incidents(
        self,
        *,
        limit: int,
        status_value: object,
    ) -> dict[str, Any]:
        if self._awareness.incidents is None:
            return {"available": False, "incidents": []}
        status = IncidentStatus(str(status_value)) if status_value else None
        incidents = self._awareness.incidents.list_recent(limit=limit, status=status)
        return {
            "available": True,
            "incidents": [
                {
                    "incident_id": item.incident_id,
                    "title": item.title,
                    "symptom": item.symptom,
                    "severity": item.severity.value,
                    "status": item.status.value,
                    "created_at_epoch": item.created_at_epoch,
                    "updated_at_epoch": item.updated_at_epoch,
                    "affected_components": list(item.affected_components),
                    "evidence_count": len(item.evidence),
                    "root_cause": item.root_cause,
                    "accepted_fix": item.accepted_fix,
                    "regression_tests": list(item.regression_tests),
                    "commit_sha": item.commit_sha,
                    "pr_number": item.pr_number,
                    "deployment_result": item.deployment_result,
                    "rollback_status": item.rollback_status,
                    "lessons": list(item.lessons),
                }
                for item in incidents
            ],
        }

    @staticmethod
    def _health_payload(snapshot: ComponentSnapshot) -> dict[str, Any]:
        health = snapshot.health
        return {
            "component_id": snapshot.descriptor.component_id,
            "state": health.state.value,
            "evaluated_at_epoch": health.evaluated_at_epoch,
            "reason_codes": list(health.reason_codes),
            "summaries": list(health.summaries),
            "sources": list(health.sources),
            "dependency_states": [
                {"component_id": component_id, "state": state.value}
                for component_id, state in health.dependency_states
            ],
        }

    @staticmethod
    def _dependency_payload(dependency) -> dict[str, Any]:
        return {
            "source_component_id": dependency.source_component_id,
            "target_component_id": dependency.target_component_id,
            "relation": dependency.relation,
            "criticality": dependency.criticality.value,
            "fallback_component_id": dependency.fallback_component_id,
        }
