import asyncio

import pytest
from google.genai.errors import APIError
from livekit.agents import (
    Agent,
    AgentSession,
    TurnHandlingOptions,
    UserInputTranscribedEvent,
    llm,
)
from tests.gemini_fallback.live_helpers import ProviderModel
from tests.gemini_fallback.test_hands_memory import shared

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationSession, ConversationStatus
from jarvis.memory.live_context import LiveContext
from jarvis.provider_resilience import (
    ProviderResilienceState,
    classify_provider_failure,
)
from jarvis.voice.livekit_session import LiveKitConversationBridge
from jarvis.voice.provider_resilience import ProviderResilienceSessionObserver


class SyntheticAdmission:
    """Task8 transport-only test; real admission/generation limits belong to Task9."""

    def __init__(self):
        self.prepared = []

    def reserve_transport(self, **kwargs):
        self.prepared.append(kwargs)


async def setup(tmp_path, monkeypatch, *, paid=True, tools=None):
    from jarvis.voice.gemini_handoff import GeminiLiveHandoff
    from jarvis.voice.gemini_transport import (
        GeminiTransportState,
        GuardedGeminiRealtimeModel,
    )

    runtime, _ = shared(tmp_path, monkeypatch, {})
    conversation = ConversationSession()
    conversation.start()
    raw = ProviderModel("free")
    epoch = [0]
    state = GeminiTransportState(epoch=0, current_epoch=lambda: epoch[0])
    model = GuardedGeminiRealtimeModel(raw, state)
    session = AgentSession(
        llm=model, vad=None, turn_handling=TurnHandlingOptions(turn_detection=None)
    )
    bridge = LiveKitConversationBridge(
        session, conversation, LiveContext(max_recent_turns=8), show_transcript=False
    )
    state.current_epoch = lambda: bridge.transport_epoch
    models = []

    def factory(config, *, target, transport_state):
        new = ProviderModel("paid" if ".paid." in target.target_id else "free")
        wrapped = GuardedGeminiRealtimeModel(new, transport_state)
        models.append((target, new, wrapped))
        return wrapped

    admission = SyntheticAdmission() if paid else None

    async def guard():
        return conversation.status is ConversationStatus.ACTIVE

    handoff = GeminiLiveHandoff(
        config=JarvisConfig(ai_provider="gemini"),
        routing_runtime=runtime,
        session=session,
        bridge=bridge,
        current_model=model,
        guard=guard,
        model_factory=factory,
        paid_admission=admission,
        setup_timeout=1,
    )
    agent = Agent(instructions="fictional instructions", llm=model, tools=tools)
    handoff.bind_agent(agent)
    observer = ProviderResilienceSessionObserver(
        session,
        provider="gemini",
        state=ProviderResilienceState(),
        status_speech=None,
        output_getter=lambda: None,
        handoff=handoff,
    )
    await session.start(agent=agent, record=False)
    return session, bridge, raw, handoff, models, admission, observer


@pytest.mark.asyncio
async def test_registered_sdk_error_hands_off_once_without_closing_canonical_session(
    tmp_path, monkeypatch
):
    session, bridge, raw, handoff, models, admission, observer = await setup(
        tmp_path, monkeypatch
    )
    try:
        session.emit(
            "user_input_transcribed",
            UserInputTranscribedEvent(
                transcript="What is two plus two?", is_final=True, item_id="user-1"
            ),
        )
        original = bridge.conversation.turns
        error = llm.RealtimeModelError(
            timestamp=1,
            label="synthetic quota",
            error=APIError(429, {}),
            recoverable=False,
        )
        raw.sessions[0].emit("error", error)
        assert error.recoverable
        await asyncio.wait_for(handoff.task, 2)
        assert handoff.current_target.credential_ref == "JARVIS_GEMINI_PAID_API_KEY"
        assert len(models) == 1
        assert len(admission.prepared) == 1
        assert bridge.conversation.status is ConversationStatus.ACTIVE
        assert bridge.conversation.turns == original
        assert observer.terminal_task is None
        assert [
            m.text_content
            for m in session.current_agent.chat_ctx.messages()
            if m.role == "user"
        ] == ["What is two plus two?"]
        await asyncio.wait_for(models[0][1].sessions[0].reply_started.wait(), 1)
        assert models[0][1].sessions[0].replies == 1
        raw.sessions[0].emit("error", error)
        assert len(models) == 1
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
async def test_task8_cannot_activate_paid_without_bounded_admission(
    tmp_path, monkeypatch
):
    session, _, _, handoff, models, _, _ = await setup(
        tmp_path, monkeypatch, paid=False
    )
    try:
        assert not await handoff.handle_failure(
            classify_provider_failure(APIError(429, {}), provider="gemini")
        )
        assert models == []
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 503])
async def test_nonquota_live_error_does_not_create_paid_hop(
    tmp_path, monkeypatch, status
):
    session, _, _, handoff, models, _, _ = await setup(tmp_path, monkeypatch)
    try:
        assert not await handoff.handle_failure(
            classify_provider_failure(APIError(status, {}), provider="gemini")
        )
        assert models == []
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
async def test_partial_output_does_not_replay_last_question(tmp_path, monkeypatch):
    session, bridge, _, handoff, models, _, _ = await setup(tmp_path, monkeypatch)
    try:
        session.emit(
            "user_input_transcribed",
            UserInputTranscribedEvent(transcript="fictional question", is_final=True),
        )
        handoff.note_output_delivered()
        assert await handoff.handle_failure(
            classify_provider_failure(APIError(429, {}), provider="gemini")
        )
        assert models[0][1].sessions[0].replies == 0
        assert bridge.conversation.status is ConversationStatus.ACTIVE
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
async def test_pending_tool_prevents_handoff_and_reexecution(tmp_path, monkeypatch):
    from livekit.agents.voice.events import ToolCallStarted, ToolExecutionUpdatedEvent

    session, _, _, handoff, models, _, _ = await setup(tmp_path, monkeypatch)
    try:
        session.emit(
            "tool_execution_updated",
            ToolExecutionUpdatedEvent(
                update=ToolCallStarted(
                    function_call=llm.FunctionCall(
                        id="pending", call_id="pending", name="send", arguments="{}"
                    )
                )
            ),
        )
        assert not await handoff.handle_failure(
            classify_provider_failure(APIError(429, {}), provider="gemini")
        )
        assert models == []
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
async def test_pinned_sdk_requires_update_agent_for_running_realtime_model(
    tmp_path, monkeypatch
):
    session, _, _, handoff, _, _, _ = await setup(tmp_path, monkeypatch)
    try:
        original = session.current_agent.llm
        with pytest.raises(RuntimeError, match="RealtimeModel"):
            session.current_agent.update_options(llm=ProviderModel("paid"))
        assert session.current_agent.llm is original
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
async def test_explicit_paid_model_factory_requires_live_admission(
    tmp_path, monkeypatch
):
    from jarvis.model_routing.budget import PaidBudgetDenied
    from jarvis.voice.livekit_session import _create_realtime_model

    session, _, _, handoff, _, _, _ = await setup(tmp_path, monkeypatch)
    try:
        paid = next(
            t
            for t in handoff.router.target_registry.all()
            if t.credential_ref == "JARVIS_GEMINI_PAID_API_KEY"
        )
        with pytest.raises(PaidBudgetDenied):
            _create_realtime_model(handoff.config, target=paid)
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
async def test_completed_tool_keeps_receipt_and_instance_without_reexecuting(
    tmp_path, monkeypatch
):
    from tests.gemini_fallback.live_helpers import empty_stream

    calls = []
    finished = asyncio.Event()

    @llm.function_tool
    async def bounded_action() -> str:
        """Perform one fictional bounded action."""
        calls.append("executed")
        return "private-tool-result-canary"

    session, bridge, raw, handoff, models, _, _ = await setup(
        tmp_path, monkeypatch, tools=[bounded_action]
    )
    session.on("function_tools_executed", lambda _: finished.set())
    try:
        session.emit(
            "user_input_transcribed",
            UserInputTranscribedEvent(
                transcript="Perform the fictional bounded action", is_final=True
            ),
        )

        async def functions():
            yield llm.FunctionCall(
                id="function-1",
                call_id="action-1",
                name="bounded_action",
                arguments="{}",
            )

        raw.sessions[0].emit(
            "generation_created",
            llm.GenerationCreatedEvent(
                message_stream=empty_stream(),
                function_stream=functions(),
                user_initiated=False,
            ),
        )
        await asyncio.wait_for(finished.wait(), 2)
        assert calls == ["executed"]
        assert await handoff.handle_failure(
            classify_provider_failure(APIError(429, {}), provider="gemini")
        )
        assert calls == ["executed"]
        assert models[0][1].sessions[0].replies == 0
        assert session.current_agent.tools[0] is bounded_action
        context = session.current_agent.chat_ctx
        assert all(not isinstance(item, llm.FunctionCall) for item in context.items)
        original_turns = bridge.conversation.turns
        from livekit.agents import ConversationItemAddedEvent

        for item in context.messages():
            session.emit(
                "conversation_item_added", ConversationItemAddedEvent(item=item)
            )
        assert bridge.conversation.turns == original_turns
        restored = " ".join(m.text_content for m in context.messages())
        assert "action-1" in restored
        assert "private-tool-result-canary" not in restored
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
async def test_paid_setup_failure_has_one_bounded_attempt_and_sanitized_status(
    tmp_path, monkeypatch
):
    session, _, _, handoff, _models, admission, _ = await setup(tmp_path, monkeypatch)
    count = []

    def unavailable(*args, **kwargs):
        count.append(True)
        raise RuntimeError("private-provider-setup-canary")

    handoff.model_factory = unavailable
    try:
        assert not await handoff.handle_failure(
            classify_provider_failure(APIError(429, {}), provider="gemini")
        )
        assert count == [True]
        assert len(admission.prepared) == 1
        assert "private-provider-setup-canary" not in handoff.last_reason
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
async def test_missing_paid_credential_closes_safely_after_claimed_quota_event(
    tmp_path, monkeypatch
):
    session, bridge, raw, handoff, models, _, _ = await setup(tmp_path, monkeypatch)
    monkeypatch.delenv("JARVIS_GEMINI_PAID_API_KEY")
    try:
        raw.sessions[0].emit(
            "error",
            llm.RealtimeModelError(
                timestamp=1, label="quota", error=APIError(429, {}), recoverable=False
            ),
        )
        await asyncio.wait_for(handoff.task, 2)
        assert models == []
        assert bridge.conversation.status is not ConversationStatus.ACTIVE
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
async def test_guard_failure_closes_claimed_handoff_without_provider_body(
    tmp_path, monkeypatch
):
    session, bridge, raw, handoff, models, _, _ = await setup(tmp_path, monkeypatch)

    async def denied():
        raise RuntimeError("private-continuity-canary")

    handoff.guard = denied
    try:
        raw.sessions[0].emit(
            "error",
            llm.RealtimeModelError(
                timestamp=1, label="quota", error=APIError(429, {}), recoverable=False
            ),
        )
        await asyncio.wait_for(handoff.task, 2)
        assert models == []
        assert bridge.conversation.status is not ConversationStatus.ACTIVE
        assert "private-continuity-canary" not in handoff.last_reason
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,message",
    [
        (1011, "Internal error encountered"),
        (
            1008,
            "BidiGenerateContent session is already connected to an existing client",
        ),
    ],
)
async def test_voice_disconnect_gets_one_fresh_same_key_session_without_replay(
    tmp_path, monkeypatch, code, message
):
    session, bridge, raw, handoff, models, _, observer = await setup(
        tmp_path, monkeypatch, paid=False
    )
    try:
        session.emit(
            "user_input_transcribed",
            UserInputTranscribedEvent(
                transcript="Remember both bikes", is_final=True, item_id="bike-turn"
            ),
        )
        original = bridge.conversation.turns
        handoff._completed_tools = True
        error = llm.RealtimeModelError(
            timestamp=1,
            label="disconnect",
            error=APIError(code, {"message": message}),
            recoverable=False,
        )
        raw.sessions[0].emit("error", error)
        assert error.recoverable
        await asyncio.wait_for(handoff.task, 3)
        assert len(models) == 1
        assert models[0][0].credential_ref == "GOOGLE_API_KEY"
        assert raw.sessions[0].closed
        assert models[0][1].sessions[0].replies == 0
        assert bridge.conversation.turns == original
        assert bridge.conversation.status is ConversationStatus.ACTIVE
        assert observer.terminal_task is None
        assert "Remember both bikes" in [
            m.text_content for m in session.current_agent.chat_ctx.messages()
        ]
        task = handoff.task
        models[0][1].sessions[0].emit(
            "error",
            llm.RealtimeModelError(
                timestamp=2,
                label="again",
                error=APIError(code, {"message": message}),
                recoverable=False,
            ),
        )
        assert handoff.task is task
        assert len(models) == 1
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
async def test_disconnect_recovery_does_not_cross_pending_tool_or_authority_boundary(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    session, _, _, handoff, models, _, _ = await setup(
        tmp_path, monkeypatch, paid=False
    )
    try:
        for message in [
            "unrelated policy violation",
            "BidiGenerateContent session is already connected to an existing client",
        ]:
            handoff._pending_tools.add("in-flight")
            event = SimpleNamespace(
                source=handoff.current_model,
                error=llm.RealtimeModelError(
                    timestamp=1,
                    label="policy",
                    error=APIError(1008, {"message": message}),
                    recoverable=False,
                ),
            )
            assert not handoff.try_handle_event(event)
        handoff._pending_tools.clear()
        event.error.error = APIError(1008, {"message": "unrelated policy violation"})
        assert not handoff.try_handle_event(event)
        event.error.error = APIError(1011, {"message": "Internal error encountered"})
        handoff.guard = lambda: False
        assert handoff.try_handle_event(event)
        await asyncio.wait_for(handoff.task, 3)
        assert not models
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
async def test_initial_routed_voice_transport_disables_sdk_reconnect(
    tmp_path, monkeypatch
):
    from jarvis.voice.livekit_session import create_voice_session

    runtime, _ = shared(tmp_path, monkeypatch, {})
    options = []

    def model(**kwargs):
        options.append(kwargs)
        return ProviderModel()

    monkeypatch.setattr(
        "jarvis.voice.livekit_session.google.realtime.RealtimeModel", model
    )
    monkeypatch.setattr("livekit.agents.inference.VAD", lambda **_: None)
    session, bridge = create_voice_session(
        JarvisConfig(ai_provider="gemini"), routing_runtime=runtime
    )
    try:
        assert options[0]["conn_options"].max_retry == 0
    finally:
        bridge.gemini_handoff.close()
        await session.aclose()


@pytest.mark.asyncio
async def test_fresh_recovery_preserves_paid_target_and_admission(
    tmp_path, monkeypatch
):
    session, _, raw, handoff, models, admission, _ = await setup(tmp_path, monkeypatch)
    try:
        paid = next(
            t
            for t in handoff.router.target_registry.all()
            if t.credential_ref == "JARVIS_GEMINI_PAID_API_KEY"
        )
        handoff.current_target = paid
        raw.sessions[0].emit(
            "error",
            llm.RealtimeModelError(
                timestamp=1,
                label="disconnect",
                error=APIError(1011, {"message": "Internal error encountered"}),
                recoverable=False,
            ),
        )
        await asyncio.wait_for(handoff.task, 3)
        assert len(models) == 1
        assert models[0][0] is paid
        assert len(admission.prepared) == 1
        assert models[0][1].sessions[0].replies == 0
    finally:
        handoff.close()
        await session.aclose()


@pytest.mark.asyncio
async def test_fresh_recovery_closes_conversation_if_physical_teardown_fails(
    tmp_path, monkeypatch
):
    from unittest.mock import AsyncMock

    session, _, raw, handoff, models, _, _ = await setup(
        tmp_path, monkeypatch, paid=False
    )
    try:
        raw.sessions[0].aclose = AsyncMock(side_effect=[TimeoutError, None, None])
        raw.sessions[0].emit(
            "error",
            llm.RealtimeModelError(
                timestamp=1,
                label="disconnect",
                error=APIError(1011, {"message": "Internal error encountered"}),
                recoverable=False,
            ),
        )
        await asyncio.wait_for(handoff.task, 3)
        assert not models
        assert handoff.last_reason == "fresh_session_recovery_failed"
    finally:
        raw.sessions[0].aclose = AsyncMock()
        handoff.close()
        await session.aclose()


@pytest.mark.parametrize(
    "code,message",
    [
        (1008, "1011 Internal error encountered"),
        (403, "1011 Internal error encountered"),
        (11011, "Internal error encountered"),
        (1008, "unrelated policy violation"),
    ],
)
def test_fresh_recovery_rejects_conflicting_structured_codes(code, message):
    from jarvis.voice.gemini_handoff import _fresh_session_failure

    error = RuntimeError("wrapped 1011 Internal error encountered")
    error.__cause__ = APIError(code, {"message": message})
    assert not _fresh_session_failure(error)


@pytest.mark.asyncio
async def test_fresh_recovery_bounds_stalled_model_cleanup(tmp_path, monkeypatch):
    session, _, raw, handoff, models, _, _ = await setup(
        tmp_path, monkeypatch, paid=False
    )
    original_close = raw.aclose

    async def stalled():
        await asyncio.Event().wait()

    raw.aclose = stalled
    try:
        raw.sessions[0].emit(
            "error",
            llm.RealtimeModelError(
                timestamp=1,
                label="disconnect",
                error=APIError(1011, {"message": "Internal error encountered"}),
                recoverable=False,
            ),
        )
        await asyncio.wait_for(asyncio.shield(handoff.task), 4)
        assert not models
        assert handoff.last_reason == "fresh_session_recovery_failed"
    finally:
        raw.aclose = original_close
        handoff.close()
        await session.aclose()
