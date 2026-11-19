"""Option A: a read whose 30 s delegated lease lapsed while the answer was
still being written is renewed under the same session approval, for the same
turn, only when the same facts are still current. Every other reason a read
stops being valid still ends it."""

from types import SimpleNamespace

import pytest
from test_personal_context_session import VEHICLE, _question, _setup

from jarvis.authority.personal_context_session import ABSOLUTE_LIMIT_SECONDS
from jarvis.conversation import ConversationRole
from jarvis.voice import personal_context


@pytest.fixture(autouse=True)
def proposal_clock(monkeypatch, clock):
    from jarvis.authority import proposal

    monkeypatch.setattr(proposal, "time", SimpleNamespace(monotonic=clock))


async def released(learning, authority_parts, text="Should I drive myself?"):
    factory, session = await _setup(learning, authority_parts)
    conversation = _question(text)
    personal = factory(conversation)
    result = await personal.query_for_question(VEHICLE)
    assert result["status"] == "selected"
    return personal, personal._inner, session, conversation


@pytest.mark.asyncio
async def test_lapsed_lease_alone_is_renewed_without_hello(
    learning, authority_parts, clock
):
    personal, inner, session, _ = await released(learning, authority_parts)
    hellos = len(authority_parts.hello.calls)
    try:
        old = inner._permit
        clock.advance(31)
        assert not await inner._validate_strict()
        assert await inner._validate()
        assert inner._permit is not old and inner._read_renewals == 1
        assert await inner._facts_current()
        assert len(authority_parts.hello.calls) == hellos
        assert session.opened == 1
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["windows_lock", "session_revoked", "session_expired", "new_owner_turn", "cap"],
)
async def test_any_other_change_still_ends_the_read(
    learning, authority_parts, clock, change
):
    personal, inner, session, conversation = await released(learning, authority_parts)
    try:
        clock.advance(31)
        if change == "windows_lock":
            authority_parts.windows.lock_unlock()
        elif change == "session_revoked":
            session.close("owner_revoked")
        elif change == "session_expired":
            clock.advance(ABSOLUTE_LIMIT_SECONDS)
        elif change == "new_owner_turn":
            conversation.accept_turn(ConversationRole.USER, "Actually, never mind.")
        else:
            inner._read_renewals = personal_context.MAX_READ_RENEWALS
        assert not await inner._validate()
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
async def test_a_live_lease_is_never_replaced(learning, authority_parts, clock):
    personal, inner, session, _ = await released(learning, authority_parts)
    try:
        old = inner._permit
        clock.advance(10)
        assert await inner._validate()
        assert inner._permit is old and inner._read_renewals == 0
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
async def test_a_closed_session_is_never_renewed(learning, authority_parts, clock):
    personal, inner, session, _ = await released(learning, authority_parts)
    try:
        inner.close()
        clock.advance(31)
        assert not await inner._validate()
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["corrected", "forgotten", "category_disabled"])
async def test_changed_facts_are_never_renewed(
    learning, authority_parts, clock, change
):
    """Stand-ins at the storage layer for a correction, a forget and a disabled
    learning category; the canonical paths each change these same rows."""
    personal, inner, session, _ = await released(learning, authority_parts)
    statements = {
        "corrected": "UPDATE semantic_assertion SET normalized_text='Nexon' "
        "WHERE state='active'",
        "forgotten": "UPDATE semantic_assertion SET state='retracted' "
        "WHERE state='active'",
        "category_disabled": "INSERT INTO personal_learning_suppression "
        "VALUES ('owned_item.vehicle',1,1,'fictional')",
    }

    def update(connection):
        with connection:
            connection.execute(statements[change])

    try:
        clock.advance(31)
        await learning.writer.run(update)
        assert not await inner._validate()
    finally:
        personal.close()
        session.close()
