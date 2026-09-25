"""Trusted owner interaction adapter over change records and canonical WorkItems."""

from __future__ import annotations

import json
import re

from jarvis.authority.approval import ApprovalService
from jarvis.authority.proposal import ActionProposal
from jarvis.authority.strong_approval import StrongApprovalService
from jarvis.authority.types import ActionAttributes, ActionOrigin
from jarvis.authority.verifier import WindowsHelloVerifier
from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.work.models import WorkDeliveryKind, WorkState

from .coordinator import ChangeCoordinator
from .gates import GateChallenge, GateDecision, GateKind, GateService
from .models import ChangeConflict, ChangeState, EngineeringChange

_DECISION = re.compile(
    r"\s*(approve|reject)\s+(gate_[0-9a-f]{16})[.!]?\s*", re.IGNORECASE
)


class ChangeService:
    """Only accepted USER turns from this session can produce gate decisions."""

    def __init__(
        self,
        coordinator: ChangeCoordinator,
        session: ConversationSession,
        *,
        strong_approval: StrongApprovalService | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.session = session
        self._strong_approval = strong_approval or StrongApprovalService(
            approvals=ApprovalService(), verifier=WindowsHelloVerifier()
        )

    def start(self, turn: ConversationTurn) -> EngineeringChange:
        if turn.role is not ConversationRole.USER or not any(
            candidate is turn for candidate in self.session.turns
        ):
            raise ChangeConflict("change requires an accepted canonical owner turn")
        return self.coordinator.start(turn.text, self.session.session_id, turn.turn_id)

    def propose_architecture(
        self, change_id: str, payload: dict[str, object]
    ) -> GateChallenge:
        store = self.coordinator.store
        change = store.require(change_id)
        if change.state not in {
            ChangeState.RESEARCHING,
            ChangeState.ARCHITECTURE_READY,
            ChangeState.WAITING_OWNER_APPROVAL,
        }:
            raise ChangeConflict("architecture requires completed research")
        stages = store.list_stages(change_id)
        research = next((s for s in stages if s.stage_key == "research"), None)
        if (
            research is None
            or store.work.require(research.work_id).state is not WorkState.COMPLETED
        ):
            raise ChangeConflict("research WorkItem has not completed")
        if not isinstance(payload, dict) or not payload:
            raise ChangeConflict("architecture proposal is empty")
        rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(rendered.encode("utf-8")) > 16_384:
            raise ChangeConflict("architecture proposal exceeds review limit")
        artifact = store.latest_artifact(change_id, "architecture")
        if change.state is ChangeState.RESEARCHING and artifact is None:
            artifact = store.add_artifact(
                change_id, kind="architecture", payload=payload
            )
        elif artifact is None or artifact.payload != payload:
            raise ChangeConflict("architecture revision differs from current review")
        if change.state is ChangeState.RESEARCHING:
            self.coordinator.reconcile(change_id)
        # This callback never creates approval authority: only decide_latest can
        # use the exact current canonical USER turn to resolve this challenge.
        gate = GateService(store, verify_owner=lambda *_: False).present(
            change_id, GateKind.ARCHITECTURE, artifact.artifact_id
        )
        store.work.enqueue_delivery(
            work=store.work.require(research.work_id),
            kind=WorkDeliveryKind.OWNER_INPUT,
            message=(
                f"Review EngineeringChange {change_id} architecture revision "
                f"{artifact.revision}: {rendered}. Digest: {artifact.digest}. "
                f"To decide, say 'approve {gate.gate_id}' or 'reject {gate.gate_id}'."
            ),
            event_key=f"change:{change_id}:{gate.gate_id}:{artifact.digest}",
        )
        return gate

    def decide_latest(self, gate_id: str) -> GateDecision:
        turn = next(
            (
                candidate
                for candidate in reversed(self.session.turns)
                if candidate.role is ConversationRole.USER
            ),
            None,
        )
        if turn is None:
            raise ChangeConflict("no accepted owner turn")
        match = _DECISION.fullmatch(turn.text)
        if match is None or match.group(2) != gate_id:
            raise ChangeConflict("owner must explicitly identify the current gate")
        store = self.coordinator.store
        verification = lambda actor, source_session, source_turn, gate, digest: (
            actor == "owner"
            and source_session == self.session.session_id
            and source_turn == turn.turn_id
            and gate.gate_id == gate_id
            and digest == gate.artifact_digest
            and any(candidate is turn for candidate in self.session.turns)
            and next(
                (
                    candidate
                    for candidate in reversed(self.session.turns)
                    if candidate.role is ConversationRole.USER
                ),
                None,
            )
            is turn
        )
        gates = GateService(store, verify_owner=verification)
        gate = gates.get(gate_id)
        if gate is None:
            raise ChangeConflict("unknown gate")
        challenge = gate.challenge if isinstance(gate, GateDecision) else gate
        approved = match.group(1).casefold() == "approve"
        proposal = ActionProposal.create(
            session_id=self.session.session_id,
            capability="engineering_change",
            operation=f"decide_{challenge.kind.value}",
            target={"change_id": challenge.change_id, "gate_id": gate_id},
            parameters={
                "artifact_id": challenge.artifact_id,
                "digest": challenge.artifact_digest,
                "approved": approved,
                "source_turn_id": turn.turn_id,
            },
            material_summary=(
                f"{'Approve' if approved else 'Reject'} EngineeringChange "
                f"{challenge.change_id} {challenge.kind.value} gate {gate_id}, "
                f"artifact SHA-256 {challenge.artifact_digest}"
            ),
            attributes=ActionAttributes(persistent_write=True),
            origin=ActionOrigin.DIRECT_USER,
        )
        outcome = self._strong_approval.verify_and_resolve(
            proposal=proposal, session_id=self.session.session_id
        )
        if not outcome.granted or not outcome.verification.is_bound_to(
            proposal=proposal, session_id=self.session.session_id
        ):
            raise ChangeConflict("strong owner verification required for change gate")
        decision = gates.decide(
            gate_id,
            approved=approved,
            artifact_digest=challenge.artifact_digest,
            actor_id="owner",
            source_session_id=self.session.session_id,
            source_turn_id=turn.turn_id,
            request_key=f"change-decision:{self.session.session_id}:{turn.turn_id}",
            verification_id=outcome.verification.verification_id,
            verifier_id=outcome.verification.verifier_id,
            proposal_fingerprint=proposal.fingerprint,
        )
        self.coordinator.reconcile(challenge.change_id)
        return decision

    def prepare_acceptance(self, change_id: str) -> GateChallenge:
        """Present canonical development evidence; never trust a model pass claim."""
        store = self.coordinator.store
        change = store.require(change_id)
        if change.state is not ChangeState.VERIFYING:
            raise ChangeConflict("change has not reached verification")
        stage = next(
            (
                s
                for s in reversed(store.list_stages(change_id))
                if s.stage_key == "development"
            ),
            None,
        )
        if stage is None:
            raise ChangeConflict("development stage is missing")
        work = store.work.require(stage.work_id)
        result = work.result
        if (
            work.state is not WorkState.COMPLETED
            or not isinstance(result.get("verification"), dict)
            or result["verification"].get("passed") is not True
            or not result.get("commit")
            or not result.get("branch")
        ):
            raise ChangeConflict("canonical development has no verified commit")
        payload = {"work_id": stage.work_id, "result": result}
        artifact = store.add_artifact(change_id, kind="acceptance", payload=payload)
        gate = GateService(store, verify_owner=lambda *_: False).present(
            change_id, GateKind.ACCEPTANCE, artifact.artifact_id
        )
        store.work.enqueue_delivery(
            work=work,
            kind=WorkDeliveryKind.OWNER_INPUT,
            message=(
                f"Review EngineeringChange {change_id} acceptance: branch "
                f"{result['branch']}, commit {result['commit']}, tests passed in "
                f"{result['verification'].get('sandbox')}. Digest: {artifact.digest}. "
                f"Say 'approve {gate.gate_id}' or 'reject {gate.gate_id}'."
            ),
            event_key=f"change:{change_id}:{gate.gate_id}:{artifact.digest}",
        )
        return gate
