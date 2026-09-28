"""Typed contracts for the Phase-10A autonomous operations control plane."""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self

from jarvis.engineering_knowledge.canonical import JSONValue
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.work.models import WorkPriority

AUTONOMY_CONTRACT_SCHEMA_VERSION = "1"


class ObjectiveOrigin(StrEnum):
    OWNER = "owner"
    REGISTERED_SYSTEM_OBLIGATION = "registered_system_obligation"


class ObjectiveStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    SATISFIED = "satisfied"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class DesiredStateStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class FindingStatus(StrEnum):
    STABILIZING = "stabilizing"
    ACTIVE = "active"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"
    SUPERSEDED = "superseded"


class ActionKind(StrEnum):
    NO_ACTION = "no_action"
    EXISTING_CONTROLLER = "existing_controller"
    WORK_ITEM = "work_item"
    ENGINEERING_CHANGE = "engineering_change"
    OWNER_ATTENTION = "owner_attention"


class CandidateDisposition(StrEnum):
    SHADOW_ONLY = "shadow_only"
    ADMITTED = "admitted"
    DEFERRED_BUDGET = "deferred_budget"
    DEFERRED_COOLDOWN = "deferred_cooldown"
    BLOCKED_POLICY = "blocked_policy"
    INHIBITED = "inhibited"
    OBSOLETE = "obsolete"


class AttentionStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class AutonomyMode(StrEnum):
    OFF = "off"
    OBSERVE = "observe"
    SHADOW = "shadow"
    ASSISTED = "assisted"
    ACTIVE_BOUNDED = "active_bounded"


class ReconcileTrigger(StrEnum):
    STARTUP = "startup"
    STATE_CHANGE_HINT = "state_change_hint"
    PERIODIC = "periodic"
    MANUAL_TEST = "manual_test"


class ReconcileStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    REPLAY_NOOP = "replay_noop"


def _text(value: object, field: str, *, max_length: int = 1000) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


def _token(value: object, field: str, *, max_length: int = 200) -> str:
    return _text(value, field, max_length=max_length).casefold()


def _optional_text(
    value: object | None,
    field: str,
    *,
    max_length: int = 1000,
) -> str | None:
    if value is None:
        return None
    return _text(value, field, max_length=max_length)


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


def _epoch(
    value: object | None,
    field: str,
    *,
    optional: bool = False,
) -> float | None:
    if value is None:
        if optional:
            return None
        raise ValueError(f"{field} must not be None")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


def _nonnegative_float(
    value: object | None,
    field: str,
    *,
    optional: bool = False,
) -> float | None:
    if value is None:
        if optional:
            return None
        raise ValueError(f"{field} must not be None")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


def _json_object(value: object, field: str) -> dict[str, JSONValue]:
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be a JSON object")
    canonical_digest(value)
    return deepcopy(value)


def _unique_tokens(
    values: tuple[str, ...],
    field: str,
    *,
    allow_empty: bool = False,
    max_items: int = 64,
) -> tuple[str, ...]:
    if not values and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    if len(values) > max_items:
        raise ValueError(f"{field} exceeds {max_items} items")
    normalized = tuple(
        _token(value, f"{field}[{index}]", max_length=240)
        for index, value in enumerate(values)
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def _unique_texts(
    values: tuple[str, ...],
    field: str,
    *,
    allow_empty: bool = False,
    max_items: int = 64,
) -> tuple[str, ...]:
    if not values and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    if len(values) > max_items:
        raise ValueError(f"{field} exceeds {max_items} items")
    normalized = tuple(
        _text(value, f"{field}[{index}]", max_length=1000)
        for index, value in enumerate(values)
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def _sha256(value: object, field: str) -> str:
    normalized = _text(value, field, max_length=64).casefold()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


def _sha256_tuple(
    values: tuple[str, ...],
    field: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not values and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    normalized = tuple(
        _sha256(value, f"{field}[{index}]") for index, value in enumerate(values)
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def deterministic_id(prefix: str, payload: object) -> str:
    normalized = _token(prefix, "prefix", max_length=40).replace(".", "_")
    return f"{normalized}_{canonical_digest(payload)[:24]}"


def contract_digest(value: Any) -> str:
    payload = value.to_payload() if hasattr(value, "to_payload") else value
    return canonical_digest(payload)


@dataclass(frozen=True, slots=True)
class StabilizationPolicyV1:
    required_consecutive_violations: int = 1
    minimum_violation_age_seconds: float = 0.0
    minimum_recovery_age_seconds: float = 0.0
    cooldown_after_dispatch_seconds: float = 0.0
    numeric_tolerance: float | None = None
    renotify_interval_seconds: float = 3600.0
    max_dispatches_per_window: int = 1
    window_seconds: float = 3600.0
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported stabilization policy schema_version")
        object.__setattr__(
            self,
            "required_consecutive_violations",
            _positive_int(
                self.required_consecutive_violations,
                "required_consecutive_violations",
            ),
        )
        for field_name in (
            "minimum_violation_age_seconds",
            "minimum_recovery_age_seconds",
            "cooldown_after_dispatch_seconds",
            "renotify_interval_seconds",
            "window_seconds",
        ):
            object.__setattr__(
                self,
                field_name,
                _nonnegative_float(getattr(self, field_name), field_name),
            )
        tolerance = _nonnegative_float(
            self.numeric_tolerance,
            "numeric_tolerance",
            optional=True,
        )
        object.__setattr__(self, "numeric_tolerance", tolerance)
        object.__setattr__(
            self,
            "max_dispatches_per_window",
            _positive_int(
                self.max_dispatches_per_window,
                "max_dispatches_per_window",
            ),
        )
        if self.window_seconds == 0:
            raise ValueError("window_seconds must be greater than zero")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "required_consecutive_violations": self.required_consecutive_violations,
            "minimum_violation_age_seconds": self.minimum_violation_age_seconds,
            "minimum_recovery_age_seconds": self.minimum_recovery_age_seconds,
            "cooldown_after_dispatch_seconds": self.cooldown_after_dispatch_seconds,
            "numeric_tolerance": self.numeric_tolerance,
            "renotify_interval_seconds": self.renotify_interval_seconds,
            "max_dispatches_per_window": self.max_dispatches_per_window,
            "window_seconds": self.window_seconds,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ObjectiveV1:
    objective_id: str
    origin: ObjectiveOrigin
    source_identity: str
    title: str
    description: str
    priority: WorkPriority
    status: ObjectiveStatus
    horizon: str
    constraint_json: dict[str, JSONValue]
    created_at_epoch: float
    updated_at_epoch: float
    generation: int = 1
    deadline_at_epoch: float | None = None
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "objective_id",
            _text(self.objective_id, "objective_id", max_length=240),
        )
        if not isinstance(self.origin, ObjectiveOrigin):
            raise TypeError("origin must be an ObjectiveOrigin")
        if not isinstance(self.priority, WorkPriority):
            raise TypeError("priority must be a WorkPriority")
        if not isinstance(self.status, ObjectiveStatus):
            raise TypeError("status must be an ObjectiveStatus")
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported objective schema_version")
        object.__setattr__(
            self, "source_identity", _text(self.source_identity, "source_identity")
        )
        object.__setattr__(self, "title", _text(self.title, "title", max_length=240))
        object.__setattr__(
            self, "description", _text(self.description, "description", max_length=4000)
        )
        object.__setattr__(self, "horizon", _token(self.horizon, "horizon"))
        object.__setattr__(
            self,
            "constraint_json",
            _json_object(self.constraint_json, "constraint_json"),
        )
        created = _epoch(self.created_at_epoch, "created_at_epoch")
        updated = _epoch(self.updated_at_epoch, "updated_at_epoch")
        if updated < created:
            raise ValueError("updated_at_epoch cannot precede created_at_epoch")
        object.__setattr__(self, "created_at_epoch", created)
        object.__setattr__(self, "updated_at_epoch", updated)
        deadline = _epoch(
            self.deadline_at_epoch,
            "deadline_at_epoch",
            optional=True,
        )
        object.__setattr__(self, "deadline_at_epoch", deadline)
        object.__setattr__(
            self, "generation", _positive_int(self.generation, "generation")
        )

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "objective_id": self.objective_id,
            "origin": self.origin.value,
            "source_identity": self.source_identity,
            "title": self.title,
            "description": self.description,
            "priority": int(self.priority),
            "status": self.status.value,
            "horizon": self.horizon,
            "constraint_json": deepcopy(self.constraint_json),
            "created_at_epoch": self.created_at_epoch,
            "updated_at_epoch": self.updated_at_epoch,
            "generation": self.generation,
            "deadline_at_epoch": self.deadline_at_epoch,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        data = dict(payload)
        data["origin"] = ObjectiveOrigin(data["origin"])
        data["priority"] = WorkPriority(int(data["priority"]))
        data["status"] = ObjectiveStatus(data["status"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class DesiredStateV1:
    desired_state_id: str
    objective_id: str
    target_namespace: str
    target_identity: str
    rule_key: str
    rule_version: int
    expected_json: dict[str, JSONValue]
    required_source_namespaces: tuple[str, ...]
    stabilization_policy: StabilizationPolicyV1
    generation: int
    status: DesiredStateStatus
    provenance_source_identity: str
    created_at_epoch: float
    updated_at_epoch: float
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "desired_state_id",
            _text(self.desired_state_id, "desired_state_id", max_length=240),
        )
        object.__setattr__(
            self,
            "objective_id",
            _text(self.objective_id, "objective_id", max_length=240),
        )
        object.__setattr__(
            self,
            "target_namespace",
            _token(self.target_namespace, "target_namespace"),
        )
        object.__setattr__(
            self,
            "target_identity",
            _text(self.target_identity, "target_identity", max_length=500),
        )
        object.__setattr__(self, "rule_key", _token(self.rule_key, "rule_key"))
        object.__setattr__(
            self, "rule_version", _positive_int(self.rule_version, "rule_version")
        )
        object.__setattr__(
            self, "expected_json", _json_object(self.expected_json, "expected_json")
        )
        object.__setattr__(
            self,
            "required_source_namespaces",
            _unique_tokens(
                self.required_source_namespaces,
                "required_source_namespaces",
            ),
        )
        if not isinstance(self.stabilization_policy, StabilizationPolicyV1):
            raise TypeError("stabilization_policy must be a StabilizationPolicyV1")
        object.__setattr__(
            self, "generation", _positive_int(self.generation, "generation")
        )
        if not isinstance(self.status, DesiredStateStatus):
            raise TypeError("status must be a DesiredStateStatus")
        object.__setattr__(
            self,
            "provenance_source_identity",
            _text(
                self.provenance_source_identity,
                "provenance_source_identity",
            ),
        )
        created = _epoch(self.created_at_epoch, "created_at_epoch")
        updated = _epoch(self.updated_at_epoch, "updated_at_epoch")
        if updated < created:
            raise ValueError("updated_at_epoch cannot precede created_at_epoch")
        object.__setattr__(self, "created_at_epoch", created)
        object.__setattr__(self, "updated_at_epoch", updated)
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported desired-state schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "desired_state_id": self.desired_state_id,
            "objective_id": self.objective_id,
            "target_namespace": self.target_namespace,
            "target_identity": self.target_identity,
            "rule_key": self.rule_key,
            "rule_version": self.rule_version,
            "expected_json": deepcopy(self.expected_json),
            "required_source_namespaces": list(self.required_source_namespaces),
            "stabilization_policy": self.stabilization_policy.to_payload(),
            "generation": self.generation,
            "status": self.status.value,
            "provenance_source_identity": self.provenance_source_identity,
            "created_at_epoch": self.created_at_epoch,
            "updated_at_epoch": self.updated_at_epoch,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        data = dict(payload)
        data["required_source_namespaces"] = tuple(data["required_source_namespaces"])
        data["stabilization_policy"] = StabilizationPolicyV1.from_payload(
            dict(data["stabilization_policy"])
        )
        data["status"] = DesiredStateStatus(data["status"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class AutonomyFindingV1:
    finding_id: str
    desired_state_id: str
    desired_generation: int
    target_namespace: str
    target_identity: str
    finding_kind: str
    rule_key: str
    rule_version: int
    status: FindingStatus
    latest_snapshot_digest: str
    first_seen_epoch: float
    last_seen_epoch: float
    violation_count: int
    reason_codes: tuple[str, ...]
    supporting_fact_digests: tuple[str, ...]
    version: int = 1
    root_finding_id: str | None = None
    suppression_finding_id: str | None = None
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in ("finding_id", "desired_state_id"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name, max_length=240),
            )
        object.__setattr__(
            self,
            "desired_generation",
            _positive_int(self.desired_generation, "desired_generation"),
        )
        object.__setattr__(
            self,
            "target_namespace",
            _token(self.target_namespace, "target_namespace"),
        )
        object.__setattr__(
            self,
            "target_identity",
            _text(self.target_identity, "target_identity", max_length=500),
        )
        object.__setattr__(
            self, "finding_kind", _token(self.finding_kind, "finding_kind")
        )
        object.__setattr__(self, "rule_key", _token(self.rule_key, "rule_key"))
        object.__setattr__(
            self, "rule_version", _positive_int(self.rule_version, "rule_version")
        )
        if not isinstance(self.status, FindingStatus):
            raise TypeError("status must be a FindingStatus")
        object.__setattr__(
            self,
            "latest_snapshot_digest",
            _sha256(self.latest_snapshot_digest, "latest_snapshot_digest"),
        )
        first_seen = _epoch(self.first_seen_epoch, "first_seen_epoch")
        last_seen = _epoch(self.last_seen_epoch, "last_seen_epoch")
        if last_seen < first_seen:
            raise ValueError("last_seen_epoch cannot precede first_seen_epoch")
        object.__setattr__(self, "first_seen_epoch", first_seen)
        object.__setattr__(self, "last_seen_epoch", last_seen)
        object.__setattr__(
            self,
            "violation_count",
            _positive_int(self.violation_count, "violation_count"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_tokens(self.reason_codes, "reason_codes"),
        )
        object.__setattr__(
            self,
            "supporting_fact_digests",
            _sha256_tuple(
                self.supporting_fact_digests,
                "supporting_fact_digests",
                allow_empty=True,
            ),
        )
        object.__setattr__(self, "version", _positive_int(self.version, "version"))
        object.__setattr__(
            self,
            "root_finding_id",
            _optional_text(
                self.root_finding_id,
                "root_finding_id",
                max_length=240,
            ),
        )
        object.__setattr__(
            self,
            "suppression_finding_id",
            _optional_text(
                self.suppression_finding_id,
                "suppression_finding_id",
                max_length=240,
            ),
        )
        if self.root_finding_id == self.finding_id:
            raise ValueError("root_finding_id cannot self-reference")
        if self.suppression_finding_id == self.finding_id:
            raise ValueError("suppression_finding_id cannot self-reference")
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported finding schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "finding_id": self.finding_id,
            "desired_state_id": self.desired_state_id,
            "desired_generation": self.desired_generation,
            "target_namespace": self.target_namespace,
            "target_identity": self.target_identity,
            "finding_kind": self.finding_kind,
            "rule_key": self.rule_key,
            "rule_version": self.rule_version,
            "status": self.status.value,
            "latest_snapshot_digest": self.latest_snapshot_digest,
            "first_seen_epoch": self.first_seen_epoch,
            "last_seen_epoch": self.last_seen_epoch,
            "violation_count": self.violation_count,
            "reason_codes": list(self.reason_codes),
            "supporting_fact_digests": list(self.supporting_fact_digests),
            "version": self.version,
            "root_finding_id": self.root_finding_id,
            "suppression_finding_id": self.suppression_finding_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        data = dict(payload)
        data["status"] = FindingStatus(data["status"])
        data["reason_codes"] = tuple(data["reason_codes"])
        data["supporting_fact_digests"] = tuple(data["supporting_fact_digests"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class AutonomyFindingEventV1:
    event_id: str
    finding_id: str
    event_key: str
    kind: str
    detail_json: dict[str, JSONValue]
    created_at_epoch: float
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _text(self.event_id, "event_id"))
        object.__setattr__(
            self, "finding_id", _text(self.finding_id, "finding_id", max_length=240)
        )
        object.__setattr__(self, "event_key", _text(self.event_key, "event_key"))
        object.__setattr__(self, "kind", _token(self.kind, "kind"))
        object.__setattr__(
            self, "detail_json", _json_object(self.detail_json, "detail_json")
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, "created_at_epoch"),
        )
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported finding-event schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "event_id": self.event_id,
            "finding_id": self.finding_id,
            "event_key": self.event_key,
            "kind": self.kind,
            "detail_json": deepcopy(self.detail_json),
            "created_at_epoch": self.created_at_epoch,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ActionCandidateV1:
    candidate_id: str
    finding_id: str
    desired_state_id: str
    desired_generation: int
    action_kind: ActionKind
    resolver_key: str
    resolver_version: int
    expected_effect: str
    target_namespace: str
    target_identity: str
    snapshot_digest: str
    reversibility_class: str
    resource_class: str
    cost_class: str
    risk_json: dict[str, JSONValue]
    dependencies: tuple[str, ...]
    mode: AutonomyMode
    policy_reason_codes: tuple[str, ...]
    created_at_epoch: float
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in ("candidate_id", "finding_id", "desired_state_id"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name, max_length=240),
            )
        object.__setattr__(
            self,
            "desired_generation",
            _positive_int(self.desired_generation, "desired_generation"),
        )
        if not isinstance(self.action_kind, ActionKind):
            raise TypeError("action_kind must be an ActionKind")
        object.__setattr__(
            self, "resolver_key", _token(self.resolver_key, "resolver_key")
        )
        object.__setattr__(
            self,
            "resolver_version",
            _positive_int(self.resolver_version, "resolver_version"),
        )
        object.__setattr__(
            self,
            "expected_effect",
            _text(self.expected_effect, "expected_effect", max_length=2000),
        )
        object.__setattr__(
            self,
            "target_namespace",
            _token(self.target_namespace, "target_namespace"),
        )
        object.__setattr__(
            self,
            "target_identity",
            _text(self.target_identity, "target_identity", max_length=500),
        )
        object.__setattr__(
            self, "snapshot_digest", _sha256(self.snapshot_digest, "snapshot_digest")
        )
        for field_name in (
            "reversibility_class",
            "resource_class",
            "cost_class",
        ):
            object.__setattr__(
                self,
                field_name,
                _token(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "risk_json", _json_object(self.risk_json, "risk_json"))
        object.__setattr__(
            self,
            "dependencies",
            _unique_texts(
                self.dependencies,
                "dependencies",
                allow_empty=True,
            ),
        )
        if not isinstance(self.mode, AutonomyMode):
            raise TypeError("mode must be an AutonomyMode")
        object.__setattr__(
            self,
            "policy_reason_codes",
            _unique_tokens(
                self.policy_reason_codes,
                "policy_reason_codes",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, "created_at_epoch"),
        )
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported action-candidate schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "candidate_id": self.candidate_id,
            "finding_id": self.finding_id,
            "desired_state_id": self.desired_state_id,
            "desired_generation": self.desired_generation,
            "action_kind": self.action_kind.value,
            "resolver_key": self.resolver_key,
            "resolver_version": self.resolver_version,
            "expected_effect": self.expected_effect,
            "target_namespace": self.target_namespace,
            "target_identity": self.target_identity,
            "snapshot_digest": self.snapshot_digest,
            "reversibility_class": self.reversibility_class,
            "resource_class": self.resource_class,
            "cost_class": self.cost_class,
            "risk_json": deepcopy(self.risk_json),
            "dependencies": list(self.dependencies),
            "mode": self.mode.value,
            "policy_reason_codes": list(self.policy_reason_codes),
            "created_at_epoch": self.created_at_epoch,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        data = dict(payload)
        data["action_kind"] = ActionKind(data["action_kind"])
        data["dependencies"] = tuple(data["dependencies"])
        data["mode"] = AutonomyMode(data["mode"])
        data["policy_reason_codes"] = tuple(data["policy_reason_codes"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class DispatchIntentV1:
    dispatch_intent_id: str
    candidate_id: str
    dispatch_role: str
    action_kind: ActionKind
    disposition: CandidateDisposition
    source_identity: str
    reason_codes: tuple[str, ...]
    created_at_epoch: float
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dispatch_intent_id",
            _text(
                self.dispatch_intent_id,
                "dispatch_intent_id",
                max_length=240,
            ),
        )
        object.__setattr__(
            self,
            "candidate_id",
            _text(self.candidate_id, "candidate_id", max_length=240),
        )
        object.__setattr__(
            self,
            "dispatch_role",
            _token(self.dispatch_role, "dispatch_role"),
        )
        if not isinstance(self.action_kind, ActionKind):
            raise TypeError("action_kind must be an ActionKind")
        if not isinstance(self.disposition, CandidateDisposition):
            raise TypeError("disposition must be a CandidateDisposition")
        object.__setattr__(
            self,
            "source_identity",
            _text(self.source_identity, "source_identity", max_length=500),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_tokens(self.reason_codes, "reason_codes"),
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, "created_at_epoch"),
        )
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported dispatch-intent schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "dispatch_intent_id": self.dispatch_intent_id,
            "candidate_id": self.candidate_id,
            "dispatch_role": self.dispatch_role,
            "action_kind": self.action_kind.value,
            "disposition": self.disposition.value,
            "source_identity": self.source_identity,
            "reason_codes": list(self.reason_codes),
            "created_at_epoch": self.created_at_epoch,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        data = dict(payload)
        data["action_kind"] = ActionKind(data["action_kind"])
        data["disposition"] = CandidateDisposition(data["disposition"])
        data["reason_codes"] = tuple(data["reason_codes"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class AutonomyDispatchLinkV1:
    dispatch_link_id: str
    candidate_id: str
    dispatch_role: str
    downstream_kind: str
    downstream_id: str
    source_identity: str
    mode: AutonomyMode
    disposition: CandidateDisposition
    bridge_contract_digest: str
    reason_codes: tuple[str, ...]
    created_at_epoch: float
    downstream_version: str | None = None
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in ("dispatch_link_id", "candidate_id"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name, max_length=240),
            )
        object.__setattr__(
            self,
            "dispatch_role",
            _token(self.dispatch_role, "dispatch_role"),
        )
        object.__setattr__(
            self,
            "downstream_kind",
            _token(self.downstream_kind, "downstream_kind"),
        )
        object.__setattr__(
            self,
            "downstream_id",
            _text(self.downstream_id, "downstream_id", max_length=500),
        )
        object.__setattr__(
            self,
            "source_identity",
            _text(self.source_identity, "source_identity", max_length=1000),
        )
        if not isinstance(self.mode, AutonomyMode):
            raise TypeError("mode must be an AutonomyMode")
        if not isinstance(self.disposition, CandidateDisposition):
            raise TypeError("disposition must be a CandidateDisposition")
        object.__setattr__(
            self,
            "bridge_contract_digest",
            _sha256(
                self.bridge_contract_digest,
                "bridge_contract_digest",
            ),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_tokens(self.reason_codes, "reason_codes"),
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, "created_at_epoch"),
        )
        object.__setattr__(
            self,
            "downstream_version",
            _optional_text(
                self.downstream_version,
                "downstream_version",
                max_length=500,
            ),
        )
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported dispatch-link schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "dispatch_link_id": self.dispatch_link_id,
            "candidate_id": self.candidate_id,
            "dispatch_role": self.dispatch_role,
            "downstream_kind": self.downstream_kind,
            "downstream_id": self.downstream_id,
            "source_identity": self.source_identity,
            "mode": self.mode.value,
            "disposition": self.disposition.value,
            "bridge_contract_digest": self.bridge_contract_digest,
            "reason_codes": list(self.reason_codes),
            "created_at_epoch": self.created_at_epoch,
            "downstream_version": self.downstream_version,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        data = dict(payload)
        data["mode"] = AutonomyMode(data["mode"])
        data["disposition"] = CandidateDisposition(data["disposition"])
        data["reason_codes"] = tuple(data["reason_codes"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class AutonomyDispatchLinkV1:
    dispatch_link_id: str
    candidate_id: str
    dispatch_role: str
    downstream_kind: str
    downstream_id: str
    source_identity: str
    created_at_epoch: float
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in ("dispatch_link_id", "candidate_id"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name, max_length=240),
            )
        object.__setattr__(
            self,
            "dispatch_role",
            _token(self.dispatch_role, "dispatch_role"),
        )
        object.__setattr__(
            self,
            "downstream_kind",
            _token(self.downstream_kind, "downstream_kind"),
        )
        object.__setattr__(
            self,
            "downstream_id",
            _text(self.downstream_id, "downstream_id", max_length=500),
        )
        object.__setattr__(
            self,
            "source_identity",
            _text(self.source_identity, "source_identity", max_length=500),
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, "created_at_epoch"),
        )
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported dispatch-link schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "dispatch_link_id": self.dispatch_link_id,
            "candidate_id": self.candidate_id,
            "dispatch_role": self.dispatch_role,
            "downstream_kind": self.downstream_kind,
            "downstream_id": self.downstream_id,
            "source_identity": self.source_identity,
            "created_at_epoch": self.created_at_epoch,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class OwnerAttentionItemV1:
    attention_id: str
    fingerprint: str
    group_key: str
    objective_id: str
    finding_id: str
    priority: WorkPriority
    reason_codes: tuple[str, ...]
    question: str
    option_metadata_json: dict[str, JSONValue]
    consequence_of_waiting: str
    first_occurrence_epoch: float
    last_occurrence_epoch: float
    status: AttentionStatus
    version: int = 1
    candidate_id: str | None = None
    root_attention_id: str | None = None
    next_renotify_epoch: float | None = None
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "attention_id",
            "fingerprint",
            "group_key",
            "objective_id",
            "finding_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name, max_length=500),
            )
        if not isinstance(self.priority, WorkPriority):
            raise TypeError("priority must be a WorkPriority")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_tokens(self.reason_codes, "reason_codes"),
        )
        object.__setattr__(
            self, "question", _text(self.question, "question", max_length=2000)
        )
        object.__setattr__(
            self,
            "option_metadata_json",
            _json_object(self.option_metadata_json, "option_metadata_json"),
        )
        object.__setattr__(
            self,
            "consequence_of_waiting",
            _text(
                self.consequence_of_waiting,
                "consequence_of_waiting",
                max_length=2000,
            ),
        )
        first = _epoch(self.first_occurrence_epoch, "first_occurrence_epoch")
        last = _epoch(self.last_occurrence_epoch, "last_occurrence_epoch")
        if last < first:
            raise ValueError(
                "last_occurrence_epoch cannot precede first_occurrence_epoch"
            )
        object.__setattr__(self, "first_occurrence_epoch", first)
        object.__setattr__(self, "last_occurrence_epoch", last)
        if not isinstance(self.status, AttentionStatus):
            raise TypeError("status must be an AttentionStatus")
        object.__setattr__(self, "version", _positive_int(self.version, "version"))
        object.__setattr__(
            self,
            "candidate_id",
            _optional_text(self.candidate_id, "candidate_id", max_length=240),
        )
        object.__setattr__(
            self,
            "root_attention_id",
            _optional_text(
                self.root_attention_id,
                "root_attention_id",
                max_length=240,
            ),
        )
        if self.root_attention_id == self.attention_id:
            raise ValueError("root_attention_id cannot self-reference")
        object.__setattr__(
            self,
            "next_renotify_epoch",
            _epoch(
                self.next_renotify_epoch,
                "next_renotify_epoch",
                optional=True,
            ),
        )
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported owner-attention schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "attention_id": self.attention_id,
            "fingerprint": self.fingerprint,
            "group_key": self.group_key,
            "objective_id": self.objective_id,
            "finding_id": self.finding_id,
            "priority": int(self.priority),
            "reason_codes": list(self.reason_codes),
            "question": self.question,
            "option_metadata_json": deepcopy(self.option_metadata_json),
            "consequence_of_waiting": self.consequence_of_waiting,
            "first_occurrence_epoch": self.first_occurrence_epoch,
            "last_occurrence_epoch": self.last_occurrence_epoch,
            "status": self.status.value,
            "version": self.version,
            "candidate_id": self.candidate_id,
            "root_attention_id": self.root_attention_id,
            "next_renotify_epoch": self.next_renotify_epoch,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        data = dict(payload)
        data["priority"] = WorkPriority(int(data["priority"]))
        data["reason_codes"] = tuple(data["reason_codes"])
        data["status"] = AttentionStatus(data["status"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class OwnerAttentionEventV1:
    event_id: str
    attention_id: str
    event_key: str
    kind: str
    detail_json: dict[str, JSONValue]
    created_at_epoch: float
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _text(self.event_id, "event_id"))
        object.__setattr__(
            self,
            "attention_id",
            _text(self.attention_id, "attention_id", max_length=240),
        )
        object.__setattr__(self, "event_key", _text(self.event_key, "event_key"))
        object.__setattr__(self, "kind", _token(self.kind, "kind"))
        object.__setattr__(
            self, "detail_json", _json_object(self.detail_json, "detail_json")
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, "created_at_epoch"),
        )
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported attention-event schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "event_id": self.event_id,
            "attention_id": self.attention_id,
            "event_key": self.event_key,
            "kind": self.kind,
            "detail_json": deepcopy(self.detail_json),
            "created_at_epoch": self.created_at_epoch,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class AutonomyOutcomeRecordV1:
    outcome_record_id: str
    candidate_id: str
    dispatch_link_id: str
    downstream_source_kind: str
    downstream_source_id: str
    verification_references: tuple[str, ...]
    recorded_at_epoch: float
    downstream_source_version: str | None = None
    terminal_status_ref: str | None = None
    phase10_engineering_outcome_id: str | None = None
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "outcome_record_id",
            "candidate_id",
            "dispatch_link_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name, max_length=240),
            )
        object.__setattr__(
            self,
            "downstream_source_kind",
            _token(self.downstream_source_kind, "downstream_source_kind"),
        )
        object.__setattr__(
            self,
            "downstream_source_id",
            _text(
                self.downstream_source_id,
                "downstream_source_id",
                max_length=500,
            ),
        )
        object.__setattr__(
            self,
            "verification_references",
            _unique_texts(
                self.verification_references,
                "verification_references",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "recorded_at_epoch",
            _epoch(self.recorded_at_epoch, "recorded_at_epoch"),
        )
        for field_name in (
            "downstream_source_version",
            "terminal_status_ref",
            "phase10_engineering_outcome_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_text(
                    getattr(self, field_name),
                    field_name,
                    max_length=1000,
                ),
            )
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported outcome-record schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "outcome_record_id": self.outcome_record_id,
            "candidate_id": self.candidate_id,
            "dispatch_link_id": self.dispatch_link_id,
            "downstream_source_kind": self.downstream_source_kind,
            "downstream_source_id": self.downstream_source_id,
            "verification_references": list(self.verification_references),
            "recorded_at_epoch": self.recorded_at_epoch,
            "downstream_source_version": self.downstream_source_version,
            "terminal_status_ref": self.terminal_status_ref,
            "phase10_engineering_outcome_id": self.phase10_engineering_outcome_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        data = dict(payload)
        data["verification_references"] = tuple(data["verification_references"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class ReconcileRunV1:
    reconcile_run_id: str
    request_token: str
    trigger: ReconcileTrigger
    started_at_epoch: float
    desired_generation_digest: str
    status: ReconcileStatus
    ended_at_epoch: float | None = None
    snapshot_digest: str | None = None
    handled_token: str | None = None
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reconcile_run_id",
            _text(self.reconcile_run_id, "reconcile_run_id", max_length=240),
        )
        object.__setattr__(
            self, "request_token", _text(self.request_token, "request_token")
        )
        if not isinstance(self.trigger, ReconcileTrigger):
            raise TypeError("trigger must be a ReconcileTrigger")
        object.__setattr__(
            self,
            "started_at_epoch",
            _epoch(self.started_at_epoch, "started_at_epoch"),
        )
        object.__setattr__(
            self,
            "desired_generation_digest",
            _sha256(
                self.desired_generation_digest,
                "desired_generation_digest",
            ),
        )
        if not isinstance(self.status, ReconcileStatus):
            raise TypeError("status must be a ReconcileStatus")
        ended = _epoch(self.ended_at_epoch, "ended_at_epoch", optional=True)
        if ended is not None and ended < self.started_at_epoch:
            raise ValueError("ended_at_epoch cannot precede started_at_epoch")
        object.__setattr__(self, "ended_at_epoch", ended)
        snapshot = self.snapshot_digest
        if snapshot is not None:
            snapshot = _sha256(snapshot, "snapshot_digest")
        object.__setattr__(self, "snapshot_digest", snapshot)
        object.__setattr__(
            self,
            "handled_token",
            _optional_text(self.handled_token, "handled_token"),
        )
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported reconcile-run schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "reconcile_run_id": self.reconcile_run_id,
            "request_token": self.request_token,
            "trigger": self.trigger.value,
            "started_at_epoch": self.started_at_epoch,
            "desired_generation_digest": self.desired_generation_digest,
            "status": self.status.value,
            "ended_at_epoch": self.ended_at_epoch,
            "snapshot_digest": self.snapshot_digest,
            "handled_token": self.handled_token,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        data = dict(payload)
        data["trigger"] = ReconcileTrigger(data["trigger"])
        data["status"] = ReconcileStatus(data["status"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class AutonomyBudgetPolicyV1:
    policy_id: str
    max_concurrent_autonomous_work_items: int
    max_new_autonomous_work_items_per_window: int
    max_active_candidates_per_objective: int
    max_repeat_dispatches_per_finding_window: int
    max_owner_attention_notifications_per_window: int
    window_seconds: float
    provider_model_work_ceiling: float | None = None
    schema_version: str = AUTONOMY_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        for field_name in (
            "max_concurrent_autonomous_work_items",
            "max_new_autonomous_work_items_per_window",
            "max_active_candidates_per_objective",
            "max_repeat_dispatches_per_finding_window",
            "max_owner_attention_notifications_per_window",
        ):
            object.__setattr__(
                self,
                field_name,
                _positive_int(getattr(self, field_name), field_name),
            )
        window = _nonnegative_float(self.window_seconds, "window_seconds")
        if window == 0:
            raise ValueError("window_seconds must be greater than zero")
        object.__setattr__(self, "window_seconds", window)
        object.__setattr__(
            self,
            "provider_model_work_ceiling",
            _nonnegative_float(
                self.provider_model_work_ceiling,
                "provider_model_work_ceiling",
                optional=True,
            ),
        )
        if self.schema_version != AUTONOMY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported budget-policy schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "policy_id": self.policy_id,
            "max_concurrent_autonomous_work_items": (
                self.max_concurrent_autonomous_work_items
            ),
            "max_new_autonomous_work_items_per_window": (
                self.max_new_autonomous_work_items_per_window
            ),
            "max_active_candidates_per_objective": (
                self.max_active_candidates_per_objective
            ),
            "max_repeat_dispatches_per_finding_window": (
                self.max_repeat_dispatches_per_finding_window
            ),
            "max_owner_attention_notifications_per_window": (
                self.max_owner_attention_notifications_per_window
            ),
            "window_seconds": self.window_seconds,
            "provider_model_work_ceiling": self.provider_model_work_ceiling,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        return cls(**payload)


def finding_id_for(
    desired_state: DesiredStateV1,
    *,
    finding_kind: str,
) -> str:
    return deterministic_id(
        "finding",
        {
            "desired_state_id": desired_state.desired_state_id,
            "target_namespace": desired_state.target_namespace,
            "target_identity": desired_state.target_identity,
            "finding_kind": _token(finding_kind, "finding_kind"),
            "rule_version": desired_state.rule_version,
        },
    )


def candidate_id_for(
    finding: AutonomyFindingV1,
    *,
    action_kind: ActionKind,
    resolver_key: str,
    resolver_version: int,
) -> str:
    return deterministic_id(
        "candidate",
        {
            "finding_id": finding.finding_id,
            "desired_state_id": finding.desired_state_id,
            "desired_generation": finding.desired_generation,
            "action_kind": action_kind.value,
            "resolver_key": _token(resolver_key, "resolver_key"),
            "resolver_version": _positive_int(
                resolver_version,
                "resolver_version",
            ),
        },
    )
