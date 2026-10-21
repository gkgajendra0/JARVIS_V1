"""Bounded proposals and immutable canonical input snapshots; never authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from jarvis.conversation import (
    ConversationRole,
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
)

Category = Literal[
    "owned_item", "food_preference", "response_preference", "routine", "goal"
]


@dataclass(frozen=True)
class AcceptedLearningSource:
    runtime_id: str
    session_id: str
    receipt_id: str
    turns: tuple[ConversationTurn, ...]
    created_monotonic: float
    digest: str

    @classmethod
    def from_turn(cls, runtime_id, conversation, turn, *, now):
        if (
            not isinstance(conversation, ConversationSession)
            or conversation.status is not ConversationStatus.ACTIVE
            or turn.role is not ConversationRole.USER
            or not any(t is turn for t in conversation.turns)
        ):
            raise ValueError("canonical accepted USER source required")
        users = tuple(t for t in conversation.turns if t.role is ConversationRole.USER)
        if not users or users[-1] is not turn or not runtime_id:
            raise ValueError("latest canonical user source required")
        window = users[-4:]
        if sum(len(t.text.encode("utf-8")) for t in window) > 8000:
            raise ValueError("learning source exceeds 8000 bytes")
        encoded = json.dumps([(t.turn_id, t.text) for t in window], ensure_ascii=False)
        return cls(
            runtime_id,
            conversation.session_id,
            str(uuid4()),
            window,
            now,
            hashlib.sha256(encoded.encode()).hexdigest(),
        )

    @property
    def turn_id(self):
        return self.turns[-1].turn_id

    @property
    def text(self):
        return self.turns[-1].text


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    turn_id: str = Field(min_length=1, max_length=128)
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)


class LearningCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    category: Category
    kind: Literal["vehicle", "device", "other"] = "other"
    intent: Literal["new", "change", "correction", "retraction", "transient", "none"]
    label: str = Field(min_length=1, max_length=240)
    value: str = Field(min_length=1, max_length=1200)
    evidence: list[EvidenceSpan] = Field(min_length=1, max_length=8)
    qualification: Literal["direct", "quoted", "hypothetical", "uncertain"] = "direct"
    importance: Literal["stable", "ongoing", "transient"] = "stable"
    sensitivity: Literal["standard", "private", "local_only", "secret_prohibited"] = (
        "standard"
    )
    state: Literal["owned", "not_owned", "active", "completed"] = "active"
    scalar_facet: (
        Literal["diet_preference", "response_language", "response_style"] | None
    ) = None
    confidence: float = Field(default=0, ge=0, le=1)

    @property
    def suppression_key(self):
        return (
            f"owned_item.{self.kind}"
            if self.category == "owned_item"
            else self.category
        )


class LearningBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidates: list[LearningCandidate] = Field(default_factory=list, max_length=8)


class LearningCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    assertion_id: str
    predicate: str
    category: str
    text: str = Field(max_length=1800)
    value: str = Field(max_length=1800)
    kind: str = "other"


class LearningCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entries: list[LearningCatalogEntry] = Field(default_factory=list, max_length=32)
    suppression_epochs: dict[str, int] = Field(default_factory=dict)


class LearningResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_index: int = Field(ge=0, lt=8, strict=True)
    decision: Literal["match", "new", "uncertain", "duplicate"]
    target_id: str | None = None


class LearningResolutionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resolutions: list[LearningResolution] = Field(default_factory=list, max_length=8)


@dataclass(frozen=True)
class LearningEligibility:
    status: str
    reason: str = ""


@dataclass(frozen=True)
class LearningAdmissionResult:
    status: str
    assertion_ids: tuple[str, ...] = ()
