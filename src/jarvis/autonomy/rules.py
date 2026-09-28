"""Deterministic DesiredState evaluation and stabilization for Phase 10A."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from jarvis.engineering_knowledge.canonical import JSONValue
from jarvis.engineering_substrate.canonical import canonical_digest

from .models import DesiredStateStatus, DesiredStateV1, StabilizationPolicyV1
from .system_state import SystemStateFactV1, SystemStateSnapshotV1

DESIRED_STATE_EVALUATION_SCHEMA_VERSION = "1"


def _token(value: object, field: str, *, max_length: int = 200) -> str:
    normalized = str(value).strip().casefold()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


def _text(value: object, field: str, *, max_length: int = 500) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


def _epoch(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


def _optional_epoch(value: object | None, field: str) -> float | None:
    return None if value is None else _epoch(value, field)


def _unique_tokens(
    values: tuple[str, ...] | list[str],
    field: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not values and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    normalized = tuple(
        _token(value, f"{field}[{index}]") for index, value in enumerate(values)
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def _sha256_tuple(
    values: tuple[str, ...] | list[str],
    field: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not values and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    normalized = []
    for index, value in enumerate(values):
        text = _text(value, f"{field}[{index}]", max_length=64).casefold()
        if len(text) != 64 or any(
            character not in "0123456789abcdef" for character in text
        ):
            raise ValueError(f"{field}[{index}] must be a lowercase SHA-256 digest")
        normalized.append(text)
    result = tuple(normalized)
    if len(set(result)) != len(result):
        raise ValueError(f"{field} must not contain duplicates")
    return result


class DesiredStateEvaluationStatus(StrEnum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNKNOWN = "unknown"
    STABILIZING = "stabilizing"


@dataclass(frozen=True, slots=True)
class DesiredStateEvaluationV1:
    desired_state_id: str
    desired_generation: int
    rule_key: str
    rule_version: int
    status: DesiredStateEvaluationStatus
    snapshot_digest: str
    reason_codes: tuple[str, ...]
    supporting_fact_digests: tuple[str, ...]
    evaluated_at_epoch: float
    first_violation_at_epoch: float | None = None
    last_violation_at_epoch: float | None = None
    first_recovery_at_epoch: float | None = None
    consecutive_violations: int = 0
    cooldown_until_epoch: float | None = None
    schema_version: str = DESIRED_STATE_EVALUATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "desired_state_id",
            _text(self.desired_state_id, "desired_state_id", max_length=240),
        )
        object.__setattr__(
            self,
            "desired_generation",
            _positive_int(self.desired_generation, "desired_generation"),
        )
        object.__setattr__(self, "rule_key", _token(self.rule_key, "rule_key"))
        object.__setattr__(
            self,
            "rule_version",
            _positive_int(self.rule_version, "rule_version"),
        )
        if not isinstance(self.status, DesiredStateEvaluationStatus):
            raise TypeError("status must be a DesiredStateEvaluationStatus")
        digest = _text(
            self.snapshot_digest, "snapshot_digest", max_length=64
        ).casefold()
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError("snapshot_digest must be a lowercase SHA-256 digest")
        object.__setattr__(self, "snapshot_digest", digest)
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
        object.__setattr__(
            self,
            "evaluated_at_epoch",
            _epoch(self.evaluated_at_epoch, "evaluated_at_epoch"),
        )
        for field_name in (
            "first_violation_at_epoch",
            "last_violation_at_epoch",
            "first_recovery_at_epoch",
            "cooldown_until_epoch",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_epoch(getattr(self, field_name), field_name),
            )
        if (
            self.first_violation_at_epoch is not None
            and self.last_violation_at_epoch is not None
            and self.last_violation_at_epoch < self.first_violation_at_epoch
        ):
            raise ValueError(
                "last_violation_at_epoch cannot precede first_violation_at_epoch"
            )
        if isinstance(self.consecutive_violations, bool) or not isinstance(
            self.consecutive_violations,
            int,
        ):
            raise TypeError("consecutive_violations must be an integer")
        if self.consecutive_violations < 0:
            raise ValueError("consecutive_violations must not be negative")
        if self.schema_version != DESIRED_STATE_EVALUATION_SCHEMA_VERSION:
            raise ValueError("unsupported DesiredState evaluation schema_version")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "desired_state_id": self.desired_state_id,
            "desired_generation": self.desired_generation,
            "rule_key": self.rule_key,
            "rule_version": self.rule_version,
            "status": self.status.value,
            "snapshot_digest": self.snapshot_digest,
            "reason_codes": list(self.reason_codes),
            "supporting_fact_digests": list(self.supporting_fact_digests),
            "evaluated_at_epoch": self.evaluated_at_epoch,
            "first_violation_at_epoch": self.first_violation_at_epoch,
            "last_violation_at_epoch": self.last_violation_at_epoch,
            "first_recovery_at_epoch": self.first_recovery_at_epoch,
            "consecutive_violations": self.consecutive_violations,
            "cooldown_until_epoch": self.cooldown_until_epoch,
            "schema_version": self.schema_version,
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_payload())


@dataclass(frozen=True, slots=True)
class StabilizationCursorV1:
    desired_state_id: str
    desired_generation: int
    rule_key: str
    rule_version: int
    last_snapshot_digest: str
    last_observation_status: DesiredStateEvaluationStatus
    evaluated_at_epoch: float
    consecutive_violations: int = 0
    first_violation_at_epoch: float | None = None
    last_violation_at_epoch: float | None = None
    first_recovery_at_epoch: float | None = None
    violation_active: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "desired_state_id",
            _text(self.desired_state_id, "desired_state_id", max_length=240),
        )
        object.__setattr__(
            self,
            "desired_generation",
            _positive_int(self.desired_generation, "desired_generation"),
        )
        object.__setattr__(self, "rule_key", _token(self.rule_key, "rule_key"))
        object.__setattr__(
            self,
            "rule_version",
            _positive_int(self.rule_version, "rule_version"),
        )
        digest = _text(
            self.last_snapshot_digest,
            "last_snapshot_digest",
            max_length=64,
        ).casefold()
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError("last_snapshot_digest must be a SHA-256 digest")
        object.__setattr__(self, "last_snapshot_digest", digest)
        if self.last_observation_status not in {
            DesiredStateEvaluationStatus.SATISFIED,
            DesiredStateEvaluationStatus.VIOLATED,
            DesiredStateEvaluationStatus.UNKNOWN,
        }:
            raise ValueError(
                "last_observation_status must be a raw deterministic observation"
            )
        object.__setattr__(
            self,
            "evaluated_at_epoch",
            _epoch(self.evaluated_at_epoch, "evaluated_at_epoch"),
        )
        if isinstance(self.consecutive_violations, bool) or not isinstance(
            self.consecutive_violations,
            int,
        ):
            raise TypeError("consecutive_violations must be an integer")
        if self.consecutive_violations < 0:
            raise ValueError("consecutive_violations must not be negative")
        for field_name in (
            "first_violation_at_epoch",
            "last_violation_at_epoch",
            "first_recovery_at_epoch",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_epoch(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class StabilizationDecisionV1:
    evaluation: DesiredStateEvaluationV1
    cursor: StabilizationCursorV1
    cooldown_active: bool

    def __post_init__(self) -> None:
        if not isinstance(self.evaluation, DesiredStateEvaluationV1):
            raise TypeError("evaluation must be a DesiredStateEvaluationV1")
        if not isinstance(self.cursor, StabilizationCursorV1):
            raise TypeError("cursor must be a StabilizationCursorV1")
        if (
            self.evaluation.desired_state_id,
            self.evaluation.desired_generation,
            self.evaluation.rule_key,
            self.evaluation.rule_version,
        ) != (
            self.cursor.desired_state_id,
            self.cursor.desired_generation,
            self.cursor.rule_key,
            self.cursor.rule_version,
        ):
            raise ValueError("stabilization decision identity mismatch")


class DesiredStateRule(Protocol):
    rule_key: str
    rule_version: int
    target_namespace: str
    required_source_namespaces: tuple[str, ...]
    supports_numeric_tolerance: bool

    def validate_expected(self, expected: dict[str, JSONValue]) -> None: ...

    def evaluate(
        self,
        desired: DesiredStateV1,
        snapshot: SystemStateSnapshotV1,
    ) -> DesiredStateEvaluationV1: ...


class DesiredStateRuleError(RuntimeError):
    pass


class UnknownDesiredStateRuleError(DesiredStateRuleError):
    pass


class DuplicateDesiredStateRuleError(DesiredStateRuleError):
    pass


class DesiredStateRuleContractError(DesiredStateRuleError):
    pass


def numeric_within_tolerance(
    actual: float,
    expected: float,
    tolerance: float,
) -> bool:
    """Deterministic absolute deadband hook for future numeric DesiredState rules."""

    values = (actual, expected, tolerance)
    if any(
        isinstance(value, bool) or not isinstance(value, int | float)
        for value in values
    ):
        raise TypeError("numeric tolerance inputs must be numeric")
    normalized = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in normalized):
        raise ValueError("numeric tolerance inputs must be finite")
    if normalized[2] < 0:
        raise ValueError("numeric tolerance must not be negative")
    return abs(normalized[0] - normalized[1]) <= normalized[2]


def cooldown_until_epoch(
    last_dispatch_at_epoch: float | None,
    policy: StabilizationPolicyV1,
) -> float | None:
    if not isinstance(policy, StabilizationPolicyV1):
        raise TypeError("policy must be a StabilizationPolicyV1")
    if last_dispatch_at_epoch is None:
        return None
    dispatched = _epoch(last_dispatch_at_epoch, "last_dispatch_at_epoch")
    return dispatched + policy.cooldown_after_dispatch_seconds


def cooldown_is_active(
    *,
    now_epoch: float,
    last_dispatch_at_epoch: float | None,
    policy: StabilizationPolicyV1,
) -> bool:
    now = _epoch(now_epoch, "now_epoch")
    until = cooldown_until_epoch(last_dispatch_at_epoch, policy)
    return until is not None and now < until


def _unknown_evaluation(
    desired: DesiredStateV1,
    snapshot: SystemStateSnapshotV1,
    *,
    reason_codes: tuple[str, ...],
    supporting_facts: tuple[SystemStateFactV1, ...] = (),
) -> DesiredStateEvaluationV1:
    return DesiredStateEvaluationV1(
        desired_state_id=desired.desired_state_id,
        desired_generation=desired.generation,
        rule_key=desired.rule_key,
        rule_version=desired.rule_version,
        status=DesiredStateEvaluationStatus.UNKNOWN,
        snapshot_digest=snapshot.snapshot_digest,
        reason_codes=reason_codes,
        supporting_fact_digests=tuple(fact.digest for fact in supporting_facts),
        evaluated_at_epoch=snapshot.ended_at_epoch,
    )


def _raw_evaluation(
    desired: DesiredStateV1,
    snapshot: SystemStateSnapshotV1,
    *,
    status: DesiredStateEvaluationStatus,
    reason_codes: tuple[str, ...],
    supporting_facts: tuple[SystemStateFactV1, ...],
) -> DesiredStateEvaluationV1:
    if status not in {
        DesiredStateEvaluationStatus.SATISFIED,
        DesiredStateEvaluationStatus.VIOLATED,
    }:
        raise ValueError("raw deterministic rule status must be SATISFIED or VIOLATED")
    return DesiredStateEvaluationV1(
        desired_state_id=desired.desired_state_id,
        desired_generation=desired.generation,
        rule_key=desired.rule_key,
        rule_version=desired.rule_version,
        status=status,
        snapshot_digest=snapshot.snapshot_digest,
        reason_codes=reason_codes,
        supporting_fact_digests=tuple(fact.digest for fact in supporting_facts),
        evaluated_at_epoch=snapshot.ended_at_epoch,
    )


def _required_source_problem(
    desired: DesiredStateV1,
    snapshot: SystemStateSnapshotV1,
    required: tuple[str, ...],
) -> tuple[str, ...]:
    required_set = set(required)
    declared = set(desired.required_source_namespaces)
    evaluated = set(snapshot.evaluated_source_namespaces)
    incomplete = set(snapshot.incomplete_namespaces)
    reasons: set[str] = set()
    if not required_set.issubset(declared):
        reasons.add("desired_required_sources_incomplete")
    if not required_set.issubset(evaluated):
        reasons.add("required_source_not_evaluated")
    if required_set.intersection(incomplete):
        reasons.add("required_source_incomplete")
    if any(error.source_namespace in required_set for error in snapshot.source_errors):
        reasons.add("required_source_error")
    return tuple(sorted(reasons))


def _target_facts(
    snapshot: SystemStateSnapshotV1,
    *,
    fact_namespace: str,
    target_namespace: str,
    target_identity: str,
) -> tuple[SystemStateFactV1, ...]:
    return tuple(
        fact
        for fact in snapshot.facts
        if fact.fact_namespace == fact_namespace
        and fact.target_namespace == target_namespace
        and fact.target_identity == target_identity
    )


class _BaseDesiredStateRule:
    supports_numeric_tolerance = False

    def _precheck(
        self,
        desired: DesiredStateV1,
        snapshot: SystemStateSnapshotV1,
    ) -> DesiredStateEvaluationV1 | None:
        if desired.status is not DesiredStateStatus.ACTIVE:
            return _unknown_evaluation(
                desired,
                snapshot,
                reason_codes=("desired_state_not_active",),
            )
        if desired.target_namespace != self.target_namespace:
            return _unknown_evaluation(
                desired,
                snapshot,
                reason_codes=("target_namespace_mismatch",),
            )
        if (
            desired.stabilization_policy.numeric_tolerance is not None
            and not self.supports_numeric_tolerance
        ):
            return _unknown_evaluation(
                desired,
                snapshot,
                reason_codes=("numeric_tolerance_unsupported",),
            )
        source_problems = _required_source_problem(
            desired,
            snapshot,
            self.required_source_namespaces,
        )
        if source_problems:
            return _unknown_evaluation(
                desired,
                snapshot,
                reason_codes=source_problems,
            )
        try:
            self.validate_expected(desired.expected_json)
        except (TypeError, ValueError):
            return _unknown_evaluation(
                desired,
                snapshot,
                reason_codes=("expected_value_invalid",),
            )
        return None

    @staticmethod
    def _one_fact_or_unknown(
        desired: DesiredStateV1,
        snapshot: SystemStateSnapshotV1,
        facts: tuple[SystemStateFactV1, ...],
        *,
        missing_reason: str,
        duplicate_reason: str,
    ) -> DesiredStateEvaluationV1 | SystemStateFactV1:
        if not facts:
            return _unknown_evaluation(
                desired,
                snapshot,
                reason_codes=(missing_reason,),
            )
        if len(facts) != 1:
            return _unknown_evaluation(
                desired,
                snapshot,
                reason_codes=(duplicate_reason,),
                supporting_facts=facts,
            )
        return facts[0]


class ComponentHealthRuleV1(_BaseDesiredStateRule):
    rule_key = "component_health"
    rule_version = 1
    target_namespace = "component"
    required_source_namespaces = ("health_registry", "self_model")

    def validate_expected(self, expected: dict[str, JSONValue]) -> None:
        raw = expected.get("acceptable_states")
        if not isinstance(raw, list) or not raw:
            raise ValueError("acceptable_states must be a non-empty list")
        states = tuple(_token(value, "acceptable_state") for value in raw)
        supported = {
            "unknown",
            "starting",
            "healthy",
            "degraded",
            "failed",
            "recovering",
            "disabled",
        }
        if len(set(states)) != len(states) or not set(states).issubset(supported):
            raise ValueError("acceptable_states contains invalid health states")

    def evaluate(
        self,
        desired: DesiredStateV1,
        snapshot: SystemStateSnapshotV1,
    ) -> DesiredStateEvaluationV1:
        if (precheck := self._precheck(desired, snapshot)) is not None:
            return precheck
        self_model = _target_facts(
            snapshot,
            fact_namespace="self_model",
            target_namespace="component",
            target_identity=desired.target_identity,
        )
        model_fact = self._one_fact_or_unknown(
            desired,
            snapshot,
            self_model,
            missing_reason="self_model_fact_missing",
            duplicate_reason="self_model_fact_ambiguous",
        )
        if isinstance(model_fact, DesiredStateEvaluationV1):
            return model_fact
        health = _target_facts(
            snapshot,
            fact_namespace="health_registry",
            target_namespace="component",
            target_identity=desired.target_identity,
        )
        health_fact = self._one_fact_or_unknown(
            desired,
            snapshot,
            health,
            missing_reason="health_fact_missing",
            duplicate_reason="health_fact_ambiguous",
        )
        if isinstance(health_fact, DesiredStateEvaluationV1):
            return health_fact
        state = health_fact.value_json.get("state")
        if not isinstance(state, str):
            return _unknown_evaluation(
                desired,
                snapshot,
                reason_codes=("health_fact_malformed",),
                supporting_facts=(model_fact, health_fact),
            )
        normalized = state.strip().casefold()
        acceptable = {
            str(value).strip().casefold()
            for value in desired.expected_json["acceptable_states"]
        }
        if normalized == "unknown":
            return _unknown_evaluation(
                desired,
                snapshot,
                reason_codes=("health_state_unknown",),
                supporting_facts=(model_fact, health_fact),
            )
        return _raw_evaluation(
            desired,
            snapshot,
            status=(
                DesiredStateEvaluationStatus.SATISFIED
                if normalized in acceptable
                else DesiredStateEvaluationStatus.VIOLATED
            ),
            reason_codes=(
                ("component_health_acceptable",)
                if normalized in acceptable
                else ("component_health_not_acceptable",)
            ),
            supporting_facts=(model_fact, health_fact),
        )


class CapabilityEffectiveStateRuleV1(_BaseDesiredStateRule):
    rule_key = "capability_effective_state"
    rule_version = 1
    target_namespace = "capability"
    required_source_namespaces = ("capability_registry",)

    def validate_expected(self, expected: dict[str, JSONValue]) -> None:
        value = expected.get("effective_enabled")
        if not isinstance(value, bool):
            raise ValueError("effective_enabled must be boolean")

    def evaluate(
        self,
        desired: DesiredStateV1,
        snapshot: SystemStateSnapshotV1,
    ) -> DesiredStateEvaluationV1:
        if (precheck := self._precheck(desired, snapshot)) is not None:
            return precheck
        facts = _target_facts(
            snapshot,
            fact_namespace="capability_registry",
            target_namespace="capability",
            target_identity=desired.target_identity,
        )
        fact = self._one_fact_or_unknown(
            desired,
            snapshot,
            facts,
            missing_reason="capability_fact_missing",
            duplicate_reason="capability_fact_ambiguous",
        )
        if isinstance(fact, DesiredStateEvaluationV1):
            return fact
        known = fact.value_json.get("effective_known")
        actual = fact.value_json.get("effective_enabled")
        if known is not True or not isinstance(actual, bool):
            return _unknown_evaluation(
                desired,
                snapshot,
                reason_codes=("capability_effective_state_unknown",),
                supporting_facts=(fact,),
            )
        expected = bool(desired.expected_json["effective_enabled"])
        return _raw_evaluation(
            desired,
            snapshot,
            status=(
                DesiredStateEvaluationStatus.SATISFIED
                if actual is expected
                else DesiredStateEvaluationStatus.VIOLATED
            ),
            reason_codes=(
                ("capability_effective_state_matches",)
                if actual is expected
                else ("capability_effective_state_mismatch",)
            ),
            supporting_facts=(fact,),
        )


class DurableWorkRuleV1(_BaseDesiredStateRule):
    rule_key = "durable_work"
    rule_version = 1
    target_namespace = "work"
    required_source_namespaces = ("work",)

    def validate_expected(self, expected: dict[str, JSONValue]) -> None:
        raw = expected.get("acceptable_states")
        if not isinstance(raw, list) or not raw:
            raise ValueError("acceptable_states must be a non-empty list")
        states = tuple(_token(value, "acceptable_state") for value in raw)
        supported = {
            "queued",
            "running",
            "waiting_resource",
            "waiting_dependency",
            "waiting_until",
            "waiting_for_owner",
            "paused",
            "retrying",
            "completed",
            "failed",
            "cancelled",
        }
        if len(set(states)) != len(states) or not set(states).issubset(supported):
            raise ValueError("acceptable_states contains invalid WorkState")
        terminal = expected.get("require_terminal", False)
        if not isinstance(terminal, bool):
            raise ValueError("require_terminal must be boolean")

    def evaluate(
        self,
        desired: DesiredStateV1,
        snapshot: SystemStateSnapshotV1,
    ) -> DesiredStateEvaluationV1:
        if (precheck := self._precheck(desired, snapshot)) is not None:
            return precheck
        facts = _target_facts(
            snapshot,
            fact_namespace="work",
            target_namespace="work",
            target_identity=desired.target_identity,
        )
        fact = self._one_fact_or_unknown(
            desired,
            snapshot,
            facts,
            missing_reason="work_fact_missing",
            duplicate_reason="work_fact_ambiguous",
        )
        if isinstance(fact, DesiredStateEvaluationV1):
            return fact
        state = fact.value_json.get("state")
        terminal = fact.value_json.get("terminal")
        if not isinstance(state, str) or not isinstance(terminal, bool):
            return _unknown_evaluation(
                desired,
                snapshot,
                reason_codes=("work_fact_malformed",),
                supporting_facts=(fact,),
            )
        acceptable = {
            str(value).strip().casefold()
            for value in desired.expected_json["acceptable_states"]
        }
        require_terminal = desired.expected_json.get("require_terminal", False) is True
        state_ok = state.strip().casefold() in acceptable
        terminal_ok = not require_terminal or terminal
        satisfied = state_ok and terminal_ok
        if not state_ok:
            reason = "work_state_not_acceptable"
        elif not terminal_ok:
            reason = "work_not_terminal"
        else:
            reason = "work_obligation_satisfied"
        return _raw_evaluation(
            desired,
            snapshot,
            status=(
                DesiredStateEvaluationStatus.SATISFIED
                if satisfied
                else DesiredStateEvaluationStatus.VIOLATED
            ),
            reason_codes=(reason,),
            supporting_facts=(fact,),
        )


class DesiredStateRuleRegistry:
    """Exact rule/version registry; unknown or incompatible rules fail closed."""

    def __init__(self, rules: tuple[DesiredStateRule, ...] = ()) -> None:
        self._rules: dict[tuple[str, int], DesiredStateRule] = {}
        for rule in rules:
            self.register(rule)

    def register(self, rule: DesiredStateRule) -> None:
        key = _token(getattr(rule, "rule_key", ""), "rule_key")
        version = _positive_int(
            getattr(rule, "rule_version", None),
            "rule_version",
        )
        target_namespace = _token(
            getattr(rule, "target_namespace", ""),
            "target_namespace",
        )
        required = _unique_tokens(
            tuple(getattr(rule, "required_source_namespaces", ())),
            "required_source_namespaces",
        )
        if not callable(getattr(rule, "validate_expected", None)) or not callable(
            getattr(rule, "evaluate", None)
        ):
            raise TypeError(
                "DesiredState rule must implement validation and evaluation"
            )
        identity = (key, version)
        if identity in self._rules:
            raise DuplicateDesiredStateRuleError(
                f"DesiredState rule already registered: {key}.v{version}"
            )
        if target_namespace != getattr(rule, "target_namespace"):
            raise DesiredStateRuleContractError(
                "rule target_namespace must be normalized"
            )
        if required != tuple(getattr(rule, "required_source_namespaces")):
            raise DesiredStateRuleContractError(
                "rule required_source_namespaces must be normalized and unique"
            )
        self._rules[identity] = rule

    def require(self, rule_key: str, rule_version: int) -> DesiredStateRule:
        key = _token(rule_key, "rule_key")
        version = _positive_int(rule_version, "rule_version")
        try:
            return self._rules[(key, version)]
        except KeyError as exc:
            raise UnknownDesiredStateRuleError(
                f"unknown DesiredState rule: {key}.v{version}"
            ) from exc

    def evaluate(
        self,
        desired: DesiredStateV1,
        snapshot: SystemStateSnapshotV1,
    ) -> DesiredStateEvaluationV1:
        if not isinstance(desired, DesiredStateV1):
            raise TypeError("desired must be a DesiredStateV1")
        if not isinstance(snapshot, SystemStateSnapshotV1):
            raise TypeError("snapshot must be a SystemStateSnapshotV1")
        rule = self.require(desired.rule_key, desired.rule_version)
        result = rule.evaluate(desired, snapshot)
        assert_evaluation_current(desired, result)
        if result.snapshot_digest != snapshot.snapshot_digest:
            raise DesiredStateRuleContractError(
                "rule evaluation returned a mismatched snapshot digest"
            )
        return result

    def all(self) -> tuple[DesiredStateRule, ...]:
        return tuple(self._rules[key] for key in sorted(self._rules))


def build_default_desired_state_rule_registry() -> DesiredStateRuleRegistry:
    return DesiredStateRuleRegistry(
        (
            ComponentHealthRuleV1(),
            CapabilityEffectiveStateRuleV1(),
            DurableWorkRuleV1(),
        )
    )


def assert_evaluation_current(
    desired: DesiredStateV1,
    evaluation: DesiredStateEvaluationV1,
) -> None:
    if not isinstance(desired, DesiredStateV1):
        raise TypeError("desired must be a DesiredStateV1")
    if not isinstance(evaluation, DesiredStateEvaluationV1):
        raise TypeError("evaluation must be a DesiredStateEvaluationV1")
    expected = (
        desired.desired_state_id,
        desired.generation,
        desired.rule_key,
        desired.rule_version,
    )
    observed = (
        evaluation.desired_state_id,
        evaluation.desired_generation,
        evaluation.rule_key,
        evaluation.rule_version,
    )
    if observed != expected:
        raise DesiredStateRuleContractError(
            "evaluation is stale or belongs to another DesiredState generation"
        )


class DesiredStateStabilizer:
    """Apply count/age/recovery/cooldown policy without mutating canonical source truth."""

    def apply(
        self,
        desired: DesiredStateV1,
        raw: DesiredStateEvaluationV1,
        *,
        previous: StabilizationCursorV1 | None = None,
        last_dispatch_at_epoch: float | None = None,
    ) -> StabilizationDecisionV1:
        if not isinstance(desired, DesiredStateV1):
            raise TypeError("desired must be a DesiredStateV1")
        if not isinstance(raw, DesiredStateEvaluationV1):
            raise TypeError("raw must be a DesiredStateEvaluationV1")
        assert_evaluation_current(desired, raw)
        if raw.status not in {
            DesiredStateEvaluationStatus.SATISFIED,
            DesiredStateEvaluationStatus.VIOLATED,
            DesiredStateEvaluationStatus.UNKNOWN,
        }:
            raise DesiredStateRuleContractError(
                "stabilizer requires a raw rule evaluation"
            )
        if previous is not None:
            previous_identity = (
                previous.desired_state_id,
                previous.desired_generation,
                previous.rule_key,
                previous.rule_version,
            )
            current_identity = (
                desired.desired_state_id,
                desired.generation,
                desired.rule_key,
                desired.rule_version,
            )
            if previous_identity != current_identity:
                previous = None
            elif raw.evaluated_at_epoch < previous.evaluated_at_epoch:
                raise DesiredStateRuleContractError(
                    "evaluation time regressed within one DesiredState generation"
                )

        policy = desired.stabilization_policy
        cooldown_until = cooldown_until_epoch(last_dispatch_at_epoch, policy)
        cooldown_active = (
            cooldown_until is not None and raw.evaluated_at_epoch < cooldown_until
        )

        if raw.status is DesiredStateEvaluationStatus.UNKNOWN:
            cursor = StabilizationCursorV1(
                desired_state_id=desired.desired_state_id,
                desired_generation=desired.generation,
                rule_key=desired.rule_key,
                rule_version=desired.rule_version,
                last_snapshot_digest=raw.snapshot_digest,
                last_observation_status=raw.status,
                evaluated_at_epoch=raw.evaluated_at_epoch,
                consecutive_violations=0,
                first_violation_at_epoch=None,
                last_violation_at_epoch=None,
                first_recovery_at_epoch=None,
                violation_active=False
                if previous is None
                else previous.violation_active,
            )
            result = replace(
                raw,
                consecutive_violations=0,
                cooldown_until_epoch=cooldown_until,
            )
            return StabilizationDecisionV1(result, cursor, cooldown_active)

        if raw.status is DesiredStateEvaluationStatus.VIOLATED:
            continues = (
                previous is not None
                and previous.last_observation_status
                is DesiredStateEvaluationStatus.VIOLATED
            )
            consecutive = previous.consecutive_violations + 1 if continues else 1
            first_violation = (
                previous.first_violation_at_epoch
                if continues and previous.first_violation_at_epoch is not None
                else raw.evaluated_at_epoch
            )
            violation_age = raw.evaluated_at_epoch - first_violation
            active = bool(
                consecutive >= policy.required_consecutive_violations
                and violation_age >= policy.minimum_violation_age_seconds
            )
            cursor = StabilizationCursorV1(
                desired_state_id=desired.desired_state_id,
                desired_generation=desired.generation,
                rule_key=desired.rule_key,
                rule_version=desired.rule_version,
                last_snapshot_digest=raw.snapshot_digest,
                last_observation_status=raw.status,
                evaluated_at_epoch=raw.evaluated_at_epoch,
                consecutive_violations=consecutive,
                first_violation_at_epoch=first_violation,
                last_violation_at_epoch=raw.evaluated_at_epoch,
                first_recovery_at_epoch=None,
                violation_active=active or bool(previous and previous.violation_active),
            )
            result = replace(
                raw,
                status=(
                    DesiredStateEvaluationStatus.VIOLATED
                    if active
                    else DesiredStateEvaluationStatus.STABILIZING
                ),
                reason_codes=(
                    raw.reason_codes
                    if active
                    else tuple(
                        sorted(
                            {
                                *raw.reason_codes,
                                "violation_stabilizing",
                            }
                        )
                    )
                ),
                first_violation_at_epoch=first_violation,
                last_violation_at_epoch=raw.evaluated_at_epoch,
                consecutive_violations=consecutive,
                cooldown_until_epoch=cooldown_until,
            )
            return StabilizationDecisionV1(result, cursor, cooldown_active)

        previously_active = bool(previous and previous.violation_active)
        if not previously_active:
            cursor = StabilizationCursorV1(
                desired_state_id=desired.desired_state_id,
                desired_generation=desired.generation,
                rule_key=desired.rule_key,
                rule_version=desired.rule_version,
                last_snapshot_digest=raw.snapshot_digest,
                last_observation_status=raw.status,
                evaluated_at_epoch=raw.evaluated_at_epoch,
                violation_active=False,
            )
            result = replace(raw, cooldown_until_epoch=cooldown_until)
            return StabilizationDecisionV1(result, cursor, cooldown_active)

        continues_recovery = (
            previous is not None
            and previous.last_observation_status
            is DesiredStateEvaluationStatus.SATISFIED
            and previous.first_recovery_at_epoch is not None
        )
        first_recovery = (
            previous.first_recovery_at_epoch
            if continues_recovery
            else raw.evaluated_at_epoch
        )
        recovered = bool(
            raw.evaluated_at_epoch - first_recovery
            >= policy.minimum_recovery_age_seconds
        )
        cursor = StabilizationCursorV1(
            desired_state_id=desired.desired_state_id,
            desired_generation=desired.generation,
            rule_key=desired.rule_key,
            rule_version=desired.rule_version,
            last_snapshot_digest=raw.snapshot_digest,
            last_observation_status=raw.status,
            evaluated_at_epoch=raw.evaluated_at_epoch,
            consecutive_violations=0,
            first_violation_at_epoch=(
                None if recovered else previous.first_violation_at_epoch
            ),
            last_violation_at_epoch=(
                None if recovered else previous.last_violation_at_epoch
            ),
            first_recovery_at_epoch=None if recovered else first_recovery,
            violation_active=not recovered,
        )
        result = replace(
            raw,
            status=(
                DesiredStateEvaluationStatus.SATISFIED
                if recovered
                else DesiredStateEvaluationStatus.STABILIZING
            ),
            reason_codes=(
                raw.reason_codes
                if recovered
                else tuple(
                    sorted(
                        {
                            *raw.reason_codes,
                            "recovery_stabilizing",
                        }
                    )
                )
            ),
            first_violation_at_epoch=(
                None if recovered else previous.first_violation_at_epoch
            ),
            last_violation_at_epoch=(
                None if recovered else previous.last_violation_at_epoch
            ),
            first_recovery_at_epoch=None if recovered else first_recovery,
            consecutive_violations=0,
            cooldown_until_epoch=cooldown_until,
        )
        return StabilizationDecisionV1(result, cursor, cooldown_active)


@dataclass(frozen=True, slots=True)
class ObjectiveCompletionV1:
    objective_id: str
    objective_generation: int
    status: DesiredStateEvaluationStatus
    desired_state_ids: tuple[str, ...]
    evaluation_digests: tuple[str, ...]
    evaluated_at_epoch: float
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "objective_id",
            _text(self.objective_id, "objective_id", max_length=240),
        )
        object.__setattr__(
            self,
            "objective_generation",
            _positive_int(self.objective_generation, "objective_generation"),
        )
        if not isinstance(self.status, DesiredStateEvaluationStatus):
            raise TypeError("status must be a DesiredStateEvaluationStatus")
        object.__setattr__(
            self,
            "desired_state_ids",
            tuple(
                _text(value, "desired_state_id", max_length=240)
                for value in self.desired_state_ids
            ),
        )
        object.__setattr__(
            self,
            "evaluation_digests",
            _sha256_tuple(self.evaluation_digests, "evaluation_digests"),
        )
        if len(self.desired_state_ids) != len(self.evaluation_digests):
            raise ValueError("objective completion identity/evaluation lengths differ")
        if len(set(self.desired_state_ids)) != len(self.desired_state_ids):
            raise ValueError("objective completion DesiredState ids must be unique")
        object.__setattr__(
            self,
            "evaluated_at_epoch",
            _epoch(self.evaluated_at_epoch, "evaluated_at_epoch"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_tokens(self.reason_codes, "reason_codes"),
        )


def aggregate_objective_completion(
    *,
    objective_id: str,
    objective_generation: int,
    desired_states: tuple[DesiredStateV1, ...],
    evaluations: tuple[DesiredStateEvaluationV1, ...],
) -> ObjectiveCompletionV1:
    normalized_objective = _text(objective_id, "objective_id", max_length=240)
    generation = _positive_int(objective_generation, "objective_generation")
    if not desired_states:
        raise ValueError("objective completion requires DesiredStates")
    by_id = {evaluation.desired_state_id: evaluation for evaluation in evaluations}
    if len(by_id) != len(evaluations):
        raise DesiredStateRuleContractError("duplicate DesiredState evaluations")
    ordered: list[tuple[DesiredStateV1, DesiredStateEvaluationV1]] = []
    for desired in sorted(desired_states, key=lambda item: item.desired_state_id):
        if desired.objective_id != normalized_objective:
            raise DesiredStateRuleContractError(
                "DesiredState belongs to another Objective"
            )
        evaluation = by_id.get(desired.desired_state_id)
        if evaluation is None:
            raise DesiredStateRuleContractError(
                "objective completion is missing a DesiredState evaluation"
            )
        assert_evaluation_current(desired, evaluation)
        ordered.append((desired, evaluation))
    if set(by_id) != {desired.desired_state_id for desired in desired_states}:
        raise DesiredStateRuleContractError(
            "objective completion contains unrelated evaluations"
        )

    statuses = {evaluation.status for _, evaluation in ordered}
    if DesiredStateEvaluationStatus.VIOLATED in statuses:
        status = DesiredStateEvaluationStatus.VIOLATED
        reason = "objective_has_violated_desired_state"
    elif DesiredStateEvaluationStatus.UNKNOWN in statuses:
        status = DesiredStateEvaluationStatus.UNKNOWN
        reason = "objective_has_unknown_desired_state"
    elif DesiredStateEvaluationStatus.STABILIZING in statuses:
        status = DesiredStateEvaluationStatus.STABILIZING
        reason = "objective_has_stabilizing_desired_state"
    elif statuses == {DesiredStateEvaluationStatus.SATISFIED}:
        status = DesiredStateEvaluationStatus.SATISFIED
        reason = "objective_all_desired_states_satisfied"
    else:
        raise DesiredStateRuleContractError(
            "objective completion contains unsupported evaluation status"
        )

    return ObjectiveCompletionV1(
        objective_id=normalized_objective,
        objective_generation=generation,
        status=status,
        desired_state_ids=tuple(desired.desired_state_id for desired, _ in ordered),
        evaluation_digests=tuple(evaluation.digest for _, evaluation in ordered),
        evaluated_at_epoch=max(
            evaluation.evaluated_at_epoch for _, evaluation in ordered
        ),
        reason_codes=(reason,),
    )
