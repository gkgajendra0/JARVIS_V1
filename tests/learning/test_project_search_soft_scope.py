"""FTS5 conversation search, Unicode terms and soft project separation."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest
from test_project_conversation_store import event, setup_store
from test_project_routing import accepted, routed

from jarvis.authority.conversation_history import HistoryActionBinding
from jarvis.memory.migration_runner import (
    MemoryMigrationRunner,
    discover_memory_migrations,
)
from jarvis.memory.project_access import (
    ProjectArchiveAccess,
    conversation_match_expression,
    conversation_search_terms,
)
from jarvis.memory.project_context import build_project_context
from jarvis.memory.project_conversation_store import archive_digest
from jarvis.memory.project_conversations import ProjectSelection
from jarvis.memory.project_routing import ProjectRouter
from jarvis.voice.project_memory_tools import ProjectMemoryTools


def test_search_terms_keep_devanagari_words_whole():
    assert conversation_search_terms("नेपाल ट्रिप का परमिट") == (
        "नेपाल",
        "ट्रिप",
        "का",
        "परमिट",
    )
    assert conversation_search_terms("What did we decide about the Jimny?") == (
        "we",
        "decide",
        "about",
        "jimny",
    )
    assert conversation_search_terms("?? !!") == ()
    expression = conversation_match_expression(("permit", "ok"))
    assert expression == '"permit"* OR "ok"'
    with pytest.raises(ValueError):
        conversation_match_expression(())


def _migrated(connection, count=None):
    migrations = discover_memory_migrations()
    MemoryMigrationRunner(migrations if count is None else migrations[:count]).apply(
        connection
    )


def _insert_event(connection, event_id, text, thread="thread-1"):
    connection.execute(
        "INSERT INTO conversation_event(event_id,thread_id,sequence,revision,segment_id,"
        "request_id,role,text,accepted_at,delivery,payload_sha256) VALUES "
        "(?,?,(SELECT coalesce(max(sequence),0)+1 FROM conversation_event),1,'s','r',"
        "'user',?,'2026-10-30T00:00:00+00:00','complete',?)",
        (event_id, thread, text, "0" * 64),
    )


def _project(connection, project="project-1", thread="thread-1", title="Nepal trip"):
    connection.execute(
        "INSERT INTO conversation_workspace(project_id,title) VALUES (?,?)",
        (project, title),
    )
    connection.execute(
        "INSERT INTO conversation_thread(thread_id,project_id) VALUES (?,?)",
        (thread, project),
    )


def _matches(connection, expression):
    return [
        r[0]
        for r in connection.execute(
            "SELECT e.event_id FROM conversation_event_fts JOIN conversation_event e "
            "ON e.rowid=conversation_event_fts.rowid WHERE conversation_event_fts MATCH ?",
            (expression,),
        )
    ]


def test_upgrade_backfills_existing_history_into_the_index():
    connection = sqlite3.connect(":memory:")
    _migrated(connection, 5)
    _project(connection)
    _insert_event(connection, "old", "The permits are sorted")
    connection.commit()
    _migrated(connection)
    assert _matches(connection, '"permit"*') == ["old"]
    _insert_event(connection, "new", "हम जिम्नी लेंगे")
    assert _matches(connection, '"जिम्नी"*') == ["new"]


def test_forgotten_text_leaves_the_derived_index():
    connection = sqlite3.connect(":memory:")
    _migrated(connection)
    _project(connection)
    _insert_event(connection, "secret", "Jimny salary negotiation")
    connection.execute(
        "CREATE VIRTUAL TABLE temp.vocab USING fts5vocab(main, conversation_event_fts, 'row')"
    )

    def terms():
        return {r[0] for r in connection.execute("SELECT term FROM temp.vocab")}

    assert _matches(connection, '"salary"*') == ["secret"]
    assert {"salari", "jimni"} <= terms()
    # The same statement shape the project forget control uses.
    connection.execute(
        "UPDATE conversation_event SET text='[forgotten]',role='tool',delivery='failed'"
    )
    assert _matches(connection, '"salary"*') == []
    assert not {"salari", "jimni", "negoti"} & terms()
    # Project forget also optimizes, physically rewriting the index segments.
    connection.execute(
        "INSERT INTO conversation_event_fts(conversation_event_fts) VALUES('optimize')"
    )
    segments = b"".join(
        r[0]
        for r in connection.execute("SELECT block FROM conversation_event_fts_data")
        if isinstance(r[0], bytes)
    )
    assert b"salari" not in segments and b"jimni" not in segments
    connection.execute("DELETE FROM conversation_event")
    assert _matches(connection, '"forgotten"') == []
    assert (
        connection.execute(
            "INSERT INTO conversation_event_fts(conversation_event_fts) VALUES('integrity-check')"
        ).fetchall()
        == []
    )


async def _append(store, issuer, grant, selection, value, revision):
    material = store.append_material(selection, value, revision)
    issuer.register_source(grant, value.event_id, source=value)
    permit = issuer.issue_child(
        grant,
        HistoryActionBinding(
            "admit",
            value.event_id,
            archive_digest(material),
            targets=(
                ("project", selection.project_id),
                ("thread", selection.thread_id),
            ),
        ),
    )
    await store.append_event(
        selection, value, permit=permit, expected_revision=revision
    )
    issuer.release_source(grant, value.event_id)


async def _two_projects(tmp_path, authority_parts, *, local_text, foreign_text):
    path, store, selection, _, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    foreign = ProjectSelection("project-interview", "thread-interview", 0)
    await access.create_project(foreign, "Interview preparation")
    await _append(
        store,
        issuer,
        grant,
        selection,
        replace(event("local", text=local_text), request_id="local"),
        0,
    )
    await _append(
        store,
        issuer,
        grant,
        foreign,
        replace(
            event("foreign", text=foreign_text),
            request_id="foreign",
            accepted_at=event().accepted_at + timedelta(seconds=1),
        ),
        0,
    )
    return path, access, selection, writer, reader


@pytest.mark.asyncio
async def test_search_widens_to_other_projects_only_when_selected_has_no_match(
    tmp_path, authority_parts
):
    _, access, selection, writer, reader = await _two_projects(
        tmp_path,
        authority_parts,
        local_text="We will take the Jimny",
        foreign_text="My salary expectation is fixed",
    )
    try:
        tools = ProjectMemoryTools(
            access, selection=selection, request_id="question", is_current=lambda: True
        )
        found = await tools.search_conversation_memory(
            selection.project_id, "What salary did I mention?"
        )
        assert found.status == "other_projects"
        assert [s.event.event_id for s in found.sources] == ["foreign"]
        assert found.sources[0].project_title == "Interview preparation"
        assert found.sources[0].project_id == "project-interview"
        read = await tools.read_conversation_sources(("foreign",))
        assert [s.event.event_id for s in read.sources] == ["foreign"]
        snapshot = await access.snapshot(selection, project_wide=True)
        packet, ids, _ = build_project_context(snapshot, extra_sources=found.sources)
        assert "foreign" in ids
        assert '"from_project":"Interview preparation"' in packet
        # Local rows are never relabelled as coming from another project.
        assert packet.count("from_project") == 1
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_selected_project_match_keeps_other_projects_out(
    tmp_path, authority_parts
):
    _, access, selection, writer, reader = await _two_projects(
        tmp_path,
        authority_parts,
        local_text="We will take the Jimny",
        foreign_text="Interview travel by Jimny",
    )
    try:
        tools = ProjectMemoryTools(
            access, selection=selection, request_id="question", is_current=lambda: True
        )
        found = await tools.search_conversation_memory(selection.project_id, "Jimny")
        assert found.status == "complete"
        assert [s.event.event_id for s in found.sources] == ["local"]
        with pytest.raises(PermissionError):
            await tools.read_conversation_sources(("foreign",))
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_forgotten_projects_never_appear_in_the_wider_search(
    tmp_path, authority_parts
):
    path, access, selection, writer, reader = await _two_projects(
        tmp_path,
        authority_parts,
        local_text="We will take the Jimny",
        foreign_text="My salary expectation is fixed",
    )
    try:
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE conversation_workspace SET forgotten_at='2026-10-31T00:00:00Z' "
                "WHERE project_id='project-interview'"
            )
        tools = ProjectMemoryTools(
            access, selection=selection, request_id="question", is_current=lambda: True
        )
        found = await tools.search_conversation_memory(selection.project_id, "salary")
        assert found.status == "no_match" and found.sources == ()
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_all_project_scope_rejects_unbounded_reads(tmp_path, authority_parts):
    _, store, selection, _, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    try:
        with pytest.raises(ValueError):
            await access.snapshot(selection, all_projects=True)
        with pytest.raises(ValueError):
            await access.snapshot(
                selection, all_projects=True, query="x y", source_ids=("a",)
            )
    finally:
        await reader.close()
        await writer.close()


def test_short_names_select_an_existing_project_but_plan_still_creates(
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
            await routed(router, "create project called interview preparation")
            back = await routed(router, "Switch to the trip")
            assert back.selection == nepal.selection
            assert back.announcement == "Switched to Nepal trip."
            created = await routed(router, "Let's plan a Goa trip")
            assert created.selection.project_id != nepal.selection.project_id
            c, t = accepted("Continue the trip")
            decision = await router.resolve(c, t)
            assert decision.status == "clarification"
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())
