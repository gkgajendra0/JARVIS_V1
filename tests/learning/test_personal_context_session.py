"""One Hello per read-only personal-fact session (30 min absolute, 10 min idle)."""

from types import SimpleNamespace

import pytest

from jarvis.authority.personal_context_session import (
    ABSOLUTE_LIMIT_SECONDS,
    IDLE_LIMIT_SECONDS,
    PersonalContextSessionAuthority,
    PersonalContextSessionBinding,
)
from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.retrieval import SemanticRetrievalService
from jarvis.voice.project_memory_lab import build_session_personal_factory

VEHICLE = [{"scope_key": "owned_item.vehicle"}]


async def _setup(learning, authority_parts):
    await learning.service.admit_learning(learning.plan, learning.new_permit())
    capability = CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=authority_parts.broker,
    )
    memory = SimpleNamespace(retrieval=SemanticRetrievalService(learning.reader))
    factory, session = build_session_personal_factory(memory, capability)
    return factory, session


def _question(text):
    conversation = ConversationSession()
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, text)
    return conversation


async def _ask(factory, text):
    personal = factory(_question(text))
    try:
        return await personal.query_for_question(VEHICLE)
    finally:
        personal.close()


@pytest.mark.asyncio
async def test_one_hello_serves_several_personal_questions(learning, authority_parts):
    factory, session = await _setup(learning, authority_parts)
    before = len(authority_parts.hello.calls)
    try:
        first = await _ask(factory, "What vehicle can I take to Nepal?")
        second = await _ask(factory, "Which car should I service first?")
        assert first["status"] == second["status"] == "selected"
        assert "City" in str(first["facts"]) and "City" in str(second["facts"])
        assert len(authority_parts.hello.calls) == before + 1
        assert session.opened == 1
    finally:
        session.close()


@pytest.mark.asyncio
async def test_questions_without_personal_reads_never_open_hello(
    learning, authority_parts
):
    factory, session = await _setup(learning, authority_parts)
    before = len(authority_parts.hello.calls)
    personal = factory(_question("What did we decide about permits?"))
    personal.close()
    assert len(authority_parts.hello.calls) == before
    assert session.opened == 0


@pytest.mark.asyncio
async def test_idle_limit_requires_a_new_hello(learning, authority_parts, clock):
    factory, session = await _setup(learning, authority_parts)
    try:
        await _ask(factory, "What vehicle do I have?")
        clock.advance(IDLE_LIMIT_SECONDS - 5)
        assert (await _ask(factory, "Is it due a service?"))["status"] == "selected"
        assert session.opened == 1
        clock.advance(IDLE_LIMIT_SECONDS + 1)
        assert (await _ask(factory, "And the tyres?"))["status"] == "selected"
        assert session.opened == 2
    finally:
        session.close()


@pytest.mark.asyncio
async def test_absolute_limit_ends_even_an_active_session(
    learning, authority_parts, clock
):
    factory, session = await _setup(learning, authority_parts)
    try:
        await _ask(factory, "What vehicle do I have?")
        for _ in range(ABSOLUTE_LIMIT_SECONDS // 300 - 1):
            clock.advance(300)
            await _ask(factory, "Still the same vehicle?")
        assert session.opened == 1
        clock.advance(301)
        await _ask(factory, "Still the same vehicle?")
        assert session.opened == 2
    finally:
        session.close()


@pytest.mark.asyncio
async def test_windows_lock_ends_the_session(learning, authority_parts):
    factory, session = await _setup(learning, authority_parts)
    try:
        await _ask(factory, "What vehicle do I have?")
        authority_parts.windows.lock_unlock()
        await _ask(factory, "What vehicle do I have?")
        assert session.opened == 2
    finally:
        session.close()


@pytest.mark.asyncio
async def test_declined_hello_releases_no_facts(learning, authority_parts):
    factory, session = await _setup(learning, authority_parts)
    authority_parts.hello.denied = True
    result = await _ask(factory, "What vehicle do I have?")
    assert result == {
        "status": "denied",
        "facts": [],
        "reason": "personal_session_not_approved",
    }
    assert session.opened == 0


def test_session_grant_cannot_write(authority_parts):
    issuer = PersonalContextSessionAuthority(authority_parts.broker)
    grant = issuer.open("runtime", "gemini")
    try:
        for operation in ("admit", "suppress"):
            with pytest.raises(PermissionError, match="read-only"):
                issuer.issue_child(
                    grant,
                    PersonalContextSessionBinding(
                        operation, "receipt", "0" * 64, ("owned_item",)
                    ),
                )
        with pytest.raises(PermissionError):
            issuer.authorize_reenable_category("owned_item")
    finally:
        issuer.revoke(grant)


def test_session_policy_identity_is_distinct_from_learning(authority_parts):
    from jarvis.authority.personal_learning import PersonalLearningAuthority

    session = PersonalContextSessionAuthority(authority_parts.broker)
    learning = PersonalLearningAuthority(authority_parts.broker)
    assert session.CAPABILITY == "memory:personal_context_session"
    assert session.POLICY_DIGEST != learning.POLICY_DIGEST
    assert "Read only" in session.SESSION_SUMMARY
