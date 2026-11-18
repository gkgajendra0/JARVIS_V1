"""Offline replay of context-eval-3 (2026-11-18, c458cefd, travel case, with).

The added advice rule made the model ask for personal facts in both questions.
Replaying its recorded requests through the real coordinator, personal session,
projection and authority (fake model, fake clock) reproduces both outcomes:

1. Gokarna asked for ``owned_item.vehicle`` AND ``personal_fact`` in one query.
   ``project_personal_context`` is all-or-nothing: one requested scope with no
   saved fact makes the whole query ``no_match`` and releases nothing, so the
   saved vehicles were dropped and the model told the owner his records held
   no vehicle ownership. ``no_match`` carries no per-scope detail.
2. The follow-up asked for ``owned_item.vehicle`` alone: selected, and the
   fact reached the model. But the read lease (a delegated read child) lives
   30 s; the free model took longer than that to write the answer, so the
   release check (``_validate`` -> ``validate_read``: "learning child expired")
   failed and the coordinator raised "personal context invalidated": no answer.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_project_memory_acceptance_lab import (
    empty_access as empty_access,  # noqa: PLC0414
)
from test_project_personal_acceptance import runtime as acceptance_runtime

from jarvis.memory.project_history_source import standard_history_source
from jarvis.voice.project_answer_provider import ProjectAnswerProvider
from jarvis.voice.project_conversation import ProjectConversationCoordinator
from jarvis.voice.project_memory_lab import build_session_personal_factory
from jarvis.voice.project_personal_context_eval import QUESTIONS, run_context_eval

RECORDED = json.loads(
    (
        Path(__file__).parent / "fixtures" / "context_eval_3_recorded_steps.json"
    ).read_text()
)


@pytest.fixture(autouse=True)
def proposal_clock(monkeypatch, clock):
    # Keep proposal expiry on the broker's fake clock (as in
    # test_personal_context_session).
    from jarvis.authority import proposal

    monkeypatch.setattr(proposal, "time", SimpleNamespace(monotonic=clock))


def strip_times(personal):
    return {
        **personal,
        "facts": [
            {k: v for k, v in f.items() if k != "recorded_at"}
            for f in personal.get("facts", [])
        ],
    }


async def replay(empty_access, authority_parts, clock, tmp_path, *, answer_seconds):
    """The recorded outputs, step by step; the clock advances by the time the
    model spends writing each final answer."""
    seen = {}

    class RecordedModel:
        async def parse_with_telemetry(self, **kwargs):
            await kwargs["before_dispatch"]()
            payload = kwargs["input_payload"]
            question = next(
                q for q in QUESTIONS if q["question"] == payload["question"]
            )
            steps = seen.setdefault(question["id"], [])
            recorded = RECORDED[question["id"]]["steps"][len(steps)]
            steps.append(payload)
            output = {  # model_dump wrote absent target_quote as null
                key: [{k: v for k, v in r.items() if v is not None} for r in value]
                if key == "personal_requests"
                else value
                for key, value in recorded["output"].items()
            }
            if "answer" in output:
                clock.advance(answer_seconds)
            return SimpleNamespace(
                parsed=kwargs["response_model"](response=output),
                usage={},
                usage_observed=False,
                latency_ms=1,
            )

    memory, capability, _, _, _ = acceptance_runtime(empty_access, authority_parts)
    # As the lab builds it: one read-only session grant shared by requests, each
    # read a short delegated child of it.
    factory, session = build_session_personal_factory(memory, capability)
    coordinator = ProjectConversationCoordinator(
        empty_access, source_clearance=standard_history_source, personal_factory=factory
    )
    root = tmp_path / "with"
    root.mkdir()
    error = None
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
    except RuntimeError as exc:
        error = exc
    finally:
        coordinator.invalidate("test_end")
        session.close()
    rows = {
        r["question_id"]: r
        for r in map(
            json.loads, (root / "context-eval-with.jsonl").read_text().splitlines()
        )
        if r["kind"] == "question"
    }
    return seen, rows, error


@pytest.mark.asyncio
async def test_recorded_sequence_reproduces_both_live_outcomes(
    empty_access, authority_parts, clock, tmp_path
):
    seen, rows, error = await replay(
        empty_access, authority_parts, clock, tmp_path, answer_seconds=31
    )
    # Every recorded request produced the same result the model saw live.
    for question_id, recorded in RECORDED.items():
        for payload, step in zip(seen[question_id], recorded["steps"], strict=True):
            assert strip_times(payload["context"]["personal"]) == strip_times(
                step["personal_in"]
            ), question_id
            assert payload["context"]["retrieval"] == step["retrieval_in"]
            assert payload["available_tools"] == step["available_tools"]
    # 1. One empty scope (personal_fact) made the vehicle query release nothing.
    gokarna = rows["travel_named_destination"]
    assert gokarna["personal"]["requested_scopes"] == [
        "owned_item.vehicle",
        "personal_fact",
    ]
    assert gokarna["personal"]["query_status"] == "no_match"
    assert gokarna["status"] == "completed"
    # 2. The fact was selected, then the 30 s read lease expired before release.
    followup = rows["travel_ambiguous_followup"]
    assert followup["personal"]["selected_facts"] == [
        "vehicles: a Mahindra Thar diesel 4x4 and an Ather 450X electric scooter"
    ]
    assert followup["status"] == "failed"
    assert followup["error"] == RECORDED["travel_ambiguous_followup"]["error"]
    assert followup["error_message"] == "personal context invalidated"
    assert isinstance(error, RuntimeError)


@pytest.mark.asyncio
@pytest.mark.parametrize("answer_seconds", [5, 29])
async def test_the_same_follow_up_completes_within_the_read_lease(
    empty_access, authority_parts, clock, tmp_path, answer_seconds
):
    _, rows, error = await replay(
        empty_access, authority_parts, clock, tmp_path, answer_seconds=answer_seconds
    )
    assert error is None
    assert rows["travel_ambiguous_followup"]["status"] == "completed"
    # The all-or-nothing Gokarna miss does not depend on timing.
    assert rows["travel_named_destination"]["personal"]["query_status"] == "no_match"
