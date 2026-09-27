"""Canonical Phase-7 candidate verification before external promotion work."""

from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.engineering_change.models import ChangeArtifact, ChangeConflict, ChangeState
from jarvis.engineering_change.store import ChangeStore

from .models import PromotionAttemptState
from .store import PromotionStore

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class PromotionCandidateError(ChangeConflict):
    def __init__(self, reason_code: str, message: str) -> None:
        code = str(reason_code).strip().casefold()
        text = str(message).strip()
        if not code or not text:
            raise ValueError("candidate failure requires reason code and message")
        super().__init__(text)
        self.reason_code = code


class StalePromotionCandidate(PromotionCandidateError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedPromotionCandidate:
    change_id: str
    acceptance_artifact_id: str
    acceptance_artifact_digest: str
    candidate_artifact_id: str
    candidate_artifact_digest: str
    candidate_id: str
    candidate_digest: str
    base_sha: str
    head_sha: str
    diff_digest: str
    changed_paths: tuple[str, ...]
    protected_policy_id: str
    protected_policy_version: int
    protected_verdict: str


class PromotionCandidateVerifier:
    """Fail closed unless canonical Phase-6 candidate evidence is current and exact."""

    def __init__(self, changes: ChangeStore, promotions: PromotionStore) -> None:
        if not isinstance(changes, ChangeStore):
            raise TypeError("changes must be ChangeStore")
        if not isinstance(promotions, PromotionStore):
            raise TypeError("promotions must be PromotionStore")
        if promotions.changes is not changes:
            raise ValueError("promotion store must share the canonical ChangeStore")
        self._changes = changes
        self._promotions = promotions

    @staticmethod
    def _sha(value: object, *, field: str) -> str:
        text = str(value or "").strip().casefold()
        if _GIT_SHA.fullmatch(text) is None:
            raise PromotionCandidateError(
                "invalid_git_identity",
                f"{field} must be an exact 40-character Git SHA",
            )
        return text

    @staticmethod
    def _digest(value: object, *, field: str) -> str:
        text = str(value or "").strip().casefold()
        if _HEX_64.fullmatch(text) is None:
            raise PromotionCandidateError(
                "invalid_digest",
                f"{field} must be a SHA-256 digest",
            )
        return text

    @staticmethod
    def _candidate_from_artifact(
        artifact: ChangeArtifact,
        acceptance: ChangeArtifact,
    ) -> VerifiedPromotionCandidate:
        payload = artifact.payload
        if acceptance.payload.get("candidate_artifact_id") != artifact.artifact_id:
            raise PromotionCandidateError(
                "acceptance_candidate_mismatch",
                "acceptance does not bind the current candidate artifact",
            )
        if (
            acceptance.payload.get("candidate_artifact_digest") != artifact.digest
        ):
            raise PromotionCandidateError(
                "acceptance_candidate_mismatch",
                "acceptance does not bind the current candidate artifact digest",
            )
        protected = payload.get("protected_surface")
        if not isinstance(protected, dict):
            raise PromotionCandidateError(
                "protected_surface_missing",
                "candidate has no protected-surface evidence",
            )
        verdict = str(protected.get("verdict") or "").strip().casefold()
        if verdict != "clear":
            raise PromotionCandidateError(
                "protected_surface_not_clear",
                "candidate is not eligible for ordinary promotion",
            )
        policy_id = str(protected.get("policy_id") or "").strip()
        policy_version = protected.get("policy_version")
        if not policy_id or type(policy_version) is not int or policy_version < 1:
            raise PromotionCandidateError(
                "protected_surface_malformed",
                "candidate protected-surface policy identity is malformed",
            )
        candidate_id = str(payload.get("candidate_id") or "").strip()
        if not candidate_id:
            raise PromotionCandidateError(
                "candidate_id_missing",
                "candidate id is missing",
            )
        candidate_digest = PromotionCandidateVerifier._digest(
            payload.get("digest"),
            field="candidate digest",
        )
        base_sha = PromotionCandidateVerifier._sha(
            payload.get("source_revision"),
            field="candidate source revision",
        )
        head_sha = PromotionCandidateVerifier._sha(
            payload.get("commit"),
            field="candidate commit",
        )
        diff_digest = PromotionCandidateVerifier._digest(
            payload.get("diff_digest"),
            field="candidate diff digest",
        )
        raw_paths = payload.get("changed_paths")
        if not isinstance(raw_paths, list) or not raw_paths:
            raise PromotionCandidateError(
                "changed_paths_missing",
                "candidate has no changed paths",
            )
        changed_paths = tuple(
            sorted(dict.fromkeys(str(item).strip() for item in raw_paths))
        )
        if any(not item for item in changed_paths):
            raise PromotionCandidateError(
                "changed_paths_malformed",
                "candidate changed paths are malformed",
            )
        return VerifiedPromotionCandidate(
            change_id=artifact.change_id,
            acceptance_artifact_id=acceptance.artifact_id,
            acceptance_artifact_digest=acceptance.digest,
            candidate_artifact_id=artifact.artifact_id,
            candidate_artifact_digest=artifact.digest,
            candidate_id=candidate_id,
            candidate_digest=candidate_digest,
            base_sha=base_sha,
            head_sha=head_sha,
            diff_digest=diff_digest,
            changed_paths=changed_paths,
            protected_policy_id=policy_id,
            protected_policy_version=policy_version,
            protected_verdict=verdict,
        )

    def verify_and_create_attempt(
        self,
        change_id: str,
        *,
        current_main_sha: str,
    ):
        current_main = self._sha(current_main_sha, field="current main SHA")
        change = self._changes.require(change_id)
        if change.state not in {
            ChangeState.READY_FOR_PROMOTION,
            ChangeState.WAITING_PROMOTION_APPROVAL,
        }:
            raise PromotionCandidateError(
                "change_not_ready",
                "EngineeringChange is not ready for promotion",
            )
        acceptance = self._changes.latest_artifact(change_id, "acceptance")
        candidate = self._changes.latest_artifact(
            change_id,
            "source_repair_candidate",
        )
        if acceptance is None or candidate is None:
            raise PromotionCandidateError(
                "candidate_evidence_missing",
                "promotion requires canonical acceptance and source-repair candidate evidence",
            )
        verified = self._candidate_from_artifact(candidate, acceptance)
        attempt = self._promotions.create_or_get(
            change_id=change_id,
            candidate_artifact_id=verified.candidate_artifact_id,
            candidate_artifact_digest=verified.candidate_artifact_digest,
            candidate_id=verified.candidate_id,
            candidate_digest=verified.candidate_digest,
            base_sha=verified.base_sha,
            head_sha=verified.head_sha,
        )
        if verified.base_sha != current_main:
            if attempt.state.value == "created":
                attempt = self._promotions.transition(
                    attempt.attempt_id,
                    state=PromotionAttemptState.STALE,
                    expected_version=attempt.version,
                    reason=(
                        "candidate base does not equal current protected main; "
                        "integration and reverification required"
                    ),
                )
            raise StalePromotionCandidate(
                "stale_candidate_base",
                "candidate base no longer equals protected main",
            )
        return verified, attempt
