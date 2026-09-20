"""JARVIS-owned approximate progress and ETA for persistent WorkItems.

Estimates are derived from canonical WorkItem/WorkStep truth. They deliberately do not
ask the model provider to guess progress or completion time, and they expose semantic
facts rather than pre-written owner-facing sentences.
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
    milestone: str
    completed_work: tuple[str, ...]
    remaining_work: tuple[str, ...]
    blocked_reason: str | None
    eta_low_seconds: int | None
    eta_high_seconds: int | None
    eta_confidence: str
    eta_basis: tuple[str, ...]
    estimate_updated_at: str


def _finished_successfully(step: WorkStep, kind: str) -> bool:
    return step.kind == kind and step.state is WorkStepState.COMPLETED


def _research_progress(
    work: WorkItem,
    steps: tuple[WorkStep, ...],
) -> tuple[int, str, tuple[str, ...], tuple[str, ...]]:
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
            "evidence_gathered",
            ("evidence_gathering",),
            ("synthesis", "verification", "finalization"),
        )
    if current is not None and current.kind == "research_web":
        return (
            35,
            "gathering_evidence",
            ("research_planning",),
            ("evidence_gathering", "synthesis", "verification", "finalization"),
        )
    if any(step.kind == "provider_pressure" for step in steps):
        return (
            20,
            "provider_pressure_before_evidence",
            ("work_accepted",),
            ("evidence_gathering", "synthesis", "verification", "finalization"),
        )
    if work.state is WorkState.QUEUED:
        return (
            5,
            "queued",
            (),
            (
                "research_planning",
                "evidence_gathering",
                "synthesis",
                "verification",
                "finalization",
            ),
        )
    return (
        15,
        "preparing_evidence",
        ("work_accepted",),
        ("evidence_gathering", "synthesis", "verification", "finalization"),
    )


def _development_progress(
    work: WorkItem,
    steps: tuple[WorkStep, ...],
) -> tuple[int, str, tuple[str, ...], tuple[str, ...]]:
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
            "isolated_commit_ready",
            (
                "workspace_preparation",
                "repository_inspection",
                "implementation",
                "sandbox_tests",
                "diff_review",
                "isolated_commit",
            ),
            ("finalization",),
        )
    if diff_index >= 0:
        return (
            85,
            "diff_verified",
            (
                "workspace_preparation",
                "repository_inspection",
                "implementation",
                "sandbox_tests",
                "diff_review",
            ),
            ("isolated_commit", "finalization"),
        )
    if test_index >= 0:
        return (
            70,
            "tests_passed",
            (
                "workspace_preparation",
                "repository_inspection",
                "implementation",
                "sandbox_tests",
            ),
            ("diff_review", "isolated_commit", "finalization"),
        )
    if write_index >= 0:
        return (
            50,
            "implementation_written",
            ("workspace_preparation", "repository_inspection", "implementation"),
            ("sandbox_tests", "diff_review", "isolated_commit", "finalization"),
        )
    if inspect_index >= 0:
        return (
            25,
            "repository_inspected",
            ("workspace_preparation", "repository_inspection"),
            (
                "implementation",
                "sandbox_tests",
                "diff_review",
                "isolated_commit",
                "finalization",
            ),
        )
    if prepare_index >= 0:
        return (
            10,
            "workspace_prepared",
            ("workspace_preparation",),
            (
                "repository_inspection",
                "implementation",
                "sandbox_tests",
                "diff_review",
                "isolated_commit",
                "finalization",
            ),
        )
    if work.state is WorkState.QUEUED:
        return (
            5,
            "queued",
            (),
            (
                "workspace_preparation",
                "repository_inspection",
                "implementation",
                "sandbox_tests",
                "diff_review",
                "isolated_commit",
                "finalization",
            ),
        )
    return (
        8,
        "preparing_workspace",
        ("work_accepted",),
        (
            "workspace_preparation",
            "repository_inspection",
            "implementation",
            "sandbox_tests",
            "diff_review",
            "isolated_commit",
            "finalization",
        ),
    )


def _generic_progress(
    work: WorkItem,
    steps: tuple[WorkStep, ...],
) -> tuple[int, str, tuple[str, ...], tuple[str, ...]]:
    completed = sum(
        1
        for step in steps
        if step.state is WorkStepState.COMPLETED
        and step.kind not in {"provider_pressure", "owner_input"}
    )
    progress = min(90, 10 + completed * 15)
    if work.state is WorkState.QUEUED:
        progress = 5
    completed_work = ("recorded_steps",) if completed else ()
    return (
        progress,
        "queued" if work.state is WorkState.QUEUED else "advancing_recorded_steps",
        completed_work,
        ("remaining_recorded_steps", "finalization"),
    )


def _history_seconds(store: SQLiteWorkStore, work: WorkItem) -> tuple[float, int]:
    samples: list[float] = []
    for item in store.list(limit=100):
        if item.work_id == work.work_id:
            continue
        if (
            item.work_type is not work.work_type
            or item.state is not WorkState.COMPLETED
        ):
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
) -> tuple[int | None, int | None, str, tuple[str, ...]]:
    if work.state is WorkState.COMPLETED:
        return 0, 0, "high", ("terminal_completed",)
    if work.state in {WorkState.FAILED, WorkState.CANCELLED}:
        return None, None, "unavailable", ("terminal_unsuccessful",)
    if work.state is WorkState.PAUSED:
        return None, None, "unavailable", ("owner_paused",)
    if work.state is WorkState.WAITING_FOR_OWNER:
        return None, None, "unavailable", ("owner_input_required",)
    if work.state is WorkState.WAITING_DEPENDENCY:
        return None, None, "unavailable", ("dependency_incomplete",)

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
    basis = ["milestone_progress", "elapsed_time"]
    if history_count:
        basis.append(f"history_samples:{history_count}")
    if provider_blocked:
        basis.append("provider_pressure")
    return low, high, confidence, tuple(basis)


def estimate_work(
    store: SQLiteWorkStore,
    work: WorkItem,
    *,
    now: datetime | None = None,
) -> WorkEstimate:
    """Compute a provider-neutral structured progress/ETA snapshot."""

    observed_now = now or datetime.now(UTC)
    steps = store.list_steps(work.work_id)

    if work.state is WorkState.COMPLETED:
        progress = 100
        milestone = "completed"
        completed_work = ("all_work",)
        remaining_work: tuple[str, ...] = ()
        approximate = False
    elif work.state in {WorkState.FAILED, WorkState.CANCELLED}:
        progress, _, completed_work, _ = _generic_progress(work, steps)
        milestone = work.state.value
        remaining_work = ()
        approximate = True
    else:
        if work.work_type is WorkType.RESEARCH:
            progress, milestone, completed_work, remaining_work = _research_progress(
                work, steps
            )
        elif work.work_type is WorkType.DEVELOPMENT:
            progress, milestone, completed_work, remaining_work = _development_progress(
                work, steps
            )
        else:
            progress, milestone, completed_work, remaining_work = _generic_progress(
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
    eta_low, eta_high, confidence, eta_basis = _eta(
        store,
        work,
        steps,
        progress=progress,
        now=observed_now,
    )
    return WorkEstimate(
        progress_percent=progress,
        progress_is_approximate=approximate,
        milestone=milestone,
        completed_work=completed_work,
        remaining_work=remaining_work,
        blocked_reason=blocked_reason,
        eta_low_seconds=eta_low,
        eta_high_seconds=eta_high,
        eta_confidence=confidence,
        eta_basis=eta_basis,
        estimate_updated_at=observed_now.isoformat(),
    )
