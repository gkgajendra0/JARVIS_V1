"""Reviewed synthetic voice-smoke sources; never a general privacy classifier.

Only these test utterances may enter optional semantic extraction. Ordinary
Gemini Live audio remains the normal voice channel, outside this admission gate.
No durable memory writes or cross-wake replay are enabled by this module.
"""

from __future__ import annotations

from jarvis.conversation import ConversationRole, ConversationTurn
from jarvis.memory.types import Sensitivity

SMOKE_UTTERANCES = (
    "I am planning a Nepal trip",
    "I will travel in my Jimny",
    "The permits are already sorted",
    "Budget is unrestricted",
    "We still need to plan the route",
    "Correction, we will leave on 10 November",
    "The route is already planned",
    "Nepal trip ka budget fixed nahi hai",
)


def _normalized(text: str) -> str:
    return text.strip().rstrip(".?!").strip().casefold()


_APPROVED = frozenset(_normalized(text) for text in SMOKE_UTTERANCES)


def script_source_clearance(turn: ConversationTurn) -> Sensitivity | None:
    if (
        isinstance(turn, ConversationTurn)
        and turn.role is ConversationRole.USER
        and _normalized(turn.text) in _APPROVED
    ):
        return Sensitivity.STANDARD
    return None


def build_smoke_session_components(
    conversation, *, authority, grant, client, accepted_plan_epoch
):
    """Use a genuine canonical grant, independently admitting only the script.

    This hook observes transient reducer results. It never creates a checkpoint
    writer, issues a write child, releases stored context, or resumes a topic.
    """
    import logging
    from time import monotonic

    from jarvis.memory.semantic_model_producer import build_session_semantic_producer
    from jarvis.voice.semantic_context_bridge import SemanticSessionComponents

    logger = logging.getLogger(__name__)

    def binding():
        try:
            if authority.validate(grant).status != "active":
                return None
            return f"{grant.token}:{conversation.session_id}"
        except Exception:  # noqa: BLE001 - unavailable authority means no inference
            return None

    guarded = build_session_semantic_producer(
        conversation=conversation,
        client=client,
        authorization_binding=binding,
        source_clearance=script_source_clearance,
    )

    async def produce(turn):
        started = monotonic()
        proposals = await guarded(turn)
        logger.info(
            "Semantic script smoke inference | proposals=%s | elapsed_ms=%.1f",
            len(proposals),
            (monotonic() - started) * 1000,
        )
        return proposals

    async def observe_applied(turn, proposals, before, after, source_plan_epoch):
        logger.info(
            "Semantic script smoke applied | topic_present=%s | constraints=%s | "
            "pending_steps=%s | completed_steps=%s | checkpoint_write=False",
            after is not None,
            len(after.constraints) if after else 0,
            sum(not value.completed for _, value in after.steps) if after else 0,
            sum(value.completed for _, value in after.steps) if after else 0,
        )

    return SemanticSessionComponents(
        conversation=conversation,
        producer=produce,
        authorization_binding=binding,
        on_applied=observe_applied,
        accepted_plan_epoch=accepted_plan_epoch,
    )
