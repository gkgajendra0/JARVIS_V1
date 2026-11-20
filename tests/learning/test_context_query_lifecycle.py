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
    "change", ["duplicate", "suppression", "source", "correction", "forget"]
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
                evidence_text=None,
            )
            if change == "correction":
                await learning.service.correct_text(
                    predicate=selected.predicate, value="Nexon", source=source
                )
            else:
                await learning.service.forget_exact(
                    predicate=selected.predicate, source=source
                )
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
        # Slice 1 PR C: storage beyond 32 rows is no longer a global
        # failure; many rows in another scope leave this answer valid.
        for i in range(32):
            await seed_item(learning, f"phone{i}", "device")
        assert await s.allow_audio()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["lock", "expiry", "new_turn", "activity_then_turn"])
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
            assert await s.allow_audio() and not retired
            c.accept_turn(ConversationRole.USER, "What now?")
        assert not await s.allow_audio() and retired


@pytest.mark.asyncio
async def test_voice_activity_without_a_transcript_keeps_query_audio(learning):
    """speaker-eval-2: VAD activity with no accepted turn is not a new question."""
    await seed_item(learning)
    async with context_session(learning, "My City?") as (s, c, retired):
        await s.query_for_question(QUERY)
        c.begin_user_activity()
        s.observe_activity()
        assert await s.allow_audio() and not retired


@pytest.mark.asyncio
async def test_cancelled_snapshot_closes_session_and_releases_serialization_lock(
    learning, monkeypatch
):
    async with context_session(learning, "My City?") as (s, _, retired):
        entered = asyncio.Event()

        async def paused(*args):
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["expiry", "lock", "mutation", "permit", "operation"]
)
async def test_revocation_during_snapshot_cannot_forward_a_frame(
    learning, authority_parts, clock, monkeypatch, change
):
    from jarvis.authority.personal_learning import CATEGORIES, LearningActionBinding

    await seed_item(learning)
    async with context_session(learning, "My City?") as (s, _, retired):
        assert (await s.query_for_question(QUERY))["status"] == "selected"
        s._watchdog.cancel()
        await asyncio.gather(s._watchdog, return_exceptions=True)
        original = s._retrieval.learning_context_snapshot

        async def changed_during_read(*args):
            snapshot = await original(*args)
            if change == "expiry":
                clock.advance(901)
            elif change == "lock":
                authority_parts.windows.lock_unlock()
            elif change == "mutation":
                s._mutation_inflight = True
            elif change == "operation":
                s._operation = "correct"
            else:
                source = s._learning_source
                permit = learning.authority.issue_child(
                    learning.grant,
                    LearningActionBinding(
                        "read",
                        source.receipt_id,
                        source.digest,
                        tuple(sorted(CATEGORIES)),
                    ),
                )
                learning.authority.consume_read(permit)
                s._permit = permit
            return snapshot

        monkeypatch.setattr(
            s._retrieval, "learning_context_snapshot", changed_during_read
        )
        sink = Sink()
        output = PersonalContextAudioOutput(sink, s)
        try:
            await output.capture_frame(rtc.AudioFrame.create(16000, 1, 160))
            assert not sink.frames and sink.clears and retired
        finally:
            output.detach()


@pytest.mark.asyncio
async def test_legacy_release_rechecks_authority_after_final_storage_await(
    learning, clock, monkeypatch
):
    await seed_item(learning)
    async with context_session(learning) as (s, _, retired):
        catalog = await s.catalog()
        s._watchdog.cancel()
        await asyncio.gather(s._watchdog, return_exceptions=True)
        original = s._retrieval.retrieve_exact_current_facet
        calls = 0

        async def revoke_after_final_read(*args, **kwargs):
            nonlocal calls
            rows = await original(*args, **kwargs)
            calls += 1
            if calls == 2:
                clock.advance(901)
            return rows

        monkeypatch.setattr(
            s._retrieval, "retrieve_exact_current_facet", revoke_after_final_read
        )
        result = await s.read(catalog["catalog_id"], [0])
        assert result["status"] == "denied" and retired
