"""Adapters that convert accepted runtime outcomes into health evidence."""

from __future__ import annotations

from typing import Any

from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.config import JarvisConfig
from jarvis.observability.redaction import redact_data
from jarvis.preflight import StartupPreflightError, print_preflight, run_startup_preflight
from jarvis.provider_resilience import ProviderHealth, ProviderResilienceState
from jarvis.self_awareness import SelfAwarenessRuntime
from jarvis.self_model.health import HealthState


def _preflight_component(label: str) -> str:
    normalized = str(label).casefold()
    if "cloud ai" in normalized:
        return "runtime.provider"
    if any(item in normalized for item in ("authority", "hello", "opa")):
        return "authority"
    if any(item in normalized for item in ("lr-asd", "active-speaker")):
        return "vision.base"
    return "runtime.voice"


def _observe_safely(
    awareness: SelfAwarenessRuntime,
    **kwargs: Any,
) -> None:
    try:
        awareness.observe(**kwargs)
    except Exception:  # noqa: BLE001,S110 - diagnostics must never block runtime
        pass


def record_foundation_health(awareness: SelfAwarenessRuntime) -> None:
    """Publish the state of the new evidence and incident foundation itself."""

    _observe_safely(
        awareness,
        component_id="observability",
        source="startup",
        state=HealthState.HEALTHY,
        reason_code="evidence_runtime_available",
        summary="Operational evidence runtime is available",
        ttl_seconds=300.0,
    )
    incident_state = (
        HealthState.HEALTHY
        if awareness.incident_persistence_available
        else HealthState.DEGRADED
    )
    _observe_safely(
        awareness,
        component_id="incidents",
        source="startup",
        state=incident_state,
        reason_code=(
            "incident_store_available"
            if awareness.incident_persistence_available
            else "incident_store_unavailable"
        ),
        summary=(
            "Engineering incident persistence is available"
            if awareness.incident_persistence_available
            else "Engineering incident persistence is unavailable"
        ),
        ttl_seconds=300.0,
    )


def require_startup_preflight_with_health(
    config: JarvisConfig,
    awareness: SelfAwarenessRuntime,
) -> None:
    """Run canonical preflight once and mirror its outcomes into health evidence."""

    checks = run_startup_preflight(config)
    print_preflight(checks)
    for check in checks:
        _observe_safely(
            awareness,
            component_id=_preflight_component(check.label),
            source=f"preflight:{check.label.casefold().replace(' ', '_')}",
            state=HealthState.HEALTHY if check.ok else HealthState.FAILED,
            reason_code=("startup_check_passed" if check.ok else "startup_check_failed"),
            summary=f"{check.label}: {'passed' if check.ok else 'failed'}",
            ttl_seconds=300.0,
            metadata=redact_data({"detail": check.detail}),
        )

    failures = [check for check in checks if not check.ok]
    if failures:
        raise StartupPreflightError(
            f"JARVIS startup blocked by {len(failures)} preflight failure(s). "
            "Run jarvis-setup after fixing the reported item(s)."
        )
    print("Preflight passed. Starting JARVIS...\n")


def record_capability_catalog_health(
    awareness: SelfAwarenessRuntime,
    catalog: CapabilityCatalog,
) -> None:
    _observe_safely(
        awareness,
        component_id="capability_runtime",
        source="capability_catalog",
        state=HealthState.HEALTHY,
        reason_code="capability_catalog_refreshed",
        summary="Capability catalog refreshed successfully",
        ttl_seconds=300.0,
        metadata={"capability_count": len(catalog.capabilities)},
    )


class CapabilityExecutionHealthObserver:
    """Translate governed capability outcomes into deterministic health evidence."""

    def __init__(self, awareness: SelfAwarenessRuntime) -> None:
        self._awareness = awareness

    def __call__(self, result: CapabilityResult) -> None:
        if result.status in {CapabilityStatus.DENIED, CapabilityStatus.INVALID}:
            return
        state = (
            HealthState.HEALTHY
            if result.status is CapabilityStatus.SUCCEEDED
            else HealthState.DEGRADED
        )
        _observe_safely(
            self._awareness,
            component_id="capability_runtime",
            source=f"execution:{result.capability_key}",
            state=state,
            reason_code=f"capability_{result.status.value}",
            summary=(
                f"{result.capability_key} operation {result.operation} "
                f"finished with {result.status.value}"
            ),
            ttl_seconds=120.0,
            metadata=redact_data(
                {
                    "elapsed_ms": result.elapsed_ms,
                    "reason": result.reason,
                }
            ),
        )


class ProviderResilienceHealthObserver:
    """Mirror deterministic provider resilience state into the Self Model."""

    def __init__(self, awareness: SelfAwarenessRuntime) -> None:
        self._awareness = awareness

    def __call__(self, state: ProviderResilienceState) -> None:
        failure = state.last_failure
        if state.health is ProviderHealth.HEALTHY:
            health_state = HealthState.HEALTHY
            reason_code = "provider_healthy"
            summary = "Cloud provider session is healthy"
            metadata: dict[str, Any] = {}
        else:
            health_state = HealthState.DEGRADED
            reason_code = (
                f"provider_{failure.kind.value}" if failure is not None else "provider_degraded"
            )
            summary = "Cloud provider session is degraded"
            metadata = (
                {
                    "provider": failure.provider,
                    "failure_kind": failure.kind.value,
                    "status_code": failure.status_code,
                    "retryable": failure.retryable,
                }
                if failure is not None
                else {}
            )
        _observe_safely(
            self._awareness,
            component_id="runtime.provider",
            source="provider_session",
            state=health_state,
            reason_code=reason_code,
            summary=summary,
            ttl_seconds=120.0,
            metadata=redact_data(metadata),
        )
