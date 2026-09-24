from __future__ import annotations

from jarvis.incidents import IncidentService, SqliteIncidentStore
from jarvis.self_model import HealthState
from jarvis.self_repair import RepairActionKind, RepairTrigger, RepairVerdict
from jarvis.self_repair.supervisor import (
    CrashFingerprint,
    SupervisorFailurePhase,
    SupervisorRepairController,
    build_runtime_child_exit_policy,
    build_runtime_liveness_policy,
)


def _controller(
    path,
    *,
    max_attempts: int = 3,
    window: float = 300,
    cooldown: float = 2,
    backoff: float = 2,
):
    store = SqliteIncidentStore(path)
    service = IncidentService(store)
    policy = build_runtime_child_exit_policy(
        max_attempts=max_attempts,
        rolling_window_seconds=window,
        cooldown_seconds=cooldown,
        backoff_multiplier=backoff,
    )
    return store, SupervisorRepairController(service, policy=policy)


def test_crash_fingerprint_is_deterministic_and_commit_scoped() -> None:
    first = CrashFingerprint.create(
        exit_code=1,
        phase=SupervisorFailurePhase.RUNTIME,
        reason_code="unexpected_child_exit",
        component_ids=("voice_runtime",),
        commit_sha="A" * 40,
    )
    repeated = CrashFingerprint.create(
        exit_code=1,
        phase=SupervisorFailurePhase.RUNTIME,
        reason_code=" Unexpected_Child_Exit ",
        component_ids=("VOICE_RUNTIME",),
        commit_sha="a" * 40,
    )
    different_revision = CrashFingerprint.create(
        exit_code=1,
        phase=SupervisorFailurePhase.RUNTIME,
        reason_code="unexpected_child_exit",
        component_ids=("voice_runtime",),
        commit_sha="b" * 40,
    )

    assert first == repeated
    assert first.fingerprint_id == repeated.fingerprint_id
    assert first.fingerprint_id != different_revision.fingerprint_id
    assert first.evidence_reference.startswith("crash_fingerprint:")


def test_restart_budget_survives_store_reopen_and_exhausts(tmp_path) -> None:
    path = tmp_path / "incidents.sqlite3"
    store, controller = _controller(
        path,
        max_attempts=2,
        window=60,
        cooldown=2,
        backoff=2,
    )

    first_plan = controller.plan_unexpected_exit(
        exit_code=7,
        commit_sha="a" * 40,
        now_epoch=100,
    )
    assert first_plan.budget.allowed is True
    assert first_plan.budget.attempt_number == 1
    assert first_plan.budget.budget_index == 1
    assert first_plan.budget.wait_seconds == 2

    first = controller.start_attempt(first_plan, now_epoch=102)
    controller.complete_attempt(
        first_plan,
        first,
        execution_result="same-version child restart started",
        verifier_result="startup readiness confirmed; liveness pending",
        verdict=RepairVerdict.INCONCLUSIVE,
        now_epoch=103,
    )
    incident_id = first_plan.incident.incident_id
    store.close()

    reopened_store, reopened = _controller(
        path,
        max_attempts=2,
        window=60,
        cooldown=2,
        backoff=2,
    )
    second_plan = reopened.plan_unexpected_exit(
        exit_code=7,
        commit_sha="a" * 40,
        now_epoch=104,
    )

    assert second_plan.incident.incident_id == incident_id
    assert second_plan.budget.attempt_number == 2
    assert second_plan.budget.budget_index == 2
    assert second_plan.budget.wait_seconds == 3

    second = reopened.start_attempt(second_plan, now_epoch=107)
    reopened.complete_attempt(
        second_plan,
        second,
        execution_result="same-version child restart started",
        verifier_result="startup readiness failed",
        verdict=RepairVerdict.NOT_RECOVERED,
        now_epoch=108,
    )

    exhausted = reopened.plan_unexpected_exit(
        exit_code=7,
        commit_sha="a" * 40,
        now_epoch=109,
    )
    assert exhausted.exhausted is True
    assert exhausted.action is None
    assert exhausted.budget.recent_attempts == 2

    incident = reopened_store.get(incident_id)
    assert incident is not None
    assert any(
        evidence.kind == "repair_budget_exhausted" for evidence in incident.evidence
    )
    reopened_store.close()


def test_budget_resets_after_rolling_window_without_reusing_attempt_number(
    tmp_path,
) -> None:
    store, controller = _controller(
        tmp_path / "incidents.sqlite3",
        max_attempts=1,
        window=10,
        cooldown=2,
        backoff=2,
    )
    first_plan = controller.plan_unexpected_exit(
        exit_code=3,
        commit_sha="a" * 40,
        now_epoch=100,
    )
    first = controller.start_attempt(first_plan, now_epoch=102)
    controller.complete_attempt(
        first_plan,
        first,
        execution_result="restart started",
        verifier_result="readiness confirmed",
        verdict=RepairVerdict.INCONCLUSIVE,
        now_epoch=103,
    )

    reset = controller.plan_unexpected_exit(
        exit_code=3,
        commit_sha="a" * 40,
        now_epoch=120,
    )
    assert reset.budget.allowed is True
    assert reset.budget.budget_index == 1
    assert reset.budget.attempt_number == 2
    assert reset.budget.wait_seconds == 2
    store.close()


def test_provider_quota_does_not_match_runtime_restart_policy(tmp_path) -> None:
    store, controller = _controller(tmp_path / "incidents.sqlite3")
    trigger = RepairTrigger.create(
        component_id="voice_runtime",
        reason_code="provider_quota_exhausted",
        source="dev_supervisor",
        health_state=HealthState.DEGRADED,
        observed_at_epoch=100,
    )

    assert controller.registry.match(trigger) is None
    store.close()


def test_verified_recovery_does_not_forgive_restart_storm_history(
    tmp_path,
) -> None:
    store, controller = _controller(
        tmp_path / "incidents.sqlite3",
        max_attempts=1,
        window=300,
        cooldown=2,
        backoff=2,
    )
    first_plan = controller.plan_unexpected_exit(
        exit_code=5,
        commit_sha="a" * 40,
        now_epoch=100,
    )
    first = controller.start_attempt(first_plan, now_epoch=102)
    controller.complete_attempt(
        first_plan,
        first,
        execution_result="same-version child restart stabilized",
        verifier_result="readiness_and_liveness_stable:4_probes",
        verdict=RepairVerdict.RECOVERED,
        now_epoch=112,
    )

    blocked = controller.plan_unexpected_exit(
        exit_code=5,
        commit_sha="a" * 40,
        now_epoch=120,
    )

    assert blocked.budget.allowed is False
    assert blocked.budget.exhausted is True
    assert blocked.action is None
    assert blocked.budget.recent_attempts == 1
    store.close()


def test_liveness_failure_has_distinct_policy_and_incident(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    service = IncidentService(store)
    controller = SupervisorRepairController(
        service,
        policy=build_runtime_child_exit_policy(
            max_attempts=1,
            cooldown_seconds=0,
        ),
        additional_policies=(
            build_runtime_liveness_policy(
                max_attempts=1,
                cooldown_seconds=0,
            ),
        ),
    )

    plan = controller.plan_liveness_failure(
        commit_sha="a" * 40,
        now_epoch=100,
    )

    assert plan.policy.policy_id == "supervisor-runtime-unresponsive-v1"
    assert plan.trigger.reason_code == "runtime_unresponsive"
    assert plan.trigger.process_exit_code is None
    assert plan.incident.title == "JARVIS runtime became unresponsive"
    assert plan.action is not None
    assert plan.action.kind is RepairActionKind.RESTART_RUNTIME_CHILD
    store.close()


def test_shared_restart_circuit_breaker_spans_crash_and_liveness(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    service = IncidentService(store)
    controller = SupervisorRepairController(
        service,
        policy=build_runtime_child_exit_policy(
            max_attempts=1,
            cooldown_seconds=0,
        ),
        additional_policies=(
            build_runtime_liveness_policy(
                max_attempts=1,
                cooldown_seconds=0,
            ),
        ),
    )

    crash_plan = controller.plan_unexpected_exit(
        exit_code=9,
        commit_sha="a" * 40,
        now_epoch=100,
    )
    crash_attempt = controller.start_attempt(crash_plan, now_epoch=100)
    controller.complete_attempt(
        crash_plan,
        crash_attempt,
        execution_result="restart failed",
        verifier_result="startup_readiness_failed",
        verdict=RepairVerdict.NOT_RECOVERED,
        now_epoch=101,
    )

    liveness_plan = controller.plan_liveness_failure(
        commit_sha="a" * 40,
        now_epoch=102,
    )

    assert liveness_plan.exhausted is True
    assert liveness_plan.action is None
    assert liveness_plan.budget.recent_attempts == 1
    store.close()


def test_shared_restart_circuit_breaker_spans_crash_fingerprints(tmp_path) -> None:
    store, controller = _controller(
        tmp_path / "incidents.sqlite3",
        max_attempts=1,
        window=300,
        cooldown=0,
    )

    first_plan = controller.plan_unexpected_exit(
        exit_code=7,
        commit_sha="a" * 40,
        now_epoch=100,
    )
    first = controller.start_attempt(first_plan, now_epoch=100)
    controller.complete_attempt(
        first_plan,
        first,
        execution_result="restart failed",
        verifier_result="startup_readiness_failed",
        verdict=RepairVerdict.NOT_RECOVERED,
        now_epoch=101,
    )

    different_fingerprint = controller.plan_unexpected_exit(
        exit_code=8,
        commit_sha="a" * 40,
        now_epoch=102,
    )

    assert different_fingerprint.incident.incident_id != first_plan.incident.incident_id
    assert different_fingerprint.exhausted is True
    assert different_fingerprint.action is None
    assert different_fingerprint.budget.recent_attempts == 1
    store.close()
