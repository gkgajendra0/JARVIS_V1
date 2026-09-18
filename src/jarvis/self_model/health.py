"""Deterministic component health evidence and evaluation."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Any

from jarvis.self_model.models import DependencyCriticality


class HealthState(str, Enum):
    UNKNOWN = "unknown"
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    RECOVERING = "recovering"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class HealthObservation:
    component_id: str
    source: str
    state: HealthState
    reason_code: str
    summary: str
    observed_at_epoch: float
    ttl_seconds: float
    metadata_json: str = "{}"

    @classmethod
    def create(
        cls,
        *,
        component_id: str,
        source: str,
        state: HealthState,
        reason_code: str,
        summary: str,
        ttl_seconds: float,
        metadata: dict[str, Any] | None = None,
        observed_at_epoch: float | None = None,
    ) -> HealthObservation:
        if ttl_seconds <= 0:
            raise ValueError("health observation ttl_seconds must be positive")
        return cls(
            component_id=str(component_id).strip().lower(),
            source=str(source).strip().lower(),
            state=state,
            reason_code=str(reason_code).strip().lower(),
            summary=str(summary).strip(),
            observed_at_epoch=(
                time.time() if observed_at_epoch is None else observed_at_epoch
            ),
            ttl_seconds=ttl_seconds,
            metadata_json=json.dumps(
                metadata or {},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            ),
        )

    def is_fresh(self, *, now_epoch: float | None = None) -> bool:
        now = time.time() if now_epoch is None else now_epoch
        return now <= self.observed_at_epoch + self.ttl_seconds


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    component_id: str
    state: HealthState
    evaluated_at_epoch: float
    reason_codes: tuple[str, ...] = ()
    summaries: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    dependency_states: tuple[tuple[str, HealthState], ...] = ()


_STATE_PRECEDENCE = {
    HealthState.FAILED: 60,
    HealthState.RECOVERING: 50,
    HealthState.DEGRADED: 40,
    HealthState.STARTING: 30,
    HealthState.HEALTHY: 20,
    HealthState.DISABLED: 10,
    HealthState.UNKNOWN: 0,
}


class HealthRegistry:
    """Thread-safe latest-evidence registry; an LLM never writes health state."""

    def __init__(self) -> None:
        self._latest: dict[tuple[str, str], HealthObservation] = {}
        self._lock = RLock()

    def record(self, observation: HealthObservation) -> None:
        key = (observation.component_id, observation.source)
        with self._lock:
            previous = self._latest.get(key)
            if previous is not None and (
                observation.observed_at_epoch < previous.observed_at_epoch
            ):
                return
            self._latest[key] = observation

    def observations(
        self,
        component_id: str,
        *,
        now_epoch: float | None = None,
    ) -> tuple[HealthObservation, ...]:
        normalized = str(component_id).strip().lower()
        with self._lock:
            items = tuple(
                observation
                for (candidate, _), observation in self._latest.items()
                if candidate == normalized and observation.is_fresh(now_epoch=now_epoch)
            )
        return tuple(sorted(items, key=lambda item: item.source))

    def snapshot(
        self,
        component_id: str,
        *,
        now_epoch: float | None = None,
    ) -> HealthSnapshot:
        evaluated_at = time.time() if now_epoch is None else now_epoch
        observations = self.observations(component_id, now_epoch=evaluated_at)
        if not observations:
            return HealthSnapshot(
                component_id=str(component_id).strip().lower(),
                state=HealthState.UNKNOWN,
                evaluated_at_epoch=evaluated_at,
                reason_codes=("no_fresh_health_evidence",),
            )
        state = max(
            (item.state for item in observations),
            key=_STATE_PRECEDENCE.__getitem__,
        )
        return HealthSnapshot(
            component_id=observations[0].component_id,
            state=state,
            evaluated_at_epoch=evaluated_at,
            reason_codes=tuple(sorted({item.reason_code for item in observations})),
            summaries=tuple(item.summary for item in observations),
            sources=tuple(item.source for item in observations),
        )


def roll_up_dependency_health(
    base: HealthSnapshot,
    dependencies: tuple[tuple[str, DependencyCriticality, HealthSnapshot], ...],
) -> HealthSnapshot:
    """Apply explicit dependency criticality without model inference."""

    state = base.state
    reason_codes = set(base.reason_codes)
    summaries = list(base.summaries)
    dependency_states: list[tuple[str, HealthState]] = []

    for dependency_id, criticality, snapshot in dependencies:
        dependency_states.append((dependency_id, snapshot.state))
        unhealthy = snapshot.state in {
            HealthState.STARTING,
            HealthState.DEGRADED,
            HealthState.FAILED,
            HealthState.RECOVERING,
            HealthState.DISABLED,
        }
        if not unhealthy or criticality is DependencyCriticality.OPTIONAL:
            continue
        reason_codes.add(f"dependency_{dependency_id}_{snapshot.state.value}")
        summaries.append(f"dependency {dependency_id} is {snapshot.state.value}")
        if (
            criticality is DependencyCriticality.BLOCKING
            and snapshot.state is HealthState.FAILED
        ):
            state = HealthState.FAILED
        elif state not in {HealthState.FAILED, HealthState.RECOVERING}:
            state = HealthState.DEGRADED

    return HealthSnapshot(
        component_id=base.component_id,
        state=state,
        evaluated_at_epoch=base.evaluated_at_epoch,
        reason_codes=tuple(sorted(reason_codes)),
        summaries=tuple(summaries),
        sources=base.sources,
        dependency_states=tuple(sorted(dependency_states)),
    )
