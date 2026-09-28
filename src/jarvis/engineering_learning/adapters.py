"""Read-only adapters from canonical engineering records to Phase-10 outcomes."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from jarvis.capability_registry.compatibility import (
    CapabilityCompatibilityReportV1,
    CompatibilityVerdict as CapabilityCompatibilityVerdict,
)
from jarvis.engineering_change.models import (
    ChangeArtifact,
    ChangeState,
    EngineeringChange,
)
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.promotion.models import PromotionAttempt, PromotionAttemptState
from jarvis.promotion.observation import FailureAttribution
from jarvis.self_repair.domain import RepairAttempt, RepairVerdict

from .models import (
    EngineeringOutcomeAttribution,
    EngineeringOutcomeResult,
    EngineeringOutcomeSourceKind,
    EngineeringOutcomeV1,
    OutcomeApplicability,
)


class EngineeringOutcomeAdapterError(ValueError):
    """Canonical source evidence cannot be normalized safely."""


def _epoch_from_iso(value: str, *, field: str) -> float:
    text = str(value).strip()
    if not text:
        raise EngineeringOutcomeAdapterError(f"{field} must not be empty")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EngineeringOutcomeAdapterError(
            f"{field} is not an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EngineeringOutcomeAdapterError(f"{field} must be timezone-aware")
    epoch = parsed.timestamp()
    if epoch <= 0:
        raise EngineeringOutcomeAdapterError(f"{field} must be positive")
    return epoch


def _artifact_ref(artifact: ChangeArtifact) -> str:
    return f"change-artifact:{artifact.artifact_id}:sha256:{artifact.digest}"


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for raw in values:
        value = str(raw).strip()
        if value and value not in result:
            result.append(value)
    return tuple(result)


def _promotion_observations(
    changes: ChangeStore,
    attempt: PromotionAttempt,
) -> tuple[ChangeArtifact, ...]:
    return tuple(
        artifact
        for artifact in changes.list_artifacts(
            attempt.change_id,
            kind="production_observation",
        )
        if artifact.payload.get("attempt_id") == attempt.attempt_id
    )


def _observation_reason_codes(
    artifacts: Iterable[ChangeArtifact],
) -> tuple[str, ...]:
    return _unique(
        str(artifact.payload.get("reason_code") or "").strip().casefold()
        for artifact in artifacts
    )


def _observation_epoch(artifacts: Iterable[ChangeArtifact]) -> float | None:
    observed: list[float] = []
    for artifact in artifacts:
        value = artifact.payload.get("observed_at_epoch")
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        timestamp = float(value)
        if timestamp > 0:
            observed.append(timestamp)
    return max(observed) if observed else None


class PromotionOutcomeAdapter:
    """Normalize terminal Phase-7 promotion truth without changing it."""

    _TERMINAL = frozenset(
        {
            PromotionAttemptState.COMPLETED,
            PromotionAttemptState.ROLLED_BACK,
            PromotionAttemptState.FAILED,
            PromotionAttemptState.BLOCKED,
            PromotionAttemptState.STALE,
        }
    )

    def __init__(self, changes: ChangeStore) -> None:
        if not isinstance(changes, ChangeStore):
            raise TypeError("changes must be a ChangeStore")
        self._changes = changes

    def normalize(self, attempt: PromotionAttempt) -> EngineeringOutcomeV1:
        if not isinstance(attempt, PromotionAttempt):
            raise TypeError("attempt must be a PromotionAttempt")
        if attempt.state not in self._TERMINAL:
            raise EngineeringOutcomeAdapterError(
                "promotion attempt is not terminal"
            )

        candidate = self._changes.get_artifact(attempt.candidate_artifact_id)
        if candidate is None:
            raise EngineeringOutcomeAdapterError(
                "promotion candidate artifact is missing"
            )
        if candidate.digest != attempt.candidate_artifact_digest:
            raise EngineeringOutcomeAdapterError(
                "promotion candidate artifact digest is stale"
            )

        observations = _promotion_observations(self._changes, attempt)
        healthy = tuple(
            artifact
            for artifact in observations
            if artifact.payload.get("healthy") is True
        )
        failed = tuple(
            artifact
            for artifact in observations
            if artifact.payload.get("healthy") is False
        )
        candidate_failures = tuple(
            artifact
            for artifact in failed
            if artifact.payload.get("attribution")
            == FailureAttribution.CANDIDATE_LOCAL.value
        )
        provider_failures = tuple(
            artifact
            for artifact in failed
            if artifact.payload.get("attribution")
            == FailureAttribution.EXTERNAL_PROVIDER.value
        )
        hardware_failures = tuple(
            artifact
            for artifact in failed
            if artifact.payload.get("attribution")
            == FailureAttribution.EXTERNAL_HARDWARE.value
        )

        if attempt.state is PromotionAttemptState.COMPLETED:
            if attempt.merge_sha is None or not healthy:
                raise EngineeringOutcomeAdapterError(
                    "completed promotion lacks exact release/healthy observation"
                )
            result = EngineeringOutcomeResult.SUCCESS
            attribution = EngineeringOutcomeAttribution.NOT_APPLICABLE
            reasons = _observation_reason_codes(healthy) or (
                "promotion_completed",
            )
        elif attempt.state is PromotionAttemptState.ROLLED_BACK:
            if attempt.merge_sha is None or not candidate_failures:
                raise EngineeringOutcomeAdapterError(
                    "rolled-back promotion lacks candidate-local failure evidence"
                )
            result = EngineeringOutcomeResult.ROLLED_BACK
            attribution = EngineeringOutcomeAttribution.CANDIDATE
            reasons = _unique(
                (
                    *_observation_reason_codes(candidate_failures),
                    "promotion_rolled_back",
                )
            )
        elif attempt.state is PromotionAttemptState.FAILED:
            result = EngineeringOutcomeResult.FAILURE
            if candidate_failures:
                attribution = EngineeringOutcomeAttribution.CANDIDATE
                reasons = _observation_reason_codes(candidate_failures)
            elif provider_failures and not hardware_failures:
                attribution = EngineeringOutcomeAttribution.EXTERNAL_PROVIDER
                reasons = _observation_reason_codes(provider_failures)
            elif hardware_failures and not provider_failures:
                attribution = EngineeringOutcomeAttribution.EXTERNAL_HARDWARE
                reasons = _observation_reason_codes(hardware_failures)
            else:
                attribution = EngineeringOutcomeAttribution.UNKNOWN
                reasons = ()
            reasons = reasons or _unique(
                (attempt.last_reason or "", "promotion_failed")
            )
        elif attempt.state is PromotionAttemptState.STALE:
            result = EngineeringOutcomeResult.BLOCKED
            attribution = EngineeringOutcomeAttribution.ENVIRONMENT
            reasons = _unique(
                (attempt.last_reason or "", "promotion_candidate_stale")
            )
        else:
            result = EngineeringOutcomeResult.BLOCKED
            attribution = EngineeringOutcomeAttribution.UNKNOWN
            reasons = _unique((attempt.last_reason or "", "promotion_blocked"))

        if not reasons:
            raise EngineeringOutcomeAdapterError(
                "promotion outcome has no reason code"
            )

        revision = attempt.merge_sha or attempt.head_sha
        evidence = _unique(
            (
                f"promotion-attempt:{attempt.attempt_id}",
                _artifact_ref(candidate),
                *(_artifact_ref(item) for item in observations),
            )
        )
        observed_at = _observation_epoch(observations)
        if observed_at is None:
            observed_at = _epoch_from_iso(
                attempt.updated_at,
                field="promotion.updated_at",
            )

        return EngineeringOutcomeV1.create(
            source_kind=EngineeringOutcomeSourceKind.PROMOTION,
            source_identity=attempt.attempt_id,
            subject_type="promotion_candidate",
            subject_id=attempt.candidate_id,
            subject_digest=attempt.candidate_digest,
            result=result,
            attribution=attribution,
            reason_codes=reasons,
            evidence_references=evidence,
            applicability=(
                OutcomeApplicability(
                    target_namespace="jarvis.revision",
                    target_identity=revision,
                    matcher_type="exact",
                    constraint={},
                    required=True,
                ),
            ),
            observed_at_epoch=observed_at,
            producer="phase10.promotion_outcome_adapter:v1",
            change_id=attempt.change_id,
            candidate_id=attempt.candidate_id,
            candidate_digest=attempt.candidate_digest,
            release_sha=attempt.merge_sha,
        )


class RepairOutcomeAdapter:
    """Normalize typed terminal RepairAttempt evidence."""

    def normalize(self, attempt: RepairAttempt) -> EngineeringOutcomeV1:
        if not isinstance(attempt, RepairAttempt):
            raise TypeError("attempt must be a RepairAttempt")
        if attempt.finished_at_epoch is None or attempt.verdict is None:
            raise EngineeringOutcomeAdapterError("repair attempt is not terminal")

        if attempt.verdict is RepairVerdict.RECOVERED:
            result = EngineeringOutcomeResult.SUCCESS
        elif attempt.verdict is RepairVerdict.NOT_RECOVERED:
            result = EngineeringOutcomeResult.FAILURE
        elif attempt.verdict is RepairVerdict.ESCALATED:
            result = EngineeringOutcomeResult.BLOCKED
        else:
            result = EngineeringOutcomeResult.INCONCLUSIVE

        reason = (
            attempt.trigger_snapshot.reason_code
            if attempt.trigger_snapshot is not None
            else attempt.action.kind.value
        )
        evidence = _unique(
            (
                f"repair-attempt:{attempt.attempt_id}",
                f"repair-trigger:{attempt.trigger_id}",
                f"repair-policy:{attempt.policy_id}:v{attempt.policy_version}",
                *attempt.pre_repair_evidence,
                *attempt.post_repair_evidence,
                *(
                    ()
                    if attempt.verification is None
                    else attempt.verification.evidence_references
                ),
            )
        )

        return EngineeringOutcomeV1.create(
            source_kind=EngineeringOutcomeSourceKind.REPAIR,
            source_identity=attempt.attempt_id,
            subject_type="repair_attempt",
            subject_id=attempt.attempt_id,
            subject_digest=canonical_digest(attempt),
            result=result,
            attribution=EngineeringOutcomeAttribution.NOT_APPLICABLE,
            reason_codes=(reason,),
            evidence_references=evidence,
            applicability=(
                OutcomeApplicability(
                    target_namespace="jarvis.component",
                    target_identity=attempt.action.component_id,
                    matcher_type="exact",
                    constraint={},
                    required=True,
                ),
            ),
            observed_at_epoch=attempt.finished_at_epoch,
            producer="phase10.repair_outcome_adapter:v1",
        )


class CapabilityCompatibilityOutcomeAdapter:
    """Normalize exact Phase-8 compatibility reports."""

    def normalize(
        self,
        report: CapabilityCompatibilityReportV1,
        *,
        observed_at_epoch: float,
    ) -> EngineeringOutcomeV1:
        if not isinstance(report, CapabilityCompatibilityReportV1):
            raise TypeError("report must be a CapabilityCompatibilityReportV1")

        if report.verdict is CapabilityCompatibilityVerdict.READY:
            result = EngineeringOutcomeResult.SUCCESS
        else:
            result = EngineeringOutcomeResult.BLOCKED

        applicability: list[OutcomeApplicability] = [
            OutcomeApplicability(
                target_namespace="package",
                target_identity=report.package_id,
                matcher_type="version_exact",
                constraint={"version": report.package_version},
                required=True,
            ),
            OutcomeApplicability(
                target_namespace="jarvis.revision",
                target_identity=report.current_release_sha,
                matcher_type="exact",
                constraint={},
                required=True,
            ),
        ]
        applicability.extend(
            OutcomeApplicability(
                target_namespace="platform",
                target_identity=tag,
                matcher_type="exact",
                constraint={},
                required=False,
            )
            for tag in report.platform_tags
        )

        reasons = report.reason_codes or (report.verdict.value,)
        return EngineeringOutcomeV1.create(
            source_kind=EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY,
            source_identity=report.digest,
            subject_type="capability_package",
            subject_id=f"{report.package_id}@{report.package_version}",
            subject_digest=report.package_digest,
            result=result,
            attribution=EngineeringOutcomeAttribution.COMPATIBILITY,
            reason_codes=tuple(reasons),
            evidence_references=(
                f"capability-compatibility-report:sha256:{report.digest}",
            ),
            applicability=tuple(applicability),
            observed_at_epoch=observed_at_epoch,
            producer="phase10.capability_compatibility_outcome_adapter:v1",
            release_sha=report.current_release_sha,
            package_id=report.package_id,
            package_version=report.package_version,
            package_digest=report.package_digest,
        )


class CapabilityAcquisitionOutcomeAdapter:
    """Normalize only durable Phase-9 acquisition states that are actually proven."""

    _TERMINAL = frozenset(
        {
            ChangeState.CLOSED,
            ChangeState.ROLLED_BACK,
            ChangeState.FAILED,
            ChangeState.BLOCKED_EXTERNAL,
            ChangeState.REJECTED,
        }
    )

    def __init__(self, changes: ChangeStore) -> None:
        if not isinstance(changes, ChangeStore):
            raise TypeError("changes must be a ChangeStore")
        self._changes = changes

    def normalize(
        self,
        change_or_id: EngineeringChange | str,
    ) -> EngineeringOutcomeV1:
        change = (
            change_or_id
            if isinstance(change_or_id, EngineeringChange)
            else self._changes.require(str(change_or_id).strip())
        )
        if change.state not in self._TERMINAL:
            raise EngineeringOutcomeAdapterError(
                "capability acquisition change is not terminal"
            )

        candidate = self._changes.latest_artifact(
            change.change_id,
            "capability_candidate",
        )
        if candidate is None:
            raise EngineeringOutcomeAdapterError(
                "capability acquisition has no verified candidate"
            )
        package_id = str(candidate.payload.get("package_id") or "").strip().casefold()
        package_version = str(
            candidate.payload.get("package_version") or ""
        ).strip()
        package_digest = str(
            candidate.payload.get("package_digest") or ""
        ).strip().casefold()
        if not package_id or not package_version or len(package_digest) != 64:
            raise EngineeringOutcomeAdapterError(
                "capability candidate package identity is incomplete"
            )

        admission = self._changes.latest_artifact(
            change.change_id,
            "capability_package_admission",
        )
        activation = self._changes.latest_artifact(
            change.change_id,
            "capability_lifecycle_activation",
        )

        evidence: list[str] = [_artifact_ref(candidate)]
        if admission is not None:
            evidence.append(_artifact_ref(admission))
        if activation is not None:
            evidence.append(_artifact_ref(activation))

        if change.state is ChangeState.CLOSED:
            if (
                admission is None
                or activation is None
                or activation.payload.get("effective_enabled") is not True
            ):
                raise EngineeringOutcomeAdapterError(
                    "closed capability acquisition lacks activation evidence"
                )
            result = EngineeringOutcomeResult.SUCCESS
            attribution = EngineeringOutcomeAttribution.NOT_APPLICABLE
            reasons = ("capability_acquisition_closed",)
        elif change.state is ChangeState.BLOCKED_EXTERNAL:
            result = EngineeringOutcomeResult.BLOCKED
            attribution = EngineeringOutcomeAttribution.EXTERNAL_PROVIDER
            reasons = ("capability_acquisition_blocked_external",)
        elif change.state is ChangeState.ROLLED_BACK:
            result = EngineeringOutcomeResult.ROLLED_BACK
            attribution = EngineeringOutcomeAttribution.UNKNOWN
            reasons = ("capability_acquisition_rolled_back",)
        elif change.state is ChangeState.REJECTED:
            result = EngineeringOutcomeResult.BLOCKED
            attribution = EngineeringOutcomeAttribution.NOT_APPLICABLE
            reasons = ("capability_acquisition_rejected",)
        else:
            result = EngineeringOutcomeResult.FAILURE
            attribution = EngineeringOutcomeAttribution.UNKNOWN
            reasons = ("capability_acquisition_failed",)

        applicability: list[OutcomeApplicability] = [
            OutcomeApplicability(
                target_namespace="package",
                target_identity=package_id,
                matcher_type="version_exact",
                constraint={"version": package_version},
                required=True,
            )
        ]
        release_sha: str | None = None
        if admission is not None:
            raw_release = str(
                admission.payload.get("active_release_sha") or ""
            ).strip().casefold()
            if raw_release:
                release_sha = raw_release
                applicability.append(
                    OutcomeApplicability(
                        target_namespace="jarvis.revision",
                        target_identity=raw_release,
                        matcher_type="exact",
                        constraint={},
                        required=True,
                    )
                )

        return EngineeringOutcomeV1.create(
            source_kind=EngineeringOutcomeSourceKind.CAPABILITY_ACQUISITION,
            source_identity=change.change_id,
            subject_type="capability_package",
            subject_id=f"{package_id}@{package_version}",
            subject_digest=package_digest,
            result=result,
            attribution=attribution,
            reason_codes=reasons,
            evidence_references=tuple(evidence),
            applicability=tuple(applicability),
            observed_at_epoch=_epoch_from_iso(
                change.updated_at,
                field="engineering_change.updated_at",
            ),
            producer="phase10.capability_acquisition_outcome_adapter:v1",
            change_id=change.change_id,
            release_sha=release_sha,
            package_id=package_id,
            package_version=package_version,
            package_digest=package_digest,
        )
