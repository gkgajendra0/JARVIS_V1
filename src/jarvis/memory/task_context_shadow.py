"""Task-conditioned memory compilation prototype for *shadow evaluation only*.

Inspired by MemCompiler's brief-state selection, not a reproduction of its
learned or latent-memory model. Returns opaque IDs, never a memory value or a
provider context packet. Not imported by voice/runtime and cannot inject.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .decision_shadow import (
    ContextShadowDisposition,
    ContextShadowEvidence,
    assess_context_shadow,
)


class TaskNeedKind(StrEnum):
    """A trusted task classifier must supply this independently of memories."""

    PRESENTATION_STYLE = "presentation_style"
    EXACT_OWNER_FACT = "exact_owner_fact"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True, slots=True)
class ShadowTaskNeed:
    scope: str
    kind: TaskNeedKind
    grounded_in_current_user_turn: bool

    def __post_init__(self) -> None:
        if not isinstance(self.scope, str) or not self.scope.strip():
            raise ValueError("task scope must not be empty")
        if not isinstance(self.kind, TaskNeedKind):
            raise TypeError("task kind must be TaskNeedKind")


@dataclass(frozen=True, slots=True)
class ShadowMemoryCandidate:
    """Current metadata is caller supplied and cannot authorize release."""

    opaque_assertion_id: str
    evidence: ContextShadowEvidence
    need_kind: TaskNeedKind
    provenance_verified: bool
    fact_support_verified: bool
    utility_rank: int

    def __post_init__(self) -> None:
        if not isinstance(self.opaque_assertion_id, str) or not (
            self.opaque_assertion_id.strip()
        ):
            raise ValueError("opaque assertion ID must not be empty")
        if not isinstance(self.need_kind, TaskNeedKind):
            raise TypeError("memory need kind must be TaskNeedKind")
        if isinstance(self.utility_rank, bool) or not isinstance(
            self.utility_rank, int
        ):
            raise TypeError("utility rank must be an integer")


@dataclass(frozen=True, slots=True)
class ShadowCompiledPlan:
    """Simulation only; no data is exported to the assistant or memory store."""

    candidate_ids: tuple[str, ...]
    examined_count: int
    rejected_count: int
    mode: str = "shadow_only_not_authorized"


def compile_shadow_plan(
    *,
    task: ShadowTaskNeed,
    candidates: tuple[ShadowMemoryCandidate, ...],
    max_selected: int = 2,
) -> ShadowCompiledPlan:
    """Construct minimal candidate ID plan after independent eligibility gates.

    This is NOT an influence/answerability verifier. It assumes independently
    supplied provenance and support checks and must NOT be used in production
    until those are implemented and blindly validated.
    """

    if not isinstance(task, ShadowTaskNeed):
        raise TypeError("task must be a ShadowTaskNeed")
    if isinstance(max_selected, bool) or not isinstance(max_selected, int):
        raise TypeError("max_selected must be an integer")
    if not 1 <= max_selected <= 3:
        raise ValueError("max_selected must be between 1 and 3")
    if not all(isinstance(item, ShadowMemoryCandidate) for item in candidates):
        raise TypeError("all candidates must be ShadowMemoryCandidate")
    ids = [x.opaque_assertion_id for x in candidates]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate assertion identity")

    rejected = 0
    if not task.grounded_in_current_user_turn or task.kind is (
        TaskNeedKind.UNCLASSIFIED
    ):
        return ShadowCompiledPlan((), len(candidates), len(candidates))

    eligible: list[ShadowMemoryCandidate] = []
    for candidate in candidates:
        evidence = candidate.evidence
        if (
            candidate.need_kind is not task.kind
            or not candidate.provenance_verified
            or not candidate.fact_support_verified
            or evidence.current_task_scope is None
            or evidence.current_task_scope.strip().casefold()
            != task.scope.strip().casefold()
        ):
            rejected += 1
            continue
        if (
            assess_context_shadow(evidence).disposition
            is not ContextShadowDisposition.MEASURE_ONLY
        ):
            rejected += 1
            continue
        eligible.append(candidate)
    selected = sorted(
        eligible,
        key=lambda x: (x.utility_rank, x.opaque_assertion_id),
    )[:max_selected]
    return ShadowCompiledPlan(
        tuple(x.opaque_assertion_id for x in selected),
        len(candidates),
        len(candidates) - len(selected),
    )
