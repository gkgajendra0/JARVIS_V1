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
@pytest.mark.parametrize("operational", [False, True])
async def test_silent_tool_receipt_closes_connection_and_accepts_new_request(
    tmp_path, operational
):
    from tests.gemini_operational.helpers import (
        environment as operational_environment,
    )
    from tests.gemini_operational.helpers import (
        usage,
    )

    env = operational_environment(tmp_path) if operational else environment(tmp_path)
    usage_event = usage if operational else raw_usage
    calls = []

    @llm.function_tool
    async def wait_for_instruction() -> None:
        """Wait for a new confirmed instruction without another automatic reply."""
        calls.append("suppressed")
        raise llm.StopResponse()

    session = AgentSession(
        llm=env.model, vad=None, turn_handling=TurnHandlingOptions(turn_detection=None)
    )
    try:
        await session.start(
            agent=Agent(
                instructions="Fictional test only",
                llm=env.model,
                tools=[wait_for_instruction],
            ),
            record=False,
        )
        first = session.generate_reply(user_input="Fictional missing instruction")
        await until(lambda: env.endpoint.wires and len(env.endpoint.wires[0].sent) >= 2)
        wire = env.endpoint.wires[0]
        wire.feed(
            tool_call={
                "function_calls": [
                    {
                        "id": "silent-1",
                        "name": "wait_for_instruction",
                        "args": {},
                    }
                ]
            },
            server_content={"turn_complete": True},
            usage_metadata=usage_event(),
        )
        await until(lambda: wire.closed)
        await asyncio.wait_for(first, 5)
        assert first.exception() is None
        assert calls == ["suppressed"]
        assert not any(kind == "tool" for kind, _ in wire.sent)
        assert env.model.sessions[-1]._pending_tools == {}

        second = session.generate_reply(user_input="New confirmed request")
        await until(lambda: len(env.endpoint.wires) == 2)
        env.endpoint.wires[1].feed(
            server_content={
                "output_transcription": {"text": "New request accepted"},
                "turn_complete": True,
            },
            usage_metadata=usage_event(),
        )
        await asyncio.wait_for(second, 5)
        assert second.exception() is None
        assert calls == ["suppressed"]
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


@pytest.mark.asyncio
async def test_real_local_vad_and_audio_pipeline_drive_manual_activity_and_endpoint(
    tmp_path,
):
    from livekit import rtc
    from tests.gemini_live.vad_helpers import ActivityVAD

    from jarvis.voice.audio import SessionAudioInput

    env = environment(tmp_path)
    local_vad = ActivityVAD()
    session = AgentSession(
        llm=env.model,
        vad=local_vad,
        turn_handling=TurnHandlingOptions(
            turn_detection="vad",
            endpointing={"mode": "fixed", "min_delay": 0.8, "max_delay": 3},
            interruption={"enabled": True},
            preemptive_generation={"enabled": False},
        ),
    )
    source = SessionAudioInput()
    session.input.audio = source
    received = []
    session.on("conversation_item_added", received.append)

    def pcm(active=False):
        return rtc.AudioFrame(
            data=(bytes([1, 0]) if active else bytes(2)) * 960,
            sample_rate=48000,
            num_channels=1,
            samples_per_channel=960,
        )

    try:
        await session.start(
            agent=Agent(instructions="Fictional local VAD check", llm=env.model),
            record=False,
        )
        source.push_frame(pcm())
        await until(lambda: local_vad.frames >= 1)
        assert env.endpoint.clients == 0
        source.push_frame(pcm(True))
        await until(lambda: env.endpoint.wires)
        source.push_frame(pcm())
        await until(
            lambda: any(
                kind == "input" and item.activity_end is not None
                for kind, item in env.endpoint.wires[0].sent
            )
        )
        assert any(
            kind == "input" and item.audio is not None
            for kind, item in env.endpoint.wires[0].sent
        )
        env.endpoint.wires[0].feed(
            server_content={
                "input_transcription": {"text": "मेरी गाड़ी", "finished": True},
                "output_transcription": {"text": "आपकी काल्पनिक City"},
                "turn_complete": True,
            },
            usage_metadata=raw_usage(),
        )
        await until(
            lambda: any(
                e.item.type == "message"
                and e.item.role == "assistant"
                and e.item.text_content == "आपकी काल्पनिक City"
                for e in received
            )
        )
    finally:
        source.close()
        await session.aclose()
        await env.model.aclose()


@pytest.mark.asyncio
async def test_real_agent_session_cancellation_with_blocked_send_executes_no_action(
    tmp_path,
):
    from contextlib import asynccontextmanager

    env = environment(tmp_path)
    effects = []
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

    @llm.function_tool
    async def fictional_action(name: str) -> str:
        """Perform a reversible fictional test action."""
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
        await asyncio.wait_for(entered.wait(), 5)
        env.endpoint.wires[0].feed(
            tool_call={
                "function_calls": [
                    {
                        "id": "cancel-before-release",
                        "name": "fictional_action",
                        "args": {"name": "once"},
                    }
                ]
            },
            tool_call_cancellation={"ids": ["cancel-before-release"]},
        )
        await asyncio.wait_for(handle, 5)
        assert effects == []
        await until(lambda: env.endpoint.wires[0].closed)
        await until(lambda: env.runtime.paid_budget.status().unknown_reservations == 1)
    finally:
        gate.set()
        await session.aclose()
        await env.model.aclose()


@pytest.mark.asyncio
async def test_real_agent_session_uncertain_tool_reply_never_reexecutes_action(
    tmp_path,
):
    env = environment(tmp_path)
    effects = []

    @llm.function_tool
    async def fictional_action(name: str) -> str:
        """Perform a reversible fictional test action."""
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
        await until(lambda: env.endpoint.wires)
        wire = env.endpoint.wires[0]
        wire.feed(
            tool_call={
                "function_calls": [
                    {
                        "id": "uncertain-reply",
                        "name": "fictional_action",
                        "args": {"name": "once"},
                    }
                ]
            },
            server_content={"turn_complete": True},
            usage_metadata=raw_usage(),
        )
        await until(lambda: any(kind == "tool" for kind, _ in wire.sent))
        wire.feed(go_away={"time_left": "1s"})
        await asyncio.wait_for(handle, 5)
        await until(lambda: env.runtime.paid_budget.status().unknown_reservations == 1)
        assert effects == ["once"] and env.endpoint.clients == 1
    finally:
        await session.aclose()
        await env.model.aclose()
