import asyncio

import pytest
from livekit.agents import llm
from tests.gemini_live.helpers import context, environment, until
from tests.gemini_live.test_contract import raw_usage


@llm.function_tool
async def lookup_vehicle(name: str) -> str:
    """Read a fictional vehicle."""
    return name


@pytest.mark.asyncio
async def test_blocking_tools_dedupe_and_only_matching_results_trigger_paid_continuation(
    tmp_path,
):
    env = environment(tmp_path)
    try:
        await context(env.session)
        await env.session.update_tools([lookup_vehicle])
        first = env.session.generate_reply()
        await until(lambda: env.endpoint.wires)
        wire = env.endpoint.wires[0]
        declarations = env.endpoint.configs[0].tools[0].function_declarations
        assert declarations[0].behavior.value == "BLOCKING"
        call = {
            "id": "call-1",
            "name": "lookup_vehicle",
            "args": {"name": "fictional car"},
        }
        wire.feed(
            tool_call={"function_calls": [call, call]},
            server_content={"turn_complete": True},
            usage_metadata=raw_usage(),
        )
        event = await asyncio.wait_for(first, 5)
        functions = [c async for c in event.function_stream]
        assert len(functions) == 1 and functions[0].call_id == "call-1"
        await until(lambda: env.runtime.paid_budget.status().spent_inr_minor == 1)
        assert not wire.closed
        ctx = env.session.chat_ctx
        ctx.items.extend(
            [
                functions[0],
                llm.FunctionCallOutput(
                    call_id="call-1",
                    name="lookup_vehicle",
                    output="fictional car",
                    is_error=False,
                ),
            ]
        )
        await env.session.update_chat_ctx(ctx)
        second = env.session.generate_reply()
        await until(lambda: any(k == "tool" for k, _ in wire.sent))
        assert env.runtime.paid_budget.status().reserved_inr_minor == 3993
        wire.feed(server_content={"turn_complete": True}, usage_metadata=raw_usage())
        await asyncio.wait_for(second, 5)
        await until(lambda: wire.closed)
        assert sum(k == "tool" for k, _ in wire.sent) == 1
        assert env.runtime.paid_budget.status().spent_inr_minor == 2
    finally:
        await env.model.aclose()


@pytest.mark.asyncio
async def test_unsolicited_tool_result_is_rejected_without_sending(tmp_path):
    env = environment(tmp_path)
    try:
        ctx = await context(env.session)
        ctx.items.append(
            llm.FunctionCallOutput(
                call_id="unowned",
                name="lookup_vehicle",
                output="secret",
                is_error=False,
            )
        )
        with pytest.raises(llm.RealtimeError):
            await env.session.update_chat_ctx(ctx)
        assert env.endpoint.clients == 0
    finally:
        await env.model.aclose()


@pytest.mark.asyncio
async def test_fast_tool_result_waits_for_final_usage_without_duplicate_action(
    tmp_path,
):
    env = environment(tmp_path)
    try:
        await context(env.session)
        await env.session.update_tools([lookup_vehicle])
        first = env.session.generate_reply()
        await until(lambda: env.endpoint.wires)
        wire = env.endpoint.wires[0]
        wire.feed(
            tool_call={
                "function_calls": [
                    {"id": "fast", "name": "lookup_vehicle", "args": {"name": "car"}}
                ]
            }
        )
        event = await asyncio.wait_for(first, 5)
        calls = [call async for call in event.function_stream]
        ctx = env.session.chat_ctx
        ctx.items.extend(
            [
                calls[0],
                llm.FunctionCallOutput(
                    call_id="fast", name="lookup_vehicle", output="car", is_error=False
                ),
            ]
        )
        await env.session.update_chat_ctx(ctx)
        second = env.session.generate_reply()
        # Fast local tool completed before provider sent final usage/turn completion.
        wire.feed(server_content={"turn_complete": True}, usage_metadata=raw_usage())
        await until(lambda: any(kind == "tool" for kind, _ in wire.sent))
        wire.feed(server_content={"turn_complete": True}, usage_metadata=raw_usage())
        await asyncio.wait_for(second, 5)
        await until(lambda: wire.closed)
        assert env.endpoint.clients == 1
        assert env.runtime.paid_budget.status().spent_inr_minor == 2
    finally:
        await env.model.aclose()
