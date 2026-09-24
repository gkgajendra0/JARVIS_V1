from __future__ import annotations

import sqlite3

import pytest

from jarvis import engineering_knowledge as ek
from jarvis.incidents import SqliteIncidentStore


SHA_A = "a" * 64
SHA_B = "b" * 64


def _revision(**overrides: object) -> ek.EngineeringKnowledgeRevision:
    values: dict[str, object] = {
        "revision_id": "revision-1",
        "knowledge_id": "knowledge-1",
        "revision_number": 1,
        "kind_namespace": "JARVIS.REPAIR",
        "normalized_summary": "runtime child restart recovered readiness",
        "system_from_epoch": 100.0,
        "sensitivity": ek.KnowledgeSensitivity.STANDARD,
        "freshness_state": ek.KnowledgeFreshnessState.CURRENT,
        "canonical_digest": SHA_A,
        "created_at_epoch": 100.0,
        "created_by": "repair-projector",
    }
    values.update(overrides)
    return ek.EngineeringKnowledgeRevision(**values)  # type: ignore[arg-type]


def test_engineering_knowledge_contracts_normalize_open_namespaces() -> None:
    identity = ek.EngineeringKnowledgeIdentity(
        knowledge_id=" knowledge-1 ",
        stable_label=" Runtime recovery ",
        created_at_epoch=100,
        created_by=" phase2-test ",
    )
    revision = _revision()
    applicability = ek.EngineeringApplicability(
        applicability_id="app-1",
        revision_id=revision.revision_id,
        target_namespace=" JARVIS.COMPONENT ",
        target_identity="runtime.voice",
        matcher_type=" EXACT ",
        constraint_json='{"component_id":"runtime.voice"}',
        required=True,
        created_at_epoch=100,
    )

    assert identity.knowledge_id == "knowledge-1"
    assert identity.stable_label == "Runtime recovery"
    assert revision.kind_namespace == "jarvis.repair"
    assert applicability.target_namespace == "jarvis.component"
    assert applicability.matcher_type == "exact"


def test_revision_enforces_temporal_and_digest_contract() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        _revision(canonical_digest="short")

    with pytest.raises(ValueError, match="valid_to_epoch"):
        _revision(valid_from_epoch=20.0, valid_to_epoch=10.0)

    with pytest.raises(ValueError, match="system_to_epoch"):
        _revision(system_from_epoch=20.0, system_to_epoch=10.0)

    with pytest.raises(ValueError, match="same revision"):
        _revision(parent_revision_id="revision-1")


def test_facet_requires_exactly_one_payload_form() -> None:
    facet = ek.EngineeringKnowledgeFacet(
        facet_id="facet-1",
        revision_id="revision-1",
        facet_type="JARVIS.REPAIR.PLAYBOOK",
        schema_id="urn:jarvis:schema:repair-playbook:v1",
        schema_version="1",
        schema_digest=SHA_A,
        producer="phase2-test",
        payload_digest=SHA_B,
        payload_json='{"action":"restart_runtime_child"}',
        created_at_epoch=100,
    )
    assert facet.facet_type == "jarvis.repair.playbook"

    with pytest.raises(ValueError, match="exactly one"):
        ek.EngineeringKnowledgeFacet(
            facet_id="facet-2",
            revision_id="revision-1",
            facet_type="jarvis.repair.playbook",
            schema_id="urn:jarvis:schema:repair-playbook:v1",
            schema_version="1",
            schema_digest=SHA_A,
            producer="phase2-test",
            payload_digest=SHA_B,
            created_at_epoch=100,
        )

    with pytest.raises(ValueError, match="exactly one"):
        ek.EngineeringKnowledgeFacet(
            facet_id="facet-3",
            revision_id="revision-1",
            facet_type="jarvis.repair.playbook",
            schema_id="urn:jarvis:schema:repair-playbook:v1",
            schema_version="1",
            schema_digest=SHA_A,
            producer="phase2-test",
            payload_digest=SHA_B,
            payload_json='{"action":"restart_runtime_child"}',
            protected_payload_ref="protected:facet-3",
            created_at_epoch=100,
        )


def test_evidence_and_attestation_keep_verification_separate_from_confidence() -> None:
    evidence = ek.EngineeringEvidence(
        evidence_id="evidence-1",
        evidence_type="repair_verifier",
        source_class="authoritative_runtime",
        canonical_reference="repair-attempt:attempt-1",
        summary="readiness and liveness passed",
        observed_at_epoch=110,
        occurred_at_epoch=110,
        sensitivity=ek.KnowledgeSensitivity.STANDARD,
        producer="runtime-verifier",
        integrity_algorithm="SHA256",
        integrity_digest=SHA_A,
        created_at_epoch=110,
    )
    attestation = ek.EngineeringAttestation(
        attestation_id="attestation-1",
        subject_type="knowledge_revision",
        subject_id="revision-1",
        subject_digest=SHA_B,
        predicate_type="urn:jarvis:verification:repair:v1",
        producer="runtime-verifier",
        expected_contract_json='{"contract":"runtime_ready_and_live"}',
        observed_result_json='{"status":"pass"}',
        verdict=ek.AttestationVerdict.PASS,
        evidence_ids=(evidence.evidence_id,),
        observed_at_epoch=110,
        created_at_epoch=110,
    )

    assert evidence.integrity_algorithm == "sha256"
    assert attestation.verdict is ek.AttestationVerdict.PASS
    assert attestation.evidence_ids == ("evidence-1",)


def test_lifecycle_event_is_typed_and_evidence_serialization_is_deterministic() -> None:
    event = ek.KnowledgeLifecycleEvent(
        event_id="event-1",
        revision_id="revision-1",
        from_state=None,
        to_state=ek.KnowledgeLifecycleState.CANDIDATE,
        reason_code=" VERIFIED_REPAIR_PROJECTED ",
        actor="repair-projector",
        evidence_ids=("evidence-1", "evidence-1", "evidence-2"),
        occurred_at_epoch=120,
    )

    assert event.reason_code == "verified_repair_projected"
    assert event.evidence_ids == ("evidence-1", "evidence-2")
    assert ek.lifecycle_evidence_json(event) == '["evidence-1","evidence-2"]'

    with pytest.raises(ValueError, match="same state"):
        ek.KnowledgeLifecycleEvent(
            event_id="event-2",
            revision_id="revision-1",
            from_state=ek.KnowledgeLifecycleState.STAGED,
            to_state=ek.KnowledgeLifecycleState.STAGED,
            reason_code="invalid",
            actor="test",
            evidence_ids=(),
            occurred_at_epoch=121,
        )


def test_phase2a_schema_is_added_without_mutating_phase1_tables(tmp_path) -> None:
    path = tmp_path / "incidents.sqlite3"
    store = SqliteIncidentStore(path)
    try:
        store._connection.execute(
            """
            INSERT INTO engineering_knowledge_identity (
                knowledge_id, stable_label, created_at_epoch, created_by
            ) VALUES (?, ?, ?, ?)
            """,
            ("knowledge-1", "runtime recovery", 100.0, "phase2-test"),
        )
        store._connection.execute(
            """
            INSERT INTO engineering_knowledge_revision (
                revision_id, knowledge_id, revision_number,
                kind_namespace, normalized_summary,
                system_from_epoch, sensitivity, freshness_state,
                canonicalization, digest_algorithm, canonical_digest,
                created_at_epoch, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "revision-1",
                "knowledge-1",
                1,
                "jarvis.repair",
                "runtime child restart recovered readiness",
                100.0,
                "standard",
                "current",
                "rfc8785",
                "sha256",
                SHA_A,
                100.0,
                "phase2-test",
            ),
        )
        store._connection.execute(
            """
            INSERT INTO engineering_knowledge_lifecycle_event (
                event_id, revision_id, from_state, to_state,
                reason_code, actor, policy_id, evidence_ids_json,
                occurred_at_epoch
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "event-1",
                "revision-1",
                None,
                "candidate",
                "created",
                "phase2-test",
                None,
                "[]",
                100.0,
            ),
        )
        store._connection.commit()

        state = store._connection.execute(
            """
            SELECT lifecycle_state
            FROM engineering_knowledge_revision_state
            WHERE revision_id = ?
            """,
            ("revision-1",),
        ).fetchone()
        assert state == ("candidate",)

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store._connection.execute(
                """
                UPDATE engineering_knowledge_revision
                SET normalized_summary = 'mutated'
                WHERE revision_id = 'revision-1'
                """
            )
    finally:
        store.close()


def test_phase2a_revision_delete_is_fail_closed(tmp_path) -> None:
    path = tmp_path / "incidents.sqlite3"
    store = SqliteIncidentStore(path)
    try:
        connection = store._connection
        connection.execute(
            """
            INSERT INTO engineering_knowledge_identity (
                knowledge_id, created_at_epoch, created_by
            ) VALUES ('knowledge-1', 1.0, 'test')
            """
        )
        connection.execute(
            """
            INSERT INTO engineering_knowledge_revision (
                revision_id, knowledge_id, revision_number,
                kind_namespace, normalized_summary,
                system_from_epoch, sensitivity, freshness_state,
                canonicalization, digest_algorithm, canonical_digest,
                created_at_epoch, created_by
            ) VALUES (
                'revision-1', 'knowledge-1', 1,
                'jarvis.repair', 'repair summary',
                1.0, 'standard', 'current',
                'rfc8785', 'sha256',
                ?, 1.0, 'test'
            )
            """,
            (SHA_A,),
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "DELETE FROM engineering_knowledge_revision "
                "WHERE revision_id = 'revision-1'"
            )
    finally:
        store.close()
