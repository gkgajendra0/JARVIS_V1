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
from collections import OrderedDict
from time import monotonic
from uuid import uuid4

from jarvis.conversation import ConversationRole, ConversationStatus
from jarvis.memory.learning_catalog_page import PLAN_HEAD_NOUNS, name_words
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
_SENTENCE_END = re.compile(r"[.!?।]['\"’”)]*\s*$")
# A claim is found per clause ("Noted, I won't forget that." claims the first
# clause and negates only the second) and judged on its whole sentence.
_CLAUSES = re.compile(r"\s*(?:[,;:—–]|\bbut\b|\blekin\b)\s*", re.IGNORECASE)
# Negation counts only before or inside the claim itself: "I've noted that
# you don't drink coffee" is still a claim.
_NEGATION = re.compile(
    r"\b(?:no|not|nothing|never|cannot|can['’]?t|didn['’]?t|wasn['’]?t|haven['’]?t|"
    r"hasn['’]?t|couldn['’]?t|won['’]?t|isn['’]?t|aren['’]?t|nahi|nahin|mat)\b"
    r"|n['’]t\b|नहीं|नही",
    re.IGNORECASE,
)
# Only words about memory itself, or a general verb with memory as its
# object: "I've saved the document", "added the task", "stored it in my notes
# app" are other tools' actions, never checked against memory.
_MEMORY_OBJECT = r"(?:my|your|the)?\s*(?:memory|memories)"
# A verb followed by an infinitive or a question word is ordinary speech, not
# a memory change: "I have forgotten to mention", "I'll remember to call".
_NOT_A_CHANGE = r"(?!\s+(?:to|about|what|where|when|how|whether|if|which)\b)"
_EN_FORGET = re.compile(
    rf"\bI(?:['’]ve|\s+have)\s+(?:now\s+|just\s+|also\s+)?forgotten\b{_NOT_A_CHANGE}"
    r"|\b(?:it|that|this)(?:['’]s(?:\s+been)?|\s+is|\s+has\s+been|\s+was)\s+"
    r"(?:now\s+)?forgotten\b"
    rf"|\b(?:deleted|removed|erased|cleared)\b[^.!?]{{0,40}}\bfrom\s+{_MEMORY_OBJECT}\b",
    re.IGNORECASE,
)
_EN_SAVE = re.compile(
    rf"\bI(?:['’]ve|\s+have)?\s+(?:now\s+|just\s+|also\s+)?(?:noted|remembered)\b"
    rf"{_NOT_A_CHANGE}"
    rf"|\bI(?:['’]ll|\s+will)\s+(?:remember|note)\b{_NOT_A_CHANGE}"
    r"|^\s*(?:okay|ok|alright|sure|done|got\s+it|understood)?[,.!]?\s*noted\b"
    r"|\b(?:it|that|this)(?:['’]s(?:\s+been)?|\s+is|\s+has\s+been|\s+was)\s+"
    r"(?:now\s+)?noted\b"
    rf"|\b(?:saved|stored|recorded|added|updated|changed|corrected|kept)\b"
    rf"[^.!?]{{0,40}}\b(?:in|to)\s+{_MEMORY_OBJECT}\b"
    rf"|\bupdated\s+{_MEMORY_OBJECT}\b",
    re.IGNORECASE,
)
_HI_FORGET = re.compile(
    r"\b(?:memory|yaadon)\s+se\s+(?:hata|delete|remove)\b|मेमोरी\s+से\s+हटा",
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
_PATTERNS = (
    ("forgotten", _EN_FORGET),
    ("forgotten", _HI_FORGET),
    ("saved", _EN_SAVE),
    ("saved", _HI_SAVE),
)
_KINDS = {"saved": SAVE_OPERATIONS, "forgotten": FORGET_OPERATIONS}


def _affirmed(clause):
    """The kind a clause affirms, or None."""
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(clause):
            if not _NEGATION.search(clause[: match.end()]):
                return kind
    return None


def _claims(text):
    """(kind, sentence, complete) for each affirmed claim."""
    sentences = [s for s in _SENTENCES.split(text or "") if s.strip()]
    for index, sentence in enumerate(sentences):
        complete = index < len(sentences) - 1 or bool(_SENTENCE_END.search(sentence))
        kinds = []
        for clause in _CLAUSES.split(sentence):
            kind = clause.strip() and _affirmed(clause)
            if kind and kind not in kinds:
                kinds.append(kind)
        for kind in kinds:
            yield kind, sentence, complete


def memory_claims(text: str) -> set[str]:
    """Kinds of memory change a reply affirms: {"saved", "forgotten"}."""
    return {kind for kind, _, _ in _claims(text)}


def _names(sentence, label) -> bool:
    """The sentence names the recorded item (a distinctive word of its label)."""
    wanted = {w for w in name_words(label) - PLAN_HEAD_NOUNS if len(w) >= 3}
    return bool(wanted) and bool(wanted & name_words(sentence))


def unsupported_claims(text: str, operations, newest=None) -> set[str]:
    """Claims the recorded operations do not support.

    ``newest``: the newest owner turn's id (None: every operation counts as
    the newest turn's). A claim is backed by an operation of its kind on the
    newest owner turn, or by one on an earlier recent turn that the sentence
    names ("Did you save that?" "Yes, I've noted your Jimny."). A sentence
    still being spoken may not have named its item yet: until it ends, any
    recorded operation of its kind is enough.
    """
    false = set()
    for kind, sentence, complete in _claims(text):
        ops = [o for o in operations if o.operation in _KINDS[kind]]
        if any(newest is None or o.turn_id == newest for o in ops):
            continue
        if not complete and ops:
            continue
        if not any(o.label and _names(sentence, o.label) for o in ops):
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
        self._corrected: OrderedDict[str, None] = OrderedDict()
        self._closed = False
        self.corrections: list = []

    def stream_gate(self, text) -> bool:
        """While a reply streams: True (stop its speech now) when it claims a
        memory change the record does not support, including while the
        owner turn's learning is still running. The owner then hears what
        the record shows once learning has finished. Each owner turn is
        stopped and answered once; later speech is not cut."""
        if self._closed or not memory_claims(text):
            return False
        turns = _recent_owner_turns(self.conversation)
        if not turns or turns[0].turn_id in self._corrected:
            return False
        session = self.conversation.session_id
        operations = self.receipts.operations(session, tuple(t.turn_id for t in turns))
        if not unsupported_claims(text, operations, newest=turns[0].turn_id):
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
        self._corrected[turns[0].turn_id] = None
        while len(self._corrected) > 64:
            self._corrected.popitem(last=False)
        task = asyncio.get_running_loop().create_task(self._check(turns, text, stopped))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _check(self, turns, text, stopped) -> None:
        owner = turns[0]
        session = self.conversation.session_id
        ids = tuple(t.turn_id for t in turns)
        finished = await self.receipts.wait_learning(session, ids, self.learning_wait)
        operations = self.receipts.operations(session, ids)
        latest = [o for o in operations if o.turn_id == owner.turn_id]
        false = unsupported_claims(text, operations, newest=owner.turn_id)
        if not false and not stopped:
            return
        if not false:
            # Stopped before memory had confirmed it, and memory now backs
            # it: the owner hears it from the record (this turn's when any).
            facts = correction_facts(latest or operations)
        else:
            # A stopped reply is always answered, even if learning has not
            # finished: speech was cut, so the owner hears where things stand.
            facts = correction_facts(latest, still_processing=not finished)
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
