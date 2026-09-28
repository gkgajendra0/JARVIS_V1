from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.engineering_learning.models import (
    EngineeringOutcomeAttribution,
    EngineeringOutcomeResult,
    EngineeringOutcomeSourceKind,
    EngineeringOutcomeV1,
    OutcomeApplicability,
)
from jarvis.engineering_learning.policy import (
    ENGINEERING_LEARNING_POLICY_ID,
    EngineeringLearningEligibilityPolicy,
    LearningDisposition,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
RELEASE = "c" * 40


def _outcome(
    *,
    source: EngineeringOutcomeSourceKind,
    result: EngineeringOutcomeResult,
    attribution: EngineeringOutcomeAttribution,
    candidate: bool = False,
    package: bool = False,
) -> EngineeringOutcomeV1:
    kwargs: dict[str, object] = {}
    if candidate:
        kwargs.update(
            {
                "candidate_id": "candidate-1",
                "candidate_digest": SHA_A,
                "release_sha": RELEASE,
                "change_id": "change-1",
            }
        )
    if package:
        kwargs.update(
            {
                "package_id": "tv.control",
                "package_version": "1.0.0",
                "package_digest": SHA_B,
                "release_sha": RELEASE,
            }
        )
    return EngineeringOutcomeV1.create(
        source_kind=source,
        source_identity=f"{source.value}:source-1",
        subject_type="engineering_subject",
        subject_id="subject-1",
        subject_digest=SHA_A,
        result=result,
        attribution=attribution,
        reason_codes=("verified_reason",),
        evidence_references=("evidence:1",),
        applicability=(
            OutcomeApplicability(
                target_namespace="jarvis.component",
                target_identity="runtime.voice",
                matcher_type="exact",
                constraint={},
            ),
        ),
        observed_at_epoch=100.0,
        producer="phase10-policy-test",
        **kwargs,
    )


@pytest.mark.parametrize(
    ("result", "disposition"),
    [
        (EngineeringOutcomeResult.SUCCESS, LearningDisposition.POSITIVE),
        (EngineeringOutcomeResult.FAILURE, LearningDisposition.NEGATIVE),
    ],
)
def test_repair_success_and_failure_are_reusable_verified_learning(
    result: EngineeringOutcomeResult,
    disposition: LearningDisposition,
) -> None:
    outcome = _outcome(
        source=EngineeringOutcomeSourceKind.REPAIR,
        result=result,
        attribution=EngineeringOutcomeAttribution.NOT_APPLICABLE,
    )

    decision = EngineeringLearningEligibilityPolicy().evaluate(outcome)

    assert decision.eligible is True
    assert decision.disposition is disposition
    assert decision.supersession_eligible is True
    assert decision.policy_id == ENGINEERING_LEARNING_POLICY_ID


def test_verified_promotion_success_requires_candidate_and_release_lineage() -> None:
    policy = EngineeringLearningEligibilityPolicy()
    missing = _outcome(
        source=EngineeringOutcomeSourceKind.PROMOTION,
        result=EngineeringOutcomeResult.SUCCESS,
        attribution=EngineeringOutcomeAttribution.NOT_APPLICABLE,
    )
    complete = _outcome(
        source=EngineeringOutcomeSourceKind.PROMOTION,
        result=EngineeringOutcomeResult.SUCCESS,
        attribution=EngineeringOutcomeAttribution.NOT_APPLICABLE,
        candidate=True,
    )

    blocked = policy.evaluate(missing)
    accepted = policy.evaluate(complete)

    assert blocked.eligible is False
    assert blocked.disposition is LearningDisposition.INCONCLUSIVE
    assert set(blocked.reason_codes) == {"missing_candidate_digest", "missing_release_sha"}
    assert accepted.eligible is True
    assert accepted.disposition is LearningDisposition.POSITIVE


def test_candidate_local_promotion_failure_is_negative_learning() -> None:
    outcome = _outcome(
        source=EngineeringOutcomeSourceKind.PROMOTION,
        result=EngineeringOutcomeResult.ROLLED_BACK,
        attribution=EngineeringOutcomeAttribution.CANDIDATE,
        candidate=True,
    )

    decision = EngineeringLearningEligibilityPolicy().evaluate(outcome)

    assert decision.eligible is True
    assert decision.disposition is LearningDisposition.NEGATIVE
    assert decision.reason_codes == ("verified_candidate_regression",)


@pytest.mark.parametrize(
    "attribution",
    [
        EngineeringOutcomeAttribution.EXTERNAL_PROVIDER,
        EngineeringOutcomeAttribution.EXTERNAL_HARDWARE,
        EngineeringOutcomeAttribution.ENVIRONMENT,
        EngineeringOutcomeAttribution.UNKNOWN,
    ],
)
def test_non_candidate_promotion_failure_cannot_poison_candidate_learning(
    attribution: EngineeringOutcomeAttribution,
) -> None:
    outcome = _outcome(
        source=EngineeringOutcomeSourceKind.PROMOTION,
        result=EngineeringOutcomeResult.FAILURE,
        attribution=attribution,
        candidate=True,
    )

    decision = EngineeringLearningEligibilityPolicy().evaluate(outcome)

    assert decision.eligible is False
    assert decision.disposition is LearningDisposition.INCONCLUSIVE
    assert decision.supersession_eligible is False


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (EngineeringOutcomeResult.SUCCESS, "verified_compatibility_ready"),
        (EngineeringOutcomeResult.BLOCKED, "verified_compatibility_blocked"),
    ],
)
def test_exact_compatibility_ready_and_blocked_are_reusable(
    result: EngineeringOutcomeResult,
    reason: str,
) -> None:
    outcome = _outcome(
        source=EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY,
        result=result,
        attribution=EngineeringOutcomeAttribution.COMPATIBILITY,
        package=True,
    )

    decision = EngineeringLearningEligibilityPolicy().evaluate(outcome)

    assert decision.eligible is True
    assert decision.disposition is LearningDisposition.COMPATIBILITY
    assert decision.reason_codes == (reason,)
    assert decision.supersession_eligible is True


def test_compatibility_without_exact_package_lineage_fails_closed() -> None:
    outcome = _outcome(
        source=EngineeringOutcomeSourceKind.CAPABILITY_COMPATIBILITY,
        result=EngineeringOutcomeResult.SUCCESS,
        attribution=EngineeringOutcomeAttribution.COMPATIBILITY,
    )

    decision = EngineeringLearningEligibilityPolicy().evaluate(outcome)

    assert decision.eligible is False
    assert decision.disposition is LearningDisposition.INCONCLUSIVE
    assert set(decision.reason_codes) == {
        "missing_package_id",
        "missing_package_version",
        "missing_package_digest",
        "missing_release_sha",
    }


def test_verified_acquisition_success_requires_exact_package_and_release() -> None:
    outcome = _outcome(
        source=EngineeringOutcomeSourceKind.CAPABILITY_ACQUISITION,
        result=EngineeringOutcomeResult.SUCCESS,
        attribution=EngineeringOutcomeAttribution.NOT_APPLICABLE,
        package=True,
    )

    decision = EngineeringLearningEligibilityPolicy().evaluate(outcome)

    assert decision.eligible is True
    assert decision.disposition is LearningDisposition.POSITIVE
    assert decision.reason_codes == ("verified_capability_acquisition_success",)


def test_owner_or_policy_rejection_is_not_engineering_truth() -> None:
    outcome = _outcome(
        source=EngineeringOutcomeSourceKind.CAPABILITY_ACQUISITION,
        result=EngineeringOutcomeResult.BLOCKED,
        attribution=EngineeringOutcomeAttribution.NOT_APPLICABLE,
        package=True,
    )

    decision = EngineeringLearningEligibilityPolicy().evaluate(outcome)

    assert decision.eligible is False
    assert decision.disposition is LearningDisposition.IGNORE
    assert decision.supersession_eligible is False


def test_unknown_acquisition_failure_remains_inconclusive() -> None:
    outcome = _outcome(
        source=EngineeringOutcomeSourceKind.CAPABILITY_ACQUISITION,
        result=EngineeringOutcomeResult.FAILURE,
        attribution=EngineeringOutcomeAttribution.UNKNOWN,
        package=True,
    )

    decision = EngineeringLearningEligibilityPolicy().evaluate(outcome)

    assert decision.eligible is False
    assert decision.disposition is LearningDisposition.INCONCLUSIVE


def test_policy_preserves_source_evidence_and_is_deterministic() -> None:
    outcome = _outcome(
        source=EngineeringOutcomeSourceKind.REPAIR,
        result=EngineeringOutcomeResult.SUCCESS,
        attribution=EngineeringOutcomeAttribution.NOT_APPLICABLE,
    )
    policy = EngineeringLearningEligibilityPolicy()

    first = policy.evaluate(outcome)
    second = policy.evaluate(outcome)

    assert first == second
    assert first.evidence_references == outcome.evidence_references


def test_incompatible_success_attribution_fails_closed() -> None:
    outcome = _outcome(
        source=EngineeringOutcomeSourceKind.PROMOTION,
        result=EngineeringOutcomeResult.SUCCESS,
        attribution=EngineeringOutcomeAttribution.CANDIDATE,
        candidate=True,
    )

    decision = EngineeringLearningEligibilityPolicy().evaluate(outcome)

    assert decision.eligible is False
    assert decision.disposition is LearningDisposition.INCONCLUSIVE


def test_policy_refuses_non_outcome_input() -> None:
    with pytest.raises(TypeError, match="EngineeringOutcomeV1"):
        EngineeringLearningEligibilityPolicy().evaluate(object())  # type: ignore[arg-type]


def test_outcome_identity_change_does_not_change_policy_classification() -> None:
    original = _outcome(
        source=EngineeringOutcomeSourceKind.REPAIR,
        result=EngineeringOutcomeResult.SUCCESS,
        attribution=EngineeringOutcomeAttribution.NOT_APPLICABLE,
    )
    replay_variant = replace(original, producer="another-deterministic-adapter")
    policy = EngineeringLearningEligibilityPolicy()

    assert policy.evaluate(original).disposition is policy.evaluate(
        replay_variant
    ).disposition
