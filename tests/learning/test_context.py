import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.retrieval import SemanticRetrievalService
from jarvis.voice.personal_context import PersonalContextSession


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "What vehicles do I own?",
        "Meri gaadi kaunsi hai?",
        "मेरे पास कौन सी गाड़ी है?",
        "Why did I buy it?",
        "Explain a Python loop",
    ],
)
async def test_grant_reads_across_fresh_wakes_without_new_hello(
    learning, authority_parts, question
):
    await learning.service.admit_learning(learning.plan, learning.new_permit())
    for _ in range(2):
        c = ConversationSession()
        c.start()
        c.accept_turn(ConversationRole.USER, question)
        session = PersonalContextSession(
            conversation=c,
            retrieval=SemanticRetrievalService(learning.reader),
            authority=None,
            retire=lambda: None,
            learning_authority=learning.authority,
            learning_grant=learning.grant,
        )
        try:
            catalog = await session.catalog()
            assert catalog["status"] == "available"
            packet = await session.read(catalog["catalog_id"], [0])
            assert packet["status"] == "selected" and "City" in str(packet)
            assert "motives" in packet["scope"]
            assert await session.allow_audio()
        finally:
            session.close()
    assert len(authority_parts.hello.calls) == 1


@pytest.mark.asyncio
async def test_grant_revocation_blocks_already_released_audio(
    learning, authority_parts
):
    await learning.service.admit_learning(learning.plan, learning.new_permit())
    c = ConversationSession()
    c.start()
    c.accept_turn(ConversationRole.USER, "Meri car?")
    session = PersonalContextSession(
        conversation=c,
        retrieval=SemanticRetrievalService(learning.reader),
        authority=None,
        retire=lambda: None,
        learning_authority=learning.authority,
        learning_grant=learning.grant,
    )
    try:
        catalog = await session.catalog()
        await session.read(catalog["catalog_id"], [0])
        authority_parts.windows.lock_unlock()
        assert not await session.allow_audio()
    finally:
        session.close()


@pytest.mark.asyncio
async def test_ended_ownership_payload_is_not_current_ownership(learning):
    from dataclasses import replace

    m = learning.plan.mutations[0]
    draft = replace(
        m.draft,
        value={**m.draft.value, "state": "not_owned"},
        normalized_text="owned_item.vehicle: City; state=not_owned",
    )
    plan = replace(learning.plan, mutations=(replace(m, draft=draft),))
    await learning.service.admit_learning(plan, learning.new_permit(plan))
    c = ConversationSession()
    c.start()
    c.accept_turn(ConversationRole.USER, "Meri City abhi hai?")
    session = PersonalContextSession(
        conversation=c,
        retrieval=SemanticRetrievalService(learning.reader),
        authority=None,
        retire=lambda: None,
        learning_authority=learning.authority,
        learning_grant=learning.grant,
    )
    try:
        catalog = await session.catalog()
        packet = await session.read(catalog["catalog_id"], [0])
        assert "not_owned" in packet["facts"][0]["text"]
    finally:
        session.close()


def test_learning_prompt_does_not_advertise_per_fact_confirmation():
    from jarvis.voice.agent import PERSONAL_LEARNING_CONTEXT_INSTRUCTIONS

    assert (
        "Durable learning remains explicit only"
        not in PERSONAL_LEARNING_CONTEXT_INSTRUCTIONS
    )
    assert "Ordinary direct everyday facts" in PERSONAL_LEARNING_CONTEXT_INSTRUCTIONS
    assert "why it was bought" in PERSONAL_LEARNING_CONTEXT_INSTRUCTIONS
