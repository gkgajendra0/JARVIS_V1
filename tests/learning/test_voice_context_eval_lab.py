"""Isolated VOICE check of the travel case: fictional seed in the text lab,
then the production voice runtime with saved personal context in the same
isolated lab (``-SeedVoiceEval`` then ``-ResumeLab -PersonalContext``)."""

import json
import sys
from dataclasses import replace

import pytest
from livekit.agents import function_tool
from test_project_memory_acceptance_lab import (
    empty_access as empty_access,  # noqa: PLC0414
)
from test_project_personal_acceptance import runtime as acceptance_runtime

from jarvis.config import JarvisConfig
from jarvis.voice.agent import JarvisVoiceAgent
from jarvis.voice.project_personal_context_eval import seed_voice_eval
from jarvis.voice.project_voice_lab import (
    PERSONAL_READ_TOOLS,
    PROJECT_MEMORY_TOOLS,
    lab_tool_allowlist,
    voice_lab_config,
)


@pytest.mark.asyncio
async def test_seed_saves_the_fictional_setup_without_any_model_call(
    empty_access, authority_parts, tmp_path
):
    memory, capability, coordinator, _, _ = acceptance_runtime(
        empty_access, authority_parts
    )
    try:
        summary = await seed_voice_eval(
            tmp_path, memory=memory, capability=capability, access=empty_access
        )
    finally:
        coordinator.invalidate("test_end")
    assert set(summary["projects"]) == {"Spiti Valley trip", "Home errands"}
    catalog = await empty_access.catalog()
    selected = [
        e
        for e in catalog.entries
        if e.selection.project_id == catalog.current.project_id
    ]
    assert {e.title for e in selected} == {"Spiti Valley trip"}
    record = (await memory.service.inspect_exact(predicate="vehicles")).record
    assert record.assertion_id == summary["vehicles_assertion_id"]
    assert (
        record.value == "a Mahindra Thar diesel 4x4 and an Ather 450X electric scooter"
    )
    written = json.loads((tmp_path / "voice-eval-seed.json").read_text())
    assert written["questions"][0].startswith("I'm going to Gokarna")
    with pytest.raises(PermissionError):  # never seeds over existing data
        await seed_voice_eval(
            tmp_path, memory=memory, capability=capability, access=empty_access
        )


def test_personal_mode_matches_production_learning_apply():
    base = replace(JarvisConfig(), ai_provider="gemini")
    off = voice_lab_config(base)
    on = voice_lab_config(base, personal=True)
    assert (off.personal_context_mode, off.personal_learning_mode) == ("off", "off")
    assert (on.personal_context_mode, on.personal_learning_mode) == ("apply", "apply")
    assert on.gemini_fallback.enabled is False  # Free lane only
    assert on.personal_learning_reenable_categories == ()


def test_personal_mode_adds_read_tools_only():
    assert lab_tool_allowlist(baseline=False) == PROJECT_MEMORY_TOOLS
    allowed = lab_tool_allowlist(baseline=False, personal=True)
    assert allowed == PROJECT_MEMORY_TOOLS | PERSONAL_READ_TOOLS
    assert not {"remember_memory", "correct_memory", "forget_memory"} & allowed
    assert lab_tool_allowlist(baseline=True, personal=True) == {"enter_standby"}


def test_the_voice_agent_in_this_mode_carries_the_pr_328_guidance():
    async def unused():
        return {}

    names = sorted(lab_tool_allowlist(baseline=False, personal=True))
    agent = JarvisVoiceAgent(
        tools=[function_tool(unused, name=n) for n in names],
        personal_learning_mode="apply",
    )
    text = " ".join(agent.instructions.split())
    assert "controls the answer, even when it differs from the selected project" in text
    assert "ask one short question naming the candidates" in text
    assert "even when the request does not mention them" in text
    assert "not_completed or not_checked means you could not check" in text


@pytest.mark.parametrize(
    ("module", "argv", "message"),
    [
        (
            "jarvis.voice.project_voice_lab",
            ["--personal-context", "--baseline"],
            "--personal-context needs project memory",
        ),
        (
            "jarvis.voice.project_memory_lab",
            ["--seed-voice-eval", "--context-eval", "--model", "m"],
            "voice evaluation seeding requires a fresh standalone lab",
        ),
    ],
)
def test_incompatible_flags_are_refused(
    tmp_path, monkeypatch, capsys, module, argv, message
):
    import importlib
    import types

    monkeypatch.setitem(sys.modules, "msvcrt", types.ModuleType("msvcrt"))
    main = importlib.import_module(module).main
    monkeypatch.setattr(
        sys,
        "argv",
        ["lab", "--lab-root", str(tmp_path / "absent"), "--source-commit", "a" * 40]
        + argv,
    )
    with pytest.raises(SystemExit):
        main()
    assert message in capsys.readouterr().err
    assert not (tmp_path / "absent").exists()
