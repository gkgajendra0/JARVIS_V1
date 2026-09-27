"""Exact-head protected-main merge with restart-safe external reconciliation."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.engineering_change.models import ChangeConflict, ChangeState
from jarvis.engineering_change.store import ChangeStore

from .authority import AuthorizedPromotion, PromotionAuthorityBridge
from .candidate import VerifiedPromotionCandidate
from .github import GitHubPromotionAdapter, GitHubPromotionPolicy
from .models import PromotionAttempt, PromotionAttemptState, PromotionEvidenceV1
from .store import PromotionStore


class PromotionMergeError(ChangeConflict):
    pass


@dataclass(frozen=True, slots=True)
class MergeResult:
    merge_sha: str
    reconciled_after_external_merge: bool


class PromotionMerger:
    def __init__(
        self,
        changes: ChangeStore,
        promotions: PromotionStore,
        *,
        github: GitHubPromotionAdapter,
        policy: GitHubPromotionPolicy,
        authority: PromotionAuthorityBridge,
    ) -> None:
        if promotions.changes is not changes:
            raise ValueError("promotion store must share the canonical ChangeStore")
        self._changes = changes
        self._promotions = promotions
        self._github = github
        self._policy = policy
        self._authority = authority

    @staticmethod
    def _candidate(evidence: PromotionEvidenceV1) -> VerifiedPromotionCandidate:
        return VerifiedPromotionCandidate(
            change_id=evidence.change_id,
            acceptance_artifact_id="promotion_evidence",
            acceptance_artifact_digest=evidence.candidate_artifact_digest,
            candidate_artifact_id=evidence.candidate_artifact_id,
            candidate_artifact_digest=evidence.candidate_artifact_digest,
            candidate_id=evidence.candidate_id,
            candidate_digest=evidence.candidate_digest,
            development_work_id="promotion_evidence",
            branch="promotion/evidence",
            base_sha=evidence.candidate_base_sha,
            head_sha=evidence.candidate_head_sha,
            diff_digest=evidence.candidate_diff_digest,
            changed_paths=evidence.changed_paths,
            protected_policy_id=evidence.protected_policy_id,
            protected_policy_version=evidence.protected_policy_version,
            protected_verdict=evidence.protected_verdict,
        )

    @staticmethod
    def _assert_same_ci(
        evidence: PromotionEvidenceV1,
        *,
        pr_number: int,
        pr_base_sha: str,
        pr_head_sha: str,
        tested_merge_sha: str,
        ci_run_id: str,
        required_checks,
    ) -> None:
        observed = (
            pr_number,
            pr_base_sha,
            pr_head_sha,
            tested_merge_sha,
            ci_run_id,
            tuple(required_checks),
        )
        expected = (
            evidence.pr_number,
            evidence.pr_base_sha,
            evidence.pr_head_sha,
            evidence.tested_merge_sha,
            evidence.ci_run_id,
            evidence.required_checks,
        )
        if observed != expected:
            raise PromotionMergeError(
                "external PR/CI state differs from approved promotion evidence"
            )

    def _mark_merged(
        self,
        attempt: PromotionAttempt,
        *,
        merge_sha: str,
    ) -> PromotionAttempt:
        if attempt.state is PromotionAttemptState.MERGED:
            if attempt.merge_sha != merge_sha:
                raise PromotionMergeError("stored merge SHA conflicts with GitHub")
            return attempt
        updated = self._promotions.transition(
            attempt.attempt_id,
            PromotionAttemptState.MERGED,
            expected_version=attempt.version,
            merge_sha=merge_sha,
        )
        change = self._changes.require(attempt.change_id)
        if change.state is ChangeState.WAITING_PROMOTION_APPROVAL:
            if (
                attempt.promotion_artifact_id is None
                or attempt.promotion_artifact_digest is None
            ):
                raise PromotionMergeError(
                    "promotion attempt has no exact approved promotion artifact"
                )
            self._changes.mark_promoted(
                change.change_id,
                artifact_id=attempt.promotion_artifact_id,
                artifact_digest=attempt.promotion_artifact_digest,
                expected_version=change.version,
            )
        elif change.state is not ChangeState.PROMOTED:
            raise PromotionMergeError("EngineeringChange is not in a promotable state")
        return updated

    def execute(
        self,
        *,
        evidence: PromotionEvidenceV1,
        attempt: PromotionAttempt,
        authorized: AuthorizedPromotion,
    ) -> MergeResult:
        if authorized.attempt_id != attempt.attempt_id:
            raise PromotionMergeError("authorization belongs to another attempt")
        if authorized.evidence_digest != evidence.digest:
            raise PromotionMergeError("authorization evidence digest mismatch")
        if attempt.state is PromotionAttemptState.MERGED:
            if attempt.merge_sha is None:
                raise PromotionMergeError("merged attempt has no merge SHA")
            if self._github.read_protected_main_sha() != attempt.merge_sha:
                raise PromotionMergeError(
                    "protected main no longer equals stored merge"
                )
            return MergeResult(attempt.merge_sha, True)
        if attempt.state is not PromotionAttemptState.AUTHORIZED:
            raise PromotionMergeError("promotion attempt is not authorized")

        current_main = self._github.read_protected_main_sha()
        pr = self._github.read_pull_request(evidence.pr_number)

        # Crash reconciliation: the exact approved PR may already have merged after
        # Authority was issued but before local durable state was updated.
        if current_main != evidence.candidate_base_sha:
            if (
                pr.merged
                and pr.merge_sha is not None
                and pr.merge_sha == current_main
                and pr.head_sha == evidence.candidate_head_sha
                and pr.base_sha == evidence.candidate_base_sha
            ):
                self._mark_merged(attempt, merge_sha=current_main)
                return MergeResult(current_main, True)
            raise PromotionMergeError(
                "protected main changed before exact authorized merge"
            )

        workflow = self._github.read_workflow(evidence.pr_number)
        verified = self._policy.verify(
            self._candidate(evidence),
            current_main_sha=current_main,
            pr=pr,
            workflow=workflow,
        )
        self._assert_same_ci(
            evidence,
            pr_number=verified.pr_number,
            pr_base_sha=verified.pr_base_sha,
            pr_head_sha=verified.pr_head_sha,
            tested_merge_sha=verified.tested_merge_sha,
            ci_run_id=verified.ci_run_id,
            required_checks=verified.required_checks,
        )

        # Permit is one-shot and consumed only after the final external re-read.
        self._authority.consume(authorized)
        merge_sha = self._github.squash_merge(
            evidence.pr_number,
            expected_head_sha=evidence.candidate_head_sha,
        )
        if self._github.read_protected_main_sha() != merge_sha:
            raise PromotionMergeError(
                "GitHub merge returned but protected main identity did not match"
            )
        self._mark_merged(attempt, merge_sha=merge_sha)
        return MergeResult(merge_sha, False)
