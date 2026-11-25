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

from jarvis.conversation import ConversationRole
from jarvis.voice.voice_output_safety import (
    note_generation_instructions,
    register_internal_text,
)

LOGGER = logging.getLogger(__name__)

NOTE_PREFIX = "[From Jarvis, not speech from the owner.] learning_note: "
FOLLOW_UP_REQUEST = (
    "[From Jarvis, not speech from the owner.] Ask the owner, in one short "
    "natural question, what they meant about the unclear detail in the "
    "learning note above. Do not ask about anything already known, and do not "
    "mention memory or saving."
)
ACK = "Noted."
register_internal_text(FOLLOW_UP_REQUEST)


def note_message(notes) -> str:
    return NOTE_PREFIX + json.dumps([n.model_view() for n in notes], ensure_ascii=False)


def _latest_owner_turn_id(conversation):
    for turn in reversed(conversation.turns):
        if turn.role is ConversationRole.USER:
            return turn.turn_id
    return None


async def inject_learning_note(session, notes, *, register=None) -> bool:
    """Add the note as a completed exchange and request the question."""
    from livekit.agents.llm import ChatContext, ChatMessage

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
    await agent.update_chat_ctx(context)
    session.generate_reply(allow_interruptions=True)
    return True


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
        return (
            not self._closed
            and note.session_id == self.conversation.session_id
            and _latest_owner_turn_id(self.conversation) == note.turn_id
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
        try:
            if await self.deliver(notes):
                self.delivered.append(notes)
        except Exception as exc:  # noqa: BLE001 - the conversation continues
            LOGGER.warning(
                "Learning follow-up not delivered | error=%s", type(exc).__name__
            )

    async def close(self) -> None:
        self._closed = True
        for task in tuple(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
