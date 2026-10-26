from dataclasses import replace

import pytest

from jarvis.config import JarvisConfig
from jarvis.model_routing.budget import PaidBudgetDenied
from jarvis.model_routing.gemini import GeminiFallbackConfig
from jarvis.voice.gemini_transport import GeminiTransportState


def test_default_policy_is_strict_and_operational_selection_does_not_enable_paid():
    assert GeminiFallbackConfig().live_policy_mode == "strict"
    c = GeminiFallbackConfig.from_settings(
        {"JARVIS_GEMINI_PAID_LIVE_POLICY": "operational_v1"}
    )
    assert c.live_policy_mode == "operational_v1" and not c.enabled
    with pytest.raises(ValueError):
        GeminiFallbackConfig(live_policy_mode="anything")


def test_operational_mode_without_receipt_cannot_construct_paid_client(op_env):
    from jarvis.voice.gemini_operational_budget import build_operational_live_admission

    op_env.runtime.config = replace(
        op_env.runtime.config, live_policy_mode="operational_v1"
    )
    with pytest.raises(PaidBudgetDenied, match="qualified"):
        build_operational_live_admission(
            op_env.runtime, session_id="owner", authorize=lambda: True
        )
    assert op_env.governor.status().reserved_inr_minor == 0


@pytest.mark.asyncio
async def test_factory_accepts_typed_operational_model_without_constructing_client(
    op_env, monkeypatch
):
    from jarvis.voice.gemini_operational_budget import OperationalLiveAdmission
    from jarvis.voice.livekit_session import _create_realtime_model

    a = OperationalLiveAdmission(
        op_env.runtime,
        session_id="owner",
        authorize=lambda: True,
        policy=op_env.policy,
        profile=op_env.profile,
    )
    state = GeminiTransportState(
        epoch=0, current_epoch=lambda: 0, authorize=lambda: True, controlled_admission=a
    )
    monkeypatch.setattr(
        "jarvis.voice.livekit_session.genai.Client",
        lambda **_: pytest.fail("early client"),
    )
    m = _create_realtime_model(
        JarvisConfig(ai_provider="gemini", gemini_realtime_model=a.model_id),
        target=op_env.target,
        transport_state=state,
    )
    assert m.inner.admission is a
    await m.aclose()


@pytest.mark.asyncio
async def test_qualified_normal_factory_preserves_original_closed_guard(
    op_env, monkeypatch, tmp_path
):
    from tests.gemini_fallback.live_helpers import ProviderModel
    from tests.gemini_fallback.test_hands_memory import shared

    from jarvis.voice import gemini_operational_budget as module
    from jarvis.voice.livekit_session import create_voice_session

    runtime, _ = shared(tmp_path / "normal", monkeypatch, {})
    runtime.config = replace(runtime.config, live_policy_mode="operational_v1")
    monkeypatch.setattr(
        module,
        "resolve_qualified_live_profile",
        lambda runtime, *, policy: op_env.profile,
    )
    # Test profile matches the accepted versioned production policy except its provenance.
    monkeypatch.setattr(module, "operational_live_policy", lambda: op_env.policy)
    monkeypatch.setenv("GOOGLE_API_KEY", "offline-free")
    monkeypatch.setattr(
        "jarvis.voice.livekit_session.google.realtime.RealtimeModel",
        lambda **_: ProviderModel(),
    )
    session, bridge = create_voice_session(
        JarvisConfig(ai_provider="gemini", gemini_fallback=runtime.config),
        routing_runtime=runtime,
    )
    h = bridge.gemini_handoff
    assert h.runtime is runtime and h.bridge is bridge and h.guard() is False
    assert h.paid_admission.profile is op_env.profile
    assert not await h.paid_admission.authorize()
    await session.aclose()
