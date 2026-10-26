from dataclasses import replace
from types import SimpleNamespace

import pytest
from google.genai.errors import APIError
from livekit.agents import Agent, UserInputTranscribedEvent
from tests.gemini_fallback.live_helpers import ProviderModel
from tests.gemini_fallback.test_hands_memory import shared
from tests.gemini_live.helpers import SyntheticPlayback

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationStatus
from jarvis.model_routing.gemini import GeminiFallbackConfig
from jarvis.voice.livekit_session import create_voice_session


def test_budget_switch_is_explicit_and_machine_configurable():
    assert GeminiFallbackConfig().budget_enforced is True
    config = GeminiFallbackConfig.from_settings(
        {
            "JARVIS_GEMINI_PAID_FALLBACK_ENABLED": "true",
            "JARVIS_GEMINI_PAID_BUDGET_ENABLED": "false",
        }
    )
    assert config.enabled and config.budget_enforced is False
    with pytest.raises(ValueError):
        GeminiFallbackConfig.from_settings(
            {"JARVIS_GEMINI_PAID_BUDGET_ENABLED": "maybe"}
        )


async def voice_environment(tmp_path, monkeypatch):
    runtime, env = shared(tmp_path, monkeypatch, {})
    runtime.config = replace(runtime.config, budget_enforced=False, pricing_path=None)
    runtime.prices.clear()
    raw = []

    def provider(**kwargs):
        m = ProviderModel(
            slot="paid" if kwargs["api_key"] == "paid-private-canary" else "free"
        )
        raw.append(m)
        return m

    monkeypatch.setattr(
        "jarvis.voice.livekit_session.google.realtime.RealtimeModel", provider
    )
    config = JarvisConfig(
        ai_provider="gemini",
        gemini_realtime_model="gemini-3.8-live",
        gemini_fallback=runtime.config,
    )
    session, bridge = create_voice_session(config, routing_runtime=runtime)
    session.output.audio = SyntheticPlayback()
    handoff = bridge.gemini_handoff
    bridge.conversation.start()
    handoff.guard = lambda: bridge.conversation.status is ConversationStatus.ACTIVE
    agent = Agent(instructions="Fictional fallback test", llm=handoff.current_model)
    handoff.bind_agent(agent)
    await session.start(agent=agent, record=False)
    session.emit(
        "user_input_transcribed",
        UserInputTranscribedEvent(
            transcript="Say blue", is_final=True, item_id="owner-1"
        ),
    )
    return SimpleNamespace(
        runtime=runtime, h=handoff, session=session, bridge=bridge, raw=raw, env=env
    )


@pytest.mark.asyncio
async def test_voice_quota_switches_without_prices_profile_or_ledger_updates(
    tmp_path, monkeypatch
):
    from jarvis.provider_resilience import classify_provider_failure

    e = await voice_environment(tmp_path, monkeypatch)
    try:
        with e.runtime.store.work_store.extension_transaction() as c:
            c.execute("UPDATE paid_fallback_budgets SET blocked_reason='unknown_usage'")
        before = e.runtime.paid_budget.status()
        conversation = e.bridge.conversation.session_id
        assert await e.h.handle_failure(
            classify_provider_failure(APIError(429, {}), provider="gemini")
        )
        assert e.h.current_target.credential_ref == "JARVIS_GEMINI_PAID_API_KEY"
        assert [m.slot for m in e.raw] == ["free", "paid"]
        assert e.runtime.paid_budget.status() == before
        assert e.bridge.conversation.session_id == conversation
        assert e.h.current_model.state.budget is None
        e.raw[-1].sessions[-1].emit(
            "metrics_collected", SimpleNamespace(input_tokens=517, output_tokens=22)
        )
        assert e.runtime.paid_budget.status() == before
    finally:
        e.h.close()
        await e.session.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 503])
async def test_automatic_mode_does_not_pay_for_nonquota_errors(
    tmp_path, monkeypatch, code
):
    from jarvis.provider_resilience import classify_provider_failure

    e = await voice_environment(tmp_path, monkeypatch)
    try:
        assert not await e.h.handle_failure(
            classify_provider_failure(APIError(code, {}), provider="gemini")
        )
        assert [m.slot for m in e.raw] == ["free"]
    finally:
        e.h.close()
        await e.session.aclose()


@pytest.mark.asyncio
async def test_revoked_context_cannot_open_paid_in_automatic_mode(
    tmp_path, monkeypatch
):
    from jarvis.provider_resilience import classify_provider_failure

    e = await voice_environment(tmp_path, monkeypatch)
    try:
        e.h.guard = lambda: False
        assert not await e.h.handle_failure(
            classify_provider_failure(APIError(429, {}), provider="gemini")
        )
        assert len(e.raw) == 1
    finally:
        e.h.close()
        await e.session.aclose()


@pytest.mark.asyncio
async def test_automatic_voice_returns_to_free_after_cooldown(tmp_path, monkeypatch):
    from jarvis.provider_resilience import classify_provider_failure

    e = await voice_environment(tmp_path, monkeypatch)
    try:
        assert await e.h.handle_failure(
            classify_provider_failure(APIError(429, {}), provider="gemini")
        )
        e.runtime.clock = lambda: 1000
        e.h.router._clock = e.runtime.clock
        assert await e.h.maybe_recover_free()
        assert e.h.current_target.credential_ref == "GOOGLE_API_KEY"
        assert [m.slot for m in e.raw] == ["free", "paid", "free"]
    finally:
        e.h.close()
        await e.session.aclose()


def test_structured_quota_falls_back_without_pricing_or_accounting(
    tmp_path, monkeypatch
):
    from tests.gemini_fallback.test_invocation import environment, invoke

    e = environment(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(429, {})],
            "paid-private-canary": [{"output_text": '{"answer":"blue"}'}],
        },
        pricing_enabled=False,
    )
    e[2].config = replace(e[2].config, budget_enforced=False)
    with e[1].routing_store.work_store.extension_transaction() as c:
        c.execute("UPDATE paid_fallback_budgets SET blocked_reason='unknown_usage'")
    before = e[2].status()
    result = invoke(e)
    assert result.parsed.answer == "blue"
    assert [key for key, _, _ in e[3]] == ["free-private-canary", "paid-private-canary"]
    assert e[2].status() == before


def test_automatic_mode_still_blocks_invalid_paid_key(tmp_path, monkeypatch):
    from tests.gemini_fallback.test_invocation import environment, invoke

    from jarvis.model_routing.invoker import RoutedInferenceFailure

    e = environment(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(429, {})],
            "paid-private-canary": [APIError(401, {})],
        },
        pricing_enabled=False,
    )
    e[2].config = replace(e[2].config, budget_enforced=False)
    with pytest.raises(RoutedInferenceFailure):
        invoke(e)
    assert e[1].routing_store.credential_blocked("JARVIS_GEMINI_PAID_API_KEY")
    assert not e[1].routing_store.credential_blocked("GOOGLE_API_KEY")
