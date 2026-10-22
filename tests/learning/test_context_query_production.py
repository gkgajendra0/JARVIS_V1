import asyncio
import json
from types import SimpleNamespace

import pytest
from context_query_helpers import context_session, seed_item
from livekit import rtc
from livekit.agents import llm
from livekit.agents.llm.utils import prepare_function_arguments
from livekit.plugins.google.utils import create_tools_config
from test_context_query_lifecycle import Sink
from test_production import _session_pair, capability

from jarvis.config import JarvisConfig
from jarvis.conversation import ConversationRole
from jarvis.memory.retrieval import SemanticRetrievalService
from jarvis.personal_learning_scope import SUPPRESSION_KEYS
from jarvis.voice.agent import JarvisVoiceAgent
from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.personal_context import PersonalContextAgentTools

TOOL = "read_personal_context_for_question"


@pytest.mark.asyncio
@pytest.mark.parametrize("json_schema", [True, False])
async def test_pinned_gemini_schema_and_raw_binding_preserve_strict_local_attempts(
    learning, json_schema, caplog
):
    await seed_item(learning)
    async with context_session(learning) as (s, _, _):
        tool = {t.id: t for t in PersonalContextAgentTools(s).tools}[TOOL]
        schema = tool.info.raw_schema["parameters"]
        assert (
            set(schema["properties"]) == {"requests"}
            and schema["additionalProperties"] is False
        )
        assert (
            set(
                schema["properties"]["requests"]["items"]["properties"]["scope_key"][
                    "enum"
                ]
            )
            == SUPPRESSION_KEYS
        )
        declared, _ = create_tools_config(
            llm.ToolContext([tool]), use_parameters_json_schema=json_schema
        )
        assert declared[0].function_declarations[0].name == TOOL
        for payload in (
            {"requests": [{"scope_key": "goal", "target_quote": None}]},
            {"requests": [], "owner": "PRIVATE-CANARY"},
            {"requests": "PRIVATE-CANARY"},
        ):
            args, kwargs = prepare_function_arguments(
                fnc=tool, json_arguments=json.dumps(payload)
            )
            result = await tool(*args, **kwargs)
            assert result["status"] == "invalid_selection"
            assert "PRIVATE-CANARY" not in str(result) + caplog.text
        args, kwargs = prepare_function_arguments(
            fnc=tool, json_arguments={"requests": [{"scope_key": "owned_item.vehicle"}]}
        )
        assert (await tool(*args, **kwargs))["status"] == "invalid_selection"


@pytest.mark.asyncio
@pytest.mark.parametrize("delegated", [False, True])
async def test_tool_and_instruction_composition_agree_with_actual_mode(
    learning, delegated
):
    async with context_session(learning, delegated=delegated) as (s, _, _):
        tools = PersonalContextAgentTools(s).tools
        assert (TOOL in {t.id for t in tools}) is delegated
        agent = JarvisVoiceAgent(
            tools=tools, personal_learning_mode="apply" if delegated else "off"
        )
        assert (TOOL in agent.instructions) is delegated
        assert (
            "correct_memory" in agent.instructions
            and "personal_context_catalog" in agent.instructions
        )
        fallback = JarvisVoiceAgent(
            tools=[t for t in tools if t.id != TOOL], personal_learning_mode="apply"
        )
        assert TOOL not in fallback.instructions
    assert TOOL not in JarvisVoiceAgent().instructions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    ["What vehicles do I own?", "Meri gaadiyan kaunsi hain?", "मेरी गाड़ियाँ कौन सी हैं?"],
)
async def test_normal_controller_routes_registered_query_and_guarded_audio(
    learning, authority_parts, question
):
    await seed_item(learning, "City")
    await seed_item(learning, "Nexon")
    for i in range(5):
        await seed_item(learning, f"Phone{i}", "device")
    config = JarvisConfig(personal_learning_mode="apply")
    capabilities = capability(authority_parts.broker)
    capabilities._personal_learning_authority = learning.authority
    session, bridge = _session_pair()
    sink = Sink()
    controller = CanonicalActiveSpeakerRuntimeController(
        config,
        SimpleNamespace(output=sink),
        session_factory=lambda config: (session, bridge),
        memory_runtime=SimpleNamespace(
            service=learning.service,
            retrieval=SemanticRetrievalService(learning.reader),
        ),
        capability_runtime=capabilities,
    )
    controller._learning_grant = learning.grant
    controller._active_end = asyncio.Event()
    controller._session_factory(config)
    bridge.conversation.start()
    bridge.conversation.accept_turn(ConversationRole.USER, question)
    output = controller._session_audio_output(bridge, sink)
    try:
        tools = controller._vision_tools.tools
        agent = JarvisVoiceAgent(tools=tools, personal_learning_mode="apply")
        tool = {t.id: t for t in agent.tools}[TOOL]
        args, kwargs = prepare_function_arguments(
            fnc=tool, json_arguments={"requests": [{"scope_key": "owned_item.vehicle"}]}
        )
        result = await tool(*args, **kwargs)
        assert result["status"] == "selected" and len(result["facts"]) == 2
        assert "Phone" not in str(result)
        await output.capture_frame(rtc.AudioFrame.create(16000, 1, 160))
        assert len(sink.frames) == 1
        controller._personal_context.playback_finished()
        controller._personal_context.response_finished()
        assert controller._active_end.is_set()
    finally:
        output.detach()
        controller._cancel_timeout()
