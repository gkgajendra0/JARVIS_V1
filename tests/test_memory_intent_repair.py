"""Natural language proposals still need canonical targets and exact owner consent."""

import pytest
import test_personal_context_runtime as fixtures

from jarvis.conversation import ConversationRole
from jarvis.memory.explicit import ExplicitMemoryAuthorizationError
from jarvis.memory.service import MemoryNotFoundError, MemoryServiceError
from jarvis.voice.memory_tools import MemoryAgentTools

personal = fixtures.personal
source = fixtures.source


@pytest.mark.asyncio
async def test_new_turn_during_direct_resolution_cannot_rebind_old_proposal(personal):
    import asyncio

    session, service, conversation, authority, _ = personal
    conversation.accept_turn(
        ConversationRole.USER, "Update my diet preference to vegan."
    )
    entered, resume = asyncio.Event(), asyncio.Event()
    original = service.inspect_exact

    async def paused(**kwargs):
        result = await original(**kwargs)
        entered.set()
        await resume.wait()
        return result

    service.inspect_exact = paused
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    task = asyncio.create_task(
        tools.correct(predicate="diet preference", value="vegan")
    )
    await entered.wait()
    conversation.accept_turn(ConversationRole.USER, "Tell me about rain instead.")
    resume.set()
    with pytest.raises(ExplicitMemoryAuthorizationError):
        await task
    assert authority.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,value",
    [
        ("Update my diet preference to vegan.", "vegan"),
        ("Ab main vegan hoon, meri diet preference badal do.", "vegan"),
        ("अब मेरी खाने की पसंद वीगन कर दो।", "वीगन"),
    ],
)
async def test_natural_correction_uses_canonical_catalog_and_concrete_consent(
    personal, question, value
):
    session, service, conversation, authority, _ = personal
    await service.forget_exact(
        predicate="diet preference", source=source("remove-singular")
    )
    saved = await service.remember_text(
        predicate="diet preferences", value="vegetarian", source=source("plural")
    )
    conversation.accept_turn(ConversationRole.USER, question)
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    catalog = await session.catalog()
    assert catalog["request"]["text"] == question
    result = await tools.correct(
        predicate="diet preference",
        value=value,
        catalog_id=catalog["catalog_id"],
        facet_index=catalog["facets"].index("diet_preferences"),
    )
    assert result["ok"] and result["predicate"] == "diet_preferences"
    record = (await service.inspect_exact(predicate="diet preferences")).record
    assert record.value == value and record.supersedes_id == saved.record.assertion_id
    assert [call["operation"] for call in authority.calls] == ["read", "correct"]
    proposal = authority.calls[-1]["mutation"]
    assert proposal == {
        "predicate": "diet_preferences",
        "assertion_id": saved.record.assertion_id,
        "value": value,
        "sensitivity": "standard",
    }
    with pytest.raises(MemoryNotFoundError):
        await service.inspect_exact(predicate="diet preference")


@pytest.mark.asyncio
async def test_wrong_key_requests_resolution_and_cannot_fall_back_to_remember(personal):
    session, service, conversation, authority, _ = personal
    conversation.accept_turn(
        ConversationRole.USER,
        "Update my diet preferences to vegan; remember the change.",
    )
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    result = await tools.correct(predicate="diet preferences", value="vegan")
    assert result["status"] == "resolution_required"
    assert authority.calls == []
    with pytest.raises(ExplicitMemoryAuthorizationError):
        await tools.remember(predicate="diet preferences", value="vegan")
    assert (
        await service.inspect_exact(predicate="diet preference")
    ).record.value == "vegetarian"


@pytest.mark.asyncio
async def test_semantic_forget_targets_catalog_record_not_user_wording(personal):
    session, service, conversation, authority, _ = personal
    conversation.accept_turn(ConversationRole.USER, "मेरी खाने की पसंद हटा दो।")
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    catalog = await session.catalog()
    result = await tools.forget(
        predicate="खाने की पसंद", catalog_id=catalog["catalog_id"], facet_index=0
    )
    assert result["ok"] and authority.calls[-1]["operation"] == "forget"
    with pytest.raises(MemoryNotFoundError):
        await service.inspect_exact(predicate="diet preference")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Do not update my diet preference to vegan.",
        "Meri diet preference vegan mat karna.",
        "मेरी खाने की पसंद वीगन मत करना।",
    ],
)
async def test_negated_request_cannot_become_a_change_proposal(personal, question):
    session, service, conversation, authority, _ = personal
    conversation.accept_turn(ConversationRole.USER, question)
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    with pytest.raises(ExplicitMemoryAuthorizationError):
        await tools.correct(predicate="diet preference", value="vegan")
    assert authority.calls == []
    assert (
        await service.inspect_exact(predicate="diet preference")
    ).record.value == "vegetarian"


@pytest.mark.asyncio
async def test_canonical_selection_does_not_override_concrete_owner_denial(personal):
    session, service, conversation, authority, _ = personal
    conversation.accept_turn(ConversationRole.USER, "Meri preference vegan kar do.")
    catalog = await session.catalog()
    authority.denied = True
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    with pytest.raises(PermissionError):
        await tools.correct(
            predicate="preference",
            value="vegan",
            catalog_id=catalog["catalog_id"],
            facet_index=0,
        )
    assert (
        await service.inspect_exact(predicate="diet preference")
    ).record.value == "vegetarian"


@pytest.mark.asyncio
async def test_version_changed_during_approval_cannot_overwrite_new_fact(personal):
    session, service, conversation, _authority, _ = personal
    conversation.accept_turn(
        ConversationRole.USER, "Update my diet preference to vegan."
    )
    catalog = await session.catalog()
    original = session.authorize_mutation

    async def approve_then_other_change(*args, **kwargs):
        await original(*args, **kwargs)
        await service.correct_text(
            predicate="diet preference",
            value="another preference",
            source=source("concurrent"),
        )

    session.authorize_mutation = approve_then_other_change
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    with pytest.raises(MemoryServiceError):
        await tools.correct(
            predicate="diet preference",
            value="vegan",
            catalog_id=catalog["catalog_id"],
            facet_index=0,
        )
    assert (
        await service.inspect_exact(predicate="diet preference")
    ).record.value == "another preference"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "catalog_id,index", [("invented", 0), (None, True), (None, -1), (None, 999)]
)
async def test_invalid_selection_never_grants_mutation(personal, catalog_id, index):
    session, service, conversation, authority, _ = personal
    conversation.accept_turn(
        ConversationRole.USER, "Update my diet preference to vegan."
    )
    catalog = await session.catalog()
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    result = await tools.correct(
        predicate="diet preference",
        value="vegan",
        catalog_id=catalog_id or catalog["catalog_id"],
        facet_index=index,
    )
    assert not result["ok"] and len(authority.calls) == 1
    assert (
        await service.inspect_exact(predicate="diet preference")
    ).record.value == "vegetarian"


@pytest.mark.asyncio
async def test_real_function_tools_expose_canonical_resolution_and_new_instructions(
    personal,
):
    from types import SimpleNamespace

    from jarvis.voice.agent import JarvisVoiceAgent
    from jarvis.voice.personal_context import PersonalContextAgentTools

    session, service, conversation, _, _ = personal
    conversation.accept_turn(
        ConversationRole.USER, "Meri diet preference vegan kar do."
    )
    tools = {
        tool.id: tool
        for tool in [
            *MemoryAgentTools(service, conversation, personal_context=session).tools,
            *PersonalContextAgentTools(session).tools,
        ]
    }
    agent = JarvisVoiceAgent(tools=list(tools.values()))
    assert "Do not call the catalog before an explicit memory" not in agent.instructions
    assert "facet_index" in agent.instructions
    catalog = await tools["personal_context_catalog"]()
    result = await tools["correct_memory"](
        SimpleNamespace(disallow_interruptions=lambda: None),
        predicate="diet preference",
        value="vegan",
        catalog_id=catalog["catalog_id"],
        facet_index=0,
    )
    assert result["ok"]


@pytest.mark.asyncio
async def test_private_diagnostics_log_status_without_request_or_values(
    personal, caplog
):
    import logging

    session, service, conversation, _, _ = personal
    conversation.accept_turn(
        ConversationRole.USER, "Update my diet preference to PRIVATE-NEW-VALUE."
    )
    tools = MemoryAgentTools(service, conversation, personal_context=session)
    with caplog.at_level(logging.INFO):
        catalog = await session.catalog()
        await tools.correct(
            predicate="diet preference",
            value="PRIVATE-NEW-VALUE",
            catalog_id=catalog["catalog_id"],
            facet_index=0,
        )
    assert "Memory change consent" in caplog.text
    assert (
        "PRIVATE-NEW-VALUE" not in caplog.text
        and "Update my diet preference" not in caplog.text
    )
