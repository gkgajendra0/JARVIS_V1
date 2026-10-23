import asyncio

import pytest
from livekit.agents import llm
from tests.gemini_live.helpers import context, environment, frame, until
from tests.gemini_live.test_contract import raw_usage


@pytest.mark.asyncio
async def test_public_connection_has_prior_hold_manual_activity_and_no_idle_socket(
    tmp_path,
):
    env = environment(tmp_path)
    s = env.session
    try:
        await context(s)
        await s.update_instructions("Speak Hindi, Hinglish or English as requested")
        assert env.endpoint.clients == 0
        s.start_user_activity()
        s.push_audio(frame())
        s.commit_audio()
        response = s.generate_reply()
        await until(lambda: env.endpoint.wires and len(env.endpoint.wires[0].sent) >= 4)
        wire = env.endpoint.wires[0]
        conf = env.endpoint.configs[0]
        assert conf.realtime_input_config.automatic_activity_detection.disabled is True
        assert (
            conf.speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"
        )
        assert (
            conf.session_resumption is None and conf.context_window_compression is None
        )
        assert conf.history_config.initial_history_in_client_content is True
        assert wire.sent[0][0] == "content" and wire.sent[0][1].turn_complete
        assert wire.sent[1][1].activity_start is not None
        assert wire.sent[2][1].audio.data == bytes(640)
        assert wire.sent[3][1].activity_end is not None
        wire.feed(
            server_content={
                "model_turn": {"role": "model", "parts": [{"text": "Haan"}]},
                "turn_complete": True,
            },
            usage_metadata=raw_usage(),
        )
        event = await asyncio.wait_for(response, 5)
        assert isinstance(event, llm.GenerationCreatedEvent) and event.user_initiated
        messages = [m async for m in event.message_stream]
        assert len(messages) == 1
        assert [t async for t in messages[0].text_stream] == ["Haan"]
        await until(lambda: wire.closed)
        await until(lambda: env.runtime.paid_budget.status().spent_inr_minor == 1)
        assert env.runtime.paid_budget.status().spent_inr_minor == 1
        assert env.runtime.paid_budget.status().reserved_inr_minor == 0
        assert env.endpoint.clients == 1
        # Same logical session, new physical connection and original canonical history.
        next_response = s.generate_reply()
        await until(lambda: len(env.endpoint.wires) == 2)
        assert "vegetarian" in env.endpoint.wires[1].sent[0][1].model_dump_json()
        env.endpoint.wires[1].feed(
            server_content={"turn_complete": True}, usage_metadata=raw_usage()
        )
        await asyncio.wait_for(next_response, 5)
    finally:
        await env.model.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["goaway", "read", "setup"])
async def test_provider_failure_never_reconnects_or_refunds_ambiguous_send(
    tmp_path, kind
):
    env = environment(tmp_path)
    errors = []
    env.session.on("error", errors.append)
    if kind == "setup":
        env.endpoint.setup_error = RuntimeError("synthetic setup failure")
    try:
        await context(env.session)
        result = env.session.generate_reply()
        if kind != "setup":
            await until(lambda: env.endpoint.wires)
            wire = env.endpoint.wires[0]
            if kind == "goaway":
                wire.feed(go_away={"time_left": "1s"})
            else:
                wire.events.put_nowait(RuntimeError("synthetic read failure"))
        with pytest.raises(llm.RealtimeError):
            await asyncio.wait_for(result, 5)
        await until(lambda: errors)
        assert env.endpoint.clients == 1
        assert env.runtime.paid_budget.status().unknown_reservations == 1
        again = env.session.generate_reply()
        with pytest.raises(llm.RealtimeError):
            await asyncio.wait_for(again, 5)
        assert env.endpoint.clients == 1
    finally:
        await env.model.aclose()


@pytest.mark.asyncio
async def test_revoke_during_setup_never_discloses_canonical_history(tmp_path):
    valid = [True]
    env = environment(tmp_path, authorize=lambda: valid[0])
    original = env.endpoint.client

    def revoked():
        client = original()
        valid[0] = False
        return client

    env.model.client_factory = revoked
    try:
        await context(env.session)
        result = env.session.generate_reply()
        with pytest.raises(llm.RealtimeError):
            await asyncio.wait_for(result, 5)
        assert all(not w.sent for w in env.endpoint.wires)
    finally:
        await env.model.aclose()


@pytest.mark.asyncio
async def test_response_before_client_trigger_cannot_release_tools_or_output(tmp_path):
    env = environment(tmp_path)
    emitted = []
    env.session.on("generation_created", emitted.append)
    try:
        await context(env.session)
        env.session.start_user_activity()
        await until(lambda: env.endpoint.wires and len(env.endpoint.wires[0].sent) >= 2)
        env.endpoint.wires[0].feed(
            server_content={
                "model_turn": {
                    "role": "model",
                    "parts": [{"text": "unrequested personal response"}],
                },
                "turn_complete": True,
            },
            usage_metadata=raw_usage(),
        )
        await until(lambda: env.endpoint.wires[0].closed)
        assert not emitted
        assert env.runtime.paid_budget.status().spent_inr_minor == 0
    finally:
        await env.model.aclose()
