"""Offline reproduction of the context-eval-2 miss (2026-11-18, 308492da).

Personal reads were approved at the start and the fictional vehicles were
saved, yet neither travel question requested a personal fact: the model
answered at step 0. This rebuilds, offline, the exact step-0 input the model
received (fixture: the live payloads) and shows what told it about personal
facts: only ``available_tools.personal_available: true`` and an empty
``context.personal``. Whether to ask was left to one prompt line ("missing
established global facts such as actual ownership, preferences or background,
when relevant") next to "If supplied evidence suffices, answer directly", so a
general travel question looked answerable without the owner's facts. The food
question passed because "preferences" maps onto it directly.
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
from test_project_personal_context_eval import StartSession

from jarvis.memory.project_history_source import standard_history_source
from jarvis.voice.project_answer_provider import (
    PROJECT_ANSWER_PROMPT,
    ProjectAnswerProvider,
)
from jarvis.voice.project_conversation import ProjectConversationCoordinator
from jarvis.voice.project_memory_lab import build_project_personal_session
from jarvis.voice.project_personal_context_eval import QUESTIONS, run_context_eval

LIVE = json.loads(
    (Path(__file__).parent / "fixtures" / "context_eval_2_live_step0.json").read_text()
)
# Jarvis's live replies, verbatim (the first one is omitted from the archive:
# "private buses" matches the restricted-topic filter, source_not_eligible).
LIVE_ANSWERS = {
    "travel_named_destination": "For your trip from Bengaluru to Gokarna, you can "
    "travel by bus, train, or car. Overnight state or private buses run frequently "
    "from Bengaluru to Gokarna and take around 10 to 12 hours. Alternatively, you "
    "can take a train to Gokarna Road station (or nearby Ankola/Kumta) and hire a "
    "cab, or drive yourself via NH 48.",
    "travel_ambiguous_followup": "For the Spiti Valley trip, the plan is to fly to "
    "Chandigarh and hire a local driver for the mountain roads rather than driving "
    "yourself.",
}


def normalize(value):
    text = json.dumps(value, sort_keys=True)
    text = re.sub(r"eval-[0-9a-f]{8}", "eval-<tag>", text)
    text = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<id>", text
    )
    text = re.sub(r"\b[0-9a-f]{64}\b", "<hash>", text)
    text = re.sub(r"2026-11-(?!01T)\d\dT[0-9:.]+\+00:00", "<now>", text)
    text = re.sub(
        r"20\d\d-\d\d-\d\dT[0-9:.]+\+00:00(?<!2026-11-01T09:0\d:00\+00:00)",
        "<now>",
        text,
    )
    return json.loads(text)


async def step0_inputs(empty_access, authority_parts, tmp_path):
    seen = {}

    class LiveLikeWire:
        """Answers at step 0, as the live model did; records what it was sent."""

        async def parse_with_telemetry(self, **kwargs):
            await kwargs["before_dispatch"]()
            payload = kwargs["input_payload"]
            question = next(
                q for q in QUESTIONS if q["question"] == payload["question"]
            )
            seen.setdefault(
                question["id"],
                {
                    "system_prompt": kwargs["system_prompt"],
                    "payload": payload,
                    "schema": kwargs["response_model"].model_json_schema(),
                },
            )
            return SimpleNamespace(
                parsed=kwargs["response_model"](
                    response={"answer": LIVE_ANSWERS[question["id"]]}
                ),
                usage={},
                usage_observed=False,
                latency_ms=1,
            )

    memory, capability, _, _, _ = acceptance_runtime(empty_access, authority_parts)
    # The lab's real archive rule (the shared test runtime admits everything).
    coordinator = ProjectConversationCoordinator(
        empty_access,
        source_clearance=standard_history_source,
        personal_factory=lambda c: build_project_personal_session(
            c, memory, capability
        ),
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
            provider=ProjectAnswerProvider(LiveLikeWire()),
            personal_session=StartSession(),
            case="travel",
        )
    finally:
        coordinator.invalidate("test_end")
    return seen


@pytest.mark.asyncio
async def test_offline_step0_input_matches_the_live_run(
    empty_access, authority_parts, tmp_path
):
    seen = await step0_inputs(empty_access, authority_parts, tmp_path)
    for question_id, live in LIVE.items():
        assert normalize(seen[question_id]["payload"]) == normalize(live), question_id


@pytest.mark.asyncio
async def test_the_model_is_told_only_that_a_personal_query_is_possible(
    empty_access, authority_parts, tmp_path
):
    seen = await step0_inputs(empty_access, authority_parts, tmp_path)
    for question_id in LIVE:
        payload = seen[question_id]["payload"]
        assert payload["available_tools"]["personal_available"] is True
        assert payload["context"]["personal"] == {
            "facts": [],
            "status": "not_requested",
        }
        # Nothing in the input says which owner facts exist or matter here.
        text = json.dumps(payload).casefold()
        assert not any(w in text for w in ("vehicle", "thar", "ather", "owned_item"))
        # The schema lists every scope key, without saying any has saved facts.
        assert "owned_item.vehicle" in json.dumps(seen[question_id]["schema"])


def test_the_prompt_asks_for_owner_facts_whenever_they_would_change_advice():
    rule = " ".join(
        PROJECT_ANSWER_PROMPT.split("Return exactly one response object")[0].split()
    )
    assert "advice, a recommendation, a choice or a plan" in rule
    assert "even when the request does not mention them" in rule
    # The project archive still comes first for past project discussion.
    assert "use search_query FIRST, not personal_requests" in rule
    # The held-out generalization case must stay unseen by the prompt.
    assert not re.search(r"(?i)laptop|device|software|macbook|thinkpad", rule)
