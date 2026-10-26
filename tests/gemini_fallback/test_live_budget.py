import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from jarvis.config import JarvisConfig
from jarvis.model_routing.budget import PaidBudgetDenied
from jarvis.voice.livekit_session import _create_realtime_model


def test_installed_live_sdk_has_explicit_pre_dispatch_budget_blocker():
    from jarvis.voice.gemini_budget import GeminiLiveBudget

    budget = GeminiLiveBudget()
    assert not budget.available
    assert budget.reason == "live_transport_bound_unavailable"
    with pytest.raises(PaidBudgetDenied, match="reconnect"):
        budget.reserve_transport(target=None, context=None, instructions="", tools=[])
    assert not budget.allow_input(modality="audio", quantity=1, now_epoch=1)
    with pytest.raises(PaidBudgetDenied):
        budget.before_connect()


@pytest.mark.asyncio
async def test_current_budget_cannot_fund_an_interval_or_convert_missing_usage_to_zero():
    from jarvis.voice.gemini_budget import GeminiLiveBudget

    budget = GeminiLiveBudget()
    with pytest.raises(PaidBudgetDenied):
        await budget.reserve_interval(None)
    with pytest.raises(PaidBudgetDenied):
        budget.observe_usage(
            event_id="missing", usage={}, cumulative=True, complete=False
        )
    budget.close(uncertain=True)
    assert not budget.available


@pytest.mark.asyncio
async def test_real_pinned_sdk_goaway_reconnects_even_with_error_retries_disabled(
    monkeypatch,
):
    # Upstream compatibility characterization: fake only the network client.
    from google.genai import types
    from livekit.agents import APIConnectOptions
    from livekit.plugins.google.realtime import realtime_api

    connected = asyncio.Event()
    counts = []

    class Connection:
        async def close(self):
            pass

        async def receive(self):
            if len(counts) == 1:
                yield types.LiveServerMessage(
                    go_away=types.LiveServerGoAway(time_left="1s")
                )
            await asyncio.Future()

    class Live:
        @asynccontextmanager
        async def connect(self, **kwargs):
            counts.append(kwargs)
            if len(counts) == 2:
                connected.set()
            yield Connection()

    async def close():
        pass

    client = SimpleNamespace(aio=SimpleNamespace(live=Live(), aclose=close))
    monkeypatch.setattr(realtime_api, "GenAIClient", lambda **_: client)
    model = realtime_api.RealtimeModel(
        api_key="synthetic-not-a-key", conn_options=APIConnectOptions(max_retry=0)
    )
    session = model.session()
    try:
        await asyncio.wait_for(connected.wait(), 2)
        assert len(counts) == 2
    finally:
        await session.aclose()
        await model.aclose()


def test_budget_blocker_prevents_paid_model_even_if_caller_supplies_budget(
    monkeypatch, tmp_path
):
    from tests.gemini_fallback.test_hands_memory import shared

    from jarvis.voice.gemini_budget import GeminiLiveBudget
    from jarvis.voice.gemini_transport import GeminiTransportState

    runtime, _ = shared(tmp_path, monkeypatch, {})
    paid = runtime.targets_for("voice.live", "gemini-test-live")[1]
    state = GeminiTransportState(
        epoch=0, current_epoch=lambda: 0, budget=GeminiLiveBudget()
    )
    with pytest.raises(PaidBudgetDenied):
        _create_realtime_model(
            JarvisConfig(ai_provider="gemini"), target=paid, transport_state=state
        )
