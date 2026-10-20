from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_registry.compatibility import (
    CapabilityCompatibilityReportV1,
    CompatibilityVerdict,
)
from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_learning.adapters import (
    CapabilityAcquisitionOutcomeAdapter,
    CapabilityCompatibilityOutcomeAdapter,
    EngineeringOutcomeAdapterError,
    PromotionOutcomeAdapter,
    RepairOutcomeAdapter,
)
from jarvis.engineering_learning.models import (
    EngineeringOutcomeAttribution,
    EngineeringOutcomeResult,
)
from jarvis.engineering_learning.reconciliation import (
    EngineeringLearningReconciler,
    LearningReconciliationStatus,
)
from jarvis.engineering_learning.sources import (
    CapabilityAcquisitionOutcomeSource,
    PromotionOutcomeSource,
    RepairOutcomeSource,
)
from jarvis.incidents import IncidentService, SqliteIncidentStore
from jarvis.promotion.models import PromotionAttempt, PromotionAttemptState
from jarvis.promotion.store import PromotionStore
from jarvis.self_model import HealthState
from jarvis.self_repair import (
    RepairAction,
    RepairActionKind,
    RepairAttempt,
    RepairPolicy,
    RepairRiskClass,
    RepairTrigger,
    RepairVerificationResult,
    RepairVerificationStatus,
)
from jarvis.work.store import SQLiteWorkStore

BASE = "1" * 40
HEAD = "2" * 40
MERGE = "3" * 40
CANDIDATE_DIGEST = "a" * 64
PACKAGE_DIGEST = "b" * 64
REPORT_DIGEST = "c" * 64


def _changes(tmp_path: Path) -> ChangeStore:
    return ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))


def _promotion_fixture(
    tmp_path: Path,
    *,
    state: PromotionAttemptState,
):
    changes = _changes(tmp_path)
    change = changes.create(
        request="promote candidate",
        process_key="engineering.change",
        process_version=1,
        source_session_id="owner",
        source_turn_id="turn",
    )
    candidate = changes.add_artifact(
        change.change_id,
        kind="source_repair_candidate",
        payload={"candidate_id": "candidate-1"},
    )
    attempt = PromotionAttempt(
        attempt_id="promotion_phase10_adapter",
        change_id=change.change_id,
        candidate_artifact_id=candidate.artifact_id,
        candidate_artifact_digest=candidate.digest,
        candidate_id="candidate-1",
        candidate_digest=CANDIDATE_DIGEST,
        base_sha=BASE,
        head_sha=HEAD,
        state=state,
        pr_number=1,
        promotion_artifact_id=None,
        promotion_artifact_digest=None,
        merge_sha=MERGE
        if state
        in {
            PromotionAttemptState.COMPLETED,
            PromotionAttemptState.ROLLED_BACK,
            PromotionAttemptState.FAILED,
        }
        else None,
        deployment_id="deploy-1",
        lkg_sha=BASE,
        last_reason=None,
        version=1,
        created_at="2026-09-28T00:00:00+00:00",
        updated_at="2026-09-28T00:01:00+00:00",
    )
    return changes, change, candidate, attempt


def _observation(
    changes: ChangeStore,
    change_id: str,
    *,
    attempt_id: str,
    healthy: bool,
    attribution: str | None,
    reason_code: str,
    epoch: float,
) -> None:
    changes.add_artifact(
        change_id,
        kind="production_observation",
        payload={
            "attempt_id": attempt_id,
            "ordinal": 1,
            "healthy": healthy,
            "attribution": attribution,
            "reason_code": reason_code,
            "evidence": ["runtime:evidence"],
            "observed_at_epoch": epoch,
        },
    )


def test_promotion_completed_requires_and_preserves_healthy_observation(
    tmp_path: Path,
) -> None:
    changes, change, _, attempt = _promotion_fixture(
        tmp_path,
        state=PromotionAttemptState.COMPLETED,
    )
    _observation(
        changes,
        change.change_id,
        attempt_id=attempt.attempt_id,
        healthy=True,
        attribution=None,
        reason_code="runtime_healthy",
        epoch=100.0,
    )

    outcome = PromotionOutcomeAdapter(changes).normalize(attempt)

    assert outcome.result is EngineeringOutcomeResult.SUCCESS
    assert outcome.attribution is EngineeringOutcomeAttribution.NOT_APPLICABLE
    assert outcome.release_sha == MERGE
    assert "runtime_healthy" in outcome.reason_codes
    assert (
        sum(ref.startswith("change-artifact:") for ref in outcome.evidence_references)
        == 2
    )


def test_candidate_local_rollback_becomes_candidate_negative_outcome(
    tmp_path: Path,
) -> None:
    changes, change, _, attempt = _promotion_fixture(
        tmp_path,
        state=PromotionAttemptState.ROLLED_BACK,
    )
    _observation(
        changes,
        change.change_id,
        attempt_id=attempt.attempt_id,
        healthy=False,
        attribution="candidate_local",
        reason_code="candidate_runtime_regression",
        epoch=100.0,
    )

    outcome = PromotionOutcomeAdapter(changes).normalize(attempt)

    assert outcome.result is EngineeringOutcomeResult.ROLLED_BACK
    assert outcome.attribution is EngineeringOutcomeAttribution.CANDIDATE
    assert "candidate_runtime_regression" in outcome.reason_codes


def test_rollback_without_candidate_local_evidence_fails_closed(
    tmp_path: Path,
) -> None:
    changes, change, _, attempt = _promotion_fixture(
        tmp_path,
        state=PromotionAttemptState.ROLLED_BACK,
    )
    _observation(
        changes,
        change.change_id,
        attempt_id=attempt.attempt_id,
        healthy=False,
        attribution="external_provider",
        reason_code="provider_quota",
        epoch=100.0,
    )

    with pytest.raises(
        EngineeringOutcomeAdapterError,
        match="candidate-local failure",
    ):
        PromotionOutcomeAdapter(changes).normalize(attempt)


def test_failed_promotion_preserves_external_provider_attribution(
    tmp_path: Path,
) -> None:
    changes, change, _, attempt = _promotion_fixture(
        tmp_path,
        state=PromotionAttemptState.FAILED,
    )
    _observation(
        changes,
        change.change_id,
        attempt_id=attempt.attempt_id,
        healthy=False,
        attribution="external_provider",
        reason_code="provider_quota",
        epoch=100.0,
    )

    outcome = PromotionOutcomeAdapter(changes).normalize(attempt)

    assert outcome.result is EngineeringOutcomeResult.FAILURE
    assert outcome.attribution is EngineeringOutcomeAttribution.EXTERNAL_PROVIDER
    assert outcome.attribution is not EngineeringOutcomeAttribution.CANDIDATE


def _three_repair_outcomes(tmp_path):
    store = SqliteIncidentStore(tmp_path / "engineering.sqlite")
    incident = IncidentService(store).create_manual(
        symptom="synthetic runtime failure", now_epoch=80
    )
    for ordinal in range(3):
        IncidentService(store).record_repair_attempt(
            replace(
                _repair_attempt(RepairVerificationStatus.PASS),
                incident_id=incident.incident_id,
                attempt_id=f"repair-{ordinal}",
                finished_at_epoch=100.0,
            )
        )
    return store


def test_bounded_repair_scans_reach_later_outcomes_and_retry_index_failure(
    tmp_path, monkeypatch
):
    store = _three_repair_outcomes(tmp_path)
    source = RepairOutcomeSource(store)
    reconciler = EngineeringLearningReconciler(store)
    refresh = reconciler._refresh_index
    failed = False

    def fail_once(revision_id, *, now_epoch):
        nonlocal failed
        if not failed:
            failed = True
            return "synthetic_index_unavailable"
        return refresh(revision_id, now_epoch=now_epoch)

    monkeypatch.setattr(reconciler, "_refresh_index", fail_once)
    try:
        reports = [
            reconciler.reconcile_source(source, limit=1, now_epoch=110 + n)
            for n in range(4)
        ]
        assert len({r.items[0].outcome_id for r in reports[:3]}) == 3
        assert (
            reports[0].items[0].status
            is LearningReconciliationStatus.INDEX_RETRY_REQUIRED
        )
        assert reports[3].items[0].outcome_id == reports[0].items[0].outcome_id
        assert reports[3].items[0].status in {
            LearningReconciliationStatus.REPLAYED,
            LearningReconciliationStatus.RESUMED,
        }
        assert all(r.processed_count <= 1 for r in reports)
    finally:
        reconciler.close()
        store.close()


def test_bounded_repair_scans_retry_bad_normalization_after_reaching_later_records(
    tmp_path, monkeypatch
):
    store = _three_repair_outcomes(tmp_path)
    source = RepairOutcomeSource(store)
    normalize = source._adapter.normalize

    def fail_first(attempt):
        if attempt.attempt_id == "repair-0":
            raise EngineeringOutcomeAdapterError("synthetic missing evidence")
        return normalize(attempt)

    monkeypatch.setattr(source._adapter, "normalize", fail_first)
    try:
        first = source.scan(limit=2, observed_at_epoch=110)
        second = source.scan(limit=2, observed_at_epoch=111)
        monkeypatch.setattr(source._adapter, "normalize", normalize)
        retry = source.scan(limit=2, observed_at_epoch=112)
        assert first.errors
        assert [o.source_identity for o in second.outcomes] == ["repair-2"]
        assert "repair-0" in [o.source_identity for o in retry.outcomes]
        restarted = RepairOutcomeSource(store)
        assert len(restarted.scan(limit=2, observed_at_epoch=113).outcomes) == 2
        assert [
            o.source_identity
            for o in restarted.scan(limit=2, observed_at_epoch=114).outcomes
        ] == ["repair-2"]
    finally:
        store.close()


@pytest.mark.parametrize("kind", ["promotion", "capability_acquisition"])
def test_bounded_work_outcome_scans_reach_all_records_then_wrap(tmp_path, kind):
    changes = ChangeStore(
        SQLiteWorkStore(tmp_path / "work.sqlite"),
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    promotions = PromotionStore(changes)
    expected = set()
    for ordinal in range(3):
        change = changes.create(
            request="synthetic candidate",
            process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
            process_version=1,
            source_session_id="test",
            source_turn_id=str(ordinal),
        )
        candidate = changes.add_artifact(
            change.change_id,
            kind="capability_candidate",
            payload={
                "candidate_id": f"candidate-{ordinal}",
                "package_id": "test.capability",
                "package_version": "1.0.0",
                "package_digest": PACKAGE_DIGEST,
            },
        )
        if kind == "promotion":
            attempt = promotions.create_or_get(
                change_id=change.change_id,
                candidate_artifact_id=candidate.artifact_id,
                candidate_artifact_digest=candidate.digest,
                candidate_id=f"candidate-{ordinal}",
                candidate_digest=CANDIDATE_DIGEST,
                base_sha=BASE,
                head_sha=HEAD,
            )
            with changes.work._connect() as db:
                db.execute(
                    "UPDATE promotion_attempts SET state='failed' WHERE attempt_id=?",
                    (attempt.attempt_id,),
                )
            expected.add(attempt.attempt_id)
        else:
            _set_change_state(changes, change.change_id, ChangeState.FAILED)
            expected.add(change.change_id)
    source = (
        PromotionOutcomeSource(promotions)
        if kind == "promotion"
        else CapabilityAcquisitionOutcomeSource(changes)
    )
    scans = [source.scan(limit=2, observed_at_epoch=110 + n) for n in range(3)]
    assert all(not scan.errors for scan in scans)
    assert {o.source_identity for scan in scans[:2] for o in scan.outcomes} == expected
    assert len(scans[1].outcomes) == 1
    assert scans[2].outcomes == scans[0].outcomes


def _repair_attempt(status: RepairVerificationStatus) -> RepairAttempt:
    policy = RepairPolicy(
        policy_id="runtime-child-exit-v1",
        version=1,
        trigger_source="dev_supervisor",
        component_id="runtime.voice",
        reason_code="child_exited",
        action_kind=RepairActionKind.RESTART_RUNTIME_CHILD,
        risk_class=RepairRiskClass.R2_RESTART,
        preconditions=("same_local_revision", "restart_budget_available"),
        max_attempts=3,
        rolling_window_seconds=300,
        cooldown_seconds=2,
        backoff_multiplier=2,
        verification_contract="runtime_ready_and_live",
        health_states=(HealthState.FAILED,),
        reversible=True,
        automatic=True,
    )
    trigger = RepairTrigger.create(
        trigger_id="trigger-phase10",
        component_id="runtime.voice",
        reason_code="child_exited",
        source="dev_supervisor",
        health_state=HealthState.FAILED,
        process_exit_code=1,
        evidence_references=("crash:abc",),
        observed_at_epoch=90.0,
    )
    action = RepairAction.create(
        policy,
        trigger,
        now_epoch=91.0,
        action_id="action-phase10",
    )
    started = RepairAttempt.start(
        incident_id="incident-phase10",
        trigger=trigger,
        policy=policy,
        action=action,
        attempt_number=1,
        now_epoch=91.0,
        attempt_id="attempt-phase10",
    )
    verification = RepairVerificationResult.create(
        verifier_id="runtime-verifier",
        verifier_version=1,
        contract_id="runtime_ready_and_live",
        status=status,
        summary="verified result",
        evidence_references=("health:runtime.voice",),
        observed_at_epoch=100.0,
    )
    return started.complete(
        execution_result="restart attempted",
        verification=verification,
        post_repair_evidence=("health:runtime.voice",),
        now_epoch=100.0,
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (RepairVerificationStatus.PASS, EngineeringOutcomeResult.SUCCESS),
        (RepairVerificationStatus.FAIL, EngineeringOutcomeResult.FAILURE),
        (
            RepairVerificationStatus.INCONCLUSIVE,
            EngineeringOutcomeResult.INCONCLUSIVE,
        ),
    ],
)
def test_repair_adapter_preserves_typed_verification_result(
    status: RepairVerificationStatus,
    expected: EngineeringOutcomeResult,
) -> None:
    outcome = RepairOutcomeAdapter().normalize(_repair_attempt(status))

    assert outcome.result is expected
    assert outcome.attribution is EngineeringOutcomeAttribution.NOT_APPLICABLE
    assert outcome.applicability[0].target_identity == "runtime.voice"


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        (CompatibilityVerdict.READY, EngineeringOutcomeResult.SUCCESS),
        (CompatibilityVerdict.BLOCKED, EngineeringOutcomeResult.BLOCKED),
        (CompatibilityVerdict.RESTART_REQUIRED, EngineeringOutcomeResult.BLOCKED),
    ],
)
def test_compatibility_adapter_scopes_exact_package_and_release(
    verdict: CompatibilityVerdict,
    expected: EngineeringOutcomeResult,
) -> None:
    report = CapabilityCompatibilityReportV1(
        package_id="tv.control",
        package_version="1.2.3",
        package_digest=PACKAGE_DIGEST,
        current_release_sha=MERGE,
        runtime_release_sha=MERGE,
        platform_tags=("windows-amd64",),
        verdict=verdict,
        reason_codes=(verdict.value,),
        manifest_digest=None,
        provider_descriptor_digest=None,
        artifact_digests=(),
    )

    outcome = CapabilityCompatibilityOutcomeAdapter().normalize(
        report,
        observed_at_epoch=100.0,
    )

    assert outcome.result is expected
    assert outcome.attribution is EngineeringOutcomeAttribution.COMPATIBILITY
    assert outcome.package_id == "tv.control"
    assert outcome.package_version == "1.2.3"
    assert any(
        item.target_namespace == "package"
        and item.matcher_type == "version_exact"
        and item.constraint == {"version": "1.2.3"}
        for item in outcome.applicability
    )
    assert any(
        item.target_namespace == "jarvis.revision" and item.target_identity == MERGE
        for item in outcome.applicability
    )


def _acquisition_store(tmp_path: Path):
    changes = ChangeStore(
        SQLiteWorkStore(tmp_path / "acquisition.sqlite3"),
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    change = changes.create(
        request="Acquire TV control",
        process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
        source_session_id="owner",
        source_turn_id="turn",
    )
    candidate = changes.add_artifact(
        change.change_id,
        kind="capability_candidate",
        payload={
            "candidate_id": "capcand-1",
            "package_id": "tv.control",
            "package_version": "1.0.0",
            "package_digest": PACKAGE_DIGEST,
            "capability_id": "tv.control",
        },
    )
    return changes, change, candidate


def _set_change_state(changes: ChangeStore, change_id: str, state: ChangeState) -> None:
    with changes.work._lock, changes.work._connect() as db:
        db.execute(
            "UPDATE engineering_changes SET state=?, updated_at=? WHERE change_id=?",
            (state.value, "2026-09-28T00:01:00+00:00", change_id),
        )


def test_closed_acquisition_requires_activation_and_healthy_observation(
    tmp_path: Path,
) -> None:
    changes, change, _ = _acquisition_store(tmp_path)
    _set_change_state(changes, change.change_id, ChangeState.CLOSED)

    with pytest.raises(
        EngineeringOutcomeAdapterError,
        match="activation/observation evidence",
    ):
        CapabilityAcquisitionOutcomeAdapter(changes).normalize(change.change_id)


def test_closed_acquisition_with_canonical_evidence_becomes_success(
    tmp_path: Path,
) -> None:
    changes, change, candidate = _acquisition_store(tmp_path)
    changes.add_artifact(
        change.change_id,
        kind="capability_package_admission",
        payload={
            "attempt_id": "promotion_phase10",
            "active_release_sha": MERGE,
        },
    )
    changes.add_artifact(
        change.change_id,
        kind="capability_lifecycle_activation",
        payload={
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
            "effective_enabled": True,
        },
    )
    _observation(
        changes,
        change.change_id,
        attempt_id="promotion_phase10",
        healthy=True,
        attribution=None,
        reason_code="runtime_healthy",
        epoch=100.0,
    )
    _set_change_state(changes, change.change_id, ChangeState.CLOSED)

    outcome = CapabilityAcquisitionOutcomeAdapter(changes).normalize(change.change_id)

    assert outcome.result is EngineeringOutcomeResult.SUCCESS
    assert outcome.package_id == "tv.control"
    assert outcome.release_sha == MERGE
    assert len(outcome.evidence_references) == 4


def test_blocked_external_acquisition_does_not_invent_provider_causality(
    tmp_path: Path,
) -> None:
    changes, change, _ = _acquisition_store(tmp_path)
    _set_change_state(changes, change.change_id, ChangeState.BLOCKED_EXTERNAL)

    outcome = CapabilityAcquisitionOutcomeAdapter(changes).normalize(change.change_id)

    assert outcome.result is EngineeringOutcomeResult.BLOCKED
    assert outcome.attribution is EngineeringOutcomeAttribution.UNKNOWN
