"""Source-bound bridge from transient semantic state to canonical SQLCipher.

This callback does NOT generate owner grants or admit model claims. A trusted
caller must supply source-bound, revocable write/forget validators and an
independent privacy/suppression admission function. The canonical SQLCipher
store performs its own transaction-time revalidation.
"""

from __future__ import annotations

from collections.abc import Callable

from jarvis.conversation import ConversationSession, ConversationTurn

from .conversation_checkpoint import EncryptedTopicCheckpointStore
from .conversation_semantics import (
    SemanticAction,
    SemanticProposal,
    TopicSnapshot,
)

PermitValidator = Callable[[ConversationTurn], bool]
SnapshotAdmission = Callable[[TopicSnapshot, ConversationTurn], bool]


class SemanticCheckpointWriter:
    """Optional async persistence hook for an authorized semantic pipeline."""

    def __init__(
        self,
        *,
        conversation: ConversationSession,
        store: EncryptedTopicCheckpointStore,
        authorize_write: PermitValidator,
        authorize_forget: PermitValidator,
        admit_snapshot: SnapshotAdmission,
    ) -> None:
        if not isinstance(conversation, ConversationSession):
            raise TypeError("canonical conversation required")
        if not isinstance(store, EncryptedTopicCheckpointStore):
            raise TypeError("canonical encrypted checkpoint store required")
        if not all(
            callable(callback)
            for callback in (authorize_write, authorize_forget, admit_snapshot)
        ):
            raise TypeError("source-bound write, forget and privacy validators required")
        self._conversation = conversation
        self._store = store
        self._write = authorize_write
        self._forget = authorize_forget
        self._admit = admit_snapshot

    async def __call__(
        self,
        turn: ConversationTurn,
        proposals: tuple[SemanticProposal, ...],
        before: TopicSnapshot | None,
        after: TopicSnapshot | None,
    ) -> None:
        if any(p.action is SemanticAction.FORGET_TOPIC for p in proposals):
            if len(proposals) != 1:
                raise PermissionError("forget cannot accompany another mutation")
            if before is None or after is not None:
                raise PermissionError("forget must target one existing active topic")
            await self._store.forget(
                self._conversation,
                turn,
                title=before.title,
                authorize_forget=lambda: self._forget(turn),
            )
            return
        if after is None:
            return
        await self._store.save(
            self._conversation,
            turn,
            after,
            authorize_write=lambda: self._write(turn),
            admit_snapshot=lambda snapshot, source: self._admit(snapshot, source),
        )
