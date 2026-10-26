import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from tests.gemini_live.helpers import context, until

from .helpers import environment, usage


@pytest.mark.asyncio
async def test_price_change_during_history_prevents_next_paid_send(tmp_path):
    e = environment(tmp_path)
    connect = e.endpoint.connect

    @asynccontextmanager
    async def changed(**kwargs):
        async with connect(**kwargs) as wire:
            send = wire.send_client_content

            async def history(**content):
                await send(**content)
                price = e.runtime.pricing_for(e.model.target)
                e.runtime.pricing_for = lambda _: replace(
                    price, fx_version=price.fx_version + 1
                )

            wire.send_client_content = history
            yield wire

    e.endpoint.connect = changed
    try:
        await context(e.session)
        f = e.session.generate_reply()
        await until(lambda: e.endpoint.wires and e.endpoint.wires[0].sent)
        await asyncio.sleep(0.1)
        assert len(e.endpoint.wires[0].sent) == 1
        await asyncio.gather(f, return_exceptions=True)
    finally:
        await e.model.aclose()


@pytest.mark.asyncio
async def test_capture_waits_for_terminal_metadata_and_exports_exact_evidence(
    op_env, monkeypatch
):
    from tools.research.gemini_operational_live_qualification import FIXTURE, capture

    from jarvis.model_routing.live_policy import digest
    from jarvis.voice import gemini_operational_budget

    from .admin_helpers import broker
    from .helpers import OperationalEndpoint
    from .test_diagnostics import plan

    op_env.profile = replace(op_env.profile, terminal_mode="post_turn_complete")
    p = plan(
        op_env, fixture_ref=digest(FIXTURE), profile_ref=op_env.profile.fingerprint
    )
    b, _ = broker()
    runtime = op_env.runtime
    runtime.targets_for = lambda *args: (
        replace(
            op_env.target,
            credential_ref="GOOGLE_API_KEY",
            target_id=op_env.target.target_id.replace(".paid.", ".free."),
        ),
        op_env.target,
    )
    runtime.validate_live_experiment = lambda auth: runtime.live_diagnostics.validate(
        auth
    )
    endpoint = OperationalEndpoint(runtime)
    monkeypatch.setenv("JARVIS_GEMINI_PAID_API_KEY", "offline-canary")
    monkeypatch.setattr(
        gemini_operational_budget, "operational_live_policy", lambda: op_env.policy
    )
    monkeypatch.setattr(
        "jarvis.model_routing.live_budget_admin._profile_sources", lambda *args: None
    )
    monkeypatch.setattr(
        "jarvis.voice.livekit_session.genai.Client", lambda **_: endpoint.client()
    )

    async def provider():
        await until(lambda: endpoint.wires and endpoint.wires[0].sent)
        endpoint.wires[0].feed(server_content={"turn_complete": True})
        await asyncio.sleep(0.1)
        endpoint.wires[0].feed(usage_metadata=usage())

    feeder = asyncio.create_task(provider())
    result = await capture(runtime, p, op_env.profile, broker=b)
    await feeder
    assert runtime.paid_budget.status().spent_inr_minor == 1
    assert result["evidence"]["reports"][0]["complete"] is True
    assert result["evidence"]["reservation_id"]
    assert runtime.paid_budget.status().unknown_reservations == 1


def test_default_admin_cli_reads_canonical_encrypted_ledger(
    op_env, monkeypatch, capsys
):
    import json

    from jarvis.paid_budget_cli import main
    from jarvis.work.privacy import ProtectedWorkPayloadCodec

    from .admin_helpers import unknown_complete

    codec = ProtectedWorkPayloadCodec(bytes(range(32)))
    path = op_env.store.work_store.path
    op_env.store.work_store._payload_codec = codec
    unknown_complete(op_env)
    monkeypatch.setattr("jarvis.work.store.default_work_store_path", lambda: path)
    monkeypatch.setattr(
        "jarvis.work.privacy.build_default_work_payload_codec", lambda path: codec
    )
    assert main(["status"]) == 0
    assert (
        json.loads(capsys.readouterr().out)["operational_live"][0]["known_minor"] == 850
    )


def test_known_response_text_is_debited_when_thought_usage_is_missing():
    from jarvis.voice.gemini_live_usage import normalize_operational_usage

    from .helpers import profile

    raw = usage()
    del raw["thoughts_token_count"]
    result = normalize_operational_usage(
        raw,
        profile=profile(),
        round_id="r1",
        sequence=3,
        after_round_complete=True,
        last_output_sequence=2,
    )
    assert result.complete is False
    assert result.usage["output_tokens"] == 4


def test_partial_cumulative_round_keeps_omitted_prior_lower_bounds(op_env):
    from jarvis.model_routing.live_policy import LiveUsageReport

    from .test_governor import checkpoint, reserve

    op_env.profile = replace(op_env.profile, counter_scope="connection")
    r = reserve(op_env)
    checkpoint(op_env, r)
    report = LiveUsageReport(
        "r1",
        2,
        {
            "input_tokens": 100,
            "input_audio_tokens": 10,
            "output_tokens": 5,
            "output_audio_tokens": 5,
        },
        True,
        op_env.profile.fingerprint,
        True,
        1,
    )
    op_env.governor.observe_operational_live(
        reservation_id=r.reservation_id, report=report, event_id="first"
    )
    checkpoint(op_env, r, kind="tool", round_id="r2", trigger="tool1")
    partial = LiveUsageReport(
        "r2", 3, {"input_tokens": 200}, False, op_env.profile.fingerprint, False, 2
    )
    result = op_env.governor.observe_operational_live(
        reservation_id=r.reservation_id, report=partial, event_id="second-partial"
    )
    assert result.unknown_reason is None and not result.stop_required
    assert op_env.governor.status().unknown_reservations == 0
