from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.autonomy.findings import FindingLifecycle
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
    ActionResolutionSpecV1,
    ActionResolverRegistry,
    DuplicateActionResolverError,
    StaticActionResolverV1,
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


def _objective() -> ObjectiveV1:
    return ObjectiveV1(
        objective_id="objective_phase10a4",
        origin=ObjectiveOrigin.REGISTERED_SYSTEM_OBLIGATION,
        source_identity="registered:phase10a4:test",
        title="Keep test component healthy",
        description="Phase 10A.4 deterministic finding/action test.",
        priority=WorkPriority.HIGH,
        status=ObjectiveStatus.ACTIVE,
        horizon="continuous",
        constraint_json={"scope": "test"},
        created_at_epoch=NOW - 100,
        updated_at_epoch=NOW - 100,
    )


def _desired(
    *,
    rule_key: str = "component_health",
    rule_version: int = 1,
    target_namespace: str = "component",
    target_identity: str = "runtime.test",
) -> DesiredStateV1:
    return DesiredStateV1(
        desired_state_id=f"desired_{rule_key}",
        objective_id="objective_phase10a4",
        target_namespace=target_namespace,
        target_identity=target_identity,
        rule_key=rule_key,
        rule_version=rule_version,
        expected_json={"acceptable_states": ["healthy"]},
        required_source_namespaces=("health_registry", "self_model"),
        stabilization_policy=StabilizationPolicyV1(),
        generation=1,
        status=DesiredStateStatus.ACTIVE,
        provenance_source_identity="registered:phase10a4:test",
        created_at_epoch=NOW - 90,
        updated_at_epoch=NOW - 90,
    )


def _evaluation(
    desired: DesiredStateV1,
    *,
    status: DesiredStateEvaluationStatus,
    now: float,
    consecutive: int = 0,
    snapshot_digest: str = DIGEST_A,
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
        consecutive_violations=consecutive,
        first_violation_at_epoch=(None if consecutive == 0 else NOW),
        last_violation_at_epoch=(None if consecutive == 0 else now),
    )


def _store(tmp_path: Path) -> tuple[AutonomyStore, DesiredStateV1]:
    store = AutonomyStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    objective = _objective()
    desired = _desired()
    store.create_objective(objective)
    store.create_desired_state(desired)
    return store, desired


def test_same_gap_reuses_one_finding_and_promotes_stabilizing_to_active(
    tmp_path: Path,
) -> None:
    store, desired = _store(tmp_path)
    lifecycle = FindingLifecycle(store)

    first = lifecycle.observe(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.STABILIZING,
            now=NOW,
            consecutive=1,
        ),
    )
    replay = lifecycle.observe(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.STABILIZING,
            now=NOW,
            consecutive=1,
        ),
    )
    active = lifecycle.observe(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            now=NOW + 10,
            consecutive=2,
            snapshot_digest="c" * 64,
        ),
    )

    assert first.finding is not None
    assert first.finding.status is FindingStatus.STABILIZING
    assert replay.changed is False
    assert replay.finding == first.finding
    assert active.finding is not None
    assert active.finding.finding_id == first.finding.finding_id
    assert active.finding.status is FindingStatus.ACTIVE
    assert active.finding.version == 2
    assert len(store.list_finding_events(first.finding.finding_id)) == 2


def test_unknown_evaluation_does_not_create_or_mutate_finding(tmp_path: Path) -> None:
    store, desired = _store(tmp_path)
    lifecycle = FindingLifecycle(store)

    result = lifecycle.observe(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.UNKNOWN,
            now=NOW,
        ),
    )

    assert result.finding is None
    assert result.changed is False


def test_default_resolver_prefers_existing_controller_and_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    store, desired = _store(tmp_path)
    lifecycle = FindingLifecycle(store)
    active = lifecycle.observe(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            now=NOW,
            consecutive=1,
        ),
    ).finding
    assert active is not None

    service = ActionResolutionService(
        store,
        build_default_action_resolver_registry(),
    )
    first = service.resolve(desired, active, mode=AutonomyMode.SHADOW)
    replay = service.resolve(desired, active, mode=AutonomyMode.SHADOW)

    assert first.candidate.action_kind is ActionKind.EXISTING_CONTROLLER
    assert first.decision.disposition is CandidateDisposition.SHADOW_ONLY
    assert first.dispatch_intent is not None
    assert first.dispatch_intent.intent_json["live_dispatch_performed"] is False
    assert replay.candidate == first.candidate
    assert replay.reused_candidate is True
    assert replay.decision == first.decision
    assert replay.dispatch_intent == first.dispatch_intent
    assert len(store.list_action_candidates(active.finding_id)) == 1
    assert len(store.list_candidate_decisions(first.candidate.candidate_id)) == 1


def test_unsupported_action_mapping_fails_closed_to_no_action(tmp_path: Path) -> None:
    store = AutonomyStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    objective = _objective()
    desired = _desired(rule_key="unmapped_rule")
    store.create_objective(objective)
    store.create_desired_state(desired)

    active = (
        FindingLifecycle(store)
        .observe(
            desired,
            _evaluation(
                desired,
                status=DesiredStateEvaluationStatus.VIOLATED,
                now=NOW,
                consecutive=1,
            ),
        )
        .finding
    )
    assert active is not None

    result = ActionResolutionService(
        store,
        ActionResolverRegistry(),
    ).resolve(desired, active, mode=AutonomyMode.SHADOW)

    assert result.resolver_supported is False
    assert result.candidate.action_kind is ActionKind.NO_ACTION
    assert result.decision.disposition is CandidateDisposition.BLOCKED_POLICY
    assert result.dispatch_intent is None
    assert "unsupported_action_mapping" in result.decision.reason_codes


def test_duplicate_mapping_cannot_replace_deterministic_controller() -> None:
    registry = build_default_action_resolver_registry()
    competing = StaticActionResolverV1(
        rule_key="component_health",
        rule_version=1,
        finding_kind="state_gap",
        resolver_key="competing_agentic_work",
        resolver_version=1,
        spec=ActionResolutionSpecV1(
            action_kind=ActionKind.WORK_ITEM,
            expected_effect="Create duplicate diagnostics work.",
            reversibility_class="reversible",
            resource_class="background",
            cost_class="bounded",
            risk_json={"risk": "low"},
        ),
    )

    with pytest.raises(DuplicateActionResolverError):
        registry.register(competing)


@pytest.mark.parametrize(
    "kind",
    (
        ActionKind.EXISTING_CONTROLLER,
        ActionKind.WORK_ITEM,
        ActionKind.ENGINEERING_CHANGE,
        ActionKind.OWNER_ATTENTION,
    ),
)
def test_registered_response_classes_create_proposal_only_intents(
    tmp_path: Path,
    kind: ActionKind,
) -> None:
    store, desired = _store(tmp_path)
    active = (
        FindingLifecycle(store)
        .observe(
            desired,
            _evaluation(
                desired,
                status=DesiredStateEvaluationStatus.VIOLATED,
                now=NOW,
                consecutive=1,
            ),
        )
        .finding
    )
    assert active is not None

    resolver = StaticActionResolverV1(
        rule_key=desired.rule_key,
        rule_version=desired.rule_version,
        finding_kind=active.finding_kind,
        resolver_key=f"test_{kind.value}",
        resolver_version=1,
        spec=ActionResolutionSpecV1(
            action_kind=kind,
            expected_effect=f"Test {kind.value} response.",
            reversibility_class="bounded",
            resource_class="test",
            cost_class="bounded",
            risk_json={"risk": "test"},
            dispatch_role=f"{kind.value}_request",
        ),
    )
    result = ActionResolutionService(
        store,
        ActionResolverRegistry((resolver,)),
    ).resolve(desired, active, mode=AutonomyMode.ASSISTED)

    assert result.candidate.action_kind is kind
    assert result.dispatch_intent is not None
    assert result.dispatch_intent.intent_json["proposal_only"] is True
    assert result.decision.disposition is CandidateDisposition.BLOCKED_POLICY
    assert "admission_deferred_until_phase10a5" in result.decision.reason_codes


def test_resolved_finding_marks_existing_candidate_obsolete(tmp_path: Path) -> None:
    store, desired = _store(tmp_path)
    lifecycle = FindingLifecycle(store)
    active = lifecycle.observe(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            now=NOW,
            consecutive=1,
        ),
    ).finding
    assert active is not None
    service = ActionResolutionService(
        store,
        build_default_action_resolver_registry(),
    )
    resolution = service.resolve(desired, active, mode=AutonomyMode.SHADOW)

    resolved = lifecycle.observe(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.SATISFIED,
            now=NOW + 5,
            snapshot_digest="d" * 64,
        ),
    )

    assert resolved.finding is not None
    assert resolved.finding.status is FindingStatus.RESOLVED
    assert resolved.obsoleted_candidate_ids == (resolution.candidate.candidate_id,)
    latest = store.latest_candidate_decision(resolution.candidate.candidate_id)
    assert latest is not None
    assert latest.disposition is CandidateDisposition.OBSOLETE


def test_reopened_finding_can_record_new_decision_after_obsolete(
    tmp_path: Path,
) -> None:
    store, desired = _store(tmp_path)
    lifecycle = FindingLifecycle(store)
    active = lifecycle.observe(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            now=NOW,
            consecutive=1,
        ),
    ).finding
    assert active is not None
    service = ActionResolutionService(
        store,
        build_default_action_resolver_registry(),
    )
    first = service.resolve(desired, active, mode=AutonomyMode.SHADOW)

    lifecycle.observe(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.SATISFIED,
            now=NOW + 5,
            snapshot_digest="d" * 64,
        ),
    )
    reopened = lifecycle.observe(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            now=NOW + 10,
            consecutive=1,
            snapshot_digest="e" * 64,
        ),
    ).finding
    assert reopened is not None
    again = service.resolve(desired, reopened, mode=AutonomyMode.SHADOW)

    assert again.candidate.candidate_id == first.candidate.candidate_id
    decisions = store.list_candidate_decisions(first.candidate.candidate_id)
    assert [item.disposition for item in decisions] == [
        CandidateDisposition.SHADOW_ONLY,
        CandidateDisposition.OBSOLETE,
        CandidateDisposition.SHADOW_ONLY,
    ]


def test_suppression_survives_repeated_violating_observation(
    tmp_path: Path,
) -> None:
    store, desired = _store(tmp_path)
    lifecycle = FindingLifecycle(store)
    active = lifecycle.observe(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            now=NOW,
            consecutive=1,
        ),
    ).finding
    assert active is not None

    suppressed = lifecycle.suppress(
        active.finding_id,
        suppression_finding_id="finding_root_cause",
        root_finding_id="finding_root_cause",
        at_epoch=NOW + 1,
    ).finding
    assert suppressed is not None

    observed = lifecycle.observe(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            now=NOW + 2,
            consecutive=2,
            snapshot_digest="f" * 64,
        ),
    ).finding

    assert observed is not None
    assert observed.status is FindingStatus.SUPPRESSED
    assert observed.suppression_finding_id == "finding_root_cause"
    assert observed.root_finding_id == "finding_root_cause"


def test_suppression_links_root_and_obsoletes_candidate(tmp_path: Path) -> None:
    store, desired = _store(tmp_path)
    lifecycle = FindingLifecycle(store)
    active = lifecycle.observe(
        desired,
        _evaluation(
            desired,
            status=DesiredStateEvaluationStatus.VIOLATED,
            now=NOW,
            consecutive=1,
        ),
    ).finding
    assert active is not None
    candidate = (
        ActionResolutionService(
            store,
            build_default_action_resolver_registry(),
        )
        .resolve(desired, active, mode=AutonomyMode.SHADOW)
        .candidate
    )

    suppressed = lifecycle.suppress(
        active.finding_id,
        suppression_finding_id="finding_root_cause",
        root_finding_id="finding_root_cause",
        at_epoch=NOW + 1,
    )

    assert suppressed.finding is not None
    assert suppressed.finding.status is FindingStatus.SUPPRESSED
    assert suppressed.finding.root_finding_id == "finding_root_cause"
    assert suppressed.finding.suppression_finding_id == "finding_root_cause"
    assert suppressed.obsoleted_candidate_ids == (candidate.candidate_id,)
