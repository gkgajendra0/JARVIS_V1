"""Durable deterministic Finding lifecycle for Phase 10A.4."""

from __future__ import annotations

from dataclasses import dataclass, replace

from jarvis.autonomy.models import (
    AutonomyFindingEventV1,
    AutonomyFindingV1,
    CandidateDisposition,
    CandidateDispositionRecordV1,
    DesiredStateV1,
    FindingStatus,
    candidate_decision_id_for,
    deterministic_id,
    finding_id_for,
)
from jarvis.autonomy.rules import (
    DesiredStateEvaluationStatus,
    DesiredStateEvaluationV1,
)
from jarvis.autonomy.store import AutonomyStore


@dataclass(frozen=True, slots=True)
class FindingObservationResultV1:
    finding: AutonomyFindingV1 | None
    changed: bool
    event: AutonomyFindingEventV1 | None
    obsoleted_candidate_ids: tuple[str, ...] = ()


class FindingLifecycle:
    """Project stabilized DesiredState evaluation into one durable finding lifecycle."""

    finding_kind = "state_gap"

    def __init__(self, store: AutonomyStore) -> None:
        if not isinstance(store, AutonomyStore):
            raise TypeError("store must be an AutonomyStore")
        self.store = store

    def _current(self, finding_id: str) -> AutonomyFindingV1 | None:
        try:
            return self.store.require_finding(finding_id)
        except KeyError:
            return None

    @staticmethod
    def _event(
        finding: AutonomyFindingV1,
        *,
        kind: str,
        previous_status: FindingStatus | None,
    ) -> AutonomyFindingEventV1:
        event_key = deterministic_id(
            "finding_event_key",
            {
                "finding_id": finding.finding_id,
                "version": finding.version,
                "status": finding.status.value,
                "kind": kind,
            },
        )
        return AutonomyFindingEventV1(
            event_id=deterministic_id(
                "finding_event",
                {
                    "finding_id": finding.finding_id,
                    "event_key": event_key,
                },
            ),
            finding_id=finding.finding_id,
            event_key=event_key,
            kind=kind,
            detail_json={
                "version": finding.version,
                "previous_status": (
                    None if previous_status is None else previous_status.value
                ),
                "status": finding.status.value,
                "desired_generation": finding.desired_generation,
                "snapshot_digest": finding.latest_snapshot_digest,
                "violation_count": finding.violation_count,
                "reason_codes": list(finding.reason_codes),
                "supporting_fact_digests": list(
                    finding.supporting_fact_digests
                ),
                "root_finding_id": finding.root_finding_id,
                "suppression_finding_id": finding.suppression_finding_id,
            },
            created_at_epoch=finding.last_seen_epoch,
        )

    def _persist_transition(
        self,
        finding: AutonomyFindingV1,
        *,
        previous: AutonomyFindingV1 | None,
        kind: str,
    ) -> FindingObservationResultV1:
        if previous is None:
            persisted = self.store.create_finding(finding)
            previous_status = None
        else:
            persisted = self.store.update_finding(
                finding,
                expected_version=previous.version,
            )
            previous_status = previous.status
        event = self._event(
            persisted,
            kind=kind,
            previous_status=previous_status,
        )
        self.store.append_finding_event(event)
        return FindingObservationResultV1(
            finding=persisted,
            changed=True,
            event=event,
        )

    def _obsolete_candidates(
        self,
        finding: AutonomyFindingV1,
        *,
        at_epoch: float,
        reason_code: str,
    ) -> tuple[str, ...]:
        obsoleted: list[str] = []
        for candidate in self.store.list_action_candidates(finding.finding_id):
            latest = self.store.latest_candidate_decision(candidate.candidate_id)
            if (
                latest is not None
                and latest.disposition is CandidateDisposition.OBSOLETE
            ):
                continue
            decision = CandidateDispositionRecordV1(
                decision_id=candidate_decision_id_for(
                    candidate,
                    disposition=CandidateDisposition.OBSOLETE,
                    source_identity="finding_lifecycle:obsolete",
                    reason_codes=(reason_code,),
                ),
                candidate_id=candidate.candidate_id,
                disposition=CandidateDisposition.OBSOLETE,
                reason_codes=(reason_code,),
                source_identity="finding_lifecycle:obsolete",
                created_at_epoch=at_epoch,
            )
            self.store.record_candidate_decision(decision)
            obsoleted.append(candidate.candidate_id)
        return tuple(obsoleted)

    def observe(
        self,
        desired: DesiredStateV1,
        evaluation: DesiredStateEvaluationV1,
        *,
        root_finding_id: str | None = None,
    ) -> FindingObservationResultV1:
        if not isinstance(desired, DesiredStateV1):
            raise TypeError("desired must be a DesiredStateV1")
        if not isinstance(evaluation, DesiredStateEvaluationV1):
            raise TypeError("evaluation must be a DesiredStateEvaluationV1")

        finding_id = finding_id_for(
            desired,
            finding_kind=self.finding_kind,
        )
        current = self._current(finding_id)

        if (
            evaluation.desired_state_id != desired.desired_state_id
            or evaluation.desired_generation != desired.generation
            or evaluation.rule_key != desired.rule_key
            or evaluation.rule_version != desired.rule_version
        ):
            return FindingObservationResultV1(
                finding=current,
                changed=False,
                event=None,
            )

        if evaluation.status is DesiredStateEvaluationStatus.UNKNOWN:
            return FindingObservationResultV1(
                finding=current,
                changed=False,
                event=None,
            )

        if evaluation.status is DesiredStateEvaluationStatus.SATISFIED:
            if current is None or current.status is FindingStatus.RESOLVED:
                return FindingObservationResultV1(
                    finding=current,
                    changed=False,
                    event=None,
                )
            resolved = replace(
                current,
                desired_generation=desired.generation,
                status=FindingStatus.RESOLVED,
                latest_snapshot_digest=evaluation.snapshot_digest,
                last_seen_epoch=evaluation.evaluated_at_epoch,
                reason_codes=evaluation.reason_codes,
                supporting_fact_digests=evaluation.supporting_fact_digests,
                version=current.version + 1,
            )
            result = self._persist_transition(
                resolved,
                previous=current,
                kind="resolved",
            )
            obsoleted = self._obsolete_candidates(
                resolved,
                at_epoch=evaluation.evaluated_at_epoch,
                reason_code="finding_resolved",
            )
            return replace(
                result,
                obsoleted_candidate_ids=obsoleted,
            )

        target_status = (
            FindingStatus.ACTIVE
            if evaluation.status is DesiredStateEvaluationStatus.VIOLATED
            else FindingStatus.STABILIZING
        )
        violation_count = max(1, evaluation.consecutive_violations)

        if current is None:
            created = AutonomyFindingV1(
                finding_id=finding_id,
                desired_state_id=desired.desired_state_id,
                desired_generation=desired.generation,
                target_namespace=desired.target_namespace,
                target_identity=desired.target_identity,
                finding_kind=self.finding_kind,
                rule_key=desired.rule_key,
                rule_version=desired.rule_version,
                status=target_status,
                latest_snapshot_digest=evaluation.snapshot_digest,
                first_seen_epoch=evaluation.evaluated_at_epoch,
                last_seen_epoch=evaluation.evaluated_at_epoch,
                violation_count=violation_count,
                reason_codes=evaluation.reason_codes,
                supporting_fact_digests=evaluation.supporting_fact_digests,
                root_finding_id=root_finding_id,
            )
            return self._persist_transition(
                created,
                previous=None,
                kind="observed",
            )

        if (
            current.desired_generation == desired.generation
            and current.status is target_status
            and current.latest_snapshot_digest == evaluation.snapshot_digest
            and current.last_seen_epoch == evaluation.evaluated_at_epoch
            and current.violation_count == violation_count
            and current.reason_codes == evaluation.reason_codes
            and current.supporting_fact_digests
            == evaluation.supporting_fact_digests
            and current.root_finding_id == root_finding_id
        ):
            return FindingObservationResultV1(
                finding=current,
                changed=False,
                event=None,
            )

        updated = replace(
            current,
            desired_generation=desired.generation,
            status=target_status,
            latest_snapshot_digest=evaluation.snapshot_digest,
            last_seen_epoch=evaluation.evaluated_at_epoch,
            violation_count=violation_count,
            reason_codes=evaluation.reason_codes,
            supporting_fact_digests=evaluation.supporting_fact_digests,
            root_finding_id=root_finding_id,
            suppression_finding_id=None,
            version=current.version + 1,
        )
        return self._persist_transition(
            updated,
            previous=current,
            kind="activated" if target_status is FindingStatus.ACTIVE else "stabilizing",
        )

    def suppress(
        self,
        finding_id: str,
        *,
        suppression_finding_id: str,
        root_finding_id: str | None = None,
        at_epoch: float,
    ) -> FindingObservationResultV1:
        current = self.store.require_finding(finding_id)
        if current.finding_id == suppression_finding_id:
            raise ValueError("finding cannot suppress itself")
        if (
            current.status is FindingStatus.SUPPRESSED
            and current.suppression_finding_id == suppression_finding_id
            and current.root_finding_id == root_finding_id
        ):
            return FindingObservationResultV1(
                finding=current,
                changed=False,
                event=None,
            )
        updated = replace(
            current,
            status=FindingStatus.SUPPRESSED,
            last_seen_epoch=float(at_epoch),
            suppression_finding_id=suppression_finding_id,
            root_finding_id=root_finding_id,
            version=current.version + 1,
        )
        result = self._persist_transition(
            updated,
            previous=current,
            kind="suppressed",
        )
        obsoleted = self._obsolete_candidates(
            updated,
            at_epoch=float(at_epoch),
            reason_code="finding_suppressed",
        )
        return replace(
            result,
            obsoleted_candidate_ids=obsoleted,
        )
