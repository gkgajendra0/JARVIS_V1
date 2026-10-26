import asyncio

import pytest
from livekit.agents import llm
from tests.gemini_live.helpers import context, until
from tests.gemini_live.test_tools import lookup_vehicle

from .helpers import environment, usage


@pytest.mark.asyncio
async def test_intermediate_round_needs_usage_before_tool_result(tmp_path):
    e = environment(tmp_path)
    try:
        await context(e.session)
        await e.session.update_tools([lookup_vehicle])
        first = e.session.generate_reply()
        await until(lambda: e.endpoint.wires and e.endpoint.wires[0].sent)
        w = e.endpoint.wires[0]
        w.feed(
            tool_call={
                "function_calls": [
                    {"id": "call-1", "name": "lookup_vehicle", "args": {"name": "car"}}
                ]
            }
        )
        event = await asyncio.wait_for(first, 5)
        calls = [c async for c in event.function_stream]
        ctx = e.session.chat_ctx
        ctx.items.extend(
            [
                calls[0],
                llm.FunctionCallOutput(
                    call_id="call-1",
                    name="lookup_vehicle",
                    output="car",
                    is_error=False,
                ),
            ]
        )
        await e.session.update_chat_ctx(ctx)
        second = e.session.generate_reply()
        await asyncio.sleep(0.02)
        assert not any(k == "tool" for k, _ in w.sent)
        w.feed(server_content={"turn_complete": True}, usage_metadata=usage())
        await until(lambda: any(k == "tool" for k, _ in w.sent))
        assert e.runtime.paid_budget.status().reserved_inr_minor == 999
        w.feed(server_content={"turn_complete": True}, usage_metadata=usage())
        await asyncio.wait_for(second, 5)
        await until(lambda: e.runtime.paid_budget.status().reserved_inr_minor == 0)
        assert e.runtime.paid_budget.status().spent_inr_minor == 1
        assert e.endpoint.clients == 1
    finally:
        await e.model.aclose()
