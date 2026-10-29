"""Explicitly gated semantic observer attachment for native voice sessions.

This adapter does not discover or mint owner authority. A caller must provide
a source-cleared proposal producer and a rotating trusted authorization binding.
Nothing changes in production unless both are deliberately injected.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.conversation import ConversationSession
from jarvis.memory.conversation_semantics import SemanticContextEngine
from jarvis.memory.semantic_pipeline import (
    AcceptedPlanEpoch,
    AppliedStateCallback,
    AuthorizationBinding,
    ProposalProducer,
    SemanticTurnPipeline,
)


@dataclass(frozen=True, slots=True)
class SemanticSessionComponents:
    """Trusted dependencies constructed afresh for one canonical conversation."""

    conversation: ConversationSession
    producer: ProposalProducer
    authorization_binding: AuthorizationBinding
    on_applied: AppliedStateCallback | None = None
    accepted_plan_epoch: AcceptedPlanEpoch | None = None

    def __post_init__(self):
        if not isinstance(self.conversation, ConversationSession):
            raise TypeError("canonical conversation required")
        if not callable(self.producer) or not callable(self.authorization_binding):
            raise TypeError("semantic producer and owner binding must be callable")
        if self.on_applied is not None and not callable(self.on_applied):
            raise TypeError("semantic checkpoint callback must be callable")
        if self.accepted_plan_epoch is not None and not callable(
            self.accepted_plan_epoch
        ):
            raise TypeError("accepted plan epoch must be callable")
        if self.on_applied is not None and self.accepted_plan_epoch is None:
            raise TypeError("checkpoint persistence requires accepted plan epoch")


def resolve_session_components(conversation: ConversationSession, *, factory):
    """Reject ambiguous factory output before any observer or worker is attached."""
    if not isinstance(conversation, ConversationSession) or not callable(factory):
        raise TypeError("canonical conversation and semantic session factory required")
    components = factory(conversation)
    if not isinstance(components, SemanticSessionComponents):
        raise TypeError(
            "semantic session factory must return SemanticSessionComponents"
        )
    if components.conversation is not conversation:
        raise ValueError("semantic components belong to another conversation")
    return components


def resolve_session_commit_callback(
    conversation: ConversationSession,
    *,
    direct: AppliedStateCallback | None,
    factory: Callable[[ConversationSession], AppliedStateCallback] | None,
) -> AppliedStateCallback | None:
    """Bind checkpoint mutations to the current canonical voice session."""
    if not isinstance(conversation, ConversationSession):
        raise TypeError("canonical conversation required")
    if direct is not None and factory is not None:
        raise ValueError("semantic callback and factory cannot both be active")
    callback = factory(conversation) if factory is not None else direct
    if factory is not None and not callable(callback):
        raise TypeError("semantic commit factory returned no callback")
    if callback is not None and not callable(callback):
        raise TypeError("semantic commit callback must be callable")
    return callback


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
        on_applied: AppliedStateCallback | None = None,
        accepted_plan_epoch: AcceptedPlanEpoch | None = None,
    ) -> None:
        if not callable(add_turn_observer) or not callable(add_close_observer):
            raise TypeError("canonical bridge observers required")
        self.state = SemanticContextEngine()
        self.pipeline = SemanticTurnPipeline(
            conversation=conversation,
            state=self.state,
            producer=producer,
            authorization_binding=authorization_binding,
            on_applied=on_applied,
            accepted_plan_epoch=accepted_plan_epoch,
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
        # Revoke and cancel now: do not defer cancellation until the new
        # cleanup task gets scheduled behind a blocked producer.
        self.pipeline.request_close()
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
    on_applied: AppliedStateCallback | None = None,
    accepted_plan_epoch: AcceptedPlanEpoch | None = None,
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
        on_applied=on_applied,
        accepted_plan_epoch=accepted_plan_epoch,
    )
