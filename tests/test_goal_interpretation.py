from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.goal_intelligence.interpretation import (
    GoalInterpretationError,
    GoalInterpretationShadowRuntime,
    GoalInterpreter,
    ShadowCapabilityRequirement,
    ShadowEntityCandidate,
    ShadowGoalInterpretationOutput,
    ShadowInformationNeedCandidate,
)
from jarvis.goal_intelligence.models import GoalKind
from jarvis.goal_intelligence.store import GoalStore
from jarvis.hands.provider_adapters import StructuredOutputTelemetry
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore


class FakeStructuredClient:
    provider_name = "fake"
    model_name = "fake-gicc"

    def __init__(self, output: ShadowGoalInterpretationOutput) -> None:
        self.output = output
        self.calls: list[dict[str, object]] = []

    async def parse_with_telemetry(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, object],
        response_model,
    ) -> StructuredOutputTelemetry:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "input_payload": input_payload,
                "response_model": response_model,
            }
        )
        return StructuredOutputTelemetry(
            parsed=self.output,
            usage={"input_tokens": 10, "output_tokens": 5},
            usage_observed=True,
            latency_ms=2.5,
        )


def _store(tmp_path: Path) -> GoalStore:
    work = SQLiteWorkStore(
        tmp_path / "work.sqlite3",
        payload_codec=ProtectedWorkPayloadCodec(b"i" * 32),
    )
    return GoalStore(work)


def _conversation(text: str) -> tuple[ConversationSession, object]:
    conversation = ConversationSession(session_id="session-gicc")
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, text)
    return conversation, turn


@pytest.mark.asyncio
async def test_tv_shadow_interpretation_separates_task_from_reusable_capability(
    tmp_path: Path,
) -> None:
    conversation, turn = _conversation("I want to watch Transporter on my TV.")
    client = FakeStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome="Watch Transporter on the owner's TV.",
            goal_kind=GoalKind.ONE_SHOT,
            candidate_entities=[
                ShadowEntityCandidate(
                    mention="my TV",
                    proposed_type="media_player",
                    evidence_turn_ids=[turn.turn_id],
                )
            ],
            candidate_completion_predicates=["media playback has started"],
            candidate_information_needs=[],
            candidate_capability_requirements=[
                ShadowCapabilityRequirement(
                    family="media_player.control",
                    operations=["launch_app", "play"],
                    target_entity_type="media_player",
                )
            ],
            evidence_turn_ids=[turn.turn_id],
        )
    )

    result = await GoalInterpreter(client=client).interpret(
        conversation=conversation,
        turn=turn,
        store=_store(tmp_path),
    )

    assert result.actionable is True
    assert result.candidate.goal_kind is GoalKind.ONE_SHOT
    assert "Transporter" in result.candidate.desired_outcome
    assert [item.family for item in result.capability_requirements] == [
        "media_player.control"
    ]
    assert all(
        "transporter" not in item.family
        for item in result.capability_requirements
    )


@pytest.mark.asyncio
async def test_gate_shadow_interpretation_composes_generic_capability_hints(
    tmp_path: Path,
) -> None:
    conversation, turn = _conversation(
        "Monitor my main gate and tell me when a delivery agent is at the door."
    )
    client = FakeStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome=(
                "Notify the owner when a delivery agent is verified at the main gate."
            ),
            goal_kind=GoalKind.MONITORING,
            candidate_entities=[
                ShadowEntityCandidate(
                    mention="main gate",
                    proposed_type="entrance",
                    evidence_turn_ids=[turn.turn_id],
                )
            ],
            candidate_completion_predicates=[
                "delivery-agent condition verified",
                "owner notified",
            ],
            candidate_information_needs=[],
            candidate_capability_requirements=[
                ShadowCapabilityRequirement(
                    family="camera.observe",
                    operations=["read_stream"],
                    target_entity_type="camera",
                ),
                ShadowCapabilityRequirement(
                    family="vision.perceive",
                    operations=["detect_person"],
                ),
                ShadowCapabilityRequirement(
                    family="notification.owner",
                    operations=["send"],
                ),
            ],
            evidence_turn_ids=[turn.turn_id],
        )
    )

    result = await GoalInterpreter(client=client).interpret(
        conversation=conversation,
        turn=turn,
        store=_store(tmp_path),
    )

    families = {item.family for item in result.capability_requirements}
    assert families == {"camera.observe", "notification.owner", "vision.perceive"}
    assert all("main_gate" not in family for family in families)


@pytest.mark.asyncio
async def test_conversational_turn_is_not_promoted_to_actionable_work(
    tmp_path: Path,
) -> None:
    conversation, turn = _conversation("Good evening Jarvis, how are you?")
    client = FakeStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=False,
            desired_outcome="Respond conversationally to the owner's greeting.",
            goal_kind=GoalKind.ONE_SHOT,
            candidate_entities=[],
            candidate_completion_predicates=[],
            candidate_information_needs=[],
            candidate_capability_requirements=[],
            evidence_turn_ids=[turn.turn_id],
        )
    )

    result = await GoalInterpreter(client=client).interpret(
        conversation=conversation,
        turn=turn,
        store=_store(tmp_path),
    )

    assert result.actionable is False
    assert result.capability_requirements == ()


@pytest.mark.asyncio
async def test_interpreter_rejects_invented_conversation_evidence(
    tmp_path: Path,
) -> None:
    conversation, turn = _conversation("Open Notepad.")
    client = FakeStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome="Open Notepad on the current computer.",
            goal_kind=GoalKind.ONE_SHOT,
            candidate_entities=[],
            candidate_completion_predicates=["Notepad is open"],
            candidate_information_needs=[],
            candidate_capability_requirements=[
                ShadowCapabilityRequirement(
                    family="computer.application",
                    operations=["launch"],
                    target_entity_type="computer",
                )
            ],
            evidence_turn_ids=["invented-turn"],
        )
    )

    with pytest.raises(GoalInterpretationError, match="not supplied"):
        await GoalInterpreter(client=client).interpret(
            conversation=conversation,
            turn=turn,
            store=_store(tmp_path),
        )


@pytest.mark.asyncio
async def test_secret_bearing_turn_never_reaches_provider(tmp_path: Path) -> None:
    conversation, turn = _conversation("The pairing PIN is 1234")
    client = FakeStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=False,
            desired_outcome="Handle a pairing response.",
            goal_kind=GoalKind.ONE_SHOT,
            evidence_turn_ids=[turn.turn_id],
        )
    )

    with pytest.raises(GoalInterpretationError, match="secret-bearing"):
        await GoalInterpreter(client=client).interpret(
            conversation=conversation,
            turn=turn,
            store=_store(tmp_path),
        )
    assert client.calls == []


@pytest.mark.asyncio
async def test_shadow_runtime_persists_evidence_without_creating_goal(
    tmp_path: Path,
) -> None:
    conversation, turn = _conversation("Open Calculator.")
    store = _store(tmp_path)
    client = FakeStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome="Open Calculator on the current computer.",
            goal_kind=GoalKind.ONE_SHOT,
            candidate_entities=[],
            candidate_completion_predicates=["Calculator is open"],
            candidate_information_needs=[
                ShadowInformationNeedCandidate(
                    required_fact="current computer target",
                    why_required="Target identity affects execution.",
                    material_effect="target",
                    evidence_turn_ids=[turn.turn_id],
                )
            ],
            candidate_capability_requirements=[
                ShadowCapabilityRequirement(
                    family="computer.application",
                    operations=["launch"],
                    target_entity_type="computer",
                )
            ],
            evidence_turn_ids=[turn.turn_id],
        )
    )
    runtime = GoalInterpretationShadowRuntime(
        conversation=conversation,
        interpreter=GoalInterpreter(client=client),
        store=store,
    )

    runtime.observe_turn(turn)
    for _ in range(100):
        if runtime.pending_task_count == 0:
            break
        await asyncio.sleep(0.01)

    evidence = store.get_shadow_interpretation(
        source_session_id=conversation.session_id,
        source_turn_id=turn.turn_id,
    )
    assert evidence is not None
    assert evidence["actionable"] is True
    payload = evidence["payload"]
    assert isinstance(payload, dict)
    assert payload["legacy_authoritative_behavior_unchanged"] is True
    assert payload["new_owner_questions"] == 0
    assert payload["new_phase9_acquisitions"] == 0
    assert payload["new_actions"] == 0
    assert store.list_active_goals() == ()
    runtime.close()
