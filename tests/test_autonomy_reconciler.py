from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from jarvis.autonomy.dispatch import (
    AutonomyDispatchConfigV1,
    AutonomyDispatchService,
    DispatchBridgeRegistry,
)
from jarvis.autonomy.findings import FindingLifecycleManager
from jarvis.autonomy.models import (
    AutonomyMode,
    CandidateDisposition,
    DesiredStateStatus,
    DesiredStateV1,
    FindingStatus,
    ObjectiveOrigin,
    ObjectiveStatus,
    ObjectiveV1,
    ReconcileStatus,
    ReconcileTrigger,
    StabilizationPolicyV1,
)
from jarvis.autonomy.portfolio import PortfolioPrioritizer
from jarvis.autonomy.reconciler import AutonomyReconciler, PeriodicAutonomyReconciler
from jarvis.autonomy.resolution import (
    ActionResolutionService,
    build_default_action_resolver_registry,
)
from jarvis.autonomy.rules import (
    DesiredStateEvaluationStatus,
    DesiredStateEvaluator,
    DesiredStateStabilizer,
    build_default_desired_state_rule_registry,
)
from jarvis.autonomy.store import AutonomyStore
from jarvis.autonomy.system_state import (
    SystemStateAggregator,
    SystemStateFactV1,
    SystemStateReadRequestV1,
    SystemStateSourceRegistry,
    SystemStateSourceResultV1,
    SystemStateSourceStatus,
)
from jarvis.work.models import WorkPriority
from jarvis.work.store import SQLiteWorkStore

DIGEST = "a" * 64


@dataclass
class _Clock:
    value: float = 1_800_000_000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float = 1.0) -> None:
        self.value += seconds


class _ComponentSource:
    source_key = "test.component"
    source_version = 1
    namespaces = ("health_registry", "self_model")

    def __init__(self, clock: _Clock, *, state: str = "healthy") -> None:
        self.clock = clock
        self.state = state

    def read(
        self,
        request: SystemStateReadRequestV1,
    ) -> SystemStateSourceResultV1:
        facts: list[SystemStateFactV1] = []
        targets = tuple(
            item for item in request.targets if item.target_namespace == "component"
        )
        for target in targets:
            if "self_model" in request.requested_namespaces:
                facts.append(
                    SystemStateFactV1(
                        fact_namespace="self_model",
                        source_identity=f"component:{target.target_identity}",
                        source_version_or_digest=DIGEST,
                        target_namespace="component",
                        target_identity=target.target_identity,
                        value_json={"component_id": target.target_identity},
                        observed_at_epoch=self.clock(),
                        evidence_references=(f"component:{target.target_identity}",),
                        source_adapter_key=self.source_key,
                        source_adapter_version=self.source_version,
                        fresh_until_epoch=self.clock() + 60,
                    )
                )
            if "health_registry" in request.requested_namespaces:
                facts.append(
                    SystemStateFactV1(
                        fact_namespace="health_registry",
                        source_identity=f"health:{target.target_identity}",
                        source_version_or_digest=DIGEST,
                        target_namespace="component",
                        target_identity=target.target_identity,
                        value_json={"state": self.state},
                        observed_at_epoch=self.clock(),
                        evidence_references=(f"health:{target.target_identity}",),
                        source_adapter_key=self.source_key,
                        source_adapter_version=self.source_version,
                        fresh_until_epoch=self.clock() + 60,
                    )
                )
        return SystemStateSourceResultV1(
            source_adapter_key=self.source_key,
            source_adapter_version=self.source_version,
            status=SystemStateSourceStatus.COMPLETE,
            facts=tuple(facts),
        )


def _objective() -> ObjectiveV1:
    return ObjectiveV1(
        objective_id="objective_runtime_health",
        origin=ObjectiveOrigin.REGISTERED_SYSTEM_OBLIGATION,
        source_identity="registered:runtime-health:v1",
        title="Keep runtime healthy",
        description="Keep the reviewed runtime component healthy.",
        priority=WorkPriority.HIGH,
        status=ObjectiveStatus.ACTIVE,
        horizon="continuous",
        constraint_json={},
        created_at_epoch=1_799_999_000.0,
        updated_at_epoch=1_799_999_000.0,
    )


def _desired(objective: ObjectiveV1) -> DesiredStateV1:
    return DesiredStateV1(
        desired_state_id="desired_runtime_health",
        objective_id=objective.objective_id,
        target_namespace="component",
        target_identity="runtime.test",
        rule_key="component_health",
        rule_version=1,
        expected_json={"acceptable_states": ["healthy"]},
        required_source_namespaces=("health_registry", "self_model"),
        stabilization_policy=StabilizationPolicyV1(
            required_consecutive_violations=2,
            minimum_violation_age_seconds=0,
            minimum_recovery_age_seconds=0,
            cooldown_after_dispatch_seconds=0,
        ),
        generation=1,
        status=DesiredStateStatus.ACTIVE,
        provenance_source_identity=objective.source_identity,
        created_at_epoch=1_799_999_000.0,
        updated_at_epoch=1_799_999_000.0,
    )


def _build(
    tmp_path: Path,
    *,
    clock: _Clock | None = None,
    priority_factor_provider=None,
    recovery_age_seconds: float = 0.0,
) -> tuple[
    AutonomyReconciler,
    AutonomyStore,
    _ComponentSource,
    _Clock,
]:
    resolved_clock = clock or _Clock()
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = AutonomyStore(work)
    objective = _objective()
    desired = _desired(objective)
    if recovery_age_seconds:
        desired = replace(
            desired,
            stabilization_policy=replace(
                desired.stabilization_policy,
                minimum_recovery_age_seconds=recovery_age_seconds,
            ),
        )
    store.create_objective(objective)
    store.create_desired_state(desired)
    source = _ComponentSource(resolved_clock)
    aggregator = SystemStateAggregator(
        SystemStateSourceRegistry((source,)),
        clock=resolved_clock,
    )
    reconciler = AutonomyReconciler(
        store=store,
        aggregator=aggregator,
        evaluator=DesiredStateEvaluator(build_default_desired_state_rule_registry()),
        stabilizer=DesiredStateStabilizer(),
        findings=FindingLifecycleManager(store),
        resolution=ActionResolutionService(
            store,
            build_default_action_resolver_registry(),
        ),
        portfolio=PortfolioPrioritizer(),
        dispatch=AutonomyDispatchService(
            store=store,
            registrations=DispatchBridgeRegistry(),
            config=AutonomyDispatchConfigV1(mode=AutonomyMode.SHADOW),
        ),
        priority_factor_provider=priority_factor_provider,
        clock=resolved_clock,
    )
    return reconciler, store, source, resolved_clock


def test_reconciler_quiet_violation_replay_and_recovery(tmp_path: Path) -> None:
    reconciler, store, source, clock = _build(tmp_path)

    healthy = reconciler.reconcile(
        "quiet-healthy",
        trigger=ReconcileTrigger.MANUAL_TEST,
    )
    assert healthy.status is ReconcileStatus.COMPLETED
    assert healthy.desired_results[0].evaluation_status is (
        DesiredStateEvaluationStatus.SATISFIED
    )
    assert healthy.desired_results[0].finding_id is None
    assert healthy.desired_results[0].candidate_id is None

    replay = reconciler.reconcile(
        "quiet-healthy",
        trigger=ReconcileTrigger.MANUAL_TEST,
    )
    assert replay.status is ReconcileStatus.REPLAY_NOOP
    assert replay.replayed is True

    source.state = "degraded"
    clock.advance()
    transient = reconciler.reconcile(
        "violation-1",
        trigger=ReconcileTrigger.STATE_CHANGE_HINT,
    )
    assert transient.desired_results[0].evaluation_status is (
        DesiredStateEvaluationStatus.STABILIZING
    )
    assert transient.desired_results[0].candidate_id is None

    clock.advance()
    sustained = reconciler.reconcile(
        "violation-2",
        trigger=ReconcileTrigger.PERIODIC,
    )
    result = sustained.desired_results[0]
    assert result.evaluation_status is DesiredStateEvaluationStatus.VIOLATED
    assert result.finding_status is not None
    assert result.candidate_id is not None
    assert result.dispatch_disposition is CandidateDisposition.SHADOW_ONLY

    candidate_id = result.candidate_id
    assert candidate_id is not None
    with sqlite3.connect(store.path) as db:
        candidate_count = db.execute(
            "SELECT COUNT(*) FROM autonomy_action_candidates"
        ).fetchone()[0]
        dispatch_count = db.execute(
            """
            SELECT COUNT(*) FROM autonomy_dispatch_links
            WHERE downstream_kind != 'dispatch_intent'
            """
        ).fetchone()[0]
    assert candidate_count == 1
    assert dispatch_count == 0

    replay_violation = reconciler.reconcile(
        "violation-2",
        trigger=ReconcileTrigger.PERIODIC,
    )
    assert replay_violation.replayed is True
    with sqlite3.connect(store.path) as db:
        assert (
            db.execute("SELECT COUNT(*) FROM autonomy_action_candidates").fetchone()[0]
            == 1
        )

    source.state = "healthy"
    clock.advance()
    recovered = reconciler.reconcile(
        "recovered",
        trigger=ReconcileTrigger.STATE_CHANGE_HINT,
    )
    recovered_result = recovered.desired_results[0]
    assert recovered_result.evaluation_status is (
        DesiredStateEvaluationStatus.SATISFIED
    )
    assert recovered_result.finding_status is FindingStatus.RESOLVED
    assert store.require_action_candidate(candidate_id).candidate_id == candidate_id


def test_reconcile_failure_is_retryable_with_same_token(tmp_path: Path) -> None:
    fail = {"value": False}

    def factors(objective, desired, finding):
        if fail["value"]:
            raise RuntimeError("synthetic priority failure")
        from jarvis.autonomy.portfolio import PriorityFactorsV1

        return PriorityFactorsV1(
            owner_priority=objective.priority,
            obligation_criticality=0,
            deadline_urgency=0,
            impact_scope=0,
            dependency_unblocking=0,
            starvation_age=0,
            resource_feasibility=0,
            provenance_json={
                "owner_priority": "objective.priority",
                "obligation_criticality": "test",
                "deadline_urgency": "test",
                "impact_scope": "test",
                "dependency_unblocking": "test",
                "starvation_age": "test",
                "resource_feasibility": "test",
            },
        )

    reconciler, store, source, clock = _build(
        tmp_path,
        priority_factor_provider=factors,
    )
    source.state = "degraded"
    reconciler.reconcile("prime-1", trigger=ReconcileTrigger.MANUAL_TEST)
    clock.advance()
    fail["value"] = True
    with pytest.raises(RuntimeError, match="synthetic priority failure"):
        reconciler.reconcile(
            "retryable-token",
            trigger=ReconcileTrigger.MANUAL_TEST,
        )
    failed = store.require_reconcile_run_by_token("retryable-token")
    assert failed.status is ReconcileStatus.FAILED
    assert failed.handled_token is None

    fail["value"] = False
    clock.advance()
    retried = reconciler.reconcile(
        "retryable-token",
        trigger=ReconcileTrigger.MANUAL_TEST,
    )
    assert retried.status is ReconcileStatus.COMPLETED
    completed = store.require_reconcile_run_by_token("retryable-token")
    assert completed.status is ReconcileStatus.COMPLETED
    assert completed.handled_token == "retryable-token"


def test_reconcile_single_run_lock_returns_busy_without_state_change(
    tmp_path: Path,
) -> None:
    reconciler, store, _, _ = _build(tmp_path)
    assert reconciler._lock.acquire(blocking=False)
    try:
        result = reconciler.reconcile(
            "concurrent-trigger",
            trigger=ReconcileTrigger.STATE_CHANGE_HINT,
        )
    finally:
        reconciler._lock.release()

    assert result.busy is True
    with pytest.raises(KeyError):
        store.require_reconcile_run_by_token("concurrent-trigger")


def test_restart_reconstructs_stabilization_without_duplicate_candidate(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    reconciler, store, source, _ = _build(tmp_path, clock=clock)
    source.state = "degraded"
    reconciler.reconcile("restart-1", trigger=ReconcileTrigger.MANUAL_TEST)
    clock.advance()
    active = reconciler.reconcile(
        "restart-2",
        trigger=ReconcileTrigger.MANUAL_TEST,
    )
    candidate_id = active.desired_results[0].candidate_id
    assert candidate_id is not None

    restarted = AutonomyReconciler(
        store=store,
        aggregator=reconciler.aggregator,
        evaluator=reconciler.evaluator,
        stabilizer=DesiredStateStabilizer(),
        findings=FindingLifecycleManager(store),
        resolution=ActionResolutionService(
            store,
            build_default_action_resolver_registry(),
        ),
        portfolio=PortfolioPrioritizer(),
        dispatch=reconciler.dispatch,
        clock=clock,
    )
    clock.advance()
    again = restarted.reconcile(
        "restart-3",
        trigger=ReconcileTrigger.STARTUP,
    )
    assert again.desired_results[0].candidate_id == candidate_id
    with sqlite3.connect(store.path) as db:
        assert (
            db.execute("SELECT COUNT(*) FROM autonomy_action_candidates").fetchone()[0]
            == 1
        )


def test_restart_preserves_original_recovery_stabilization_clock(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    reconciler, store, source, _ = _build(
        tmp_path,
        clock=clock,
        recovery_age_seconds=10.0,
    )
    source.state = "degraded"
    reconciler.reconcile("recovery-restart-1", trigger=ReconcileTrigger.MANUAL_TEST)
    clock.advance()
    active = reconciler.reconcile(
        "recovery-restart-2",
        trigger=ReconcileTrigger.MANUAL_TEST,
    )
    assert active.desired_results[0].finding_status is FindingStatus.ACTIVE

    source.state = "healthy"
    clock.advance()
    recovering = reconciler.reconcile(
        "recovery-restart-3",
        trigger=ReconcileTrigger.STATE_CHANGE_HINT,
    )
    assert recovering.desired_results[0].evaluation_status is (
        DesiredStateEvaluationStatus.STABILIZING
    )

    clock.advance(4)
    still_recovering = reconciler.reconcile(
        "recovery-restart-4",
        trigger=ReconcileTrigger.PERIODIC,
    )
    assert still_recovering.desired_results[0].evaluation_status is (
        DesiredStateEvaluationStatus.STABILIZING
    )

    restarted = AutonomyReconciler(
        store=store,
        aggregator=reconciler.aggregator,
        evaluator=reconciler.evaluator,
        stabilizer=DesiredStateStabilizer(),
        findings=FindingLifecycleManager(store),
        resolution=ActionResolutionService(
            store,
            build_default_action_resolver_registry(),
        ),
        portfolio=PortfolioPrioritizer(),
        dispatch=reconciler.dispatch,
        clock=clock,
    )
    clock.advance(6)
    recovered = restarted.reconcile(
        "recovery-restart-5",
        trigger=ReconcileTrigger.STARTUP,
    )
    assert recovered.desired_results[0].evaluation_status is (
        DesiredStateEvaluationStatus.SATISFIED
    )
    assert recovered.desired_results[0].finding_status is FindingStatus.RESOLVED


def test_periodic_wrapper_starts_sweeps_and_stops_cleanly(tmp_path: Path) -> None:
    reconciler, store, _, _ = _build(tmp_path)
    periodic = PeriodicAutonomyReconciler(
        reconciler,
        interval_seconds=0.02,
        instance_token="test-instance",
    )

    periodic.start()
    time.sleep(0.07)
    periodic.stop(timeout_seconds=1.0)

    assert periodic.running is False
    with sqlite3.connect(store.path) as db:
        run_count = db.execute(
            "SELECT COUNT(*) FROM autonomy_reconcile_runs"
        ).fetchone()[0]
    assert run_count >= 2


def test_off_mode_performs_no_control_plane_persistence(tmp_path: Path) -> None:
    reconciler, store, _, _ = _build(tmp_path)
    reconciler.dispatch.config = AutonomyDispatchConfigV1(mode=AutonomyMode.OFF)

    result = reconciler.reconcile(
        "off-mode",
        trigger=ReconcileTrigger.MANUAL_TEST,
    )

    assert result.status is ReconcileStatus.REPLAY_NOOP
    with pytest.raises(KeyError):
        store.require_reconcile_run_by_token("off-mode")
