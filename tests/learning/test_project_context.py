from test_project_conversation_store import event

from jarvis.memory.project_access import ArchivedSource, ArchiveSnapshot
from jarvis.memory.project_context import build_project_context
from jarvis.memory.project_conversations import ProjectSelection


def test_context_keeps_source_roles_and_marks_omitted_history_with_bounded_estimate():
    selection = ProjectSelection("p", "t", 0)
    snapshot = ArchiveSnapshot(
        selection,
        "Nepal",
        2,
        2,
        (
            ArchivedSource(
                event(text="Consider renting a Jimny", role="assistant"), 1, 1
            ),
            ArchivedSource(event("two", text="The permit is pending"), 2, 2),
        ),
        "complete",
    )
    context, ids, estimate = build_project_context(snapshot)
    assert "assistant" in context and "user" in context
    assert ids == ("turn-1", "two") and 0 < estimate <= 6000
    large = ArchiveSnapshot(
        selection,
        "Nepal",
        1,
        1,
        (ArchivedSource(event(text="x" * 10000), 1, 1),),
        "complete",
    )
    context, ids, estimate = build_project_context(large)
    assert "omitted" in context and estimate <= 6000


def test_large_recent_project_history_reserves_space_for_omission_metadata():
    import json

    selection = ProjectSelection("p", "new-thread", 0)
    sources = tuple(
        ArchivedSource(
            event(f"source-{i:032x}", text=f"Message {i}: " + "x" * 1050),
            i + 1,
            i + 1,
            f"thread-{i % 3}",
        )
        for i in range(32)
    )
    snapshot = ArchiveSnapshot(selection, "Nepal", 1, 1, sources, "complete")
    context, ids, bound = build_project_context(snapshot)
    body = json.loads(context)
    assert 0 < len(ids) < 32
    assert bound <= 6000 and body["coverage"] == "partial"
    assert set(ids).isdisjoint(body["omitted_source_ids"])
    assert set(ids) | set(body["omitted_source_ids"]) == {
        s.event.event_id for s in sources
    }


def test_context_wire_is_compact_without_losing_any_evidence():
    import json

    selection = ProjectSelection("p", "t", 0)
    sources = tuple(
        ArchivedSource(event(f"e-{i}", text="नेपाल permit " + str(i)), i + 1, i + 1)
        for i in range(6)
    )
    snapshot = ArchiveSnapshot(selection, "Nepal", 6, 6, sources, "complete")
    context, ids, bound = build_project_context(snapshot)
    decoded = json.loads(context)
    assert [s["text"] for s in decoded["sources"]] == [s.event.text for s in sources]
    assert len(ids) == 6 and not decoded["omitted_source_ids"]
    spaced = json.dumps(decoded, ensure_ascii=False, sort_keys=True)
    assert len(context.encode()) < len(spaced.encode())
    assert bound == len(context.encode()) + 32 and bound <= 6000


def test_retrieved_user_originals_fit_before_large_assistant_echoes():
    import json

    selection = ProjectSelection("p", "t", 0)
    snapshot = ArchiveSnapshot(selection, "Nepal", 0, 0, (), "partial")
    originals = tuple(
        ArchivedSource(
            event(f"owner-{i}", text="Permit decision " + "x" * 900), i + 1, i + 1
        )
        for i in range(2)
    )
    echoes = tuple(
        ArchivedSource(
            event(
                f"echo-{i}",
                text="Assistant recollection " + "x" * 900,
                role="assistant",
            ),
            i + 3,
            i + 3,
        )
        for i in range(6)
    )
    context, ids, bound = build_project_context(
        snapshot, extra_sources=(*originals, *echoes)
    )
    assert {"owner-0", "owner-1"} <= set(ids)
    assert bound <= 6000 and json.loads(context)["coverage"] == "partial"
