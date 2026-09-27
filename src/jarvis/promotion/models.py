"""Typed contracts for governed Phase-7 promotion and deployment evidence."""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from enum import Enum

from jarvis.engineering_substrate.canonical import canonical_digest

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def _token(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    return text


def _digest(value: object, *, field: str) -> str:
    text = _token(value, field=field).casefold()
    if _HEX_64.fullmatch(text) is None:
        raise ValueError(f"{field} must be a SHA-256 digest")
    return text


def _sha(value: object, *, field: str) -> str:
    text = _token(value, field=field).casefold()
    if _GIT_SHA.fullmatch(text) is None:
        raise ValueError(f"{field} must be an exact 40-character Git SHA")
    return text


class PromotionAttemptState(str, Enum):
    """Operational progress for one candidate; EngineeringChange remains lifecycle truth."""

    CREATED = "created"
    EVIDENCE_READY = "evidence_ready"
    AUTHORIZED = "authorized"
    MERGED = "merged"
    DEPLOYING = "deploying"
    OBSERVING = "observing"
    COMPLETED = "completed"
    STALE = "stale"
    BLOCKED = "blocked"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class PromotionAttempt:
    attempt_id: str
    change_id: str
    candidate_artifact_id: str
    candidate_artifact_digest: str
    candidate_id: str
    candidate_digest: str
    base_sha: str
    head_sha: str
    state: PromotionAttemptState
    pr_number: int | None
    promotion_artifact_id: str | None
    promotion_artifact_digest: str | None
    merge_sha: str | None
    deployment_id: str | None
    lkg_sha: str | None
    last_reason: str | None
    version: int
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if not self.attempt_id.startswith("promotion_"):
            raise ValueError("attempt_id must use promotion_ prefix")
        _token(self.change_id, field="change_id")
        _token(self.candidate_artifact_id, field="candidate_artifact_id")
        _digest(self.candidate_artifact_digest, field="candidate_artifact_digest")
        _token(self.candidate_id, field="candidate_id")
        _digest(self.candidate_digest, field="candidate_digest")
        _sha(self.base_sha, field="base_sha")
        _sha(self.head_sha, field="head_sha")
        if not isinstance(self.state, PromotionAttemptState):
            raise TypeError("state must be PromotionAttemptState")
        if self.pr_number is not None and (
            type(self.pr_number) is not int or self.pr_number <= 0
        ):
            raise ValueError("pr_number must be positive")
        if self.promotion_artifact_digest is not None:
            _digest(
                self.promotion_artifact_digest,
                field="promotion_artifact_digest",
            )
        if self.merge_sha is not None:
            _sha(self.merge_sha, field="merge_sha")
        if self.lkg_sha is not None:
            _sha(self.lkg_sha, field="lkg_sha")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be positive")


@dataclass(frozen=True, slots=True)
class CheckEvidence:
    context: str
    conclusion: str
    app_id: int | None = None

    def __post_init__(self) -> None:
        if _token(self.context, field="check context") != self.context:
            raise ValueError("check context must be normalized")
        conclusion = _token(self.conclusion, field="check conclusion").casefold()
        if conclusion != self.conclusion:
            raise ValueError("check conclusion must be lowercase")
        if self.app_id is not None and (
            type(self.app_id) is not int or self.app_id <= 0
        ):
            raise ValueError("check app_id must be positive")


class CompatibilityVerdict(str, Enum):
    SAFE = "safe"
    REVIEW_REQUIRED = "review_required"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True, slots=True)
class CompatibilityEvidence:
    schema: CompatibilityVerdict
    dbos: CompatibilityVerdict
    dependencies: CompatibilityVerdict

    @property
    def ordinary_path_safe(self) -> bool:
        return (
            self.schema is CompatibilityVerdict.SAFE
            and self.dbos is CompatibilityVerdict.SAFE
            and self.dependencies is CompatibilityVerdict.SAFE
        )


@dataclass(frozen=True, slots=True)
class PromotionEvidenceV1:
    """Immutable owner-review evidence for one exact protected-main promotion."""

    evidence_id: str
    change_id: str
    attempt_id: str
    candidate_artifact_id: str
    candidate_artifact_digest: str
    candidate_id: str
    candidate_digest: str
    candidate_base_sha: str
    candidate_head_sha: str
    candidate_diff_digest: str
    changed_paths: tuple[str, ...]
    protected_policy_id: str
    protected_policy_version: int
    protected_verdict: str
    pr_number: int
    pr_base_sha: str
    pr_head_sha: str
    tested_merge_sha: str
    ci_run_id: str
    required_checks: tuple[CheckEvidence, ...]
    windows_verified: bool
    compatibility: CompatibilityEvidence
    config_digest: str
    merge_method: str
    deployment_environment: str
    lkg_release_sha: str
    created_at_epoch: float
    digest: str

    @classmethod
    def create(
        cls,
        *,
        change_id: str,
        attempt_id: str,
        candidate_artifact_id: str,
        candidate_artifact_digest: str,
        candidate_id: str,
        candidate_digest: str,
        candidate_base_sha: str,
        candidate_head_sha: str,
        candidate_diff_digest: str,
        changed_paths: tuple[str, ...] | list[str],
        protected_policy_id: str,
        protected_policy_version: int,
        protected_verdict: str,
        pr_number: int,
        pr_base_sha: str,
        pr_head_sha: str,
        tested_merge_sha: str,
        ci_run_id: str,
        required_checks: tuple[CheckEvidence, ...] | list[CheckEvidence],
        windows_verified: bool,
        compatibility: CompatibilityEvidence,
        config_digest: str,
        merge_method: str,
        deployment_environment: str,
        lkg_release_sha: str,
        now_epoch: float | None = None,
    ) -> PromotionEvidenceV1:
        if protected_verdict != "clear":
            raise ValueError("promotion requires CLEAR protected-surface verdict")
        if type(protected_policy_version) is not int or protected_policy_version < 1:
            raise ValueError("protected_policy_version must be positive")
        if type(pr_number) is not int or pr_number <= 0:
            raise ValueError("pr_number must be positive")
        if windows_verified is not True:
            raise ValueError("promotion requires successful Windows verification")
        if not isinstance(compatibility, CompatibilityEvidence):
            raise TypeError("compatibility must be CompatibilityEvidence")
        if not compatibility.ordinary_path_safe:
            raise ValueError("ordinary promotion requires SAFE compatibility evidence")
        checks = tuple(required_checks)
        if not checks or any(not isinstance(item, CheckEvidence) for item in checks):
            raise ValueError("promotion requires typed CI checks")
        if any(item.conclusion != "success" for item in checks):
            raise ValueError("all required CI checks must have conclusion=success")
        contexts = tuple(item.context for item in checks)
        if len(set(contexts)) != len(contexts):
            raise ValueError("required CI check contexts must be unique")
        paths = tuple(
            sorted(dict.fromkeys(str(item).strip() for item in changed_paths))
        )
        if not paths or any(not item for item in paths):
            raise ValueError("promotion requires changed paths")
        created = time.time() if now_epoch is None else float(now_epoch)
        if not math.isfinite(created) or created <= 0:
            raise ValueError("created_at_epoch must be finite and positive")
        payload: dict[str, object] = {
            "schema_version": 1,
            "change_id": _token(change_id, field="change_id"),
            "attempt_id": _token(attempt_id, field="attempt_id"),
            "candidate_artifact_id": _token(
                candidate_artifact_id, field="candidate_artifact_id"
            ),
            "candidate_artifact_digest": _digest(
                candidate_artifact_digest,
                field="candidate_artifact_digest",
            ),
            "candidate_id": _token(candidate_id, field="candidate_id"),
            "candidate_digest": _digest(candidate_digest, field="candidate_digest"),
            "candidate_base_sha": _sha(candidate_base_sha, field="candidate_base_sha"),
            "candidate_head_sha": _sha(candidate_head_sha, field="candidate_head_sha"),
            "candidate_diff_digest": _digest(
                candidate_diff_digest, field="candidate_diff_digest"
            ),
            "changed_paths": list(paths),
            "protected_policy_id": _token(
                protected_policy_id, field="protected_policy_id"
            ),
            "protected_policy_version": protected_policy_version,
            "protected_verdict": protected_verdict,
            "pr_number": pr_number,
            "pr_base_sha": _sha(pr_base_sha, field="pr_base_sha"),
            "pr_head_sha": _sha(pr_head_sha, field="pr_head_sha"),
            "tested_merge_sha": _sha(tested_merge_sha, field="tested_merge_sha"),
            "ci_run_id": _token(ci_run_id, field="ci_run_id"),
            "required_checks": [
                {
                    "context": item.context,
                    "conclusion": item.conclusion,
                    "app_id": item.app_id,
                }
                for item in checks
            ],
            "windows_verified": True,
            "compatibility": {
                "schema": compatibility.schema.value,
                "dbos": compatibility.dbos.value,
                "dependencies": compatibility.dependencies.value,
            },
            "config_digest": _digest(config_digest, field="config_digest"),
            "merge_method": _token(merge_method, field="merge_method").casefold(),
            "deployment_environment": _token(
                deployment_environment,
                field="deployment_environment",
            ),
            "lkg_release_sha": _sha(lkg_release_sha, field="lkg_release_sha"),
            "created_at_epoch": created,
        }
        if payload["merge_method"] != "squash":
            raise ValueError("Phase-7 standard merge method must be squash")
        if payload["pr_head_sha"] != payload["candidate_head_sha"]:
            raise ValueError("PR head must equal candidate head")
        digest = canonical_digest(payload)
        return cls(
            evidence_id=f"promotion_evidence_{digest[:16]}",
            change_id=str(payload["change_id"]),
            attempt_id=str(payload["attempt_id"]),
            candidate_artifact_id=str(payload["candidate_artifact_id"]),
            candidate_artifact_digest=str(payload["candidate_artifact_digest"]),
            candidate_id=str(payload["candidate_id"]),
            candidate_digest=str(payload["candidate_digest"]),
            candidate_base_sha=str(payload["candidate_base_sha"]),
            candidate_head_sha=str(payload["candidate_head_sha"]),
            candidate_diff_digest=str(payload["candidate_diff_digest"]),
            changed_paths=paths,
            protected_policy_id=str(payload["protected_policy_id"]),
            protected_policy_version=protected_policy_version,
            protected_verdict=protected_verdict,
            pr_number=pr_number,
            pr_base_sha=str(payload["pr_base_sha"]),
            pr_head_sha=str(payload["pr_head_sha"]),
            tested_merge_sha=str(payload["tested_merge_sha"]),
            ci_run_id=str(payload["ci_run_id"]),
            required_checks=checks,
            windows_verified=True,
            compatibility=compatibility,
            config_digest=str(payload["config_digest"]),
            merge_method=str(payload["merge_method"]),
            deployment_environment=str(payload["deployment_environment"]),
            lkg_release_sha=str(payload["lkg_release_sha"]),
            created_at_epoch=created,
            digest=digest,
        )

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> PromotionEvidenceV1:
        """Reconstruct and re-verify one persisted immutable promotion artifact."""

        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("promotion evidence schema version is unsupported")
        raw_checks = payload.get("required_checks")
        raw_compatibility = payload.get("compatibility")
        if not isinstance(raw_checks, list) or not isinstance(
            raw_compatibility, dict
        ):
            raise ValueError("promotion evidence payload is malformed")
        try:
            checks = tuple(
                CheckEvidence(
                    context=str(item["context"]),
                    conclusion=str(item["conclusion"]),
                    app_id=(
                        item.get("app_id")
                        if isinstance(item.get("app_id"), int)
                        else None
                    ),
                )
                for item in raw_checks
                if isinstance(item, dict)
            )
            compatibility = CompatibilityEvidence(
                schema=CompatibilityVerdict(str(raw_compatibility["schema"])),
                dbos=CompatibilityVerdict(str(raw_compatibility["dbos"])),
                dependencies=CompatibilityVerdict(
                    str(raw_compatibility["dependencies"])
                ),
            )
            evidence = cls.create(
                change_id=str(payload["change_id"]),
                attempt_id=str(payload["attempt_id"]),
                candidate_artifact_id=str(payload["candidate_artifact_id"]),
                candidate_artifact_digest=str(
                    payload["candidate_artifact_digest"]
                ),
                candidate_id=str(payload["candidate_id"]),
                candidate_digest=str(payload["candidate_digest"]),
                candidate_base_sha=str(payload["candidate_base_sha"]),
                candidate_head_sha=str(payload["candidate_head_sha"]),
                candidate_diff_digest=str(payload["candidate_diff_digest"]),
                changed_paths=list(payload["changed_paths"]),
                protected_policy_id=str(payload["protected_policy_id"]),
                protected_policy_version=int(payload["protected_policy_version"]),
                protected_verdict=str(payload["protected_verdict"]),
                pr_number=int(payload["pr_number"]),
                pr_base_sha=str(payload["pr_base_sha"]),
                pr_head_sha=str(payload["pr_head_sha"]),
                tested_merge_sha=str(payload["tested_merge_sha"]),
                ci_run_id=str(payload["ci_run_id"]),
                required_checks=checks,
                windows_verified=payload["windows_verified"] is True,
                compatibility=compatibility,
                config_digest=str(payload["config_digest"]),
                merge_method=str(payload["merge_method"]),
                deployment_environment=str(payload["deployment_environment"]),
                lkg_release_sha=str(payload["lkg_release_sha"]),
                now_epoch=float(payload["created_at_epoch"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("promotion evidence payload is malformed") from exc
        if payload.get("evidence_id") not in {None, evidence.evidence_id}:
            raise ValueError("promotion evidence id mismatch")
        if payload.get("digest") not in {None, evidence.digest}:
            raise ValueError("promotion evidence digest mismatch")
        return evidence

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "change_id": self.change_id,
            "attempt_id": self.attempt_id,
            "candidate_artifact_id": self.candidate_artifact_id,
            "candidate_artifact_digest": self.candidate_artifact_digest,
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "candidate_base_sha": self.candidate_base_sha,
            "candidate_head_sha": self.candidate_head_sha,
            "candidate_diff_digest": self.candidate_diff_digest,
            "changed_paths": list(self.changed_paths),
            "protected_policy_id": self.protected_policy_id,
            "protected_policy_version": self.protected_policy_version,
            "protected_verdict": self.protected_verdict,
            "pr_number": self.pr_number,
            "pr_base_sha": self.pr_base_sha,
            "pr_head_sha": self.pr_head_sha,
            "tested_merge_sha": self.tested_merge_sha,
            "ci_run_id": self.ci_run_id,
            "required_checks": [
                {
                    "context": item.context,
                    "conclusion": item.conclusion,
                    "app_id": item.app_id,
                }
                for item in self.required_checks
            ],
            "windows_verified": self.windows_verified,
            "compatibility": {
                "schema": self.compatibility.schema.value,
                "dbos": self.compatibility.dbos.value,
                "dependencies": self.compatibility.dependencies.value,
            },
            "config_digest": self.config_digest,
            "merge_method": self.merge_method,
            "deployment_environment": self.deployment_environment,
            "lkg_release_sha": self.lkg_release_sha,
            "created_at_epoch": self.created_at_epoch,
        }

    def __post_init__(self) -> None:
        _digest(self.digest, field="digest")
        if self.evidence_id != f"promotion_evidence_{self.digest[:16]}":
            raise ValueError("evidence_id must be derived from digest")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("promotion evidence digest mismatch")
