"""Trusted owner interaction adapter over change records and canonical WorkItems."""

from __future__ import annotations

import json
import re

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
        self, coordinator: ChangeCoordinator, session: ConversationSession
    ) -> None:
        self.coordinator = coordinator
        self.session = session

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
        if change.state is not ChangeState.RESEARCHING:
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
        artifact = store.add_artifact(change_id, kind="architecture", payload=payload)
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
        decision = gates.decide(
            gate_id,
            approved=match.group(1).casefold() == "approve",
            artifact_digest=challenge.artifact_digest,
            actor_id="owner",
            source_session_id=self.session.session_id,
            source_turn_id=turn.turn_id,
            request_key=f"change-decision:{self.session.session_id}:{turn.turn_id}",
        )
        self.coordinator.reconcile(challenge.change_id)
        return decision
