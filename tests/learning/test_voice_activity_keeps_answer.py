"""Voice activity without a transcript must not discard a pending personal answer.

speaker-eval-2 (2026-11-19, run 20261119T175702Z-3d24b4, video playing):

Q1 "What should I pack?": transcript 17:59:34.51, thinking 37.74, local VAD
    "speaking" 38.78 with no transcript -> the session was retired
    ``user_activity`` at once and the answer never played.
Q2 "Which one is better for Spiti trip?": transcript 47.82, thinking 48.03,
    personal facts selected 48.15, a 90 ms VAD burst at 48.29 with no
    transcript -> retired ``user_activity``; the response completed at 48.38
    with no audio.

These replay those event orders through the production delegated-read path
(the real session authority, Windows lock state, revocation and storage):
activity alone keeps the answer; a genuine new accepted turn, a lock, a
revocation, an expiry, a correction, a forget or a disabled category still
end it.
"""

from types import SimpleNamespace

import pytest
from test_personal_context_session import VEHICLE, _question, _setup

from jarvis.authority.personal_context_session import ABSOLUTE_LIMIT_SECONDS
from jarvis.conversation import ConversationRole

Q1 = "What should I pack?"
Q2 = "Which one is better for Spiti trip?"


@pytest.fixture(autouse=True)
def proposal_clock(monkeypatch, clock):
    from jarvis.authority import proposal

    monkeypatch.setattr(proposal, "time", SimpleNamespace(monotonic=clock))


def burst(conversation, inner):
    """What the runtime does on local VAD "speaking": a new activity epoch,
    then the personal-context activity check. No transcript follows."""
    conversation.begin_user_activity()
    inner.observe_activity()


def new_turn(conversation, inner, text):
    """A genuine accepted USER transcript, as the bridge delivers it."""
    turn = conversation.accept_turn(ConversationRole.USER, text)
    inner.observe_turn(turn)
    return turn


async def opened(learning, authority_parts, text):
    factory, session = await _setup(learning, authority_parts)
    conversation = _question(text)
    personal = factory(conversation)
    return personal, session, conversation


def plays_to_completion(inner):
    inner.playback_finished()
    inner.response_finished()
    return inner.retirement_reason


@pytest.mark.asyncio
async def test_q2_burst_after_release_keeps_the_answer(learning, authority_parts):
    personal, session, conversation = await opened(learning, authority_parts, Q2)
    try:
        assert (await personal.query_for_question(VEHICLE))["status"] == "selected"
        inner = personal._inner
        cleared = []
        inner.bind_audio_clear(lambda: cleared.append(True))
        burst(conversation, inner)  # 48.29, 90 ms, no transcript
        assert not inner._closed and inner.retirement_reason is None
        assert await inner._validate()
        assert await inner.allow_audio()
        assert cleared == []
        assert plays_to_completion(inner) == "response_completed"
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
async def test_q1_burst_while_thinking_keeps_the_question(learning, authority_parts):
    personal, session, conversation = await opened(learning, authority_parts, Q1)
    try:
        # Thinking started; voice activity (38.78, no transcript) arrives
        # before the lookup, then again before the answer plays.
        conversation.begin_user_activity()
        result = await personal.query_for_question(VEHICLE)
        assert result["status"] == "selected"
        inner = personal._inner
        burst(conversation, inner)
        assert await inner.allow_audio()
        assert plays_to_completion(inner) == "response_completed"
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
async def test_repeated_bursts_never_retire_the_same_question(
    learning, authority_parts
):
    personal, session, conversation = await opened(learning, authority_parts, Q2)
    try:
        await personal.query_for_question(VEHICLE)
        inner = personal._inner
        for _ in range(5):
            burst(conversation, inner)
            assert await inner.allow_audio()
        assert not inner._closed
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("audio_started", [False, True])
async def test_a_genuine_new_turn_revokes_the_previous_answer(
    learning, authority_parts, audio_started
):
    personal, session, conversation = await opened(learning, authority_parts, Q2)
    try:
        await personal.query_for_question(VEHICLE)
        inner = personal._inner
        cleared = []
        inner.bind_audio_clear(lambda: cleared.append(True))
        if audio_started:
            assert await inner.allow_audio()
        burst(conversation, inner)  # the new question starts: activity first
        assert not inner._closed
        new_turn(conversation, inner, "Actually, what about Ladakh?")
        assert inner._closed and inner.retirement_reason == "user_activity"
        assert cleared == [True]
        assert not await inner.allow_audio()
        assert not await inner._validate()
        # The previous answer's lookup can't be reused for the new question.
        assert (await personal.query_for_question(VEHICLE))["status"] != "selected"
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
async def test_the_new_question_gets_its_own_lookup(learning, authority_parts):
    """A fresh request is bound to the new turn, never to the old release."""
    factory, session = await _setup(learning, authority_parts)
    conversation = _question(Q2)
    first = factory(conversation)
    try:
        await first.query_for_question(VEHICLE)
        old = first._inner
        burst(conversation, old)
        new = new_turn(conversation, old, "Should I take the Thar to Ladakh?")
        second = factory(conversation)
        try:
            assert (await second.query_for_question(VEHICLE))["status"] == "selected"
            assert second._inner._binding[1] == new.turn_id != old._binding[1]
        finally:
            second.close()
    finally:
        first.close()
        session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "windows_lock",
        "session_revoked",
        "session_expired",
        "corrected",
        "forgotten",
        "category_disabled",
    ],
)
async def test_protections_still_end_the_answer_after_a_burst(
    learning, authority_parts, clock, change
):
    personal, session, conversation = await opened(learning, authority_parts, Q2)
    statements = {
        "corrected": "UPDATE semantic_assertion SET normalized_text='Nexon' "
        "WHERE state='active'",
        "forgotten": "UPDATE semantic_assertion SET state='retracted' "
        "WHERE state='active'",
        "category_disabled": "INSERT INTO personal_learning_suppression "
        "VALUES ('owned_item.vehicle',1,1,'fictional')",
    }
    try:
        await personal.query_for_question(VEHICLE)
        inner = personal._inner
        burst(conversation, inner)
        assert not inner._closed
        if change == "windows_lock":
            authority_parts.windows.lock_unlock()
        elif change == "session_revoked":
            session.close("owner_revoked")
        elif change == "session_expired":
            clock.advance(ABSOLUTE_LIMIT_SECONDS)
        else:

            def update(connection):
                with connection:
                    connection.execute(statements[change])

            await learning.writer.run(update)
        assert not await inner.allow_audio()
        assert inner._closed
    finally:
        personal.close()
        session.close()
