"""Reproductions for the five independently reviewed Important findings."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from google.genai.errors import APIError
from livekit.agents import llm
from tests.gemini_live.helpers import context, environment, frame, until
from tests.gemini_live.test_contract import raw_usage
from tests.gemini_live.test_handoff import production
from tests.gemini_live.test_tools import lookup_vehicle


@pytest.mark.asyncio
async def test_review_2_earlier_complete_shaped_usage_is_not_final_at_later_output(
    tmp_path,
):
    env = environment(tmp_path)
    try:
        await context(env.session)
        future = env.session.generate_reply()
        await until(lambda: env.endpoint.wires)
        wire = env.endpoint.wires[0]
        wire.feed(usage_metadata=raw_usage())
        wire.feed(
            server_content={
                "output_transcription": {"text": "more billable output"},
                "turn_complete": True,
            }
        )
        await asyncio.wait_for(future, 5)
        await until(lambda: wire.closed)
        await until(lambda: env.runtime.paid_budget.status().unknown_reservations == 1)
        status = env.runtime.paid_budget.status()
        assert status.reserved_inr_minor == 3993 and status.spent_inr_minor == 0
    finally:
        await env.model.aclose()


@pytest.mark.asyncio
async def test_review_3_next_connection_uses_full_accepted_spoken_canonical_context(
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
        await until(lambda: env.endpoint.wires)
        env.endpoint.wires[0].feed(
            server_content={
                "input_transcription": {
                    "text": "Meri fictional City neeli hai",
                    "finished": True,
                },
                "output_transcription": {"text": "Aapki fictional City neeli hai"},
                "turn_complete": True,
            },
            usage_metadata=raw_usage(),
        )
        await until(
            lambda: (
                env.endpoint.wires[0].closed
                and any(
                    turn.role.value == "assistant"
                    for turn in env.bridge.conversation.turns
                )
            )
        )
        handle = env.session.generate_reply(user_input="Abhi maine kya bola tha?")
        await until(lambda: len(env.endpoint.wires) == 2 and env.endpoint.wires[1].sent)
        replay = env.endpoint.wires[1].sent[0][1].model_dump_json()
        assert "Meri fictional City neeli hai" in replay
        assert "Aapki fictional City neeli hai" in replay
        env.endpoint.wires[1].feed(
            server_content={"turn_complete": True}, usage_metadata=raw_usage()
        )
        await asyncio.wait_for(handle, 5)
    finally:
        env.h.close()
        await env.session.aclose()


@pytest.mark.asyncio
async def test_review_4_cancelled_queued_function_is_never_released_behind_blocked_sender(
    tmp_path,
):
    env = environment(tmp_path)
    entered, gate = asyncio.Event(), asyncio.Event()
    original = env.endpoint.connect

    @asynccontextmanager
    async def connect(**kwargs):
        async with original(**kwargs) as wire:
            send = wire.send_client_content

            async def blocked(**content):
                await send(**content)
                if len(wire.sent) == 2:
                    entered.set()
                    await gate.wait()

            wire.send_client_content = blocked
            yield wire

    env.endpoint.connect = connect
    try:
        await context(env.session)
        await env.session.update_tools([lookup_vehicle])
        future = env.session.generate_reply()
        await asyncio.wait_for(entered.wait(), 5)
        wire = env.endpoint.wires[0]
        wire.feed(
            tool_call={
                "function_calls": [
                    {
                        "id": "cancel-me",
                        "name": "lookup_vehicle",
                        "args": {"name": "City"},
                    }
                ]
            }
        )
        event = await asyncio.wait_for(future, 5)
        wire.feed(tool_call_cancellation={"ids": ["cancel-me"]})
        await until(lambda: "cancel-me" in env.session._cancelled_tools)
        assert not gate.is_set()
        assert [call async for call in event.function_stream] == []
        await until(lambda: wire.closed)
    finally:
        gate.set()
        await env.model.aclose()


@pytest.mark.asyncio
async def test_review_5_next_eligible_owner_demand_attempts_free_before_paid_dispatch(
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
        await until(lambda: env.endpoint.wires)
        env.endpoint.wires[0].feed(
            server_content={"turn_complete": True}, usage_metadata=raw_usage()
        )
        await until(lambda: env.h.current_model.inner.sessions[0].idle)
        env.runtime.clock = lambda: 200
        env.h.router._clock = env.runtime.clock
        env.session.emit("user_state_changed", SimpleNamespace(new_state="speaking"))
        paid_session = env.h.current_model.inner.sessions[0]
        paid_session.start_user_activity()
        paid_session.push_audio(frame())
        await until(lambda: len(env.raw) == 2 or env.endpoint.clients == 2)
        assert len(env.raw) == 2 and env.endpoint.clients == 1
        await asyncio.wait_for(env.h.task, 5)
        assert env.h.current_target.credential_ref == "GOOGLE_API_KEY"
        assert len(env.raw[-1].sessions[0].audio) == 1
        assert bytes(env.raw[-1].sessions[0].audio[0].data) == bytes(640)
        assert env.bridge.conversation.status.value == "active"
    finally:
        env.h.close()
        await env.session.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["setup", "history", "activity", "tool", "teardown"])
async def test_review_1_absolute_deadline_interrupts_blocked_public_io(tmp_path, stage):
    env = environment(tmp_path)
    env.model.admission.contract = replace(
        env.model.admission.contract, max_activity_seconds=1, max_physical_seconds=1
    )
    entered, gate = asyncio.Event(), asyncio.Event()
    original = env.endpoint.connect

    @asynccontextmanager
    async def connect(**kwargs):
        if stage == "setup":
            entered.set()
            await gate.wait()
        async with original(**kwargs) as wire:
            if stage == "history":
                send = wire.send_client_content

                async def blocked(**content):
                    entered.set()
                    await gate.wait()
                    await send(**content)

                wire.send_client_content = blocked
            if stage == "activity":
                send = wire.send_realtime_input

                async def blocked(**content):
                    entered.set()
                    await gate.wait()
                    await send(**content)

                wire.send_realtime_input = blocked
            if stage == "tool":
                send = wire.send_tool_response

                async def blocked(**content):
                    entered.set()
                    await gate.wait()
                    await send(**content)

                wire.send_tool_response = blocked
            yield wire
            if stage == "teardown":
                entered.set()
                await gate.wait()

    env.endpoint.connect = connect
    future = None
    try:
        await context(env.session)
        if stage == "activity":
            env.session.start_user_activity()
        if stage == "tool":
            await env.session.update_tools([lookup_vehicle])
        future = env.session.generate_reply()
        if stage in {"tool", "teardown"}:
            await until(lambda: env.endpoint.wires)
            wire = env.endpoint.wires[0]
            if stage == "tool":
                wire.feed(
                    tool_call={
                        "function_calls": [
                            {
                                "id": "deadline-tool",
                                "name": "lookup_vehicle",
                                "args": {"name": "City"},
                            }
                        ]
                    },
                    server_content={"turn_complete": True},
                    usage_metadata=raw_usage(),
                )
                event = await asyncio.wait_for(future, 5)
                calls = [call async for call in event.function_stream]
                await until(
                    lambda: env.runtime.paid_budget.status().spent_inr_minor == 1
                )
                ctx = env.session.chat_ctx
                ctx.items.extend(
                    [
                        calls[0],
                        llm.FunctionCallOutput(
                            call_id="deadline-tool",
                            name="lookup_vehicle",
                            output="City",
                            is_error=False,
                        ),
                    ]
                )
                await env.session.update_chat_ctx(ctx)
                future = env.session.generate_reply()
            else:
                wire.feed(
                    server_content={"turn_complete": True}, usage_metadata=raw_usage()
                )
        await asyncio.wait_for(entered.wait(), 5)
        await asyncio.sleep(1.25)
        assert all(wire.closed for wire in env.endpoint.wires)
        assert future.done()
        assert env.runtime.paid_budget.status().unknown_reservations == 1
    finally:
        gate.set()
        await env.model.aclose()
        if future is not None:
            await asyncio.gather(future, return_exceptions=True)


@pytest.mark.asyncio
async def test_close_finishes_even_if_public_send_swallows_first_cancellation(tmp_path):
    env = environment(tmp_path)
    entered, gate = asyncio.Event(), asyncio.Event()
    original = env.endpoint.connect

    @asynccontextmanager
    async def connect(**kwargs):
        async with original(**kwargs) as wire:
            send = wire.send_client_content

            async def cancellation_race(**content):
                await send(**content)
                if len(wire.sent) == 2:
                    entered.set()
                    try:
                        await gate.wait()
                    except asyncio.CancelledError:
                        return

            wire.send_client_content = cancellation_race
            yield wire

    env.endpoint.connect = connect
    closing = None
    future = None
    try:
        await context(env.session)
        future = env.session.generate_reply()
        await asyncio.wait_for(entered.wait(), 5)
        closing = asyncio.create_task(env.model.aclose())
        await asyncio.wait_for(asyncio.shield(closing), 1)
        assert env.endpoint.wires[0].closed
        assert env.runtime.paid_budget.status().unknown_reservations == 1
    finally:
        gate.set()
        if closing is not None:
            closing.cancel()
            await asyncio.gather(closing, return_exceptions=True)
        if future is not None:
            if not future.done():
                future.cancel()
            await asyncio.gather(future, return_exceptions=True)
        await env.model.aclose()
