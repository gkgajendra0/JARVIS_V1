"""The isolated voice labs expose only their exact tools to Gemini.

Regression for the 2 Nov baseline run at 757ea68e: "Create project called
Nepal trip" reached Jarvis Hands (file operations, make_directory) because the
lab still exposed the normal production tool set.
"""

import inspect
from types import SimpleNamespace

import pytest

from jarvis.voice.project_voice_lab import (
    BASELINE_TOOLS,
    PROJECT_MEMORY_TOOLS,
    PROJECT_TOOLS,
    lab_tool_allowlist,
    run_voice_lab,
)
from jarvis.voice.runtime import VoiceRuntimeController, restrict_tools

# Every tool id the normal production session can declare (voice/*_tools.py).
PRODUCTION_ACTION_TOOLS = {
    # Hands and desktop/file control
    "use_computer",
    "computer_action",
    "control_computer",
    # Local reads / self-awareness (capability runtime)
    "inspect_local",
    "list_self_components",
    "get_self_system_health",
    "get_self_component_health",
    "get_self_component_details",
    "query_self_operational_evidence",
    "list_similar_self_incidents",
    "list_self_incidents",
    # Capability acquisition, engineering and background work
    "start_capability_acquisition",
    "activate_acquired_capability",
    "disable_acquired_capability",
    "start_engineering_change",
    "execute_change_promotion",
    "start_background_work",
    "cancel_background_work",
    # Research, vision and canonical-memory mutation
    "search_web",
    "inspect_vision",
    "switch_vision_camera",
    "control_vision_follow",
    "remember_memory",
    "correct_memory",
    "forget_memory",
    "recall_memory",
    "inspect_memory",
    "personal_context_catalog",
    "read_personal_context",
    "prepare_conversation_topic",
}


def fake_tools(names):
    return [SimpleNamespace(id=name) for name in sorted(names)]


@pytest.mark.parametrize("baseline", [True, False])
def test_lab_modes_expose_only_their_exact_tools(baseline):
    allowlist = lab_tool_allowlist(baseline=baseline)
    offered = fake_tools(PRODUCTION_ACTION_TOOLS | {"enter_standby"} | PROJECT_TOOLS)
    offered.append(SimpleNamespace())  # a tool without a declared id
    kept = {tool.id for tool in restrict_tools(offered, allowlist)}
    assert kept == set(allowlist)
    assert not kept & PRODUCTION_ACTION_TOOLS
    expected = {"enter_standby"} if baseline else {"enter_standby", *PROJECT_TOOLS}
    assert kept == expected


def test_allowlists_are_disjoint_from_every_action_tool():
    assert BASELINE_TOOLS == frozenset({"enter_standby"})
    assert PROJECT_MEMORY_TOOLS == BASELINE_TOOLS | PROJECT_TOOLS
    assert PROJECT_TOOLS == {
        "prepare_project_turn",
        "search_project_history",
        "forget_saved_history",
    }
    assert not PROJECT_MEMORY_TOOLS & PRODUCTION_ACTION_TOOLS


def test_no_allowlist_leaves_normal_jarvis_unchanged():
    tools = fake_tools(PRODUCTION_ACTION_TOOLS)
    assert restrict_tools(tools, None) is tools
    signature = inspect.signature(VoiceRuntimeController.__init__)
    assert signature.parameters["tool_allowlist"].default is None


@pytest.mark.parametrize("bad", [{"enter_standby"}, ["enter_standby"], frozenset({""})])
def test_controller_rejects_an_ambiguous_allowlist(bad):
    with pytest.raises(TypeError, match="tool_allowlist"):
        VoiceRuntimeController(None, None, tool_allowlist=bad)


def test_restriction_sits_between_tool_assembly_and_the_realtime_agent():
    source = inspect.getsource(VoiceRuntimeController._run_one_session_owned)
    restrict = source.index("tools = restrict_tools(tools, self._tool_allowlist)")
    assembled = source.index("tools.extend(standby_tools.tools)")
    factory = source.index("tools = list(session_tool_factory(bridge.conversation))")
    agent = source.index("agent = JarvisVoiceAgent(")
    assert factory < assembled < restrict < agent
    # It is the only agent in the controller that receives tools at all.
    module = inspect.getsource(inspect.getmodule(VoiceRuntimeController))
    assert module.count("tools=tools") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("baseline", [True, False])
async def test_both_lab_modes_pass_the_allowlist_to_the_runtime(tmp_path, baseline):
    seen = {}

    class Runtime:
        async def run(self):
            return None

    def builder(config, **kwargs):
        seen.update(kwargs)
        return Runtime()

    await run_voice_lab(object(), tmp_path, baseline=baseline, runtime_builder=builder)
    assert seen["tool_allowlist"] == lab_tool_allowlist(baseline=baseline)
    assert ("project_memory_factory" in seen) is (not baseline)


def test_production_entry_point_passes_no_allowlist():
    import jarvis.voice.production_runtime as production

    for entry in (production.main, production._run_from_configuration):
        assert "tool_allowlist" not in inspect.getsource(entry)
    signature = inspect.signature(production.build_production_voice_runtime)
    assert signature.parameters["tool_allowlist"].default is None


def test_meter_flags_any_tool_call_outside_the_allowlist(tmp_path):
    import json

    from jarvis.conversation import ConversationSession
    from jarvis.voice.voice_usage_meter import VoiceUsageMeter

    handlers, closers = {}, []
    session = SimpleNamespace(
        on=lambda name, handler: handlers.__setitem__(name, handler)
    )
    conversation = ConversationSession()
    conversation.start()
    bridge = SimpleNamespace(
        conversation=conversation, add_close_observer=closers.append
    )
    meter = VoiceUsageMeter(
        tmp_path / "u.jsonl", mode="project_memory", allowed_tools=PROJECT_MEMORY_TOOLS
    )
    meter.attach(session, bridge)
    handlers["function_tools_executed"](
        SimpleNamespace(
            function_calls=[
                SimpleNamespace(name="prepare_project_turn"),
                SimpleNamespace(name="use_computer"),
            ]
        )
    )
    closers[0]()
    row = json.loads((tmp_path / "u.jsonl").read_text())
    assert row["disallowed_tool_calls"] == 1
    assert row["tool_calls"] == {"prepare_project_turn": 1, "use_computer": 1}


def _real_livekit():
    from livekit.agents import function_tool

    return inspect.isfunction(function_tool)


@pytest.mark.skipif(not _real_livekit(), reason="needs the real LiveKit SDK")
def test_real_decorated_tools_are_filtered_by_their_declared_ids():
    from jarvis.voice.project_voice import VoiceProjectTools
    from jarvis.voice.standby_tools import StandbyAgentTools

    real = [*StandbyAgentTools(lambda: True).tools, *VoiceProjectTools(object()).tools]
    assert {t.id for t in restrict_tools(real, PROJECT_MEMORY_TOOLS)} == {
        "enter_standby",
        *PROJECT_TOOLS,
    }
    assert [t.id for t in restrict_tools(real, BASELINE_TOOLS)] == ["enter_standby"]


def _declared_voice_tool_ids():
    """Every function_tool the voice package declares, found from source."""
    import ast
    import re
    from pathlib import Path

    from jarvis import voice

    ids = set()
    for path in Path(voice.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                text = ast.unparse(decorator)
                if "function_tool" not in text:
                    continue
                named = re.search(r"['\"]name['\"]:\s*['\"](\w+)", text)
                ids.add(named.group(1) if named else node.name)
    return ids


def test_every_declared_voice_tool_except_the_allowlist_is_withheld():
    declared = _declared_voice_tool_ids()
    # Sanity: discovery finds the tools from the failing run and the lab tools.
    assert {"use_computer", "computer_action", "enter_standby"} <= declared
    assert PROJECT_MEMORY_TOOLS <= declared  # the lab's names are real tool ids
    for baseline in (True, False):
        allowlist = lab_tool_allowlist(baseline=baseline)
        kept = {t.id for t in restrict_tools(fake_tools(declared), allowlist)}
        assert kept == set(allowlist)
        assert len(declared - kept) >= 40
