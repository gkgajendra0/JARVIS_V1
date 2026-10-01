"""Canonical contracts for Goal Intelligence & Capability Composition (GICC)."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from jarvis.engineering_substrate.canonical import canonical_digest


def _text(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _optional_text(value: object | None, *, field: str) -> str | None:
    return None if value is None else _text(value, field=field)


def _tokens(
    values: tuple[str, ...] | list[str],
    *,
    field: str,
    normalized: bool = False,
) -> tuple[str, ...]:
    items = tuple(
        _text(value, field=field).casefold()
        if normalized
        else _text(value, field=field)
        for value in values
    )
    if len(set(items)) != len(items):
        raise ValueError(f"{field} values must be unique")
    return tuple(sorted(items))


def _mapping(value: dict[str, object] | None, *, field: str) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be a dict")
    if any(not isinstance(key, str) or not key.strip() for key in value):
        raise ValueError(f"{field} keys must be non-empty strings")
    return dict(value)


def _timestamp(value: str | None, *, field: str) -> str:
    if value is None:
        return datetime.now(UTC).isoformat()
    parsed = datetime.fromisoformat(_text(value, field=field))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC).isoformat()


def _optional_timestamp(value: str | None, *, field: str) -> str | None:
    return None if value is None else _timestamp(value, field=field)


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _finite_non_negative(value: object, *, field: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return result


def _stable_id(prefix: str, payload: dict[str, object]) -> str:
    return f"{prefix}_{canonical_digest(payload)[:20]}"


def _assert_digest(payload: dict[str, object], digest: str, *, field: str) -> None:
    normalized = _text(digest, field=field).casefold()
    if canonical_digest(payload) != normalized:
        raise ValueError(f"{field} mismatch")


class GoalKind(str, Enum):
    ONE_SHOT = "one_shot"
    CONDITIONAL = "conditional"
    MONITORING = "monitoring"
    LONG_RUNNING = "long_running"


class GoalState(str, Enum):
    RECEIVED = "received"
    RESOLVING = "resolving"
    WAITING_INFORMATION = "waiting_information"
    REQUIREMENTS_READY = "requirements_ready"
    WAITING_CAPABILITY = "waiting_capability"
    PLANNED = "planned"
    EXECUTING = "executing"
    MONITORING = "monitoring"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EntityLifecycleState(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    RETIRED = "retired"


class InformationNeedCategory(str, Enum):
    MISSING_VALUE = "missing_value"
    AMBIGUOUS_REFERENCE = "ambiguous_reference"
    DISAMBIGUATION = "disambiguation"
    OWNER_PREFERENCE = "owner_preference"
    OWNER_SECRET = "owner_secret"
    AUTHORIZATION = "authorization"
    SUCCESS_CRITERIA = "success_criteria"
    PHYSICAL_OBSERVATION = "physical_observation"


class InformationNeedState(str, Enum):
    OPEN = "open"
    SELF_RESOLVING = "self_resolving"
    WAITING_FOR_OWNER = "waiting_for_owner"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class CapabilityGapState(str, Enum):
    OPEN = "open"
    SATISFIED = "satisfied"
    CANCELLED = "cancelled"


class PlanNodeType(str, Enum):
    ACTION = "action"
    OBSERVE = "observe"
    VERIFY = "verify"
    SUBGOAL = "subgoal"
    CLARIFY = "clarify"
    ACQUIRE_CAPABILITY = "acquire_capability"
    WAIT = "wait"
    MONITOR = "monitor"


class PlanNodeState(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class PlanState(str, Enum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class ContinuationBlockerType(str, Enum):
    INFORMATION_NEED = "information_need"
    CAPABILITY_ACQUISITION = "capability_acquisition"
    EXTERNAL_ACCEPTANCE = "external_acceptance"
    WAIT = "wait"
    WORK_ITEM = "work_item"


class ContinuationState(str, Enum):
    BLOCKED = "blocked"
    READY = "ready"
    RESUMED = "resumed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class OwnerGoalV2:
    goal_id: str
    goal_revision: int
    source_session_id: str
    source_turn_id: str
    exact_owner_request: str
    goal_kind: GoalKind
    desired_outcome: str
    completion_predicates: tuple[str, ...]
    referenced_entity_ids: tuple[str, ...]
    state: GoalState
    priority: int
    created_at: str
    updated_at: str
    interpretation_evidence: tuple[str, ...]
    digest: str

    @classmethod
    def create(
        cls,
        *,
        source_session_id: str,
        source_turn_id: str,
        exact_owner_request: str,
        goal_kind: GoalKind,
        desired_outcome: str,
        completion_predicates: tuple[str, ...] | list[str] = (),
        referenced_entity_ids: tuple[str, ...] | list[str] = (),
        state: GoalState = GoalState.RECEIVED,
        priority: int = 0,
        interpretation_evidence: tuple[str, ...] | list[str] = (),
        created_at: str | None = None,
    ) -> OwnerGoalV2:
        session_id = _text(source_session_id, field="source_session_id")
        turn_id = _text(source_turn_id, field="source_turn_id")
        if not isinstance(goal_kind, GoalKind):
            raise TypeError("goal_kind must be GoalKind")
        if not isinstance(state, GoalState):
            raise TypeError("state must be GoalState")
        priority_value = _non_negative_int(priority, field="priority")
        created = _timestamp(created_at, field="created_at")
        goal_id = _stable_id(
            "goal",
            {"source_session_id": session_id, "source_turn_id": turn_id},
        )
        instance = cls(
            goal_id=goal_id,
            goal_revision=1,
            source_session_id=session_id,
            source_turn_id=turn_id,
            exact_owner_request=_text(exact_owner_request, field="exact_owner_request"),
            goal_kind=goal_kind,
            desired_outcome=_text(desired_outcome, field="desired_outcome"),
            completion_predicates=_tokens(
                tuple(completion_predicates), field="completion_predicate"
            ),
            referenced_entity_ids=_tokens(
                tuple(referenced_entity_ids),
                field="referenced_entity_id",
                normalized=True,
            ),
            state=state,
            priority=priority_value,
            created_at=created,
            updated_at=created,
            interpretation_evidence=_tokens(
                tuple(interpretation_evidence), field="interpretation_evidence"
            ),
            digest="pending",
        )
        return replace(instance, digest=canonical_digest(instance.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "source_session_id": self.source_session_id,
            "source_turn_id": self.source_turn_id,
            "exact_owner_request": self.exact_owner_request,
            "goal_kind": self.goal_kind.value,
            "desired_outcome": self.desired_outcome,
            "completion_predicates": list(self.completion_predicates),
            "referenced_entity_ids": list(self.referenced_entity_ids),
            "state": self.state.value,
            "priority": self.priority,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "interpretation_evidence": list(self.interpretation_evidence),
        }

    def __post_init__(self) -> None:
        _text(self.goal_id, field="goal_id")
        _positive_int(self.goal_revision, field="goal_revision")
        _text(self.source_session_id, field="source_session_id")
        _text(self.source_turn_id, field="source_turn_id")
        _text(self.exact_owner_request, field="exact_owner_request")
        _text(self.desired_outcome, field="desired_outcome")
        if not isinstance(self.goal_kind, GoalKind) or not isinstance(
            self.state, GoalState
        ):
            raise TypeError("goal_kind/state must use GICC enums")
        _non_negative_int(self.priority, field="priority")
        _timestamp(self.created_at, field="created_at")
        _timestamp(self.updated_at, field="updated_at")
        if self.digest != "pending":
            _assert_digest(self.canonical_payload(), self.digest, field="goal digest")

    def with_state(
        self,
        state: GoalState,
        *,
        updated_at: str | None = None,
    ) -> OwnerGoalV2:
        if not isinstance(state, GoalState):
            raise TypeError("state must be GoalState")
        candidate = replace(
            self,
            goal_revision=self.goal_revision + 1,
            state=state,
            updated_at=_timestamp(updated_at, field="updated_at"),
            digest="pending",
        )
        return replace(
            candidate, digest=canonical_digest(candidate.canonical_payload())
        )

    @classmethod
    def from_payload(cls, payload: dict[str, Any], digest: str) -> OwnerGoalV2:
        return cls(
            goal_id=payload["goal_id"],
            goal_revision=int(payload["goal_revision"]),
            source_session_id=payload["source_session_id"],
            source_turn_id=payload["source_turn_id"],
            exact_owner_request=payload["exact_owner_request"],
            goal_kind=GoalKind(payload["goal_kind"]),
            desired_outcome=payload["desired_outcome"],
            completion_predicates=tuple(payload["completion_predicates"]),
            referenced_entity_ids=tuple(payload["referenced_entity_ids"]),
            state=GoalState(payload["state"]),
            priority=int(payload["priority"]),
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            interpretation_evidence=tuple(payload["interpretation_evidence"]),
            digest=digest,
        )


@dataclass(frozen=True, slots=True)
class GoalInterpretationCandidateV1:
    desired_outcome: str
    goal_kind: GoalKind
    candidate_entities: tuple[str, ...]
    candidate_completion_predicates: tuple[str, ...]
    candidate_information_needs: tuple[str, ...]
    reasoning_evidence_refs: tuple[str, ...]
    digest: str

    @classmethod
    def create(
        cls,
        *,
        desired_outcome: str,
        goal_kind: GoalKind,
        candidate_entities: tuple[str, ...] | list[str] = (),
        candidate_completion_predicates: tuple[str, ...] | list[str] = (),
        candidate_information_needs: tuple[str, ...] | list[str] = (),
        reasoning_evidence_refs: tuple[str, ...] | list[str] = (),
    ) -> GoalInterpretationCandidateV1:
        if not isinstance(goal_kind, GoalKind):
            raise TypeError("goal_kind must be GoalKind")
        item = cls(
            desired_outcome=_text(desired_outcome, field="desired_outcome"),
            goal_kind=goal_kind,
            candidate_entities=_tokens(
                tuple(candidate_entities), field="candidate_entity"
            ),
            candidate_completion_predicates=_tokens(
                tuple(candidate_completion_predicates),
                field="candidate_completion_predicate",
            ),
            candidate_information_needs=_tokens(
                tuple(candidate_information_needs),
                field="candidate_information_need",
            ),
            reasoning_evidence_refs=_tokens(
                tuple(reasoning_evidence_refs), field="reasoning_evidence_ref"
            ),
            digest="pending",
        )
        return replace(item, digest=canonical_digest(item.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "desired_outcome": self.desired_outcome,
            "goal_kind": self.goal_kind.value,
            "candidate_entities": list(self.candidate_entities),
            "candidate_completion_predicates": list(
                self.candidate_completion_predicates
            ),
            "candidate_information_needs": list(self.candidate_information_needs),
            "reasoning_evidence_refs": list(self.reasoning_evidence_refs),
        }

    def __post_init__(self) -> None:
        _text(self.desired_outcome, field="desired_outcome")
        if not isinstance(self.goal_kind, GoalKind):
            raise TypeError("goal_kind must be GoalKind")
        if self.digest != "pending":
            _assert_digest(
                self.canonical_payload(), self.digest, field="interpretation digest"
            )


@dataclass(frozen=True, slots=True)
class WorldEntityRefV1:
    entity_id: str
    entity_type: str
    canonical_name: str
    aliases: tuple[str, ...]
    relation_ids: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    lifecycle_state: EntityLifecycleState
    digest: str

    @classmethod
    def create(
        cls,
        *,
        entity_type: str,
        canonical_name: str,
        aliases: tuple[str, ...] | list[str] = (),
        relation_ids: tuple[str, ...] | list[str] = (),
        provenance_refs: tuple[str, ...] | list[str] = (),
        lifecycle_state: EntityLifecycleState = EntityLifecycleState.ACTIVE,
        entity_id: str | None = None,
    ) -> WorldEntityRefV1:
        kind = _text(entity_type, field="entity_type").casefold()
        name = _text(canonical_name, field="canonical_name")
        if not isinstance(lifecycle_state, EntityLifecycleState):
            raise TypeError("lifecycle_state must be EntityLifecycleState")
        stable = entity_id or _stable_id(
            "entity", {"entity_type": kind, "canonical_name": name.casefold()}
        )
        item = cls(
            entity_id=_text(stable, field="entity_id").casefold(),
            entity_type=kind,
            canonical_name=name,
            aliases=_tokens(tuple(aliases), field="alias"),
            relation_ids=_tokens(
                tuple(relation_ids), field="relation_id", normalized=True
            ),
            provenance_refs=_tokens(tuple(provenance_refs), field="provenance_ref"),
            lifecycle_state=lifecycle_state,
            digest="pending",
        )
        return replace(item, digest=canonical_digest(item.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "canonical_name": self.canonical_name,
            "aliases": list(self.aliases),
            "relation_ids": list(self.relation_ids),
            "provenance_refs": list(self.provenance_refs),
            "lifecycle_state": self.lifecycle_state.value,
        }

    def __post_init__(self) -> None:
        _text(self.entity_id, field="entity_id")
        _text(self.entity_type, field="entity_type")
        _text(self.canonical_name, field="canonical_name")
        if not isinstance(self.lifecycle_state, EntityLifecycleState):
            raise TypeError("lifecycle_state must be EntityLifecycleState")
        if self.digest != "pending":
            _assert_digest(self.canonical_payload(), self.digest, field="entity digest")

    @classmethod
    def from_payload(cls, payload: dict[str, Any], digest: str) -> WorldEntityRefV1:
        return cls(
            entity_id=payload["entity_id"],
            entity_type=payload["entity_type"],
            canonical_name=payload["canonical_name"],
            aliases=tuple(payload["aliases"]),
            relation_ids=tuple(payload["relation_ids"]),
            provenance_refs=tuple(payload["provenance_refs"]),
            lifecycle_state=EntityLifecycleState(payload["lifecycle_state"]),
            digest=digest,
        )


@dataclass(frozen=True, slots=True)
class ResourceBindingV1:
    binding_id: str
    binding_revision: int
    entity_id: str
    provider_id: str
    provider_resource_id: str
    capability_keys: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    last_verified_at: str
    binding_digest: str

    @classmethod
    def create(
        cls,
        *,
        entity_id: str,
        provider_id: str,
        provider_resource_id: str,
        capability_keys: tuple[str, ...] | list[str] = (),
        evidence_refs: tuple[str, ...] | list[str] = (),
        last_verified_at: str | None = None,
    ) -> ResourceBindingV1:
        entity = _text(entity_id, field="entity_id").casefold()
        provider = _text(provider_id, field="provider_id").casefold()
        resource = _text(provider_resource_id, field="provider_resource_id")
        binding_id = _stable_id(
            "binding",
            {
                "entity_id": entity,
                "provider_id": provider,
                "provider_resource_id": resource,
            },
        )
        item = cls(
            binding_id=binding_id,
            binding_revision=1,
            entity_id=entity,
            provider_id=provider,
            provider_resource_id=resource,
            capability_keys=_tokens(
                tuple(capability_keys), field="capability_key", normalized=True
            ),
            evidence_refs=_tokens(tuple(evidence_refs), field="evidence_ref"),
            last_verified_at=_timestamp(last_verified_at, field="last_verified_at"),
            binding_digest="pending",
        )
        return replace(item, binding_digest=canonical_digest(item.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "binding_id": self.binding_id,
            "binding_revision": self.binding_revision,
            "entity_id": self.entity_id,
            "provider_id": self.provider_id,
            "provider_resource_id": self.provider_resource_id,
            "capability_keys": list(self.capability_keys),
            "evidence_refs": list(self.evidence_refs),
            "last_verified_at": self.last_verified_at,
        }

    def __post_init__(self) -> None:
        _positive_int(self.binding_revision, field="binding_revision")
        _timestamp(self.last_verified_at, field="last_verified_at")
        if self.binding_digest != "pending":
            _assert_digest(
                self.canonical_payload(),
                self.binding_digest,
                field="binding digest",
            )

    @classmethod
    def from_payload(cls, payload: dict[str, Any], digest: str) -> ResourceBindingV1:
        return cls(
            binding_id=payload["binding_id"],
            binding_revision=int(payload["binding_revision"]),
            entity_id=payload["entity_id"],
            provider_id=payload["provider_id"],
            provider_resource_id=payload["provider_resource_id"],
            capability_keys=tuple(payload["capability_keys"]),
            evidence_refs=tuple(payload["evidence_refs"]),
            last_verified_at=payload["last_verified_at"],
            binding_digest=digest,
        )


@dataclass(frozen=True, slots=True)
class InformationNeedV1:
    information_need_id: str
    revision: int
    goal_id: str
    plan_node_id: str | None
    category: InformationNeedCategory
    subject: str
    required_fact: str
    why_required: str
    candidate_values: tuple[str, ...]
    allowed_resolution_sources: tuple[str, ...]
    self_resolution_attempts: tuple[str, ...]
    owner_question: str | None
    answer_schema: dict[str, object]
    state: InformationNeedState
    created_at: str
    resolved_at: str | None
    resolution_ref: str | None
    evidence_refs: tuple[str, ...]
    digest: str

    @classmethod
    def create(
        cls,
        *,
        goal_id: str,
        category: InformationNeedCategory,
        subject: str,
        required_fact: str,
        why_required: str,
        plan_node_id: str | None = None,
        candidate_values: tuple[str, ...] | list[str] = (),
        allowed_resolution_sources: tuple[str, ...] | list[str] = (),
        self_resolution_attempts: tuple[str, ...] | list[str] = (),
        owner_question: str | None = None,
        answer_schema: dict[str, object] | None = None,
        state: InformationNeedState = InformationNeedState.OPEN,
        evidence_refs: tuple[str, ...] | list[str] = (),
        created_at: str | None = None,
    ) -> InformationNeedV1:
        if not isinstance(category, InformationNeedCategory):
            raise TypeError("category must be InformationNeedCategory")
        if not isinstance(state, InformationNeedState):
            raise TypeError("state must be InformationNeedState")
        goal = _text(goal_id, field="goal_id").casefold()
        subject_value = _text(subject, field="subject")
        fact = _text(required_fact, field="required_fact")
        plan = _optional_text(plan_node_id, field="plan_node_id")
        need_id = _stable_id(
            "information_need",
            {
                "goal_id": goal,
                "plan_node_id": plan,
                "category": category.value,
                "subject": subject_value.casefold(),
                "required_fact": fact.casefold(),
            },
        )
        created = _timestamp(created_at, field="created_at")
        item = cls(
            information_need_id=need_id,
            revision=1,
            goal_id=goal,
            plan_node_id=plan,
            category=category,
            subject=subject_value,
            required_fact=fact,
            why_required=_text(why_required, field="why_required"),
            candidate_values=_tokens(tuple(candidate_values), field="candidate_value"),
            allowed_resolution_sources=_tokens(
                tuple(allowed_resolution_sources),
                field="allowed_resolution_source",
                normalized=True,
            ),
            self_resolution_attempts=_tokens(
                tuple(self_resolution_attempts),
                field="self_resolution_attempt",
            ),
            owner_question=_optional_text(owner_question, field="owner_question"),
            answer_schema=_mapping(answer_schema, field="answer_schema"),
            state=state,
            created_at=created,
            resolved_at=None,
            resolution_ref=None,
            evidence_refs=_tokens(tuple(evidence_refs), field="evidence_ref"),
            digest="pending",
        )
        return replace(item, digest=canonical_digest(item.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "information_need_id": self.information_need_id,
            "revision": self.revision,
            "goal_id": self.goal_id,
            "plan_node_id": self.plan_node_id,
            "category": self.category.value,
            "subject": self.subject,
            "required_fact": self.required_fact,
            "why_required": self.why_required,
            "candidate_values": list(self.candidate_values),
            "allowed_resolution_sources": list(self.allowed_resolution_sources),
            "self_resolution_attempts": list(self.self_resolution_attempts),
            "owner_question": self.owner_question,
            "answer_schema": self.answer_schema,
            "state": self.state.value,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolution_ref": self.resolution_ref,
            "evidence_refs": list(self.evidence_refs),
        }

    def __post_init__(self) -> None:
        _positive_int(self.revision, field="revision")
        if not isinstance(self.category, InformationNeedCategory):
            raise TypeError("category must be InformationNeedCategory")
        if not isinstance(self.state, InformationNeedState):
            raise TypeError("state must be InformationNeedState")
        _timestamp(self.created_at, field="created_at")
        _optional_timestamp(self.resolved_at, field="resolved_at")
        if (
            self.category is InformationNeedCategory.OWNER_SECRET
            and self.resolution_ref
            and self.resolution_ref.startswith(("plain:", "value:"))
        ):
            raise ValueError("OWNER_SECRET resolution must reference the secret store")
        if self.state is InformationNeedState.RESOLVED and (
            self.resolved_at is None or self.resolution_ref is None
        ):
            raise ValueError("resolved information need requires resolution metadata")
        if self.digest != "pending":
            _assert_digest(
                self.canonical_payload(), self.digest, field="information need digest"
            )

    def with_resolution(
        self,
        *,
        resolution_ref: str,
        evidence_refs: tuple[str, ...] | list[str] = (),
        resolved_at: str | None = None,
    ) -> InformationNeedV1:
        reference = _text(resolution_ref, field="resolution_ref")
        combined = _tokens(
            tuple(self.evidence_refs) + tuple(evidence_refs), field="evidence_ref"
        )
        candidate = replace(
            self,
            revision=self.revision + 1,
            state=InformationNeedState.RESOLVED,
            resolved_at=_timestamp(resolved_at, field="resolved_at"),
            resolution_ref=reference,
            evidence_refs=combined,
            digest="pending",
        )
        return replace(
            candidate, digest=canonical_digest(candidate.canonical_payload())
        )

    @classmethod
    def from_payload(cls, payload: dict[str, Any], digest: str) -> InformationNeedV1:
        return cls(
            information_need_id=payload["information_need_id"],
            revision=int(payload["revision"]),
            goal_id=payload["goal_id"],
            plan_node_id=payload["plan_node_id"],
            category=InformationNeedCategory(payload["category"]),
            subject=payload["subject"],
            required_fact=payload["required_fact"],
            why_required=payload["why_required"],
            candidate_values=tuple(payload["candidate_values"]),
            allowed_resolution_sources=tuple(payload["allowed_resolution_sources"]),
            self_resolution_attempts=tuple(payload["self_resolution_attempts"]),
            owner_question=payload["owner_question"],
            answer_schema=dict(payload["answer_schema"]),
            state=InformationNeedState(payload["state"]),
            created_at=payload["created_at"],
            resolved_at=payload["resolved_at"],
            resolution_ref=payload["resolution_ref"],
            evidence_refs=tuple(payload["evidence_refs"]),
            digest=digest,
        )


@dataclass(frozen=True, slots=True)
class CapabilityRequirementV1:
    requirement_id: str
    goal_id: str
    semantic_capability: str
    operation: str
    target_entity_id: str | None
    target_entity_type: str | None
    required_parameters_schema: dict[str, object]
    preconditions: tuple[str, ...]
    expected_postconditions: tuple[str, ...]
    observation_requirements: tuple[str, ...]
    reason: str
    digest: str

    @classmethod
    def create(
        cls,
        *,
        goal_id: str,
        semantic_capability: str,
        operation: str,
        target_entity_id: str | None = None,
        target_entity_type: str | None = None,
        required_parameters_schema: dict[str, object] | None = None,
        preconditions: tuple[str, ...] | list[str] = (),
        expected_postconditions: tuple[str, ...] | list[str] = (),
        observation_requirements: tuple[str, ...] | list[str] = (),
        reason: str,
    ) -> CapabilityRequirementV1:
        goal = _text(goal_id, field="goal_id").casefold()
        semantic = _text(semantic_capability, field="semantic_capability").casefold()
        operation_value = _text(operation, field="operation").casefold()
        target_id = _optional_text(target_entity_id, field="target_entity_id")
        target_type = _optional_text(target_entity_type, field="target_entity_type")
        requirement_id = _stable_id(
            "requirement",
            {
                "goal_id": goal,
                "semantic_capability": semantic,
                "operation": operation_value,
                "target_entity_id": target_id,
                "target_entity_type": target_type,
            },
        )
        item = cls(
            requirement_id=requirement_id,
            goal_id=goal,
            semantic_capability=semantic,
            operation=operation_value,
            target_entity_id=target_id,
            target_entity_type=(
                None if target_type is None else target_type.casefold()
            ),
            required_parameters_schema=_mapping(
                required_parameters_schema, field="required_parameters_schema"
            ),
            preconditions=_tokens(tuple(preconditions), field="precondition"),
            expected_postconditions=_tokens(
                tuple(expected_postconditions), field="expected_postcondition"
            ),
            observation_requirements=_tokens(
                tuple(observation_requirements), field="observation_requirement"
            ),
            reason=_text(reason, field="reason"),
            digest="pending",
        )
        return replace(item, digest=canonical_digest(item.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "goal_id": self.goal_id,
            "semantic_capability": self.semantic_capability,
            "operation": self.operation,
            "target_entity_id": self.target_entity_id,
            "target_entity_type": self.target_entity_type,
            "required_parameters_schema": self.required_parameters_schema,
            "preconditions": list(self.preconditions),
            "expected_postconditions": list(self.expected_postconditions),
            "observation_requirements": list(self.observation_requirements),
            "reason": self.reason,
        }

    def __post_init__(self) -> None:
        if self.digest != "pending":
            _assert_digest(
                self.canonical_payload(), self.digest, field="requirement digest"
            )

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], digest: str
    ) -> CapabilityRequirementV1:
        return cls(
            requirement_id=payload["requirement_id"],
            goal_id=payload["goal_id"],
            semantic_capability=payload["semantic_capability"],
            operation=payload["operation"],
            target_entity_id=payload["target_entity_id"],
            target_entity_type=payload["target_entity_type"],
            required_parameters_schema=dict(payload["required_parameters_schema"]),
            preconditions=tuple(payload["preconditions"]),
            expected_postconditions=tuple(payload["expected_postconditions"]),
            observation_requirements=tuple(payload["observation_requirements"]),
            reason=payload["reason"],
            digest=digest,
        )


@dataclass(frozen=True, slots=True)
class CapabilityRequirementGraphV1:
    graph_id: str
    goal_id: str
    requirements: tuple[CapabilityRequirementV1, ...]
    information_need_ids: tuple[str, ...]
    world_state_preconditions: tuple[str, ...]
    completion_predicates: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    digest: str

    @classmethod
    def create(
        cls,
        *,
        goal_id: str,
        requirements: tuple[CapabilityRequirementV1, ...]
        | list[CapabilityRequirementV1],
        information_need_ids: tuple[str, ...] | list[str] = (),
        world_state_preconditions: tuple[str, ...] | list[str] = (),
        completion_predicates: tuple[str, ...] | list[str] = (),
        edges: tuple[tuple[str, str], ...] | list[tuple[str, str]] = (),
    ) -> CapabilityRequirementGraphV1:
        goal = _text(goal_id, field="goal_id").casefold()
        requirement_values = tuple(requirements)
        if any(
            not isinstance(requirement, CapabilityRequirementV1)
            for requirement in requirement_values
        ):
            raise TypeError("requirements must contain CapabilityRequirementV1 values")
        if any(requirement.goal_id != goal for requirement in requirement_values):
            raise ValueError("all requirements must belong to the graph goal")
        requirement_ids = tuple(
            sorted(requirement.requirement_id for requirement in requirement_values)
        )
        if len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError("requirement IDs must be unique")
        normalized_edges = tuple(sorted(tuple(edge) for edge in edges))
        if any(len(edge) != 2 or edge[0] == edge[1] for edge in normalized_edges):
            raise ValueError("requirement graph edges must be two distinct node IDs")
        graph_id = _stable_id(
            "requirement_graph",
            {
                "goal_id": goal,
                "requirement_ids": list(requirement_ids),
                "edges": [list(edge) for edge in normalized_edges],
            },
        )
        item = cls(
            graph_id=graph_id,
            goal_id=goal,
            requirements=requirement_values,
            information_need_ids=_tokens(
                tuple(information_need_ids),
                field="information_need_id",
                normalized=True,
            ),
            world_state_preconditions=_tokens(
                tuple(world_state_preconditions), field="world_state_precondition"
            ),
            completion_predicates=_tokens(
                tuple(completion_predicates), field="completion_predicate"
            ),
            edges=normalized_edges,
            digest="pending",
        )
        item._validate_acyclic()
        return replace(item, digest=canonical_digest(item.canonical_payload()))

    @property
    def requirement_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(requirement.requirement_id for requirement in self.requirements)
        )

    def _validate_acyclic(self) -> None:
        nodes = set(self.requirement_ids) | set(self.information_need_ids)
        nodes.update(self.world_state_preconditions)
        nodes.update(self.completion_predicates)
        adjacency: dict[str, set[str]] = {node: set() for node in nodes}
        for source, target in self.edges:
            if source not in adjacency or target not in adjacency:
                raise ValueError("requirement graph edge references unknown node")
            adjacency[source].add(target)
        temporary: set[str] = set()
        permanent: set[str] = set()

        def visit(node: str) -> None:
            if node in permanent:
                return
            if node in temporary:
                raise ValueError("requirement graph must be acyclic")
            temporary.add(node)
            for child in adjacency[node]:
                visit(child)
            temporary.remove(node)
            permanent.add(node)

        for node in sorted(nodes):
            visit(node)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "graph_id": self.graph_id,
            "goal_id": self.goal_id,
            "requirements": [
                requirement.canonical_payload() | {"digest": requirement.digest}
                for requirement in self.requirements
            ],
            "information_need_ids": list(self.information_need_ids),
            "world_state_preconditions": list(self.world_state_preconditions),
            "completion_predicates": list(self.completion_predicates),
            "edges": [list(edge) for edge in self.edges],
        }

    def __post_init__(self) -> None:
        self._validate_acyclic()
        if self.digest != "pending":
            _assert_digest(
                self.canonical_payload(), self.digest, field="requirement graph digest"
            )

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], digest: str
    ) -> CapabilityRequirementGraphV1:
        requirements = tuple(
            CapabilityRequirementV1.from_payload(
                {key: value for key, value in item.items() if key != "digest"},
                item["digest"],
            )
            for item in payload["requirements"]
        )
        return cls(
            graph_id=payload["graph_id"],
            goal_id=payload["goal_id"],
            requirements=requirements,
            information_need_ids=tuple(payload["information_need_ids"]),
            world_state_preconditions=tuple(payload["world_state_preconditions"]),
            completion_predicates=tuple(payload["completion_predicates"]),
            edges=tuple(tuple(edge) for edge in payload["edges"]),
            digest=digest,
        )


@dataclass(frozen=True, slots=True)
class CapabilityGapV1:
    gap_id: str
    revision: int
    goal_id: str
    requirement_ids: tuple[str, ...]
    reusable_capability_family: str
    target_entity_type: str
    target_entity_id: str | None
    minimum_required_operations: tuple[str, ...]
    matching_capability_keys: tuple[str, ...]
    missing_reason_codes: tuple[str, ...]
    motivating_goal_id: str
    state: CapabilityGapState
    digest: str

    @classmethod
    def create(
        cls,
        *,
        goal_id: str,
        requirement_ids: tuple[str, ...] | list[str],
        reusable_capability_family: str,
        target_entity_type: str,
        minimum_required_operations: tuple[str, ...] | list[str],
        target_entity_id: str | None = None,
        matching_capability_keys: tuple[str, ...] | list[str] = (),
        missing_reason_codes: tuple[str, ...] | list[str] = (),
        motivating_goal_id: str | None = None,
        state: CapabilityGapState = CapabilityGapState.OPEN,
    ) -> CapabilityGapV1:
        if not isinstance(state, CapabilityGapState):
            raise TypeError("state must be CapabilityGapState")
        goal = _text(goal_id, field="goal_id").casefold()
        family = _text(
            reusable_capability_family, field="reusable_capability_family"
        ).casefold()
        target_type = _text(target_entity_type, field="target_entity_type").casefold()
        target_id = _optional_text(target_entity_id, field="target_entity_id")
        operations = _tokens(
            tuple(minimum_required_operations),
            field="minimum_required_operation",
            normalized=True,
        )
        if not operations:
            raise ValueError("minimum_required_operations must not be empty")
        gap_id = _stable_id(
            "capability_gap",
            {
                "goal_id": goal,
                "reusable_capability_family": family,
                "target_entity_type": target_type,
                "target_entity_id": target_id,
                "minimum_required_operations": list(operations),
            },
        )
        item = cls(
            gap_id=gap_id,
            revision=1,
            goal_id=goal,
            requirement_ids=_tokens(
                tuple(requirement_ids), field="requirement_id", normalized=True
            ),
            reusable_capability_family=family,
            target_entity_type=target_type,
            target_entity_id=target_id,
            minimum_required_operations=operations,
            matching_capability_keys=_tokens(
                tuple(matching_capability_keys),
                field="matching_capability_key",
                normalized=True,
            ),
            missing_reason_codes=_tokens(
                tuple(missing_reason_codes),
                field="missing_reason_code",
                normalized=True,
            ),
            motivating_goal_id=_text(
                motivating_goal_id or goal, field="motivating_goal_id"
            ).casefold(),
            state=state,
            digest="pending",
        )
        return replace(item, digest=canonical_digest(item.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "gap_id": self.gap_id,
            "revision": self.revision,
            "goal_id": self.goal_id,
            "requirement_ids": list(self.requirement_ids),
            "reusable_capability_family": self.reusable_capability_family,
            "target_entity_type": self.target_entity_type,
            "target_entity_id": self.target_entity_id,
            "minimum_required_operations": list(self.minimum_required_operations),
            "matching_capability_keys": list(self.matching_capability_keys),
            "missing_reason_codes": list(self.missing_reason_codes),
            "motivating_goal_id": self.motivating_goal_id,
            "state": self.state.value,
        }

    def __post_init__(self) -> None:
        _positive_int(self.revision, field="revision")
        if not isinstance(self.state, CapabilityGapState):
            raise TypeError("state must be CapabilityGapState")
        if self.digest != "pending":
            _assert_digest(self.canonical_payload(), self.digest, field="gap digest")

    @classmethod
    def from_payload(cls, payload: dict[str, Any], digest: str) -> CapabilityGapV1:
        return cls(
            gap_id=payload["gap_id"],
            revision=int(payload["revision"]),
            goal_id=payload["goal_id"],
            requirement_ids=tuple(payload["requirement_ids"]),
            reusable_capability_family=payload["reusable_capability_family"],
            target_entity_type=payload["target_entity_type"],
            target_entity_id=payload["target_entity_id"],
            minimum_required_operations=tuple(payload["minimum_required_operations"]),
            matching_capability_keys=tuple(payload["matching_capability_keys"]),
            missing_reason_codes=tuple(payload["missing_reason_codes"]),
            motivating_goal_id=payload["motivating_goal_id"],
            state=CapabilityGapState(payload["state"]),
            digest=digest,
        )


@dataclass(frozen=True, slots=True)
class PlanNodeV1:
    node_id: str
    node_type: PlanNodeType
    state: PlanNodeState
    summary: str
    capability_key: str | None = None
    operation: str | None = None
    work_id: str | None = None
    information_need_id: str | None = None
    gap_id: str | None = None
    subgoal_id: str | None = None
    postcondition_ref: str | None = None
    digest: str = "pending"

    @classmethod
    def create(
        cls,
        *,
        plan_identity: str,
        ordinal: int,
        node_type: PlanNodeType,
        summary: str,
        state: PlanNodeState = PlanNodeState.PENDING,
        capability_key: str | None = None,
        operation: str | None = None,
        work_id: str | None = None,
        information_need_id: str | None = None,
        gap_id: str | None = None,
        subgoal_id: str | None = None,
        postcondition_ref: str | None = None,
    ) -> PlanNodeV1:
        if not isinstance(node_type, PlanNodeType):
            raise TypeError("node_type must be PlanNodeType")
        if not isinstance(state, PlanNodeState):
            raise TypeError("state must be PlanNodeState")
        ordinal_value = _non_negative_int(ordinal, field="ordinal")
        node_id = _stable_id(
            "plan_node",
            {
                "plan_identity": _text(plan_identity, field="plan_identity"),
                "ordinal": ordinal_value,
            },
        )
        item = cls(
            node_id=node_id,
            node_type=node_type,
            state=state,
            summary=_text(summary, field="summary"),
            capability_key=_optional_text(capability_key, field="capability_key"),
            operation=_optional_text(operation, field="operation"),
            work_id=_optional_text(work_id, field="work_id"),
            information_need_id=_optional_text(
                information_need_id, field="information_need_id"
            ),
            gap_id=_optional_text(gap_id, field="gap_id"),
            subgoal_id=_optional_text(subgoal_id, field="subgoal_id"),
            postcondition_ref=_optional_text(
                postcondition_ref, field="postcondition_ref"
            ),
            digest="pending",
        )
        return replace(item, digest=canonical_digest(item.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "state": self.state.value,
            "summary": self.summary,
            "capability_key": self.capability_key,
            "operation": self.operation,
            "work_id": self.work_id,
            "information_need_id": self.information_need_id,
            "gap_id": self.gap_id,
            "subgoal_id": self.subgoal_id,
            "postcondition_ref": self.postcondition_ref,
        }

    def __post_init__(self) -> None:
        if not isinstance(self.node_type, PlanNodeType):
            raise TypeError("node_type must be PlanNodeType")
        if not isinstance(self.state, PlanNodeState):
            raise TypeError("state must be PlanNodeState")
        if self.node_type is PlanNodeType.ACTION and (
            self.capability_key is None or self.operation is None
        ):
            raise ValueError("ACTION node requires capability_key and operation")
        if self.node_type is PlanNodeType.CLARIFY and self.information_need_id is None:
            raise ValueError("CLARIFY node requires information_need_id")
        if self.node_type is PlanNodeType.ACQUIRE_CAPABILITY and self.gap_id is None:
            raise ValueError("ACQUIRE_CAPABILITY node requires gap_id")
        if self.node_type is PlanNodeType.SUBGOAL and self.subgoal_id is None:
            raise ValueError("SUBGOAL node requires subgoal_id")
        if self.digest != "pending":
            _assert_digest(
                self.canonical_payload(), self.digest, field="plan node digest"
            )

    @classmethod
    def from_payload(cls, payload: dict[str, Any], digest: str) -> PlanNodeV1:
        return cls(
            node_id=payload["node_id"],
            node_type=PlanNodeType(payload["node_type"]),
            state=PlanNodeState(payload["state"]),
            summary=payload["summary"],
            capability_key=payload["capability_key"],
            operation=payload["operation"],
            work_id=payload["work_id"],
            information_need_id=payload["information_need_id"],
            gap_id=payload["gap_id"],
            subgoal_id=payload["subgoal_id"],
            postcondition_ref=payload["postcondition_ref"],
            digest=digest,
        )


@dataclass(frozen=True, slots=True)
class PlanGraphV1:
    plan_id: str
    goal_id: str
    goal_revision: int
    plan_revision: int
    nodes: tuple[PlanNodeV1, ...]
    edges: tuple[tuple[str, str], ...]
    root_node_ids: tuple[str, ...]
    completion_node_ids: tuple[str, ...]
    state: PlanState
    created_at: str
    updated_at: str
    digest: str

    @classmethod
    def create(
        cls,
        *,
        goal_id: str,
        goal_revision: int,
        nodes: tuple[PlanNodeV1, ...] | list[PlanNodeV1],
        edges: tuple[tuple[str, str], ...] | list[tuple[str, str]],
        root_node_ids: tuple[str, ...] | list[str],
        completion_node_ids: tuple[str, ...] | list[str],
        plan_revision: int = 1,
        state: PlanState = PlanState.PROPOSED,
        created_at: str | None = None,
    ) -> PlanGraphV1:
        if not isinstance(state, PlanState):
            raise TypeError("state must be PlanState")
        goal = _text(goal_id, field="goal_id").casefold()
        goal_rev = _positive_int(goal_revision, field="goal_revision")
        plan_rev = _positive_int(plan_revision, field="plan_revision")
        node_values = tuple(nodes)
        if not node_values or any(
            not isinstance(node, PlanNodeV1) for node in node_values
        ):
            raise ValueError("nodes must contain at least one PlanNodeV1")
        plan_id = _stable_id(
            "plan",
            {"goal_id": goal, "goal_revision": goal_rev, "plan_revision": plan_rev},
        )
        created = _timestamp(created_at, field="created_at")
        item = cls(
            plan_id=plan_id,
            goal_id=goal,
            goal_revision=goal_rev,
            plan_revision=plan_rev,
            nodes=node_values,
            edges=tuple(sorted(tuple(edge) for edge in edges)),
            root_node_ids=_tokens(
                tuple(root_node_ids), field="root_node_id", normalized=True
            ),
            completion_node_ids=_tokens(
                tuple(completion_node_ids), field="completion_node_id", normalized=True
            ),
            state=state,
            created_at=created,
            updated_at=created,
            digest="pending",
        )
        item._validate_graph()
        return replace(item, digest=canonical_digest(item.canonical_payload()))

    def _validate_graph(self) -> None:
        node_ids = {node.node_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("plan node IDs must be unique")
        if not set(self.root_node_ids).issubset(node_ids):
            raise ValueError("root_node_ids reference unknown nodes")
        if not set(self.completion_node_ids).issubset(node_ids):
            raise ValueError("completion_node_ids reference unknown nodes")
        adjacency = {node_id: set() for node_id in node_ids}
        for source, target in self.edges:
            if source not in node_ids or target not in node_ids or source == target:
                raise ValueError("plan edge references invalid nodes")
            adjacency[source].add(target)
        temporary: set[str] = set()
        permanent: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in permanent:
                return
            if node_id in temporary:
                raise ValueError("PlanGraph must be a DAG")
            temporary.add(node_id)
            for child in adjacency[node_id]:
                visit(child)
            temporary.remove(node_id)
            permanent.add(node_id)

        for node_id in sorted(node_ids):
            visit(node_id)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "plan_revision": self.plan_revision,
            "nodes": [
                node.canonical_payload() | {"digest": node.digest}
                for node in self.nodes
            ],
            "edges": [list(edge) for edge in self.edges],
            "root_node_ids": list(self.root_node_ids),
            "completion_node_ids": list(self.completion_node_ids),
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def __post_init__(self) -> None:
        self._validate_graph()
        if not isinstance(self.state, PlanState):
            raise TypeError("state must be PlanState")
        _timestamp(self.created_at, field="created_at")
        _timestamp(self.updated_at, field="updated_at")
        if self.digest != "pending":
            _assert_digest(self.canonical_payload(), self.digest, field="plan digest")

    @classmethod
    def from_payload(cls, payload: dict[str, Any], digest: str) -> PlanGraphV1:
        node_payloads = payload["nodes"]
        nodes = tuple(
            PlanNodeV1.from_payload(
                {key: value for key, value in item.items() if key != "digest"},
                item["digest"],
            )
            for item in node_payloads
        )
        return cls(
            plan_id=payload["plan_id"],
            goal_id=payload["goal_id"],
            goal_revision=int(payload["goal_revision"]),
            plan_revision=int(payload["plan_revision"]),
            nodes=nodes,
            edges=tuple(tuple(edge) for edge in payload["edges"]),
            root_node_ids=tuple(payload["root_node_ids"]),
            completion_node_ids=tuple(payload["completion_node_ids"]),
            state=PlanState(payload["state"]),
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            digest=digest,
        )


@dataclass(frozen=True, slots=True)
class GoalContinuationV1:
    continuation_id: str
    revision: int
    goal_id: str
    plan_id: str
    blocked_by_type: ContinuationBlockerType
    blocked_by_id: str
    resume_node_id: str
    work_ids: tuple[str, ...]
    goal_revision: int
    state: ContinuationState
    created_at: str
    resumed_at: str | None
    digest: str

    @classmethod
    def create(
        cls,
        *,
        goal_id: str,
        plan_id: str,
        blocked_by_type: ContinuationBlockerType,
        blocked_by_id: str,
        resume_node_id: str,
        goal_revision: int,
        work_ids: tuple[str, ...] | list[str] = (),
        state: ContinuationState = ContinuationState.BLOCKED,
        created_at: str | None = None,
    ) -> GoalContinuationV1:
        if not isinstance(blocked_by_type, ContinuationBlockerType):
            raise TypeError("blocked_by_type must be ContinuationBlockerType")
        if not isinstance(state, ContinuationState):
            raise TypeError("state must be ContinuationState")
        goal = _text(goal_id, field="goal_id").casefold()
        plan = _text(plan_id, field="plan_id").casefold()
        blocker = _text(blocked_by_id, field="blocked_by_id")
        resume = _text(resume_node_id, field="resume_node_id")
        continuation_id = _stable_id(
            "continuation",
            {
                "goal_id": goal,
                "plan_id": plan,
                "blocked_by_type": blocked_by_type.value,
                "blocked_by_id": blocker,
                "resume_node_id": resume,
            },
        )
        item = cls(
            continuation_id=continuation_id,
            revision=1,
            goal_id=goal,
            plan_id=plan,
            blocked_by_type=blocked_by_type,
            blocked_by_id=blocker,
            resume_node_id=resume,
            work_ids=_tokens(tuple(work_ids), field="work_id", normalized=True),
            goal_revision=_positive_int(goal_revision, field="goal_revision"),
            state=state,
            created_at=_timestamp(created_at, field="created_at"),
            resumed_at=None,
            digest="pending",
        )
        return replace(item, digest=canonical_digest(item.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "continuation_id": self.continuation_id,
            "revision": self.revision,
            "goal_id": self.goal_id,
            "plan_id": self.plan_id,
            "blocked_by_type": self.blocked_by_type.value,
            "blocked_by_id": self.blocked_by_id,
            "resume_node_id": self.resume_node_id,
            "work_ids": list(self.work_ids),
            "goal_revision": self.goal_revision,
            "state": self.state.value,
            "created_at": self.created_at,
            "resumed_at": self.resumed_at,
        }

    def __post_init__(self) -> None:
        _positive_int(self.revision, field="revision")
        _positive_int(self.goal_revision, field="goal_revision")
        if not isinstance(self.blocked_by_type, ContinuationBlockerType):
            raise TypeError("blocked_by_type must be ContinuationBlockerType")
        if not isinstance(self.state, ContinuationState):
            raise TypeError("state must be ContinuationState")
        if self.state is ContinuationState.RESUMED and self.resumed_at is None:
            raise ValueError("resumed continuation requires resumed_at")
        if self.digest != "pending":
            _assert_digest(
                self.canonical_payload(), self.digest, field="continuation digest"
            )

    def resumed(self, *, resumed_at: str | None = None) -> GoalContinuationV1:
        if self.state is ContinuationState.RESUMED:
            return self
        candidate = replace(
            self,
            revision=self.revision + 1,
            state=ContinuationState.RESUMED,
            resumed_at=_timestamp(resumed_at, field="resumed_at"),
            digest="pending",
        )
        return replace(
            candidate, digest=canonical_digest(candidate.canonical_payload())
        )

    @classmethod
    def from_payload(cls, payload: dict[str, Any], digest: str) -> GoalContinuationV1:
        return cls(
            continuation_id=payload["continuation_id"],
            revision=int(payload["revision"]),
            goal_id=payload["goal_id"],
            plan_id=payload["plan_id"],
            blocked_by_type=ContinuationBlockerType(payload["blocked_by_type"]),
            blocked_by_id=payload["blocked_by_id"],
            resume_node_id=payload["resume_node_id"],
            work_ids=tuple(payload["work_ids"]),
            goal_revision=int(payload["goal_revision"]),
            state=ContinuationState(payload["state"]),
            created_at=payload["created_at"],
            resumed_at=payload["resumed_at"],
            digest=digest,
        )


@dataclass(frozen=True, slots=True)
class MonitorPredicateV1:
    predicate_id: str
    goal_id: str
    source_entity_ids: tuple[str, ...]
    observation_capabilities: tuple[str, ...]
    semantic_condition: str
    candidate_trigger_strategy: str
    stability_window: float
    cooldown: float
    timeout: float | None
    completion_policy: str
    notification_policy: str
    verification_requirement: str
    digest: str

    @classmethod
    def create(
        cls,
        *,
        goal_id: str,
        source_entity_ids: tuple[str, ...] | list[str],
        observation_capabilities: tuple[str, ...] | list[str],
        semantic_condition: str,
        candidate_trigger_strategy: str,
        stability_window: float = 0.0,
        cooldown: float = 0.0,
        timeout: float | None = None,
        completion_policy: str,
        notification_policy: str,
        verification_requirement: str,
    ) -> MonitorPredicateV1:
        timeout_value = (
            None if timeout is None else _finite_non_negative(timeout, field="timeout")
        )
        goal = _text(goal_id, field="goal_id").casefold()
        sources = _tokens(
            tuple(source_entity_ids), field="source_entity_id", normalized=True
        )
        condition = _text(semantic_condition, field="semantic_condition")
        predicate_id = _stable_id(
            "monitor_predicate",
            {
                "goal_id": goal,
                "source_entity_ids": list(sources),
                "semantic_condition": condition,
            },
        )
        item = cls(
            predicate_id=predicate_id,
            goal_id=goal,
            source_entity_ids=sources,
            observation_capabilities=_tokens(
                tuple(observation_capabilities),
                field="observation_capability",
                normalized=True,
            ),
            semantic_condition=condition,
            candidate_trigger_strategy=_text(
                candidate_trigger_strategy, field="candidate_trigger_strategy"
            ),
            stability_window=_finite_non_negative(
                stability_window, field="stability_window"
            ),
            cooldown=_finite_non_negative(cooldown, field="cooldown"),
            timeout=timeout_value,
            completion_policy=_text(completion_policy, field="completion_policy"),
            notification_policy=_text(notification_policy, field="notification_policy"),
            verification_requirement=_text(
                verification_requirement, field="verification_requirement"
            ),
            digest="pending",
        )
        return replace(item, digest=canonical_digest(item.canonical_payload()))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "predicate_id": self.predicate_id,
            "goal_id": self.goal_id,
            "source_entity_ids": list(self.source_entity_ids),
            "observation_capabilities": list(self.observation_capabilities),
            "semantic_condition": self.semantic_condition,
            "candidate_trigger_strategy": self.candidate_trigger_strategy,
            "stability_window": self.stability_window,
            "cooldown": self.cooldown,
            "timeout": self.timeout,
            "completion_policy": self.completion_policy,
            "notification_policy": self.notification_policy,
            "verification_requirement": self.verification_requirement,
        }

    def __post_init__(self) -> None:
        _finite_non_negative(self.stability_window, field="stability_window")
        _finite_non_negative(self.cooldown, field="cooldown")
        if self.timeout is not None:
            _finite_non_negative(self.timeout, field="timeout")
        if self.digest != "pending":
            _assert_digest(
                self.canonical_payload(), self.digest, field="monitor predicate digest"
            )

    @classmethod
    def from_payload(cls, payload: dict[str, Any], digest: str) -> MonitorPredicateV1:
        return cls(
            predicate_id=payload["predicate_id"],
            goal_id=payload["goal_id"],
            source_entity_ids=tuple(payload["source_entity_ids"]),
            observation_capabilities=tuple(payload["observation_capabilities"]),
            semantic_condition=payload["semantic_condition"],
            candidate_trigger_strategy=payload["candidate_trigger_strategy"],
            stability_window=float(payload["stability_window"]),
            cooldown=float(payload["cooldown"]),
            timeout=None if payload["timeout"] is None else float(payload["timeout"]),
            completion_policy=payload["completion_policy"],
            notification_policy=payload["notification_policy"],
            verification_requirement=payload["verification_requirement"],
            digest=digest,
        )
