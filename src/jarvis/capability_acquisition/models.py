"""Typed Phase-9 owner-requested capability acquisition contracts."""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from urllib.parse import unquote, urlparse
from enum import Enum

from jarvis.capability_registry.contracts import StrictSemVer
from jarvis.engineering_substrate.canonical import canonical_digest

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PYTHON_DISTRIBUTION = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")


def normalize_python_distribution_identity(value: object) -> str:
    """Return one safe Python distribution identity, accepting canonical PyPI URLs."""

    raw = _text(value, field="package_identity")
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        host = parsed.netloc.casefold()
        parts = [unquote(part).strip() for part in parsed.path.split("/") if part.strip()]
        if (
            parsed.scheme.casefold() not in {"http", "https"}
            or host not in {"pypi.org", "www.pypi.org"}
            or len(parts) < 2
            or parts[0].casefold() != "project"
        ):
            raise ValueError(
                "SDK package identity must be a Python distribution name or PyPI project URL"
            )
        raw = parts[1]

    normalized = raw.strip().casefold()
    if (
        not normalized
        or len(normalized) > 160
        or "/" in normalized
        or "\\" in normalized
        or "@" in normalized
        or _PYTHON_DISTRIBUTION.fullmatch(normalized) is None
    ):
        raise ValueError("SDK package identity must be a Python distribution name")
    return normalized


def _text(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _identity(value: object, *, field: str) -> str:
    return _text(value, field=field).casefold()


def _tokens(
    values: tuple[str, ...] | list[str],
    *,
    field: str,
    normalized: bool = True,
    require_nonempty: bool = False,
) -> tuple[str, ...]:
    items = tuple(
        _identity(value, field=field) if normalized else _text(value, field=field)
        for value in values
    )
    if require_nonempty and not items:
        raise ValueError(f"{field} requires at least one value")
    if len(set(items)) != len(items):
        raise ValueError(f"{field} values must be unique")
    return tuple(sorted(items))


def _optional_text(value: object | None, *, field: str) -> str | None:
    return None if value is None else _text(value, field=field)


def _digest(value: object, *, field: str) -> str:
    normalized = _text(value, field=field).casefold()
    if _SHA256.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


def _optional_digest(value: object | None, *, field: str) -> str | None:
    return None if value is None else _digest(value, field=field)


def _timestamp(value: float | None) -> float:
    result = time.time() if value is None else float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("created_at_epoch must be finite and positive")
    return result


class AcquisitionSourceKind(str, Enum):
    EXISTING_CAPABILITY = "existing_capability"
    OWNER_CONFIGURED_LOCAL = "owner_configured_local"
    MCP = "mcp"
    OPENAPI = "openapi"
    ASYNCAPI = "asyncapi"
    SDK_LIBRARY = "sdk_library"
    CUSTOM_BUILD = "custom_build"


class AcquisitionTrustClass(str, Enum):
    ACCEPTED_RELEASE = "accepted_release"
    OWNER_CONFIGURED = "owner_configured"
    VERIFIED_OFFICIAL_REMOTE = "verified_official_remote"
    VERIFIED_SIGNED_EXTERNAL = "verified_signed_external"
    UNVERIFIED_CANDIDATE = "unverified_candidate"


class AcquisitionStrategy(str, Enum):
    REUSE = "reuse"
    WRAP = "wrap"
    GENERATE_CONTRACT_CLIENT = "generate_contract_client"
    ADAPT_SDK = "adapt_sdk"
    BUILD_CUSTOM = "build_custom"


class AcquisitionDisposition(str, Enum):
    SELECTABLE = "selectable"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class OwnerCapabilityGoalV1:
    goal_id: str
    request: str
    requested_capability: str
    required_operations: tuple[str, ...]
    target_hints: tuple[str, ...]
    source_session_id: str
    source_turn_id: str
    created_at_epoch: float
    digest: str

    @classmethod
    def create(
        cls,
        *,
        request: str,
        requested_capability: str,
        required_operations: tuple[str, ...] | list[str],
        target_hints: tuple[str, ...] | list[str] = (),
        source_session_id: str,
        source_turn_id: str,
        now_epoch: float | None = None,
    ) -> OwnerCapabilityGoalV1:
        request_text = _text(request, field="request")
        capability = _text(requested_capability, field="requested_capability")
        operations = _tokens(
            tuple(required_operations),
            field="required_operation",
            require_nonempty=True,
        )
        hints = _tokens(tuple(target_hints), field="target_hint", normalized=False)
        session_id = _text(source_session_id, field="source_session_id")
        turn_id = _text(source_turn_id, field="source_turn_id")
        created = _timestamp(now_epoch)
        payload = {
            "request": request_text,
            "requested_capability": capability,
            "required_operations": list(operations),
            "target_hints": list(hints),
            "source_session_id": session_id,
            "source_turn_id": turn_id,
            "created_at_epoch": created,
        }
        digest = canonical_digest(payload)
        return cls(
            goal_id=f"capability_goal_{digest[:16]}",
            request=request_text,
            requested_capability=capability,
            required_operations=operations,
            target_hints=hints,
            source_session_id=session_id,
            source_turn_id=turn_id,
            created_at_epoch=created,
            digest=digest,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "request": self.request,
            "requested_capability": self.requested_capability,
            "required_operations": list(self.required_operations),
            "target_hints": list(self.target_hints),
            "source_session_id": self.source_session_id,
            "source_turn_id": self.source_turn_id,
            "created_at_epoch": self.created_at_epoch,
        }

    def __post_init__(self) -> None:
        _digest(self.digest, field="goal digest")
        if self.goal_id != f"capability_goal_{self.digest[:16]}":
            raise ValueError("goal_id must be derived from digest")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("owner capability goal digest mismatch")


@dataclass(frozen=True, slots=True)
class AcquisitionCandidateV1:
    candidate_id: str
    source_kind: AcquisitionSourceKind
    source_identity: str
    source_version: str | None
    source_digest: str | None
    trust_class: AcquisitionTrustClass
    supported_operations: tuple[str, ...]
    dependency_refs: tuple[str, ...]
    secret_scopes: tuple[str, ...]
    network_scopes: tuple[str, ...]
    device_scopes: tuple[str, ...]
    discovery_scopes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    license_id: str | None
    provenance_refs: tuple[str, ...]
    strategy: AcquisitionStrategy
    verification_requirements: tuple[str, ...]
    external_acceptance_requirements: tuple[str, ...]
    reason_codes: tuple[str, ...]
    digest: str

    @classmethod
    def create(
        cls,
        *,
        source_kind: AcquisitionSourceKind,
        source_identity: str,
        trust_class: AcquisitionTrustClass,
        supported_operations: tuple[str, ...] | list[str],
        strategy: AcquisitionStrategy,
        evidence_refs: tuple[str, ...] | list[str],
        verification_requirements: tuple[str, ...] | list[str],
        source_version: str | None = None,
        source_digest: str | None = None,
        dependency_refs: tuple[str, ...] | list[str] = (),
        secret_scopes: tuple[str, ...] | list[str] = (),
        network_scopes: tuple[str, ...] | list[str] = (),
        device_scopes: tuple[str, ...] | list[str] = (),
        discovery_scopes: tuple[str, ...] | list[str] = (),
        license_id: str | None = None,
        provenance_refs: tuple[str, ...] | list[str] = (),
        external_acceptance_requirements: tuple[str, ...] | list[str] = (),
        reason_codes: tuple[str, ...] | list[str] = (),
    ) -> AcquisitionCandidateV1:
        if not isinstance(source_kind, AcquisitionSourceKind):
            raise TypeError("source_kind must be AcquisitionSourceKind")
        if not isinstance(trust_class, AcquisitionTrustClass):
            raise TypeError("trust_class must be AcquisitionTrustClass")
        if not isinstance(strategy, AcquisitionStrategy):
            raise TypeError("strategy must be AcquisitionStrategy")

        identity = _text(source_identity, field="source_identity")
        version = _optional_text(source_version, field="source_version")
        digest_value = _optional_digest(source_digest, field="source_digest")
        if (
            trust_class is not AcquisitionTrustClass.UNVERIFIED_CANDIDATE
            and digest_value is None
        ):
            raise ValueError("verified candidate trust classes require source_digest")

        operations = _tokens(
            tuple(supported_operations),
            field="supported_operation",
            require_nonempty=True,
        )
        evidence = _tokens(
            tuple(evidence_refs),
            field="evidence_ref",
            normalized=False,
            require_nonempty=True,
        )
        verification = _tokens(
            tuple(verification_requirements),
            field="verification_requirement",
            normalized=False,
            require_nonempty=True,
        )
        payload: dict[str, object] = {
            "source_kind": source_kind.value,
            "source_identity": identity,
            "source_version": version,
            "source_digest": digest_value,
            "trust_class": trust_class.value,
            "supported_operations": list(operations),
            "dependency_refs": list(
                _tokens(
                    tuple(dependency_refs), field="dependency_ref", normalized=False
                )
            ),
            "secret_scopes": list(_tokens(tuple(secret_scopes), field="secret_scope")),
            "network_scopes": list(
                _tokens(tuple(network_scopes), field="network_scope", normalized=False)
            ),
            "device_scopes": list(
                _tokens(tuple(device_scopes), field="device_scope", normalized=False)
            ),
            "discovery_scopes": list(
                _tokens(tuple(discovery_scopes), field="discovery_scope")
            ),
            "evidence_refs": list(evidence),
            "license_id": _optional_text(license_id, field="license_id"),
            "provenance_refs": list(
                _tokens(
                    tuple(provenance_refs), field="provenance_ref", normalized=False
                )
            ),
            "strategy": strategy.value,
            "verification_requirements": list(verification),
            "external_acceptance_requirements": list(
                _tokens(
                    tuple(external_acceptance_requirements),
                    field="external_acceptance_requirement",
                    normalized=False,
                )
            ),
            "reason_codes": list(_tokens(tuple(reason_codes), field="reason_code")),
        }
        digest = canonical_digest(payload)
        return cls(
            candidate_id=f"acquisition_candidate_{digest[:16]}",
            source_kind=source_kind,
            source_identity=identity,
            source_version=version,
            source_digest=digest_value,
            trust_class=trust_class,
            supported_operations=operations,
            dependency_refs=tuple(payload["dependency_refs"]),
            secret_scopes=tuple(payload["secret_scopes"]),
            network_scopes=tuple(payload["network_scopes"]),
            device_scopes=tuple(payload["device_scopes"]),
            discovery_scopes=tuple(payload["discovery_scopes"]),
            evidence_refs=evidence,
            license_id=payload["license_id"],
            provenance_refs=tuple(payload["provenance_refs"]),
            strategy=strategy,
            verification_requirements=verification,
            external_acceptance_requirements=tuple(
                payload["external_acceptance_requirements"]
            ),
            reason_codes=tuple(payload["reason_codes"]),
            digest=digest,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "source_kind": self.source_kind.value,
            "source_identity": self.source_identity,
            "source_version": self.source_version,
            "source_digest": self.source_digest,
            "trust_class": self.trust_class.value,
            "supported_operations": list(self.supported_operations),
            "dependency_refs": list(self.dependency_refs),
            "secret_scopes": list(self.secret_scopes),
            "network_scopes": list(self.network_scopes),
            "device_scopes": list(self.device_scopes),
            "discovery_scopes": list(self.discovery_scopes),
            "evidence_refs": list(self.evidence_refs),
            "license_id": self.license_id,
            "provenance_refs": list(self.provenance_refs),
            "strategy": self.strategy.value,
            "verification_requirements": list(self.verification_requirements),
            "external_acceptance_requirements": list(
                self.external_acceptance_requirements
            ),
            "reason_codes": list(self.reason_codes),
        }

    def __post_init__(self) -> None:
        _digest(self.digest, field="candidate digest")
        if self.candidate_id != f"acquisition_candidate_{self.digest[:16]}":
            raise ValueError("candidate_id must be derived from digest")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("acquisition candidate digest mismatch")


@dataclass(frozen=True, slots=True)
class AcquisitionCandidateEvaluationV1:
    evaluation_id: str
    candidate_id: str
    candidate_digest: str
    requested_operations: tuple[str, ...]
    covered_operations: tuple[str, ...]
    missing_operations: tuple[str, ...]
    evidence_complete: bool
    trust_allowed: bool
    requirements_compatible: bool
    disposition: AcquisitionDisposition
    reason_codes: tuple[str, ...]
    evaluator_id: str
    evaluator_version: int
    digest: str

    @classmethod
    def create(
        cls,
        candidate: AcquisitionCandidateV1,
        *,
        requested_operations: tuple[str, ...] | list[str],
        evidence_complete: bool,
        trust_allowed: bool,
        requirements_compatible: bool,
        reason_codes: tuple[str, ...] | list[str] = (),
        evaluator_id: str = "jarvis.capability_acquisition",
        evaluator_version: int = 1,
    ) -> AcquisitionCandidateEvaluationV1:
        if not isinstance(candidate, AcquisitionCandidateV1):
            raise TypeError("candidate must be AcquisitionCandidateV1")
        if type(evaluator_version) is not int or evaluator_version <= 0:
            raise ValueError("evaluator_version must be a positive integer")
        for field_name, value in (
            ("evidence_complete", evidence_complete),
            ("trust_allowed", trust_allowed),
            ("requirements_compatible", requirements_compatible),
        ):
            if type(value) is not bool:
                raise TypeError(f"{field_name} must be bool")
        requested = _tokens(
            tuple(requested_operations),
            field="requested_operation",
            require_nonempty=True,
        )
        supported = set(candidate.supported_operations)
        covered = tuple(item for item in requested if item in supported)
        missing = tuple(item for item in requested if item not in supported)
        reasons = list(_tokens(tuple(reason_codes), field="reason_code"))
        if missing and "missing_required_operations" not in reasons:
            reasons.append("missing_required_operations")
        if not evidence_complete and "evidence_incomplete" not in reasons:
            reasons.append("evidence_incomplete")
        if not trust_allowed and "trust_not_allowed" not in reasons:
            reasons.append("trust_not_allowed")
        if not requirements_compatible and "requirements_incompatible" not in reasons:
            reasons.append("requirements_incompatible")
        normalized_reasons = tuple(sorted(reasons))
        selectable = (
            not missing
            and bool(evidence_complete)
            and bool(trust_allowed)
            and bool(requirements_compatible)
        )
        disposition = (
            AcquisitionDisposition.SELECTABLE
            if selectable
            else AcquisitionDisposition.BLOCKED
        )
        payload = {
            "candidate_id": candidate.candidate_id,
            "candidate_digest": candidate.digest,
            "requested_operations": list(requested),
            "covered_operations": list(covered),
            "missing_operations": list(missing),
            "evidence_complete": bool(evidence_complete),
            "trust_allowed": bool(trust_allowed),
            "requirements_compatible": bool(requirements_compatible),
            "disposition": disposition.value,
            "reason_codes": list(normalized_reasons),
            "evaluator_id": _identity(evaluator_id, field="evaluator_id"),
            "evaluator_version": evaluator_version,
        }
        digest = canonical_digest(payload)
        return cls(
            evaluation_id=f"acquisition_evaluation_{digest[:16]}",
            candidate_id=candidate.candidate_id,
            candidate_digest=candidate.digest,
            requested_operations=requested,
            covered_operations=covered,
            missing_operations=missing,
            evidence_complete=bool(evidence_complete),
            trust_allowed=bool(trust_allowed),
            requirements_compatible=bool(requirements_compatible),
            disposition=disposition,
            reason_codes=normalized_reasons,
            evaluator_id=payload["evaluator_id"],
            evaluator_version=evaluator_version,
            digest=digest,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "requested_operations": list(self.requested_operations),
            "covered_operations": list(self.covered_operations),
            "missing_operations": list(self.missing_operations),
            "evidence_complete": self.evidence_complete,
            "trust_allowed": self.trust_allowed,
            "requirements_compatible": self.requirements_compatible,
            "disposition": self.disposition.value,
            "reason_codes": list(self.reason_codes),
            "evaluator_id": self.evaluator_id,
            "evaluator_version": self.evaluator_version,
        }

    def __post_init__(self) -> None:
        _digest(self.candidate_digest, field="candidate_digest")
        _digest(self.digest, field="evaluation digest")
        if self.evaluation_id != f"acquisition_evaluation_{self.digest[:16]}":
            raise ValueError("evaluation_id must be derived from digest")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("candidate evaluation digest mismatch")


@dataclass(frozen=True, slots=True)
class CapabilityAcquisitionPlanV1:
    plan_id: str
    goal_id: str
    goal_digest: str
    candidate_id: str
    candidate_digest: str
    evaluation_digest: str
    strategy: AcquisitionStrategy
    requested_operations: tuple[str, ...]
    changed_components: tuple[str, ...]
    changed_paths: tuple[str, ...]
    dependency_refs: tuple[str, ...]
    secret_scopes: tuple[str, ...]
    sandbox_profile_ids: tuple[str, ...]
    discovery_scopes: tuple[str, ...]
    network_scopes: tuple[str, ...]
    device_scopes: tuple[str, ...]
    verification_contract_ids: tuple[str, ...]
    development_test_targets: tuple[str, ...]
    owner_acceptance_contract_ids: tuple[str, ...]
    proposed_capability_id: str
    proposed_package_id: str
    proposed_package_version: str
    rollback_summary: str
    evidence_refs: tuple[str, ...]
    digest: str

    @classmethod
    def create(
        cls,
        goal: OwnerCapabilityGoalV1,
        candidate: AcquisitionCandidateV1,
        evaluation: AcquisitionCandidateEvaluationV1,
        *,
        proposed_capability_id: str,
        proposed_package_id: str,
        proposed_package_version: str,
        rollback_summary: str,
        changed_components: tuple[str, ...] | list[str] = (),
        changed_paths: tuple[str, ...] | list[str] = (),
        dependency_refs: tuple[str, ...] | list[str] = (),
        secret_scopes: tuple[str, ...] | list[str] = (),
        sandbox_profile_ids: tuple[str, ...] | list[str] = (),
        discovery_scopes: tuple[str, ...] | list[str] = (),
        network_scopes: tuple[str, ...] | list[str] = (),
        device_scopes: tuple[str, ...] | list[str] = (),
        verification_contract_ids: tuple[str, ...] | list[str] = (),
        development_test_targets: tuple[str, ...] | list[str] = (),
        owner_acceptance_contract_ids: tuple[str, ...] | list[str] = (),
        evidence_refs: tuple[str, ...] | list[str] = (),
    ) -> CapabilityAcquisitionPlanV1:
        if not isinstance(goal, OwnerCapabilityGoalV1):
            raise TypeError("goal must be OwnerCapabilityGoalV1")
        if not isinstance(candidate, AcquisitionCandidateV1):
            raise TypeError("candidate must be AcquisitionCandidateV1")
        if not isinstance(evaluation, AcquisitionCandidateEvaluationV1):
            raise TypeError("evaluation must be AcquisitionCandidateEvaluationV1")
        if (
            evaluation.candidate_id != candidate.candidate_id
            or evaluation.candidate_digest != candidate.digest
        ):
            raise ValueError("evaluation does not bind selected candidate")
        if evaluation.disposition is not AcquisitionDisposition.SELECTABLE:
            raise ValueError("blocked acquisition candidate cannot produce a plan")
        if evaluation.requested_operations != goal.required_operations:
            raise ValueError("evaluation does not bind exact owner operations")
        if not set(goal.required_operations).issubset(candidate.supported_operations):
            raise ValueError("candidate does not cover all required operations")

        package_version = _text(
            proposed_package_version,
            field="proposed_package_version",
        )
        StrictSemVer.parse(package_version)
        payload = {
            "goal_id": goal.goal_id,
            "goal_digest": goal.digest,
            "candidate_id": candidate.candidate_id,
            "candidate_digest": candidate.digest,
            "evaluation_digest": evaluation.digest,
            "strategy": candidate.strategy.value,
            "requested_operations": list(goal.required_operations),
            "changed_components": list(
                _tokens(
                    tuple(changed_components),
                    field="changed_component",
                    normalized=False,
                )
            ),
            "changed_paths": list(
                _tokens(tuple(changed_paths), field="changed_path", normalized=False)
            ),
            "dependency_refs": list(
                _tokens(
                    tuple(dependency_refs), field="dependency_ref", normalized=False
                )
            ),
            "secret_scopes": list(_tokens(tuple(secret_scopes), field="secret_scope")),
            "sandbox_profile_ids": list(
                _tokens(tuple(sandbox_profile_ids), field="sandbox_profile_id")
            ),
            "discovery_scopes": list(
                _tokens(tuple(discovery_scopes), field="discovery_scope")
            ),
            "network_scopes": list(
                _tokens(tuple(network_scopes), field="network_scope", normalized=False)
            ),
            "device_scopes": list(
                _tokens(tuple(device_scopes), field="device_scope", normalized=False)
            ),
            "verification_contract_ids": list(
                _tokens(
                    tuple(verification_contract_ids),
                    field="verification_contract_id",
                    require_nonempty=True,
                )
            ),
            "development_test_targets": list(
                _tokens(
                    tuple(development_test_targets),
                    field="development_test_target",
                    normalized=False,
                    require_nonempty=True,
                )
            ),
            "owner_acceptance_contract_ids": list(
                _tokens(
                    tuple(owner_acceptance_contract_ids),
                    field="owner_acceptance_contract_id",
                )
            ),
            "proposed_capability_id": _identity(
                proposed_capability_id,
                field="proposed_capability_id",
            ),
            "proposed_package_id": _identity(
                proposed_package_id,
                field="proposed_package_id",
            ),
            "proposed_package_version": package_version,
            "rollback_summary": _text(rollback_summary, field="rollback_summary"),
            "evidence_refs": list(
                _tokens(
                    tuple(evidence_refs),
                    field="evidence_ref",
                    normalized=False,
                    require_nonempty=True,
                )
            ),
        }
        digest = canonical_digest(payload)
        return cls(
            plan_id=f"capability_plan_{digest[:16]}",
            goal_id=goal.goal_id,
            goal_digest=goal.digest,
            candidate_id=candidate.candidate_id,
            candidate_digest=candidate.digest,
            evaluation_digest=evaluation.digest,
            strategy=candidate.strategy,
            requested_operations=goal.required_operations,
            changed_components=tuple(payload["changed_components"]),
            changed_paths=tuple(payload["changed_paths"]),
            dependency_refs=tuple(payload["dependency_refs"]),
            secret_scopes=tuple(payload["secret_scopes"]),
            sandbox_profile_ids=tuple(payload["sandbox_profile_ids"]),
            discovery_scopes=tuple(payload["discovery_scopes"]),
            network_scopes=tuple(payload["network_scopes"]),
            device_scopes=tuple(payload["device_scopes"]),
            verification_contract_ids=tuple(payload["verification_contract_ids"]),
            development_test_targets=tuple(payload["development_test_targets"]),
            owner_acceptance_contract_ids=tuple(
                payload["owner_acceptance_contract_ids"]
            ),
            proposed_capability_id=payload["proposed_capability_id"],
            proposed_package_id=payload["proposed_package_id"],
            proposed_package_version=package_version,
            rollback_summary=payload["rollback_summary"],
            evidence_refs=tuple(payload["evidence_refs"]),
            digest=digest,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "goal_digest": self.goal_digest,
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "evaluation_digest": self.evaluation_digest,
            "strategy": self.strategy.value,
            "requested_operations": list(self.requested_operations),
            "changed_components": list(self.changed_components),
            "changed_paths": list(self.changed_paths),
            "dependency_refs": list(self.dependency_refs),
            "secret_scopes": list(self.secret_scopes),
            "sandbox_profile_ids": list(self.sandbox_profile_ids),
            "discovery_scopes": list(self.discovery_scopes),
            "network_scopes": list(self.network_scopes),
            "device_scopes": list(self.device_scopes),
            "verification_contract_ids": list(self.verification_contract_ids),
            "development_test_targets": list(self.development_test_targets),
            "owner_acceptance_contract_ids": list(self.owner_acceptance_contract_ids),
            "proposed_capability_id": self.proposed_capability_id,
            "proposed_package_id": self.proposed_package_id,
            "proposed_package_version": self.proposed_package_version,
            "rollback_summary": self.rollback_summary,
            "evidence_refs": list(self.evidence_refs),
        }

    def __post_init__(self) -> None:
        _digest(self.goal_digest, field="goal_digest")
        _digest(self.candidate_digest, field="candidate_digest")
        _digest(self.evaluation_digest, field="evaluation_digest")
        _digest(self.digest, field="plan digest")
        if self.plan_id != f"capability_plan_{self.digest[:16]}":
            raise ValueError("plan_id must be derived from digest")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("capability acquisition plan digest mismatch")
