"""Typed Phase-6 unknown-incident investigation and source-repair contracts."""

from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass
from enum import Enum

import rfc8785

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_GIT_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _token(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _normalized_token(value: object, *, field: str) -> str:
    normalized = _token(value, field=field).lower()
    if normalized != str(value):
        raise ValueError(f"{field} must be normalized lowercase")
    return normalized


def _unique(values: tuple[str, ...] | list[str], *, field: str) -> tuple[str, ...]:
    normalized = tuple(_token(value, field=field) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} values must be unique")
    return normalized


def _digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(rfc8785.dumps(payload)).hexdigest()


def _require_digest(value: str, *, field: str) -> str:
    normalized = _token(value, field=field).lower()
    if _HEX_64.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a sha256 digest")
    return normalized


def _require_git_revision(value: str) -> str:
    normalized = _token(value, field="source_revision").lower()
    if _GIT_REVISION.fullmatch(normalized) is None:
        raise ValueError("source_revision must be an exact Git object id")
    return normalized


class HypothesisState(str, Enum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


class ReproductionState(str, Enum):
    REPRODUCED = "reproduced"
    NOT_REPRODUCED = "not_reproduced"
    INCONCLUSIVE = "inconclusive"


class DiagnosisDisposition(str, Enum):
    SUPPORTED_REPAIR = "supported_repair"
    INCONCLUSIVE = "inconclusive"


class ProtectedSurfaceVerdict(str, Enum):
    CLEAR = "clear"
    PROTECTED_CHANGE_REQUIRED = "protected_change_required"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class IncidentRepairTrigger:
    trigger_id: str
    incident_id: str
    source_revision: str
    component_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    reason_code: str
    created_at_epoch: float
    digest: str

    @classmethod
    def create(
        cls,
        *,
        incident_id: str,
        source_revision: str,
        component_ids: tuple[str, ...] | list[str],
        evidence_ids: tuple[str, ...] | list[str],
        reason_code: str,
        now_epoch: float | None = None,
    ) -> IncidentRepairTrigger:
        incident = _token(incident_id, field="incident_id")
        revision = _require_git_revision(source_revision)
        components = tuple(sorted(_unique(tuple(component_ids), field="component_id")))
        evidence = tuple(sorted(_unique(tuple(evidence_ids), field="evidence_id")))
        if not evidence:
            raise ValueError("incident repair trigger requires evidence")
        reason = _normalized_token(reason_code, field="reason_code")
        created = time.time() if now_epoch is None else float(now_epoch)
        if not math.isfinite(created) or created <= 0:
            raise ValueError("created_at_epoch must be finite and positive")
        payload: dict[str, object] = {
            "incident_id": incident,
            "source_revision": revision,
            "component_ids": list(components),
            "evidence_ids": list(evidence),
            "reason_code": reason,
            "created_at_epoch": created,
        }
        digest = _digest(payload)
        return cls(
            trigger_id=f"incident_repair_{digest[:16]}",
            incident_id=incident,
            source_revision=revision,
            component_ids=components,
            evidence_ids=evidence,
            reason_code=reason,
            created_at_epoch=created,
            digest=digest,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "incident_id": self.incident_id,
            "source_revision": self.source_revision,
            "component_ids": list(self.component_ids),
            "evidence_ids": list(self.evidence_ids),
            "reason_code": self.reason_code,
            "created_at_epoch": self.created_at_epoch,
        }

    def __post_init__(self) -> None:
        if self.trigger_id != f"incident_repair_{self.digest[:16]}":
            raise ValueError("trigger_id must be derived from digest")
        _require_digest(self.digest, field="digest")
        if _digest(self.canonical_payload()) != self.digest:
            raise ValueError("incident repair trigger digest mismatch")


@dataclass(frozen=True, slots=True)
class DiagnosticHypothesis:
    hypothesis_id: str
    statement: str
    affected_components: tuple[str, ...]
    affected_paths: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]
    refuting_evidence_ids: tuple[str, ...]
    status: HypothesisState
    discriminator: str | None = None

    @classmethod
    def create(
        cls,
        *,
        statement: str,
        affected_components: tuple[str, ...] | list[str] = (),
        affected_paths: tuple[str, ...] | list[str] = (),
        supporting_evidence_ids: tuple[str, ...] | list[str] = (),
        refuting_evidence_ids: tuple[str, ...] | list[str] = (),
        status: HypothesisState = HypothesisState.PROPOSED,
        discriminator: str | None = None,
    ) -> DiagnosticHypothesis:
        if not isinstance(status, HypothesisState):
            raise TypeError("hypothesis status must be HypothesisState")
        statement_text = _token(statement, field="statement")
        components = tuple(
            sorted(_unique(tuple(affected_components), field="affected_component"))
        )
        paths = tuple(sorted(_unique(tuple(affected_paths), field="affected_path")))
        supporting = tuple(
            sorted(
                _unique(tuple(supporting_evidence_ids), field="supporting_evidence_id")
            )
        )
        refuting = tuple(
            sorted(_unique(tuple(refuting_evidence_ids), field="refuting_evidence_id"))
        )
        if set(supporting).intersection(refuting):
            raise ValueError("evidence cannot both support and refute one hypothesis")
        if status is HypothesisState.SUPPORTED and not supporting:
            raise ValueError("supported hypothesis requires supporting evidence")
        if status is HypothesisState.REFUTED and not refuting:
            raise ValueError("refuted hypothesis requires refuting evidence")
        discriminator_text = (
            None
            if discriminator is None
            else _token(discriminator, field="discriminator")
        )
        identity_payload = {
            "statement": statement_text,
            "affected_components": list(components),
            "affected_paths": list(paths),
        }
        hypothesis_id = f"hypothesis_{_digest(identity_payload)[:16]}"
        return cls(
            hypothesis_id=hypothesis_id,
            statement=statement_text,
            affected_components=components,
            affected_paths=paths,
            supporting_evidence_ids=supporting,
            refuting_evidence_ids=refuting,
            status=status,
            discriminator=discriminator_text,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "affected_components": list(self.affected_components),
            "affected_paths": list(self.affected_paths),
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "refuting_evidence_ids": list(self.refuting_evidence_ids),
            "status": self.status.value,
            "discriminator": self.discriminator,
        }


@dataclass(frozen=True, slots=True)
class IncidentDiagnosis:
    diagnosis_id: str
    incident_id: str
    change_id: str
    work_id: str
    source_revision: str
    evidence_ids: tuple[str, ...]
    knowledge_revision_ids: tuple[str, ...]
    reproduction_state: ReproductionState
    hypotheses: tuple[DiagnosticHypothesis, ...]
    selected_hypothesis_id: str | None
    affected_paths: tuple[str, ...]
    affected_components: tuple[str, ...]
    proposed_repair_scope: str | None
    verification_targets: tuple[str, ...]
    reason_codes: tuple[str, ...]
    disposition: DiagnosisDisposition
    created_at_epoch: float
    digest: str

    @classmethod
    def create(
        cls,
        *,
        incident_id: str,
        change_id: str,
        work_id: str,
        source_revision: str,
        evidence_ids: tuple[str, ...] | list[str],
        knowledge_revision_ids: tuple[str, ...] | list[str] = (),
        reproduction_state: ReproductionState,
        hypotheses: tuple[DiagnosticHypothesis, ...] | list[DiagnosticHypothesis],
        selected_hypothesis_id: str | None = None,
        affected_paths: tuple[str, ...] | list[str] = (),
        affected_components: tuple[str, ...] | list[str] = (),
        proposed_repair_scope: str | None = None,
        verification_targets: tuple[str, ...] | list[str] = (),
        reason_codes: tuple[str, ...] | list[str] = (),
        disposition: DiagnosisDisposition,
        now_epoch: float | None = None,
    ) -> IncidentDiagnosis:
        if not isinstance(reproduction_state, ReproductionState):
            raise TypeError("reproduction_state must be ReproductionState")
        if not isinstance(disposition, DiagnosisDisposition):
            raise TypeError("disposition must be DiagnosisDisposition")
        hypothesis_values = tuple(hypotheses)
        if not hypothesis_values or any(
            not isinstance(item, DiagnosticHypothesis) for item in hypothesis_values
        ):
            raise ValueError("diagnosis requires typed hypotheses")
        hypothesis_ids = [item.hypothesis_id for item in hypothesis_values]
        if len(set(hypothesis_ids)) != len(hypothesis_ids):
            raise ValueError("diagnosis hypothesis ids must be unique")

        selected = (
            None
            if selected_hypothesis_id is None
            else _token(selected_hypothesis_id, field="selected_hypothesis_id")
        )
        selected_item = next(
            (item for item in hypothesis_values if item.hypothesis_id == selected),
            None,
        )
        targets = tuple(
            sorted(_unique(tuple(verification_targets), field="verification_target"))
        )
        scope = (
            None
            if proposed_repair_scope is None
            else _token(proposed_repair_scope, field="proposed_repair_scope")
        )
        if disposition is DiagnosisDisposition.SUPPORTED_REPAIR:
            if (
                selected_item is None
                or selected_item.status is not HypothesisState.SUPPORTED
            ):
                raise ValueError(
                    "supported repair diagnosis requires a selected supported hypothesis"
                )
            if scope is None or not targets:
                raise ValueError(
                    "supported repair diagnosis requires repair scope and verification targets"
                )
        elif selected is not None:
            raise ValueError("inconclusive diagnosis cannot select a root cause")

        created = time.time() if now_epoch is None else float(now_epoch)
        if not math.isfinite(created) or created <= 0:
            raise ValueError("created_at_epoch must be finite and positive")
        payload: dict[str, object] = {
            "incident_id": _token(incident_id, field="incident_id"),
            "change_id": _token(change_id, field="change_id"),
            "work_id": _token(work_id, field="work_id"),
            "source_revision": _require_git_revision(source_revision),
            "evidence_ids": sorted(_unique(tuple(evidence_ids), field="evidence_id")),
            "knowledge_revision_ids": sorted(
                _unique(
                    tuple(knowledge_revision_ids),
                    field="knowledge_revision_id",
                )
            ),
            "reproduction_state": reproduction_state.value,
            "hypotheses": [
                hypothesis.canonical_payload() for hypothesis in hypothesis_values
            ],
            "selected_hypothesis_id": selected,
            "affected_paths": sorted(
                _unique(tuple(affected_paths), field="affected_path")
            ),
            "affected_components": sorted(
                _unique(
                    tuple(affected_components),
                    field="affected_component",
                )
            ),
            "proposed_repair_scope": scope,
            "verification_targets": list(targets),
            "reason_codes": sorted(_unique(tuple(reason_codes), field="reason_code")),
            "disposition": disposition.value,
            "created_at_epoch": created,
        }
        if not payload["evidence_ids"]:
            raise ValueError("diagnosis requires evidence")
        evidence_set = set(payload["evidence_ids"])
        referenced_hypothesis_evidence = {
            evidence_id
            for hypothesis in hypothesis_values
            for evidence_id in (
                *hypothesis.supporting_evidence_ids,
                *hypothesis.refuting_evidence_ids,
            )
        }
        if not referenced_hypothesis_evidence.issubset(evidence_set):
            raise ValueError(
                "hypothesis evidence must be included in diagnosis evidence"
            )
        digest = _digest(payload)
        return cls(
            diagnosis_id=f"diagnosis_{digest[:16]}",
            incident_id=str(payload["incident_id"]),
            change_id=str(payload["change_id"]),
            work_id=str(payload["work_id"]),
            source_revision=str(payload["source_revision"]),
            evidence_ids=tuple(payload["evidence_ids"]),
            knowledge_revision_ids=tuple(payload["knowledge_revision_ids"]),
            reproduction_state=reproduction_state,
            hypotheses=hypothesis_values,
            selected_hypothesis_id=selected,
            affected_paths=tuple(payload["affected_paths"]),
            affected_components=tuple(payload["affected_components"]),
            proposed_repair_scope=scope,
            verification_targets=targets,
            reason_codes=tuple(payload["reason_codes"]),
            disposition=disposition,
            created_at_epoch=created,
            digest=digest,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "incident_id": self.incident_id,
            "change_id": self.change_id,
            "work_id": self.work_id,
            "source_revision": self.source_revision,
            "evidence_ids": list(self.evidence_ids),
            "knowledge_revision_ids": list(self.knowledge_revision_ids),
            "reproduction_state": self.reproduction_state.value,
            "hypotheses": [
                hypothesis.canonical_payload() for hypothesis in self.hypotheses
            ],
            "selected_hypothesis_id": self.selected_hypothesis_id,
            "affected_paths": list(self.affected_paths),
            "affected_components": list(self.affected_components),
            "proposed_repair_scope": self.proposed_repair_scope,
            "verification_targets": list(self.verification_targets),
            "reason_codes": list(self.reason_codes),
            "disposition": self.disposition.value,
            "created_at_epoch": self.created_at_epoch,
        }

    def __post_init__(self) -> None:
        if self.diagnosis_id != f"diagnosis_{self.digest[:16]}":
            raise ValueError("diagnosis_id must be derived from digest")
        _require_digest(self.digest, field="digest")
        if _digest(self.canonical_payload()) != self.digest:
            raise ValueError("diagnosis digest mismatch")


@dataclass(frozen=True, slots=True)
class SourceRepairCandidateEvidence:
    candidate_id: str
    incident_id: str
    diagnosis_id: str
    diagnosis_digest: str
    architecture_artifact_id: str
    architecture_digest: str
    development_work_id: str
    branch: str
    commit: str
    changed_paths: tuple[str, ...]
    diff_digest: str
    verification_targets: tuple[str, ...]
    sandbox_profile: str
    sandbox_profile_version: int
    protected_surface_verdict: ProtectedSurfaceVerdict
    created_at_epoch: float
    digest: str

    @classmethod
    def create(
        cls,
        *,
        incident_id: str,
        diagnosis_id: str,
        diagnosis_digest: str,
        architecture_artifact_id: str,
        architecture_digest: str,
        development_work_id: str,
        branch: str,
        commit: str,
        changed_paths: tuple[str, ...] | list[str],
        diff_digest: str,
        verification_targets: tuple[str, ...] | list[str],
        sandbox_profile: str,
        sandbox_profile_version: int,
        protected_surface_verdict: ProtectedSurfaceVerdict,
        now_epoch: float | None = None,
    ) -> SourceRepairCandidateEvidence:
        if protected_surface_verdict is not ProtectedSurfaceVerdict.CLEAR:
            raise ValueError(
                "source repair candidate requires CLEAR protected-surface verdict"
            )
        if type(sandbox_profile_version) is not int or sandbox_profile_version < 1:
            raise ValueError("sandbox_profile_version must be positive")
        commit_id = _require_git_revision(commit)
        changed = tuple(sorted(_unique(tuple(changed_paths), field="changed_path")))
        targets = tuple(
            sorted(_unique(tuple(verification_targets), field="verification_target"))
        )
        if not changed or not targets:
            raise ValueError(
                "source repair candidate requires changed paths and verification targets"
            )
        created = time.time() if now_epoch is None else float(now_epoch)
        if not math.isfinite(created) or created <= 0:
            raise ValueError("created_at_epoch must be finite and positive")
        payload: dict[str, object] = {
            "incident_id": _token(incident_id, field="incident_id"),
            "diagnosis_id": _token(diagnosis_id, field="diagnosis_id"),
            "diagnosis_digest": _require_digest(
                diagnosis_digest,
                field="diagnosis_digest",
            ),
            "architecture_artifact_id": _token(
                architecture_artifact_id,
                field="architecture_artifact_id",
            ),
            "architecture_digest": _require_digest(
                architecture_digest,
                field="architecture_digest",
            ),
            "development_work_id": _token(
                development_work_id,
                field="development_work_id",
            ),
            "branch": _token(branch, field="branch"),
            "commit": commit_id,
            "changed_paths": list(changed),
            "diff_digest": _require_digest(diff_digest, field="diff_digest"),
            "verification_targets": list(targets),
            "sandbox_profile": _token(sandbox_profile, field="sandbox_profile"),
            "sandbox_profile_version": sandbox_profile_version,
            "protected_surface_verdict": protected_surface_verdict.value,
            "created_at_epoch": created,
        }
        digest = _digest(payload)
        return cls(
            candidate_id=f"repair_candidate_{digest[:16]}",
            incident_id=str(payload["incident_id"]),
            diagnosis_id=str(payload["diagnosis_id"]),
            diagnosis_digest=str(payload["diagnosis_digest"]),
            architecture_artifact_id=str(payload["architecture_artifact_id"]),
            architecture_digest=str(payload["architecture_digest"]),
            development_work_id=str(payload["development_work_id"]),
            branch=str(payload["branch"]),
            commit=commit_id,
            changed_paths=changed,
            diff_digest=str(payload["diff_digest"]),
            verification_targets=targets,
            sandbox_profile=str(payload["sandbox_profile"]),
            sandbox_profile_version=sandbox_profile_version,
            protected_surface_verdict=protected_surface_verdict,
            created_at_epoch=created,
            digest=digest,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "incident_id": self.incident_id,
            "diagnosis_id": self.diagnosis_id,
            "diagnosis_digest": self.diagnosis_digest,
            "architecture_artifact_id": self.architecture_artifact_id,
            "architecture_digest": self.architecture_digest,
            "development_work_id": self.development_work_id,
            "branch": self.branch,
            "commit": self.commit,
            "changed_paths": list(self.changed_paths),
            "diff_digest": self.diff_digest,
            "verification_targets": list(self.verification_targets),
            "sandbox_profile": self.sandbox_profile,
            "sandbox_profile_version": self.sandbox_profile_version,
            "protected_surface_verdict": self.protected_surface_verdict.value,
            "created_at_epoch": self.created_at_epoch,
        }

    def __post_init__(self) -> None:
        if self.candidate_id != f"repair_candidate_{self.digest[:16]}":
            raise ValueError("candidate_id must be derived from digest")
        _require_digest(self.digest, field="digest")
        if self.protected_surface_verdict is not ProtectedSurfaceVerdict.CLEAR:
            raise ValueError(
                "persisted candidate must have CLEAR protected-surface verdict"
            )
        if _digest(self.canonical_payload()) != self.digest:
            raise ValueError("source repair candidate digest mismatch")
