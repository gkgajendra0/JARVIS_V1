from __future__ import annotations

import json
import sqlite3

import numpy as np
from jarvis.engineering_knowledge import (
    ApplicabilityContext,
    ApplicabilityFact,
    EngineeringKnowledgeFacet,
    EngineeringKnowledgeRetrievalIndex,
    KnowledgeLifecycleService,
    RepairKnowledgeProjector,
    build_engineering_qwen_encoder,
    canonical_sha256,
)
from jarvis.incidents import IncidentService, SqliteIncidentStore
from jarvis.memory.embeddings import QWEN3_EMBEDDING_CONTRACT
from jarvis.memory.retrieval_models import LocalRetrievalModelError
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


class FakeEngineeringEncoder:
    contract = QWEN3_EMBEDDING_CONTRACT

    def encode_query(self, text: str) -> np.ndarray:
        vector = np.zeros(self.contract.dimension, dtype=np.float32)
        vector[1 if "semantic-only" in text else 0] = 1.0
        return vector

    def encode_documents(self, texts: tuple[str, ...]) -> tuple[np.ndarray, ...]:
        output: list[np.ndarray] = []
        for text in texts:
            vector = np.zeros(self.contract.dimension, dtype=np.float32)
            vector[1 if "runtime_unresponsive" in text else 0] = 1.0
            output.append(vector)
        return tuple(output)


class UnavailableEngineeringEncoder(FakeEngineeringEncoder):
    def encode_query(self, text: str) -> np.ndarray:
        raise LocalRetrievalModelError("model unavailable")

    def encode_documents(self, texts: tuple[str, ...]) -> tuple[np.ndarray, ...]:
        raise LocalRetrievalModelError("model unavailable")


def _policy(*, component: str, reason: str, suffix: str) -> RepairPolicy:
    return RepairPolicy(
        policy_id=f"repair-{suffix}-v1",
        version=1,
        trigger_source="dev_supervisor",
        component_id=component,
        reason_code=reason,
        action_kind=RepairActionKind.RESTART_RUNTIME_CHILD,
        risk_class=RepairRiskClass.R2_RESTART,
        preconditions=("same_local_revision", "restart_budget_available"),
        max_attempts=3,
        rolling_window_seconds=300,
        cooldown_seconds=2,
        backoff_multiplier=2,
        verification_contract="runtime_ready_and_live",
        health_states=(HealthState.FAILED,),
        reversible=True,
        automatic=True,
    )


def _candidate(
    store: SqliteIncidentStore,
    *,
    component: str = "runtime.voice",
    reason: str = "child_exited",
    suffix: str = "voice",
) -> tuple[str, str]:
    service = IncidentService(store)
    incident = service.create_manual(
        symptom=f"{component} {reason}",
        affected_components=(component,),
        now_epoch=100.0,
    )
    policy = _policy(component=component, reason=reason, suffix=suffix)
    trigger = RepairTrigger.create(
        trigger_id=f"trigger-{suffix}",
        component_id=component,
        reason_code=reason,
        source="dev_supervisor",
        health_state=HealthState.FAILED,
        process_exit_code=1,
        evidence_references=(f"crash_fingerprint:{suffix}",),
        observed_at_epoch=101.0,
    )
    action = RepairAction.create(
        policy,
        trigger,
        now_epoch=102.0,
        action_id=f"action-{suffix}",
    )
    attempt = RepairAttempt.start(
        incident_id=incident.incident_id,
        trigger=trigger,
        policy=policy,
        action=action,
        attempt_number=1,
        now_epoch=102.0,
        attempt_id=f"attempt-{suffix}",
    )
    verification = RepairVerificationResult.create(
        verifier_id="external_runtime_supervisor",
        verifier_version=1,
        contract_id=policy.verification_contract,
        status=RepairVerificationStatus.PASS,
        summary=f"{suffix}_stable",
        evidence_references=(f"health:{component}:healthy",),
        observed_at_epoch=110.0,
    )
    completed = attempt.complete(
        execution_result=f"{component} restart stabilized",
        verification=verification,
        post_repair_evidence=(f"health:{component}:healthy",),
        now_epoch=110.0,
    )
    service.record_repair_attempt(completed)
    projected = RepairKnowledgeProjector().project_attempt(store, completed.attempt_id)
    return projected.revision_id, completed.attempt_id


def _accept(store: SqliteIncidentStore, revision_id: str) -> None:
    KnowledgeLifecycleService(store).promote_verified_repair(
        revision_id,
        staged_at_epoch=120.0,
        accepted_at_epoch=121.0,
    )


def _context(component: str = "runtime.voice") -> ApplicabilityContext:
    return ApplicabilityContext(
        (
            ApplicabilityFact(
                target_namespace="jarvis.component",
                target_identity=component,
                attributes={},
            ),
        )
    )


def test_candidate_is_not_retrievable_until_accepted(tmp_path) -> None:
    path = tmp_path / "engineering.sqlite3"
    store = SqliteIncidentStore(path)
    revision_id, _ = _candidate(store)
    index = EngineeringKnowledgeRetrievalIndex(path)
    indexed = index.refresh_revision(revision_id, now_epoch=122.0)

    assert indexed.indexed is True
    assert indexed.embedding_indexed is False
    assert (
        index.retrieve(
            "runtime child restart",
            context=_context(),
            now_epoch=123.0,
        )
        == ()
    )

    _accept(store, revision_id)
    results = index.retrieve(
        "runtime child restart",
        context=_context(),
        now_epoch=124.0,
    )

    assert len(results) == 1
    assert results[0].revision.revision_id == revision_id
    assert results[0].lexical_rank == 1
    assert results[0].applicability.eligible is True
    index.close()
    store.close()


def test_inapplicable_exact_reference_is_filtered_before_ranking(tmp_path) -> None:
    path = tmp_path / "engineering.sqlite3"
    store = SqliteIncidentStore(path)
    revision_id, attempt_id = _candidate(store)
    _accept(store, revision_id)
    index = EngineeringKnowledgeRetrievalIndex(path)
    index.refresh_revision(revision_id, now_epoch=122.0)

    results = index.retrieve(
        f"repair-attempt:{attempt_id}",
        context=_context("runtime.vision"),
        now_epoch=123.0,
    )

    assert results == ()
    index.close()
    store.close()


def test_exact_evidence_reference_has_priority_and_provenance_envelope(
    tmp_path,
) -> None:
    path = tmp_path / "engineering.sqlite3"
    store = SqliteIncidentStore(path)
    revision_id, attempt_id = _candidate(store)
    _accept(store, revision_id)
    index = EngineeringKnowledgeRetrievalIndex(path)
    index.refresh_revision(revision_id, now_epoch=122.0)

    results = index.retrieve(
        f"repair-attempt:{attempt_id}",
        context=_context(),
        now_epoch=123.0,
    )

    assert len(results) == 1
    result = results[0]
    assert result.exact_rank == 1
    assert result.fused_score == 1.0
    assert any(
        item.canonical_reference == f"repair-attempt:{attempt_id}"
        for item in result.evidence
    )
    assert any(item.verdict.value == "pass" for item in result.attestations)
    index.close()
    store.close()


def test_dense_retrieval_uses_only_accepted_applicable_revisions(tmp_path) -> None:
    path = tmp_path / "engineering.sqlite3"
    store = SqliteIncidentStore(path)
    first_id, _ = _candidate(store, suffix="voice-exit")
    second_id, _ = _candidate(
        store,
        reason="runtime_unresponsive",
        suffix="voice-hang",
    )
    _accept(store, first_id)
    _accept(store, second_id)

    encoder = FakeEngineeringEncoder()
    index = EngineeringKnowledgeRetrievalIndex(path)
    index.refresh_revision(first_id, encoder=encoder, now_epoch=122.0)
    index.refresh_revision(second_id, encoder=encoder, now_epoch=122.0)

    results = index.retrieve(
        "semantic-only",
        context=_context(),
        encoder=encoder,
        now_epoch=123.0,
    )

    assert results
    assert results[0].revision.revision_id == second_id
    assert results[0].dense_rank == 1
    index.close()
    store.close()


def test_encoder_outage_degrades_to_lexical_retrieval(tmp_path) -> None:
    path = tmp_path / "engineering.sqlite3"
    store = SqliteIncidentStore(path)
    revision_id, _ = _candidate(store)
    _accept(store, revision_id)
    index = EngineeringKnowledgeRetrievalIndex(path)
    unavailable = UnavailableEngineeringEncoder()

    indexed = index.refresh_revision(
        revision_id,
        encoder=unavailable,
        now_epoch=122.0,
    )
    results = index.retrieve(
        "runtime child restart",
        context=_context(),
        encoder=unavailable,
        now_epoch=123.0,
    )

    assert indexed.indexed is True
    assert indexed.embedding_indexed is False
    assert indexed.embedding_reason == "encoder_unavailable"
    assert len(results) == 1
    assert results[0].lexical_rank == 1
    assert results[0].dense_rank is None
    index.close()
    store.close()


def test_stale_embedding_is_skipped_when_document_hash_differs(tmp_path) -> None:
    path = tmp_path / "engineering.sqlite3"
    store = SqliteIncidentStore(path)
    revision_id, _ = _candidate(
        store,
        reason="runtime_unresponsive",
        suffix="voice-hang",
    )
    _accept(store, revision_id)
    encoder = FakeEngineeringEncoder()
    index = EngineeringKnowledgeRetrievalIndex(path)
    index.refresh_revision(revision_id, encoder=encoder, now_epoch=122.0)
    index.close()

    connection = sqlite3.connect(path)
    connection.execute(
        """
        UPDATE engineering_knowledge_search_document
        SET content_sha256 = ?
        WHERE revision_id = ?
        """,
        ("f" * 64, revision_id),
    )
    connection.commit()
    connection.close()

    reopened = EngineeringKnowledgeRetrievalIndex(path)
    results = reopened.retrieve(
        "semantic-only",
        context=_context(),
        encoder=encoder,
        now_epoch=123.0,
    )

    assert results == ()
    reopened.close()
    store.close()


def test_unknown_facet_payload_is_not_added_to_search_document(tmp_path) -> None:
    path = tmp_path / "engineering.sqlite3"
    store = SqliteIncidentStore(path)
    revision_id, _ = _candidate(store)
    _accept(store, revision_id)
    marker = "TOP_SECRET_POISON_MARKER"
    payload = {"untrusted_instruction": marker}
    unknown = EngineeringKnowledgeFacet(
        facet_id="facet-future-untrusted",
        revision_id=revision_id,
        facet_type="future.untrusted.experimental",
        schema_id="urn:future:untrusted:v1",
        schema_version="1",
        schema_digest="d" * 64,
        producer="untrusted-test",
        payload_json=json.dumps(payload),
        payload_digest=canonical_sha256(payload),
        created_at_epoch=111.0,
    )
    store.insert_engineering_knowledge_facet(unknown)

    index = EngineeringKnowledgeRetrievalIndex(path)
    index.refresh_revision(revision_id, now_epoch=122.0)
    results = index.retrieve(
        marker,
        context=_context(),
        now_epoch=123.0,
    )

    assert results == ()
    connection = sqlite3.connect(path)
    try:
        document = connection.execute(
            """
            SELECT searchable_text
            FROM engineering_knowledge_search_document
            WHERE revision_id = ?
            """,
            (revision_id,),
        ).fetchone()
        assert document is not None
        assert marker not in str(document[0])
    finally:
        connection.close()
    index.close()
    store.close()


def test_retrieval_index_reopens_without_becoming_canonical_truth(tmp_path) -> None:
    path = tmp_path / "engineering.sqlite3"
    store = SqliteIncidentStore(path)
    revision_id, _ = _candidate(store)
    _accept(store, revision_id)

    index = EngineeringKnowledgeRetrievalIndex(path)
    index.refresh_revision(revision_id, now_epoch=122.0)
    index.close()

    connection = sqlite3.connect(path)
    connection.execute("DELETE FROM engineering_knowledge_fts")
    connection.execute("DELETE FROM engineering_knowledge_search_document")
    connection.execute("DELETE FROM engineering_knowledge_embedding")
    connection.commit()
    canonical_count = connection.execute(
        "SELECT COUNT(*) FROM engineering_knowledge_revision"
    ).fetchone()
    connection.close()
    assert canonical_count == (1,)

    rebuilt = EngineeringKnowledgeRetrievalIndex(path)
    rebuilt.rebuild_accepted(now_epoch=123.0)
    results = rebuilt.retrieve(
        "runtime child restart",
        context=_context(),
        now_epoch=124.0,
    )

    assert len(results) == 1
    assert results[0].revision.revision_id == revision_id
    rebuilt.close()
    store.close()


def test_engineering_qwen_encoder_uses_engineering_instruction() -> None:
    encoder = build_engineering_qwen_encoder(device="cpu")

    assert "engineering query" in encoder.query_instruction
    assert "applicable" in encoder.query_instruction
