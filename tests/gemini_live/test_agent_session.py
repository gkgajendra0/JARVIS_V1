"""Actual public AgentSession consumes the adapter; only network is synthetic."""

import asyncio

import pytest
from livekit.agents import Agent, AgentSession, TurnHandlingOptions, llm
from tests.gemini_live.helpers import environment, until
from tests.gemini_live.test_contract import raw_usage


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,answer",
    [
        ("मेरी गाड़ी कौन सी है?", "आपकी काल्पनिक City है"),
        ("Meri car kaunsi hai?", "Aapki fictional City hai"),
        ("Which car do I own?", "Your fictional car is City"),
    ],
)
async def test_real_agent_session_consumes_public_generation_streams(
    tmp_path, question, answer
):
    env = environment(tmp_path)
    session = AgentSession(
        llm=env.model, vad=None, turn_handling=TurnHandlingOptions(turn_detection=None)
    )
    received = []
    session.on("conversation_item_added", received.append)
    try:
        await session.start(
            agent=Agent(instructions="Use fictional facts", llm=env.model), record=False
        )
        handle = session.generate_reply(user_input=question)
        await until(lambda: env.endpoint.wires and len(env.endpoint.wires[0].sent) >= 2)
        env.endpoint.wires[0].feed(
            server_content={
                "output_transcription": {"text": answer},
                "turn_complete": True,
            },
            usage_metadata=raw_usage(),
        )
        await asyncio.wait_for(handle, 5)
        assert handle.exception() is None
        assert any(
            e.item.type == "message"
            and e.item.role == "assistant"
            and e.item.text_content == answer
            for e in received
        )
    finally:
        await session.aclose()
        await env.model.aclose()


@pytest.mark.asyncio
async def test_real_agent_session_executes_tool_once_and_reserves_its_reply(tmp_path):
    env = environment(tmp_path)
    effects = []

    @llm.function_tool
    async def fictional_action(name: str) -> str:
        """Record a fictional, reversible test action."""
        effects.append(name)
        return "done"

    session = AgentSession(
        llm=env.model, vad=None, turn_handling=TurnHandlingOptions(turn_detection=None)
    )
    try:
        await session.start(
            agent=Agent(
                instructions="Fictional test only",
                llm=env.model,
                tools=[fictional_action],
            ),
            record=False,
        )
        handle = session.generate_reply(user_input="Run the fictional action once")
        await until(lambda: env.endpoint.wires and len(env.endpoint.wires[0].sent) >= 2)
        wire = env.endpoint.wires[0]
        call = {
            "id": "actual-tool-1",
            "name": "fictional_action",
            "args": {"name": "once"},
        }
        wire.feed(
            tool_call={"function_calls": [call, call]},
            server_content={"turn_complete": True},
            usage_metadata=raw_usage(),
        )
        await until(lambda: any(kind == "tool" for kind, _ in wire.sent))
        assert effects == ["once"]
        assert env.runtime.paid_budget.status().reserved_inr_minor == 3993
        wire.feed(
            server_content={
                "output_transcription": {"text": "Done"},
                "turn_complete": True,
            },
            usage_metadata=raw_usage(),
        )
        await asyncio.wait_for(handle, 5)
        assert handle.exception() is None
        assert effects == ["once"] and env.endpoint.clients == 1
    finally:
        await session.aclose()
        await env.model.aclose()


@pytest.mark.asyncio
async def test_conflicting_tool_batch_cannot_partially_execute_actions(tmp_path):
    env = environment(tmp_path)
    effects = []

    @llm.function_tool
    async def fictional_action(name: str) -> str:
        """Record a fictional test action."""
        effects.append(name)
        return "done"

    session = AgentSession(
        llm=env.model, vad=None, turn_handling=TurnHandlingOptions(turn_detection=None)
    )
    try:
        await session.start(
            agent=Agent(
                instructions="Fictional only", llm=env.model, tools=[fictional_action]
            ),
            record=False,
        )
        handle = session.generate_reply(user_input="Fictional action")
        await until(lambda: env.endpoint.wires and len(env.endpoint.wires[0].sent) >= 2)
        env.endpoint.wires[0].feed(
            tool_call={
                "function_calls": [
                    {
                        "id": "conflict",
                        "name": "fictional_action",
                        "args": {"name": "first"},
                    },
                    {
                        "id": "conflict",
                        "name": "fictional_action",
                        "args": {"name": "different"},
                    },
                ]
            }
        )
        await until(lambda: env.endpoint.wires[0].closed)
        await asyncio.wait_for(handle, 5)
        assert effects == []
    finally:
        await session.aclose()
        await env.model.aclose()
