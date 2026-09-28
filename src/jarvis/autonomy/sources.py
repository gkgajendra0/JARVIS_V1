"""Read-only adapters from canonical JARVIS state into normalized SystemState facts."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from jarvis.capability_registry.projection import CapabilityRegistryProjection
from jarvis.capability_registry.store import CapabilityRegistryStore
from jarvis.engineering_change.models import ChangeState
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.incidents.store import SqliteIncidentStore
from jarvis.model_routing.registry import ModelTargetRegistry
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.promotion.release import DeploymentMetadataStore
from jarvis.self_model.health import HealthRegistry, HealthState
from jarvis.self_model.registry import SelfModelRegistry
from jarvis.work.resources import ResourceLeaseManager
from jarvis.work.store import SQLiteWorkStore

from .system_state import (
    SystemStateFactV1,
    SystemStateReadRequestV1,
    SystemStateSourceErrorV1,
    SystemStateSourceResultV1,
    SystemStateSourceStatus,
)


def _target_ids(
    request: SystemStateReadRequestV1,
    target_namespace: str,
) -> tuple[str, ...] | None:
    if not request.targets:
        return None
    identities = tuple(
        item.target_identity
        for item in request.targets
        if item.target_namespace == target_namespace
    )
    return tuple(dict.fromkeys(identities))


def _result(
    *,
    source_key: str,
    source_version: int,
    facts: Iterable[SystemStateFactV1],
    incomplete_namespaces: Iterable[str] = (),
    errors: Iterable[SystemStateSourceErrorV1] = (),
) -> SystemStateSourceResultV1:
    fact_tuple = tuple(facts)
    incomplete = tuple(sorted(set(incomplete_namespaces)))
    error_tuple = tuple(errors)
    status = (
        SystemStateSourceStatus.INCOMPLETE
        if incomplete or error_tuple
        else SystemStateSourceStatus.COMPLETE
    )
    return SystemStateSourceResultV1(
        source_adapter_key=source_key,
        source_adapter_version=source_version,
        status=status,
        facts=fact_tuple,
        incomplete_namespaces=incomplete,
        errors=error_tuple,
    )


def _target_not_found(
    *,
    namespace: str,
    source_key: str,
    source_version: int,
    target_namespace: str,
    target_identity: str,
) -> SystemStateSourceErrorV1:
    return SystemStateSourceErrorV1(
        source_namespace=namespace,
        source_adapter_key=source_key,
        source_adapter_version=source_version,
        reason_code="target_not_found",
        summary=f"{target_namespace}:{target_identity} is not present in canonical state.",
    )


def _iso_epoch(value: str) -> float:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("canonical timestamp must be timezone-aware")
    return parsed.timestamp()


def _source_error(
    *,
    namespace: str,
    source_key: str,
    source_version: int,
    reason_code: str,
    summary: str,
) -> SystemStateSourceErrorV1:
    return SystemStateSourceErrorV1(
        source_namespace=namespace,
        source_adapter_key=source_key,
        source_adapter_version=source_version,
        reason_code=reason_code,
        summary=summary,
    )


class SelfModelHealthSource:
    source_key = "self_model_health"
    source_version = 1
    namespaces = ("health_registry", "self_model")

    def __init__(
        self,
        model: SelfModelRegistry,
        health: HealthRegistry,
        *,
        max_components: int = 250,
    ) -> None:
        if not isinstance(model, SelfModelRegistry):
            raise TypeError("model must be a SelfModelRegistry")
        if not isinstance(health, HealthRegistry):
            raise TypeError("health must be a HealthRegistry")
        if max_components <= 0:
            raise ValueError("max_components must be positive")
        self.model = model
        self.health = health
        self.max_components = int(max_components)

    def _fresh_until(self, component_id: str, *, now_epoch: float) -> float:
        observations = list(self.health.observations(component_id, now_epoch=now_epoch))
        for dependency in self.model.dependencies_for(component_id):
            observations.extend(
                self.health.observations(
                    dependency.target_component_id,
                    now_epoch=now_epoch,
                )
            )
        if not observations:
            return now_epoch
        return min(item.observed_at_epoch + item.ttl_seconds for item in observations)

    def read(
        self,
        request: SystemStateReadRequestV1,
    ) -> SystemStateSourceResultV1:
        target_ids = _target_ids(request, "component")
        descriptors = (
            self.model.health_components
            if target_ids is None
            else tuple(
                descriptor
                for target_id in target_ids
                if (descriptor := self.model.component(target_id)) is not None
            )
        )
        descriptors = descriptors[: self.max_components]
        facts: list[SystemStateFactV1] = []
        errors: list[SystemStateSourceErrorV1] = []
        incomplete: set[str] = set()

        if target_ids is not None:
            known = {item.component_id for item in descriptors}
            for target_id in target_ids:
                normalized = str(target_id).strip().casefold()
                if normalized in known:
                    continue
                for namespace in request.requested_namespaces:
                    incomplete.add(namespace)
                    errors.append(
                        _target_not_found(
                            namespace=namespace,
                            source_key=self.source_key,
                            source_version=self.source_version,
                            target_namespace="component",
                            target_identity=normalized,
                        )
                    )

        for descriptor in descriptors:
            dependencies = self.model.dependencies_for(descriptor.component_id)
            descriptor_payload = {
                "component_id": descriptor.component_id,
                "parent_component_id": descriptor.parent_component_id,
                "lifecycle": descriptor.lifecycle,
                "health_surface": descriptor.health_surface,
                "dependencies": [
                    {
                        "target_component_id": item.target_component_id,
                        "relation": item.relation,
                        "criticality": item.criticality.value,
                        "fallback_component_id": item.fallback_component_id,
                    }
                    for item in dependencies
                ],
            }
            if "self_model" in request.requested_namespaces:
                facts.append(
                    SystemStateFactV1(
                        fact_namespace="self_model",
                        source_identity=f"self_model:{descriptor.component_id}",
                        source_version_or_digest=canonical_digest(descriptor_payload),
                        target_namespace="component",
                        target_identity=descriptor.component_id,
                        value_json=descriptor_payload,
                        observed_at_epoch=request.now_epoch,
                        evidence_references=(f"component:{descriptor.component_id}",),
                        source_adapter_key=self.source_key,
                        source_adapter_version=self.source_version,
                    )
                )

            if "health_registry" in request.requested_namespaces:
                snapshot = self.model.snapshot(
                    descriptor.component_id,
                    self.health,
                    now_epoch=request.now_epoch,
                )
                health_payload = {
                    "state": snapshot.state.value,
                    "reason_codes": list(snapshot.reason_codes),
                    "sources": list(snapshot.sources),
                    "dependency_states": [
                        [component_id, state.value]
                        for component_id, state in snapshot.dependency_states
                    ],
                }
                if snapshot.state is HealthState.UNKNOWN:
                    incomplete.add("health_registry")
                facts.append(
                    SystemStateFactV1(
                        fact_namespace="health_registry",
                        source_identity=f"health:{descriptor.component_id}",
                        source_version_or_digest=canonical_digest(health_payload),
                        target_namespace="component",
                        target_identity=descriptor.component_id,
                        value_json=health_payload,
                        observed_at_epoch=snapshot.evaluated_at_epoch,
                        fresh_until_epoch=self._fresh_until(
                            descriptor.component_id,
                            now_epoch=request.now_epoch,
                        ),
                        evidence_references=tuple(
                            sorted(
                                {
                                    f"health-source:{source}"
                                    for source in snapshot.sources
                                }
                            )
                        ),
                        source_adapter_key=self.source_key,
                        source_adapter_version=self.source_version,
                    )
                )

        return _result(
            source_key=self.source_key,
            source_version=self.source_version,
            facts=facts,
            incomplete_namespaces=incomplete,
            errors=errors,
        )


class WorkPortfolioSource:
    source_key = "work_portfolio"
    source_version = 1
    namespaces = ("work",)

    def __init__(
        self,
        store: SQLiteWorkStore,
        *,
        default_limit: int = 100,
    ) -> None:
        if not isinstance(store, SQLiteWorkStore):
            raise TypeError("store must be a SQLiteWorkStore")
        if default_limit <= 0:
            raise ValueError("default_limit must be positive")
        self.store = store
        self.default_limit = int(default_limit)

    def read(
        self,
        request: SystemStateReadRequestV1,
    ) -> SystemStateSourceResultV1:
        target_ids = _target_ids(request, "work")
        facts: list[SystemStateFactV1] = []
        errors: list[SystemStateSourceErrorV1] = []
        incomplete: set[str] = set()

        if target_ids is None:
            limit = min(self.default_limit, request.max_facts)
            observed = self.store.list(limit=limit + 1)
            if len(observed) > limit:
                incomplete.add("work")
                errors.append(
                    _source_error(
                        namespace="work",
                        source_key=self.source_key,
                        source_version=self.source_version,
                        reason_code="source_read_truncated",
                        summary="WorkStore read exceeded the bounded SystemState limit.",
                    )
                )
            items = observed[:limit]
        else:
            found = []
            for work_id in target_ids:
                item = self.store.get(work_id)
                if item is None:
                    incomplete.add("work")
                    errors.append(
                        _target_not_found(
                            namespace="work",
                            source_key=self.source_key,
                            source_version=self.source_version,
                            target_namespace="work",
                            target_identity=work_id,
                        )
                    )
                else:
                    found.append(item)
            items = tuple(found)

        for item in items:
            steps = self.store.list_steps(item.work_id)
            payload = {
                "state": item.state.value,
                "terminal": item.state.terminal,
                "work_type": item.work_type.value,
                "priority": int(item.priority),
                "dependencies": list(item.dependencies),
                "current_step_id": item.current_step_id,
                "version": item.version,
                "created_at_epoch": item.created_at.timestamp(),
                "updated_at_epoch": item.updated_at.timestamp(),
                "steps": [
                    {
                        "step_id": step.step_id,
                        "kind": step.kind,
                        "state": step.state.value,
                        "created_at_epoch": step.created_at.timestamp(),
                        "started_at_epoch": (
                            None
                            if step.started_at is None
                            else step.started_at.timestamp()
                        ),
                        "completed_at_epoch": (
                            None
                            if step.completed_at is None
                            else step.completed_at.timestamp()
                        ),
                    }
                    for step in steps
                ],
            }
            facts.append(
                SystemStateFactV1(
                    fact_namespace="work",
                    source_identity=f"work:{item.work_id}",
                    source_version_or_digest=f"work-v{item.version}",
                    target_namespace="work",
                    target_identity=item.work_id,
                    value_json=payload,
                    observed_at_epoch=item.updated_at.timestamp(),
                    evidence_references=(f"work:{item.work_id}",),
                    source_adapter_key=self.source_key,
                    source_adapter_version=self.source_version,
                )
            )

        return _result(
            source_key=self.source_key,
            source_version=self.source_version,
            facts=facts,
            incomplete_namespaces=incomplete,
            errors=errors,
        )


_OWNER_GATE_BY_STATE = {
    ChangeState.WAITING_OWNER_APPROVAL: "architecture",
    ChangeState.WAITING_OWNER_ACCEPTANCE: "owner_machine_acceptance",
    ChangeState.WAITING_PROMOTION_APPROVAL: "promotion",
}


class EngineeringChangeSource:
    source_key = "engineering_change"
    source_version = 1
    namespaces = ("engineering_change",)

    def __init__(
        self,
        store: ChangeStore,
        *,
        default_limit: int = 100,
    ) -> None:
        if not isinstance(store, ChangeStore):
            raise TypeError("store must be a ChangeStore")
        if default_limit <= 0:
            raise ValueError("default_limit must be positive")
        self.store = store
        self.default_limit = int(default_limit)

    def read(
        self,
        request: SystemStateReadRequestV1,
    ) -> SystemStateSourceResultV1:
        target_ids = _target_ids(request, "engineering_change")
        facts: list[SystemStateFactV1] = []
        errors: list[SystemStateSourceErrorV1] = []
        incomplete: set[str] = set()

        if target_ids is None:
            limit = min(self.default_limit, request.max_facts)
            active_ids = self.store.active_ids()
            if len(active_ids) > limit:
                incomplete.add("engineering_change")
                errors.append(
                    _source_error(
                        namespace="engineering_change",
                        source_key=self.source_key,
                        source_version=self.source_version,
                        reason_code="source_read_truncated",
                        summary=(
                            "EngineeringChange read exceeded the bounded "
                            "SystemState limit."
                        ),
                    )
                )
            ids = active_ids[:limit]
            changes = tuple(
                change
                for change_id in ids
                if (change := self.store.get(change_id)) is not None
            )
        else:
            found = []
            for change_id in target_ids:
                change = self.store.get(change_id)
                if change is None:
                    incomplete.add("engineering_change")
                    errors.append(
                        _target_not_found(
                            namespace="engineering_change",
                            source_key=self.source_key,
                            source_version=self.source_version,
                            target_namespace="engineering_change",
                            target_identity=change_id,
                        )
                    )
                else:
                    found.append(change)
            changes = tuple(found)

        for change in changes:
            stages = self.store.list_stages(change.change_id)
            try:
                updated = _iso_epoch(change.updated_at)
            except (TypeError, ValueError):
                incomplete.add("engineering_change")
                errors.append(
                    _source_error(
                        namespace="engineering_change",
                        source_key=self.source_key,
                        source_version=self.source_version,
                        reason_code="source_timestamp_invalid",
                        summary="EngineeringChange updated_at is malformed.",
                    )
                )
                continue
            payload = {
                "state": change.state.value,
                "process_key": change.process_key,
                "process_version": change.process_version,
                "version": change.version,
                "owner_gate": _OWNER_GATE_BY_STATE.get(change.state),
                "stages": [
                    {
                        "stage_key": stage.stage_key,
                        "attempt": stage.attempt,
                        "work_id": stage.work_id,
                    }
                    for stage in stages
                ],
            }
            facts.append(
                SystemStateFactV1(
                    fact_namespace="engineering_change",
                    source_identity=f"engineering-change:{change.change_id}",
                    source_version_or_digest=f"change-v{change.version}",
                    target_namespace="engineering_change",
                    target_identity=change.change_id,
                    value_json=payload,
                    observed_at_epoch=updated,
                    evidence_references=(f"change:{change.change_id}",),
                    source_adapter_key=self.source_key,
                    source_adapter_version=self.source_version,
                )
            )

        return _result(
            source_key=self.source_key,
            source_version=self.source_version,
            facts=facts,
            incomplete_namespaces=incomplete,
            errors=errors,
        )


class IncidentSource:
    source_key = "incident"
    source_version = 1
    namespaces = ("incident",)

    def __init__(
        self,
        store: SqliteIncidentStore,
        *,
        default_limit: int = 100,
    ) -> None:
        if not isinstance(store, SqliteIncidentStore):
            raise TypeError("store must be a SqliteIncidentStore")
        if default_limit <= 0:
            raise ValueError("default_limit must be positive")
        self.store = store
        self.default_limit = int(default_limit)

    def read(
        self,
        request: SystemStateReadRequestV1,
    ) -> SystemStateSourceResultV1:
        target_ids = _target_ids(request, "incident")
        facts: list[SystemStateFactV1] = []
        errors: list[SystemStateSourceErrorV1] = []
        incomplete: set[str] = set()

        if target_ids is None:
            limit = min(self.default_limit, request.max_facts)
            observed = self.store.list_recent(limit=limit + 1)
            if len(observed) > limit:
                incomplete.add("incident")
                errors.append(
                    _source_error(
                        namespace="incident",
                        source_key=self.source_key,
                        source_version=self.source_version,
                        reason_code="source_read_truncated",
                        summary="Incident read exceeded the bounded SystemState limit.",
                    )
                )
            incidents = observed[:limit]
        else:
            found = []
            for incident_id in target_ids:
                incident = self.store.get(incident_id)
                if incident is None:
                    incomplete.add("incident")
                    errors.append(
                        _target_not_found(
                            namespace="incident",
                            source_key=self.source_key,
                            source_version=self.source_version,
                            target_namespace="incident",
                            target_identity=incident_id,
                        )
                    )
                else:
                    found.append(incident)
            incidents = tuple(found)

        for incident in incidents:
            payload = {
                "status": incident.status.value,
                "severity": incident.severity.value,
                "affected_components": list(incident.affected_components),
                "evidence_count": len(incident.evidence),
                "root_cause_known": bool(incident.root_cause),
                "accepted_fix_known": bool(incident.accepted_fix),
                "commit_sha": incident.commit_sha,
                "pr_number": incident.pr_number,
                "deployment_result": incident.deployment_result,
                "rollback_status": incident.rollback_status,
            }
            facts.append(
                SystemStateFactV1(
                    fact_namespace="incident",
                    source_identity=f"incident:{incident.incident_id}",
                    source_version_or_digest=canonical_digest(payload),
                    target_namespace="incident",
                    target_identity=incident.incident_id,
                    value_json=payload,
                    observed_at_epoch=incident.updated_at_epoch,
                    evidence_references=tuple(
                        f"incident-evidence:{item.evidence_id}"
                        for item in incident.evidence
                    ),
                    source_adapter_key=self.source_key,
                    source_adapter_version=self.source_version,
                )
            )

        return _result(
            source_key=self.source_key,
            source_version=self.source_version,
            facts=facts,
            incomplete_namespaces=incomplete,
            errors=errors,
        )


class CapabilityStateSource:
    source_key = "capability_state"
    source_version = 1
    namespaces = ("capability_registry",)

    def __init__(
        self,
        store: CapabilityRegistryStore,
        projection: CapabilityRegistryProjection,
    ) -> None:
        if not isinstance(store, CapabilityRegistryStore):
            raise TypeError("store must be a CapabilityRegistryStore")
        if not isinstance(projection, CapabilityRegistryProjection):
            raise TypeError("projection must be a CapabilityRegistryProjection")
        self.store = store
        self.projection = projection

    def read(
        self,
        request: SystemStateReadRequestV1,
    ) -> SystemStateSourceResultV1:
        target_ids = _target_ids(request, "capability")
        registry_states = self.store.list_registry()
        by_id = {item.capability_id: item for item in registry_states}
        errors: list[SystemStateSourceErrorV1] = []
        incomplete: set[str] = set()
        facts: list[SystemStateFactV1] = []

        if target_ids is None:
            selected = registry_states
        else:
            found = []
            for capability_id in target_ids:
                normalized = str(capability_id).strip().casefold()
                state = by_id.get(normalized)
                if state is None:
                    incomplete.add("capability_registry")
                    errors.append(
                        _target_not_found(
                            namespace="capability_registry",
                            source_key=self.source_key,
                            source_version=self.source_version,
                            target_namespace="capability",
                            target_identity=normalized,
                        )
                    )
                else:
                    found.append(state)
            selected = tuple(found)

        effective_snapshot = self.projection.snapshot
        for state in selected:
            try:
                observed_at_epoch = _iso_epoch(state.updated_at)
            except (TypeError, ValueError):
                incomplete.add("capability_registry")
                errors.append(
                    _source_error(
                        namespace="capability_registry",
                        source_key=self.source_key,
                        source_version=self.source_version,
                        reason_code="source_timestamp_invalid",
                        summary="Capability Registry updated_at is malformed.",
                    )
                )
                continue
            effective = (
                None
                if effective_snapshot is None
                else effective_snapshot.state(state.capability_id)
            )
            if effective is None:
                incomplete.add("capability_registry")
            payload = {
                "desired_state": state.desired_state.value,
                "generation": state.generation,
                "selected_package_id": state.selected_package_id,
                "selected_package_version": state.selected_package_version,
                "selected_package_digest": state.selected_package_digest,
                "effective_known": effective is not None,
                "effective_enabled": (
                    None if effective is None else effective.effective_enabled
                ),
                "applied_generation": (
                    None if effective is None else effective.applied_generation
                ),
                "health_state": (
                    None if effective is None else effective.health_state.value
                ),
                "transition_fenced": (
                    None if effective is None else effective.transition_fenced
                ),
                "reason_codes": (
                    [] if effective is None else list(effective.reason_codes)
                ),
            }
            source_version = f"generation:{state.generation}"
            if effective_snapshot is not None:
                source_version += f":projection:{effective_snapshot.digest}"
            facts.append(
                SystemStateFactV1(
                    fact_namespace="capability_registry",
                    source_identity=f"capability:{state.capability_id}",
                    source_version_or_digest=source_version,
                    target_namespace="capability",
                    target_identity=state.capability_id,
                    value_json=payload,
                    observed_at_epoch=observed_at_epoch,
                    evidence_references=(f"capability-registry:{state.capability_id}",),
                    source_adapter_key=self.source_key,
                    source_adapter_version=self.source_version,
                )
            )

        return _result(
            source_key=self.source_key,
            source_version=self.source_version,
            facts=facts,
            incomplete_namespaces=incomplete,
            errors=errors,
        )


class ModelProviderStateSource:
    source_key = "model_provider_state"
    source_version = 1
    namespaces = ("model_routing",)

    def __init__(
        self,
        targets: ModelTargetRegistry,
        store: ModelRoutingStore,
    ) -> None:
        if not isinstance(targets, ModelTargetRegistry):
            raise TypeError("targets must be a ModelTargetRegistry")
        if not isinstance(store, ModelRoutingStore):
            raise TypeError("store must be a ModelRoutingStore")
        self.targets = targets
        self.store = store

    def read(
        self,
        request: SystemStateReadRequestV1,
    ) -> SystemStateSourceResultV1:
        target_ids = _target_ids(request, "model_target")
        all_targets = {item.target_id: item for item in self.targets.all()}
        errors: list[SystemStateSourceErrorV1] = []
        incomplete: set[str] = set()
        facts: list[SystemStateFactV1] = []

        if target_ids is None:
            selected = tuple(all_targets[key] for key in sorted(all_targets))
        else:
            found = []
            for target_id in target_ids:
                normalized = str(target_id).strip().casefold()
                target = all_targets.get(normalized)
                if target is None:
                    incomplete.add("model_routing")
                    errors.append(
                        _target_not_found(
                            namespace="model_routing",
                            source_key=self.source_key,
                            source_version=self.source_version,
                            target_namespace="model_target",
                            target_identity=normalized,
                        )
                    )
                else:
                    found.append(target)
            selected = tuple(found)

        for target in selected:
            health = self.store.get_health(target.target_id)
            payload = {
                "provider_id": target.provider_id,
                "model_id": target.model_id,
                "enabled": target.enabled,
                "benchmark_status": target.benchmark_status.value,
                "locality": target.locality.value,
                "registry_version": target.registry_version,
                "health_record_present": health is not None,
                "health_state": (
                    "unknown"
                    if health is None
                    else health.effective_state(now_epoch=request.now_epoch).value
                ),
                "consecutive_failures": (
                    0 if health is None else health.consecutive_failures
                ),
                "cooldown_until_epoch": (
                    None if health is None else health.cooldown_until_epoch
                ),
                "last_failure_kind": (
                    None if health is None else health.last_failure_kind
                ),
                "health_version": 0 if health is None else health.version,
            }
            facts.append(
                SystemStateFactV1(
                    fact_namespace="model_routing",
                    source_identity=f"model-target:{target.target_id}",
                    source_version_or_digest=(
                        f"registry:{target.registry_version}:health:"
                        f"{0 if health is None else health.version}"
                    ),
                    target_namespace="model_target",
                    target_identity=target.target_id,
                    value_json=payload,
                    observed_at_epoch=(
                        request.now_epoch if health is None else health.updated_at_epoch
                    ),
                    evidence_references=(f"model-target:{target.target_id}",),
                    source_adapter_key=self.source_key,
                    source_adapter_version=self.source_version,
                )
            )

        return _result(
            source_key=self.source_key,
            source_version=self.source_version,
            facts=facts,
            incomplete_namespaces=incomplete,
            errors=errors,
        )


class ResourceStateSource:
    source_key = "resource_state"
    source_version = 1
    namespaces = ("resource",)

    def __init__(
        self,
        resources: ResourceLeaseManager,
        *,
        freshness_seconds: float = 5.0,
    ) -> None:
        if not isinstance(resources, ResourceLeaseManager):
            raise TypeError("resources must be a ResourceLeaseManager")
        if freshness_seconds <= 0:
            raise ValueError("freshness_seconds must be positive")
        self.resources = resources
        self.freshness_seconds = float(freshness_seconds)

    def read(
        self,
        request: SystemStateReadRequestV1,
    ) -> SystemStateSourceResultV1:
        target_ids = _target_ids(request, "resource")
        snapshots = {item.key: item for item in self.resources.snapshot()}
        errors: list[SystemStateSourceErrorV1] = []
        incomplete: set[str] = set()

        if target_ids is None:
            selected = tuple(snapshots[key] for key in sorted(snapshots))
        else:
            found = []
            for resource_id in target_ids:
                normalized = str(resource_id).strip().casefold()
                item = snapshots.get(normalized)
                if item is None:
                    incomplete.add("resource")
                    errors.append(
                        _target_not_found(
                            namespace="resource",
                            source_key=self.source_key,
                            source_version=self.source_version,
                            target_namespace="resource",
                            target_identity=normalized,
                        )
                    )
                else:
                    found.append(item)
            selected = tuple(found)

        facts = tuple(
            SystemStateFactV1(
                fact_namespace="resource",
                source_identity=f"resource:{item.key}",
                source_version_or_digest=(
                    f"capacity:{item.capacity}:available:{item.available}"
                ),
                target_namespace="resource",
                target_identity=item.key,
                value_json={
                    "capacity": item.capacity,
                    "available": item.available,
                    "in_use": item.capacity - item.available,
                },
                observed_at_epoch=request.now_epoch,
                fresh_until_epoch=request.now_epoch + self.freshness_seconds,
                evidence_references=(f"resource:{item.key}",),
                source_adapter_key=self.source_key,
                source_adapter_version=self.source_version,
            )
            for item in selected
        )
        return _result(
            source_key=self.source_key,
            source_version=self.source_version,
            facts=facts,
            incomplete_namespaces=incomplete,
            errors=errors,
        )


class ProductionObservationSource:
    source_key = "production_observation"
    source_version = 1
    namespaces = ("production",)

    def __init__(self, deployment: DeploymentMetadataStore) -> None:
        if not isinstance(deployment, DeploymentMetadataStore):
            raise TypeError("deployment must be a DeploymentMetadataStore")
        self.deployment = deployment

    def read(
        self,
        request: SystemStateReadRequestV1,
    ) -> SystemStateSourceResultV1:
        target_ids = _target_ids(request, "production_release")
        requested = (
            ("active", "lkg", "recovery")
            if target_ids is None
            else tuple(str(item).strip().casefold() for item in target_ids)
        )
        facts: list[SystemStateFactV1] = []
        errors: list[SystemStateSourceErrorV1] = []
        incomplete: set[str] = set()

        for identity in requested:
            if identity == "active":
                release = self.deployment.active()
                if release is None:
                    incomplete.add("production")
                    continue
                payload = {
                    "kind": "active",
                    "release_sha": release.release_sha,
                    "promotion_attempt_id": release.promotion_attempt_id,
                    "promotion_evidence_digest": release.promotion_evidence_digest,
                    "config_digest": release.config_digest,
                    "schema_versions": [
                        [name, version] for name, version in release.schema_versions
                    ],
                    "accepted_at_epoch": release.accepted_at_epoch,
                }
                version = release.release_sha
                observed = request.now_epoch
            elif identity == "lkg":
                release = self.deployment.lkg()
                if release is None:
                    if target_ids is not None:
                        incomplete.add("production")
                    continue
                payload = {
                    "kind": "lkg",
                    "release_sha": release.release_sha,
                    "promotion_attempt_id": release.promotion_attempt_id,
                    "promotion_evidence_digest": release.promotion_evidence_digest,
                    "config_digest": release.config_digest,
                    "schema_versions": [
                        [name, version] for name, version in release.schema_versions
                    ],
                    "accepted_at_epoch": release.accepted_at_epoch,
                }
                version = release.release_sha
                observed = request.now_epoch
            elif identity == "recovery":
                recovery = self.deployment.recovery()
                if recovery is None:
                    if target_ids is not None:
                        incomplete.add("production")
                    continue
                payload = {
                    "kind": "recovery",
                    "deployment_id": recovery.deployment_id,
                    "attempt_id": recovery.attempt_id,
                    "phase": recovery.phase.value,
                    "candidate_release_sha": recovery.candidate.release_sha,
                    "lkg_release_sha": recovery.lkg.release_sha,
                }
                version = canonical_digest(payload)
                observed = request.now_epoch
            else:
                incomplete.add("production")
                errors.append(
                    _target_not_found(
                        namespace="production",
                        source_key=self.source_key,
                        source_version=self.source_version,
                        target_namespace="production_release",
                        target_identity=identity,
                    )
                )
                continue

            facts.append(
                SystemStateFactV1(
                    fact_namespace="production",
                    source_identity=f"production:{identity}",
                    source_version_or_digest=version,
                    target_namespace="production_release",
                    target_identity=identity,
                    value_json=payload,
                    observed_at_epoch=observed,
                    evidence_references=(f"deployment-metadata:{identity}",),
                    source_adapter_key=self.source_key,
                    source_adapter_version=self.source_version,
                )
            )

        return _result(
            source_key=self.source_key,
            source_version=self.source_version,
            facts=facts,
            incomplete_namespaces=incomplete,
            errors=errors,
        )
