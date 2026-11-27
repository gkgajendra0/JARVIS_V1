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
from time import monotonic
from uuid import uuid4

from jarvis.conversation import ConversationRole, ConversationStatus
from jarvis.memory.memory_receipts import (
    FORGET_OPERATIONS,
    RECENT_TURNS,
    SAVE_OPERATIONS,
)
from jarvis.voice.voice_output_safety import (
    note_generation_instructions,
    register_internal_text,
)

LOGGER = logging.getLogger(__name__)

_SENTENCES = re.compile(r"(?<=[.!?।])\s+")
# A claim is judged per clause: "Noted, I won't forget that." claims the
# first clause and negates only the second.
_CLAUSES = re.compile(r"\s*(?:[,;:—–]|\bbut\b|\blekin\b)\s*", re.IGNORECASE)
_NEGATION = re.compile(
    r"\b(?:no|not|nothing|never|cannot|can['’]?t|didn['’]?t|wasn['’]?t|haven['’]?t|"
    r"hasn['’]?t|couldn['’]?t|won['’]?t|isn['’]?t|aren['’]?t|nahi|nahin|mat)\b"
    r"|n['’]t\b|नहीं|नही",
    re.IGNORECASE,
)
# Only words that are about memory itself, or a general verb with a memory
# object: "I've saved the document" or "I've added the task" is another
# tool's action, never checked against memory.
_MEMORY_OBJECT = r"(?:my|your|the)?\s*(?:memory|memories|records?|notes)"
_EN_FORGET = re.compile(
    r"\bI(?:['’]ve|\s+have|['’]ll|\s+will)?\s+(?:now\s+|just\s+|also\s+)?"
    r"(?:forgotten|forgot|forget)\b"
    r"|\b(?:it|that|this)(?:['’]s(?:\s+been)?|\s+is|\s+has\s+been|\s+was)\s+"
    r"(?:now\s+)?forgotten\b"
    rf"|\b(?:deleted|removed|erased|cleared)\b[^.!?]{{0,40}}\bfrom\s+{_MEMORY_OBJECT}\b",
    re.IGNORECASE,
)
_EN_SAVE = re.compile(
    r"\bI(?:['’]ve|\s+have)?\s+(?:now\s+|just\s+|also\s+)?(?:noted|remembered)\b"
    r"|\bI(?:['’]ll|\s+will)\s+(?:remember|note)\b"
    r"|^\s*(?:okay|ok|alright|sure|done|got\s+it|understood)?[,.!]?\s*noted\b"
    r"|\b(?:it|that|this)(?:['’]s(?:\s+been)?|\s+is|\s+has\s+been|\s+was)\s+"
    r"(?:now\s+)?noted\b"
    rf"|\b(?:saved|stored|recorded|added|updated|changed|corrected|kept)\b"
    rf"[^.!?]{{0,40}}\b(?:in|to)\s+{_MEMORY_OBJECT}\b"
    rf"|\bupdated\s+{_MEMORY_OBJECT}\b",
    re.IGNORECASE,
)
_HI_FORGET = re.compile(
    r"\bbhool\s+(?:gaya|gayi|jaunga|jaungi)\b"
    r"|\b(?:memory|yaadon)\s+se\s+(?:hata|delete|remove)\b"
    r"|मेमोरी\s+से\s+हटा",
    re.IGNORECASE,
)
_HI_SAVE = re.compile(
    r"\bnote\s+(?:kar\s+)?(?:liya|li|lunga|lungi)\b"
    r"|\byaad\s+(?:rakh|kar)\s+(?:liya|li|lunga|lungi|loonga|loongi)\b"
    r"|\byaad\s+rakhunga\b|\byaad\s+rakhungi\b"
    r"|\bmemory\s+(?:mein|me)\s+(?:save|add|update)\b"
    r"|नोट\s+कर\s+(?:लिया|ली)|याद\s+रख\s+(?:लिया|ली|लूँगा|लूंगा|लूँगी|लूंगी)",
    re.IGNORECASE,
)
_WORD = re.compile(r"\w+", re.UNICODE)
# A short bare acknowledgement names no item ("Noted.", "I'll remember that.").
_BARE_MAX_WORDS = 4


def _claim_clauses(text):
    """(kind, clause) for each affirmed memory claim."""
    for sentence in _SENTENCES.split(text or ""):
        for clause in _CLAUSES.split(sentence):
            if not clause.strip() or _NEGATION.search(clause):
                continue
            if _EN_FORGET.search(clause) or _HI_FORGET.search(clause):
                yield "forgotten", clause
            elif _EN_SAVE.search(clause) or _HI_SAVE.search(clause):
                yield "saved", clause


def memory_claims(text: str) -> set[str]:
    """Kinds of memory change a reply affirms: {"saved", "forgotten"}."""
    return {kind for kind, _ in _claim_clauses(text)}


def _names(clause, label) -> bool:
    """The clause names the recorded item (a distinctive word of its label)."""
    from jarvis.memory.learning_catalog_page import PLAN_HEAD_NOUNS, name_words

    wanted = {w for w in name_words(label) - PLAN_HEAD_NOUNS if len(w) >= 3}
    return bool(wanted) and bool(wanted & name_words(clause))


def unsupported_claims(text: str, operations) -> set[str]:
    """Claims the recorded operations do not support, item by item: a claim
    naming an item needs an operation of its kind on that item; a bare
    acknowledgement ("Noted.") needs an operation of its kind."""
    kinds = {"saved": SAVE_OPERATIONS, "forgotten": FORGET_OPERATIONS}
    false = set()
    for kind, clause in _claim_clauses(text):
        ops = [o for o in operations if o.operation in kinds[kind]]
        bare = len(_WORD.findall(clause)) <= _BARE_MAX_WORDS
        if bare:
            ok = bool(ops)
        else:
            ok = any(o.label and _names(clause, o.label) for o in ops)
        if not ok:
            false.add(kind)
    return false


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


# The gate rides on the live session object itself (agent.py
# guarded_transcription reads it from the speaking session) and is removed
# when the conversation closes, so nothing outlives the session.
_GATE_ATTRIBUTE = "_jarvis_memory_claim_gate"


def register_stream_gate(session, gate) -> None:
    try:
        setattr(session, _GATE_ATTRIBUTE, gate)
    except (AttributeError, TypeError):
        LOGGER.info("Memory claim stream gate not registered for this session")


def unregister_stream_gate(session, gate=None) -> None:
    current = getattr(session, _GATE_ATTRIBUTE, None)
    if current is not None and (gate is None or current == gate):
        try:
            delattr(session, _GATE_ATTRIBUTE)
        except (AttributeError, TypeError):
            pass


def stream_gate_for(session):
    return getattr(session, _GATE_ATTRIBUTE, None)


def _recent_owner_turns(conversation, before=None):
    """The owner's most recent turns (newest first), up to ``before`` when
    given: a reply may answer the latest turn or speak about an earlier one,
    and its owner turn may be accepted after the reply starts."""
    owner = []
    for item in conversation.turns:
        if before is not None and (item is before or item.turn_id == before.turn_id):
            break
        if item.role is ConversationRole.USER:
            owner.append(item)
    return list(reversed(owner))[:RECENT_TURNS]


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
        memory change the record of the owner's recent turns does not
        support, including while their learning is still running. The owner
        then hears what the record shows once learning has finished. Each
        owner turn is stopped and answered once; later speech is not cut."""
        if self._closed or not memory_claims(text):
            return False
        turns = _recent_owner_turns(self.conversation)
        if not turns or turns[0].turn_id in self._corrected:
            return False
        session = self.conversation.session_id
        ids = tuple(t.turn_id for t in turns)
        # Unsupported now, whether learning is still running or finished.
        if not unsupported_claims(text, self.receipts.operations(session, ids)):
            return False
        self._schedule(turns, text, stopped=True)
        return True

    def observe(self, turn) -> None:
        """Accepted-turn observer: a finished reply that claims a change."""
        if self._closed or turn.role is not ConversationRole.ASSISTANT:
            return
        if not memory_claims(turn.text):
            return
        turns = _recent_owner_turns(self.conversation, before=turn)
        if turns and turns[0].turn_id not in self._corrected:
            self._schedule(turns, turn.text, stopped=False)

    def _schedule(self, turns, text, *, stopped) -> None:
        self._corrected.add(turns[0].turn_id)
        task = asyncio.get_running_loop().create_task(self._check(turns, text, stopped))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _check(self, turns, text, stopped) -> None:
        owner = turns[0]
        session = self.conversation.session_id
        ids = tuple(t.turn_id for t in turns)
        finished = await self.receipts.wait_learning(session, ids, self.learning_wait)
        operations = self.receipts.operations(session, ids)
        false = unsupported_claims(text, operations)
        if not false and stopped and finished:
            # Stopped before memory had confirmed it; memory has now confirmed
            # it: the owner hears it from the record.
            facts = correction_facts(operations)
        elif not false:
            return
        else:
            facts = correction_facts(
                [o for o in operations if o.turn_id == owner.turn_id],
                still_processing=not finished,
            )
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
