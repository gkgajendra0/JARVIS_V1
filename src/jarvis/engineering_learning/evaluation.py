"""Deterministic Phase-10 closed-loop engineering-learning evaluation."""

from __future__ import annotations

import pathlib
from collections.abc import Callable
from dataclasses import dataclass, replace

from jarvis.engineering_knowledge import (
    EngineeringKnowledgeRetrievalIndex,
    KnowledgeLifecycleService,
    KnowledgeLifecycleState,
    KnowledgePromotionError,
)
from jarvis.engineering_learning.facets import (
    ENGINEERING_COMPATIBILITY_FACET_TYPE,
    ENGINEERING_OUTCOME_FACET_TYPE,
    ENGINEERING_REGRESSION_FACET_TYPE,
)
from jarvis.engineering_learning.lifecycle import (
    EngineeringLearningLifecycleService,
)
from jarvis.engineering_learning.models import (
    EngineeringOutcomeAttribution,
    EngineeringOutcomeResult,
    EngineeringOutcomeSourceKind,
    EngineeringOutcomeV1,
    OutcomeApplicability,
)
from jarvis.engineering_learning.projector import (
    EngineeringLearningProjectionError,
    EngineeringLearningProjector,
)
from jarvis.engineering_learning.reconciliation import (
    EngineeringLearningReconciler,
    LearningReconciliationStatus,
)
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.incident_repair.evidence import IncidentEvidencePackage
from jarvis.incident_repair.knowledge import IncidentKnowledgeRetriever
from jarvis.incidents.store import SqliteIncidentStore

_RELEASE = "c" * 40
_CANDIDATE_DIGEST = "a" * 64
_PACKAGE_DIGEST = "b" * 64
_EVIDENCE_DIGEST = "d" * 64


class Phase10ReplayError(RuntimeError):
    """A deterministic Phase-10 replay invariant failed."""


@dataclass(frozen=True, slots=True)
class Phase10ReplayCase:
    case_id: str
    passed: bool
    evidence: dict[str, object]

    def payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class Phase10ReplayReport:
    cases: tuple[Phase10ReplayCase, ...]
    status: str
    suite_digest: str

    def payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "cases": [item.payload() for item in self.cases],
        }


def _case(
    case_id: str,
    root: pathlib.Path,
    operation: Callable[[pathlib.Path], dict[str, object]],
) -> Phase10ReplayCase:
    case_root = root / case_id
    case_root.mkdir(parents=True, exist_ok=True)
    try:
        evidence = operation(case_root)
    except Exception as exc:  # noqa: BLE001 - evaluation converts failures to evidence.
        return Phase10ReplayCase(
            case_id=case_id,
            passed=False,
            evidence={
                "error_type": type(exc).__name__,
                "reason": str(exc),
            },
        )
    return Phase10ReplayCase(case_id=case_id, passed=True, evidence=evidence)


def _promotion_outcome(
    *,
    result: EngineeringOutcomeResult = EngineeringOutcomeResult.SUCCESS,
    attribution: EngineeringOutcomeAttribution = (
        EngineeringOutcomeAttribution.NOT_APPLICABLE
    ),
    reason: str = "runtime_healthy",
    observed_at_epoch: float = 100.0,
) -> EngineeringOutcomeV1:
    return EngineeringOutcomeV1.create(
        source_kind=EngineeringOutcomeSourceKind.PROMOTION,
        source_identity="promotion-phase10-eval",
        subject_type="promotion_candidate",
        subject_id="candidate-phase10",
        subject_digest=_CANDIDATE_DIGEST,
        result=result,
        attribution=attribution,
        reason_codes=(reason,),
        evidence_references=(
            "promotion-attempt:phase10-eval",
            f"change-artifact:phase10-observation:sha256:{_EVIDENCE_DIGEST}",
        ),
        applicability=(
            OutcomeApplicability(
                target_namespace="jarvis.revision",
                target_identity=_RELEASE,
                matcher_type="exact",
                constraint={},
                required=True,
            ),
        ),
        observed_at_epoch=observed_at_epoch,
        producer="phase10.evaluation:v1",
        change_id="change-phase10-eval",
        candidate_id="candidate-phase10",
        candidate_digest=_CANDIDATE_DIGEST,
        release_sha=_RELEASE,
    )


def _repair_outcome(
    *,
    result: EngineeringOutcomeResult = EngineeringOutcomeResult.SUCCESS,
    reason: str = "runtime_voice_repair_verified",
    observed_at_epoch: float = 100.0,
) -> EngineeringOutcomeV1:
    return EngineeringOutcomeV1.create(
        source_kind=EngineeringOutcomeSourceKind.REPAIR,
        source_identity="repair-attempt-phase10-eval",
        subject_type="repair_attempt",
        subject_id="repair-attempt-phase10-eval",
        subject_digest=_CANDIDATE_DIGEST,
        result=result,
        attribution=EngineeringOutcomeAttribution.NOT_APPLICABLE,
        reason_codes=(reason,),
        evidence_references=(
            f"repair-attempt:phase10-eval:sha256:{_EVIDENCE_DIGEST}",
        ),
        applicability=(
            OutcomeApplicability(
                target_namespace="jarvis.component",
                target_identity="runtime.voice",
                matcher_type="exact",
                constraint={},
                required=True,
            ),
        ),
        observed_at_epoch=observed_at_epoch,
        producer="phase10.evaluation:v1",
    )


def _compatibility_outcome(
    *,
    result: EngineeringOutcomeResult,
    reason: str,
    observed_at_epoch: float = 100.0,
) -> EngineeringOutcomeV1:
    return EngineeringOutcomeV1.create(
        source_kind=EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY,
        source_identity=f"compatibility:{reason}",
        subject_type="capability_package",
        subject_id="tv.control@1.0.0",
        subject_digest=_PACKAGE_DIGEST,
        result=result,
        attribution=EngineeringOutcomeAttribution.COMPATIBILITY,
        reason_codes=(reason,),
        evidence_references=(
            f"capability-compatibility-report:sha256:{_EVIDENCE_DIGEST}",
        ),
        applicability=(
            OutcomeApplicability(
                target_namespace="package",
                target_identity="tv.control",
                matcher_type="version_exact",
                constraint={"version": "1.0.0"},
                required=True,
            ),
            OutcomeApplicability(
                target_namespace="jarvis.revision",
                target_identity=_RELEASE,
                matcher_type="exact",
                constraint={},
                required=True,
            ),
        ),
        observed_at_epoch=observed_at_epoch,
        producer="phase10.evaluation:v1",
        release_sha=_RELEASE,
        package_id="tv.control",
        package_version="1.0.0",
        package_digest=_PACKAGE_DIGEST,
    )


def _learn(
    store: SqliteIncidentStore,
    outcome: EngineeringOutcomeV1,
    *,
    now_epoch: float,
):
    reconciler = EngineeringLearningReconciler(store)
    try:
        return reconciler.reconcile((outcome,), limit=10, now_epoch=now_epoch)
    finally:
        reconciler.close()


def _01_verified_success(root: pathlib.Path) -> dict[str, object]:
    store = SqliteIncidentStore(root / "engineering.sqlite3")
    try:
        report = _learn(store, _promotion_outcome(), now_epoch=110.0)
        item = report.items[0]
        if item.status is not LearningReconciliationStatus.LEARNED:
            raise Phase10ReplayError("verified success was not learned")
        if item.revision_id is None:
            raise Phase10ReplayError("verified success produced no revision")
        if (
            store.get_engineering_knowledge_lifecycle_state(item.revision_id)
            is not KnowledgeLifecycleState.ACCEPTED
        ):
            raise Phase10ReplayError("verified success was not accepted")
        return {
            "revision_id": item.revision_id,
            "status": item.status.value,
            "lifecycle": "accepted",
        }
    finally:
        store.close()


def _02_candidate_regression(root: pathlib.Path) -> dict[str, object]:
    store = SqliteIncidentStore(root / "engineering.sqlite3")
    try:
        outcome = _promotion_outcome(
            result=EngineeringOutcomeResult.ROLLED_BACK,
            attribution=EngineeringOutcomeAttribution.CANDIDATE,
            reason="candidate_runtime_regression",
        )
        report = _learn(store, outcome, now_epoch=110.0)
        item = report.items[0]
        if item.revision_id is None:
            raise Phase10ReplayError("candidate regression produced no revision")
        facets = store.list_engineering_knowledge_facets(item.revision_id)
        facet_types = {facet.facet_type for facet in facets}
        expected = {
            ENGINEERING_OUTCOME_FACET_TYPE,
            ENGINEERING_REGRESSION_FACET_TYPE,
        }
        if facet_types != expected:
            raise Phase10ReplayError("candidate regression facet set is incomplete")
        return {
            "revision_id": item.revision_id,
            "facet_types": sorted(facet_types),
        }
    finally:
        store.close()


def _inconclusive_failure_case(
    root: pathlib.Path,
    *,
    attribution: EngineeringOutcomeAttribution,
    reason: str,
) -> dict[str, object]:
    store = SqliteIncidentStore(root / "engineering.sqlite3")
    try:
        outcome = _promotion_outcome(
            result=EngineeringOutcomeResult.FAILURE,
            attribution=attribution,
            reason=reason,
        )
        report = _learn(store, outcome, now_epoch=110.0)
        item = report.items[0]
        if item.status is not LearningReconciliationStatus.INCONCLUSIVE:
            raise Phase10ReplayError("non-candidate failure became durable truth")
        if item.knowledge_id is None:
            raise Phase10ReplayError("inconclusive result lost stable proposition id")
        if store.list_engineering_knowledge_revisions(item.knowledge_id):
            raise Phase10ReplayError("inconclusive result created durable knowledge")
        return {
            "status": item.status.value,
            "attribution": attribution.value,
            "reason_codes": item.reason_codes,
        }
    finally:
        store.close()


def _03_external_provider(root: pathlib.Path) -> dict[str, object]:
    return _inconclusive_failure_case(
        root,
        attribution=EngineeringOutcomeAttribution.EXTERNAL_PROVIDER,
        reason="provider_quota",
    )


def _04_external_hardware(root: pathlib.Path) -> dict[str, object]:
    return _inconclusive_failure_case(
        root,
        attribution=EngineeringOutcomeAttribution.EXTERNAL_HARDWARE,
        reason="device_unreachable",
    )


def _05_unknown_cause(root: pathlib.Path) -> dict[str, object]:
    return _inconclusive_failure_case(
        root,
        attribution=EngineeringOutcomeAttribution.UNKNOWN,
        reason="unknown_runtime_failure",
    )


def _compatibility_case(
    root: pathlib.Path,
    *,
    result: EngineeringOutcomeResult,
    reason: str,
) -> dict[str, object]:
    store = SqliteIncidentStore(root / "engineering.sqlite3")
    try:
        report = _learn(
            store,
            _compatibility_outcome(result=result, reason=reason),
            now_epoch=110.0,
        )
        item = report.items[0]
        if item.revision_id is None:
            raise Phase10ReplayError("compatibility result produced no revision")
        facets = store.list_engineering_knowledge_facets(item.revision_id)
        facet_types = {facet.facet_type for facet in facets}
        if ENGINEERING_COMPATIBILITY_FACET_TYPE not in facet_types:
            raise Phase10ReplayError("compatibility facet was not projected")
        return {
            "revision_id": item.revision_id,
            "result": result.value,
            "facet_types": sorted(facet_types),
        }
    finally:
        store.close()


def _06_compatibility_ready(root: pathlib.Path) -> dict[str, object]:
    return _compatibility_case(
        root,
        result=EngineeringOutcomeResult.SUCCESS,
        reason="ready",
    )


def _07_compatibility_blocked(root: pathlib.Path) -> dict[str, object]:
    return _compatibility_case(
        root,
        result=EngineeringOutcomeResult.BLOCKED,
        reason="platform_unsupported",
    )


def _08_contradiction_supersedes(root: pathlib.Path) -> dict[str, object]:
    store = SqliteIncidentStore(root / "engineering.sqlite3")
    try:
        first = _learn(store, _promotion_outcome(), now_epoch=110.0)
        old_id = first.items[0].revision_id
        if old_id is None:
            raise Phase10ReplayError("initial learning missing revision")
        regression = _promotion_outcome(
            result=EngineeringOutcomeResult.ROLLED_BACK,
            attribution=EngineeringOutcomeAttribution.CANDIDATE,
            reason="candidate_runtime_regression",
            observed_at_epoch=101.0,
        )
        second = _learn(store, regression, now_epoch=120.0)
        new_id = second.items[0].revision_id
        if new_id is None or new_id == old_id:
            raise Phase10ReplayError("contradiction did not create successor revision")
        if (
            store.get_engineering_knowledge_lifecycle_state(old_id)
            is not KnowledgeLifecycleState.SUPERSEDED
        ):
            raise Phase10ReplayError("prior accepted revision was not superseded")
        if (
            store.get_engineering_knowledge_lifecycle_state(new_id)
            is not KnowledgeLifecycleState.ACCEPTED
        ):
            raise Phase10ReplayError("successor revision is not accepted")
        return {
            "prior_revision_id": old_id,
            "successor_revision_id": new_id,
            "prior_state": "superseded",
            "successor_state": "accepted",
        }
    finally:
        store.close()


def _09_restart_replay(root: pathlib.Path) -> dict[str, object]:
    path = root / "engineering.sqlite3"
    first_store = SqliteIncidentStore(path)
    first = EngineeringLearningReconciler(first_store)
    try:
        learned = first.reconcile(
            (_promotion_outcome(),),
            limit=10,
            now_epoch=110.0,
        )
        revision_id = learned.items[0].revision_id
        knowledge_id = learned.items[0].knowledge_id
        if revision_id is None or knowledge_id is None:
            raise Phase10ReplayError("initial replay case did not learn")
    finally:
        first.close()
        first_store.close()

    restarted_store = SqliteIncidentStore(path)
    restarted = EngineeringLearningReconciler(restarted_store)
    try:
        replay = restarted.reconcile(
            (_promotion_outcome(),),
            limit=10,
            now_epoch=120.0,
        )
        item = replay.items[0]
        if item.status is not LearningReconciliationStatus.REPLAYED:
            raise Phase10ReplayError("restart replay was not idempotent")
        revisions = restarted_store.list_engineering_knowledge_revisions(knowledge_id)
        if tuple(row.revision_id for row in revisions) != (revision_id,):
            raise Phase10ReplayError("restart replay duplicated knowledge")
        return {
            "revision_id": revision_id,
            "revision_count": len(revisions),
            "status": item.status.value,
        }
    finally:
        restarted.close()
        restarted_store.close()


def _10_crash_gap_recovery(root: pathlib.Path) -> dict[str, object]:
    path = root / "engineering.sqlite3"
    store = SqliteIncidentStore(path)
    reconciler = EngineeringLearningReconciler(store)
    try:
        first = reconciler.reconcile(
            (_promotion_outcome(),),
            limit=10,
            now_epoch=110.0,
        )
        prior_id = first.items[0].revision_id
        if prior_id is None:
            raise Phase10ReplayError("initial revision missing")

        successor = _promotion_outcome(
            result=EngineeringOutcomeResult.ROLLED_BACK,
            attribution=EngineeringOutcomeAttribution.CANDIDATE,
            reason="candidate_runtime_regression",
            observed_at_epoch=101.0,
        )
        projected = EngineeringLearningProjector().project(
            store,
            successor,
            revision_number=2,
            parent_revision_id=prior_id,
            supersedes_revision_id=prior_id,
        )
        EngineeringLearningLifecycleService(store).promote(
            projected.revision_id,
            staged_at_epoch=120.0,
            accepted_at_epoch=121.0,
        )
        if (
            store.get_engineering_knowledge_lifecycle_state(prior_id)
            is not KnowledgeLifecycleState.ACCEPTED
        ):
            raise Phase10ReplayError("test did not create accepted/supersede crash gap")
    finally:
        reconciler.close()
        store.close()

    restarted_store = SqliteIncidentStore(path)
    restarted = EngineeringLearningReconciler(restarted_store)
    try:
        recovered = restarted.reconcile(
            (successor,),
            limit=10,
            now_epoch=130.0,
        )
        if recovered.items[0].status is not LearningReconciliationStatus.RESUMED:
            raise Phase10ReplayError("crash gap was not resumed")
        if (
            restarted_store.get_engineering_knowledge_lifecycle_state(prior_id)
            is not KnowledgeLifecycleState.SUPERSEDED
        ):
            raise Phase10ReplayError("crash recovery did not supersede prior revision")
        return {
            "prior_revision_id": prior_id,
            "successor_revision_id": projected.revision_id,
            "status": recovered.items[0].status.value,
        }
    finally:
        restarted.close()
        restarted_store.close()


def _11_missing_attestation_blocks(root: pathlib.Path) -> dict[str, object]:
    store = SqliteIncidentStore(root / "engineering.sqlite3")
    try:
        projector = EngineeringLearningProjector()
        candidate, _ = projector.build_candidate(_promotion_outcome())
        candidate = replace(candidate, attestations=())
        write = store.persist_engineering_knowledge_candidate(candidate)
        try:
            EngineeringLearningLifecycleService(store).stage(
                write.revision_id,
                now_epoch=110.0,
            )
        except KnowledgePromotionError:
            pass
        else:
            raise Phase10ReplayError("missing learning attestation was accepted")
        if (
            store.get_engineering_knowledge_lifecycle_state(write.revision_id)
            is not KnowledgeLifecycleState.CANDIDATE
        ):
            raise Phase10ReplayError("blocked candidate left candidate state")
        return {
            "revision_id": write.revision_id,
            "state": "candidate",
            "blocked": True,
        }
    finally:
        store.close()


def _12_unknown_schema_blocks(root: pathlib.Path) -> dict[str, object]:
    store = SqliteIncidentStore(root / "engineering.sqlite3")
    try:
        projector = EngineeringLearningProjector()
        candidate, _ = projector.build_candidate(_promotion_outcome())
        original = candidate.facets[0]
        unknown = replace(
            original,
            facet_id=original.facet_id + ":future",
            schema_version="999",
        )
        candidate = replace(candidate, facets=(unknown,))
        write = store.persist_engineering_knowledge_candidate(candidate)
        try:
            EngineeringLearningLifecycleService(store).stage(
                write.revision_id,
                now_epoch=110.0,
            )
        except KnowledgePromotionError:
            pass
        else:
            raise Phase10ReplayError("unknown future facet schema was accepted")
        return {
            "revision_id": write.revision_id,
            "unknown_schema_version": "999",
            "blocked": True,
        }
    finally:
        store.close()


def _13_rejected_not_resurrected(root: pathlib.Path) -> dict[str, object]:
    store = SqliteIncidentStore(root / "engineering.sqlite3")
    reconciler = EngineeringLearningReconciler(store)
    try:
        projection = EngineeringLearningProjector().project(
            store,
            _promotion_outcome(),
        )
        evidence_ids = tuple(
            item.evidence_id
            for item in store.list_engineering_knowledge_evidence(
                projection.revision_id
            )
        )
        KnowledgeLifecycleService(store).reject(
            projection.revision_id,
            reason_code="phase10_evaluation_rejected",
            actor="phase10.evaluation:v1",
            evidence_ids=evidence_ids,
            now_epoch=105.0,
        )
        replay = reconciler.reconcile(
            (_promotion_outcome(),),
            limit=10,
            now_epoch=110.0,
        )
        if replay.items[0].status is not LearningReconciliationStatus.TERMINAL_IGNORED:
            raise Phase10ReplayError("rejected knowledge was resurrected")
        if (
            store.get_engineering_knowledge_lifecycle_state(projection.revision_id)
            is not KnowledgeLifecycleState.REJECTED
        ):
            raise Phase10ReplayError("rejected knowledge changed lifecycle state")
        return {
            "revision_id": projection.revision_id,
            "state": "rejected",
            "status": replay.items[0].status.value,
        }
    finally:
        reconciler.close()
        store.close()


def _14_phase6_advisory_retrieval(root: pathlib.Path) -> dict[str, object]:
    store = SqliteIncidentStore(root / "engineering.sqlite3")
    index = EngineeringKnowledgeRetrievalIndex(store.path)
    reconciler = EngineeringLearningReconciler(store, index=index)
    try:
        learned = reconciler.reconcile(
            (_repair_outcome(),),
            limit=10,
            now_epoch=110.0,
        )
        revision_id = learned.items[0].revision_id
        if revision_id is None:
            raise Phase10ReplayError("repair learning did not create revision")

        package = IncidentEvidencePackage.create(
            incident_id="incident-phase10-eval",
            source_revision=_RELEASE,
            trigger_digest="e" * 64,
            title="runtime voice repair",
            symptom="runtime.voice runtime voice repair verified",
            severity="medium",
            status="open",
            affected_components=("runtime.voice",),
            evidence=(),
            excluded_evidence=(),
            repair_attempts=(),
            knowledge_revision_ids=(),
            package_reason_codes=(),
            created_at_epoch=111.0,
        )
        retriever = IncidentKnowledgeRetriever(index)
        revision_ids = retriever.retrieve_revision_ids(
            package,
            now_epoch=112.0,
        )
        if revision_id not in revision_ids:
            raise Phase10ReplayError("Phase-6 advisory retrieval missed learned repair")
        if hasattr(retriever, "execute") or hasattr(retriever, "promote"):
            raise Phase10ReplayError("advisory retriever exposes mutation authority")
        return {
            "revision_ids": revision_ids,
            "advisory_only": True,
        }
    finally:
        reconciler.close()
        index.close()
        store.close()


def _15_malformed_integrity_reference(root: pathlib.Path) -> dict[str, object]:
    del root
    outcome = replace(
        _promotion_outcome(),
        evidence_references=(
            "promotion-attempt:phase10-eval",
            "change-artifact:phase10-observation:sha256:not-a-digest",
        ),
    )
    try:
        EngineeringLearningProjector().build_candidate(outcome)
    except EngineeringLearningProjectionError:
        return {"blocked": True}
    raise Phase10ReplayError("malformed claimed sha256 evidence was accepted")


_CASES: tuple[
    tuple[str, Callable[[pathlib.Path], dict[str, object]]],
    ...,
] = (
    ("01_verified_success_accepted", _01_verified_success),
    ("02_candidate_regression_negative_evidence", _02_candidate_regression),
    ("03_external_provider_not_candidate_truth", _03_external_provider),
    ("04_external_hardware_not_candidate_truth", _04_external_hardware),
    ("05_unknown_cause_inconclusive", _05_unknown_cause),
    ("06_compatibility_ready_learned", _06_compatibility_ready),
    ("07_compatibility_blocked_learned", _07_compatibility_blocked),
    ("08_contradiction_supersedes_prior", _08_contradiction_supersedes),
    ("09_restart_replay_idempotent", _09_restart_replay),
    ("10_crash_gap_recovery", _10_crash_gap_recovery),
    ("11_missing_attestation_blocks", _11_missing_attestation_blocks),
    ("12_unknown_schema_blocks", _12_unknown_schema_blocks),
    ("13_rejected_not_resurrected", _13_rejected_not_resurrected),
    ("14_phase6_advisory_retrieval", _14_phase6_advisory_retrieval),
    ("15_malformed_integrity_reference_blocks", _15_malformed_integrity_reference),
)


def run_replay_suite(root: str | pathlib.Path) -> Phase10ReplayReport:
    resolved = pathlib.Path(root).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    cases = tuple(_case(case_id, resolved, operation) for case_id, operation in _CASES)
    status = "PASS" if all(item.passed for item in cases) else "FAIL"
    payload = {
        "status": status,
        "cases": [item.payload() for item in cases],
    }
    return Phase10ReplayReport(
        cases=cases,
        status=status,
        suite_digest=canonical_digest(payload),
    )
