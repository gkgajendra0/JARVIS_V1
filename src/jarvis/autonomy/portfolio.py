"""Auditable deterministic autonomy portfolio prioritization for Phase 10A."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.autonomy.models import ActionCandidateV1, ObjectiveV1
from jarvis.engineering_knowledge.canonical import JSONValue
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.work.models import WorkPriority

_FACTOR_NAMES = (
    "owner_priority",
    "obligation_criticality",
    "deadline_urgency",
    "impact_scope",
    "dependency_unblocking",
    "starvation_age",
    "resource_feasibility",
)


def _bucket(value: object, field: str, *, maximum: int = 3) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer bucket")
    if value < 0 or value > maximum:
        raise ValueError(f"{field} must be between 0 and {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class PriorityFactorsV1:
    owner_priority: WorkPriority
    obligation_criticality: int
    deadline_urgency: int
    impact_scope: int
    dependency_unblocking: int
    starvation_age: int
    resource_feasibility: int
    provenance_json: dict[str, JSONValue]

    def __post_init__(self) -> None:
        if not isinstance(self.owner_priority, WorkPriority):
            raise TypeError("owner_priority must be a WorkPriority")
        for field_name in (
            "obligation_criticality",
            "deadline_urgency",
            "impact_scope",
            "dependency_unblocking",
            "starvation_age",
        ):
            object.__setattr__(
                self,
                field_name,
                _bucket(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "resource_feasibility",
            _bucket(
                self.resource_feasibility,
                "resource_feasibility",
                maximum=2,
            ),
        )
        if not isinstance(self.provenance_json, dict):
            raise TypeError("provenance_json must be a JSON object")
        canonical_digest(self.provenance_json)
        missing = set(_FACTOR_NAMES) - set(self.provenance_json)
        if missing:
            raise ValueError(
                f"priority factor provenance missing keys: {sorted(missing)}"
            )

    @property
    def ordering_vector(self) -> tuple[int, ...]:
        return (
            int(self.owner_priority),
            self.obligation_criticality,
            self.deadline_urgency,
            self.impact_scope,
            self.dependency_unblocking,
            self.starvation_age,
            self.resource_feasibility,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "owner_priority": int(self.owner_priority),
            "obligation_criticality": self.obligation_criticality,
            "deadline_urgency": self.deadline_urgency,
            "impact_scope": self.impact_scope,
            "dependency_unblocking": self.dependency_unblocking,
            "starvation_age": self.starvation_age,
            "resource_feasibility": self.resource_feasibility,
            "provenance_json": dict(self.provenance_json),
        }


@dataclass(frozen=True, slots=True)
class PortfolioInputV1:
    candidate: ActionCandidateV1
    objective: ObjectiveV1
    factors: PriorityFactorsV1

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, ActionCandidateV1):
            raise TypeError("candidate must be an ActionCandidateV1")
        if not isinstance(self.objective, ObjectiveV1):
            raise TypeError("objective must be an ObjectiveV1")
        if not isinstance(self.factors, PriorityFactorsV1):
            raise TypeError("factors must be PriorityFactorsV1")
        if self.factors.owner_priority is not self.objective.priority:
            raise ValueError(
                "owner priority factor must exactly preserve Objective priority"
            )


@dataclass(frozen=True, slots=True)
class PrioritizedCandidateV1:
    candidate_id: str
    objective_id: str
    work_priority: WorkPriority
    ordering_vector: tuple[int, ...]
    priority_factor_payload: dict[str, Any]
    rank: int

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty")
        if not self.objective_id.strip():
            raise ValueError("objective_id must not be empty")
        if not isinstance(self.work_priority, WorkPriority):
            raise TypeError("work_priority must be a WorkPriority")
        if len(self.ordering_vector) != len(_FACTOR_NAMES):
            raise ValueError("ordering_vector has unexpected shape")
        if self.rank <= 0:
            raise ValueError("rank must be positive")
        canonical_digest(self.priority_factor_payload)


class PortfolioPrioritizer:
    """Order candidates by the approved explicit lexicographic factor vector."""

    def prioritize(
        self,
        items: tuple[PortfolioInputV1, ...],
    ) -> tuple[PrioritizedCandidateV1, ...]:
        if any(not isinstance(item, PortfolioInputV1) for item in items):
            raise TypeError("items must contain PortfolioInputV1 values")
        candidate_ids = tuple(item.candidate.candidate_id for item in items)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("portfolio candidate IDs must be unique")

        ordered = sorted(
            items,
            key=lambda item: (
                -int(item.factors.owner_priority),
                -item.factors.obligation_criticality,
                -item.factors.deadline_urgency,
                -item.factors.impact_scope,
                -item.factors.dependency_unblocking,
                -item.factors.starvation_age,
                -item.factors.resource_feasibility,
                item.candidate.candidate_id,
            ),
        )
        return tuple(
            PrioritizedCandidateV1(
                candidate_id=item.candidate.candidate_id,
                objective_id=item.objective.objective_id,
                work_priority=item.objective.priority,
                ordering_vector=item.factors.ordering_vector,
                priority_factor_payload=item.factors.to_payload(),
                rank=index,
            )
            for index, item in enumerate(ordered, start=1)
        )
