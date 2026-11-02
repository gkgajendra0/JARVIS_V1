"""Project commands succeed only through a committed routing action."""

import asyncio
import json

import pytest
from test_project_conversation_store import setup_store
from test_project_forget_provenance import EchoingModel, say
from test_project_routing import accepted, routed

from jarvis.memory.project_access import ProjectArchiveAccess
from jarvis.memory.project_routing import (
    ProjectClarificationRequired,
    ProjectRouter,
    parse_project_command,
)
from jarvis.voice.project_answer_provider import ProjectAnswerProvider
from jarvis.voice.project_conversation import ProjectConversationCoordinator


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("create a nepal project", ("nepal", "create")),
        ("Create a new project called Goa trip.", ("Goa trip", "create")),
        ("make my Goa trip project", ("Goa trip", "create")),
        ("start project for interview prep", ("interview prep", "create")),
        ("new project Nepal", ("Nepal", "create")),
        ("Let's plan my Nepal trip", ("Nepal trip", "plan")),
        ("Switch to the trip", ("trip", "select")),
        ("We will take the Jimny", (None, None)),
        ("I want to start a new project at work soon", (None, None)),
        ("make sure the project is ready", (None, None)),
        ("start a new project at work", (None, None)),
    ],
)
def test_project_command_phrases(text, expected):
    assert parse_project_command(text) == expected


def test_create_command_creates_and_announces(tmp_path, authority_parts):
    async def scenario():
        _, store, _, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        router = ProjectRouter(
            ProjectArchiveAccess(store, authority=issuer, grant=grant)
        )
        try:
            general = await routed(router, "Hello")
            assert general.title == "General"
            created = await routed(router, "create a nepal project")
            assert created.create is True and created.title == "nepal"
            assert created.selection.project_id != general.selection.project_id
            assert created.announcement == "Selected nepal."
            catalog = await router.access.catalog()
            assert catalog.current == created.selection
            # Creating an exact existing name selects it instead of duplicating.
            again = await routed(router, "create project nepal")
            assert again.selection == created.selection and again.create is False
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_unreadable_project_command_is_not_reported_as_done(tmp_path, authority_parts):
    async def scenario():
        _, store, _, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        router = ProjectRouter(
            ProjectArchiveAccess(store, authority=issuer, grant=grant)
        )
        try:
            await routed(router, "Hello")
            c, t = accepted("please create a project")
            decision = await router.resolve(c, t)
            assert decision.status == "clarification"
            # Ordinary sentences that mention a project still reach the model.
            for text in (
                "I want to start a new project at work soon",
                "make sure the project is ready",
            ):
                c, t = accepted(text)
                assert (await router.resolve(c, t)).status == "ready"
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


@pytest.mark.asyncio
async def test_coordinator_grounds_routing_and_never_answers_unparsed_commands(
    tmp_path, authority_parts
):
    _, store, _, _, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    model = EchoingModel()
    coordinator = ProjectConversationCoordinator(
        access, source_clearance=lambda _: True
    )
    provider = ProjectAnswerProvider(model)
    try:
        await say(coordinator, provider, "Hello")
        assert model.contexts[-1]["routing"]["action"] == "created"
        created = await say(coordinator, provider, "create a nepal project")
        assert created.announcement == "Selected nepal."
        routing = model.contexts[-1]["routing"]
        assert routing == {"action": "created", "project_title": "nepal"}
        await say(coordinator, provider, "We will take the Jimny")
        assert model.contexts[-1]["routing"]["action"] == "unchanged"
        calls = len(model.contexts)
        from jarvis.conversation import ConversationRole, ConversationSession

        conversation = ConversationSession()
        conversation.start()
        turn = conversation.accept_turn(
            ConversationRole.USER, "please create a project"
        )
        with pytest.raises(ProjectClarificationRequired) as raised:
            await coordinator.respond(
                conversation, turn, provider=provider, authorize=lambda: True
            )
        assert "No project was created" in raised.value.question
        # The model was never asked, so it could not claim the project exists.
        assert len(model.contexts) == calls
        assert "project_title" in json.dumps(model.contexts[-1])
    finally:
        await reader.close()
        await writer.close()
