"""Jarvis never describes a memory change in its own words.

Owner decision 2026-11-27 (Memory V1 closure): automatic learning is silent,
and the only way Jarvis says something was saved, updated or forgotten is a
receipt sentence composed in code from the verified record
(jarvis.memory.memory_receipts.compose_say), handed to it by memory_status or
an explicit memory tool and spoken word for word.

This module enforces that on the spoken reply. Any first-person memory claim
(true or not) and any receipt-form sentence ("Saved: ...") that is not, word
for word, a sentence Jarvis was given is unverified: while streaming its
speech is stopped, and the owner then hears the receipt for their recent
turns, composed from the record. A finished reply is checked the same way.
Paid lab 8ea0fd4e, D11 ("Understood, I've noted that the Goa plan is
cancelled." while nothing was stored) is the recorded case.

Detection only decides what to check, never what is true. The documented
limit: a claim worded outside the narrow first-person patterns is not
detected; the instructions forbid any such wording, and a miss is an
improvement candidate, not a reason for more phrase rules.
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
from jarvis.memory.memory_receipts import RECEIPT_VERBS, RECENT_TURNS
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
# A sentence in the receipt form ("Saved: ...", "Forgot: ...") is a memory
# statement too: it must be one Jarvis was given, word for word.
_RECEIPT_FORM = re.compile(
    r"^\s*(?:" + "|".join(re.escape(v) for v in RECEIPT_VERBS) + r")\b\s*[:.]",
    re.IGNORECASE,
)
_NORMAL = re.compile(r"[^\w]+", re.UNICODE)


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


def _normal(text) -> str:
    return " ".join(_NORMAL.sub(" ", text or "").lower().split())


def unverified_statements(text: str, issued) -> list[str]:
    """Memory statements in a reply that are not receipt sentences Jarvis was
    given (``issued``), word for word.

    Owner decision 2026-11-27: automatic learning is silent, and Jarvis
    never describes a memory change in its own words; it only speaks the
    sentence code composed from the verified record (memory_status, or an
    explicit tool's result). So any first-person memory claim, true or not,
    and any receipt-form sentence that differs from what was issued, is
    unverified. A sentence still being spoken only has to be the start of
    an issued one.
    """
    given = [
        _normal(sentence)
        for say in issued
        for sentence in _SENTENCES.split(say or "")
        if sentence.strip()
    ]
    found = []
    sentences = [s for s in _SENTENCES.split(text or "") if s.strip()]
    for index, sentence in enumerate(sentences):
        complete = index < len(sentences) - 1 or bool(_SENTENCE_END.search(sentence))
        claim = any(
            clause.strip() and _affirmed(clause) for clause in _CLAUSES.split(sentence)
        )
        if not claim and not _RECEIPT_FORM.search(sentence):
            continue
        spoken = _normal(sentence)
        if complete:
            ok = spoken in given
        else:
            ok = any(g.startswith(spoken) for g in given)
        if not ok:
            found.append(sentence.strip())
    return found


NOTE_PREFIX = "[From Jarvis, not speech from the owner.] memory_check: "
CORRECTION_REQUEST = (
    "[From Jarvis, not speech from the owner.] Your previous reply described a "
    "memory change in your own words, which is never allowed. Say exactly the "
    "say sentence in the memory check above, word for word, and nothing else."
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


async def inject_correction(session, owner_words, say, *, register=None) -> bool:
    from livekit.agents.llm import ChatContext, ChatMessage

    agent = getattr(session, "current_agent", None)
    if agent is None or not callable(getattr(agent, "update_chat_ctx", None)):
        return False
    identity = uuid4().hex[:12]
    note = NOTE_PREFIX + json.dumps(
        {"owner_words": owner_words, "say": say}, ensure_ascii=False
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
        """While a reply streams: True (stop its speech now) when it states a
        memory change other than a receipt sentence Jarvis was given. The
        owner then hears the receipt for their recent turns. Each owner turn
        is stopped and answered once; later speech is not cut."""
        if self._closed:
            return False
        session = self.conversation.session_id
        if not unverified_statements(text, self.receipts.issued(session)):
            return False
        turns = _recent_owner_turns(self.conversation)
        if not turns or turns[0].turn_id in self._corrected:
            return False
        self._schedule(turns, text, stopped=True)
        return True

    def observe(self, turn) -> None:
        """Accepted-turn observer: a finished reply with an unverified memory
        statement."""
        if self._closed or turn.role is not ConversationRole.ASSISTANT:
            return
        session = self.conversation.session_id
        if not unverified_statements(turn.text, self.receipts.issued(session)):
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
        await self.receipts.wait_learning(session, ids, self.learning_wait)
        statements = unverified_statements(text, self.receipts.issued(session))
        if not statements and not stopped:
            return
        # The owner hears the receipt, composed from the record.
        say = self.receipts.issue(session, self.receipts.say(session, ids))
        LOGGER.warning(
            "Memory claim check: unverified memory statement (%s sentences, "
            "stopped=%s); speaking the receipt",
            len(statements),
            stopped,
        )
        if self._diag is not None:
            self._diag("unverified_memory_statement", stopped=stopped)
        deadline = self._clock() + self.idle_wait
        while not self.idle():
            if self._closed or self._clock() >= deadline:
                LOGGER.warning("Memory claim correction not delivered: never idle")
                return
            await self._sleep(self.poll)
        if self._closed or self.conversation.status is not ConversationStatus.ACTIVE:
            return
        try:
            if await self.deliver(owner.text, say):
                self.corrections.append((owner.turn_id, statements, say))
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
