"""Build and persist exact owner-reviewable Phase-7 promotion evidence."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.engineering_change.models import ChangeArtifact, ChangeConflict
from jarvis.engineering_change.store import ChangeStore

from .candidate import VerifiedPromotionCandidate
from .github import VerifiedGitHubEvidence
from .models import (
    CompatibilityEvidence,
    PromotionAttempt,
    PromotionAttemptState,
    PromotionEvidenceV1,
)
from .store import PromotionStore


@dataclass(frozen=True, slots=True)
class PreparedPromotionEvidence:
    evidence: PromotionEvidenceV1
    artifact: ChangeArtifact
    attempt: PromotionAttempt


class PromotionEvidenceBuilder:
    def __init__(self, changes: ChangeStore, promotions: PromotionStore) -> None:
        if promotions.changes is not changes:
            raise ValueError("promotion store must share the canonical ChangeStore")
        self._changes = changes
        self._promotions = promotions

    def prepare(
        self,
        candidate: VerifiedPromotionCandidate,
        attempt: PromotionAttempt,
        github: VerifiedGitHubEvidence,
        *,
        compatibility: CompatibilityEvidence,
        config_digest: str,
        deployment_environment: str,
        lkg_release_sha: str,
        now_epoch: float | None = None,
    ) -> PreparedPromotionEvidence:
        if attempt.change_id != candidate.change_id:
            raise ChangeConflict("promotion attempt belongs to a different change")
        if (
            attempt.candidate_artifact_id != candidate.candidate_artifact_id
            or attempt.candidate_artifact_digest != candidate.candidate_artifact_digest
            or attempt.candidate_digest != candidate.candidate_digest
            or attempt.base_sha != candidate.base_sha
            or attempt.head_sha != candidate.head_sha
        ):
            raise ChangeConflict(
                "promotion attempt no longer matches candidate evidence"
            )
        if attempt.state not in {
            PromotionAttemptState.CREATED,
            PromotionAttemptState.EVIDENCE_READY,
        }:
            raise ChangeConflict("promotion attempt is not eligible for evidence")
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
            pr_number=github.pr_number,
            pr_base_sha=github.pr_base_sha,
            pr_head_sha=github.pr_head_sha,
            tested_merge_sha=github.tested_merge_sha,
            ci_run_id=github.ci_run_id,
            required_checks=github.required_checks,
            windows_verified=github.windows_verified,
            compatibility=compatibility,
            config_digest=config_digest,
            merge_method="squash",
            deployment_environment=deployment_environment,
            lkg_release_sha=lkg_release_sha,
            now_epoch=now_epoch,
        )
        payload = {
            "evidence_id": evidence.evidence_id,
            **evidence.canonical_payload(),
            "digest": evidence.digest,
        }
        latest = self._changes.latest_artifact(candidate.change_id, "promotion")
        if latest is not None and latest.payload == payload:
            artifact = latest
        elif attempt.state is PromotionAttemptState.EVIDENCE_READY:
            raise ChangeConflict(
                "existing promotion evidence differs from current inputs"
            )
        else:
            artifact = self._changes.add_artifact(
                candidate.change_id,
                kind="promotion",
                payload=payload,
            )
        if attempt.state is PromotionAttemptState.CREATED:
            attempt = self._promotions.transition(
                attempt.attempt_id,
                PromotionAttemptState.EVIDENCE_READY,
                expected_version=attempt.version,
                pr_number=github.pr_number,
                promotion_artifact_id=artifact.artifact_id,
                promotion_artifact_digest=artifact.digest,
            )
        elif (
            attempt.promotion_artifact_id != artifact.artifact_id
            or attempt.promotion_artifact_digest != artifact.digest
        ):
            raise ChangeConflict("promotion attempt points to different evidence")
        return PreparedPromotionEvidence(
            evidence=evidence,
            artifact=artifact,
            attempt=attempt,
        )
