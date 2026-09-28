"""Deterministic DesiredState rules and anti-flapping evaluation for Phase 10A."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from jarvis.autonomy.models import DesiredStateStatus, DesiredStateV1, StabilizationPolicyV1
from jarvis.autonomy.system_state import SystemStateFactV1, SystemStateSnapshotV1
from jarvis.self_model.health import HealthState
from jarvis.work.models import WorkState


class DesiredStateEvaluationStatus(StrEnum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNKNOWN = "unknown"
    STABILIZING = "stabilizing"


def _positive_epoch(value: float | None, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


def _reason_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(sorted({str(value).strip().casefold() for value in values}))
    if any(not value for value in normalized):
        raise ValueError("reason codes must not contain empty values")
    return normalized


def _fact_digests(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(sorted(set(values)))
    for value in normalized:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("supporting fact digest must be SHA-256")
    return normalized


@dataclass(frozen=True, slots=True)
class RawDesiredStateEvaluationV1:
    desired_state_id: str
    desired_generation: int
    rule_key: str
    rule_version: int
    status: DesiredStateEvaluationStatus
    snapshot_digest: str
    reason_codes: tuple[str, ...]
    supporting_fact_digests: tuple[str, ...]
    evaluated_at_epoch: float

    def __post_init__(self) -> None:
        if not self.desired_state_id.strip():
            raise ValueError("desired_state_id must not be empty")
        if self.desired_generation <= 0:
            raise ValueError("desired_generation must be positive")
        if not self.rule_key.strip():
            raise ValueError("rule_key must not be empty")
        if self.rule_version <= 0:
            raise ValueError("rule_version must be positive")
        if self.status is DesiredStateEvaluationStatus.STABILIZING:
            raise ValueError("raw rule evaluation cannot be STABILIZING")
        if len(self.snapshot_digest) != 64:
            raise ValueError("snapshot_digest must be SHA-256")
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        object.__setattr__(
            self,
            "supporting_fact_digests",
            _fact_digests(self.supporting_fact_digests),
        )
        object.__setattr__(
            self,
            "evaluated_at_epoch",
            _positive_epoch(self.evaluated_at_epoch, "evaluated_at_epoch"),
        )


@dataclass(frozen=True, slots=True)
class StabilizationStateV1:
    desired_state_id: str
    desired_generation: int
    consecutive_violations: int = 0
    first_violation_at_epoch: float | None = None
    last_violation_at_epoch: float | None = None
    recovery_started_at_epoch: float | None = None
    stable_violation: bool = False
    last_raw_status: DesiredStateEvaluationStatus = DesiredStateEvaluationStatus.UNKNOWN

    def __post_init__(self) -> None:
        if not self.desired_state_id.strip():
            raise ValueError("desired_state_id must not be empty")
        if self.desired_generation <= 0:
            raise ValueError("desired_generation must be positive")
        if self.consecutive_violations < 0:
            raise ValueError("consecutive_violations must not be negative")
        for field_name in (
            "first_violation_at_epoch",
            "last_violation_at_epoch",
            "recovery_started_at_epoch",
        ):
            object.__setattr__(
                self,
                field_name,
                _positive_epoch(getattr(self, field_name), field_name),
            )
        if self.first_violation_at_epoch is None and self.last_violation_at_epoch is not None:
            raise ValueError("last violation requires first violation evidence")
        if (
            self.first_violation_at_epoch is not None
            and self.last_violation_at_epoch is not None
            and self.last_violation_at_epoch < self.first_violation_at_epoch
        ):
            raise ValueError("last violation cannot precede first violation")
        if self.stable_violation and self.first_violation_at_epoch is None:
            raise ValueError("stable violation requires violation evidence")
        if self.last_raw_status is DesiredStateEvaluationStatus.STABILIZING:
            raise ValueError("last_raw_status must be a raw evaluation status")


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
    consecutive_violations: int = 0
    first_violation_at_epoch: float | None = None
    last_violation_at_epoch: float | None = None

    def __post_init__(self) -> None:
        if not self.desired_state_id.strip():
            raise ValueError("desired_state_id must not be empty")
        if self.desired_generation <= 0:
            raise ValueError("desired_generation must be positive")
        if not self.rule_key.strip():
            raise ValueError("rule_key must not be empty")
        if self.rule_version <= 0:
            raise ValueError("rule_version must be positive")
        if len(self.snapshot_digest) != 64:
            raise ValueError("snapshot_digest must be SHA-256")
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        object.__setattr__(
            self,
            "supporting_fact_digests",
            _fact_digests(self.supporting_fact_digests),
        )
        object.__setattr__(
            self,
            "evaluated_at_epoch",
            _positive_epoch(self.evaluated_at_epoch, "evaluated_at_epoch"),
        )
        if self.consecutive_violations < 0:
            raise ValueError("consecutive_violations must not be negative")
        first = _positive_epoch(
            self.first_violation_at_epoch,
            "first_violation_at_epoch",
        )
        last = _positive_epoch(
            self.last_violation_at_epoch,
            "last_violation_at_epoch",
        )
        if first is None and last is not None:
            raise ValueError("last violation requires first violation evidence")
        if first is not None and last is not None and last < first:
            raise ValueError("last violation cannot precede first violation")
        object.__setattr__(self, "first_violation_at_epoch", first)
        object.__setattr__(self, "last_violation_at_epoch", last)


@dataclass(frozen=True, slots=True)
class StabilizationResultV1:
    evaluation: DesiredStateEvaluationV1
    state: StabilizationStateV1
    dispatch_cooldown_active: bool
    dispatch_cooldown_until_epoch: float | None


@dataclass(frozen=True, slots=True)
class ObjectiveCompletionV1:
    objective_id: str
    status: DesiredStateEvaluationStatus
    desired_state_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    evaluated_at_epoch: float

    def __post_init__(self) -> None:
        if not self.objective_id.strip():
            raise ValueError("objective_id must not be empty")
        if not self.desired_state_ids:
            raise ValueError("objective completion requires DesiredState evaluations")
        if len(set(self.desired_state_ids)) != len(self.desired_state_ids):
            raise ValueError("desired_state_ids must be unique")
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        object.__setattr__(
            self,
            "evaluated_at_epoch",
            _positive_epoch(self.evaluated_at_epoch, "evaluated_at_epoch"),
        )


class DesiredStateRule(Protocol):
    rule_key: str
    rule_version: int
    required_namespaces: tuple[str, ...]
    resolver_key: str
    default_stabilization_policy: StabilizationPolicyV1

    def validate_expected(self, desired: DesiredStateV1) -> None: ...

    def evaluate(
        self,
        desired: DesiredStateV1,
        snapshot: SystemStateSnapshotV1,
    ) -> RawDesiredStateEvaluationV1: ...


class DuplicateDesiredStateRuleError(RuntimeError):
    pass


class UnknownDesiredStateRuleError(RuntimeError):
    pass


class DesiredStateRuleRegistry:
    """Exact rule-key/version registry; rule-version drift never falls back."""

    def __init__(self, rules: tuple[DesiredStateRule, ...] = ()) -> None:
        self._rules: dict[tuple[str, int], DesiredStateRule] = {}
        for rule in rules:
            self.register(rule)

    def register(self, rule: DesiredStateRule) -> None:
        key = str(getattr(rule, "rule_key", "")).strip().casefold()
        version = getattr(rule, "rule_version", None)
        namespaces = tuple(
            str(item).strip().casefold()
            for item in getattr(rule, "required_namespaces", ())
        )
        resolver_key = str(getattr(rule, "resolver_key", "")).strip().casefold()
        default_policy = getattr(rule, "default_stabilization_policy", None)
        if not key or isinstance(version, bool) or not isinstance(version, int) or version <= 0:
            raise ValueError("rule requires normalized key and positive version")
        if not namespaces or any(not item for item in namespaces):
            raise ValueError("rule requires source namespaces")
        if len(set(namespaces)) != len(namespaces):
            raise ValueError("rule source namespaces must be unique")
        if not resolver_key:
            raise ValueError("rule resolver_key must not be empty")
        if not isinstance(default_policy, StabilizationPolicyV1):
            raise TypeError("rule default_stabilization_policy must be StabilizationPolicyV1")
        if not callable(getattr(rule, "validate_expected", None)):
            raise TypeError("rule must provide validate_expected(desired)")
        if not callable(getattr(rule, "evaluate", None)):
            raise TypeError("rule must provide evaluate(desired, snapshot)")
        identity = (key, version)
        if identity in self._rules:
            raise DuplicateDesiredStateRuleError(
                f"DesiredState rule already registered: {key}.v{version}"
            )
        self._rules[identity] = rule

    def require(self, rule_key: str, rule_version: int) -> DesiredStateRule:
        key = str(rule_key).strip().casefold()
        identity = (key, int(rule_version))
        try:
            return self._rules[identity]
        except KeyError as exc:
            raise UnknownDesiredStateRuleError(
                f"unknown DesiredState rule: {key}.v{rule_version}"
            ) from exc

    def all(self) -> tuple[DesiredStateRule, ...]:
        return tuple(self._rules[key] for key in sorted(self._rules))


def _matching_facts(
    snapshot: SystemStateSnapshotV1,
    desired: DesiredStateV1,
    namespace: str,
) -> tuple[SystemStateFactV1, ...]:
    return tuple(
        fact
        for fact in snapshot.facts
        if fact.fact_namespace == namespace
        and fact.target_namespace == desired.target_namespace
        and fact.target_identity == desired.target_identity
    )


def _raw(
    desired: DesiredStateV1,
    snapshot: SystemStateSnapshotV1,
    *,
    status: DesiredStateEvaluationStatus,
    reason_codes: tuple[str, ...],
    facts: tuple[SystemStateFactV1, ...] = (),
) -> RawDesiredStateEvaluationV1:
    return RawDesiredStateEvaluationV1(
        desired_state_id=desired.desired_state_id,
        desired_generation=desired.generation,
        rule_key=desired.rule_key,
        rule_version=desired.rule_version,
        status=status,
        snapshot_digest=snapshot.snapshot_digest,
        reason_codes=reason_codes,
        supporting_fact_digests=tuple(fact.digest for fact in facts),
        evaluated_at_epoch=snapshot.ended_at_epoch,
    )


def _expected_strings(
    desired: DesiredStateV1,
    field: str,
    *,
    allowed: frozenset[str],
) -> tuple[str, ...]:
    raw = desired.expected_json.get(field)
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"expected_json.{field} must be a non-empty list")
    values = tuple(str(item).strip().casefold() for item in raw)
    if any(not item for item in values) or len(set(values)) != len(values):
        raise ValueError(f"expected_json.{field} must contain unique values")
    if not set(values).issubset(allowed):
        raise ValueError(f"expected_json.{field} contains unsupported values")
    return values


class ComponentHealthRuleV1:
    rule_key = "component_health"
    rule_version = 1
    required_namespaces = ("health_registry", "self_model")
    resolver_key = "component_health"
    default_stabilization_policy = StabilizationPolicyV1()

    def validate_expected(self, desired: DesiredStateV1) -> None:
        if desired.target_namespace != "component":
            raise ValueError("component-health rule requires component target")
        _expected_strings(
            desired,
            "acceptable_states",
            allowed=frozenset(item.value for item in HealthState),
        )

    def evaluate(
        self,
        desired: DesiredStateV1,
        snapshot: SystemStateSnapshotV1,
    ) -> RawDesiredStateEvaluationV1:
        acceptable = _expected_strings(
            desired,
            "acceptable_states",
            allowed=frozenset(item.value for item in HealthState),
        )
        model_facts = _matching_facts(snapshot, desired, "self_model")
        health_facts = _matching_facts(snapshot, desired, "health_registry")
        supporting = (*model_facts, *health_facts)
        if len(model_facts) != 1 or len(health_facts) != 1:
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                reason_codes=("component_health_fact_missing_or_ambiguous",),
                facts=supporting,
            )
        state = str(health_facts[0].value_json.get("state", "")).strip().casefold()
        if state not in {item.value for item in HealthState} or state == HealthState.UNKNOWN.value:
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                reason_codes=("component_health_unknown",),
                facts=supporting,
            )
        if state in acceptable:
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.SATISFIED,
                reason_codes=("component_health_acceptable",),
                facts=supporting,
            )
        return _raw(
            desired,
            snapshot,
            status=DesiredStateEvaluationStatus.VIOLATED,
            reason_codes=("component_health_unacceptable",),
            facts=supporting,
        )


class CapabilityEffectiveStateRuleV1:
    rule_key = "capability_effective_state"
    rule_version = 1
    required_namespaces = ("capability_registry",)
    resolver_key = "capability_effective_state"
    default_stabilization_policy = StabilizationPolicyV1()

    def validate_expected(self, desired: DesiredStateV1) -> None:
        if desired.target_namespace != "capability":
            raise ValueError("capability rule requires capability target")
        expected_enabled = desired.expected_json.get("effective_enabled")
        if not isinstance(expected_enabled, bool):
            raise ValueError("expected_json.effective_enabled must be boolean")
        raw_health = desired.expected_json.get("acceptable_health_states")
        if raw_health is not None:
            _expected_strings(
                desired,
                "acceptable_health_states",
                allowed=frozenset(item.value for item in HealthState),
            )

    def evaluate(
        self,
        desired: DesiredStateV1,
        snapshot: SystemStateSnapshotV1,
    ) -> RawDesiredStateEvaluationV1:
        self.validate_expected(desired)
        facts = _matching_facts(snapshot, desired, "capability_registry")
        if len(facts) != 1:
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                reason_codes=("capability_fact_missing_or_ambiguous",),
                facts=facts,
            )
        fact = facts[0]
        if fact.value_json.get("effective_known") is not True:
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                reason_codes=("capability_effective_state_unknown",),
                facts=facts,
            )
        actual_enabled = fact.value_json.get("effective_enabled")
        if not isinstance(actual_enabled, bool):
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                reason_codes=("capability_effective_state_malformed",),
                facts=facts,
            )
        if actual_enabled is not desired.expected_json["effective_enabled"]:
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.VIOLATED,
                reason_codes=("capability_effective_state_mismatch",),
                facts=facts,
            )
        if "acceptable_health_states" in desired.expected_json:
            acceptable = _expected_strings(
                desired,
                "acceptable_health_states",
                allowed=frozenset(item.value for item in HealthState),
            )
            health_state = str(fact.value_json.get("health_state", "")).casefold()
            if not health_state:
                return _raw(
                    desired,
                    snapshot,
                    status=DesiredStateEvaluationStatus.UNKNOWN,
                    reason_codes=("capability_health_unknown",),
                    facts=facts,
                )
            if health_state not in acceptable:
                return _raw(
                    desired,
                    snapshot,
                    status=DesiredStateEvaluationStatus.VIOLATED,
                    reason_codes=("capability_health_unacceptable",),
                    facts=facts,
                )
        return _raw(
            desired,
            snapshot,
            status=DesiredStateEvaluationStatus.SATISFIED,
            reason_codes=("capability_effective_state_acceptable",),
            facts=facts,
        )


class DurableWorkRuleV1:
    rule_key = "durable_work"
    rule_version = 1
    required_namespaces = ("work",)
    resolver_key = "durable_work"
    default_stabilization_policy = StabilizationPolicyV1()

    def validate_expected(self, desired: DesiredStateV1) -> None:
        if desired.target_namespace != "work":
            raise ValueError("durable-work rule requires work target")
        _expected_strings(
            desired,
            "acceptable_states",
            allowed=frozenset(item.value for item in WorkState),
        )

    def evaluate(
        self,
        desired: DesiredStateV1,
        snapshot: SystemStateSnapshotV1,
    ) -> RawDesiredStateEvaluationV1:
        acceptable = _expected_strings(
            desired,
            "acceptable_states",
            allowed=frozenset(item.value for item in WorkState),
        )
        facts = _matching_facts(snapshot, desired, "work")
        if len(facts) != 1:
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                reason_codes=("durable_work_fact_missing_or_ambiguous",),
                facts=facts,
            )
        state = str(facts[0].value_json.get("state", "")).strip().casefold()
        if state not in {item.value for item in WorkState}:
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                reason_codes=("durable_work_state_malformed",),
                facts=facts,
            )
        if state in acceptable:
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.SATISFIED,
                reason_codes=("durable_work_state_acceptable",),
                facts=facts,
            )
        return _raw(
            desired,
            snapshot,
            status=DesiredStateEvaluationStatus.VIOLATED,
            reason_codes=("durable_work_state_unacceptable",),
            facts=facts,
        )


def build_default_desired_state_rule_registry() -> DesiredStateRuleRegistry:
    return DesiredStateRuleRegistry(
        (
            ComponentHealthRuleV1(),
            CapabilityEffectiveStateRuleV1(),
            DurableWorkRuleV1(),
        )
    )


class DesiredStateEvaluator:
    """Fail-closed deterministic evaluation against one immutable SystemState snapshot."""

    def __init__(self, registry: DesiredStateRuleRegistry) -> None:
        if not isinstance(registry, DesiredStateRuleRegistry):
            raise TypeError("registry must be a DesiredStateRuleRegistry")
        self.registry = registry

    def evaluate_raw(
        self,
        desired: DesiredStateV1,
        snapshot: SystemStateSnapshotV1,
    ) -> RawDesiredStateEvaluationV1:
        if not isinstance(desired, DesiredStateV1):
            raise TypeError("desired must be a DesiredStateV1")
        if not isinstance(snapshot, SystemStateSnapshotV1):
            raise TypeError("snapshot must be a SystemStateSnapshotV1")
        if desired.status is not DesiredStateStatus.ACTIVE:
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                reason_codes=("desired_state_not_active",),
            )
        try:
            rule = self.registry.require(desired.rule_key, desired.rule_version)
        except UnknownDesiredStateRuleError:
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                reason_codes=("unknown_rule_version",),
            )
        expected_namespaces = tuple(sorted(rule.required_namespaces))
        configured_namespaces = tuple(sorted(desired.required_source_namespaces))
        if configured_namespaces != expected_namespaces:
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                reason_codes=("required_source_namespace_mismatch",),
            )
        evaluated = set(snapshot.evaluated_source_namespaces)
        required = set(expected_namespaces)
        if not required.issubset(evaluated):
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                reason_codes=("required_source_not_evaluated",),
            )
        incomplete = required.intersection(snapshot.incomplete_namespaces)
        if incomplete:
            reasons = tuple(
                sorted(
                    {
                        "required_source_incomplete",
                        *(
                            f"source_{item.reason_code}"
                            for item in snapshot.source_errors
                            if item.source_namespace in incomplete
                        ),
                    }
                )
            )
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                reason_codes=reasons,
            )
        try:
            rule.validate_expected(desired)
            return rule.evaluate(desired, snapshot)
        except (KeyError, TypeError, ValueError):
            return _raw(
                desired,
                snapshot,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                reason_codes=("invalid_expected_or_source_payload",),
            )


def within_numeric_tolerance(
    actual: float,
    expected: float,
    policy: StabilizationPolicyV1,
) -> bool:
    if isinstance(actual, bool) or not isinstance(actual, int | float):
        raise TypeError("actual must be numeric")
    if isinstance(expected, bool) or not isinstance(expected, int | float):
        raise TypeError("expected must be numeric")
    actual_value = float(actual)
    expected_value = float(expected)
    if not math.isfinite(actual_value) or not math.isfinite(expected_value):
        raise ValueError("numeric values must be finite")
    tolerance = policy.numeric_tolerance
    return (
        actual_value == expected_value
        if tolerance is None
        else abs(actual_value - expected_value) <= tolerance
    )


def dispatch_cooldown_until(
    policy: StabilizationPolicyV1,
    last_dispatch_at_epoch: float | None,
) -> float | None:
    last = _positive_epoch(last_dispatch_at_epoch, "last_dispatch_at_epoch")
    if last is None or policy.cooldown_after_dispatch_seconds <= 0:
        return None
    return last + policy.cooldown_after_dispatch_seconds


class DesiredStateStabilizer:
    """Apply consecutive/age/recovery stabilization without changing source truth."""

    def apply(
        self,
        desired: DesiredStateV1,
        raw: RawDesiredStateEvaluationV1,
        *,
        previous: StabilizationStateV1 | None = None,
        last_dispatch_at_epoch: float | None = None,
    ) -> StabilizationResultV1:
        if not isinstance(desired, DesiredStateV1):
            raise TypeError("desired must be a DesiredStateV1")
        if not isinstance(raw, RawDesiredStateEvaluationV1):
            raise TypeError("raw must be a RawDesiredStateEvaluationV1")
        now = raw.evaluated_at_epoch
        policy = desired.stabilization_policy
        if (
            raw.desired_state_id != desired.desired_state_id
            or raw.desired_generation != desired.generation
            or raw.rule_key != desired.rule_key
            or raw.rule_version != desired.rule_version
        ):
            state = StabilizationStateV1(
                desired_state_id=desired.desired_state_id,
                desired_generation=desired.generation,
            )
            evaluation = DesiredStateEvaluationV1(
                desired_state_id=desired.desired_state_id,
                desired_generation=desired.generation,
                rule_key=desired.rule_key,
                rule_version=desired.rule_version,
                status=DesiredStateEvaluationStatus.UNKNOWN,
                snapshot_digest=raw.snapshot_digest,
                reason_codes=("stale_desired_generation_or_rule",),
                supporting_fact_digests=raw.supporting_fact_digests,
                evaluated_at_epoch=now,
            )
            cooldown_until = dispatch_cooldown_until(policy, last_dispatch_at_epoch)
            return StabilizationResultV1(
                evaluation=evaluation,
                state=state,
                dispatch_cooldown_active=(
                    cooldown_until is not None and now < cooldown_until
                ),
                dispatch_cooldown_until_epoch=cooldown_until,
            )

        state = previous
        if (
            state is None
            or state.desired_state_id != desired.desired_state_id
            or state.desired_generation != desired.generation
        ):
            state = StabilizationStateV1(
                desired_state_id=desired.desired_state_id,
                desired_generation=desired.generation,
            )

        reasons = set(raw.reason_codes)
        if raw.status is DesiredStateEvaluationStatus.UNKNOWN:
            next_state = StabilizationStateV1(
                desired_state_id=desired.desired_state_id,
                desired_generation=desired.generation,
                consecutive_violations=0,
                first_violation_at_epoch=state.first_violation_at_epoch,
                last_violation_at_epoch=state.last_violation_at_epoch,
                recovery_started_at_epoch=None,
                stable_violation=state.stable_violation,
                last_raw_status=DesiredStateEvaluationStatus.UNKNOWN,
            )
            final_status = DesiredStateEvaluationStatus.UNKNOWN
        elif raw.status is DesiredStateEvaluationStatus.VIOLATED:
            contiguous = state.last_raw_status is DesiredStateEvaluationStatus.VIOLATED
            count = state.consecutive_violations + 1 if contiguous else 1
            first = (
                state.first_violation_at_epoch
                if contiguous and state.first_violation_at_epoch is not None
                else now
            )
            stable = state.stable_violation or (
                count >= policy.required_consecutive_violations
                and now - first >= policy.minimum_violation_age_seconds
            )
            next_state = StabilizationStateV1(
                desired_state_id=desired.desired_state_id,
                desired_generation=desired.generation,
                consecutive_violations=count,
                first_violation_at_epoch=first,
                last_violation_at_epoch=now,
                recovery_started_at_epoch=None,
                stable_violation=stable,
                last_raw_status=DesiredStateEvaluationStatus.VIOLATED,
            )
            if stable:
                final_status = DesiredStateEvaluationStatus.VIOLATED
            else:
                final_status = DesiredStateEvaluationStatus.STABILIZING
                reasons.add("violation_stabilizing")
        else:
            if state.stable_violation:
                recovery_started = state.recovery_started_at_epoch or now
                recovered = (
                    now - recovery_started >= policy.minimum_recovery_age_seconds
                )
                if recovered:
                    next_state = StabilizationStateV1(
                        desired_state_id=desired.desired_state_id,
                        desired_generation=desired.generation,
                        last_raw_status=DesiredStateEvaluationStatus.SATISFIED,
                    )
                    final_status = DesiredStateEvaluationStatus.SATISFIED
                    reasons.add("stable_recovery")
                else:
                    next_state = StabilizationStateV1(
                        desired_state_id=desired.desired_state_id,
                        desired_generation=desired.generation,
                        consecutive_violations=0,
                        first_violation_at_epoch=state.first_violation_at_epoch,
                        last_violation_at_epoch=state.last_violation_at_epoch,
                        recovery_started_at_epoch=recovery_started,
                        stable_violation=True,
                        last_raw_status=DesiredStateEvaluationStatus.SATISFIED,
                    )
                    final_status = DesiredStateEvaluationStatus.STABILIZING
                    reasons.add("recovery_stabilizing")
            else:
                next_state = StabilizationStateV1(
                    desired_state_id=desired.desired_state_id,
                    desired_generation=desired.generation,
                    last_raw_status=DesiredStateEvaluationStatus.SATISFIED,
                )
                final_status = DesiredStateEvaluationStatus.SATISFIED

        evaluation = DesiredStateEvaluationV1(
            desired_state_id=desired.desired_state_id,
            desired_generation=desired.generation,
            rule_key=desired.rule_key,
            rule_version=desired.rule_version,
            status=final_status,
            snapshot_digest=raw.snapshot_digest,
            reason_codes=tuple(reasons),
            supporting_fact_digests=raw.supporting_fact_digests,
            evaluated_at_epoch=now,
            consecutive_violations=next_state.consecutive_violations,
            first_violation_at_epoch=next_state.first_violation_at_epoch,
            last_violation_at_epoch=next_state.last_violation_at_epoch,
        )
        cooldown_until = dispatch_cooldown_until(policy, last_dispatch_at_epoch)
        return StabilizationResultV1(
            evaluation=evaluation,
            state=next_state,
            dispatch_cooldown_active=(cooldown_until is not None and now < cooldown_until),
            dispatch_cooldown_until_epoch=cooldown_until,
        )


def aggregate_objective_completion(
    objective_id: str,
    evaluations: tuple[DesiredStateEvaluationV1, ...],
    *,
    now_epoch: float,
) -> ObjectiveCompletionV1:
    if not evaluations:
        raise ValueError("objective completion requires evaluations")
    identities = tuple(item.desired_state_id for item in evaluations)
    statuses = {item.status for item in evaluations}
    if DesiredStateEvaluationStatus.VIOLATED in statuses:
        status = DesiredStateEvaluationStatus.VIOLATED
        reasons = ("objective_has_violated_desired_state",)
    elif DesiredStateEvaluationStatus.UNKNOWN in statuses:
        status = DesiredStateEvaluationStatus.UNKNOWN
        reasons = ("objective_has_unknown_desired_state",)
    elif DesiredStateEvaluationStatus.STABILIZING in statuses:
        status = DesiredStateEvaluationStatus.STABILIZING
        reasons = ("objective_has_stabilizing_desired_state",)
    else:
        status = DesiredStateEvaluationStatus.SATISFIED
        reasons = ("objective_all_desired_states_satisfied",)
    return ObjectiveCompletionV1(
        objective_id=objective_id,
        status=status,
        desired_state_ids=tuple(sorted(identities)),
        reason_codes=reasons,
        evaluated_at_epoch=now_epoch,
    )
