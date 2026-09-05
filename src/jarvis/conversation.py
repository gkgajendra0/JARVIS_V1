"""Provider-independent conversation truth for JARVIS."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


def _new_id() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ConversationStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    CLOSED = "closed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    role: ConversationRole
    text: str
    interrupted: bool = False
    turn_id: str = field(default_factory=_new_id)
    accepted_at: datetime = field(default_factory=_utc_now)
    external_item_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.role, ConversationRole):
            raise TypeError("role must be a ConversationRole")
        if not isinstance(self.text, str):
            raise TypeError("conversation text must be a string")
        text = self.text.strip()
        if not text:
            raise ValueError("conversation text must not be empty")
        if self.interrupted and self.role is not ConversationRole.ASSISTANT:
            raise ValueError("only assistant turns can be interrupted")
        if not isinstance(self.turn_id, str) or not self.turn_id.strip():
            raise ValueError("turn_id must not be empty")
        if not isinstance(self.accepted_at, datetime):
            raise TypeError("accepted_at must be a datetime")
        if self.accepted_at.tzinfo is None or self.accepted_at.utcoffset() is None:
            raise ValueError("accepted_at must be timezone-aware")
        external_item_id = self.external_item_id
        if external_item_id is not None:
            if not isinstance(external_item_id, str):
                raise TypeError("external_item_id must be a string when provided")
            external_item_id = external_item_id.strip()
            if not external_item_id:
                raise ValueError("external_item_id must not be empty when provided")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "turn_id", self.turn_id.strip())
        object.__setattr__(self, "accepted_at", self.accepted_at.astimezone(UTC))
        object.__setattr__(self, "external_item_id", external_item_id)


class ConversationSession:
    """Own accepted turns and the product-level conversation lifecycle."""

    def __init__(self, *, session_id: str | None = None) -> None:
        if session_id is not None and not isinstance(session_id, str):
            raise TypeError("session_id must be a string when provided")
        resolved_session_id = _new_id() if session_id is None else session_id.strip()
        if not resolved_session_id:
            raise ValueError("session_id must not be empty")
        self._session_id = resolved_session_id
        self._status = ConversationStatus.CREATED
        self._turns: list[ConversationTurn] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def status(self) -> ConversationStatus:
        return self._status

    @property
    def turns(self) -> tuple[ConversationTurn, ...]:
        return tuple(self._turns)

    def start(self) -> None:
        if self._status is not ConversationStatus.CREATED:
            raise RuntimeError(f"cannot start a {self._status.value} conversation")
        self._status = ConversationStatus.ACTIVE

    def accept_turn(
        self,
        role: ConversationRole,
        text: str,
        *,
        interrupted: bool = False,
        external_item_id: str | None = None,
    ) -> ConversationTurn:
        if self._status is not ConversationStatus.ACTIVE:
            raise RuntimeError(
                f"cannot add a turn to a {self._status.value} conversation"
            )
        turn = ConversationTurn(
            role=role,
            text=text,
            interrupted=interrupted,
            external_item_id=external_item_id,
        )
        self._turns.append(turn)
        return turn

    def close(self) -> None:
        if self._status is ConversationStatus.ACTIVE:
            self._status = ConversationStatus.CLOSED
        elif self._status not in {ConversationStatus.CLOSED, ConversationStatus.FAILED}:
            raise RuntimeError(f"cannot close a {self._status.value} conversation")

    def fail(self) -> None:
        if self._status in {ConversationStatus.CREATED, ConversationStatus.ACTIVE}:
            self._status = ConversationStatus.FAILED
