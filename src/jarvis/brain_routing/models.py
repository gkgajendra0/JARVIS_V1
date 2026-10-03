"""Typed, subsystem-neutral contracts for JARVIS intelligence-path routing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from jarvis.model_routing.models import (
    EvidenceSizeClass,
    LocalityRequirement,
    PrivacyClass,
    RoutingRequest,
)


def _required_text(value: object, *, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _token(value: object, *, field: str) -> str:
    return _required_text(value, field=field).casefold()


def _tokens(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_token(value, field=field) for value in values))


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} must not be negative")
    return value


def _epoch(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


class BrainRouteKind(StrEnum):
    DETERMINISTIC = "deterministic"
    BOUNDED_DECISION = "bounded_decision"
    MODEL = "model"
    BLOCKED = "blocked"


class BrainRoutingMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    APPLY = "apply"

    @classmethod
    def parse(cls, value: str | BrainRoutingMode) -> BrainRoutingMode:
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().casefold()
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(
                "brain routing mode must be one of: off, shadow, apply"
            ) from exc


@dataclass(frozen=True, slots=True)
class GlobalBrainRouteFacts:
    """Trusted routing facts only; no prompt text or hidden reasoning."""

    route_request_id: str
    scope_id: str
    subsystem_key: str
    task_kind: str
    required_capabilities: tuple[str, ...]
    privacy_class: PrivacyClass
    locality_requirement: LocalityRequirement
    estimated_context_tokens: int
    evidence_size_class: EvidenceSizeClass
    latency_preference: str
    cost_preference: str
    output_contract: str
    quality_class: str
    knowledge_state: str
    recent_progress_signals: tuple[str, ...] = ()
    recent_failure_signals: tuple[str, ...] = ()
    affinity_key: str | None = None
    deterministic_candidate_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "route_request_id",
            _required_text(self.route_request_id, field="route_request_id"),
        )
        object.__setattr__(
            self,
            "scope_id",
            _required_text(self.scope_id, field="scope_id"),
        )
        object.__setattr__(
            self,
            "subsystem_key",
            _token(self.subsystem_key, field="subsystem_key"),
        )
        object.__setattr__(
            self,
            "task_kind",
            _token(self.task_kind, field="task_kind"),
        )
        object.__setattr__(
            self,
            "required_capabilities",
            _tokens(self.required_capabilities, field="required_capability"),
        )
        if not isinstance(self.privacy_class, PrivacyClass):
            raise TypeError("privacy_class must be a PrivacyClass")
        if not isinstance(self.locality_requirement, LocalityRequirement):
            raise TypeError("locality_requirement must be a LocalityRequirement")
        if not isinstance(self.evidence_size_class, EvidenceSizeClass):
            raise TypeError("evidence_size_class must be an EvidenceSizeClass")
        object.__setattr__(
            self,
            "estimated_context_tokens",
            _non_negative_int(
                self.estimated_context_tokens,
                field="estimated_context_tokens",
            ),
        )
        for name in (
            "latency_preference",
            "cost_preference",
            "output_contract",
            "quality_class",
            "knowledge_state",
        ):
            object.__setattr__(
                self,
                name,
                _token(getattr(self, name), field=name),
            )
        object.__setattr__(
            self,
            "recent_progress_signals",
            _tokens(self.recent_progress_signals, field="recent_progress_signal"),
        )
        object.__setattr__(
            self,
            "recent_failure_signals",
            _tokens(self.recent_failure_signals, field="recent_failure_signal"),
        )
        object.__setattr__(self, "affinity_key", _optional_text(self.affinity_key))
        object.__setattr__(
            self,
            "deterministic_candidate_count",
            _non_negative_int(
                self.deterministic_candidate_count,
                field="deterministic_candidate_count",
            ),
        )


@dataclass(frozen=True, slots=True)
class BrainRouteRecord:
    """Durable bounded provenance for one intelligence-path decision."""

    route_request_id: str
    work_id: str
    subsystem_key: str
    task_kind: str
    route_kind: BrainRouteKind
    mode: BrainRoutingMode
    policy_version: int
    policy_digest: str
    reason_codes: tuple[str, ...]
    created_at_epoch: float
    selected_action: str | None = None
    resolver_id: str | None = None
    resolver_version: int | None = None
    shadow_proposed_action: str | None = None
    shadow_match: bool | None = None
    model_decision_id: str | None = None
    model_target_id: str | None = None
    goal_complete: bool | None = None
    needs_owner: bool | None = None
    owner_question: str | None = None
    parameters_digest: str | None = None
    outcome_code: str = "selected"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "route_request_id",
            _required_text(self.route_request_id, field="route_request_id"),
        )
        object.__setattr__(
            self,
            "work_id",
            _required_text(self.work_id, field="work_id"),
        )
        object.__setattr__(
            self,
            "subsystem_key",
            _token(self.subsystem_key, field="subsystem_key"),
        )
        object.__setattr__(
            self,
            "task_kind",
            _token(self.task_kind, field="task_kind"),
        )
        if not isinstance(self.route_kind, BrainRouteKind):
            raise TypeError("route_kind must be a BrainRouteKind")
        if not isinstance(self.mode, BrainRoutingMode):
            raise TypeError("mode must be a BrainRoutingMode")
        if isinstance(self.policy_version, bool) or not isinstance(
            self.policy_version, int
        ):
            raise TypeError("policy_version must be an integer")
        if self.policy_version <= 0:
            raise ValueError("policy_version must be positive")
        digest = _token(self.policy_digest, field="policy_digest")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("policy_digest must be a 64-character SHA-256 digest")
        object.__setattr__(self, "policy_digest", digest)
        object.__setattr__(
            self,
            "reason_codes",
            _tokens(self.reason_codes, field="reason_code"),
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, field="created_at_epoch"),
        )
        for name in (
            "selected_action",
            "resolver_id",
            "shadow_proposed_action",
            "model_decision_id",
            "model_target_id",
            "owner_question",
        ):
            object.__setattr__(self, name, _optional_text(getattr(self, name)))
        for name in ("goal_complete", "needs_owner"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise TypeError(f"{name} must be a bool or None")
        digest = self.parameters_digest
        if digest is not None:
            normalized_digest = _token(digest, field="parameters_digest")
            if len(normalized_digest) != 64 or any(
                char not in "0123456789abcdef" for char in normalized_digest
            ):
                raise ValueError(
                    "parameters_digest must be a 64-character SHA-256 digest"
                )
            object.__setattr__(self, "parameters_digest", normalized_digest)
        if self.needs_owner is True and self.owner_question is None:
            raise ValueError("owner-waiting route provenance requires owner_question")
        if self.resolver_version is not None:
            if isinstance(self.resolver_version, bool) or not isinstance(
                self.resolver_version, int
            ):
                raise TypeError("resolver_version must be an integer or None")
            if self.resolver_version <= 0:
                raise ValueError("resolver_version must be positive")
        if self.shadow_match is not None and not isinstance(self.shadow_match, bool):
            raise TypeError("shadow_match must be a bool or None")
        object.__setattr__(
            self,
            "outcome_code",
            _token(self.outcome_code, field="outcome_code"),
        )


def project_global_facts_to_model_request(
    facts: GlobalBrainRouteFacts,
    *,
    strategy_key: str,
    strategy_version: int,
    stage_key: str | None = None,
    routing_features: dict[str, str | int | float | bool | None] | None = None,
) -> RoutingRequest:
    """Project global facts into the existing Phase-4 model target router."""

    if not isinstance(facts, GlobalBrainRouteFacts):
        raise TypeError("facts must be GlobalBrainRouteFacts")
    return RoutingRequest(
        routing_request_id=facts.route_request_id,
        work_id=facts.scope_id,
        task_kind=facts.task_kind,
        strategy_key=strategy_key,
        strategy_version=strategy_version,
        required_capabilities=facts.required_capabilities,
        privacy_class=facts.privacy_class,
        locality_requirement=facts.locality_requirement,
        estimated_context_tokens=facts.estimated_context_tokens,
        evidence_size_class=facts.evidence_size_class,
        recent_progress_signals=facts.recent_progress_signals,
        recent_failure_signals=facts.recent_failure_signals,
        latency_preference=facts.latency_preference,
        cost_preference=facts.cost_preference,
        stage_key=stage_key,
        affinity_key=facts.affinity_key,
        routing_features=dict(routing_features or {}),
    )
