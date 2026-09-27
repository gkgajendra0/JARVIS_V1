"""Owner-session Phase-7 approval path: exact gate -> one-shot permit -> merge."""

from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.engineering_change.gates import GateDecision, GateKind, GateService
from jarvis.engineering_change.models import ChangeConflict
from jarvis.engineering_change.store import ChangeStore

from .authority import PromotionAuthorityBridge
from .merge import MergeResult, PromotionMerger
from .models import PromotionAttemptState, PromotionEvidenceV1
from .store import PromotionStore

_GATE_DECISION = re.compile(
    r"\s*approve\s+(gate_[0-9a-f]{16})[.!]?\s*",
    re.IGNORECASE,
)
_TYPED_DECISION = re.compile(
    r"\s*approve\s+promotion(?:\s+(?:proposal|gate))?[.!]?\s*",
    re.IGNORECASE,
)


class PromotionSessionError(ChangeConflict):
    pass


@dataclass(frozen=True, slots=True)
class PromotionExecutionResult:
    gate_decision: GateDecision
    merge: MergeResult
    evidence: PromotionEvidenceV1


class PromotionSessionService:
    """Consume only the latest canonical owner approval and merge immediately."""

    def __init__(
        self,
        changes: ChangeStore,
        promotions: PromotionStore,
        *,
        session: ConversationSession,
        authority: PromotionAuthorityBridge,
        merger: PromotionMerger,
        repository_full_name: str,
    ) -> None:
        if promotions.changes is not changes:
            raise ValueError("promotion store must share the canonical ChangeStore")
        if not isinstance(session, ConversationSession):
            raise TypeError("session must be ConversationSession")
        self._changes = changes
        self._promotions = promotions
        self._session = session
        self._authority = authority
        self._merger = merger
        self._repository = str(repository_full_name).strip()
        if not self._repository:
            raise ValueError("repository_full_name must not be empty")

    def _latest_owner_turn(self):
        turn = next(
            (
                candidate
                for candidate in reversed(self._session.turns)
                if candidate.role is ConversationRole.USER
            ),
            None,
        )
        if turn is None or not any(
            candidate is turn for candidate in self._session.turns
        ):
            raise PromotionSessionError("no accepted canonical owner turn")
        return turn

    def authorize_and_merge(self, gate_id: str) -> PromotionExecutionResult:
        turn = self._latest_owner_turn()
        named = _GATE_DECISION.fullmatch(turn.text)
        typed = _TYPED_DECISION.fullmatch(turn.text)
        if named is None and typed is None:
            raise PromotionSessionError(
                "owner must explicitly approve the current promotion gate"
            )
        if named is not None and named.group(1) != gate_id:
            raise PromotionSessionError("owner named a different promotion gate")

        gates = GateService(self._changes, verify_owner=lambda *_: False)
        gate = gates.get(gate_id)
        if gate is None:
            raise PromotionSessionError("unknown promotion gate")
        challenge = gate.challenge if isinstance(gate, GateDecision) else gate
        if challenge.kind is not GateKind.PROMOTION:
            raise PromotionSessionError("gate is not a promotion gate")
        if typed is not None and gates.pending_gate_ids() != (gate_id,):
            raise PromotionSessionError(
                "spoken promotion review is ambiguous; identify the gate ID"
            )

        artifact = self._changes.get_artifact(challenge.artifact_id)
        if artifact is None or artifact.kind != "promotion":
            raise PromotionSessionError("promotion evidence artifact is unavailable")
        try:
            evidence = PromotionEvidenceV1.from_payload(artifact.payload)
        except ValueError as exc:
            raise PromotionSessionError("promotion evidence is invalid") from exc
        attempt = self._promotions.require(evidence.attempt_id)
        if attempt.state in {
            PromotionAttemptState.MERGED,
            PromotionAttemptState.DEPLOYING,
            PromotionAttemptState.OBSERVING,
            PromotionAttemptState.COMPLETED,
            PromotionAttemptState.ROLLED_BACK,
        }:
            if not isinstance(gate, GateDecision) or not gate.approved:
                raise PromotionSessionError(
                    "post-merge promotion has no durable approved gate"
                )
            if attempt.merge_sha is None:
                raise PromotionSessionError(
                    "post-merge promotion has no durable merge identity"
                )
            return PromotionExecutionResult(
                gate_decision=gate,
                merge=MergeResult(
                    merge_sha=attempt.merge_sha,
                    reconciled_after_external_merge=True,
                ),
                evidence=evidence,
            )

        authorized = self._authority.authorize(
            gate_id=gate_id,
            evidence=evidence,
            attempt=attempt,
            session_id=self._session.session_id,
            source_turn_id=turn.turn_id,
            request_key=(f"phase7-promotion:{self._session.session_id}:{turn.turn_id}"),
            repository_full_name=self._repository,
        )
        merge = self._merger.execute(
            evidence=evidence,
            attempt=self._promotions.require(attempt.attempt_id),
            authorized=authorized,
        )
        decision = GateService(
            self._changes,
            verify_owner=lambda *_: False,
        ).get(gate_id)
        if not isinstance(decision, GateDecision) or not decision.approved:
            raise PromotionSessionError(
                "promotion execution completed without durable approved gate"
            )
        return PromotionExecutionResult(
            gate_decision=decision,
            merge=merge,
            evidence=evidence,
        )
