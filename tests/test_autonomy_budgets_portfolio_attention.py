from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.autonomy.attention import (
    OwnerAttentionDeliveryAdapter,
    OwnerAttentionManager,
    attention_fingerprint_for,
)
from jarvis.autonomy.budgets import (
    BUDGET_DIMENSION_NEW_WORK,
    AutonomyBudgetEvaluator,
    AutonomyBudgetLedger,
    BudgetUsageV1,
)
from jarvis.autonomy.models import (
    ActionCandidateV1,
    ActionKind,
    AttentionStatus,
    AutonomyBudgetPolicyV1,
    AutonomyFindingV1,
    AutonomyMode,
    CandidateDisposition,
    DesiredStateStatus,
    DesiredStateV1,
    FindingStatus,
    ObjectiveOrigin,
    ObjectiveStatus,
    ObjectiveV1,
    StabilizationPolicyV1,
)
from jarvis.autonomy.portfolio import (
    PortfolioInputV1,
    PortfolioPrioritizer,
    PriorityFactorsV1,
)
from jarvis.autonomy.store import AutonomyIntegrityError, AutonomyStore
from jarvis.work.models import WorkPriority
from jarvis.work.store import SQLiteWorkStore

NOW = 1_800_000_000.0
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _objective(
    *,
    objective_id: str = "objective_10a5",
    priority: WorkPriority = WorkPriority.HIGH,
) -> ObjectiveV1:
    return ObjectiveV1(
        objective_id=objective_id,
        origin=ObjectiveOrigin.OWNER,
        source_identity=f"owner:{objective_id}",
        title="Protect owner intent",
        description="Phase 10A.5 deterministic portfolio test.",
        priority=priority,
        status=ObjectiveStatus.ACTIVE,
        horizon="continuous",
        constraint_json={"criticality": "high"},
        created_at_epoch=NOW - 100,
        updated_at_epoch=NOW - 100,
    )


def _desired(objective: ObjectiveV1) -> DesiredStateV1:
    return DesiredStateV1(
        desired_state_id=f"desired_{objective.objective_id}",
        objective_id=objective.objective_id,
        target_namespace="component",
        target_identity="jarvis.core",
        rule_key="component_health",
        rule_version=1,
        expected_json={"acceptable_states": ["healthy"]},
        required_source_namespaces=("health_registry", "self_model"),
        stabilization_policy=StabilizationPolicyV1(),
        generation=1,
        status=DesiredStateStatus.ACTIVE,
        provenance_source_identity=objective.source_identity,
        created_at_epoch=NOW - 90,
        updated_at_epoch=NOW - 90,
    )


def _finding(desired: DesiredStateV1) -> AutonomyFindingV1:
    return AutonomyFindingV1(
        finding_id=f"finding_{desired.desired_state_id}",
        desired_state_id=desired.desired_state_id,
        desired_generation=desired.generation,
        target_namespace=desired.target_namespace,
        target_identity=desired.target_identity,
        finding_kind="state_gap",
        rule_key=desired.rule_key,
        rule_version=desired.rule_version,
        status=FindingStatus.ACTIVE,
        latest_snapshot_digest=DIGEST_A,
        first_seen_epoch=NOW - 30,
        last_seen_epoch=NOW,
        violation_count=3,
        reason_codes=("component_health_unacceptable",),
        supporting_fact_digests=(DIGEST_B,),
    )


def _candidate(
    finding: AutonomyFindingV1,
    *,
    candidate_id: str = "candidate_10a5",
    action_kind: ActionKind = ActionKind.WORK_ITEM,
    mode: AutonomyMode = AutonomyMode.SHADOW,
) -> ActionCandidateV1:
    return ActionCandidateV1(
        candidate_id=candidate_id,
        finding_id=finding.finding_id,
        desired_state_id=finding.desired_state_id,
        desired_generation=finding.desired_generation,
        action_kind=action_kind,
        resolver_key="phase10a5_test",
        resolver_version=1,
        expected_effect="Exercise deterministic Phase 10A.5 policy.",
        target_namespace=finding.target_namespace,
        target_identity=finding.target_identity,
        snapshot_digest=finding.latest_snapshot_digest,
        reversibility_class="fully_reversible",
        resource_class="background",
        cost_class="bounded",
        risk_json={"risk": "low"},
        dependencies=(),
        mode=mode,
        policy_reason_codes=("test",),
        created_at_epoch=NOW,
    )


def _policy() -> AutonomyBudgetPolicyV1:
    return AutonomyBudgetPolicyV1(
        policy_id="budget_test",
        max_concurrent_autonomous_work_items=2,
        max_new_autonomous_work_items_per_window=2,
        max_active_candidates_per_objective=3,
        max_repeat_dispatches_per_finding_window=2,
        max_owner_attention_notifications_per_window=2,
        window_seconds=3600,
    )


def _usage(**overrides) -> BudgetUsageV1:
    values = {
        "active_autonomous_work_items": 0,
        "new_autonomous_work_items_in_window": 0,
        "active_candidates_for_objective": 0,
        "repeated_dispatches_for_finding_window": 0,
        "owner_attention_notifications_in_window": 0,
        "provider_model_work_used": None,
        "urgent_root_attention_override": False,
    }
    values.update(overrides)
    return BudgetUsageV1(**values)


def _store(tmp_path: Path) -> AutonomyStore:
    return AutonomyStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))


def _seed_attention_chain(
    store: AutonomyStore,
) -> tuple[ObjectiveV1, DesiredStateV1, AutonomyFindingV1]:
    objective = _objective()
    desired = _desired(objective)
    finding = _finding(desired)
    store.create_objective(objective)
    store.create_desired_state(desired)
    store.create_finding(finding)
    return objective, desired, finding


def test_missing_budget_blocks_assisted_admission() -> None:
    objective = _objective()
    desired = _desired(objective)
    finding = _finding(desired)
    candidate = _candidate(finding, mode=AutonomyMode.ASSISTED)

    assessment = AutonomyBudgetEvaluator().evaluate(
        candidate,
        mode=AutonomyMode.ASSISTED,
        policy=None,
        usage=_usage(),
    )

    assert assessment.disposition is CandidateDisposition.BLOCKED_POLICY
    assert assessment.reason_codes == ("assisted_budget_policy_missing",)


def test_budget_exhaustion_creates_no_work(tmp_path: Path) -> None:
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    objective = _objective()
    desired = _desired(objective)
    finding = _finding(desired)
    candidate = _candidate(finding, mode=AutonomyMode.ASSISTED)

    assessment = AutonomyBudgetEvaluator().evaluate(
        candidate,
        mode=AutonomyMode.ASSISTED,
        policy=_policy(),
        usage=_usage(new_autonomous_work_items_in_window=2),
    )

    assert assessment.disposition is CandidateDisposition.DEFERRED_BUDGET
    assert "new_work_window_budget_exhausted" in assessment.reason_codes
    with sqlite3.connect(work_store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0


def test_provider_ceiling_never_invents_missing_metering() -> None:
    objective = _objective()
    finding = _finding(_desired(objective))
    candidate = _candidate(finding, mode=AutonomyMode.ASSISTED)
    policy = replace(_policy(), provider_model_work_ceiling=100.0)

    assessment = AutonomyBudgetEvaluator().evaluate(
        candidate,
        mode=AutonomyMode.ASSISTED,
        policy=policy,
        usage=_usage(provider_model_work_used=None),
    )

    assert assessment.disposition is CandidateDisposition.BLOCKED_POLICY
    assert assessment.reason_codes == ("provider_model_metering_unavailable",)


def test_budget_window_accounting_is_durable_and_integrity_checked(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    ledger = AutonomyBudgetLedger(store)
    policy = _policy()

    first = ledger.increment(
        policy,
        BUDGET_DIMENSION_NEW_WORK,
        now_epoch=NOW,
    )
    second = ledger.increment(
        policy,
        BUDGET_DIMENSION_NEW_WORK,
        now_epoch=NOW + 30,
    )

    assert first.used_value == 1
    assert first.version == 1
    assert second.used_value == 2
    assert second.version == 2
    assert ledger.read(
        policy,
        BUDGET_DIMENSION_NEW_WORK,
        now_epoch=NOW + 30,
    ) == second

    with store.work.extension_transaction() as db:
        db.execute(
            """
            UPDATE autonomy_budget_windows
            SET used_value=?
            WHERE policy_id=? AND dimension_key=? AND window_started_epoch=?
            """,
            (
                999,
                second.policy_id,
                second.dimension_key,
                second.window_started_epoch,
            ),
        )

    with pytest.raises(AutonomyIntegrityError, match="column mismatch"):
        ledger.read(
            policy,
            BUDGET_DIMENSION_NEW_WORK,
            now_epoch=NOW + 30,
        )


def _factors(
    priority: WorkPriority,
    *,
    criticality: int = 1,
    deadline: int = 1,
    impact: int = 1,
    unblock: int = 1,
    age: int = 1,
    feasibility: int = 1,
) -> PriorityFactorsV1:
    return PriorityFactorsV1(
        owner_priority=priority,
        obligation_criticality=criticality,
        deadline_urgency=deadline,
        impact_scope=impact,
        dependency_unblocking=unblock,
        starvation_age=age,
        resource_feasibility=feasibility,
        provenance_json={
            "owner_priority": "Objective.priority",
            "obligation_criticality": "registered obligation metadata",
            "deadline_urgency": "deadline bucket",
            "impact_scope": "current impact evidence",
            "dependency_unblocking": "dependency graph evidence",
            "starvation_age": "candidate age bucket",
            "resource_feasibility": "resource lease observation",
        },
    )


def test_portfolio_ordering_is_deterministic_and_owner_priority_is_preserved() -> None:
    high = _objective(objective_id="objective_high", priority=WorkPriority.HIGH)
    normal = _objective(
        objective_id="objective_normal",
        priority=WorkPriority.NORMAL,
    )
    high_candidate = _candidate(
        _finding(_desired(high)),
        candidate_id="candidate_high",
    )
    normal_candidate = _candidate(
        _finding(_desired(normal)),
        candidate_id="candidate_normal",
    )
    items = (
        PortfolioInputV1(
            candidate=normal_candidate,
            objective=normal,
            factors=_factors(
                normal.priority,
                criticality=3,
                deadline=3,
                impact=3,
            ),
        ),
        PortfolioInputV1(
            candidate=high_candidate,
            objective=high,
            factors=_factors(high.priority),
        ),
    )

    prioritizer = PortfolioPrioritizer()
    first = prioritizer.prioritize(items)
    second = prioritizer.prioritize(tuple(reversed(items)))

    assert tuple(item.candidate_id for item in first) == (
        "candidate_high",
        "candidate_normal",
    )
    assert tuple(item.candidate_id for item in second) == (
        "candidate_high",
        "candidate_normal",
    )
    assert first[0].work_priority is WorkPriority.HIGH
    assert first[1].work_priority is WorkPriority.NORMAL
    assert first[0].priority_factor_payload["owner_priority"] == int(
        WorkPriority.HIGH
    )


def test_portfolio_rejects_priority_factor_that_rewrites_owner_priority() -> None:
    objective = _objective(priority=WorkPriority.HIGH)
    candidate = _candidate(_finding(_desired(objective)))

    with pytest.raises(ValueError, match="preserve Objective priority"):
        PortfolioInputV1(
            candidate=candidate,
            objective=objective,
            factors=_factors(WorkPriority.NORMAL),
        )


def _attention_kwargs(
    objective: ObjectiveV1,
    finding: AutonomyFindingV1,
) -> dict:
    return {
        "objective_id": objective.objective_id,
        "finding_id": finding.finding_id,
        "candidate_id": None,
        "group_key": "runtime-health",
        "priority": objective.priority,
        "reason_codes": ("owner_decision_required",),
        "question": "Choose the protected recovery option.",
        "option_metadata_json": {"options": ["approve", "reject"]},
        "consequence_of_waiting": "The protected recovery remains blocked.",
    }


def test_repeated_same_attention_is_deduplicated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    objective, _, finding = _seed_attention_chain(store)
    manager = OwnerAttentionManager(store)
    kwargs = _attention_kwargs(objective, finding)

    first = manager.open_or_update(**kwargs, now_epoch=NOW)
    second = manager.open_or_update(**kwargs, now_epoch=NOW + 10)

    assert first.item.attention_id == second.item.attention_id
    assert second.deduplicated is True
    assert second.item.version == first.item.version + 1
    assert len(
        store.list_owner_attention(statuses=(AttentionStatus.OPEN.value,))
    ) == 1


def test_attention_fingerprint_is_semantic_and_deterministic() -> None:
    objective = _objective()
    finding = _finding(_desired(objective))
    kwargs = _attention_kwargs(objective, finding)

    first = attention_fingerprint_for(
        objective_id=kwargs["objective_id"],
        finding_id=kwargs["finding_id"],
        candidate_id=kwargs["candidate_id"],
        group_key=kwargs["group_key"],
        reason_codes=kwargs["reason_codes"],
        question=kwargs["question"],
        option_metadata_json=kwargs["option_metadata_json"],
        consequence_of_waiting=kwargs["consequence_of_waiting"],
    )
    second = attention_fingerprint_for(
        objective_id=kwargs["objective_id"],
        finding_id=kwargs["finding_id"],
        candidate_id=kwargs["candidate_id"],
        group_key=kwargs["group_key"],
        reason_codes=kwargs["reason_codes"],
        question=kwargs["question"],
        option_metadata_json={"options": ["approve", "reject"]},
        consequence_of_waiting=kwargs["consequence_of_waiting"],
    )

    assert first == second


def test_root_attention_inhibits_derivative_spam(tmp_path: Path) -> None:
    store = _store(tmp_path)
    objective, _, finding = _seed_attention_chain(store)
    manager = OwnerAttentionManager(store)
    kwargs = _attention_kwargs(objective, finding)
    root = manager.open_or_update(**kwargs, now_epoch=NOW)

    derivative = manager.open_or_update(
        **{
            **kwargs,
            "reason_codes": ("derivative_owner_decision",),
            "question": "Derivative question that should be inhibited.",
        },
        now_epoch=NOW + 1,
        root_attention_id=root.item.attention_id,
    )

    assert derivative.inhibited is True
    assert derivative.item.attention_id == root.item.attention_id
    assert len(
        store.list_owner_attention(statuses=(AttentionStatus.OPEN.value,))
    ) == 1
    assert "derivative_inhibited" in {
        event.kind
        for event in store.list_attention_events(root.item.attention_id)
    }


class _RecordingTransport:
    def __init__(self) -> None:
        self.deliveries = []

    def deliver(self, delivery) -> None:
        self.deliveries.append(delivery)


class _FailingTransport:
    def deliver(self, delivery) -> None:
        raise RuntimeError("transport unavailable")


def test_renotify_interval_is_respected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    objective, _, finding = _seed_attention_chain(store)
    manager = OwnerAttentionManager(store)
    opened = manager.open_or_update(
        **_attention_kwargs(objective, finding),
        now_epoch=NOW,
    )
    transport = _RecordingTransport()
    adapter = OwnerAttentionDeliveryAdapter(manager, transport)

    first = adapter.attempt(
        opened.item,
        now_epoch=NOW,
        renotify_interval_seconds=3600,
    )
    assert first.delivered is True
    assert len(transport.deliveries) == 1

    early = adapter.attempt(
        first.attention,
        now_epoch=NOW + 3599,
        renotify_interval_seconds=3600,
    )
    assert early.attempted is False
    assert len(transport.deliveries) == 1

    due = adapter.attempt(
        first.attention,
        now_epoch=NOW + 3600,
        renotify_interval_seconds=3600,
    )
    assert due.delivered is True
    assert len(transport.deliveries) == 2


def test_notification_failure_keeps_canonical_attention_truth(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    objective, _, finding = _seed_attention_chain(store)
    manager = OwnerAttentionManager(store)
    opened = manager.open_or_update(
        **_attention_kwargs(objective, finding),
        now_epoch=NOW,
    )
    adapter = OwnerAttentionDeliveryAdapter(manager, _FailingTransport())

    attempt = adapter.attempt(
        opened.item,
        now_epoch=NOW,
        renotify_interval_seconds=600,
    )

    assert attempt.attempted is True
    assert attempt.delivered is False
    assert attempt.failure_reason == "RuntimeError"
    persisted = store.require_owner_attention(opened.item.attention_id)
    assert persisted == attempt.attention
    assert persisted.status is AttentionStatus.OPEN
    assert persisted.next_renotify_epoch == NOW + 600
    assert "notification_failed" in {
        event.kind
        for event in store.list_attention_events(persisted.attention_id)
    }


def test_delivery_adapter_does_not_create_fake_work_item(tmp_path: Path) -> None:
    store = _store(tmp_path)
    objective, _, finding = _seed_attention_chain(store)
    manager = OwnerAttentionManager(store)
    opened = manager.open_or_update(
        **_attention_kwargs(objective, finding),
        now_epoch=NOW,
    )
    transport = _RecordingTransport()
    adapter = OwnerAttentionDeliveryAdapter(manager, transport)

    delivery = adapter.build_delivery(opened.item, now_epoch=NOW)

    assert delivery.work_id == f"owner_attention:{opened.item.attention_id}"
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM work_deliveries").fetchone()[0] == 0


def test_terminal_attention_is_not_implicitly_reopened(tmp_path: Path) -> None:
    store = _store(tmp_path)
    objective, _, finding = _seed_attention_chain(store)
    manager = OwnerAttentionManager(store)
    kwargs = _attention_kwargs(objective, finding)
    opened = manager.open_or_update(**kwargs, now_epoch=NOW)
    resolved = manager.transition_status(
        opened.item.attention_id,
        status=AttentionStatus.RESOLVED,
        now_epoch=NOW + 10,
    )
    replay = manager.open_or_update(**kwargs, now_epoch=NOW + 20)

    assert resolved.status is AttentionStatus.RESOLVED
    assert replay.item == resolved
    assert replay.inhibited is True
    assert replay.reason_codes == ("terminal_attention_not_reopened_implicitly",)
