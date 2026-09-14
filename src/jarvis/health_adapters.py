"""Adapters that convert accepted runtime outcomes into health evidence."""

from __future__ import annotations

from jarvis.capabilities.models import CapabilityResult, CapabilityStatus
from jarvis.config import JarvisConfig
from jarvis.observability.redaction import redact_data
from jarvis.preflight import StartupPreflightError, print_preflight, run_startup_preflight
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


def require_startup_preflight_with_health(
    config: JarvisConfig,
    awareness: SelfAwarenessRuntime,
) -> None:
    """Run canonical preflight once and mirror its outcomes into health evidence."""

    checks = run_startup_preflight(config)
    print_preflight(checks)
    for check in checks:
        awareness.observe(
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
        self._awareness.observe(
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
