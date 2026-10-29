"""Explicitly gated semantic observer attachment for native voice sessions.

This adapter does not discover or mint owner authority. A caller must provide
a source-cleared proposal producer and a rotating trusted authorization binding.
Nothing changes in production unless both are deliberately injected.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from jarvis.conversation import ConversationSession
from jarvis.memory.conversation_semantics import SemanticContextEngine
from jarvis.memory.semantic_pipeline import (
    AuthorizationBinding,
    ProposalProducer,
    SemanticTurnPipeline,
)


class SemanticVoiceAttachment:
    """One canonical voice session owns one transient semantic state epoch."""

    def __init__(
        self,
        *,
        conversation: ConversationSession,
        add_turn_observer: Callable[[Callable], None],
        add_close_observer: Callable[[Callable], None],
        producer: ProposalProducer,
        authorization_binding: AuthorizationBinding,
    ) -> None:
        if not callable(add_turn_observer) or not callable(add_close_observer):
            raise TypeError("canonical bridge observers required")
        self.state = SemanticContextEngine()
        self.pipeline = SemanticTurnPipeline(
            conversation=conversation,
            state=self.state,
            producer=producer,
            authorization_binding=authorization_binding,
        )
        self._closed = False
        self._closing: asyncio.Task[None] | None = None
        self.pipeline.start()
        add_turn_observer(self.pipeline.submit)
        add_close_observer(self.close)

    def close(self) -> None:
        """Immediately revoke state; schedule async worker shutdown."""
        if self._closed:
            return
        self._closed = True
        self.pipeline.invalidate()
        self._closing = asyncio.create_task(
            self.pipeline.close(), name="jarvis-semantic-voice-close"
        )

    async def wait_closed(self) -> None:
        if self._closing is not None:
            await self._closing
        else:
            await self.pipeline.close()


def attach_semantic_voice_context(
    bridge,
    *,
    producer: ProposalProducer,
    authorization_binding: AuthorizationBinding,
) -> SemanticVoiceAttachment:
    """Attach only to a bridge exposing the canonical accepted-turn contract.

    Calling this helper is an explicit opt-in. It does not enable model context
    replay, checkpoint writes, read authority, or a cloud-model dispatch itself.
    """
    if not callable(producer) or not callable(authorization_binding):
        raise TypeError("authorized semantic producer and binding are mandatory")
    if not isinstance(getattr(bridge, "conversation", None), ConversationSession):
        raise TypeError("canonical conversation bridge required")
    return SemanticVoiceAttachment(
        conversation=bridge.conversation,
        add_turn_observer=bridge.add_accepted_turn_observer,
        add_close_observer=bridge.add_close_observer,
        producer=producer,
        authorization_binding=authorization_binding,
    )
