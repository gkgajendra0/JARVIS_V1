"""Durable deterministic finding lifecycle for Phase 10A."""

from __future__ import annotations

from dataclasses import dataclass, replace

from jarvis.autonomy.models import (
    AutonomyFindingEventV1,
    AutonomyFindingV1,
    DesiredStateStatus,
    DesiredStateV1,
    FindingStatus,
    deterministic_id,
    finding_id_for,
)
from jarvis.autonomy.rules import (
    DesiredStateEvaluationStatus,
    DesiredStateEvaluationV1,
)
from jarvis.autonomy.store import AutonomyStore


@dataclass(frozen=True, slots=True)
class FindingLifecycleResultV1:
    finding: AutonomyFindingV1 | None
    event: AutonomyFindingEventV1 | None
    changed: bool
    reason_code: str


_STATUS_EVENT_KIND = {
    FindingStatus.STABILIZING: "stabilizing",
    FindingStatus.ACTIVE: "activated",
    FindingStatus.RESOLVED: "resolved",
    FindingStatus.SUPPRESSED: "suppressed",
    FindingStatus.SUPERSEDED: "superseded",
}


def _event_for(finding: AutonomyFindingV1) -> AutonomyFindingEventV1:
    kind = _STATUS_EVENT_KIND[finding.status]
    event_key = f"v{finding.version}:{kind}"
    event_id = deterministic_id(
        "finding_event",
        {
            "finding_id": finding.finding_id,
            "event_key": event_key,
        },
    )
    return AutonomyFindingEventV1(
        event_id=event_id,
        finding_id=finding.finding_id,
        event_key=event_key,
        kind=kind,
        detail_json={
            "desired_generation": finding.desired_generation,
            "status": finding.status.value,
            "latest_snapshot_digest": finding.latest_snapshot_digest,
            "violation_count": finding.violation_count,
            "root_finding_id": finding.root_finding_id,
            "suppression_finding_id": finding.suppression_finding_id,
        },
        created_at_epoch=finding.last_seen_epoch,
    )


def _optional_finding(
    store: AutonomyStore,
    finding_id: str,
) -> AutonomyFindingV1 | None:
    try:
        return store.require_finding(finding_id)
    except KeyError:
        return None


def _same_persisted_state(
    current: AutonomyFindingV1,
    proposed: AutonomyFindingV1,
) -> bool:
    return replace(proposed, version=current.version) == current


class FindingLifecycleManager:
    """Project stabilized evaluations into one replay-safe durable finding lifecycle."""

    def __init__(self, store: AutonomyStore) -> None:
        if not isinstance(store, AutonomyStore):
            raise TypeError("store must be an AutonomyStore")
        self.store = store

    def _ensure_event(
        self,
        finding: AutonomyFindingV1,
    ) -> AutonomyFindingEventV1:
        event = _event_for(finding)
        return self.store.append_finding_event(event)

    def apply(
        self,
        desired: DesiredStateV1,
        evaluation: DesiredStateEvaluationV1,
        *,
        finding_kind: str = "state_gap",
        root_finding_id: str | None = None,
        suppression_finding_id: str | None = None,
    ) -> FindingLifecycleResultV1:
        if not isinstance(desired, DesiredStateV1):
            raise TypeError("desired must be a DesiredStateV1")
        if not isinstance(evaluation, DesiredStateEvaluationV1):
            raise TypeError("evaluation must be a DesiredStateEvaluationV1")
        if evaluation.desired_state_id != desired.desired_state_id:
            raise ValueError("evaluation DesiredState identity mismatch")

        finding_id = finding_id_for(desired, finding_kind=finding_kind)
        current = _optional_finding(self.store, finding_id)

        if desired.status is not DesiredStateStatus.ACTIVE:
            if current is None:
                return FindingLifecycleResultV1(
                    finding=None,
                    event=None,
                    changed=False,
                    reason_code="desired_state_not_active_no_finding",
                )
            if current.status is FindingStatus.SUPERSEDED:
                event = self._ensure_event(current)
                return FindingLifecycleResultV1(
                    finding=current,
                    event=event,
                    changed=False,
                    reason_code="finding_already_superseded",
                )
            updated = replace(
                current,
                desired_generation=desired.generation,
                status=FindingStatus.SUPERSEDED,
                latest_snapshot_digest=evaluation.snapshot_digest,
                last_seen_epoch=evaluation.evaluated_at_epoch,
                reason_codes=("desired_state_not_active",),
                supporting_fact_digests=evaluation.supporting_fact_digests,
                version=current.version + 1,
            )
            persisted = self.store.update_finding(
                updated,
                expected_version=current.version,
            )
            event = self._ensure_event(persisted)
            return FindingLifecycleResultV1(
                finding=persisted,
                event=event,
                changed=True,
                reason_code="finding_superseded",
            )

        if evaluation.desired_generation != desired.generation:
            return FindingLifecycleResultV1(
                finding=current,
                event=None,
                changed=False,
                reason_code="stale_evaluation_ignored",
            )

        if evaluation.status is DesiredStateEvaluationStatus.UNKNOWN:
            return FindingLifecycleResultV1(
                finding=current,
                event=None,
                changed=False,
                reason_code="unknown_evidence_preserves_finding",
            )

        if evaluation.status is DesiredStateEvaluationStatus.SATISFIED:
            if current is None:
                return FindingLifecycleResultV1(
                    finding=None,
                    event=None,
                    changed=False,
                    reason_code="aligned_no_finding",
                )
            if current.status is FindingStatus.RESOLVED:
                event = self._ensure_event(current)
                return FindingLifecycleResultV1(
                    finding=current,
                    event=event,
                    changed=False,
                    reason_code="finding_already_resolved",
                )
            proposed = replace(
                current,
                desired_generation=desired.generation,
                status=FindingStatus.RESOLVED,
                latest_snapshot_digest=evaluation.snapshot_digest,
                last_seen_epoch=evaluation.evaluated_at_epoch,
                reason_codes=evaluation.reason_codes,
                supporting_fact_digests=evaluation.supporting_fact_digests,
                root_finding_id=root_finding_id or current.root_finding_id,
                suppression_finding_id=None,
                version=current.version + 1,
            )
            persisted = self.store.update_finding(
                proposed,
                expected_version=current.version,
            )
            event = self._ensure_event(persisted)
            return FindingLifecycleResultV1(
                finding=persisted,
                event=event,
                changed=True,
                reason_code="finding_resolved",
            )

        if evaluation.status not in {
            DesiredStateEvaluationStatus.STABILIZING,
            DesiredStateEvaluationStatus.VIOLATED,
        }:
            raise ValueError("unsupported stabilized evaluation status")

        desired_status = (
            FindingStatus.STABILIZING
            if evaluation.status is DesiredStateEvaluationStatus.STABILIZING
            else FindingStatus.ACTIVE
        )
        if suppression_finding_id is not None:
            desired_status = FindingStatus.SUPPRESSED

        count = max(1, evaluation.consecutive_violations)
        if current is None:
            proposed = AutonomyFindingV1(
                finding_id=finding_id,
                desired_state_id=desired.desired_state_id,
                desired_generation=desired.generation,
                target_namespace=desired.target_namespace,
                target_identity=desired.target_identity,
                finding_kind=finding_kind,
                rule_key=desired.rule_key,
                rule_version=desired.rule_version,
                status=desired_status,
                latest_snapshot_digest=evaluation.snapshot_digest,
                first_seen_epoch=(
                    evaluation.first_violation_at_epoch or evaluation.evaluated_at_epoch
                ),
                last_seen_epoch=evaluation.evaluated_at_epoch,
                violation_count=count,
                reason_codes=evaluation.reason_codes,
                supporting_fact_digests=evaluation.supporting_fact_digests,
                root_finding_id=root_finding_id,
                suppression_finding_id=suppression_finding_id,
            )
            persisted = self.store.create_finding(proposed)
            event = self._ensure_event(persisted)
            return FindingLifecycleResultV1(
                finding=persisted,
                event=event,
                changed=True,
                reason_code="finding_created",
            )

        proposed = replace(
            current,
            desired_generation=desired.generation,
            target_namespace=desired.target_namespace,
            target_identity=desired.target_identity,
            finding_kind=finding_kind,
            rule_key=desired.rule_key,
            rule_version=desired.rule_version,
            status=desired_status,
            latest_snapshot_digest=evaluation.snapshot_digest,
            last_seen_epoch=evaluation.evaluated_at_epoch,
            violation_count=max(current.violation_count, count),
            reason_codes=evaluation.reason_codes,
            supporting_fact_digests=evaluation.supporting_fact_digests,
            root_finding_id=root_finding_id or current.root_finding_id,
            suppression_finding_id=suppression_finding_id,
            version=current.version + 1,
        )
        if _same_persisted_state(current, proposed):
            event = self._ensure_event(current)
            return FindingLifecycleResultV1(
                finding=current,
                event=event,
                changed=False,
                reason_code="finding_replay_noop",
            )

        persisted = self.store.update_finding(
            proposed,
            expected_version=current.version,
        )
        event = self._ensure_event(persisted)
        return FindingLifecycleResultV1(
            finding=persisted,
            event=event,
            changed=True,
            reason_code="finding_updated",
        )
