"""context-eval-5 (2026-11-18, c6701adc, travel case, with): both lookups
returned the vehicles and both answers completed, but the Gokarna answer
recognised Gokarna and then answered about the active Spiti project:
"…the Gokarna trip … belongs to a separate context, but for your Spiti Valley
project…".

This replays the recorded steps offline and pins what pushed it there:

- Routing (by design) keeps a question in the selected project, so every
  source shown is Spiti history and routing reads ``resumed`` Spiti.
- The model's archive search "Gokarna trip Bengaluru" returns the Spiti
  planning turn (it shares "trip"), presented as the search hit.
- The prompt's only priority rules are about projects ("Keep projects
  separate … do not merge it into this one"); none says the subject the user
  names in the request controls the answer.

The ambiguous follow-up ("Should I just drive myself for the trip, then?") had
both trips in its fresh-thread context and was answered for Spiti without
asking.
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_project_memory_acceptance_lab import (
    empty_access as empty_access,  # noqa: PLC0414
)
from test_project_personal_acceptance import runtime as acceptance_runtime

from jarvis.memory.project_history_source import standard_history_source
from jarvis.voice.project_answer_provider import (
    PROJECT_ANSWER_PROMPT,
    ProjectAnswerProvider,
)
from jarvis.voice.project_conversation import ProjectConversationCoordinator
from jarvis.voice.project_memory_lab import build_session_personal_factory
from jarvis.voice.project_personal_context_eval import QUESTIONS, run_context_eval

RECORDED = json.loads(
    (
        Path(__file__).parent / "fixtures" / "context_eval_5_recorded_steps.json"
    ).read_text()
)
RULES = " ".join(PROJECT_ANSWER_PROMPT.split())


@pytest.fixture(autouse=True)
def proposal_clock(monkeypatch, clock):
    from jarvis.authority import proposal

    monkeypatch.setattr(proposal, "time", SimpleNamespace(monotonic=clock))


async def replay(empty_access, authority_parts, tmp_path):
    seen = {}

    class RecordedModel:
        async def parse_with_telemetry(self, **kwargs):
            await kwargs["before_dispatch"]()
            payload = kwargs["input_payload"]
            question = next(
                q for q in QUESTIONS if q["question"] == payload["question"]
            )
            steps = seen.setdefault(question["id"], [])
            output = RECORDED[question["id"]]["steps"][len(steps)]["output"]
            steps.append(payload)
            output = {
                key: [{k: v for k, v in r.items() if v is not None} for r in value]
                if key == "personal_requests"
                else value
                for key, value in output.items()
            }
            return SimpleNamespace(
                parsed=kwargs["response_model"](response=output),
                usage={},
                usage_observed=False,
                latency_ms=1,
            )

    memory, capability, _, _, _ = acceptance_runtime(empty_access, authority_parts)
    factory, session = build_session_personal_factory(memory, capability)
    coordinator = ProjectConversationCoordinator(
        empty_access, source_clearance=standard_history_source, personal_factory=factory
    )
    root = tmp_path / "with"
    root.mkdir()
    try:
        await run_context_eval(
            root,
            arm="with",
            memory=memory,
            capability=capability,
            coordinator=coordinator,
            access=empty_access,
            provider=ProjectAnswerProvider(RecordedModel()),
            personal_session=session,
            case="travel",
        )
    finally:
        coordinator.invalidate("test_end")
        session.close()
    return seen


def texts(payload):
    return [s["text"] for s in payload["context"]["sources"]]


@pytest.mark.asyncio
async def test_gokarna_answer_step_saw_only_spiti_evidence_and_a_spiti_search_hit(
    empty_access, authority_parts, tmp_path
):
    seen = await replay(empty_access, authority_parts, tmp_path)
    final = seen["travel_named_destination"][-1]
    live = RECORDED["travel_named_destination"]["steps"][-1]
    assert (
        final["context"]["routing"]
        == live["routing"]
        == {
            "action": "resumed",
            "project_title": "Spiti Valley trip",
        }
    )
    assert final["context"]["personal"]["status"] == "selected"
    # The archive search for Gokarna "found" the Spiti planning turn.
    (search,) = [r for r in final["context"]["retrieval"] if r["tool"] == "search"]
    assert search["status"] == "complete" and len(search["source_ids"]) == 1
    (hit,) = [
        s
        for s in final["context"]["sources"]
        if s["source_id"] == search["source_ids"][0]
    ]
    assert hit["text"] == "We are planning a Spiti Valley trip for June."
    assert not any("Gokarna" in t for t in texts(final)[:5])


@pytest.mark.asyncio
async def test_follow_up_fresh_thread_holds_both_trips(
    empty_access, authority_parts, tmp_path
):
    seen = await replay(empty_access, authority_parts, tmp_path)
    final = seen["travel_ambiguous_followup"][-1]
    joined = " ".join(texts(final))
    assert "Spiti" in joined and "Gokarna" in joined
    assert final["question"] == "Should I just drive myself for the trip, then?"


def test_the_named_subject_controls_the_answer():
    assert "explicitly names" in RULES
    assert "controls the answer" in RULES
    assert "even when it differs from the selected project" in RULES
    assert "only the sources about that subject" in RULES
    assert "a search hit is relevant only if it is about that subject" in RULES


def test_unresolved_reference_with_several_candidates_asks_first():
    assert "could refer to more than one" in RULES
    assert "ask one short question naming the candidates" in RULES


def test_rules_stay_general_for_the_held_out_case():
    assert not re.search(r"(?i)laptop|device|software|macbook|thinkpad|video", RULES)
    assert not re.search(r"(?i)gokarna|spiti", RULES)
