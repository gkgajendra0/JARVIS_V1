from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from jarvis.work.estimates import estimate_work, owner_work_status_summary
from jarvis.work.models import WorkItem, WorkState, WorkStep, WorkType
from jarvis.work.store import SQLiteWorkStore


def _item(work_type: WorkType, *, request: str = "Do work") -> WorkItem:
    return WorkItem(
        request=request,
        work_type=work_type,
        source_session_id="session-estimate",
        source_turn_id=f"turn-{work_type.value}",
    )


def _complete_step(
    store: SQLiteWorkStore,
    item: WorkItem,
    kind: str,
    observation: dict | None = None,
) -> WorkStep:
    step = WorkStep(work_id=item.work_id, kind=kind, summary=kind)
    store.add_step(step)
    completed = step.start().complete(observation or {})
    store.save_step(completed)
    return completed


def test_research_estimate_exposes_provider_blocker_and_low_confidence(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    item = _item(WorkType.RESEARCH)
    store.create(item)
    running = item.transition(WorkState.RUNNING, status_detail="reasoning")
    store.save(running, expected_version=item.version)

    pressure = _complete_step(
        store,
        running,
        "provider_pressure",
        {
            "provider": "gemini",
            "status_code": 429,
            "reason": "rate limit",
            "attempt": 2,
            "retry_after_seconds": 10.0,
        },
    )
    latest = store.require(item.work_id)
    waiting = latest.transition(
        WorkState.WAITING_RESOURCE,
        status_detail="waiting for Gemini rate limit; retrying in 10 seconds",
        current_step_id=pressure.step_id,
    )
    store.save(waiting, expected_version=latest.version)

    estimate = estimate_work(
        store,
        waiting,
        now=waiting.created_at + timedelta(seconds=30),
    )

    assert estimate.progress_percent == 20
    assert estimate.progress_is_approximate is True
    assert estimate.blocked_reason == (
        "waiting for Gemini rate limit; retrying in 10 seconds"
    )
    assert estimate.eta_low_seconds is not None
    assert estimate.eta_high_seconds is not None
    assert estimate.eta_high_seconds >= estimate.eta_low_seconds
    assert estimate.eta_confidence == "low"
    assert "Provider pressure" in estimate.eta_reason


def test_research_progress_advances_after_successful_web_evidence(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    item = _item(WorkType.RESEARCH)
    store.create(item)
    running = item.transition(WorkState.RUNNING)
    store.save(running, expected_version=item.version)
    _complete_step(store, running, "research_web", {"ok": True})

    estimate = estimate_work(store, store.require(item.work_id))

    assert estimate.progress_percent == 70
    assert "synthesis" in estimate.progress_summary
    assert "finalize" in estimate.remaining_summary


def test_development_progress_follows_verified_milestones(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    item = _item(WorkType.DEVELOPMENT)
    store.create(item)
    running = item.transition(WorkState.RUNNING)
    store.save(running, expected_version=item.version)

    _complete_step(store, running, "dev_prepare_workspace")
    assert estimate_work(store, store.require(item.work_id)).progress_percent == 10

    _complete_step(store, running, "dev_read_file")
    assert estimate_work(store, store.require(item.work_id)).progress_percent == 25

    _complete_step(store, running, "dev_write_file", {"path": "README.md"})
    assert estimate_work(store, store.require(item.work_id)).progress_percent == 50

    _complete_step(
        store,
        running,
        "dev_run_tests",
        {"passed": True, "sandbox": "docker"},
    )
    assert estimate_work(store, store.require(item.work_id)).progress_percent == 70

    _complete_step(store, running, "dev_diff", {"diff": "changed"})
    assert estimate_work(store, store.require(item.work_id)).progress_percent == 85

    _complete_step(
        store,
        running,
        "dev_commit",
        {"committed": True, "clean": True, "commit": "abc"},
    )
    estimate = estimate_work(store, store.require(item.work_id))
    assert estimate.progress_percent == 95
    assert estimate.eta_confidence in {"medium", "high"}


def test_completed_work_is_exactly_100_percent_with_zero_eta(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    item = _item(WorkType.RESEARCH)
    store.create(item)
    running = item.transition(WorkState.RUNNING)
    store.save(running, expected_version=item.version)
    completed = running.transition(
        WorkState.COMPLETED,
        status_detail="Research complete",
        result={"summary": "done"},
    )
    store.save(completed, expected_version=running.version)

    estimate = estimate_work(
        store,
        completed,
        now=datetime.now(UTC),
    )

    assert estimate.progress_percent == 100
    assert estimate.progress_is_approximate is False
    assert estimate.remaining_summary == "No work remains."
    assert estimate.eta_low_seconds == 0
    assert estimate.eta_high_seconds == 0
    assert estimate.eta_confidence == "high"


def test_paused_work_has_no_eta(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    item = _item(WorkType.DEVELOPMENT)
    store.create(item)
    paused = item.transition(WorkState.PAUSED, status_detail="paused by owner")
    store.save(paused, expected_version=item.version)

    estimate = estimate_work(store, paused)

    assert estimate.blocked_reason == "paused by owner"
    assert estimate.eta_low_seconds is None
    assert estimate.eta_high_seconds is None
    assert estimate.eta_confidence == "unavailable"


def test_owner_status_summary_preserves_specific_blocker_remaining_eta_and_promise(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    item = _item(WorkType.RESEARCH)
    store.create(item)
    running = item.transition(WorkState.RUNNING, status_detail="reasoning")
    store.save(running, expected_version=item.version)
    pressure = _complete_step(
        store,
        running,
        "provider_pressure",
        {
            "provider": "gemini",
            "status_code": 429,
            "reason": "rate limit",
            "attempt": 2,
            "retry_after_seconds": 10.0,
        },
    )
    latest = store.require(item.work_id)
    waiting = latest.transition(
        WorkState.WAITING_RESOURCE,
        status_detail="waiting for Gemini rate limit; retrying in 10 seconds",
        current_step_id=pressure.step_id,
    )
    store.save(waiting, expected_version=latest.version)
    estimate = estimate_work(
        store,
        waiting,
        now=waiting.created_at + timedelta(seconds=30),
    )

    summary = owner_work_status_summary(
        waiting,
        estimate,
        completion_notification_expected=True,
    )

    assert "approximately 20% complete" in summary
    assert "waiting for Gemini rate limit; retrying in 10 seconds" in summary
    assert "Remaining work:" in summary
    assert "with low confidence" in summary
    assert "I will let you know when it is complete." in summary
