"""Earlier owner decisions survive newer chatter in the wake preload.

Munnar live test 2026-11-17 on 94c5196f: the vehicle change ("Change of plan.
We're taking the Creta.") and the stay correction ("I misspoke earlier. The
stay was always Hilltop Cottage, not Tea Valley Resort.") were saved before a
long wake in which follow-up questions and background speech were saved as
owner rows. The wake preload holds only the newest 12 rows, so neither
decision reached Gemini at the next wake, and "help me pack" was generic.

The preload now also carries earlier owner decisions (plan statements and
corrections; not questions, fragments or chatter) that newer turns pushed out.
These tests prove what Gemini is GIVEN, with real storage; whether the advice
changes is proven only by the live voice retest.
"""

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import Wake
from test_project_voice_fast_path import FastWake

from jarvis.voice import project_voice
from jarvis.voice.project_voice import _is_owner_decision

lab = project_voice_tests.lab

INNOVA = "For the Munnar trip, we're taking the Innova."
TEA_VALLEY = "We're staying at Tea Valley Resort."
CRETA = "Change of plan. We're taking the Creta."
HILLTOP = (
    "I misspoke earlier. The stay was always Hilltop Cottage, not Tea Valley Resort."
)
# What filled the recent history live: follow-up questions, background speech
# transcribed as the owner, fragments, and a control request.
CHATTER = [
    "Which vehicle are we taking for the Munnar trip?",
    "Okay, and what was the original plan?",
    "Where are we staying? And was Tea Valley Resort ever the plan?",
    "When did I tell you we were switching to the Creta?",
    "As of now, I have to report to M&D that we have nothing.",
    "We cannot afford anymore mistakes. I can't afford anymore mistakes.",
    "Apsara TV release",
    "prostituta",
    "health insurance or cash",
    "Remove all the projects.",
    "Rock Freedom",
    "extranjeros",
    "Nussschinken",
    "polsuelo",
]


async def munnar_then_chatter(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask(
        "Create a project called Munnar trip.", "Created project Munnar trip."
    )
    for line in (INNOVA, TEA_VALLEY, CRETA, HILLTOP):
        await wake.ask(line, "Understood.")
    wake.close()
    wake = Wake(voice)
    for line in CHATTER:
        await wake.ask(line, "Okay.")
    wake.close()
    return voice


def section(context, start, end=None):
    text = context.split(start, 1)[1]
    return text.split(end, 1)[0] if end else text


@pytest.mark.asyncio
async def test_decisions_pushed_out_of_the_recent_rows_still_reach_gemini(lab):
    voice = await munnar_then_chatter(lab)
    wake = FastWake(voice)
    await wake.preload()
    (context,) = wake.agent.injected()
    recent = section(context, "Recent history:")
    decisions = section(context, "Earlier owner decisions", "Recent history:")
    # The decisions are outside the newest 12 rows ...
    for line in (INNOVA, TEA_VALLEY, CRETA, HILLTOP):
        assert line not in recent
    # ... and still reach Gemini, oldest first, so the change and the
    # correction are the newer statements.
    order = [
        decisions.index(": " + line) for line in (INNOVA, TEA_VALLEY, CRETA, HILLTOP)
    ]
    assert order == sorted(order)
    # Chatter, questions and fragments are not promoted.
    for line in CHATTER:
        assert line not in decisions
    # The recent rows are unchanged: still the newest history.
    assert "owner: Nussschinken" in recent and "owner: polsuelo" in recent
    wake.close()


@pytest.mark.asyncio
async def test_practical_question_is_answered_from_the_preload_without_repeating_details(
    lab,
):
    voice = await munnar_then_chatter(lab)
    delivered = voice.metrics.delivered
    wake = FastWake(voice)
    await wake.preload()
    (context,) = wake.agent.injected()
    assert "owner: " + CRETA in context
    assert "owner (correction): " + HILLTOP in context
    # The owner does not repeat the car or the cottage; the ordinary fast path
    # answers from what was preloaded, with no tool call or second generation.
    await wake.fast(
        "Help me pack for the trip.",
        "Since you're driving the Creta, pack a car kit; ask the cottage about linen.",
    )
    assert voice.metrics.delivered == delivered
    assert wake.session.replies == []
    wake.close()


@pytest.mark.asyncio
async def test_decision_rows_are_not_sent_twice_in_one_session(lab):
    voice = await munnar_then_chatter(lab)
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.transcript("Which car again?")
    found = await wake.turns.search_history("Creta")
    assert all(row["text"] != CRETA for row in found.get("history", ()))
    assert found["already_in_conversation"] >= 1
    wake.close()


@pytest.mark.asyncio
async def test_newest_decisions_win_when_the_budget_overflows(lab, monkeypatch):
    monkeypatch.setattr(project_voice, "DECISION_MAX_ROWS", 2)
    voice = await munnar_then_chatter(lab)
    wake = FastWake(voice)
    await wake.preload()
    (context,) = wake.agent.injected()
    decisions = section(context, "Earlier owner decisions", "Recent history:")
    assert CRETA in decisions and HILLTOP in decisions
    assert INNOVA not in decisions and TEA_VALLEY not in decisions
    wake.close()


@pytest.mark.asyncio
async def test_no_decision_section_while_decisions_are_still_recent(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask(
        "Create a project called Munnar trip.", "Created project Munnar trip."
    )
    await wake.ask(CRETA, "Understood.")
    wake.close()
    wake = FastWake(voice)
    await wake.preload()
    (context,) = wake.agent.injected()
    assert "Earlier owner decisions" not in context
    assert "owner: " + CRETA in context
    wake.close()


@pytest.mark.parametrize(
    "text",
    [
        INNOVA,
        TEA_VALLEY,
        CRETA,
        HILLTOP,
        "Our campsite will be Lakeview Camp.",
        "We will take the Jimny on our Nepal trip.",
        "Hum Creta le ja rahe hain Munnar ke liye.",
    ],
)
def test_plan_statements_and_corrections_qualify(text):
    assert _is_owner_decision(_Event("user", text))


@pytest.mark.parametrize("text", CHATTER + ["Sounds good to me."])
def test_questions_fragments_and_chatter_do_not(text):
    assert not _is_owner_decision(_Event("user", text))


def test_jarvis_rows_never_count_as_owner_decisions():
    assert not _is_owner_decision(_Event("assistant", CRETA))


class _Event:
    def __init__(self, role, text):
        self.role = role
        self.text = text


@pytest.mark.asyncio
async def test_decisions_come_only_from_the_active_project(lab):
    """Another project's decisions never enter this project's wake history,
    however far back they sit or however much chatter follows."""
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("Create a project called Goa trip.", "Created project Goa trip.")
    await wake.ask("For the Goa trip, we're taking the train.", "Understood.")
    await wake.ask("We're staying at Palm Grove Villa.", "Understood.")
    await wake.ask(
        "Create a project called Munnar trip.", "Created project Munnar trip."
    )
    for line in (INNOVA, TEA_VALLEY, CRETA, HILLTOP):
        await wake.ask(line, "Understood.")
    wake.close()
    wake = Wake(voice)
    for line in CHATTER:
        await wake.ask(line, "Okay.")
    wake.close()
    wake = FastWake(voice)
    await wake.preload()
    (context,) = wake.agent.injected()
    assert "Current project: Munnar trip." in context
    assert CRETA in context and HILLTOP in context
    assert "taking the train" not in context and "Palm Grove" not in context
    wake.close()

    switch = Wake(voice)
    await switch.ask("switch to Goa trip", "Switched.")
    switch.close()
    wake = FastWake(voice)
    await wake.preload()
    (context,) = wake.agent.injected()
    assert "Current project: Goa trip." in context
    assert "taking the train" in context and "Palm Grove Villa" in context
    for line in (INNOVA, TEA_VALLEY, CRETA, HILLTOP):
        assert line not in context
    wake.close()


# Verbatim live transcripts (jarvis.jsonl, 2026-11-17 06:47-06:49 UTC). The
# owner's live check of #322 at 7b12c424 found the Hilltop correction
# (eaa67639) missing: the recogniser wrote "mis spoke", and "We were always
# staying" matched no plan pattern.
LIVE_DECISIONS = [
    "For the Munnar trip, we are taking Innova.",
    "Change of plan, we are taking Creta.",
    "And we are staying at Tea Valley Resort.",
    "Javed I mis spoke earlier. We were always staying at Hilltop Cottage, not T Valley Resort.",
]
LIVE_HILLTOP = LIVE_DECISIONS[-1]


async def live_munnar_then_chatter(lab, *, other_project=False):
    voice = await lab.runtime()
    wake = Wake(voice)
    if other_project:
        await wake.ask("create a project called Goa trip", "Created project Goa trip.")
        await wake.ask("For the Goa trip, we are taking the train.", "Understood.")
        await wake.ask("We were always staying at Palm Grove Villa.", "Understood.")
    await wake.ask(
        "create a project called Munnar trip", "Created project Munnar trip."
    )
    await wake.ask(LIVE_DECISIONS[0], "Understood.")
    await wake.ask("Go back.", "Okay.")
    wake.close()
    wake = Wake(voice)
    for line in LIVE_DECISIONS[1:]:
        await wake.ask(line, "Understood.")
    await wake.ask("Okay, go back to sleep.", "Okay.")
    wake.close()
    wake = Wake(voice)
    for line in CHATTER:
        await wake.ask(line, "Okay.")
    wake.close()
    return voice


def test_the_live_hilltop_correction_qualifies_as_a_decision():
    assert _is_owner_decision(_Event("user", LIVE_HILLTOP))
    for line in LIVE_DECISIONS:
        assert _is_owner_decision(_Event("user", line))
    for line in (
        "Go back.",
        "Okay, go back to sleep.",
        "create a project called Munnar trip",
    ):
        assert not _is_owner_decision(_Event("user", line))


@pytest.mark.asyncio
async def test_live_hilltop_correction_reaches_gemini_as_the_current_stay(lab):
    voice = await live_munnar_then_chatter(lab)
    wake = FastWake(voice)
    await wake.preload()
    (context,) = wake.agent.injected()
    recent = section(context, "Recent history:")
    decisions = section(context, "Earlier owner decisions", "Recent history:")
    assert LIVE_HILLTOP not in recent  # pushed out of the newest 12 rows
    lines = [line for line in decisions.splitlines() if line.startswith("- ")]
    texts = [line.split(": ", 1)[1] for line in lines]
    assert texts == LIVE_DECISIONS  # all four, oldest first
    by_text = dict(zip(texts, lines, strict=True))
    # The correction is marked and comes after the value it corrects, and
    # the rules say a correction means the earlier value was never the plan.
    assert "owner (correction): " + LIVE_HILLTOP in by_text[LIVE_HILLTOP]
    assert (
        "owner: And we are staying at Tea Valley Resort." in by_text[LIVE_DECISIONS[2]]
    )
    assert "(correction)" not in by_text[LIVE_DECISIONS[2]]
    rules = section(context, "How to read it: ", "Earlier owner decisions")
    assert "misspoke or that it was always X" in rules
    assert "never the plan" in rules
    wake.close()


@pytest.mark.asyncio
async def test_live_transcripts_stay_within_the_active_project(lab):
    voice = await live_munnar_then_chatter(lab, other_project=True)
    wake = FastWake(voice)
    await wake.preload()
    (context,) = wake.agent.injected()
    assert "Current project: Munnar trip." in context
    assert LIVE_HILLTOP in context and LIVE_DECISIONS[1] in context
    assert "Goa" not in context and "Palm Grove" not in context
    assert "taking the train" not in context
    wake.close()
