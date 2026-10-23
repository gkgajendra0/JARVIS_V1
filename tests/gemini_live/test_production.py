import pytest
from tests.gemini_fallback.live_helpers import ProviderModel
from tests.gemini_live.helpers import Endpoint, context, until
from tests.gemini_live.test_budget import live_env

from jarvis.config import JarvisConfig
from jarvis.model_routing.budget import PaidBudgetDenied
from jarvis.voice.gemini_transport import GeminiTransportState
from jarvis.voice.livekit_session import _create_realtime_model, create_voice_session


@pytest.mark.asyncio
async def test_actual_factory_accepts_only_typed_current_admission_and_resolves_paid_key_lazily(
    tmp_path, monkeypatch
):
    admission, runtime, target, _ = live_env(tmp_path)
    state = GeminiTransportState(
        epoch=0,
        current_epoch=lambda: 0,
        authorize=lambda: True,
        controlled_admission=admission,
    )
    endpoint = Endpoint(runtime)
    keys = []
    monkeypatch.setenv("GOOGLE_API_KEY", "synthetic-free")
    monkeypatch.setenv("JARVIS_GEMINI_PAID_API_KEY", "synthetic-paid")

    def client(*, api_key):
        keys.append(api_key)
        return endpoint.client()

    monkeypatch.setattr("jarvis.voice.livekit_session.genai.Client", client)
    model = _create_realtime_model(
        JarvisConfig(ai_provider="gemini", gemini_realtime_model=target.model_id),
        target=target,
        transport_state=state,
    )
    try:
        assert not keys
        session = model.session(turn_detection_disabled=True)
        await context(session)
        future = session.generate_reply()
        await until(lambda: endpoint.wires)
        assert keys == ["synthetic-paid"]
        future.cancel()
    finally:
        await model.aclose()


def test_arbitrary_legacy_budget_still_cannot_bypass_paid_gate(tmp_path):
    _, _, target, _ = live_env(tmp_path)
    state = GeminiTransportState(epoch=0, current_epoch=lambda: 0, budget=object())
    with pytest.raises(PaidBudgetDenied):
        _create_realtime_model(
            JarvisConfig(ai_provider="gemini"), target=target, transport_state=state
        )


@pytest.mark.asyncio
async def test_normal_voice_factory_shares_router_and_starts_with_closed_original_guard(
    tmp_path, monkeypatch
):
    from tests.gemini_fallback.test_hands_memory import shared

    runtime, _ = shared(tmp_path, monkeypatch, {})
    monkeypatch.setenv("GOOGLE_API_KEY", "synthetic-free")
    monkeypatch.setattr(
        "jarvis.voice.livekit_session.google.realtime.RealtimeModel",
        lambda **_: ProviderModel(),
    )
    config = JarvisConfig(ai_provider="gemini", gemini_fallback=runtime.config)
    session, bridge = create_voice_session(config, routing_runtime=runtime)
    handoff = bridge.gemini_handoff
    assert handoff.runtime is runtime and handoff.session is session
    assert handoff.bridge is bridge and handoff.paid_admission is None
    assert handoff.guard() is False
    assert handoff.current_model.state.current
    assert session is not None
    await session.aclose()
