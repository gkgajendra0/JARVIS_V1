import asyncio

import pytest
from livekit.agents import Agent, AgentSession, TurnHandlingOptions, llm
from tests.gemini_live.helpers import until

from .helpers import environment, expensive_usage, usage


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,answer",
    [
        ("मेरी गाड़ी कौन सी है?", "आपकी काल्पनिक City है"),
        ("Meri car kaunsi hai?", "Aapki fictional City hai"),
        ("Which car do I own?", "Your fictional car is City"),
    ],
)
async def test_actual_agent_session_preserves_operational_conversation(
    tmp_path, question, answer
):
    e = environment(tmp_path)
    s = AgentSession(
        llm=e.model, vad=None, turn_handling=TurnHandlingOptions(turn_detection=None)
    )
    received = []
    s.on("conversation_item_added", received.append)
    try:
        await s.start(
            agent=Agent(instructions="Fictional only", llm=e.model), record=False
        )
        h = s.generate_reply(user_input=question)
        await until(lambda: e.endpoint.wires and len(e.endpoint.wires[0].sent) >= 2)
        e.endpoint.wires[0].feed(
            server_content={
                "output_transcription": {"text": answer},
                "turn_complete": True,
            },
            usage_metadata=usage(),
        )
        await asyncio.wait_for(h, 5)
        assert h.exception() is None
        assert any(
            i.item.type == "message"
            and i.item.role == "assistant"
            and i.item.text_content == answer
            for i in received
        )
    finally:
        await s.aclose()
        await e.model.aclose()


@pytest.mark.asyncio
async def test_soft_stop_fences_queued_function_and_audio(tmp_path):
    e = environment(tmp_path)
    effects = []

    @llm.function_tool
    async def fictional_action(name: str) -> str:
        """Record fictional effect."""
        effects.append(name)
        return "done"

    s = AgentSession(
        llm=e.model, vad=None, turn_handling=TurnHandlingOptions(turn_detection=None)
    )
    try:
        await s.start(
            agent=Agent(
                instructions="Fictional only", llm=e.model, tools=[fictional_action]
            ),
            record=False,
        )
        h = s.generate_reply(user_input="do fictional action")
        await until(lambda: e.endpoint.wires and e.endpoint.wires[0].sent)
        e.endpoint.wires[0].feed(
            tool_call={
                "function_calls": [
                    {"id": "x", "name": "fictional_action", "args": {"name": "once"}}
                ]
            },
            usage_metadata=expensive_usage(),
        )
        await until(lambda: e.endpoint.wires[0].closed)
        await asyncio.wait_for(h, 5)
        assert effects == []
    finally:
        await s.aclose()
        await e.model.aclose()


@pytest.mark.asyncio
async def test_running_action_is_not_reexecuted_when_spoken_reply_is_cut(tmp_path):
    e = environment(tmp_path)
    effects = []
    release = asyncio.Event()
    started = asyncio.Event()

    @llm.function_tool
    async def fictional_action(name: str) -> str:
        """Record one fictional effect then wait for its outcome."""
        effects.append(name)
        started.set()
        await release.wait()
        return "done"

    s = AgentSession(
        llm=e.model, vad=None, turn_handling=TurnHandlingOptions(turn_detection=None)
    )
    try:
        await s.start(
            agent=Agent(
                instructions="Fictional only", llm=e.model, tools=[fictional_action]
            ),
            record=False,
        )
        h = s.generate_reply(user_input="do fictional action")
        await until(lambda: e.endpoint.wires and e.endpoint.wires[0].sent)
        w = e.endpoint.wires[0]
        w.feed(
            tool_call={
                "function_calls": [
                    {"id": "one", "name": "fictional_action", "args": {"name": "once"}}
                ]
            },
            server_content={"turn_complete": True},
            usage_metadata=usage(),
        )
        await asyncio.wait_for(started.wait(), 5)
        w.feed(usage_metadata=expensive_usage())
        await until(lambda: w.closed)
        release.set()
        await asyncio.wait_for(h, 5)
        assert effects == ["once"]
        assert not any(k == "tool" for k, _ in w.sent)
        assert e.endpoint.clients == 1
    finally:
        release.set()
        await s.aclose()
        await e.model.aclose()
