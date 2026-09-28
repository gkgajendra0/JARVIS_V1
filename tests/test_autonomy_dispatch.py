from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jarvis.autonomy.attention import (
    OwnerAttentionDeliveryAdapter,
    OwnerAttentionManager,
)
from jarvis.autonomy.budgets import BudgetUsageV1
from jarvis.autonomy.dispatch import (
    AutonomyDispatchConfigV1,
    AutonomyDispatchService,
    CapabilityReconciliationControllerV1,
    ChangeCoordinatorDispatchBridge,
    ControllerDispatchReceiptV1,
    DispatchBridgeRegistrationV1,
    DispatchBridgeRegistry,
    ExistingControllerRegistry,
    WorkOrchestratorDispatchBridge,
)
from jarvis.autonomy.models import (
    ActionCandidateV1,
    ActionKind,
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
from jarvis.autonomy.portfolio import PrioritizedCandidateV1
from jarvis.autonomy.store import AutonomyStore
from jarvis.config import JarvisConfig
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.models import ChangeState
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.machine_config import PERSISTABLE_SETTINGS
from jarvis.work.models import (
    DeliveryPolicy,
    WorkItem,
    WorkPriority,
    WorkType,
)
from jarvis.work.orchestrator import WorkOrchestrator
from jarvis.work.store import SQLiteWorkStore

NOW = 1_800_000_000.0
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


class _Backend:
    def __init__(self) -> None:
        self.submitted: list[tuple[str, WorkPriority]] = []

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        self.submitted.append((work_id, priority))
        return work_id

    def cancel(self, execution_id: str, *, idempotency_key: str | None = None) -> None:
        del execution_id, idempotency_key

    def pause(self, execution_id: str) -> None:
        del execution_id

    def resume(
        self,
        execution_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> None:
        del execution_id, idempotency_key


class _RecordingTransport:
    def __init__(self) -> None:
        self.deliveries = []

    def deliver(self, delivery) -> None:
        self.deliveries.append(delivery)


class _Controller:
    controller_key = "test.controller"
    controller_version = 1
    replay_safe = True
    contract_digest = canonical_digest(
        {
            "controller_key": controller_key,
            "controller_version": controller_version,
            "effect": "bounded-test-reconcile",
        }
    )

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def invoke(
        self,
        candidate: ActionCandidateV1,
        *,
        source_identity: str,
    ) -> ControllerDispatchReceiptV1:
        self.calls.append((candidate.candidate_id, source_identity))
        return ControllerDispatchReceiptV1(
            downstream_id=f"controller-result:{candidate.target_identity}",
            downstream_version="1",
        )


def _store(tmp_path: Path) -> tuple[SQLiteWorkStore, AutonomyStore]:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    return work, AutonomyStore(work)


def _objective(
    *,
    objective_id: str = "objective_dispatch",
    priority: WorkPriority = WorkPriority.HIGH,
) -> ObjectiveV1:
    return ObjectiveV1(
        objective_id=objective_id,
        origin=ObjectiveOrigin.OWNER,
        source_identity="owner:phase10a6:test",
        title="Exercise bounded autonomy dispatch",
        description="Verify Phase 10A.6 dispatch without bypassing governance.",
        priority=priority,
        status=ObjectiveStatus.ACTIVE,
        horizon="continuous",
        constraint_json={"authority": "unchanged"},
        created_at_epoch=NOW - 100,
        updated_at_epoch=NOW - 100,
    )


def _desired(
    objective: ObjectiveV1,
    *,
    desired_state_id: str = "desired_dispatch",
) -> DesiredStateV1:
    return DesiredStateV1(
        desired_state_id=desired_state_id,
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
    candidate_id: str,
    action_kind: ActionKind,
    resolver_key: str,
    dependencies: tuple[str, ...] = (),
) -> ActionCandidateV1:
    return ActionCandidateV1(
        candidate_id=candidate_id,
        finding_id=finding.finding_id,
        desired_state_id=finding.desired_state_id,
        desired_generation=finding.desired_generation,
        action_kind=action_kind,
        resolver_key=resolver_key,
        resolver_version=1,
        expected_effect="Perform the registered bounded Phase 10A.6 response.",
        target_namespace=finding.target_namespace,
        target_identity=finding.target_identity,
        snapshot_digest=finding.latest_snapshot_digest,
        reversibility_class="bounded",
        resource_class="background",
        cost_class="bounded",
        risk_json={"risk": "low"},
        dependencies=dependencies,
        mode=AutonomyMode.SHADOW,
        policy_reason_codes=("phase10a6_test",),
        created_at_epoch=NOW,
    )


def _seed(
    store: AutonomyStore,
    *,
    candidate_id: str,
    action_kind: ActionKind,
    resolver_key: str,
    dependencies: tuple[str, ...] = (),
) -> tuple[ObjectiveV1, DesiredStateV1, AutonomyFindingV1, ActionCandidateV1]:
    objective = _objective(objective_id=f"objective_{candidate_id}")
    desired = _desired(objective, desired_state_id=f"desired_{candidate_id}")
    finding = _finding(desired)
    candidate = _candidate(
        finding,
        candidate_id=candidate_id,
        action_kind=action_kind,
        resolver_key=resolver_key,
        dependencies=dependencies,
    )
    store.create_objective(objective)
    store.create_desired_state(desired)
    store.create_finding(finding)
    store.create_action_candidate(candidate)
    return objective, desired, finding, candidate


def _budget() -> AutonomyBudgetPolicyV1:
    return AutonomyBudgetPolicyV1(
        policy_id="phase10a6_budget",
        max_concurrent_autonomous_work_items=3,
        max_new_autonomous_work_items_per_window=3,
        max_active_candidates_per_objective=3,
        max_repeat_dispatches_per_finding_window=3,
        max_owner_attention_notifications_per_window=3,
        window_seconds=3600,
    )


def _usage() -> BudgetUsageV1:
    return BudgetUsageV1(
        active_autonomous_work_items=0,
        new_autonomous_work_items_in_window=0,
        active_candidates_for_objective=0,
        repeated_dispatches_for_finding_window=0,
        owner_attention_notifications_in_window=0,
    )


def _priority(
    objective: ObjectiveV1,
    candidate: ActionCandidateV1,
) -> PrioritizedCandidateV1:
    return PrioritizedCandidateV1(
        candidate_id=candidate.candidate_id,
        objective_id=objective.objective_id,
        work_priority=objective.priority,
        ordering_vector=(int(objective.priority), 1, 1, 1, 1, 1, 1),
        priority_factor_payload={
            "owner_priority": int(objective.priority),
            "obligation_criticality": 1,
            "deadline_urgency": 1,
            "impact_scope": 1,
            "dependency_unblocking": 1,
            "starvation_age": 1,
            "resource_feasibility": 1,
        },
        rank=1,
    )


def test_production_autonomy_mode_defaults_to_shadow() -> None:
    assert JarvisConfig().autonomy_mode is AutonomyMode.SHADOW
    assert AutonomyDispatchConfigV1().mode is AutonomyMode.SHADOW
    assert "JARVIS_AUTONOMY_MODE" in PERSISTABLE_SETTINGS

    with pytest.raises(ValueError, match="ACTIVE_BOUNDED"):
        AutonomyDispatchConfigV1(mode=AutonomyMode.ACTIVE_BOUNDED)


def test_shadow_dispatch_has_zero_downstream_side_effects(tmp_path: Path) -> None:
    work, store = _store(tmp_path)
    backend = _Backend()
    orchestrator = WorkOrchestrator(work, backend)
    objective, _, _, candidate = _seed(
        store,
        candidate_id="candidate_shadow_work",
        action_kind=ActionKind.WORK_ITEM,
        resolver_key="shadow_work",
    )
    service = AutonomyDispatchService(
        store=store,
        registrations=DispatchBridgeRegistry(
            (
                DispatchBridgeRegistrationV1(
                    resolver_key="shadow_work",
                    resolver_version=1,
                    action_kind=ActionKind.WORK_ITEM,
                    work_type=WorkType.RESEARCH,
                ),
            )
        ),
        work_bridge=WorkOrchestratorDispatchBridge(
            orchestrator=orchestrator,
            store=work,
            supported_work_types=frozenset({WorkType.RESEARCH}),
        ),
    )

    result = service.dispatch(
        candidate.candidate_id,
        budget_policy=_budget(),
        budget_usage=_usage(),
        priority=_priority(objective, candidate),
        now_epoch=NOW,
    )

    assert result.disposition is CandidateDisposition.SHADOW_ONLY
    assert result.link is None
    assert backend.submitted == []
    with sqlite3.connect(work.path) as db:
        assert db.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
        assert (
            db.execute(
                """
                SELECT COUNT(*) FROM autonomy_dispatch_links
                WHERE downstream_kind != 'dispatch_intent'
                """
            ).fetchone()[0]
            == 0
        )


def test_assisted_work_dispatch_is_exactly_once_and_preserves_dependencies(
    tmp_path: Path,
) -> None:
    work, store = _store(tmp_path)
    dependency = WorkItem(
        request="existing dependency",
        work_type=WorkType.RESEARCH,
        source_session_id="test",
        source_turn_id="dependency",
        delivery_policy=DeliveryPolicy.SILENT,
    )
    work.create(dependency)
    backend = _Backend()
    orchestrator = WorkOrchestrator(work, backend)
    objective, _, _, candidate = _seed(
        store,
        candidate_id="candidate_assisted_work",
        action_kind=ActionKind.WORK_ITEM,
        resolver_key="assisted_work",
        dependencies=(dependency.work_id,),
    )
    service = AutonomyDispatchService(
        store=store,
        registrations=DispatchBridgeRegistry(
            (
                DispatchBridgeRegistrationV1(
                    resolver_key="assisted_work",
                    resolver_version=1,
                    action_kind=ActionKind.WORK_ITEM,
                    work_type=WorkType.RESEARCH,
                ),
            )
        ),
        config=AutonomyDispatchConfigV1(mode=AutonomyMode.ASSISTED),
        work_bridge=WorkOrchestratorDispatchBridge(
            orchestrator=orchestrator,
            store=work,
            supported_work_types=frozenset({WorkType.RESEARCH}),
        ),
    )

    first = service.dispatch(
        candidate.candidate_id,
        budget_policy=_budget(),
        budget_usage=_usage(),
        priority=_priority(objective, candidate),
        now_epoch=NOW,
    )
    replay = service.dispatch(
        candidate.candidate_id,
        budget_policy=_budget(),
        budget_usage=_usage(),
        priority=_priority(objective, candidate),
        now_epoch=NOW + 1,
    )

    assert first.disposition is CandidateDisposition.ADMITTED
    assert first.link is not None
    assert first.link.downstream_kind == "work_item"
    assert replay.replayed is True
    assert replay.link == first.link
    dispatched = work.require(first.link.downstream_id)
    assert dispatched.dependencies == (dependency.work_id,)
    assert dispatched.delivery_policy is DeliveryPolicy.SILENT
    assert len(backend.submitted) == 1


def test_restart_after_downstream_work_before_link_reuses_same_work(
    tmp_path: Path,
) -> None:
    work, store = _store(tmp_path)
    backend = _Backend()
    orchestrator = WorkOrchestrator(work, backend)
    objective, _, _, candidate = _seed(
        store,
        candidate_id="candidate_restart_work",
        action_kind=ActionKind.WORK_ITEM,
        resolver_key="restart_work",
    )
    registration = DispatchBridgeRegistrationV1(
        resolver_key="restart_work",
        resolver_version=1,
        action_kind=ActionKind.WORK_ITEM,
        work_type=WorkType.RESEARCH,
    )
    service = AutonomyDispatchService(
        store=store,
        registrations=DispatchBridgeRegistry((registration,)),
        config=AutonomyDispatchConfigV1(mode=AutonomyMode.ASSISTED),
        work_bridge=WorkOrchestratorDispatchBridge(
            orchestrator=orchestrator,
            store=work,
            supported_work_types=frozenset({WorkType.RESEARCH}),
        ),
    )
    first = service.dispatch(
        candidate.candidate_id,
        budget_policy=_budget(),
        budget_usage=_usage(),
        priority=_priority(objective, candidate),
        now_epoch=NOW,
    )
    assert first.link is not None
    work_id = first.link.downstream_id

    with store.work.extension_transaction() as db:
        db.execute(
            """
            DELETE FROM autonomy_dispatch_links
            WHERE candidate_id=? AND dispatch_role='dispatch'
            """,
            (candidate.candidate_id,),
        )

    recovered = service.dispatch(
        candidate.candidate_id,
        budget_policy=_budget(),
        budget_usage=_usage(),
        priority=_priority(objective, candidate),
        now_epoch=NOW + 1,
    )

    assert recovered.link is not None
    assert recovered.link.downstream_id == work_id
    assert len(work.list(limit=100)) == 1
    assert len(backend.submitted) == 1


def test_assisted_engineering_change_uses_governed_change_lifecycle(
    tmp_path: Path,
) -> None:
    work, store = _store(tmp_path)
    backend = _Backend()
    changes_store = ChangeStore(work)
    coordinator = ChangeCoordinator(changes_store, backend)
    objective, _, _, candidate = _seed(
        store,
        candidate_id="candidate_change",
        action_kind=ActionKind.ENGINEERING_CHANGE,
        resolver_key="governed_change",
    )
    registration = DispatchBridgeRegistrationV1(
        resolver_key="governed_change",
        resolver_version=1,
        action_kind=ActionKind.ENGINEERING_CHANGE,
        process_key="engineering.change",
        process_version=1,
    )
    service = AutonomyDispatchService(
        store=store,
        registrations=DispatchBridgeRegistry((registration,)),
        config=AutonomyDispatchConfigV1(mode=AutonomyMode.ASSISTED),
        change_bridge=ChangeCoordinatorDispatchBridge(coordinator),
    )

    result = service.dispatch(
        candidate.candidate_id,
        budget_policy=_budget(),
        budget_usage=_usage(),
        priority=_priority(objective, candidate),
        now_epoch=NOW,
    )

    assert result.link is not None
    assert result.link.downstream_kind == "engineering_change"
    change = changes_store.require(result.link.downstream_id)
    assert change.state is ChangeState.RESEARCHING
    assert changes_store.latest_artifact(change.change_id, "architecture") is None
    with work.extension_transaction() as db:
        assert (
            db.execute(
                """
                SELECT COUNT(*) FROM engineering_change_decisions AS decision
                JOIN engineering_change_gates AS gate USING (gate_id)
                WHERE gate.change_id=?
                """,
                (change.change_id,),
            ).fetchone()[0]
            == 0
        )
    assert len(changes_store.list_stages(change.change_id)) == 1


def test_existing_controller_requires_exact_registered_contract_and_replays(
    tmp_path: Path,
) -> None:
    _, store = _store(tmp_path)
    objective, _, _, candidate = _seed(
        store,
        candidate_id="candidate_controller",
        action_kind=ActionKind.EXISTING_CONTROLLER,
        resolver_key="controller_resolver",
    )
    controller = _Controller()
    registration = DispatchBridgeRegistrationV1(
        resolver_key="controller_resolver",
        resolver_version=1,
        action_kind=ActionKind.EXISTING_CONTROLLER,
        controller_key=controller.controller_key,
        controller_version=controller.controller_version,
        controller_contract_digest=controller.contract_digest,
    )
    service = AutonomyDispatchService(
        store=store,
        registrations=DispatchBridgeRegistry((registration,)),
        config=AutonomyDispatchConfigV1(mode=AutonomyMode.ASSISTED),
        controllers=ExistingControllerRegistry((controller,)),
    )

    first = service.dispatch(
        candidate.candidate_id,
        budget_policy=_budget(),
        budget_usage=_usage(),
        priority=_priority(objective, candidate),
        now_epoch=NOW,
    )
    replay = service.dispatch(
        candidate.candidate_id,
        budget_policy=_budget(),
        budget_usage=_usage(),
        priority=_priority(objective, candidate),
        now_epoch=NOW + 1,
    )

    assert first.link is not None
    assert first.link.downstream_kind == "existing_controller"
    assert len(controller.calls) == 1
    assert replay.replayed is True
    assert replay.link == first.link


def test_controller_contract_mismatch_fails_closed_without_invocation(
    tmp_path: Path,
) -> None:
    _, store = _store(tmp_path)
    objective, _, _, candidate = _seed(
        store,
        candidate_id="candidate_controller_mismatch",
        action_kind=ActionKind.EXISTING_CONTROLLER,
        resolver_key="controller_mismatch",
    )
    controller = _Controller()
    registration = DispatchBridgeRegistrationV1(
        resolver_key="controller_mismatch",
        resolver_version=1,
        action_kind=ActionKind.EXISTING_CONTROLLER,
        controller_key=controller.controller_key,
        controller_version=controller.controller_version,
        controller_contract_digest="c" * 64,
    )
    service = AutonomyDispatchService(
        store=store,
        registrations=DispatchBridgeRegistry((registration,)),
        config=AutonomyDispatchConfigV1(mode=AutonomyMode.ASSISTED),
        controllers=ExistingControllerRegistry((controller,)),
    )

    result = service.dispatch(
        candidate.candidate_id,
        budget_policy=_budget(),
        budget_usage=_usage(),
        priority=_priority(objective, candidate),
        now_epoch=NOW,
    )

    assert result.disposition is CandidateDisposition.BLOCKED_POLICY
    assert result.reason_codes == ("registered_controller_contract_mismatch",)
    assert controller.calls == []


def test_owner_attention_bridge_replays_without_duplicate_notification(
    tmp_path: Path,
) -> None:
    work, store = _store(tmp_path)
    objective, _, _, candidate = _seed(
        store,
        candidate_id="candidate_attention",
        action_kind=ActionKind.OWNER_ATTENTION,
        resolver_key="attention_resolver",
    )
    transport = _RecordingTransport()
    manager = OwnerAttentionManager(store)
    delivery = OwnerAttentionDeliveryAdapter(manager, transport)
    registration = DispatchBridgeRegistrationV1(
        resolver_key="attention_resolver",
        resolver_version=1,
        action_kind=ActionKind.OWNER_ATTENTION,
        attention_group_key="phase10a6",
        attention_reason_codes=("owner_decision_required",),
        attention_question="Approve the protected decision?",
        attention_option_metadata_json={"options": ["approve", "reject"]},
        attention_consequence_of_waiting="The protected operation remains blocked.",
    )
    service = AutonomyDispatchService(
        store=store,
        registrations=DispatchBridgeRegistry((registration,)),
        config=AutonomyDispatchConfigV1(mode=AutonomyMode.ASSISTED),
        attention_manager=manager,
        attention_delivery=delivery,
    )

    first = service.dispatch(
        candidate.candidate_id,
        budget_policy=_budget(),
        budget_usage=_usage(),
        priority=_priority(objective, candidate),
        now_epoch=NOW,
    )
    replay = service.dispatch(
        candidate.candidate_id,
        budget_policy=_budget(),
        budget_usage=_usage(),
        priority=_priority(objective, candidate),
        now_epoch=NOW + 1,
    )

    assert first.link is not None
    assert first.link.downstream_kind == "owner_attention"
    assert first.attention_delivery is not None
    assert first.attention_delivery.delivered is True
    assert replay.replayed is True
    assert len(transport.deliveries) == 1
    assert work.list(limit=100) == ()


def test_no_generic_dispatch_bridge_exists_for_unregistered_candidate(
    tmp_path: Path,
) -> None:
    _, store = _store(tmp_path)
    objective, _, _, candidate = _seed(
        store,
        candidate_id="candidate_unregistered",
        action_kind=ActionKind.WORK_ITEM,
        resolver_key="not_registered",
    )
    service = AutonomyDispatchService(
        store=store,
        registrations=DispatchBridgeRegistry(),
        config=AutonomyDispatchConfigV1(mode=AutonomyMode.ASSISTED),
    )

    result = service.dispatch(
        candidate.candidate_id,
        budget_policy=_budget(),
        budget_usage=_usage(),
        priority=_priority(objective, candidate),
        now_epoch=NOW,
    )

    assert result.disposition is CandidateDisposition.BLOCKED_POLICY
    assert result.reason_codes == ("dispatch_bridge_not_registered",)


def test_capability_controller_adapter_is_typed_not_generic() -> None:
    assert CapabilityReconciliationControllerV1.controller_key == (
        "capability_registry.reconcile"
    )
    assert CapabilityReconciliationControllerV1.replay_safe is True
