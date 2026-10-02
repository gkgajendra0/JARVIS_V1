"""Shadow goal interpretation for GICC.

This module is deliberately non-authoritative.  A model may propose an owner-goal
interpretation, but it cannot create canonical goals, ask the owner questions,
acquire capabilities, grant Authority, execute actions, or report success.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.hands.provider_adapters import (
    StructuredOutputClient,
    StructuredOutputError,
    build_chatgpt_plan_structured_output_client,
    build_structured_output_client,
)
from jarvis.observability.redaction import redact_data
from jarvis.provider_circuit import BackgroundProviderCircuit

from .models import GoalInterpretationCandidateV1, GoalKind
from .store import GoalStore

LOGGER = logging.getLogger(__name__)

_DEFAULT_RECENT_TURNS = 8
_MAX_TURN_CHARS = 1200
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|otp|pin|passcode|secret|token|api[-_ ]?key|"
    r"authorization)\b\s*(?:is|=|:)?\s*([^\s,;]{2,})"
)
_CAPABILITY_KEY = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_OPERATION_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


class GoalInterpretationError(RuntimeError):
    """A proposed interpretation failed the GICC shadow boundary."""


class ShadowEntityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mention: str = Field(min_length=1, max_length=240)
    proposed_type: str | None = Field(default=None, max_length=80)
    evidence_turn_ids: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("mention")
    @classmethod
    def _normalize_mention(cls, value: str) -> str:
        return value.strip()

    @field_validator("proposed_type")
    @classmethod
    def _normalize_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().casefold()
        return normalized or None


class ShadowInformationNeedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_fact: str = Field(min_length=1, max_length=320)
    why_required: str = Field(min_length=1, max_length=480)
    material_effect: Literal[
        "target",
        "result",
        "authority",
        "cost",
        "success_criteria",
    ]
    evidence_turn_ids: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("required_fact", "why_required")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        return value.strip()


class ShadowCapabilityRequirement(BaseModel):
    """Non-canonical hint used only to compare task vs reusable capability shape."""

    model_config = ConfigDict(extra="forbid")

    family: str = Field(min_length=3, max_length=120)
    operations: list[str] = Field(min_length=1, max_length=16)
    target_entity_type: str | None = Field(default=None, max_length=80)

    @field_validator("family")
    @classmethod
    def _validate_family(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not _CAPABILITY_KEY.fullmatch(normalized):
            raise ValueError("capability family must be a reusable dotted semantic key")
        return normalized

    @field_validator("operations")
    @classmethod
    def _validate_operations(cls, value: list[str]) -> list[str]:
        normalized = []
        for item in value:
            operation = str(item).strip().casefold()
            if not _OPERATION_KEY.fullmatch(operation):
                raise ValueError("capability operations must be semantic identifiers")
            if operation not in normalized:
                normalized.append(operation)
        if not normalized:
            raise ValueError("at least one operation is required")
        return sorted(normalized)

    @field_validator("target_entity_type")
    @classmethod
    def _normalize_target_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().casefold()
        return normalized or None


class ShadowGoalInterpretationOutput(BaseModel):
    """Strict provider output.  This object is evidence, never canonical truth."""

    model_config = ConfigDict(extra="forbid")

    actionable: bool
    desired_outcome: str = Field(min_length=1, max_length=640)
    goal_kind: GoalKind
    candidate_entities: list[ShadowEntityCandidate] = Field(
        default_factory=list,
        max_length=16,
    )
    candidate_completion_predicates: list[str] = Field(
        default_factory=list,
        max_length=16,
    )
    candidate_information_needs: list[ShadowInformationNeedCandidate] = Field(
        default_factory=list,
        max_length=12,
    )
    candidate_capability_requirements: list[ShadowCapabilityRequirement] = Field(
        default_factory=list,
        max_length=20,
    )
    evidence_turn_ids: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("desired_outcome")
    @classmethod
    def _normalize_outcome(cls, value: str) -> str:
        return value.strip()

    @field_validator("candidate_completion_predicates", "evidence_turn_ids")
    @classmethod
    def _normalize_unique_strings(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            normalized = str(item).strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result


@dataclass(frozen=True, slots=True)
class GoalInterpretationResult:
    candidate: GoalInterpretationCandidateV1
    actionable: bool
    capability_requirements: tuple[ShadowCapabilityRequirement, ...]
    provider_name: str
    model_name: str
    input_digest: str
    usage: dict[str, int]
    usage_observed: bool
    latency_ms: float

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, GoalInterpretationCandidateV1):
            raise TypeError("candidate must be GoalInterpretationCandidateV1")
        if not isinstance(self.actionable, bool):
            raise TypeError("actionable must be a bool")


def _secret_safe_text(value: str) -> str:
    sanitized = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=[REDACTED]",
        str(value),
    )
    result = redact_data(sanitized)
    assert isinstance(result, str)
    return result[:_MAX_TURN_CHARS]


def _contains_secret_assignment(value: str) -> bool:
    return _SECRET_ASSIGNMENT.search(str(value)) is not None


def _turn_payload(turn: ConversationTurn) -> dict[str, object]:
    return {
        "turn_id": turn.turn_id,
        "role": turn.role.value,
        "text": _secret_safe_text(turn.text),
    }


def _entity_summary(store: GoalStore) -> list[dict[str, object]]:
    return [
        {
            "entity_id": entity.entity_id,
            "entity_type": entity.entity_type,
            "canonical_name": _secret_safe_text(entity.canonical_name),
            "aliases": [_secret_safe_text(alias) for alias in entity.aliases[:6]],
            "lifecycle_state": entity.lifecycle_state.value,
        }
        for entity in store.list_entities(limit=30)
    ]


def _goal_summary(store: GoalStore) -> list[dict[str, object]]:
    return [
        {
            "goal_id": goal.goal_id,
            "goal_kind": goal.goal_kind.value,
            "state": goal.state.value,
            "desired_outcome": _secret_safe_text(goal.desired_outcome),
            "referenced_entity_ids": list(goal.referenced_entity_ids),
        }
        for goal in store.list_active_goals(limit=12)
    ]


_SYSTEM_PROMPT = """
You are the Goal Interpreter inside JARVIS GICC. You propose structured evidence only.
JARVIS, not you, owns canonical goal state, capability truth, Authority and execution.

Interpret the owner's desired outcome rather than mapping the sentence directly to one
tool or one-off skill. Separate task-specific parameters from reusable capability needs.

Rules:
- Mark actionable=false for greetings, casual conversation, acknowledgements, opinions,
  or speech that does not ask JARVIS to achieve/maintain/find/change/monitor something.
- Preserve the owner's natural intent even when phrased in English, Hinglish or shorthand.
- Never invent a concrete resource, application, account, provider, movie edition,
  service, location, or success condition that is not supported by supplied evidence.
- Prefer an unresolved entity or information need over a guessed target.
- Information needs are only facts that can materially change target, result, Authority,
  cost, success criteria or ability to continue. Do not ask questions yourself.
- Capability requirements are reusable semantic families, never one-off task names.
  Keep task parameters (titles, filenames, people, products, search terms) out of the
  capability family and operation names.
- A capability family must be a reusable dotted key such as domain.control or data.search.
  Operations are generic verbs/verb_phrases such as launch_app, search, play, read_stream.
- Do not claim an action succeeded. Do not grant permission. Do not create Authority.
- Cite only supplied conversation turn IDs as evidence.
- Do not output secrets or credentials.
""".strip()


class GoalInterpreter:
    """Provider-backed structured proposal boundary for one accepted USER turn."""

    def __init__(
        self,
        *,
        client: StructuredOutputClient,
        recent_turn_limit: int = _DEFAULT_RECENT_TURNS,
    ) -> None:
        if not isinstance(recent_turn_limit, int) or isinstance(
            recent_turn_limit, bool
        ):
            raise TypeError("recent_turn_limit must be an integer")
        if not 1 <= recent_turn_limit <= 24:
            raise ValueError("recent_turn_limit must be between 1 and 24")
        self._client = client
        self._recent_turn_limit = recent_turn_limit

    @property
    def provider_name(self) -> str:
        return str(self._client.provider_name)

    @property
    def model_name(self) -> str:
        return str(self._client.model_name)

    async def interpret(
        self,
        *,
        conversation: ConversationSession,
        turn: ConversationTurn,
        store: GoalStore,
    ) -> GoalInterpretationResult:
        if turn.role is not ConversationRole.USER:
            raise GoalInterpretationError("goal interpretation requires a USER turn")
        if turn not in conversation.turns:
            raise GoalInterpretationError(
                "goal interpretation turn must belong to the canonical conversation"
            )
        if _contains_secret_assignment(turn.text):
            raise GoalInterpretationError(
                "secret-bearing owner input is excluded from GICC model interpretation"
            )

        bounded_turns = conversation.turns[-self._recent_turn_limit :]
        allowed_turn_ids = {item.turn_id for item in bounded_turns}
        allowed_turn_ids.add(turn.turn_id)
        input_payload = {
            "latest_user_turn": _turn_payload(turn),
            "recent_conversation": [_turn_payload(item) for item in bounded_turns],
            "known_entities": _entity_summary(store),
            "relevant_active_goals": _goal_summary(store),
        }
        input_digest = canonical_digest(input_payload)
        telemetry = await self._client.parse_with_telemetry(
            system_prompt=_SYSTEM_PROMPT,
            input_payload=input_payload,
            response_model=ShadowGoalInterpretationOutput,
        )
        parsed = telemetry.parsed
        if not isinstance(parsed, ShadowGoalInterpretationOutput):
            raise StructuredOutputError(
                "GICC interpreter returned the wrong structured-output contract"
            )

        cited_ids = set(parsed.evidence_turn_ids)
        for entity in parsed.candidate_entities:
            cited_ids.update(entity.evidence_turn_ids)
        for need in parsed.candidate_information_needs:
            cited_ids.update(need.evidence_turn_ids)
        unknown = cited_ids - allowed_turn_ids
        if unknown:
            raise GoalInterpretationError(
                "GICC interpretation cited conversation evidence not supplied to it"
            )
        evidence_ids = tuple(sorted(cited_ids or {turn.turn_id}))

        entity_strings = tuple(
            sorted(
                (f"{entity.proposed_type or 'unresolved'}::{entity.mention.strip()}")
                for entity in parsed.candidate_entities
            )
        )
        information_strings = tuple(
            sorted(
                (
                    f"{need.material_effect}::{need.required_fact.strip()}::"
                    f"{need.why_required.strip()}"
                )
                for need in parsed.candidate_information_needs
            )
        )
        candidate = GoalInterpretationCandidateV1.create(
            desired_outcome=parsed.desired_outcome,
            goal_kind=parsed.goal_kind,
            candidate_entities=entity_strings,
            candidate_completion_predicates=tuple(
                parsed.candidate_completion_predicates
            ),
            candidate_information_needs=information_strings,
            reasoning_evidence_refs=evidence_ids,
        )
        return GoalInterpretationResult(
            candidate=candidate,
            actionable=parsed.actionable,
            capability_requirements=tuple(parsed.candidate_capability_requirements),
            provider_name=self.provider_name,
            model_name=self.model_name,
            input_digest=input_digest,
            usage=dict(telemetry.usage),
            usage_observed=telemetry.usage_observed,
            latency_ms=telemetry.latency_ms,
        )


def build_goal_interpreter(
    *,
    provider: str,
    chatgpt_plan_enabled: bool,
    chatgpt_plan_model: str | None,
    reasoning_model: str | None,
) -> GoalInterpreter | None:
    """Build from existing model/provider configuration without inventing a new brain."""

    if chatgpt_plan_enabled and str(chatgpt_plan_model or "").strip():
        client = build_chatgpt_plan_structured_output_client(
            model=str(chatgpt_plan_model).strip()
        )
        return GoalInterpreter(client=client)

    model = str(reasoning_model or "").strip()
    if not model:
        return None
    client = build_structured_output_client(provider=provider, model=model)
    return GoalInterpreter(client=client)


class GoalInterpretationShadowRuntime:
    """Asynchronous shadow observer with zero authority over existing routing."""

    def __init__(
        self,
        *,
        conversation: ConversationSession,
        interpreter: GoalInterpreter,
        store: GoalStore,
    ) -> None:
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be a ConversationSession")
        if not isinstance(interpreter, GoalInterpreter):
            raise TypeError("interpreter must be GoalInterpreter")
        if not isinstance(store, GoalStore):
            raise TypeError("store must be GoalStore")
        self._conversation = conversation
        self._interpreter = interpreter
        self._store = store
        self._tasks: set[asyncio.Task[None]] = set()
        self._provider_circuit = BackgroundProviderCircuit()
        self._closed = False

    @property
    def pending_task_count(self) -> int:
        return len(self._tasks)

    @property
    def closed(self) -> bool:
        return self._closed

    def observe_turn(self, turn: ConversationTurn) -> None:
        if self._closed or turn.role is not ConversationRole.USER:
            return
        if not self._provider_circuit.allow_request():
            return
        if _contains_secret_assignment(turn.text):
            LOGGER.info(
                "GICC shadow skipped secret-bearing USER turn | turn_id=%s "
                "authoritative_behavior_unchanged=True",
                turn.turn_id,
            )
            return
        task = asyncio.create_task(
            self._process_turn(turn),
            name=f"jarvis-gicc-shadow-{turn.turn_id[:8]}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    async def _process_turn(self, turn: ConversationTurn) -> None:
        try:
            result = await self._interpreter.interpret(
                conversation=self._conversation,
                turn=turn,
                store=self._store,
            )
            self._provider_circuit.record_success()
            capability_payload = [
                {
                    "family": item.family,
                    "operations": list(item.operations),
                    "target_entity_type": item.target_entity_type,
                }
                for item in result.capability_requirements
            ]
            payload = {
                "candidate": result.candidate.canonical_payload(),
                "candidate_digest": result.candidate.digest,
                "capability_requirements": capability_payload,
                "input_digest": result.input_digest,
                "usage": result.usage,
                "usage_observed": result.usage_observed,
                "latency_ms": result.latency_ms,
                "legacy_authoritative_behavior_unchanged": True,
                "new_owner_questions": 0,
                "new_phase9_acquisitions": 0,
                "new_actions": 0,
            }
            evidence = self._store.put_shadow_interpretation(
                source_session_id=self._conversation.session_id,
                source_turn_id=turn.turn_id,
                provider_name=result.provider_name,
                model_name=result.model_name,
                actionable=result.actionable,
                payload=payload,
                created_at=datetime.now(UTC).isoformat(),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            trip = self._provider_circuit.record_failure(exc)
            if trip is not None:
                LOGGER.warning(
                    "GICC shadow paused for provider pressure | turn_id=%s "
                    "reason=%s status=%s retry_in=%.1fs attempts=%s "
                    "authoritative_behavior_unchanged=True",
                    turn.turn_id,
                    trip.reason,
                    trip.status_code,
                    trip.delay_seconds,
                    trip.failed_attempts,
                )
            else:
                LOGGER.exception(
                    "GICC shadow interpretation failed for turn %s; "
                    "authoritative conversation behavior is unchanged",
                    turn.turn_id,
                )
            return

        candidate = result.candidate
        LOGGER.info(
            "GICC shadow interpretation | turn_id=%s evidence_id=%s actionable=%s "
            "goal_kind=%s outcome_digest=%s entities=%s information_needs=%s "
            "capability_families=%s authoritative_behavior_unchanged=True "
            "owner_questions=0 phase9_acquisitions=0 actions=0",
            turn.turn_id,
            evidence["evidence_id"],
            result.actionable,
            candidate.goal_kind.value,
            canonical_digest({"desired_outcome": candidate.desired_outcome})[:16],
            len(candidate.candidate_entities),
            len(candidate.candidate_information_needs),
            [item.family for item in result.capability_requirements],
        )

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        task.result()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for task in tuple(self._tasks):
            task.cancel()
        LOGGER.info(
            "GICC shadow session closed | cancelled_tasks=%s "
            "authoritative_behavior_unchanged=True",
            len(self._tasks),
        )
