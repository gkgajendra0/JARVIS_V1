"""Deterministic Phase-8 lifecycle reconciliation and trusted health bridge."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from threading import Event, RLock, Thread
from typing import Callable

from jarvis.capability_registry.compatibility import (
    CapabilityCompatibilityEvaluator,
    CompatibilityVerdict,
)
from jarvis.capability_registry.models import (
    DesiredActivationState,
    PackageDisposition,
)
from jarvis.capability_registry.projection import (
    CapabilityEffectiveSnapshot,
    CapabilityManagementMode,
    CapabilityRegistryProjection,
    EffectiveCapabilityState,
    package_component_id,
)
from jarvis.capability_registry.provider import (
    CapabilityProviderRegistration,
    CapabilityProviderRegistry,
)
from jarvis.capability_registry.store import CapabilityRegistryStore
from jarvis.self_model.health import (
    HealthObservation,
    HealthRegistry,
    HealthSnapshot,
    HealthState,
)


class ReconciliationTrigger(str, Enum):
    STARTUP = "startup"
    ADMISSION = "admission"
    LIFECYCLE = "lifecycle"
    RELEASE = "release"
    HEALTH = "health"
    PERIODIC = "periodic"
    MANUAL_TEST = "manual_test"


class CapabilityHealthBridge:
    """Only trusted release-owned probes may write package health observations."""

    def __init__(
        self,
        health_registry: HealthRegistry,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = 60.0,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("health bridge ttl_seconds must be positive")
        self.health_registry = health_registry
        self.clock = clock
        self.ttl_seconds = float(ttl_seconds)

    def _record(
        self,
        *,
        component_id: str,
        source: str,
        state: HealthState,
        reason_code: str,
        summary: str,
    ) -> None:
        self.health_registry.record(
            HealthObservation.create(
                component_id=component_id,
                source=source,
                state=state,
                reason_code=reason_code,
                summary=summary,
                ttl_seconds=self.ttl_seconds,
                observed_at_epoch=self.clock(),
            )
        )

    def disabled(self, component_id: str) -> HealthSnapshot:
        self._record(
            component_id=component_id,
            source="capability_registry.lifecycle",
            state=HealthState.DISABLED,
            reason_code="desired_disabled",
            summary="Package-managed capability is durably disabled.",
        )
        return self.health_registry.snapshot(component_id, now_epoch=self.clock())

    def incompatible(
        self,
        component_id: str,
        *,
        reason_code: str,
    ) -> HealthSnapshot:
        self._record(
            component_id=component_id,
            source="capability_registry.compatibility",
            state=HealthState.DEGRADED,
            reason_code=reason_code,
            summary="Package-managed capability is not currently compatible.",
        )
        return self.health_registry.snapshot(component_id, now_epoch=self.clock())

    def observe(
        self,
        component_id: str,
        *,
        provider: CapabilityProviderRegistration,
        required_probe_ids: tuple[str, ...],
    ) -> HealthSnapshot:
        self._record(
            component_id=component_id,
            source="capability_registry.compatibility",
            state=HealthState.HEALTHY,
            reason_code="compatibility_ready",
            summary="Package compatibility evidence is READY.",
        )
        probes = {probe.probe_id.casefold(): probe for probe in provider.health_probes}
        if not required_probe_ids:
            self._record(
                component_id=component_id,
                source="capability_registry.health",
                state=HealthState.HEALTHY,
                reason_code="no_required_health_probes",
                summary="No trusted package health probes are required.",
            )
            return self.health_registry.snapshot(component_id, now_epoch=self.clock())

        for probe_id in required_probe_ids:
            probe = probes.get(probe_id.casefold())
            if probe is None:
                self._record(
                    component_id=component_id,
                    source=f"capability_probe:{probe_id}",
                    state=HealthState.FAILED,
                    reason_code="required_probe_missing",
                    summary="A required trusted health probe is unavailable.",
                )
                continue
            try:
                observation = probe.observe(component_id=component_id)
            except Exception:  # noqa: BLE001 - trusted probe failure becomes health truth
                self._record(
                    component_id=component_id,
                    source=f"capability_probe:{probe_id}",
                    state=HealthState.FAILED,
                    reason_code="trusted_probe_failed",
                    summary="A trusted capability health probe failed.",
                )
                continue
            if observation.component_id != component_id:
                self._record(
                    component_id=component_id,
                    source=f"capability_probe:{probe_id}",
                    state=HealthState.FAILED,
                    reason_code="probe_component_mismatch",
                    summary="Trusted health probe returned mismatched component identity.",
                )
                continue
            self.health_registry.record(observation)
        return self.health_registry.snapshot(component_id, now_epoch=self.clock())


class CapabilityLifecycleReconciler:
    """Authority-free durable-truth -> effective-state reconciliation."""

    def __init__(
        self,
        *,
        store: CapabilityRegistryStore,
        evaluator: CapabilityCompatibilityEvaluator,
        provider_registry: CapabilityProviderRegistry,
        health_registry: HealthRegistry,
        projection: CapabilityRegistryProjection,
        health_bridge: CapabilityHealthBridge | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if projection.provider_registry is not provider_registry:
            raise ValueError("projection and reconciler must share provider registry")
        self.store = store
        self.evaluator = evaluator
        self.provider_registry = provider_registry
        self.health_registry = health_registry
        self.projection = projection
        self.clock = clock
        self.health_bridge = health_bridge or CapabilityHealthBridge(
            health_registry,
            clock=clock,
        )
        self._lock = RLock()

    def reconcile(
        self,
        trigger: ReconciliationTrigger = ReconciliationTrigger.PERIODIC,
    ) -> CapabilityEffectiveSnapshot:
        if not isinstance(trigger, ReconciliationTrigger):
            raise TypeError("trigger must be ReconciliationTrigger")
        with self._lock:
            try:
                snapshot = self._build_snapshot(trigger)
            except Exception:
                self.projection.fail_closed("reconciliation_failed")
                raise
            self.projection.install(snapshot)
            return snapshot

    def _build_snapshot(
        self,
        trigger: ReconciliationTrigger,
    ) -> CapabilityEffectiveSnapshot:
        states: list[EffectiveCapabilityState] = []
        for registry in self.store.list_registry():
            reasons: set[str] = set()
            component_id = package_component_id(registry.capability_id)
            package = None
            report = None
            provider = None
            required_probes: tuple[str, ...] = ()
            health_state = HealthState.UNKNOWN
            capability_key: str | None = None
            disposition: PackageDisposition | None = None

            if not registry.has_selection:
                reasons.add("no_selected_package")
                if registry.desired_state is DesiredActivationState.DISABLED:
                    health_state = self.health_bridge.disabled(component_id).state
                else:
                    health_state = self.health_bridge.incompatible(
                        component_id,
                        reason_code="no_selected_package",
                    ).state
            else:
                package = self.store.get_package(
                    registry.selected_package_id or "",
                    registry.selected_package_version or "",
                )
                if package is None:
                    reasons.add("selected_package_missing")
                    health_state = self.health_bridge.incompatible(
                        component_id,
                        reason_code="selected_package_missing",
                    ).state
                else:
                    disposition = package.disposition
                    report = self.evaluator.evaluate(package)
                    try:
                        registered_manifest = self.evaluator.manifest_registry.require(
                            package.package.manifest_id,
                            package.package.manifest_version,
                        )
                    except Exception:  # noqa: BLE001 - compatibility already blocks unknown manifest
                        registered_manifest = None
                    if registered_manifest is not None:
                        required_probes = registered_manifest.manifest.health_probe_ids
                        provider = self.provider_registry.get(
                            package.package.capability_id,
                            registered_manifest.manifest.executor_id,
                            registered_manifest.manifest.adapter_id,
                        )
                    if provider is not None:
                        capability_key = provider.descriptor.key

                    if registry.desired_state is DesiredActivationState.DISABLED:
                        reasons.add("desired_disabled")
                        health_state = self.health_bridge.disabled(component_id).state
                    elif report.verdict is not CompatibilityVerdict.READY:
                        reasons.add(f"compatibility_{report.verdict.value}")
                        reasons.update(report.reason_codes)
                        health_state = self.health_bridge.incompatible(
                            component_id,
                            reason_code=f"compatibility_{report.verdict.value}",
                        ).state
                    elif provider is None:
                        reasons.add("provider_unavailable")
                        health_state = self.health_bridge.incompatible(
                            component_id,
                            reason_code="provider_unavailable",
                        ).state
                    else:
                        health_state = self.health_bridge.observe(
                            component_id,
                            provider=provider,
                            required_probe_ids=required_probes,
                        ).state
                        if health_state is not HealthState.HEALTHY:
                            reasons.add(f"health_{health_state.value}")

            fenced = self.projection.transition_fence.is_fenced(
                registry.capability_id
            )
            if fenced:
                reasons.add("transition_fenced")

            compatible = (
                report is not None
                and report.verdict is CompatibilityVerdict.READY
            )
            health_ok = (
                not required_probes or health_state is HealthState.HEALTHY
            )
            effective = bool(
                registry.desired_state is DesiredActivationState.ENABLED
                and package is not None
                and disposition is PackageDisposition.AVAILABLE
                and compatible
                and provider is not None
                and health_ok
                and not fenced
            )
            if effective:
                reasons.add("ready")

            states.append(
                EffectiveCapabilityState(
                    capability_id=registry.capability_id,
                    capability_key=capability_key,
                    component_id=component_id,
                    management_mode=CapabilityManagementMode.PACKAGE_MANAGED,
                    registry_generation=registry.generation,
                    applied_generation=registry.generation,
                    desired_state=registry.desired_state,
                    selected_package_id=registry.selected_package_id,
                    selected_package_version=registry.selected_package_version,
                    selected_package_digest=registry.selected_package_digest,
                    package_disposition=disposition,
                    compatibility_verdict=(
                        None if report is None else report.verdict
                    ),
                    compatibility_digest=(
                        None if report is None else report.digest
                    ),
                    health_state=health_state,
                    transition_fenced=fenced,
                    effective_enabled=effective,
                    reason_codes=tuple(sorted(reasons)),
                    required_health_probe_ids=required_probes,
                )
            )

        return CapabilityEffectiveSnapshot(
            release_sha=self.evaluator.package_source.release_sha,
            states=tuple(sorted(states, key=lambda item: item.capability_id)),
            reconciled_at_epoch=self.clock(),
            trigger=trigger.value,
        )


@dataclass(slots=True)
class PeriodicCapabilityReconciler:
    reconciler: CapabilityLifecycleReconciler
    interval_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not 5.0 <= self.interval_seconds <= 3600.0:
            raise ValueError("periodic reconciliation interval must be 5..3600 seconds")
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = RLock()
        self.last_run_failed = False

    def run_once(self) -> CapabilityEffectiveSnapshot:
        try:
            snapshot = self.reconciler.reconcile(ReconciliationTrigger.PERIODIC)
        except Exception:
            self.last_run_failed = True
            raise
        self.last_run_failed = False
        return snapshot

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(
                target=self._run,
                name="jarvis-capability-reconciler",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - reconciler already failed routing closed
                continue

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None
            self._stop.set()
        if thread is not None:
            thread.join(timeout=max(0.0, timeout_seconds))
