"""Research-only, deterministic, fail-closed decision gate for fictional memories.

NO database, Hindsight SDK, provider, network, filesystem writes or owner data.
This is deliberately *not* a natural-language reasoner: callers supply a
verified structured assertion graph and an explicit question intent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MAX_ASSERTIONS = 12_000
MAX_CHAIN = 64
_SAFE_ID = re.compile(r"^synthetic-[a-z0-9-]{3,80}$")
_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_KINDS = frozenset(
    {
        "original_statement",
        "correction",
        "historical_state",
        "historical_change",
        "unrelated_current_fact",
    }
)


class DecisionSafetyError(ValueError):
    """Fixed failure reason only; never interpolate input content."""


@dataclass(frozen=True, slots=True)
class Assertion:
    assertion_id: str
    subject: str
    predicate: str
    value: str
    source_ref: str
    mentioned_at: str
    version: int
    revision_kind: str
    supersedes_id: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryQuestion:
    subject: str
    predicate: str
    intent: Literal["current", "original", "history"]


@dataclass(frozen=True, slots=True)
class MemoryDecision:
    status: Literal["answer", "abstain"]
    answer_code: str | None
    evidence_assertion_ids: tuple[str, ...]
    reason_code: str


def _time(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DecisionSafetyError("invalid_synthetic_timestamp")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DecisionSafetyError("invalid_synthetic_timestamp") from exc
    if dt.utcoffset() is None or dt.utcoffset().total_seconds() != 0:
        raise DecisionSafetyError("invalid_synthetic_timestamp")
    return dt


def _safe_fact(fact: Assertion) -> None:
    if not isinstance(fact, Assertion):
        raise DecisionSafetyError("invalid_assertion")
    if (
        not _SAFE_ID.fullmatch(fact.assertion_id)
        or not _SAFE_ID.fullmatch(fact.subject)
        or not _SAFE_NAME.fullmatch(fact.predicate)
        or not _SAFE_NAME.fullmatch(fact.value)
        or not isinstance(fact.source_ref, str)
        or not re.fullmatch(
            r"conversation:synthetic:synthetic-[a-z0-9-]{3,80}", fact.source_ref
        )
        or fact.revision_kind not in _KINDS
        or type(fact.version) is not int
        or not 1 <= fact.version <= MAX_CHAIN
        or (
            fact.supersedes_id is not None
            and (
                not isinstance(fact.supersedes_id, str)
                or not _SAFE_ID.fullmatch(fact.supersedes_id)
            )
        )
    ):
        raise DecisionSafetyError("untrusted_assertion")
    _time(fact.mentioned_at)


def _abstain(reason: str) -> MemoryDecision:
    return MemoryDecision("abstain", None, (), reason)


class MemoryDecisionIndex:
    """Strict graph projection. Multiple roots/branches and gaps abstain.

    Full lineage is required: a solitary 'corrected' fact cannot silently
    become a trusted current answer with its predecessor missing.
    """

    def __init__(self, assertions: tuple[Assertion, ...]) -> None:
        if (
            not isinstance(assertions, tuple)
            or len(assertions) > MAX_ASSERTIONS
        ):
            raise DecisionSafetyError("unbounded_assertion_collection")
        by_id: dict[str, Assertion] = {}
        grouped: dict[tuple[str, str], list[Assertion]] = {}
        for fact in assertions:
            _safe_fact(fact)
            if fact.assertion_id in by_id:
                raise DecisionSafetyError("duplicate_assertion")
            by_id[fact.assertion_id] = fact
            grouped.setdefault((fact.subject, fact.predicate), []).append(fact)
        self._by_id = by_id
        self._groups = grouped

    def decide(self, question: MemoryQuestion) -> MemoryDecision:
        if not isinstance(question, MemoryQuestion):
            raise DecisionSafetyError("invalid_question")
        if (
            not isinstance(question.subject, str)
            or not _SAFE_ID.fullmatch(question.subject)
            or not isinstance(question.predicate, str)
            or not _SAFE_NAME.fullmatch(question.predicate)
            or question.intent not in ("current", "original", "history")
        ):
            raise DecisionSafetyError("untrusted_question")
        group = self._groups.get((question.subject, question.predicate), [])
        if not group:
            return _abstain("insufficient_evidence")
        if len(group) > MAX_CHAIN:
            return _abstain("unbounded_lineage")

        roots = [fact for fact in group if fact.supersedes_id is None]
        if len(roots) != 1:
            return _abstain("conflicting_roots")
        root = roots[0]
        if root.version != 1 or root.revision_kind not in (
            "original_statement",
            "historical_state",
            "unrelated_current_fact",
        ):
            return _abstain("invalid_lineage_root")

        children: dict[str, list[Assertion]] = {}
        for fact in group:
            if fact is root:
                continue
            predecessor = self._by_id.get(fact.supersedes_id or "")
            if (
                predecessor is None
                or predecessor.subject != fact.subject
                or predecessor.predicate != fact.predicate
                or fact.version != predecessor.version + 1
                or _time(fact.mentioned_at) < _time(predecessor.mentioned_at)
                or fact.revision_kind not in ("correction", "historical_change")
            ):
                return _abstain("invalid_lineage")
            children.setdefault(predecessor.assertion_id, []).append(fact)

        ordered = [root]
        visited = {root.assertion_id}
        current = root
        while current.assertion_id in children:
            descendants = children[current.assertion_id]
            if len(descendants) != 1:
                return _abstain("conflicting_successors")
            current = descendants[0]
            if current.assertion_id in visited:
                return _abstain("lineage_cycle")
            ordered.append(current)
            visited.add(current.assertion_id)
        if len(visited) != len(group):
            return _abstain("disconnected_lineage")

        if question.intent == "current":
            selected = ordered[-1]
            return MemoryDecision(
                "answer", selected.value, (selected.assertion_id,), "grounded_current"
            )
        if question.intent == "original":
            return MemoryDecision(
                "answer", root.value, (root.assertion_id,), "grounded_original"
            )
        if len(ordered) == 1:
            return MemoryDecision(
                "answer", root.value, (root.assertion_id,), "grounded_single_state"
            )
        transitions = [f.revision_kind for f in ordered[1:]]
        if len(set(transitions)) != 1:
            # Mixed correction/history transitions need an explicit temporal
            # semantics policy; do not manufacture a single history summary.
            return _abstain("mixed_revision_semantics")
        separator = (
            "_corrected_to_" if transitions[0] == "correction" else "_then_"
        )
        return MemoryDecision(
            "answer",
            separator.join(f.value for f in ordered),
            tuple(f.assertion_id for f in ordered),
            "grounded_correction" if transitions[0] == "correction"
            else "grounded_historical_change",
        )


def compare_shadow(
    canonical: MemoryDecision, candidate: MemoryDecision
) -> dict[str, object]:
    """Observability only: NEVER chooses a new canonical answer or writes data."""
    if not isinstance(canonical, MemoryDecision) or not isinstance(
        candidate, MemoryDecision
    ):
        raise DecisionSafetyError("invalid_shadow_decision")
    return {
        "kind": "SYNTHETIC_SHADOW_COMPARISON_ONLY",
        "equal": (
            canonical.status == candidate.status
            and canonical.answer_code == candidate.answer_code
            and canonical.evidence_assertion_ids == candidate.evidence_assertion_ids
        ),
        "canonical_unmodified": True,
        "production_promotion_allowed": False,
        "memory_write_performed": False,
    }
