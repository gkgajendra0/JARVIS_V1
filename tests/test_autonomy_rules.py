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
    DesiredStateRuleContractError,
    DesiredStateRuleRegistry,
    DesiredStateStabilizer,
    DurableWorkRuleV1,
    UnknownDesiredStateRuleError,
    aggregate_objective_completion,
    build_default_desired_state_rule_registry,
    cooldown_is_active,
    cooldown_until_epoch,
    numeric_within_tolerance,
)
from jarvis.autonomy.system_state import (
    SystemStateFactV1,
    SystemStateSnapshotV1,
    SystemStateSourceErrorV1,
)

NOW = 1_800_000_000.0
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _fact(
    *,
    namespace: str,
    target_namespace: str,
    target_identity: str,
    value: dict,
    source_key: str = "test_source",
    source_version: int = 1,
) -> SystemStateFactV1:
    return SystemStateFactV1(
        fact_namespace=namespace,
        source_identity=f"{namespace}:{target_identity}",
        source_version_or_digest=DIGEST_A,
        target_namespace=target_namespace,
        target_identity=target_identity,
        value_json=value,
        observed_at_epoch=NOW,
        evidence_references=(f"evidence:{namespace}:{target_identity}",),
        source_adapter_key=source_key,
        source_adapter_version=source_version,
    )


def _snapshot(
    *,
    namespaces: tuple[str, ...],
    facts: tuple[SystemStateFactV1, ...],
    incomplete: tuple[str, ...] = (),
    errors: tuple[SystemStateSourceErrorV1, ...] = (),
    ended_at_epoch: float = NOW,
) -> SystemStateSnapshotV1:
    return SystemStateSnapshotV1.create(
        evaluated_source_namespaces=namespaces,
        facts=facts,
        source_errors=errors,
        incomplete_namespaces=incomplete,
        started_at_epoch=ended_at_epoch,
        ended_at_epoch=ended_at_epoch,
    )


def _desired(
    *,
    rule_key: str,
    target_namespace: str,
    target_identity: str,
    expected: dict,
    required: tuple[str, ...],
    generation: int = 1,
    policy: StabilizationPolicyV1 | None = None,
) -> DesiredStateV1:
    return DesiredStateV1(
        desired_state_id=f"desired_{rule_key}_{target_identity}",
        objective_id="objective_phase10a_rules",
        target_namespace=target_namespace,
        target_identity=target_identity,
        rule_key=rule_key,
        rule_version=1,
        expected_json=expected,
        required_source_namespaces=required,
        stabilization_policy=policy or StabilizationPolicyV1(),
        generation=generation,
        status=DesiredStateStatus.ACTIVE,
        provenance_source_identity="registered:phase10a:test",
        created_at_epoch=NOW - 100,
        updated_at_epoch=NOW - 100 + generation - 1,
    )


def _component_snapshot(
    *,
    state: str,
    incomplete: tuple[str, ...] = (),
) -> SystemStateSnapshotV1:
    model = _fact(
        namespace="self_model",
        target_namespace="component",
        target_identity="runtime.test",
        value={
            "component_id": "runtime.test",
            "lifecycle": "active",
            "dependencies": [],
        },
        source_key="self_model_health",
    )
    health = _fact(
        namespace="health_registry",
        target_namespace="component",
        target_identity="runtime.test",
        value={
            "state": state,
            "reason_codes": ["test"],
            "sources": ["test"],
            "dependency_states": [],
        },
        source_key="self_model_health",
    )
    return _snapshot(
        namespaces=("self_model", "health_registry"),
        facts=(model, health),
        incomplete=incomplete,
    )


def _component_desired(
    *,
    generation: int = 1,
    policy: StabilizationPolicyV1 | None = None,
) -> DesiredStateV1:
    return _desired(
        rule_key="component_health",
        target_namespace="component",
        target_identity="runtime.test",
        expected={"acceptable_states": ["healthy"]},
        required=("self_model", "health_registry"),
        generation=generation,
        policy=policy,
    )


def test_default_rule_registry_is_exact_and_unknown_version_fails_closed() -> None:
    registry = build_default_desired_state_rule_registry()

    assert tuple((rule.rule_key, rule.rule_version) for rule in registry.all()) == (
        ("capability_effective_state", 1),
        ("component_health", 1),
        ("durable_work", 1),
    )
    assert isinstance(registry.require("component_health", 1), ComponentHealthRuleV1)

    with pytest.raises(UnknownDesiredStateRuleError):
        registry.require("component_health", 2)


def test_component_health_rule_satisfied_violated_and_unknown() -> None:
    registry = DesiredStateRuleRegistry((ComponentHealthRuleV1(),))
    desired = _component_desired()

    satisfied = registry.evaluate(desired, _component_snapshot(state="healthy"))
    assert satisfied.status is DesiredStateEvaluationStatus.SATISFIED
    assert satisfied.reason_codes == ("component_health_acceptable",)
    assert len(satisfied.supporting_fact_digests) == 2

    violated = registry.evaluate(desired, _component_snapshot(state="failed"))
    assert violated.status is DesiredStateEvaluationStatus.VIOLATED
    assert violated.reason_codes == ("component_health_not_acceptable",)

    unknown = registry.evaluate(
        desired,
        _component_snapshot(
            state="failed",
            incomplete=("health_registry",),
        ),
    )
    assert unknown.status is DesiredStateEvaluationStatus.UNKNOWN
    assert "required_source_incomplete" in unknown.reason_codes

    unknown_state = registry.evaluate(
        desired,
        _component_snapshot(state="unknown"),
    )
    assert unknown_state.status is DesiredStateEvaluationStatus.UNKNOWN
    assert unknown_state.reason_codes == ("health_state_unknown",)


def test_component_health_rule_requires_canonical_self_model_fact() -> None:
    desired = _component_desired()
    health = _fact(
        namespace="health_registry",
        target_namespace="component",
        target_identity="runtime.test",
        value={"state": "healthy"},
        source_key="self_model_health",
    )
    snapshot = _snapshot(
        namespaces=("self_model", "health_registry"),
        facts=(health,),
    )

    result = ComponentHealthRuleV1().evaluate(desired, snapshot)

    assert result.status is DesiredStateEvaluationStatus.UNKNOWN
    assert result.reason_codes == ("self_model_fact_missing",)


def test_rule_source_error_is_unknown_not_violation() -> None:
    desired = _component_desired()
    model = _fact(
        namespace="self_model",
        target_namespace="component",
        target_identity="runtime.test",
        value={"component_id": "runtime.test"},
        source_key="self_model_health",
    )
    error = SystemStateSourceErrorV1(
        source_namespace="health_registry",
        source_adapter_key="self_model_health",
        source_adapter_version=1,
        reason_code="source_read_failed",
        summary="RuntimeError",
    )
    snapshot = _snapshot(
        namespaces=("self_model", "health_registry"),
        facts=(model,),
        incomplete=("health_registry",),
        errors=(error,),
    )

    result = ComponentHealthRuleV1().evaluate(desired, snapshot)

    assert result.status is DesiredStateEvaluationStatus.UNKNOWN
    assert "required_source_error" in result.reason_codes
    assert "required_source_incomplete" in result.reason_codes


def test_capability_effective_state_rule_uses_effective_projection_only() -> None:
    desired = _desired(
        rule_key="capability_effective_state",
        target_namespace="capability",
        target_identity="example.capability",
        expected={"effective_enabled": True},
        required=("capability_registry",),
    )
    fact = _fact(
        namespace="capability_registry",
        target_namespace="capability",
        target_identity="example.capability",
        value={
            "desired_state": "enabled",
            "generation": 3,
            "effective_known": True,
            "effective_enabled": True,
            "applied_generation": 3,
            "health_state": "healthy",
        },
        source_key="capability_state",
    )
    snapshot = _snapshot(
        namespaces=("capability_registry",),
        facts=(fact,),
    )

    satisfied = CapabilityEffectiveStateRuleV1().evaluate(desired, snapshot)
    assert satisfied.status is DesiredStateEvaluationStatus.SATISFIED

    unknown_fact = replace(
        fact,
        value_json={
            **fact.value_json,
            "effective_known": False,
            "effective_enabled": None,
        },
    )
    unknown = CapabilityEffectiveStateRuleV1().evaluate(
        desired,
        _snapshot(
            namespaces=("capability_registry",),
            facts=(unknown_fact,),
        ),
    )
    assert unknown.status is DesiredStateEvaluationStatus.UNKNOWN
    assert unknown.reason_codes == ("capability_effective_state_unknown",)


def test_durable_work_rule_handles_terminal_requirement_deterministically() -> None:
    desired = _desired(
        rule_key="durable_work",
        target_namespace="work",
        target_identity="work_123",
        expected={
            "acceptable_states": ["completed"],
            "require_terminal": True,
        },
        required=("work",),
    )
    completed = _fact(
        namespace="work",
        target_namespace="work",
        target_identity="work_123",
        value={
            "state": "completed",
            "terminal": True,
            "version": 4,
            "steps": [],
        },
        source_key="work_portfolio",
    )
    running = replace(
        completed,
        source_version_or_digest=DIGEST_B,
        value_json={
            "state": "running",
            "terminal": False,
            "version": 3,
            "steps": [],
        },
    )

    satisfied = DurableWorkRuleV1().evaluate(
        desired,
        _snapshot(namespaces=("work",), facts=(completed,)),
    )
    assert satisfied.status is DesiredStateEvaluationStatus.SATISFIED
    assert satisfied.reason_codes == ("work_obligation_satisfied",)

    violated = DurableWorkRuleV1().evaluate(
        desired,
        _snapshot(namespaces=("work",), facts=(running,)),
    )
    assert violated.status is DesiredStateEvaluationStatus.VIOLATED
    assert violated.reason_codes == ("work_state_not_acceptable",)


def test_unsupported_numeric_tolerance_fails_to_unknown() -> None:
    desired = _component_desired(policy=StabilizationPolicyV1(numeric_tolerance=0.5))

    result = ComponentHealthRuleV1().evaluate(
        desired,
        _component_snapshot(state="healthy"),
    )

    assert result.status is DesiredStateEvaluationStatus.UNKNOWN
    assert result.reason_codes == ("numeric_tolerance_unsupported",)


def test_numeric_tolerance_hook_is_deterministic() -> None:
    assert numeric_within_tolerance(10.4, 10.0, 0.5) is True
    assert numeric_within_tolerance(10.6, 10.0, 0.5) is False

    with pytest.raises(ValueError):
        numeric_within_tolerance(10.0, 10.0, -0.1)


def test_stale_evaluation_cannot_apply_to_newer_desired_generation() -> None:
    rule = ComponentHealthRuleV1()
    desired_v1 = _component_desired(generation=1)
    desired_v2 = replace(
        desired_v1,
        generation=2,
        updated_at_epoch=NOW,
    )
    raw_v1 = rule.evaluate(
        desired_v1,
        _component_snapshot(state="healthy"),
    )

    with pytest.raises(DesiredStateRuleContractError, match="stale"):
        DesiredStateStabilizer().apply(desired_v2, raw_v1)


def test_transient_then_sustained_violation_stabilizes() -> None:
    desired = _component_desired(
        policy=StabilizationPolicyV1(
            required_consecutive_violations=2,
            minimum_violation_age_seconds=10.0,
        )
    )
    stabilizer = DesiredStateStabilizer()
    first_raw = ComponentHealthRuleV1().evaluate(
        desired,
        _component_snapshot(state="failed"),
    )
    first = stabilizer.apply(desired, first_raw)

    assert first.evaluation.status is DesiredStateEvaluationStatus.STABILIZING
    assert first.evaluation.consecutive_violations == 1
    assert first.cursor.violation_active is False

    second_snapshot = _component_snapshot(state="failed")
    second_snapshot = SystemStateSnapshotV1.create(
        evaluated_source_namespaces=second_snapshot.evaluated_source_namespaces,
        facts=second_snapshot.facts,
        source_errors=second_snapshot.source_errors,
        incomplete_namespaces=second_snapshot.incomplete_namespaces,
        started_at_epoch=NOW + 10,
        ended_at_epoch=NOW + 10,
    )
    second_raw = ComponentHealthRuleV1().evaluate(desired, second_snapshot)
    second = stabilizer.apply(
        desired,
        second_raw,
        previous=first.cursor,
    )

    assert second.evaluation.status is DesiredStateEvaluationStatus.VIOLATED
    assert second.evaluation.consecutive_violations == 2
    assert second.evaluation.first_violation_at_epoch == NOW
    assert second.cursor.violation_active is True


def test_unknown_breaks_consecutive_violation_progression() -> None:
    desired = _component_desired(
        policy=StabilizationPolicyV1(required_consecutive_violations=2)
    )
    stabilizer = DesiredStateStabilizer()
    violation = ComponentHealthRuleV1().evaluate(
        desired,
        _component_snapshot(state="failed"),
    )
    first = stabilizer.apply(desired, violation)

    unknown_snapshot = _component_snapshot(
        state="failed",
        incomplete=("health_registry",),
    )
    unknown_snapshot = SystemStateSnapshotV1.create(
        evaluated_source_namespaces=unknown_snapshot.evaluated_source_namespaces,
        facts=unknown_snapshot.facts,
        source_errors=unknown_snapshot.source_errors,
        incomplete_namespaces=unknown_snapshot.incomplete_namespaces,
        started_at_epoch=NOW + 1,
        ended_at_epoch=NOW + 1,
    )
    unknown_raw = ComponentHealthRuleV1().evaluate(
        desired,
        unknown_snapshot,
    )
    interrupted = stabilizer.apply(
        desired,
        unknown_raw,
        previous=first.cursor,
    )
    assert interrupted.evaluation.status is DesiredStateEvaluationStatus.UNKNOWN
    assert interrupted.cursor.consecutive_violations == 0

    next_snapshot = _component_snapshot(state="failed")
    next_snapshot = SystemStateSnapshotV1.create(
        evaluated_source_namespaces=next_snapshot.evaluated_source_namespaces,
        facts=next_snapshot.facts,
        source_errors=next_snapshot.source_errors,
        incomplete_namespaces=next_snapshot.incomplete_namespaces,
        started_at_epoch=NOW + 2,
        ended_at_epoch=NOW + 2,
    )
    next_raw = ComponentHealthRuleV1().evaluate(desired, next_snapshot)
    restarted = stabilizer.apply(
        desired,
        next_raw,
        previous=interrupted.cursor,
    )
    assert restarted.evaluation.status is DesiredStateEvaluationStatus.STABILIZING
    assert restarted.evaluation.consecutive_violations == 1


def test_stable_recovery_requires_configured_age() -> None:
    desired = _component_desired(
        policy=StabilizationPolicyV1(
            required_consecutive_violations=1,
            minimum_recovery_age_seconds=5.0,
        )
    )
    stabilizer = DesiredStateStabilizer()
    violated_raw = ComponentHealthRuleV1().evaluate(
        desired,
        _component_snapshot(state="failed"),
    )
    active = stabilizer.apply(desired, violated_raw)
    assert active.evaluation.status is DesiredStateEvaluationStatus.VIOLATED

    healthy_snapshot = _component_snapshot(state="healthy")
    healthy_snapshot = SystemStateSnapshotV1.create(
        evaluated_source_namespaces=healthy_snapshot.evaluated_source_namespaces,
        facts=healthy_snapshot.facts,
        source_errors=healthy_snapshot.source_errors,
        incomplete_namespaces=healthy_snapshot.incomplete_namespaces,
        started_at_epoch=NOW + 1,
        ended_at_epoch=NOW + 1,
    )
    recovering_raw = ComponentHealthRuleV1().evaluate(
        desired,
        healthy_snapshot,
    )
    recovering = stabilizer.apply(
        desired,
        recovering_raw,
        previous=active.cursor,
    )
    assert recovering.evaluation.status is DesiredStateEvaluationStatus.STABILIZING
    assert recovering.cursor.violation_active is True

    recovered_snapshot = _component_snapshot(state="healthy")
    recovered_snapshot = SystemStateSnapshotV1.create(
        evaluated_source_namespaces=recovered_snapshot.evaluated_source_namespaces,
        facts=recovered_snapshot.facts,
        source_errors=recovered_snapshot.source_errors,
        incomplete_namespaces=recovered_snapshot.incomplete_namespaces,
        started_at_epoch=NOW + 6,
        ended_at_epoch=NOW + 6,
    )
    recovered_raw = ComponentHealthRuleV1().evaluate(
        desired,
        recovered_snapshot,
    )
    recovered = stabilizer.apply(
        desired,
        recovered_raw,
        previous=recovering.cursor,
    )
    assert recovered.evaluation.status is DesiredStateEvaluationStatus.SATISFIED
    assert recovered.cursor.violation_active is False


def test_generation_change_resets_old_stabilization_cursor() -> None:
    policy = StabilizationPolicyV1(required_consecutive_violations=2)
    desired_v1 = _component_desired(generation=1, policy=policy)
    first_raw = ComponentHealthRuleV1().evaluate(
        desired_v1,
        _component_snapshot(state="failed"),
    )
    first = DesiredStateStabilizer().apply(desired_v1, first_raw)

    desired_v2 = replace(
        desired_v1,
        generation=2,
        updated_at_epoch=NOW,
    )
    snapshot_v2 = _component_snapshot(state="failed")
    snapshot_v2 = SystemStateSnapshotV1.create(
        evaluated_source_namespaces=snapshot_v2.evaluated_source_namespaces,
        facts=snapshot_v2.facts,
        source_errors=snapshot_v2.source_errors,
        incomplete_namespaces=snapshot_v2.incomplete_namespaces,
        started_at_epoch=NOW + 1,
        ended_at_epoch=NOW + 1,
    )
    raw_v2 = ComponentHealthRuleV1().evaluate(desired_v2, snapshot_v2)
    decision = DesiredStateStabilizer().apply(
        desired_v2,
        raw_v2,
        previous=first.cursor,
    )

    assert decision.evaluation.status is DesiredStateEvaluationStatus.STABILIZING
    assert decision.evaluation.consecutive_violations == 1
    assert decision.cursor.desired_generation == 2


def test_cooldown_policy_is_explicit_and_does_not_grant_authority() -> None:
    policy = StabilizationPolicyV1(cooldown_after_dispatch_seconds=30.0)

    assert cooldown_until_epoch(NOW, policy) == NOW + 30.0
    assert cooldown_is_active(
        now_epoch=NOW + 29,
        last_dispatch_at_epoch=NOW,
        policy=policy,
    )
    assert not cooldown_is_active(
        now_epoch=NOW + 30,
        last_dispatch_at_epoch=NOW,
        policy=policy,
    )

    desired = _component_desired(policy=policy)
    raw = ComponentHealthRuleV1().evaluate(
        desired,
        _component_snapshot(state="failed"),
    )
    decision = DesiredStateStabilizer().apply(
        desired,
        raw,
        last_dispatch_at_epoch=NOW - 10,
    )
    assert decision.cooldown_active is True
    assert decision.evaluation.cooldown_until_epoch == NOW + 20
    assert decision.evaluation.status is DesiredStateEvaluationStatus.VIOLATED


def test_objective_completion_aggregates_without_overriding_child_truth() -> None:
    health_desired = _component_desired()
    work_desired = _desired(
        rule_key="durable_work",
        target_namespace="work",
        target_identity="work_123",
        expected={"acceptable_states": ["completed"], "require_terminal": True},
        required=("work",),
    )
    health_eval = ComponentHealthRuleV1().evaluate(
        health_desired,
        _component_snapshot(state="healthy"),
    )
    work_fact = _fact(
        namespace="work",
        target_namespace="work",
        target_identity="work_123",
        value={"state": "completed", "terminal": True},
        source_key="work_portfolio",
    )
    work_eval = DurableWorkRuleV1().evaluate(
        work_desired,
        _snapshot(namespaces=("work",), facts=(work_fact,)),
    )

    completed = aggregate_objective_completion(
        objective_id="objective_phase10a_rules",
        objective_generation=1,
        desired_states=(work_desired, health_desired),
        evaluations=(health_eval, work_eval),
    )
    assert completed.status is DesiredStateEvaluationStatus.SATISFIED
    assert completed.reason_codes == ("objective_all_desired_states_satisfied",)

    unknown_work = replace(
        work_eval,
        status=DesiredStateEvaluationStatus.UNKNOWN,
        reason_codes=("required_source_incomplete",),
    )
    unknown = aggregate_objective_completion(
        objective_id="objective_phase10a_rules",
        objective_generation=1,
        desired_states=(health_desired, work_desired),
        evaluations=(health_eval, unknown_work),
    )
    assert unknown.status is DesiredStateEvaluationStatus.UNKNOWN


def test_objective_completion_rejects_stale_child_generation() -> None:
    desired = _component_desired(generation=2)
    stale_desired = replace(
        desired,
        generation=1,
        updated_at_epoch=NOW - 1,
    )
    stale = ComponentHealthRuleV1().evaluate(
        stale_desired,
        _component_snapshot(state="healthy"),
    )

    with pytest.raises(DesiredStateRuleContractError, match="stale"):
        aggregate_objective_completion(
            objective_id="objective_phase10a_rules",
            objective_generation=2,
            desired_states=(desired,),
            evaluations=(stale,),
        )
