from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.autonomy.models import (
    DesiredStateStatus,
    DesiredStateV1,
    StabilizationPolicyV1,
)
from jarvis.autonomy.rules import (
    CapabilityEffectiveStateRuleV1,
    ComponentHealthRuleV1,
    DesiredStateEvaluationStatus,
    DesiredStateEvaluator,
    DesiredStateRuleRegistry,
    DesiredStateStabilizer,
    DuplicateDesiredStateRuleError,
    DurableWorkRuleV1,
    RawDesiredStateEvaluationV1,
    StabilizationStateV1,
    aggregate_objective_completion,
    build_default_desired_state_rule_registry,
    dispatch_cooldown_until,
    within_numeric_tolerance,
)
from jarvis.autonomy.system_state import (
    SystemStateFactV1,
    SystemStateSnapshotV1,
    SystemStateSourceErrorV1,
)

NOW = 1_800_000_000.0
DIGEST_A = "a" * 64


def _policy(
    *,
    violations: int = 1,
    violation_age: float = 0.0,
    recovery_age: float = 0.0,
    cooldown: float = 0.0,
    tolerance: float | None = None,
) -> StabilizationPolicyV1:
    return StabilizationPolicyV1(
        required_consecutive_violations=violations,
        minimum_violation_age_seconds=violation_age,
        minimum_recovery_age_seconds=recovery_age,
        cooldown_after_dispatch_seconds=cooldown,
        numeric_tolerance=tolerance,
    )


def _desired(
    *,
    desired_state_id: str = "desired_test",
    target_namespace: str = "component",
    target_identity: str = "runtime.test",
    rule_key: str = "component_health",
    rule_version: int = 1,
    expected_json: dict | None = None,
    required_source_namespaces: tuple[str, ...] = (
        "health_registry",
        "self_model",
    ),
    generation: int = 1,
    policy: StabilizationPolicyV1 | None = None,
) -> DesiredStateV1:
    return DesiredStateV1(
        desired_state_id=desired_state_id,
        objective_id="objective_test",
        target_namespace=target_namespace,
        target_identity=target_identity,
        rule_key=rule_key,
        rule_version=rule_version,
        expected_json=(
            {"acceptable_states": ["healthy"]}
            if expected_json is None
            else expected_json
        ),
        required_source_namespaces=required_source_namespaces,
        stabilization_policy=policy or _policy(),
        generation=generation,
        status=DesiredStateStatus.ACTIVE,
        provenance_source_identity="test:owner-approved",
        created_at_epoch=NOW - 100,
        updated_at_epoch=NOW - 100 + generation - 1,
    )


def _fact(
    *,
    namespace: str,
    target_namespace: str,
    target_identity: str,
    value: dict,
    source_identity: str | None = None,
) -> SystemStateFactV1:
    return SystemStateFactV1(
        fact_namespace=namespace,
        source_identity=source_identity or f"{namespace}:{target_identity}",
        source_version_or_digest=DIGEST_A,
        target_namespace=target_namespace,
        target_identity=target_identity,
        value_json=value,
        observed_at_epoch=NOW,
        evidence_references=(f"evidence:{namespace}:{target_identity}",),
        source_adapter_key="phase10a.test",
        source_adapter_version=1,
    )


def _snapshot(
    *,
    facts: tuple[SystemStateFactV1, ...],
    namespaces: tuple[str, ...],
    incomplete: tuple[str, ...] = (),
    errors: tuple[SystemStateSourceErrorV1, ...] = (),
    now: float = NOW,
) -> SystemStateSnapshotV1:
    return SystemStateSnapshotV1.create(
        evaluated_source_namespaces=namespaces,
        facts=facts,
        source_errors=errors,
        incomplete_namespaces=incomplete,
        started_at_epoch=now,
        ended_at_epoch=now,
    )


def _raw(
    desired: DesiredStateV1,
    *,
    status: DesiredStateEvaluationStatus,
    now: float,
) -> RawDesiredStateEvaluationV1:
    return RawDesiredStateEvaluationV1(
        desired_state_id=desired.desired_state_id,
        desired_generation=desired.generation,
        rule_key=desired.rule_key,
        rule_version=desired.rule_version,
        status=status,
        snapshot_digest=DIGEST_A,
        reason_codes=(f"raw_{status.value}",),
        supporting_fact_digests=(),
        evaluated_at_epoch=now,
    )


def test_rule_registry_is_exact_versioned_and_duplicate_safe() -> None:
    registry = DesiredStateRuleRegistry((ComponentHealthRuleV1(),))

    assert registry.require("component_health", 1).rule_version == 1

    with pytest.raises(DuplicateDesiredStateRuleError):
        registry.register(ComponentHealthRuleV1())

    desired = _desired(rule_version=99)
    evaluation = DesiredStateEvaluator(registry).evaluate_raw(
        desired,
        _snapshot(
            facts=(),
            namespaces=("health_registry", "self_model"),
        ),
    )

    assert evaluation.status is DesiredStateEvaluationStatus.UNKNOWN
    assert evaluation.reason_codes == ("unknown_rule_version",)


def test_required_source_incomplete_is_unknown_not_violation() -> None:
    desired = _desired()
    health = _fact(
        namespace="health_registry",
        target_namespace="component",
        target_identity=desired.target_identity,
        value={"state": "failed"},
    )
    model = _fact(
        namespace="self_model",
        target_namespace="component",
        target_identity=desired.target_identity,
        value={"component_id": desired.target_identity},
    )
    error = SystemStateSourceErrorV1(
        source_namespace="health_registry",
        source_adapter_key="phase10a.test",
        source_adapter_version=1,
        reason_code="stale_fact",
        summary="Canonical health fact is stale.",
    )
    snapshot = _snapshot(
        facts=(health, model),
        namespaces=("health_registry", "self_model"),
        incomplete=("health_registry",),
        errors=(error,),
    )

    evaluation = DesiredStateEvaluator(
        build_default_desired_state_rule_registry()
    ).evaluate_raw(desired, snapshot)

    assert evaluation.status is DesiredStateEvaluationStatus.UNKNOWN
    assert "required_source_incomplete" in evaluation.reason_codes
    assert "source_stale_fact" in evaluation.reason_codes


@pytest.mark.parametrize(
    ("health_state", "expected"),
    (
        ("healthy", DesiredStateEvaluationStatus.SATISFIED),
        ("degraded", DesiredStateEvaluationStatus.VIOLATED),
        ("unknown", DesiredStateEvaluationStatus.UNKNOWN),
    ),
)
def test_component_health_rule_is_deterministic(
    health_state: str,
    expected: DesiredStateEvaluationStatus,
) -> None:
    desired = _desired()
    snapshot = _snapshot(
        facts=(
            _fact(
                namespace="self_model",
                target_namespace="component",
                target_identity=desired.target_identity,
                value={"component_id": desired.target_identity},
            ),
            _fact(
                namespace="health_registry",
                target_namespace="component",
                target_identity=desired.target_identity,
                value={"state": health_state},
            ),
        ),
        namespaces=("health_registry", "self_model"),
    )

    evaluation = DesiredStateEvaluator(
        build_default_desired_state_rule_registry()
    ).evaluate_raw(desired, snapshot)

    assert evaluation.status is expected
    assert len(evaluation.supporting_fact_digests) == 2


def test_capability_effective_state_rule_requires_known_effective_projection() -> None:
    desired = _desired(
        desired_state_id="desired_capability",
        target_namespace="capability",
        target_identity="capability.test",
        rule_key="capability_effective_state",
        expected_json={
            "effective_enabled": True,
            "acceptable_health_states": ["healthy"],
        },
        required_source_namespaces=("capability_registry",),
    )
    evaluator = DesiredStateEvaluator(build_default_desired_state_rule_registry())

    unknown = evaluator.evaluate_raw(
        desired,
        _snapshot(
            facts=(
                _fact(
                    namespace="capability_registry",
                    target_namespace="capability",
                    target_identity=desired.target_identity,
                    value={
                        "effective_known": False,
                        "effective_enabled": None,
                        "health_state": None,
                    },
                ),
            ),
            namespaces=("capability_registry",),
        ),
    )
    assert unknown.status is DesiredStateEvaluationStatus.UNKNOWN

    violated = evaluator.evaluate_raw(
        desired,
        _snapshot(
            facts=(
                _fact(
                    namespace="capability_registry",
                    target_namespace="capability",
                    target_identity=desired.target_identity,
                    value={
                        "effective_known": True,
                        "effective_enabled": False,
                        "health_state": "healthy",
                    },
                ),
            ),
            namespaces=("capability_registry",),
        ),
    )
    assert violated.status is DesiredStateEvaluationStatus.VIOLATED

    satisfied = evaluator.evaluate_raw(
        desired,
        _snapshot(
            facts=(
                _fact(
                    namespace="capability_registry",
                    target_namespace="capability",
                    target_identity=desired.target_identity,
                    value={
                        "effective_known": True,
                        "effective_enabled": True,
                        "health_state": "healthy",
                    },
                ),
            ),
            namespaces=("capability_registry",),
        ),
    )
    assert satisfied.status is DesiredStateEvaluationStatus.SATISFIED


def test_durable_work_rule_tracks_canonical_work_state_only() -> None:
    desired = _desired(
        desired_state_id="desired_work",
        target_namespace="work",
        target_identity="work_test",
        rule_key="durable_work",
        expected_json={"acceptable_states": ["completed"]},
        required_source_namespaces=("work",),
    )
    evaluator = DesiredStateEvaluator(build_default_desired_state_rule_registry())

    running = evaluator.evaluate_raw(
        desired,
        _snapshot(
            facts=(
                _fact(
                    namespace="work",
                    target_namespace="work",
                    target_identity=desired.target_identity,
                    value={"state": "running", "terminal": False},
                ),
            ),
            namespaces=("work",),
        ),
    )
    completed = evaluator.evaluate_raw(
        desired,
        _snapshot(
            facts=(
                _fact(
                    namespace="work",
                    target_namespace="work",
                    target_identity=desired.target_identity,
                    value={"state": "completed", "terminal": True},
                ),
            ),
            namespaces=("work",),
        ),
    )

    assert running.status is DesiredStateEvaluationStatus.VIOLATED
    assert completed.status is DesiredStateEvaluationStatus.SATISFIED


def test_required_namespace_contract_mismatch_fails_closed() -> None:
    desired = _desired(required_source_namespaces=("health_registry",))
    snapshot = _snapshot(
        facts=(),
        namespaces=("health_registry", "self_model"),
    )

    evaluation = DesiredStateEvaluator(
        build_default_desired_state_rule_registry()
    ).evaluate_raw(desired, snapshot)

    assert evaluation.status is DesiredStateEvaluationStatus.UNKNOWN
    assert evaluation.reason_codes == ("required_source_namespace_mismatch",)


def test_transient_violation_stabilizes_then_becomes_violated() -> None:
    desired = _desired(
        policy=_policy(violations=2, violation_age=10.0),
    )
    stabilizer = DesiredStateStabilizer()

    first = stabilizer.apply(
        desired,
        _raw(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            now=NOW,
        ),
    )
    assert first.evaluation.status is DesiredStateEvaluationStatus.STABILIZING
    assert first.state.consecutive_violations == 1
    assert first.state.stable_violation is False

    second = stabilizer.apply(
        desired,
        _raw(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            now=NOW + 5,
        ),
        previous=first.state,
    )
    assert second.evaluation.status is DesiredStateEvaluationStatus.STABILIZING
    assert second.state.consecutive_violations == 2
    assert second.state.stable_violation is False

    third = stabilizer.apply(
        desired,
        _raw(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            now=NOW + 10,
        ),
        previous=second.state,
    )
    assert third.evaluation.status is DesiredStateEvaluationStatus.VIOLATED
    assert third.state.consecutive_violations == 3
    assert third.state.stable_violation is True


def test_stable_recovery_requires_minimum_recovery_age() -> None:
    desired = _desired(
        policy=_policy(violations=1, recovery_age=20.0),
    )
    stabilizer = DesiredStateStabilizer()

    violated = stabilizer.apply(
        desired,
        _raw(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            now=NOW,
        ),
    )
    assert violated.evaluation.status is DesiredStateEvaluationStatus.VIOLATED
    assert violated.state.stable_violation is True

    recovering = stabilizer.apply(
        desired,
        _raw(
            desired,
            status=DesiredStateEvaluationStatus.SATISFIED,
            now=NOW + 1,
        ),
        previous=violated.state,
    )
    assert recovering.evaluation.status is DesiredStateEvaluationStatus.STABILIZING
    assert recovering.state.stable_violation is True
    assert recovering.state.recovery_started_at_epoch == NOW + 1

    recovered = stabilizer.apply(
        desired,
        _raw(
            desired,
            status=DesiredStateEvaluationStatus.SATISFIED,
            now=NOW + 21,
        ),
        previous=recovering.state,
    )
    assert recovered.evaluation.status is DesiredStateEvaluationStatus.SATISFIED
    assert recovered.state.stable_violation is False
    assert "stable_recovery" in recovered.evaluation.reason_codes


def test_stale_generation_cannot_satisfy_new_desired_state() -> None:
    previous_desired = _desired(generation=1)
    current = replace(
        previous_desired,
        generation=2,
        updated_at_epoch=NOW,
    )
    stale = _raw(
        previous_desired,
        status=DesiredStateEvaluationStatus.SATISFIED,
        now=NOW,
    )

    result = DesiredStateStabilizer().apply(current, stale)

    assert result.evaluation.status is DesiredStateEvaluationStatus.UNKNOWN
    assert result.evaluation.desired_generation == 2
    assert result.evaluation.reason_codes == ("stale_desired_generation_or_rule",)
    assert result.state.desired_generation == 2


def test_unknown_evidence_does_not_resolve_existing_stable_violation() -> None:
    desired = _desired()
    previous = StabilizationStateV1(
        desired_state_id=desired.desired_state_id,
        desired_generation=desired.generation,
        consecutive_violations=3,
        first_violation_at_epoch=NOW - 30,
        last_violation_at_epoch=NOW - 10,
        stable_violation=True,
        last_raw_status=DesiredStateEvaluationStatus.VIOLATED,
    )

    result = DesiredStateStabilizer().apply(
        desired,
        _raw(
            desired,
            status=DesiredStateEvaluationStatus.UNKNOWN,
            now=NOW,
        ),
        previous=previous,
    )

    assert result.evaluation.status is DesiredStateEvaluationStatus.UNKNOWN
    assert result.state.stable_violation is True
    assert result.state.first_violation_at_epoch == NOW - 30


def test_numeric_tolerance_and_dispatch_cooldown_are_bounded_helpers() -> None:
    policy = _policy(tolerance=0.5, cooldown=30.0)

    assert within_numeric_tolerance(10.4, 10.0, policy) is True
    assert within_numeric_tolerance(10.6, 10.0, policy) is False
    assert dispatch_cooldown_until(policy, NOW) == NOW + 30

    desired = _desired(policy=policy)
    result = DesiredStateStabilizer().apply(
        desired,
        _raw(
            desired,
            status=DesiredStateEvaluationStatus.SATISFIED,
            now=NOW + 10,
        ),
        last_dispatch_at_epoch=NOW,
    )
    assert result.evaluation.status is DesiredStateEvaluationStatus.SATISFIED
    assert result.dispatch_cooldown_active is True
    assert result.dispatch_cooldown_until_epoch == NOW + 30


def test_objective_completion_aggregates_without_model_inference() -> None:
    desired_a = _desired(desired_state_id="desired_a")
    desired_b = _desired(desired_state_id="desired_b")
    stabilizer = DesiredStateStabilizer()

    sat = stabilizer.apply(
        desired_a,
        _raw(
            desired_a,
            status=DesiredStateEvaluationStatus.SATISFIED,
            now=NOW,
        ),
    ).evaluation
    unknown = stabilizer.apply(
        desired_b,
        _raw(
            desired_b,
            status=DesiredStateEvaluationStatus.UNKNOWN,
            now=NOW,
        ),
    ).evaluation
    completion = aggregate_objective_completion(
        "objective_test",
        (sat, unknown),
        now_epoch=NOW,
    )

    assert completion.status is DesiredStateEvaluationStatus.UNKNOWN
    assert completion.reason_codes == ("objective_has_unknown_desired_state",)

    all_satisfied = aggregate_objective_completion(
        "objective_test",
        (sat, replace(unknown, status=DesiredStateEvaluationStatus.SATISFIED)),
        now_epoch=NOW,
    )
    assert all_satisfied.status is DesiredStateEvaluationStatus.SATISFIED


@pytest.mark.parametrize(
    "rule",
    (
        ComponentHealthRuleV1(),
        CapabilityEffectiveStateRuleV1(),
        DurableWorkRuleV1(),
    ),
)
def test_default_rule_registry_contains_only_initial_reviewed_families(rule) -> None:
    registry = build_default_desired_state_rule_registry()
    resolved = registry.require(rule.rule_key, rule.rule_version)

    assert type(resolved) is type(rule)
