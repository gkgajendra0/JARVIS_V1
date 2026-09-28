"""Deterministic Phase-10 engineering-learning eligibility policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import (
    EngineeringOutcomeAttribution,
    EngineeringOutcomeResult,
    EngineeringOutcomeSourceKind,
    EngineeringOutcomeV1,
)

ENGINEERING_LEARNING_POLICY_ID = "engineering-learning-eligibility:v1"


class LearningDisposition(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    COMPATIBILITY = "compatibility"
    INCONCLUSIVE = "inconclusive"
    IGNORE = "ignore"


@dataclass(frozen=True, slots=True)
class LearningEligibilityDecision:
    eligible: bool
    disposition: LearningDisposition
    reason_codes: tuple[str, ...]
    evidence_references: tuple[str, ...]
    supersession_eligible: bool
    policy_id: str = ENGINEERING_LEARNING_POLICY_ID


class EngineeringLearningEligibilityPolicy:
    """Classify verified outcomes without model inference or new Authority."""

    policy_id = ENGINEERING_LEARNING_POLICY_ID

    def evaluate(self, outcome: EngineeringOutcomeV1) -> LearningEligibilityDecision:
        if not isinstance(outcome, EngineeringOutcomeV1):
            raise TypeError("outcome must be an EngineeringOutcomeV1")

        structural = self._structural_reasons(outcome)
        if structural:
            return self._decision(
                outcome,
                eligible=False,
                disposition=LearningDisposition.INCONCLUSIVE,
                reasons=structural,
                supersession=False,
            )

        if outcome.source_kind is EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY:
            return self._compatibility(outcome)
        if outcome.source_kind is EngineeringOutcomeSourceKind.PROMOTION:
            return self._promotion(outcome)
        if outcome.source_kind is EngineeringOutcomeSourceKind.REPAIR:
            return self._repair(outcome)
        if outcome.source_kind is EngineeringOutcomeSourceKind.CAPABILITY_ACQUISITION:
            return self._acquisition(outcome)

        return self._decision(
            outcome,
            eligible=False,
            disposition=LearningDisposition.IGNORE,
            reasons=("unsupported_source_kind",),
            supersession=False,
        )

    @staticmethod
    def _structural_reasons(outcome: EngineeringOutcomeV1) -> tuple[str, ...]:
        reasons: list[str] = []
        if not outcome.evidence_references:
            reasons.append("missing_evidence")
        if not outcome.reason_codes:
            reasons.append("missing_reason_codes")
        if not outcome.applicability:
            reasons.append("missing_applicability")
        if not any(item.required for item in outcome.applicability):
            reasons.append("missing_required_applicability")
        return tuple(reasons)

    def _promotion(
        self,
        outcome: EngineeringOutcomeV1,
    ) -> LearningEligibilityDecision:
        if outcome.result is EngineeringOutcomeResult.SUCCESS:
            if outcome.attribution is not EngineeringOutcomeAttribution.NOT_APPLICABLE:
                return self._inconclusive(outcome, "success_has_failure_attribution")
            missing = self._missing(
                outcome,
                candidate_digest=True,
                release_sha=True,
            )
            if missing:
                return self._inconclusive(outcome, *missing)
            return self._decision(
                outcome,
                eligible=True,
                disposition=LearningDisposition.POSITIVE,
                reasons=("verified_promotion_success",),
                supersession=True,
            )

        if outcome.result in {
            EngineeringOutcomeResult.FAILURE,
            EngineeringOutcomeResult.ROLLED_BACK,
        }:
            if outcome.attribution is EngineeringOutcomeAttribution.CANDIDATE:
                missing = self._missing(
                    outcome,
                    candidate_digest=True,
                    release_sha=True,
                )
                if missing:
                    return self._inconclusive(outcome, *missing)
                return self._decision(
                    outcome,
                    eligible=True,
                    disposition=LearningDisposition.NEGATIVE,
                    reasons=("verified_candidate_regression",),
                    supersession=True,
                )
            if outcome.attribution in {
                EngineeringOutcomeAttribution.EXTERNAL_PROVIDER,
                EngineeringOutcomeAttribution.EXTERNAL_HARDWARE,
                EngineeringOutcomeAttribution.ENVIRONMENT,
                EngineeringOutcomeAttribution.UNKNOWN,
            }:
                return self._inconclusive(
                    outcome,
                    "promotion_failure_not_candidate_attributable",
                )
            return self._inconclusive(outcome, "unsupported_failure_attribution")

        if outcome.result is EngineeringOutcomeResult.BLOCKED:
            return self._inconclusive(outcome, "promotion_blocked_not_reusable_truth")

        return self._inconclusive(outcome, "promotion_outcome_inconclusive")

    def _repair(
        self,
        outcome: EngineeringOutcomeV1,
    ) -> LearningEligibilityDecision:
        if outcome.attribution is not EngineeringOutcomeAttribution.NOT_APPLICABLE:
            return self._inconclusive(outcome, "repair_has_unexpected_attribution")
        if outcome.result is EngineeringOutcomeResult.SUCCESS:
            return self._decision(
                outcome,
                eligible=True,
                disposition=LearningDisposition.POSITIVE,
                reasons=("verified_repair_success",),
                supersession=True,
            )
        if outcome.result is EngineeringOutcomeResult.FAILURE:
            return self._decision(
                outcome,
                eligible=True,
                disposition=LearningDisposition.NEGATIVE,
                reasons=("verified_repair_failure",),
                supersession=True,
            )
        if outcome.result in {
            EngineeringOutcomeResult.BLOCKED,
            EngineeringOutcomeResult.INCONCLUSIVE,
        }:
            return self._inconclusive(outcome, "repair_not_conclusive")
        return self._inconclusive(outcome, "unsupported_repair_result")

    def _compatibility(
        self,
        outcome: EngineeringOutcomeV1,
    ) -> LearningEligibilityDecision:
        if outcome.attribution is not EngineeringOutcomeAttribution.COMPATIBILITY:
            return self._inconclusive(
                outcome,
                "compatibility_outcome_has_wrong_attribution",
            )
        missing = self._missing(
            outcome,
            package_id=True,
            package_version=True,
            package_digest=True,
            release_sha=True,
        )
        if missing:
            return self._inconclusive(outcome, *missing)
        if outcome.result not in {
            EngineeringOutcomeResult.SUCCESS,
            EngineeringOutcomeResult.BLOCKED,
        }:
            return self._inconclusive(
                outcome,
                "compatibility_result_not_decisive",
            )
        return self._decision(
            outcome,
            eligible=True,
            disposition=LearningDisposition.COMPATIBILITY,
            reasons=(
                "verified_compatibility_ready"
                if outcome.result is EngineeringOutcomeResult.SUCCESS
                else "verified_compatibility_blocked",
            ),
            supersession=True,
        )

    def _acquisition(
        self,
        outcome: EngineeringOutcomeV1,
    ) -> LearningEligibilityDecision:
        if outcome.result is EngineeringOutcomeResult.SUCCESS:
            if outcome.attribution is not EngineeringOutcomeAttribution.NOT_APPLICABLE:
                return self._inconclusive(
                    outcome,
                    "acquisition_success_has_failure_attribution",
                )
            missing = self._missing(
                outcome,
                package_id=True,
                package_version=True,
                package_digest=True,
                release_sha=True,
            )
            if missing:
                return self._inconclusive(outcome, *missing)
            return self._decision(
                outcome,
                eligible=True,
                disposition=LearningDisposition.POSITIVE,
                reasons=("verified_capability_acquisition_success",),
                supersession=True,
            )

        if (
            outcome.result is EngineeringOutcomeResult.BLOCKED
            and outcome.attribution is EngineeringOutcomeAttribution.NOT_APPLICABLE
        ):
            return self._decision(
                outcome,
                eligible=False,
                disposition=LearningDisposition.IGNORE,
                reasons=("owner_or_policy_rejection_is_not_engineering_truth",),
                supersession=False,
            )

        return self._inconclusive(
            outcome,
            "acquisition_failure_not_safely_attributable",
        )

    @staticmethod
    def _missing(
        outcome: EngineeringOutcomeV1,
        *,
        candidate_digest: bool = False,
        release_sha: bool = False,
        package_id: bool = False,
        package_version: bool = False,
        package_digest: bool = False,
    ) -> tuple[str, ...]:
        checks = (
            ("candidate_digest", candidate_digest, outcome.candidate_digest),
            ("release_sha", release_sha, outcome.release_sha),
            ("package_id", package_id, outcome.package_id),
            ("package_version", package_version, outcome.package_version),
            ("package_digest", package_digest, outcome.package_digest),
        )
        return tuple(
            f"missing_{name}"
            for name, required, value in checks
            if required and value is None
        )

    def _inconclusive(
        self,
        outcome: EngineeringOutcomeV1,
        *reasons: str,
    ) -> LearningEligibilityDecision:
        return self._decision(
            outcome,
            eligible=False,
            disposition=LearningDisposition.INCONCLUSIVE,
            reasons=tuple(reasons) or ("inconclusive",),
            supersession=False,
        )

    @staticmethod
    def _decision(
        outcome: EngineeringOutcomeV1,
        *,
        eligible: bool,
        disposition: LearningDisposition,
        reasons: tuple[str, ...],
        supersession: bool,
    ) -> LearningEligibilityDecision:
        return LearningEligibilityDecision(
            eligible=eligible,
            disposition=disposition,
            reason_codes=tuple(dict.fromkeys(reasons)),
            evidence_references=outcome.evidence_references,
            supersession_eligible=supersession,
        )
