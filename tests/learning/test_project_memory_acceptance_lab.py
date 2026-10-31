import json
import sqlite3
from types import SimpleNamespace

import pytest
import pytest_asyncio

from jarvis.authority.conversation_history import ConversationHistoryAuthority
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.project_access import ProjectArchiveAccess
from jarvis.memory.project_conversation_store import ProjectConversationStore
from jarvis.memory.worker import SerialConnectionWorker
from jarvis.voice.project_answer_provider import ProjectAnswerProvider
from jarvis.voice.project_conversation import ProjectConversationCoordinator


@pytest_asyncio.fixture
async def empty_access(tmp_path, authority_parts):
    path = tmp_path / "acceptance.db"
    with sqlite3.connect(path) as conn:
        MemoryMigrationRunner().apply(conn)
    writer = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="fixture-write"
    )
    reader = SerialConnectionWorker(
        lambda: sqlite3.connect(path), thread_name="fixture-read"
    )
    issuer = ConversationHistoryAuthority(authority_parts.broker)
    grant = issuer.open("fixture-runtime", "gemini")
    store = ProjectConversationStore(writer=writer, reader=reader, authority=issuer)
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    try:
        yield access
    finally:
        issuer.close()
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_fixture_seeds_originals_conflict_and_older_window_without_provider(
    empty_access,
):
    from jarvis.voice.project_memory_acceptance import seed_acceptance_fixture

    manifest = await seed_acceptance_fixture(empty_access)
    selection = (await empty_access.catalog()).current
    assert selection.project_id == manifest["project_id"]
    full = await empty_access.snapshot(selection, limit=128, project_wide=True)
    assert len(full.sources) == 43
    by_id = {s.event.event_id: s for s in full.sources}
    originals = [by_id[k] for k in manifest["original_source_ids"]]
    assert all(s.event.role == "user" for s in originals)
    assert "Jimny" in originals[0].event.text and "approved" in originals[1].event.text
    conflict = by_id[manifest["conflicting_assistant_id"]].event
    assert (
        conflict.role == "assistant"
        and "Scorpio" in conflict.text
        and "pending" in conflict.text
    )
    recent = await empty_access.snapshot(selection, project_wide=True)
    assert not set(manifest["original_source_ids"]) & {
        s.event.event_id for s in recent.sources
    }
    before = empty_access.store.change_revision
    with pytest.raises(ValueError, match="empty"):
        await seed_acceptance_fixture(empty_access)
    assert empty_access.store.change_revision == before


@pytest.mark.asyncio
async def test_seed_requires_live_authority(empty_access):
    from jarvis.voice.project_memory_acceptance import seed_acceptance_fixture

    empty_access.authority.revoke(empty_access.grant)
    with pytest.raises(PermissionError):
        await seed_acceptance_fixture(empty_access)


@pytest.mark.asyncio
async def test_original_source_report_observes_real_search_to_generation(empty_access):
    from jarvis.voice.project_memory_acceptance import (
        FixtureEvidenceProvider,
        fixture_evidence,
        seed_acceptance_fixture,
    )

    manifest = await seed_acceptance_fixture(empty_access)
    coordinator = ProjectConversationCoordinator(
        empty_access, source_clearance=lambda _: True
    )
    c = ConversationSession()
    c.start()
    payloads = []

    class Wire:
        async def parse_with_telemetry(self, **kwargs):
            await kwargs["before_dispatch"]()
            payloads.append(kwargs["input_payload"]["context"])
            response = (
                {"search_query": "vehicle permit"}
                if len(payloads) == 1
                else {"answer": "You chose the Jimny. The permit is approved."}
            )
            return SimpleNamespace(
                parsed=kwargs["response_model"](response=response),
                usage={},
                usage_observed=False,
                latency_ms=1,
            )

    observer = FixtureEvidenceProvider(
        ProjectAnswerProvider(Wire()), empty_access, manifest
    )
    result = await coordinator.respond(
        c,
        c.accept_turn(
            ConversationRole.USER,
            "Which vehicle did we choose and what is the latest permit status?",
        ),
        provider=observer,
        authorize=empty_access.current,
    )
    first = {s["source_id"] for s in payloads[0]["sources"]}
    assert not set(manifest["original_source_ids"]) & first
    report = fixture_evidence(manifest, result, observer=observer)
    assert report["fresh_fixture_trial"]
    assert report["original_sources_in_final_context"] == 2
    assert report["original_sources_expected"] == 2
    assert report["provider_steps"] == 2 and report["answer_quality"] == "not_evaluated"
    assert report["tools"] == [{"tool": "search", "status": "complete"}]
    assert "Jimny" not in json.dumps(report) and "Scorpio" not in json.dumps(report)
    assert report["conflicting_assistant_in_final_context"]


@pytest.mark.asyncio
async def test_explicit_reauthorization_requires_new_hello_and_preserves_store(
    empty_access, authority_parts
):
    from jarvis.voice.project_memory_lab import reauthorize_lab_history

    old = ProjectConversationCoordinator(empty_access, source_clearance=lambda _: True)
    c = ConversationSession()
    c.start()
    packet = await old.prepare_reply(
        c,
        c.accept_turn(ConversationRole.USER, "Plan my Nepal trip"),
        authorize=empty_access.current,
    )
    empty_access.authority.revoke(empty_access.grant)
    before = len(authority_parts.hello.calls)
    fresh_access, fresh = await reauthorize_lab_history(empty_access, old)
    assert len(authority_parts.hello.calls) == before + 1
    assert not empty_access.current() and fresh_access.current()
    assert not old.validate_current(packet) and fresh_access.store is empty_access.store
    assert (await fresh_access.catalog()).current == packet.selection
    c2 = ConversationSession()
    c2.start()
    await fresh.prepare_reply(
        c2,
        c2.accept_turn(ConversationRole.USER, "Continue my Nepal trip"),
        authorize=fresh_access.current,
    )


@pytest.mark.asyncio
async def test_denied_reauthorization_invalidates_old_reply_and_never_reopens(
    empty_access, authority_parts
):
    from jarvis.voice.project_memory_lab import reauthorize_lab_history

    old = ProjectConversationCoordinator(empty_access, source_clearance=lambda _: True)
    c = ConversationSession()
    c.start()
    packet = await old.prepare_reply(
        c,
        c.accept_turn(ConversationRole.USER, "Plan my Nepal trip"),
        authorize=empty_access.current,
    )
    authority_parts.hello.denied = True
    with pytest.raises(PermissionError):
        await reauthorize_lab_history(empty_access, old)
    assert not old.validate_current(packet) and not empty_access.current()


@pytest.mark.asyncio
async def test_reauthorization_keeps_paused_project_paused(empty_access):
    from jarvis.memory.project_controls import ProjectControls
    from jarvis.voice.project_memory_lab import reauthorize_lab_history

    old = ProjectConversationCoordinator(empty_access, source_clearance=lambda _: True)
    c = ConversationSession()
    c.start()
    packet = await old.prepare_reply(
        c,
        c.accept_turn(ConversationRole.USER, "Plan my Nepal trip"),
        authorize=empty_access.current,
    )
    await ProjectControls(empty_access).pause_project(
        packet.selection.project_id, paused=True
    )
    fresh_access, fresh = await reauthorize_lab_history(empty_access, old)
    selected = (await fresh_access.catalog()).current
    assert (await fresh_access.snapshot(selected)).retention_paused
    with pytest.raises(PermissionError, match="omitted"):
        await fresh.prepare_reply(
            c,
            c.accept_turn(ConversationRole.USER, "A new note"),
            authorize=fresh_access.current,
        )


def test_seed_resume_cli_rejected_before_profile_or_platform_operations(
    monkeypatch, capsys
):
    import sys

    from jarvis.voice.project_memory_lab import main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lab",
            "--lab-root",
            "unused",
            "--model",
            "unused",
            "--source-commit",
            "a" * 40,
            "--seed-acceptance",
            "--resume-lab",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "never --resume-lab" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_other_thread_then_original_thread_is_not_a_fresh_fixture_trial(
    empty_access,
):
    from jarvis.voice.project_memory_acceptance import (
        FixtureEvidenceProvider,
        fixture_evidence,
        seed_acceptance_fixture,
    )

    manifest = await seed_acceptance_fixture(empty_access)
    coordinator = ProjectConversationCoordinator(
        empty_access, source_clearance=lambda _: True
    )
    c = ConversationSession()
    c.start()

    class Wire:
        async def parse_with_telemetry(self, **kwargs):
            await kwargs["before_dispatch"]()
            return SimpleNamespace(
                parsed=kwargs["response_model"](
                    response={"answer": "Prior assistant answer"}
                ),
                usage={},
                usage_observed=False,
                latency_ms=1,
            )

    provider = ProjectAnswerProvider(Wire())
    for question in (
        "New conversation in Nepal acceptance",
        f"Select project {manifest['project_id']} thread {manifest['thread_id']}",
    ):
        observer = FixtureEvidenceProvider(provider, empty_access, manifest)
        result = await coordinator.respond(
            c,
            c.accept_turn(ConversationRole.USER, question),
            provider=observer,
            authorize=empty_access.current,
        )
        await coordinator.record_assistant(c, result, delivered_text=result.answer)
    assert result.receipt.sequence == 44
    assert not fixture_evidence(manifest, result, observer=observer)[
        "fresh_fixture_trial"
    ]
