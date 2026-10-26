import asyncio

import pytest
from livekit.agents import llm
from tests.gemini_live.helpers import context, environment, frame, until


@pytest.mark.asyncio
async def test_pre_admission_audio_queue_overflow_never_becomes_unbounded(tmp_path):
    env = environment(tmp_path)
    errors = []
    env.session.on("error", errors.append)
    try:
        env.session.start_user_activity()
        for _ in range(9):
            env.session.push_audio(frame())
        await until(lambda: errors)
        assert env.endpoint.clients == 0
        assert env.runtime.paid_budget.status().reserved_inr_minor == 0
    finally:
        await env.model.aclose()


@pytest.mark.asyncio
async def test_video_is_denied_and_interrupt_never_starts_an_extra_generation(tmp_path):
    env = environment(tmp_path)
    try:
        with pytest.raises(llm.RealtimeError):
            env.session.push_video(object())
        await context(env.session)
        response = env.session.generate_reply()
        await until(lambda: env.endpoint.wires)
        env.session.interrupt()
        with pytest.raises(llm.RealtimeError):
            await asyncio.wait_for(response, 5)
        await until(lambda: env.endpoint.wires[0].closed)
        assert env.endpoint.clients == 1
        assert env.runtime.paid_budget.status().unknown_reservations == 1
    finally:
        await env.model.aclose()


@pytest.mark.asyncio
async def test_cancelled_generation_future_closes_paid_input_without_new_connect(
    tmp_path,
):
    env = environment(tmp_path)
    try:
        await context(env.session)
        future = env.session.generate_reply()
        await until(lambda: env.endpoint.wires and len(env.endpoint.wires[0].sent) >= 2)
        future.cancel()
        await until(lambda: env.endpoint.wires[0].closed)
        await until(lambda: env.runtime.paid_budget.status().unknown_reservations == 1)
        assert env.endpoint.clients == 1
    finally:
        await env.model.aclose()


@pytest.mark.asyncio
async def test_owner_48khz_frames_are_resampled_to_admitted_16khz(tmp_path):
    from livekit import rtc
    from tests.gemini_live.test_contract import raw_usage

    env = environment(tmp_path)
    try:
        env.session.start_user_activity()
        env.session.push_audio(
            rtc.AudioFrame(
                data=bytes(1920),
                sample_rate=48000,
                num_channels=1,
                samples_per_channel=960,
            )
        )
        env.session.commit_audio()
        future = env.session.generate_reply()
        await until(
            lambda: (
                env.endpoint.wires
                and any(
                    kind == "input" and item.audio is not None
                    for kind, item in env.endpoint.wires[0].sent
                )
            )
        )
        audio = [
            item.audio
            for kind, item in env.endpoint.wires[0].sent
            if kind == "input" and item.audio is not None
        ]
        assert all(item.mime_type == "audio/pcm;rate=16000" for item in audio)
        env.endpoint.wires[0].feed(
            server_content={"turn_complete": True}, usage_metadata=raw_usage()
        )
        await asyncio.wait_for(future, 5)
    finally:
        await env.model.aclose()


@pytest.mark.asyncio
async def test_continuous_idle_microphone_buffers_bounded_preroll_without_paid_connect(
    tmp_path,
):
    env = environment(tmp_path)
    errors = []
    env.session.on("error", errors.append)
    try:
        for _ in range(100):
            env.session.push_audio(frame())
            await asyncio.sleep(0)
        assert errors == [] and env.endpoint.clients == 0
        assert env.runtime.paid_budget.status().reserved_inr_minor == 0
        env.session.start_user_activity()
        await until(
            lambda: (
                env.endpoint.wires
                and any(
                    kind == "input" and item.audio is not None
                    for kind, item in env.endpoint.wires[0].sent
                )
            )
        )
        samples = sum(
            len(item.audio.data) // 2
            for kind, item in env.endpoint.wires[0].sent
            if kind == "input" and item.audio is not None
        )
        assert 0 < samples <= 2560
    finally:
        await env.model.aclose()
