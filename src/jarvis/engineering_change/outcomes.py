"""System-level meaning for child Work outcomes.

Work state is execution truth, but a failed specialist WorkItem is not automatically a
terminal system decision. This module deterministically classifies canonical Work/step
evidence for EngineeringChange and, later, the Global Supervisor.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.work.models import WorkItem, WorkState, WorkStep


class SystemOutcomeKind(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    TEMPORARY_RESOURCE = "temporary_resource"
    RETRYABLE = "retryable"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    NEEDS_RESEARCH = "needs_research"
    NEEDS_ARCHITECTURE_REVISION = "needs_architecture_revision"
    NEEDS_DEPENDENCY = "needs_dependency"
    NEEDS_OWNER = "needs_owner"
    SUPERSEDED = "superseded"
    TERMINAL = "terminal"


_NONTERMINAL_KINDS = frozenset(
    {
        SystemOutcomeKind.IN_PROGRESS,
        SystemOutcomeKind.COMPLETED,
        SystemOutcomeKind.TEMPORARY_RESOURCE,
        SystemOutcomeKind.RETRYABLE,
        SystemOutcomeKind.EVIDENCE_INSUFFICIENT,
        SystemOutcomeKind.NEEDS_RESEARCH,
        SystemOutcomeKind.NEEDS_ARCHITECTURE_REVISION,
        SystemOutcomeKind.NEEDS_DEPENDENCY,
        SystemOutcomeKind.NEEDS_OWNER,
        SystemOutcomeKind.SUPERSEDED,
    }
)


@dataclass(frozen=True, slots=True)
class SystemOutcomeV1:
    kind: SystemOutcomeKind
    source_work_id: str
    source_work_state: str
    reason: str | None
    owner_action_required: bool
    retry_after_seconds: float | None
    evidence_refs: tuple[str, ...]
    digest: str

    @property
    def terminal(self) -> bool:
        return self.kind not in _NONTERMINAL_KINDS

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SystemOutcomeKind):
            raise TypeError("kind must be SystemOutcomeKind")
        if not self.source_work_id.strip():
            raise ValueError("source_work_id must not be empty")
        if not self.source_work_state.strip():
            raise ValueError("source_work_state must not be empty")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("system outcome digest mismatch")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "source_work_id": self.source_work_id,
            "source_work_state": self.source_work_state,
            "reason": self.reason,
            "owner_action_required": self.owner_action_required,
            "retry_after_seconds": self.retry_after_seconds,
            "evidence_refs": list(self.evidence_refs),
        }


def _normalized(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _development_result(
    work: WorkItem,
    steps: tuple[WorkStep, ...],
) -> tuple[dict[str, object] | None, tuple[str, ...]]:
    raw = work.result.get("development_engine")
    if isinstance(raw, dict):
        return dict(raw), (f"work:{work.work_id}:development_engine",)

    for step in reversed(steps):
        candidate = step.observation.get("development_result")
        if isinstance(candidate, dict):
            return dict(candidate), (f"work_step:{step.step_id}",)
        wrapper = step.observation.get("development_engine")
        if isinstance(wrapper, dict):
            return dict(wrapper), (f"work_step:{step.step_id}",)
    return None, ()


def _failure_text(work: WorkItem, steps: tuple[WorkStep, ...]) -> str:
    values = [work.status_detail or ""]
    for step in steps:
        values.extend(
            (
                step.error or "",
                step.summary,
                step.observation.get("reason", ""),
                step.observation.get("error", ""),
            )
        )
        raw_result = step.observation.get("development_result")
        if isinstance(raw_result, dict):
            values.extend(
                (
                    raw_result.get("reason", ""),
                    raw_result.get("summary", ""),
                    raw_result.get("blocker_code", ""),
                )
            )
    return " ".join(_normalized(item) for item in values).casefold()


def _create(
    work: WorkItem,
    *,
    kind: SystemOutcomeKind,
    reason: str | None = None,
    owner_action_required: bool = False,
    retry_after_seconds: float | None = None,
    evidence_refs: tuple[str, ...] = (),
) -> SystemOutcomeV1:
    payload = {
        "kind": kind.value,
        "source_work_id": work.work_id,
        "source_work_state": work.state.value,
        "reason": None if reason is None else _normalized(reason) or None,
        "owner_action_required": bool(owner_action_required),
        "retry_after_seconds": retry_after_seconds,
        "evidence_refs": list(evidence_refs),
    }
    digest = canonical_digest(payload)
    return SystemOutcomeV1(
        kind=kind,
        source_work_id=work.work_id,
        source_work_state=work.state.value,
        reason=payload["reason"] if isinstance(payload["reason"], str) else None,
        owner_action_required=bool(payload["owner_action_required"]),
        retry_after_seconds=retry_after_seconds,
        evidence_refs=evidence_refs,
        digest=digest,
    )


def classify_work_system_outcome(
    work: WorkItem,
    *,
    steps: tuple[WorkStep, ...] = (),
    superseded: bool = False,
) -> SystemOutcomeV1:
    """Classify one canonical child outcome without changing lifecycle state."""

    if not isinstance(work, WorkItem):
        raise TypeError("work must be WorkItem")
    if any(not isinstance(step, WorkStep) for step in steps):
        raise TypeError("steps must contain WorkStep values")

    if superseded:
        return _create(
            work,
            kind=SystemOutcomeKind.SUPERSEDED,
            reason="A newer authoritative attempt replaced this work.",
        )

    if work.state in {WorkState.QUEUED, WorkState.RUNNING, WorkState.PAUSED}:
        return _create(work, kind=SystemOutcomeKind.IN_PROGRESS)

    if work.state in {WorkState.WAITING_RESOURCE, WorkState.WAITING_UNTIL}:
        return _create(
            work,
            kind=SystemOutcomeKind.TEMPORARY_RESOURCE,
            reason=work.status_detail,
        )

    if work.state is WorkState.RETRYING:
        return _create(
            work,
            kind=SystemOutcomeKind.RETRYABLE,
            reason=work.status_detail,
        )

    if work.state is WorkState.WAITING_DEPENDENCY:
        return _create(
            work,
            kind=SystemOutcomeKind.NEEDS_DEPENDENCY,
            reason=work.status_detail,
        )

    if work.state is WorkState.WAITING_FOR_OWNER:
        return _create(
            work,
            kind=SystemOutcomeKind.NEEDS_OWNER,
            reason=work.status_detail,
            owner_action_required=True,
        )

    if work.state is WorkState.CANCELLED:
        return _create(
            work,
            kind=SystemOutcomeKind.TERMINAL,
            reason=work.status_detail or "Work was cancelled.",
        )

    development, development_evidence = _development_result(work, steps)
    if development is not None:
        disposition = _normalized(development.get("disposition")).casefold()
        reason = _normalized(
            development.get("reason") or development.get("summary") or work.status_detail
        )
        blocker = _normalized(development.get("blocker_code")).casefold()
        retry_after_raw = development.get("retry_after_seconds")
        retry_after = (
            float(retry_after_raw)
            if isinstance(retry_after_raw, (int, float))
            and not isinstance(retry_after_raw, bool)
            and float(retry_after_raw) > 0
            else None
        )
        mapped = {
            "completed": SystemOutcomeKind.COMPLETED,
            "blocked_resource": SystemOutcomeKind.TEMPORARY_RESOURCE,
            "needs_research": SystemOutcomeKind.NEEDS_RESEARCH,
            "needs_architecture_revision": SystemOutcomeKind.NEEDS_ARCHITECTURE_REVISION,
            "needs_dependency": SystemOutcomeKind.NEEDS_DEPENDENCY,
        }.get(disposition)
        if mapped is not None:
            return _create(
                work,
                kind=mapped,
                reason=reason or None,
                retry_after_seconds=retry_after,
                evidence_refs=development_evidence,
            )
        if disposition == "failed":
            failure = f"{reason} {blocker}".casefold()
            if any(
                marker in failure
                for marker in (
                    "response_contract_invalid",
                    "provider_overload",
                    "resource_exhausted",
                    "temporarily unavailable",
                    "servers are currently overloaded",
                    "rate limit",
                    "too many requests",
                )
            ):
                return _create(
                    work,
                    kind=SystemOutcomeKind.RETRYABLE,
                    reason=reason or blocker or work.status_detail,
                    evidence_refs=development_evidence,
                )
            return _create(
                work,
                kind=SystemOutcomeKind.TERMINAL,
                reason=reason or blocker or work.status_detail,
                evidence_refs=development_evidence,
            )

    if work.state is WorkState.COMPLETED:
        return _create(work, kind=SystemOutcomeKind.COMPLETED)

    failure_text = _failure_text(work, steps)
    failed_step_refs = tuple(
        f"work_step:{step.step_id}"
        for step in steps
        if step.state.value in {"failed", "interrupted"}
    )

    if any(
        marker in failure_text
        for marker in (
            "servers are currently overloaded",
            "servers overloaded",
            "resource_exhausted",
            "temporarily unavailable",
            "too many requests",
            "rate limit",
            "subscription sharing usage limit",
        )
    ):
        return _create(
            work,
            kind=SystemOutcomeKind.RETRYABLE,
            reason=work.status_detail or "Temporary provider pressure.",
            evidence_refs=failed_step_refs,
        )

    if any(
        marker in failure_text
        for marker in (
            "insufficient evidence",
            "evidence insufficient",
            "missing evidence",
            "evidence is missing",
        )
    ):
        return _create(
            work,
            kind=SystemOutcomeKind.EVIDENCE_INSUFFICIENT,
            reason=work.status_detail,
            evidence_refs=failed_step_refs,
        )

    return _create(
        work,
        kind=SystemOutcomeKind.TERMINAL,
        reason=work.status_detail,
        evidence_refs=failed_step_refs,
    )
