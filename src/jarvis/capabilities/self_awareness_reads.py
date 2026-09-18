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

_INCIDENT_LIMIT = 50
_EVIDENCE_LIMIT = 50
_SIMILAR_LIMIT = 20
_MAX_EVIDENCE_WINDOW_SECONDS = 7 * 24 * 60 * 60
_SEVERITIES = {"debug", "info", "warning", "error", "critical"}


class SelfAwarenessReadValidationError(ValueError):
    pass


class SelfAwarenessReadExecutor:
    capability_key = "local:self_awareness.read"
    operations = (
        "list_components",
        "get_system_health",
        "get_component_health",
        "get_component_details",
        "query_operational_evidence",
        "list_recent_incidents",
        "list_similar_resolved_incidents",
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
                "Read-only access to the hierarchical Self Model, deterministic health, "
                "dependencies, implementation metadata, blast radius, bounded operational "
                "evidence and engineering incident/fix history."
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

        component_operations = {
            "get_component_health",
            "get_component_details",
            "query_operational_evidence",
            "list_similar_resolved_incidents",
        }
        if request.operation in component_operations:
            component_id = str(params.get("component_id") or "").strip().lower()
            if not component_id:
                raise SelfAwarenessReadValidationError("component_id is required")
            if self._awareness.self_model.component(component_id) is None:
                raise SelfAwarenessReadValidationError(
                    "unknown component_id; use list_components to select a canonical "
                    "component_id from the Self Model"
                )
            params["component_id"] = component_id
            target["component_id"] = component_id

        if request.operation in {"get_component_health", "get_component_details"}:
            params = {"component_id": params["component_id"]}
        elif request.operation == "query_operational_evidence":
            params = self._prepare_evidence_params(params)
        elif request.operation == "list_similar_resolved_incidents":
            limit = int(params.get("max_results", 5))
            if limit < 1 or limit > _SIMILAR_LIMIT:
                raise SelfAwarenessReadValidationError(
                    f"max_results must be between 1 and {_SIMILAR_LIMIT}"
                )
            params = {
                "component_id": params["component_id"],
                "max_results": limit,
            }
        elif request.operation == "list_recent_incidents":
            limit = int(params.get("max_results", 20))
            if limit < 1 or limit > _INCIDENT_LIMIT:
                raise SelfAwarenessReadValidationError(
                    f"max_results must be between 1 and {_INCIDENT_LIMIT}"
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
        elif request.operation in {"list_components", "get_system_health"}:
            params = {}

        summaries = {
            "list_components": "List canonical hierarchical JARVIS Self Model components",
            "get_system_health": "Read current JARVIS component health summary",
            "get_component_health": "Read deterministic health for one JARVIS component",
            "get_component_details": (
                "Read hierarchy, implementation and dependency metadata for one component"
            ),
            "query_operational_evidence": (
                "Read bounded structured operational evidence for one JARVIS component"
            ),
            "list_recent_incidents": "Read bounded recent JARVIS engineering incidents",
            "list_similar_resolved_incidents": (
                "Read prior resolved engineering incidents and accepted fixes for a component"
            ),
        }
        routine_health = request.operation in {
            "list_components",
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

    def _prepare_evidence_params(self, params: dict[str, Any]) -> dict[str, Any]:
        window = float(params.get("since_seconds", 15 * 60))
        if window <= 0 or window > _MAX_EVIDENCE_WINDOW_SECONDS:
            raise SelfAwarenessReadValidationError(
                "since_seconds must be positive and no more than 7 days"
            )
        limit = int(params.get("max_results", 30))
        if limit < 1 or limit > _EVIDENCE_LIMIT:
            raise SelfAwarenessReadValidationError(
                f"max_results must be between 1 and {_EVIDENCE_LIMIT}"
            )
        severity = str(params.get("severity") or "").strip().lower()
        if severity and severity not in _SEVERITIES:
            raise SelfAwarenessReadValidationError("severity is not supported")

        bounded: dict[str, Any] = {
            "component_id": params["component_id"],
            "since_seconds": window,
            "max_results": limit,
            "severity": severity,
        }
        for key, max_length in (
            ("reason_code", 180),
            ("session_id", 180),
            ("turn_id", 180),
            ("incident_id", 180),
            ("query", 300),
        ):
            value = str(params.get(key) or "").strip()
            if len(value) > max_length:
                raise SelfAwarenessReadValidationError(
                    f"{key} exceeds {max_length} characters"
                )
            bounded[key] = value
        return bounded

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        try:
            operation = prepared.request.operation
            if operation == "list_components":
                data = self._list_components()
            elif operation == "get_system_health":
                data = self._system_health()
            elif operation == "get_component_health":
                data = self._component_health(str(prepared.parameters["component_id"]))
            elif operation == "get_component_details":
                data = self._component_details(str(prepared.parameters["component_id"]))
            elif operation == "query_operational_evidence":
                data = self._operational_evidence(prepared.parameters)
            elif operation == "list_similar_resolved_incidents":
                data = self._similar_resolved_incidents(
                    component_id=str(prepared.parameters["component_id"]),
                    limit=int(prepared.parameters["max_results"]),
                )
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
                provenance=(
                    "JARVIS Self Model",
                    "JARVIS Health Registry",
                    "JARVIS Operational Evidence",
                    "JARVIS Incident Memory",
                ),
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

    def _list_components(self) -> dict[str, Any]:
        components = self._awareness.self_model.components
        return {
            "components": [
                {
                    "component_id": item.component_id,
                    "purpose": item.purpose,
                    "parent_component_id": item.parent_component_id,
                    "children": [
                        child.component_id
                        for child in self._awareness.self_model.children_of(
                            item.component_id
                        )
                    ],
                    "health_surface": item.health_surface,
                }
                for item in components
            ],
            "component_count": len(components),
            "root_components": [
                item.component_id
                for item in self._awareness.self_model.root_components
            ],
        }

    def _system_health(self) -> dict[str, Any]:
        snapshots = self._awareness.system_snapshot(health_surface_only=True)
        return {
            "components": [self._health_payload(item) for item in snapshots],
            "component_count": len(snapshots),
            "model_component_count": len(self._awareness.self_model.components),
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
            "parent_component_id": descriptor.parent_component_id,
            "children": [
                item.component_id
                for item in self._awareness.self_model.children_of(component_id)
            ],
            "ancestors": [
                item.component_id
                for item in self._awareness.self_model.ancestors_of(component_id)
            ],
            "descendants": [
                item.component_id
                for item in self._awareness.self_model.descendants_of(component_id)
            ],
            "source_paths": list(descriptor.source_paths),
            "product_capabilities": list(descriptor.product_capabilities),
            "capability_keys": list(descriptor.capability_keys),
            "code_symbols": list(descriptor.code_symbols),
            "tests": list(descriptor.tests),
            "config_keys": list(descriptor.config_keys),
            "docs": list(descriptor.docs),
            "resources": list(descriptor.resources),
            "health_probes": list(descriptor.health_probes),
            "logger_prefixes": list(descriptor.logger_prefixes),
            "dependencies": [self._dependency_payload(item) for item in dependencies],
            "dependents": [self._dependency_payload(item) for item in dependents],
            "affected_components": list(
                self._awareness.self_model.affected_components(component_id)
            ),
        }

    def _operational_evidence(self, params: dict[str, Any]) -> dict[str, Any]:
        result = self._awareness.query_operational_evidence(
            component_id=str(params["component_id"]),
            since_seconds=float(params["since_seconds"]),
            severity=str(params["severity"]),
            reason_code=str(params["reason_code"]),
            session_id=str(params["session_id"]),
            turn_id=str(params["turn_id"]),
            incident_id=str(params["incident_id"]),
            query=str(params["query"]),
            max_results=int(params["max_results"]),
        )
        return {
            "available": result.available,
            "events": list(result.events),
            "event_count": len(result.events),
            "scanned_lines": result.scanned_lines,
            "truncated": result.truncated,
            "log_files": list(result.log_files),
            "component_id": params["component_id"],
            "since_seconds": params["since_seconds"],
        }

    def _similar_resolved_incidents(
        self,
        *,
        component_id: str,
        limit: int,
    ) -> dict[str, Any]:
        if self._awareness.incidents is None:
            return {"available": False, "incidents": []}
        scope = {
            component_id,
            *(
                item.component_id
                for item in self._awareness.self_model.descendants_of(component_id)
            ),
        }
        candidates = self._awareness.incidents.list_recent(
            limit=max(100, limit * 10),
            status=IncidentStatus.RESOLVED,
        )
        incidents = tuple(
            item
            for item in candidates
            if scope.intersection(item.affected_components)
        )[:limit]
        return {
            "available": True,
            "component_id": component_id,
            "component_scope": sorted(scope),
            "incidents": [self._incident_payload(item) for item in incidents],
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
            "incidents": [self._incident_payload(item) for item in incidents],
        }

    @staticmethod
    def _incident_payload(item) -> dict[str, Any]:
        return {
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
