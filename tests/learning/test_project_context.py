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
