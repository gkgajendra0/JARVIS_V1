import asyncio

import pytest
from test_project_conversation_store import event, setup_store

from jarvis.memory.project_access import ProjectArchiveAccess
from jarvis.memory.project_controls import ProjectControls


def test_forget_removes_content_and_blocks_delayed_event_resurrection(
    tmp_path, authority_parts
):
    async def scenario():
        (
            path,
            store,
            selection,
            permit,
            writer,
            reader,
            issuer,
            grant,
        ) = await setup_store(tmp_path, authority_parts)
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        controls = ProjectControls(access)
        value = event()
        token = permit("admit", store.append_material(selection, value, 0), value)
        await store.append_event(selection, value, permit=token, expected_revision=0)
        try:
            inspected = await controls.inspect_project(selection.project_id)
            assert inspected.sources[0].event.text == value.text
            await controls.forget_project(selection.project_id, expected_revision=1)
            with pytest.raises(PermissionError):
                await access.snapshot(selection)
            token = permit("admit", store.append_material(selection, value, 1), value)
            with pytest.raises(PermissionError):
                await store.append_event(
                    selection, value, permit=token, expected_revision=1
                )
            import sqlite3

            with sqlite3.connect(path) as conn:
                assert value.text not in str(
                    conn.execute("SELECT text FROM conversation_event").fetchall()
                )
            assert (
                len(authority_parts.hello.calls) == 2
            )  # separate explicit destructive approval
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_pause_revokes_old_routes_and_aliases_resolve_exactly(
    tmp_path, authority_parts
):
    async def scenario():
        _, store, selection, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        controls = ProjectControls(access)
        try:
            await controls.set_aliases(selection.project_id, ("Himalayan holiday",))
            from jarvis.conversation import ConversationRole, ConversationSession
            from jarvis.memory.project_routing import ProjectRouter

            c = ConversationSession()
            c.start()
            turn = c.accept_turn(ConversationRole.USER, "Continue my Himalayan holiday")
            decision = await ProjectRouter(access).resolve(c, turn)
            assert decision.selection.project_id == selection.project_id
            await controls.pause_project(selection.project_id, paused=True)
            snapshot = await controls.inspect_project(selection.project_id)
            assert snapshot.retention_paused
            with pytest.raises(PermissionError):
                await access.snapshot(selection)
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_snapshot_must_not_return_sources_after_forget_between_read_and_return(
    tmp_path, authority_parts
):
    async def scenario():
        _, store, selection, permit, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        value = event()
        await store.append_event(
            selection,
            value,
            permit=permit("admit", store.append_material(selection, value, 0), value),
            expected_revision=0,
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        controls = ProjectControls(access)
        original = access._perform
        injected = False

        async def racing(selected, material, operation, run):
            nonlocal injected
            result = await original(selected, material, operation, run)
            if material["operation"] == "snapshot" and not injected:
                injected = True
                await controls.forget_project(selection.project_id, expected_revision=1)
            return result

        access._perform = racing
        try:
            with pytest.raises(PermissionError):
                await access.snapshot(selection)
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_deletion_approval_is_invalidated_if_another_thread_changes(
    tmp_path, authority_parts
):
    async def scenario():
        (
            path,
            store,
            selection,
            _permit,
            writer,
            reader,
            issuer,
            grant,
        ) = await setup_store(tmp_path, authority_parts)
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        from dataclasses import replace

        other = replace(selection, thread_id="other-thread")
        await access.create_project(other, "Nepal trip")
        controls = ProjectControls(access)
        original = issuer.authorize_project_deletion

        def approve_then_late_write(material):
            token = original(material)
            import sqlite3

            with sqlite3.connect(path) as conn:
                conn.execute(
                    "UPDATE conversation_thread SET archive_revision=archive_revision+1 WHERE thread_id=?",
                    (selection.thread_id,),
                )
            return token

        issuer.authorize_project_deletion = approve_then_late_write
        try:
            with pytest.raises(PermissionError, match="project changed"):
                await controls.forget_project(selection.project_id, expected_revision=0)
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())
