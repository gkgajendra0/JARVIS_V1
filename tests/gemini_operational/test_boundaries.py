import asyncio

import pytest
from google.genai.errors import APIError
from livekit.agents import llm
from tests.gemini_live.helpers import frame, until
from tests.gemini_live.test_handoff import production

from jarvis.voice.gemini_operational_budget import OperationalLiveAdmission

from .helpers import OperationalEndpoint, policy, profile, usage


@pytest.mark.asyncio
async def test_normal_operational_handoff_keeps_context_and_recovers_free_on_demand(
    tmp_path, monkeypatch
):
    env = await production(tmp_path, monkeypatch)
    endpoint = OperationalEndpoint(env.runtime)
    monkeypatch.setattr(
        "jarvis.voice.livekit_session.genai.Client", lambda **_: endpoint.client()
    )
    env.h.paid_admission = OperationalLiveAdmission(
        env.runtime,
        session_id=env.bridge.conversation.session_id,
        authorize=env.h._authorized,
        policy=policy(),
        profile=profile(),
    )
    try:
        original = env.bridge.conversation.turns
        session_id = env.bridge.conversation.session_id
        env.raw[0].sessions[0].emit(
            "error",
            llm.RealtimeModelError(
                timestamp=1, label="quota", error=APIError(429, {}), recoverable=False
            ),
        )
        await asyncio.wait_for(env.h.task, 5)
        await until(lambda: endpoint.wires and endpoint.wires[0].sent)
        assert env.bridge.conversation.session_id == session_id
        assert env.bridge.conversation.turns == original
        assert "vegetarian" in endpoint.wires[0].sent[0][1].model_dump_json()
        endpoint.wires[0].feed(
            server_content={"turn_complete": True}, usage_metadata=usage()
        )
        await until(
            lambda: (
                endpoint.wires[0].closed and env.h.current_model.inner.sessions[0].idle
            )
        )
        assert env.runtime.paid_budget.status().unknown_reservations == 0
        env.runtime.clock = lambda: 200
        env.h.router._clock = env.runtime.clock
        env.session.emit(
            "user_state_changed",
            __import__("types").SimpleNamespace(new_state="speaking"),
        )
        paid = env.h.current_model.inner.sessions[0]
        paid.start_user_activity()
        paid.push_audio(frame())
        await until(lambda: len(env.raw) == 2 or endpoint.clients == 2)
        assert endpoint.clients == 1 and len(env.raw) == 2
        assert env.h.current_target.credential_ref == "GOOGLE_API_KEY"
    finally:
        env.h.close()
        await env.session.aclose()


@pytest.mark.asyncio
async def test_capture_unknown_retains_hold_and_denies_second_paid_connection(op_env):
    from jarvis.model_routing.budget import PaidBudgetDenied
    from jarvis.voice.gemini_live_budget_session import create_connection_budget
    from jarvis.voice.gemini_live_diagnostics import authorize_live_experiment

    from .admin_helpers import broker
    from .test_diagnostics import plan

    b, _ = broker()
    auth = authorize_live_experiment(
        op_env.runtime, plan(op_env), broker=b, session_id="owner"
    )
    op_env.runtime.validate_live_experiment = op_env.runtime.live_diagnostics.validate
    a = OperationalLiveAdmission(
        op_env.runtime,
        session_id="owner",
        authorize=lambda: True,
        policy=op_env.policy,
        profile=op_env.profile,
        capture_only=True,
        experiment_authorization=auth,
    )
    lease = create_connection_budget(a, connection_id="first", target=op_env.target)
    await lease.reserve_round("r1")
    assert lease.controls.max_physical_seconds == 15
    await lease.before_send("setup", "setup")
    await lease.before_send("history", "history")
    await lease.before_send("initial", "initial")
    await lease.close(teardown_confirmed=True, complete=False)
    s = op_env.governor.status()
    assert s.unknown_reservations == 1 and s.reserved_inr_minor == 1000
    next_lease = create_connection_budget(
        a, connection_id="second", target=op_env.target
    )
    with pytest.raises(PaidBudgetDenied):
        await next_lease.reserve_round("r2")
