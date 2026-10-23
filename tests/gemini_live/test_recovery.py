import asyncio
from types import SimpleNamespace

import pytest
from google.genai.errors import APIError
from livekit.agents import llm
from tests.gemini_live.helpers import until
from tests.gemini_live.test_contract import raw_usage
from tests.gemini_live.test_handoff import production


@pytest.mark.asyncio
async def test_real_demand_returns_to_free_only_after_paid_socket_and_speech_are_idle(
    tmp_path, monkeypatch
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
        env.runtime.clock = lambda: 200
        env.h.router._clock = env.runtime.clock
        # New physical owner demand while the Paid reply is still in flight.
        env.session.emit("user_state_changed", SimpleNamespace(new_state="speaking"))
        env.session.emit("user_state_changed", SimpleNamespace(new_state="listening"))
        await asyncio.sleep(0)
        assert len(env.raw) == 1
        env.endpoint.wires[0].feed(
            server_content={
                "model_turn": {
                    "role": "model",
                    "parts": [
                        {
                            "inline_data": {
                                "data": bytes(960),
                                "mime_type": "audio/pcm;rate=24000",
                            }
                        }
                    ],
                },
                "output_transcription": {"text": "Fictional reply"},
                "turn_complete": True,
            },
            usage_metadata=raw_usage(),
        )
        await until(lambda: len(env.raw) == 2)
        await asyncio.wait_for(env.h.task, 5)
        assert env.h.current_target.credential_ref == "GOOGLE_API_KEY"
        assert env.endpoint.clients == 1
        free_id = env.h.current_target.target_id
        assert env.runtime.store.get_health(free_id).consecutive_failures == 1
        assert env.raw[-1].sessions[0].replies == 0
    finally:
        env.h.close()
        await env.session.aclose()
