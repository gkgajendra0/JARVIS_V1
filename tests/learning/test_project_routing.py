import asyncio
from dataclasses import replace

import pytest
from test_project_conversation_store import setup_store

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.project_access import ProjectArchiveAccess
from jarvis.memory.project_routing import ProjectRouter


def accepted(text):
    c = ConversationSession()
    c.start()
    return c, c.accept_turn(ConversationRole.USER, text)


async def routed(router, text, **kwargs):
    c, t = accepted(text)
    decision = await router.resolve(c, t, **kwargs)
    return await router.select(decision)


def test_project_selection_survives_segments_restart_and_explicit_switch(
    tmp_path, authority_parts
):
    async def scenario():
        _, store, _, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        router = ProjectRouter(access)
        try:
            general = await routed(router, "Hello")
            assert general.title == "General"
            nepal = await routed(router, "Let's plan my Nepal trip")
            follow = await routed(router, "We will take the Jimny")
            assert follow.selection == nepal.selection
            other = await routed(router, "Switch to interview preparation")
            assert other.selection.project_id != nepal.selection.project_id
            restarted = ProjectRouter(
                ProjectArchiveAccess(
                    store, authority=issuer, grant=issuer.open("runtime-2", "gemini")
                )
            )
            resumed = await routed(restarted, "Where were we?")
            assert resumed.selection == other.selection
            assert "Resuming" in resumed.announcement
            restored = await routed(restarted, "What is the status of my Nepal trip?")
            assert restored.selection == nepal.selection
            issuer.revoke(grant)
            with pytest.raises(PermissionError):
                await routed(router, "Continue my Nepal trip")
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_duplicate_exact_names_require_clarification_and_cas_prevents_lost_switch(
    tmp_path, authority_parts
):
    async def scenario():
        _, store, selection, _permit, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        router = ProjectRouter(access)
        try:
            await access.create_project(
                replace(selection, project_id="nepal-2", thread_id="thread-2"),
                "Nepal trip",
            )
            c, t = accepted("Continue my Nepal trip")
            ambiguous = await router.resolve(c, t)
            assert ambiguous.status == "clarification"
            assert len(ambiguous.candidates) == 2
            with pytest.raises(ValueError):
                await router.select(ambiguous)
            c, t = accepted("Switch to coding")
            one = await router.resolve(c, t)
            c, t = accepted("Switch to interviews")
            two = await router.resolve(c, t)
            await router.select(one)
            with pytest.raises(PermissionError, match="selection revision"):
                await router.select(two)
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_new_conversation_creates_thread_in_same_project(tmp_path, authority_parts):
    async def scenario():
        _, store, _, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        router = ProjectRouter(
            ProjectArchiveAccess(store, authority=issuer, grant=grant)
        )
        try:
            original = await routed(router, "Continue my Nepal trip")
            new = await routed(router, "New conversation in Nepal trip")
            assert new.selection.project_id == original.selection.project_id
            assert new.selection.thread_id != original.selection.thread_id
            assert (
                await routed(router, "Continue my Nepal trip")
            ).selection == new.selection
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_explicit_owned_project_id_resolves_an_ambiguous_name(
    tmp_path, authority_parts
):
    async def scenario():
        _, store, selection, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        router = ProjectRouter(access)
        try:
            await access.create_project(
                replace(
                    selection, project_id="other-nepal", thread_id="other-nepal-thread"
                ),
                "Nepal trip",
            )
            c, t = accepted("Select project " + selection.project_id)
            chosen = await router.select(await router.resolve(c, t))
            assert chosen.selection.project_id == selection.project_id
            c, t = accepted("Select project nonexistent")
            with pytest.raises(ValueError):
                await router.resolve(c, t)
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_named_question_selects_existing_project_without_fuzzy_topic_guessing(
    tmp_path, authority_parts
):
    async def scenario():
        _, store, _, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        router = ProjectRouter(
            ProjectArchiveAccess(store, authority=issuer, grant=grant)
        )
        try:
            nepal = await routed(router, "Continue my Nepal trip")
            await routed(router, "Switch to interview preparation")
            assert (
                await routed(router, "Which vehicle did I choose for my Nepal trip?")
            ).selection == nepal.selection
            assert (
                await routed(router, "Do not switch to interview preparation")
            ).selection == nepal.selection
            c, t = accepted("Compare Nepal trip and interview preparation?")
            assert (await router.resolve(c, t)).status == "clarification"
        finally:
            await reader.close()
            await writer.close()

    # Clarification is not committed: resolve it directly for the final assertion.
    asyncio.run(scenario())
