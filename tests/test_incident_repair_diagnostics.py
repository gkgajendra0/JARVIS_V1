from __future__ import annotations

import asyncio

import pytest

from jarvis.engineering_change import ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.incident_repair import UNKNOWN_INCIDENT_REPAIR_PROCESS
from jarvis.incident_repair.diagnostics import (
    DiagnosticContextResolver,
    DiagnosticFinalizeExecutor,
    DiagnosticGetIncidentExecutor,
    DiagnosticProtocolError,
    DiagnosticRecordHypothesisExecutor,
    DiagnosticRetrieveKnowledgeExecutor,
    suspicious_location_scores,
)
from jarvis.model_routing.strategy import derive_work_step_signals
from jarvis.work.engine import WorkEngine
from jarvis.work.models import WorkItem, WorkStep, WorkType
from jarvis.work.store import SQLiteWorkStore


REVISION = "a" * 40


class Backend:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, work_id, *, priority):
        del priority
        self.submitted.append(work_id)
        return work_id


def _fixture(tmp_path):
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    changes = ChangeStore(
        work_store,
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    change = changes.create(
        request=f"Investigate incident incident-1 at exact source revision {REVISION}",
        process_key="unknown_incident_repair",
        process_version=1,
        source_session_id="incident:incident-1",
        source_turn_id=f"revision:{REVISION}",
    )
    changes.add_artifact(
        change.change_id,
        kind="incident_repair_trigger",
        payload={
            "trigger_id": "trigger-1",
            "incident_id": "incident-1",
            "source_revision": REVISION,
            "component_ids": ["runtime.voice"],
            "evidence_ids": ["e1"],
            "reason_code": "unknown_failure",
            "created_at_epoch": 100.0,
            "digest": "b" * 64,
        },
    )
    changes.add_artifact(
        change.change_id,
        kind="incident_evidence",
        payload={
            "package_id": "incident_evidence_test",
            "incident_id": "incident-1",
            "source_revision": REVISION,
            "trigger_digest": "b" * 64,
            "title": "voice failure",
            "symptom": "runtime crash",
            "severity": "error",
            "status": "investigating",
            "affected_components": ["runtime.voice"],
            "evidence": [
                {
                    "evidence_id": "e1",
                    "kind": "crash_fingerprint",
                    "reference": "crash:1",
                    "summary": "exit code 1",
                    "occurred_at_epoch": 100.0,
                    "component_id": "runtime.voice",
                }
            ],
            "excluded_evidence": [],
            "repair_attempts": [],
            "knowledge_revision_ids": ["knowledge-r1"],
            "package_reason_codes": [],
            "created_at_epoch": 100.0,
            "digest": "c" * 64,
        },
    )
    backend = Backend()
    coordinator = ChangeCoordinator(changes, backend)
    coordinator.reconcile(change.change_id)
    stage = changes.list_stages(change.change_id)[0]
    return work_store, changes, stage.work_id


def _persist_completed(
    store: SQLiteWorkStore,
    *,
    work_id: str,
    kind: str,
    observation: dict,
) -> WorkStep:
    step = WorkStep(
        work_id=work_id,
        kind=kind,
        summary=kind,
        input_data={},
    )
    store.add_step(step)
    completed = step.start().complete(observation)
    store.save_step(completed)
    return completed


def _completed_step(kind: str, observation: dict) -> WorkStep:
    return (
        WorkStep(
            work_id="work-diagnostic",
            kind=kind,
            summary=kind,
            input_data={},
        )
        .start()
        .complete(observation)
    )


def test_incident_and_knowledge_actions_read_only_admitted_artifacts(tmp_path) -> None:
    _, changes, work_id = _fixture(tmp_path)
    resolver = DiagnosticContextResolver(changes)

    incident = asyncio.run(
        DiagnosticGetIncidentExecutor(resolver).execute(
            work=changes.work.require(work_id),
            parameters={},
        )
    )
    knowledge = asyncio.run(
        DiagnosticRetrieveKnowledgeExecutor(resolver).execute(
            work=changes.work.require(work_id),
            parameters={},
        )
    )

    assert incident["incident"]["incident_id"] == "incident-1"
    assert incident["source_revision"] == REVISION
    assert knowledge["revision_ids"] == ["knowledge-r1"]
    assert knowledge["advisory_only"] is True


def test_hypothesis_rejects_stale_or_unknown_evidence_ids(tmp_path) -> None:
    _, changes, work_id = _fixture(tmp_path)
    resolver = DiagnosticContextResolver(changes)
    executor = DiagnosticRecordHypothesisExecutor(resolver)

    with pytest.raises(DiagnosticProtocolError, match="stale or unknown"):
        asyncio.run(
            executor.execute(
                work=changes.work.require(work_id),
                parameters={
                    "statement": "possible race",
                    "status": "supported",
                    "supporting_evidence_ids": ["invented-evidence"],
                },
            )
        )


def test_finalize_persists_supported_diagnosis_bound_to_evidence(tmp_path) -> None:
    work_store, changes, work_id = _fixture(tmp_path)
    resolver = DiagnosticContextResolver(changes)
    work = changes.work.require(work_id)

    hypothesis = asyncio.run(
        DiagnosticRecordHypothesisExecutor(resolver).execute(
            work=work,
            parameters={
                "statement": "voice supervisor race",
                "affected_components": ["runtime.voice"],
                "affected_paths": ["src/jarvis/voice/runtime.py"],
                "status": "supported",
                "supporting_evidence_ids": ["e1"],
                "discriminator": "failure occurs before supervisor state commit",
            },
        )
    )
    _persist_completed(
        work_store,
        work_id=work_id,
        kind="diag_record_hypothesis",
        observation=hypothesis,
    )
    _persist_completed(
        work_store,
        work_id=work_id,
        kind="diag_run_reproduction",
        observation={
            "evidence_id": "reproduction_test",
            "reproduction_state": "reproduced",
            "pytest_returncode": 1,
            "coverage_files": [
                {
                    "path": "src/jarvis/voice/runtime.py",
                    "executed_lines": [10, 11],
                }
            ],
        },
    )

    result = asyncio.run(
        DiagnosticFinalizeExecutor(resolver).execute(
            work=changes.work.require(work_id),
            parameters={
                "selected_hypothesis_id": hypothesis["hypothesis"]["hypothesis_id"],
                "affected_paths": ["src/jarvis/voice/runtime.py"],
                "affected_components": ["runtime.voice"],
                "proposed_repair_scope": "serialize supervisor state commit",
                "verification_targets": ["tests/test_voice_runtime.py"],
                "reason_codes": ["reproduced", "supported_hypothesis"],
                "disposition": "supported_repair",
            },
        )
    )

    diagnosis = result["diagnosis"]
    assert result["finalized"] is True
    assert diagnosis["disposition"] == "supported_repair"
    assert (
        diagnosis["selected_hypothesis_id"] == hypothesis["hypothesis"]["hypothesis_id"]
    )
    assert "e1" in diagnosis["evidence_ids"]
    assert "reproduction_test" in diagnosis["evidence_ids"]
    assert diagnosis["knowledge_revision_ids"] == ["knowledge-r1"]
    artifact = changes.latest_artifact(
        changes.stage_for_work(work_id).change_id,
        "diagnosis",
    )
    assert artifact is not None
    assert artifact.artifact_id == result["diagnosis_artifact_id"]


def test_finalize_without_reproduction_requires_typed_impossible_reason(
    tmp_path,
) -> None:
    work_store, changes, work_id = _fixture(tmp_path)
    resolver = DiagnosticContextResolver(changes)
    work = changes.work.require(work_id)
    hypothesis = asyncio.run(
        DiagnosticRecordHypothesisExecutor(resolver).execute(
            work=work,
            parameters={
                "statement": "external hardware timing may be involved",
                "status": "inconclusive",
            },
        )
    )
    _persist_completed(
        work_store,
        work_id=work_id,
        kind="diag_record_hypothesis",
        observation=hypothesis,
    )

    executor = DiagnosticFinalizeExecutor(resolver)
    with pytest.raises(DiagnosticProtocolError, match="reproduction evidence"):
        asyncio.run(
            executor.execute(
                work=changes.work.require(work_id),
                parameters={"disposition": "inconclusive"},
            )
        )

    result = asyncio.run(
        executor.execute(
            work=changes.work.require(work_id),
            parameters={
                "disposition": "inconclusive",
                "reproduction_impossible_reason": (
                    "requires unavailable physical timing fault injection"
                ),
            },
        )
    )
    assert result["diagnosis"]["disposition"] == "inconclusive"
    assert result["diagnosis"]["selected_hypothesis_id"] is None
    assert "reproduction_impossible" in result["diagnosis"]["reason_codes"]


def test_ochiai_scoring_requires_failing_and_passing_coverage_samples() -> None:
    failing = _completed_step(
        "diag_run_reproduction",
        {
            "reproduction_state": "reproduced",
            "coverage_files": [
                {
                    "path": "src/jarvis/example.py",
                    "executed_lines": [10, 11],
                }
            ],
        },
    )
    passing = _completed_step(
        "diag_run_reproduction",
        {
            "reproduction_state": "not_reproduced",
            "coverage_files": [
                {
                    "path": "src/jarvis/example.py",
                    "executed_lines": [11],
                }
            ],
        },
    )

    assert suspicious_location_scores((failing,)) == ()
    scores = suspicious_location_scores((failing, passing))
    assert scores[0]["path"] == "src/jarvis/example.py"
    assert scores[0]["line"] == 10
    assert scores[0]["score"] == 1.0
    assert scores[1]["line"] == 11
    assert 0 < scores[1]["score"] < 1.0


def test_diagnostic_completion_guard_requires_latest_structured_finalize() -> None:
    work = WorkItem(
        request="diagnose",
        work_type=WorkType.DIAGNOSTICS,
        source_session_id="incident:1",
        source_turn_id="revision:a",
    )
    steps = (
        _completed_step(
            "diag_get_incident",
            {"incident": {"incident_id": "1"}},
        ),
        _completed_step(
            "diag_prepare_workspace",
            {"prepared": True, "revision": REVISION},
        ),
        _completed_step(
            "diag_record_hypothesis",
            {"hypothesis": {"hypothesis_id": "h1"}},
        ),
        _completed_step(
            "diag_run_reproduction",
            {"reproduction_state": "reproduced"},
        ),
        _completed_step(
            "diag_finalize",
            {
                "finalized": True,
                "diagnosis": {
                    "disposition": "supported_repair",
                    "selected_hypothesis_id": "h1",
                    "proposed_repair_scope": "fix race",
                    "verification_targets": ["tests/test_fault.py"],
                },
                "diagnosis_artifact_id": "artifact-1",
                "diagnosis_artifact_digest": "d" * 64,
            },
        ),
    )

    allowed, reason = WorkEngine._completion_guard(work, steps)
    assert allowed is True
    assert reason is None
    result = WorkEngine._diagnostic_result_payload(steps)
    assert result["diagnosis"]["disposition"] == "supported_repair"
    assert "summary" not in result

    stale = (*steps, _completed_step("diag_read_file", {"path": "x.py"}))
    allowed, reason = WorkEngine._completion_guard(work, stale)
    assert allowed is False
    assert "re-finalize" in str(reason)


def test_diagnostic_completion_guard_allows_typed_inconclusive_without_repro() -> None:
    work = WorkItem(
        request="diagnose",
        work_type=WorkType.DIAGNOSTICS,
        source_session_id="incident:1",
        source_turn_id="revision:a",
    )
    steps = (
        _completed_step(
            "diag_get_incident",
            {"incident": {"incident_id": "1"}},
        ),
        _completed_step(
            "diag_prepare_workspace",
            {"prepared": True, "revision": REVISION},
        ),
        _completed_step(
            "diag_record_hypothesis",
            {"hypothesis": {"hypothesis_id": "h1"}},
        ),
        _completed_step(
            "diag_finalize",
            {
                "finalized": True,
                "diagnosis": {
                    "disposition": "inconclusive",
                    "selected_hypothesis_id": None,
                    "verification_targets": [],
                },
                "reproduction_impossible_reason": "hardware unavailable",
            },
        ),
    )
    assert WorkEngine._completion_guard(work, steps) == (True, None)


def test_diagnostic_steps_produce_routing_failure_signals() -> None:
    steps = (
        _completed_step(
            "diag_record_hypothesis",
            {"hypothesis": {"status": "refuted"}},
        ),
        _completed_step(
            "diag_run_reproduction",
            {"reproduction_state": "not_reproduced"},
        ),
        _completed_step(
            "diag_finalize",
            {
                "diagnosis": {
                    "reason_codes": ["conflicting_evidence"],
                }
            },
        ),
    )

    signals = derive_work_step_signals(steps)

    assert signals.routing_features["failed_hypothesis_count"] == 1
    assert signals.routing_features["conflicting_evidence_count"] == 1
    assert signals.routing_features["reproduction_failure_count"] == 1
    assert "failed_hypothesis" in signals.failure_signals
    assert "conflicting_evidence" in signals.failure_signals
    assert "stalled_progress" in signals.failure_signals
