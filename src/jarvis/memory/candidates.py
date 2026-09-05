"""Typed memory-candidate extraction and process-local quarantine primitives."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn

from .explicit import (
    ExplicitMemoryAction,
    ExplicitMemoryAuthorizationError,
    MemorySecretRejectedError,
    authorize_explicit_memory_action,
    latest_user_turn,
    reject_prohibited_secret,
)
from .types import AuthorityClass, MemorySourceClass


class MemoryExtractionIntent(StrEnum):
    REMEMBER = "remember"
    CANDIDATE = "candidate"
    TRANSIENT = "transient"
    HISTORICAL_CHANGE = "historical_change"
    CORRECTION = "correction"
    FORGET = "forget"
    RETRACTION = "retraction"
    UNTRUSTED = "untrusted"
    NONE = "none"
    SENSITIVE_REJECT = "sensitive_reject_or_secret_store"


class MemoryCandidateType(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    RULE = "rule"
    WEAK_PREFERENCE = "weak_preference"
    SESSION_INSTRUCTION = "session_instruction"
    INTERACTION_CONTEXT = "interaction_context"
    FACT_CHANGE = "fact_change"
    FACT_CORRECTION = "fact_correction"
    DELETION_REQUEST = "deletion_request"
    FACT_RETRACTION = "fact_retraction"
    EPISODE_DECISION = "episode_decision"
    INCIDENT_OBSERVATION = "incident_observation"
    SECRET = "secret"
    UNCERTAIN_FUTURE = "uncertain_future"
    NONE = "none"


class MemoryExtractionSensitivity(StrEnum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    SECRET = "secret"


class MemoryCandidateDisposition(StrEnum):
    QUARANTINE = "quarantine"
    DROP = "drop"


class MemoryCandidateOutcome(StrEnum):
    QUARANTINED = "quarantined"
    SKIPPED_EXPLICIT_MEMORY_CONTROL = "skipped_explicit_memory_control"
    REJECTED_SECRET = "rejected_secret"
    REJECTED_POLICY = "rejected_policy"


class MemoryExtractionProposal(BaseModel):
    """Provider proposal only; this model never represents canonical truth."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent: MemoryExtractionIntent
    candidate_type: MemoryCandidateType
    durable_candidate: bool
    subject: str | None = Field(default=None, min_length=1, max_length=160)
    predicate: str | None = Field(default=None, min_length=1, max_length=160)
    value: str | None = Field(default=None, min_length=1, max_length=1200)
    temporal_hint: str | None = Field(default=None, min_length=1, max_length=240)
    sensitivity: MemoryExtractionSensitivity
    confidence: float = Field(ge=0.0, le=1.0)


class MemoryCandidateExtractor(Protocol):
    """Provider-swappable semantic proposal boundary."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def extract(self, *, text: str) -> MemoryExtractionProposal: ...


@dataclass(frozen=True, slots=True)
class MemoryCandidatePolicyDecision:
    disposition: MemoryCandidateDisposition
    reason_code: str


class MemoryCandidatePolicy:
    """Deterministic eligibility for quarantine; never promotes canonical memory."""

    _ALLOWED_INTENTS = frozenset(
        {
            MemoryExtractionIntent.CANDIDATE,
            MemoryExtractionIntent.HISTORICAL_CHANGE,
            MemoryExtractionIntent.CORRECTION,
            MemoryExtractionIntent.RETRACTION,
        }
    )
    _ALLOWED_TYPES = frozenset(
        {
            MemoryCandidateType.FACT,
            MemoryCandidateType.PREFERENCE,
            MemoryCandidateType.RULE,
            MemoryCandidateType.FACT_CHANGE,
            MemoryCandidateType.FACT_CORRECTION,
            MemoryCandidateType.FACT_RETRACTION,
            MemoryCandidateType.EPISODE_DECISION,
            MemoryCandidateType.INCIDENT_OBSERVATION,
        }
    )

    def evaluate(self, proposal: MemoryExtractionProposal) -> MemoryCandidatePolicyDecision:
        if not isinstance(proposal, MemoryExtractionProposal):
            raise TypeError("proposal must be a MemoryExtractionProposal")
        if proposal.sensitivity is MemoryExtractionSensitivity.SECRET:
            return MemoryCandidatePolicyDecision(
                MemoryCandidateDisposition.DROP,
                "secret_proposal",
            )
        if proposal.candidate_type is MemoryCandidateType.SECRET:
            return MemoryCandidatePolicyDecision(
                MemoryCandidateDisposition.DROP,
                "secret_candidate_type",
            )
        if not proposal.durable_candidate:
            return MemoryCandidatePolicyDecision(
                MemoryCandidateDisposition.DROP,
                "provider_marked_non_durable",
            )
        if proposal.intent not in self._ALLOWED_INTENTS:
            return MemoryCandidatePolicyDecision(
                MemoryCandidateDisposition.DROP,
                "intent_not_quarantine_eligible",
            )
        if proposal.candidate_type not in self._ALLOWED_TYPES:
            return MemoryCandidatePolicyDecision(
                MemoryCandidateDisposition.DROP,
                "candidate_type_not_quarantine_eligible",
            )
        if proposal.subject is None or proposal.predicate is None or proposal.value is None:
            return MemoryCandidatePolicyDecision(
                MemoryCandidateDisposition.DROP,
                "incomplete_semantic_candidate",
            )
        return MemoryCandidatePolicyDecision(
            MemoryCandidateDisposition.QUARANTINE,
            "structurally_eligible_candidate",
        )


@dataclass(frozen=True, slots=True)
class QuarantinedMemoryCandidate:
    """Session-local structured evidence with JARVIS-owned provenance."""

    candidate_id: str
    session_id: str
    source_turn_id: str
    source_accepted_at: datetime
    source_class: MemorySourceClass
    authority_class: AuthorityClass
    proposal: MemoryExtractionProposal
    extractor_provider: str
    extractor_model: str
    quarantined_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "session_id",
            "source_turn_id",
            "extractor_provider",
            "extractor_model",
        ):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            normalized = value.strip()
            if not normalized:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, normalized)
        if not isinstance(self.source_class, MemorySourceClass):
            raise TypeError("source_class must be a MemorySourceClass")
        if not isinstance(self.authority_class, AuthorityClass):
            raise TypeError("authority_class must be an AuthorityClass")
        if not isinstance(self.proposal, MemoryExtractionProposal):
            raise TypeError("proposal must be a MemoryExtractionProposal")
        object.__setattr__(
            self,
            "source_accepted_at",
            _aware_utc(self.source_accepted_at, name="source_accepted_at"),
        )
        object.__setattr__(
            self,
            "quarantined_at",
            _aware_utc(self.quarantined_at, name="quarantined_at"),
        )


class MemoryCandidateQuarantine:
    """Non-durable candidate staging owned by exactly one conversation session."""

    def __init__(self, *, session_id: str) -> None:
        if not isinstance(session_id, str):
            raise TypeError("session_id must be a string")
        normalized = session_id.strip()
        if not normalized:
            raise ValueError("session_id must not be empty")
        self._session_id = normalized
        self._candidates: list[QuarantinedMemoryCandidate] = []
        self._candidate_ids: set[str] = set()
        self._disposed = False

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def disposed(self) -> bool:
        return self._disposed

    def add(self, candidate: QuarantinedMemoryCandidate) -> None:
        if self._disposed:
            raise RuntimeError("memory candidate quarantine is disposed")
        if not isinstance(candidate, QuarantinedMemoryCandidate):
            raise TypeError("candidate must be a QuarantinedMemoryCandidate")
        if candidate.session_id != self._session_id:
            raise ValueError("candidate belongs to a different conversation session")
        if candidate.candidate_id in self._candidate_ids:
            raise ValueError("candidate_id is already quarantined")
        self._candidates.append(candidate)
        self._candidate_ids.add(candidate.candidate_id)

    def snapshot(self) -> tuple[QuarantinedMemoryCandidate, ...]:
        if self._disposed:
            return ()
        return tuple(self._candidates)

    def dispose(self) -> None:
        self._candidates.clear()
        self._candidate_ids.clear()
        self._disposed = True


@dataclass(frozen=True, slots=True)
class MemoryCandidateProcessingResult:
    outcome: MemoryCandidateOutcome
    reason_code: str
    candidate: QuarantinedMemoryCandidate | None = None


class MemoryCandidateCoordinator:
    """Run bounded extraction and quarantine without touching durable memory."""

    def __init__(
        self,
        *,
        extractor: MemoryCandidateExtractor,
        quarantine: MemoryCandidateQuarantine,
        policy: MemoryCandidatePolicy | None = None,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not callable(getattr(extractor, "extract", None)):
            raise TypeError("extractor must implement MemoryCandidateExtractor")
        self._extractor = extractor
        self._quarantine = quarantine
        self._policy = policy or MemoryCandidatePolicy()
        self._id_factory = id_factory
        self._clock = clock

    async def consider_latest_user_turn(
        self,
        conversation: ConversationSession,
    ) -> MemoryCandidateProcessingResult:
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be a ConversationSession")
        if conversation.session_id != self._quarantine.session_id:
            raise ValueError("conversation does not own this candidate quarantine")

        turn = latest_user_turn(conversation)
        if turn.role is not ConversationRole.USER:
            raise RuntimeError("candidate extraction requires a canonical USER turn")

        if _is_explicit_memory_control(conversation):
            return MemoryCandidateProcessingResult(
                MemoryCandidateOutcome.SKIPPED_EXPLICIT_MEMORY_CONTROL,
                "phase_4_3_explicit_memory_control",
            )

        try:
            reject_prohibited_secret(
                predicate="candidate_extraction",
                value=turn.text,
            )
        except MemorySecretRejectedError:
            return MemoryCandidateProcessingResult(
                MemoryCandidateOutcome.REJECTED_SECRET,
                "local_secret_prefilter",
            )

        proposal = await self._extractor.extract(text=turn.text)
        if not isinstance(proposal, MemoryExtractionProposal):
            raise TypeError("extractor returned an invalid proposal type")

        try:
            reject_prohibited_secret(
                predicate=proposal.predicate or "candidate",
                value=proposal.value or "",
            )
        except MemorySecretRejectedError:
            return MemoryCandidateProcessingResult(
                MemoryCandidateOutcome.REJECTED_SECRET,
                "proposal_secret_guard",
            )

        decision = self._policy.evaluate(proposal)
        if decision.disposition is MemoryCandidateDisposition.DROP:
            return MemoryCandidateProcessingResult(
                MemoryCandidateOutcome.REJECTED_POLICY,
                decision.reason_code,
            )

        candidate = self._build_candidate(turn=turn, proposal=proposal)
        self._quarantine.add(candidate)
        return MemoryCandidateProcessingResult(
            MemoryCandidateOutcome.QUARANTINED,
            decision.reason_code,
            candidate,
        )

    def _build_candidate(
        self,
        *,
        turn: ConversationTurn,
        proposal: MemoryExtractionProposal,
    ) -> QuarantinedMemoryCandidate:
        candidate_id = self._id_factory()
        quarantined_at = _aware_utc(self._clock(), name="quarantined_at")
        provider_name = str(self._extractor.provider_name).strip()
        model_name = str(self._extractor.model_name).strip()
        return QuarantinedMemoryCandidate(
            candidate_id=candidate_id,
            session_id=self._quarantine.session_id,
            source_turn_id=turn.turn_id,
            source_accepted_at=turn.accepted_at,
            source_class=MemorySourceClass.OWNER_DIRECT,
            authority_class=AuthorityClass.OWNER_DIRECT,
            proposal=proposal,
            extractor_provider=provider_name,
            extractor_model=model_name,
            quarantined_at=quarantined_at,
        )


def _is_explicit_memory_control(conversation: ConversationSession) -> bool:
    for action in ExplicitMemoryAction:
        try:
            authorize_explicit_memory_action(conversation, action)
        except ExplicitMemoryAuthorizationError:
            continue
        return True
    return False


def _aware_utc(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
