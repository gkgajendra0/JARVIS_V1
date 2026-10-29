"""Authorized projection of grounded task state into bounded model context.

This is a release boundary, not a grant issuer. A trusted capability service
must validate the current canonical question, topic, owner and response scope.
Every produced packet must be revalidated at actual provider/audio release.
"""

from __future__ import annotations

from collections.abc import Callable

from jarvis.conversation import (
    ConversationRole,
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
)

from .context import ContextAssembler, ContextPacket, Utf8ByteBudgetEstimator
from .conversation_checkpoint import _explicit_topic
from .conversation_semantics import TopicSnapshot
from .live_context import LiveContext, LiveContextPriority
from .types import Sensitivity

ContextReleaseValidator = Callable[
    [ConversationSession, ConversationTurn, str], bool
]


class ContextReleaseDenied(PermissionError):
    pass


class SemanticContextProjector:
    """Fail closed on stale, ambiguous, or unauthorized context release."""

    def __init__(
        self,
        *,
        validate_release: ContextReleaseValidator,
        max_bytes: int = 4096,
    ) -> None:
        if not callable(validate_release):
            raise TypeError("trusted release validator is required")
        if type(max_bytes) is not int or not 256 <= max_bytes <= 16_384:
            raise ValueError("context budget must be in [256, 16384]")
        self._validate_release = validate_release
        self._assembler = ContextAssembler(
            estimator=Utf8ByteBudgetEstimator(),
            max_units=max_bytes,
        )

    def _allowed(
        self,
        conversation: ConversationSession,
        turn: ConversationTurn,
        title: str,
    ) -> None:
        if (
            not isinstance(conversation, ConversationSession)
            or conversation.status is not ConversationStatus.ACTIVE
            or not isinstance(turn, ConversationTurn)
            or turn.role is not ConversationRole.USER
            or not conversation.turns
            or conversation.turns[-1] is not turn
        ):
            raise ContextReleaseDenied("latest canonical owner request required")
        try:
            permitted = self._validate_release(conversation, turn, title)
        except Exception as exc:
            raise ContextReleaseDenied("context authorization unavailable") from exc
        if permitted is not True:
            raise ContextReleaseDenied("context release is not authorized")

    def assemble_named(
        self,
        conversation: ConversationSession,
        turn: ConversationTurn,
        snapshot: TopicSnapshot,
    ) -> ContextPacket:
        """For a fresh wake/restart, the current question must name the topic."""
        if not isinstance(snapshot, TopicSnapshot):
            raise TypeError("snapshot must be TopicSnapshot")
        self._allowed(conversation, turn, snapshot.title)
        if not _explicit_topic(turn.text, snapshot.title):
            raise ContextReleaseDenied("new request does not name the topic")
        live = LiveContext(max_recent_turns=1)
        live.observe_turn(turn)
        live.set_active_topic(
            snapshot.title,
            source_turn_id=turn.turn_id,
            sensitivity=Sensitivity.PRIVATE,
        )
        if snapshot.goal is not None:
            live.set_active_goal(
                snapshot.goal.value,
                source_turn_id=snapshot.goal.source_turn_id,
                sensitivity=self._release_sensitivity(snapshot.goal.sensitivity),
            )
        for key, field in snapshot.constraints:
            live.set_entity(
                f"constraint:{key}",
                field.value,
                source_turn_id=field.source_turn_id,
                priority=LiveContextPriority.HIGH,
                sensitivity=self._release_sensitivity(field.sensitivity),
            )
        for key, step in snapshot.steps:
            if not step.completed:
                live.set_unresolved_work(
                    key,
                    step.value,
                    source_turn_id=step.source_turn_id,
                    sensitivity=self._release_sensitivity(step.sensitivity),
                )
        packet = self._assembler.assemble(live.snapshot(), current_turn=turn)
        self._allowed(conversation, turn, snapshot.title)
        return packet

    @staticmethod
    def _release_sensitivity(sensitivity: Sensitivity) -> Sensitivity:
        if not isinstance(sensitivity, Sensitivity):
            raise ContextReleaseDenied("invalid context sensitivity")
        return sensitivity
