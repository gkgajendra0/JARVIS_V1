from jarvis.engineering_change import (
    ChangeState,
    ChangeStore,
    SystemOutcomeKind,
    classify_work_system_outcome,
)
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.work.models import WorkItem, WorkPriority, WorkState, WorkStep, WorkType
from jarvis.work.store import SQLiteWorkStore


class RecordingBackend:
    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        return work_id


def _work(*, state: WorkState, detail: str | None = None) -> WorkItem:
    return WorkItem(
        request="Specialist assignment",
        work_type=WorkType.RESEARCH,
        source_session_id="system-outcome",
        source_turn_id="case",
        state=state,
        status_detail=detail,
    )


def test_system_outcome_classifies_provider_pressure_as_retryable() -> None:
    work = _work(
        state=WorkState.FAILED,
        detail="ChatGPTPlanHTTPError: Our servers are currently overloaded.",
    )
    failed_step = (
        WorkStep(
            work_id=work.work_id,
            kind="brain_reasoning",
            summary="Reasoning provider call",
        )
        .start()
        .fail("Our servers are currently overloaded. Please try again later.")
    )

    outcome = classify_work_system_outcome(work, steps=(failed_step,))

    assert outcome.kind is SystemOutcomeKind.RETRYABLE
    assert outcome.terminal is False
    assert outcome.owner_action_required is False
    assert outcome.evidence_refs == (f"work_step:{failed_step.step_id}",)


def test_system_outcome_keeps_unknown_failure_terminal() -> None:
    work = _work(
        state=WorkState.FAILED,
        detail="Repository invariant irreparably violated.",
    )

    outcome = classify_work_system_outcome(work)

    assert outcome.kind is SystemOutcomeKind.TERMINAL
    assert outcome.terminal is True


def test_system_outcome_maps_typed_specialist_contracts() -> None:
    research_work = WorkItem(
        request="Develop capability",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="system-outcome",
        source_turn_id="development",
        state=WorkState.COMPLETED,
    )
    step = (
        WorkStep(
            work_id=research_work.work_id,
            kind="phase9_development_engine",
            summary="Run DevelopmentEngine",
        )
        .start()
        .complete(
            {
                "development_result": {
                    "disposition": "needs_research",
                    "summary": "Pairing behavior needs exact evidence.",
                    "reason": "VIDAA certificate behavior is not sufficiently evidenced.",
                }
            }
        )
    )

    outcome = classify_work_system_outcome(research_work, steps=(step,))

    assert outcome.kind is SystemOutcomeKind.NEEDS_RESEARCH
    assert outcome.terminal is False
    assert outcome.evidence_refs == (f"work_step:{step.step_id}",)


def test_completed_failed_external_acceptance_is_terminal() -> None:
    work = WorkItem(
        request="Validate acquired capability on the real target.",
        work_type=WorkType.EXTERNAL_ACCEPTANCE,
        source_session_id="phase9-external:change-demo",
        source_turn_id="activation-demo",
        state=WorkState.COMPLETED,
    )
    record = (
        WorkStep(
            work_id=work.work_id,
            kind="external_acceptance_record",
            summary="Record physical acceptance.",
        )
        .start()
        .complete({"acceptance_recorded": True, "verdict": "fail"})
    )

    outcome = classify_work_system_outcome(work, steps=(record,))

    assert outcome.kind is SystemOutcomeKind.TERMINAL
    assert outcome.terminal is True
    assert outcome.evidence_refs == (f"work_step:{record.step_id}",)


def test_system_outcome_owner_and_superseded_are_nonterminal() -> None:
    owner_wait = _work(
        state=WorkState.WAITING_FOR_OWNER,
        detail="Owner approval is required.",
    )
    owner = classify_work_system_outcome(owner_wait)
    superseded = classify_work_system_outcome(owner_wait, superseded=True)

    assert owner.kind is SystemOutcomeKind.NEEDS_OWNER
    assert owner.owner_action_required is True
    assert owner.terminal is False
    assert superseded.kind is SystemOutcomeKind.SUPERSEDED
    assert superseded.owner_action_required is False
    assert superseded.terminal is False


def test_recoverable_research_failure_does_not_fail_engineering_change(
    tmp_path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    coordinator = ChangeCoordinator(changes, RecordingBackend())
    change = coordinator.start("Research TV transport.", "session", "turn")
    stage = changes.list_stages(change.change_id)[0]
    item = work.require(stage.work_id)
    running = work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    step = WorkStep(
        work_id=running.work_id,
        kind="brain_reasoning",
        summary="Research reasoning",
    )
    work.add_step(step)
    failed_step = step.start().fail(
        "ChatGPTPlanHTTPError: Our servers are currently overloaded."
    )
    work.save_step(failed_step)
    work.save(
        running.transition(
            WorkState.FAILED,
            status_detail="Our servers are currently overloaded.",
            current_step_id=failed_step.step_id,
        ),
        expected_version=running.version,
    )

    reconciled = coordinator.reconcile_for_work(stage.work_id)

    assert reconciled is not None
    assert reconciled.state is ChangeState.RESEARCHING
    assert changes.require(change.change_id).state is ChangeState.RESEARCHING


def test_unknown_research_failure_still_fails_engineering_change(tmp_path) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(work)
    coordinator = ChangeCoordinator(changes, RecordingBackend())
    change = coordinator.start("Research TV transport.", "session", "turn")
    stage = changes.list_stages(change.change_id)[0]
    item = work.require(stage.work_id)
    running = work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    work.save(
        running.transition(
            WorkState.FAILED,
            status_detail="Unrecoverable specialist invariant violation.",
        ),
        expected_version=running.version,
    )

    reconciled = coordinator.reconcile_for_work(stage.work_id)

    assert reconciled is not None
    assert reconciled.state is ChangeState.FAILED
