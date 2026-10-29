"""Grounded, process-local semantic conversation state.

This is a proposal/reconciliation boundary, NOT a memory write path. A model may
propose typed changes, but only accepted canonical USER turns can supply evidence.
An owner-authorized caller must explicitly decide whether to expose a snapshot.
Nothing in this module reads or writes persistent storage or calls an LLM.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.memory.types import Sensitivity


class SemanticAction(StrEnum):
    TOPIC = "topic"
    GOAL = "goal"
    CONSTRAINT = "constraint"
    PENDING_STEP = "pending_step"
    COMPLETE_STEP = "complete_step"
    CORRECT = "correct"
    FORGET_TOPIC = "forget_topic"


class EvidenceStrength(StrEnum):
    LITERAL = "literal"
    INTERPRETED = "interpreted"


class SemanticRejected(ValueError):
    """Untrusted semantic proposal or canonical source does not pass admission."""


@dataclass(frozen=True, slots=True)
class SemanticProposal:
    action: SemanticAction
    quote: str
    start: int
    end: int
    value: str = ""
    key: str = ""
    topic: str = ""
    sensitivity: Sensitivity = Sensitivity.STANDARD


@dataclass(frozen=True, slots=True)
class GroundedStateValue:
    value: str
    evidence: str
    source_turn_id: str
    accepted_at: datetime
    sensitivity: Sensitivity
    evidence_strength: EvidenceStrength
    completed: bool = False


@dataclass(slots=True)
class _Topic:
    title: str
    goal: GroundedStateValue | None = None
    constraints: dict[str, GroundedStateValue] = field(default_factory=dict)
    pending_steps: dict[str, GroundedStateValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TopicSnapshot:
    title: str
    goal: GroundedStateValue | None
    constraints: tuple[tuple[str, GroundedStateValue], ...]
    steps: tuple[tuple[str, GroundedStateValue], ...]


class SemanticContextEngine:
    """Bounded transient topics. Does not persist or release protected context.

    Extractors provide *proposals*, not authority. Each proposed change has to
    quote an exact span of an accepted canonical user turn. Untrusted proposals
    cannot switch topics implicitly, rewrite older values, or resurrect forgotten
    topics from older turns. The caller owns authentication and redaction.
    """

    def __init__(self, *, max_topics: int = 8, max_fields: int = 20) -> None:
        if type(max_topics) is not int or not 1 <= max_topics <= 32:
            raise ValueError("max_topics must be an integer between 1 and 32")
        if type(max_fields) is not int or not 1 <= max_fields <= 64:
            raise ValueError("max_fields must be an integer between 1 and 64")
        self.max_topics = max_topics
        self.max_fields = max_fields
        self._topics: dict[str, _Topic] = {}
        self._active: str | None = None
        self._seen: set[str] = set()
        self._cutoffs: dict[str, datetime] = {}

    @property
    def active_topic(self) -> str | None:
        topic = self._topics.get(self._active or "")
        return topic.title if topic else None

    def clear(self) -> None:
        """On lock, revoke, or protected-session retirement: clear everything."""
        self._topics.clear()
        self._active = None
        self._seen.clear()
        self._cutoffs.clear()

    def snapshot(self, topic: str | None = None) -> TopicSnapshot | None:
        """Returns a local snapshot only. The caller must check release authority."""
        key = self._key(topic) if topic is not None else self._active
        state = self._topics.get(key or "")
        if state is None:
            return None
        return TopicSnapshot(
            title=state.title,
            goal=state.goal,
            constraints=tuple(sorted(state.constraints.items())),
            steps=tuple(sorted(state.pending_steps.items())),
        )

    def apply(
        self,
        conversation: ConversationSession,
        turn: ConversationTurn,
        proposals: tuple[SemanticProposal, ...] | list[SemanticProposal],
    ) -> int:
        """Validate and apply one ordered canonical user turn atomically.

        All source and proposal checks run before mutation. No AI-produced
        instruction or assistant turn is treated as owner evidence.
        """
        if not isinstance(conversation, ConversationSession):
            raise SemanticRejected("invalid canonical conversation")
        if (
            not isinstance(turn, ConversationTurn)
            or turn.role is not ConversationRole.USER
        ):
            raise SemanticRejected("only accepted USER turns are eligible")
        if not any(original is turn for original in conversation.turns):
            raise SemanticRejected("turn not present in canonical conversation")
        if turn.turn_id in self._seen:
            return 0
        if len(self._seen) >= 4096:
            raise SemanticRejected("session input budget exhausted")
        if not isinstance(proposals, (tuple, list)) or len(proposals) > 12:
            raise SemanticRejected("invalid proposal batch")
        if not proposals:
            self._seen.add(turn.turn_id)
            return 0
        for proposal in proposals:
            self._validate_proposal(turn, proposal)

        # Work on a detached copy: no partial changes on an invalid proposal.
        topics = {
            key: _Topic(
                value.title,
                value.goal,
                dict(value.constraints),
                dict(value.pending_steps),
            )
            for key, value in self._topics.items()
        }
        active = self._active
        cutoffs = dict(self._cutoffs)
        changed = 0
        for proposal in proposals:
            key = self._key(proposal.topic) if proposal.topic else active
            if proposal.action is SemanticAction.TOPIC:
                key = self._key(proposal.value)
                if key not in self._key(proposal.quote):
                    raise SemanticRejected("topic must be named in the user evidence")
                cutoff = cutoffs.get(key)
                if cutoff is not None and turn.accepted_at <= cutoff:
                    raise SemanticRejected("stale topic after forget")
                if key not in topics and len(topics) >= self.max_topics:
                    raise SemanticRejected("topic capacity exceeded")
                if key not in topics:
                    topics[key] = _Topic(proposal.value.strip())
                active = key
                changed += 1
                continue
            if key is None:
                raise SemanticRejected("no active topic; explicit topic required")
            if proposal.topic and key != active:
                raise SemanticRejected("cannot modify inactive topic implicitly")
            cutoff = cutoffs.get(key)
            if cutoff is not None and turn.accepted_at <= cutoff:
                raise SemanticRejected("stale turn after forget")
            if proposal.action is SemanticAction.FORGET_TOPIC:
                title = topics.get(key).title if key in topics else ""
                if title and self._key(title) not in self._key(proposal.quote):
                    raise SemanticRejected("forget must name the active topic")
                topics.pop(key, None)
                cutoffs[key] = turn.accepted_at
                if active == key:
                    active = None
                changed += 1
                continue
            state = topics.get(key)
            if state is None:
                raise SemanticRejected("unknown topic")
            fact = GroundedStateValue(
                value=proposal.value.strip(),
                evidence=proposal.quote,
                source_turn_id=turn.turn_id,
                accepted_at=turn.accepted_at,
                sensitivity=proposal.sensitivity,
                evidence_strength=(
                    EvidenceStrength.LITERAL
                    if proposal.value.strip().casefold() in proposal.quote.casefold()
                    else EvidenceStrength.INTERPRETED
                ),
            )
            if proposal.action is SemanticAction.GOAL:
                if self._newer(state.goal, turn):
                    state.goal = fact
                    changed += 1
            elif proposal.action in (SemanticAction.CONSTRAINT, SemanticAction.CORRECT):
                field_key = self._key(proposal.key)
                if (
                    proposal.action is SemanticAction.CORRECT
                    and field_key not in state.constraints
                ):
                    raise SemanticRejected("correction has no target")
                if (
                    field_key not in state.constraints
                    and len(state.constraints) >= self.max_fields
                ):
                    raise SemanticRejected("constraint capacity exceeded")
                if self._newer(state.constraints.get(field_key), turn):
                    state.constraints[field_key] = fact
                    changed += 1
            elif proposal.action is SemanticAction.PENDING_STEP:
                field_key = self._key(proposal.key)
                if (
                    field_key not in state.pending_steps
                    and len(state.pending_steps) >= self.max_fields
                ):
                    raise SemanticRejected("step capacity exceeded")
                if self._newer(state.pending_steps.get(field_key), turn):
                    state.pending_steps[field_key] = fact
                    changed += 1
            elif proposal.action is SemanticAction.COMPLETE_STEP:
                field_key = self._key(proposal.key)
                if field_key not in self._key(proposal.quote):
                    raise SemanticRejected("completion must name the pending step")
                old = state.pending_steps.get(field_key)
                if old is None:
                    raise SemanticRejected("completion has no matching pending step")
                if self._newer(old, turn):
                    state.pending_steps[field_key] = GroundedStateValue(
                        value=old.value,
                        evidence=proposal.quote,
                        source_turn_id=turn.turn_id,
                        accepted_at=turn.accepted_at,
                        sensitivity=old.sensitivity,
                        evidence_strength=EvidenceStrength.INTERPRETED,
                        completed=True,
                    )
                    changed += 1
            else:
                raise SemanticRejected("unsupported action")
        self._topics = topics
        self._active = active
        self._cutoffs = cutoffs
        self._seen.add(turn.turn_id)
        return changed

    @staticmethod
    def _key(text: str) -> str:
        if not isinstance(text, str) or not text.strip() or len(text) > 160:
            raise SemanticRejected("invalid topic or field key")
        return unicodedata.normalize("NFKC", text).strip().casefold()

    @staticmethod
    def _newer(previous: GroundedStateValue | None, turn: ConversationTurn) -> bool:
        return previous is None or turn.accepted_at > previous.accepted_at

    @staticmethod
    def _validate_proposal(turn: ConversationTurn, proposal: SemanticProposal) -> None:
        if not isinstance(proposal, SemanticProposal):
            raise SemanticRejected("invalid proposal")
        if not isinstance(proposal.action, SemanticAction):
            raise SemanticRejected("unknown semantic action")
        if proposal.sensitivity is Sensitivity.SECRET_PROHIBITED:
            raise SemanticRejected("secret prohibited from working state")
        if not isinstance(proposal.sensitivity, Sensitivity):
            raise SemanticRejected("invalid sensitivity")
        if (
            type(proposal.start) is not int
            or type(proposal.end) is not int
            or proposal.start < 0
            or proposal.end <= proposal.start
            or proposal.end > len(turn.text)
        ):
            raise SemanticRejected("invalid evidence span")
        quote = turn.text[proposal.start : proposal.end]
        if not proposal.quote or quote != proposal.quote or len(quote) > 1000:
            raise SemanticRejected("proposal does not match exact user evidence")
        if len(proposal.value) > 500 or len(proposal.key) > 160:
            raise SemanticRejected("proposal too long")
        if (
            proposal.action
            not in (
                SemanticAction.FORGET_TOPIC,
                SemanticAction.COMPLETE_STEP,
            )
            and not proposal.value.strip()
        ):
            raise SemanticRejected("missing semantic value")
        if (
            proposal.action
            in (
                SemanticAction.CONSTRAINT,
                SemanticAction.CORRECT,
                SemanticAction.PENDING_STEP,
                SemanticAction.COMPLETE_STEP,
            )
            and not proposal.key.strip()
        ):
            raise SemanticRejected("missing field key")
        # Reject invented numbers, dates, quantities and currency amounts.
        # Linguistic paraphrase is permitted in the *transient* context only.
        numbers = set(re.findall(r"\d+(?:[.,]\d+)*", quote))
        if not set(re.findall(r"\d+(?:[.,]\d+)*", proposal.value)).issubset(numbers):
            raise SemanticRejected("unquoted numerical claim")
