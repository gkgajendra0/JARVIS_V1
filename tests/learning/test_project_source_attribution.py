"""An answer taken from another project names that project.

Live run 2026-11-08 07:19:20 (R2-A): from Interview Prep, "Which hotel are we
staying at for the Nepal trip?" was answered "You are staying at the Yak and
Yeti." The answer was right (the owner named the project, so it was read), but
the reply did not say where it came from. It arrived on the repair path: the
first answer was withheld, the context was delivered by the application and the
answer re-requested.

Gemini is simulated: these tests check what Jarvis gives the model (tool result,
delivered context and re-request wording) and how the acceptance recorder
grades a reply that does or does not name the project.
"""

import pytest
import test_project_voice as project_voice_tests
from test_project_voice import Wake, settle
from test_project_voice_fast_path import FastWake

from jarvis.voice import project_memory_production_acceptance as acceptance
from jarvis.voice.project_voice import (
    REPAIR_ANSWER_INSTRUCTIONS,
    REPAIR_ATTRIBUTION_INSTRUCTIONS,
    source_attribution,
)

lab = project_voice_tests.lab

QUESTION = "Which hotel are we staying at for the Nepal trip?"


async def _two_projects(lab):
    voice = await lab.runtime()
    wake = Wake(voice)
    await wake.ask("create project called Nepal trip", "Created project Nepal trip.")
    await wake.ask("Our hotel is YAK and YETI.", "Understood.")
    await wake.ask("create project called Interview prep", "Created.")
    await wake.ask("The interview panel is on Friday at ten.", "Noted.")
    wake.close()
    return voice


def test_attribution_wording():
    assert source_attribution(["Nepal trip"]) == "In your Nepal trip project"
    assert (
        source_attribution(["Nepal trip", "Goa"])
        == "In your Nepal trip and Goa projects"
    )
    assert source_attribution([]) == ""


@pytest.mark.asyncio
async def test_tool_result_for_a_named_project_carries_its_attribution(lab):
    voice = await _two_projects(lab)
    wake = Wake(voice)  # current project: Interview prep
    result = await wake.ask(QUESTION)
    assert result["status"] == "ready" and result["action"] in {"continued", "resumed"}
    assert result["project"] == "Interview prep"  # nothing switched
    assert result["referenced_projects"] == ["Nepal trip"]
    assert result["source_attribution"] == "In your Nepal trip project"
    assert "start the answer with 'source_attribution'" in result["guidance"]
    rows = [r for r in result["history"] if "YETI" in r["text"]]
    assert rows and all(r["from_project"] == "Nepal trip" for r in rows)


@pytest.mark.asyncio
async def test_a_question_about_the_current_project_has_no_attribution(lab):
    voice = await _two_projects(lab)
    wake = Wake(voice)
    result = await wake.ask("When is the interview panel?")
    assert "source_attribution" not in result
    assert "referenced_projects" not in result


@pytest.mark.asyncio
async def test_the_repair_re_request_names_the_source_project(lab):
    """The live path: answer withheld, context delivered, answer re-requested."""
    voice = await _two_projects(lab)
    wake = FastWake(voice)
    await wake.preload()
    wake.speech()
    wake.partial(QUESTION)
    allowed, _ = await wake.gate()  # answered before reading Nepal trip
    assert allowed is False
    wake.transcript(QUESTION)
    await settle(voice)
    assert voice.metrics.repair_deliveries == 1
    delivered = wake.agent.injected()[-1]
    assert '"source_attribution": "In your Nepal trip project"' in delivered
    expected = REPAIR_ANSWER_INSTRUCTIONS + REPAIR_ATTRIBUTION_INSTRUCTIONS.format(
        attribution="In your Nepal trip project"
    )
    assert wake.session.replies == [expected]
    assert wake.response()[0] is True


def _graded(reply):
    isolation = acceptance.Turn(
        at="2026-11-08T07:18:15Z",
        user="Which hotel are we staying at?",
        reply="That detail hasn't been recorded in your project records.",
        saved_action="continued",
        turn_id="t0",
        session_id="s0",
    )
    turn = acceptance.Turn(
        at="2026-11-08T07:19:20Z",
        user=QUESTION,
        reply=reply,
        saved_action="continued",
        turn_id="t1",
        session_id="s1",
    )
    record = acceptance.grade([isolation, turn], None)
    return next(s for s in record["steps"] if s["step_id"] == "4-cross-project")


def test_recorder_fails_the_live_reply_that_did_not_name_the_project():
    step = _graded("You are staying at the Yak and Yeti.")
    assert step["verdict"] == "FAIL"
    assert "reply lacks 'nepal'" in step["reasons"]


def test_recorder_passes_a_reply_that_names_the_project():
    step = _graded("In your Nepal trip project, you are staying at the Yak and Yeti.")
    assert step["verdict"] == "PASS", step
