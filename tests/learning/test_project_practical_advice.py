"""Practical help uses the current project's saved decisions (Munnar retest).

Live run 2026-11-17 on c4259775: in one wake Gemini correctly said we drive
the Creta (originally the Innova) and stay at Hilltop Cottage, then answered
"help me pack" with a generic list. The history rule to apply decisions rode
only in the preload, while the standing instructions said "Connect facts only
if a saved row states the link" and sent personalized advice to personal
memory, which holds no trip facts.

The standing instructions now keep the no-invented-links rule as a limit on
claims and say practical help lets current decisions change the advice and
asks about what is not saved. These tests prove what Gemini is GIVEN; whether
the advice changes is proven only by the live voice retest.
"""

from types import SimpleNamespace

import pytest

from jarvis.voice import agent as agent_module
from jarvis.voice.agent import PROJECT_MEMORY_INSTRUCTIONS, JarvisVoiceAgent

RULES = " ".join(PROJECT_MEMORY_INSTRUCTIONS.split())

PRODUCTION_TOOLS = (
    "personal_context_catalog",
    "read_personal_context",
    "read_personal_context_for_question",
    "prepare_project_turn",
)


@pytest.fixture
def production_instructions(monkeypatch):
    """The instructions the production voice agent hands Gemini with project
    memory on and personal learning in apply mode (the installed settings)."""
    captured = {}

    def capture(self, *, instructions, tools, **_):
        captured["text"] = instructions

    monkeypatch.setattr(agent_module.Agent, "__init__", capture)
    JarvisVoiceAgent(
        tools=[SimpleNamespace(id=name) for name in PRODUCTION_TOOLS],
        personal_learning_mode="apply",
    )
    return " ".join(captured["text"].split())


def test_no_invented_links_rule_is_kept_as_a_limit_on_claims():
    assert "Connect facts only if a saved row states the link" in RULES
    assert 'present owner reports as such ("you said ...")' in RULES
    assert "That limits claims, not help" in RULES


def test_practical_help_applies_current_decisions_and_asks_about_the_rest():
    assert "practical help with the current project (packing, planning)" in RULES
    assert "relevant current decisions (vehicle, stay, dates)" in RULES
    # The pass condition: decisions change the advice, not just get named.
    assert "change the advice itself" in RULES
    assert "ask about what is not saved" in RULES


def test_personal_memory_route_does_not_replace_project_history(
    production_instructions,
):
    text = production_instructions
    advice_route = text.index("For ordinary personal advice, request only")
    practical = text.index("for practical help with the current project")
    adds = text.index("Personal memory adds to this history, never replaces it")
    # Both routes reach Gemini; the project rule comes after the personal
    # advice route, so it is the last word on trip advice.
    assert advice_route < practical < adds
    assert "Connect facts only if a saved row states the link" in text


def test_instruction_budget_stays_bounded():
    # Sent with every response in project mode: 1,212 chars before this
    # change, +269 for the practical-help rule. The named-subject and
    # clarification rules (#328) fit by compacting, not by raising the cap.
    assert len(PROJECT_MEMORY_INSTRUCTIONS) <= 1500
