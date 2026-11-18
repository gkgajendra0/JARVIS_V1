"""Regression suite from context-eval-3 (2026-11-18, c458cefd, travel, with).

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

Both recorded sequences are replayed exactly; the assertions pin the repaired
behaviour (per-scope lookup results; lease renewal under the same session
approval) and that lock, revocation, expiry, correction and forget still stop
a slow answer.
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


async def replay(
    empty_access,
    authority_parts,
    clock,
    tmp_path,
    *,
    answer_seconds,
    during_followup_answer=None,
):
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
                if (
                    during_followup_answer is not None
                    and question["id"] == "travel_ambiguous_followup"
                ):
                    await during_followup_answer(
                        SimpleNamespace(
                            memory=memory,
                            capability=capability,
                            session=session,
                            clock=clock,
                        )
                    )
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


FACT = "vehicles: a Mahindra Thar diesel 4x4 and an Ather 450X electric scooter"


@pytest.mark.asyncio
async def test_the_recorded_requests_reach_the_same_first_step(
    empty_access, authority_parts, clock, tmp_path
):
    seen, _, _ = await replay(
        empty_access, authority_parts, clock, tmp_path, answer_seconds=5
    )
    for question_id, recorded in RECORDED.items():
        first, live = seen[question_id][0], recorded["steps"][0]
        assert strip_times(first["context"]["personal"]) == live["personal_in"]
        assert first["available_tools"] == live["available_tools"]


@pytest.mark.asyncio
async def test_mixed_lookup_releases_the_saved_vehicles_and_names_each_scope(
    empty_access, authority_parts, clock, tmp_path
):
    seen, rows, _ = await replay(
        empty_access, authority_parts, clock, tmp_path, answer_seconds=5
    )
    # Live: {"facts": [], "status": "no_match"} -> "not available in your records".
    personal = seen["travel_named_destination"][1]["context"]["personal"]
    assert personal["status"] == "selected"
    assert [f["text"] for f in personal["facts"]] == [FACT]
    assert personal["scopes"] == {
        "owned_item.vehicle": "selected",
        "personal_fact": "no_match",
    }
    assert (
        "no_match means nothing is saved in that category only"
        in (personal["absence_rule"])
    )
    assert rows["travel_named_destination"]["personal"]["expected_in_final_context"]


@pytest.mark.asyncio
@pytest.mark.parametrize("answer_seconds", [5, 31, 95])
async def test_a_slow_answer_alone_is_released_under_the_session_approval(
    empty_access, authority_parts, clock, tmp_path, answer_seconds
):
    hellos = len(authority_parts.hello.calls)
    _, rows, error = await replay(
        empty_access, authority_parts, clock, tmp_path, answer_seconds=answer_seconds
    )
    assert error is None
    followup = rows["travel_ambiguous_followup"]
    assert followup["status"] == "completed"
    assert followup["personal"]["selected_facts"] == [FACT]
    assert (
        followup["answer"]
        == RECORDED["travel_ambiguous_followup"]["steps"][1]["output"]["answer"]
    )
    # Hello: history grant, start-of-run personal reads, the vehicles command.
    assert len(authority_parts.hello.calls) - hellos <= 3


async def lock(ctx, authority_parts):
    authority_parts.windows.lock_unlock()


async def revoke(ctx, authority_parts):
    ctx.session.close("owner_revoked")


async def expire(ctx, authority_parts):
    from jarvis.authority.personal_context_session import ABSOLUTE_LIMIT_SECONDS

    ctx.clock.advance(ABSOLUTE_LIMIT_SECONDS)  # the session approval itself ends


async def correct(ctx, authority_parts):
    from jarvis.voice.project_personal_context_eval import _mutate

    await _mutate(ctx.memory, ctx.capability, "correct", "vehicles", "a Tata Nexon")


async def forget(ctx, authority_parts):
    from jarvis.conversation import ConversationRole, ConversationSession
    from jarvis.voice.memory_tools import MemoryAgentTools
    from jarvis.voice.project_memory_lab import build_project_personal_session

    conversation = ConversationSession()
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Forget my vehicles.")
    personal = build_project_personal_session(conversation, ctx.memory, ctx.capability)
    try:
        receipt = await MemoryAgentTools(
            ctx.memory.service, conversation, personal_context=personal
        ).forget(predicate="vehicles")
        assert receipt.get("ok") is True
    finally:
        personal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [lock, revoke, expire, correct, forget])
async def test_a_slow_answer_is_still_stopped_by_any_other_change(
    empty_access, authority_parts, clock, tmp_path, change
):
    _, rows, error = await replay(
        empty_access,
        authority_parts,
        clock,
        tmp_path,
        answer_seconds=31,
        during_followup_answer=lambda ctx: change(ctx, authority_parts),
    )
    followup = rows["travel_ambiguous_followup"]
    assert followup["status"] == "failed", change.__name__
    assert followup["error"] == "PermissionError"
    assert isinstance(error, RuntimeError)
