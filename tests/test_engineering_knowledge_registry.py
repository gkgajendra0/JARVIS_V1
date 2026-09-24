from __future__ import annotations

import json

import pytest

import jarvis.engineering_knowledge as ek
from jarvis.incidents import SqliteIncidentStore


def _repair_payload() -> dict[str, ek.canonical.JSONValue]:
    return {
        "component_id": "runtime.voice",
        "trigger": {
            "source": "dev_supervisor",
            "reason_code": "child_exited",
            "failure_signature": "process_exit_code:1",
        },
        "repair": {
            "policy_id": "runtime-child-exit-v1",
            "policy_version": 1,
            "action_kind": "restart_runtime_child",
            "preconditions": [
                "same_local_revision",
                "restart_budget_available",
            ],
            "successful_sequence": ["restart_runtime_child"],
        },
        "verification": {
            "contract_id": "runtime_ready_and_live",
            "verdict": "recovered",
        },
        "applicability": [
            {
                "target_namespace": "jarvis.component",
                "target_identity": "runtime.voice",
                "matcher_type": "exact",
                "constraint": {},
                "required": True,
            }
        ],
        "required_resources": [],
        "revalidation": {
            "strategy": "verification_contract",
            "contract_id": "runtime_ready_and_live",
        },
    }


def _repair_facet(
    payload: dict[str, ek.canonical.JSONValue] | None = None,
    *,
    schema_digest: str | None = None,
) -> ek.EngineeringKnowledgeFacet:
    actual = payload or _repair_payload()
    handler = ek.RepairFindingV1Handler()
    return ek.EngineeringKnowledgeFacet(
        facet_id="facet-repair-1",
        revision_id="revision-1",
        facet_type=ek.REPAIR_FINDING_FACET_TYPE,
        schema_id=ek.REPAIR_FINDING_V1_SCHEMA_ID,
        schema_version=ek.REPAIR_FINDING_V1_SCHEMA_VERSION,
        schema_digest=schema_digest or handler.schema_digest,
        producer="repair-projector",
        payload_json=json.dumps(actual, separators=(",", ":")),
        payload_digest=ek.canonical_sha256(actual),
        created_at_epoch=100.0,
    )


def _insert_revision(store: SqliteIncidentStore) -> None:
    store._connection.execute(
        """
        INSERT INTO engineering_knowledge_identity (
            knowledge_id, stable_label, created_at_epoch, created_by
        ) VALUES ('knowledge-1', 'runtime recovery', 1.0, 'test')
        """
    )
    store._connection.execute(
        """
        INSERT INTO engineering_knowledge_revision (
            revision_id, knowledge_id, revision_number,
            kind_namespace, normalized_summary,
            system_from_epoch, sensitivity, freshness_state,
            canonicalization, digest_algorithm, canonical_digest,
            created_at_epoch, created_by
        ) VALUES (
            'revision-1', 'knowledge-1', 1,
            'jarvis.repair', 'runtime recovery',
            1.0, 'standard', 'current',
            'rfc8785', 'sha256',
            ?, 1.0, 'test'
        )
        """,
        ("a" * 64,),
    )
    store._connection.commit()


def test_rfc8785_digest_is_order_independent_and_payload_sensitive() -> None:
    first = {"b": 2, "a": {"z": 1, "y": [3, 4]}}
    reordered = {"a": {"y": [3, 4], "z": 1}, "b": 2}
    changed = {"a": {"y": [3, 5], "z": 1}, "b": 2}

    assert ek.canonical_sha256(first) == ek.canonical_sha256(reordered)
    assert ek.canonical_sha256(first) != ek.canonical_sha256(changed)


def test_rfc8785_uses_utf16_property_ordering() -> None:
    canonical = ek.canonicalize_json(
        {
            "\u20ac": "Euro",
            "\r": "Carriage",
            "\ufb33": "Hebrew",
            "1": "One",
            "\U0001f600": "Emoji",
            "\u0080": "Control",
            "\u00f6": "Latin",
        }
    ).decode("utf-8")

    ordered_pairs = json.loads(canonical, object_pairs_hook=lambda pairs: pairs)
    assert [key for key, _ in ordered_pairs] == [
        "\r",
        "1",
        "\u0080",
        "ö",
        "€",
        "😀",
        "דּ",
    ]


def test_duplicate_json_property_names_fail_closed() -> None:
    with pytest.raises(
        ek.EngineeringKnowledgeDuplicateKeyError,
        match="duplicate JSON property",
    ):
        ek.parse_json_object('{"component":"a","component":"b"}')




def test_registered_schema_identity_is_stable_against_descriptor_mutation() -> None:
    handler = ek.RepairFindingV1Handler()
    descriptor = handler.schema_descriptor
    descriptor["facet_type"] = "mutated"

    assert handler.schema_digest == ek.REPAIR_FINDING_V1_SCHEMA_DIGEST
    assert handler.schema_descriptor["facet_type"] == ek.REPAIR_FINDING_FACET_TYPE
    registry = ek.EngineeringKnowledgeFacetRegistry()
    registry.register(handler)

def test_default_registry_validates_repair_finding_v1() -> None:
    registry = ek.build_default_facet_registry()
    facet = _repair_facet()

    validated = registry.validate_for_decision(facet)
    assessment = registry.assess_for_decision(facet)

    assert assessment.eligible is True
    assert assessment.reason_code == "validated_registered_facet"
    assert validated.schema_key.facet_type == ek.REPAIR_FINDING_FACET_TYPE
    assert validated.duplicate_key.startswith("sha256:")
    assert "runtime.voice" in validated.searchable_text
    assert "child_exited" in validated.searchable_text
    assert validated.applicability == (
        ek.FacetApplicabilityConstraint(
            target_namespace="jarvis.component",
            target_identity="runtime.voice",
            matcher_type="exact",
            constraint={},
            required=True,
        ),
    )


def test_registered_repair_facet_rejects_malformed_semantics() -> None:
    payload = _repair_payload()
    verification = payload["verification"]
    assert isinstance(verification, dict)
    verification["verdict"] = "inconclusive"
    facet = _repair_facet(payload)

    registry = ek.build_default_facet_registry()

    with pytest.raises(ek.FacetValidationError, match="must be 'recovered'"):
        registry.validate_for_decision(facet)

    assessment = registry.assess_for_decision(facet)
    assert assessment.eligible is False
    assert assessment.reason_code == "facet_validation_failure"


def test_registered_facet_rejects_schema_digest_drift() -> None:
    facet = _repair_facet(schema_digest="f" * 64)
    assessment = ek.build_default_facet_registry().assess_for_decision(facet)

    assert assessment.eligible is False
    assert assessment.reason_code == "facet_integrity_failure"


def test_applicability_matcher_boundary_fails_closed_until_registered() -> None:
    facet = _repair_facet()
    registry = ek.build_default_facet_registry()
    matchers = ek.ApplicabilityMatcherRegistry()

    blocked = registry.assess_for_decision(
        facet,
        applicability_registry=matchers,
    )
    assert blocked.eligible is False
    assert blocked.reason_code == "unsupported_applicability_matcher"

    matchers.register(target_namespace="jarvis.component", matcher_type="exact")
    allowed = registry.assess_for_decision(
        facet,
        applicability_registry=matchers,
    )
    assert allowed.eligible is True


def test_unknown_facet_persists_but_is_ineligible_for_decision_use(tmp_path) -> None:
    store = SqliteIncidentStore(tmp_path / "incidents.sqlite3")
    try:
        _insert_revision(store)
        payload = {"future_field": "preserve me", "version": 1}
        facet = ek.EngineeringKnowledgeFacet(
            facet_id="facet-future-1",
            revision_id="revision-1",
            facet_type="future.experimental.finding",
            schema_id="urn:future:facet:v1",
            schema_version="1",
            schema_digest="c" * 64,
            producer="future-producer",
            payload_json=json.dumps(payload, separators=(",", ":")),
            payload_digest=ek.canonical_sha256(payload),
            created_at_epoch=2.0,
        )

        store.insert_engineering_knowledge_facet(facet)

        assert store.get_engineering_knowledge_facet(facet.facet_id) == facet
        assert store.list_engineering_knowledge_facets("revision-1") == (facet,)

        assessment = ek.build_default_facet_registry().assess_for_decision(facet)
        assert assessment.eligible is False
        assert assessment.reason_code == "unsupported_facet_schema"
    finally:
        store.close()


def test_payload_digest_changes_when_canonical_payload_changes() -> None:
    before = _repair_payload()
    after = _repair_payload()
    trigger = after["trigger"]
    assert isinstance(trigger, dict)
    trigger["failure_signature"] = "process_exit_code:2"

    assert ek.canonical_sha256(before) != ek.canonical_sha256(after)
