from __future__ import annotations

import pytest

from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.promotion import (
    CheckEvidence,
    CompatibilityEvidence,
    CompatibilityVerdict,
    PromotionAttemptState,
    PromotionCandidateError,
    PromotionCandidateVerifier,
    PromotionEvidenceV1,
    PromotionStore,
    StalePromotionCandidate,
)
from jarvis.work.store import SQLiteWorkStore

BASE = "1" * 40
HEAD = "2" * 40
MERGE = "3" * 40
LKG = "4" * 40
DIGEST = "a" * 64
DIFF = "b" * 64
CONFIG = "c" * 64


def _ready_candidate(tmp_path):
    changes = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    change = changes.create(
        request="Repair runtime",
        process_key="engineering.change",
        process_version=1,
        source_session_id="owner-session",
        source_turn_id="owner-turn",
    )
    with changes.work._lock, changes.work._connect() as db:
        db.execute(
            "UPDATE engineering_changes SET state=? WHERE change_id=?",
            (ChangeState.READY_FOR_PROMOTION.value, change.change_id),
        )
    candidate = changes.add_artifact(
        change.change_id,
        kind="source_repair_candidate",
        payload={
            "candidate_id": "candidate_123",
            "digest": DIGEST,
            "source_revision": BASE,
            "commit": HEAD,
            "diff_digest": DIFF,
            "changed_paths": ["src/jarvis/voice/runtime.py"],
            "protected_surface": {
                "policy_id": "repair.protected_surfaces",
                "policy_version": 2,
                "verdict": "clear",
                "protected": [],
                "unknown_paths": [],
                "clear_paths": ["src/jarvis/voice/runtime.py"],
            },
        },
    )
    acceptance = changes.add_artifact(
        change.change_id,
        kind="acceptance",
        payload={
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
        },
    )
    promotions = PromotionStore(changes)
    return changes, promotions, change, candidate, acceptance


def test_candidate_verification_creates_idempotent_exact_attempt(tmp_path) -> None:
    changes, promotions, change, candidate, acceptance = _ready_candidate(tmp_path)
    verifier = PromotionCandidateVerifier(changes, promotions)

    verified, first = verifier.verify_and_create_attempt(
        change.change_id,
        current_main_sha=BASE,
    )
    _, second = verifier.verify_and_create_attempt(
        change.change_id,
        current_main_sha=BASE,
    )

    assert first == second
    assert first.state is PromotionAttemptState.CREATED
    assert first.base_sha == BASE
    assert first.head_sha == HEAD
    assert verified.candidate_artifact_id == candidate.artifact_id
    assert verified.acceptance_artifact_id == acceptance.artifact_id


def test_candidate_stale_base_fails_closed_and_is_durable(tmp_path) -> None:
    changes, promotions, change, _, _ = _ready_candidate(tmp_path)
    verifier = PromotionCandidateVerifier(changes, promotions)

    with pytest.raises(StalePromotionCandidate) as error:
        verifier.verify_and_create_attempt(
            change.change_id,
            current_main_sha="9" * 40,
        )

    assert error.value.reason_code == "stale_candidate_base"
    with changes.work._lock, changes.work._connect() as db:
        row = db.execute(
            "SELECT state FROM promotion_attempts WHERE change_id=?",
            (change.change_id,),
        ).fetchone()
    assert row["state"] == PromotionAttemptState.STALE.value


def test_candidate_acceptance_mismatch_is_rejected(tmp_path) -> None:
    changes, promotions, change, _, _ = _ready_candidate(tmp_path)
    newer = changes.add_artifact(
        change.change_id,
        kind="acceptance",
        payload={
            "candidate_artifact_id": "wrong",
            "candidate_artifact_digest": DIGEST,
        },
    )
    assert newer.revision == 2

    with pytest.raises(PromotionCandidateError) as error:
        PromotionCandidateVerifier(changes, promotions).verify_and_create_attempt(
            change.change_id,
            current_main_sha=BASE,
        )

    assert error.value.reason_code == "acceptance_candidate_mismatch"


def test_promotion_attempt_transition_is_optimistic_and_bounded(tmp_path) -> None:
    changes, promotions, change, _, _ = _ready_candidate(tmp_path)
    _, attempt = PromotionCandidateVerifier(
        changes, promotions
    ).verify_and_create_attempt(change.change_id, current_main_sha=BASE)

    ready = promotions.transition(
        attempt.attempt_id,
        PromotionAttemptState.EVIDENCE_READY,
        expected_version=attempt.version,
        pr_number=123,
        promotion_artifact_id="artifact_promotion",
        promotion_artifact_digest=DIGEST,
    )
    assert ready.version == 2
    assert ready.pr_number == 123

    with pytest.raises(Exception, match="stale promotion attempt update"):
        promotions.transition(
            ready.attempt_id,
            PromotionAttemptState.AUTHORIZED,
            expected_version=1,
        )


def test_promotion_evidence_binds_exact_candidate_ci_and_compatibility() -> None:
    evidence = PromotionEvidenceV1.create(
        change_id="change_1",
        attempt_id="promotion_123",
        candidate_artifact_id="artifact_1",
        candidate_artifact_digest=DIGEST,
        candidate_id="candidate_1",
        candidate_digest=DIGEST,
        candidate_base_sha=BASE,
        candidate_head_sha=HEAD,
        candidate_diff_digest=DIFF,
        changed_paths=["src/jarvis/voice/runtime.py"],
        protected_policy_id="repair.protected_surfaces",
        protected_policy_version=2,
        protected_verdict="clear",
        pr_number=12,
        pr_base_sha=BASE,
        pr_head_sha=HEAD,
        tested_merge_sha=MERGE,
        ci_run_id="run-12",
        required_checks=[
            CheckEvidence("ruff", "success", 15368),
            CheckEvidence("pytest", "success", 15368),
            CheckEvidence("promotion-policy", "success", 15368),
        ],
        windows_verified=True,
        compatibility=CompatibilityEvidence(
            schema=CompatibilityVerdict.SAFE,
            dbos=CompatibilityVerdict.SAFE,
            dependencies=CompatibilityVerdict.SAFE,
        ),
        config_digest=CONFIG,
        merge_method="squash",
        deployment_environment="owner-windows",
        lkg_release_sha=LKG,
        now_epoch=1.0,
    )

    assert evidence.digest
    assert evidence.evidence_id.endswith(evidence.digest[:16])
    assert evidence.canonical_payload()["pr_head_sha"] == HEAD


def test_promotion_evidence_rejects_non_success_or_high_risk_path() -> None:
    safe = CompatibilityEvidence(
        schema=CompatibilityVerdict.SAFE,
        dbos=CompatibilityVerdict.SAFE,
        dependencies=CompatibilityVerdict.SAFE,
    )
    kwargs = dict(
        change_id="change_1",
        attempt_id="promotion_123",
        candidate_artifact_id="artifact_1",
        candidate_artifact_digest=DIGEST,
        candidate_id="candidate_1",
        candidate_digest=DIGEST,
        candidate_base_sha=BASE,
        candidate_head_sha=HEAD,
        candidate_diff_digest=DIFF,
        changed_paths=["src/jarvis/voice/runtime.py"],
        protected_policy_id="repair.protected_surfaces",
        protected_policy_version=2,
        protected_verdict="clear",
        pr_number=12,
        pr_base_sha=BASE,
        pr_head_sha=HEAD,
        tested_merge_sha=MERGE,
        ci_run_id="run-12",
        windows_verified=True,
        config_digest=CONFIG,
        merge_method="squash",
        deployment_environment="owner-windows",
        lkg_release_sha=LKG,
        now_epoch=1.0,
    )
    with pytest.raises(ValueError, match="conclusion=success"):
        PromotionEvidenceV1.create(
            **kwargs,
            required_checks=[CheckEvidence("ruff", "failure", 15368)],
            compatibility=safe,
        )
    with pytest.raises(ValueError, match="SAFE compatibility"):
        PromotionEvidenceV1.create(
            **kwargs,
            required_checks=[CheckEvidence("ruff", "success", 15368)],
            compatibility=CompatibilityEvidence(
                schema=CompatibilityVerdict.SAFE,
                dbos=CompatibilityVerdict.REVIEW_REQUIRED,
                dependencies=CompatibilityVerdict.SAFE,
            ),
        )
