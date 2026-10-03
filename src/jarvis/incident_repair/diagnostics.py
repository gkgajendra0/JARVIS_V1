"""Typed diagnostic evidence, hypothesis and finalization actions for Phase 6."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.engineering_change import ChangeArtifact, ChangeStore
from jarvis.incident_repair.models import (
    DiagnosisDisposition,
    DiagnosticHypothesis,
    HypothesisState,
    IncidentDiagnosis,
    ReproductionState,
)
from jarvis.work.brain import BrainAction
from jarvis.work.models import WorkItem, WorkStep, WorkType


class DiagnosticProtocolError(RuntimeError):
    """Typed diagnostic evidence or finalization failed validation."""


class KnowledgeRevisionReader(Protocol):
    def read_revision(self, revision_id: str) -> dict[str, object] | None: ...


@dataclass(frozen=True, slots=True)
class DiagnosticWorkContext:
    change_id: str
    work_id: str
    source_revision: str
    incident_id: str
    incident_artifact: ChangeArtifact
    incident_package: dict[str, object]
    knowledge_revision_ids: tuple[str, ...]
    canonical_evidence_ids: tuple[str, ...]


class DiagnosticContextResolver:
    """Resolve canonical Phase-6 artifacts for one DIAGNOSTICS WorkItem."""

    def __init__(self, store: ChangeStore) -> None:
        if not isinstance(store, ChangeStore):
            raise TypeError("store must be ChangeStore")
        self._store = store

    @property
    def store(self) -> ChangeStore:
        return self._store

    def context_for(self, work_id: str) -> DiagnosticWorkContext:
        normalized = str(work_id).strip()
        stage = self._store.stage_for_work(normalized)
        if stage is None:
            raise DiagnosticProtocolError(
                "diagnostic WorkItem is not linked to an EngineeringChange"
            )
        change = self._store.require(stage.change_id)
        process = self._store.process_contract(
            change.process_key,
            change.process_version,
        )
        if stage.stage_key != process.architecture_source_stage.stage_key:
            raise DiagnosticProtocolError(
                "diagnostic context requested for a non-diagnostics stage"
            )
        trigger_artifact = self._store.latest_artifact(
            change.change_id,
            "incident_repair_trigger",
        )
        incident_artifact = self._store.latest_artifact(
            change.change_id,
            "incident_evidence",
        )
        if trigger_artifact is None or incident_artifact is None:
            raise DiagnosticProtocolError(
                "diagnostic trigger/evidence artifacts are incomplete"
            )
        source_revision = (
            str(trigger_artifact.payload.get("source_revision") or "").strip().lower()
        )
        incident_id = str(incident_artifact.payload.get("incident_id") or "").strip()
        if not source_revision or not incident_id:
            raise DiagnosticProtocolError("diagnostic artifact identity is incomplete")

        raw_evidence = incident_artifact.payload.get("evidence")
        evidence_ids: list[str] = []
        if isinstance(raw_evidence, list):
            for item in raw_evidence:
                if not isinstance(item, dict):
                    continue
                evidence_id = str(item.get("evidence_id") or "").strip()
                if evidence_id and evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)

        raw_knowledge = incident_artifact.payload.get("knowledge_revision_ids")
        knowledge_ids = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in (raw_knowledge if isinstance(raw_knowledge, list) else [])
                if str(item).strip()
            )
        )
        return DiagnosticWorkContext(
            change_id=change.change_id,
            work_id=normalized,
            source_revision=source_revision,
            incident_id=incident_id,
            incident_artifact=incident_artifact,
            incident_package=dict(incident_artifact.payload),
            knowledge_revision_ids=knowledge_ids,
            canonical_evidence_ids=tuple(evidence_ids),
        )

    def completed_steps(self, work_id: str) -> tuple[WorkStep, ...]:
        return tuple(
            step
            for step in self._store.work.list_steps(str(work_id).strip())
            if step.state.value == "completed"
        )

    def known_evidence_ids(self, work_id: str) -> frozenset[str]:
        context = self.context_for(work_id)
        known = set(context.canonical_evidence_ids)
        known.add(context.incident_artifact.artifact_id)
        known.add(context.incident_artifact.digest)
        package_id = str(context.incident_package.get("package_id") or "").strip()
        if package_id:
            known.add(package_id)

        for step in self.completed_steps(work_id):
            known.add(step.step_id)
            evidence_id = step.observation.get("evidence_id")
            if isinstance(evidence_id, str) and evidence_id.strip():
                known.add(evidence_id.strip())
            diagnosis = step.observation.get("diagnosis")
            if isinstance(diagnosis, dict):
                diagnosis_id = str(diagnosis.get("diagnosis_id") or "").strip()
                if diagnosis_id:
                    known.add(diagnosis_id)
        return frozenset(known)


def _hypothesis_from_payload(payload: object) -> DiagnosticHypothesis:
    if not isinstance(payload, dict):
        raise DiagnosticProtocolError("stored hypothesis payload is invalid")
    try:
        recreated = DiagnosticHypothesis.create(
            statement=str(payload["statement"]),
            affected_components=tuple(payload.get("affected_components") or ()),
            affected_paths=tuple(payload.get("affected_paths") or ()),
            supporting_evidence_ids=tuple(payload.get("supporting_evidence_ids") or ()),
            refuting_evidence_ids=tuple(payload.get("refuting_evidence_ids") or ()),
            status=HypothesisState(str(payload["status"])),
            discriminator=payload.get("discriminator"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DiagnosticProtocolError(
            "stored hypothesis payload failed validation"
        ) from exc
    if recreated.hypothesis_id != str(payload.get("hypothesis_id") or ""):
        raise DiagnosticProtocolError("stored hypothesis identity digest mismatch")
    return recreated


def recorded_hypotheses(
    steps: tuple[WorkStep, ...],
) -> tuple[DiagnosticHypothesis, ...]:
    output: list[DiagnosticHypothesis] = []
    for step in steps:
        if step.kind != "diag_record_hypothesis" or step.state.value != "completed":
            continue
        hypothesis = _hypothesis_from_payload(step.observation.get("hypothesis"))
        if any(item.hypothesis_id == hypothesis.hypothesis_id for item in output):
            output = [
                item
                for item in output
                if item.hypothesis_id != hypothesis.hypothesis_id
            ]
        output.append(hypothesis)
    return tuple(output)


def reproduction_state_from_steps(
    steps: tuple[WorkStep, ...],
) -> tuple[ReproductionState | None, str | None]:
    for step in reversed(steps):
        if step.kind != "diag_run_reproduction" or step.state.value != "completed":
            continue
        raw = step.observation.get("reproduction_state")
        try:
            state = ReproductionState(str(raw))
        except ValueError:
            return ReproductionState.INCONCLUSIVE, None
        evidence_id = step.observation.get("evidence_id")
        return (
            state,
            evidence_id if isinstance(evidence_id, str) else None,
        )
    return None, None


def suspicious_location_scores(
    steps: tuple[WorkStep, ...],
    *,
    limit: int = 50,
) -> tuple[dict[str, object], ...]:
    """Compute deterministic Ochiai line scores from fail/pass coverage samples."""

    failing: list[dict[str, set[int]]] = []
    passing: list[dict[str, set[int]]] = []
    for step in steps:
        if step.kind != "diag_run_reproduction" or step.state.value != "completed":
            continue
        try:
            state = ReproductionState(str(step.observation.get("reproduction_state")))
        except ValueError:
            continue
        if state not in {
            ReproductionState.REPRODUCED,
            ReproductionState.NOT_REPRODUCED,
        }:
            continue
        raw_files = step.observation.get("coverage_files")
        if not isinstance(raw_files, list):
            continue
        sample: dict[str, set[int]] = {}
        for raw in raw_files:
            if not isinstance(raw, dict):
                continue
            path = str(raw.get("path") or "").strip()
            raw_lines = raw.get("executed_lines")
            if not path or not isinstance(raw_lines, list):
                continue
            lines = {
                int(item)
                for item in raw_lines
                if isinstance(item, int) and not isinstance(item, bool) and item > 0
            }
            if lines:
                sample[path] = lines
        if not sample:
            continue
        if state is ReproductionState.REPRODUCED:
            failing.append(sample)
        else:
            passing.append(sample)

    if not failing or not passing:
        return ()

    all_locations: set[tuple[str, int]] = set()
    for sample in (*failing, *passing):
        for path, lines in sample.items():
            all_locations.update((path, line) for line in lines)

    total_failed = len(failing)
    scored: list[tuple[float, str, int, int, int]] = []
    for path, line in sorted(all_locations):
        fail_covered = sum(line in sample.get(path, set()) for sample in failing)
        pass_covered = sum(line in sample.get(path, set()) for sample in passing)
        denominator = math.sqrt(total_failed * (fail_covered + pass_covered))
        score = 0.0 if denominator == 0 else fail_covered / denominator
        scored.append(
            (
                score,
                path,
                line,
                fail_covered,
                pass_covered,
            )
        )

    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    bound = max(1, min(int(limit), 200))
    return tuple(
        {
            "path": path,
            "line": line,
            "score": round(score, 6),
            "failing_samples_covered": fail_covered,
            "passing_samples_covered": pass_covered,
            "formula": "ochiai.v1",
        }
        for score, path, line, fail_covered, pass_covered in scored[:bound]
    )


class DiagnosticGetIncidentExecutor:
    descriptor = BrainAction(
        name="diag_get_incident",
        description=(
            "Read the canonical bounded/redacted incident evidence package already "
            "admitted for this diagnostic WorkItem."
        ),
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(self, resolver: DiagnosticContextResolver) -> None:
        self._resolver = resolver

    def resource_keys(
        self, work: WorkItem, parameters: dict[str, Any]
    ) -> tuple[str, ...]:
        del work, parameters
        return ()

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del parameters
        context = self._resolver.context_for(work.work_id)
        return {
            "evidence_id": context.incident_artifact.artifact_id,
            "artifact_digest": context.incident_artifact.digest,
            "incident": context.incident_package,
            "source_revision": context.source_revision,
        }


class DiagnosticRetrieveKnowledgeExecutor:
    descriptor = BrainAction(
        name="diag_retrieve_knowledge",
        description=(
            "Read accepted EngineeringKnowledge revision references admitted into "
            "the incident package. Knowledge is advisory evidence, never authority."
        ),
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(
        self,
        resolver: DiagnosticContextResolver,
        *,
        reader: KnowledgeRevisionReader | None = None,
    ) -> None:
        self._resolver = resolver
        self._reader = reader

    def resource_keys(
        self, work: WorkItem, parameters: dict[str, Any]
    ) -> tuple[str, ...]:
        del work, parameters
        return ()

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del parameters
        context = self._resolver.context_for(work.work_id)
        rows: list[dict[str, object]] = []
        for revision_id in context.knowledge_revision_ids:
            row: dict[str, object] = {"revision_id": revision_id}
            if self._reader is not None:
                detail = await asyncio.to_thread(
                    self._reader.read_revision,
                    revision_id,
                )
                if detail is not None:
                    row["detail"] = detail
            rows.append(row)
        digest = hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "evidence_id": f"knowledge_bundle_{digest[:16]}",
            "revision_ids": list(context.knowledge_revision_ids),
            "revisions": rows,
            "advisory_only": True,
        }


class DiagnosticRecordHypothesisExecutor:
    descriptor = BrainAction(
        name="diag_record_hypothesis",
        description=(
            "Persist one typed diagnostic hypothesis bound only to known evidence IDs. "
            "No confidence score can mark a hypothesis supported."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "statement": {"type": "string", "minLength": 1, "maxLength": 2000},
                "affected_components": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 180},
                    "maxItems": 20,
                },
                "affected_paths": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "maxItems": 50,
                },
                "supporting_evidence_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 200},
                    "maxItems": 50,
                },
                "refuting_evidence_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 200},
                    "maxItems": 50,
                },
                "status": {
                    "type": "string",
                    "enum": [
                        "proposed",
                        "supported",
                        "refuted",
                        "inconclusive",
                    ],
                },
                "discriminator": {
                    "type": ["string", "null"],
                    "maxLength": 2000,
                },
            },
            "required": ["statement", "status"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(self, resolver: DiagnosticContextResolver) -> None:
        self._resolver = resolver

    def resource_keys(
        self, work: WorkItem, parameters: dict[str, Any]
    ) -> tuple[str, ...]:
        del work, parameters
        return ()

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        known = self._resolver.known_evidence_ids(work.work_id)
        supporting = tuple(
            str(item).strip()
            for item in (parameters.get("supporting_evidence_ids") or [])
            if str(item).strip()
        )
        refuting = tuple(
            str(item).strip()
            for item in (parameters.get("refuting_evidence_ids") or [])
            if str(item).strip()
        )
        unknown = tuple(
            sorted({item for item in (*supporting, *refuting) if item not in known})
        )
        if unknown:
            raise DiagnosticProtocolError(
                "hypothesis references stale or unknown evidence IDs: "
                + ", ".join(unknown)
            )

        try:
            status = HypothesisState(str(parameters.get("status")))
        except ValueError as exc:
            raise DiagnosticProtocolError("invalid hypothesis status") from exc
        hypothesis = DiagnosticHypothesis.create(
            statement=str(parameters.get("statement") or ""),
            affected_components=tuple(
                str(item) for item in (parameters.get("affected_components") or [])
            ),
            affected_paths=tuple(
                str(item) for item in (parameters.get("affected_paths") or [])
            ),
            supporting_evidence_ids=supporting,
            refuting_evidence_ids=refuting,
            status=status,
            discriminator=parameters.get("discriminator"),
        )
        return {
            "evidence_id": hypothesis.hypothesis_id,
            "hypothesis": hypothesis.canonical_payload(),
        }


class DiagnosticFinalizeExecutor:
    descriptor = BrainAction(
        name="diag_finalize",
        description=(
            "Validate and persist the final structured diagnosis. Supported repair "
            "requires a selected evidence-supported hypothesis plus verification targets; "
            "otherwise finalize truthfully as inconclusive."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "selected_hypothesis_id": {
                    "type": ["string", "null"],
                    "maxLength": 200,
                },
                "affected_paths": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "maxItems": 50,
                },
                "affected_components": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 180},
                    "maxItems": 20,
                },
                "proposed_repair_scope": {
                    "type": ["string", "null"],
                    "maxLength": 4000,
                },
                "verification_targets": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 500},
                    "maxItems": 30,
                },
                "reason_codes": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 180},
                    "maxItems": 30,
                },
                "disposition": {
                    "type": "string",
                    "enum": ["supported_repair", "inconclusive"],
                },
                "reproduction_impossible_reason": {
                    "type": ["string", "null"],
                    "maxLength": 2000,
                },
            },
            "required": ["disposition"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DIAGNOSTICS})

    def __init__(self, resolver: DiagnosticContextResolver) -> None:
        self._resolver = resolver

    def resource_keys(
        self, work: WorkItem, parameters: dict[str, Any]
    ) -> tuple[str, ...]:
        del work, parameters
        return ()

    @staticmethod
    def _persist_if_changed(
        store: ChangeStore,
        *,
        change_id: str,
        payload: dict[str, object],
    ) -> ChangeArtifact:
        latest = store.latest_artifact(change_id, "diagnosis")
        if latest is not None and latest.payload == payload:
            return latest
        return store.add_artifact(
            change_id,
            kind="diagnosis",
            payload=payload,
        )

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._resolver.context_for(work.work_id)
        steps = self._resolver.completed_steps(work.work_id)
        hypotheses = recorded_hypotheses(steps)
        if not hypotheses:
            raise DiagnosticProtocolError(
                "final diagnosis requires at least one recorded hypothesis"
            )

        reproduction_state, reproduction_evidence_id = reproduction_state_from_steps(
            steps
        )
        impossible_reason = str(
            parameters.get("reproduction_impossible_reason") or ""
        ).strip()
        if reproduction_state is None:
            if not impossible_reason:
                raise DiagnosticProtocolError(
                    "final diagnosis requires reproduction evidence or a typed "
                    "reproduction-impossible reason"
                )
            reproduction_state = ReproductionState.INCONCLUSIVE

        selected = parameters.get("selected_hypothesis_id")
        selected_id = None if selected is None else str(selected).strip() or None
        known_hypothesis_ids = {item.hypothesis_id for item in hypotheses}
        if selected_id is not None and selected_id not in known_hypothesis_ids:
            raise DiagnosticProtocolError("selected hypothesis is stale or unknown")

        try:
            disposition = DiagnosisDisposition(str(parameters.get("disposition")))
        except ValueError as exc:
            raise DiagnosticProtocolError("invalid diagnosis disposition") from exc

        evidence_ids = list(context.canonical_evidence_ids)
        for hypothesis in hypotheses:
            for evidence_id in (
                *hypothesis.supporting_evidence_ids,
                *hypothesis.refuting_evidence_ids,
            ):
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
        if reproduction_evidence_id and reproduction_evidence_id not in evidence_ids:
            evidence_ids.append(reproduction_evidence_id)

        known_evidence = self._resolver.known_evidence_ids(work.work_id)
        unknown = [item for item in evidence_ids if item not in known_evidence]
        if unknown:
            raise DiagnosticProtocolError(
                "final diagnosis references stale or unknown evidence IDs"
            )

        reason_codes = [
            str(item).strip()
            for item in (parameters.get("reason_codes") or [])
            if str(item).strip()
        ]
        if impossible_reason:
            reason_codes.append("reproduction_impossible")

        diagnosis = IncidentDiagnosis.create(
            incident_id=context.incident_id,
            change_id=context.change_id,
            work_id=work.work_id,
            source_revision=context.source_revision,
            evidence_ids=tuple(evidence_ids),
            knowledge_revision_ids=context.knowledge_revision_ids,
            reproduction_state=reproduction_state,
            hypotheses=hypotheses,
            selected_hypothesis_id=selected_id,
            affected_paths=tuple(
                str(item) for item in (parameters.get("affected_paths") or [])
            ),
            affected_components=tuple(
                str(item) for item in (parameters.get("affected_components") or [])
            ),
            proposed_repair_scope=parameters.get("proposed_repair_scope"),
            verification_targets=tuple(
                str(item) for item in (parameters.get("verification_targets") or [])
            ),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            disposition=disposition,
            now_epoch=work.updated_at.timestamp(),
        )
        suspicious = suspicious_location_scores(steps)
        diagnosis_payload: dict[str, object] = {
            "diagnosis_id": diagnosis.diagnosis_id,
            **diagnosis.canonical_payload(),
            "digest": diagnosis.digest,
        }
        artifact_payload: dict[str, object] = {
            "diagnosis": diagnosis_payload,
            "suspicious_locations": list(suspicious),
            "reproduction_impossible_reason": impossible_reason or None,
        }
        artifact = self._persist_if_changed(
            self._resolver.store,
            change_id=context.change_id,
            payload=artifact_payload,
        )
        return {
            "evidence_id": diagnosis.diagnosis_id,
            "finalized": True,
            "diagnosis": diagnosis_payload,
            "diagnosis_artifact_id": artifact.artifact_id,
            "diagnosis_artifact_digest": artifact.digest,
            "suspicious_locations": list(suspicious),
            "reproduction_impossible_reason": impossible_reason or None,
        }


def build_diagnostic_protocol_executors(
    resolver: DiagnosticContextResolver,
    *,
    knowledge_reader: KnowledgeRevisionReader | None = None,
) -> tuple[object, ...]:
    return (
        DiagnosticGetIncidentExecutor(resolver),
        DiagnosticRetrieveKnowledgeExecutor(
            resolver,
            reader=knowledge_reader,
        ),
        DiagnosticRecordHypothesisExecutor(resolver),
        DiagnosticFinalizeExecutor(resolver),
    )
