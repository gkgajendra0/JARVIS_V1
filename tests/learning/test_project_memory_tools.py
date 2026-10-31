import asyncio

import pytest
from test_project_conversation_store import event, setup_store

from jarvis.memory.project_access import ProjectArchiveAccess
from jarvis.voice.project_memory_tools import ProjectMemoryTools


def test_memory_tools_scope_budget_and_source_allowlist(tmp_path, authority_parts):
    async def scenario():
        _, store, selection, permit, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        value = event()
        await store.append_event(
            selection,
            value,
            permit=permit("admit", store.append_material(selection, value, 0), value),
            expected_revision=0,
        )
        tools = ProjectMemoryTools(
            access,
            selection=selection,
            request_id="next-request",
            is_current=lambda: True,
        )
        try:
            with pytest.raises(PermissionError):
                await tools.search_conversation_memory("interviews", "Jimny")
            found = await tools.search_conversation_memory(
                selection.project_id, "Jimny"
            )
            assert (
                found.status == "complete"
                and found.sources[0].event.event_id == value.event_id
            )
            with pytest.raises(PermissionError):
                await tools.read_conversation_sources(("unrelated",))
            read = await tools.read_conversation_sources((value.event_id,))
            assert read.sources[0].event.text == value.text
            with pytest.raises(PermissionError):
                await tools.search_conversation_memory(selection.project_id, "again")
            issuer.revoke(grant)
            with pytest.raises(PermissionError):
                await access.snapshot(selection)
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_project_tools_and_inspection_reach_older_threads_in_same_project(
    tmp_path, authority_parts
):
    async def scenario():
        _, store, _, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        from jarvis.conversation import ConversationRole, ConversationSession
        from jarvis.memory.project_controls import ProjectControls
        from jarvis.voice.project_conversation import ProjectConversationCoordinator

        coordinator = ProjectConversationCoordinator(
            access, source_clearance=lambda _: True
        )
        c = ConversationSession()
        c.start()
        try:
            for text in (
                "Continue my Nepal trip",
                "The chosen vehicle is a Jimny",
                "New conversation in Nepal trip",
            ):
                turn = c.accept_turn(ConversationRole.USER, text)
                packet = await coordinator.prepare_reply(
                    c, turn, authorize=lambda: True
                )
            tools = ProjectMemoryTools(
                access,
                selection=packet.selection,
                request_id=packet.request_id,
                is_current=lambda: coordinator.validate_current(packet),
            )
            result = await tools.search_conversation_memory(
                packet.selection.project_id, "Jimny"
            )
            assert result.sources and "Jimny" in result.sources[0].event.text
            ids = tuple(s.event.event_id for s in result.sources)
            assert (await tools.read_conversation_sources(ids)).sources
            inspection = await ProjectControls(access).inspect_project(
                packet.selection.project_id
            )
            assert any("Jimny" in s.event.text for s in inspection.sources)
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


@pytest.mark.asyncio
async def test_search_balances_original_users_with_repeated_assistant_matches(
    tmp_path, authority_parts
):
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    _, store, selection, permit, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    values = [
        event("user-choice", text="The permit for our Jimny is pending."),
        event("user-correction", text="The permit is now approved."),
        *[
            event(f"echo-{i}", text="The Jimny permit is approved.", role="assistant")
            for i in range(12)
        ],
        event("current-question", text="What is the permit status?"),
        event("journal", text='{"tool":"search","query":"permit"}', role="tool"),
    ]
    try:
        for revision, value in enumerate(values):
            value = replace(
                value,
                request_id="current"
                if value.event_id == "current-question"
                else value.event_id,
                accepted_at=datetime(2026, 10, 31, tzinfo=UTC)
                + timedelta(seconds=revision),
            )
            await store.append_event(
                selection,
                value,
                permit=permit(
                    "admit", store.append_material(selection, value, revision), value
                ),
                expected_revision=revision,
            )
        tools = ProjectMemoryTools(
            access, selection=selection, request_id="current", is_current=lambda: True
        )
        found = await tools.search_conversation_memory(selection.project_id, "permit")
        ids = {s.event.event_id for s in found.sources}
        assert {"user-choice", "user-correction"} <= ids
        assert "current-question" not in ids and "journal" not in ids
        assert len(found.sources) == 8 and found.status == "partial"
        assert any(s.event.role == "assistant" for s in found.sources)
        assert [s.event.accepted_at for s in found.sources] == sorted(
            s.event.accepted_at for s in found.sources
        )
        read = await tools.read_conversation_sources(("user-correction",))
        assert read.sources[0].event.text == "The permit is now approved."
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "assistant"])
async def test_search_uses_full_budget_when_only_one_role_matches(
    tmp_path, authority_parts, role
):
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    _, store, selection, permit, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    try:
        for i in range(10):
            value = replace(
                event(f"only-{i}", text="permit note", role=role),
                accepted_at=datetime(2026, 10, 31, tzinfo=UTC) + timedelta(seconds=i),
            )
            await store.append_event(
                selection,
                value,
                permit=permit(
                    "admit", store.append_material(selection, value, i), value
                ),
                expected_revision=i,
            )
        result = await access.snapshot(
            selection, query="permit", project_wide=True, limit=8
        )
        assert [s.event.event_id for s in result.sources] == [
            f"only-{i}" for i in range(2, 10)
        ]
        assert result.status == "partial"
        no_match = await access.snapshot(
            selection, query="nonexistent", project_wide=True, limit=8
        )
        assert no_match.status == "no_match" and not no_match.sources
    finally:
        await reader.close()
        await writer.close()
