"""Actual canonical storage and audio chain; fictional data, no cloud/owner DB."""

import asyncio
import sqlite3
import threading
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from livekit import rtc
from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.retrieval import SemanticRetrievalService
from jarvis.memory.service import MemoryService
from jarvis.memory.types import AuthorityClass, MemorySourceClass, Sensitivity
from jarvis.memory.worker import SerialConnectionWorker
from jarvis.voice.personal_context import PersonalContextSession
from jarvis.voice.personal_context_audio import PersonalContextAudioOutput

NOW = datetime(2026, 10, 20, tzinfo=UTC)


def source(name, sensitivity=Sensitivity.STANDARD):
    return MemorySource(
        source_id=name,
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        canonical_ref=f"synthetic:{name}",
        observed_at=NOW,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
        sensitivity=sensitivity,
        created_at=NOW,
    )


class Authority:
    def __init__(self):
        self.calls = []
        self.valid = True
        self.denied = False
        self.wait = threading.Event()
        self.wait.set()
        self.entered = threading.Event()

    def authorize_personal_context(self, **kwargs):
        self.calls.append(kwargs)
        self.entered.set()
        self.wait.wait(2)
        if self.denied:
            raise PermissionError("denied")
        return object()

    def consume_personal_context(self, permit):
        self.validate_personal_context(permit)

    def validate_personal_context(self, permit):
        if not self.valid:
            raise PermissionError("locked or expired")

    def invalidate_personal_context(self, session_id):
        self.valid = False


@pytest_asyncio.fixture
async def personal(tmp_path):
    path = tmp_path / "fiction.db"
    with sqlite3.connect(path) as connection:
        MemoryMigrationRunner(clock=lambda: NOW).apply(connection)

    def factory():
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    writer = SerialConnectionWorker(factory, thread_name="personal-writer")
    reader = SerialConnectionWorker(factory, thread_name="personal-reader")
    service = MemoryService(
        MemoryLifecycleService(writer), CanonicalMemoryReader(reader)
    )
    await service.remember_text(
        predicate="diet preference", value="vegetarian", source=source("diet")
    )
    await service.remember_text(
        predicate="private plan",
        value="PRIVATE-CANARY",
        sensitivity=Sensitivity.PRIVATE,
        source=source("private", Sensitivity.PRIVATE),
    )
    conversation = ConversationSession()
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Aaj dinner mein kya khaun?")
    authority = Authority()
    retired = []
    session = PersonalContextSession(
        conversation=conversation,
        retrieval=SemanticRetrievalService(reader),
        authority=authority,
        retire=lambda: retired.append(True),
    )
    yield session, service, conversation, authority, retired
    session.close()
    await reader.close()
    await writer.close()


@pytest.mark.asyncio
async def test_canonical_catalog_and_current_selection(personal):
    session, service, _, authority, _ = personal
    catalog = await session.catalog()
    assert catalog["status"] == "available"
    assert catalog["facets"] == ["diet_preference"]
    assert "vegetarian" not in str(catalog) and "CANARY" not in str(catalog)
    assert len(authority.calls) == 1
    await service.correct_text(
        predicate="diet preference", value="vegan", source=source("new")
    )
    packet = await session.read(catalog["catalog_id"], [0])
    assert packet["status"] == "selected"
    assert "vegan" in str(packet) and "vegetarian" not in str(packet)
    assert len(authority.calls) == 1
    await service.forget_exact(predicate="diet preference", source=source("delete"))
    assert (await session.read(catalog["catalog_id"], [0]))["status"] == "denied"


@pytest.mark.asyncio
@pytest.mark.parametrize("indices", [[True], [-1], [1], [0, 0], list(range(5)), "0"])
async def test_untrusted_selection_is_strict(personal, indices):
    session, *_ = personal
    catalog = await session.catalog()
    assert (await session.read(catalog["catalog_id"], indices))[
        "status"
    ] == "invalid_selection"
    assert (await session.read("invented", [0]))["status"] == "invalid_selection"


@pytest.mark.asyncio
async def test_late_consent_after_activity_never_releases(personal):
    session, _, conversation, authority, _ = personal
    authority.wait.clear()
    task = asyncio.create_task(session.catalog())
    await asyncio.to_thread(authority.entered.wait, 1)
    conversation.begin_user_activity()
    session.observe_activity()
    authority.wait.set()
    assert (await task)["status"] == "denied"
    assert not await session.allow_audio()


@pytest.mark.asyncio
async def test_denial_and_store_failure_are_distinct(personal, monkeypatch):
    session, _, _, authority, _ = personal
    authority.denied = True
    assert (await session.catalog())["status"] == "denied"
    authority.denied = False

    async def fail(**kwargs):
        raise RuntimeError("sensitive internal exception")

    monkeypatch.setattr(session._retrieval, "eligible_facet_catalog", fail)
    result = await session.catalog()
    assert result["status"] == "unavailable"
    assert "sensitive" not in str(result)


@pytest.mark.asyncio
async def test_same_text_new_turn_and_cancelled_consent_are_revoked(personal):
    session, _, conversation, authority, retired = personal
    authority.wait.clear()
    task = asyncio.create_task(session.catalog())
    await asyncio.to_thread(authority.entered.wait, 1)
    assert (await session.catalog())["status"] == "denied"  # no second Hello
    old = conversation.turns[-1]
    new = conversation.accept_turn(ConversationRole.USER, old.text)
    session.observe_turn(new)
    authority.wait.set()
    assert (await task)["status"] == "denied"
    assert old.turn_id != new.turn_id and retired


@pytest.mark.asyncio
async def test_mutation_consent_is_not_a_read_permit(personal):
    session, _, _, authority, _ = personal
    await session.authorize_mutation("remember", "diet", "vegan")
    session.mutation_committed()
    assert (await session.catalog())["status"] == "denied"
    assert authority.calls[0]["operation"] == "remember"


@pytest.mark.asyncio
async def test_cancellation_closes_late_authorization(personal):
    session, _, _, authority, retired = personal
    authority.wait.clear()
    task = asyncio.create_task(session.catalog())
    await asyncio.to_thread(authority.entered.wait, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    authority.wait.set()
    assert retired and not await session.allow_audio()


@pytest.mark.asyncio
async def test_deleted_before_release_is_no_match_and_large_value_dropped(personal):
    session, service, _, _, _ = personal
    catalog = await session.catalog()
    await service.correct_text(
        predicate="diet preference", value="अ" * 1000, source=source("large")
    )
    assert (await session.read(catalog["catalog_id"], [0]))["status"] == "no_match"
    await service.forget_exact(predicate="diet preference", source=source("gone"))
    assert (await session.read(catalog["catalog_id"], [0]))["status"] == "no_match"


class Sink(AudioOutput):
    def __init__(self):
        super().__init__(
            label="test", capabilities=AudioOutputCapabilities(pause=False)
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


@pytest.mark.asyncio
async def test_real_audio_chain_cannot_forward_after_lock_or_new_turn(personal):
    session, _, _, authority, retired = personal
    catalog = await session.catalog()
    await session.read(catalog["catalog_id"], [0])
    sink = Sink()
    output = PersonalContextAudioOutput(sink, session)
    frame = rtc.AudioFrame.create(16000, 1, 160)
    await output.capture_frame(frame)
    assert len(sink.frames) == 1
    authority.valid = False
    await output.capture_frame(frame)
    assert len(sink.frames) == 1 and sink.clears
    assert retired
    output.detach()


@pytest.mark.asyncio
async def test_private_history_retires_after_completed_audio(personal):
    session, _, _, _, retired = personal
    sink = Sink()
    output = PersonalContextAudioOutput(sink, session)
    # A pre-tool preamble cannot retire the later personal response.
    await output.capture_frame(rtc.AudioFrame.create(16000, 1, 160))
    output.flush()
    sink.on_playback_finished(playback_position=0.01, interrupted=False)
    assert not retired
    catalog = await session.catalog()
    await session.read(catalog["catalog_id"], [0])
    await output.capture_frame(rtc.AudioFrame.create(16000, 1, 160))
    output.flush()
    sink.on_playback_finished(playback_position=0.02, interrupted=False)
    session.response_finished()
    assert retired
    assert not await session.allow_audio()
    output.detach()


@pytest.mark.asyncio
async def test_output_detach_does_not_leak_shared_device_listeners(personal):
    session, *_ = personal
    sink = Sink()
    before = {name: len(callbacks) for name, callbacks in sink._events.items()}
    output = PersonalContextAudioOutput(sink, session)
    output.detach()
    assert {
        name: len(callbacks) for name, callbacks in sink._events.items() if callbacks
    } == before


@pytest.mark.asyncio
async def test_external_correction_stops_already_released_audio(personal):
    session, service, _, _, retired = personal
    catalog = await session.catalog()
    await session.read(catalog["catalog_id"], [0])
    await service.correct_text(
        predicate="diet preference", value="vegan", source=source("change")
    )
    assert not await session.allow_audio()
    assert retired


@pytest.mark.asyncio
async def test_catalog_and_total_fact_budgets(personal):
    session, service, _, _, _ = personal
    for index in range(130):
        await service.remember_text(
            predicate=f"facet {index:03}",
            value="fictional",
            source=source(f"facet-{index}"),
        )
    catalog = await session.catalog()
    assert len(catalog["facets"]) == 128 and catalog["truncated"] is True
    first = await session.read(catalog["catalog_id"], [0, 1, 2, 3])
    assert first["status"] == "selected" and len(first["facts"]) == 4
    assert (await session.read(catalog["catalog_id"], [4]))[
        "status"
    ] == "invalid_selection"


@pytest.mark.asyncio
async def test_consent_timeout_retires_before_late_result(personal):
    session, _, _, authority, retired = personal
    authority.wait.clear()
    session._consent_timeout = 0.01
    assert (await session.catalog())["status"] == "denied"
    authority.wait.set()
    assert retired and not await session.allow_audio()


@pytest.mark.asyncio
@pytest.mark.parametrize("release", ["audio", "read"])
async def test_no_release_after_last_storage_await_is_interrupted(
    personal, monkeypatch, release
):
    session, _, conversation, _, _ = personal
    catalog = await session.catalog()
    await session.read(catalog["catalog_id"], [0])
    entered = asyncio.Event()
    resume = asyncio.Event()
    calls = 0

    async def paused_current():
        nonlocal calls
        calls += 1
        if release == "audio" or calls == 2:
            entered.set()
            await resume.wait()
        return True

    monkeypatch.setattr(session, "_facts_current", paused_current)
    task = asyncio.create_task(
        session.allow_audio()
        if release == "audio"
        else session.read(catalog["catalog_id"], [0])
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    conversation.begin_user_activity()
    session.observe_activity()
    resume.set()
    result = await task
    assert result is False if release == "audio" else result["status"] == "denied"
