"""JARVIS-owned approximate progress and ETA for persistent WorkItems.

Estimates are derived from canonical WorkItem/WorkStep truth. They deliberately do not
ask the model provider to guess progress or completion time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median

from jarvis.work.models import WorkItem, WorkState, WorkStep, WorkStepState, WorkType
from jarvis.work.store import SQLiteWorkStore

_BASELINE_TOTAL_SECONDS = {
    WorkType.RESEARCH: 240.0,
    WorkType.DEVELOPMENT: 360.0,
}
_DEFAULT_BASELINE_SECONDS = 180.0
_MAX_HISTORY_ITEMS = 10


@dataclass(frozen=True, slots=True)
class WorkEstimate:
    progress_percent: int
    progress_is_approximate: bool
    progress_summary: str
    remaining_summary: str
    blocked_reason: str | None
    eta_low_seconds: int | None
    eta_high_seconds: int | None
    eta_confidence: str
    eta_reason: str
    estimate_updated_at: str


def _finished_successfully(step: WorkStep, kind: str) -> bool:
    return step.kind == kind and step.state is WorkStepState.COMPLETED


def _research_progress(
    work: WorkItem,
    steps: tuple[WorkStep, ...],
) -> tuple[int, str, str]:
    successful_research = any(
        _finished_successfully(step, "research_web")
        and bool(step.observation.get("ok"))
        for step in steps
    )
    current = next(
        (step for step in reversed(steps) if step.step_id == work.current_step_id),
        None,
    )

    if successful_research:
        return (
            70,
            "Current web evidence has been gathered; synthesis and final verification remain.",
            "Synthesize and verify the gathered evidence, then finalize the summary.",
        )
    if current is not None and current.kind == "research_web":
        return (
            35,
            "JARVIS is gathering current web evidence.",
            "Finish evidence gathering, synthesize the findings, verify them, and finalize.",
        )
    if any(step.kind == "provider_pressure" for step in steps):
        return (
            20,
            "The research is accepted but provider pressure is delaying evidence gathering.",
            "Gather current evidence, synthesize the findings, verify them, and finalize.",
        )
    if work.state is WorkState.QUEUED:
        return (
            5,
            "The research request is durably queued.",
            "Plan the research, gather current evidence, synthesize, verify, and finalize.",
        )
    return (
        15,
        "The research is active and preparing its evidence-gathering work.",
        "Gather current evidence, synthesize the findings, verify them, and finalize.",
    )


def _development_progress(
    work: WorkItem,
    steps: tuple[WorkStep, ...],
) -> tuple[int, str, str]:
    completed = [
        (index, step)
        for index, step in enumerate(steps)
        if step.state is WorkStepState.COMPLETED
    ]

    prepare_index = max(
        (index for index, step in completed if step.kind == "dev_prepare_workspace"),
        default=-1,
    )
    inspect_index = max(
        (
            index
            for index, step in completed
            if step.kind in {"dev_list_files", "dev_read_file", "dev_search"}
        ),
        default=-1,
    )
    write_index = max(
        (index for index, step in completed if step.kind == "dev_write_file"),
        default=-1,
    )
    test_index = max(
        (
            index
            for index, step in completed
            if step.kind == "dev_run_tests"
            and step.observation.get("passed") is True
            and index > write_index
        ),
        default=-1,
    )
    diff_index = max(
        (
            index
            for index, step in completed
            if step.kind == "dev_diff" and index > test_index
        ),
        default=-1,
    )
    commit_index = max(
        (
            index
            for index, step in completed
            if step.kind == "dev_commit"
            and step.observation.get("committed") is True
            and step.observation.get("clean") is True
            and index > diff_index
        ),
        default=-1,
    )

    if commit_index >= 0:
        return (
            95,
            "The isolated change is committed cleanly and is nearly ready for review.",
            "Finalize the WorkItem and prepare the owner-facing review result.",
        )
    if diff_index >= 0:
        return (
            85,
            "Passing sandbox tests and the final diff have been verified.",
            "Create the clean isolated review commit, then finalize the result.",
        )
    if test_index >= 0:
        return (
            70,
            "The latest edit has passed the required sandboxed tests.",
            "Inspect the final diff, create a clean isolated commit, and finalize.",
        )
    if write_index >= 0:
        return (
            50,
            "The source change is staged in the isolated worktree.",
            "Run sandboxed tests, inspect the final diff, commit cleanly, and finalize.",
        )
    if inspect_index >= 0:
        return (
            25,
            "The isolated repository context has been inspected.",
            "Implement the change, test it in Docker, inspect the diff, and commit it.",
        )
    if prepare_index >= 0:
        return (
            10,
            "The isolated Git worktree is prepared.",
            "Inspect the repository, implement the change, test, review the diff, and commit.",
        )
    if work.state is WorkState.QUEUED:
        return (
            5,
            "The development request is durably queued.",
            "Prepare an isolated worktree, inspect, implement, test, review, and commit.",
        )
    return (
        8,
        "The development task is active and preparing its isolated workspace.",
        "Prepare and inspect the worktree, implement, test, review, and commit.",
    )


def _generic_progress(
    work: WorkItem,
    steps: tuple[WorkStep, ...],
) -> tuple[int, str, str]:
    completed = sum(
        1
        for step in steps
        if step.state is WorkStepState.COMPLETED
        and step.kind not in {"provider_pressure", "owner_input"}
    )
    progress = min(90, 10 + completed * 15)
    if work.state is WorkState.QUEUED:
        progress = 5
    return (
        progress,
        "JARVIS is advancing the durable task through its recorded work steps.",
        "Continue the remaining recorded work steps and finalize the result.",
    )


def _history_seconds(store: SQLiteWorkStore, work: WorkItem) -> tuple[float, int]:
    samples: list[float] = []
    for item in store.list(limit=100):
        if item.work_id == work.work_id:
            continue
        if item.work_type is not work.work_type or item.state is not WorkState.COMPLETED:
            continue
        duration = (item.updated_at - item.created_at).total_seconds()
        if duration <= 0:
            continue
        samples.append(duration)
        if len(samples) >= _MAX_HISTORY_ITEMS:
            break
    if not samples:
        return 0.0, 0
    return float(median(samples)), len(samples)


def _current_provider_retry(steps: tuple[WorkStep, ...], work: WorkItem) -> float:
    if work.current_step_id is None:
        return 0.0
    step = next(
        (item for item in reversed(steps) if item.step_id == work.current_step_id),
        None,
    )
    if step is None or step.kind != "provider_pressure":
        return 0.0
    value = step.observation.get("retry_after_seconds")
    return float(value) if isinstance(value, (int, float)) and value > 0 else 0.0


def _round_seconds(value: float) -> int:
    if value <= 60:
        quantum = 5
    elif value <= 300:
        quantum = 15
    else:
        quantum = 30
    return max(quantum, int(round(value / quantum) * quantum))


def _eta(
    store: SQLiteWorkStore,
    work: WorkItem,
    steps: tuple[WorkStep, ...],
    *,
    progress: int,
    now: datetime,
) -> tuple[int | None, int | None, str, str]:
    if work.state is WorkState.COMPLETED:
        return 0, 0, "high", "The WorkItem is complete."
    if work.state in {WorkState.FAILED, WorkState.CANCELLED}:
        return None, None, "unavailable", "Terminal unsuccessful work has no completion ETA."
    if work.state is WorkState.PAUSED:
        return None, None, "unavailable", "The task is paused by the owner."
    if work.state is WorkState.WAITING_FOR_OWNER:
        return (
            None,
            None,
            "unavailable",
            "Completion time depends on the owner's next decision or input.",
        )
    if work.state is WorkState.WAITING_DEPENDENCY:
        return (
            None,
            None,
            "unavailable",
            "Completion time depends on an unfinished prerequisite task.",
        )

    baseline = _BASELINE_TOTAL_SECONDS.get(work.work_type, _DEFAULT_BASELINE_SECONDS)
    elapsed = max(1.0, (now - work.created_at).total_seconds())
    fraction = max(0.10, min(progress / 100.0, 0.95))
    projected_from_elapsed = min(baseline * 8.0, elapsed / fraction)

    history_total, history_count = _history_seconds(store, work)
    if history_count >= 3:
        projected_total = (history_total * 0.60) + (projected_from_elapsed * 0.40)
    elif history_count:
        projected_total = (history_total * 0.30) + (projected_from_elapsed * 0.70)
    else:
        projected_total = max(baseline, projected_from_elapsed)

    remaining = max(10.0, projected_total * max(0.0, 1.0 - progress / 100.0))
    retry_delay = _current_provider_retry(steps, work)
    remaining += retry_delay

    provider_blocked = retry_delay > 0 or (
        work.state is WorkState.WAITING_RESOURCE
        and bool(work.status_detail)
        and any(
            token in work.status_detail.casefold()
            for token in ("rate limit", "temporarily unavailable", "provider")
        )
    )

    if provider_blocked or progress < 25:
        confidence = "low"
        low_factor, high_factor = 0.65, 1.85
    elif history_count >= 3 and progress >= 70:
        confidence = "high"
        low_factor, high_factor = 0.85, 1.20
    else:
        confidence = "medium"
        low_factor, high_factor = 0.75, 1.45

    low = _round_seconds(remaining * low_factor)
    high = max(low, _round_seconds(remaining * high_factor))
    history_phrase = (
        f" and {history_count} similar completed task(s)" if history_count else ""
    )
    reason = (
        "Based on canonical milestone progress, elapsed time"
        f"{history_phrase}. "
        "Provider pressure is currently reducing ETA confidence."
        if provider_blocked
        else (
            "Based on canonical milestone progress, elapsed time"
            f"{history_phrase}."
        )
    )
    return low, high, confidence, reason


def estimate_work(
    store: SQLiteWorkStore,
    work: WorkItem,
    *,
    now: datetime | None = None,
) -> WorkEstimate:
    """Compute a provider-neutral approximate progress/ETA snapshot."""

    observed_now = now or datetime.now(UTC)
    steps = store.list_steps(work.work_id)

    if work.state is WorkState.COMPLETED:
        progress = 100
        progress_summary = "The WorkItem has completed successfully."
        remaining_summary = "No work remains."
        approximate = False
    elif work.state in {WorkState.FAILED, WorkState.CANCELLED}:
        progress, progress_summary, remaining_summary = _generic_progress(work, steps)
        progress_summary = (
            f"The WorkItem ended in state {work.state.value} after partial progress."
        )
        remaining_summary = "No completion ETA is available for this terminal state."
        approximate = True
    else:
        if work.work_type is WorkType.RESEARCH:
            progress, progress_summary, remaining_summary = _research_progress(
                work, steps
            )
        elif work.work_type is WorkType.DEVELOPMENT:
            progress, progress_summary, remaining_summary = _development_progress(
                work, steps
            )
        else:
            progress, progress_summary, remaining_summary = _generic_progress(
                work, steps
            )
        approximate = True

    blocked_reason = (
        work.status_detail
        if work.state
        in {
            WorkState.WAITING_RESOURCE,
            WorkState.WAITING_DEPENDENCY,
            WorkState.WAITING_UNTIL,
            WorkState.WAITING_FOR_OWNER,
            WorkState.PAUSED,
            WorkState.RETRYING,
        }
        else None
    )
    eta_low, eta_high, confidence, eta_reason = _eta(
        store,
        work,
        steps,
        progress=progress,
        now=observed_now,
    )
    return WorkEstimate(
        progress_percent=progress,
        progress_is_approximate=approximate,
        progress_summary=progress_summary,
        remaining_summary=remaining_summary,
        blocked_reason=blocked_reason,
        eta_low_seconds=eta_low,
        eta_high_seconds=eta_high,
        eta_confidence=confidence,
        eta_reason=eta_reason,
        estimate_updated_at=observed_now.isoformat(),
    )
