"""Owner-only admission and private reads under speaker enforcement.

Source review after the 27 Nov 2026 live voice acceptance found that with
JARVIS_SPEAKER_EVIDENCE_ENFORCEMENT on:
- project history kept the opening turn and unknown (unscored) turns;
- project history was preloaded into the model with no verified owner speech;
- search_history read the archive even after the turn was kept out as
  speaker_not_owner (the outcome only chose an excluded request id);
- personal-context reads and memory_status used no speaker evidence.

Now only positive owner evidence for the exact request turn acts for the
owner: saving to history, preloading it, archive search and forget, personal
reads and memory receipts. Unknown, non-owner, timed-out, missing, stale or
another turn's evidence never does. Ordinary conversation still gets an
answer; it just gets no private context. Mutations keep fresh Windows Hello.
"""

import asyncio
from types import SimpleNamespace

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import Wake, settle
from test_runtime import conversation as learning_conversation
from test_speaker_evidence_candidate import OWNER_FOLLOW_UP, OWNER_QUESTION

from jarvis.conversation import ConversationRole
from jarvis.memory.memory_receipts import SPEAKER_NOT_VERIFIED, MemoryReceipts
from jarvis.voice.speaker_turn_evidence import (
    SpeakerTurnEvidenceBook,
    UnavailableSpeakerEvidence,
)

lab = project_voice_tests.lab


def _book(**kwargs):
    return SpeakerTurnEvidenceBook(
        threshold=0.45,
        enforce=True,
        follow_up=False,
        **{"wait_seconds": 0.05, **kwargs},
    )


async def _wake(lab):
    voice = await lab.runtime()
    setup = Wake(voice)
    await setup.ask("create project called Nepal trip", "Created project Nepal trip.")
    await setup.ask("We will take the Jimny.", "Noted.")
    setup.close()
    wake = Wake(voice)
    book = _book()
    wake.turns.bind_speaker_evidence(book)
    return voice, wake, book


def _say(wake, book, text, score, *, resolve=True):
    wake.speech()
    turn = wake.conversation.accept_turn(ConversationRole.USER, text)
    book.observe_turn(turn)  # registered before project history
    wake.turns.observe_turn(turn)
    if resolve:
        book.resolve(turn.turn_id, score=score, reason="scored" if score else "short")
    return turn


@pytest.mark.asyncio
async def test_history_keeps_only_owner_scored_turns_opening_included(lab):
    voice, wake, book = await _wake(lab)
    _say(wake, book, "What should I pack?", None)  # opening, too short to score
    await settle(voice)
    _say(wake, book, "Book the Yak and Yeti.", 0.30)  # TV
    await settle(voice)
    _say(wake, book, "Is it cold there?", None, resolve=False)  # evidence never came
    await settle(voice)
    _say(wake, book, *OWNER_QUESTION)
    await settle(voice)
    texts = [text for _, text, *_ in lab.rows()]
    assert OWNER_QUESTION[0] in texts
    for kept_out in (
        "What should I pack?",
        "Book the Yak and Yeti.",
        "Is it cold there?",
    ):
        assert kept_out not in texts
    wake.close()


@pytest.mark.asyncio
async def test_archive_search_and_forget_need_the_owners_voice(lab):
    voice, wake, book = await _wake(lab)
    _say(wake, book, "Which car are we taking, the Jimny?", 0.30)
    denied = await wake.turns.search_history("Jimny")
    assert denied["reason"] == "speaker_not_verified" and "history" not in denied
    forgot = await wake.turns.forget_history("Jimny")
    assert forgot["reason"] == "speaker_not_verified"
    await settle(voice)
    _say(wake, book, "Which car did we pick, the Jimny?", OWNER_FOLLOW_UP[1])
    found = await wake.turns.search_history("Jimny")
    assert found.get("reason") != "speaker_not_verified"
    await settle(voice)
    wake.close()


@pytest.mark.asyncio
async def test_history_is_preloaded_only_after_verified_owner_speech(lab):
    voice, wake, book = await _wake(lab)
    waiting = asyncio.create_task(wake.turns._owner_spoke())
    _say(wake, book, "Jarvis?", None)  # wake word alone, unscored
    await asyncio.sleep(0.2)
    assert not waiting.done()  # nothing preloaded on unverified speech
    _say(wake, book, *OWNER_QUESTION)
    assert await asyncio.wait_for(waiting, 2) is True
    await settle(voice)
    # A wake with no owner speech ends without ever preloading.
    other = Wake(voice)
    other.turns.bind_speaker_evidence(_book())
    never = asyncio.create_task(other.turns._owner_spoke())
    await asyncio.sleep(0.05)
    other.close()
    assert await asyncio.wait_for(never, 2) is False
    wake.close()


@pytest.mark.asyncio
async def test_personal_reads_need_the_owners_voice_for_the_bound_turn():
    from jarvis.voice.personal_context import PersonalContextSession

    c = learning_conversation()
    book = _book()
    turn = c.accept_turn(ConversationRole.USER, "What vehicles do I have?")
    book.observe_turn(turn)
    binding = (c.session_id, turn.turn_id)
    session = SimpleNamespace(
        _speaker_evidence=book, _closed=False, _current=lambda activity=True: binding
    )
    verify = PersonalContextSession._speaker_verified
    assert await verify(session, binding) is False  # timed out: unknown
    book.resolve(turn.turn_id, score=0.30, reason="scored")
    assert await verify(session, binding) is False  # non-owner
    other = c.accept_turn(ConversationRole.USER, "And my phone?")
    book.observe_turn(other)
    book.resolve(other.turn_id, score=0.70, reason="scored")
    stale = SimpleNamespace(
        _speaker_evidence=book,
        _closed=False,
        _current=lambda activity=True: (c.session_id, "a-newer-turn"),
    )
    other_binding = (c.session_id, other.turn_id)
    assert await verify(stale, other_binding) is False  # no longer the request
    current = SimpleNamespace(
        _speaker_evidence=book,
        _closed=False,
        _current=lambda activity=True: other_binding,
    )
    assert await verify(current, other_binding) is True
    unavailable = SimpleNamespace(
        _speaker_evidence=UnavailableSpeakerEvidence(),
        _closed=False,
        _current=lambda activity=True: other_binding,
    )
    assert await verify(unavailable, other_binding) is False


@pytest.mark.asyncio
async def test_memory_status_names_no_fact_for_an_unverified_speaker(learning):
    from jarvis.voice.memory_tools import MemoryAgentTools

    c = learning_conversation()
    receipts = MemoryReceipts()
    first = c.accept_turn(ConversationRole.USER, "I bought a Suzuki Jimny.")
    receipts.learning_finished(
        c.session_id, first.turn_id, "committed", [("create", "Suzuki Jimny")]
    )
    book = _book()
    book.observe_turn(first)
    book.resolve(first.turn_id, score=0.70, reason="scored")
    question = c.accept_turn(ConversationRole.USER, "Did you save that?")
    book.observe_turn(question)
    book.resolve(question.turn_id, score=0.30, reason="scored")  # someone else
    tools = MemoryAgentTools(
        learning.service, c, receipts=receipts, speaker_evidence=book
    )
    status = await tools.verified_memory_status(wait=0)
    assert status["say"] == SPEAKER_NOT_VERIFIED and status["turns"] == []
    assert "Jimny" not in str(status)
    asked = c.accept_turn(ConversationRole.USER, "Did you save my Jimny?")
    book.observe_turn(asked)
    book.resolve(asked.turn_id, score=0.70, reason="scored")
    status = await tools.verified_memory_status(wait=0)
    assert status["say"] == "Saved: Suzuki Jimny."


@pytest.mark.asyncio
async def test_direct_memory_reads_need_the_owners_voice(learning):
    from jarvis.voice.memory_tools import MemoryAgentTools

    c = learning_conversation()
    turn = c.accept_turn(
        ConversationRole.USER, "What do you remember about my diet_preference?"
    )
    book = _book()
    book.observe_turn(turn)
    book.resolve(turn.turn_id, score=None, reason="short")
    tools = MemoryAgentTools(learning.service, c, speaker_evidence=book)
    with pytest.raises(PermissionError, match="owner's voice"):
        await tools.inspect(predicate="diet_preference")
