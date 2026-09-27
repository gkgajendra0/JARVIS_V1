from __future__ import annotations

import json

from jarvis.incident_repair import (
    IncidentEvidencePackager,
    IncidentEvidencePolicy,
)
from jarvis.incidents.models import EvidenceReference, IncidentRecord


REVISION = "a" * 40
TRIGGER_DIGEST = "b" * 64


def _incident_with(*evidence: EvidenceReference) -> IncidentRecord:
    incident = IncidentRecord.create(
        title="voice runtime crash",
        symptom="runtime exited during provider recovery",
        affected_components=("voice_runtime",),
        now_epoch=100.0,
    )
    for item in evidence:
        incident = incident.add_evidence(item, now_epoch=101.0)
    return incident


def test_evidence_package_excludes_secret_bearing_material() -> None:
    safe = EvidenceReference.create(
        kind="crash_fingerprint",
        reference="crash:voice:123",
        summary="exit_code=1; revision=abc",
        component_id="voice_runtime",
        occurred_at_epoch=100.0,
    )
    secret = EvidenceReference.create(
        kind="structured_log",
        reference="log:secret",
        summary="api_key=THISISASECRETVALUE123456",
        component_id="voice_runtime",
        occurred_at_epoch=100.0,
    )
    package = IncidentEvidencePackager().build(
        incident=_incident_with(safe, secret),
        source_revision=REVISION,
        trigger_digest=TRIGGER_DIGEST,
        now_epoch=102.0,
    )

    assert [item.evidence_id for item in package.evidence] == [safe.evidence_id]
    excluded = {item.evidence_id: item for item in package.excluded_evidence}
    assert secret.evidence_id in excluded
    assert "secret_prohibited" in excluded[secret.evidence_id].reason_codes

    serialized = json.dumps(package.to_payload(), sort_keys=True)
    assert "THISISASECRETVALUE123456" not in serialized
    assert "api_key=" not in serialized


def test_evidence_package_fails_closed_on_unregistered_kind() -> None:
    unknown = EvidenceReference.create(
        kind="raw_environment_dump",
        reference="env:1",
        summary="PATH=safe-looking-but-unregistered",
        component_id="voice_runtime",
        occurred_at_epoch=100.0,
    )
    package = IncidentEvidencePackager().build(
        incident=_incident_with(unknown),
        source_revision=REVISION,
        trigger_digest=TRIGGER_DIGEST,
        now_epoch=102.0,
    )

    assert package.evidence == ()
    assert package.excluded_evidence[0].evidence_id == unknown.evidence_id
    assert package.excluded_evidence[0].reason_codes == ("evidence_kind_not_allowed",)


def test_evidence_package_enforces_item_and_text_bounds() -> None:
    items = tuple(
        EvidenceReference.create(
            kind="structured_log",
            reference=f"log:{index}",
            summary="x" * 200,
            component_id="voice_runtime",
            occurred_at_epoch=100.0 + index,
        )
        for index in range(3)
    )
    policy = IncidentEvidencePolicy(
        max_evidence_items=2,
        max_summary_chars=64,
        max_reference_chars=32,
        max_incident_text_chars=128,
    )
    package = IncidentEvidencePackager(policy=policy).build(
        incident=_incident_with(*items),
        source_revision=REVISION,
        trigger_digest=TRIGGER_DIGEST,
        now_epoch=110.0,
    )

    assert len(package.evidence) == 2
    assert all(len(item.summary) <= 64 for item in package.evidence)
    assert any(
        item.evidence_id == items[2].evidence_id
        and item.reason_codes == ("evidence_item_limit_exceeded",)
        for item in package.excluded_evidence
    )


def test_incident_title_or_symptom_with_secret_is_blocked_not_leaked() -> None:
    incident = IncidentRecord.create(
        title="provider token sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        symptom="normal symptom",
        affected_components=("runtime.provider",),
        now_epoch=100.0,
    )
    package = IncidentEvidencePackager().build(
        incident=incident,
        source_revision=REVISION,
        trigger_digest=TRIGGER_DIGEST,
        now_epoch=101.0,
    )

    assert package.title == "[BLOCKED_UNSAFE_EVIDENCE]"
    assert any(
        reason.startswith("title:secret_prohibited")
        for reason in package.package_reason_codes
    )
    assert "sk-proj-" not in json.dumps(package.to_payload())
