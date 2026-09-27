from __future__ import annotations

import math

import pytest

from jarvis.incident_repair import (
    DiagnosisDisposition,
    DiagnosticHypothesis,
    HypothesisState,
    IncidentDiagnosis,
    IncidentRepairTrigger,
    ProtectedSurfaceVerdict,
    ReproductionState,
    SourceRepairCandidateEvidence,
)

REVISION = "a" * 40
DIGEST = "b" * 64


def test_incident_repair_trigger_is_canonical_and_digest_bound() -> None:
    first = IncidentRepairTrigger.create(
        incident_id="incident-1",
        source_revision=REVISION,
        component_ids=["voice", "router"],
        evidence_ids=["e2", "e1"],
        reason_code="unknown_failure",
        now_epoch=100.0,
    )
    second = IncidentRepairTrigger.create(
        incident_id="incident-1",
        source_revision=REVISION,
        component_ids=["router", "voice"],
        evidence_ids=["e1", "e2"],
        reason_code="unknown_failure",
        now_epoch=100.0,
    )

    assert first == second
    assert len(first.digest) == 64
    assert first.trigger_id == f"incident_repair_{first.digest[:16]}"


def test_trigger_requires_exact_revision_and_evidence() -> None:
    with pytest.raises(ValueError, match="exact Git object"):
        IncidentRepairTrigger.create(
            incident_id="incident-1",
            source_revision="main",
            component_ids=["voice"],
            evidence_ids=["e1"],
            reason_code="unknown_failure",
        )
    with pytest.raises(ValueError, match="requires evidence"):
        IncidentRepairTrigger.create(
            incident_id="incident-1",
            source_revision=REVISION,
            component_ids=["voice"],
            evidence_ids=[],
            reason_code="unknown_failure",
        )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, 0.0])
def test_trigger_rejects_non_finite_or_non_positive_time(value: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        IncidentRepairTrigger.create(
            incident_id="incident-1",
            source_revision=REVISION,
            component_ids=["voice"],
            evidence_ids=["e1"],
            reason_code="unknown_failure",
            now_epoch=value,
        )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, 0.0])
def test_diagnosis_rejects_non_finite_or_non_positive_time(value: float) -> None:
    hypothesis = DiagnosticHypothesis.create(
        statement="possible race",
        status=HypothesisState.INCONCLUSIVE,
    )
    with pytest.raises(ValueError, match="finite and positive"):
        IncidentDiagnosis.create(
            incident_id="incident-1",
            change_id="change-1",
            work_id="work-1",
            source_revision=REVISION,
            evidence_ids=["e1"],
            reproduction_state=ReproductionState.INCONCLUSIVE,
            hypotheses=[hypothesis],
            disposition=DiagnosisDisposition.INCONCLUSIVE,
            now_epoch=value,
        )


def test_hypothesis_support_and_refutation_are_evidence_bound() -> None:
    with pytest.raises(ValueError, match="requires supporting evidence"):
        DiagnosticHypothesis.create(
            statement="router health race",
            status=HypothesisState.SUPPORTED,
        )
    with pytest.raises(ValueError, match="requires refuting evidence"):
        DiagnosticHypothesis.create(
            statement="quota caused the crash",
            status=HypothesisState.REFUTED,
        )

    supported = DiagnosticHypothesis.create(
        statement="router health race",
        affected_components=["router"],
        affected_paths=["src/jarvis/model_routing/health.py"],
        supporting_evidence_ids=["repro-1"],
        status=HypothesisState.SUPPORTED,
        discriminator="repeat failure under concurrent health update",
    )
    assert supported.status is HypothesisState.SUPPORTED
    assert supported.hypothesis_id.startswith("hypothesis_")


def test_supported_diagnosis_requires_supported_root_cause_and_verification() -> None:
    proposed = DiagnosticHypothesis.create(statement="possible race")
    with pytest.raises(ValueError, match="selected supported hypothesis"):
        IncidentDiagnosis.create(
            incident_id="incident-1",
            change_id="change-1",
            work_id="work-1",
            source_revision=REVISION,
            evidence_ids=["e1"],
            reproduction_state=ReproductionState.REPRODUCED,
            hypotheses=[proposed],
            selected_hypothesis_id=proposed.hypothesis_id,
            disposition=DiagnosisDisposition.SUPPORTED_REPAIR,
        )

    supported = DiagnosticHypothesis.create(
        statement="health version race",
        supporting_evidence_ids=["e1"],
        status=HypothesisState.SUPPORTED,
    )
    diagnosis = IncidentDiagnosis.create(
        incident_id="incident-1",
        change_id="change-1",
        work_id="work-1",
        source_revision=REVISION,
        evidence_ids=["e1"],
        knowledge_revision_ids=["knowledge-r1"],
        reproduction_state=ReproductionState.REPRODUCED,
        hypotheses=[supported],
        selected_hypothesis_id=supported.hypothesis_id,
        affected_paths=["src/jarvis/model_routing/health.py"],
        affected_components=["router"],
        proposed_repair_scope="serialize target-health version updates",
        verification_targets=["tests/test_model_routing_health.py"],
        reason_codes=["reproduced", "supported_hypothesis"],
        disposition=DiagnosisDisposition.SUPPORTED_REPAIR,
        now_epoch=200.0,
    )
    assert diagnosis.diagnosis_id == f"diagnosis_{diagnosis.digest[:16]}"
    assert diagnosis.selected_hypothesis_id == supported.hypothesis_id


def test_diagnosis_rejects_hypothesis_evidence_outside_evidence_package() -> None:
    supported = DiagnosticHypothesis.create(
        statement="health version race",
        supporting_evidence_ids=["evidence-not-packaged"],
        status=HypothesisState.SUPPORTED,
    )
    with pytest.raises(ValueError, match="included in diagnosis evidence"):
        IncidentDiagnosis.create(
            incident_id="incident-1",
            change_id="change-1",
            work_id="work-1",
            source_revision=REVISION,
            evidence_ids=["e1"],
            reproduction_state=ReproductionState.REPRODUCED,
            hypotheses=[supported],
            selected_hypothesis_id=supported.hypothesis_id,
            proposed_repair_scope="serialize target-health version updates",
            verification_targets=["tests/test_model_routing_health.py"],
            disposition=DiagnosisDisposition.SUPPORTED_REPAIR,
            now_epoch=200.0,
        )


def test_inconclusive_diagnosis_cannot_claim_selected_root_cause() -> None:
    hypothesis = DiagnosticHypothesis.create(
        statement="possible race",
        status=HypothesisState.INCONCLUSIVE,
    )
    with pytest.raises(ValueError, match="cannot select a root cause"):
        IncidentDiagnosis.create(
            incident_id="incident-1",
            change_id="change-1",
            work_id="work-1",
            source_revision=REVISION,
            evidence_ids=["e1"],
            reproduction_state=ReproductionState.INCONCLUSIVE,
            hypotheses=[hypothesis],
            selected_hypothesis_id=hypothesis.hypothesis_id,
            disposition=DiagnosisDisposition.INCONCLUSIVE,
        )

    result = IncidentDiagnosis.create(
        incident_id="incident-1",
        change_id="change-1",
        work_id="work-1",
        source_revision=REVISION,
        evidence_ids=["e1"],
        reproduction_state=ReproductionState.NOT_REPRODUCED,
        hypotheses=[hypothesis],
        reason_codes=["not_reproduced"],
        disposition=DiagnosisDisposition.INCONCLUSIVE,
        now_epoch=201.0,
    )
    assert result.selected_hypothesis_id is None
    assert result.disposition is DiagnosisDisposition.INCONCLUSIVE


def test_source_repair_candidate_requires_clear_protected_surface() -> None:
    with pytest.raises(ValueError, match="CLEAR"):
        SourceRepairCandidateEvidence.create(
            incident_id="incident-1",
            diagnosis_id="diagnosis-1",
            diagnosis_digest=DIGEST,
            architecture_artifact_id="artifact-1",
            architecture_digest=DIGEST,
            development_work_id="work-dev",
            branch="work/repair",
            commit=REVISION,
            changed_paths=["src/jarvis/example.py"],
            diff_digest=DIGEST,
            verification_targets=["tests/test_example.py"],
            sandbox_profile="test.offline.v1",
            sandbox_profile_version=1,
            protected_surface_verdict=ProtectedSurfaceVerdict.UNKNOWN,
        )

    candidate = SourceRepairCandidateEvidence.create(
        incident_id="incident-1",
        diagnosis_id="diagnosis-1",
        diagnosis_digest=DIGEST,
        architecture_artifact_id="artifact-1",
        architecture_digest=DIGEST,
        development_work_id="work-dev",
        branch="work/repair",
        commit=REVISION,
        changed_paths=["src/jarvis/example.py"],
        diff_digest=DIGEST,
        verification_targets=["tests/test_example.py"],
        sandbox_profile="test.offline.v1",
        sandbox_profile_version=1,
        protected_surface_verdict=ProtectedSurfaceVerdict.CLEAR,
        now_epoch=300.0,
    )
    assert candidate.candidate_id == f"repair_candidate_{candidate.digest[:16]}"
