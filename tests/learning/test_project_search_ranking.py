"""Real archive regressions for relevance without dropping matching corrections."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_project_conversation_store import event, setup_store

from jarvis.authority.conversation_history import HistoryActionBinding
from jarvis.memory.project_access import ProjectArchiveAccess
from jarvis.memory.project_context import build_project_context
from jarvis.memory.project_conversation_store import archive_digest
from jarvis.memory.project_conversations import ProjectSelection
from jarvis.voice.project_memory_tools import ProjectMemoryTools


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["Jimny chose", "Jimny Jimny Jimny chose"])
@pytest.mark.parametrize("padding", [0, 1000])
async def test_specific_old_decision_and_latest_correction_survive_echoes(
    tmp_path, authority_parts, query, padding
):
    _, store, selection, permit, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    values = [
        event("old-choice", text="I chose the Jimny for Nepal."),
        *[event(f"note-{i}", text="Jimny accessory discussion.") for i in range(20)],
        event("correction", text="Correction: the Jimny plan is cancelled."),
        *[
            event(f"echo-{i}", text="I chose the Jimny for Nepal.", role="assistant")
            for i in range(20)
        ],
        event("current-question", text="Which Jimny did I chose?"),
        event("tool-log", text="Jimny chose", role="tool"),
    ]
    try:
        for revision, value in enumerate(values):
            value = replace(
                value,
                accepted_at=value.accepted_at + timedelta(seconds=revision),
                request_id=value.event_id,
                text=value.text + "x" * padding,
            )
            await store.append_event(
                selection,
                value,
                permit=permit(
                    "admit", store.append_material(selection, value, revision), value
                ),
                expected_revision=revision,
            )
            issuer.release_source(grant, value.event_id)
        tools = ProjectMemoryTools(
            access,
            selection=selection,
            request_id="current-question",
            is_current=lambda: True,
        )
        found = await tools.search_conversation_memory(selection.project_id, query)
        ids = {s.event.event_id for s in found.sources}
        assert {"old-choice", "correction"} <= ids
        assert "current-question" not in ids and "tool-log" not in ids
        assert len(found.sources) == 8 and found.status == "partial"
        assert any(s.event.role == "assistant" for s in found.sources)
        assert [s.event.accepted_at for s in found.sources] == sorted(
            s.event.accepted_at for s in found.sources
        )
        snapshot = await access.snapshot(selection, project_wide=True)
        _, packet_ids, bound = build_project_context(
            snapshot, extra_sources=found.sources
        )
        assert {"old-choice", "correction"} <= set(packet_ids)
        assert bound <= 6000
        read = await tools.read_conversation_sources(("old-choice", "correction"))
        assert [s.event.event_id for s in read.sources] == ["old-choice", "correction"]
        _, packet_ids, bound = build_project_context(
            snapshot, extra_sources=(*found.sources, *read.sources)
        )
        assert {"old-choice", "correction"} <= set(packet_ids)
        assert bound <= 6000
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("project_wide", [False, True])
async def test_relevance_does_not_admit_foreign_sources_or_current_request(
    tmp_path, authority_parts, project_wide
):
    _, store, selection, permit, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    foreign = ProjectSelection("foreign-project", "foreign-thread", 0)
    try:
        await access.create_project(foreign, "Interview")
        for revision, value in enumerate(
            [
                event("local", text="Jimny note"),
                event("question", text="Jimny chose Nepal"),
            ]
        ):
            value = replace(value, request_id=value.event_id)
            await store.append_event(
                selection,
                value,
                permit=permit(
                    "admit", store.append_material(selection, value, revision), value
                ),
                expected_revision=revision,
            )
            issuer.release_source(grant, value.event_id)
        value = event("foreign", text="Jimny chose Nepal")
        material = store.append_material(foreign, value, 0)
        issuer.register_source(grant, value.event_id, source=value)
        token = issuer.issue_child(
            grant,
            HistoryActionBinding(
                "admit",
                value.event_id,
                archive_digest(material),
                targets=(
                    ("project", foreign.project_id),
                    ("thread", foreign.thread_id),
                ),
            ),
        )
        await store.append_event(foreign, value, permit=token, expected_revision=0)
        issuer.release_source(grant, value.event_id)
        found = await access.snapshot(
            selection,
            query="Jimny chose Nepal",
            project_wide=project_wide,
            exclude_request_id="question",
        )
        assert [s.event.event_id for s in found.sources] == ["local"]
        assert found.status == "complete"
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_latest_matching_correction_survives_many_more_specific_old_sources(
    tmp_path, authority_parts
):
    _, store, selection, permit, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    try:
        for index in range(22):
            value = replace(
                event(
                    f"row-{index:02d}",
                    text="Correction: Jimny cancelled."
                    if index == 20
                    else "Jimny accessory discussion."
                    if index == 21
                    else "I chose the Jimny for Nepal.",
                ),
                request_id=f"old-{index}",
            )
            value = replace(
                value, accepted_at=value.accepted_at + timedelta(seconds=index)
            )
            await store.append_event(
                selection,
                value,
                permit=permit(
                    "admit", store.append_material(selection, value, index), value
                ),
                expected_revision=index,
            )
            issuer.release_source(grant, value.event_id)
        found = await access.snapshot(
            selection, query="Jimny chose Nepal", project_wide=True, limit=8
        )
        assert len(found.sources) == 8
        assert "Correction: Jimny cancelled." in [s.event.text for s in found.sources]
    finally:
        await reader.close()
        await writer.close()
