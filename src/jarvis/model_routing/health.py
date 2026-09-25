"""Target-scoped routing health and provider-failure policy."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum

from jarvis.model_routing.eligibility import TargetHealthEligibility
from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind


def _token(value: object, *, field: str) -> str:
    normalized = str(value).strip().casefold()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _epoch(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


class HealthAction(StrEnum):
    RETRY_SAME_TARGET = "retry_same_target"
    FALLBACK_ALLOWED = "fallback_allowed"
    FAIL_CLOSED_NO_FALLBACK = "fail_closed_no_fallback"


@dataclass(frozen=True, slots=True)
class TargetHealthRecord:
    target_id: str
    state: TargetHealthEligibility = TargetHealthEligibility.UNKNOWN
    consecutive_failures: int = 0
    cooldown_until_epoch: float | None = None
    last_failure_kind: str | None = None
    updated_at_epoch: float = 0.0
    version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_id",
            _token(self.target_id, field="target_id"),
        )
        if not isinstance(self.state, TargetHealthEligibility):
            raise TypeError("state must be a TargetHealthEligibility")
        if isinstance(self.consecutive_failures, bool) or not isinstance(
            self.consecutive_failures,
            int,
        ):
            raise TypeError("consecutive_failures must be an integer")
        if self.consecutive_failures < 0:
            raise ValueError("consecutive_failures must not be negative")
        if self.cooldown_until_epoch is not None:
            object.__setattr__(
                self,
                "cooldown_until_epoch",
                _epoch(self.cooldown_until_epoch, field="cooldown_until_epoch"),
            )
        object.__setattr__(
            self,
            "last_failure_kind",
            None
            if self.last_failure_kind is None
            else _token(self.last_failure_kind, field="last_failure_kind"),
        )
        object.__setattr__(
            self,
            "updated_at_epoch",
            _epoch(self.updated_at_epoch, field="updated_at_epoch"),
        )
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise TypeError("version must be an integer")
        if self.version <= 0:
            raise ValueError("version must be positive")

    def effective_state(self, *, now_epoch: float) -> TargetHealthEligibility:
        now = _epoch(now_epoch, field="now_epoch")
        if (
            self.state is TargetHealthEligibility.COOLDOWN
            and self.cooldown_until_epoch is not None
            and now >= self.cooldown_until_epoch
        ):
            return TargetHealthEligibility.HEALTHY
        return self.state

    def recovered(self, *, now_epoch: float) -> TargetHealthRecord:
        now = _epoch(now_epoch, field="now_epoch")
        return replace(
            self,
            state=TargetHealthEligibility.HEALTHY,
            consecutive_failures=0,
            cooldown_until_epoch=None,
            last_failure_kind=None,
            updated_at_epoch=now,
            version=self.version + 1,
        )


@dataclass(frozen=True, slots=True)
class HealthMutation:
    record: TargetHealthRecord
    action: HealthAction
    reason_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.record, TargetHealthRecord):
            raise TypeError("record must be a TargetHealthRecord")
        if not isinstance(self.action, HealthAction):
            raise TypeError("action must be a HealthAction")
        object.__setattr__(
            self,
            "reason_code",
            _token(self.reason_code, field="reason_code"),
        )


def apply_provider_failure(
    record: TargetHealthRecord,
    failure: ProviderFailure,
    *,
    now_epoch: float,
    base_cooldown_seconds: float = 30.0,
    max_cooldown_seconds: float = 300.0,
) -> HealthMutation:
    """Map normalized provider failures to bounded target-local health actions."""

    if not isinstance(record, TargetHealthRecord):
        raise TypeError("record must be a TargetHealthRecord")
    if not isinstance(failure, ProviderFailure):
        raise TypeError("failure must be a ProviderFailure")
    now = _epoch(now_epoch, field="now_epoch")
    base = _epoch(base_cooldown_seconds, field="base_cooldown_seconds")
    cap = _epoch(max_cooldown_seconds, field="max_cooldown_seconds")
    if base <= 0 or cap <= 0 or cap < base:
        raise ValueError("cooldown bounds are invalid")

    count = record.consecutive_failures + 1
    kind = failure.kind

    if kind in {
        ProviderFailureKind.RATE_LIMITED,
        ProviderFailureKind.QUOTA_EXHAUSTED,
    }:
        seconds = min(cap, base * (2 ** max(0, count - 1)))
        next_record = replace(
            record,
            state=TargetHealthEligibility.COOLDOWN,
            consecutive_failures=count,
            cooldown_until_epoch=now + seconds,
            last_failure_kind=kind.value,
            updated_at_epoch=now,
            version=record.version + 1,
        )
        return HealthMutation(
            record=next_record,
            action=HealthAction.FALLBACK_ALLOWED,
            reason_code="provider_pressure_cooldown",
        )

    if kind in {
        ProviderFailureKind.AUTHENTICATION_FAILED,
        ProviderFailureKind.PERMISSION_DENIED,
        ProviderFailureKind.MODEL_UNAVAILABLE,
    }:
        next_record = replace(
            record,
            state=TargetHealthEligibility.UNAVAILABLE,
            consecutive_failures=count,
            cooldown_until_epoch=None,
            last_failure_kind=kind.value,
            updated_at_epoch=now,
            version=record.version + 1,
        )
        return HealthMutation(
            record=next_record,
            action=HealthAction.FALLBACK_ALLOWED,
            reason_code="target_configuration_unavailable",
        )

    if kind is ProviderFailureKind.REQUEST_REJECTED:
        next_record = replace(
            record,
            state=TargetHealthEligibility.DEGRADED,
            consecutive_failures=count,
            cooldown_until_epoch=None,
            last_failure_kind=kind.value,
            updated_at_epoch=now,
            version=record.version + 1,
        )
        return HealthMutation(
            record=next_record,
            action=HealthAction.FAIL_CLOSED_NO_FALLBACK,
            reason_code="request_rejected_no_provider_hop",
        )

    if kind in {
        ProviderFailureKind.SERVICE_UNAVAILABLE,
        ProviderFailureKind.PROVIDER_SERVER_ERROR,
        ProviderFailureKind.TIMEOUT,
        ProviderFailureKind.CONNECTION_LOST,
    }:
        if count >= 2:
            seconds = min(cap, base * (2 ** max(0, count - 2)))
            state = TargetHealthEligibility.COOLDOWN
            cooldown_until = now + seconds
            action = HealthAction.FALLBACK_ALLOWED
            reason = "transient_failure_cooldown"
        else:
            state = TargetHealthEligibility.DEGRADED
            cooldown_until = None
            action = HealthAction.RETRY_SAME_TARGET
            reason = "transient_failure_degraded"
        next_record = replace(
            record,
            state=state,
            consecutive_failures=count,
            cooldown_until_epoch=cooldown_until,
            last_failure_kind=kind.value,
            updated_at_epoch=now,
            version=record.version + 1,
        )
        return HealthMutation(
            record=next_record,
            action=action,
            reason_code=reason,
        )

    next_record = replace(
        record,
        state=TargetHealthEligibility.DEGRADED,
        consecutive_failures=count,
        cooldown_until_epoch=None,
        last_failure_kind=kind.value,
        updated_at_epoch=now,
        version=record.version + 1,
    )
    return HealthMutation(
        record=next_record,
        action=HealthAction.FAIL_CLOSED_NO_FALLBACK,
        reason_code="unclassified_failure_no_provider_hop",
    )
