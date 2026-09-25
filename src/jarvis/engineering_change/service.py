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
_SINGLE_REVIEW = re.compile(
    r"\s*(approve|reject)\s+(architecture|acceptance|promotion)(?:\s+(?:proposal|gate))?[.!]?\s*",
    re.IGNORECASE,
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
                f"To decide, say 'approve architecture' if this is the only pending "
                f"review, or 'approve {gate.gate_id}' to identify it exactly. "
                f"Say 'reject architecture' or 'reject {gate.gate_id}' to decline."
            ),
            event_key=f"change:{change_id}:{gate.gate_id}:{artifact.digest}",
        )
        return gate

    def revise_architecture(
        self, change_id: str, payload: dict[str, object]
    ) -> GateChallenge:
        """Supersede an approved architecture and reopen its exact owner gate safely."""
        store = self.coordinator.store
        change = store.require(change_id)
        current = store.latest_artifact(change_id, "architecture")
        if current is None:
            raise ChangeConflict("architecture revision requires an existing proposal")
        if not isinstance(payload, dict) or not payload:
            raise ChangeConflict("architecture proposal is empty")
        rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(rendered.encode("utf-8")) > 16_384:
            raise ChangeConflict("architecture proposal exceeds review limit")

        recovery_states = {
            ChangeState.ARCHITECTURE_READY,
            ChangeState.WAITING_OWNER_APPROVAL,
        }
        downstream_states = {
            ChangeState.APPROVED_FOR_BUILD,
            ChangeState.DEVELOPING,
            ChangeState.VERIFYING,
            ChangeState.WAITING_OWNER_ACCEPTANCE,
            ChangeState.READY_FOR_PROMOTION,
            ChangeState.WAITING_PROMOTION_APPROVAL,
        }
        if change.state in recovery_states:
            if current.revision < 2 or current.payload != payload:
                raise ChangeConflict(
                    "architecture revision differs from the pending reviewed revision"
                )
            return self.propose_architecture(change_id, payload)
        if change.state not in downstream_states:
            raise ChangeConflict(
                "architecture revision requires an approved or downstream change"
            )
        if current.payload == payload:
            raise ChangeConflict(\n                "architecture revision must change the current proposal"\n            )

        store.add_artifact(change_id, kind="architecture", payload=payload)
        return self.propose_architecture(change_id, payload)

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
        typed = _SINGLE_REVIEW.fullmatch(turn.text)
        if match is None and typed is None:
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
        if (
            isinstance(gate, GateDecision)
            and gate.verification_id is not None
            and gate.source_session_id == self.session.session_id
            and gate.source_turn_id == turn.turn_id
            and gate.approved == ((match or typed).group(1).casefold() == "approve")
            and (match is None or match.group(2) == gate_id)
            and (typed is None or typed.group(2).casefold() == challenge.kind.value)
        ):
            self.coordinator.reconcile(challenge.change_id)
            return gate
        if match is not None and match.group(2) != gate_id:
            raise ChangeConflict("owner named a different gate")
        if typed is not None and (
            typed.group(2).casefold() != challenge.kind.value
            or gates.pending_gate_ids() != (gate_id,)
        ):
            raise ChangeConflict("spoken review is ambiguous; identify the gate ID")
        approved = (match or typed).group(1).casefold() == "approve"
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

    def prepare_promotion(self, change_id: str) -> GateChallenge:
        """Present promotion intent without performing any merge or deployment."""
        store = self.coordinator.store
        change = store.require(change_id)
        if change.state not in {
            ChangeState.READY_FOR_PROMOTION,
            ChangeState.WAITING_PROMOTION_APPROVAL,
        }:
            raise ChangeConflict("change is not ready for promotion review")
        acceptance = store.latest_artifact(change_id, "acceptance")
        if acceptance is None:
            raise ChangeConflict("promotion requires accepted development evidence")

        promotion = store.latest_artifact(change_id, "promotion")
        payload = {
            "acceptance_artifact_id": acceptance.artifact_id,
            "acceptance_digest": acceptance.digest,
            "work_id": acceptance.payload.get("work_id"),
            "result": acceptance.payload.get("result"),
        }
        if change.state is ChangeState.READY_FOR_PROMOTION:
            if promotion is None:
                promotion = store.add_artifact(
                    change_id, kind="promotion", payload=payload
                )
            elif promotion.payload != payload:
                raise ChangeConflict(
                    "promotion review does not match current acceptance"
                )
        elif promotion is None or promotion.payload != payload:
            raise ChangeConflict("promotion review does not match current acceptance")
        gate = GateService(store, verify_owner=lambda *_: False).present(
            change_id, GateKind.PROMOTION, promotion.artifact_id
        )
        work_id = str(acceptance.payload.get("work_id", ""))
        stage = store.stage_for_work(work_id)
        if stage is None or stage.change_id != change_id:
            raise ChangeConflict("promotion evidence has no canonical development")
        work = store.work.require(work_id)
        result = acceptance.payload.get("result")
        branch = result.get("branch") if isinstance(result, dict) else None
        commit = result.get("commit") if isinstance(result, dict) else None
        store.work.enqueue_delivery(
            work=work,
            kind=WorkDeliveryKind.OWNER_INPUT,
            message=(
                f"Review EngineeringChange {change_id} promotion intent for "
                f"branch {branch}, commit {commit}. Digest: {promotion.digest}. "
                f"Approval records promotion intent only and does not push, merge, "
                f"deploy, or mark the change promoted. Say 'approve promotion' for "
                f"a single pending review, or 'approve {gate.gate_id}' to identify "
                f"it exactly. Use 'reject promotion' or 'reject {gate.gate_id}' to decline."
            ),
            event_key=f"change:{change_id}:{gate.gate_id}:{promotion.digest}",
        )
        return gate

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
                f"Say 'approve acceptance' for a single pending review, or "
                f"'approve {gate.gate_id}' to identify it exactly. "
                f"Use 'reject acceptance' or 'reject {gate.gate_id}' to decline."
            ),
            event_key=f"change:{change_id}:{gate.gate_id}:{artifact.digest}",
        )
        return gate
