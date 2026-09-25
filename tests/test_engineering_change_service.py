from __future__ import annotations

import pytest

from jarvis.authority.approval import ApprovalService
from jarvis.authority.strong_approval import StrongApprovalService
from jarvis.authority.verifier import StrongVerificationResult, StrongVerificationStatus
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.engineering_change.acceptance import inspect_change
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.models import ChangeConflict, ChangeState
from jarvis.engineering_change.service import ChangeService
from jarvis.engineering_change.store import ChangeStore
from jarvis.work.models import WorkState
from jarvis.work.store import SQLiteWorkStore


class Backend:
    def submit(self, work_id, *, priority):
        return work_id


class VerifiedOwner:
    def verify(self, *, proposal, session_id):
        return StrongVerificationResult(
            status=StrongVerificationStatus.VERIFIED,
            verifier_id="fixture",
            verification_id=proposal.proposal_id,
            proposal_fingerprint=proposal.fingerprint,
            session_id=session_id,
        )


class UnavailableOwner:
    def verify(self, *, proposal, session_id):
        return StrongVerificationResult(
            status=StrongVerificationStatus.UNAVAILABLE,
            verifier_id="fixture",
            proposal_fingerprint=proposal.fingerprint,
            session_id=session_id,
        )


def _service(store, session):
    return ChangeService(
        ChangeCoordinator(store, Backend()),
        session,
        strong_approval=StrongApprovalService(
            approvals=ApprovalService(), verifier=VerifiedOwner()
        ),
    )


def test_only_explicit_canonical_owner_turn_can_decide_current_gate(tmp_path) -> None:
    session = ConversationSession(session_id="owner-session")
    session.start()
    initial = session.accept_turn(ConversationRole.USER, "Build camera support")
    store = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    service = _service(store, session)
    change = service.start(initial)
    research = store.list_stages(change.change_id)[0]
    work = store.work.require(research.work_id)
    running = store.work.save(
        work.transition(WorkState.RUNNING), expected_version=work.version
    )
    store.work.save(
        running.transition(WorkState.COMPLETED), expected_version=running.version
    )
    gate = service.propose_architecture(change.change_id, {"plan": "typed adapter"})
    assert store.require(change.change_id).state is ChangeState.WAITING_OWNER_APPROVAL
    session.accept_turn(ConversationRole.ASSISTANT, f"I approve {gate.gate_id}")
    with pytest.raises(ChangeConflict):
        service.decide_latest(gate.gate_id)
    session.accept_turn(ConversationRole.USER, "yes")
    with pytest.raises(ChangeConflict):
        service.decide_latest(gate.gate_id)
    session.accept_turn(ConversationRole.USER, f"Approve {gate.gate_id}")
    decision = service.decide_latest(gate.gate_id)
    assert decision.approved
    assert decision.verification_id is not None
    assert decision.verifier_id == "fixture"
    assert store.require(change.change_id).state is ChangeState.DEVELOPING
    assert len(store.list_stages(change.change_id)) == 2


def test_model_cannot_use_an_older_matching_turn_for_a_new_gate(tmp_path) -> None:
    session = ConversationSession(session_id="owner-session")
    session.start()
    initial = session.accept_turn(ConversationRole.USER, "New adapter")
    store = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    service = _service(store, session)
    change = service.start(initial)
    research = store.list_stages(change.change_id)[0]
    item = store.work.require(research.work_id)
    running = store.work.save(
        item.transition(WorkState.RUNNING), expected_version=item.version
    )
    store.work.save(
        running.transition(WorkState.COMPLETED), expected_version=running.version
    )
    gate = service.propose_architecture(change.change_id, {"plan": "a"})
    session.accept_turn(ConversationRole.USER, f"Approve {gate.gate_id}")
    session.accept_turn(ConversationRole.USER, "Check status")
    with pytest.raises(ChangeConflict):
        service.decide_latest(gate.gate_id)


def test_explicit_turn_cannot_approve_without_strong_owner_verification(
    tmp_path,
) -> None:
    session = ConversationSession(session_id="owner-session")
    session.start()
    initial = session.accept_turn(ConversationRole.USER, "New adapter")
    store = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    service = ChangeService(
        ChangeCoordinator(store, Backend()),
        session,
        strong_approval=StrongApprovalService(
            approvals=ApprovalService(), verifier=UnavailableOwner()
        ),
    )
    change = service.start(initial)
    research = store.list_stages(change.change_id)[0]
    item = store.work.require(research.work_id)
    running = store.work.save(
        item.transition(WorkState.RUNNING), expected_version=item.version
    )
    store.work.save(
        running.transition(WorkState.COMPLETED), expected_version=running.version
    )
    gate = service.propose_architecture(change.change_id, {"plan": "a"})
    session.accept_turn(ConversationRole.USER, f"Approve {gate.gate_id}")
    with pytest.raises(ChangeConflict, match="strong owner verification"):
        service.decide_latest(gate.gate_id)
    assert store.require(change.change_id).state is ChangeState.WAITING_OWNER_APPROVAL


def test_acceptance_challenge_requires_canonical_verified_development(tmp_path) -> None:
    session = ConversationSession(session_id="owner-session")
    session.start()
    initial = session.accept_turn(ConversationRole.USER, "New adapter")
    store = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    service = _service(store, session)
    change = service.start(initial)
    research = store.list_stages(change.change_id)[0]
    item = store.work.require(research.work_id)
    running = store.work.save(
        item.transition(WorkState.RUNNING), expected_version=item.version
    )
    store.work.save(
        running.transition(WorkState.COMPLETED), expected_version=running.version
    )
    gate = service.propose_architecture(change.change_id, {"plan": "a"})
    session.accept_turn(ConversationRole.USER, f"Approve {gate.gate_id}")
    service.decide_latest(gate.gate_id)
    development = store.list_stages(change.change_id)[1]
    item = store.work.require(development.work_id)
    running = store.work.save(
        item.transition(WorkState.RUNNING), expected_version=item.version
    )
    store.work.save(
        running.transition(WorkState.COMPLETED), expected_version=running.version
    )
    service.coordinator.reconcile_for_work(development.work_id)
    with pytest.raises(ChangeConflict, match="verified"):
        service.prepare_acceptance(change.change_id)


def test_verified_commit_requires_separate_owner_acceptance(tmp_path) -> None:
    session = ConversationSession(session_id="owner-session")
    session.start()
    initial = session.accept_turn(ConversationRole.USER, "New adapter")
    store = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    service = _service(store, session)
    change = service.start(initial)
    research = store.list_stages(change.change_id)[0]
    item = store.work.require(research.work_id)
    running = store.work.save(
        item.transition(WorkState.RUNNING), expected_version=item.version
    )
    store.work.save(
        running.transition(WorkState.COMPLETED), expected_version=running.version
    )
    gate = service.propose_architecture(change.change_id, {"plan": "a"})
    session.accept_turn(ConversationRole.USER, f"Approve {gate.gate_id}")
    service.decide_latest(gate.gate_id)
    development = store.list_stages(change.change_id)[1]
    item = store.work.require(development.work_id)
    running = store.work.save(
        item.transition(WorkState.RUNNING), expected_version=item.version
    )
    store.work.save(
        running.transition(
            WorkState.COMPLETED,
            result={
                "branch": "isolated",
                "commit": "a" * 40,
                "verification": {"passed": True, "sandbox": "isolated"},
            },
        ),
        expected_version=running.version,
    )
    service.coordinator.reconcile_for_work(development.work_id)
    acceptance = service.prepare_acceptance(change.change_id)
    assert store.require(change.change_id).state is ChangeState.WAITING_OWNER_ACCEPTANCE
    session.accept_turn(ConversationRole.USER, "Approve acceptance")
    accepted = service.decide_latest(acceptance.gate_id)
    assert service.decide_latest(acceptance.gate_id) == accepted
    assert store.require(change.change_id).state is ChangeState.READY_FOR_PROMOTION
    report = inspect_change(store, change.change_id)
    assert report["result"] == "PENDING"
    assert set(report["store_gates"].values()) == {"PASS"}


def test_restart_resends_same_architecture_gate_and_delivery(tmp_path) -> None:
    session = ConversationSession(session_id="owner-session")
    session.start()
    initial = session.accept_turn(ConversationRole.USER, "New adapter")
    store = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    service = _service(store, session)
    change = service.start(initial)
    research = store.list_stages(change.change_id)[0]
    item = store.work.require(research.work_id)
    running = store.work.save(
        item.transition(WorkState.RUNNING), expected_version=item.version
    )
    store.work.save(
        running.transition(WorkState.COMPLETED), expected_version=running.version
    )
    gate = service.propose_architecture(change.change_id, {"plan": "a"})
    restarted = _service(ChangeStore(SQLiteWorkStore(store.work.path)), session)
    retry = restarted.propose_architecture(change.change_id, {"plan": "a"})
    assert retry == gate
    assert store.latest_artifact(change.change_id, "architecture").revision == 1
    assert len(store.work.list_pending_deliveries()) == 1
    with pytest.raises(ChangeConflict):
        restarted.propose_architecture(change.change_id, {"plan": "different"})


def test_short_spoken_review_requires_one_pending_gate(tmp_path) -> None:
    session = ConversationSession(session_id="owner-session")
    session.start()
    store = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    service = _service(store, session)
    gates = []
    for goal in ("First goal", "Second goal"):
        change = service.start(session.accept_turn(ConversationRole.USER, goal))
        research = store.list_stages(change.change_id)[0]
        item = store.work.require(research.work_id)
        running = store.work.save(
            item.transition(WorkState.RUNNING), expected_version=item.version
        )
        store.work.save(
            running.transition(WorkState.COMPLETED), expected_version=running.version
        )
        gates.append(service.propose_architecture(change.change_id, {"plan": goal}))
    session.accept_turn(ConversationRole.USER, "Approve architecture")
    with pytest.raises(ChangeConflict, match="ambiguous"):
        service.decide_latest(gates[0].gate_id)
    assert all(
        store.require(gate.change_id).state is ChangeState.WAITING_OWNER_APPROVAL
        for gate in gates
    )
