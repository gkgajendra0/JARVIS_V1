from __future__ import annotations

import importlib
import importlib.util
import inspect

from jarvis.voice import agent as agent_module
from jarvis.voice import runtime as runtime_module


def test_semantic_standby_tool_module_exists_and_exposes_enter_standby() -> None:
    spec = importlib.util.find_spec("jarvis.voice.standby_tools")
    assert spec is not None

    module = importlib.import_module("jarvis.voice.standby_tools")
    assert hasattr(module, "StandbyAgentTools")
    source = inspect.getsource(module.StandbyAgentTools)
    assert "enter_standby" in source
    assert "function_tool" in source


def test_voice_runtime_no_longer_uses_hardcoded_exit_phrase_matcher() -> None:
    source = inspect.getsource(runtime_module)
    assert "_EXIT_CORES" not in source
    assert "_EXIT_PREFIXES" not in source
    assert "_EXIT_SUFFIXES" not in source
    assert "_is_exit_intent" not in source


def test_voice_agent_contract_separates_jarvis_standby_from_computer_power() -> None:
    instructions = agent_module.INSTRUCTIONS.casefold()
    assert "enter_standby" in instructions
    assert "standby" in instructions
    assert "computer" in instructions
    assert "sleep" in instructions
    assert "use_computer" in instructions
