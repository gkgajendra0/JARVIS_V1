from __future__ import annotations

from types import SimpleNamespace

from jarvis.authority.approval import ApprovalService
from jarvis.authority.types import AuthorityEffect
from jarvis.authority.verifier import (
    StrongVerificationResult,
    StrongVerificationStatus,
)
from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.promotion.authority import PromotionAuthorityBridge
from jarvis.promotion.github import (
    GitHubPromotionPolicy,
    GitHubPullRequestSnapshot,
    GitHubWorkflowSnapshot,
)
from jarvis.promotion.merge import PromotionMerger
from jarvis.promotion.models import (
    CheckEvidence,
    CompatibilityEvidence,
    CompatibilityVerdict,
    PromotionAttemptState,
    PromotionEvidenceV1,
)
from jarvis.promotion.store import PromotionStore
from jarvis.work.store import SQLiteWorkStore

BASE = "1" * 40
HEAD = "2" * 40
TESTED_MERGE = "3" * 40
MERGE = "4" * 40
LKG = "5" * 40
DIGEST = "a" * 64
DIFF = "b" * 64
CONFIG = "c" * 64


class FakeVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, *, proposal, session_id):
        self.calls += 1
        return StrongVerificationResult(
            status=StrongVerificationStatus.VERIFIED,
            verifier_id="fake-windows-hello",
            verification_id=f"verification-{self.calls}",
            proposal_fingerprint=proposal.fingerprint,
            session_id=session_id,
        )


class FakeAuthority:
    def __init__(self) -> None:
        self.consumed = 0

    def evaluate(self, *, proposal, context, approval_id=None):
        del proposal, context, approval_id
        return SimpleNamespace(
            effect=AuthorityEffect.ALLOW,
            execution_permit=SimpleNamespace(permit_id="permit-1"),
            reason_codes=(),
        )

    def revalidate_and_consume(self, *, permit_id, proposal, context):
        del permit_id, proposal, context
        self.consumed += 1


class FakeGitHub:
    def __init__(self) -> None:
        self.main = BASE
        self.merged = False
        self.pr = GitHubPullRequestSnapshot(12, BASE, HEAD, False, "open")
        checks = (
            CheckEvidence("ruff", "success", 15368),
            CheckEvidence("pytest", "success", 15368),
            CheckEvidence("windows-hello-helper", "success", 15368),
            CheckEvidence("windows-dpapi", "success", 15368),
            CheckEvidence("promotion-policy", "success", 15368),
        )
        self.workflow = GitHubWorkflowSnapshot(
            run_id="run-12",
            event="pull_request",
            head_sha=HEAD,
            tested_merge_sha=TESTED_MERGE,
            status="completed",
            conclusion="success",
            checks=checks,
        )

    def read_protected_main_sha(self):
        return self.main

    def read_pull_request(self, number):
        assert number == 12
        return self.pr

    def read_workflow(self, number):
        assert number == 12
        return self.workflow

    def squash_merge(self, number, *, expected_head_sha):
        assert number == 12
        assert expected_head_sha == HEAD
        self.main = MERGE
        self.merged = True
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


def _fixture(tmp_path):
    changes = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    change = changes.create(
        request="Repair runtime",
        process_key="engineering.change",
        process_version=1,
        source_session_id="session",
        source_turn_id="turn-1",
    )
    with changes.work._lock, changes.work._connect() as db:
        db.execute(
            "UPDATE engineering_changes SET state=? WHERE change_id=?",
            (ChangeState.READY_FOR_PROMOTION.value, change.change_id),
        )
    candidate = changes.add_artifact(
        change.change_id,
        kind="source_repair_candidate",
        payload={"candidate_id": "candidate-1"},
    )
    promotions = PromotionStore(changes)
    attempt = promotions.create_or_get(
        change_id=change.change_id,
        candidate_artifact_id=candidate.artifact_id,
        candidate_artifact_digest=candidate.digest,
        candidate_id="candidate-1",
        candidate_digest=DIGEST,
        base_sha=BASE,
        head_sha=HEAD,
    )
    checks = (
        CheckEvidence("ruff", "success", 15368),
        CheckEvidence("pytest", "success", 15368),
        CheckEvidence("windows-hello-helper", "success", 15368),
        CheckEvidence("windows-dpapi", "success", 15368),
        CheckEvidence("promotion-policy", "success", 15368),
    )
    evidence = PromotionEvidenceV1.create(
        change_id=change.change_id,
        attempt_id=attempt.attempt_id,
        candidate_artifact_id=candidate.artifact_id,
        candidate_artifact_digest=candidate.digest,
        candidate_id="candidate-1",
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
        tested_merge_sha=TESTED_MERGE,
        ci_run_id="run-12",
        required_checks=checks,
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
    artifact = changes.add_artifact(
        change.change_id,
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
        pr_number=12,
        promotion_artifact_id=artifact.artifact_id,
        promotion_artifact_digest=artifact.digest,
    )
    gate = GateService(changes, verify_owner=lambda *_: False).present(
        change.change_id,
        GateKind.PROMOTION,
        artifact.artifact_id,
    )
    return changes, promotions, attempt, evidence, gate


def test_one_strong_verification_binds_gate_and_authority_permit(tmp_path) -> None:
    changes, promotions, attempt, evidence, gate = _fixture(tmp_path)
    verifier = FakeVerifier()
    authority = FakeAuthority()
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
        session_id="session",
        source_turn_id="turn-2",
        request_key="phase7:turn-2",
        repository_full_name="gkgajendra0/JARVIS_V1",
    )

    assert verifier.calls == 1
    assert authorized.gate_decision.approved is True
    assert promotions.require(attempt.attempt_id).state is PromotionAttemptState.AUTHORIZED
    assert changes.require(evidence.change_id).state is ChangeState.WAITING_PROMOTION_APPROVAL


def test_authorized_merge_rechecks_external_state_and_promotes_change(tmp_path) -> None:
    changes, promotions, attempt, evidence, gate = _fixture(tmp_path)
    verifier = FakeVerifier()
    authority = FakeAuthority()
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
        session_id="session",
        source_turn_id="turn-2",
        request_key="phase7:turn-2",
        repository_full_name="gkgajendra0/JARVIS_V1",
    )
    attempt = promotions.require(attempt.attempt_id)
    github = FakeGitHub()
    merger = PromotionMerger(
        changes,
        promotions,
        github=github,
        policy=GitHubPromotionPolicy(),
        authority=bridge,
    )

    result = merger.execute(
        evidence=evidence,
        attempt=attempt,
        authorized=authorized,
    )

    assert result.merge_sha == MERGE
    assert result.reconciled_after_external_merge is False
    assert authority.consumed == 1
    assert promotions.require(attempt.attempt_id).state is PromotionAttemptState.MERGED
    assert changes.require(evidence.change_id).state is ChangeState.PROMOTED
