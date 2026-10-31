import asyncio
from types import SimpleNamespace

import pytest
from test_project_conversation_store import setup_store

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.project_access import ProjectArchiveAccess
from jarvis.voice.project_answer_provider import ProjectAnswerProvider
from jarvis.voice.project_conversation import ProjectConversationCoordinator


class WireBoundary:
    def __init__(self):
        self.calls = []

    async def parse_with_telemetry(self, **kwargs):
        import inspect

        check = kwargs["before_dispatch"]()
        if inspect.isawaitable(check):
            await check
        self.calls.append(kwargs["input_payload"])
        response = kwargs["response_model"](
            response={"answer": "Your Jimny trip has a pending permit."}
        )
        return SimpleNamespace(
            parsed=response,
            usage={"input_tokens": 10, "output_tokens": 10},
            usage_observed=True,
            latency_ms=1,
        )


def test_connected_project_history_reaches_generation_without_save_proposals(
    tmp_path, authority_parts
):
    async def scenario():
        _, store, _, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        coordinator = ProjectConversationCoordinator(
            access, source_clearance=lambda _: True
        )
        provider = ProjectAnswerProvider(WireBoundary())
        conversation = ConversationSession()
        conversation.start()
        try:
            for text in (
                "Let's plan my Nepal trip",
                "We will take the Jimny; the permit is pending",
                "Switch to interview preparation",
                "My interview is on Monday",
                "What is the status of my Nepal trip?",
            ):
                turn = conversation.accept_turn(ConversationRole.USER, text)
                result = await coordinator.respond(
                    conversation, turn, provider=provider, authorize=lambda: True
                )
            payload = provider.client.calls[-1]
            assert (
                "Jimny" in payload["context"]
                and "permit is pending" in payload["context"]
            )
            assert "interview is on Monday" not in payload["context"]
            assert result.packet.source_ids
            old = result.packet
            coordinator.invalidate("sleep")
            assert not coordinator.validate_current(old)
            resumed = ProjectConversationCoordinator(
                access, source_clearance=lambda _: True
            )
            next_segment = ConversationSession()
            next_segment.start()
            turn = next_segment.accept_turn(
                ConversationRole.USER, "What is the status of my Nepal trip?"
            )
            await resumed.respond(
                next_segment, turn, provider=provider, authorize=lambda: True
            )
            assert "Jimny" in provider.client.calls[-1]["context"]
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_correction_during_generation_prevents_answer_release(
    tmp_path, authority_parts
):
    async def scenario():
        _, store, _selection, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        coordinator = ProjectConversationCoordinator(
            access, source_clearance=lambda _: True
        )
        started, finish = asyncio.Event(), asyncio.Event()

        class Delayed(WireBoundary):
            async def parse_with_telemetry(self, **kwargs):
                started.set()
                await finish.wait()
                return await super().parse_with_telemetry(**kwargs)

        conversation = ConversationSession()
        conversation.start()
        turn = conversation.accept_turn(ConversationRole.USER, "Continue my Nepal trip")
        provider = ProjectAnswerProvider(Delayed())
        pending = asyncio.create_task(
            coordinator.respond(
                conversation, turn, provider=provider, authorize=lambda: True
            )
        )
        await started.wait()
        coordinator.invalidate("correction")
        finish.set()
        try:
            with pytest.raises(PermissionError):
                await pending
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_excluded_source_leaves_only_omission_metadata_and_never_reaches_provider(
    tmp_path, authority_parts
):
    async def scenario():
        _, store, _, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        coordinator = ProjectConversationCoordinator(
            access, source_clearance=lambda _: False
        )
        provider = ProjectAnswerProvider(WireBoundary())
        c = ConversationSession()
        c.start()
        t = c.accept_turn(ConversationRole.USER, "Excluded private content")
        try:
            with pytest.raises(PermissionError):
                await coordinator.respond(
                    c, t, provider=provider, authorize=lambda: True
                )
            catalog = await access.catalog()
            snapshot = await access.snapshot(catalog.current)
            assert len(snapshot.sources) == 1
            text = snapshot.sources[0].event.text
            assert "omitted" in text and t.text not in text
            assert snapshot.status == "partial"
            assert provider.client.calls == []
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_excluded_text_cannot_leak_through_a_new_project_name(
    tmp_path, authority_parts
):
    async def scenario():
        _, store, _, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        coordinator = ProjectConversationCoordinator(
            access, source_clearance=lambda _: False
        )
        c = ConversationSession()
        c.start()
        turn = c.accept_turn(ConversationRole.USER, "Plan my password secret123")
        try:
            with pytest.raises(PermissionError):
                await coordinator.prepare_reply(c, turn, authorize=lambda: True)
            catalog = await access.catalog()
            assert all("secret123" not in entry.title for entry in catalog.entries)
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_excluded_delivered_assistant_is_recorded_as_an_omission(
    tmp_path, authority_parts
):
    async def scenario():
        _, store, _, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        coordinator = ProjectConversationCoordinator(
            access, source_clearance=lambda t: t.role is ConversationRole.USER
        )
        c = ConversationSession()
        c.start()
        turn = c.accept_turn(ConversationRole.USER, "Continue my Nepal trip")
        try:
            response = await coordinator.respond(
                c,
                turn,
                provider=ProjectAnswerProvider(WireBoundary()),
                authorize=lambda: True,
            )
            receipt = await coordinator.record_assistant(
                c, response, delivered_text=response.answer
            )
            assert receipt.status == "omitted"
            snapshot = await access.snapshot(response.packet.selection)
            assert snapshot.status == "partial" and snapshot.omissions == 1
            assert response.answer not in str([s.event.text for s in snapshot.sources])
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


@pytest.mark.asyncio
async def test_personal_revocation_at_final_dispatch_guard_prevents_wire_disclosure(
    learning, authority_parts
):
    import inspect

    from jarvis.authority.conversation_history import ConversationHistoryAuthority
    from jarvis.capabilities.discovery import CapabilityResolver
    from jarvis.capabilities.runtime import CapabilityRuntime
    from jarvis.memory.project_conversation_store import ProjectConversationStore
    from jarvis.memory.retrieval import SemanticRetrievalService
    from jarvis.voice.project_memory_lab import build_project_personal_session

    await learning.service.admit_learning(learning.plan, learning.new_permit())
    issuer = ConversationHistoryAuthority(authority_parts.broker)
    grant = issuer.open("project-test", "gemini")
    store = ProjectConversationStore(
        writer=learning.writer, reader=learning.reader, authority=issuer
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    capability = CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=authority_parts.broker,
    )
    sessions = []

    def personal(conversation):
        session = build_project_personal_session(
            conversation,
            SimpleNamespace(retrieval=SemanticRetrievalService(learning.reader)),
            capability,
        )
        sessions.append(session)
        return session

    coordinator = ProjectConversationCoordinator(
        access, source_clearance=lambda _: True, personal_factory=personal
    )

    class LateWire:
        def __init__(self):
            self.calls = 0
            self.disclosed = []

        async def parse_with_telemetry(self, **kwargs):
            self.calls += 1
            if self.calls == 2:
                sessions[-1].close()
            check = kwargs["before_dispatch"]()
            if inspect.isawaitable(check):
                await check
            if self.calls == 1:
                step = kwargs["response_model"](
                    response={
                        "personal_requests": [{"scope_key": "owned_item.vehicle"}]
                    }
                )
            else:
                self.disclosed.append(kwargs["input_payload"])
                step = kwargs["response_model"](
                    response={"answer": "You can use your City."}
                )
            return SimpleNamespace(
                parsed=step, usage={}, usage_observed=False, latency_ms=1
            )

    client = LateWire()
    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, "Which vehicle can I take?")
    try:
        with pytest.raises(PermissionError):
            await coordinator.respond(
                conversation,
                turn,
                provider=ProjectAnswerProvider(client),
                authorize=lambda: True,
            )
        assert client.disclosed == []
    finally:
        for session in sessions:
            session.close()


def test_archive_search_outcome_is_explicit_in_actual_next_generation_payload(
    tmp_path, authority_parts
):
    async def scenario():
        import inspect
        import json

        _, store, _, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        coordinator = ProjectConversationCoordinator(
            access, source_clearance=lambda _: True
        )

        class SearchWire:
            def __init__(self):
                self.calls = []

            async def parse_with_telemetry(self, **kwargs):
                checked = kwargs["before_dispatch"]()
                if inspect.isawaitable(checked):
                    await checked
                self.calls.append(kwargs["input_payload"])
                step = (
                    kwargs["response_model"](response={"search_query": "unobtainium"})
                    if len(self.calls) == 1
                    else kwargs["response_model"](
                        response={"answer": "That was not found in saved context."}
                    )
                )
                return SimpleNamespace(
                    parsed=step, usage={}, usage_observed=False, latency_ms=1
                )

        wire = SearchWire()
        c = ConversationSession()
        c.start()
        turn = c.accept_turn(ConversationRole.USER, "Continue my Nepal trip")
        try:
            await coordinator.respond(
                c, turn, provider=ProjectAnswerProvider(wire), authorize=lambda: True
            )
            context = json.loads(wire.calls[-1]["context"])
            assert (
                "retrieval" in context
                and context["retrieval"][0]["status"] == "no_match"
            )
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_late_delivered_assistant_is_saved_once_in_original_project(
    tmp_path, authority_parts
):
    async def scenario():
        _, store, _, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        coordinator = ProjectConversationCoordinator(
            access, source_clearance=lambda _: True
        )
        c = ConversationSession()
        c.start()
        turn = c.accept_turn(ConversationRole.USER, "Continue my Nepal trip")
        try:
            response = await coordinator.respond(
                c,
                turn,
                provider=ProjectAnswerProvider(WireBoundary()),
                authorize=lambda: True,
            )
            assert coordinator.validate_current(
                response.packet
            )  # delivered while authorized
            other = ConversationSession()
            other.start()
            new = other.accept_turn(
                ConversationRole.USER, "Switch to interview preparation"
            )
            other_packet = await coordinator.prepare_reply(
                other, new, authorize=lambda: True
            )
            receipt = await coordinator.record_assistant(
                c, response, delivered_text=response.answer[:12], interrupted=True
            )
            duplicate = await coordinator.record_assistant(
                c, response, delivered_text=response.answer[:12], interrupted=True
            )
            assert duplicate.event_id == receipt.event_id
            original = await access.snapshot(response.packet.selection)
            assert original.sources[-1].event.delivery == "partial"
            assert original.sources[-1].event.text == response.answer[:12]
            assert all(
                s.event.text != response.answer[:12]
                for s in (await access.snapshot(other_packet.selection)).sources
            )
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


def test_existing_gemini_adapter_serializes_the_prepared_context_in_actual_wire_arguments(
    tmp_path, authority_parts
):
    async def scenario():
        import inspect
        import json

        from jarvis.hands.provider_adapters import GeminiStructuredOutputClient

        _, store, _, _, writer, reader, issuer, grant = await setup_store(
            tmp_path, authority_parts
        )
        wire = []

        class Endpoint:
            async def create(self, **kwargs):
                wire.append(kwargs)
                return SimpleNamespace(
                    output_text=json.dumps(
                        {"response": {"answer": "Saved project sources are available."}}
                    ),
                    usage={"total_input_tokens": 10, "total_output_tokens": 4},
                )

        sdk = GeminiStructuredOutputClient(
            client=SimpleNamespace(aio=SimpleNamespace(interactions=Endpoint())),
            model="configured-test-model",
        )

        class RouterBoundary:
            async def parse_with_telemetry(self, **kwargs):
                check = kwargs["before_dispatch"]()
                if inspect.isawaitable(check):
                    await check
                return await sdk.parse_with_telemetry(
                    **{
                        k: kwargs[k]
                        for k in ("system_prompt", "input_payload", "response_model")
                    }
                )

        access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
        coordinator = ProjectConversationCoordinator(
            access, source_clearance=lambda _: True
        )
        c = ConversationSession()
        c.start()
        turn = c.accept_turn(ConversationRole.USER, "Continue my Nepal trip")
        try:
            response = await coordinator.respond(
                c,
                turn,
                provider=ProjectAnswerProvider(RouterBoundary()),
                authorize=lambda: True,
            )
            sent = json.loads(wire[0]["input"])
            assert sent["context"] == response.packet.context
            assert sent["context_revision"] == response.packet.revision
            assert sent["request_id"] == response.packet.request_id
            assert wire[0]["store"] is False
            assert response.usage[0]["usage"]["input_tokens"] == 10
        finally:
            await reader.close()
            await writer.close()

    asyncio.run(scenario())


@pytest.mark.asyncio
async def test_failure_probe_observes_real_mixed_step_without_losing_saved_user(
    tmp_path, authority_parts
):
    import json
    import runpy
    from pathlib import Path

    probe = runpy.run_path(
        str(Path(__file__).parents[2] / "tools/project_memory_failure_probe.py")
    )
    _, store, _, _, writer, reader, issuer, grant = await setup_store(
        tmp_path, authority_parts
    )
    access = ProjectArchiveAccess(store, authority=issuer, grant=grant)
    coordinator = ProjectConversationCoordinator(
        access, source_clearance=lambda _: True
    )
    rows = []

    class MixedWire(WireBoundary):
        async def parse_with_telemetry(self, **kwargs):
            await kwargs["before_dispatch"]()
            self.calls.append(kwargs["input_payload"])
            return SimpleNamespace(
                parsed=SimpleNamespace(
                    answer="PRIVATE_MODEL_ANSWER",
                    search_query=None,
                    source_ids=["PRIVATE_SOURCE"],
                    personal_requests=[],
                ),
                usage={},
                usage_observed=False,
                latency_ms=1,
            )

    wire = MixedWire()
    c = ConversationSession()
    c.start()
    turn = c.accept_turn(ConversationRole.USER, "What is the status of my Nepal trip?")
    try:
        with (
            probe["trace_calls"](
                ProjectAnswerProvider, ProjectConversationCoordinator, emit=rows.append
            ),
            pytest.raises(ValueError, match="one memory tool or answer"),
        ):
            await coordinator.respond(
                c, turn, provider=ProjectAnswerProvider(wire), authorize=access.current
            )
        assert len(wire.calls) == 1
        error = json.loads(rows[-1].split(" ", 1)[1])
        assert error["reason"] == "mixed_answer_or_tools"
        assert error["frames"][-1]["module"] == "jarvis.voice.project_conversation"
        assert coordinator.stage == "generating"
        catalog = await access.catalog()
        snapshot = await access.snapshot(catalog.current)
        assert [s.event.role for s in snapshot.sources] == ["user"]
        assert snapshot.sources[0].event.text == turn.text
        assert "PRIVATE_" not in "\n".join(rows)
    finally:
        await reader.close()
        await writer.close()
