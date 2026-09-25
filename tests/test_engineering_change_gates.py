from __future__ import annotations

import pytest

from jarvis.engineering_change import ChangeConflict, ChangeState, ChangeStore
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.work.store import SQLiteWorkStore


def _architecture_ready(tmp_path):
    store = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    change = store.create(
        request="Add capability",
        process_key="engineering.change",
        process_version=1,
        source_session_id="owner-session",
        source_turn_id="owner-turn",
    )
    change = store.transition(
        change.change_id, ChangeState.RESEARCHING, expected_version=1
    )
    change = store.transition(
        change.change_id,
        ChangeState.ARCHITECTURE_READY,
        expected_version=change.version,
    )
    artifact = store.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"proposal": "use typed device adapter"},
    )
    return store, change, artifact


def _trusted_gates(store):
    return GateService(
        store,
        verify_owner=lambda actor, session, turn, gate, digest: (
            actor == "owner"
            and session == "owner-session"
            and turn in {"approval-turn", "reject-turn"}
            and digest == gate.artifact_digest
        ),
    )


def test_approval_binds_exact_revision_and_is_idempotent(tmp_path) -> None:
    store, change, artifact = _architecture_ready(tmp_path)
    gates = _trusted_gates(store)
    challenge = gates.present(
        change.change_id, GateKind.ARCHITECTURE, artifact.artifact_id
    )
    assert store.require(change.change_id).state is ChangeState.WAITING_OWNER_APPROVAL
    decision = gates.decide(
        challenge.gate_id,
        approved=True,
        artifact_digest=artifact.digest,
        actor_id="owner",
        source_session_id="owner-session",
        source_turn_id="approval-turn",
        request_key="owner-session:approval-turn",
    )
    assert (
        gates.decide(
            challenge.gate_id,
            approved=True,
            artifact_digest=artifact.digest,
            actor_id="owner",
            source_session_id="owner-session",
            source_turn_id="approval-turn",
            request_key="owner-session:approval-turn",
        )
        == decision
    )
    assert store.require(change.change_id).state is ChangeState.APPROVED_FOR_BUILD
    assert (
        _trusted_gates(ChangeStore(SQLiteWorkStore(store.work.path))).get(
            challenge.gate_id
        )
        == decision
    )


def test_conflicting_or_stale_owner_approval_cannot_unlock_build(tmp_path) -> None:
    store, change, artifact = _architecture_ready(tmp_path)
    gates = _trusted_gates(store)
    challenge = gates.present(
        change.change_id, GateKind.ARCHITECTURE, artifact.artifact_id
    )
    with pytest.raises(ChangeConflict):
        gates.decide(
            challenge.gate_id,
            approved=True,
            artifact_digest="0" * 64,
            actor_id="owner",
            source_session_id="owner-session",
            source_turn_id="approval-turn",
            request_key="owner-session:approval-turn",
        )
    newer = store.add_artifact(
        change.change_id, kind="architecture", payload={"proposal": "new"}
    )
    assert newer.revision == 2
    with pytest.raises(ChangeConflict):
        gates.decide(
            challenge.gate_id,
            approved=True,
            artifact_digest=artifact.digest,
            actor_id="owner",
            source_session_id="owner-session",
            source_turn_id="approval-turn",
            request_key="owner-session:approval-turn",
        )
    assert store.require(change.change_id).state is ChangeState.ARCHITECTURE_READY


def test_unverified_owner_source_cannot_decide(tmp_path) -> None:
    store, change, artifact = _architecture_ready(tmp_path)
    gates = _trusted_gates(store)
    challenge = gates.present(
        change.change_id, GateKind.ARCHITECTURE, artifact.artifact_id
    )
    with pytest.raises(ChangeConflict, match="trusted owner verification denied"):
        gates.decide(
            challenge.gate_id,
            approved=True,
            artifact_digest=artifact.digest,
            actor_id="assistant",
            source_session_id="owner-session",
            source_turn_id="approval-turn",
            request_key="model-attempt",
        )
    assert store.require(change.change_id).state is ChangeState.WAITING_OWNER_APPROVAL


def test_owner_rejection_is_durable_and_free_text_work_input_is_not_a_gate(
    tmp_path,
) -> None:
    store, change, artifact = _architecture_ready(tmp_path)
    gates = _trusted_gates(store)
    challenge = gates.present(
        change.change_id, GateKind.ARCHITECTURE, artifact.artifact_id
    )
    with pytest.raises(ChangeConflict):
        store.transition(
            change.change_id,
            ChangeState.APPROVED_FOR_BUILD,
            expected_version=store.require(change.change_id).version,
        )
    gates.decide(
        challenge.gate_id,
        approved=False,
        artifact_digest=artifact.digest,
        actor_id="owner",
        source_session_id="owner-session",
        source_turn_id="reject-turn",
        request_key="owner-session:reject-turn",
    )
    assert store.require(change.change_id).state is ChangeState.REJECTED


def test_promotion_decision_records_intent_without_claiming_promotion(tmp_path) -> None:
    store, change, _ = _architecture_ready(tmp_path)
    # Stage progression is simulated only to exercise the promotion boundary.
    with store.work._lock, store.work._connect() as db:
        db.execute(
            "UPDATE engineering_changes SET state=? WHERE change_id=?",
            (ChangeState.READY_FOR_PROMOTION.value, change.change_id),
        )
    artifact = store.add_artifact(
        change.change_id, kind="promotion", payload={"pr": "#123"}
    )
    gates = _trusted_gates(store)
    challenge = gates.present(
        change.change_id, GateKind.PROMOTION, artifact.artifact_id
    )
    decision = gates.decide(
        challenge.gate_id,
        approved=True,
        artifact_digest=artifact.digest,
        actor_id="owner",
        source_session_id="owner-session",
        source_turn_id="approval-turn",
        request_key="promote:123",
    )
    assert decision.approved
    assert (
        store.require(change.change_id).state is ChangeState.WAITING_PROMOTION_APPROVAL
    )
