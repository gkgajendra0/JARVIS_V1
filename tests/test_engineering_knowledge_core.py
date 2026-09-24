from __future__ import annotations

import jarvis.engineering_knowledge as ek
import pytest


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
