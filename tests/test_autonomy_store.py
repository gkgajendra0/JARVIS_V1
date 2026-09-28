from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.autonomy.models import (
    ActionCandidateV1,
    ActionKind,
    AttentionStatus,
    AutonomyFindingEventV1,
    AutonomyFindingV1,
    AutonomyMode,
    AutonomyOutcomeRecordV1,
    DesiredStateStatus,
    DesiredStateV1,
    FindingStatus,
    ObjectiveOrigin,
    ObjectiveStatus,
    ObjectiveV1,
    OwnerAttentionEventV1,
    OwnerAttentionItemV1,
    ReconcileRunV1,
    ReconcileStatus,
    ReconcileTrigger,
    StabilizationPolicyV1,
    candidate_id_for,
    contract_digest,
    deterministic_id,
    finding_id_for,
)
from jarvis.autonomy.store import (
    AUTONOMY_SCHEMA_CHECKSUM,
    AUTONOMY_SCHEMA_VERSION,
    AutonomyConflictError,
    AutonomyIntegrityError,
    AutonomyStore,
)
from jarvis.work.models import WorkPriority
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore

NOW = 1_800_000_000.0
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _objective(
    *,
    generation: int = 1,
    title: str = "Keep runtime healthy",
) -> ObjectiveV1:
    return ObjectiveV1(
        objective_id="objective_runtime_health",
        origin=ObjectiveOrigin.REGISTERED_SYSTEM_OBLIGATION,
        source_identity="registered:critical-runtime-health:v1",
        title=title,
        description="Preserve accepted critical runtime availability.",
        priority=WorkPriority.HIGH,
        status=ObjectiveStatus.ACTIVE,
        horizon="continuous",
        constraint_json={"criticality": "critical"},
        created_at_epoch=NOW,
        updated_at_epoch=NOW + generation - 1,
        generation=generation,
    )


def _desired(
    objective: ObjectiveV1,
    *,
    generation: int = 1,
) -> DesiredStateV1:
    return DesiredStateV1(
        desired_state_id="desired_runtime_health",
        objective_id=objective.objective_id,
        target_namespace="component",
        target_identity="jarvis.core",
        rule_key="component_health",
        rule_version=1,
        expected_json={"acceptable_states": ["healthy"]},
        required_source_namespaces=("self_model", "health_registry"),
        stabilization_policy=StabilizationPolicyV1(
            required_consecutive_violations=2,
            minimum_violation_age_seconds=5.0,
            minimum_recovery_age_seconds=5.0,
        ),
        generation=generation,
        status=DesiredStateStatus.ACTIVE,
        provenance_source_identity=objective.source_identity,
        created_at_epoch=NOW,
        updated_at_epoch=NOW + generation - 1,
    )


def _finding(
    desired: DesiredStateV1,
    *,
    version: int = 1,
) -> AutonomyFindingV1:
    finding_id = finding_id_for(desired, finding_kind="state_gap")
    return AutonomyFindingV1(
        finding_id=finding_id,
        desired_state_id=desired.desired_state_id,
        desired_generation=desired.generation,
        target_namespace=desired.target_namespace,
        target_identity=desired.target_identity,
        finding_kind="state_gap",
        rule_key=desired.rule_key,
        rule_version=desired.rule_version,
        status=FindingStatus.STABILIZING,
        latest_snapshot_digest=DIGEST_A,
        first_seen_epoch=NOW + 10,
        last_seen_epoch=NOW + 10 + version - 1,
        violation_count=version,
        reason_codes=("health_not_acceptable",),
        supporting_fact_digests=(DIGEST_B,),
        version=version,
    )


def _candidate(finding: AutonomyFindingV1) -> ActionCandidateV1:
    candidate_id = candidate_id_for(
        finding,
        action_kind=ActionKind.WORK_ITEM,
        resolver_key="diagnostics_work",
        resolver_version=1,
    )
    return ActionCandidateV1(
        candidate_id=candidate_id,
        finding_id=finding.finding_id,
        desired_state_id=finding.desired_state_id,
        desired_generation=finding.desired_generation,
        action_kind=ActionKind.WORK_ITEM,
        resolver_key="diagnostics_work",
        resolver_version=1,
        expected_effect="Collect bounded deterministic diagnostics.",
        target_namespace=finding.target_namespace,
        target_identity=finding.target_identity,
        snapshot_digest=finding.latest_snapshot_digest,
        reversibility_class="fully_reversible",
        resource_class="background",
        cost_class="bounded",
        risk_json={"risk": "low"},
        dependencies=(),
        mode=AutonomyMode.SHADOW,
        policy_reason_codes=("shadow_only",),
        created_at_epoch=NOW + 20,
    )


def _seed_chain(store: AutonomyStore):
    objective = _objective()
    desired = _desired(objective)
    finding = _finding(desired)
    candidate = _candidate(finding)
    assert store.create_objective(objective) == objective
    assert store.create_desired_state(desired) == desired
    assert store.create_finding(finding) == finding
    assert store.create_action_candidate(candidate) == candidate
    return objective, desired, finding, candidate


def test_phase10a_contract_ids_and_digests_are_deterministic() -> None:
    objective = _objective()
    desired = _desired(objective)
    finding = _finding(desired)

    assert finding_id_for(desired, finding_kind="state_gap") == finding.finding_id
    assert (
        candidate_id_for(
            finding,
            action_kind=ActionKind.WORK_ITEM,
            resolver_key="diagnostics_work",
            resolver_version=1,
        )
        == _candidate(finding).candidate_id
    )
    assert deterministic_id("example", {"b": 2, "a": 1}) == deterministic_id(
        "example",
        {"a": 1, "b": 2},
    )
    assert contract_digest(objective) == contract_digest(
        ObjectiveV1.from_payload(objective.to_payload())
    )


def test_autonomy_store_uses_workstore_only_and_round_trips_contracts(
    tmp_path: Path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = AutonomyStore(work)

    assert store.path == work.path
    objective, desired, finding, candidate = _seed_chain(store)

    finding_event = AutonomyFindingEventV1(
        event_id="finding_event_1",
        finding_id=finding.finding_id,
        event_key="observed:1",
        kind="observed",
        detail_json={"status": "stabilizing"},
        created_at_epoch=NOW + 21,
    )
    assert store.append_finding_event(finding_event) == finding_event

    attention = OwnerAttentionItemV1(
        attention_id="attention_1",
        fingerprint="runtime-health-owner-input",
        group_key="runtime-health",
        objective_id=objective.objective_id,
        finding_id=finding.finding_id,
        candidate_id=candidate.candidate_id,
        priority=WorkPriority.HIGH,
        reason_codes=("owner_decision_required",),
        question="Approve the protected decision?",
        option_metadata_json={"options": ["approve", "reject"]},
        consequence_of_waiting="The protected action remains blocked.",
        first_occurrence_epoch=NOW + 22,
        last_occurrence_epoch=NOW + 22,
        next_renotify_epoch=NOW + 3600,
        status=AttentionStatus.OPEN,
    )
    assert store.create_owner_attention(attention) == attention

    attention_event = OwnerAttentionEventV1(
        event_id="attention_event_1",
        attention_id=attention.attention_id,
        event_key="opened:1",
        kind="opened",
        detail_json={"delivery": "not_dispatched"},
        created_at_epoch=NOW + 23,
    )
    assert store.append_attention_event(attention_event) == attention_event

    outcome = AutonomyOutcomeRecordV1(
        outcome_record_id="outcome_link_1",
        candidate_id=candidate.candidate_id,
        dispatch_link_id="dispatch_shadow_1",
        downstream_source_kind="work_item",
        downstream_source_id="work_shadow_1",
        downstream_source_version="1",
        terminal_status_ref="completed",
        verification_references=("evidence:phase10a:test",),
        recorded_at_epoch=NOW + 24,
    )
    assert store.record_outcome(outcome) == outcome

    run = ReconcileRunV1(
        reconcile_run_id="reconcile_1",
        request_token="manual-test-1",
        trigger=ReconcileTrigger.MANUAL_TEST,
        started_at_epoch=NOW + 25,
        ended_at_epoch=NOW + 26,
        desired_generation_digest=DIGEST_A,
        snapshot_digest=DIGEST_B,
        status=ReconcileStatus.COMPLETED,
        handled_token="manual-test-1",
    )
    assert store.create_reconcile_run(run) == run

    assert store.require_objective(objective.objective_id) == objective
    assert store.require_desired_state(desired.desired_state_id) == desired
    assert store.require_finding(finding.finding_id) == finding
    assert store.require_action_candidate(candidate.candidate_id) == candidate
    assert store.list_finding_events(finding.finding_id) == (finding_event,)
    assert store.require_owner_attention(attention.attention_id) == attention
    assert store.list_attention_events(attention.attention_id) == (attention_event,)
    assert store.require_outcome(outcome.outcome_record_id) == outcome
    assert store.require_reconcile_run_by_token(run.request_token) == run

    with sqlite3.connect(work.path) as db:
        names = {
            row[0]
            for row in db.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name LIKE 'autonomy_%'
                """
            )
        }
    assert names == {
        "autonomy_schema",
        "autonomy_objectives",
        "autonomy_desired_states",
        "autonomy_findings",
        "autonomy_finding_events",
        "autonomy_action_candidates",
        "autonomy_dispatch_links",
        "autonomy_owner_attention",
        "autonomy_attention_events",
        "autonomy_system_snapshots",
        "autonomy_outcome_links",
        "autonomy_reconcile_runs",
        "autonomy_budget_windows",
    }


def test_autonomy_store_protects_payloads_with_canonical_work_codec(
    tmp_path: Path,
) -> None:
    codec = ProtectedWorkPayloadCodec(b"k" * 32)
    work = SQLiteWorkStore(tmp_path / "work.sqlite3", payload_codec=codec)
    store = AutonomyStore(work)
    objective = _objective(title="owner-private-autonomy-objective")
    store.create_objective(objective)

    with sqlite3.connect(work.path) as db:
        payload = db.execute(
            """
            SELECT payload FROM autonomy_objectives
            WHERE objective_id=?
            """,
            (objective.objective_id,),
        ).fetchone()[0]

    assert payload.startswith("enc:v1:")
    assert "owner-private-autonomy-objective" not in payload
    assert store.require_objective(objective.objective_id) == objective


def test_autonomy_store_idempotency_conflicts_and_cas_fail_closed(
    tmp_path: Path,
) -> None:
    store = AutonomyStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    objective = _objective()
    store.create_objective(objective)
    assert store.create_objective(objective) == objective

    with pytest.raises(AutonomyConflictError):
        store.create_objective(replace(objective, title="same ID, different semantics"))

    objective_v2 = replace(
        objective,
        title="Updated runtime-health objective",
        generation=2,
        updated_at_epoch=NOW + 1,
    )
    assert (
        store.update_objective(
            objective_v2,
            expected_generation=1,
        )
        == objective_v2
    )

    conflicting_v2 = replace(objective_v2, title="conflicting retry")
    with pytest.raises(AutonomyConflictError):
        store.update_objective(
            conflicting_v2,
            expected_generation=1,
        )

    desired = _desired(objective_v2)
    store.create_desired_state(desired)
    finding = _finding(desired)
    store.create_finding(finding)

    event = AutonomyFindingEventV1(
        event_id="finding_event_replay",
        finding_id=finding.finding_id,
        event_key="same-key",
        kind="observed",
        detail_json={"count": 1},
        created_at_epoch=NOW + 30,
    )
    assert store.append_finding_event(event) == event
    assert store.append_finding_event(event) == event

    with pytest.raises(AutonomyConflictError):
        store.append_finding_event(
            replace(event, event_id="other_event", detail_json={"count": 2})
        )


def test_autonomy_store_schema_ledger_tamper_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "work.sqlite3"
    work = SQLiteWorkStore(path)
    AutonomyStore(work)

    with sqlite3.connect(path) as db:
        row = db.execute("SELECT version, checksum FROM autonomy_schema").fetchone()
        assert row == (AUTONOMY_SCHEMA_VERSION, AUTONOMY_SCHEMA_CHECKSUM)
        db.execute(
            "UPDATE autonomy_schema SET checksum=?",
            ("0" * 64,),
        )
        db.commit()

    with pytest.raises(AutonomyIntegrityError, match="checksum"):
        AutonomyStore(SQLiteWorkStore(path))


def test_autonomy_store_unknown_schema_version_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "work.sqlite3"
    work = SQLiteWorkStore(path)
    AutonomyStore(work)

    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE autonomy_schema SET version=?",
            (AUTONOMY_SCHEMA_VERSION + 1,),
        )
        db.commit()

    with pytest.raises(AutonomyIntegrityError, match="version"):
        AutonomyStore(SQLiteWorkStore(path))


def test_reconcile_request_token_is_replay_safe(tmp_path: Path) -> None:
    store = AutonomyStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    run = ReconcileRunV1(
        reconcile_run_id="reconcile_restart_safe",
        request_token="startup-token-1",
        trigger=ReconcileTrigger.STARTUP,
        started_at_epoch=NOW,
        desired_generation_digest=DIGEST_A,
        status=ReconcileStatus.STARTED,
    )
    assert store.create_reconcile_run(run) == run
    assert store.create_reconcile_run(run) == run

    with pytest.raises(AutonomyConflictError):
        store.create_reconcile_run(
            replace(
                run,
                reconcile_run_id="reconcile_other",
                trigger=ReconcileTrigger.PERIODIC,
            )
        )
