"""Phase-9 verified capability-candidate evidence contracts."""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass

from jarvis.engineering_substrate.canonical import canonical_digest

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def _text(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _digest(value: object, *, field: str) -> str:
    normalized = _text(value, field=field).casefold()
    if _SHA256.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


def _git_sha(value: object, *, field: str) -> str:
    normalized = _text(value, field=field).casefold()
    if _GIT_SHA.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be an exact lowercase Git SHA")
    return normalized


def _unique(
    values: tuple[str, ...] | list[str],
    *,
    field: str,
) -> tuple[str, ...]:
    normalized = tuple(sorted({_text(item, field=field) for item in values}))
    return normalized


@dataclass(frozen=True, slots=True)
class CapabilityAcquisitionCandidateEvidenceV1:
    candidate_evidence_id: str
    goal_digest: str
    plan_digest: str
    architecture_artifact_id: str
    architecture_digest: str
    development_work_id: str
    branch: str
    commit: str
    source_revision: str
    changed_paths: tuple[str, ...]
    diff_digest: str
    verification_targets: tuple[str, ...]
    sandbox_profile: str
    sandbox_profile_version: int
    package_descriptor_path: str
    package_id: str
    package_version: str
    package_digest: str
    capability_id: str
    manifest_id: str
    manifest_version: int
    manifest_digest: str
    substrate_verification_artifact_id: str
    substrate_verification_artifact_digest: str
    substrate_binding_digest: str
    external_acceptance_contract_ids: tuple[str, ...]
    protected_surface_policy_id: str
    protected_surface_policy_version: int
    created_at_epoch: float
    digest: str

    @classmethod
    def create(
        cls,
        *,
        goal_digest: str,
        plan_digest: str,
        architecture_artifact_id: str,
        architecture_digest: str,
        development_work_id: str,
        branch: str,
        commit: str,
        source_revision: str,
        changed_paths: tuple[str, ...] | list[str],
        diff_digest: str,
        verification_targets: tuple[str, ...] | list[str],
        sandbox_profile: str,
        sandbox_profile_version: int,
        package_descriptor_path: str,
        package_id: str,
        package_version: str,
        package_digest: str,
        capability_id: str,
        manifest_id: str,
        manifest_version: int,
        manifest_digest: str,
        substrate_verification_artifact_id: str,
        substrate_verification_artifact_digest: str,
        substrate_binding_digest: str,
        external_acceptance_contract_ids: tuple[str, ...] | list[str],
        protected_surface_policy_id: str,
        protected_surface_policy_version: int,
        now_epoch: float | None = None,
    ) -> CapabilityAcquisitionCandidateEvidenceV1:
        if type(sandbox_profile_version) is not int or sandbox_profile_version < 1:
            raise ValueError("sandbox_profile_version must be positive")
        if type(manifest_version) is not int or manifest_version < 1:
            raise ValueError("manifest_version must be positive")
        if (
            type(protected_surface_policy_version) is not int
            or protected_surface_policy_version < 1
        ):
            raise ValueError("protected_surface_policy_version must be positive")
        changed = _unique(tuple(changed_paths), field="changed_path")
        targets = _unique(tuple(verification_targets), field="verification_target")
        external = _unique(
            tuple(external_acceptance_contract_ids),
            field="external_acceptance_contract_id",
        )
        if not changed or not targets:
            raise ValueError(
                "capability candidate requires changed paths and verification targets"
            )
        created = time.time() if now_epoch is None else float(now_epoch)
        if not math.isfinite(created) or created <= 0:
            raise ValueError("created_at_epoch must be finite and positive")

        normalized = {
            "goal_digest": _digest(goal_digest, field="goal_digest"),
            "plan_digest": _digest(plan_digest, field="plan_digest"),
            "architecture_artifact_id": _text(
                architecture_artifact_id,
                field="architecture_artifact_id",
            ),
            "architecture_digest": _digest(
                architecture_digest,
                field="architecture_digest",
            ),
            "development_work_id": _text(
                development_work_id,
                field="development_work_id",
            ),
            "branch": _text(branch, field="branch"),
            "commit": _git_sha(commit, field="commit"),
            "source_revision": _git_sha(
                source_revision,
                field="source_revision",
            ),
            "changed_paths": changed,
            "diff_digest": _digest(diff_digest, field="diff_digest"),
            "verification_targets": targets,
            "sandbox_profile": _text(sandbox_profile, field="sandbox_profile"),
            "sandbox_profile_version": sandbox_profile_version,
            "package_descriptor_path": _text(
                package_descriptor_path,
                field="package_descriptor_path",
            ),
            "package_id": _text(package_id, field="package_id").casefold(),
            "package_version": _text(package_version, field="package_version"),
            "package_digest": _digest(package_digest, field="package_digest"),
            "capability_id": _text(capability_id, field="capability_id").casefold(),
            "manifest_id": _text(manifest_id, field="manifest_id").casefold(),
            "manifest_version": manifest_version,
            "manifest_digest": _digest(manifest_digest, field="manifest_digest"),
            "substrate_verification_artifact_id": _text(
                substrate_verification_artifact_id,
                field="substrate_verification_artifact_id",
            ),
            "substrate_verification_artifact_digest": _digest(
                substrate_verification_artifact_digest,
                field="substrate_verification_artifact_digest",
            ),
            "substrate_binding_digest": _digest(
                substrate_binding_digest,
                field="substrate_binding_digest",
            ),
            "external_acceptance_contract_ids": external,
            "protected_surface_policy_id": _text(
                protected_surface_policy_id,
                field="protected_surface_policy_id",
            ),
            "protected_surface_policy_version": protected_surface_policy_version,
            "created_at_epoch": created,
        }
        canonical = {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in normalized.items()
        }
        digest = canonical_digest(canonical)
        return cls(
            candidate_evidence_id=f"capability_candidate_{digest[:16]}",
            digest=digest,
            **normalized,  # type: ignore[arg-type]
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "goal_digest": self.goal_digest,
            "plan_digest": self.plan_digest,
            "architecture_artifact_id": self.architecture_artifact_id,
            "architecture_digest": self.architecture_digest,
            "development_work_id": self.development_work_id,
            "branch": self.branch,
            "commit": self.commit,
            "source_revision": self.source_revision,
            "changed_paths": list(self.changed_paths),
            "diff_digest": self.diff_digest,
            "verification_targets": list(self.verification_targets),
            "sandbox_profile": self.sandbox_profile,
            "sandbox_profile_version": self.sandbox_profile_version,
            "package_descriptor_path": self.package_descriptor_path,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "package_digest": self.package_digest,
            "capability_id": self.capability_id,
            "manifest_id": self.manifest_id,
            "manifest_version": self.manifest_version,
            "manifest_digest": self.manifest_digest,
            "substrate_verification_artifact_id": (
                self.substrate_verification_artifact_id
            ),
            "substrate_verification_artifact_digest": (
                self.substrate_verification_artifact_digest
            ),
            "substrate_binding_digest": self.substrate_binding_digest,
            "external_acceptance_contract_ids": list(
                self.external_acceptance_contract_ids
            ),
            "protected_surface_policy_id": self.protected_surface_policy_id,
            "protected_surface_policy_version": self.protected_surface_policy_version,
            "created_at_epoch": self.created_at_epoch,
        }

    def __post_init__(self) -> None:
        _digest(self.digest, field="candidate evidence digest")
        if self.candidate_evidence_id != f"capability_candidate_{self.digest[:16]}":
            raise ValueError("candidate_evidence_id must be derived from digest")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("capability candidate evidence digest mismatch")
