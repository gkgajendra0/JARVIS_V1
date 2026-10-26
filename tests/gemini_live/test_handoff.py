import asyncio
from types import SimpleNamespace

import pytest
from google.genai.errors import APIError
from livekit.agents import Agent, UserInputTranscribedEvent, llm
from tests.gemini_fallback.live_helpers import ProviderModel
from tests.gemini_fallback.test_hands_memory import shared
from tests.gemini_live.helpers import Endpoint, SyntheticPlayback, until
from tests.gemini_live.test_budget import live_env
from tests.gemini_live.test_contract import raw_usage, synthetic_contract

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationStatus
from jarvis.provider_resilience import ProviderResilienceState
from jarvis.voice.livekit_session import create_voice_session
from jarvis.voice.provider_resilience import ProviderResilienceSessionObserver


async def production(tmp_path, monkeypatch):
    runtime, _ = shared(tmp_path, monkeypatch, {})
    price_root = tmp_path / "price-only"
    price_root.mkdir()
    _, _, _, price = live_env(price_root)
    runtime.prices[("gemini-3.8-live", "live")] = price
    endpoint = Endpoint(runtime)
    raw = []

    def free(**kwargs):
        result = ProviderModel()
        raw.append(result)
        return result

    monkeypatch.setattr(
        "jarvis.voice.livekit_session.google.realtime.RealtimeModel", free
    )
    monkeypatch.setattr(
        "jarvis.voice.gemini_live_contract.reviewed_live_contract",
        lambda _: synthetic_contract(),
    )
    monkeypatch.setattr(
        "jarvis.voice.livekit_session.genai.Client", lambda **_: endpoint.client()
    )
    monkeypatch.setattr("livekit.agents.inference.VAD", lambda **_: None)
    config = JarvisConfig(
        ai_provider="gemini",
        gemini_realtime_model="gemini-3.8-live",
        gemini_fallback=runtime.config,
    )
    session, bridge = create_voice_session(config, routing_runtime=runtime)
    session.output.audio = SyntheticPlayback()
    h = bridge.gemini_handoff
    bridge.conversation.start()
    h.guard = lambda: bridge.conversation.status is ConversationStatus.ACTIVE
    agent = Agent(instructions="Fictional canonical context", llm=h.current_model)
    h.bind_agent(agent)
    observer = ProviderResilienceSessionObserver(
        session,
        provider="gemini",
        state=ProviderResilienceState(),
        status_speech=None,
        output_getter=lambda: None,
        handoff=h,
    )
    await session.start(agent=agent, record=False)
    session.emit(
        "user_input_transcribed",
        UserInputTranscribedEvent(
            transcript="Meri vegetarian preference ke hisaab se suggest karo",
            is_final=True,
            item_id="owner-1",
        ),
    )
    return SimpleNamespace(
        session=session,
        bridge=bridge,
        h=h,
        raw=raw,
        endpoint=endpoint,
        runtime=runtime,
        observer=observer,
    )


@pytest.mark.asyncio
async def test_actual_normal_quota_event_continues_accepted_question_with_same_canonical_owner(
    tmp_path, monkeypatch
):
    env = await production(tmp_path, monkeypatch)
    try:
        original = env.bridge.conversation.turns
        identity = env.bridge.conversation.session_id
        error = llm.RealtimeModelError(
            timestamp=1,
            label="synthetic quota",
            error=APIError(429, {}),
            recoverable=False,
        )
        env.raw[0].sessions[0].emit("error", error)
        await asyncio.wait_for(env.h.task, 5)
        await until(lambda: env.endpoint.wires and len(env.endpoint.wires[0].sent) >= 2)
        assert env.h.current_target.credential_ref == "JARVIS_GEMINI_PAID_API_KEY"
        assert (
            env.bridge.conversation.session_id == identity
            and env.bridge.conversation.turns == original
        )
        assert env.observer.terminal_task is None
        assert env.h.paid_admission.session_id == identity
        assert "vegetarian" in env.endpoint.wires[0].sent[0][1].model_dump_json()
        env.endpoint.wires[0].feed(
            server_content={
                "output_transcription": {"text": "Try a fictional veg meal"},
                "turn_complete": True,
            },
            usage_metadata=raw_usage(),
        )
        await until(lambda: env.endpoint.wires[0].closed)
    finally:
        env.h.close()
        await env.session.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [503, 401])
async def test_nonquota_failure_does_not_open_paid(tmp_path, monkeypatch, code):
    env = await production(tmp_path, monkeypatch)
    try:
        error = llm.RealtimeModelError(
            timestamp=1,
            label="synthetic provider error",
            error=APIError(code, {}),
            recoverable=False,
        )
        env.raw[0].sessions[0].emit("error", error)
        assert env.h.task is None and not env.endpoint.wires
    finally:
        env.h.close()
        await env.session.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [402, 401])
async def test_paid_balance_or_auth_error_blocks_only_paid_credential_and_holds_unknown(
    tmp_path, monkeypatch, code
):
    env = await production(tmp_path, monkeypatch)
    try:
        env.raw[0].sessions[0].emit(
            "error",
            llm.RealtimeModelError(
                timestamp=1, label="quota", error=APIError(429, {}), recoverable=False
            ),
        )
        await asyncio.wait_for(env.h.task, 5)
        await until(lambda: env.endpoint.wires and len(env.endpoint.wires[0].sent) >= 2)
        env.endpoint.wires[0].events.put_nowait(APIError(code, {}))
        await until(
            lambda: env.runtime.store.credential_blocked("JARVIS_GEMINI_PAID_API_KEY")
        )
        assert not env.runtime.store.credential_blocked("GOOGLE_API_KEY")
        assert env.runtime.paid_budget.status().unknown_reservations == 1
        assert env.endpoint.clients == 1
    finally:
        env.h.close()
        await env.session.aclose()
