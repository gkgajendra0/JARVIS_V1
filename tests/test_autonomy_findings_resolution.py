from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.autonomy.findings import FindingLifecycleManager
from jarvis.autonomy.models import (
    ActionKind,
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
from jarvis.autonomy.resolution import (
    ActionResolutionService,
    ActionResolverRegistry,
    ActionResponseSpecV1,
    DuplicateActionResolverError,
    LeastPowerfulActionResolverV1,
    build_default_action_resolver_registry,
)
from jarvis.autonomy.rules import (
    DesiredStateEvaluationStatus,
    DesiredStateEvaluationV1,
)
from jarvis.autonomy.store import AutonomyStore
from jarvis.work.models import WorkPriority
from jarvis.work.store import SQLiteWorkStore

NOW = 1_800_000_000.0
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def _objective() -> ObjectiveV1:
    return ObjectiveV1(
        objective_id="objective_phase10a4",
        origin=ObjectiveOrigin.REGISTERED_SYSTEM_OBLIGATION,
        source_identity="registered:phase10a4:test",
        title="Keep component healthy",
        description="Deterministic Phase 10A.4 lifecycle test.",
        priority=WorkPriority.HIGH,
        status=ObjectiveStatus.ACTIVE,
        horizon="continuous",
        constraint_json={"criticality": "high"},
        created_at_epoch=NOW - 100,
        updated_at_epoch=NOW - 100,
    )


def _desired(
    objective: ObjectiveV1,
    *,
    generation: int = 1,
    rule_key: str = "component_health",
    target_namespace: str = "component",
    target_identity: str = "runtime.test",
) -> DesiredStateV1:
    required = {
        "component_health": ("health_registry", "self_model"),
        "capability_effective_state": ("capability_registry",),
        "durable_work": ("work",),
    }[rule_key]
    expected = {
        "component_health": {"acceptable_states": ["healthy"]},
        "capability_effective_state": {"effective_enabled": True},
        "durable_work": {"acceptable_states": ["completed"]},
    }[rule_key]
    return DesiredStateV1(
        desired_state_id=f"desired_{rule_key}",
        objective_id=objective.objective_id,
        target_namespace=target_namespace,
        target_identity=target_identity,
        rule_key=rule_key,
        rule_version=1,
        expected_json=expected,
        required_source_namespaces=required,
        stabilization_policy=StabilizationPolicyV1(),
        generation=generation,
        status=DesiredStateStatus.ACTIVE,
        provenance_source_identity=objective.source_identity,
        created_at_epoch=NOW - 90,
        updated_at_epoch=NOW - 90 + generation - 1,
    )


def _evaluation(
    desired: DesiredStateV1,
    *,
    status: DesiredStateEvaluationStatus,
    snapshot_digest: str = DIGEST_A,
    now: float = NOW,
    count: int = 1,
) -> DesiredStateEvaluationV1:
    return DesiredStateEvaluationV1(
        desired_state_id=desired.desired_state_id,
        desired_generation=desired.generation,
        rule_key=desired.rule_key,
        rule_version=desired.rule_version,
        status=status,
        snapshot_digest=snapshot_digest,
        reason_codes=(f"test_{status.value}",),
        supporting_fact_digests=(DIGEST_B,),
        evaluated_at_epoch=now,
        consecutive_violations=count if status in {
            DesiredStateEvaluationStatus.STABILIZING,
            DesiredStateEvaluationStatus.VIOLATED,
        } else 0,
        first_violation_at_epoch=(
            now - count + 1
            if status in {
                DesiredStateEvaluationStatus.STABILIZING,
                DesiredStateEvaluationStatus.VIOLATED,
            }
            else None
        ),
        last_violation_at_epoch=(
            now
            if status in {
                DesiredStateEvaluationStatus.STABILIZING,
                DesiredStateEvaluationStatus.VIOLATED,
            }
            else None
        ),
    )


def _store(tmp_path: Path) -> AutonomyStore:
    return AutonomyStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))


def _seed_desired(store: AutonomyStore, desired: DesiredStateV1) -> None:
    objective = _objective()
    store.create_objective(objective)
    store.create_desired_state(desired)


def test_same_active_gap_reuses_one_finding_and_one_event(tmp_path: Path) -> None:
    store = _store(tmp_path)
    objective = _objective()
    desired = _desired(objective)
    store.create_objective(objective)
    store.create_desired_state(desired)
    manager = FindingLifecycleManager(store)
    evaluation = _evaluation(
        desired,
        status=DesiredStateEvaluationStatus.VIOLATED,
        count=3,
    )

    first = manager.apply(desired, evaluation)
    second = manager.apply(desired, evaluation)

    assert first.finding is not None
    assert first.finding.status is FindingStatus.ACTIVE
    assert second.finding == first.finding
    assert second.changed is False
    assert second.reason_code == "finding_replay_noop"
    assert store.require_finding(first.finding.finding_id) == first.finding
    assert store.list_finding_events(first.finding.finding_id) == (first.event,)


def test_replay_repairs_missing_finding_event_without_version_bump(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    objective = _objective()
    desired = _desired(objective)
    store.create_objective(objective)
    store.create_desired_state(desired)
    manager = FindingLifecycleManager(store)
    evaluation = _evaluation(
        desired,
        status=DesiredStateEvaluationStatus.VIOLATED,
        count=2,
    )
    first = manager.apply(desired, evaluation)
    assert first.finding is not None
    assert first.event is not None

    with store.work.extension_transaction() as db:
        db.execute(
            "DELETE FROM autonomy_finding_events WHERE event_id=?",
            (first.event.event_id,),
        )

    replay = manager.apply(desired, evaluation)

    assert replay.finding == first.finding
    assert replay.finding.version == 1
    assert replay.changed is False
    assert store.list_finding_events(first.finding.finding_id) == (first.event,)


def test_unknown_evidence_never_resolves_active_finding(tmp_path: Path) -> None:
    store = _store(tmp_path)
    objective = _objective()
    desired = _desired(objective)
    store.create_objective(objective)
    store.create_desired_state(desired)
    manager = FindingLifecycleManager(store)

    active = manager.apply(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            count=2,
        ),
    )
    unknown = manager.apply(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.UNKNOWN,
            snapshot_digest=DIGEST_C,
            now=NOW + 10,
            count=0,
        ),
    )

    assert active.finding is not None
    assert unknown.finding == active.finding
    assert unknown.finding.status is FindingStatus.ACTIVE
    assert unknown.changed is False
    assert unknown.reason_code == "unknown_evidence_preserves_finding"


def test_stable_recovery_resolves_existing_finding_and_logs_transition(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    objective = _objective()
    desired = _desired(objective)
    store.create_objective(objective)
    store.create_desired_state(desired)
    manager = FindingLifecycleManager(store)

    active = manager.apply(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            count=2,
        ),
    )
    resolved = manager.apply(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.SATISFIED,
            snapshot_digest=DIGEST_C,
            now=NOW + 30,
            count=0,
        ),
    )

    assert active.finding is not None
    assert resolved.finding is not None
    assert resolved.finding.finding_id == active.finding.finding_id
    assert resolved.finding.version == active.finding.version + 1
    assert resolved.finding.status is FindingStatus.RESOLVED
    assert [event.kind for event in store.list_finding_events(
        active.finding.finding_id
    )] == ["activated", "resolved"]


def test_suppression_and_root_relationships_are_durable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    objective = _objective()
    desired = _desired(objective)
    store.create_objective(objective)
    store.create_desired_state(desired)
    manager = FindingLifecycleManager(store)

    result = manager.apply(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
        ),
        root_finding_id="finding_root",
        suppression_finding_id="finding_root",
    )

    assert result.finding is not None
    assert result.finding.status is FindingStatus.SUPPRESSED
    assert result.finding.root_finding_id == "finding_root"
    assert result.finding.suppression_finding_id == "finding_root"
    assert result.event is not None
    assert result.event.kind == "suppressed"


def test_non_active_desired_state_supersedes_existing_finding(tmp_path: Path) -> None:
    store = _store(tmp_path)
    objective = _objective()
    desired = _desired(objective)
    store.create_objective(objective)
    store.create_desired_state(desired)
    manager = FindingLifecycleManager(store)
    active = manager.apply(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
        ),
    )
    assert active.finding is not None

    paused = replace(
        desired,
        status=DesiredStateStatus.PAUSED,
        generation=2,
        updated_at_epoch=NOW + 1,
    )
    store.update_desired_state(paused, expected_generation=1)
    result = manager.apply(
        paused,
        _evaluation(
            paused,
            status=DesiredStateEvaluationStatus.UNKNOWN,
            snapshot_digest=DIGEST_C,
            now=NOW + 2,
            count=0,
        ),
    )

    assert result.finding is not None
    assert result.finding.status is FindingStatus.SUPERSEDED
    assert result.finding.desired_generation == 2
    assert result.event is not None
    assert result.event.kind == "superseded"


def _active_finding(
    store: AutonomyStore,
    desired: DesiredStateV1,
) -> tuple[FindingLifecycleManager, object]:
    manager = FindingLifecycleManager(store)
    result = manager.apply(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            count=2,
        ),
    )
    assert result.finding is not None
    return manager, result.finding


def test_same_finding_policy_generation_reuses_one_immutable_candidate(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    objective = _objective()
    desired = _desired(objective)
    store.create_objective(objective)
    store.create_desired_state(desired)
    manager, finding = _active_finding(store, desired)
    service = ActionResolutionService(
        store,
        build_default_action_resolver_registry(),
    )

    first = service.resolve_and_record(
        desired,
        finding,
        resolver_key="component_health",
        resolver_version=1,
    )
    assert first.candidate is not None

    updated = manager.apply(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            snapshot_digest=DIGEST_C,
            now=NOW + 30,
            count=4,
        ),
    )
    assert updated.finding is not None

    replay = service.resolve_and_record(
        desired,
        updated.finding,
        resolver_key="component_health",
        resolver_version=1,
    )

    assert replay.candidate == first.candidate
    assert replay.reason_codes == ("candidate_replay_reused",)
    assert replay.candidate.snapshot_digest == DIGEST_A


def test_resolved_finding_makes_existing_candidate_obsolete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    objective = _objective()
    desired = _desired(objective)
    store.create_objective(objective)
    store.create_desired_state(desired)
    manager, finding = _active_finding(store, desired)
    service = ActionResolutionService(
        store,
        build_default_action_resolver_registry(),
    )

    candidate_result = service.resolve_and_record(
        desired,
        finding,
        resolver_key="component_health",
        resolver_version=1,
    )
    assert candidate_result.candidate is not None

    resolved = manager.apply(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.SATISFIED,
            snapshot_digest=DIGEST_C,
            now=NOW + 20,
            count=0,
        ),
    )
    assert resolved.finding is not None

    obsolete = service.resolve_and_record(
        desired,
        resolved.finding,
        resolver_key="component_health",
        resolver_version=1,
    )

    assert obsolete.candidate is None
    assert obsolete.disposition is CandidateDisposition.OBSOLETE
    assert store.require_action_candidate(
        candidate_result.candidate.candidate_id
    ) == candidate_result.candidate


def test_existing_controller_wins_over_new_agentic_work(tmp_path: Path) -> None:
    store = _store(tmp_path)
    objective = _objective()
    desired = _desired(objective)
    store.create_objective(objective)
    store.create_desired_state(desired)
    _, finding = _active_finding(store, desired)

    resolver = LeastPowerfulActionResolverV1(
        resolver_key="component_health",
        supported_rules=(("component_health", 1),),
        responses=(
            ActionResponseSpecV1(
                action_kind=ActionKind.WORK_ITEM,
                expected_effect="Create diagnostics work.",
                reversibility_class="fully_reversible",
                resource_class="background",
                cost_class="bounded",
                risk_json={"risk": "low"},
            ),
            ActionResponseSpecV1(
                action_kind=ActionKind.EXISTING_CONTROLLER,
                expected_effect="Use accepted deterministic controller.",
                reversibility_class="controller_defined",
                resource_class="existing_controller",
                cost_class="bounded",
                risk_json={"risk": "bounded"},
            ),
        ),
    )
    service = ActionResolutionService(
        store,
        ActionResolverRegistry((resolver,)),
    )

    result = service.resolve_and_record(
        desired,
        finding,
        resolver_key="component_health",
        resolver_version=1,
    )

    assert result.candidate is not None
    assert result.candidate.action_kind is ActionKind.EXISTING_CONTROLLER


def test_unsupported_action_mapping_fails_closed_without_candidate(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    objective = _objective()
    desired = _desired(objective)
    store.create_objective(objective)
    store.create_desired_state(desired)
    _, finding = _active_finding(store, desired)
    service = ActionResolutionService(store, ActionResolverRegistry())

    result = service.resolve_and_record(
        desired,
        finding,
        resolver_key="missing",
        resolver_version=1,
    )

    assert result.candidate is None
    assert result.disposition is CandidateDisposition.BLOCKED_POLICY
    assert result.reason_codes == ("unsupported_action_mapping",)


def test_observe_and_assisted_modes_cannot_record_phase10a4_candidate(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    objective = _objective()
    desired = _desired(objective)
    store.create_objective(objective)
    store.create_desired_state(desired)
    _, finding = _active_finding(store, desired)
    service = ActionResolutionService(
        store,
        build_default_action_resolver_registry(),
    )

    for mode in (AutonomyMode.OBSERVE, AutonomyMode.ASSISTED):
        result = service.resolve_and_record(
            desired,
            finding,
            resolver_key="component_health",
            resolver_version=1,
            mode=mode,
        )
        assert result.candidate is None
        assert result.disposition is CandidateDisposition.BLOCKED_POLICY
        assert result.reason_codes == ("phase10a4_is_shadow_only",)

    with sqlite3.connect(store.path) as db:
        count = db.execute(
            "SELECT COUNT(*) FROM autonomy_action_candidates"
        ).fetchone()[0]
    assert count == 0


def test_resolver_registry_rejects_duplicate_exact_version() -> None:
    resolver = LeastPowerfulActionResolverV1(
        resolver_key="test",
        supported_rules=(("component_health", 1),),
        responses=(
            ActionResponseSpecV1(
                action_kind=ActionKind.NO_ACTION,
                expected_effect="No action.",
                reversibility_class="not_applicable",
                resource_class="none",
                cost_class="none",
                risk_json={"risk": "none"},
            ),
        ),
    )
    registry = ActionResolverRegistry((resolver,))

    with pytest.raises(DuplicateActionResolverError):
        registry.register(resolver)


def test_default_capability_resolution_prefers_existing_controller(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    objective = _objective()
    desired = _desired(
        objective,
        rule_key="capability_effective_state",
        target_namespace="capability",
        target_identity="capability.test",
    )
    store.create_objective(objective)
    store.create_desired_state(desired)
    _, finding = _active_finding(store, desired)
    service = ActionResolutionService(
        store,
        build_default_action_resolver_registry(),
    )

    result = service.resolve_and_record(
        desired,
        finding,
        resolver_key="capability_effective_state",
        resolver_version=1,
    )

    assert result.candidate is not None
    assert result.candidate.action_kind is ActionKind.EXISTING_CONTROLLER
    assert result.disposition is CandidateDisposition.SHADOW_ONLY
