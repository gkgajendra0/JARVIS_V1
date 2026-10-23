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
