"""Provider-neutral Phase-4 model-routing contracts.

This module is intentionally side-effect free. It defines immutable routing facts
only; eligibility, health, persistence, provider invocation and fallback live in
later Phase-4 modules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeAlias

RoutingFeatureValue: TypeAlias = str | int | float | bool | None
MAX_ROUTING_FEATURES = 32


def _required_text(value: object, *, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _token(value: object, *, field: str) -> str:
    return _required_text(value, field=field).casefold()


def _tokens(
    values: tuple[str, ...],
    *,
    field: str,
    required: bool = False,
) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(_token(value, field=field) for value in values))
    if required and not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


def _non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} must not be negative")
    return value


def _non_negative_float(value: object | None, *, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


def _epoch(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


def _optional_epoch(value: object | None, *, field: str) -> float | None:
    if value is None:
        return None
    return _epoch(value, field=field)


def _sha256(value: object, *, field: str) -> str:
    normalized = _token(value, field=field)
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return normalized


def _bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be a bool")
    return value


def _feature_map(
    values: dict[str, RoutingFeatureValue],
) -> dict[str, RoutingFeatureValue]:
    if len(values) > MAX_ROUTING_FEATURES:
        raise ValueError(f"routing_features exceed {MAX_ROUTING_FEATURES}")
    normalized: dict[str, RoutingFeatureValue] = {}
    for key, value in values.items():
        token = _token(key, field="routing_feature key")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("routing feature floats must be finite")
        if value is not None and not isinstance(value, str | int | float | bool):
            raise TypeError("routing feature values must be scalar JSON values")
        normalized[token] = value
    return normalized


class ModelLocality(StrEnum):
    LOCAL = "local"
    PRIVATE_REMOTE = "private_remote"
    CLOUD = "cloud"


class PrivacyClass(StrEnum):
    STANDARD = "standard"
    PRIVATE = "private"
    LOCAL_ONLY = "local_only"


class LocalityRequirement(StrEnum):
    ANY = "any"
    PRIVATE_OR_LOCAL = "private_or_local"
    LOCAL_ONLY = "local_only"


class EvidenceSizeClass(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    HETEROGENEOUS = "heterogeneous"


class BenchmarkStatus(StrEnum):
    ACCEPTED = "accepted"
    UNVERIFIED = "unverified"
    REJECTED = "rejected"
    DISABLED = "disabled"


class RoutingAttemptKind(StrEnum):
    PRIMARY = "primary"
    FALLBACK = "fallback"


class ResponseContractResult(StrEnum):
    UNKNOWN = "unknown"
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class CostProfile:
    profile_id: str
    version: int
    effective_from_epoch: float
    input_usd_per_million_tokens: float | None = None
    output_usd_per_million_tokens: float | None = None
    effective_to_epoch: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "profile_id",
            _token(self.profile_id, field="profile_id"),
        )
        object.__setattr__(
            self,
            "version",
            _positive_int(self.version, field="version"),
        )
        start = _epoch(self.effective_from_epoch, field="effective_from_epoch")
        end = _optional_epoch(self.effective_to_epoch, field="effective_to_epoch")
        if end is not None and end < start:
            raise ValueError("effective_to_epoch cannot precede effective_from_epoch")
        object.__setattr__(self, "effective_from_epoch", start)
        object.__setattr__(self, "effective_to_epoch", end)
        object.__setattr__(
            self,
            "input_usd_per_million_tokens",
            _non_negative_float(
                self.input_usd_per_million_tokens,
                field="input_usd_per_million_tokens",
            ),
        )
        object.__setattr__(
            self,
            "output_usd_per_million_tokens",
            _non_negative_float(
                self.output_usd_per_million_tokens,
                field="output_usd_per_million_tokens",
            ),
        )


@dataclass(frozen=True, slots=True)
class ModelTarget:
    target_id: str
    adapter_id: str
    provider_id: str
    model_id: str
    locality: ModelLocality
    capabilities: tuple[str, ...]
    roles: tuple[str, ...]
    max_context_tokens: int
    supports_structured_output: bool
    supports_tools: bool
    supports_streaming: bool
    latency_class: str
    benchmark_status: BenchmarkStatus
    registry_version: int
    endpoint_ref: str | None = None
    credential_ref: str | None = None
    cost_profile: CostProfile | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_id",
            _token(self.target_id, field="target_id"),
        )
        object.__setattr__(
            self,
            "adapter_id",
            _token(self.adapter_id, field="adapter_id"),
        )
        object.__setattr__(
            self,
            "provider_id",
            _token(self.provider_id, field="provider_id"),
        )
        object.__setattr__(
            self,
            "model_id",
            _required_text(self.model_id, field="model_id"),
        )
        if not isinstance(self.locality, ModelLocality):
            raise TypeError("locality must be a ModelLocality")
        object.__setattr__(
            self,
            "capabilities",
            _tokens(
                self.capabilities,
                field="capability",
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "roles",
            _tokens(self.roles, field="role", required=True),
        )
        object.__setattr__(
            self,
            "max_context_tokens",
            _positive_int(
                self.max_context_tokens,
                field="max_context_tokens",
            ),
        )
        object.__setattr__(
            self,
            "supports_structured_output",
            _bool(
                self.supports_structured_output,
                field="supports_structured_output",
            ),
        )
        object.__setattr__(
            self,
            "supports_tools",
            _bool(self.supports_tools, field="supports_tools"),
        )
        object.__setattr__(
            self,
            "supports_streaming",
            _bool(self.supports_streaming, field="supports_streaming"),
        )
        object.__setattr__(
            self,
            "latency_class",
            _token(self.latency_class, field="latency_class"),
        )
        if not isinstance(self.benchmark_status, BenchmarkStatus):
            raise TypeError("benchmark_status must be a BenchmarkStatus")
        object.__setattr__(
            self,
            "registry_version",
            _positive_int(
                self.registry_version,
                field="registry_version",
            ),
        )
        object.__setattr__(
            self,
            "endpoint_ref",
            _optional_text(self.endpoint_ref),
        )
        object.__setattr__(
            self,
            "credential_ref",
            _optional_text(self.credential_ref),
        )
        if self.cost_profile is not None and not isinstance(
            self.cost_profile,
            CostProfile,
        ):
            raise TypeError("cost_profile must be a CostProfile or None")
        object.__setattr__(
            self,
            "enabled",
            _bool(self.enabled, field="enabled"),
        )

    @property
    def stable_identity(self) -> str:
        return self.target_id


@dataclass(frozen=True, slots=True)
class RoutingRequest:
    routing_request_id: str
    work_id: str
    task_kind: str
    strategy_key: str
    strategy_version: int
    required_capabilities: tuple[str, ...]
    privacy_class: PrivacyClass
    locality_requirement: LocalityRequirement
    estimated_context_tokens: int
    evidence_size_class: EvidenceSizeClass
    recent_progress_signals: tuple[str, ...]
    recent_failure_signals: tuple[str, ...]
    latency_preference: str
    cost_preference: str
    change_id: str | None = None
    stage_key: str | None = None
    affinity_key: str | None = None
    routing_features: dict[str, RoutingFeatureValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "routing_request_id",
            _required_text(
                self.routing_request_id,
                field="routing_request_id",
            ),
        )
        object.__setattr__(
            self,
            "work_id",
            _required_text(self.work_id, field="work_id"),
        )
        object.__setattr__(
            self,
            "task_kind",
            _token(self.task_kind, field="task_kind"),
        )
        object.__setattr__(
            self,
            "strategy_key",
            _token(self.strategy_key, field="strategy_key"),
        )
        object.__setattr__(
            self,
            "strategy_version",
            _positive_int(
                self.strategy_version,
                field="strategy_version",
            ),
        )
        object.__setattr__(
            self,
            "required_capabilities",
            _tokens(
                self.required_capabilities,
                field="required_capability",
            ),
        )
        if not isinstance(self.privacy_class, PrivacyClass):
            raise TypeError("privacy_class must be a PrivacyClass")
        if not isinstance(self.locality_requirement, LocalityRequirement):
            raise TypeError("locality_requirement must be a LocalityRequirement")
        object.__setattr__(
            self,
            "estimated_context_tokens",
            _non_negative_int(
                self.estimated_context_tokens,
                field="estimated_context_tokens",
            ),
        )
        if not isinstance(self.evidence_size_class, EvidenceSizeClass):
            raise TypeError("evidence_size_class must be an EvidenceSizeClass")
        object.__setattr__(
            self,
            "recent_progress_signals",
            _tokens(
                self.recent_progress_signals,
                field="recent_progress_signal",
            ),
        )
        object.__setattr__(
            self,
            "recent_failure_signals",
            _tokens(
                self.recent_failure_signals,
                field="recent_failure_signal",
            ),
        )
        object.__setattr__(
            self,
            "latency_preference",
            _token(
                self.latency_preference,
                field="latency_preference",
            ),
        )
        object.__setattr__(
            self,
            "cost_preference",
            _token(self.cost_preference, field="cost_preference"),
        )
        object.__setattr__(
            self,
            "change_id",
            _optional_text(self.change_id),
        )
        object.__setattr__(
            self,
            "stage_key",
            _optional_text(self.stage_key),
        )
        object.__setattr__(
            self,
            "affinity_key",
            _optional_text(self.affinity_key),
        )
        object.__setattr__(
            self,
            "routing_features",
            _feature_map(self.routing_features),
        )


@dataclass(frozen=True, slots=True)
class TargetExclusion:
    target_id: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_id",
            _token(self.target_id, field="target_id"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tokens(
                self.reason_codes,
                field="exclusion_reason",
                required=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class EligibilitySnapshot:
    snapshot_id: str
    routing_request_id: str
    considered_target_ids: tuple[str, ...]
    eligible_target_ids: tuple[str, ...]
    exclusions: tuple[TargetExclusion, ...]
    target_health_versions: dict[str, int]
    credential_availability: dict[str, bool]
    required_capabilities: tuple[str, ...]
    privacy_class: PrivacyClass
    locality_requirement: LocalityRequirement
    policy_version: int
    policy_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "snapshot_id",
            _required_text(self.snapshot_id, field="snapshot_id"),
        )
        object.__setattr__(
            self,
            "routing_request_id",
            _required_text(
                self.routing_request_id,
                field="routing_request_id",
            ),
        )
        considered = _tokens(
            self.considered_target_ids,
            field="considered_target_id",
        )
        eligible = _tokens(
            self.eligible_target_ids,
            field="eligible_target_id",
        )
        considered_set = set(considered)
        if not set(eligible).issubset(considered_set):
            raise ValueError("eligible targets must be part of considered targets")
        exclusion_ids = tuple(exclusion.target_id for exclusion in self.exclusions)
        if not set(exclusion_ids).issubset(considered_set):
            raise ValueError("excluded targets must be part of considered targets")
        if set(eligible).intersection(exclusion_ids):
            raise ValueError("target cannot be both eligible and excluded")
        if set(eligible).union(exclusion_ids) != considered_set:
            raise ValueError("every considered target must be eligible or excluded")
        if len(exclusion_ids) != len(set(exclusion_ids)):
            raise ValueError("target exclusions must be unique")
        object.__setattr__(
            self,
            "considered_target_ids",
            considered,
        )
        object.__setattr__(
            self,
            "eligible_target_ids",
            eligible,
        )

        health: dict[str, int] = {}
        for target_id, version in self.target_health_versions.items():
            normalized = _token(
                target_id,
                field="target health target_id",
            )
            health[normalized] = _positive_int(
                version,
                field="target health version",
            )
        if not set(health).issubset(considered_set):
            raise ValueError("target health snapshot contains an unconsidered target")
        object.__setattr__(
            self,
            "target_health_versions",
            health,
        )

        credentials: dict[str, bool] = {}
        for target_id, available in self.credential_availability.items():
            normalized = _token(
                target_id,
                field="credential target_id",
            )
            credentials[normalized] = _bool(
                available,
                field="credential availability",
            )
        if not set(credentials).issubset(considered_set):
            raise ValueError("credential snapshot contains an unconsidered target")
        object.__setattr__(
            self,
            "credential_availability",
            credentials,
        )
        object.__setattr__(
            self,
            "required_capabilities",
            _tokens(
                self.required_capabilities,
                field="required_capability",
            ),
        )
        if not isinstance(self.privacy_class, PrivacyClass):
            raise TypeError("privacy_class must be a PrivacyClass")
        if not isinstance(
            self.locality_requirement,
            LocalityRequirement,
        ):
            raise TypeError(
                "locality_requirement must be a LocalityRequirement"
            )
        object.__setattr__(
            self,
            "policy_version",
            _positive_int(
                self.policy_version,
                field="policy_version",
            ),
        )
        object.__setattr__(
            self,
            "policy_digest",
            _sha256(
                self.policy_digest,
                field="policy_digest",
            ),
        )


@dataclass(frozen=True, slots=True)
class RoutingStrategyResult:
    ordered_target_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    selected_role: str

    def __post_init__(self) -> None:
        targets = _tokens(
            self.ordered_target_ids,
            field="ordered_target_id",
            required=True,
        )
        if len(targets) != len(self.ordered_target_ids):
            raise ValueError("ordered_target_ids must not contain duplicates")
        object.__setattr__(
            self,
            "ordered_target_ids",
            targets,
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tokens(
                self.reason_codes,
                field="decision_reason",
            ),
        )
        object.__setattr__(
            self,
            "selected_role",
            _token(
                self.selected_role,
                field="selected_role",
            ),
        )


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    decision_id: str
    routing_request_id: str
    strategy_key: str
    strategy_version: int
    strategy_digest: str
    ordered_target_ids: tuple[str, ...]
    selected_target_id: str
    reason_codes: tuple[str, ...]
    selected_role: str
    fallback_budget: int
    created_at_epoch: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decision_id",
            _required_text(self.decision_id, field="decision_id"),
        )
        object.__setattr__(
            self,
            "routing_request_id",
            _required_text(
                self.routing_request_id,
                field="routing_request_id",
            ),
        )
        object.__setattr__(
            self,
            "strategy_key",
            _token(self.strategy_key, field="strategy_key"),
        )
        object.__setattr__(
            self,
            "strategy_version",
            _positive_int(
                self.strategy_version,
                field="strategy_version",
            ),
        )
        object.__setattr__(
            self,
            "strategy_digest",
            _sha256(
                self.strategy_digest,
                field="strategy_digest",
            ),
        )
        ordered = _tokens(
            self.ordered_target_ids,
            field="ordered_target_id",
            required=True,
        )
        if len(ordered) != len(self.ordered_target_ids):
            raise ValueError(
                "ordered_target_ids must not contain duplicates"
            )
        selected = _token(
            self.selected_target_id,
            field="selected_target_id",
        )
        if selected not in ordered:
            raise ValueError("selected_target_id must be in ordered_target_ids")
        object.__setattr__(
            self,
            "ordered_target_ids",
            ordered,
        )
        object.__setattr__(
            self,
            "selected_target_id",
            selected,
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tokens(
                self.reason_codes,
                field="decision_reason",
            ),
        )
        object.__setattr__(
            self,
            "selected_role",
            _token(
                self.selected_role,
                field="selected_role",
            ),
        )
        object.__setattr__(
            self,
            "fallback_budget",
            _non_negative_int(
                self.fallback_budget,
                field="fallback_budget",
            ),
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(
                self.created_at_epoch,
                field="created_at_epoch",
            ),
        )


@dataclass(frozen=True, slots=True)
class RoutingAttempt:
    attempt_id: str
    decision_id: str
    work_id: str
    target_id: str
    attempt_ordinal: int
    started_at_epoch: float
    kind: RoutingAttemptKind
    ended_at_epoch: float | None = None
    latency_ms: float | None = None
    failure_class: str | None = None
    usage: dict[str, int | float] = field(default_factory=dict)
    estimated_cost_usd: float | None = None
    response_contract_result: ResponseContractResult = ResponseContractResult.UNKNOWN
    correlation_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attempt_id",
            _required_text(self.attempt_id, field="attempt_id"),
        )
        object.__setattr__(
            self,
            "decision_id",
            _required_text(self.decision_id, field="decision_id"),
        )
        object.__setattr__(
            self,
            "work_id",
            _required_text(self.work_id, field="work_id"),
        )
        object.__setattr__(
            self,
            "target_id",
            _token(self.target_id, field="target_id"),
        )
        object.__setattr__(
            self,
            "attempt_ordinal",
            _positive_int(
                self.attempt_ordinal,
                field="attempt_ordinal",
            ),
        )
        started = _epoch(
            self.started_at_epoch,
            field="started_at_epoch",
        )
        ended = _optional_epoch(
            self.ended_at_epoch,
            field="ended_at_epoch",
        )
        if ended is not None and ended < started:
            raise ValueError("ended_at_epoch cannot precede started_at_epoch")
        object.__setattr__(
            self,
            "started_at_epoch",
            started,
        )
        object.__setattr__(
            self,
            "ended_at_epoch",
            ended,
        )
        object.__setattr__(
            self,
            "latency_ms",
            _non_negative_float(
                self.latency_ms,
                field="latency_ms",
            ),
        )
        object.__setattr__(
            self,
            "failure_class",
            _optional_text(self.failure_class),
        )
        normalized_usage: dict[str, int | float] = {}
        for key, value in self.usage.items():
            normalized_key = _token(
                key,
                field="usage key",
            )
            normalized_value = _non_negative_float(
                value,
                field=f"usage[{normalized_key}]",
            )
            assert normalized_value is not None
            normalized_usage[normalized_key] = normalized_value
        object.__setattr__(
            self,
            "usage",
            normalized_usage,
        )
        object.__setattr__(
            self,
            "estimated_cost_usd",
            _non_negative_float(
                self.estimated_cost_usd,
                field="estimated_cost_usd",
            ),
        )
        if not isinstance(self.kind, RoutingAttemptKind):
            raise TypeError("kind must be a RoutingAttemptKind")
        if not isinstance(
            self.response_contract_result,
            ResponseContractResult,
        ):
            raise TypeError("response_contract_result must be a ResponseContractResult")
        object.__setattr__(
            self,
            "correlation_key",
            _optional_text(self.correlation_key),
        )


@dataclass(frozen=True, slots=True)
class RoutingOutcome:
    outcome_id: str
    decision_id: str
    work_id: str
    fallback_path: tuple[str, ...]
    total_attempts: int
    total_latency_ms: float
    final_target_id: str | None = None
    work_step_succeeded: bool | None = None
    verifier_reference: str | None = None
    accepted_result: bool | None = None
    aggregate_usage: dict[str, int | float] = field(default_factory=dict)
    estimated_total_cost_usd: float | None = None
    outcome_evidence_reference: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "outcome_id",
            _required_text(self.outcome_id, field="outcome_id"),
        )
        object.__setattr__(
            self,
            "decision_id",
            _required_text(self.decision_id, field="decision_id"),
        )
        object.__setattr__(
            self,
            "work_id",
            _required_text(self.work_id, field="work_id"),
        )
        path = _tokens(
            self.fallback_path,
            field="fallback_target_id",
        )
        object.__setattr__(
            self,
            "fallback_path",
            path,
        )
        object.__setattr__(
            self,
            "total_attempts",
            _non_negative_int(
                self.total_attempts,
                field="total_attempts",
            ),
        )
        latency = _non_negative_float(
            self.total_latency_ms,
            field="total_latency_ms",
        )
        assert latency is not None
        object.__setattr__(
            self,
            "total_latency_ms",
            latency,
        )
        final_target = (
            None
            if self.final_target_id is None
            else _token(
                self.final_target_id,
                field="final_target_id",
            )
        )
        if final_target is not None and path and final_target != path[-1]:
            raise ValueError("final_target_id must match the last fallback_path target")
        object.__setattr__(
            self,
            "final_target_id",
            final_target,
        )
        if self.work_step_succeeded is not None:
            object.__setattr__(
                self,
                "work_step_succeeded",
                _bool(
                    self.work_step_succeeded,
                    field="work_step_succeeded",
                ),
            )
        if self.accepted_result is not None:
            object.__setattr__(
                self,
                "accepted_result",
                _bool(
                    self.accepted_result,
                    field="accepted_result",
                ),
            )
        object.__setattr__(
            self,
            "verifier_reference",
            _optional_text(self.verifier_reference),
        )
        normalized_usage: dict[str, int | float] = {}
        for key, value in self.aggregate_usage.items():
            normalized_key = _token(
                key,
                field="aggregate usage key",
            )
            normalized_value = _non_negative_float(
                value,
                field=f"aggregate_usage[{normalized_key}]",
            )
            assert normalized_value is not None
            normalized_usage[normalized_key] = normalized_value
        object.__setattr__(
            self,
            "aggregate_usage",
            normalized_usage,
        )
        object.__setattr__(
            self,
            "estimated_total_cost_usd",
            _non_negative_float(
                self.estimated_total_cost_usd,
                field="estimated_total_cost_usd",
            ),
        )
        object.__setattr__(
            self,
            "outcome_evidence_reference",
            _optional_text(self.outcome_evidence_reference),
        )
