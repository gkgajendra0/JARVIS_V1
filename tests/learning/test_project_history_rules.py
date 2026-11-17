"""How Gemini is told to read saved project history (Zanskar live test).

Live run 2026-11-16 on 6a48b050: with the owner's correction "I misspoke
earlier. The campsite was always Riverside Camp, not Lakeview Camp." preloaded,
Gemini still called Lakeview "the original plan"; its own saved reply saying so
was preloaded next wake; and "help me pack" ignored the saved Thar and
Riverside. The rows stay raw; every block of history Gemini receives (wake
preload, prepared turn, search) now carries HISTORY_RULES.

These tests prove what Gemini is GIVEN, with real storage and routing. Whether
Gemini then answers correctly is proven only by the live voice retest.
"""

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import Wake
from test_project_voice_fast_path import FastWake

from jarvis.voice.project_voice import _GUIDANCE, HISTORY_RULES
from jarvis.voice.voice_output_safety import non_user_facing_reason

lab = project_voice_tests.lab

CORRECTION = (
    "I misspoke earlier. The campsite was always Riverside Camp, not Lakeview Camp."
)
CHANGE = "Change of plan. We're taking the Fortuner."
WRONG_REPLY = "The original plan was to stay at Lakeview Camp."


async def zanskar(lab):
    """Fictional trip: a genuine vehicle change and a campsite correction,
    plus a wrong Jarvis reply saved as history (the live echo)."""
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask(
        "Create a project called Kargil trip.", "Created project Kargil trip."
    )
    await wake.ask("For the Kargil trip, we are taking the Bolero.", "Understood.")
    await wake.ask("Our campsite will be Lakeview Camp.", "Understood.")
    await wake.ask(CHANGE, "Understood, the Fortuner.")
    await wake.ask(CORRECTION, "Understood, Riverside Camp.")
    await wake.ask("What was the original plan?", WRONG_REPLY)
    wake.close()
    return voice


def lines_of(context):
    return [line for line in context.splitlines() if line.startswith("- ")]


@pytest.mark.asyncio
async def test_correction_reaches_gemini_with_the_rule_that_governs_it(lab):
    voice = await zanskar(lab)
    wake = FastWake(voice)  # a fresh Gemini session, as after a restart
    await wake.preload()
    (context,) = wake.agent.injected()
    rows = lines_of(context)
    # The owner's exact correction, labelled as the owner's, after the value
    # it corrects.
    correction = next(
        i for i, r in enumerate(rows) if r.endswith("owner: " + CORRECTION)
    )
    lakeview = next(
        i for i, r in enumerate(rows) if "owner: Our campsite will be Lakeview" in r
    )
    assert lakeview < correction
    # The rule that makes Lakeview "never the plan", before any row.
    rule_at = context.index("How to read it: " + HISTORY_RULES)
    assert rule_at < context.index(rows[0])
    assert "misspoke" in HISTORY_RULES and "never the plan" in HISTORY_RULES
    assert "do not call it original, initial or former" in HISTORY_RULES
    # Jarvis's wrong saved reply is still evidence of what was said, but is
    # labelled Jarvis and the rules say Jarvis rows never prove a plan.
    assert any(r.endswith("Jarvis: " + WRONG_REPLY) for r in rows)
    assert not any(r.endswith("owner: " + WRONG_REPLY) for r in rows)
    assert (
        "Jarvis rows only show what Jarvis said and never prove a plan" in HISTORY_RULES
    )
    wake.close()


@pytest.mark.asyncio
async def test_genuine_change_keeps_the_earlier_value_as_a_former_plan(lab):
    voice = await zanskar(lab)
    wake = FastWake(voice)
    wake.speech()
    wake.transcript("Which vehicle was the original plan?")
    found = await wake.turns.search_history("Bolero")
    owner = [r["text"] for r in found["history"] if r["role"] == "owner"]
    assert "For the Kargil trip, we are taking the Bolero." in owner
    # Search on one word still brings the old value; the change itself is
    # preloaded (newest rows) and names only the new vehicle.
    assert found["history_rules"] == HISTORY_RULES
    assert (
        "Only a change of plan makes the earlier value a former plan" in HISTORY_RULES
    )
    # The old instruction to call every disagreement a change is gone.
    assert "mention that it changed" not in found["guidance"]
    assert "newest owner statement is current" in found["guidance"]
    wake.close()
    wake = FastWake(voice)  # a fresh session: nothing delivered yet
    await wake.preload()
    (context,) = wake.agent.injected()
    rows = lines_of(context)
    bolero = next(i for i, r in enumerate(rows) if "taking the Bolero" in r)
    change = next(i for i, r in enumerate(rows) if r.endswith("owner: " + CHANGE))
    assert bolero < change  # oldest first: the change is the newer statement
    wake.close()


@pytest.mark.asyncio
async def test_practical_request_has_current_decisions_and_the_rule_to_use_them(lab):
    voice = await zanskar(lab)
    tool_calls = voice.metrics.delivered
    wake = FastWake(voice)
    await wake.preload()
    (context,) = wake.agent.injected()
    assert "owner: " + CHANGE in context
    assert "owner: " + CORRECTION in context
    assert "practical help with this project (packing, planning) without asking" in (
        HISTORY_RULES
    )
    assert "ask only for what is missing" in HISTORY_RULES
    # "Help me pack" is an ordinary turn: answered from the preload, no tool
    # call or second generation needed to get the saved decisions.
    await wake.fast(
        "Help me pack for the trip.",
        "For the Fortuner and Riverside Camp: warm layers and a tarp.",
    )
    assert voice.metrics.delivered == tool_calls
    assert wake.session.replies == []
    wake.close()


@pytest.mark.asyncio
async def test_tool_path_turn_carries_the_rules_too(lab):
    voice = await zanskar(lab)
    wake = Wake(voice)
    result = await wake.ask("Help me pack for the Kargil trip.")
    assert result["history_rules"] == HISTORY_RULES
    assert result["guidance"] == _GUIDANCE  # unchanged size budget
    wake.close()


def test_rules_are_internal_text_never_spoken_or_saved():
    assert non_user_facing_reason(HISTORY_RULES) is not None
    assert non_user_facing_reason("Sure. " + HISTORY_RULES[:200]) is not None
    # An ordinary answer about the same trip is not mistaken for the rules.
    assert (
        non_user_facing_reason(
            "You're taking the Fortuner and staying at Riverside Camp."
        )
        is None
    )
