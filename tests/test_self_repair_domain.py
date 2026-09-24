from __future__ import annotations

import pytest

from jarvis.self_model import HealthState
from jarvis.self_repair import (
    MAX_EVIDENCE_REFERENCES,
    RepairAction,
    RepairActionKind,
    RepairAttempt,
    RepairAuthorizationError,
    RepairExecutionContext,
    RepairPolicy,
    RepairPolicyConflictError,
    RepairPolicySnapshot,
    RepairPolicyError,
    RepairRegistry,
    RepairRiskClass,
    RepairTrigger,
    RepairVerdict,
    RepairVerificationResult,
    RepairVerificationStatus,
)


def _trigger(*, reason_code: str = "child_exited") -> RepairTrigger:
    return RepairTrigger.create(
        trigger_id="trigger-1",
        component_id=" Voice_Runtime ",
        reason_code=reason_code,
        source=" Dev_Supervisor ",
        health_state=HealthState.FAILED,
        process_exit_code=1,
        evidence_references=("incident:event:1",),
        correlation_id="corr-1",
        session_id="session-1",
        work_id="work-1",
        observed_at_epoch=100,
    )


def _restart_policy(
    *,
    policy_id: str = "runtime-child-exit-v1",
    reason_code: str = "child_exited",
) -> RepairPolicy:
    return RepairPolicy(
        policy_id=policy_id,
        version=1,
        trigger_source="dev_supervisor",
        component_id="voice_runtime",
        reason_code=reason_code,
        action_kind=RepairActionKind.RESTART_RUNTIME_CHILD,
        risk_class=RepairRiskClass.R2_RESTART,
        preconditions=("same_local_revision", "restart_budget_available"),
        max_attempts=3,
        rolling_window_seconds=300,
        cooldown_seconds=2,
        backoff_multiplier=2,
        verification_contract="runtime_ready_and_live",
        health_states=(HealthState.FAILED,),
        idempotent=False,
        reversible=True,
        automatic=True,
    )


def _verification(
    policy: RepairPolicy,
    status: RepairVerificationStatus,
    *,
    summary: str,
    now_epoch: float = 102,
) -> RepairVerificationResult:
    return RepairVerificationResult.create(
        verifier_id="test-verifier",
        verifier_version=1,
        contract_id=policy.verification_contract,
        status=status,
        summary=summary,
        evidence_references=("test:verification",),
        observed_at_epoch=now_epoch,
    )


def test_trigger_is_normalized_and_immutable() -> None:
    trigger = _trigger()

    assert trigger.component_id == "voice_runtime"
    assert trigger.reason_code == "child_exited"
    assert trigger.source == "dev_supervisor"
    assert trigger.evidence_references == ("incident:event:1",)

    with pytest.raises(AttributeError):
        trigger.reason_code = "different"  # type: ignore[misc]


def test_trigger_rejects_unbounded_evidence() -> None:
    references = tuple(
        f"evidence:{index}" for index in range(MAX_EVIDENCE_REFERENCES + 1)
    )

    with pytest.raises(ValueError, match="evidence references exceed"):
        RepairTrigger.create(
            component_id="voice_runtime",
            reason_code="child_exited",
            source="dev_supervisor",
            health_state=HealthState.FAILED,
            evidence_references=references,
        )


def test_registered_policy_matches_known_reason_and_authorizes_typed_action() -> None:
    trigger = _trigger()
    policy = _restart_policy()
    registry = RepairRegistry((policy,))

    assert registry.match(trigger) is policy

    action = registry.action_for(trigger, now_epoch=101)
    assert action is not None
    assert action.kind is RepairActionKind.RESTART_RUNTIME_CHILD
    assert action.risk_class is RepairRiskClass.R2_RESTART

    authorized = registry.assert_executable(
        trigger,
        action,
        execution_context=RepairExecutionContext(
            expected_revision="a" * 40,
            current_revision="a" * 40,
            restart_budget_available=True,
        ),
    )
    assert authorized is policy


def test_unknown_reason_returns_no_repair() -> None:
    registry = RepairRegistry((_restart_policy(),))

    assert registry.match(_trigger(reason_code="provider_quota_exhausted")) is None
    assert registry.action_for(_trigger(reason_code="provider_quota_exhausted")) is None


def test_unregistered_action_cannot_execute() -> None:
    trigger = _trigger()
    registry = RepairRegistry((_restart_policy(),))
    action = RepairAction(
        action_id="forged-action",
        policy_id="missing-policy",
        policy_version=1,
        trigger_id=trigger.trigger_id,
        component_id=trigger.component_id,
        kind=RepairActionKind.RESTART_RUNTIME_CHILD,
        risk_class=RepairRiskClass.R2_RESTART,
        created_at_epoch=101,
    )

    with pytest.raises(
        RepairAuthorizationError,
        match="unregistered policy",
    ):
        registry.assert_executable(
            trigger,
            action,
            execution_context=RepairExecutionContext(
                expected_revision="a" * 40,
                current_revision="a" * 40,
                restart_budget_available=True,
            ),
        )


def test_missing_precondition_fails_closed() -> None:
    trigger = _trigger()
    registry = RepairRegistry((_restart_policy(),))
    action = registry.action_for(trigger)
    assert action is not None

    with pytest.raises(
        RepairAuthorizationError,
        match="preconditions are not satisfied",
    ):
        registry.assert_executable(
            trigger,
            action,
            execution_context=RepairExecutionContext(
                expected_revision="a" * 40,
                current_revision="a" * 40,
                restart_budget_available=False,
            ),
        )


def test_invalid_policy_action_risk_pair_fails_closed() -> None:
    with pytest.raises(
        RepairPolicyError,
        match="requires risk",
    ):
        RepairPolicy(
            policy_id="bad-policy",
            version=1,
            trigger_source="subsystem",
            component_id="search",
            reason_code="connection_failed",
            action_kind=RepairActionKind.RETRY_OPERATION,
            risk_class=RepairRiskClass.R2_RESTART,
            preconditions=(),
            max_attempts=2,
            rolling_window_seconds=60,
            cooldown_seconds=1,
            backoff_multiplier=1,
            verification_contract="operation_succeeds",
            reversible=True,
        )


def test_non_reversible_automatic_policy_fails_closed() -> None:
    with pytest.raises(
        RepairPolicyError,
        match="reversible=True",
    ):
        RepairPolicy(
            policy_id="bad-reconnect",
            version=1,
            trigger_source="health_registry",
            component_id="camera",
            reason_code="connection_lost",
            action_kind=RepairActionKind.RECONNECT_SUBSYSTEM,
            risk_class=RepairRiskClass.R1_RETRY_RECONNECT,
            preconditions=(),
            max_attempts=2,
            rolling_window_seconds=60,
            cooldown_seconds=1,
            backoff_multiplier=1,
            verification_contract="camera_healthy",
            reversible=False,
            automatic=True,
        )


def test_ambiguous_policy_match_fails_closed() -> None:
    registry = RepairRegistry(
        (
            _restart_policy(policy_id="runtime-exit-a"),
            _restart_policy(policy_id="runtime-exit-b"),
        )
    )

    with pytest.raises(
        RepairPolicyConflictError,
        match="multiple repair policies matched",
    ):
        registry.match(_trigger())


def test_no_action_escalate_is_never_an_executable_effect() -> None:
    trigger = _trigger(reason_code="unknown_runtime_failure")
    policy = RepairPolicy(
        policy_id="unknown-runtime-escalation",
        version=1,
        trigger_source="dev_supervisor",
        component_id="voice_runtime",
        reason_code="unknown_runtime_failure",
        action_kind=RepairActionKind.NO_ACTION_ESCALATE,
        risk_class=RepairRiskClass.R0_OBSERVE,
        preconditions=(),
        max_attempts=1,
        rolling_window_seconds=60,
        cooldown_seconds=0,
        backoff_multiplier=1,
        verification_contract="owner_or_diagnostics_review",
        reversible=False,
        automatic=False,
    )
    registry = RepairRegistry((policy,))
    action = registry.action_for(trigger)
    assert action is not None

    with pytest.raises(
        RepairAuthorizationError,
        match="not an executable repair effect",
    ):
        registry.assert_executable(
            trigger,
            action,
            execution_context=RepairExecutionContext(),
        )


def test_successful_execution_does_not_imply_recovered_verdict() -> None:
    trigger = _trigger()
    policy = _restart_policy()
    action = RepairAction.create(policy, trigger, now_epoch=101)
    attempt = RepairAttempt.start(
        incident_id="incident-1",
        trigger=trigger,
        policy=policy,
        action=action,
        attempt_number=1,
        now_epoch=101,
    )

    completed = attempt.complete(
        execution_result="child process started",
        verification=_verification(
            policy,
            RepairVerificationStatus.FAIL,
            summary="readiness probe failed",
        ),
        post_repair_evidence=("health:voice_runtime:failed",),
        next_retry_eligible_epoch=105,
        now_epoch=102,
    )

    assert completed.execution_result == "child process started"
    assert completed.verdict is RepairVerdict.NOT_RECOVERED
    assert completed.recovered is False


def test_only_recovered_verdict_marks_attempt_recovered() -> None:
    trigger = _trigger()
    policy = _restart_policy()
    action = RepairAction.create(policy, trigger, now_epoch=101)
    attempt = RepairAttempt.start(
        incident_id="incident-1",
        trigger=trigger,
        policy=policy,
        action=action,
        attempt_number=1,
        now_epoch=101,
    )

    recovered = attempt.complete(
        execution_result="child process started",
        verification=_verification(
            policy,
            RepairVerificationStatus.PASS,
            summary="readiness and liveness stable",
        ),
        now_epoch=102,
    )

    assert recovered.recovered is True


def test_trigger_rejects_non_integer_exit_code() -> None:
    with pytest.raises(TypeError, match="process_exit_code"):
        RepairTrigger.create(
            component_id="voice_runtime",
            reason_code="child_exited",
            source="dev_supervisor",
            health_state=HealthState.FAILED,
            process_exit_code="1",  # type: ignore[arg-type]
        )


def test_attempt_rejects_action_from_different_policy() -> None:
    trigger = _trigger()
    policy = _restart_policy()
    other_policy = _restart_policy(
        policy_id="different-policy",
        reason_code="different_reason",
    )
    action = RepairAction(
        action_id="wrong-policy-action",
        policy_id=other_policy.policy_id,
        policy_version=other_policy.version,
        trigger_id=trigger.trigger_id,
        component_id=trigger.component_id,
        kind=RepairActionKind.RESTART_RUNTIME_CHILD,
        risk_class=RepairRiskClass.R2_RESTART,
        created_at_epoch=101,
    )

    with pytest.raises(
        RepairAuthorizationError,
        match="different policy",
    ):
        RepairAttempt.start(
            incident_id="incident-1",
            trigger=trigger,
            policy=policy,
            action=action,
            attempt_number=1,
            now_epoch=101,
        )


def test_verification_contract_mismatch_cannot_mark_recovery() -> None:
    trigger = _trigger()
    policy = _restart_policy()
    action = RepairAction.create(policy, trigger, now_epoch=101)
    attempt = RepairAttempt.start(
        incident_id="incident-1",
        trigger=trigger,
        policy=policy,
        action=action,
        attempt_number=1,
        now_epoch=101,
    )
    wrong = RepairVerificationResult.create(
        verifier_id="test-verifier",
        verifier_version=1,
        contract_id="different_contract",
        status=RepairVerificationStatus.PASS,
        summary="looks healthy",
        observed_at_epoch=102,
    )

    with pytest.raises(ValueError, match="verification contract"):
        attempt.complete(
            execution_result="child process started",
            verification=wrong,
            now_epoch=102,
        )


def test_policy_snapshot_digest_is_stable_across_json_roundtrip() -> None:
    policy = _restart_policy()
    snapshot = RepairPolicySnapshot.from_policy(policy)
    restored = RepairPolicySnapshot.from_payload(snapshot.to_payload())

    assert restored == snapshot
    assert restored.digest == snapshot.digest
