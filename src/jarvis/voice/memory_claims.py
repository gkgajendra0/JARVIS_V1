"""A reply may only say memory changed when memory verifiably changed.

The confirmation path is structural: memory results are recorded per owner
turn (jarvis.memory.memory_receipts) by the operations themselves, and the
``memory_status`` tool lets Jarvis confirm only what is recorded.

This module is the backstop for a reply that claims a change anyway (Paid lab
8ea0fd4e, D11: "Understood, I've noted that the Goa plan is cancelled." while
nothing was stored). Spoken audio cannot be retracted, so, as for project
actions (jarvis.voice.project_claims), the finished reply is checked against
the record once that turn's learning has finished, and a false claim is
corrected at once from the recorded facts.

Claim detection is deliberately narrow: affirmative first-person sentences
saying Jarvis saved, noted, remembered, updated or forgot something. It only
ever triggers a check against the record; it never decides what is true. A
claim it does not recognise is not corrected (the documented limit).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import weakref
from time import monotonic
from uuid import uuid4

from jarvis.conversation import ConversationRole, ConversationStatus
from jarvis.memory.memory_receipts import FORGET_OPERATIONS, SAVE_OPERATIONS
from jarvis.voice.voice_output_safety import (
    note_generation_instructions,
    register_internal_text,
)

LOGGER = logging.getLogger(__name__)

_SENTENCES = re.compile(r"(?<=[.!?।])\s+")
_NEGATION = re.compile(
    r"\b(?:no|not|nothing|never|cannot|can['’]?t|didn['’]?t|wasn['’]?t|haven['’]?t|"
    r"hasn['’]?t|couldn['’]?t|won['’]?t|isn['’]?t|aren['’]?t|nahi|nahin|mat)\b"
    r"|n['’]t\b|नहीं|नही",
    re.IGNORECASE,
)
_FORGET_VERBS = r"(?:deleted|removed|forgotten|forgot|erased|cleared)"
_SAVE_VERBS = (
    r"(?:saved|noted|stored|remembered|recorded|updated|changed|corrected|added|"
    r"marked)"
)
# English: "I've saved ...", "I have noted ...", "I'll remember ...",
# "Noted.", "It's saved", "That has been updated".
_EN_FORGET = re.compile(
    rf"\bI(?:['’]ve|\s+have|['’]ll|\s+will)?\s+(?:now\s+|just\s+|also\s+)?{_FORGET_VERBS}\b"
    rf"|\b(?:it|that|this)(?:['’]s(?:\s+been)?|\s+is|\s+has\s+been|\s+was)\s+(?:now\s+)?{_FORGET_VERBS}\b",
    re.IGNORECASE,
)
_EN_SAVE = re.compile(
    rf"\bI(?:['’]ve|\s+have)?\s+(?:now\s+|just\s+|also\s+)?{_SAVE_VERBS}\b"
    r"|\bI(?:['’]ll|\s+will)\s+(?:remember|note|save|update)\b"
    r"|^\s*(?:okay|ok|alright|sure|done|got\s+it)?[,.!]?\s*noted\b"
    rf"|\b(?:it|that|this)(?:['’]s(?:\s+been)?|\s+is|\s+has\s+been|\s+was)\s+(?:now\s+)?{_SAVE_VERBS}\b"
    r"|\b(?:saved|noted|updated)\s+(?:it|that|this)\b",
    re.IGNORECASE,
)
# Hinglish / Hindi: "save kar liya", "note kar liya", "yaad rakh liya",
# "update kar diya", "hata diya", "सेव कर लिया".
_HI_FORGET = re.compile(
    r"\b(?:delete|remove|hata)\s+(?:kar\s+)?(?:diya|di|liya|li|dunga|dungi)\b"
    r"|\bbhool\s+(?:gaya|gayi|jaunga|jaungi)\b|हटा\s+(?:दिया|दी)|डिलीट\s+कर\s+(?:दिया|दी)",
    re.IGNORECASE,
)
_HI_SAVE = re.compile(
    r"\b(?:save|note|update|record|store)\s+(?:kar\s+)?(?:liya|li|diya|di|lunga|lungi)\b"
    r"|\byaad\s+(?:rakh|kar)\s+(?:liya|li|lunga|lungi|loonga|loongi)\b"
    r"|\byaad\s+rakhunga\b|\byaad\s+rakhungi\b"
    r"|(?:सेव|नोट|अपडेट)\s+कर\s+(?:लिया|ली|दिया|दी)|याद\s+रख\s+(?:लिया|ली|लूँगा|लूंगा|लूँगी|लूंगी)",
    re.IGNORECASE,
)


def memory_claims(text: str) -> set[str]:
    """Kinds of memory change a reply affirms: {"saved", "forgotten"}."""
    claims = set()
    for sentence in _SENTENCES.split(text or ""):
        if _NEGATION.search(sentence):
            continue
        if _EN_FORGET.search(sentence) or _HI_FORGET.search(sentence):
            claims.add("forgotten")
        elif _EN_SAVE.search(sentence) or _HI_SAVE.search(sentence):
            claims.add("saved")
    return claims


def unsupported_claims(text: str, operations) -> set[str]:
    """Claims the recorded operations of that owner turn do not support."""
    done = {o.operation for o in operations}
    supported = set()
    if done & SAVE_OPERATIONS:
        supported.add("saved")
    if done & FORGET_OPERATIONS:
        supported |= {"forgotten", "saved"}  # "updated" after a withdrawal
    return memory_claims(text) - supported


def correction_facts(operations, still_processing=False) -> str:
    if still_processing:
        return "your request is still being processed and nothing is saved yet"
    if not operations:
        return "nothing was saved, changed or forgotten for that request"
    parts = [f"{o.operation} {o.label}" if o.label else o.operation for o in operations]
    return "only this was recorded: " + "; ".join(parts)


NOTE_PREFIX = "[From Jarvis, not speech from the owner.] memory_check: "
CORRECTION_REQUEST = (
    "[From Jarvis, not speech from the owner.] Your previous reply said "
    "something was saved, changed or forgotten before memory confirmed it. The "
    "memory check above is what was actually recorded. Tell the owner now, in "
    "one short sentence, exactly what the check shows. Do not claim anything "
    "else was saved, and if nothing was saved offer to try again."
)
ACK = "Checked."
register_internal_text(CORRECTION_REQUEST)


# Live sessions whose replies are gated while they stream (agent.py
# guarded_transcription looks the gate up by the speaking session).
_STREAM_GATES = weakref.WeakKeyDictionary()


def register_stream_gate(session, gate) -> None:
    try:
        _STREAM_GATES[session] = gate
    except TypeError:  # an object that cannot be weakly referenced
        LOGGER.info("Memory claim stream gate not registered for this session")


def stream_gate_for(session):
    try:
        return _STREAM_GATES.get(session)
    except TypeError:
        return None


def _latest_owner_turn(conversation):
    for item in reversed(conversation.turns):
        if item.role is ConversationRole.USER:
            return item
    return None


def _owner_turn_before(conversation, turn):
    owner = None
    for item in conversation.turns:
        if item is turn or item.turn_id == turn.turn_id:
            return owner
        if item.role is ConversationRole.USER:
            owner = item
    return owner


async def inject_correction(session, owner_words, facts, *, register=None) -> bool:
    from livekit.agents.llm import ChatContext, ChatMessage

    agent = getattr(session, "current_agent", None)
    if agent is None or not callable(getattr(agent, "update_chat_ctx", None)):
        return False
    identity = uuid4().hex[:12]
    note = NOTE_PREFIX + json.dumps(
        {"owner_words": owner_words, "memory_check": facts}, ensure_ascii=False
    )
    items = [
        ChatMessage(id="jarvis:memory-check:" + identity, role="user", content=[note]),
        ChatMessage(
            id="jarvis:memory-check-ack:" + identity, role="assistant", content=[ACK]
        ),
        ChatMessage(
            id="jarvis:memory-check-request:" + identity,
            role="user",
            content=[CORRECTION_REQUEST],
        ),
    ]
    note_generation_instructions(CORRECTION_REQUEST)
    if register is not None:
        register(ChatContext(items=list(items)))
    context = agent.chat_ctx.copy()
    context.items.extend(items)
    await agent.update_chat_ctx(context)
    if getattr(session, "current_agent", None) is not agent:
        return False
    session.generate_reply(allow_interruptions=True)
    return True


class MemoryClaimCheck:
    """One live conversation's check of finished replies against the record.

    For each finished assistant reply that claims a memory change: wait
    (bounded) for that owner turn's learning, then compare with the recorded
    operations; a claim they do not support is corrected once, when Jarvis is
    idle, within the same conversation.
    """

    def __init__(
        self,
        receipts,
        conversation,
        deliver,
        *,
        idle,
        learning_wait: float = 12.0,
        idle_wait: float = 20.0,
        poll: float = 0.2,
        clock=monotonic,
        sleep=asyncio.sleep,
        diagnostics=None,
    ):
        self.receipts, self.conversation = receipts, conversation
        self.deliver, self.idle = deliver, idle
        self.learning_wait, self.idle_wait, self.poll = learning_wait, idle_wait, poll
        self._clock, self._sleep = clock, sleep
        self._diag = diagnostics
        self._tasks: set[asyncio.Task] = set()
        self._corrected: set[str] = set()
        self._closed = False
        self.corrections: list = []

    def stream_gate(self, text) -> bool:
        """While a reply streams: True (stop its speech now) when it claims a
        memory change the record of the current owner turn does not yet
        support, including while that turn's learning is still running. The
        owner then hears what the record shows once learning has finished."""
        if self._closed or not memory_claims(text):
            return False
        owner = _latest_owner_turn(self.conversation)
        if owner is None:
            return False
        session = self.conversation.session_id
        if not self.receipts.pending(session, owner.turn_id) and not (
            unsupported_claims(text, self.receipts.operations(session, owner.turn_id))
        ):
            return False
        self._schedule(owner, text, stopped=True)
        return True

    def observe(self, turn) -> None:
        """Accepted-turn observer: a finished reply that claims a change."""
        if self._closed or turn.role is not ConversationRole.ASSISTANT:
            return
        if not memory_claims(turn.text):
            return
        owner = _owner_turn_before(self.conversation, turn)
        if owner is not None:
            self._schedule(owner, turn.text, stopped=False)

    def _schedule(self, owner, text, *, stopped) -> None:
        if owner.turn_id in self._corrected:
            return
        self._corrected.add(owner.turn_id)
        task = asyncio.get_running_loop().create_task(self._check(owner, text, stopped))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _check(self, owner, text, stopped) -> None:
        session = self.conversation.session_id
        finished = await self.receipts.wait_learning(
            session, owner.turn_id, self.learning_wait
        )
        operations = self.receipts.operations(session, owner.turn_id)
        false = unsupported_claims(text, operations)
        if not false and stopped and finished and operations:
            # Stopped before memory had confirmed it; memory has now confirmed
            # it: the owner hears it from the record.
            facts = correction_facts(operations)
        elif not false:
            return
        else:
            facts = correction_facts(operations, still_processing=not finished)
        LOGGER.warning(
            "Memory claim check: reply claimed %s; recorded operations %s; correcting",
            sorted(false),
            sorted({o.operation for o in operations}),
        )
        if self._diag is not None:
            self._diag("false_memory_claim", claims=sorted(false))
        deadline = self._clock() + self.idle_wait
        while not self.idle():
            if self._closed or self._clock() >= deadline:
                LOGGER.warning("Memory claim correction not delivered: never idle")
                return
            await self._sleep(self.poll)
        if self._closed or self.conversation.status is not ConversationStatus.ACTIVE:
            return
        try:
            if await self.deliver(owner.text, facts):
                self.corrections.append((owner.turn_id, sorted(false), facts))
        except Exception as exc:  # noqa: BLE001 - the conversation continues
            LOGGER.warning(
                "Memory claim correction not delivered | error=%s", type(exc).__name__
            )

    async def close(self) -> None:
        tasks = tuple(self._tasks)
        if not self._closed:
            self._closed = True
            for task in tasks:
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
