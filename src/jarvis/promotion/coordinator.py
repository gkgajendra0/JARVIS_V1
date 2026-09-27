"""Manager-facing Phase-7 coordinator from verified candidate to promotion review."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.engineering_change.gates import GateChallenge, GateKind, GateService
from jarvis.engineering_change.models import ChangeArtifact, ChangeConflict
from jarvis.engineering_change.store import ChangeStore
from jarvis.work.development import DevelopmentWorkspaceManager
from jarvis.work.models import WorkDeliveryKind

from .candidate import PromotionCandidateVerifier, VerifiedPromotionCandidate
from .compatibility import assess_ordinary_compatibility
from .evidence import PromotionEvidenceBuilder
from .github import (
    GitHubPromotionAdapter,
    GitHubPromotionPolicy,
    VerifiedGitHubEvidence,
)
from .models import PromotionAttempt, PromotionAttemptState, PromotionEvidenceV1
from .release import DeploymentMetadataStore
from .store import PromotionStore


class PromotionPreparationError(ChangeConflict):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = str(reason_code).strip().casefold()
        text = str(message).strip()
        if not self.reason_code or not text:
            raise ValueError("promotion preparation failure requires code and message")
        super().__init__(text)


@dataclass(frozen=True, slots=True)
class PreparedPromotionReview:
    candidate: VerifiedPromotionCandidate
    attempt: PromotionAttempt
    evidence: PromotionEvidenceV1
    artifact: ChangeArtifact
    gate: GateChallenge


class PromotionCoordinator:
    """Reconcile local candidate, GitHub PR/CI, LKG and exact owner review evidence."""

    def __init__(
        self,
        changes: ChangeStore,
        promotions: PromotionStore,
        *,
        github: GitHubPromotionAdapter,
        workspace_manager: DevelopmentWorkspaceManager,
        deployment_metadata: DeploymentMetadataStore,
        policy: GitHubPromotionPolicy | None = None,
    ) -> None:
        if promotions.changes is not changes:
            raise ValueError("promotion store must share the canonical ChangeStore")
        self._changes = changes
        self._promotions = promotions
        self._github = github
        self._workspace = workspace_manager
        self._metadata = deployment_metadata
        self._policy = policy or GitHubPromotionPolicy()
        self._candidate = PromotionCandidateVerifier(changes, promotions)
        self._evidence = PromotionEvidenceBuilder(changes, promotions)

    def _external_evidence(
        self,
        candidate: VerifiedPromotionCandidate,
        *,
        title: str,
        body: str,
    ) -> VerifiedGitHubEvidence:
        workspace = self._workspace.workspace_for(candidate.development_work_id)
        if not workspace.path.is_dir():
            raise PromotionPreparationError(
                "candidate_workspace_missing",
                "verified candidate development workspace is unavailable",
            )
        self._github.publish_candidate(candidate, workspace_root=workspace.path)
        pr = self._github.ensure_pull_request(candidate, title=title, body=body)
        workflow = self._github.read_workflow(pr.number)
        current_main = self._github.read_protected_main_sha()
        return self._policy.verify(
            candidate,
            current_main_sha=current_main,
            pr=pr,
            workflow=workflow,
        )

    @staticmethod
    def _same_github_evidence(
        persisted: PromotionEvidenceV1,
        current: VerifiedGitHubEvidence,
    ) -> bool:
        return (
            persisted.pr_number == current.pr_number
            and persisted.pr_base_sha == current.pr_base_sha
            and persisted.pr_head_sha == current.pr_head_sha
            and persisted.tested_merge_sha == current.tested_merge_sha
            and persisted.ci_run_id == current.ci_run_id
            and persisted.required_checks == current.required_checks
            and persisted.windows_verified == current.windows_verified
        )

    def prepare_review(
        self,
        change_id: str,
        *,
        config_digest: str,
        deployment_environment: str,
        title: str,
        body: str,
    ) -> PreparedPromotionReview:
        current_main = self._github.read_protected_main_sha()
        candidate, attempt = self._candidate.verify_and_create_attempt(
            change_id,
            current_main_sha=current_main,
        )
        compatibility = assess_ordinary_compatibility(candidate.changed_paths)
        if not compatibility.evidence.ordinary_path_safe:
            if attempt.state is PromotionAttemptState.CREATED:
                attempt = self._promotions.transition(
                    attempt.attempt_id,
                    PromotionAttemptState.BLOCKED,
                    expected_version=attempt.version,
                    reason=";".join(compatibility.reason_codes),
                )
            raise PromotionPreparationError(
                "compatibility_review_required",
                "candidate changes require an explicit compatibility/deployment plan",
            )

        github = self._external_evidence(candidate, title=title, body=body)
        lkg = self._metadata.lkg()
        if lkg is None:
            raise PromotionPreparationError(
                "lkg_missing",
                "promotion requires a verified Last Known Good release identity",
            )

        if attempt.state is PromotionAttemptState.EVIDENCE_READY:
            if (
                attempt.promotion_artifact_id is None
                or attempt.promotion_artifact_digest is None
            ):
                raise PromotionPreparationError(
                    "promotion_artifact_missing",
                    "evidence-ready attempt lost its promotion artifact identity",
                )
            artifact = self._changes.get_artifact(attempt.promotion_artifact_id)
            if (
                artifact is None
                or artifact.digest != attempt.promotion_artifact_digest
                or artifact.kind != "promotion"
            ):
                raise PromotionPreparationError(
                    "promotion_artifact_mismatch",
                    "persisted promotion artifact no longer matches attempt",
                )
            evidence = PromotionEvidenceV1.from_payload(artifact.payload)
            if not self._same_github_evidence(evidence, github):
                raise PromotionPreparationError(
                    "promotion_evidence_stale",
                    "current GitHub evidence differs from owner-review evidence",
                )
            if (
                evidence.config_digest != config_digest
                or evidence.deployment_environment != deployment_environment
                or evidence.lkg_release_sha != lkg.release_sha
            ):
                raise PromotionPreparationError(
                    "promotion_environment_changed",
                    "deployment/LKG identity changed after promotion evidence creation",
                )
        elif attempt.state is PromotionAttemptState.CREATED:
            prepared = self._evidence.prepare(
                candidate,
                attempt,
                github,
                compatibility=compatibility.evidence,
                config_digest=config_digest,
                deployment_environment=deployment_environment,
                lkg_release_sha=lkg.release_sha,
            )
            evidence = prepared.evidence
            artifact = prepared.artifact
            attempt = prepared.attempt
        else:
            raise PromotionPreparationError(
                "promotion_attempt_not_reviewable",
                "promotion attempt is not eligible for owner review",
            )

        gate = GateService(self._changes, verify_owner=lambda *_: False).present(
            change_id,
            GateKind.PROMOTION,
            artifact.artifact_id,
        )
        work = self._changes.work.require(candidate.development_work_id)
        self._changes.work.enqueue_delivery(
            work=work,
            kind=WorkDeliveryKind.OWNER_INPUT,
            message=(
                f"Review EngineeringChange {change_id} promotion evidence: "
                f"PR #{evidence.pr_number}, candidate {evidence.candidate_head_sha}, "
                f"tested merge {evidence.tested_merge_sha}, "
                f"evidence SHA-256 {evidence.digest}, LKG {evidence.lkg_release_sha}. "
                f"Approval authorizes only this exact evidence through the governed "
                f"Phase-7 promotion/Authority path. Say 'approve promotion' if this "
                f"is the only pending promotion, or 'approve {gate.gate_id}'."
            ),
            event_key=f"phase7:{attempt.attempt_id}:{artifact.digest}",
        )
        return PreparedPromotionReview(
            candidate=candidate,
            attempt=attempt,
            evidence=evidence,
            artifact=artifact,
            gate=gate,
        )
