"""Only explicit project commands change the selection or create projects.

Regression for the 2 Nov Windows acceptance failure at 85bd790e: after a
restart, "What is the status of my nepal trip?" created a second project
"nepal trip", switched to it and announced "Selected nepal trip.".
"""

import json
import sqlite3

import pytest
from test_project_forget_provenance import EchoingModel, say
from test_project_routing import accepted, routed

from jarvis.authority.conversation_history import ConversationHistoryAuthority
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.project_access import ProjectArchiveAccess
from jarvis.memory.project_controls import ProjectControls
from jarvis.memory.project_conversation_store import ProjectConversationStore
from jarvis.memory.project_routing import ProjectClarificationRequired, ProjectRouter
from jarvis.memory.worker import SerialConnectionWorker
from jarvis.voice.project_answer_provider import ProjectAnswerProvider
from jarvis.voice.project_conversation import ProjectConversationCoordinator


@pytest.fixture
async def lab(tmp_path, authority_parts):
    """An empty project archive, like a fresh text lab (no seeded projects)."""
    path = tmp_path / "history.db"
    with sqlite3.connect(path) as connection:
        MemoryMigrationRunner().apply(connection)
    writer = SerialConnectionWorker(lambda: sqlite3.connect(path), thread_name="w")
    reader = SerialConnectionWorker(lambda: sqlite3.connect(path), thread_name="r")
    issuer = ConversationHistoryAuthority(authority_parts.broker)
    store = ProjectConversationStore(writer=writer, reader=reader, authority=issuer)

    class Lab:
        runs = 0

        def access(self):
            # A new runtime grant, as each lab start/restart gets.
            Lab.runs += 1
            grant = issuer.open(f"runtime-{Lab.runs}", "gemini")
            return ProjectArchiveAccess(store, authority=issuer, grant=grant)

        def coordinator(self, access):
            return ProjectConversationCoordinator(
                access, source_clearance=lambda _: True
            )

    try:
        yield Lab()
    finally:
        await reader.close()
        await writer.close()


async def live_titles(access):
    catalog = await access.catalog()
    return sorted({e.title for e in catalog.entries})


async def current_title(access):
    catalog = await access.catalog()
    return next(e.title for e in catalog.entries if e.selection == catalog.current)


@pytest.mark.asyncio
async def test_owner_repro_status_question_after_restart_creates_nothing(lab):
    access = lab.access()
    model = EchoingModel()
    provider = ProjectAnswerProvider(model)
    coordinator = lab.coordinator(access)
    created = await say(coordinator, provider, "create a nepal project")
    assert created.announcement == "Created project nepal."
    await say(coordinator, provider, "We will take the Jimny. The permits are sorted.")
    await say(coordinator, provider, "create project called interview preparation")
    await say(coordinator, provider, "My interview topic is SQL window functions.")
    controls = ProjectControls(access)
    catalog = await access.catalog()
    interview = next(e for e in catalog.entries if e.title == "interview preparation")
    inspected = await controls.inspect_project(interview.selection.project_id)
    await controls.forget_project(
        interview.selection.project_id, expected_revision=inspected.archive_revision
    )
    back = await say(coordinator, provider, "switch to nepal")
    assert back.announcement == "Switched to nepal."
    # Restart (-ResumeLab): new grant and coordinator over the same archive.
    access = lab.access()
    coordinator = lab.coordinator(access)
    unknown = await say(coordinator, provider, "What is my interview topic?")
    assert "SQL window functions" not in unknown.answer
    assert unknown.announcement == "Resuming nepal."
    status = await say(coordinator, provider, "What is the status of my nepal trip?")
    assert status.announcement == ""
    assert await current_title(access) == "nepal"
    assert await live_titles(access) == ["nepal"]
    context = model.contexts[-1]
    assert context["project_title"] == "nepal"
    assert context["routing"] == {"action": "continued", "project_title": "nepal"}
    assert "Jimny" in json.dumps(context)
    assert all("from_project" not in row for row in context["sources"])


@pytest.mark.asyncio
async def test_question_about_another_project_reads_it_but_stays(lab):
    access = lab.access()
    model = EchoingModel()
    provider = ProjectAnswerProvider(model)
    coordinator = lab.coordinator(access)
    await say(coordinator, provider, "create project called Nepal")
    await say(coordinator, provider, "We will take the Jimny.")
    await say(coordinator, provider, "create project called Interview")
    await say(coordinator, provider, "My interview is on Monday.")
    asked = await say(coordinator, provider, "What's the status of my Nepal trip?")
    assert asked.announcement == ""
    assert await current_title(access) == "Interview"
    context = model.contexts[-1]
    assert context["project_title"] == "Interview"
    assert context["routing"] == {
        "action": "continued",
        "project_title": "Interview",
        "referenced_projects": ["Nepal"],
    }
    labelled = [r for r in context["sources"] if r.get("from_project") == "Nepal"]
    assert any("Jimny" in r["text"] for r in labelled)
    # The answer is still recorded in Interview, not in Nepal.
    assert asked.packet.selection.project_id == (
        (await access.catalog()).current.project_id
    )


@pytest.mark.asyncio
async def test_question_about_an_unknown_project_stays_and_invents_nothing(lab):
    access = lab.access()
    model = EchoingModel()
    provider = ProjectAnswerProvider(model)
    coordinator = lab.coordinator(access)
    await say(coordinator, provider, "create project called Nepal")
    asked = await say(coordinator, provider, "What is the status of my Tokyo trip?")
    assert asked.announcement == ""
    assert await live_titles(access) == ["Nepal"]
    assert "referenced_projects" not in model.contexts[-1]["routing"]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("What is the status of my nepal trip?", "question"),
        ("What did I decide for the nepal trip?", "question"),
        ("Which vehicle are we taking to nepal?", "question"),
        ("Tell me about nepal", "question"),
        ("switch to nepal", "command"),
        ("continue my nepal trip", "command"),
        ("resume nepal", "command"),
        ("open project nepal", "command"),
    ],
)
@pytest.mark.asyncio
async def test_questions_never_switch_commands_do(lab, text, kind):
    router = ProjectRouter(lab.access())
    nepal = await routed(router, "create project called nepal")
    other = await routed(router, "create project called chores")
    decision = await routed(router, text)
    if kind == "question":
        assert decision.selection == other.selection
        assert decision.references == (nepal.selection,)
        assert decision.announcement == ""
    else:
        assert decision.selection.project_id == nepal.selection.project_id
        assert decision.action == "switched"
        assert decision.announcement == "Switched to nepal."


@pytest.mark.asyncio
async def test_switch_resolves_exact_then_similar_or_asks(lab):
    router = ProjectRouter(lab.access())
    nepal = await routed(router, "create project called nepal")
    await routed(router, "create project called chores")
    # Similar in the other direction: "nepal trip" finds "nepal".
    assert (await routed(router, "switch to nepal trip")).selection == nepal.selection
    for text in ("switch to tokyo", "continue the tokyo plan", "resume tokyo"):
        c, t = accepted(text)
        decision = await router.resolve(c, t)
        assert decision.status == "clarification"
        assert "No project called" in decision.question
    nepal_trip = await routed(router, "create project called nepal trip")
    goa = await routed(router, "create project called goa trip")
    # Exact beats similar.
    assert (await routed(router, "switch to nepal")).selection == nepal.selection
    assert (
        await routed(router, "switch to nepal trip")
    ).selection == nepal_trip.selection
    # "the trip" is similar to two projects: ask.
    c, t = accepted("switch to the trip")
    ambiguous = await router.resolve(c, t)
    assert ambiguous.status == "clarification"
    assert set(ambiguous.candidates) == {
        nepal_trip.selection.project_id,
        goa.selection.project_id,
    }
    assert sorted(await live_titles(router.access)) == [
        "chores",
        "goa trip",
        "nepal",
        "nepal trip",
    ]


@pytest.mark.asyncio
async def test_create_only_when_the_name_is_free_and_plan_never_duplicates(lab):
    router = ProjectRouter(lab.access())
    nepal = await routed(router, "create project called nepal")
    await routed(router, "create project called chores")
    again = await routed(router, "create project called Nepal")
    assert again.selection == nepal.selection and not again.create
    assert again.announcement == "Switched to nepal."
    c, t = accepted("Let's plan my nepal trip")
    plan = await router.resolve(c, t)
    assert plan.status == "clarification"  # "nepal" exists: ask, don't duplicate
    fresh = await routed(router, "Let's plan my Goa trip")
    assert fresh.create and fresh.announcement == "Created project Goa trip."
    assert await live_titles(router.access) == ["Goa trip", "chores", "nepal"]


@pytest.mark.asyncio
async def test_coordinator_asks_instead_of_creating_on_unknown_switch(lab):
    access = lab.access()
    model = EchoingModel()
    provider = ProjectAnswerProvider(model)
    coordinator = lab.coordinator(access)
    await say(coordinator, provider, "create project called nepal")
    calls = len(model.contexts)
    from jarvis.conversation import ConversationRole, ConversationSession

    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, "switch to tokyo")
    with pytest.raises(ProjectClarificationRequired) as raised:
        await coordinator.respond(
            conversation, turn, provider=provider, authorize=lambda: True
        )
    assert "No project called 'tokyo'" in raised.value.question
    assert len(model.contexts) == calls  # the model never ran
    assert await live_titles(access) == ["nepal"]


@pytest.mark.asyncio
async def test_acknowledgments_match_the_committed_action(lab):
    router = ProjectRouter(lab.access())
    created = await routed(router, "create project called nepal")
    assert (created.action, created.announcement) == (
        "created",
        "Created project nepal.",
    )
    same = await routed(router, "switch to nepal")
    assert (same.action, same.announcement) == ("continued", "")
    chat = await routed(router, "We will take the Jimny")
    assert (chat.action, chat.announcement) == ("continued", "")
    await routed(router, "create project called chores")
    switched = await routed(router, "switch to nepal")
    assert (switched.action, switched.announcement) == (
        "switched",
        "Switched to nepal.",
    )
    thread = await routed(router, "New conversation in nepal")
    assert (thread.action, thread.announcement) == (
        "new_thread",
        "New conversation in nepal.",
    )
    restarted = ProjectRouter(lab.access())
    first = await routed(restarted, "Where were we?")
    assert (first.action, first.announcement) == ("resumed", "Resuming nepal.")
    assert first.selection == thread.selection
    second = await routed(restarted, "And the permits?")
    assert (second.action, second.announcement) == ("continued", "")


@pytest.mark.asyncio
async def test_restart_preserves_the_selection_through_questions(lab):
    router = ProjectRouter(lab.access())
    await routed(router, "create project called nepal")
    chores = await routed(router, "create project called chores")
    restarted = ProjectRouter(lab.access())
    for text in (
        "Buy milk tomorrow",
        "What is the status of my nepal trip?",
        "Which vehicle did we pick for nepal?",
    ):
        decision = await routed(restarted, text)
        assert decision.selection == chores.selection
    assert await current_title(restarted.access) == "chores"
