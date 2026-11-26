"""Ask about a "meaning unclear" learning note in the live voice session.

Learning runs beside the reply, so its outcome arrives after Jarvis has begun
answering the turn. When it reports that the owner's words about a detail
could not be understood (jarvis.memory.learning_clarification), Jarvis asks
one brief question once its reply has finished, only if the owner has not
spoken since, and only once per detail. If the owner has moved on, Jarvis
does not interrupt with it.

The note reaches Gemini as a completed, labelled exchange plus an owner-side
request from Jarvis (the pattern project_voice uses for repair), never inside
generate_reply instructions, which LiveKit sends as model-role text that can
be echoed. The note holds the owner's own words and the details already
known; it says nothing about storage.
"""

from __future__ import annotations

import asyncio
import json
import logging
from time import monotonic
from uuid import uuid4

from jarvis.conversation import ConversationRole, ConversationStatus
from jarvis.voice.voice_output_safety import (
    note_generation_instructions,
    register_internal_text,
)

LOGGER = logging.getLogger(__name__)

NOTE_PREFIX = "[From Jarvis, not speech from the owner.] learning_note: "
FOLLOW_UP_REQUEST = (
    "[From Jarvis, not speech from the owner.] Ask the owner one short "
    "natural question for each open detail in the learning note above: what they "
    "meant about the unclear detail, or whether they are still choosing between "
    "the listed choices. Keep each plan and detail separate so an answer to one "
    "does not confirm another. Do not ask about anything already known, and do not "
    "mention memory or saving."
)
ACK = "Noted."
register_internal_text(FOLLOW_UP_REQUEST)


def note_message(notes) -> str:
    return NOTE_PREFIX + json.dumps([n.model_view() for n in notes], ensure_ascii=False)


def _latest_owner_turn(conversation):
    for turn in reversed(conversation.turns):
        if turn.role is ConversationRole.USER:
            return turn
    return None


async def inject_learning_note(
    session, notes, *, register=None, is_current=None
) -> bool:
    """Add the note as a completed exchange and request the question.

    If delivery becomes obsolete, clean the agent's local context. Gemini
    Live cannot recall items already sent to the provider.
    """
    from livekit.agents.llm import ChatContext, ChatMessage

    if is_current is not None and not is_current():
        return False
    agent = getattr(session, "current_agent", None)
    if agent is None or not callable(getattr(agent, "update_chat_ctx", None)):
        return False
    identity = uuid4().hex[:12]
    items = [
        ChatMessage(
            id="jarvis:learning-note:" + identity,
            role="user",
            content=[note_message(notes)],
        ),
        ChatMessage(
            id="jarvis:learning-note-ack:" + identity,
            role="assistant",
            content=[ACK],
        ),
        ChatMessage(
            id="jarvis:learning-note-request:" + identity,
            role="user",
            content=[FOLLOW_UP_REQUEST],
        ),
    ]
    note_generation_instructions(FOLLOW_UP_REQUEST)
    if register is not None:
        register(ChatContext(items=list(items)))
    context = agent.chat_ctx.copy()
    context.items.extend(items)
    delivered = False
    try:
        await agent.update_chat_ctx(context)
        if (is_current is not None and not is_current()) or getattr(
            session, "current_agent", None
        ) is not agent:
            return False
        session.generate_reply(allow_interruptions=True)
        delivered = True
        return True
    finally:
        if not delivered:
            # The provider update may have yielded after the agent accepted a
            # newer owner turn. Remove only our items from its latest context.
            try:
                current_context = agent.chat_ctx.copy()
                injected_ids = {item.id for item in items}
                kept = [
                    item
                    for item in current_context.items
                    if item.id not in injected_ids
                ]
                if len(kept) != len(current_context.items):
                    current_context.items = kept
                    await agent.update_chat_ctx(current_context)
            except Exception as exc:  # noqa: BLE001 - preserve delivery failure/cancellation
                LOGGER.warning(
                    "Learning follow-up cleanup failed | error=%s", type(exc).__name__
                )


class LearningFollowUp:
    """One live conversation's follow-up questions from learning notes."""

    def __init__(
        self,
        board,
        conversation,
        deliver,
        *,
        idle,
        max_wait: float = 10.0,
        poll: float = 0.2,
        clock=monotonic,
        sleep=asyncio.sleep,
    ):
        self.board, self.conversation = board, conversation
        self.deliver, self.idle = deliver, idle
        self.max_wait, self.poll = max_wait, poll
        self._clock, self._sleep = clock, sleep
        self._tasks: set[asyncio.Task] = set()
        self._closed = False
        self.delivered: list = []

    def _current(self, note) -> bool:
        owner_turn = _latest_owner_turn(self.conversation)
        return (
            not self._closed
            and self.conversation.status is ConversationStatus.ACTIVE
            and note.session_id == self.conversation.session_id
            and owner_turn is not None
            and owner_turn.turn_id == note.turn_id
            and (owner_turn.user_activity_epoch or 0)
            == self.conversation.user_activity_epoch
        )

    def offer(self, note) -> None:
        """Learning observer. A note for an older turn (the owner has spoken
        since) or another conversation is not asked."""
        if not self._current(note):
            return
        task = asyncio.get_running_loop().create_task(self._ask(note))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _ask(self, note) -> None:
        deadline = self._clock() + self.max_wait
        while not self.idle():
            if self._clock() >= deadline or not self._current(note):
                return
            await self._sleep(self.poll)
        if not self._current(note):
            return
        notes = self.board.take(note.session_id, note.turn_id)
        if not notes:
            return  # already asked, or settled by a later statement

        def is_current():
            return self.idle() and self._current(note)

        try:
            if await self.deliver(notes, is_current=is_current):
                self.delivered.append(notes)
        except Exception as exc:  # noqa: BLE001 - the conversation continues
            LOGGER.warning(
                "Learning follow-up not delivered | error=%s", type(exc).__name__
            )

    async def close(self) -> None:
        tasks = tuple(self._tasks)
        if not self._closed:
            self._closed = True
            for task in tasks:
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
