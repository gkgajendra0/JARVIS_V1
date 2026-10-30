import asyncio
from dataclasses import replace

import pytest
from test_project_conversation_store import setup_store

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.project_conversation_recording import (
    RecordingRoute,
    RequiredConversationRecorder,
)
from jarvis.voice.project_memory_transport import ProjectReplyDispatcher


def test_required_recorder_archives_canonical_turn_without_model_proposals(
    tmp_path, authority_parts
):
    async def scenario():
        (
            _path,
            store,
            selection,
            _permit,
            writer,
            reader,
            issuer,
            grant,
        ) = await setup_store(tmp_path, authority_parts)
        conversation = ConversationSession()
        conversation.start()
        turn = conversation.accept_turn(
            ConversationRole.USER, "I want to go to Nepal in my Jimny"
        )
        recorder = RequiredConversationRecorder(
            store, authority=issuer, grant=grant, source_clearance=lambda _: True
        )
        route = RecordingRoute(selection, 0, "request-1")
        try:
            first = await recorder.record(conversation, turn, route)
            duplicate = await recorder.record(conversation, turn, route)
            assert first.status == "committed"
            assert first.event_id == turn.turn_id
            assert duplicate.status == "duplicate"
            assert duplicate.sequence == first.sequence
            with pytest.raises(PermissionError):
                await recorder.record(conversation, replace(turn), route)
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_denied_recording_prevents_dependent_provider_dispatch(
    tmp_path, authority_parts
):
    async def scenario():
        (
            _path,
            store,
            selection,
            _permit,
            writer,
            reader,
            issuer,
            grant,
        ) = await setup_store(tmp_path, authority_parts)
        conversation = ConversationSession()
        conversation.start()
        turn = conversation.accept_turn(ConversationRole.USER, "private input")
        recorder = RequiredConversationRecorder(
            store, authority=issuer, grant=grant, source_clearance=lambda _: False
        )

        class Provider:
            calls = 0

            async def generate(self, packet):
                self.calls += 1
                yield b"wrong"

        provider = Provider()
        dispatcher = ProjectReplyDispatcher(
            provider, validate_current=lambda _: True, release_audio=lambda _: None
        )

        async def prepare():
            await recorder.record(
                conversation, turn, RecordingRoute(selection, 0, "request-1")
            )
            raise AssertionError("denied recording must not prepare context")

        try:
            with pytest.raises(PermissionError):
                await dispatcher.reply("request-1", prepare)
            assert provider.calls == 0
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_overlapping_duplicate_callbacks_share_one_recording_lease(
    tmp_path, authority_parts
):
    async def scenario():
        (
            _path,
            store,
            selection,
            _permit,
            writer,
            reader,
            issuer,
            grant,
        ) = await setup_store(tmp_path, authority_parts)
        conversation = ConversationSession()
        conversation.start()
        turn = conversation.accept_turn(ConversationRole.USER, "Nepal trip")
        recorder = RequiredConversationRecorder(
            store, authority=issuer, grant=grant, source_clearance=lambda _: True
        )
        route = RecordingRoute(selection, 0, "request-1")
        entered, proceed = asyncio.Event(), asyncio.Event()
        append_calls = []
        original = store.append_event

        async def held_append(*args, **kwargs):
            append_calls.append(args)
            if len(append_calls) == 1:
                entered.set()
                await proceed.wait()
            return await original(*args, **kwargs)

        store.append_event = held_append
        one = asyncio.create_task(recorder.record(conversation, turn, route))
        await entered.wait()
        two = asyncio.create_task(recorder.record(conversation, turn, route))
        await asyncio.sleep(0)
        try:
            assert (
                len(append_calls) == 1
            )  # second must not share/release first permit's source lease
            proceed.set()
            receipts = await asyncio.gather(one, two)
            assert [item.status for item in receipts] == ["committed", "duplicate"]
        finally:
            proceed.set()
            await asyncio.gather(one, two, return_exceptions=True)
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_failed_turn_can_retry_with_refreshed_archive_revision(
    tmp_path, authority_parts
):
    async def scenario():
        (
            _path,
            store,
            selection,
            _permit,
            writer,
            reader,
            issuer,
            grant,
        ) = await setup_store(tmp_path, authority_parts)
        conversation = ConversationSession()
        conversation.start()
        one = conversation.accept_turn(ConversationRole.USER, "Nepal trip")
        two = conversation.accept_turn(ConversationRole.USER, "The permit is pending")
        recorder = RequiredConversationRecorder(
            store, authority=issuer, grant=grant, source_clearance=lambda _: True
        )
        try:
            await recorder.record(
                conversation, one, RecordingRoute(selection, 0, "request-1")
            )
            with pytest.raises(PermissionError, match="archive revision changed"):
                await recorder.record(
                    conversation, two, RecordingRoute(selection, 0, "request-2")
                )
            receipt = await recorder.record(
                conversation, two, RecordingRoute(selection, 1, "request-2")
            )
            assert receipt.status == "committed" and receipt.sequence == 2
            with pytest.raises(PermissionError, match="routing changed"):
                await recorder.record(
                    conversation, two, RecordingRoute(selection, 2, "other-request")
                )
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())
