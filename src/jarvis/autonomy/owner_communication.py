"""Supervisor-owned owner communication contracts.

Specialists and deterministic subsystems emit typed communication intents. The Global
Supervisor communication boundary decides whether an owner-visible message exists and
renders the one JARVIS voice. WorkDelivery remains the durable transport.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from jarvis.engineering_substrate.canonical import canonical_digest


class OwnerCommunicationKind(StrEnum):
    PROGRESS = "progress"
    BLOCKER = "blocker"
    OWNER_INPUT = "owner_input"
    CHANGE_GATE = "change_gate"
    COMPLETION = "completion"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class OwnerCommunicationIntentV1:
    schema: str
    kind: OwnerCommunicationKind
    event_key: str
    summary: str
    owner_action_required: bool
    terminal: bool
    goal_id: str | None
    change_id: str | None
    work_id: str | None
    system_outcome_kind: str | None
    gate_id: str | None
    artifact_digest: str | None
    artifact_revision: int | None
    proposal_summary: dict[str, object]
    technical_detail: str | None
    digest: str

    @classmethod
    def create(
        cls,
        *,
        kind: OwnerCommunicationKind,
        event_key: str,
        summary: str,
        owner_action_required: bool = False,
        terminal: bool = False,
        goal_id: str | None = None,
        change_id: str | None = None,
        work_id: str | None = None,
        system_outcome_kind: str | None = None,
        gate_id: str | None = None,
        artifact_digest: str | None = None,
        artifact_revision: int | None = None,
        proposal_summary: dict[str, object] | None = None,
        technical_detail: str | None = None,
    ) -> OwnerCommunicationIntentV1:
        if not isinstance(kind, OwnerCommunicationKind):
            raise TypeError("kind must be OwnerCommunicationKind")
        normalized_event = str(event_key).strip()
        normalized_summary = " ".join(str(summary).split()).strip()
        if not normalized_event:
            raise ValueError("event_key must not be empty")
        if not normalized_summary:
            raise ValueError("summary must not be empty")
        if kind in {OwnerCommunicationKind.OWNER_INPUT, OwnerCommunicationKind.CHANGE_GATE}:
            owner_action_required = True
        if kind is OwnerCommunicationKind.CHANGE_GATE:
            if not str(gate_id or "").strip():
                raise ValueError("change gate communication requires gate_id")
            if not str(artifact_digest or "").strip():
                raise ValueError("change gate communication requires artifact_digest")
            if artifact_revision is None or artifact_revision <= 0:
                raise ValueError("change gate communication requires artifact_revision")
        payload = {
            "schema": "owner_communication_intent.v1",
            "kind": kind.value,
            "event_key": normalized_event,
            "summary": normalized_summary,
            "owner_action_required": bool(owner_action_required),
            "terminal": bool(terminal),
            "goal_id": _optional(goal_id),
            "change_id": _optional(change_id),
            "work_id": _optional(work_id),
            "system_outcome_kind": _optional(system_outcome_kind),
            "gate_id": _optional(gate_id),
            "artifact_digest": _optional(artifact_digest),
            "artifact_revision": artifact_revision,
            "proposal_summary": dict(proposal_summary or {}),
            "technical_detail": _optional(technical_detail),
        }
        return cls(
            schema="owner_communication_intent.v1",
            kind=kind,
            event_key=normalized_event,
            summary=normalized_summary,
            owner_action_required=bool(owner_action_required),
            terminal=bool(terminal),
            goal_id=payload["goal_id"],
            change_id=payload["change_id"],
            work_id=payload["work_id"],
            system_outcome_kind=payload["system_outcome_kind"],
            gate_id=payload["gate_id"],
            artifact_digest=payload["artifact_digest"],
            artifact_revision=artifact_revision,
            proposal_summary=dict(payload["proposal_summary"]),
            technical_detail=payload["technical_detail"],
            digest=canonical_digest(payload),
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "kind": self.kind.value,
            "event_key": self.event_key,
            "summary": self.summary,
            "owner_action_required": self.owner_action_required,
            "terminal": self.terminal,
            "goal_id": self.goal_id,
            "change_id": self.change_id,
            "work_id": self.work_id,
            "system_outcome_kind": self.system_outcome_kind,
            "gate_id": self.gate_id,
            "artifact_digest": self.artifact_digest,
            "artifact_revision": self.artifact_revision,
            "proposal_summary": self.proposal_summary,
            "technical_detail": self.technical_detail,
        }

    def __post_init__(self) -> None:
        if self.schema != "owner_communication_intent.v1":
            raise ValueError("unsupported owner communication intent schema")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("owner communication intent digest mismatch")


@dataclass(frozen=True, slots=True)
class SupervisorOwnerMessageV1:
    schema: str
    kind: OwnerCommunicationKind
    event_key: str
    message: str
    owner_action_required: bool
    goal_id: str | None
    change_id: str | None
    work_id: str | None
    intent_digest: str
    digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "kind": self.kind.value,
            "event_key": self.event_key,
            "message": self.message,
            "owner_action_required": self.owner_action_required,
            "goal_id": self.goal_id,
            "change_id": self.change_id,
            "work_id": self.work_id,
            "intent_digest": self.intent_digest,
        }

    def __post_init__(self) -> None:
        if self.schema != "supervisor_owner_message.v1":
            raise ValueError("unsupported supervisor owner message schema")
        if not self.message.strip():
            raise ValueError("owner message must not be empty")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("supervisor owner message digest mismatch")


class SupervisorOwnerCommunication:
    """Deterministically decide visibility and render the one owner-facing JARVIS voice."""

    @staticmethod
    def compile(
        intent: OwnerCommunicationIntentV1,
    ) -> SupervisorOwnerMessageV1 | None:
        if not isinstance(intent, OwnerCommunicationIntentV1):
            raise TypeError("intent must be OwnerCommunicationIntentV1")

        # Internal specialist trouble is system evidence, not automatically an owner
        # failure or interruption.
        if intent.kind is OwnerCommunicationKind.FAILURE and not intent.terminal:
            return None
        if (
            intent.kind is OwnerCommunicationKind.BLOCKER
            and not intent.owner_action_required
        ):
            return None

        message = SupervisorOwnerCommunication._render(intent)
        payload = {
            "schema": "supervisor_owner_message.v1",
            "kind": intent.kind.value,
            "event_key": intent.event_key,
            "message": message,
            "owner_action_required": intent.owner_action_required,
            "goal_id": intent.goal_id,
            "change_id": intent.change_id,
            "work_id": intent.work_id,
            "intent_digest": intent.digest,
        }
        return SupervisorOwnerMessageV1(
            schema="supervisor_owner_message.v1",
            kind=intent.kind,
            event_key=intent.event_key,
            message=message,
            owner_action_required=intent.owner_action_required,
            goal_id=intent.goal_id,
            change_id=intent.change_id,
            work_id=intent.work_id,
            intent_digest=intent.digest,
            digest=canonical_digest(payload),
        )

    @staticmethod
    def _render(intent: OwnerCommunicationIntentV1) -> str:
        if intent.kind is OwnerCommunicationKind.CHANGE_GATE:
            assert intent.gate_id is not None
            assert intent.artifact_digest is not None
            assert intent.artifact_revision is not None
            proposal = json.dumps(
                intent.proposal_summary,
                ensure_ascii=False,
                sort_keys=True,
            )
            return (
                "The architecture is ready for your approval before I start "
                f"development. Proposal: {proposal}. Revision "
                f"{intent.artifact_revision}; artifact SHA-256: "
                f"{intent.artifact_digest}. Say 'approve {intent.gate_id}' to "
                f"approve it or 'reject {intent.gate_id}' to reject it."
            )
        if intent.kind is OwnerCommunicationKind.OWNER_INPUT:
            return f"I need your input before I can continue: {intent.summary}"
        if intent.kind is OwnerCommunicationKind.PROGRESS:
            return f"Update: {intent.summary}"
        if intent.kind is OwnerCommunicationKind.BLOCKER:
            return f"I need your help to continue: {intent.summary}"
        if intent.kind is OwnerCommunicationKind.COMPLETION:
            return f"Completed: {intent.summary}"
        return f"I can't continue with this objective: {intent.summary}"


def _optional(value: object) -> str | None:
    normalized = " ".join(str(value or "").split()).strip()
    return normalized or None
