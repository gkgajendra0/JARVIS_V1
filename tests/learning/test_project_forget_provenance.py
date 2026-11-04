"""Forgetting a project also removes what Jarvis derived from it elsewhere.

Reproduces the owner's 30 Oct / 2 Nov lab trace: a fact said only in
Interview preparation is recalled from Nepal, Interview preparation is
forgotten, and the fact must not come back in Nepal, after restart, or
through search, source reads or a fresh coordinator.
"""

import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest
from test_project_conversation_store import setup_store

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.project_access import ProjectArchiveAccess
from jarvis.memory.project_controls import ProjectControls
from jarvis.voice.project_answer_provider import ProjectAnswerProvider
from jarvis.voice.project_conversation import ProjectConversationCoordinator

FACT = "SQL window functions"


class EchoingModel:
    """Stands in for Gemini: answers from whatever evidence the context shows,
    including Jarvis's own earlier replies. It never knows the fact itself."""

    def __init__(self):
        self.contexts = []

    async def parse_with_telemetry(self, **kwargs):
        check = kwargs["before_dispatch"]()
        if asyncio.iscoroutine(check):
            await check
        payload = kwargs["input_payload"]
        context = payload["context"]
        self.contexts.append(context)
        question = payload["question"].casefold()
        tools = payload["available_tools"]
        if "interview topic" in question:
            seen = json.dumps(context, ensure_ascii=False)
            if FACT in seen:
                response = {"answer": f"Your interview topic is {FACT}."}
            elif tools["search_available"] and not context["retrieval"]:
                response = {"search_query": "interview topic"}
            else:
                response = {"answer": "I don't have your interview topic."}
        else:
            response = {"answer": "Understood."}
        return SimpleNamespace(
            parsed=kwargs["response_model"](response=response),
            usage={"input_tokens": 1, "output_tokens": 1},
            usage_observed=True,
            latency_ms=1,
        )


async def say(coordinator, provider, text):
    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, text)
    result = await coordinator.respond(
        conversation, turn, provider=provider, authorize=lambda: True
    )
    await coordinator.validate_for_release(result)
    await coordinator.record_assistant(
        conversation, result, delivered_text=result.answer
    )
    return result


def rows(path, sql, params=()):
    with sqlite3.connect(path) as connection:
        return connection.execute(sql, params).fetchall()


async def owner_trace(tmp_path, authority_parts):
    """Steps 1-7 of the owner's reproduction."""
    path, store, _, _, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    model = EchoingModel()
    provider = ProjectAnswerProvider(model)
    coordinator = ProjectConversationCoordinator(
        access, source_clearance=lambda _: True
    )
    await say(coordinator, provider, "Let's plan my Nepal trip")
    await say(coordinator, provider, "We will take the Jimny. The permits are sorted.")
    await say(coordinator, provider, "create project called interview preparation")
    await say(coordinator, provider, f"My interview topic is {FACT}.")
    await say(coordinator, provider, "Switch to the trip")
    recalled = await say(coordinator, provider, "What is my interview topic?")
    assert recalled.answer == f"Your interview topic is {FACT}."
    catalog = await access.catalog()
    interview = next(e for e in catalog.entries if e.title == "interview preparation")
    nepal = next(e for e in catalog.entries if e.title == "Nepal trip")
    await say(coordinator, provider, "create project called interview preparation")
    controls = ProjectControls(access)
    inspected = await controls.inspect_project(interview.selection.project_id)
    receipt = await controls.forget_project(
        interview.selection.project_id, expected_revision=inspected.archive_revision
    )
    return SimpleNamespace(
        path=path,
        store=store,
        access=access,
        issuer=issuer,
        grant=grant,
        model=model,
        provider=provider,
        coordinator=coordinator,
        controls=controls,
        receipt=receipt,
        nepal=nepal,
        interview=interview,
        writer=writer,
        reader=reader,
    )


@pytest.mark.asyncio
async def test_root_cause_is_the_assistant_reply_saved_in_the_other_project(
    tmp_path, authority_parts
):
    trace = await owner_trace(tmp_path, authority_parts)
    try:
        # The forgotten project's own events are redacted...
        assert not rows(
            trace.path,
            "SELECT 1 FROM conversation_event WHERE thread_id=? AND text LIKE ?",
            (trace.interview.selection.thread_id, f"%{FACT}%"),
        )
        # ...and so is the Nepal reply that quoted them. Before the fix this
        # Nepal assistant event was the retained source of the post-forget answer.
        assert not rows(
            trace.path,
            "SELECT event_id FROM conversation_event WHERE text LIKE ?",
            (f"%{FACT}%",),
        )
        derived = rows(
            trace.path,
            "SELECT e.role,e.text FROM conversation_event e JOIN conversation_thread t "
            "ON t.thread_id=e.thread_id WHERE t.project_id=? AND e.text='[forgotten]'",
            (trace.nepal.selection.project_id,),
        )
        assert derived and all(role == "tool" for role, _ in derived)
        assert trace.receipt.derived_sources == len(derived)
        # Nepal's own user-authored history is untouched.
        nepal_user = [
            t
            for (t,) in rows(
                trace.path,
                "SELECT e.text FROM conversation_event e JOIN conversation_thread t "
                "ON t.thread_id=e.thread_id WHERE t.project_id=? AND e.role='user'",
                (trace.nepal.selection.project_id,),
            )
        ]
        assert "We will take the Jimny. The permits are sorted." in nepal_user
        assert "What is my interview topic?" in nepal_user
    finally:
        await trace.reader.close()
        await trace.writer.close()


@pytest.mark.asyncio
async def test_forgotten_fact_is_not_recalled_in_another_project_or_after_restart(
    tmp_path, authority_parts
):
    trace = await owner_trace(tmp_path, authority_parts)
    try:
        await say(trace.coordinator, trace.provider, "Switch to the trip")
        after = await say(
            trace.coordinator, trace.provider, "What is my interview topic?"
        )
        assert FACT not in after.answer
        assert all(FACT not in json.dumps(c) for c in trace.model.contexts[-3:])
        # Restart: a fresh access and coordinator over the same database.
        restarted_grant = trace.issuer.open("runtime-restart", "gemini")
        access = ProjectArchiveAccess(
            trace.store, authority=trace.issuer, grant=restarted_grant
        )
        coordinator = ProjectConversationCoordinator(
            access, source_clearance=lambda _: True
        )
        resumed = await say(
            coordinator, trace.provider, "What is the status of my Nepal trip?"
        )
        assert "Jimny" in json.dumps(trace.model.contexts[-1])
        assert FACT not in resumed.answer
        again = await say(coordinator, trace.provider, "What is my interview topic?")
        assert FACT not in again.answer
        assert all(FACT not in json.dumps(c) for c in trace.model.contexts[-4:])
    finally:
        await trace.reader.close()
        await trace.writer.close()


@pytest.mark.asyncio
async def test_search_reads_and_index_cannot_recover_forgotten_evidence(
    tmp_path, authority_parts
):
    from jarvis.voice.project_memory_tools import ProjectMemoryTools

    trace = await owner_trace(tmp_path, authority_parts)
    try:
        nepal = trace.nepal.selection
        for query in ("SQL window functions", "interview topic", "window"):
            tools = ProjectMemoryTools(
                trace.access,
                selection=nepal,
                request_id="probe",
                is_current=lambda: True,
            )
            found = await tools.search_conversation_memory(nepal.project_id, query)
            assert all(FACT not in s.event.text for s in found.sources)
        redacted = [
            e
            for (e,) in rows(
                trace.path,
                "SELECT event_id FROM conversation_event WHERE text='[forgotten]'",
            )
        ]
        with pytest.raises(PermissionError):
            await trace.access.snapshot(
                nepal, source_ids=(redacted[-1],), project_wide=True, limit=16
            )
        with pytest.raises(PermissionError):
            await trace.access.snapshot(
                nepal,
                source_ids=(redacted[-1],),
                project_wide=True,
                all_projects=True,
                limit=16,
            )
        recent = await trace.access.snapshot(nepal, project_wide=True)
        assert all(s.event.text != "[forgotten]" for s in recent.sources)
        assert not rows(
            trace.path,
            "SELECT rowid FROM conversation_event_fts WHERE conversation_event_fts MATCH ?",
            ('"window"*',),
        )
        segments = b"".join(
            r[0]
            for r in rows(trace.path, "SELECT block FROM conversation_event_fts_data")
            if isinstance(r[0], bytes)
        )
        assert b"window" not in segments
        assert not rows(
            trace.path,
            "SELECT 1 FROM conversation_event_dependency d JOIN conversation_event e "
            "ON e.event_id=d.event_id WHERE e.text='[forgotten]'",
        )
    finally:
        await trace.reader.close()
        await trace.writer.close()


@pytest.mark.asyncio
async def test_late_reply_built_on_forgotten_evidence_is_refused(
    tmp_path, authority_parts
):
    """A reply prepared before forget but delivered after it is not saved."""
    path, store, _, _, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    provider = ProjectAnswerProvider(EchoingModel())
    coordinator = ProjectConversationCoordinator(
        access, source_clearance=lambda _: True
    )
    try:
        await say(coordinator, provider, "create project called interview preparation")
        await say(coordinator, provider, f"My interview topic is {FACT}.")
        await say(coordinator, provider, "Switch to the trip")
        conversation = ConversationSession()
        conversation.start()
        turn = conversation.accept_turn(
            ConversationRole.USER, "What is my interview topic?"
        )
        pending = await coordinator.respond(
            conversation, turn, provider=provider, authorize=lambda: True
        )
        assert FACT in pending.answer
        catalog = await access.catalog()
        interview = next(
            e for e in catalog.entries if e.title == "interview preparation"
        )
        controls = ProjectControls(access)
        inspected = await controls.inspect_project(interview.selection.project_id)
        await controls.forget_project(
            interview.selection.project_id,
            expected_revision=inspected.archive_revision,
        )
        with pytest.raises(PermissionError):
            await coordinator.record_assistant(
                conversation, pending, delivered_text=pending.answer
            )
        assert not rows(
            path, "SELECT 1 FROM conversation_event WHERE text LIKE ?", (f"%{FACT}%",)
        )
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_unrelated_replies_and_independent_owner_statements_survive(
    tmp_path, authority_parts
):
    trace = await owner_trace(tmp_path, authority_parts)
    try:
        await say(trace.coordinator, trace.provider, "Switch to the trip")
        # The owner states the fact again, independently, in Nepal. That is
        # new owner evidence and is kept; deletion is not retroactive here.
        await say(
            trace.coordinator,
            trace.provider,
            f"Reminder: my interview topic is {FACT}.",
        )
        kept = rows(
            trace.path,
            "SELECT e.role FROM conversation_event e JOIN conversation_thread t "
            "ON t.thread_id=e.thread_id WHERE t.project_id=? AND e.text LIKE ?",
            (trace.nepal.selection.project_id, f"%{FACT}%"),
        )
        assert ("user",) in kept
        # Replies made before the other project ever existed are unaffected.
        early = rows(
            trace.path,
            "SELECT e.text FROM conversation_event e JOIN conversation_thread t "
            "ON t.thread_id=e.thread_id WHERE t.project_id=? AND e.role='assistant'",
            (trace.nepal.selection.project_id,),
        )
        assert ("Understood.",) in early
    finally:
        await trace.reader.close()
        await trace.writer.close()


@pytest.mark.asyncio
async def test_second_order_quotes_are_also_removed(tmp_path, authority_parts):
    """Nepal quotes Interview; General quotes Nepal's reply. Both go on forget."""
    trace = await owner_trace(tmp_path, authority_parts)
    try:
        # Rebuild the chain: fact -> Nepal reply -> reply in a third project.
        await say(
            trace.coordinator,
            trace.provider,
            "create project called interview preparation",
        )
        await say(trace.coordinator, trace.provider, f"My interview topic is {FACT}.")
        await say(trace.coordinator, trace.provider, "Switch to the trip")
        await say(trace.coordinator, trace.provider, "What is my interview topic?")
        await say(
            trace.coordinator, trace.provider, "create project called weekend chores"
        )
        third = await say(
            trace.coordinator, trace.provider, "What is my interview topic?"
        )
        assert FACT in third.answer  # quoted from Nepal's reply (or the source)
        catalog = await trace.access.catalog()
        interview = next(
            e for e in catalog.entries if e.title == "interview preparation"
        )
        inspected = await trace.controls.inspect_project(interview.selection.project_id)
        await trace.controls.forget_project(
            interview.selection.project_id,
            expected_revision=inspected.archive_revision,
        )
        assert not rows(
            trace.path,
            "SELECT 1 FROM conversation_event WHERE text LIKE ?",
            (f"%{FACT}%",),
        )
    finally:
        await trace.reader.close()
        await trace.writer.close()


@pytest.mark.asyncio
async def test_untracked_legacy_replies_after_the_project_began_are_removed(
    tmp_path, authority_parts
):
    """Databases from before provenance tracking have no evidence edges."""
    path, store, _, _, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    provider = ProjectAnswerProvider(EchoingModel())
    coordinator = ProjectConversationCoordinator(
        access, source_clearance=lambda _: True
    )
    try:
        await say(coordinator, provider, "Let's plan my Nepal trip")
        await say(coordinator, provider, "create project called interview preparation")
        await say(coordinator, provider, f"My interview topic is {FACT}.")
        await say(coordinator, provider, "Switch to the trip")
        await say(coordinator, provider, "What is my interview topic?")
        # Make the database look like one written before migration 0007.
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE conversation_event SET provenance_tracked=0")
            connection.execute("DELETE FROM conversation_event_dependency")
        catalog = await access.catalog()
        interview = next(
            e for e in catalog.entries if e.title == "interview preparation"
        )
        controls = ProjectControls(access)
        inspected = await controls.inspect_project(interview.selection.project_id)
        receipt = await controls.forget_project(
            interview.selection.project_id,
            expected_revision=inspected.archive_revision,
        )
        assert receipt.derived_sources >= 1
        assert not rows(
            path, "SELECT 1 FROM conversation_event WHERE text LIKE ?", (f"%{FACT}%",)
        )
        # The Nepal reply from before Interview preparation existed is kept,
        # as is every owner turn.
        nepal = next(e for e in catalog.entries if e.title == "Nepal trip")
        kept = rows(
            path,
            "SELECT e.role,e.text FROM conversation_event e JOIN conversation_thread t "
            "ON t.thread_id=e.thread_id WHERE t.project_id=? ORDER BY e.sequence",
            (nepal.selection.project_id,),
        )
        assert kept[0] == ("user", "Let's plan my Nepal trip")
        assert kept[1] == ("assistant", "Understood.")
        assert ("user", "What is my interview topic?") in kept
    finally:
        await reader.close()
        await writer.close()


def test_owner_turns_cannot_carry_evidence_and_evidence_is_bound():
    from datetime import UTC, datetime

    from jarvis.memory.project_conversation_store import _event_material
    from jarvis.memory.project_conversations import ConversationEvent

    now = datetime(2026, 11, 2, tzinfo=UTC)
    with pytest.raises(ValueError):
        ConversationEvent("u", "s", "r", "user", "hi", now, evidence=("x",))
    with pytest.raises(ValueError):
        ConversationEvent("a", "s", "r", "assistant", "hi", now, evidence=("a",))
    plain = ConversationEvent("a", "s", "r", "assistant", "hi", now)
    cited = ConversationEvent("a", "s", "r", "assistant", "hi", now, evidence=("x",))
    assert "evidence" not in _event_material(plain)
    assert _event_material(cited)["evidence"] == ["x"]


@pytest.mark.asyncio
async def test_tracked_reply_chained_to_an_untracked_reply_is_also_removed(
    tmp_path, authority_parts
):
    """Reviewer finding: legacy R0 quotes the fact; new R1 cites R0."""
    path, store, _, _, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    provider = ProjectAnswerProvider(EchoingModel())
    coordinator = ProjectConversationCoordinator(
        access, source_clearance=lambda _: True
    )
    try:
        await say(coordinator, provider, "create project called interview preparation")
        await say(coordinator, provider, f"My interview topic is {FACT}.")
        await say(coordinator, provider, "Switch to the trip")
        await say(coordinator, provider, "What is my interview topic?")
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE conversation_event SET provenance_tracked=0")
            connection.execute("DELETE FROM conversation_event_dependency")
        # After the upgrade: a tracked reply whose evidence is the legacy reply.
        chained = await say(coordinator, provider, "Remind me of my interview topic?")
        assert FACT in chained.answer
        catalog = await access.catalog()
        interview = next(
            e for e in catalog.entries if e.title == "interview preparation"
        )
        controls = ProjectControls(access)
        inspected = await controls.inspect_project(interview.selection.project_id)
        await controls.forget_project(
            interview.selection.project_id,
            expected_revision=inspected.archive_revision,
        )
        assert not rows(
            path, "SELECT 1 FROM conversation_event WHERE text LIKE ?", (f"%{FACT}%",)
        )
        assert not rows(
            path,
            "SELECT 1 FROM conversation_event_dependency d JOIN conversation_event e "
            "ON e.event_id=d.event_id WHERE e.payload_sha256=?",
            ("0" * 64,),
        )
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_approval_is_bound_to_the_derived_replies_it_listed(
    tmp_path, authority_parts
):
    """If the derived set changes while Hello is open, nothing is deleted."""
    trace_path, store, _, _, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    provider = ProjectAnswerProvider(EchoingModel())
    coordinator = ProjectConversationCoordinator(
        access, source_clearance=lambda _: True
    )
    try:
        await say(coordinator, provider, "Let's plan my Nepal trip")
        await say(coordinator, provider, "create project called interview preparation")
        await say(coordinator, provider, f"My interview topic is {FACT}.")
        await say(coordinator, provider, "Switch to the trip")
        await say(coordinator, provider, "What is my interview topic?")
        catalog = await access.catalog()
        interview = next(
            e for e in catalog.entries if e.title == "interview preparation"
        )
        controls = ProjectControls(access)
        preview = await controls.preview_forget(interview.selection.project_id)
        assert preview.derived_sources >= 1
        assert preview.affected_projects == ("Nepal trip",)
        original = issuer.authorize_project_deletion
        seen = {}

        def approve_while_history_changes(material):
            seen.update(material)
            handle = original(material)
            # A previously unrelated Nepal reply gains evidence from Interview.
            with sqlite3.connect(trace_path) as connection:
                unrelated = connection.execute(
                    "SELECT e.event_id FROM conversation_event e JOIN conversation_thread t "
                    "ON t.thread_id=e.thread_id WHERE t.project_id=? AND e.role='assistant' "
                    "ORDER BY e.sequence LIMIT 1",
                    (catalog.current.project_id,),
                ).fetchone()[0]
                source = connection.execute(
                    "SELECT event_id FROM conversation_event WHERE thread_id=? LIMIT 1",
                    (interview.selection.thread_id,),
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO conversation_event_dependency VALUES (?,?)",
                    (unrelated, source),
                )
            return handle

        issuer.authorize_project_deletion = approve_while_history_changes
        inspected = await controls.inspect_project(interview.selection.project_id)
        with pytest.raises(PermissionError, match="derived history changed"):
            await controls.forget_project(
                interview.selection.project_id,
                expected_revision=inspected.archive_revision,
            )
        assert seen["derived_count"] == preview.derived_sources
        assert rows(
            trace_path,
            "SELECT 1 FROM conversation_event WHERE text LIKE ?",
            (f"%{FACT}%",),
        )
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_one_cross_project_recall_does_not_taint_later_unrelated_replies(
    tmp_path, authority_parts
):
    """Reviewer finding: removal must stay at direct dependants."""
    path, store, _, _, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    model = EchoingModel()
    provider = ProjectAnswerProvider(model)
    coordinator = ProjectConversationCoordinator(
        access, source_clearance=lambda _: True
    )
    try:
        await say(coordinator, provider, "create project called interview preparation")
        await say(coordinator, provider, f"My interview topic is {FACT}.")
        await say(coordinator, provider, "Switch to the trip")
        await say(coordinator, provider, "What is my interview topic?")
        for index in range(10):
            await say(coordinator, provider, f"Packing note {index}: bring a jacket.")
        # The recall reply is never fed back into Nepal's later context.
        assert all(FACT not in json.dumps(c) for c in model.contexts[-10:])
        catalog = await access.catalog()
        interview = next(
            e for e in catalog.entries if e.title == "interview preparation"
        )
        controls = ProjectControls(access)
        inspected = await controls.inspect_project(interview.selection.project_id)
        receipt = await controls.forget_project(
            interview.selection.project_id,
            expected_revision=inspected.archive_revision,
        )
        # Only the recall reply is derived. "interview" now names the
        # "interview preparation" project directly (distinctive-word
        # reference), so its rows arrive as labelled evidence and no separate
        # search-result row is produced. Later unrelated replies stay intact.
        assert receipt.derived_sources == 1
        replies = rows(
            path,
            "SELECT e.text FROM conversation_event e JOIN conversation_thread t "
            "ON t.thread_id=e.thread_id JOIN conversation_workspace w "
            "ON w.project_id=t.project_id WHERE w.title='Nepal trip' AND e.role='assistant'",
        )
        assert replies.count(("Understood.",)) == 11
        assert not rows(
            path, "SELECT 1 FROM conversation_event WHERE text LIKE ?", (f"%{FACT}%",)
        )
    finally:
        await reader.close()
        await writer.close()
