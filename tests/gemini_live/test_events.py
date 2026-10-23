import asyncio

import pytest
from livekit.agents import llm
from tests.gemini_live.helpers import context, environment, until
from tests.gemini_live.test_contract import raw_usage


@pytest.mark.asyncio
async def test_every_part_and_transcription_in_same_event_is_processed(tmp_path):
    env = environment(tmp_path)
    transcriptions = []
    env.session.on("input_audio_transcription_completed", transcriptions.append)
    try:
        await context(env.session)
        response = env.session.generate_reply()
        await until(lambda: env.endpoint.wires)
        env.endpoint.wires[0].feed(
            server_content={
                "model_turn": {
                    "role": "model",
                    "parts": [
                        {"text": "private thought", "thought": True},
                        {"text": "unspoken model text"},
                        {
                            "inline_data": {
                                "mime_type": "audio/pcm;rate=24000",
                                "data": bytes(960),
                            }
                        },
                    ],
                },
                "input_transcription": {"text": "meri gaadi", "finished": True},
                "output_transcription": {"text": "Aapki gaadi"},
                "turn_complete": True,
            },
            usage_metadata=raw_usage(),
        )
        event = await asyncio.wait_for(response, 5)
        messages = [m async for m in event.message_stream]
        assert [text async for text in messages[0].text_stream] == ["Aapki gaadi"]
        audio = [frame async for frame in messages[0].audio_stream]
        assert len(audio) == 1 and audio[0].sample_rate == 24000
        assert (
            transcriptions[-1].is_final
            and transcriptions[-1].transcript == "meri gaadi"
        )
        assert await messages[0].modalities == ["text", "audio"]
        await until(lambda: env.endpoint.wires[0].closed)
        assert env.runtime.paid_budget.status().spent_inr_minor == 1
    finally:
        await env.model.aclose()


@pytest.mark.asyncio
async def test_obsolete_epoch_drops_all_incoming_personal_output(tmp_path):
    env = environment(tmp_path)
    delivered = []
    env.session.on("generation_created", delivered.append)
    env.session.on("input_audio_transcription_completed", delivered.append)
    try:
        await context(env.session)
        future = env.session.generate_reply()
        await until(lambda: env.endpoint.wires)
        env.epoch[0] = 2
        env.endpoint.wires[0].feed(
            server_content={
                "model_turn": {"role": "model", "parts": [{"text": "old secret"}]},
                "input_transcription": {"text": "old personal speech"},
                "turn_complete": True,
            },
            usage_metadata=raw_usage(),
        )
        with pytest.raises(llm.RealtimeError):
            await asyncio.wait_for(future, 5)
        assert not delivered
    finally:
        await env.model.aclose()


@pytest.mark.parametrize(
    "kind", ["quota", "auth", "balance", "service", "timeout", "connection"]
)
def test_sanitized_error_preserves_existing_provider_policy_facts(kind):
    from google.genai.errors import APIError

    from jarvis.provider_resilience import classify_provider_failure
    from jarvis.voice.gemini_live_events import sanitized_live_error

    errors = {
        "quota": APIError(
            429,
            {
                "message": "quota exceeded",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "120s",
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaId": "RequestsPerDay",
                                "quotaMetric": "generativelanguage.googleapis.com/requests",
                            }
                        ],
                    },
                ],
            },
        ),
        "auth": APIError(401, {}),
        "balance": APIError(402, {}),
        "service": APIError(503, {}),
        "timeout": TimeoutError("private payload"),
        "connection": ConnectionError("private payload"),
    }
    original = errors[kind]
    assert classify_provider_failure(
        sanitized_live_error(original), provider="gemini"
    ) == classify_provider_failure(original, provider="gemini")
