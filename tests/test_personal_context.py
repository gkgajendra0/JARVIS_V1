from __future__ import annotations

import asyncio
import itertools
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.context import Utf8ByteBudgetEstimator
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.personal_context import (
    NativePersonalContextSource,
    PersonalContextRequest,
    PersonalContextSelector,
)
from jarvis.memory.provenance import MemorySource
from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.query_coordinator import MemoryQueryCoordinator
from jarvis.memory.query_plan import (
    MemoryQueryIntent,
    MemoryQueryProposal,
    MemoryTemporalScope,
)
from jarvis.memory.retrieval import SemanticRetrievalService
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker


class Interpreter:
    """Controlled planner only; canonical gates and store stay real."""

    def __init__(self):
        self.started = asyncio.Event()
        self.resume = asyncio.Event()
        self.resume.set()
        self.calls = 0
        self.fail = False

    async def interpret(self, *, text, catalog):
        self.calls += 1
        self.started.set()
        await self.resume.wait()
        if self.fail:
            raise RuntimeError("private value must not appear in diagnostics")
        return MemoryQueryProposal(
            intent=MemoryQueryIntent.EXACT_FACT,
            subject_scope="personal",
            subject="owner",
            predicate="coffee_preference",
            subject_reference="my",
            requested_relation="coffee preference",
            temporal_scope=MemoryTemporalScope.CURRENT,
        )


@pytest_asyncio.fixture
async def lab(tmp_path: Path):
    now = datetime.now(UTC)

    def connect():
        connection = sqlite3.connect(tmp_path / "fictional.db")
        connection.execute("PRAGMA foreign_keys = ON")
        MemoryMigrationRunner(clock=lambda: now).apply(connection)
        return connection

    worker = SerialConnectionWorker(connect, thread_name="personal-context-test")
    counter = itertools.count()
    lifecycle = MemoryLifecycleService(
        worker, clock=lambda: now, assertion_id_factory=lambda: f"fact-{next(counter)}"
    )
    interpreter = Interpreter()
    retrieval = SemanticRetrievalService(worker)
    reader = CanonicalMemoryReader(worker)
    coordinator = MemoryQueryCoordinator(interpreter=interpreter, retrieval=retrieval)
    source = NativePersonalContextSource(
        coordinator=coordinator, retrieval=retrieval, reader=reader
    )
    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(
        ConversationRole.USER, "What is my coffee preference?"
    )
    identity = ["owner"]
    selector = PersonalContextSelector(
        source=source,
        conversation=conversation,
        requester=lambda: identity[0],
        clock=lambda: now,
    )
    request = PersonalContextRequest(
        turn_id=turn.turn_id,
        session_id=conversation.session_id,
        requester="owner",
        utterance=turn.text,
        as_of=now,
        destination="cloud",
        budget_units=2048,
        deadline_ms=1000,
    )

    def provenance(name="source", **overrides):
        return replace(
            MemorySource(
                source_id=name,
                source_class=MemorySourceClass.OWNER_EXPLICIT,
                canonical_ref=f"fictional:{name}",
                observed_at=now,
                created_at=now,
                authority_class=AuthorityClass.OWNER_EXPLICIT,
                sensitivity=Sensitivity.STANDARD,
            ),
            **overrides,
        )

    def draft(value="decaf", **overrides):
        return replace(
            SemanticAssertionDraft(
                subject_scope="personal",
                subject="owner",
                predicate="coffee_preference",
                value_type=ValueType.TEXT,
                value=value,
                normalized_text=f"My coffee preference is {value}.",
                freshness_class=FreshnessClass.CHANGEABLE,
                sensitivity=Sensitivity.STANDARD,
            ),
            **overrides,
        )

    class Lab:
        pass

    state = Lab()
    state.__dict__.update(locals())
    try:
        yield state
    finally:
        selector.set_enabled(False)
        await worker.close()


@pytest.mark.asyncio
async def test_off_is_default_and_reads_nothing(lab):
    packet = await lab.selector.select(lab.request)
    assert packet.status == "abstain"
    assert packet.reason_codes == ("disabled",)
    assert not packet.evidence and lab.interpreter.calls == 0


@pytest.mark.asyncio
async def test_shadow_reads_canonical_fact_with_actual_provenance_and_budget(lab):
    fact = await lab.lifecycle.create(lab.draft(), lab.provenance())
    lab.selector.set_enabled(True)
    packet = await lab.selector.select(lab.request)
    assert packet.status == "ready"
    (evidence,) = packet.evidence
    assert json.loads(evidence.text) == {
        "subject": "owner",
        "predicate": "coffee_preference",
        "value": "decaf",
    }
    assert evidence.source_ids == (fact.source_id,)
    assert evidence.assertion_id == fact.assertion_id
    assert evidence.authority_class is AuthorityClass.OWNER_EXPLICIT
    assert evidence.observed_at == lab.now
    assert evidence.subject == "owner" and evidence.source_version
    assert packet.used_units == Utf8ByteBudgetEstimator().estimate_text(evidence.text)
    assert packet.budget_unit == "utf8_bytes_with_framing"
    assert len(lab.conversation.turns) == 1
    assert await lab.reader.get_current(fact.assertion_id) == fact


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("turn_id", "unaccepted"),
        ("session_id", "elsewhere"),
        ("utterance", "Invent my coffee preference"),
        ("requester", "guest"),
    ],
)
async def test_unbound_request_never_reads_memory(lab, field, value):
    lab.selector.set_enabled(True)
    packet = await lab.selector.select(replace(lab.request, **{field: value}))
    assert packet.status in {"stale_turn", "abstain"}
    assert not packet.evidence and lab.interpreter.calls == 0


@pytest.mark.asyncio
async def test_guest_cannot_self_declare_owner(lab):
    lab.identity[0] = "guest"
    lab.selector.set_enabled(True)
    packet = await lab.selector.select(lab.request)
    assert packet.status == "abstain" and not packet.evidence
    assert lab.interpreter.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "destination,expected", [("cloud", "abstain"), ("local", "ready")]
)
async def test_local_only_fact_obeys_destination(lab, destination, expected):
    await lab.lifecycle.create(
        lab.draft(sensitivity=Sensitivity.LOCAL_ONLY),
        lab.provenance(sensitivity=Sensitivity.LOCAL_ONLY),
    )
    lab.selector.set_enabled(True)
    packet = await lab.selector.select(replace(lab.request, destination=destination))
    assert packet.status == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["correct", "forget", "expire"])
async def test_canonical_change_after_candidate_selection_cannot_release_old_fact(
    lab, operation
):
    fact = await lab.lifecycle.create(lab.draft(), lab.provenance())
    original = lab.source.propose

    async def racing_proposal(request):
        candidate = await original(request)
        if operation == "correct":
            await lab.lifecycle.correct(
                fact.assertion_id, lab.draft("tea"), lab.provenance("changed")
            )
        elif operation == "forget":
            await lab.lifecycle.forget(fact.assertion_id, lab.provenance("forgotten"))
        else:
            await lab.lifecycle.expire(
                fact.assertion_id, lab.provenance("expired"), effective_at=lab.now
            )
        return candidate

    lab.source.propose = racing_proposal
    lab.selector.set_enabled(True)
    packet = await lab.selector.select(lab.request)
    assert packet.status == "abstain" and not packet.evidence
    assert "source_changed" in packet.reason_codes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["time_sensitive", "future", "assistant", "other_subject", "conflict"]
)
async def test_unsupported_or_unreliable_source_cannot_become_owner_fact(lab, kind):
    draft = lab.draft()
    source = lab.provenance()
    if kind == "time_sensitive":
        draft = lab.draft(freshness_class=FreshnessClass.TIME_SENSITIVE)
    elif kind == "future":
        draft = lab.draft(valid_from=lab.now + timedelta(days=1))
    elif kind == "assistant":
        source = lab.provenance(
            source_class=MemorySourceClass.ASSISTANT_OUTPUT,
            authority_class=AuthorityClass.INFERRED,
        )
    elif kind == "other_subject":
        draft = lab.draft(subject="Nila")
    elif kind == "conflict":
        await lab.lifecycle.create(lab.draft("regular"), lab.provenance("second"))
    await lab.lifecycle.create(draft, source)
    lab.selector.set_enabled(True)
    packet = await lab.selector.select(lab.request)
    assert packet.status == "abstain" and not packet.evidence


@pytest.mark.asyncio
async def test_budget_never_truncates_a_fact_into_a_different_meaning(lab):
    await lab.lifecycle.create(lab.draft("decaf, never regular"), lab.provenance())
    lab.selector.set_enabled(True)
    packet = await lab.selector.select(replace(lab.request, budget_units=8))
    assert packet.status == "abstain" and not packet.evidence
    assert packet.used_units == 0 and "budget_exceeded" in packet.reason_codes


@pytest.mark.asyncio
async def test_failure_returns_sanitized_unavailable_without_private_error(lab):
    lab.interpreter.fail = True
    lab.selector.set_enabled(True)
    packet = await lab.selector.select(lab.request)
    assert packet.status == "unavailable" and not packet.evidence
    assert packet.reason_codes == ("source_unavailable",)
    assert "private value" not in repr(packet)


@pytest.mark.asyncio
async def test_deadline_drops_late_context(lab):
    lab.interpreter.resume.clear()
    lab.selector.set_enabled(True)
    packet = await lab.selector.select(replace(lab.request, deadline_ms=10))
    assert packet.status == "unavailable" and not packet.evidence
    assert packet.reason_codes == ("deadline_exceeded",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["new_turn", "reconnect", "closed", "guest", "off", "off_on"]
)
async def test_pending_context_is_discarded_when_binding_changes(lab, change):
    await lab.lifecycle.create(lab.draft(), lab.provenance())
    lab.interpreter.resume.clear()
    lab.selector.set_enabled(True)
    pending = asyncio.create_task(lab.selector.select(lab.request))
    await lab.interpreter.started.wait()
    if change == "new_turn":
        lab.conversation.accept_turn(ConversationRole.USER, "New question")
    elif change == "reconnect":
        lab.selector.reconnect(lab.conversation)
    elif change == "closed":
        lab.conversation.close()
    elif change == "guest":
        lab.identity[0] = "guest"
    else:
        lab.selector.set_enabled(False)
        if change == "off_on":
            lab.selector.set_enabled(True)
    lab.interpreter.resume.set()
    packet = await pending
    assert packet.status in {"stale_turn", "abstain"} and not packet.evidence


@pytest.mark.asyncio
async def test_external_cancellation_propagates_and_cancels_read(lab):
    lab.interpreter.resume.clear()
    lab.selector.set_enabled(True)
    pending = asyncio.create_task(lab.selector.select(lab.request))
    await lab.interpreter.started.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending


@pytest.mark.asyncio
async def test_duplicate_event_does_not_repeat_selection(lab):
    await lab.lifecycle.create(lab.draft(), lab.provenance())
    lab.selector.set_enabled(True)
    first = await lab.selector.select(lab.request)
    duplicate = await lab.selector.select(lab.request)
    assert first.status == "ready"
    assert duplicate.status == "abstain" and not duplicate.evidence
    assert duplicate.reason_codes == ("duplicate_turn",) and lab.interpreter.calls == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("as_of", datetime(2026, 1, 1)),  # noqa: DTZ001 -- Deliberately invalid input.
        ("destination", "internet"),
        ("budget_units", True),
        ("deadline_ms", 0),
    ],
)
def test_invalid_request_fails_before_execution(field, value):
    # Construction has no side effects and does not accept ambiguous time/policy values.
    values = {
        "turn_id": "t",
        "session_id": "s",
        "requester": "owner",
        "utterance": "coffee?",
        "as_of": datetime.now(UTC),
        "destination": "cloud",
        "budget_units": 512,
        "deadline_ms": 100,
    }
    values[field] = value
    with pytest.raises((TypeError, ValueError)):
        PersonalContextRequest(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["core", "verifier"])
async def test_supported_verifier_errors_cannot_log_personal_content(
    lab, caplog, failure
):
    from jarvis.memory.provider_verified_query import (
        ProviderVerifiedMemoryQueryCoordinator,
    )

    class Guard:
        provider_name = "fictional"
        model_name = "controlled"

        async def evaluate(self, **kwargs):
            raise RuntimeError("private value must not appear in diagnostics")

    await lab.lifecycle.create(lab.draft(), lab.provenance())
    lab.interpreter.fail = failure == "core"
    verified = ProviderVerifiedMemoryQueryCoordinator(
        coordinator=lab.coordinator, release_guard=Guard()
    )
    source = NativePersonalContextSource(
        coordinator=verified, retrieval=lab.retrieval, reader=lab.reader
    )
    selector = PersonalContextSelector(
        source=source,
        conversation=lab.conversation,
        requester=lambda: lab.identity[0],
        clock=lambda: lab.now,
    )
    selector.set_enabled(True)
    packet = await selector.select(lab.request)
    assert not packet.evidence
    assert "private value" not in caplog.text
    assert "decaf" not in caplog.text
    selector.set_enabled(False)


@pytest.mark.asyncio
async def test_abandoned_read_prevents_unbounded_requests_on_later_turns(lab):
    release = asyncio.Event()
    finished = asyncio.Event()
    calls = []

    async def stubborn_proposal(request):
        calls.append(request.turn_id)
        try:
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
        finally:
            finished.set()

    lab.source.propose = stubborn_proposal
    lab.selector.set_enabled(True)
    try:
        first = await lab.selector.select(replace(lab.request, deadline_ms=10))
        assert first.reason_codes == ("deadline_exceeded",)
        for number in range(3):
            turn = lab.conversation.accept_turn(
                ConversationRole.USER, f"next question {number}"
            )
            query = replace(
                lab.request, turn_id=turn.turn_id, utterance=turn.text, deadline_ms=10
            )
            packet = await lab.selector.select(query)
            assert packet.status == "unavailable" and not packet.evidence
        assert len(calls) == 1
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=1)


@pytest.mark.asyncio
async def test_late_cancellation_resistant_proposal_does_not_start_more_reads(lab):
    proposed = await lab.lifecycle.create(lab.draft(), lab.provenance())
    release = asyncio.Event()
    finished = asyncio.Event()
    validation_calls = []
    original = lab.source.revalidate

    async def stubborn_proposal(request):
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return proposed

    async def track_validation(*args, **kwargs):
        validation_calls.append(True)
        return await original(*args, **kwargs)

    lab.source.propose = stubborn_proposal
    lab.source.revalidate = track_validation
    lab.selector.set_enabled(True)
    packet = await lab.selector.select(replace(lab.request, deadline_ms=10))
    assert packet.status == "unavailable" and packet.reason_codes == (
        "deadline_exceeded",
    )
    for task in tuple(lab.selector._pending):
        task.add_done_callback(lambda _: finished.set())
    release.set()
    await asyncio.wait_for(finished.wait(), timeout=1)
    assert not validation_calls


@pytest.mark.asyncio
async def test_operational_log_projection_omits_personal_values_and_utterance(lab):
    await lab.lifecycle.create(lab.draft(), lab.provenance())
    lab.selector.set_enabled(True)
    packet = await lab.selector.select(lab.request)
    summary = json.dumps(packet.operational_summary())
    assert packet.status == "ready"
    assert "decaf" not in summary and "coffee" not in summary and "owner" not in summary


@pytest.mark.asyncio
async def test_corrected_fact_is_available_on_new_accepted_turn(lab):
    fact = await lab.lifecycle.create(lab.draft(), lab.provenance())
    await lab.lifecycle.correct(
        fact.assertion_id, lab.draft("tea"), lab.provenance("correction")
    )
    lab.selector.set_enabled(True)
    packet = await lab.selector.select(lab.request)
    assert packet.status == "ready"
    assert json.loads(packet.evidence[0].text)["value"] == "tea"


@pytest.mark.asyncio
async def test_assistant_output_and_false_activity_do_not_replace_accepted_owner_turn(
    lab,
):
    await lab.lifecycle.create(lab.draft(), lab.provenance())
    lab.interpreter.resume.clear()
    lab.selector.set_enabled(True)
    pending = asyncio.create_task(lab.selector.select(lab.request))
    await lab.interpreter.started.wait()
    lab.conversation.begin_user_activity()
    lab.conversation.accept_turn(
        ConversationRole.ASSISTANT, "Saved regular coffee", interrupted=True
    )
    lab.interpreter.resume.set()
    packet = await pending
    assert packet.status == "ready"
    assert json.loads(packet.evidence[0].text)["value"] == "decaf"


@pytest.mark.asyncio
async def test_bridge_shadow_observer_deduplicates_without_mutating_provider_context(
    lab,
):
    from livekit.agents import ConversationItemAddedEvent
    from livekit.agents.llm import ChatMessage

    from jarvis.memory.live_context import LiveContext
    from jarvis.voice.livekit_session import LiveKitConversationBridge

    class ProviderProbe:
        def __init__(self):
            self.handlers = {}
            self.updates = 0

        def on(self, name, callback):
            self.handlers[name] = callback

        async def update_chat_ctx(self, *args, **kwargs):
            self.updates += 1
            raise AssertionError("Shadow must not update the provider")

    await lab.lifecycle.create(lab.draft(), lab.provenance())
    provider = ProviderProbe()
    bridge = LiveKitConversationBridge(
        provider,
        lab.conversation,
        LiveContext(max_recent_turns=8),
        show_transcript=False,
    )
    selections = []

    def observe(turn):
        if turn.role is ConversationRole.USER:
            query = replace(lab.request, turn_id=turn.turn_id, utterance=turn.text)
            selections.append(asyncio.create_task(lab.selector.select(query)))

    bridge.add_accepted_turn_observer(observe)
    lab.selector.set_enabled(True)
    lab.interpreter.resume.clear()
    event = ConversationItemAddedEvent(
        item=ChatMessage(
            id="fictional-event", role="user", content=[lab.request.utterance]
        )
    )
    provider.handlers["conversation_item_added"](event)
    provider.handlers["conversation_item_added"](event)
    await asyncio.wait_for(lab.interpreter.started.wait(), timeout=1)
    # Local simulation permits a reply before context arrives; this is not audio timing.
    provider.handlers["conversation_item_added"](
        ConversationItemAddedEvent(
            item=ChatMessage(
                id="fictional-response",
                role="assistant",
                content=["A response already started"],
                interrupted=True,
            )
        )
    )
    lab.interpreter.resume.set()
    packets = await asyncio.gather(*selections)
    assert len(packets) == 1 and packets[0].status == "ready"
    assert provider.updates == 0
    assert lab.conversation.turns[-1].interrupted
