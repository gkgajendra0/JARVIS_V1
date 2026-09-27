"""Deterministic Phase-7 promotion/deployment replay evaluation.

The replay suite uses only local disposable state and typed fakes. It proves
governance/restart/rollback invariants in CI; it does not replace the final
owner-machine Windows acceptance harness.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace

from jarvis.authority.approval import ApprovalService
from jarvis.authority.types import AuthorityEffect
from jarvis.authority.verifier import (
    StrongVerificationResult,
    StrongVerificationStatus,
)
from jarvis.dev_control import RuntimeReleaseIdentity
from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.incident_repair.protected_surfaces import RepairProtectedSurfacePolicy
from jarvis.work.store import SQLiteWorkStore

from .authority import PromotionAuthorityBridge
from .candidate import PromotionCandidateVerifier, StalePromotionCandidate
from .compatibility import assess_ordinary_compatibility
from .deployment import DeploymentCoordinator
from .github import (
    GitHubPromotionError,
    GitHubPromotionPolicy,
    GitHubPullRequestSnapshot,
    GitHubWorkflowSnapshot,
)
from .merge import PromotionMerger
from .models import (
    CheckEvidence,
    CompatibilityEvidence,
    CompatibilityVerdict,
    PromotionAttemptState,
    PromotionEvidenceV1,
)
from .observation import (
    FailureAttribution,
    ObservationController,
    ObservationDisposition,
)
from .release import DeploymentMetadataStore, RecoveryPhase
from .rollback import RollbackCoordinator, RollbackError
from .store import PromotionStore

BASE = "1" * 40
HEAD = "2" * 40
TESTED_MERGE = "3" * 40
MERGE = "4" * 40
DIGEST = "a" * 64
DIFF = "b" * 64
CONFIG = "c" * 64


class Phase7EvaluationError(RuntimeError):
    """One deterministic Phase-7 replay invariant failed."""


@dataclass(frozen=True, slots=True)
class Phase7ReplayCase:
    case_id: str
    passed: bool
    evidence: dict[str, object]

    def to_payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class Phase7ReplayReport:
    status: str
    cases: tuple[Phase7ReplayCase, ...]
    suite_digest: str

    def to_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "cases": [item.to_payload() for item in self.cases],
            "suite_digest": self.suite_digest,
        }


class _Verifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, *, proposal, session_id):
        self.calls += 1
        return StrongVerificationResult(
            status=StrongVerificationStatus.VERIFIED,
            verifier_id="phase7-replay-verifier",
            verification_id=f"phase7-verification-{self.calls}",
            proposal_fingerprint=proposal.fingerprint,
            session_id=session_id,
        )


class _Authority:
    def __init__(self) -> None:
        self.consumed = 0

    def evaluate(self, *, proposal, context, approval_id=None):
        del proposal, context, approval_id
        return SimpleNamespace(
            effect=AuthorityEffect.ALLOW,
            execution_permit=SimpleNamespace(permit_id="phase7-permit"),
            reason_codes=(),
        )

    def revalidate_and_consume(self, *, permit_id, proposal, context):
        del permit_id, proposal, context
        self.consumed += 1


class _GitHub:
    def __init__(self) -> None:
        self.main = BASE
        self.merge_calls = 0
        self.pr = GitHubPullRequestSnapshot(12, BASE, HEAD, False, "open")
        self.workflow = _workflow()

    def read_protected_main_sha(self) -> str:
        return self.main

    def read_pull_request(self, number: int) -> GitHubPullRequestSnapshot:
        if number != 12:
            raise Phase7EvaluationError("unexpected PR number")
        return self.pr

    def read_workflow(self, number: int) -> GitHubWorkflowSnapshot:
        if number != 12:
            raise Phase7EvaluationError("unexpected workflow PR number")
        return self.workflow

    def squash_merge(self, number: int, *, expected_head_sha: str) -> str:
        if number != 12 or expected_head_sha != HEAD:
            raise Phase7EvaluationError("merge was not bound to exact candidate")
        self.merge_calls += 1
        self.main = MERGE
        self.pr = GitHubPullRequestSnapshot(
            12,
            BASE,
            HEAD,
            False,
            "closed",
            merged=True,
            merge_sha=MERGE,
        )
        return MERGE


class _Stager:
    def __init__(self, root: pathlib.Path) -> None:
        self.root = root

    def stage(self, sha: str) -> pathlib.Path:
        target = self.root / sha
        target.mkdir(parents=True, exist_ok=True)
        return target


class _Runtime:
    def __init__(self) -> None:
        self.events: list[str] = []

    def stop_active(self, *, timeout_seconds: float) -> None:
        del timeout_seconds
        self.events.append("stop_active")

    def start_release(self, identity: RuntimeReleaseIdentity) -> None:
        del identity
        self.events.append("start_release")

    def wait_ready(
        self,
        identity: RuntimeReleaseIdentity,
        *,
        timeout_seconds: float,
    ) -> None:
        del identity, timeout_seconds
        self.events.append("wait_ready")

    def stop_candidate(self, *, timeout_seconds: float) -> None:
        del timeout_seconds
        self.events.append("stop_candidate")

    def ensure_release(
        self,
        identity: RuntimeReleaseIdentity,
        *,
        timeout_seconds: float,
    ) -> None:
        del identity, timeout_seconds
        self.events.append("ensure_release")


def _checks(
    *,
    ruff_app_id: int = 15368,
    windows_conclusion: str = "success",
) -> tuple[CheckEvidence, ...]:
    return (
        CheckEvidence("ruff", "success", ruff_app_id),
        CheckEvidence("pytest", "success", 15368),
        CheckEvidence("windows-hello-helper", "success", 15368),
        CheckEvidence("windows-dpapi", windows_conclusion, 15368),
        CheckEvidence("promotion-policy", "success", 15368),
    )


def _workflow(
    *,
    head_sha: str = HEAD,
    checks: tuple[CheckEvidence, ...] | None = None,
) -> GitHubWorkflowSnapshot:
    return GitHubWorkflowSnapshot(
        run_id="phase7-run",
        event="pull_request",
        head_sha=head_sha,
        tested_merge_sha=TESTED_MERGE,
        status="completed",
        conclusion="success",
        checks=_checks() if checks is None else checks,
    )


def _case(
    case_id: str,
    callback: Callable[[], dict[str, object]],
) -> Phase7ReplayCase:
    try:
        evidence = callback()
    except Exception as exc:  # noqa: BLE001 - replay must preserve exact failed case
        return Phase7ReplayCase(
            case_id=case_id,
            passed=False,
            evidence={"error_type": type(exc).__name__, "reason": str(exc)},
        )
    return Phase7ReplayCase(case_id=case_id, passed=True, evidence=evidence)


def _candidate_fixture(root: pathlib.Path):
    root.mkdir(parents=True, exist_ok=True)
    changes = ChangeStore(SQLiteWorkStore(root / "work.sqlite3"))
    change = changes.create(
        request="Phase7 replay promotion",
        process_key="engineering.change",
        process_version=1,
        source_session_id="phase7-replay",
        source_turn_id="candidate",
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
            "candidate_id": "candidate-phase7",
            "digest": DIGEST,
            "source_revision": BASE,
            "branch": "repair/phase7-replay",
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
    changes.add_artifact(
        change.change_id,
        kind="acceptance",
        payload={
            "candidate_artifact_id": candidate.artifact_id,
            "candidate_artifact_digest": candidate.digest,
        },
    )
    promotions = PromotionStore(changes)
    verified, attempt = PromotionCandidateVerifier(
        changes,
        promotions,
    ).verify_and_create_attempt(
        change.change_id,
        current_main_sha=BASE,
    )
    return changes, promotions, verified, attempt


def _promotion_fixture(root: pathlib.Path):
    changes, promotions, candidate, attempt = _candidate_fixture(root)
    github_evidence = GitHubPromotionPolicy().verify(
        candidate,
        current_main_sha=BASE,
        pr=GitHubPullRequestSnapshot(12, BASE, HEAD, False, "open"),
        workflow=_workflow(),
    )
    evidence = PromotionEvidenceV1.create(
        change_id=candidate.change_id,
        attempt_id=attempt.attempt_id,
        candidate_artifact_id=candidate.candidate_artifact_id,
        candidate_artifact_digest=candidate.candidate_artifact_digest,
        candidate_id=candidate.candidate_id,
        candidate_digest=candidate.candidate_digest,
        candidate_base_sha=candidate.base_sha,
        candidate_head_sha=candidate.head_sha,
        candidate_diff_digest=candidate.diff_digest,
        changed_paths=candidate.changed_paths,
        protected_policy_id=candidate.protected_policy_id,
        protected_policy_version=candidate.protected_policy_version,
        protected_verdict=candidate.protected_verdict,
        pr_number=github_evidence.pr_number,
        pr_base_sha=github_evidence.pr_base_sha,
        pr_head_sha=github_evidence.pr_head_sha,
        tested_merge_sha=github_evidence.tested_merge_sha,
        ci_run_id=github_evidence.ci_run_id,
        required_checks=github_evidence.required_checks,
        windows_verified=github_evidence.windows_verified,
        compatibility=CompatibilityEvidence(
            schema=CompatibilityVerdict.SAFE,
            dbos=CompatibilityVerdict.SAFE,
            dependencies=CompatibilityVerdict.SAFE,
        ),
        config_digest=CONFIG,
        merge_method="squash",
        deployment_environment="phase7-replay-windows",
        lkg_release_sha=BASE,
        now_epoch=1.0,
    )
    artifact = changes.add_artifact(
        candidate.change_id,
        kind="promotion",
        payload={
            "evidence_id": evidence.evidence_id,
            **evidence.canonical_payload(),
            "digest": evidence.digest,
        },
    )
    attempt = promotions.transition(
        attempt.attempt_id,
        PromotionAttemptState.EVIDENCE_READY,
        expected_version=attempt.version,
        pr_number=evidence.pr_number,
        promotion_artifact_id=artifact.artifact_id,
        promotion_artifact_digest=artifact.digest,
    )
    gate = GateService(changes, verify_owner=lambda *_: False).present(
        candidate.change_id,
        GateKind.PROMOTION,
        artifact.artifact_id,
    )
    verifier = _Verifier()
    authority = _Authority()
    bridge = PromotionAuthorityBridge(
        changes,
        promotions,
        approvals=ApprovalService(),
        authority=authority,
        verifier=verifier,
    )
    authorized = bridge.authorize(
        gate_id=gate.gate_id,
        evidence=evidence,
        attempt=attempt,
        session_id="phase7-replay",
        source_turn_id="approve-promotion",
        request_key=f"phase7:{attempt.attempt_id}",
        repository_full_name="gkgajendra0/JARVIS_V1",
    )
    return (
        changes,
        promotions,
        evidence,
        promotions.require(attempt.attempt_id),
        bridge,
        authorized,
        authority,
    )


def _case_exact_candidate(root: pathlib.Path) -> dict[str, object]:
    _, _, candidate, attempt = _candidate_fixture(root)
    return {
        "attempt_id": attempt.attempt_id,
        "base_sha": candidate.base_sha,
        "head_sha": candidate.head_sha,
        "state": attempt.state.value,
    }


def _case_stale_candidate(root: pathlib.Path) -> dict[str, object]:
    changes, promotions, _, _ = _candidate_fixture(root)
    change = changes.list(states=(ChangeState.READY_FOR_PROMOTION,))[0]
    try:
        PromotionCandidateVerifier(changes, promotions).verify_and_create_attempt(
            change.change_id,
            current_main_sha="9" * 40,
        )
    except StalePromotionCandidate as exc:
        attempts = promotions.list_for_change(change.change_id)
        if not attempts or attempts[-1].state is not PromotionAttemptState.STALE:
            raise Phase7EvaluationError("stale candidate was not durably marked") from exc
        return {"reason_code": exc.reason_code, "state": attempts[-1].state.value}
    raise Phase7EvaluationError("stale candidate was accepted")


def _case_moved_head(root: pathlib.Path) -> dict[str, object]:
    _, _, candidate, _ = _candidate_fixture(root)
    try:
        GitHubPromotionPolicy().verify(
            candidate,
            current_main_sha=BASE,
            pr=GitHubPullRequestSnapshot(12, BASE, "9" * 40, False, "open"),
            workflow=_workflow(),
        )
    except GitHubPromotionError as exc:
        if exc.reason_code != "pr_head_moved":
            raise
        return {"reason_code": exc.reason_code}
    raise Phase7EvaluationError("moved PR head was accepted")


def _case_wrong_ci_app(root: pathlib.Path) -> dict[str, object]:
    _, _, candidate, _ = _candidate_fixture(root)
    try:
        GitHubPromotionPolicy().verify(
            candidate,
            current_main_sha=BASE,
            pr=GitHubPullRequestSnapshot(12, BASE, HEAD, False, "open"),
            workflow=_workflow(checks=_checks(ruff_app_id=999)),
        )
    except GitHubPromotionError as exc:
        if exc.reason_code != "ci_app_mismatch":
            raise
        return {"reason_code": exc.reason_code}
    raise Phase7EvaluationError("wrong CI app was accepted")


def _case_skipped_windows(root: pathlib.Path) -> dict[str, object]:
    _, _, candidate, _ = _candidate_fixture(root)
    try:
        GitHubPromotionPolicy().verify(
            candidate,
            current_main_sha=BASE,
            pr=GitHubPullRequestSnapshot(12, BASE, HEAD, False, "open"),
            workflow=_workflow(checks=_checks(windows_conclusion="skipped")),
        )
    except GitHubPromotionError as exc:
        if exc.reason_code != "required_ci_not_success":
            raise
        return {"reason_code": exc.reason_code}
    raise Phase7EvaluationError("skipped Windows validation was accepted")


def _merge(root: pathlib.Path, *, external_first: bool):
    (
        changes,
        promotions,
        evidence,
        attempt,
        bridge,
        authorized,
        authority,
    ) = _promotion_fixture(root)
    github = _GitHub()
    if external_first:
        github.main = MERGE
        github.pr = GitHubPullRequestSnapshot(
            12,
            BASE,
            HEAD,
            False,
            "closed",
            merged=True,
            merge_sha=MERGE,
        )
    result = PromotionMerger(
        changes,
        promotions,
        github=github,
        policy=GitHubPromotionPolicy(),
        authority=bridge,
    ).execute(
        evidence=evidence,
        attempt=attempt,
        authorized=authorized,
    )
    return changes, promotions, evidence, result, github, authority


def _case_exact_merge(root: pathlib.Path) -> dict[str, object]:
    changes, promotions, evidence, result, github, authority = _merge(
        root,
        external_first=False,
    )
    attempt = promotions.require(evidence.attempt_id)
    if changes.require(evidence.change_id).state is not ChangeState.PROMOTED:
        raise Phase7EvaluationError("EngineeringChange did not enter PROMOTED")
    return {
        "merge_sha": result.merge_sha,
        "merge_calls": github.merge_calls,
        "permit_consumed": authority.consumed,
        "attempt_state": attempt.state.value,
    }


def _case_merge_reconcile(root: pathlib.Path) -> dict[str, object]:
    _, _, _, result, github, authority = _merge(root, external_first=True)
    if not result.reconciled_after_external_merge:
        raise Phase7EvaluationError("external exact merge was not reconciled")
    return {
        "merge_calls": github.merge_calls,
        "permit_consumed": authority.consumed,
        "reconciled": result.reconciled_after_external_merge,
    }


def _merged_fixture(root: pathlib.Path):
    changes, promotions, evidence, _, _, _ = _merge(root, external_first=False)
    return changes, promotions, evidence, promotions.require(evidence.attempt_id)


def _deployment(
    root: pathlib.Path,
):
    changes, promotions, evidence, attempt = _merged_fixture(root)
    metadata = DeploymentMetadataStore(root / "deployment")
    runtime = _Runtime()
    coordinator = DeploymentCoordinator(
        changes,
        promotions,
        stager=_Stager(root / "releases"),
        metadata=metadata,
        runtime=runtime,
    )
    coordinator.bootstrap_lkg(
        release_sha=BASE,
        config_digest=CONFIG,
        verified=True,
        now_epoch=1.0,
    )
    result = coordinator.deploy(evidence=evidence, attempt=attempt, now_epoch=2.0)
    return changes, promotions, evidence, metadata, runtime, coordinator, result


def _case_full_success(root: pathlib.Path) -> dict[str, object]:
    changes, promotions, evidence, metadata, _, _, _ = _deployment(root)
    attempt = promotions.require(evidence.attempt_id)
    observations = ObservationController(
        changes,
        promotions,
        metadata,
        required_healthy_samples=3,
    )
    for index in range(3):
        observations.record_healthy(
            attempt,
            evidence=(f"phase7:liveness:{index}",),
            now_epoch=3.0 + index,
        )
    completed = observations.close_success(attempt)
    return {
        "attempt_state": completed.state.value,
        "change_state": changes.require(evidence.change_id).state.value,
        "lkg_sha": metadata.lkg().release_sha,
    }


def _case_external_failure_no_rollback(root: pathlib.Path) -> dict[str, object]:
    changes, promotions, evidence, metadata, runtime, _, _ = _deployment(root)
    attempt = promotions.require(evidence.attempt_id)
    observations = ObservationController(
        changes,
        promotions,
        metadata,
        required_healthy_samples=2,
    )
    observations.record_failure(
        attempt,
        attribution=FailureAttribution.EXTERNAL_PROVIDER,
        reason_code="provider_quota",
        evidence=("provider:429",),
        now_epoch=3.0,
    )
    observations.record_healthy(attempt, now_epoch=4.0)
    observations.record_healthy(attempt, now_epoch=5.0)
    if observations.assess(attempt).disposition is not ObservationDisposition.READY_TO_CLOSE:
        raise Phase7EvaluationError("external provider failure blocked healthy close")
    try:
        RollbackCoordinator(
            changes,
            promotions,
            metadata=metadata,
            runtime=runtime,
        ).rollback(
            evidence=evidence,
            attempt=attempt,
            attribution=FailureAttribution.EXTERNAL_PROVIDER,
        )
    except RollbackError:
        return {"rollback": "rejected", "external_failure": "provider_quota"}
    raise Phase7EvaluationError("external failure triggered code rollback")


def _case_candidate_rollback(root: pathlib.Path) -> dict[str, object]:
    changes, promotions, evidence, metadata, runtime, _, _ = _deployment(root)
    attempt = promotions.require(evidence.attempt_id)
    observations = ObservationController(changes, promotions, metadata)
    observations.record_failure(
        attempt,
        attribution=FailureAttribution.CANDIDATE_LOCAL,
        reason_code="candidate_regression",
        evidence=("runtime:readiness",),
        now_epoch=3.0,
    )
    if observations.assess(attempt).disposition is not ObservationDisposition.ROLLBACK_REQUIRED:
        raise Phase7EvaluationError("candidate failure did not require rollback")
    rollback = RollbackCoordinator(
        changes,
        promotions,
        metadata=metadata,
        runtime=runtime,
    )
    first = rollback.rollback(
        evidence=evidence,
        attempt=attempt,
        attribution=FailureAttribution.CANDIDATE_LOCAL,
    )
    second = rollback.rollback(
        evidence=evidence,
        attempt=promotions.require(attempt.attempt_id),
        attribution=FailureAttribution.CANDIDATE_LOCAL,
    )
    if not second.already_reconciled:
        raise Phase7EvaluationError("second rollback was not reconciled")
    return {
        "restored_sha": first.restored.release_sha,
        "second_reconciled": second.already_reconciled,
    }


def _case_high_risk_compatibility(_: pathlib.Path) -> dict[str, object]:
    assessment = assess_ordinary_compatibility(
        (
            "src/jarvis/work/dbos_backend.py",
            "src/jarvis/memory/migrations/002_new.sql",
            "pyproject.toml",
        )
    )
    if assessment.evidence.ordinary_path_safe:
        raise Phase7EvaluationError("high-risk compatibility change was marked safe")
    return {"reason_codes": list(assessment.reason_codes)}


def _case_protected_surfaces(_: pathlib.Path) -> dict[str, object]:
    result = RepairProtectedSurfacePolicy().assess(
        (
            "src/jarvis/promotion/merge.py",
            "src/jarvis/dev_supervisor.py",
            "src/jarvis/work/dbos_backend.py",
        )
    )
    if result.verdict is not ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED:
        raise Phase7EvaluationError("Phase-7 control surfaces were not protected")
    return {
        "policy_version": result.policy_version,
        "protected_count": len(result.protected),
    }


def _case_unknown_observation_blocks(root: pathlib.Path) -> dict[str, object]:
    changes, promotions, evidence, metadata, _, _, _ = _deployment(root)
    attempt = promotions.require(evidence.attempt_id)
    observations = ObservationController(changes, promotions, metadata)
    observations.record_failure(
        attempt,
        attribution=FailureAttribution.UNKNOWN,
        reason_code="unknown_runtime_signal",
        evidence=("runtime:unknown",),
        now_epoch=3.0,
    )
    disposition = observations.assess(attempt).disposition
    if disposition is not ObservationDisposition.BLOCKED_UNKNOWN:
        raise Phase7EvaluationError("unknown production failure did not block close")
    return {"disposition": disposition.value}


def _case_deployment_resume(root: pathlib.Path) -> dict[str, object]:
    changes, promotions, evidence, attempt = _merged_fixture(root)
    metadata = DeploymentMetadataStore(root / "deployment")
    runtime = _Runtime()
    coordinator = DeploymentCoordinator(
        changes,
        promotions,
        stager=_Stager(root / "releases"),
        metadata=metadata,
        runtime=runtime,
    )
    coordinator.bootstrap_lkg(
        release_sha=BASE,
        config_digest=CONFIG,
        verified=True,
        now_epoch=1.0,
    )
    try:
        coordinator.deploy(
            evidence=evidence,
            attempt=attempt,
            now_epoch=2.0,
        )
    except Exception as exc:
        raise Phase7EvaluationError("initial deployment fixture failed") from exc
    observing = promotions.require(attempt.attempt_id)
    resumed = coordinator.resume(observing)
    if metadata.recovery().phase is not RecoveryPhase.NEW_RUNTIME_VERIFIED:
        raise Phase7EvaluationError("verified deployment recovery marker changed")
    return {
        "deployment_id": resumed.deployment_id,
        "state": observing.state.value,
    }


def run_replay_suite(root: pathlib.Path) -> Phase7ReplayReport:
    root = pathlib.Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    cases = (
        _case("01_exact_candidate_attempt", lambda: _case_exact_candidate(root / "01")),
        _case("02_stale_candidate_fails_closed", lambda: _case_stale_candidate(root / "02")),
        _case("03_moved_pr_head_rejected", lambda: _case_moved_head(root / "03")),
        _case("04_wrong_ci_app_rejected", lambda: _case_wrong_ci_app(root / "04")),
        _case("05_skipped_windows_rejected", lambda: _case_skipped_windows(root / "05")),
        _case("06_exact_authorized_merge", lambda: _case_exact_merge(root / "06")),
        _case("07_external_merge_reconciled", lambda: _case_merge_reconcile(root / "07")),
        _case("08_full_success_closes", lambda: _case_full_success(root / "08")),
        _case(
            "09_external_failure_does_not_rollback",
            lambda: _case_external_failure_no_rollback(root / "09"),
        ),
        _case(
            "10_candidate_failure_rolls_back_lkg",
            lambda: _case_candidate_rollback(root / "10"),
        ),
        _case(
            "11_high_risk_compatibility_blocked",
            lambda: _case_high_risk_compatibility(root / "11"),
        ),
        _case(
            "12_control_surfaces_protected",
            lambda: _case_protected_surfaces(root / "12"),
        ),
        _case(
            "13_unknown_failure_blocks_close",
            lambda: _case_unknown_observation_blocks(root / "13"),
        ),
        _case(
            "14_deployment_resume_idempotent",
            lambda: _case_deployment_resume(root / "14"),
        ),
    )
    payload = {
        "cases": [item.to_payload() for item in cases],
    }
    suite_digest = canonical_digest(payload)
    return Phase7ReplayReport(
        status="PASS" if all(item.passed for item in cases) else "FAIL",
        cases=cases,
        suite_digest=suite_digest,
    )
