import asyncio
from dataclasses import replace

import pytest
from context_query_helpers import context_session, seed_item
from livekit import rtc
from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities

from jarvis.conversation import ConversationRole
from jarvis.memory.types import AuthorityClass, MemorySourceClass
from jarvis.voice.personal_context_audio import PersonalContextAudioOutput


class Sink(AudioOutput):
    def __init__(self):
        super().__init__(
            label="test-sink",
            sample_rate=16000,
            capabilities=AudioOutputCapabilities(pause=False),
        )
        self.frames = []
        self.clears = 0

    async def capture_frame(self, frame):
        await super().capture_frame(frame)
        self.frames.append(frame)

    def flush(self):
        super().flush()

    def clear_buffer(self):
        self.clears += 1


QUERY = [{"scope_key": "owned_item.vehicle", "target_quote": "City"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["duplicate", "suppression", "source", "correction", "forget", "overflow"]
)
async def test_scope_changes_block_queued_audio_even_if_selected_record_survives(
    learning, change
):
    selected = await seed_item(learning)
    async with context_session(learning, "My City?") as (s, _, retired):
        assert (await s.query_for_question(QUERY))["status"] == "selected"
        sink = Sink()
        output = PersonalContextAudioOutput(sink, s)
        frame = rtc.AudioFrame.create(16000, 1, 160)
        await output.capture_frame(frame)
        assert len(sink.frames) == 1
        if change == "duplicate":
            await seed_item(learning, "City")
        elif change == "suppression":
            await learning.writer.run(
                lambda c: (
                    c.execute(
                        "INSERT INTO personal_learning_suppression VALUES ('owned_item.vehicle',1,1,'fictional')"
                    ),
                    c.commit(),
                )
            )
        elif change == "source":
            await learning.writer.run(
                lambda c: (
                    c.execute(
                        "UPDATE memory_source SET sensitivity='private' WHERE source_id=?",
                        (selected.source_id,),
                    ),
                    c.commit(),
                )
            )
        elif change in {"correction", "forget"}:
            source = replace(
                learning.plan.mutations[0].source,
                source_id="explicit-change",
                source_class=MemorySourceClass.OWNER_EXPLICIT,
                authority_class=AuthorityClass.OWNER_EXPLICIT,
            )
            if change == "correction":
                await learning.service.correct_text(
                    predicate=selected.predicate, value="Nexon", source=source
                )
            else:
                await learning.service.forget_exact(
                    predicate=selected.predicate, source=source
                )
        else:
            for i in range(32):
                await seed_item(learning, f"phone{i}", "device")
        await output.capture_frame(frame)
        assert len(sink.frames) == 1 and sink.clears and retired
        assert not await s.allow_audio()
        output.detach()


@pytest.mark.asyncio
async def test_unrelated_scope_change_does_not_invalidate_evidence(learning):
    await seed_item(learning)
    async with context_session(learning, "My City?") as (s, _, _):
        await s.query_for_question(QUERY)
        await seed_item(learning, "Phone", "device")
        assert await s.allow_audio()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["lock", "expiry", "new_turn", "activity"])
async def test_question_and_owner_lifecycle_always_revokes_query_audio(
    learning, authority_parts, clock, change
):
    await seed_item(learning)
    async with context_session(learning, "My City?") as (s, c, retired):
        await s.query_for_question(QUERY)
        if change == "lock":
            authority_parts.windows.lock_unlock()
        elif change == "expiry":
            clock.advance(901)
        elif change == "new_turn":
            c.accept_turn(ConversationRole.USER, "What now?")
        else:
            c.begin_user_activity()
        assert not await s.allow_audio() and retired


@pytest.mark.asyncio
async def test_cancelled_snapshot_closes_session_and_releases_serialization_lock(
    learning, monkeypatch
):
    async with context_session(learning, "My City?") as (s, _, retired):
        entered = asyncio.Event()

        async def paused():
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(s._retrieval, "learning_context_snapshot", paused)
        task = asyncio.create_task(s.query_for_question(QUERY))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert retired and not s._context_lock.locked() and not await s.allow_audio()
        assert s._query_projection is None


@pytest.mark.asyncio
async def test_private_response_and_mutation_cleanup_clear_query_evidence(learning):
    await seed_item(learning)
    async with context_session(learning, "My City?") as (s, _, retired):
        await s.query_for_question(QUERY)
        assert await s.allow_audio()
        s.playback_finished()
        s.response_finished()
        assert retired and s._query_projection is None
    async with context_session(learning, "My City?") as (s, _, _):
        await s.query_for_question(QUERY)
        s._operation = "correct"
        s.mutation_committed()
        assert s._query_projection is None and s._release_path is None
        assert (await s.query_for_question(QUERY))["status"] == "denied"
