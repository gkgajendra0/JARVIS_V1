"""Production voice instruction assembly for the controlled-text findings.

These verify the model contract, not the quality of generated recommendations.
"""

import pytest
from livekit.agents import function_tool

from jarvis.voice.agent import JarvisVoiceAgent


def voice_instructions(
    *, personal=True, project=True, query=True, learning_mode="apply"
):
    names = []
    if personal:
        names.extend(
            (
                "personal_context_catalog",
                "read_personal_context",
            )
        )
        if query:
            names.append("read_personal_context_for_question")
    if project:
        names.append("prepare_project_turn")

    async def unused_fixture_tool():
        return {}

    tools = [function_tool(unused_fixture_tool, name=name) for name in names]
    agent = JarvisVoiceAgent(tools=tools, personal_learning_mode=learning_mode)
    return " ".join(agent.instructions.split())


def test_voice_advice_requests_relevant_personal_facts_without_a_reminder():
    instructions = voice_instructions()
    assert "advice, a recommendation, a choice or a plan" in instructions
    assert "even when the request does not mention them" in instructions
    assert (
        "general knowledge alone does not make the evidence sufficient" in instructions
    )
    assert "do not repeat a successful lookup" in instructions
    assert "explain trade-offs" in instructions


def test_voice_named_subject_outweighs_unrelated_active_project():
    instructions = voice_instructions()
    assert "explicitly names" in instructions
    assert (
        "controls the answer, even when it differs from the selected project"
        in instructions
    )
    assert "a search hit is relevant only if it is about that subject" in instructions
    assert "ask one short question naming the candidates" in instructions
    assert "Do not mention unrelated project details" in instructions


def test_voice_distinguishes_category_absence_from_an_incomplete_lookup():
    instructions = voice_instructions()
    assert (
        "Use the matched categories even when another category has no match"
        in instructions
    )
    assert "no_match means nothing saved in that category only" in instructions
    assert "not_completed or not_checked means you could not check" in instructions
    assert "never say those facts are missing" in instructions


def test_memory_guidance_is_only_advertised_with_its_tools():
    personal_only = voice_instructions(project=False)
    project_only = voice_instructions(personal=False)
    neither = voice_instructions(personal=False, project=False)
    assert "read_personal_context_for_question" in personal_only
    assert "selected project is background" not in personal_only
    assert "selected project is background" in project_only
    assert "read_personal_context_for_question" not in project_only
    assert "selected project is background" not in neither
    assert "read_personal_context_for_question" not in neither


@pytest.mark.parametrize("query, learning_mode", [(False, "apply"), (True, "off")])
def test_legacy_and_learning_off_keep_the_catalog_read_path(query, learning_mode):
    instructions = voice_instructions(query=query, learning_mode=learning_mode)
    assert "personal_context_catalog, then read_personal_context" in instructions
    assert "read_personal_context_for_question" not in instructions
    assert "not_completed or not_checked" not in instructions
