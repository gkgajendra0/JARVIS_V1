"""Provider-independent conversation truth for JARVIS."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
        object.__setattr__(self, "text", text)


class ConversationSession:
    """Own accepted turns and the product-level conversation lifecycle."""

    def __init__(self) -> None:
        self._status = ConversationStatus.CREATED
        self._turns: list[ConversationTurn] = []

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
    ) -> ConversationTurn:
        if self._status is not ConversationStatus.ACTIVE:
            raise RuntimeError(
                f"cannot add a turn to a {self._status.value} conversation"
            )
        turn = ConversationTurn(role=role, text=text, interrupted=interrupted)
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
