import asyncio

import pytest
from livekit.agents import llm
from tests.gemini_live.helpers import context, environment, frame, until
from tests.gemini_live.test_contract import raw_usage


@pytest.mark.asyncio
@pytest.mark.parametrize("operational", [False, True])
async def test_speech_during_silent_cleanup_preserves_subsequent_pcm(
    tmp_path, operational
):
    from tests.gemini_operational.helpers import environment as operational_environment
    from tests.gemini_operational.helpers import usage

    env = operational_environment(tmp_path) if operational else environment(tmp_path)
    usage_event = usage if operational else raw_usage
    s = env.session

    @llm.function_tool
    async def wait_for_instruction() -> None:
        """Fictional declaration only; no action is executed."""

    try:
        await context(s)
        await s.update_tools([wait_for_instruction])
        first = s.generate_reply()
        await until(lambda: env.endpoint.wires and len(env.endpoint.wires[0].sent) >= 2)
        wire = env.endpoint.wires[0]
        wire.feed(
            tool_call={
                "function_calls": [
                    {
                        "id": "silent",
                        "name": "wait_for_instruction",
                        "args": {},
                    }
                ]
            }
        )
        await asyncio.wait_for(first, 5)
        ctx = s.chat_ctx
        ctx.items.append(
            llm.FunctionCallOutput(
                call_id="silent",
                name="wait_for_instruction",
                output="",
                reply_required=False,
                is_error=False,
            )
        )
        await s.update_chat_ctx(ctx)
        await asyncio.sleep(0)
        # Real speech begins while the old round is still awaiting final usage.
        s.start_user_activity()
        s.push_audio(frame(320))
        wire.feed(server_content={"turn_complete": True}, usage_metadata=usage_event())
        await until(lambda: len(env.endpoint.wires) == 2)
        next_wire = env.endpoint.wires[1]
        await until(
            lambda: any(kind == "input" and item.audio for kind, item in next_wire.sent)
        )
        s.push_audio(frame(640))
        await until(
            lambda: (
                len(
                    [
                        item
                        for kind, item in next_wire.sent
                        if kind == "input" and item.audio
                    ]
                )
                == 2
            )
        )
        assert [
            len(item.audio.data)
            for kind, item in next_wire.sent
            if kind == "input" and item.audio
        ] == [640, 1280]
        s.commit_audio()
        second = s.generate_reply()
        await until(
            lambda: any(
                kind == "input" and item.activity_end for kind, item in next_wire.sent
            )
        )
        next_wire.feed(
            server_content={"turn_complete": True}, usage_metadata=usage_event()
        )
        await asyncio.wait_for(second, 5)
    finally:
        await env.model.aclose()
