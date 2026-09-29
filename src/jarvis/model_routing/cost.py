"""Provider-neutral cost estimation and mission-level telemetry reports."""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.model_routing.models import CostProfile, ModelTarget, RoutingAttempt
from jarvis.model_routing.store import ModelRoutingStore


def estimate_usage_cost_usd(
    target: ModelTarget,
    usage: dict[str, int | float],
) -> float | None:
    """Estimate token cost when both usage and an effective target profile are known."""

    if not isinstance(target, ModelTarget):
        raise TypeError("target must be a ModelTarget")
    profile = target.cost_profile
    if profile is None:
        return None
    return estimate_profile_usage_cost_usd(profile, usage)


def estimate_profile_usage_cost_usd(
    profile: CostProfile,
    usage: dict[str, int | float],
) -> float | None:
    if not isinstance(profile, CostProfile):
        raise TypeError("profile must be a CostProfile")
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if input_tokens is None or output_tokens is None:
        return None

    input_value = float(input_tokens)
    output_value = float(output_tokens)
    if input_value < 0 or output_value < 0:
        raise ValueError("token usage must not be negative")

    input_rate = profile.input_usd_per_million_tokens
    output_rate = profile.output_usd_per_million_tokens
    if input_value > 0 and input_rate is None:
        return None
    if output_value > 0 and output_rate is None:
        return None

    return (
        input_value * float(input_rate or 0.0)
        + output_value * float(output_rate or 0.0)
    ) / 1_000_000.0


@dataclass(frozen=True, slots=True)
class CostTelemetryBucket:
    stage_key: str
    provider_id: str
    model_id: str
    attempt_count: int
    fallback_attempts: int
    failed_attempts: int
    missing_usage_attempts: int
    unpriced_attempts: int
    aggregate_usage: dict[str, float] = field(default_factory=dict)
    known_estimated_cost_usd: float = 0.0
    estimated_total_cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class CostTelemetryReport:
    scope_kind: str
    scope_id: str
    attempt_count: int
    fallback_attempts: int
    failed_attempts: int
    missing_usage_attempts: int
    unpriced_attempts: int
    aggregate_usage: dict[str, float] = field(default_factory=dict)
    known_estimated_cost_usd: float = 0.0
    estimated_total_cost_usd: float | None = None
    breakdown: tuple[CostTelemetryBucket, ...] = ()


@dataclass
class _MutableBucket:
    attempts: int = 0
    fallbacks: int = 0
    failures: int = 0
    missing_usage: int = 0
    unpriced: int = 0
    usage: dict[str, float] = field(default_factory=dict)
    known_cost: float = 0.0

    def add(self, attempt: RoutingAttempt) -> None:
        self.attempts += 1
        if attempt.kind.value == "fallback":
            self.fallbacks += 1
        if attempt.failure_class is not None:
            self.failures += 1
        if not attempt.usage_observed:
            self.missing_usage += 1
        for key, value in attempt.usage.items():
            self.usage[key] = self.usage.get(key, 0.0) + float(value)
        if attempt.estimated_cost_usd is None:
            self.unpriced += 1
        else:
            self.known_cost += float(attempt.estimated_cost_usd)

    def freeze(self, *, stage_key: str, provider_id: str, model_id: str) -> CostTelemetryBucket:
        return CostTelemetryBucket(
            stage_key=stage_key,
            provider_id=provider_id,
            model_id=model_id,
            attempt_count=self.attempts,
            fallback_attempts=self.fallbacks,
            failed_attempts=self.failures,
            missing_usage_attempts=self.missing_usage,
            unpriced_attempts=self.unpriced,
            aggregate_usage=dict(sorted(self.usage.items())),
            known_estimated_cost_usd=self.known_cost,
            estimated_total_cost_usd=(self.known_cost if self.unpriced == 0 else None),
        )


class CostTelemetryReader:
    """Aggregate durable routing attempts without exposing prompts or credentials."""

    def __init__(self, store: ModelRoutingStore) -> None:
        if not isinstance(store, ModelRoutingStore):
            raise TypeError("store must be a ModelRoutingStore")
        self._store = store

    def for_work(self, work_id: str) -> CostTelemetryReport:
        return self._report(
            scope_kind="work",
            scope_id=work_id,
            attempts=self._store.list_attempts_for_work(work_id),
        )

    def for_change(self, change_id: str) -> CostTelemetryReport:
        return self._report(
            scope_kind="engineering_change",
            scope_id=change_id,
            attempts=self._store.list_attempts_for_change(change_id),
        )

    @staticmethod
    def _report(
        *,
        scope_kind: str,
        scope_id: str,
        attempts: tuple[RoutingAttempt, ...],
    ) -> CostTelemetryReport:
        normalized_id = str(scope_id).strip()
        if not normalized_id:
            raise ValueError("scope_id must not be empty")

        overall = _MutableBucket()
        groups: dict[tuple[str, str, str], _MutableBucket] = {}
        for attempt in attempts:
            overall.add(attempt)
            key = (
                attempt.stage_key or "unknown",
                attempt.provider_id or "unknown",
                attempt.model_id or "unknown",
            )
            groups.setdefault(key, _MutableBucket()).add(attempt)

        breakdown = tuple(
            groups[key].freeze(
                stage_key=key[0],
                provider_id=key[1],
                model_id=key[2],
            )
            for key in sorted(groups)
        )
        return CostTelemetryReport(
            scope_kind=scope_kind,
            scope_id=normalized_id,
            attempt_count=overall.attempts,
            fallback_attempts=overall.fallbacks,
            failed_attempts=overall.failures,
            missing_usage_attempts=overall.missing_usage,
            unpriced_attempts=overall.unpriced,
            aggregate_usage=dict(sorted(overall.usage.items())),
            known_estimated_cost_usd=overall.known_cost,
            estimated_total_cost_usd=(
                overall.known_cost if overall.unpriced == 0 else None
            ),
            breakdown=breakdown,
        )
