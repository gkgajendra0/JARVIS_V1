"""Synthetic Phase-2J benchmark fixture for owner-machine acceptance."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from jarvis.engineering_knowledge.applicability import (
    ApplicabilityContext,
    ApplicabilityFact,
)
from jarvis.engineering_knowledge.canonical import JSONValue, canonical_sha256
from jarvis.engineering_knowledge.evaluation import (
    EngineeringKnowledgeEvaluationCase,
    EngineeringKnowledgeEvaluationHarness,
    EngineeringKnowledgeEvaluationHit,
    EngineeringKnowledgeEvaluationReport,
    EvaluationResourceProbe,
    load_engineering_knowledge_qrels,
)
from jarvis.engineering_knowledge.lifecycle import KnowledgeLifecycleService
from jarvis.engineering_knowledge.models import (
    EngineeringApplicability,
    KnowledgeSensitivity,
)
from jarvis.engineering_knowledge.projector import RepairKnowledgeProjector
from jarvis.engineering_knowledge.retrieval import (
    EngineeringKnowledgeRetrievalIndex,
    EngineeringKnowledgeRetrievalPolicy,
)
from jarvis.incidents import IncidentService, SqliteIncidentStore
from jarvis.self_model import HealthState
from jarvis.self_repair import (
    RepairAction,
    RepairActionKind,
    RepairAttempt,
    RepairPolicy,
    RepairRiskClass,
    RepairTrigger,
    RepairVerificationResult,
    RepairVerificationStatus,
)

QREL_PATH = (
    Path(__file__).resolve().parents[3]
    / "benchmarks"
    / "engineering_knowledge_qrels_v1.json"
)


@dataclass(frozen=True, slots=True)
class FixtureDocument:
    document_key: str
    revision_id: str


@dataclass(frozen=True, slots=True)
class QrelFixture:
    database_path: Path
    documents: tuple[FixtureDocument, ...]
    dynamic_queries: dict[str, str]

    @property
    def revision_to_document(self) -> dict[str, str]:
        return {
            document.revision_id: document.document_key
            for document in self.documents
        }


class FixtureQrelRetriever:
    def __init__(
        self,
        index: EngineeringKnowledgeRetrievalIndex,
        fixture: QrelFixture,
        *,
        encoder: Any | None,
        now_epoch: float,
    ) -> None:
        self._index = index
        self._fixture = fixture
        self._encoder = encoder
        self._now_epoch = now_epoch
        self._reverse = fixture.revision_to_document

    def retrieve(
        self,
        case: EngineeringKnowledgeEvaluationCase,
        *,
        limit: int,
    ) -> tuple[EngineeringKnowledgeEvaluationHit, ...]:
        context_facts = [
            ApplicabilityFact(
                target_namespace=fact.target_namespace,
                target_identity=fact.target_identity,
                attributes=fact.attributes_dict(),
            )
            for fact in case.context
        ]
        if case.query_id == "device-firmware-constraint":
            context_facts.append(
                ApplicabilityFact(
                    target_namespace="jarvis.component",
                    target_identity="device.pocket3",
                    attributes={},
                )
            )
        context = ApplicabilityContext(tuple(context_facts))
        policy = (
            EngineeringKnowledgeRetrievalPolicy.external_context()
            if "external_context" in case.tags
            else EngineeringKnowledgeRetrievalPolicy.local()
        )
        query = self._fixture.dynamic_queries.get(case.query_id, case.query_text)
        candidates = self._index.retrieve(
            query,
            context=context,
            encoder=self._encoder,
            policy=policy,
            now_epoch=self._now_epoch,
            limit=limit,
        )
        return tuple(
            EngineeringKnowledgeEvaluationHit(
                document_key=self._reverse[candidate.revision.revision_id]
            )
            for candidate in candidates
            if candidate.revision.revision_id in self._reverse
        )


def seed_qrel_fixture(database_path: Path) -> QrelFixture:
    store = SqliteIncidentStore(database_path)
    documents: list[FixtureDocument] = []
    dynamic_queries: dict[str, str] = {}
    timestamp = 1_700_000_000.0

    def add(
        document_key: str,
        *,
        component: str,
        reason: str,
        policy_id: str,
        extra_applicability: tuple[
            tuple[str, str, str, dict[str, JSONValue]], ...
        ] = (),
        sensitivity: KnowledgeSensitivity = KnowledgeSensitivity.STANDARD,
        terminal: str = "accepted",
    ) -> str:
        nonlocal timestamp
        candidate, failure_signature = _build_fixture_candidate(
            store,
            document_key=document_key,
            component=component,
            reason=reason,
            policy_id=policy_id,
            now_epoch=timestamp,
        )
        timestamp += 10.0

        if sensitivity is not candidate.revision.sensitivity:
            candidate = replace(
                candidate,
                revision=replace(
                    candidate.revision,
                    sensitivity=sensitivity,
                ),
            )

        applicability = list(candidate.applicability)
        for index, (namespace, identity, matcher, constraint) in enumerate(
            extra_applicability,
            start=1,
        ):
            applicability.append(
                EngineeringApplicability(
                    applicability_id=(
                        f"acceptance:{document_key}:applicability:{index}"
                    ),
                    revision_id=candidate.revision.revision_id,
                    target_namespace=namespace,
                    target_identity=identity,
                    matcher_type=matcher,
                    constraint_json=json.dumps(
                        constraint,
                        separators=(",", ":"),
                    ),
                    required=True,
                    created_at_epoch=candidate.revision.created_at_epoch,
                )
            )
        candidate = replace(candidate, applicability=tuple(applicability))
        write = store.persist_engineering_knowledge_candidate(candidate)
        lifecycle = KnowledgeLifecycleService(store)

        if terminal in {"accepted", "retired", "superseded"}:
            lifecycle.promote_verified_repair(
                write.revision_id,
                staged_at_epoch=timestamp,
                accepted_at_epoch=timestamp + 0.001,
            )
        if terminal == "retired":
            lifecycle.retire(
                write.revision_id,
                reason_code="acceptance_stale_fixture",
                actor="phase2j-acceptance",
                evidence_ids=(candidate.evidence[-1].evidence_id,),
                now_epoch=timestamp + 0.002,
            )
        elif terminal == "superseded":
            lifecycle.supersede(
                write.revision_id,
                reason_code="acceptance_superseded_fixture",
                actor="phase2j-acceptance",
                evidence_ids=(candidate.evidence[-1].evidence_id,),
                now_epoch=timestamp + 0.002,
            )
        elif terminal == "rejected":
            lifecycle.reject(
                write.revision_id,
                reason_code="acceptance_refuted_fixture",
                actor="phase2j-acceptance",
                evidence_ids=(candidate.evidence[-1].evidence_id,),
                now_epoch=timestamp,
            )

        documents.append(FixtureDocument(document_key, write.revision_id))
        if document_key == "repair.runtime_voice.exit.current":
            dynamic_queries["exact-crash-signature"] = failure_signature
        return write.revision_id

    add(
        "repair.runtime_voice.exit.current",
        component="runtime.voice",
        reason="child_exited",
        policy_id="runtime-voice-child-exited-v1",
    )
    add(
        "repair.runtime_vision.exit.current",
        component="runtime.vision",
        reason="child_exited",
        policy_id="runtime-vision-child-exited-v1",
    )
    add(
        "repair.memory_service.upsert.current",
        component="memory.service",
        reason="memoryservice.upsert_attributeerror",
        policy_id="memoryservice.upsert-attributeerror-v1",
    )
    add(
        "repair.runtime_voice.hang.current",
        component="runtime.voice",
        reason="runtime_unresponsive",
        policy_id="runtime-voice-unresponsive-v1",
    )
    add(
        "repair.runtime_vision.hang.current",
        component="runtime.vision",
        reason="runtime_unresponsive",
        policy_id="runtime-vision-unresponsive-v1",
    )
    add(
        "repair.qwen_embedding.v06.current",
        component="engineering.knowledge",
        reason="qwen_embedding_initialization_failure",
        policy_id="qwen-embedding-initialization-failure-v06",
        extra_applicability=(
            (
                "package",
                "qwen3-embedding",
                "version_exact",
                {"version": "0.6"},
            ),
        ),
    )
    add(
        "repair.qwen_embedding.v07.current",
        component="engineering.knowledge",
        reason="qwen_embedding_initialization_failure",
        policy_id="qwen-embedding-initialization-failure-v07",
        extra_applicability=(
            (
                "package",
                "qwen3-embedding",
                "version_exact",
                {"version": "0.7"},
            ),
        ),
    )
    add(
        "repair.pocket3.firmware2.current",
        component="device.pocket3",
        reason="pocket3_control_protocol_stopped_responding",
        policy_id="pocket3-control-protocol-recovery-v2",
        extra_applicability=(
            ("device.model", "dji.pocket3", "exact", {}),
            (
                "firmware",
                "dji.pocket3",
                "numeric_version_range",
                {"min_inclusive": "2.0", "max_exclusive": "3.0"},
            ),
        ),
    )
    add(
        "repair.pocket3.firmware3.current",
        component="device.pocket3",
        reason="pocket3_control_protocol_stopped_responding",
        policy_id="pocket3-control-protocol-recovery-v3",
        extra_applicability=(
            ("device.model", "dji.pocket3", "exact", {}),
            (
                "firmware",
                "dji.pocket3",
                "numeric_version_range",
                {"min_inclusive": "3.0", "max_exclusive": "4.0"},
            ),
        ),
    )
    add(
        "repair.runtime_voice.exit.stale",
        component="runtime.voice",
        reason="child_exited",
        policy_id="runtime-voice-child-exited-stale-v1",
        terminal="retired",
    )
    add(
        "repair.runtime_voice.exit.superseded",
        component="runtime.voice",
        reason="child_exited",
        policy_id="runtime-voice-child-exited-superseded-v1",
        terminal="superseded",
    )
    add(
        "repair.runtime_voice.exit.refuted",
        component="runtime.voice",
        reason="child_exited",
        policy_id="runtime-voice-child-exited-refuted-v1",
        terminal="rejected",
    )
    add(
        "repair.runtime_voice.private_local",
        component="runtime.voice",
        reason="local_private_runtime_repair_detail",
        policy_id="runtime-voice-private-local-v1",
        sensitivity=KnowledgeSensitivity.PRIVATE,
    )
    store.close()
    return QrelFixture(
        database_path=database_path,
        documents=tuple(documents),
        dynamic_queries=dynamic_queries,
    )


def run_fixture_benchmark(
    fixture: QrelFixture,
    *,
    encoder: Any | None,
    resource_probe: EvaluationResourceProbe | None = None,
    now_epoch: float = 1_800_000_000.0,
) -> EngineeringKnowledgeEvaluationReport:
    corpus = load_engineering_knowledge_qrels(QREL_PATH)
    index = EngineeringKnowledgeRetrievalIndex(fixture.database_path)
    indexed = index.rebuild_accepted(
        encoder=encoder,
        now_epoch=now_epoch,
    )
    if encoder is not None and not all(item.embedding_indexed for item in indexed):
        index.close()
        raise RuntimeError(
            "embedding encoder did not index every accepted fixture revision"
        )
    retriever = FixtureQrelRetriever(
        index,
        fixture,
        encoder=encoder,
        now_epoch=now_epoch,
    )
    harness = EngineeringKnowledgeEvaluationHarness(
        retriever,
        resource_probe=resource_probe,
    )
    try:
        return harness.run(corpus, k=5)
    finally:
        index.close()


def _build_fixture_candidate(
    store: SqliteIncidentStore,
    *,
    document_key: str,
    component: str,
    reason: str,
    policy_id: str,
    now_epoch: float,
) -> tuple[Any, str]:
    service = IncidentService(store)
    incident = service.create_manual(
        symptom=f"{component} {reason}",
        affected_components=(component,),
        now_epoch=now_epoch,
    )
    policy = RepairPolicy(
        policy_id=policy_id,
        version=1,
        trigger_source="phase2j_acceptance",
        component_id=component,
        reason_code=reason,
        action_kind=RepairActionKind.RESTART_RUNTIME_CHILD,
        risk_class=RepairRiskClass.R2_RESTART,
        preconditions=("same_local_revision",),
        max_attempts=3,
        rolling_window_seconds=300.0,
        cooldown_seconds=0.0,
        backoff_multiplier=1.0,
        verification_contract="acceptance_ready_and_live",
        health_states=(HealthState.FAILED,),
        reversible=True,
        automatic=True,
    )
    suffix = canonical_sha256({"document_key": document_key})[:16]
    trigger = RepairTrigger.create(
        trigger_id=f"acceptance-trigger-{suffix}",
        component_id=component,
        reason_code=reason,
        source="phase2j_acceptance",
        health_state=HealthState.FAILED,
        evidence_references=(f"acceptance:{document_key}",),
        observed_at_epoch=now_epoch + 1.0,
    )
    action = RepairAction.create(
        policy,
        trigger,
        now_epoch=now_epoch + 2.0,
        action_id=f"acceptance-action-{suffix}",
    )
    attempt = RepairAttempt.start(
        incident_id=incident.incident_id,
        trigger=trigger,
        policy=policy,
        action=action,
        attempt_number=1,
        now_epoch=now_epoch + 2.0,
        attempt_id=f"acceptance-attempt-{suffix}",
    )
    verification = RepairVerificationResult.create(
        verifier_id="phase2j_acceptance_verifier",
        verifier_version=1,
        contract_id=policy.verification_contract,
        status=RepairVerificationStatus.PASS,
        summary="acceptance_fixture_verified",
        evidence_references=(f"acceptance-verification:{document_key}",),
        observed_at_epoch=now_epoch + 3.0,
    )
    completed = attempt.complete(
        execution_result=f"{document_key} recovery completed",
        verification=verification,
        post_repair_evidence=(f"acceptance-recovered:{document_key}",),
        now_epoch=now_epoch + 3.0,
    )
    service.record_repair_attempt(completed)
    candidate = RepairKnowledgeProjector().build_candidate(
        incident=incident,
        attempt=completed,
    )
    payload = json.loads(candidate.facets[0].payload_json or "{}")
    failure_signature = str(payload["trigger"]["failure_signature"])
    return candidate, failure_signature
