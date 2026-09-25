"""Deterministic hard eligibility policy for Phase-4 model routing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from jarvis.model_routing.models import (
    BenchmarkStatus,
    EligibilitySnapshot,
    LocalityRequirement,
    ModelLocality,
    ModelTarget,
    PrivacyClass,
    RoutingRequest,
    RoutingStrategyResult,
    TargetExclusion,
)
from jarvis.model_routing.registry import ModelAdapterRegistry


def _token(value: object, *, field: str) -> str:
    normalized = str(value).strip().casefold()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


class EligibilityReason(StrEnum):
    TARGET_DISABLED = "target_disabled"
    BENCHMARK_NOT_ACCEPTED = "benchmark_not_accepted"
    CAPABILITY_MISSING = "capability_missing"
    STRUCTURED_OUTPUT_UNSUPPORTED = "structured_output_unsupported"
    CONTEXT_TOO_SMALL = "context_too_small"
    LOCALITY_MISMATCH = "locality_mismatch"
    PRIVACY_MISMATCH = "privacy_mismatch"
    CREDENTIAL_UNAVAILABLE = "credential_unavailable"
    ADAPTER_UNAVAILABLE = "adapter_unavailable"
    TARGET_UNHEALTHY = "target_unhealthy"
    TARGET_COOLDOWN = "target_cooldown"
    ROLE_MISMATCH = "role_mismatch"


class TargetHealthEligibility(StrEnum):
    """Bounded health facts consumed by eligibility before Phase-4C owns health."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    COOLDOWN = "cooldown"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class EligibilityRuntimeState:
    """Machine/runtime facts; contains availability booleans, never secret values."""

    credential_availability: dict[str, bool]
    target_health: dict[str, TargetHealthEligibility]
    target_health_versions: dict[str, int]

    def __post_init__(self) -> None:
        credentials: dict[str, bool] = {}
        for target_id, available in self.credential_availability.items():
            key = _token(target_id, field="credential target_id")
            if not isinstance(available, bool):
                raise TypeError("credential availability must be a bool")
            credentials[key] = available
        object.__setattr__(self, "credential_availability", credentials)

        health: dict[str, TargetHealthEligibility] = {}
        for target_id, state in self.target_health.items():
            key = _token(target_id, field="health target_id")
            if not isinstance(state, TargetHealthEligibility):
                raise TypeError("target health must be a TargetHealthEligibility")
            health[key] = state
        object.__setattr__(self, "target_health", health)

        versions: dict[str, int] = {}
        for target_id, version in self.target_health_versions.items():
            key = _token(target_id, field="health version target_id")
            versions[key] = _positive_int(version, field="health version")
        object.__setattr__(self, "target_health_versions", versions)


@dataclass(frozen=True, slots=True)
class EligibleTargets:
    snapshot: EligibilitySnapshot
    targets: tuple[ModelTarget, ...]

    def __post_init__(self) -> None:
        expected = self.snapshot.eligible_target_ids
        actual = tuple(target.target_id for target in self.targets)
        if actual != expected:
            raise ValueError(
                "eligible target objects must match the eligibility snapshot"
            )
        if not actual:
            raise ValueError("EligibleTargets requires at least one target")


@dataclass(frozen=True, slots=True)
class NoEligibleTargets:
    snapshot: EligibilitySnapshot
    reason_code: str = "no_eligible_target"

    def __post_init__(self) -> None:
        if self.snapshot.eligible_target_ids:
            raise ValueError("NoEligibleTargets requires an empty eligible target set")
        object.__setattr__(
            self,
            "reason_code",
            _token(self.reason_code, field="reason_code"),
        )


EligibilityResult: TypeAlias = EligibleTargets | NoEligibleTargets


class IneligibleStrategyTargetError(RuntimeError):
    """Raised when a strategy attempts to reintroduce an excluded target."""


_POLICY_VERSION = 1
_POLICY_RULES = (
    "target_enabled",
    "benchmark_accepted",
    "adapter_available",
    "required_capabilities",
    "structured_output_support",
    "context_capacity",
    "locality_requirement",
    "privacy_class",
    "credential_availability",
    "target_health",
    "required_role",
)
_POLICY_DIGEST = hashlib.sha256(
    json.dumps(
        {
            "policy": "model_routing_eligibility",
            "rules": _POLICY_RULES,
            "version": _POLICY_VERSION,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()


class EligibilityPolicy:
    """Apply deterministic hard filters before any routing strategy can rank."""

    policy_version = _POLICY_VERSION
    policy_digest = _POLICY_DIGEST

    def evaluate(
        self,
        *,
        request: RoutingRequest,
        targets: tuple[ModelTarget, ...],
        adapter_registry: ModelAdapterRegistry,
        runtime_state: EligibilityRuntimeState,
        snapshot_id: str,
    ) -> EligibilityResult:
        if not isinstance(request, RoutingRequest):
            raise TypeError("request must be a RoutingRequest")
        if not isinstance(adapter_registry, ModelAdapterRegistry):
            raise TypeError("adapter_registry must be a ModelAdapterRegistry")
        if not isinstance(runtime_state, EligibilityRuntimeState):
            raise TypeError("runtime_state must be an EligibilityRuntimeState")

        required_role = self._required_role(request)
        considered_ids: list[str] = []
        eligible: list[ModelTarget] = []
        exclusions: list[TargetExclusion] = []
        credential_snapshot: dict[str, bool] = {}
        health_versions: dict[str, int] = {}

        for target in targets:
            if not isinstance(target, ModelTarget):
                raise TypeError("targets must contain ModelTarget values")
            considered_ids.append(target.target_id)
            reasons = self._exclusion_reasons(
                request=request,
                target=target,
                adapter_registry=adapter_registry,
                runtime_state=runtime_state,
                required_role=required_role,
            )
            credential_snapshot[target.target_id] = self._credential_available(
                target,
                runtime_state,
            )
            if target.target_id in runtime_state.target_health_versions:
                health_versions[target.target_id] = (
                    runtime_state.target_health_versions[target.target_id]
                )

            if reasons:
                exclusions.append(
                    TargetExclusion(
                        target_id=target.target_id,
                        reason_codes=tuple(reason.value for reason in reasons),
                    )
                )
            else:
                eligible.append(target)

        snapshot = EligibilitySnapshot(
            snapshot_id=snapshot_id,
            routing_request_id=request.routing_request_id,
            considered_target_ids=tuple(considered_ids),
            eligible_target_ids=tuple(target.target_id for target in eligible),
            exclusions=tuple(exclusions),
            target_health_versions=health_versions,
            credential_availability=credential_snapshot,
            required_capabilities=request.required_capabilities,
            privacy_class=request.privacy_class,
            locality_requirement=request.locality_requirement,
            policy_version=self.policy_version,
            policy_digest=self.policy_digest,
        )
        if not eligible:
            return NoEligibleTargets(snapshot=snapshot)
        return EligibleTargets(snapshot=snapshot, targets=tuple(eligible))

    def validate_strategy_result(
        self,
        *,
        eligibility: EligibilityResult,
        strategy_result: RoutingStrategyResult,
    ) -> RoutingStrategyResult:
        if not isinstance(eligibility, EligibleTargets | NoEligibleTargets):
            raise TypeError("eligibility must be an eligibility result")
        if not isinstance(strategy_result, RoutingStrategyResult):
            raise TypeError("strategy_result must be a RoutingStrategyResult")

        eligible_ids = set(eligibility.snapshot.eligible_target_ids)
        reintroduced = tuple(
            target_id
            for target_id in strategy_result.ordered_target_ids
            if target_id not in eligible_ids
        )
        if reintroduced:
            raise IneligibleStrategyTargetError(
                "routing strategy returned ineligible target(s): "
                + ", ".join(reintroduced)
            )
        return strategy_result

    def _exclusion_reasons(
        self,
        *,
        request: RoutingRequest,
        target: ModelTarget,
        adapter_registry: ModelAdapterRegistry,
        runtime_state: EligibilityRuntimeState,
        required_role: str | None,
    ) -> tuple[EligibilityReason, ...]:
        reasons: list[EligibilityReason] = []

        if not target.enabled:
            reasons.append(EligibilityReason.TARGET_DISABLED)
        if target.benchmark_status is not BenchmarkStatus.ACCEPTED:
            reasons.append(EligibilityReason.BENCHMARK_NOT_ACCEPTED)
        if not adapter_registry.contains(target.adapter_id):
            reasons.append(EligibilityReason.ADAPTER_UNAVAILABLE)

        required = set(request.required_capabilities)
        if not required.issubset(target.capabilities):
            reasons.append(EligibilityReason.CAPABILITY_MISSING)
        if "structured_output" in required and not target.supports_structured_output:
            reasons.append(EligibilityReason.STRUCTURED_OUTPUT_UNSUPPORTED)
        if request.estimated_context_tokens > target.max_context_tokens:
            reasons.append(EligibilityReason.CONTEXT_TOO_SMALL)
        if not self._meets_locality(request.locality_requirement, target.locality):
            reasons.append(EligibilityReason.LOCALITY_MISMATCH)
        if not self._meets_privacy(request.privacy_class, target.locality):
            reasons.append(EligibilityReason.PRIVACY_MISMATCH)
        if not self._credential_available(target, runtime_state):
            reasons.append(EligibilityReason.CREDENTIAL_UNAVAILABLE)

        health = runtime_state.target_health.get(
            target.target_id,
            TargetHealthEligibility.UNKNOWN,
        )
        if health is TargetHealthEligibility.COOLDOWN:
            reasons.append(EligibilityReason.TARGET_COOLDOWN)
        elif health in {
            TargetHealthEligibility.UNAVAILABLE,
            TargetHealthEligibility.DISABLED,
        }:
            reasons.append(EligibilityReason.TARGET_UNHEALTHY)

        if required_role is not None and required_role not in target.roles:
            reasons.append(EligibilityReason.ROLE_MISMATCH)

        return tuple(reasons)

    @staticmethod
    def _credential_available(
        target: ModelTarget,
        runtime_state: EligibilityRuntimeState,
    ) -> bool:
        if target.credential_ref is None:
            return True
        return runtime_state.credential_availability.get(target.target_id, False)

    @staticmethod
    def _meets_locality(
        requirement: LocalityRequirement,
        locality: ModelLocality,
    ) -> bool:
        if requirement is LocalityRequirement.ANY:
            return True
        if requirement is LocalityRequirement.LOCAL_ONLY:
            return locality is ModelLocality.LOCAL
        if requirement is LocalityRequirement.PRIVATE_OR_LOCAL:
            return locality in {
                ModelLocality.LOCAL,
                ModelLocality.PRIVATE_REMOTE,
            }
        return False

    @staticmethod
    def _meets_privacy(
        privacy_class: PrivacyClass,
        locality: ModelLocality,
    ) -> bool:
        if privacy_class is PrivacyClass.STANDARD:
            return True
        if privacy_class is PrivacyClass.LOCAL_ONLY:
            return locality is ModelLocality.LOCAL
        if privacy_class is PrivacyClass.PRIVATE:
            return locality in {
                ModelLocality.LOCAL,
                ModelLocality.PRIVATE_REMOTE,
            }
        return False

    @staticmethod
    def _required_role(request: RoutingRequest) -> str | None:
        value = request.routing_features.get("required_role")
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("routing feature required_role must be a string")
        return _token(value, field="required_role")
