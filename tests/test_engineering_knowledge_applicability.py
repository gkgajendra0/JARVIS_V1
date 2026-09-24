from __future__ import annotations

from dataclasses import dataclass

import pytest

from jarvis.engineering_knowledge import (
    ApplicabilityContext,
    ApplicabilityFact,
    ApplicabilityMatchStatus,
    EngineeringApplicability,
    EngineeringApplicabilityRegistry,
    EngineeringKnowledgeApplicabilityService,
    ExactIdentityMatcher,
    ExactVersionMatcher,
    NumericVersionRangeMatcher,
    build_default_applicability_registry,
)


@dataclass(frozen=True)
class _Store:
    constraints: tuple[EngineeringApplicability, ...]

    def list_engineering_knowledge_applicability(
        self,
        revision_id: str,
    ) -> tuple[EngineeringApplicability, ...]:
        assert revision_id == "revision-1"
        return self.constraints


def _constraint(
    *,
    applicability_id: str = "app-1",
    namespace: str = "jarvis.component",
    identity: str = "runtime.voice",
    matcher_type: str = "exact",
    constraint_json: str = "{}",
    required: bool = True,
) -> EngineeringApplicability:
    return EngineeringApplicability(
        applicability_id=applicability_id,
        revision_id="revision-1",
        target_namespace=namespace,
        target_identity=identity,
        matcher_type=matcher_type,
        constraint_json=constraint_json,
        required=required,
        created_at_epoch=100.0,
    )


def test_exact_component_match_is_eligible() -> None:
    service = EngineeringKnowledgeApplicabilityService(_Store((_constraint(),)))
    context = ApplicabilityContext(
        (
            ApplicabilityFact(
                target_namespace="jarvis.component",
                target_identity="runtime.voice",
                attributes={},
            ),
        )
    )

    decision = service.evaluate("revision-1", context)

    assert decision.eligible is True
    assert decision.blocking_applicability_ids == ()
    assert decision.results[0].status is ApplicabilityMatchStatus.MATCH


def test_exact_component_mismatch_blocks_required_knowledge() -> None:
    service = EngineeringKnowledgeApplicabilityService(_Store((_constraint(),)))
    context = ApplicabilityContext(
        (
            ApplicabilityFact(
                target_namespace="jarvis.component",
                target_identity="runtime.vision",
                attributes={},
            ),
        )
    )

    decision = service.evaluate("revision-1", context)

    assert decision.eligible is False
    assert decision.blocking_applicability_ids == ("app-1",)
    assert decision.results[0].status is ApplicabilityMatchStatus.NO_MATCH


def test_missing_required_context_fails_closed_as_unknown() -> None:
    service = EngineeringKnowledgeApplicabilityService(
        _Store((_constraint(),))
    )

    decision = service.evaluate("revision-1", ApplicabilityContext(()))

    assert decision.eligible is False
    assert decision.results[0].status is ApplicabilityMatchStatus.UNKNOWN
    assert decision.results[0].reason_code == "target_namespace_not_observed"


def test_optional_mismatch_does_not_block() -> None:
    optional = _constraint(required=False)
    service = EngineeringKnowledgeApplicabilityService(_Store((optional,)))
    context = ApplicabilityContext(
        (
            ApplicabilityFact(
                target_namespace="jarvis.component",
                target_identity="runtime.vision",
                attributes={},
            ),
        )
    )

    decision = service.evaluate("revision-1", context)

    assert decision.eligible is True
    assert decision.results[0].status is ApplicabilityMatchStatus.NO_MATCH


def test_unsupported_required_matcher_fails_closed() -> None:
    unsupported = _constraint(
        matcher_type="future_range_matcher",
        constraint_json='{"future":"rule"}',
    )
    service = EngineeringKnowledgeApplicabilityService(_Store((unsupported,)))

    decision = service.evaluate(
        "revision-1",
        ApplicabilityContext(
            (
                ApplicabilityFact(
                    target_namespace="jarvis.component",
                    target_identity="runtime.voice",
                    attributes={},
                ),
            )
        ),
    )

    assert decision.eligible is False
    assert decision.results[0].status is ApplicabilityMatchStatus.UNKNOWN
    assert decision.results[0].reason_code == "unsupported_applicability_matcher"


def test_exact_version_matcher_requires_observed_version() -> None:
    constraint = _constraint(
        namespace="package",
        identity="livekit",
        matcher_type="version_exact",
        constraint_json='{"version":"1.7.1"}',
    )
    service = EngineeringKnowledgeApplicabilityService(_Store((constraint,)))
    matching = ApplicabilityContext(
        (
            ApplicabilityFact(
                target_namespace="package",
                target_identity="livekit",
                attributes={"version": "1.7.1"},
            ),
        )
    )
    missing_version = ApplicabilityContext(
        (
            ApplicabilityFact(
                target_namespace="package",
                target_identity="livekit",
                attributes={},
            ),
        )
    )

    assert service.evaluate("revision-1", matching).eligible is True
    unknown = service.evaluate("revision-1", missing_version)
    assert unknown.eligible is False
    assert unknown.results[0].status is ApplicabilityMatchStatus.UNKNOWN


def test_numeric_version_range_is_deterministic_for_dotted_integers() -> None:
    constraint = _constraint(
        namespace="firmware",
        identity="pocket3",
        matcher_type="numeric_version_range",
        constraint_json='{"min_inclusive":"2.1","max_exclusive":"3.0"}',
    )
    service = EngineeringKnowledgeApplicabilityService(_Store((constraint,)))

    matching = ApplicabilityContext(
        (
            ApplicabilityFact(
                target_namespace="firmware",
                target_identity="pocket3",
                attributes={"version": "2.5.0"},
            ),
        )
    )
    outside = ApplicabilityContext(
        (
            ApplicabilityFact(
                target_namespace="firmware",
                target_identity="pocket3",
                attributes={"version": "3.0"},
            ),
        )
    )
    opaque = ApplicabilityContext(
        (
            ApplicabilityFact(
                target_namespace="firmware",
                target_identity="pocket3",
                attributes={"version": "v2-beta"},
            ),
        )
    )

    assert service.evaluate("revision-1", matching).eligible is True

    outside_decision = service.evaluate("revision-1", outside)
    assert outside_decision.eligible is False
    assert outside_decision.results[0].status is ApplicabilityMatchStatus.NO_MATCH

    opaque_decision = service.evaluate("revision-1", opaque)
    assert opaque_decision.eligible is False
    assert opaque_decision.results[0].status is ApplicabilityMatchStatus.UNKNOWN


def test_invalid_numeric_range_constraint_fails_closed() -> None:
    constraint = _constraint(
        namespace="jarvis.revision",
        identity="jarvis",
        matcher_type="numeric_version_range",
        constraint_json='{"min_inclusive":"4.0","max_exclusive":"3.0"}',
    )

    decision = EngineeringKnowledgeApplicabilityService(_Store((constraint,))).evaluate(
        "revision-1",
        ApplicabilityContext(
            (
                ApplicabilityFact(
                    target_namespace="jarvis.revision",
                    target_identity="jarvis",
                    attributes={"version": "3.5"},
                ),
            )
        ),
    )

    assert decision.eligible is False
    assert decision.results[0].status is ApplicabilityMatchStatus.UNKNOWN
    assert decision.results[0].reason_code.startswith(
        "invalid_applicability_constraint:"
    )


def test_missing_applicability_is_not_treated_as_global_truth() -> None:
    decision = EngineeringKnowledgeApplicabilityService(_Store(())).evaluate(
        "revision-1",
        ApplicabilityContext(()),
    )

    assert decision.eligible is False
    assert decision.blocking_applicability_ids == ("missing_applicability",)


def test_matcher_registry_rejects_duplicate_semantics() -> None:
    registry = EngineeringApplicabilityRegistry()
    registry.register(
        target_namespace="jarvis.component",
        matcher_type="exact",
        matcher=ExactIdentityMatcher(),
    )

    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            target_namespace="jarvis.component",
            matcher_type="exact",
            matcher=ExactIdentityMatcher(),
        )


def test_default_registry_contains_version_and_identity_matchers() -> None:
    registry = build_default_applicability_registry()

    exact = registry.matcher_for(_constraint())
    version = registry.matcher_for(
        _constraint(
            namespace="package",
            identity="qwen",
            matcher_type="version_exact",
            constraint_json='{"version":"1"}',
        )
    )
    numeric = registry.matcher_for(
        _constraint(
            namespace="protocol",
            identity="api",
            matcher_type="numeric_version_range",
            constraint_json='{"min_inclusive":"1"}',
        )
    )

    assert isinstance(exact, ExactIdentityMatcher)
    assert isinstance(version, ExactVersionMatcher)
    assert isinstance(numeric, NumericVersionRangeMatcher)
